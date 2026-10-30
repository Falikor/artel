"""Portable process/lock behavior and operator memory/statistics contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'office_dashboard'))
from jira_gigacode import platform_support as platform, memory_store, launcher, supervisor
from artel_dashboard import insights, knowledge


class PlatformTest(unittest.TestCase):
    def test_pid_probe_does_not_kill_child(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
        try:
            self.assertTrue(platform.pid_alive(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.terminate(); child.wait(timeout=5)
        self.assertFalse(platform.pid_alive(child.pid))
        for value in (None, 'invalid', 0, -1):
            self.assertFalse(platform.pid_alive(value))

    def test_cross_process_lock_released_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'state.lock')
            code = "from jira_gigacode.platform_support import fcntl; import sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
            with open(path, 'a') as lock:
                platform.fcntl.flock(lock, platform.fcntl.LOCK_EX)
                blocked = subprocess.run([sys.executable, '-c', code, path], capture_output=True)
                self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(subprocess.run([sys.executable, '-c', code, path], capture_output=True).returncode, 0)

    def test_windows_child_runner_argv(self):
        with mock.patch.object(platform.os, 'name', 'nt'):
            cmd = platform.child_command(['tool.exe', 'path with space', 'a&b'])
        self.assertEqual(cmd[-3:], ['tool.exe', 'path with space', 'a&b'])
        self.assertTrue(cmd[1].endswith('windows_runner.py'))

    @unittest.skipUnless(os.name == 'nt', 'Native Windows job API')
    def test_windows_job_removes_orphan_after_parent_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'child.pid')
            code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); open(sys.argv[1],'w').write(str(p.pid))"
            subprocess.run(platform.child_command([sys.executable, '-c', code, path]), check=True, timeout=15)
            import time
            pid = int(Path(path).read_text())
            for _ in range(50):
                if not platform.pid_alive(pid): break
                time.sleep(.1)
            self.assertFalse(platform.pid_alive(pid))


class InsightTest(unittest.TestCase):
    def test_missing_metrics_are_not_zero_and_attempts_included(self):
        tasks = [{'id':'one','issue':'APP-1','result':'ok','attempts':2,'total_seconds':120,
                  'runs':[{'result':'fail','tokens':{'total':100}}, {'result':'ok','tokens':{'total':200}}]},
                 {'id':'two','issue':'APP-2','result':'fail'}]
        t = insights.report(tasks, {'input':0,'output':0,'cached':0,'currency':'₽'})['totals']
        self.assertEqual((t['tasks'],t['attempts'],t['failed_attempts'],t['first_pass']), (2,3,2,0))
        self.assertEqual((t['tokens'],t['token_coverage'],t['median_seconds']), (300,2,120))
        self.assertIsNone(t['cost'])
        even = insights.summarize([{'id':'a','total_seconds':10}, {'id':'b','total_seconds':20}], {'input':0,'output':0,'cached':0})
        self.assertEqual(even['median_seconds'], 15)
        self.assertIsNone(insights.percentile([], .9))
        self.assertEqual(insights.percentile([10,20,30,40,50,60,70,80,90,100],.9),90)


class MemoryDashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'memory.md')
        self.cfg = {'jira':{'project':'APP'}, 'memory':{'path':self.path}}
        self.patch = mock.patch.object(knowledge,'load_configs',return_value=[{'name':'worker','config':self.cfg}])
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_get_does_not_create_or_import_memory(self):
        Path(self.path).write_text('- Legacy note', encoding='utf-8')
        rows=knowledge.listing()
        self.assertTrue(rows[0]['legacy']); self.assertEqual(rows[0]['entries'],[])
        self.assertFalse(Path(self.path+'.store.json').exists())
        self.assertNotIn('path', rows[0]); self.assertNotIn('config', rows[0])

    def test_owner_decision_and_audit_and_no_arbitrary_path(self):
        memory_store.observe(self.path,self.cfg,'APP-1','tests',['Use stable ordering for the query results'])
        row=knowledge.listing()[0]; entry=row['entries'][0]
        with self.assertRaises(ValueError):
            knowledge.decide({'source':'../../tmp/other','action':'reject','entry':entry['id']})
        with self.assertRaises(ValueError):
            knowledge.decide({'source':row['key'],'action':'approve','entry':entry['id'],'evidence':''})
        knowledge.decide({'source':row['key'],'action':'approve','entry':entry['id'],'evidence':'Verified order in query tests'})
        self.assertEqual(knowledge.listing()[0]['entries'][0]['status'],'confirmed')
        knowledge.decide({'source':row['key'],'action':'reject','entry':entry['id']})
        self.assertEqual(knowledge.listing()[0]['entries'][0]['status'],'rejected')
        self.assertIn('rejected_by_owner',Path(self.path+'.history.jsonl').read_text())

    def test_service_memories_are_separate(self):
        self.cfg['memory']['path'] = str(Path(self.temp.name) / '{key}.md')
        self.cfg['services']=[{'name':'api','repo_path':'/work/api'},{'name':'web','repo_path':'/work/web'}]
        rows=knowledge.listing()
        self.assertEqual({r['service'] for r in rows},{'api','web'})
        self.assertEqual(len({r['key'] for r in rows}),2)
        self.assertEqual(knowledge.listing({'other'}),[])

    def test_memory_cli_dispatch(self):
        with mock.patch.object(memory_store,'command',return_value=0) as command:
            supervisor.cmd_memory(['list',self.path])
        command.assert_called_once_with(['list',self.path])



class WorkspaceHttpTest(unittest.TestCase):
    def setUp(self):
        import threading
        from artel_dashboard import common
        from artel_dashboard.handler import make_server
        from artel_dashboard.stores import Names, Prices
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.logs=self.temp.name
        self.path=str(Path(self.logs)/'notes.md')
        self.cfg={'jira':{'project':'APP'},'memory':{'path':self.path}}
        memory_store.observe(self.path,self.cfg,'APP-1','test',['Validate missing values before transforming input'])
        for patch in [mock.patch.object(common,'DEFAULT_LOGS',self.logs),
                      mock.patch.object(knowledge,'load_configs',return_value=[{'name':'worker','config':self.cfg}])]:
            patch.start(); self.addCleanup(patch.stop)
        self.server=make_server('127.0.0.1',0,self.logs,self.logs,Names(str(Path(self.logs)/'names.json')),
                                Prices(str(Path(self.logs)/'prices.json')),None)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.url='http://127.0.0.1:'+str(self.server.server_port)

    def request(self,path,body=None,headers=None):
        import urllib.request
        req=urllib.request.Request(self.url+path, data=json.dumps(body).encode() if body is not None else None,
                                   headers=headers or {'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=5) as response: return json.load(response)

    def test_http_memory_write_readonly_and_cross_origin(self):
        import urllib.error
        data=self.request('/api/memory'); row=data['sources'][0]
        payload={'source':row['key'],'entry':row['entries'][0]['id'],'action':'reject'}
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/memory',payload,{'Content-Type':'application/json','Origin':'http://other.invalid'})
        self.assertEqual(error.exception.code,403)
        self.server.control=False
        self.assertEqual(self.request('/api/memory',payload)['reason'],'readonly')
        self.assertEqual(knowledge.listing()[0]['entries'][0]['status'],'candidate')
        self.server.control=True
        self.assertTrue(self.request('/api/memory',payload)['ok'])
        self.assertEqual(self.request('/api/memory')['sources'][0]['entries'][0]['status'],'rejected')
        self.server.demo=True
        self.assertEqual(self.request('/api/memory')['sources'],[])

    def test_insights_and_retrospective_filters(self):
        import time
        now=time.time()
        Path(self.logs,'app-delivered.jsonl').write_text(json.dumps({'issue':'APP-1','at':now,'head':'a','branch':'feature/APP-1'})+'\n')
        Path(self.logs,'app-outcomes.json').write_text(json.dumps({'APP-1':{'head':'a','outcome':'merged_changed','changed':True,'human_commits':2,'checked_at':now}}))
        data=self.request('/api/retrospective?id=app&days=30')
        self.assertEqual(data['summary']['totals']['changed'],1)
        self.assertEqual(data['rows'][0]['branch'],'feature/APP-1')
        self.assertEqual(self.request('/api/retrospective?id=other')['rows'],[])
        self.assertEqual(self.request('/api/insights')['totals']['tasks'],0)


class LauncherIntegrationTest(unittest.TestCase):
    def setUp(self):
        import shutil
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        source=Path(__file__).resolve().parents[1]
        for name in ['jira_gigacode','office_dashboard/artel_dashboard']:
            shutil.copytree(source/name,self.root/name,ignore=shutil.ignore_patterns('__pycache__'))
        for name in ['artel.py','jira_to_gigacode.py','daemon_state.py','office_dashboard/server.py']:
            shutil.copy2(source/name,self.root/name)
        (self.root/'config').mkdir()
        self.env=dict(os.environ,PYTHONUTF8='1')
        self.addCleanup(lambda:self.run_cli('down'))

    def run_cli(self,*args):
        return subprocess.run([sys.executable,str(self.root/'artel.py'),*args],cwd=str(self.root),env=self.env,
                              capture_output=True,text=True,timeout=30)

    def test_up_reuses_processes_and_down_cleans_owned_dashboard(self):
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        first=self.run_cli('up','--port',str(port),'--no-browser')
        self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        record=self.root/'logs/artel-dashboard.json'
        state=json.loads(record.read_text())
        again=self.run_cli('up','--port',str(port),'--no-browser')
        self.assertEqual(again.returncode,0,again.stdout+again.stderr)
        self.assertEqual(json.loads(record.read_text())['pid'],state['pid'])
        down=self.run_cli('down')
        self.assertEqual(down.returncode,0,down.stdout+down.stderr)
        self.assertFalse(record.exists())

    def test_port_conflict_does_not_start_daemons(self):
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); sock.listen()
            result=self.run_cli('up','--port',str(sock.getsockname()[1]),'--no-browser')
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertFalse((self.root/'logs/artel-supervisor.pid').exists())


class WindowsCommandTest(unittest.TestCase):
    def test_native_build_wrappers(self):
        from jira_gigacode.memory_verify import test_commands
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'pom.xml').touch(); (root/'mvnw.cmd').touch()
            with mock.patch.object(os, 'name', 'nt'):
                self.assertEqual(test_commands({}, directory), [['./mvnw.cmd', '-B', 'test']])
            (root/'pom.xml').unlink()
            (root/'package.json').write_text('{"scripts":{"test":"node test.js"}}')
            with mock.patch.object(os, 'name', 'nt'):
                self.assertEqual(test_commands({}, directory), [['npm.cmd', 'test']])

if __name__ == '__main__':
    unittest.main()
