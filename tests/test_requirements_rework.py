"""Requirements changes are distinct from failed attempts and preserve old work."""
import json
import os
from pathlib import Path
import sys
from unittest import mock

from helpers import DaemonTestCase, git
from jira_gigacode import requirements_rework as rw, pipeline, runtime, gigacode, retry_control, issue_report
from daemon_state import StateReporter
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'office_dashboard'))
from artel_dashboard.history import read_history


class RequirementsTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)
        self.logs = os.path.join(self.tmp, 'logs')
        p = mock.patch.object(rw, 'LOGS_DIR', self.logs);p.start();self.addCleanup(p.stop)
        self.instance = rw.instance_key(self.cfg)
        self.path = rw.path_for(self.logs, self.instance)

    def submit(self):
        key = rw.submit(self.logs, self.instance, self.cfg, 'T-1', 'New acceptance criteria')
        return rw.entries(self.path)[key]

    def test_foreign_project_and_empty_note_rejected(self):
        for key,note in [('OTHER-1','changed'), ('T-1',''), ('../T-1','changed')]:
            with self.assertRaises(ValueError): rw.submit(self.logs,self.instance,self.cfg,key,note)

    def test_duplicate_and_cancel(self):
        row = self.submit()
        with self.assertRaises(ValueError): self.submit()
        rw.cancel(self.logs, self.instance, row['request'])
        self.assertEqual(rw.entries(self.path)[row['request']]['status'], 'cancelled')
        self.submit()

    def test_cancel_running_rejected(self):
        row=self.submit()
        with rw.transaction(self.path) as data: data[row['request']]['status']='running'
        with self.assertRaises(ValueError): rw.cancel(self.logs,self.instance,row['request'])

    def test_config_change_never_runs_and_is_not_retried(self):
        row=self.submit(); self.cfg['general']['base_branch']='master'
        with mock.patch.object(pipeline,'process_issue') as run:
            self.assertTrue(rw.maybe_run(self.cfg,60))
            self.assertFalse(rw.maybe_run(self.cfg,60))
        run.assert_not_called()
        self.assertEqual(rw.entries(self.path)[row['request']]['status'],'failed')

    def test_interrupted_claim_needs_new_request(self):
        row=self.submit()
        with rw.transaction(self.path) as data: data[row['request']]['status']='running'
        with mock.patch.object(pipeline,'process_issue') as run:
            self.assertFalse(rw.maybe_run(self.cfg,60))
        run.assert_not_called()
        self.assertEqual(rw.entries(self.path)[row['request']]['status'],'interrupted')

    def test_blocked_task_not_run(self):
        self.submit()
        retry_control.decide(rw.retry_path(self.logs,self.instance),'T-1','block')
        with mock.patch.object(pipeline,'process_issue') as run: rw.maybe_run(self.cfg,60)
        run.assert_not_called()

    def test_jira_unavailable_fails_closed(self):
        row=self.submit()
        with mock.patch('jira_gigacode.jira_client.fetch_issue_fields',return_value=None):
            with self.assertRaises(ValueError): rw.prepare(self.cfg,row)

    def test_dirty_worktree_untouched(self):
        row=self.submit(); path=Path(self.work)/'local.txt';path.write_text('mine')
        with self.assertRaises(ValueError): rw.prepare(self.cfg,row)
        self.assertEqual(path.read_text(),'mine')

    def test_unmerged_previous_work_is_preserved_in_new_branch(self):
        old=rw.issue_branch('T-1',self.cfg)
        git(self.work,'checkout','-b',old)
        (Path(self.work)/'original.txt').write_text('previous implementation')
        git(self.work,'add','.');git(self.work,'commit','-qm','original');git(self.work,'push','origin',old)
        head=git(self.work,'rev-parse','HEAD')
        git(self.work,'checkout','develop')
        cfg=rw.prepare(self.cfg,self.submit())
        self.assertEqual(cfg['_requirements']['base'],head)
        branch=rw.issue_branch('T-1',cfg)
        self.assertNotEqual(branch,old)
        state,_=gigacode.prepare_for_generation('T-1',self.work,branch,cfg)
        self.assertEqual(state,'ready')
        self.assertEqual((Path(self.work)/'original.txt').read_text(),'previous implementation')
        self.assertEqual(git(self.work,'rev-parse',old),head)
        self.assertEqual(git(self.work,'rev-parse','origin/'+old),head)

    def test_separate_history_and_no_normal_done_counter(self):
        reporter=StateReporter(str(Path(self.logs)/'t-state.json'),'T',heartbeat_sec=1000)
        try:
            reporter.emit('generating','T-1',request='req-1')
            reporter.finish_issue('T-1',True)
            self.assertEqual(reporter.state['counters']['done'],0)
            self.assertEqual(read_history(self.logs),[])
            raw=json.loads((Path(self.logs)/'t-history.jsonl').read_text())
            self.assertEqual(raw['request'],'req-1')
        finally: reporter.close()

    def test_execution_stores_result_and_is_once(self):
        row=self.submit()
        with mock.patch.object(pipeline,'process_issue',return_value=True) as run:
            rw.maybe_run(self.cfg,60);rw.maybe_run(self.cfg,60)
        self.assertEqual(run.call_count,1)
        result=rw.entries(self.path)[row['request']]
        self.assertEqual(result['status'],'done')
        self.assertIn('requirements-',result['branch'])
        self.assertTrue(result['requirements_hash'])
        self.assertNotIn('scope',rw.rows(self.logs)[0])

    def test_changed_requirements_after_generation_prevents_delivery(self):
        cfg=rw.prepare(self.cfg,self.submit())
        with mock.patch.object(pipeline,'run_gigacode_orchestrator',return_value=(True,'')), mock.patch.object(pipeline,'run_post_generation_steps') as deliver, mock.patch.object(pipeline.jira_client,'fetch_issue_fields',return_value={'summary':'changed again'}):
            self.assertFalse(pipeline.process_issue('T-1',cfg,60))
        deliver.assert_not_called()

    def test_manual_request_dispatches_before_status_poll(self):
        with mock.patch.object(rw,'maybe_run',return_value=True),mock.patch.object(pipeline.jira_client,'get_issues_by_statuses') as poll:
            pipeline.poll_once(self.cfg,60)
        poll.assert_not_called()

    def test_actual_pipeline_generates_and_delivers_fresh_changes(self):
        row=self.submit()
        os.environ['FAKE_MODE']='nomarker_work'
        self.cfg['review']={'enabled':False}
        # Re-enqueue with the final configuration fingerprint.
        with rw.transaction(self.path) as data: data[row['request']]['scope']=rw.scope(self.cfg)
        self.assertTrue(rw.maybe_run(self.cfg,60))
        result=rw.entries(self.path)[row['request']]
        self.assertEqual(result['status'],'done',result.get('error'))
        self.assertTrue(self.remote_files(self.work,result['branch']))
        self.assertEqual(git(self.work,'branch','--show-current'),'develop')

    def test_merged_original_uses_current_base(self):
        old=rw.issue_branch('T-1',self.cfg)
        git(self.work,'branch',old);git(self.work,'push','origin',old)
        (Path(self.work)/'new_base.txt').write_text('later base work')
        git(self.work,'add','.');git(self.work,'commit','-qm','new base');git(self.work,'push','origin','develop')
        cfg=rw.prepare(self.cfg,self.submit())
        self.assertEqual(cfg['_requirements']['base'],git(self.work,'rev-parse','develop'))


