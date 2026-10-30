"""Content snapshots shared by idle exploration and questions awaiting clarification.

Jira's issue.updated includes workflow changes and our own reports. Neither is a
new requirement. Keep the content inspected by the agent, rather than taking a
new baseline after it posts a comment (a human may reply during the run).
"""
import hashlib
import json

from . import jira_client
from .issue_report import ARTEL_REPORT_TAG
from .reports import _same_jira_user


def fingerprint(fields, comments):
    """Stable hash of the statement and external thread, independent of ordering."""
    thread = [{'id': str(c.get('id') or ''), 'body': c.get('body') or ''} for c in comments]
    thread.sort(key=lambda c: (c['id'], json.dumps(c['body'], sort_keys=True, ensure_ascii=False)))
    content = {'summary': fields.get('summary') or '', 'description': fields.get('description') or '',
               'comments': thread}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def fetch_snapshot(issue_key, config, ignored_comment_ids=(), *, meta=None):
    """None means unreadable/incomplete; an empty thread is still a valid snapshot.

    Explicit IDs must be IDs returned by our own successful publications. Text
    markers alone do not prove authorship: a human quoting an Artel report is
    still a new external comment and must wake the daemon.
    """
    fields = jira_client.fetch_issue_meta(issue_key, config) if meta is None else dict(meta)
    if not isinstance(fields, dict) or 'summary' not in fields or 'description' not in fields:
        return None
    comments = jira_client.fetch_comments(issue_key, config)
    if not isinstance(comments, list) or any(not isinstance(c, dict) for c in comments):
        return None
    user = jira_client.jira_request('GET', '/rest/api/2/myself', config=config)
    if not isinstance(user, dict) or not any(user.get(k) for k in ('accountId', 'key', 'name')):
        return None
    ignored = {str(cid) for cid in ignored_comment_ids if cid is not None}
    external = [c for c in comments if str(c.get('id')) not in ignored and not (
        ARTEL_REPORT_TAG in str(c.get('body') or '') and _same_jira_user(c.get('author') or {}, user))]
    return {'fingerprint': fingerprint(fields, external), 'fields': fields, 'comments': external,
            'all_comments': comments, 'user': user}


def comments_text(snapshot, limit=12000):
    """Bounded external context. Newer comments remain available in long threads."""
    lines = []
    for comment in snapshot.get('comments') or []:
        author = comment.get('author') or {}
        name = author.get('displayName') or author.get('name') or author.get('key') or 'Автор'
        body = comment.get('body') or ''
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)
        lines.append(f"Комментарий {comment.get('id') or 'без номера'} · {name}:\n{body}")
    text = '\n\n'.join(lines)
    limit = max(0, int(limit))
    if len(text) <= limit:
        return text
    prefix = '…(начало обсуждения усечено)\n'
    remaining = limit - len(prefix)
    return prefix[:limit] if remaining <= 0 else prefix + text[-remaining:]
