"""Проверка окружения (--check), пробный запуск (--dry-run) и запуск скрипта целиком."""
import json
import os
import shutil
import subprocess
import sys

from helpers import FAKE_GIGACODE, PROJECT_DIR, DaemonTestCase, git
from jira_gigacode import checks, dry_run, jenkins, retry, runtime


class StartupChecksTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo(branches=('develop', 'master'))

    def check(self, cfg):
        return checks.run_startup_checks(cfg)

    def test_healthy(self):
        errors, warnings = self.check(self.config(self.work))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_repo(self):
        errors, _ = self.check(self.config(os.path.join(self.tmp, 'нет')))
        self.assertTrue(any('Репозиторий не найден' in e for e in errors))

    def test_not_a_git_repo(self):
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        errors, _ = self.check(self.config(plain))
        self.assertTrue(any('не git' in e for e in errors))

    def test_no_origin(self):
        git(self.work, 'remote', 'remove', 'origin')
        errors, _ = self.check(self.config(self.work))
        self.assertTrue(any('origin' in e for e in errors))

    def test_no_develop_on_origin(self):
        origin = git(self.work, 'remote', 'get-url', 'origin')
        git(origin, 'symbolic-ref', 'HEAD', 'refs/heads/master')  # текущую ветку bare-репозитория удалить нельзя
        git(self.work, 'push', '-q', 'origin', '--delete', 'develop')
        errors, _ = self.check(self.config(self.work))
        self.assertTrue(any('develop' in e for e in errors))

    def test_no_master_is_warning(self):
        git(self.work, 'push', '-q', 'origin', '--delete', 'master')
        errors, warnings = self.check(self.config(self.work))
        self.assertEqual(errors, [])
        self.assertTrue(any('master' in w for w in warnings))

    def test_dirty_worktree_is_warning(self):
        with open(os.path.join(self.work, 'leftover.txt'), 'w') as f:
            f.write('1')
        errors, warnings = self.check(self.config(self.work))
        self.assertEqual(errors, [])
        self.assertTrue(any('незакоммиченных' in w for w in warnings))

    def test_gigacode_not_found(self):
        errors, _ = self.check(self.config(self.work, gigacode_path=os.path.join(self.tmp, 'нет')))
        self.assertTrue(any('GigaCode' in e for e in errors))

    def test_jira_token_rejected(self):
        self.jira.myself = {'_http_error': 401}
        errors, _ = self.check(self.config(self.work))
        self.assertTrue(any('токен' in e for e in errors))

    def test_jira_project_missing(self):
        self.jira.project_ok = False
        errors, _ = self.check(self.config(self.work))
        self.assertTrue(any('Проект Jira' in e for e in errors))

    def test_jira_down_is_only_warning(self):
        self.jira.down = True
        errors, warnings = self.check(self.config(self.work))
        self.assertEqual(errors, [])
        self.assertTrue(any('Jira недоступна' in w for w in warnings))

    def test_incomplete_jenkins_is_warning(self):
        cfg = self.config(self.work)
        cfg['jenkins'] = {'url': 'https://jenkins.invalid'}
        errors, warnings = self.check(cfg)
        self.assertEqual(errors, [])
        self.assertTrue(any('Jenkins неполные' in w for w in warnings))

    def test_jenkins_job_parameters(self):
        cfg = self.config(self.work)
        cfg['jenkins'] = {'url': 'https://jenkins.invalid', 'user': 'u', 'token': 't', 'job_name': 'hr/deploy'}
        job = {'name': 'deploy', 'property': [{'parameterDefinitions': [{'name': 'refName'}, {'name': 'filter'}]}]}
        from unittest import mock
        with mock.patch.object(checks, '_jenkins_get', return_value=job) as get:
            errors, warnings = self.check(cfg)
        self.assertIn('/job/hr/job/deploy/api/json', get.call_args[0][0])
        self.assertEqual(errors, [])
        self.assertTrue(any(jenkins.JENKINS_MIGRATION_PARAM in w for w in warnings))


class DryRunTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo(branches=('develop', 'master'))
        self.cfg = self.config(self.work)
        self.jira.labels = ['jenkins_ift_migration']
        self.jira.comments.append({'body': 'branch: release/9.9', 'created': '2026'})

    def test_changes_nothing(self):
        refs, remote = git(self.work, 'for-each-ref'), git(self.work, 'ls-remote', 'origin')
        runtime.DRY_RUN = True
        with self.assertLogs(level='INFO') as logs:
            dry_run.run_dry_run(self.cfg)
        runtime.DRY_RUN = False
        text = '\n'.join(logs.output)
        self.assertEqual(git(self.work, 'for-each-ref'), refs)
        self.assertEqual(git(self.work, 'ls-remote', 'origin'), remote)
        self.assertEqual(git(self.work, 'branch', '--show-current'), 'develop')
        self.assertEqual(self.jira.posted_comments, [])
        self.assertEqual(self.jira.transitions_done, [])
        # …но рассказывает, что сделал бы
        for part in ('создал бы', 'Отвёл бы feature/ai_team/T-1', 'Перевод: из «Анализ» через «На ревью»',
                     'Оставил бы в задаче комментарий'):
            self.assertIn(part, text)

    def test_reports_pending_transition(self):
        retry.pending_transition_add('T-1')
        runtime.DRY_RUN = True
        with self.assertLogs(level='INFO') as logs:
            dry_run.run_dry_run(self.cfg)
        runtime.DRY_RUN = False
        self.assertIn('повторил бы только перевод', '\n'.join(logs.output))


class ScriptEndToEndTest(DaemonTestCase):
    """Запуск скрипта как процесса: копия во временной папке, чтобы не мусорить в logs/ проекта."""

    def setUp(self):
        super().setUp()
        self.work = self.make_repo(branches=('develop', 'master'))
        self.app = os.path.join(self.tmp, 'app')
        os.makedirs(os.path.join(self.app, 'config'))
        for name in ('jira_to_gigacode.py', 'daemon_state.py'):
            if os.path.exists(os.path.join(PROJECT_DIR, name)):
                shutil.copy(os.path.join(PROJECT_DIR, name), self.app)
        shutil.copytree(os.path.join(PROJECT_DIR, 'jira_gigacode'), os.path.join(self.app, 'jira_gigacode'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        cfg = {'jira': {'url': 'http://127.0.0.1:9', 'token': 't', 'project': 'T',
                        'status_analysis': ['Анализ'], 'status_ready': ['Ревью']},
               'general': {'repo_path': self.work, 'gigacode_path': FAKE_GIGACODE}}
        with open(os.path.join(self.app, 'config', 't.json'), 'w', encoding='utf-8') as f:
            json.dump(cfg, f)

    def run_script(self, *args, timeout=60):
        return subprocess.run([sys.executable, 'jira_to_gigacode.py', *args], cwd=self.app,
                              capture_output=True, text=True, timeout=timeout)

    def test_check_passes_with_jira_down(self):
        proc = self.run_script('config/t.json', '--check')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('Проверка окружения пройдена', proc.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.app, 'logs', 't-check.log')))

    def test_check_fails_on_broken_env(self):
        path = os.path.join(self.app, 'config', 't.json')
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
        cfg['general']['gigacode_path'] = '/нет/gigacode'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
        proc = self.run_script('config/t.json', '--check')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('GigaCode CLI не найден', proc.stdout)

    def test_dry_run_exits(self):
        proc = self.run_script('config/t.json', '--dry-run')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('DRY-RUN завершён', proc.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.app, 'logs', 't-state.json')),
                         'dry-run не должен писать состояние для дашборда')

    def test_unknown_flag(self):
        proc = self.run_script('--bogus')
        self.assertEqual(proc.returncode, 2)
        self.assertIn('Неизвестный флаг', proc.stderr)
