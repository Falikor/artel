"""Read Jira Development branches and verify code in the configured backend Git remote."""
import os
import re
import subprocess
import urllib.parse
import uuid

from . import jira_client, routing
from .config import base_branch, repo_path, resolve_param


def branches(issue_id, config):
    if not str(issue_id).isdigit():
        raise ValueError('Jira не вернула числовой ID задачи для панели Development')
    application = str(resolve_param('dependencies.dev_application_type', 'DEPENDENCIES_DEV_APPLICATION_TYPE', config, 'stash'))
    datatype = str(resolve_param('dependencies.dev_data_type', 'DEPENDENCIES_DEV_DATA_TYPE', config, 'pullrequest'))
    if datatype not in ('pullrequest', 'branch'):
        raise ValueError('dependencies.dev_data_type должен быть pullrequest или branch')
    result = jira_client.jira_request('GET', '/rest/dev-status/1.0/issue/detail',
        params={'issueId':str(issue_id), 'applicationType':application, 'dataType':datatype}, config=config)
    if not isinstance(result, dict) or result.get('errors') or result.get('configErrors') or not isinstance(result.get('detail'), list):
        raise ValueError('Панель Development недоступна; проверьте права Jira и Application Link к Bitbucket')
    found = []
    for detail in result['detail']:
        if not isinstance(detail, dict) or not isinstance(detail.get('branches'), list):
            raise ValueError('Неизвестный формат списка веток Development')
        for branch in detail['branches']:
            if not isinstance(branch, dict) or not isinstance(branch.get('name'), str):
                raise ValueError('Неизвестный формат ветки Development')
            found.append(branch)
    if len(found) > 50:
        raise ValueError('В Development больше 50 веток; уточните связи задачи с кодом')
    return found


def _git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))


def repository_identity(url):
    """Bitbucket browse URLs and HTTPS/SSH clone URLs identify the same repository."""
    if not isinstance(url, str):
        return None
    if '://' not in url and re.match(r'[^/]+@[^:]+:', url):
        host, path = url.split(':', 1)
        url = 'ssh://' + host + '/' + path
    parsed = urllib.parse.urlsplit(url)
    if not parsed.hostname:
        return None
    path = urllib.parse.unquote(parsed.path).rstrip('/')
    match = re.search(r'/(?:projects/([^/]+)/repos/([^/]+)|scm/([^/]+)/([^/]+))(?:/.*)?$', path)
    if match:
        project, repo = (match[1], match[2]) if match[1] else (match[3], match[4])
    elif parsed.scheme == 'ssh' and len(path.strip('/').split('/')) == 2:
        project, repo = path.strip('/').split('/')
    else:
        return None
    return parsed.hostname.casefold(), project.casefold(), repo.removesuffix('.git').casefold()


def same_repository(repo, branch):
    origin = _git(repo, 'remote', 'get-url', '--all', 'origin')
    urls = origin.stdout.strip().splitlines()
    if origin.returncode or len(urls) != 1:
        return False
    expected = repository_identity(urls[0])
    repository = branch.get('repository') or {}
    actual = repository_identity(repository.get('url')) if isinstance(repository, dict) else None
    actual = actual or repository_identity(branch.get('url'))
    return expected is not None and actual == expected


def branch_with_code(fields, owner_config):
    """No checkouts or writes to the remote. Missing/unverifiable evidence never unlocks front."""
    candidates = branches(fields.get('_jira_id'), owner_config)
    if not candidates:
        return None
    if routing.services(owner_config):
        service, _ = routing.route(fields.get('summary') or '', fields.get('labels') or [], owner_config)
        if service is None:
            raise ValueError('Для проверки ветки бэкенда не определён services[].repo_path')
        cfg = routing.config_for_service(owner_config, service)
    else:
        cfg = owner_config
    repo, base = repo_path(cfg), base_branch(cfg)
    prefix = 'refs/artel-dependencies/' + uuid.uuid4().hex
    try:
        for item in candidates:
            name = item['name'].removeprefix('refs/heads/')
            if name == base or _git(repo, 'check-ref-format', 'refs/heads/' + name).returncode:
                continue
            if not same_repository(repo, item):
                continue
            # Exact fetch also rejects a deleted branch despite a stale Development record.
            result = _git(repo, 'fetch', '--no-tags', 'origin',
                          '+refs/heads/' + base + ':' + prefix + '/base',
                          '+refs/heads/' + name + ':' + prefix + '/branch')
            if result.returncode:
                continue
            changed = _git(repo, 'diff', '--quiet', prefix + '/base...' + prefix + '/branch', '--')
            if changed.returncode == 1:
                head = _git(repo, 'rev-parse', prefix + '/branch').stdout.strip()
                return {'branch':name, 'head':head, 'base':base, 'source':'Jira Development + Git',
                        'url':str(item.get('url') or '')}
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Git-проверка ветки Development недоступна (' + type(exc).__name__ + ')') from None
    finally:
        for suffix in ('base', 'branch'):
            try:
                _git(repo, 'update-ref', '-d', prefix + '/' + suffix)
            except (OSError, subprocess.TimeoutExpired):
                pass
    return None
