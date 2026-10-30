"""Prompt snapshots, real CLI stdin, isolated settings and HTTP permissions."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
from unittest import mock

from helpers import DaemonTestCase
from jira_gigacode import feature_control, gigacode, pipeline, prompt_control as pc, runtime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'office_dashboard'))


class PromptControlTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.logs = str(Path(self.tmp, 'logs'))
        self.cfg = {'jira': {'project': 'T'}, 'memory': {'enabled': False}}
        for module in (feature_control, pc):
            patch = mock.patch.object(module, 'LOGS_DIR', self.logs)
            patch.start()
            self.addCleanup(patch.stop)

    def test_defaults_preserve_command_and_public_scope_on_upgrade(self):
        cfg = feature_control.apply(self.cfg)
        self.assertNotIn('prompts', cfg)
        baseline = gigacode.build_command('T-1', self.cfg, self.tmp, 'work/T-1', 'origin/develop')
        self.assertEqual(gigacode.build_command('T-1', cfg, self.tmp, 'work/T-1', 'origin/develop'), baseline)
        self.assertEqual(pc.decorate('original', cfg, 'review'), 'original')

    def test_config_defaults_reset_and_startup_snapshot_do_not_stick(self):
        cfg = dict(self.cfg, prompts={'profile': 'custom', 'instructions': 'Config instruction'})
        pc.save(self.logs, 't', {'profile': 'testing'}, 0)
        startup = feature_control.apply(cfg)
        self.assertEqual(pc.effective(startup)['profile'], 'testing')
        pc.save(self.logs, 't', None, 1)
        current = feature_control.apply(startup)
        self.assertEqual(pc.effective(current)['instructions'], 'Config instruction')
        self.assertEqual(current['prompts'], cfg['prompts'])
        self.assertEqual(pc.effective(startup)['profile'], 'testing', 'running task keeps original snapshot')

    def test_settings_are_persistent_and_isolated_by_instance(self):
        pc.save(self.logs, 't', {'profile': 'testing'}, 0)
        self.assertEqual(pc.effective(feature_control.apply(self.cfg))['profile'], 'testing')
        self.assertEqual(pc.effective(feature_control.apply({'jira': {'project': 'OTHER'}}))['profile'], 'developer')
        self.assertIn('prompts', feature_control.apply(self.cfg), 'changed behavior participates in retry scope')

    def test_manual_requests_capture_effective_preferences_without_private_metadata(self):
        from jira_gigacode import requirements_rework as requests
        snapshot = feature_control.apply(self.cfg)
        self.assertEqual(requests.scope(self.cfg), requests.scope(snapshot))
        pc.save(self.logs, 't', {'profile': 'testing'}, 0)
        request = requests.submit(self.logs, 't', self.cfg, 'T-1', 'Add checks')
        saved = json.loads(requests.path_for(self.logs, 't').read_text())[request]
        current = feature_control.apply(self.cfg)
        self.assertEqual(saved['scope'], requests.scope(current))
        self.assertNotEqual(saved['scope'], requests.scope(snapshot))

    def test_atomic_conflicts_and_invalid_values_do_not_modify_settings(self):
        pc.save(self.logs, 't', {'profile': 'testing'}, 0)
        for values, revision in [({}, 0), ({'profile': []}, 1), ({'instructions': 'x' * 6001}, 1),
                                 ({'subagent': 'qa; echo hacked'}, 1), ({'stages': {'bad': ''}}, 1),
                                 ({'instructions': '\x00'}, 1), ({'command': 'sh'}, 1), ({}, True)]:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    pc.save(self.logs, 't', values, revision)
        self.assertEqual(pc.read(self.logs, 't')['revision'], 1)

    def test_corrupt_settings_fail_closed_before_network(self):
        path = pc.path_for(self.logs, 't')
        path.parent.mkdir(parents=True, exist_ok=True)
        for text in ('{broken', '{"revision":1}', '{"revision":1,"values":{"profile":null}}'):
            path.write_text(text)
            with mock.patch.object(pipeline.jira_client, 'get_issues_by_statuses') as network:
                with self.assertRaises(ValueError):
                    pipeline.poll_once(self.cfg, 60)
            network.assert_not_called()

    def test_changes_stop_before_next_task_and_snapshot_survives_save(self):
        captured = []
        def task(key, config, cooldown):
            captured.append(config)
            pc.save(self.logs, 't', {'profile': 'testing'}, 0)
        with mock.patch.object(pipeline.jira_client, 'get_issues_by_statuses', return_value=['T-1', 'T-2']), \
             mock.patch.object(pipeline, 'resolve_issue_service', side_effect=lambda key, cfg: cfg), \
             mock.patch.object(pipeline, 'process_issue', side_effect=task), \
             mock.patch.object(pipeline, 'explore_idle'), mock.patch.object(pipeline.memory_verify, 'maybe_run'):
            pipeline.poll_once(self.cfg, 60)
        self.assertEqual(len(captured), 1)
        self.assertEqual(pc.effective(captured[0])['profile'], 'developer')
        self.assertTrue(feature_control.changed(captured[0]))

    def test_idle_changes_stop_before_next_workflow(self):
        cfg = feature_control.apply(self.cfg)
        with mock.patch.object(pipeline.pr_review, 'maybe_run', side_effect=lambda c: pc.save(self.logs, 't', {'profile': 'testing'}, 0)), \
             mock.patch.object(pipeline.retro, 'maybe_run') as retro, \
             mock.patch.object(pipeline, 'explore_idle') as explore, \
             mock.patch.object(pipeline.memory_verify, 'maybe_run') as memory:
            pipeline._idle(cfg)
        retro.assert_not_called()
        explore.assert_not_called()
        memory.assert_not_called()

    def test_retro_prompt_change_defers_next_service_without_consuming_interval(self):
        from jira_gigacode import retro
        cfg = feature_control.apply(self.cfg)
        state = {'last_run': 123, 'reviewed': {}}
        entries = [{'issue': 'T-1', 'head': 'one', 'repo': '/one'},
                   {'issue': 'T-2', 'head': 'two', 'repo': '/two'}]
        def reflect(config, facts):
            pc.save(self.logs, 't', {'profile': 'testing'}, 0)
            return ('Summary', 0)
        with mock.patch.object(retro, 'candidates', return_value=entries), \
             mock.patch.object(retro, 'load_state', return_value=state), \
             mock.patch.object(retro, 'save_state'), \
             mock.patch.object(retro, 'collect_facts', side_effect=lambda entry, cfg: dict(entry)), \
             mock.patch.object(retro, 'record_outcome'), \
             mock.patch.object(retro, 'has_outcome', return_value=True), \
             mock.patch.object(retro, 'write_report', return_value=None), \
             mock.patch.object(retro, 'reflect', side_effect=reflect) as run:
            self.assertEqual(retro.run_retro(cfg, now=999), 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(state['last_run'], 123)
        self.assertEqual(state['reviewed'], {'T-1': 'one'})

    def test_restart_and_service_routing_keep_prompt_fingerprint_stable(self):
        from jira_gigacode import blocked, routing
        cfg = dict(self.cfg, prompts={'profile': 'custom', 'instructions': 'Config default'})
        pc.save(self.logs, 't', {'profile': 'testing', 'stages': {'explore': 'Focus tests'}}, 0)
        first = feature_control.apply(cfg)
        restarted = feature_control.apply(cfg)
        reapplied = feature_control.apply(first)
        service = {'name': 'back', 'repo_path': '/repo'}
        snapshots = [routing.config_for_service(x, service) for x in (first, restarted, reapplied)]
        self.assertEqual(len({blocked.scope(x) for x in snapshots}), 1)
        self.assertTrue(all(pc.effective(x)['profile'] == 'testing' for x in snapshots))
        pc.save(self.logs, 't', None, 1)
        reset = routing.config_for_service(feature_control.apply(first), service)
        self.assertNotEqual(blocked.scope(reset), blocked.scope(snapshots[0]))
        self.assertEqual(pc.effective(reset)['instructions'], 'Config default')

    def test_broken_config_does_not_hide_other_prompt_editors(self):
        from artel_dashboard import prompts
        with mock.patch.object(prompts, 'load_configs', return_value=[
                {'name': 'broken', 'config': None, 'problem': 'invalid json'},
                {'name': 'valid', 'config': self.cfg}]):
            self.assertEqual(prompts.catalog(), [{'id': 't', 'project': 'T', 'name': 'valid'}])
            self.assertEqual(prompts.configuration('t'), self.cfg)
            with self.assertRaises(ValueError):
                prompts.configuration('broken')

    def test_prompt_change_during_prerequisite_check_defers_next_manual_request(self):
        from jira_gigacode import requirements_rework as requests
        from jira_gigacode.dependencies import DependencyBlocked
        for issue in ('T-1', 'T-2'):
            requests.submit(self.logs, 't', self.cfg, issue, 'Add checks')
        snapshot = feature_control.apply(self.cfg)
        def prepare(config, row):
            pc.save(self.logs, 't', {'profile': 'testing'}, 0)
            raise DependencyBlocked('Waiting for backend')
        with mock.patch.object(requests, 'prepare', side_effect=prepare) as prepare_mock, \
             mock.patch.object(pipeline, 'process_issue') as process:
            self.assertFalse(requests.maybe_run(snapshot, 60))
        self.assertEqual(prepare_mock.call_count, 1)
        process.assert_not_called()
        rows = requests.rows(self.logs)
        self.assertEqual([row['status'] for row in rows], ['queued', 'queued'])
        self.assertTrue(all('started_at' not in row for row in rows))

    def test_testing_profile_and_custom_agent_reach_real_cli_stdin(self):
        repo = self.make_repo()
        cfg = self.config(repo)
        cfg['review'] = {'enabled': True, 'max_rework': 1}
        cfg['prompts'] = {'profile': 'testing', 'subagent': 'qa-specialist', 'instructions': 'GLOBAL_SENTINEL',
                          'stages': {'generation': 'GEN_SENTINEL', 'review': 'REVIEW_SENTINEL', 'rework': 'REWORK_SENTINEL'}}
        directory = Path(self.tmp, 'prompts')
        directory.mkdir()
        with mock.patch.dict(os.environ, {'FAKE_MODE': 'marker', 'FAKE_REVIEW': 'changes,approve',
                                         'FAKE_REWORK': 'fix', 'FAKE_PROMPT_DIR': str(directory)}), \
             contextlib.redirect_stdout(io.StringIO()):
            pipeline.process_issue('T-1', cfg, 60)
        generation = (directory / 'generate-0.txt').read_text()
        self.assertIn('/qa-specialist', generation)
        self.assertIn('Твоя специализация — тестирование', generation)
        self.assertIn('GEN_SENTINEL', generation)
        self.assertIn('CODE_GENERATION_BLOCKED', generation)
        self.assertIn('коммитить в базовую и любые другие ветки запрещено', generation)
        self.assertIn('REVIEW_SENTINEL', (directory / 'review-0.txt').read_text())
        rework = (directory / 'rework-0.txt').read_text()
        self.assertIn('REWORK_SENTINEL', rework)
        self.assertIn('/qa-specialist', rework)
        for path in directory.glob('*.txt'):
            self.assertIn('GLOBAL_SENTINEL', path.read_text())

    def test_pr_and_memory_stages_reach_their_cli_calls(self):
        from jira_gigacode import memory_verify, pr_review
        cfg = dict(self.cfg, prompts={'stages': {'pr_review': 'PR_SENTINEL', 'memory': 'MEMORY_SENTINEL'}})
        with mock.patch.object(pr_review, 'run_cli', return_value=(0, 'PR_RESULT_START\n{}\nPR_RESULT_END')) as cli:
            pr_review.ask(cfg, self.tmp, 'T-1', 'PR_PROTOCOL', 'assess')
        self.assertIn('PR_SENTINEL', cli.call_args.args[2])
        self.assertTrue(cli.call_args.args[2].endswith('PR_PROTOCOL'))
        with mock.patch.object(memory_verify, 'run_cli', return_value=(0, '{}')) as cli, \
             mock.patch.object(memory_verify, 'parse', return_value={}):
            memory_verify.ask(cfg, self.tmp, 'MEMORY-1', 'MEMORY_PROTOCOL', 'plan')
        self.assertIn('MEMORY_SENTINEL', cli.call_args.args[2])
        self.assertTrue(cli.call_args.args[2].endswith('MEMORY_PROTOCOL'))

    def test_explore_and_retro_stages_reach_their_cli_calls(self):
        from jira_gigacode import explore, retro
        repo = self.make_repo()
        cfg = self.config(repo)
        cfg['prompts'] = {'stages': {'explore': 'EXPLORE_SENTINEL', 'retro': 'RETRO_SENTINEL'}}
        with mock.patch.object(explore, 'run_cli', return_value=(1, '')) as cli:
            explore.explore_issue('T-1', {'summary': 'Explore', 'description': 'Task'}, cfg)
        self.assertIn('EXPLORE_SENTINEL', cli.call_args.args[2])
        with mock.patch.object(retro, 'run_cli', return_value=(0, 'RETRO_START\nSummary\nRETRO_END')) as cli, \
             mock.patch.object(retro, 'build_prompt', return_value='RETRO_PROTOCOL'):
            retro.reflect(cfg, [{'base': 'origin/develop'}])
        self.assertIn('RETRO_SENTINEL', cli.call_args.args[2])
        self.assertTrue(cli.call_args.args[2].endswith('RETRO_PROTOCOL'))


from test_portable_workspace import WorkspaceHttpTest


class PromptHttpTest(WorkspaceHttpTest):
    def setUp(self):
        super().setUp()
        from artel_dashboard import prompts
        self.cfg['prompts'] = {'profile': 'custom', 'instructions': 'Configuration default'}
        patch = mock.patch.object(prompts, 'load_configs', return_value=[{'name': 'worker', 'config': self.cfg}])
        patch.start()
        self.addCleanup(patch.stop)

    def test_catalog_includes_not_started_daemon_and_saved_defaults_reset(self):
        catalog = self.request('/api/prompts')
        self.assertEqual(catalog['daemons'][0]['id'], 'app')
        data = self.request('/api/prompts?id=app')
        self.assertTrue(data['available'])
        self.assertEqual(data['values']['instructions'], 'Configuration default')
        payload = {'id': 'app', 'action': 'save', 'revision': 0, 'values': {'profile': 'testing'}}
        data = self.request('/api/prompts', payload)
        self.assertTrue(data['ok'])
        self.assertTrue(Path(self.logs, 'app-poke').exists())
        self.assertEqual(data['values']['profile'], 'testing')
        self.assertFalse(self.request('/api/prompts', payload)['ok'])
        data = self.request('/api/prompts', {'id': 'app', 'action': 'reset', 'revision': 1})
        self.assertEqual(data['values']['instructions'], 'Configuration default')
        self.assertFalse(data['overridden'])

    def test_readonly_demo_preview_and_cross_origin(self):
        import urllib.error
        payload = {'id': 'app', 'action': 'save', 'revision': 0, 'values': {'profile': 'testing'}}
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/prompts', payload, {'Content-Type': 'application/json', 'Origin': 'http://other.invalid'})
        self.assertEqual(error.exception.code, 403)
        self.server.control = False
        self.assertFalse(self.request('/api/prompts', payload)['ok'])
        preview = dict(payload, action='preview', stage='review')
        data = self.request('/api/prompts', preview)
        self.assertTrue(data['ok'])
        self.assertIn('тестирование', data['preview']['text'])
        self.assertIsNone(data['preview']['subagent'])
        self.assertFalse(pc.path_for(self.logs, 'app').exists())
        self.server.demo = True
        self.server.control = True
        self.assertFalse(self.request('/api/prompts', payload)['ok'])
        self.assertTrue(self.request('/api/prompts', preview)['ok'])
        data = self.request('/api/prompts?id=demo')
        self.assertTrue(data['available'])
        self.assertFalse(data['control'])

    def test_invalid_input_or_stage_never_saves_and_large_unicode_is_accepted(self):
        for values, stage in [(None, 'generation'), ({'profile': []}, 'generation'), ({}, []), ({'stages': {'review': 2}}, 'review')]:
            payload = {'id': 'app', 'action': 'save', 'revision': 0, 'values': values, 'stage': stage}
            self.assertFalse(self.request('/api/prompts', payload)['ok'])
        self.assertFalse(pc.path_for(self.logs, 'app').exists())
        values = {'instructions': 'я' * 6000, 'stages': {s['id']: 'я' * 6000 for s in pc.STAGES}}
        data = self.request('/api/prompts', {'id': 'app', 'action': 'save', 'revision': 0, 'values': values})
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['values']['instructions']), 6000)

