"""Остановка демона с дашборда: флажок, прерывание GigaCode, кнопки «Остановить»/«Запустить» на сервере."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from unittest import mock

from helpers import PROJECT_DIR, DaemonTestCase
from jira_gigacode import gigacode, runtime


class StopFlagTest(DaemonTestCase):
    def test_flag_stops_daemon(self):
        flag = os.path.join(self.tmp, 't-stop')
        runtime.watch_stop_flag(flag, interval=0.05)
        self.assertTrue(runtime.running)
        open(flag, 'w').close()
        deadline = time.time() + 3
        while runtime.running and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(runtime.running)
        self.assertFalse(os.path.exists(flag), 'флажок снят')

    def test_stale_flag_from_previous_run_is_ignored(self):
        flag = os.path.join(self.tmp, 't-stop')
        open(flag, 'w').close()
        runtime.watch_stop_flag(flag, interval=0.05)
        time.sleep(0.3)
        self.assertTrue(runtime.running)
        runtime.running = False  # погасить поток наблюдения

    def test_stop_interrupts_gigacode_quickly(self):
        work = self.make_repo()
        cfg = self.config(work, gigacode_timeout_seconds=60)
        threading.Timer(1.0, lambda: setattr(runtime, 'running', False)).start()
        started = time.time()
        ok, out = self.run_generation('T-1', cfg, 'hang')
        self.assertEqual((ok, out), (False, gigacode.STOPPED))
        self.assertLess(time.time() - started, 15, 'не ждёт таймаута GigaCode')
        from jira_gigacode import git_workspace
        self.assertTrue(git_workspace.generation_was_interrupted(work, 'T-1'), 'прерванное не выдаётся за готовое')

    def test_features_in_state(self):
        with mock.patch.object(runtime, 'LOGS_DIR', self.tmp):
            reporter = runtime.create_state_reporter({'jira': {'project': 'T'}}, 'c.json', 60)
        try:
            self.assertIn('stop', reporter.state['features'])
        finally:
            reporter.close()


def _load_server():
    path = os.path.join(PROJECT_DIR, 'office_dashboard', 'server.py')
    spec = importlib.util.spec_from_file_location('artel_dashboard_server', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DashboardControlTest(DaemonTestCase):
    """Настоящий HTTP-сервер дашборда на свободном порту, state-файлы во временной папке."""

    @classmethod
    def setUpClass(cls):
        cls.server_module = _load_server()

    def setUp(self):
        super().setUp()
        self.logs = os.path.join(self.tmp, 'logs')
        os.makedirs(self.logs)
        srv = self.server_module
        self.httpd = srv.make_server('127.0.0.1', 0, self.logs, self.tmp, srv.Names(os.path.join(self.tmp, 'names.json')),
                                     srv.Prices(os.path.join(self.tmp, 'prices.json')), None)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def post(self, path, payload):
        req = urllib.request.Request(f'http://127.0.0.1:{self.httpd.server_address[1]}{path}',
                                     data=json.dumps(payload).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())

    def write_state(self, key, stage='generating', pid=None, features=('poke', 'stop'), host=None, config='config/hrppa.json'):
        state = {'project': key.upper(), 'pid': pid or os.getpid(), 'host': host or socket.gethostname(),
                 'stage': stage, 'issue': 'HRPPA-1', 'heartbeat': time.time(), 'config': config}
        if features is not None:
            state['features'] = list(features)
        with open(os.path.join(self.logs, f'{key}-state.json'), 'w') as f:
            json.dump(state, f)

    def test_stop_writes_flag(self):
        self.write_state('hrppa')
        res = self.post('/api/stop', {'id': 'hrppa'})
        self.assertEqual((res['ok'], res['how'], res['stage']), (True, 'flag', 'generating'))
        self.assertTrue(os.path.exists(os.path.join(self.logs, 'hrppa-stop')))

    def test_old_local_daemon_gets_sigterm(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.write_state('hrppa', pid=child.pid, features=None)
        res = self.post('/api/stop', {'id': 'hrppa'})
        self.assertEqual((res['ok'], res['how']), (True, 'signal'))
        self.assertEqual(child.wait(timeout=5), -15)

    def test_old_remote_daemon_cannot_be_stopped(self):
        self.write_state('hrppa', features=None, host='другой-компьютер')
        self.assertEqual(self.post('/api/stop', {'id': 'hrppa'})['reason'], 'old')

    def test_offline_and_unknown(self):
        self.write_state('hrppa', stage='stopped')
        self.assertEqual(self.post('/api/stop', {'id': 'hrppa'})['reason'], 'offline')
        self.assertEqual(self.post('/api/stop', {'id': 'nobody'})['reason'], 'unknown')

    def test_start_needs_supervisor(self):
        self.write_state('hrppa', stage='stopped')
        self.assertEqual(self.post('/api/start', {'id': 'hrppa'})['reason'], 'no_supervisor')
        with open(os.path.join(self.logs, 'artel-supervisor.pid'), 'w') as f:
            f.write(str(os.getpid()))
        self.assertTrue(self.post('/api/start', {'id': 'hrppa'})['ok'])
        self.assertTrue(os.path.exists(os.path.join(self.logs, 'artel-restart-hrppa')),
                        'запрос супервизору — по имени конфига')

    def test_start_running_daemon(self):
        self.write_state('hrppa')
        self.assertEqual(self.post('/api/start', {'id': 'hrppa'})['reason'], 'running')

    def test_read_only_mode(self):
        self.httpd.control = False
        self.write_state('hrppa')
        for path in ('/api/stop', '/api/start', '/api/poke'):
            self.assertEqual(self.post(path, {'id': 'hrppa'})['reason'], 'readonly')
        self.assertFalse(os.path.exists(os.path.join(self.logs, 'hrppa-stop')))

    def test_supervisor_restart_request_starts_stopped_daemon(self):
        # Сквозной путь: «Запустить» → запрос artel-restart-<конфиг> → супервизор поднимает демона
        from jira_gigacode import supervisor
        config_dir = os.path.join(self.tmp, 'config')
        os.makedirs(config_dir)
        with open(os.path.join(config_dir, 'hrppa.json'), 'w') as f:
            json.dump({'jira': {'project': 'HRPPA'}, 'behavior': 'exit0'}, f)
        entry = os.path.join(self.tmp, 'fake.py')
        with open(entry, 'w') as f:
            f.write('import sys, time\nsys.exit(0) if "--once" in sys.argv else time.sleep(30)\n')
        with mock.patch.multiple(supervisor, LOGS_DIR=self.logs, CONFIG_DIR=config_dir,
                                 PID_FILE=os.path.join(self.logs, 'artel-supervisor.pid'),
                                 STATE_FILE=os.path.join(self.logs, 'artel-supervisor.json'),
                                 RESTART_PREFIX=os.path.join(self.logs, 'artel-restart-')):
            sup = supervisor.Supervisor(config_dir=config_dir, entry=entry, stop_timeout=5)
            self.addCleanup(mock.patch.object(supervisor, 'STATE_FILE', supervisor.STATE_FILE)(sup.shutdown))
            sup.tick()
            d = sup.daemons['hrppa']
            d.stopping = True
            d.proc.terminate()
            d.proc.wait(timeout=5)
            sup.tick()
            self.assertEqual(d.status, 'stopped')
            with open(supervisor.PID_FILE, 'w') as f:
                f.write(str(os.getpid()))
            self.write_state('hrppa', stage='stopped')
            self.assertTrue(self.post('/api/start', {'id': 'hrppa'})['ok'])
            sup.tick()
            sup.tick()
            self.assertEqual(d.status, 'running')
