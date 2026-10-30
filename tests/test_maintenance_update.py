"""Real subprocess drain/re-exec integration, without Jira/network dependencies."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_under_test', ROOT / 'update_artel.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)

PROGRAM = '''import os, sys, time, subprocess, json
from pathlib import Path
from types import SimpleNamespace
from jira_gigacode import maintenance as m
version = VERSION
role = sys.argv[1]
m.register(role)
def event(kind):
    with open('events.jsonl', 'a') as f:
        f.write(json.dumps(dict(kind=kind, role=role, version=version, setting=os.environ.get('ARTEL_TEST_SETTING'), argv=sys.argv[1:]))+'\\n')
event('boot')
if role == 'supervisor':
    child = subprocess.Popen([sys.executable, 'artel.py', 'daemon'])
    d = SimpleNamespace(name='a', removed=False, status='running', proc=child)
    supervisor = SimpleNamespace(daemons={'a':d}, running=True)
    while True:
        if m.requested(): m.drain_supervisor(supervisor)
        time.sleep(.03)
elif role == 'daemon':
    event('task-start')
    time.sleep(.8)
    event('task-finished')
    while True:
        m.checkpoint()
        time.sleep(.03)
else:
    while True:
        m.checkpoint()
        time.sleep(.03)
'''

class ManagedUpdateTest(unittest.TestCase):
    def test_waits_for_task_and_restores_original_launch(self):
        self.exercise(False)

    def test_timeout_keeps_current_task_running(self):
        self.exercise(True)

    def exercise(self, cancel):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            target, source = base/'installed', base/'source'
            for folder, version in ((target, 'old'), (source, 'new')):
                for rel in u.REQUIRED:
                    p = folder/rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text('# placeholder' if p.suffix == '.py' else 'html')
                (folder/'jira_gigacode/__init__.py').write_text('')
                shutil.copy2(ROOT/'jira_gigacode/maintenance.py', folder/'jira_gigacode/maintenance.py')
                shutil.copy2(ROOT/'jira_gigacode/platform_support.py', folder/'jira_gigacode/platform_support.py')
                (folder/'artel.py').write_text(PROGRAM.replace('VERSION', repr(version)))
            env = dict(os.environ, ARTEL_TEST_SETTING='keep me')
            procs = [subprocess.Popen([sys.executable, 'artel.py', role], cwd=target, env=env,
                                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                     for role in ('supervisor', 'dashboard')]
            try:
                deadline = time.monotonic()+10
                while time.monotonic()<deadline:
                    if len(u.registered(target)) == 3 and 'task-start' in (target/'events.jsonl').read_text(): break
                    time.sleep(.03)
                else: self.fail('Processes did not start')
                if cancel:
                    with self.assertRaisesRegex(ValueError, 'Время ожидания'):
                        u.managed_install(source, target, base/'backups', [], .01)
                    time.sleep(1)
                    events = [json.loads(x) for x in (target/'events.jsonl').read_text().splitlines()]
                    self.assertTrue(any(e['kind']=='task-finished' for e in events))
                    self.assertFalse(any(e['version']=='new' for e in events))
                    self.assertTrue(all(p.poll() is None for p in procs))
                    self.assertFalse((target/'.artel-maintenance/request.json').exists())
                    self.assertFalse((base/'backups').exists())
                    return
                result = u.managed_install(source, target, base/'backups', [], 10)
                self.assertTrue(result.is_dir())
                events = [json.loads(x) for x in (target/'events.jsonl').read_text().splitlines()]
                finished = next(i for i,e in enumerate(events) if e['kind']=='task-finished' and e['version']=='old')
                boots = [(i,e) for i,e in enumerate(events) if e['kind']=='boot' and e['version']=='new']
                self.assertTrue({'supervisor','dashboard'} <= {e['role'] for _,e in boots})
                self.assertTrue(all(i > finished for i,e in boots))
                self.assertTrue(all(e['setting']=='keep me' for _,e in boots))
                self.assertFalse((target/'.artel-maintenance/request.json').exists())
                self.assertFalse((result/'installation/.artel-maintenance').exists())
            finally:
                for p in procs:
                    try: os.killpg(p.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                for p in procs:
                    p.wait(timeout=10)
                    p.stderr.close()

    def test_real_dashboard_keeps_port_paths_and_readonly_mode(self):
        import socket
        import urllib.request
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            target, source = base/'installed', base/'source'
            target.mkdir()
            for rel in ('jira_gigacode', 'office_dashboard/artel_dashboard'):
                shutil.copytree(ROOT/rel, target/rel, ignore=shutil.ignore_patterns('__pycache__'))
            for rel in ('artel.py', 'jira_to_gigacode.py', 'daemon_state.py', 'office_dashboard/server.py'):
                shutil.copy2(ROOT/rel, target/rel)
            (target/'office_dashboard/static').mkdir()
            (target/'office_dashboard/static/index.html').write_text('old')
            (target/'logs').mkdir()
            (target/'settings').mkdir()
            (target/'settings/names.json').write_text('{"a":"Original"}')
            shutil.copytree(target, source)
            (source/'office_dashboard/static/index.html').write_text('new')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            p = subprocess.Popen([sys.executable,'office_dashboard/server.py','--port',str(port),
                                  '--no-control','--logs','logs','--names','settings/names.json',
                                  '--characters','settings/characters.json'], cwd=target,
                                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic()+10
                while not u.registered(target) and time.monotonic()<deadline: time.sleep(.05)
                result = u.managed_install(source,target,base/'backups',[],10)
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/state',timeout=5) as r:
                    self.assertFalse(json.load(r)['control'])
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/names',timeout=5) as r:
                    self.assertEqual(json.load(r), {'a':'Original'})
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=5) as r:
                    self.assertEqual(r.read(), b'new')
                self.assertIsNone(p.poll())
                self.assertTrue((result/'installation/settings/names.json').exists())
            finally:
                try: os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                p.wait(timeout=10)
                p.stderr.close()
