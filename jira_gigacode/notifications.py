"""Durable, task-scoped Jira decision notices; remote comments are reconciled by author and tag."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from . import jira_client, runtime
from .base import LOGS_DIR, logger
from .config import instance_key, resolve_param, resolve_param_bool
from .issue_report import ARTEL_REPORT_TAG
from .logs import mask_secrets
from .platform_support import fcntl


RETRY_SECONDS = 300


def path_for(config, logs_dir=None):
    return Path(LOGS_DIR if logs_dir is None else logs_dir) / (instance_key(config) + '-notifications.json')


def _scope(config):
    return hashlib.sha256(json.dumps([str(resolve_param('jira.url', 'JIRA_URL', config, '')).rstrip('/'),
        resolve_param('jira.project', 'JIRA_PROJECT', config, '')], ensure_ascii=False).encode()).hexdigest()


def _identity(config, issue_key, kind, identity):
    return hashlib.sha256(json.dumps([_scope(config), instance_key(config), issue_key, kind, identity],
                                     ensure_ascii=False).encode()).hexdigest()


def _enabled(config):
    return (not runtime.DRY_RUN and resolve_param_bool('jira.enabled', 'JIRA_ENABLED', config, True)
            and resolve_param_bool('jira.result_comments', 'JIRA_RESULT_COMMENTS', config, True))


def _safe(text, config):
    text = str(text)
    for section in ('jira', 'bitbucket', 'jenkins'):
        for key in ('token', 'password', 'api_token'):
            secret = resolve_param(section + '.' + key, section.upper() + '_' + key.upper(), config, '')
            if isinstance(secret, str) and len(secret) >= 4:
                text = text.replace(secret, '***')
    return mask_secrets(text)


def _save(path, state):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.notifications-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def _journal(config, logs_dir):
    path = path_for(config, logs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'entries': {}}
        if not isinstance(state, dict) or not isinstance(state.get('entries'), dict):
            raise ValueError('Повреждён журнал уведомлений')
        yield path, state


def _deliver(config, path, state, row):
    """One reconciliation attempt. A failed/uncertain POST is never blindly repeated."""
    from .reports import _same_jira_user
    now = time.time()
    if row.get('status') == 'delivered':
        return True
    if row.get('retry_after', 0) > now:
        return False
    row['retry_after'] = now + RETRY_SECONDS
    _save(path, state)
    try:
        comments = jira_client.fetch_comments(row['issue'], config)
        user = jira_client.jira_request('GET', '/rest/api/2/myself', config=config)
        if not isinstance(comments, list) or not isinstance(user, dict) or not any(
                user.get(k) for k in ('accountId', 'key', 'name')):
            return False
        own = [c for c in comments if isinstance(c, dict) and c.get('id')
               and row['marker'] in str(c.get('body') or '')
               and _same_jira_user(c.get('author') or {}, user)]
        comment = max(own, key=lambda c: (str(c.get('created') or ''), str(c['id']))) if own else None
        if comment:
            row['comment_id'] = str(comment['id'])
            result = (comment if comment.get('body') == row['body'] else
                      jira_client.update_comment(row['issue'], comment['id'], row['body'], config))
        elif row.get('post_uncertain'):
            # The request may have reached Jira even if its reply was lost. Only a matching
            # remote comment proves delivery; an empty read does not prove POST failure.
            logger.warning('[%s] Отправка уведомления Jira не подтверждена; проверяю доставку без повторного POST', row['issue'])
            return False
        elif row.get('resolved'):
            # A deleted original is not replaced by a brand-new closing comment.
            row.update(status='delivered', retry_after=0)
            _save(path, state)
            return True
        else:
            row.update(status='sending', post_uncertain=True)
            _save(path, state)  # Survives a crash between the remote POST and its response.
            result = jira_client.jira_request('POST', '/rest/api/2/issue/' + row['issue'] + '/comment',
                data={'body': row['body']}, config=config, max_retries=0, return_error=True)
            if (isinstance(result, dict) and 400 <= result.get('_http_error', 0) < 500
                    and result['_http_error'] != 408):
                # Explicit rejection means Jira did not accept this comment. Retry later.
                row.update(status='pending', post_uncertain=False)
                result = None
        if result is not None and isinstance(result, dict) and not result.get('_http_error'):
            row.update(status='delivered', post_uncertain=False, delivered_at=now, retry_after=0)
            if result.get('id'):
                row['comment_id'] = str(result['id'])
            _save(path, state)
            return True
    except Exception as exc:
        # Exception text can contain remote URLs, response bodies or credentials.
        logger.warning('[%s] Уведомление Jira отложено (%s)', row['issue'], type(exc).__name__)
    _save(path, state)
    return False


def notify(config, issue_key, kind, reason, *, action='', identity='', logs_dir=None):
    """Upsert one decision notice. Returns true only after confirmed delivery.

    kind and identity identify a stable notice, never a timestamp or retry counter.
    The stored text is sufficient for flush() even if the issue leaves the search scope.
    """
    if not _enabled(config):
        return False
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', str(issue_key)):
        return False
    try:
        key = _identity(config, issue_key, kind, identity)
        marker = '[artel-decision:' + key + ']'
        body = ('*Артель: требуется решение*\n' + _safe(reason, config)[:18000] +
                ('\n\n*Что сделать*\n' + _safe(action, config)[:7000] if action else '') +
                '\n\n' + ARTEL_REPORT_TAG + '\n' + marker)
        with _journal(config, logs_dir) as (path, state):
            row = state['entries'].setdefault(key, {'issue': issue_key, 'kind': kind, 'marker': marker,
                'scope': _scope(config), 'created_at': time.time()})
            if row.get('body') != body:
                row.update(body=body, status='pending', updated_at=time.time(), retry_after=0, resolved=False)
                _save(path, state)
            return _deliver(config, path, state, row)
    except Exception as exc:
        logger.warning('[%s] Не удалось сохранить уведомление Jira (%s)', issue_key, type(exc).__name__)
        return False


def resolve(config, issue_key, kind, *, identity='', logs_dir=None):
    """Close an existing notice in place; never create a new resolution-only comment."""
    if not _enabled(config) or not path_for(config, logs_dir).exists():
        return False
    try:
        with _journal(config, logs_dir) as (path, state):
            row = state['entries'].get(_identity(config, issue_key, kind, identity))
            if row is None:
                return True
            if not row.get('resolved'):
                previous = row['body']
                heading = '*Артель: требуется решение*\n'
                if previous.startswith(heading):
                    previous = previous[len(heading):]
                row.update(body='*Артель: решение принято, ожидание снято*\n'
                    'Текущее состояние доступно в панели демона. '
                    'Ниже сохранён исходный запрос; повторное подтверждение не требуется.\n\n'
                    '*Исходный запрос*\n' + previous,
                    resolved=True, status='pending', updated_at=time.time(), retry_after=0)
                # Do not create a fresh notice if the original was never attempted.
                if not row.get('comment_id') and not row.get('post_uncertain'):
                    state['entries'].pop(_identity(config, issue_key, kind, identity), None)
                    _save(path, state)
                    return True
                _save(path, state)
            return _deliver(config, path, state, row)
    except Exception as exc:
        logger.warning('[%s] Закрытие уведомления Jira отложено (%s)', issue_key, type(exc).__name__)
        return False


def flush(config, logs_dir=None, limit=10):
    """Retry pending lookup/PUT safely, including notices for tasks no longer in JQL."""
    if not _enabled(config) or not path_for(config, logs_dir).exists():
        return 0
    delivered = 0
    try:
        with _journal(config, logs_dir) as (path, state):
            pending = [r for r in state['entries'].values() if isinstance(r, dict)
                       and r.get('scope') == _scope(config) and r.get('status') != 'delivered'
                       and r.get('retry_after', 0) <= time.time()]
            for row in sorted(pending, key=lambda r: r.get('retry_after', 0))[:limit]:
                delivered += bool(_deliver(config, path, state, row))
    except Exception as exc:
        logger.warning('Повтор уведомлений Jira отложен (%s)', type(exc).__name__)
    return delivered
