"""Общая обвязка тестов демона (пакет jira_gigacode).

Тесты работают без сети и без настоящих Jira/Jenkins/GigaCode:
- git — настоящий, но на временных репозиториях (origin = локальный bare-репозиторий);
- GigaCode — tests/fake_gigacode.sh, поведение задаёт FAKE_MODE;
- Jira — FakeJira, подменяет jira_request и записывает все запросы.
"""
import contextlib
import io
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TESTS_DIR)
FAKE_GIGACODE = os.path.join(TESTS_DIR, 'fake_gigacode.sh')

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from jira_gigacode import (cli, experience, explore, gigacode, git_workspace, issue_report, jira_client, log_archive,  # noqa: E402
                           logs, pipeline, reports, retro, retry, routing, runtime)

# Лог демона в тестах не печатается (иначе вывод тонет в INFO-строках).
# Показать: TEST_LOGS=1 python3 -m unittest discover -s tests
if not os.environ.get('TEST_LOGS'):
    _root = logging.getLogger()
    for _h in list(_root.handlers):
        _root.removeHandler(_h)
        _h.close()
    _root.addHandler(logging.NullHandler())
    logging.getLogger('artel').disabled = True  # журнал супервизора

# Переменные окружения, которые читает демон: в тестах их не должно быть,
# иначе настройки из оболочки разработчика (JIRA_TOKEN, REPO_PATH…) повлияют на результат
_DAEMON_ENV = re.compile(
    r'(^|_)(DEPENDENCIES_|BITBUCKET_|JIRA_|JENKINS_|GIGACODE_|REPO_PATH$|BASE_BRANCH|BRANCH_PREFIX$|POLL_INTERVAL$|DAEMON_NAME$|TEMP_FILES$|'
    r'RETRY_COOLDOWN|REQUIRE_SUCCESS_MARKER$|COMPARE_URL$|DRY_RUN$|CONFIG_PATH$|ENV_FILE$)')

# Git без глобального конфига разработчика (подпись коммитов, хуки, алиасы) и с фиксированным автором
_GIT_ENV = {
    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0',
    'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.com',
    'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.com',
}


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def git(cwd, *args, check=True):
    proc = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} упал: {proc.stderr}")
    return proc.stdout.strip()


