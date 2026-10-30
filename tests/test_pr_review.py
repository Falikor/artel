"""Idle PR handling: exact scope, evidence, concurrency and crash reconciliation."""
import copy
import json
import os
from pathlib import Path
import time
import ssl
import urllib.request
from unittest import mock
import unittest

from helpers import DaemonTestCase, git
from jira_gigacode import pr_review as pr, runtime, retry_control, routing
from jira_gigacode.bitbucket_client import Client, BitbucketError, NoRedirect


class ClientTest(unittest.TestCase):
    def client(self):
        return Client({'bitbucket': {'url': 'https://bitbucket.invalid/bitbucket', 'project': 'A',
            'repo': 'repo', 'token': 'secret', 'bot_user': 'robot'}})

    def test_pagination_and_context_path(self):
        c = self.client()
        self.assertEqual(c.path, '/rest/api/1.0/projects/A/repos/repo')
        with mock.patch.object(c, 'request', side_effect=[
                {'values': [1], 'isLastPage': False, 'nextPageStart': 7},
                {'values': [2], 'isLastPage': True}]) as request:
            self.assertEqual(list(c.pages('/pull-requests', state='OPEN')), [1, 2])
            self.assertEqual(request.call_args.kwargs['params']['start'], 7)

    def test_invalid_pagination_fails_closed(self):
        c = self.client()
        with mock.patch.object(c, 'request', return_value={'values': [], 'isLastPage': False, 'nextPageStart': 0}):
            with self.assertRaises(BitbucketError):
                list(c.pages('/pull-requests'))

    def test_reply_is_threaded_and_has_no_retry(self):
        c = self.client()
        with mock.patch.object(c, 'request', side_effect=TimeoutError) as request:
            with self.assertRaises(TimeoutError):
                c.reply(3, 4, 'Обоснование')
            request.assert_called_once_with('POST', '/pull-requests/3/comments', {'text': 'Обоснование', 'parent': {'id': 4}})

    def test_nested_activity_is_not_processed_as_a_second_thread(self):
        c = self.client()
        reply = {'id': 2, 'text': 'reply'}
        with mock.patch.object(c, 'pages', return_value=iter([
                {'comment': {'id': 1, 'comments': [reply]}}, {'comment': reply}])), \
                mock.patch.object(c, 'thread', return_value={'id': 1}) as thread:
            self.assertEqual(c.threads(3), [{'id': 1}])
            thread.assert_called_once_with(3, 1)

    def test_redirects_are_not_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid'))

    def test_tls_default_matches_jira_without_ca(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            c = self.client()
        ctx = next(h._context for h in c.opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
        self.assertFalse(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)

    def test_verified_tls_can_use_system_store(self):
        with mock.patch.dict(os.environ, {'BITBUCKET_VERIFY_SSL': 'true'}, clear=True):
            c = self.client()
        ctx = next(h._context for h in c.opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    def test_explicit_ca_keeps_verification_and_false_ignores_ca(self):
        context_factory = ssl.create_default_context
        for verify in (None, 'false'):
            env = {'BITBUCKET_CA_FILE': '/corporate/ca.pem'}
            if verify is not None:
                env['BITBUCKET_VERIFY_SSL'] = verify
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch('jira_gigacode.bitbucket_client.ssl.create_default_context',
                               return_value=context_factory()) as factory:
                c = self.client()
                factory.assert_called_once_with(cafile='/corporate/ca.pem' if verify is None else None)
                ctx = next(h._context for h in c.opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
                self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED if verify is None else ssl.CERT_NONE)


class PRFlowTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.branch = 'feature/ai_team/T-1'
        git(self.work, 'checkout', '-qb', self.branch)
        Path(self.work, 'module.py').write_text('answer = 42  # initial contract\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'T-1 initial')
        git(self.work, 'push', '-q', 'origin', self.branch)
        self.head = git(self.work, 'rev-parse', 'HEAD')
        self.base = git(self.work, 'rev-parse', 'origin/develop')
        self.cfg = self.config(self.work)
        self.cfg['bitbucket'] = {'enabled': True, 'url': 'https://bitbucket.invalid', 'project': 'A',
                                'repo': 'repo', 'token': 'x', 'bot_user': 'robot'}
        self.entry = {'issue': 'T-1', 'branch': self.branch, 'head': self.head,
                      'repo': self.work, 'service': None, 'at': time.time()}
        repository = {'id': 10, 'slug': 'repo', 'project': {'key': 'A'},
                      'links': {'clone': [{'href': git(self.work, 'remote', 'get-url', 'origin')}]}}
        self.pull = {'id': 2, 'state': 'OPEN',
                     'fromRef': {'id': 'refs/heads/' + self.branch, 'latestCommit': self.head, 'repository': repository},
                     'toRef': {'id': 'refs/heads/develop', 'latestCommit': self.base, 'repository': repository}}
        self.thread = {'id': 7, 'version': 0, 'text': 'Нужно исправить значение', 'author': {'name': 'human'}, 'comments': []}
        self.client = mock.Mock(url='https://bitbucket.invalid', project='A', repo='repo', bot='robot')
        self.client.pr.side_effect = lambda _: copy.deepcopy(self.pull)
        self.client.thread.side_effect = lambda *_: copy.deepcopy(self.thread)
        self.state = {}
        self.path = Path(self.tmp, 'pr.json')
        logs = mock.patch.object(pr, 'LOGS_DIR', self.tmp)
        logs.start(); self.addCleanup(logs.stop)
        self.decision = {'action': 'object', 'reason': 'Значение согласовано с текущим контрактом.',
                         'citations': [{'path': 'module.py', 'quote': 'answer = 42  # initial contract'}]}

    def process(self):
        return pr.process_thread(self.cfg, self.client, self.work, self.entry, self.pull,
                                 self.thread, self.state, self.path)

    def test_objection_is_once_per_human_revision(self):
        with mock.patch.object(pr, 'assess', return_value=self.decision) as assess:
            self.assertTrue(self.process())
            self.assertFalse(self.process())
            self.client.reply.assert_called_once()
            self.thread['comments'].append({'id': 8, 'text': 'Новый аргумент', 'author': {'name': 'human'}})
            self.assertTrue(self.process())
            self.assertEqual(assess.call_count, 2)

    def test_own_reply_does_not_change_revision(self):
        before = pr.human_context(self.thread, 'robot')
        self.thread['comments'].append({'id': 8, 'author': {'name': 'robot'}, 'text': 'ответ'})
        self.thread.update(version=1, updatedDate=123456)
        self.assertEqual(before, pr.human_context(self.thread, 'robot'))

    def test_remote_marker_recovers_lost_local_state(self):
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            self.process()
        text = self.client.reply.call_args.args[2]
        self.thread['comments'].append({'id': 8, 'author': {'name': 'robot'}, 'text': text})
        self.state = {}
        self.client.reply.reset_mock()
        with mock.patch.object(pr, 'assess') as assess:
            self.assertFalse(self.process())
            assess.assert_not_called()
            self.client.reply.assert_not_called()

    def test_post_timeout_is_not_blindly_retried(self):
        self.client.reply.side_effect = TimeoutError
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            with self.assertRaises(TimeoutError): self.process()
            self.state = json.loads(self.path.read_text())
            self.assertFalse(self.process())
            self.client.reply.assert_called_once()

    def test_deferred_decision_is_visible_in_jira_and_updated_in_place(self):
        with mock.patch.object(pr, 'assess', return_value={'action': 'defer', 'reason': 'Нужно уточнить новый контракт API.'}):
            self.assertTrue(self.process())
            self.assertFalse(self.process())
        self.client.reply.assert_not_called()
        self.assertEqual(len(self.jira.posted_comments), 1)
        body = self.jira.comments[-1]['body']
        self.assertIn('Нужно уточнить новый контракт API.', body)
        self.assertIn('/pull-requests/2/overview?commentId=7', body)
        self.assertIn('python artel.py pr retry t', body)
        self.assertIn(next(iter(self.state['entries'])), body)
        self.thread['text'] += ' Контракт согласован.'
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            self.assertTrue(self.process())
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertIn('ожидание снято', self.jira.comments[-1]['body'])
        self.assertTrue(all(r['status'] == 'done' for r in self.state['entries'].values()))

    def test_ambiguous_reply_is_immediately_visible_in_jira_then_resolves(self):
        self.client.reply.side_effect = TimeoutError('lost response')
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            with self.assertRaises(TimeoutError):
                self.process()
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertIn('sending', self.jira.comments[-1]['body'])
        self.assertIn('Проверьте, появился ли ответ', self.jira.comments[-1]['body'])
        self.thread['comments'].append({'id': 11, 'text': self.client.reply.call_args.args[2],
                                       'author': {'name': 'robot'}})
        self.assertFalse(self.process())
        self.client.reply.assert_called_once()
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertIn('ожидание снято', self.jira.comments[-1]['body'])

    def test_changed_head_prevents_reply(self):
        changed = copy.deepcopy(self.pull)
        changed['fromRef']['latestCommit'] = 'a' * 40
        self.client.pr.side_effect = lambda _: changed
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            with self.assertRaises(ValueError): self.process()
        self.client.reply.assert_not_called()

    def test_changed_comment_prevents_reply(self):
        changed = dict(self.thread, text='Новое замечание')
        self.client.thread.side_effect = lambda *_: changed
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            with self.assertRaises(ValueError): self.process()
        self.client.reply.assert_not_called()

    def test_excluded_issue_is_not_sent_to_model(self):
        retry_control.decide(retry_control.path_for(self.tmp, 't'), 'T-1', 'block')
        with mock.patch.object(pr, 'assess') as assess:
            self.assertFalse(self.process())
            assess.assert_not_called()

    def test_fork_wrong_branch_closed_and_wrong_remote_are_rejected(self):
        for mode in ('fork', 'branch', 'closed', 'remote'):
            pull = copy.deepcopy(self.pull)
            if mode == 'fork': pull['fromRef']['repository']['id'] = 11; pull['toRef']['repository'] = dict(pull['toRef']['repository'], id=10)
            if mode == 'branch': pull['fromRef']['id'] = 'refs/heads/other'
            if mode == 'closed': pull['state'] = 'MERGED'
            if mode == 'remote': pull['fromRef']['repository']['links']['clone'] = []
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                pr.check_pr(self.client, pull, self.entry, self.work)

    def test_defer_has_no_remote_effect(self):
        with mock.patch.object(pr, 'assess', return_value={'action': 'defer', 'reason': 'Нужны требования'}):
            self.assertTrue(self.process())
            self.assertFalse(self.process())
        self.client.reply.assert_not_called()

    def test_fix_pushes_without_force_and_survives_lost_reply(self):
        Path(self.work, 'module.py').write_text('answer = 43\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'fix')
        new = git(self.work, 'rev-parse', 'HEAD')
        def current(_):
            pull = copy.deepcopy(self.pull)
            pull['fromRef']['latestCommit'] = git(self.work, 'ls-remote', 'origin', 'refs/heads/' + self.branch).split()[0]
            return pull
        self.client.pr.side_effect = current
        self.client.reply.side_effect = TimeoutError
        with mock.patch.object(pr, 'assess', return_value=dict(self.decision, action='fix')), \
                mock.patch.object(pr, 'fix', return_value=(new, 'Исправлено')):
            with self.assertRaises(TimeoutError): self.process()
        self.assertEqual(current(2)['fromRef']['latestCommit'], new)
        self.assertEqual(next(iter(self.state['entries'].values()))['status'], 'sending')
        self.assertFalse(self.process())
        self.assertEqual(git(self.work, 'rev-parse', 'origin/develop'), self.base)

    def test_service_bitbucket_config_is_merged(self):
        cfg = routing.config_for_service(self.cfg, {'name': 'web', 'repo_path': '/web', 'bitbucket': {'repo': 'web'}})
        self.assertEqual(cfg['bitbucket']['repo'], 'web')
        self.assertEqual(cfg['bitbucket']['url'], self.cfg['bitbucket']['url'])

    def test_disabled_and_dry_run_do_not_use_network(self):
        self.cfg['bitbucket']['enabled'] = False
        with mock.patch.object(pr, 'Client') as client:
            pr.maybe_run(self.cfg)
            self.cfg['bitbucket']['enabled'] = True
            runtime.DRY_RUN = True
            pr.maybe_run(self.cfg)
            client.assert_not_called()

    def test_real_fix_runs_tests_and_commits_only_tested_patch(self):
        import sys
        self.cfg['bitbucket']['test_commands'] = [[sys.executable, '-c',
            'from pathlib import Path; assert "43" in Path("module.py").read_text(); Path("test-output.log").write_text("temporary")']]
        def agent(config, wt, issue, prompt, phase):
            if phase == 'fix':
                Path(wt, 'module.py').write_text('answer = 43\n')
                return {'action': 'fixed', 'reason': 'Исправлено'}
            return {'accept': True}
        with mock.patch.object(pr, 'ask', side_effect=agent):
            commit, _ = pr.fix(self.cfg, self.work, self.entry, self.head, {}, self.decision, 'a' * 64)
        self.assertEqual(git(self.work, 'show', commit + ':module.py'), 'answer = 43')
        self.assertNotIn('test-output.log', git(self.work, 'ls-tree', '-r', '--name-only', commit))
        self.assertEqual(git(self.work, 'rev-parse', 'HEAD'), self.head)
        self.assertEqual(git(self.work, 'ls-remote', 'origin', self.branch).split()[0], self.head)

    def test_failed_tests_prevent_prepared_commit(self):
        import sys
        self.cfg['bitbucket']['test_commands'] = [[sys.executable, '-c', 'raise SystemExit(1)']]
        def agent(config, wt, issue, prompt, phase):
            Path(wt, 'module.py').write_text('answer = 43\n')
            return {'action': 'fixed'}
        with mock.patch.object(pr, 'ask', side_effect=agent), self.assertRaisesRegex(ValueError, 'Не прошла'):
            pr.fix(self.cfg, self.work, self.entry, self.head, {}, self.decision, 'a' * 64)
        self.assertEqual(git(self.work, 'for-each-ref', 'refs/artel-pr-review'), '')

    def test_objection_without_verified_citation_is_rejected(self):
        with mock.patch.object(pr, 'ask', return_value=dict(self.decision, citations=[
                {'path': 'module.py', 'quote': 'this text is not in the repository'}])), self.assertRaises(ValueError):
            pr.assess(self.cfg, self.work, self.entry, self.head, {})

    def test_readonly_assessor_modification_is_rejected(self):
        def agent(config, wt, issue, prompt, phase):
            Path(wt, 'module.py').write_text('changed')
            return self.decision
        with mock.patch.object(pr, 'ask', side_effect=agent), self.assertRaisesRegex(ValueError, 'изменил'):
            pr.assess(self.cfg, self.work, self.entry, self.head, {})

    def test_idle_uses_delivery_ledger_and_persists_interval(self):
        self.client.prs.return_value = [self.pull]
        self.client.threads.return_value = [self.thread]
        with mock.patch.object(pr, 'Client', return_value=self.client), \
                mock.patch.object(pr.retro, 'load_deliveries', return_value={'T-1': self.entry}), \
                mock.patch.object(pr, 'assess_batch', return_value={7: dict(self.decision, id=7)}):
            self.assertEqual(pr.maybe_run(self.cfg), 1)
            self.assertEqual(pr.maybe_run(self.cfg), 0)
        self.client.reply.assert_called_once()

    def setup_batch(self):
        self.other = {'id': 9, 'text': 'Проверь также второй случай', 'author': {'name': 'reviewer'}, 'comments': []}
        self.batch_threads = [self.thread, self.other]
        self.client.threads.side_effect = lambda _: copy.deepcopy(self.batch_threads)
        def get_comment(_, cid):
            return next(copy.deepcopy(c) for t in self.batch_threads for c in pr.flatten(t) if c['id'] == cid)
        self.client.thread.side_effect = get_comment

    def batch(self):
        return pr.process_batch(self.cfg, self.client, self.work, self.entry, self.client.pr(2),
                                self.client.threads(2), self.state, self.path)

    def test_batch_assesses_all_and_replies_to_each_including_nested(self):
        self.setup_batch()
        nested = {'id': 10, 'text': 'Ещё замечание внутри обсуждения', 'author': {'name': 'human'}}
        self.thread['comments'].append(nested)
        decisions = {i: dict(self.decision, id=i, reason=f'Обоснование для замечания {i}: контракт уже соблюдён.') for i in (7, 9, 10)}
        with mock.patch.object(pr, 'assess_batch', return_value=decisions) as assess:
            self.assertTrue(self.batch())
            self.assertFalse(self.batch())
        assess.assert_called_once()
        self.assertEqual({p['id'] for p in assess.call_args.args[4]['pending']}, {7, 9, 10})
        self.assertEqual({c.args[1] for c in self.client.reply.call_args_list}, {7, 9, 10})
        for call in self.client.reply.call_args_list:
            self.assertIn(f'замечания {call.args[1]}:', call.args[2])

    def test_batch_requires_one_model_decision_per_comment(self):
        context = {'pending': [{'id': 7}, {'id': 9}]}
        with mock.patch.object(pr, 'ask', return_value={'decisions': [dict(self.decision, id=7)]}), \
                self.assertRaisesRegex(ValueError, 'Не все замечания'):
            pr.assess_batch(self.cfg, self.work, self.entry, self.head, context)

    def test_multiple_disputed_comments_are_gathered_in_one_jira_notice(self):
        self.setup_batch()
        decisions = {i: {'id': i, 'action': 'defer', 'reason': f'Нужно решение по замечанию {i}.'} for i in (7, 9)}
        with mock.patch.object(pr, 'assess_batch', return_value=decisions):
            self.assertTrue(self.batch())
            self.assertFalse(self.batch())
        self.assertEqual(len(self.jira.posted_comments), 1)
        for i in (7, 9):
            self.assertIn(f'Нужно решение по замечанию {i}.', self.jira.comments[-1]['body'])
        self.client.reply.assert_not_called()

    def test_jira_outage_does_not_change_pr_decision_or_retry_post(self):
        self.jira.down = True
        self.client.reply.side_effect = TimeoutError('lost response')
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            with self.assertRaises(TimeoutError):
                self.process()
        self.assertEqual(next(iter(self.state['entries'].values()))['status'], 'sending')
        self.jira.down = False
        with mock.patch.object(pr.notifications.time, 'time', return_value=time.time() + 600):
            self.assertEqual(pr.notifications.flush(self.cfg, logs_dir=self.tmp), 1)
        self.client.reply.assert_called_once()
        self.assertIn('sending', self.jira.comments[-1]['body'])

    def test_batch_real_combined_fix_tests_push_and_separate_replies(self):
        import sys
        self.setup_batch()
        self.cfg['bitbucket']['test_commands'] = [[sys.executable, '-c',
            'from pathlib import Path; assert "43" in Path("module.py").read_text(); assert Path("extra.py").exists()']]
        def current(_):
            pull = copy.deepcopy(self.pull)
            pull['fromRef']['latestCommit'] = git(self.work, 'ls-remote', 'origin', self.branch).split()[0]
            return pull
        self.client.pr.side_effect = current
        def agent(config, wt, issue, prompt, phase):
            if phase == 'assess-batch':
                return {'decisions': [dict(self.decision, action='fix', id=i) for i in (7, 9)]}
            if phase == 'fix':
                Path(wt, 'module.py').write_text('answer = 43\n')
                Path(wt, 'extra.py').write_text('extra = True\n')
                return {'action': 'fixed', 'replies': [
                    {'id': 7, 'reason': 'Исправлено значение результата: теперь оно равно 43.'},
                    {'id': 9, 'reason': 'Добавлена обработка второго случая в отдельном модуле.'}]}
            return {'accept': True}
        with mock.patch.object(pr, 'ask', side_effect=agent) as ask, mock.patch.object(pr, 'git', wraps=pr.git) as calls:
            self.assertTrue(self.batch())
        self.assertEqual(sum(c.args[-1] == 'fix' for c in ask.call_args_list), 1)
        self.assertEqual(sum(c.args[1] == 'push' for c in calls.call_args_list), 1)
        new_head = current(2)['fromRef']['latestCommit']
        self.assertNotEqual(new_head, self.head)
        self.assertEqual(git(self.work, 'show', new_head + ':module.py'), 'answer = 43')
        self.assertEqual(self.client.reply.call_count, 2)
        for call in self.client.reply.call_args_list:
            self.assertIn(new_head, call.args[2])
        self.assertEqual(git(self.work, 'rev-parse', 'HEAD'), self.head)
        self.assertEqual(git(self.work, 'for-each-ref', 'refs/artel-pr-review'), '')

    def test_batch_post_timeout_does_not_stop_other_replies_or_regenerate(self):
        self.setup_batch()
        self.client.reply.side_effect = [TimeoutError('uncertain'), {}]
        decisions = {i: dict(self.decision, id=i) for i in (7, 9)}
        with mock.patch.object(pr, 'assess_batch', return_value=decisions) as assess:
            self.assertTrue(self.batch())
            self.state = json.loads(self.path.read_text())
            self.batch()
            assess.assert_called_once()
        self.assertEqual(self.client.reply.call_count, 2)
        self.assertEqual({row['status'] for row in self.state['entries'].values()}, {'sending', 'done'})

    def test_batch_changed_comment_prevents_any_publication(self):
        self.setup_batch()
        def assess(*args):
            self.other['text'] = 'Изменённая постановка замечания'
            return {i: dict(self.decision, id=i) for i in (7, 9)}
        with mock.patch.object(pr, 'assess_batch', side_effect=assess):
            self.batch()
        self.client.reply.assert_not_called()
        self.assertTrue(all(row.get('error') for row in self.state['entries'].values()))

    def test_default_quota_limits_prs_not_comments(self):
        self.setup_batch()
        self.client.prs.return_value = [self.pull]
        with mock.patch.object(pr, 'Client', return_value=self.client), \
                mock.patch.object(pr.retro, 'load_deliveries', return_value={'T-1': self.entry}), \
                mock.patch.object(pr, 'assess_batch', return_value={i: dict(self.decision, id=i) for i in (7, 9)}):
            self.assertEqual(pr.maybe_run(self.cfg), 1)
        self.assertEqual(self.client.reply.call_count, 2)

    def test_batch_objections_are_independently_checked_and_deferred_per_id(self):
        self.setup_batch()
        def agent(config, wt, issue, prompt, phase):
            if phase == 'assess-batch':
                return {'decisions': [dict(self.decision, id=i) for i in (7, 9)]}
            return {'decisions': [{'id': 7, 'accept': True}, {'id': 9, 'accept': False}]}
        with mock.patch.object(pr, 'ask', side_effect=agent) as ask:
            self.batch()
        self.assertEqual([c.args[-1] for c in ask.call_args_list], ['assess-batch', 'judge-objections'])
        self.client.reply.assert_called_once()
        self.assertEqual(self.client.reply.call_args.args[1], 7)
        self.assertEqual({r['comment']: r['status'] for r in self.state['entries'].values()}, {7: 'done', 9: 'deferred'})

    def test_batch_remote_markers_survive_lost_local_journal(self):
        self.setup_batch()
        def reply(_, cid, text):
            comment = next(t for t in self.batch_threads if t['id'] == cid)
            comment['comments'].append({'id': cid + 100, 'text': text, 'author': {'name': 'robot'}})
        self.client.reply.side_effect = reply
        with mock.patch.object(pr, 'assess_batch', return_value={i: dict(self.decision, id=i) for i in (7, 9)}) as assess:
            self.batch()
            self.state = {}
            self.assertFalse(self.batch())
            assess.assert_called_once()
        self.assertEqual(self.client.reply.call_count, 2)

    def test_batch_resume_after_push_keeps_shared_commit(self):
        self.setup_batch()
        Path(self.work, 'module.py').write_text('answer = 43\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'combined fix')
        commit = git(self.work, 'rev-parse', 'HEAD')
        lost = [False]
        def current(_):
            pull = copy.deepcopy(self.pull)
            head = git(self.work, 'ls-remote', 'origin', self.branch).split()[0]
            if head == commit and not lost[0]:
                lost[0] = True
                raise TimeoutError('lost response after push')
            pull['fromRef']['latestCommit'] = head
            return pull
        self.client.pr.side_effect = current
        with mock.patch.object(pr, 'assess_batch', return_value={i: dict(self.decision, action='fix', id=i) for i in (7, 9)}) as assess, \
                mock.patch.object(pr, 'fix', return_value=(commit, {7: 'Первое исправление', 9: 'Второе исправление'})) as fix:
            self.batch()
            self.state = json.loads(self.path.read_text())
            for row in self.state['entries'].values():
                row.pop('retry_after', None)
            self.batch()
            assess.assert_called_once()
            fix.assert_called_once()
        self.assertEqual({r['status'] for r in self.state['entries'].values()}, {'done'})
        self.assertEqual(self.client.reply.call_count, 2)
        self.assertEqual(current(2)['fromRef']['latestCommit'], commit)

    def test_legacy_mode_remains_opt_in(self):
        self.setup_batch()
        self.cfg['bitbucket']['batch_comments'] = False
        self.client.prs.return_value = [self.pull]
        with mock.patch.object(pr, 'Client', return_value=self.client), \
                mock.patch.object(pr.retro, 'load_deliveries', return_value={'T-1': self.entry}), \
                mock.patch.object(pr, 'assess', return_value=self.decision), mock.patch.object(pr, 'assess_batch') as batch:
            self.assertEqual(pr.maybe_run(self.cfg), 1)
            batch.assert_not_called()
        self.client.reply.assert_called_once()

    def test_legacy_completed_thread_is_not_reprocessed_on_upgrade(self):
        with mock.patch.object(pr, 'assess', return_value=self.decision):
            self.process()
        self.setup_batch()
        self.batch_threads = [self.thread]
        with mock.patch.object(pr, 'assess_batch') as assess:
            self.assertFalse(self.batch())
            assess.assert_not_called()

    def test_objection_invalidated_by_combined_fix_is_not_published(self):
        self.setup_batch()
        Path(self.work, 'module.py').write_text('answer = 43\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'combined fix')
        commit = git(self.work, 'rev-parse', 'HEAD')
        def current(_):
            pull = copy.deepcopy(self.pull)
            pull['fromRef']['latestCommit'] = git(self.work, 'ls-remote', 'origin', self.branch).split()[0]
            return pull
        self.client.pr.side_effect = current
        with mock.patch.object(pr, 'assess_batch', return_value={
                7: dict(self.decision, action='fix', id=7), 9: dict(self.decision, id=9)}), \
                mock.patch.object(pr, 'fix', return_value=(commit, {7: 'Исправлено значение результата'})), \
                mock.patch.object(pr, 'ask', return_value={'decisions': [{'id': 9, 'accept': True}]}):
            self.batch()
        self.client.reply.assert_called_once()
        self.assertEqual(self.client.reply.call_args.args[1], 7)
        self.assertEqual({r['comment']: r['status'] for r in self.state['entries'].values()}, {7: 'done', 9: 'deferred'})

    def test_legacy_failed_record_can_be_retried_as_batch(self):
        self.setup_batch()
        context = pr.human_context(self.thread, self.client.bot)
        key = pr.digest([self.client.url, self.client.project, self.client.repo, 2, 7, context])
        self.state = {'entries': {key: {'issue': 'T-1', 'pr': 2, 'comment': 7, 'error': 'old failure'}}}
        with mock.patch.object(pr, 'assess_batch', return_value={i: dict(self.decision, id=i) for i in (7, 9)}):
            self.batch()
        self.assertEqual(self.client.reply.call_count, 2)
        self.assertTrue(self.state['entries'][key]['batch'])

    def test_cli_retry_preserves_prepared_patch(self):
        state_path = Path(self.tmp, 't-pr-review-test.json')
        pr.save(state_path, {'entries': {'abc': {'status': 'sending', 'commit': self.head, 'retry_after': time.time() + 99}}})
        self.assertEqual(pr.command(['retry', 't', 'abc']), 0)
        row = json.loads(state_path.read_text())['entries']['abc']
        self.assertEqual(row['status'], 'prepared')
        self.assertEqual(row['commit'], self.head)
        self.assertNotIn('retry_after', row)

    def test_supervisor_pr_command_dispatch(self):
        from jira_gigacode import supervisor
        with mock.patch.object(pr, 'command', return_value=0) as command:
            self.assertEqual(supervisor.main(['pr', 'list', 't']), 0)
            command.assert_called_once_with(['list', 't'])

    def test_crash_after_push_before_post_reconciles_without_regeneration(self):
        Path(self.work, 'module.py').write_text('answer = 43\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'fix')
        commit = git(self.work, 'rev-parse', 'HEAD')
        calls = [0]
        def current(_):
            calls[0] += 1
            if calls[0] == 2:
                raise TimeoutError('lost response after push')
            pull = copy.deepcopy(self.pull)
            pull['fromRef']['latestCommit'] = git(self.work, 'ls-remote', 'origin', self.branch).split()[0]
            return pull
        self.client.pr.side_effect = current
        with mock.patch.object(pr, 'assess', return_value=dict(self.decision, action='fix')), \
                mock.patch.object(pr, 'fix', return_value=(commit, 'Исправлено')):
            with self.assertRaises(TimeoutError): self.process()
        self.assertEqual(next(iter(self.state['entries'].values()))['status'], 'prepared')
        self.pull['fromRef']['latestCommit'] = commit
        with mock.patch.object(pr, 'assess') as assess, mock.patch.object(pr, 'fix') as fix:
            self.assertTrue(self.process())
            assess.assert_not_called()
            fix.assert_not_called()
        self.client.reply.assert_called_once()

    def test_concurrent_human_commit_is_not_overwritten(self):
        origin = git(self.work, 'remote', 'get-url', 'origin')
        other = os.path.join(self.tmp, 'other')
        git(self.tmp, 'clone', '-q', origin, other)
        git(other, 'checkout', '-q', self.branch)
        Path(other, 'human.py').write_text('human = True\n')
        git(other, 'add', '.')
        git(other, 'commit', '-qm', 'human update')
        human = git(other, 'rev-parse', 'HEAD')
        Path(self.work, 'module.py').write_text('answer = 43\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'agent fix')
        commit = git(self.work, 'rev-parse', 'HEAD')
        original_git = pr.git
        def race(repo, *args):
            if args[0] == 'push':
                git(other, 'push', '-q', 'origin', self.branch)
            return original_git(repo, *args)
        with mock.patch.object(pr, 'assess', return_value=dict(self.decision, action='fix')), \
                mock.patch.object(pr, 'fix', return_value=(commit, 'Исправлено')), \
                mock.patch.object(pr, 'git', side_effect=race):
            with self.assertRaises(RuntimeError): self.process()
        self.assertEqual(git(self.work, 'ls-remote', 'origin', self.branch).split()[0], human)
        self.client.reply.assert_not_called()