class RequirementsHttpTest(__import__('test_portable_workspace').WorkspaceHttpTest):
    def test_requirements_api_create_filter_cancel_and_permissions(self):
        import urllib.error
        from jira_gigacode import supervisor
        with mock.patch.object(supervisor,'load_configs',return_value=[{'name':'worker','config':self.cfg}]):
            payload={'id':'app','action':'submit','issue':'APP-1','note':'New requirements'}
            with self.assertRaises(urllib.error.HTTPError) as err:
                self.request('/api/requirements',payload,{'Content-Type':'application/json','Origin':'http://other.invalid'})
            self.assertEqual(err.exception.code,403)
            self.server.control=False
            self.assertFalse(self.request('/api/requirements',payload)['ok'])
            self.server.control=True
            result=self.request('/api/requirements',payload)
            self.assertTrue(result['ok'])
            self.assertTrue(Path(self.logs,'app-poke').exists())
            self.assertEqual(len(self.request('/api/requirements?id=app')['rows']),1)
            self.assertEqual(self.request('/api/requirements?id=other')['rows'],[])
            self.assertFalse(self.request('/api/requirements',payload)['ok'])
            self.assertTrue(self.request('/api/requirements',{'id':'app','action':'cancel','request':result['request']})['ok'])
            self.assertEqual(self.request('/api/requirements')['rows'][0]['status'],'cancelled')
            self.assertEqual(self.request('/api/insights')['totals']['tasks'],0)
