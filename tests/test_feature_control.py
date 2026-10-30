"""Operator switches are persistent and task-scoped; live output is not line-buffered."""
import io
import os
from pathlib import Path
import sys
import threading
import time
from unittest import mock
from helpers import DaemonTestCase
from daemon_state import StateReporter
from jira_gigacode import feature_control as fc, pipeline, runtime, gigacode, live_output, config, jenkins, experience, routing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'office_dashboard'))


class FeatureControlTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.logs=str(Path(self.tmp)/'logs')
        patch=mock.patch.object(fc,'LOGS_DIR',self.logs);patch.start();self.addCleanup(patch.stop)
        self.cfg={'jira':{'project':'T'},'bitbucket':{'enabled':False}}

    def test_override_beats_env_and_service_until_reset(self):
        with mock.patch.dict(os.environ,{'MEMORY_ENABLED':'true'}):
            fc.save(self.logs,'t','memory.enabled',False,0)
            snapshot=fc.apply(self.cfg)
            self.assertFalse(experience.memory_enabled(snapshot))
            service=routing.config_for_service(snapshot,{'name':'back','repo_path':self.tmp,'memory':{'enabled':True}})
            self.assertFalse(experience.memory_enabled(service))
            fc.save(self.logs,'t','memory.enabled',None,1)
            self.assertFalse(experience.memory_enabled(snapshot),'current task keeps its snapshot')
            self.assertTrue(experience.memory_enabled(fc.apply(self.cfg)))

    def test_atomic_revision_and_validation(self):
        fc.save(self.logs,'t','jira.enabled',False,0)
        for key,value,rev in [('jira.token',True,1),('jira.enabled','false',1),('jira.enabled',True,0)]:
            with self.assertRaises(ValueError):fc.save(self.logs,'t',key,value,rev)
        self.assertFalse(fc.read(self.logs,'t')['overrides']['jira.enabled'])

    def test_dependency_switch_requires_new_daemon_capability(self):
        from artel_dashboard import features
        payload={'key':'dependencies.enabled','value':False,'revision':0}
        with mock.patch.object(features,'configuration',return_value=self.cfg):
            old={'features':['feature-control']}
            with self.assertRaises(ValueError):features.update(self.logs,'t',payload,old)
            catalog=features.describe(self.logs,'t',old)['catalog']
            self.assertFalse(next(f for f in catalog if f['key']=='dependencies.enabled')['supported'])
            features.update(self.logs,'t',payload,{'features':['feature-control','task-dependencies']})
        self.assertFalse(fc.enabled(fc.apply(self.cfg),'dependencies.enabled'))

    def test_disabled_jira_skips_network_and_dependent_jobs_but_keeps_bitbucket(self):
        fc.save(self.logs,'t','jira.enabled',False,0)
        with mock.patch.object(pipeline.jira_client,'get_issues_by_statuses') as jira, mock.patch.object(pipeline.retro,'maybe_run') as retro, mock.patch.object(pipeline,'explore_idle') as explore, mock.patch.object(pipeline.pr_review,'maybe_run') as pr, mock.patch.object(pipeline.memory_verify,'maybe_run'):
            pipeline.poll_once(self.cfg,60)
        jira.assert_not_called();retro.assert_not_called();explore.assert_not_called();pr.assert_called_once()

    def test_settings_change_between_tasks_defers_remaining_tasks(self):
        with mock.patch.object(pipeline.jira_client,'get_issues_by_statuses',return_value=['T-1','T-2']),mock.patch.object(pipeline,'resolve_issue_service',return_value=self.cfg),mock.patch.object(pipeline,'process_issue',side_effect=lambda *a:fc.save(self.logs,'t','jira.enabled',False,0)) as run:
            pipeline.poll_once(self.cfg,60)
        self.assertEqual(run.call_count,1)

    def test_disabled_jenkins_does_not_read_jira_labels(self):
        cfg=dict(self.cfg,_feature_flags={'jenkins.enabled':False})
        with mock.patch.object(jenkins.jira_client,'fetch_labels') as labels:
            jenkins.deploy_for_issue('T-1','feature/T-1',cfg)
        labels.assert_not_called()

    def test_corrupt_controls_fail_closed(self):
        path=fc.path_for(self.logs,'t');path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{broken')
        with mock.patch.object(pipeline.jira_client,'get_issues_by_statuses') as jira:
            with self.assertRaises(ValueError):pipeline.poll_once(self.cfg,60)
        jira.assert_not_called()

    def test_disabled_jira_config_does_not_require_credentials(self):
        config.validate_config(dict(self.cfg,_feature_flags={'jira.enabled':False}))

    def test_startup_skips_disabled_network_integrations(self):
        from jira_gigacode import checks
        cfg=self.config(self.make_repo())
        cfg['_feature_flags']={'jira.enabled':False,'jenkins.enabled':False,'bitbucket.enabled':False}
        with mock.patch.object(checks.jira_client,'jira_request') as jira, mock.patch.object(checks,'_jenkins_get') as deploy:
            checks.run_startup_checks(cfg)
        jira.assert_not_called();deploy.assert_not_called()

    def test_bitbucket_off_overrides_environment(self):
        from jira_gigacode import pr_review
        with mock.patch.dict(os.environ,{'BITBUCKET_ENABLED':'true'}), mock.patch.object(pr_review,'Client') as client:
            self.assertEqual(pr_review.maybe_run(dict(self.cfg,_feature_flags={'bitbucket.enabled':False})),0)
        client.assert_not_called()

    def test_live_capture_is_per_daemon_and_closes_on_exception(self):
        reporter=StateReporter(str(Path(self.logs)/'t-state.json'),'T',heartbeat_sec=1000)
        try:
            with self.assertRaises(RuntimeError):
                with live_output.capture(reporter,'T-2','pr-fix') as log:
                    log.write('partial');log.flush()
                    self.assertTrue(reporter.state['cli']['active'])
                    raise RuntimeError('test')
            self.assertFalse(reporter.state['cli']['active'])
            self.assertEqual(reporter.state['cli']['purpose'],'pr-fix')
            self.assertEqual(Path(self.logs,'t-gigacode-live.log').read_text(),'partial')
            with live_output.capture(reporter,'T-3','review') as log:log.write('next')
            self.assertEqual(Path(self.logs,'t-gigacode-live.log').read_text(),'next')
        finally:reporter.close()

    def test_partial_utf8_output_visible_before_newline_or_exit(self):
        readfd,writefd=os.pipe();sink=[]
        with os.fdopen(readfd,'rb') as pipe,os.fdopen(writefd,'wb',buffering=0) as output:
            log=io.StringIO();live=io.StringIO()
            with mock.patch.object(gigacode.sys,'stdout',io.StringIO()):
                worker=threading.Thread(target=gigacode._pump_cli_output,args=(pipe,'test',log,sink,live));worker.start()
                encoded='Привет'.encode('utf-8')
                output.write(encoded[:3]);output.write(encoded[3:])
                deadline=time.monotonic()+2
                while time.monotonic()<deadline and live.getvalue()!='Привет':time.sleep(.01)
                try:
                    self.assertEqual(live.getvalue(),'Привет')
                    self.assertTrue(worker.is_alive(),'producer has not exited yet')
                finally:output.close();worker.join(2)
            self.assertEqual(''.join(sink),'Привет')
            self.assertNotIn('\ufffd',log.getvalue())


from test_portable_workspace import WorkspaceHttpTest
class FeatureHttpTest(WorkspaceHttpTest):
    def test_switches_http_and_live_log(self):
        import urllib.error
        from artel_dashboard import features
        with mock.patch.object(features,'load_configs',return_value=[{'name':'app','config':self.cfg}]):
            data=self.request('/api/features?id=app')
            self.assertTrue(data['available']);self.assertEqual(data['revision'],0)
            payload={'id':'app','key':'jira.enabled','value':False,'revision':0}
            with self.assertRaises(urllib.error.HTTPError) as err:
                self.request('/api/features',payload,{'Content-Type':'application/json','Origin':'http://other.invalid'})
            self.assertEqual(err.exception.code,403)
            self.server.control=False
            self.assertFalse(self.request('/api/features',payload)['ok'])
            self.server.control=True
            self.assertTrue(self.request('/api/features',payload)['ok'])
            self.assertTrue(Path(self.logs,'app-poke').exists())
            self.assertFalse(self.request('/api/features',payload)['ok'],'stale revision')
            self.assertFalse(self.request('/api/features?id=app')['overrides']['jira.enabled'])
            Path(self.logs,'app-gigacode-live.log').write_text('working without newline')
            self.assertEqual(self.request('/api/cli-live?id=app')['text'],'working without newline')
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/cli-live?id=../app')
            self.server.demo=True
            self.assertFalse(self.request('/api/features?id=app')['available'])
