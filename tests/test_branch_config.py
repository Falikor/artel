"""Настраиваемая база на реальных локальных git-репозиториях."""
import os
from unittest import mock

from helpers import DaemonTestCase, git
from jira_gigacode import config, checks, git_workspace, pipeline, routing


class BranchConfigTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo(branches=('main',))
        git(self.work, 'checkout', '-q', 'main')
        origin = git(self.work, 'remote', 'get-url', 'origin')
        git(origin, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        git(self.work, 'push', '-q', 'origin', '--delete', 'develop')
        git(self.work, 'branch', '-D', 'develop')
        self.cfg = self.config(self.work, base_branch='main', base_branch_create_from='main')

    def test_main_only_repository_passes_startup_and_resolves(self):
        self.assertEqual(checks.run_startup_checks(self.cfg), ([], []))
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg), ('origin/main', None))

    def test_environment_priority_and_prefixes(self):
        with mock.patch.dict(os.environ, {'BASE_BRANCH': 'master', 'T_BASE_BRANCH': 'refs/heads/main'}):
            self.assertEqual(config.default_base_ref(self.cfg), 'origin/main')
        self.cfg['general']['base_branch'] = 'origin/main'
        self.assertEqual(config.default_base_ref(self.cfg), 'origin/main')

    def test_invalid_names_are_rejected(self):
        for name in ('', '-x', 'main~1', '../main', 'main..x', 'HEAD', 'a b', 3):
            with self.subTest(name=name):
                self.cfg['general']['base_branch'] = name
                with self.assertRaises(ValueError):
                    config.default_base_ref(self.cfg)

    def test_missing_configured_branch_is_not_created(self):
        self.cfg['general']['base_branch'] = 'typo'
        before = git(self.work, 'ls-remote', 'origin')
        ref, error = git_workspace.resolve_base_ref('T-1', self.work, self.cfg)
        self.assertIsNone(ref)
        self.assertIn('general.base_branch', error)
        self.assertEqual(git(self.work, 'ls-remote', 'origin'), before)

    def test_comment_override_created_from_configured_source(self):
        self.jira.comments.append({'body': 'branch: release/new', 'created': '2026'})
        self.assertEqual(git_workspace.resolve_base_ref('T-1', self.work, self.cfg), ('origin/release/new', None))
        self.assertEqual(git(self.work, 'rev-parse', 'origin/release/new'), git(self.work, 'rev-parse', 'origin/main'))

    def test_service_overrides_and_inheritance(self):
        cfg = routing.config_for_service(self.cfg, {'name': 'web', 'repo_path': self.work, 'base_branch': 'release/web'})
        self.assertEqual(config.default_base_ref(cfg), 'origin/release/web')
        self.assertEqual(config.base_branch(cfg, creation=True), 'main')
        self.assertEqual(config.default_base_ref(self.cfg), 'origin/main')

    def test_delivery_returns_to_main_and_preserves_main(self):
        ok, _ = self.run_generation('T-1', self.cfg, 'marker')
        self.assertTrue(ok)
        self.assertTrue(pipeline.run_post_generation_steps('T-1', self.cfg))
        self.assertEqual(git(self.work, 'branch', '--show-current'), 'main')
        self.assertEqual(git(self.work, 'rev-parse', 'main'), git(self.work, 'rev-parse', 'origin/main'))
        self.assertIn('feature.py', self.remote_files(self.work, 'feature/ai_team/T-1'))

    def test_no_pull_after_failed_checkout(self):
        self.cfg['general']['base_branch'] = 'missing'
        with mock.patch.object(pipeline.subprocess, 'run', wraps=pipeline.subprocess.run) as run:
            pipeline._return_to_base('T-1', self.work, self.cfg)
        self.assertEqual(len(run.call_args_list), 2)  # validation and checkout only
        self.assertFalse(any('pull' in call.args[0] for call in run.call_args_list))

    def test_commits_in_main_are_delivered_without_polluting_main(self):
        from pathlib import Path
        from jira_gigacode import git_delivery
        before = git(self.work, 'rev-parse', 'origin/main')
        Path(self.work, 'feature.py').write_text('print(42)\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', 'agent accidentally committed in main')
        self.assertTrue(git_delivery.deliver_agent_commits(
            'T-1', self.work, 'feature/ai_team/T-1', 'main', '1', 'origin/main', self.cfg))
        self.assertEqual(git(self.work, 'rev-parse', 'main'), before)
        self.assertIn('feature.py', self.remote_files(self.work, 'feature/ai_team/T-1'))

    def test_background_work_inherits_base_and_allows_explicit_override(self):
        from jira_gigacode import explore, memory_verify
        for ref in ('origin/main', 'origin/release/check'):
            if ref != 'origin/main':
                git(self.work, 'push', '-q', 'origin', 'main:release/check')
                self.cfg['explore'] = {'base': ref}
                self.cfg['memory']['verify_base'] = ref
            with self.subTest(ref=ref):
                with mock.patch.object(explore, 'temp_worktree', wraps=explore.temp_worktree) as wt:
                    explore.explore_issue('T-7', {'summary': 'Check', 'description': '', 'updated': '2026'}, self.cfg)
                    self.assertEqual(wt.call_args.args[1], ref)
                with mock.patch.object(memory_verify, 'temp_worktree', wraps=memory_verify.temp_worktree) as wt, \
                        mock.patch.object(memory_verify, 'ask', side_effect=RuntimeError('stop at model call')):
                    with self.assertRaisesRegex(RuntimeError, 'stop at model call'):
                        memory_verify.verify(self.cfg, {'id': 'a', 'text': 'Check code'})
                    self.assertEqual(wt.call_args.args[1], ref)

    def test_service_startup_uses_its_base_for_background_checks(self):
        cfg = self.config(self.work)  # global default develop isn't present
        cfg['services'] = [{'name': 'web', 'repo_path': self.work,
                            'base_branch': 'main', 'base_branch_create_from': 'main'}]
        cfg['explore'] = {'statuses': ['Backlog']}
        errors, warnings = checks.run_startup_checks(cfg)
        self.assertEqual(errors, [])
        self.assertFalse(any('ветки' in message for message in warnings))
