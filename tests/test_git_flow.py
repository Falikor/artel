"""Генерация и Git-часть пайплайна на настоящих git-репозиториях с поддельным GigaCode."""
import os
import time

from helpers import DaemonTestCase, git
from jira_gigacode import gigacode, git_workspace, issue_report, jira_client, pipeline, retry, runtime

BR = 'feature/ai_team/T-1'


class GenerationResultTest(DaemonTestCase):
    """Когда генерация считается успешной."""

    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)

    def test_marker_is_success(self):
        ok, out = self.run_generation('T-1', self.cfg, 'marker')
        self.assertTrue(ok)
        self.assertIn('CODE_GENERATION_SUCCESS', out)
        self.assertEqual(git(self.work, 'branch', '--show-current'), BR)

    def test_exit0_without_marker_and_without_work_fails(self):
        ok, _ = self.run_generation('T-1', self.cfg, 'nomarker_empty')
        self.assertFalse(ok)

    def test_exit0_without_marker_but_with_work_succeeds(self):
        ok, _ = self.run_generation('T-1', self.cfg, 'nomarker_work')
        self.assertTrue(ok)

    def test_exit0_without_marker_only_temp_files_fails(self):
        ok, _ = self.run_generation('T-1', self.cfg, 'nomarker_tmp')
        self.assertFalse(ok)

    def test_strict_mode_requires_marker(self):
        cfg = self.config(self.work, require_success_marker=True)
        ok, _ = self.run_generation('T-1', cfg, 'nomarker_work')
        self.assertFalse(ok)

    def test_nonzero_exit_fails(self):
        ok, _ = self.run_generation('T-1', self.cfg, 'fail')
        self.assertFalse(ok)

    def test_cli_not_found(self):
        cfg = self.config(self.work, gigacode_path=os.path.join(self.tmp, 'нет-такого'))
        ok, out = gigacode.run_gigacode_orchestrator('T-1', cfg)
        self.assertEqual((ok, out), (False, 'GIGACODE_NOT_FOUND'))

    def test_prompt_contains_task_text_and_branch(self):
        prompt_file = os.path.join(self.tmp, 'prompt.txt')
        self.jira.description = 'Нужно сделать X'
        os.environ['FAKE_PROMPT_FILE'] = prompt_file
        try:
            self.run_generation('T-1', self.cfg, 'marker')
        finally:
            del os.environ['FAKE_PROMPT_FILE']
        with open(prompt_file, encoding='utf-8') as f:
            prompt = f.read()
        self.assertIn('Нужно сделать X', prompt)
        self.assertIn(f'рабочая ветка {BR} от origin/develop', prompt)

    def test_long_description_is_truncated(self):
        prompt_file = os.path.join(self.tmp, 'prompt.txt')
        self.jira.description = 'Я' * (gigacode.MAX_TASK_TEXT_CHARS + 500)
        os.environ['FAKE_PROMPT_FILE'] = prompt_file
        try:
            self.run_generation('T-1', self.cfg, 'marker')
        finally:
            del os.environ['FAKE_PROMPT_FILE']
        with open(prompt_file, encoding='utf-8') as f:
            prompt = f.read()
        self.assertIn('текст усечён', prompt)
        self.assertLess(prompt.count('Я'), gigacode.MAX_TASK_TEXT_CHARS + 10)


