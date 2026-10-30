"""A BLOCKED agent asks Jira for clarification; it is not a failed retry."""
import copy
import json
import os
from pathlib import Path
from unittest import mock

from helpers import DaemonTestCase, git
from jira_gigacode import (blocked, gigacode, issue_report, jira_client, pipeline,
                          requirements_rework, requirements_snapshot, retry, retry_control,
                          runtime)
from jira_gigacode.issue_report import ARTEL_REPORT_TAG
from daemon_state import StateReporter


QUESTION = 'Какой формат отчёта нужен: CSV или JSON?'
OUTPUT = 'Проверил обработчик.\nBLOCKED_QUESTION_START\n' + QUESTION + '\nBLOCKED_QUESTION_END\nCODE_GENERATION_BLOCKED'


class BlockedBase(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(os.path.join(self.tmp, 'repo'))
        self.cfg['explore'] = {'statuses': ['TO DO', 'Backlog']}
        self.jira.ready = 'TO DO'
        self.logs = Path(self.tmp) / 'logs'
        retry.set_pending_path(str(self.logs / 't-pending-transitions.json'))
        # Match Jira's fields projection; the general FakeJira returns updated
        # and status too, which would make our own notice look like a rework edit.
        def request(method, path, **kwargs):
            result = self.jira(method, path, **kwargs)
            if result and (kwargs.get('params') or {}).get('fields') == 'summary,description':
                return {'fields': {k: result['fields'].get(k) for k in ('summary', 'description')}}
            return result
        patch = mock.patch.object(jira_client, 'jira_request', side_effect=request)
        patch.start()
        self.addCleanup(patch.stop)

    def hold(self, snapshot=True):
        current = requirements_snapshot.fetch_snapshot('T-1', self.cfg) if snapshot else None
        return blocked.hold('T-1', self.cfg, OUTPUT, current)

    def reply(self, body='Нужен JSON'):
        self.jira.comments.append({'id': 'analyst-1', 'issue': 'T-1', 'author': {'key': 'analyst'}, 'body': body})

    def poll(self, cfg=None, output=OUTPUT):
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(False, output)) as run, \
                mock.patch.object(pipeline, 'run_post_generation_steps') as deliver, \
                mock.patch.object(pipeline, '_idle'):
            pipeline._poll_once(cfg or self.cfg, 60)
        return run, deliver


