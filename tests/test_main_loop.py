"""Основной цикл: проход опроса, обработка задачи, повтор перевода, кулдаун, ожидание."""
import contextlib
import io
import os
from unittest import mock

from helpers import DaemonTestCase
from jira_gigacode import cli, pipeline, retry, retry_control, runtime

BR = 'feature/ai_team/T-1'


class PollOnceTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)

    def poll(self, mode):
        with mock.patch.dict(os.environ, {'FAKE_MODE': mode}), contextlib.redirect_stdout(io.StringIO()):
            pipeline.poll_once(self.cfg, retry_cooldown_sec=3600)

    def test_issue_is_processed_end_to_end(self):
        self.poll('marker')
        self.assertIn('feature.py', self.remote_files(self.work, BR))
        self.assertEqual(self.jira.status, 'Ревью')
        self.assertTrue(any('Задача реализована' in c for c in self.jira.posted_comments))

    def test_no_issues(self):
        self.jira.issues = []
        self.poll('fail')  # CLI не должен запускаться вовсе
        self.assertEqual(self.jira.posted_comments, [])

    def test_pending_transition_skips_generation(self):
        retry.pending_transition_add('T-1')
        retry_control.decide(retry.control_path(), 'T-1', 'resume')
        self.poll('fail')  # если бы демон запустил генерацию, она бы упала
        self.assertEqual(self.jira.status, 'Ревью')
        self.assertFalse(retry.pending_transition_active('T-1'))
        self.assertIn('выполнен только перевод', self.jira.posted_comments[-1])
        self.assertIsNone(self.remote_files(self.work, BR))

    def test_failures_lead_to_cooldown_and_single_comment(self):
        self.poll('fail')
        self.assertFalse(retry.retry_blocked('T-1'))
        self.poll('fail')
        self.assertTrue(retry.retry_blocked('T-1'))
        failed = [c for c in self.jira.posted_comments if 'не смог реализовать' in c]
        self.assertEqual(len(failed), 1)
        # На кулдауне задача пропускается: генерация не запускается
        with mock.patch.object(pipeline, 'process_issue') as process:
            self.poll('marker')
        process.assert_not_called()

    def test_stuck_transition_comment_is_not_duplicated_by_cooldown(self):
        self.jira.can_transition = False
        self.poll('marker')       # код запушен, перевод не удался → «нужна помощь»
        self.poll('fail')         # повтор только перевода, снова неудача → кулдаун
        self.assertTrue(retry.retry_blocked('T-1'))
        self.assertEqual(sum('Нужна помощь' in c for c in self.jira.posted_comments), 1)
        self.assertFalse(any('не смог реализовать' in c for c in self.jira.posted_comments))

    def test_changed_config_requires_permission(self):
        self.poll('fail')
        self.cfg.setdefault('general', {})['poll_interval_seconds'] = 120
        with mock.patch.object(pipeline, 'process_issue') as process:
            self.poll('marker')
            process.assert_not_called()
        self.assertTrue(retry_control.entries(retry.control_path())['T-1']['needs_review'])
        retry_control.decide(retry.control_path(), 'T-1', 'resume')
        self.poll('marker')
        self.assertEqual(self.jira.status, 'Ревью')

    def test_excluded_task_is_skipped_before_routing(self):
        retry_control.decide(retry.control_path(), 'T-1', 'block')
        with mock.patch.object(pipeline, 'resolve_issue_service') as route:
            self.poll('marker')
            route.assert_not_called()
        self.assertIsNone(self.remote_files(self.work, BR))

    def test_resume_does_not_bypass_current_search(self):
        retry_control.decide(retry.control_path(), 'T-1', 'resume')
        self.jira.issues = []
        with mock.patch.object(pipeline, 'process_issue') as process:
            self.poll('marker')
            process.assert_not_called()

    def test_old_pending_transition_waits_for_permission(self):
        retry.pending_transition_add('T-1')
        self.poll('marker')
        self.assertTrue(retry.pending_transition_active('T-1'))
        self.assertIsNone(self.remote_files(self.work, BR))
        self.assertTrue(retry_control.entries(retry.control_path())['T-1']['needs_review'])

    def test_stops_between_issues_on_signal(self):
        self.jira.issues = ['T-1', 'T-2']
        calls = []

        def fake_process(key, config, cooldown):
            calls.append(key)
            runtime.running = False

        with mock.patch.object(pipeline, 'process_issue', fake_process):
            self.poll('marker')
        self.assertEqual(calls, ['T-1'])


class WaitTest(DaemonTestCase):
    def test_poke_interrupts_wait(self):
        class Poked:
            def poke_requested(self):
                return True
        runtime.state = Poked()
        with mock.patch.object(cli.time, 'time', side_effect=[0, 0, 1]):
            cli._sleep_until_next_poll(600)  # вернулся сразу, а не через 600 с

    def test_signal_ends_wait(self):
        runtime.running = False
        cli._sleep_until_next_poll(600)

    def test_signal_handler(self):
        runtime.signal_handler(15, None)
        self.assertFalse(runtime.running)
