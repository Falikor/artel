"""Linked issues gate work before retries; Development evidence uses real temporary Git."""
import copy
import contextlib
import io
import os
from pathlib import Path
from unittest import mock

from helpers import DaemonTestCase, git
from jira_gigacode import dependencies as dep, jira_development as dev, jira_client, pipeline, retry, retry_control, routing, gigacode, requirements_rework as rw, dry_run, runtime, feature_control


class DependenciesTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.back, self.front = self.make_repo(), self.make_repo()
        self.cfg = self.config(self.back, ci_id='CI00123')
        self.cfg['jira']['ci_field'] = '90001'
        self.cfg['services'] = [{'name':'back','role':'backend','repo_path':self.back},
                                {'name':'web','role':'frontend','repo_path':self.front,'base_branch':'main'}]
        self.jira.fields_by_issue = {
            'T-1':{'summary':'WEB: screen', 'labels':['front'], 'issuelinks':[self.link('T-2')]},
            'T-2':{'summary':'Backend: API', 'labels':['backend'], 'issuelinks':[self.link('T-1', 'outward')]}}
        self.jira.ci_by_issue = {'T-1':'123', 'T-2':'123'}
        self.jira.issues = ['T-1', 'T-2']
        self.dev_result = {'errors':[], 'detail':[{'branches':[]}]}
        fake = self.jira
        def request(method, path, **kwargs):
            if path == '/rest/dev-status/1.0/issue/detail':
                self.dev_calls.append(kwargs)
                return self.dev_result
            return fake(method, path, **kwargs)
        self.dev_calls = []
        p=mock.patch.object(jira_client,'jira_request',side_effect=request);p.start();self.addCleanup(p.stop)

    @staticmethod
    def link(key, side='inward', name='Blocks'):
        return {'type':{'name':name,'inward':'is blocked by','outward':'blocks'}, side+'Issue':{'key':key}}

    def ready(self, key='T-2'):
        self.jira.fields_by_issue[key]['status']={'name':self.jira.ready,'statusCategory':{'key':'indeterminate'}}

    def external(self):
        self.jira.ci_by_issue['T-2']='999'

    def test_same_ci_front_waits_without_attempt_and_backend_runs_first(self):
        calls=[]
        def run(key, cfg, cooldown):
            calls.append((key,cfg))
            self.ready(key)
            return True
        with mock.patch.object(pipeline,'process_issue',side_effect=run):
            pipeline.poll_once(self.cfg,60)
        self.assertEqual([key for key,cfg in calls],['T-2','T-1'])
        self.assertEqual(calls[0][1]['general']['repo_path'],self.back)
        self.assertEqual(calls[1][1]['general']['repo_path'],self.front)
        self.assertIn('T-2',gigacode.task_text_block('T-1',calls[1][1]))
        self.assertEqual(self.dev_calls, [], 'ready status needs no Development request')

    def test_failed_backend_does_not_unlock_front(self):
        with mock.patch.object(pipeline,'process_issue',return_value=False) as run:
            pipeline.poll_once(self.cfg,60)
        self.assertEqual([c.args[0] for c in run.call_args_list],['T-2'])
        self.assertNotIn('T-1',retry_control.entries(retry.control_path()))

    def test_external_front_requires_label_even_if_backend_ready(self):
        self.external();self.ready()
        self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.jira.fields_by_issue['T-1']['labels'].append('backend-ready')
        self.assertTrue(dep.inspect('T-1',self.cfg).allowed)
        self.assertEqual(self.dev_calls,[])

    def test_label_on_backend_is_not_permission_and_does_not_override_local_dependency(self):
        self.external();self.jira.fields_by_issue['T-2']['labels'].append('backend-ready')
        self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.jira.ci_by_issue['T-2']='123'
        self.jira.fields_by_issue['T-1']['labels'].append('backend-ready')
        self.assertFalse(dep.inspect('T-1',self.cfg).allowed)

    def test_unknown_ci_requires_external_label(self):
        del self.cfg['jira']['ci_field']
        self.ready()
        self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.jira.fields_by_issue['T-1']['labels'].append('backend-ready')
        self.assertTrue(dep.inspect('T-1',self.cfg).allowed)

    def test_multiple_backends_all_must_satisfy_their_own_rule(self):
        self.jira.fields_by_issue['T-1']['issuelinks'].append(self.link('X-3'))
        self.jira.fields_by_issue['X-3']={'summary':'backend external','labels':['backend']}
        self.jira.ci_by_issue['X-3']='999'
        self.jira.fields_by_issue['T-1']['labels'].append('backend-ready')
        self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.ready();self.assertTrue(dep.inspect('T-1',self.cfg).allowed)

    def test_ready_status_is_configurable_and_done_is_not_implicitly_enabled(self):
        self.jira.fields_by_issue['T-2']['status']={'name':'Done','statusCategory':{'key':'done'}}
        self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.cfg['dependencies']={'accept_done':True}
        self.assertTrue(dep.inspect('T-1',self.cfg).allowed)
        self.cfg['dependencies']={'ready_statuses':['Integrated']}
        self.ready();self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.jira.fields_by_issue['T-2']['status']={'name':'Integrated'}
        self.assertTrue(dep.inspect('T-1',self.cfg).allowed)

    def test_unavailable_link_or_ci_never_unlocks(self):
        for endpoint in ('/rest/api/2/issue/T-2','/rest/api/2/search'):
            old=jira_client.jira_request
            with mock.patch.object(jira_client,'jira_request',side_effect=lambda method,path,**kw: None if path==endpoint else old(method,path,**kw)):
                self.assertFalse(dep.inspect('T-1',self.cfg).allowed)

    def test_ambiguous_link_needs_role_and_link_types_can_exclude_unrelated_issues(self):
        self.jira.fields_by_issue['T-2']['labels']=['front','backend']
        self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.cfg['dependencies']={'link_types':['Relates']}
        self.assertTrue(dep.inspect('T-1',self.cfg).allowed)

    def test_no_links_still_runs_and_switch_disables_check(self):
        self.jira.fields_by_issue['T-1']['issuelinks']=[]
        self.assertTrue(dep.inspect('T-1',self.cfg).allowed)
        cfg=dict(self.cfg,_feature_flags={'dependencies.enabled':False})
        with mock.patch.object(jira_client,'jira_request') as api:
            self.assertTrue(dep.inspect('T-1',cfg).allowed)
        api.assert_not_called()

    def test_one_owned_comment_is_updated_after_restart_and_release(self):
        self.external()
        for _ in range(2):
            with self.assertRaises(dep.DependencyBlocked):dep.admit('T-1',self.cfg)
        self.assertEqual(len(self.jira.posted_comments),1)
        self.assertIn('backend-ready',self.jira.posted_comments[0])
        self.assertEqual(self.jira.updated_comments,[])
        self.jira.fields_by_issue['T-1']['labels'].append('backend-ready')
        dep.admit('T-1',copy.deepcopy(self.cfg))
        self.assertEqual(len(self.jira.posted_comments),1)
        self.assertEqual(len(self.jira.updated_comments),1)
        self.assertIn('ожидание снято',self.jira.updated_comments[0]['body'])

    def test_failed_comment_read_never_posts_duplicate(self):
        self.external()
        with mock.patch.object(jira_client,'fetch_comments',return_value=None):
            with self.assertRaises(dep.DependencyBlocked):dep.admit('T-1',self.cfg)
        self.assertEqual(self.jira.posted_comments,[])

    def test_removing_link_updates_waiting_comment(self):
        self.external()
        with self.assertRaises(dep.DependencyBlocked):dep.admit('T-1',self.cfg)
        self.jira.fields_by_issue['T-1']['issuelinks']=[]
        dep.admit('T-1',self.cfg)
        self.assertIn('ожидание снято',self.jira.updated_comments[0]['body'])

    def test_real_pipeline_in_two_repositories(self):
        git(self.front,'push','origin','develop:refs/heads/main')
        calls=[]
        process=pipeline.process_issue
        def run(key,cfg,cooldown):
            calls.append(key)
            return process(key,cfg,cooldown)
        with mock.patch.dict(os.environ,{'FAKE_MODE':'marker'}), mock.patch.object(pipeline,'process_issue',side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            pipeline.poll_once(self.cfg,60)
        self.assertEqual(calls,['T-2','T-1'])
        self.assertIn('feature.py',self.remote_files(self.back,'feature/ai_team/T-2'))
        self.assertIn('feature.py',self.remote_files(self.front,'feature/ai_team/T-1'))
        self.assertEqual(git(self.front,'branch','--show-current'),'main')

    def test_waiting_is_not_failure_and_does_not_stop_idle_jobs(self):
        self.external();self.jira.issues=['T-1']
        with mock.patch.object(pipeline,'process_issue') as run, mock.patch.object(pipeline.pr_review,'maybe_run') as pr, mock.patch.object(pipeline,'explore_idle'), mock.patch.object(pipeline.retro,'maybe_run'), mock.patch.object(pipeline.memory_verify,'maybe_run') as mem:
            pipeline.poll_once(self.cfg,60)
        run.assert_not_called();pr.assert_called_once();mem.assert_called_once()
        self.assertEqual(retry_control.entries(retry.control_path()),{})

    def test_never_executes_linked_backend_outside_search(self):
        self.jira.issues=['T-1']
        with mock.patch.object(pipeline,'process_issue') as run:
            pipeline.poll_once(self.cfg,60)
        run.assert_not_called()

    def test_search_paginates_and_preserves_project_ci_epic_assignee(self):
        self.cfg['jira'].update(epic_name='Team',epic_link_field='Epic Link',assignee='robot')
        self.jira.issues=['T-'+str(i) for i in range(1,103)]
        self.assertEqual(jira_client.get_issues_by_statuses(['Analysis'],self.cfg),self.jira.issues)
        self.assertEqual(self.jira.search_pages,[(0,100),(100,100)])
        for query in self.jira.searches:
            for required in ('project=T','cf[90001] = "123"','"Epic Link" = "Team"','assignee = "robot"'):
                self.assertIn(required,query)

    def test_dependency_context_does_not_change_retry_scope(self):
        self.ready();self.jira.issues=['T-1']
        with mock.patch.object(pipeline,'process_issue',side_effect=lambda *args:retry_control.outcome(retry.control_path(),'T-1',False,60)) as run:
            pipeline.poll_once(self.cfg,60)
            self.jira.fields_by_issue['T-2']['description']='New context from backend'
            pipeline.poll_once(self.cfg,60)
        self.assertEqual(run.call_count,2)

    def test_manual_front_waits_but_does_not_hide_queued_backend(self):
        iid=rw.instance_key(self.cfg)
        front=rw.submit(rw.LOGS_DIR,iid,self.cfg,'T-1','New screen')
        back=rw.submit(rw.LOGS_DIR,iid,self.cfg,'T-2','New API')
        with mock.patch.object(pipeline,'process_issue',return_value=True) as run:
            self.assertTrue(rw.maybe_run(self.cfg,60))
        self.assertEqual(run.call_args.args[0],'T-2')
        entries=rw.entries(rw.path_for(rw.LOGS_DIR,iid))
        self.assertEqual(entries[front]['status'],'queued')
        self.assertIn('waiting_reason',entries[front])
        self.assertNotIn('started_at',entries[front])
        self.assertEqual(entries[back]['status'],'done')
        rw.cancel(rw.LOGS_DIR,iid,front)

    def test_queued_rework_blocks_old_ready_status_and_old_branch(self):
        self.ready()
        rw.submit(rw.LOGS_DIR,rw.instance_key(self.cfg),self.cfg,'T-2','New backend requirements')
        with mock.patch.object(dev,'branch_with_code',return_value={'branch':'old'}) as branch:
            self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        branch.assert_not_called()

    def test_dry_run_does_not_write_or_generate_when_waiting(self):
        self.external()
        with mock.patch.object(dry_run,'_explain_generation') as generation:
            dry_run.dry_run_issue('T-1',self.cfg)
        generation.assert_not_called();self.assertEqual(self.jira.posted_comments,[])

    def code_branch(self):
        branch='feature/T-2-api'
        git(self.back,'checkout','-b',branch)
        (Path(self.back)/'api.py').write_text('def endpoint(): return 42\n')
        git(self.back,'add','.');git(self.back,'commit','-qm','T-2 API');git(self.back,'push','origin',branch)
        git(self.back,'checkout','develop')
        self.dev_result={'errors':[],'detail':[{'branches':[{'name':branch,'url':'https://bitbucket.example/projects/DEMO/repos/api/browse?at='+branch,
                                                         'repository':{'url':'https://bitbucket.example/projects/DEMO/repos/api'}}]}]}
        return branch

    def test_development_branch_with_real_code_unlocks_using_backend_not_front_base(self):
        branch=self.code_branch()
        cfg=routing.config_for_service(self.cfg,self.cfg['services'][1])
        with mock.patch.object(dev,'same_repository',return_value=True):
            result=dep.inspect('T-1',cfg,owner_config=self.cfg)
        self.assertTrue(result.allowed,result.reason)
        self.assertEqual(result.links[0]['code']['branch'],branch)
        self.assertEqual(result.links[0]['code']['base'],'develop')
        self.assertEqual(git(self.back,'branch','--show-current'),'develop')
        self.assertEqual(git(self.back,'for-each-ref','--format=%(refname)','refs/artel-dependencies'),'')
        self.assertEqual(self.dev_calls[0]['params'],{'issueId':'2','applicationType':'stash','dataType':'pullrequest'})

    def test_deleted_or_empty_development_branch_never_unlocks(self):
        branch=self.code_branch()
        git(self.back,'push','origin','--delete',branch)
        with mock.patch.object(dev,'same_repository',return_value=True):
            self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        git(self.back,'push','origin','develop:refs/heads/'+branch)
        with mock.patch.object(dev,'same_repository',return_value=True):
            self.assertFalse(dep.inspect('T-1',self.cfg).allowed)

    def test_wrong_repository_or_development_error_never_unlocks(self):
        self.code_branch()
        with mock.patch.object(dev,'same_repository',return_value=False):
            self.assertFalse(dep.inspect('T-1',self.cfg).allowed)
        self.dev_result={'errors':['Permission denied'],'detail':[]}
        result=dep.inspect('T-1',self.cfg)
        self.assertFalse(result.allowed);self.assertIn('Development',result.reason)

    def test_bitbucket_repository_identity(self):
        expected=('bitbucket.example','demo','api')
        for url in ('https://bitbucket.example/projects/DEMO/repos/api/browse',
                    'https://bitbucket.example/scm/DEMO/api.git',
                    'ssh://git@bitbucket.example:7999/DEMO/api.git',
                    'git@bitbucket.example:DEMO/api.git'):
            self.assertEqual(dev.repository_identity(url),expected)
        self.assertNotEqual(dev.repository_identity('https://other.example/scm/DEMO/api.git'),expected)
