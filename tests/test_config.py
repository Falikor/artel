"""Конфиг, окружение, идентификаторы инстанса, разбор флагов."""
import json
import os
from unittest import mock

from helpers import DaemonTestCase
from jira_gigacode import cli, config, logs


class ResolveParamTest(DaemonTestCase):
    def test_config_value(self):
        cfg = {'general': {'poll_interval_seconds': 120}}
        self.assertEqual(config.resolve_param('general.poll_interval_seconds', 'POLL_INTERVAL', cfg, 600), 120)

    def test_default_when_missing(self):
        self.assertEqual(config.resolve_param('general.nope', None, {}, 'dflt'), 'dflt')

    def test_env_beats_config(self):
        with mock.patch.dict(os.environ, {'POLL_INTERVAL': '30'}):
            self.assertEqual(config.resolve_param('general.poll_interval_seconds', 'POLL_INTERVAL',
                                             {'general': {'poll_interval_seconds': 120}}, 600), '30')

    def test_project_prefixed_env_beats_common(self):
        cfg = {'jira': {'project': 'HRPPA'}}
        with mock.patch.dict(os.environ, {'JIRA_TOKEN': 'common', 'HRPPA_JIRA_TOKEN': 'own'}):
            self.assertEqual(config.resolve_param('jira.token', 'JIRA_TOKEN', cfg, None), 'own')

    def test_blank_env_is_ignored(self):
        with mock.patch.dict(os.environ, {'REPO_PATH': '  '}):
            self.assertEqual(config.resolve_param('general.repo_path', 'REPO_PATH',
                                             {'general': {'repo_path': '/repo'}}, None), '/repo')

    def test_int(self):
        self.assertEqual(config.resolve_param_int('a.b', None, {'a': {'b': '15'}}, 1), 15)
        self.assertEqual(config.resolve_param_int('a.b', None, {'a': {'b': 'много'}}, 1), 1)

    def test_bool(self):
        for raw, expected in (('true', True), ('да', True), ('1', True), ('off', False), ('нет', False),
                              (True, True), (0, False)):
            self.assertIs(config.resolve_param_bool('a.b', None, {'a': {'b': raw}}, None), expected, raw)
        self.assertIs(config.resolve_param_bool('a.b', None, {'a': {'b': 'странно'}}, True), True)

    def test_list_from_string_and_list_dedup(self):
        self.assertEqual(config.resolve_param_list('a', None, {'a': 'Анализ, Разработка ,анализ'}, []),
                         ['Анализ', 'Разработка'])
        self.assertEqual(config.resolve_param_list('a', None, {'a': ['Ревью', '', 'ревью']}, []), ['Ревью'])
        self.assertEqual(config.resolve_param_list('a', None, {}, None), [])


class InstanceIdentityTest(DaemonTestCase):
    def test_ci_id_normalized(self):
        for raw in ('CI03191860', 'ci3191860', ' 03191860 ', 3191860):
            self.assertEqual(config.normalized_ci_id({'general': {'ci_id': raw}}), '3191860', raw)
        self.assertIsNone(config.normalized_ci_id({'general': {}}))

    def test_instance_key(self):
        self.assertEqual(config.instance_key({'general': {'ci_id': 'CI15172563'}, 'jira': {'project': 'HRPPA'}}),
                         'ci15172563')
        self.assertEqual(config.instance_key({'jira': {'project': 'HRPPA'}}), 'hrppa')

    def test_legacy_logs_are_adopted_once(self):
        logs_dir = os.path.join(self.tmp, 'logs')
        os.makedirs(logs_dir)
        for name in ('hrppa-history.jsonl', 'hrppa-agent.log'):
            with open(os.path.join(logs_dir, name), 'w') as f:
                f.write(name)
        cfg = {'general': {'ci_id': 'CI42'}, 'jira': {'project': 'HRPPA'}}
        logs.adopt_legacy_logs(logs_dir, cfg)
        self.assertEqual(sorted(os.listdir(logs_dir)), ['ci42-agent.log', 'ci42-history.jsonl'])
        # Повторный запуск ничего не трогает и не затирает новые файлы старыми
        with open(os.path.join(logs_dir, 'hrppa-agent.log'), 'w') as f:
            f.write('old')
        logs.adopt_legacy_logs(logs_dir, cfg)
        with open(os.path.join(logs_dir, 'ci42-agent.log')) as f:
            self.assertEqual(f.read(), 'hrppa-agent.log')


class ConfigFilesTest(DaemonTestCase):
    def test_env_file(self):
        path = os.path.join(self.tmp, '.env')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('# комментарий\nJIRA_TOKEN="from-file"\nJENKINS_USER=robot\nEMPTY=\nbroken line\n')
        with mock.patch.dict(os.environ, {'JENKINS_USER': 'from-shell'}):
            self.assertTrue(config.load_env_file(path))
            self.assertEqual(os.environ['JIRA_TOKEN'], 'from-file')
            self.assertEqual(os.environ['JENKINS_USER'], 'from-shell')  # окружение главнее .env
            self.assertNotIn('EMPTY', os.environ)
        self.assertFalse(config.load_env_file(os.path.join(self.tmp, 'нет.env')))

    def test_load_config_explicit_path(self):
        path = os.path.join(self.tmp, 'c.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'jira': {'project': 'T'}}, f)
        self.assertEqual(config.load_config(path)['jira']['project'], 'T')

    def test_load_config_missing_or_broken_exits(self):
        with self.assertRaises(SystemExit):
            config.load_config(os.path.join(self.tmp, 'нет.json'))
        broken = os.path.join(self.tmp, 'broken.json')
        with open(broken, 'w') as f:
            f.write('{')
        with self.assertRaises(SystemExit):
            config.load_config(broken)

    def test_load_config_without_any_config_exits_cleanly(self):
        # Раньше падало с TypeError на os.path.exists(None)
        with mock.patch.object(os.path, 'exists', lambda p: False if p is None or 'config' in str(p) else True):
            with self.assertRaises(SystemExit):
                config.load_config(None)

    def test_validate_config_requires_keys(self):
        with self.assertRaises(SystemExit):
            config.validate_config({'jira': {'url': 'u', 'token': 't'}})
        config.validate_config({'jira': {'url': 'u', 'token': 't', 'project': 'T',
                                    'status_analysis': ['А'], 'status_ready': ['Р']}})


class CliTest(DaemonTestCase):
    def test_parse(self):
        self.assertEqual(cli.parse_cli([]), (None, {'--check': False, '--dry-run': False, '--retro': False}))
        self.assertEqual(cli.parse_cli(['c.json', '--dry-run']), ('c.json', {'--check': False, '--dry-run': True, '--retro': False}))
        self.assertEqual(cli.parse_cli(['--check', 'c.json'])[1]['--check'], True)

    def test_bad_flags(self):
        for argv in (['--bogus'], ['a.json', 'b.json']):
            with self.assertRaises(SystemExit) as ctx, mock.patch('sys.stderr'):
                cli.parse_cli(argv)
            self.assertEqual(ctx.exception.code, 2)