class TimeoutAndRecoveryTest(DaemonTestCase):
    """Оборванные прогоны не выдаются за готовую работу; штатное восстановление работает."""

    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work, gigacode_timeout_seconds=2)

    def test_timeout_leaves_marker_and_work_is_not_pushed(self):
        ok, out = self.run_generation('T-1', self.cfg, 'hang')
        self.assertEqual((ok, out), (False, 'TIMEOUT'))
        self.assertTrue(git_workspace.generation_was_interrupted(self.work, 'T-1'))

        git(self.work, 'checkout', '-q', 'develop')
        state, _ = git_workspace.prepare_working_branch('T-1', self.work, 'origin/develop', BR, self.cfg)
        self.assertEqual(state, 'ready')
        self.assertIsNone(self.remote_files(self.work, BR), 'недоделанное не должно уйти в origin')
        self.assertIn('refs/ai-team-interrupted/T-1-', git(self.work, 'for-each-ref'))
        self.assertFalse(git_workspace.generation_was_interrupted(self.work, 'T-1'))

    def test_failed_run_is_not_recovered(self):
        git(self.work, 'checkout', '-qb', BR)
        git_workspace.mark_generation_started(self.work, 'T-1')
        with open(os.path.join(self.work, 'half.py'), 'w') as f:
            f.write('1')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'half')
        git(self.work, 'checkout', '-q', 'develop')
        state, _ = git_workspace.prepare_working_branch('T-1', self.work, 'origin/develop', BR, self.cfg)
        self.assertEqual(state, 'ready')
        self.assertIsNone(self.remote_files(self.work, BR))

    def test_unpushed_work_of_successful_run_is_recovered(self):
        git(self.work, 'checkout', '-qb', BR)
        with open(os.path.join(self.work, 'real.py'), 'w') as f:
            f.write('1')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'real')
        git(self.work, 'checkout', '-q', 'develop')
        state, _ = git_workspace.prepare_working_branch('T-1', self.work, 'origin/develop', BR, self.cfg)
        self.assertEqual(state, 'recovered')
        self.assertIn('real.py', self.remote_files(self.work, BR))

    def test_recovery_of_temp_only_commits_does_not_push_empty_branch(self):
        git(self.work, 'checkout', '-qb', BR)
        with open(os.path.join(self.work, 'tmp_check.py'), 'w') as f:
            f.write('1')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'tmp only')
        state, _ = git_workspace.prepare_working_branch('T-1', self.work, 'origin/develop', BR, self.cfg)
        self.assertEqual(state, 'ready')
        self.assertIsNone(self.remote_files(self.work, BR))

    def test_work_already_on_remote_is_regenerated(self):
        git(self.work, 'checkout', '-qb', BR)
        with open(os.path.join(self.work, 'done.py'), 'w') as f:
            f.write('1')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'done')
        git(self.work, 'push', '-q', 'origin', BR)
        state, _ = git_workspace.prepare_working_branch('T-1', self.work, 'origin/develop', BR, self.cfg)
        self.assertEqual(state, 'ready')
        self.assertEqual(git(self.work, 'rev-parse', 'HEAD'), git(self.work, 'rev-parse', 'origin/develop'))