class FakeJira:
    """Подмена jira_request: задача с состоянием, переходами, лейблами и комментариями."""

    def __init__(self, issues=('T-1',), status='Анализ', ready='Ревью'):
        self.issues = list(issues)
        self.status = status
        self.ready = ready
        self.can_transition = True
        self.labels = []
        self.comments = []         # [{'body', 'created', 'issue'?}]
        self.posted_comments = []  # тела комментариев, оставленных демоном
        self.transitions_done = []
        self.searches = []         # JQL всех поисков
        self.invalid_statuses = set()
        self.myself = {'displayName': 'Робот', 'key': 'robot', 'name': 'robot'}
        self.updated_comments = []
        self.project_ok = True
        self.down = False          # True — сеть «лежит»: всё возвращает None
        self.summary, self.description = 'Сделать отчёт', 'Описание задачи'
        self.updated = '2026-10-01T10:00:00.000+0300'
        # Бэклог для исследования в простое: задачи, которые ищутся по статусам backlog_statuses
        self.backlog = []
        self.backlog_statuses = {'TO DO', 'Backlog'}
        self.fields_by_issue = {}  # свои поля для отдельных задач (по умолчанию — общие summary/updated…)
        self.links = []
        self.ci_by_issue = {}
        self.search_pages = []     # (startAt, maxResults) всех поисков

    def __call__(self, method, path, data=None, params=None, max_retries=3, config=None, return_error=False):
        if self.down:
            return None
        if path == '/rest/api/2/myself':
            return self.myself
        if path.startswith('/rest/api/2/project/'):
            return {'name': 'Тестовый проект'} if self.project_ok else {'_http_error': 404}
        if path == '/rest/api/2/search':
            jql = data['jql']
            self.searches.append(jql)
            if jql.startswith('key IN (') and 'cf[' in jql:
                keys = re.findall(r'"([A-Z][A-Z0-9_]*-\d+)"', jql)
                ci = re.search(r'cf\[[^]]+\] = "([^"]+)"', jql).group(1)
                matches = [key for key in keys if self.ci_by_issue.get(key) == ci]
                return {'issues':[{'key':key} for key in matches], 'total':len(matches)}
            bad = [s for s in self.invalid_statuses if f'"{s}"' in jql]
            if bad:
                msgs = [f"The value '{s}' does not exist for the field 'status'." for s in bad]
                return {'_http_error': 400, '_error_messages': msgs, '_errors': {}} if return_error else None
            keys = self.backlog if any(f'"{s}"' in jql for s in self.backlog_statuses) else self.issues
            start, size = int(data.get('startAt') or 0), int(data.get('maxResults') or 50)
            self.search_pages.append((start, size))
            fields = {'summary': self.summary, 'description': self.description,
                      'updated': self.updated, 'status': {'name': self.status}}
            return {'issues': [{'key': k, 'fields': dict(self.fields_by_issue.get(k, fields))}
                               for k in keys[start:start + size]],
                    'total': len(keys), 'startAt': start}
        if '/comment/' in path and method == 'PUT':
            issue, comment_id = path.split('/')[-3], path.split('/')[-1]
            for comment in self.comments:
                if comment.get('issue') in (None, issue) and str(comment.get('id')) == comment_id:
                    comment['body'] = data['body']
                    self.updated_comments.append(dict(comment))
                    self.updated = f'edited#{len(self.updated_comments)}'
                    return dict(comment)
            return None
        if path.endswith('/comment'):
            issue = path.split('/')[-2]
            if method == 'POST':
                self.posted_comments.append(data['body'])
                self.updated = f'2026-10-02T10:00:00.000+0300#{len(self.posted_comments)}'  # комментарий меняет updated
                self.comments.append({'body': data['body'], 'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                      'issue': issue, 'id': str(len(self.comments) + 1), 'author': dict(self.myself)})
                return {'id': str(len(self.comments))}
            # Комментарии, добавленные в тесте без 'issue', видны во всех задачах
            mine = [c for c in self.comments if c.get('issue') in (None, issue)]
            return {'comments': mine, 'total': len(mine)}
        if path.endswith('/transitions'):
            if method == 'POST':
                self.transitions_done.append(data['transition']['id'])
                self.status = self.ready
                return {'_status': 204}
            if not self.can_transition:
                return {'transitions': [{'id': '9', 'name': 'Закрыть', 'to': {'name': 'Закрыта'}}]}
            return {'transitions': [{'id': '5', 'name': 'На ревью', 'to': {'name': self.ready}},
                                    {'id': '9', 'name': 'Закрыть', 'to': {'name': 'Закрыта'}}]}
        fields = (params or {}).get('fields')
        if fields == 'summary,labels':
            key = path.rsplit('/', 1)[-1]
            base = {'summary':self.summary, 'labels':list(self.labels)}
            return {'fields':dict(base, **self.fields_by_issue.get(key, {}))}
        if fields == 'summary,description,labels,status,issuelinks':
            key = path.rsplit('/', 1)[-1]
            base = {'summary':self.summary, 'description':self.description, 'labels':list(self.labels),
                    'status':{'name':self.status}, 'issuelinks':list(self.links)}
            return {'id':key.rsplit('-', 1)[-1], 'fields':dict(base, **self.fields_by_issue.get(key, {}))}
        if fields == 'status':
            return {'fields': {'status': {'name': self.status, 'id': '1'}}}
        if fields == 'labels':
            return {'fields': {'labels': list(self.labels)}}
        return {'fields': {'summary': self.summary, 'description': self.description, 'labels': list(self.labels),
                           'updated': self.updated, 'status': {'name': self.status}}}


class DaemonTestCase(unittest.TestCase):
    """База: чистое окружение, свежие глобальные состояния модуля, временные каталоги."""

    def setUp(self):
        env = {k: v for k, v in os.environ.items() if not _DAEMON_ENV.search(k)}
        env.update(_GIT_ENV)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.tmp = tempfile.mkdtemp(prefix='jira2gc-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # Счётчики вызовов поддельного CLI (FAKE_REVIEW=changes,approve) — свои у каждого теста
        os.environ['FAKE_STATE_DIR'] = self.tmp

        # Глобальные состояния демона — между тестами не протекают
        self.jira = FakeJira()
        for module, name, value in ((jira_client, 'jira_request', self.jira),
                                    (runtime, 'DRY_RUN', False),
                                    (runtime, 'running', True),
                                    (runtime, 'state', runtime.NullReporter()),
                                    (retry, '_pending_transitions_path', os.path.join(self.tmp, 'pending.json'))):
            p = mock.patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)
        # logs/ демона (заметки по задачам, учёт исследованных задач) — во временной папке
        logs_patch = mock.patch.multiple(experience, LOGS_DIR=os.path.join(self.tmp, 'logs'))
        logs_patch.start()
        self.addCleanup(logs_patch.stop)
        from jira_gigacode import requirements_rework
        for module in (explore, routing, log_archive, retro, requirements_rework):
            logs_patch2 = mock.patch.object(module, 'LOGS_DIR', os.path.join(self.tmp, 'logs'))
            logs_patch2.start()
            self.addCleanup(logs_patch2.stop)
        root_patch = mock.patch.object(log_archive, 'PROJECT_DIR', self.tmp)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        for container in (git_workspace._base_ref_cache, retry._RETRY_STATE, issue_report._REPORT,
                          jira_client._invalid_status_names, reports._FAILURE_COMMENTED):
            container.clear()
        logs._issue_errors.errors.clear()

        # Паузы демона (sleep после перевода в Jira и т. п.) в тестах не нужны. Подменяется
        # только time внутри модуля демона: subprocess и прочие пользуются настоящим
        fake_time = types.SimpleNamespace(**{n: getattr(time, n) for n in dir(time) if not n.startswith('_')})
        fake_time.sleep = lambda s: None
        for module in (jira_client, pipeline, cli):
            sleep_patch = mock.patch.object(module, 'time', fake_time)
            sleep_patch.start()
            self.addCleanup(sleep_patch.stop)

        root = logging.getLogger()
        if logs._issue_errors not in root.handlers:
            root.addHandler(logs._issue_errors)
        os.chmod(FAKE_GIGACODE, os.stat(FAKE_GIGACODE).st_mode | stat.S_IXUSR)

    # --- репозитории ---
    def make_repo(self, branches=('develop',)):
        """Рабочий клон + bare origin; в origin есть перечисленные ветки, HEAD на develop."""
        root = tempfile.mkdtemp(dir=self.tmp)
        origin, work = os.path.join(root, 'origin.git'), os.path.join(root, 'work')
        git(root, 'init', '-q', '--bare', origin)
        git(root, 'clone', '-q', origin, work)
        with open(os.path.join(work, 'README.md'), 'w') as f:
            f.write('base\n')
        git(work, 'add', '.')
        git(work, 'commit', '-qm', 'init')
        git(work, 'branch', '-M', 'develop')
        git(work, 'push', '-q', 'origin', 'develop')
        git(origin, 'symbolic-ref', 'HEAD', 'refs/heads/develop')  # основная ветка origin — develop
        for b in branches:
            if b != 'develop':
                git(work, 'push', '-q', 'origin', f'develop:refs/heads/{b}')
        git(work, 'fetch', '-q', 'origin')
        return work

    def remote_files(self, work, branch):
        """Файлы ветки в origin (пустой список — ветки нет)."""
        if not git(work, 'ls-remote', 'origin', branch):
            return None
        git(work, 'fetch', '-q', 'origin', f'+refs/heads/{branch}:refs/remotes/origin/{branch}')
        return git(work, 'ls-tree', '-r', '--name-only', f'origin/{branch}').splitlines()

    def config(self, work, **general):
        cfg = {
            'jira': {'url': 'https://jira.invalid', 'token': 't', 'project': 'T',
                     'status_analysis': ['Анализ'], 'status_ready': ['Ревью']},
            'general': {'name': 'Олег', 'repo_path': work, 'gigacode_path': FAKE_GIGACODE,
                        'gigacode_timeout_seconds': 5,
                        'gigacode_chats_dir': os.path.join(self.tmp, 'no-chats')},
        }
        # Ревью и файл опыта — включаются в своих тестах; файл опыта всегда во временной папке
        cfg['review'] = {'enabled': False}
        cfg['memory'] = {'path': os.path.join(self.tmp, 'memory', '{key}.md')}
        cfg['general'].update(general)
        return cfg

    def run_generation(self, key, cfg, mode):
        """Генерация с поддельным CLI; его эхо в терминал демона в тестах глушится."""
        sink = io.StringIO() if not os.environ.get('TEST_LOGS') else sys.stdout
        with mock.patch.dict(os.environ, {'FAKE_MODE': mode}), contextlib.redirect_stdout(sink):
            return gigacode.run_gigacode_orchestrator(key, cfg)