class BlockedLifecycleTest(BlockedBase):
    def test_pipeline_posts_question_and_returns_to_backlog_without_failure(self):
        reporter = mock.Mock()
        with mock.patch.object(runtime, 'state', reporter), \
                mock.patch.object(pipeline, '_note_outcome') as outcome:
            run, deliver = self.poll()
        run.assert_called_once()
        deliver.assert_not_called()
        outcome.assert_not_called()
        reporter.finish_issue.assert_not_called()
        reporter.finish_blocked.assert_called_once_with('T-1', QUESTION)
        self.assertEqual(self.jira.status, 'TO DO')
        self.assertEqual(self.jira.transitions_done, ['5'])
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertIn(QUESTION, self.jira.posted_comments[0])
        self.assertNotIn('BLOCKED_QUESTION_START', self.jira.posted_comments[0])
        self.assertNotIn('CODE_GENERATION_BLOCKED', self.jira.posted_comments[0])
        row = retry_control.entries(retry.control_path())['T-1']
        self.assertEqual((row['status'], row['fails'], row['until']), ('blocked', 0, 0))
        self.assertEqual(retry_control.entries(blocked.path_for(self.cfg))['T-1']['status'], 'waiting')

    def test_unchanged_own_reports_and_status_changes_do_not_resume_after_restart(self):
        self.poll()
        retry._RETRY_STATE.clear()
        self.jira.status = 'Backlog'
        self.jira.updated = 'status update'
        self.jira.comments.append({'id': 'notice', 'issue': 'T-1', 'author': self.jira.myself,
                                   'body': ARTEL_REPORT_TAG + '\nОбновлён автоотчёт'})
        for _ in range(2):
            run, _ = self.poll()
            run.assert_not_called()
        self.assertEqual(len(self.jira.posted_comments), 1)

    def test_human_reply_reenters_from_backlog_with_fresh_context(self):
        self.poll()
        self.jira.issues = []
        self.jira.backlog = ['T-1']
        self.reply()
        run, _ = self.poll(output='CODE_GENERATION_FAILED')
        run.assert_called_once()
        cfg = run.call_args.kwargs['config']
        self.assertIn('Нужен JSON', gigacode.task_text_block('T-1', cfg))
        self.assertNotIn(QUESTION, gigacode.task_text_block('T-1', cfg), 'собственный автоотчёт не считается внешним ответом')

    def test_description_change_resumes_but_self_comment_does_not(self):
        self.hold()
        self.assertIsNone(blocked.admit('T-1', self.cfg))
        self.jira.description = 'Новые критерии: выгрузить JSON'
        cfg = blocked.admit('T-1', self.cfg)
        self.assertEqual(cfg['_clarification']['fields']['description'], self.jira.description)

    def test_human_quote_of_automation_marker_still_wakes_daemon(self):
        self.hold()
        self.reply(ARTEL_REPORT_TAG + '\nОтвет на ваш вопрос: JSON')
        self.assertIsNotNone(blocked.admit('T-1', self.cfg))

    def test_config_change_requires_owner_decision_in_addition_to_clarification(self):
        self.hold()
        self.reply()
        changed = copy.deepcopy(self.cfg)
        changed['general']['base_branch'] = 'master'
        self.assertIsNone(blocked.admit('T-1', changed))
        control = retry_control.entries(retry.control_path())['T-1']
        self.assertTrue(control['needs_review'])
        self.assertTrue(any('подтвердите повтор' in c.lower() for c in self.jira.posted_comments))
        retry_control.decide(retry.control_path(), 'T-1', 'resume')
        self.assertIsNotNone(blocked.admit('T-1', changed))

    def test_approval_without_answer_does_not_retry_blocked_work(self):
        self.hold()
        retry_control.decide(retry.control_path(), 'T-1', 'resume')
        self.assertIsNone(blocked.admit('T-1', self.cfg))

    def test_approved_config_is_retained_after_resumed_attempt_fails(self):
        self.poll()
        self.jira.issues = []
        self.jira.backlog = ['T-1']
        self.reply()
        changed = copy.deepcopy(self.cfg)
        changed['general']['base_branch'] = 'master'
        run, _ = self.poll(changed, output='CODE_GENERATION_FAILED')
        run.assert_not_called()
        self.assertTrue(retry_control.entries(retry.control_path())['T-1']['needs_review'])

        retry_control.decide(retry.control_path(), 'T-1', 'resume')
        first, _ = self.poll(changed, output='CODE_GENERATION_FAILED')
        first.assert_called_once()
        control = retry_control.entries(retry.control_path())['T-1']
        self.assertEqual((control['status'], control['fails'], control['approved']), ('failed', 1, False))
        waiting = retry_control.entries(blocked.path_for(changed))['T-1']
        self.assertEqual(waiting['status'], 'resuming')

        # A new daemon process must honour the persisted approval of this config,
        # while treating the next attempt as a regular technical retry.
        retry._RETRY_STATE.clear()
        second, _ = self.poll(changed, output='CODE_GENERATION_FAILED')
        second.assert_called_once()
        control = retry_control.entries(retry.control_path())['T-1']
        self.assertFalse(control['needs_review'])
        self.assertFalse(control['approved'])
        self.assertEqual(control['attempts'], 3)
        self.assertGreater(control['until'], 0, 'две технические ошибки включают обычный кулдаун')

        changed_again = copy.deepcopy(changed)
        changed_again['general']['base_branch'] = 'release'
        self.assertIsNone(blocked.admit('T-1', changed_again))
        self.assertTrue(retry_control.entries(retry.control_path())['T-1']['needs_review'])

    def test_paused_and_excluded_tasks_do_not_resume_after_answer(self):
        self.hold()
        self.reply()
        for action in ('pause', 'block'):
            with self.subTest(action=action):
                retry_control.decide(retry.control_path(), 'T-1', action)
                run, _ = self.poll()
                run.assert_not_called()

    def test_candidate_search_uses_current_project_epic_ci_assignee_and_only_known_keys(self):
        self.hold()
        self.cfg['jira'].update(epic_name='DELIVERY', epic_link_field='Epic Link', ci_field='12345', assignee='robot')
        self.cfg['general']['ci_id'] = 'CI42'
        # Changing instance creates another ledger; move the existing fixture to that instance.
        with retry_control.transaction(blocked.path_for(self.cfg)) as data:
            data['T-1'] = {'status': 'waiting'}
        self.jira.backlog = ['T-1', 'T-999']
        self.assertEqual(blocked.candidate_keys(self.cfg), ['T-1'])
        jql = self.jira.searches[-1]
        for clause in ('project=T', '"Epic Link" = "DELIVERY"', 'cf[12345] = "42"',
                       'assignee = "robot"', '"TO DO"', 'key IN ("T-1")'):
            self.assertIn(clause, jql)

    def test_out_of_current_search_never_runs_even_after_answer(self):
        self.hold()
        self.reply()
        self.jira.issues = self.jira.backlog = []
        run, _ = self.poll()
        run.assert_not_called()

    def test_jira_unavailable_keeps_durable_wait_and_baseline(self):
        self.hold()
        original = retry_control.entries(blocked.path_for(self.cfg))['T-1']
        self.jira.down = True
        self.assertIsNone(blocked.admit('T-1', self.cfg))
        self.assertEqual(retry_control.entries(blocked.path_for(self.cfg))['T-1'], original)

    def test_missing_pre_run_snapshot_baselines_without_automatic_retry(self):
        self.hold(snapshot=False)
        self.assertIsNone(blocked.admit('T-1', self.cfg))
        self.assertIsNone(blocked.admit('T-1', self.cfg))
        self.reply()
        self.assertIsNotNone(blocked.admit('T-1', self.cfg))

    def test_unavailable_transition_keeps_wait_and_explains_recovery_in_same_comment(self):
        self.jira.can_transition = False
        row = self.hold()
        self.assertFalse(row['transition_done'])
        self.assertEqual(self.jira.transitions_done, [])
        self.assertEqual(len(self.jira.posted_comments), 1)
        self.assertIn('Переведите её вручную', self.jira.comments[0]['body'])
        self.assertIsNone(blocked.admit('T-1', self.cfg))

    def test_missing_backlog_status_never_chooses_arbitrary_transition(self):
        self.cfg['explore']['statuses'] = []
        row = self.hold()
        self.assertFalse(row['transition_done'])
        self.assertIn('explore.statuses', self.jira.comments[0]['body'])
        self.assertEqual(self.jira.transitions_done, [])

    def test_rework_blocked_short_circuits_jenkins_and_jira_delivery(self):
        def review(*args, **kwargs):
            issue_report.report_set('T-1', blocked_output=OUTPUT)
            return {'result': 'changes', 'notes': QUESTION}

        with mock.patch.object(pipeline, 'deliver_work', return_value=True), \
                mock.patch.object(pipeline, 'resolve_base_ref', return_value=('origin/develop', None)), \
                mock.patch.object(pipeline.review, 'review_and_rework', side_effect=review), \
                mock.patch.object(pipeline, 'deploy_for_issue') as deploy, \
                mock.patch.object(pipeline, 'transition_with_memory') as transition:
            self.assertFalse(pipeline.run_post_generation_steps('T-1', self.cfg))
        deploy.assert_not_called()
        transition.assert_not_called()

    def test_pipeline_routes_review_blocked_to_question_without_failure_counter(self):
        def post(*args):
            issue_report.report_set('T-1', blocked_output=OUTPUT)
            return False

        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(True, 'CODE_GENERATION_SUCCESS')), \
                mock.patch.object(pipeline, 'run_post_generation_steps', side_effect=post), \
                mock.patch.object(pipeline, '_note_outcome') as outcome:
            self.assertFalse(pipeline.process_issue('T-1', self.cfg, 60))
        outcome.assert_not_called()
        self.assertIn(QUESTION, self.jira.posted_comments[0])

    def test_finished_work_clears_waiting_record(self):
        self.hold()
        self.reply()
        cfg = blocked.admit('T-1', self.cfg)
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(True, 'CODE_GENERATION_SUCCESS')), \
                mock.patch.object(pipeline, 'run_post_generation_steps', return_value=True), \
                mock.patch.object(pipeline.retro, 'record_delivery'):
            self.assertTrue(pipeline.process_issue('T-1', cfg, 60))
        self.assertNotIn('T-1', retry_control.entries(blocked.path_for(self.cfg)))

    def test_history_records_blocked_without_done_or_failed_counts(self):
        reporter = StateReporter(str(self.logs / 't-state.json'), 'T', heartbeat_sec=1000)
        try:
            with mock.patch.object(runtime, 'state', reporter):
                self.poll()
            self.assertEqual(reporter.state['counters']['done'], 0)
            self.assertEqual(reporter.state['counters']['failed'], 0)
            self.assertEqual(reporter.state['counters']['attempts'], 1)
            rows = [json.loads(line) for line in (self.logs / 't-history.jsonl').read_text().splitlines()]
            self.assertEqual([r['result'] for r in rows], ['blocked'])
            self.assertEqual(reporter.state['last_result']['result'], 'blocked')
        finally:
            reporter.close()

    def test_interrupted_resumed_attempt_requires_confirmation(self):
        self.poll()
        self.reply()
        blocked.started('T-1', self.cfg)
        with retry_control.transaction(retry.control_path()) as data:
            data['T-1']['status'] = 'running'
        run, _ = self.poll()
        run.assert_not_called()
        self.assertTrue(retry_control.entries(retry.control_path())['T-1']['needs_review'])
        self.assertTrue(any('прервана' in c for c in self.jira.posted_comments))

    def test_ordinary_partial_work_survives_question_and_answer(self):
        repo = self.make_repo()
        self.cfg['general']['repo_path'] = repo
        partial = Path(repo) / 'partial.txt'

        def cli(*args, **kwargs):
            partial.write_text('unfinished work')
            return 0, OUTPUT

        with mock.patch.object(gigacode, 'run_cli', side_effect=cli), \
                mock.patch.object(pipeline, 'run_post_generation_steps') as deliver:
            self.assertFalse(pipeline.process_issue('T-1', self.cfg, 60))
        deliver.assert_not_called()
        branch = git(repo, 'branch', '--show-current')
        self.assertIn('T-1', branch)
        self.reply()
        cfg = blocked.admit('T-1', self.cfg)
        self.assertEqual(cfg['_clarification_resume']['branch'], branch)

        def resume_cli(*args, **kwargs):
            self.assertEqual(partial.read_text(), 'unfinished work')
            self.assertEqual(git(repo, 'branch', '--show-current'), branch)
            return 0, 'CODE_GENERATION_SUCCESS'

        with mock.patch.object(gigacode, 'run_cli', side_effect=resume_cli) as run, \
                mock.patch.object(pipeline, 'run_post_generation_steps', return_value=True), \
                mock.patch.object(pipeline.retro, 'record_delivery'):
            self.assertTrue(pipeline.process_issue('T-1', cfg, 60))
        run.assert_called_once()
        self.assertEqual(partial.read_text(), 'unfinished work')
        self.assertEqual(git(repo, 'ls-remote', 'origin', branch), '', 'подготовка продолжения не публикует незавершённый код')


