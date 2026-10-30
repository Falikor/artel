"""Cooperative drain and in-place restart, preserving argv, environment and cwd."""
import atexit
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / '.artel-maintenance'
REQUEST = DIRECTORY / 'request.json'
_session = None


def write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    tmp.write_text(json.dumps(value), encoding='utf-8')
    os.replace(tmp, path)


def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


from .platform_support import pid_alive as alive


def register(role):
    global _session
    _session = {'pid': os.getpid(), 'parent': os.getppid(), 'role': role, 'ready': None}
    path = DIRECTORY / (str(os.getpid()) + '.json')
    write(path, _session)
    atexit.register(lambda: path.unlink(missing_ok=True))


def requested():
    return REQUEST.exists()


def checkpoint(running=lambda: True, before_wait=None):
    if _session is None:
        return
    request = read(REQUEST)
    if not request:
        return
    token = request['token']
    if before_wait:
        before_wait()
    _session['ready'] = token
    write(DIRECTORY / (str(os.getpid()) + '.json'), _session)
    parent = read(DIRECTORY / (str(os.getppid()) + '.json'))
    supervised = _session['role'] == 'daemon' and parent and parent['role'] == 'supervisor'
    while requested():
        current = read(REQUEST)
        if supervised and current and current.get('phase') == 'stop':
            raise SystemExit(0)
        if not running():
            raise SystemExit(0)
        time.sleep(.25)
    if supervised:
        _session['ready'] = None
        write(DIRECTORY / (str(os.getpid()) + '.json'), _session)
        return  # Drain was cancelled; keep the parent's Popen ownership.
    restart()


def restart():
    (DIRECTORY / (str(os.getpid()) + '.json')).unlink(missing_ok=True)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def drain_supervisor(supervisor):
    request = read(REQUEST)
    if not request or _session is None:
        return
    token = request['token']
    active = [d.name for d in supervisor.daemons.values() if not d.removed and d.status != 'stopped']
    stopped = False
    while requested() and supervisor.running:
        children = [d.proc for d in supervisor.daemons.values() if d.proc and d.proc.poll() is None]
        ready = all((read(DIRECTORY / (str(p.pid) + '.json')) or {}).get('ready') == token for p in children)
        current = read(REQUEST)
        stopped = bool(current and current.get('phase') == 'stop' and not children)
        _session.update(ready=token if ready else None, stopped=stopped)
        write(DIRECTORY / (str(os.getpid()) + '.json'), _session)
        time.sleep(.25)
    if stopped:
        os.environ['ARTEL_RESTORE_ACTIVE'] = json.dumps(active)
        restart()
    _session.update(ready=None, stopped=False)
    write(DIRECTORY / (str(os.getpid()) + '.json'), _session)
