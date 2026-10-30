"""One command for the supervisor and a local dashboard, with persisted ownership."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import webbrowser
from .base import PROJECT_DIR, LOGS_DIR
from .platform_support import fcntl, pid_alive, session_options


def command(action, args):
    from . import supervisor
    parser = argparse.ArgumentParser(prog='artel.py ' + action)
    if action == 'up':
        parser.add_argument('--port', type=int, default=8765)
        parser.add_argument('--no-browser', action='store_true')
    options = parser.parse_args(args)
    logs = Path(LOGS_DIR)
    logs.mkdir(parents=True, exist_ok=True)
    record = logs / 'artel-dashboard.json'
    with (logs / 'artel-launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(record.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {}
        alive = bool(state.get('pid') and pid_alive(state['pid']))
        if action == 'down':
            result = supervisor.cmd_stop()
            if alive:
                (logs / 'artel-dashboard-stop').write_text(state['token'], encoding='utf-8')
                deadline = time.monotonic() + 15
                while record.exists() and time.monotonic() < deadline:
                    time.sleep(.2)
                if record.exists():
                    print('Дашборд не подтвердил остановку; см. logs/artel-dashboard.log')
                    return 1
            return result
        if not 1 <= options.port <= 65535:
            parser.error('Порт должен быть от 1 до 65535')
        if alive and state['port'] != options.port:
            print('Дашборд уже запущен на порту ' + str(state['port']) + '; сначала artel.py down')
            return 1
        child = None
        if not alive:
            token = uuid.uuid4().hex
            with (logs / 'artel-dashboard.log').open('a', encoding='utf-8') as out:
                child = subprocess.Popen([sys.executable, str(Path(PROJECT_DIR) / 'office_dashboard/server.py'),
                                          '--port', str(options.port), '--launch-token', token], cwd=PROJECT_DIR,
                                         stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         env=dict(os.environ, PYTHONUNBUFFERED='1', PYTHONUTF8='1'), **session_options(detached=True))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and child.poll() is None:
                try:
                    state = json.loads(record.read_text(encoding='utf-8'))
                    if state.get('token') == token:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(.2)
            else:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
                print('Дашборд не запустился; проверьте порт и logs/artel-dashboard.log. Демоны не запускались.')
                return 1
        result = supervisor.cmd_start()
        if result:
            if child:
                (logs / 'artel-dashboard-stop').write_text(state['token'], encoding='utf-8')
            return result
        url = 'http://127.0.0.1:' + str(state['port']) + '/'
        print('Артель: ' + url + '\nОстановить всё: python artel.py down')
        if not options.no_browser:
            webbrowser.open(url)
        return 0