class RequirementsBlockedTest(BlockedBase):
    def setUp(self):
        super().setUp()
        self.cfg['general']['repo_path'] = self.make_repo()
        self.path = requirements_rework.path_for(self.logs, 't')

    def test_manual_rework_waits_then_resumes_same_request_after_answer(self):
        request = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Уточнённая постановка')
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(False, OUTPUT)) as generate:
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
            self.assertFalse(requirements_rework.maybe_run(self.cfg, 60))
        self.assertEqual(generate.call_count, 1)
        row = retry_control.entries(self.path)[request]
        self.assertEqual(row['status'], 'blocked')
        self.jira.issues = []
        self.jira.backlog = ['T-1']
        self.reply()
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(True, 'CODE_GENERATION_SUCCESS')) as generate, \
                mock.patch.object(pipeline, 'run_post_generation_steps', return_value=True), \
                mock.patch.object(pipeline.retro, 'record_delivery'):
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
        generate.assert_called_once()
        cfg = generate.call_args.kwargs['config']
        self.assertEqual(cfg['_requirements']['request'], request)
        self.assertIn('Нужен JSON', gigacode.task_text_block('T-1', cfg))
        self.assertEqual(retry_control.entries(self.path)[request]['status'], 'done')

    def test_partial_rework_resumes_same_branch_without_reset_or_automatic_push(self):
        repo = self.cfg['general']['repo_path']
        partial = Path(repo) / 'rework-partial.txt'
        request = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Переделать экспорт')

        def cli(*args, **kwargs):
            partial.write_text('unfinished rework')
            return 0, OUTPUT

        with mock.patch.object(gigacode, 'run_cli', side_effect=cli), \
                mock.patch.object(pipeline, 'run_post_generation_steps') as deliver:
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
        deliver.assert_not_called()
        row = retry_control.entries(self.path)[request]
        branch = row['branch']
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(git(repo, 'branch', '--show-current'), branch)
        self.jira.backlog = ['T-1']
        self.reply()

        def resumed(*args, **kwargs):
            self.assertEqual(partial.read_text(), 'unfinished rework')
            self.assertEqual(git(repo, 'branch', '--show-current'), branch)
            return 0, 'CODE_GENERATION_SUCCESS'

        with mock.patch.object(gigacode, 'run_cli', side_effect=resumed) as run, \
                mock.patch.object(pipeline, 'run_post_generation_steps', return_value=True), \
                mock.patch.object(pipeline.retro, 'record_delivery'):
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
        run.assert_called_once()
        self.assertEqual(retry_control.entries(self.path)[request]['status'], 'done')
        self.assertEqual(partial.read_text(), 'unfinished rework')
        self.assertEqual(git(repo, 'ls-remote', 'origin', branch), '')

    def test_dirty_other_branch_is_not_taken_over_by_resume(self):
        repo = self.cfg['general']['repo_path']
        request = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Переделать экспорт')
        with mock.patch.object(gigacode, 'run_cli', return_value=(0, OUTPUT)):
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
        git(repo, 'checkout', '-b', 'human-work')
        human = Path(repo) / 'human.txt'
        human.write_text('work owned by someone else')
        self.reply()
        self.jira.backlog = ['T-1']
        with mock.patch.object(gigacode, 'run_cli') as run:
            requirements_rework.maybe_run(self.cfg, 60)
        run.assert_not_called()
        self.assertEqual(git(repo, 'branch', '--show-current'), 'human-work')
        self.assertEqual(human.read_text(), 'work owned by someone else')
        self.assertEqual(retry_control.entries(self.path)[request]['status'], 'failed')

    def test_cancelled_blocked_request_never_auto_resumes_from_backlog(self):
        request = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Переделать экспорт')
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(False, OUTPUT)):
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
        requirements_rework.cancel(self.logs, 't', request)
        self.reply()
        self.jira.issues = []
        self.jira.backlog = ['T-1']
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator') as run, \
                mock.patch.object(pipeline, '_idle'):
            self.assertFalse(requirements_rework.maybe_run(self.cfg, 60))
            pipeline._poll_once(self.cfg, 60)
        run.assert_not_called()
        self.assertEqual(retry_control.entries(self.path)[request]['status'], 'cancelled')
        self.assertIn('T-1', retry_control.entries(blocked.path_for(self.cfg)))

    def test_new_explicit_request_supersedes_old_blocked_request(self):
        old = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Первая переделка')
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(False, OUTPUT)):
            requirements_rework.maybe_run(self.cfg, 60)
        self.cfg['general']['name'] = 'Новое имя после изменения конфига'
        new = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Новая явная переделка')
        self.assertEqual(retry_control.entries(self.path)[old]['status'], 'cancelled')
        self.assertNotIn('T-1', retry_control.entries(blocked.path_for(self.cfg)))
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(True, 'CODE_GENERATION_SUCCESS')) as run, \
                mock.patch.object(pipeline, 'run_post_generation_steps', return_value=True), \
                mock.patch.object(pipeline.retro, 'record_delivery'):
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
            self.assertFalse(requirements_rework.maybe_run(self.cfg, 60))
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs['config']['_requirements']['request'], new)
        self.assertEqual(retry_control.entries(self.path)[new]['status'], 'done')

    def test_explicit_rework_replaces_ordinary_blocked_wait(self):
        self.hold()
        request = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Выполнить новую постановку')
        self.assertNotIn('T-1', retry_control.entries(blocked.path_for(self.cfg)))
        with mock.patch.object(pipeline, 'run_gigacode_orchestrator', return_value=(True, 'CODE_GENERATION_SUCCESS')) as run, \
                mock.patch.object(pipeline, 'run_post_generation_steps', return_value=True), \
                mock.patch.object(pipeline.retro, 'record_delivery'):
            self.assertTrue(requirements_rework.maybe_run(self.cfg, 60))
        run.assert_called_once()
        self.assertEqual(retry_control.entries(self.path)[request]['status'], 'done')

    def test_owner_exclusion_during_rework_preparation_is_rechecked_before_generation(self):
        request = requirements_rework.submit(self.logs, 't', self.cfg, 'T-1', 'Выполнить новую постановку')
        prepare = requirements_rework.prepare

        def prepare_then_exclude(*args):
            cfg = prepare(*args)
            retry_control.decide(retry.control_path(), 'T-1', 'block')
            return cfg

        with mock.patch.object(requirements_rework, 'prepare', side_effect=prepare_then_exclude), \
                mock.patch.object(pipeline, 'process_issue') as run:
            requirements_rework.maybe_run(self.cfg, 60)
        run.assert_not_called()
        self.assertNotEqual(retry_control.entries(self.path)[request]['status'], 'done')
