"""Супервизор artel.py: запуск по конфигам, перезапуск упавших, статус и версия."""
import json
import os
import sys
import time
from unittest import mock

from helpers import DaemonTestCase
from jira_gigacode import __version__, supervisor

FAKE_DAEMON = '''import json, sys, time
cfg = json.load(open(sys.argv[1]))
b = cfg.get('behavior', 'sleep')
if b == 'crash':
    time.sleep(0.1); sys.exit(3)
if b == 'config_error':
    sys.exit(1)
if b == 'exit0':
    sys.exit(0)
time.sleep(60)
'''


class SupervisorBase(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.config_dir = os.path.join(self.tmp, 'config')
        self.logs = os.path.join(self.tmp, 'logs')
        os.makedirs(self.config_dir)
        os.makedirs(self.logs)
        self.entry = os.path.join(self.tmp, 'fake_daemon.py')
        with open(self.entry, 'w') as f:
            f.write(FAKE_DAEMON)
        p = mock.patch.multiple(supervisor, LOGS_DIR=self.logs, CONFIG_DIR=self.config_dir,
                                PID_FILE=os.path.join(self.logs, 'artel-supervisor.pid'),
                                STATE_FILE=os.path.join(self.logs, 'artel-supervisor.json'),
                                RESTART_PREFIX=os.path.join(self.logs, 'artel-restart-'))
        p.start()
        self.addCleanup(p.stop)
        self.sup = supervisor.Supervisor(config_dir=self.config_dir, entry=self.entry, stop_timeout=5)
        self.addCleanup(self.sup.shutdown)

    def add_config(self, name, behavior='sleep', **general):
        cfg = {'jira': {'project': name.upper()}, 'general': dict({'name': name.title()}, **general),
               'behavior': behavior}
        with open(os.path.join(self.config_dir, f'{name}.json'), 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
        return cfg

    def wait_exit(self, name, timeout=5):
        d = self.sup.daemons[name]
        deadline = time.time() + timeout
        while d.proc and d.proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)



class SupervisorTest(SupervisorBase):
    def test_starts_daemons_and_skips_bad_configs(self):
        self.add_config('oleg')
        self.add_config('off', enabled=False)
        with open(os.path.join(self.config_dir, 'broken.json'), 'w') as f:
            f.write('{')
        self.sup.tick()
        self.assertEqual(set(self.sup.daemons), {'oleg'})
        self.assertEqual(self.sup.daemons['oleg'].status, 'running')
        self.assertIn('выключен', self.sup.skipped['off'])
        self.assertIn('не читается', self.sup.skipped['broken'])
        with open(supervisor.STATE_FILE, encoding='utf-8') as f:
            state = json.load(f)
        self.assertEqual(state['daemons'][0]['name'], 'oleg')

    def test_crash_is_restarted_with_backoff(self):
        self.add_config('oleg', behavior='crash')
        now = time.time()
        self.sup.tick(now)
        self.wait_exit('oleg')
        self.sup.tick(now + 200)   # упал «через 200 с после старта» → не похоже на ошибку конфига
        d = self.sup.daemons['oleg']
        self.assertEqual(d.status, 'backoff')
        self.assertAlmostEqual(d.next_start - (now + 200), 5, delta=0.5)
        self.sup.tick(now + 206)
        self.assertEqual((d.status, d.restarts), ('running', 1))
        self.wait_exit('oleg')
        self.sup.tick(now + 500)
        self.assertAlmostEqual(d.next_start - (now + 500), 10, delta=0.5, msg='пауза растёт')

    def test_config_error_waits_longer(self):
        self.add_config('oleg', behavior='config_error')
        now = time.time()
        self.sup.tick(now)
        self.wait_exit('oleg')
        self.sup.tick(now + 1)
        d = self.sup.daemons['oleg']
        self.assertEqual(d.status, 'config_error')
        self.assertGreaterEqual(d.next_start - now, supervisor.CONFIG_ERROR_RETRY)

    def test_manual_stop_is_respected_until_restart(self):
        self.add_config('oleg', behavior='exit0')
        self.sup.tick()
        self.wait_exit('oleg')
        self.sup.tick(time.time() + 1000)
        d = self.sup.daemons['oleg']
        self.assertEqual(d.status, 'stopped')
        self.assertIsNone(d.proc)
        open(supervisor.RESTART_PREFIX + 'oleg', 'w').close()
        self.sup.tick()
        self.sup.tick()
        self.assertEqual(d.status, 'running')

    def test_restart_request_restarts_running_daemon(self):
        self.add_config('oleg')
        self.sup.tick()
        first = self.sup.daemons['oleg'].proc.pid
        open(supervisor.RESTART_PREFIX + 'all', 'w').close()
        self.sup.tick()
        self.wait_exit('oleg')
        self.sup.tick()
        self.sup.tick()
        d = self.sup.daemons['oleg']
        self.assertEqual(d.status, 'running')
        self.assertNotEqual(d.proc.pid, first)
        self.assertEqual(d.restarts, 1)

    def test_removed_config_stops_daemon(self):
        self.add_config('oleg')
        self.sup.tick()
        proc = self.sup.daemons['oleg'].proc
        os.remove(os.path.join(self.config_dir, 'oleg.json'))
        self.sup.scan(time.time())
        proc.wait(timeout=5)
        self.sup.tick()
        self.assertNotIn('oleg', self.sup.daemons)

    def test_daemon_running_outside_is_not_duplicated(self):
        cfg = self.add_config('oleg')
        with open(os.path.join(self.logs, 'oleg-state.json'), 'w') as f:
            json.dump({'pid': os.getpid(), 'stage': 'idle', 'heartbeat': time.time()}, f)
        self.sup.tick()
        d = self.sup.daemons['oleg']
        self.assertEqual(d.status, 'external')
        self.assertIsNone(d.proc)
        self.assertEqual(supervisor.running_outside(cfg, set()), os.getpid())

    def test_shutdown_stops_children(self):
        self.add_config('oleg')
        self.add_config('marina')
        self.sup.tick()
        procs = [d.proc for d in self.sup.daemons.values()]
        self.sup.shutdown()
        self.assertTrue(all(p.poll() is not None for p in procs))
        self.assertTrue(all(d.status == 'stopped' for d in self.sup.daemons.values()))


class StatusTest(SupervisorBase):
    def write_state(self, name, version, stage='generating', issue='OLEG-1'):
        with open(os.path.join(self.logs, f'{name}-state.json'), 'w') as f:
            json.dump({'pid': os.getpid(), 'stage': stage, 'issue': issue, 'heartbeat': time.time(),
                       'daemon_version': version}, f)

    def test_rows_and_outdated(self):
        self.add_config('oleg')
        self.add_config('marina')
        self.write_state('oleg', '1.0.0')
        self.write_state('marina', __version__, stage='idle', issue=None)
        _, rows = supervisor.status_rows()
        by_name = {r['name']: r for r in rows}
        self.assertTrue(by_name['Oleg']['outdated'])
        self.assertEqual(by_name['Oleg']['stage'], 'пишет код')
        self.assertFalse(by_name['Marina']['outdated'])
        with mock.patch('sys.stdout') as out:
            supervisor.print_status()
        printed = ''.join(c.args[0] for c in out.write.call_args_list)
        self.assertIn('устарел', printed)
        self.assertIn('restart --outdated', printed)

    def test_restart_requires_running_supervisor(self):
        self.add_config('oleg')
        with mock.patch('sys.stdout'):
            self.assertEqual(supervisor.cmd_restart(['oleg']), 1)
        with open(supervisor.PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        with mock.patch('sys.stdout'):
            self.assertEqual(supervisor.cmd_restart(['oleg']), 0)
            self.assertEqual(supervisor.cmd_restart(['nobody']), 1)
            self.assertEqual(supervisor.cmd_restart(['--outdated']), 0)
        self.assertTrue(os.path.exists(supervisor.RESTART_PREFIX + 'oleg'))
        self.assertTrue(os.path.exists(supervisor.RESTART_PREFIX + 'outdated'))

    def test_outdated_restart_targets_only_old_versions(self):
        self.add_config('oleg')
        self.add_config('marina')
        self.sup.tick()
        self.write_state('oleg', '1.0.0')
        self.write_state('marina', __version__)
        open(supervisor.RESTART_PREFIX + 'outdated', 'w').close()
        with mock.patch.object(self.sup, 'stop_daemon') as stop:
            self.sup.tick()
        self.assertEqual([c.args[0].name for c in stop.call_args_list], ['oleg'])


class VersionTest(DaemonTestCase):
    def test_version_flag(self):
        import subprocess
        from helpers import PROJECT_DIR
        out = subprocess.run([sys.executable, os.path.join(PROJECT_DIR, 'jira_to_gigacode.py'), '--version'],
                             capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(out.stdout.strip(), __version__)
        out = subprocess.run([sys.executable, os.path.join(PROJECT_DIR, 'artel.py'), '--version'],
                             capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(out.stdout.strip(), __version__)

    def test_version_goes_to_state(self):
        from jira_gigacode import runtime
        cfg = {'jira': {'project': 'T'}, 'general': {}}
        with mock.patch.object(runtime, 'LOGS_DIR', self.tmp):
            reporter = runtime.create_state_reporter(cfg, 'c.json', 60)
        try:
            self.assertEqual(reporter.state.get('daemon_version'), __version__)
        finally:
            reporter.close()

    def test_old_daemon_state_still_works(self):
        from jira_gigacode import runtime

        class OldReporter:
            def __init__(self, path, project, config_path=None, poll_interval=None, name=None, jira_url=None):
                self.path, self.state = path, {}

            def attach_logging(self):
                pass

            def emit(self, stage, issue=None, **detail):
                if stage not in ('polling', 'jira', 'git'):
                    raise ValueError(stage)
                self.state['stage'] = stage
        with mock.patch.object(runtime, 'StateReporter', OldReporter), mock.patch.object(runtime, 'LOGS_DIR', self.tmp):
            reporter = runtime.create_state_reporter({'jira': {'project': 'T'}}, None, 60)
            self.assertEqual(reporter.state['daemon_version'], __version__)
            with mock.patch.object(runtime, 'state', reporter):
                runtime.emit('reviewing', 'T-1')
                self.assertEqual(reporter.state['stage'], 'jira')
                runtime.emit('exploring', 'T-1')
                self.assertEqual(reporter.state['stage'], 'polling')

class MaintenanceRestoreTest(SupervisorBase):
    def test_restore_does_not_start_previously_stopped_config(self):
        self.add_config('active')
        self.add_config('paused')
        self.sup.restore_active = {'active'}
        self.sup.tick()
        self.assertIsNotNone(self.sup.daemons['active'].proc)
        self.assertIsNone(self.sup.daemons['paused'].proc)
        self.assertEqual(self.sup.daemons['paused'].status, 'stopped')
        self.assertIsNone(self.sup.restore_active)