class DeliveryTest(DaemonTestCase):
    """Пост-обработка: что и куда уезжает после генерации."""

    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)

    def generate_and_deliver(self, mode, key='T-1'):
        ok, _ = self.run_generation(key, self.cfg, mode)
        self.assertTrue(ok, f'генерация {mode} должна пройти')
        return pipeline.run_post_generation_steps(key, self.cfg)

    def test_agent_commits_are_pushed_and_issue_transitioned(self):
        self.assertTrue(self.generate_and_deliver('marker'))
        self.assertIn('feature.py', self.remote_files(self.work, BR))
        self.assertEqual(self.jira.status, 'Ревью')
        self.assertEqual(git(self.work, 'branch', '--show-current'), 'develop')

    def test_dirty_worktree_is_committed_without_temp_files(self):
        self.assertTrue(self.generate_and_deliver('dirty_mixed'))
        files = self.remote_files(self.work, BR)
        self.assertIn('feature.py', files)
        self.assertNotIn('tmp_probe.py', files)

    def test_committed_temp_files_are_stripped(self):
        self.assertTrue(self.generate_and_deliver('commit_mixed'))
        files = self.remote_files(self.work, BR)
        self.assertIn('feature.py', files)
        self.assertNotIn('tmp_probe.py', files)

    def test_temp_only_commits_are_not_delivered(self):
        self.assertFalse(self.generate_and_deliver('commit_tmp'))
        self.assertIsNone(self.remote_files(self.work, BR))
        self.assertEqual(self.jira.status, 'Анализ', 'без работы задача не переводится')

    def test_commit_into_develop_is_parked_and_develop_restored(self):
        # Регрессия PERFREVIEW-5822: агент закоммитил прямо в develop
        self.assertTrue(self.generate_and_deliver('commit_develop'))
        self.assertIn('feature.py', self.remote_files(self.work, BR))
        git(self.work, 'fetch', '-q', 'origin')
        self.assertEqual(git(self.work, 'rev-parse', 'develop'), git(self.work, 'rev-parse', 'origin/develop'))
        self.assertNotIn('feature.py', git(self.work, 'ls-tree', '-r', '--name-only', 'origin/develop'))

    def test_nothing_done_is_not_transitioned(self):
        git(self.work, 'checkout', '-qb', BR)
        self.assertFalse(pipeline.run_post_generation_steps('T-1', self.cfg))
        self.assertEqual(self.jira.status, 'Анализ')
        self.assertEqual(self.jira.transitions_done, [])

    def test_existing_remote_work_allows_transition(self):
        git(self.work, 'checkout', '-qb', BR)
        with open(os.path.join(self.work, 'old.py'), 'w') as f:
            f.write('1')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'old')
        git(self.work, 'push', '-q', 'origin', BR)
        git(self.work, 'reset', '-q', '--hard', 'origin/develop')
        self.assertTrue(pipeline.run_post_generation_steps('T-1', self.cfg))
        self.assertEqual(self.jira.status, 'Ревью')

    def test_failed_transition_is_remembered_without_regeneration(self):
        self.jira.can_transition = False
        self.assertFalse(self.generate_and_deliver('marker'))
        self.assertIn('feature.py', self.remote_files(self.work, BR))
        self.assertTrue(retry.pending_transition_active('T-1'))
        # Перевод починили — повтор только перевода проходит
        self.jira.can_transition = True
        self.assertTrue(jira_client.transition_issue('T-1', self.cfg))
        self.assertEqual(self.jira.transitions_done, ['5'])

    def test_never_takes_destructive_transition(self):
        self.jira.can_transition = False  # доступно только «Закрыть»
        self.assertFalse(jira_client.transition_issue('T-1', self.cfg))
        self.assertEqual(self.jira.transitions_done, [])

    def test_pending_transition_survives_long_pause(self):
        retry.pending_transition_add('T-1')
        self.assertTrue(retry.pending_transition_active('T-1'))
        self.assertTrue(retry.pending_transition_active('T-1', now=time.time() + retry.PENDING_TRANSITION_TTL + 1))
        self.assertTrue(retry.pending_transition_active('T-1'))


class BaseBranchTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo(branches=('develop', 'master', 'release/1.0'))
        self.cfg = self.config(self.work)

    def comment(self, body, created='2026-01-01T00:00:00'):
        self.jira.comments.append({'body': body, 'created': created})

    def test_default_is_develop(self):
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg), ('origin/develop', None))

    def test_marker_selects_existing_branch(self):
        self.comment('Делать от релиза.\nbranch: release/1.0')
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg), ('origin/release/1.0', None))

    def test_latest_marker_wins(self):
        self.comment('ветка: master', '2026-01-02T00:00:00')
        self.comment('ветка: release/1.0', '2026-01-01T00:00:00')
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg)[0], 'origin/master')

    def test_missing_branch_is_created_from_master_and_pushed(self):
        self.comment('branch: release/2.0')
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg), ('origin/release/2.0', None))
        self.assertTrue(git(self.work, 'ls-remote', 'origin', 'release/2.0'))

    def test_own_reports_are_ignored(self):
        self.comment(f'branch: master\n{issue_report.ARTEL_REPORT_TAG}')
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg)[0], 'origin/develop')

    def test_dry_run_does_not_create_branches(self):
        self.comment('branch: release/3.0')
        runtime.DRY_RUN = True
        try:
            self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg)[0], 'origin/release/3.0')
        finally:
            runtime.DRY_RUN = False
        self.assertEqual(git(self.work, 'ls-remote', 'origin', 'release/3.0'), '')

    def test_comments_unavailable_is_an_error(self):
        self.jira.down = True
        base, err = git_workspace.resolve_base_ref('T-1', self.work, self.cfg)
        self.assertIsNone(base)
        self.assertIn('комментарии', err)

    def test_result_is_cached_within_a_cycle(self):
        git_workspace.resolve_base_ref('T-1', self.work, self.cfg)
        self.comment('branch: master')  # маркер поправили во время генерации
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg)[0], 'origin/develop')
