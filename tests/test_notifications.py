"""Decision notices survive restarts and never blindly repeat an uncertain POST."""
import copy
import json
from pathlib import Path
from unittest import mock

from helpers import DaemonTestCase
from jira_gigacode import jira_client, notifications as notice, runtime


class NotificationTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(self.tmp)
        self.now = 1000
        clock = mock.patch.object(notice.time, 'time', side_effect=lambda: self.now)
        clock.start(); self.addCleanup(clock.stop)

    def send(self, reason='Изменился конфиг — подтвердите повтор', **kwargs):
        return notice.notify(self.cfg, 'T-1', 'retry-confirmation', reason,
                             action='Подтвердите повтор в панели.', logs_dir=self.tmp, **kwargs)

    def flush(self):
        self.now += notice.RETRY_SECONDS + 1
        return notice.flush(self.cfg, logs_dir=self.tmp)

    def entries(self):
        return json.loads(notice.path_for(self.cfg, self.tmp).read_text())['entries']

    def test_same_notice_survives_restart_without_duplicates(self):
        self.assertTrue(self.send())
        self.assertTrue(self.send())
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(next(iter(self.entries().values()))['status'], 'delivered')

    def test_changed_reason_updates_own_comment(self):
        self.assertTrue(self.send())
        first_id = self.jira.comments[0]['id']
        self.assertTrue(self.send('Предыдущая попытка прервана — подтвердите повтор'))
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertEqual(len(self.jira.updated_comments), 1)
        self.assertEqual(self.jira.comments[0]['id'], first_id)
        self.assertIn('прервана', self.jira.comments[0]['body'])

    def test_recovery_uses_author_and_marker_never_edits_human_copy(self):
        self.assertTrue(self.send())
        body = self.jira.comments[0]['body']
        self.jira.comments = [{'id': '44', 'body': body, 'author': {'key': 'analyst'}, 'issue': 'T-1'}]
        notice.path_for(self.cfg, self.tmp).unlink()
        self.assertTrue(self.send('Новый вопрос'))
        self.assertEqual(self.jira.comments[0]['body'], body)
        self.assertEqual(len(self.jira.posted_comments), 2)
        self.assertFalse(self.jira.updated_comments)

    def test_timeout_after_post_is_reconciled_after_restart(self):
        original = jira_client.jira_request
        def response_lost(method, path, **kwargs):
            result = original(method, path, **kwargs)
            return None if method == 'POST' else result
        with mock.patch.object(jira_client, 'jira_request', side_effect=response_lost):
            self.assertFalse(self.send())
        self.assertTrue(next(iter(self.entries().values()))['post_uncertain'])
        self.assertEqual(self.flush(), 1)
        self.assertEqual(len(self.jira.posted_comments), 1)

    def test_uncertain_post_is_not_blindly_repeated_when_read_is_empty(self):
        original = jira_client.jira_request
        def timeout(method, path, **kwargs):
            return None if method == 'POST' else original(method, path, **kwargs)
        with mock.patch.object(jira_client, 'jira_request', side_effect=timeout) as request:
            self.assertFalse(self.send())
            self.assertEqual(self.flush(), 0)
            self.assertEqual(self.flush(), 0)
            self.assertEqual(sum(c.args[0] == 'POST' for c in request.call_args_list), 1)

    def test_failed_read_remains_pending_and_flush_posts_without_issue_search(self):
        self.jira.down = True
        self.assertFalse(self.send())
        self.assertFalse(next(iter(self.entries().values())).get('post_uncertain'))
        self.jira.down = False
        self.jira.issues = []  # The issue has moved out of the daemon's JQL.
        self.assertEqual(self.flush(), 1)
        self.assertEqual(len(self.jira.posted_comments), 1)

    def test_explicit_rejection_can_retry_but_server_error_is_ambiguous(self):
        original = jira_client.jira_request
        with mock.patch.object(jira_client, 'jira_request', side_effect=lambda method, path, **kwargs:
                {'_http_error': 429} if method == 'POST' else original(method, path, **kwargs)):
            self.assertFalse(self.send())
        self.assertEqual(self.flush(), 1)
        other = copy.deepcopy(self.cfg)
        other['jira']['project'] = 'U'
        with mock.patch.object(jira_client, 'jira_request', side_effect=lambda method, path, **kwargs:
                {'_http_error': 500} if method == 'POST' else original(method, path, **kwargs)):
            self.assertFalse(notice.notify(other, 'U-1', 'blocked', 'Вопрос', logs_dir=self.tmp))
        rows = json.loads(notice.path_for(other, self.tmp).read_text())['entries']
        self.assertTrue(next(iter(rows.values()))['post_uncertain'])

    def test_put_failure_retries_same_comment(self):
        self.assertTrue(self.send())
        with mock.patch.object(jira_client, 'update_comment', return_value=None):
            self.assertFalse(self.send('Изменился вопрос'))
        self.assertEqual(self.flush(), 1)
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertIn('Изменился вопрос', self.jira.comments[0]['body'])

    def test_resolve_updates_and_does_not_create_a_new_comment(self):
        self.assertTrue(notice.resolve(self.cfg, 'T-1', 'absent', logs_dir=self.tmp) is False)
        self.assertTrue(self.send())
        self.assertTrue(notice.resolve(self.cfg, 'T-1', 'retry-confirmation', logs_dir=self.tmp))
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertIn('ожидание снято', self.jira.comments[0]['body'])
        self.assertIn('Изменился конфиг', self.jira.comments[0]['body'])
        self.assertIn('Подтвердите повтор в панели.', self.jira.comments[0]['body'])
        before = len(self.jira.updated_comments)
        self.assertTrue(notice.resolve(self.cfg, 'T-1', 'retry-confirmation', logs_dir=self.tmp))
        self.assertEqual(len(self.jira.updated_comments), before)
        self.assertEqual(self.jira.comments[0]['body'].count('*Исходный запрос*'), 1)
        self.assertTrue(notice.resolve(self.cfg, 'T-1', 'absent', logs_dir=self.tmp))
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertTrue(self.send('Новый вопрос'))
        self.assertNotIn('*Исходный запрос*', self.jira.comments[0]['body'])

    def test_changed_jira_scope_does_not_flush_old_notice(self):
        self.cfg['jira']['ci_id'] = '123'
        self.jira.down = True
        self.assertFalse(self.send())
        self.jira.down = False
        self.cfg['jira']['project'] = 'OTHER'
        self.assertEqual(self.flush(), 0)
        self.assertFalse(self.jira.posted_comments)

    def test_controls_dry_run_and_corrupt_journal_fail_closed(self):
        for field in ('enabled', 'result_comments'):
            self.cfg['jira'][field] = False
            self.assertFalse(self.send())
            self.assertFalse(notice.path_for(self.cfg, self.tmp).exists())
            self.cfg['jira'][field] = True
        with mock.patch.object(runtime, 'DRY_RUN', True):
            self.assertFalse(self.send())
        notice.path_for(self.cfg, self.tmp).write_text('{broken')
        self.assertFalse(self.send())
        self.assertEqual(notice.path_for(self.cfg, self.tmp).read_text(), '{broken')
        self.assertFalse(self.jira.posted_comments)

    def test_tokens_are_redacted_before_storage_and_publication(self):
        self.cfg['jira']['token'] = 'long-secret-value'
        self.assertTrue(self.send('Токен long-secret-value token=abcde https://user:password@host/'))
        stored = notice.path_for(self.cfg, self.tmp).read_text()
        for secret in ('long-secret-value', 'abcde', 'user:password'):
            self.assertNotIn(secret, stored)
            self.assertNotIn(secret, self.jira.posted_comments[0])
