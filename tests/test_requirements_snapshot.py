"""Requirements snapshots fail closed and distinguish human changes from reports."""
import unittest
from unittest import mock

from jira_gigacode import jira_client, requirements_snapshot as snapshot
from jira_gigacode.issue_report import ARTEL_REPORT_TAG


class SnapshotTest(unittest.TestCase):
    fields = {'summary': 'Title', 'description': 'Requirements', 'updated': 'now', 'status': 'TO DO'}
    user = {'key': 'robot'}

    def read(self, comments, *, user=None, ignored=()):
        with mock.patch.object(jira_client, 'fetch_issue_meta', return_value=dict(self.fields)), \
                mock.patch.object(jira_client, 'fetch_comments', return_value=comments), \
                mock.patch.object(jira_client, 'jira_request', return_value=self.user if user is None else user):
            return snapshot.fetch_snapshot('T-1', {}, ignored)

    def test_status_timestamps_and_comment_order_do_not_change_fingerprint(self):
        comments = [{'id': '1', 'body': 'A'}, {'id': '2', 'body': 'B'}]
        first = snapshot.fingerprint(self.fields, comments)
        fields = dict(self.fields, updated='later', status='Done', labels=['new'])
        comments[0]['updated'] = 'later'
        self.assertEqual(first, snapshot.fingerprint(fields, list(reversed(comments))))
        self.assertNotEqual(first, snapshot.fingerprint(dict(fields, description='New'), comments))
        comments[0]['body'] = 'Edited'
        self.assertNotEqual(first, snapshot.fingerprint(fields, comments))

    def test_only_verified_automation_or_known_ids_are_ignored(self):
        comments = [
            {'id': '1', 'body': ARTEL_REPORT_TAG, 'author': self.user},
            {'id': '2', 'body': ARTEL_REPORT_TAG, 'author': {'key': 'analyst'}},
            {'id': '3', 'body': 'Manual comment', 'author': self.user},
            {'id': '4', 'body': 'Known publication without marker'},
        ]
        result = self.read(comments, ignored=['4'])
        self.assertEqual([c['id'] for c in result['comments']], ['2', '3'])
        self.assertEqual(len(result['all_comments']), 4)

    def test_unavailable_thread_or_unknown_identity_is_not_empty_snapshot(self):
        self.assertIsNone(self.read(None))
        self.assertIsNone(self.read([], user={'displayName': 'Robot'}))
        self.assertIsNotNone(self.read([]))

    def test_long_comment_is_bounded_but_hash_uses_full_content(self):
        before = self.read([{'id': '1', 'body': 'A' * 15000 + 'current reply'}])
        after = self.read([{'id': '1', 'body': 'B' * 15000 + 'current reply'}])
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])
        text = snapshot.comments_text(before, limit=100)
        self.assertLessEqual(len(text), 100)
        self.assertTrue(text.endswith('current reply'))
        for limit in (0, 1, 20, 30):
            self.assertLessEqual(len(snapshot.comments_text(before, limit)), limit)


class CommentPaginationTest(unittest.TestCase):
    def fetch(self, responses):
        with mock.patch.object(jira_client, 'jira_request', side_effect=responses) as request:
            result = jira_client.fetch_comments('T-1', {})
            return result, request

    def test_all_pages_are_included(self):
        first = [{'id': str(i), 'body': 'old'} for i in range(100)]
        last = [{'id': '100', 'body': 'new analyst reply'}]
        result, request = self.fetch([
            {'comments': first, 'total': 101, 'startAt': 0},
            {'comments': last, 'total': 101, 'startAt': 100},
        ])
        self.assertEqual(result, first + last)
        self.assertEqual(request.call_args.kwargs['params']['startAt'], 100)

    def test_unavailable_or_incomplete_second_page_fails_closed(self):
        for second in (None, {'comments': [], 'total': 2}, {'comments': 'bad', 'total': 2},
                       {'comments': [{'id': '1'}], 'total': 2},
                       {'comments': [{'id': '2'}], 'total': 3, 'startAt': 1},
                       {'comments': [{'id': '2'}], 'total': 2, 'startAt': 0}):
            with self.subTest(second=second):
                result, _ = self.fetch([{'comments': [{'id': '1'}], 'total': 2}, second])
                self.assertIsNone(result)

    def test_malformed_total_or_comment_fails_closed(self):
        for response in ({'comments': [], 'total': '0'}, {'comments': [], 'total': True},
                         {'comments': [], 'total': -1}, {'comments': [None], 'total': 1},
                         {'comments': [], 'total': None}):
            with self.subTest(response=response):
                result, _ = self.fetch([response])
                self.assertIsNone(result)
