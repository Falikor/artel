"""Code citations and real subprocess evidence gate automatic memory promotion."""
import contextlib
import io
import json
import os
import sys
import time
from unittest import mock

from helpers import DaemonTestCase, git
from jira_gigacode import experience, memory_store as store, memory_verify as verify, runtime, pipeline


class VerificationTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)
        os.makedirs(os.path.join(self.work, 'tests'))
        with open(os.path.join(self.work, 'tests', 'test_math.py'), 'w') as f:
            f.write('import unittest\nclass MathTest(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(2 + 2, 4)\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'tests')
        git(self.work, 'push', '-q', 'origin', 'develop')
        self.path = experience.memory_path(self.cfg)
        store.observe(self.path, self.cfg, 'T-1', 'генерация', ['Тест суммы расположен в tests/test_math.py'])
        self.entry = store.entries(self.path, self.cfg)[0]
        self.plan = {'kind': 'structural', 'citations': [
            {'path': 'tests/test_math.py', 'quote': 'self.assertEqual(2 + 2, 4)'}], 'tests': []}
        self.judge = {'verdict': 'confirmed', 'kind': 'structural', 'reason': 'Файл содержит проверку суммы', 'scope': []}

    def check(self):
        with mock.patch.object(verify, 'ask', side_effect=[self.plan, self.judge]):
            return verify.verify(self.cfg, self.entry)

    def test_structural_fact_has_verified_commit_and_citation(self):
        result = self.check()
        self.assertEqual(result['result'], 'confirmed')
        self.assertEqual(result['commit'], git(self.work, 'rev-parse', 'HEAD'))
        self.assertEqual(len(git(self.work, 'worktree', 'list').splitlines()), 1)

    def test_behavior_runs_real_tests_and_judge_receives_their_output(self):
        self.plan.update(kind='tested', tests=[0])
        self.judge['kind'] = 'tested'
        with mock.patch.object(verify, 'ask', side_effect=[self.plan, self.judge]) as ask:
            result = verify.verify(self.cfg, self.entry)
        self.assertEqual(result['tests'][0]['returncode'], 0)
        self.assertIn('Ran 1 test', ask.call_args.args[3])

    def test_fake_citation_or_unknown_test_cannot_confirm(self):
        for patch in ({'citations': [{'path': 'tests/test_math.py', 'quote': 'invented evidence not in git'}]},
                      {'tests': [999]}, {'kind': 'tested', 'tests': []},
                      {'citations': [{'path': '../outside', 'quote': 'self.assertEqual(2 + 2, 4)'}]}):
            with self.subTest(patch=patch):
                original = dict(self.plan)
                self.plan.update(patch)
                with self.assertRaises(ValueError):
                    self.check()
                self.plan = original

    def test_failing_and_empty_tests_cannot_confirm(self):
        self.plan.update(kind='tested', tests=[0])
        self.judge['kind'] = 'tested'
        for command in ([sys.executable, '-c', 'raise SystemExit(1)'],
                        [sys.executable, '-c', 'print("Ran 0 tests")']):
            self.cfg['memory']['verify_commands'] = [command]
            with self.assertRaises(ValueError):
                self.check()

    def test_mutating_verifier_cannot_confirm(self):
        def mutate(config, wt, *args):
            with open(os.path.join(wt, 'README.md'), 'w') as f:
                f.write('changed')
            return self.plan
        with mock.patch.object(verify, 'ask', side_effect=mutate), self.assertRaises(ValueError):
            verify.verify(self.cfg, self.entry)
        self.assertEqual(git(self.work, 'status', '--porcelain'), '')

    def test_test_timeout(self):
        result = verify.execute([sys.executable, '-c', 'import time; time.sleep(20)'], self.work, .1)
        self.assertIsNone(result['returncode'])

    def test_idle_confirms_without_manual_approval_and_is_rate_limited(self):
        with mock.patch.object(verify, 'ask', side_effect=[self.plan, self.judge]):
            self.assertEqual(verify.maybe_run(self.cfg), 1)
        self.assertIn('Тест суммы', experience.memory_block(self.cfg))
        row = store.entries(self.path, self.cfg)[0]
        self.assertEqual(row['verification']['result'], 'confirmed')
        store.observe(self.path, self.cfg, 'T-2', 'ревью', ['Второй кандидат'])
        with mock.patch.object(verify, 'verify') as run:
            self.assertEqual(verify.maybe_run(self.cfg), 0)
        run.assert_not_called()

    def test_disputed_only_list_and_explicit_retry(self):
        with mock.patch.object(verify, 'verify', side_effect=ValueError('Противоречие правилам')):
            verify.maybe_run(self.cfg)
        self.assertEqual(experience.memory_block(self.cfg), '')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            store.command(['list', self.path, '--disputed'])
        self.assertIn('Противоречие правилам', output.getvalue())
        with mock.patch.object(store.time, 'time', return_value=time.time() + 2 * 86400):
            self.assertIsNone(store.claim_verification(self.path, self.cfg))
            store.retry_verification(self.path, self.cfg, self.entry['id'])
            self.assertIsNotNone(store.claim_verification(self.path, self.cfg))

    def test_transient_failure_retries_and_never_promotes(self):
        with mock.patch.object(verify, 'verify', side_effect=RuntimeError('CLI unavailable')):
            verify.maybe_run(self.cfg)
        self.assertEqual(store.entries(self.path, self.cfg)[0]['verification']['result'], 'retry')
        with mock.patch.object(store.time, 'time', return_value=time.time() + 25 * 3600):
            self.assertIsNotNone(store.claim_verification(self.path, self.cfg))

    def test_manual_decision_wins_during_background_check(self):
        claimed = store.claim_verification(self.path, self.cfg)
        store.reject(self.path, self.cfg, self.entry['id'])
        self.assertFalse(store.record_verification(self.path, self.cfg, claimed,
                                                  {'result': 'confirmed', 'reason': 'test'}))
        self.assertEqual(store.entries(self.path, self.cfg)[0]['status'], 'rejected')

    def test_expired_automatic_knowledge_is_verified_again(self):
        with mock.patch.object(verify, 'ask', side_effect=[self.plan, self.judge]):
            verify.maybe_run(self.cfg)
        with mock.patch.object(store.time, 'time', return_value=time.time() + 91 * 86400):
            claimed = store.claim_verification(self.path, self.cfg)
            self.assertEqual(claimed['id'], self.entry['id'])

    def test_dry_run_and_disabled_do_not_start_verification(self):
        with mock.patch.object(runtime, 'DRY_RUN', True), mock.patch.object(verify, 'verify') as run:
            self.assertEqual(verify.maybe_run(self.cfg), 0)
        self.cfg['memory']['auto_verify'] = False
        self.assertEqual(verify.maybe_run(self.cfg), 0)
        run.assert_not_called()

    def test_poll_calls_verifier_only_when_idle(self):
        self.jira.issues = []
        with mock.patch.object(pipeline.memory_verify, 'maybe_run') as run, \
                mock.patch.object(pipeline, 'explore_idle'), mock.patch.object(pipeline.retro, 'maybe_run'):
            pipeline.poll_once(self.cfg, 60)
        run.assert_called_once_with(self.cfg)

    def test_nonzero_cli_and_invalid_json_are_not_accepted(self):
        with mock.patch.object(verify, 'run_cli', return_value=(1, 'bad')), self.assertRaises(RuntimeError):
            verify.ask(self.cfg, self.work, 'MEMORY-X', 'prompt', 'plan')
        with self.assertRaises(ValueError):
            verify.parse('no structured result')

    def test_standard_runners_are_discovered_from_project_files(self):
        cases = [('pom.xml', '', 'mvn'), ('build.gradle.kts', '', 'gradle'),
                 ('package.json', '{"scripts":{"test":"vitest run"}}', 'npm'),
                 ('go.mod', 'module example', 'go'), ('Cargo.toml', '', 'cargo'),
                 ('pyproject.toml', '[tool.pytest.ini_options]', sys.executable)]
        for name, text, runner in cases:
            with self.subTest(name=name):
                path = os.path.join(self.work, name)
                with open(path, 'w') as f:
                    f.write(text)
                commands = verify.test_commands(self.cfg, self.work)
                self.assertEqual(commands[0][0], runner)
                if name == 'pyproject.toml':
                    self.assertIn('pytest', commands[0])
                os.unlink(path)

    def test_explicit_test_commands_override_discovery(self):
        self.cfg['memory']['verify_commands'] = []
        self.assertEqual(verify.test_commands(self.cfg, self.work), [])
        self.cfg['memory']['verify_commands'] = ['make test']
        with self.assertRaises(ValueError):
            verify.test_commands(self.cfg, self.work)
