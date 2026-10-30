"""Bitbucket Server/Data Center REST, without model-side network access."""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .config import resolve_param, resolve_param_int, resolve_param_bool


class BitbucketError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials to a login page or another host.


class Client:
    def __init__(self, config):
        get = lambda key: resolve_param('bitbucket.' + key, 'BITBUCKET_' + key.upper(), config, '')
        self.url = str(get('url')).rstrip('/')
        self.project, self.repo, self.bot = str(get('project')), str(get('repo')), str(get('bot_user'))
        self.token = str(get('token'))
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise BitbucketError('bitbucket.url должен быть HTTPS URL без credentials, query и fragment')
        if not all((self.project, self.repo, self.token, self.bot)):
            raise BitbucketError('Нужны bitbucket.project, repo, token и bot_user')
        self.timeout = max(1, resolve_param_int('bitbucket.http_timeout', 'BITBUCKET_HTTP_TIMEOUT', config, 30))
        ca = get('ca_file') or None
        # Match the Jira client's default; an explicit CA retains verified TLS.
        verify = resolve_param_bool('bitbucket.verify_ssl', 'BITBUCKET_VERIFY_SSL', config, bool(ca))
        context = ssl.create_default_context(cafile=ca if verify else None)
        if not verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(
            context=context))
        q = lambda s: urllib.parse.quote(s, safe='')
        self.path = '/rest/api/1.0/projects/' + q(self.project) + '/repos/' + q(self.repo)

    def request(self, method, suffix='', data=None, params=None):
        url = self.url + self.path + suffix
        if params:
            url += '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method=method, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json',
            'Content-Type': 'application/json'},
            data=None if data is None else json.dumps(data).encode())
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise BitbucketError('Ответ Bitbucket слишком большой')
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            # No response bodies/URLs/tokens in logs; POST is deliberately never retried.
            raise BitbucketError(f'Bitbucket: HTTP {exc.code} при {method}') from None
        except (OSError, ValueError) as exc:
            raise BitbucketError(f'Bitbucket: ошибка сети или JSON ({type(exc).__name__})') from None

    def pages(self, suffix, **params):
        start, seen = 0, set()
        for _ in range(100):
            page = self.request('GET', suffix, params=dict(params, start=start, limit=100))
            if not isinstance(page, dict) or not isinstance(page.get('values'), list):
                raise BitbucketError('Неполная страница Bitbucket')
            yield from page['values']
            if page.get('isLastPage') is True:
                return
            nxt = page.get('nextPageStart')
            if type(nxt) is not int or nxt <= start or nxt in seen:
                raise BitbucketError('Некорректная пагинация Bitbucket')
            seen.add(start)
            start = nxt
        raise BitbucketError('Превышен лимит страниц Bitbucket')

    def prs(self, branch):
        return list(self.pages('/pull-requests', state='OPEN', direction='OUTGOING',
                               at='refs/heads/' + branch))

    def pr(self, number):
        return self.request('GET', f'/pull-requests/{int(number)}')

    def threads(self, number):
        roots, child_ids = {}, set()
        def children(comment):
            nested = comment.get('comments') or []
            if not isinstance(nested, list):
                raise BitbucketError('Неизвестный формат обсуждения Bitbucket')
            for child in nested:
                child_ids.add(child['id'])
                children(child)
        for activity in self.pages(f'/pull-requests/{int(number)}/activities'):
            comment = activity.get('comment')
            if comment:
                children(comment)
                if not comment.get('parent'):
                    roots[comment['id']] = comment
        # Activities contain snapshots; get the current complete thread before acting.
        return [self.thread(number, cid) for cid in sorted(set(roots) - child_ids)]

    def thread(self, number, cid):
        return self.request('GET', f'/pull-requests/{int(number)}/comments/{int(cid)}')

    def reply(self, number, cid, text):
        return self.request('POST', f'/pull-requests/{int(number)}/comments',
                            {'text': text, 'parent': {'id': int(cid)}})
