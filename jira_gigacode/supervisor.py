"""Супервизор Артели: запускает демонов по config/*.json, перезапускает упавших, показывает статус.

    python3 artel.py up [--no-browser] — дашборд + все демоны, открыть браузер
    python3 artel.py down             — остановить дашборд и всех демонов
    python3 artel.py start            — запустить супервизор в фоне (он поднимет всех демонов)
    python3 artel.py run              — то же, но в этом терминале (для launchd/systemd)
    python3 artel.py status           — кто работает, что делает, сколько раз падал, какая версия
    python3 artel.py restart [имя…]   — перезапустить демонов (все, по имени конфига, или --outdated)
    python3 artel.py stop             — остановить супервизор и всех демонов
    python3 artel.py check            — проверить окружение всех конфигов (--check каждого демона)
    python3 artel.py archive          — повернуть большие логи и убрать старые логи GigaCode в архив сейчас
                                        (logs/archive/ГГГГ-ММ/*.gz; без команды — раз в 10 минут)
    python3 artel.py memory list ПУТЬ [--disputed] [--config КОНФИГ]
    python3 artel.py memory retry ПУТЬ ID [--config КОНФИГ]
    python3 artel.py pr list ИНСТАНС | retry/skip ИНСТАНС ID
    python3 artel.py memory approve ПУТЬ ID --evidence ОСНОВАНИЕ [--scope ОБЛАСТЬ] [--replaces ID]
    python3 artel.py memory reject ПУТЬ ID
    python3 artel.py memory sweep ПУТЬ [--config КОНФИГ]
    python3 artel.py memory forget-explore [--dry-run]
                                      — убрать из memory/*.md уроки, записанные после исследования бэклога

Правила перезапуска:
  - демон упал — перезапуск через 5, 10, 20… секунд (не больше 5 минут); счётчик сбоев
    обнуляется, если демон проработал 30 минут;
  - демон вышел с кодом 1 в первые 90 секунд — скорее всего, не прошёл проверку окружения:
    повтор через 5 минут, статус «ошибка конфига»;
  - демон остановили вручную (kill, код 0) — не перезапускается до `artel restart`;
  - новые конфиги подхватываются, удалённые останавливаются (раз в 30 секунд);
  - конфиг с "general": {"enabled": false} пропускается;
  - демон этого конфига уже работает вне супервизора (живой heartbeat) — второй не запускается.

Файлы в logs/: artel-supervisor.pid, artel-supervisor.json (состояние), artel-supervisor.log,
{конфиг}-stdout.log (вывод каждого демона), artel-restart-* (запросы на перезапуск),
archive/ГГГГ-ММ/ (старые логи, gzip, хранятся бессрочно).
"""
import glob
import json
import logging
from pathlib import Path
import os
import signal
import subprocess
import sys
import time

from . import __version__, log_archive, maintenance
from .base import LOGS_DIR, PROJECT_DIR
from .logs import SUPERVISED_ENV
from .config import instance_key

CONFIG_DIR = os.path.join(PROJECT_DIR, 'config')
ENTRY = os.path.join(PROJECT_DIR, 'jira_to_gigacode.py')
PID_FILE = os.path.join(LOGS_DIR, 'artel-supervisor.pid')
STATE_FILE = os.path.join(LOGS_DIR, 'artel-supervisor.json')
LOG_FILE = os.path.join(LOGS_DIR, 'artel-supervisor.log')
RESTART_PREFIX = os.path.join(LOGS_DIR, 'artel-restart-')

RESCAN_SECONDS = 30
ARCHIVE_SECONDS = 600
STABLE_SECONDS = 30 * 60       # столько проработал — сбои забываются
CONFIG_ERROR_WINDOW = 90       # код 1 в первые N секунд — ошибка окружения/конфига
CONFIG_ERROR_RETRY = 300
MAX_BACKOFF = 300
HEARTBEAT_STALE = 45

log = logging.getLogger('artel')
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter('%(asctime)s - artel - %(message)s'))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


# =====================================================================
# Вспомогательное
# =====================================================================
from .platform_support import pid_alive, session_options, kill_tree


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def supervisor_pid():
    """pid работающего супервизора или None."""
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def load_configs(config_dir=None):
    """[{'name', 'path', 'config' | None, 'problem'}] по config/*.json."""
    config_dir = config_dir or CONFIG_DIR
    items = []
    for path in sorted(glob.glob(os.path.join(config_dir, '*.json'))):
        name = os.path.splitext(os.path.basename(path))[0]
        item = {'name': name, 'path': path, 'config': None, 'problem': None}
        cfg = read_json(path)
        if not isinstance(cfg, dict):
            item['problem'] = 'конфиг не читается'
        elif (cfg.get('general') or {}).get('enabled') is False:
            item['problem'] = 'выключен (general.enabled = false)'
            item['config'] = cfg
        else:
            item['config'] = cfg
        items.append(item)
    return items


def daemon_state(cfg):
    """state.json демона этого конфига (пишет daemon_state.py) или {}."""
    try:
        return read_json(os.path.join(LOGS_DIR, f"{instance_key(cfg)}-state.json"), {}) or {}
    except Exception:
        return {}


def running_outside(cfg, own_pids):
    """pid демона этого конфига, если он работает не под супервизором (живой heartbeat)."""
    st = daemon_state(cfg)
    pid = st.get('pid')
    if (st.get('stage') != 'stopped' and pid and pid not in own_pids and pid_alive(pid)
            and time.time() - float(st.get('heartbeat') or 0) < HEARTBEAT_STALE):
        return pid
    return None


# =====================================================================
# Супервизор
# =====================================================================
class Daemon:
    def __init__(self, item):
        self.name, self.path, self.config = item['name'], item['path'], item['config']
        self.proc = None
        self.status = 'new'
        self.started_at = None
        self.next_start = 0.0
        self.restarts = 0
        self.crashes = []          # время недавних падений
        self.last_exit = None
        self.stopping = False      # мы сами попросили его остановиться
        self.restart_after_stop = False
        self.removed = False       # конфиг удалили/выключили — после остановки забыть
        self.stop_sent_at = None

    def snapshot(self):
        return {'name': self.name, 'config': os.path.relpath(self.path, PROJECT_DIR),
                'pid': self.proc.pid if self.proc and self.proc.poll() is None else None,
                'status': self.status, 'started_at': self.started_at, 'restarts': self.restarts,
                'last_exit': self.last_exit, 'next_start': self.next_start or None}


class Supervisor:
    def __init__(self, config_dir=None, entry=None, stop_timeout=None):
        self.config_dir, self.entry = config_dir or CONFIG_DIR, entry or ENTRY
        self.stop_timeout = stop_timeout if stop_timeout is not None else \
            int(os.environ.get('ARTEL_STOP_TIMEOUT') or 120)
        self.daemons = {}
        self.skipped = {}          # name -> причина
        self.running = True
        self.restart_all = False
        self.restore_active = set(json.loads(os.environ.pop("ARTEL_RESTORE_ACTIVE", "null"))) if "ARTEL_RESTORE_ACTIVE" in os.environ else None
        self.last_scan = 0.0
        self.last_archive = 0.0

    # --- жизненный цикл ---
    def run(self):
        other = supervisor_pid()
        if other and other != os.getpid():
            log.error(f"Супервизор уже работает (pid {other}). Статус: python3 artel.py status")
            return 1
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        stop_file = os.path.join(LOGS_DIR, 'artel-stop')
        if os.path.exists(stop_file):
            os.unlink(stop_file)
        self._signals()
        maintenance.register("supervisor")
        log.info(f"Супервизор Артели запущен (pid {os.getpid()}, версия демонов {__version__}).")
        try:
            while self.running:
                self.tick()
                time.sleep(1)
        finally:
            self.shutdown()
            try:
                if supervisor_pid() == os.getpid():
                    os.remove(PID_FILE)
            except OSError:
                pass
        log.info("Супервизор остановлен.")
        return 0

    def archive_logs(self, now):
        """Раз в 10 минут: большие логи (свой, stdout демонов, jira-agent.log) и старые логи GigaCode — в архив."""
        if now - self.last_archive < ARCHIVE_SECONDS:
            return
        self.last_archive = now
        try:
            log_archive.sweep(now=now)
        except Exception as e:  # архив не должен ронять супервизор
            log.warning(f"Архиватор логов: {e}")

    def _signals(self):
        def stop(signum, frame):
            log.info(f"Сигнал {signum}: останавливаю демонов…")
            self.running = False

        def restart(signum, frame):
            self.restart_all = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, restart)

    def tick(self, now=None):
        if os.path.exists(os.path.join(LOGS_DIR, 'artel-stop')):
            self.running = False
            return
        if maintenance.requested():
            maintenance.drain_supervisor(self)
            return
        now = now if now is not None else time.time()
        if now - self.last_scan >= RESCAN_SECONDS or not self.daemons and not self.skipped:
            self.scan(now)
        self._handle_restart_requests()
        for d in list(self.daemons.values()):
            if d.proc is not None and d.proc.poll() is not None:
                self._on_exit(d, d.proc.returncode, now)
            if d.proc is None:
                if d.removed:
                    del self.daemons[d.name]
                    continue
                if d.status in ('new', 'backoff', 'config_error', 'restarting', 'external') and now >= d.next_start:
                    self.start(d, now)
            elif d.stopping and d.stop_sent_at and now - d.stop_sent_at > self.stop_timeout:
                log.warning(f"[{d.name}] Не остановился за {self.stop_timeout} с — SIGKILL.")
                if os.name == 'nt':
                    kill_tree(d.proc.pid, force=True)
                else:
                    d.proc.kill()
            if d.proc is not None and d.status == 'running' and d.started_at and now - d.started_at > STABLE_SECONDS:
                d.crashes = []
        self.archive_logs(now)
        self.save_state()

    def scan(self, now):
        self.last_scan = now
        seen = set()
        self.skipped = {}
        for item in load_configs(self.config_dir):
            if item['problem']:
                self.skipped[item['name']] = item['problem']
                if item['name'] in self.daemons:
                    self._retire(self.daemons[item['name']], item['problem'])
                continue
            seen.add(item['name'])
            if item['name'] not in self.daemons:
                log.info(f"[{item['name']}] Новый конфиг: {item['path']}")
                self.daemons[item['name']] = Daemon(item)
                if self.restore_active is not None and item['name'] not in self.restore_active:
                    self.daemons[item['name']].status = 'stopped'
            else:
                self.daemons[item['name']].config = item['config']
        self.restore_active = None
        for name, d in self.daemons.items():
            if name not in seen and not d.removed:
                self._retire(d, 'конфиг удалён')

    def _retire(self, d, why):
        log.info(f"[{d.name}] {why} — останавливаю.")
        d.removed = True
        self.stop_daemon(d)

    def start(self, d, now=None):
        now = now if now is not None else time.time()
        own = {x.proc.pid for x in self.daemons.values() if x.proc}
        outside = running_outside(d.config, own)
        if outside:
            if d.status != 'external':
                log.warning(f"[{d.name}] Демон этого конфига уже работает вне супервизора (pid {outside}) — "
                            f"второй не запускаю.")
            d.status, d.next_start = 'external', now + RESCAN_SECONDS
            return
        log_path = os.path.join(LOGS_DIR, f"{d.name}-stdout.log")
        out = open(log_path, 'a', encoding='utf-8')
        try:
            d.proc = subprocess.Popen([sys.executable, self.entry, d.path], cwd=PROJECT_DIR, stdout=out,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      env=dict(os.environ, PYTHONUNBUFFERED='1', PYTHONUTF8='1', **{SUPERVISED_ENV: '1'}))
        finally:
            out.close()
        if d.status != 'new':
            d.restarts += 1
        d.status, d.started_at, d.stopping, d.stop_sent_at = 'running', now, False, None
        log.info(f"[{d.name}] Запущен (pid {d.proc.pid}), вывод: {log_path}")

    def stop_daemon(self, d, restart=False):
        d.restart_after_stop = restart
        if d.proc is None or d.proc.poll() is not None:
            if restart:
                d.status, d.next_start = 'restarting', 0
            return
        d.stopping = True
        d.stop_sent_at = time.time()
        try:
            if os.name == 'nt':
                from .config import instance_key
                keys = [os.path.basename(path)[:-len('-state.json')]
                        for path in glob.glob(os.path.join(LOGS_DIR, '*-state.json'))
                        if read_json(path, {}).get('pid') == d.proc.pid]
                for key in keys or [instance_key(d.config)]:
                    Path(os.path.join(LOGS_DIR, key + '-stop')).touch()
            else:
                d.proc.terminate()
        except ProcessLookupError:
            pass

    def _on_exit(self, d, code, now):
        uptime = now - (d.started_at or now)
        d.last_exit, d.proc = code, None
        if d.stopping:
            d.stopping = False
            if d.restart_after_stop:
                d.restart_after_stop = False
                d.status, d.next_start = 'restarting', now
                log.info(f"[{d.name}] Остановлен для перезапуска.")
            else:
                d.status = 'stopped'
                log.info(f"[{d.name}] Остановлен.")
            return
        if code == 0:
            d.status = 'stopped'
            log.info(f"[{d.name}] Демон завершился сам (код 0) — не перезапускаю. Запустить: artel restart {d.name}")
            return
        if code == 1 and uptime < CONFIG_ERROR_WINDOW:
            d.status, d.next_start = 'config_error', now + CONFIG_ERROR_RETRY
            log.error(f"[{d.name}] Не прошёл проверку окружения (код 1) — повтор через {CONFIG_ERROR_RETRY // 60} мин. "
                      f"Подробности: python3 jira_to_gigacode.py {os.path.relpath(d.path, PROJECT_DIR)} --check")
            return
        d.crashes = [t for t in d.crashes if now - t < STABLE_SECONDS] + [now]
        delay = min(MAX_BACKOFF, 5 * 2 ** (len(d.crashes) - 1))
        d.status, d.next_start = 'backoff', now + delay
        log.error(f"[{d.name}] Упал (код {code}, проработал {int(uptime)} с) — перезапуск через {delay} с.")

    def _handle_restart_requests(self):
        names = []
        if self.restart_all:
            self.restart_all = False
            names.append('all')
        for path in glob.glob(RESTART_PREFIX + '*'):
            names.append(os.path.basename(path)[len(os.path.basename(RESTART_PREFIX)):])
            try:
                os.remove(path)
            except OSError:
                pass
        for name in names:
            targets = list(self.daemons.values()) if name == 'all' else \
                [d for d in self.daemons.values() if d.name == name]
            if name == 'outdated':
                targets = [d for d in self.daemons.values()
                           if daemon_state(d.config).get('daemon_version') not in (None, __version__)]
            for d in targets:
                log.info(f"[{d.name}] Перезапуск по запросу.")
                d.crashes = []
                self.stop_daemon(d, restart=True)

    def shutdown(self):
        for d in self.daemons.values():
            self.stop_daemon(d)
        deadline = time.time() + self.stop_timeout
        while time.time() < deadline and any(d.proc and d.proc.poll() is None for d in self.daemons.values()):
            time.sleep(0.5)
        for d in self.daemons.values():
            if d.proc and d.proc.poll() is None:
                log.warning(f"[{d.name}] Не остановился за {self.stop_timeout} с — SIGKILL.")
                if os.name == 'nt':
                    kill_tree(d.proc.pid, force=True)
                else:
                    d.proc.kill()
                d.proc.wait(timeout=10)
            if d.proc is not None:
                d.last_exit, d.proc = d.proc.returncode, None
            d.status = 'stopped'
        self.save_state(running=False)

    def save_state(self, running=True):
        try:
            write_json(STATE_FILE, {
                'pid': os.getpid() if running else None, 'version': __version__, 'updated': time.time(),
                'daemons': [d.snapshot() for d in self.daemons.values()],
                'skipped': self.skipped,
            })
        except OSError as e:
            log.warning(f"Не удалось записать {STATE_FILE}: {e}")


# =====================================================================
# Команды artel.py
# =====================================================================
STATUS_TEXT = {
    'running': 'работает', 'backoff': 'упал, жду перезапуска', 'config_error': 'ошибка конфига',
    'stopped': 'остановлен', 'restarting': 'перезапускается', 'new': 'запускается',
    'external': 'работает вне супервизора',
}
STAGE_TEXT = {
    'starting': 'запуск', 'polling': 'смотрит Jira', 'idle': 'ждёт задач', 'generating': 'пишет код',
    'reviewing': 'ревью', 'rework': 'доработка', 'git': 'git push', 'jenkins': 'деплой', 'jira': 'перевод задачи',
    'exploring': 'изучает бэклог', 'retro': 'ретроспектива', 'success': 'готово', 'error': 'ошибка', 'stopped': 'остановлен',
}


def status_rows():
    """Строки статуса: по конфигам, с данными супервизора и state.json демонов."""
    sup = read_json(STATE_FILE, {}) if supervisor_pid() else {}
    managed = {d['name']: d for d in (sup.get('daemons') or [])}
    rows = []
    for item in load_configs():
        cfg = item['config'] or {}
        st = daemon_state(cfg) if item['config'] else {}
        m = managed.get(item['name'], {})
        alive = st.get('pid') and pid_alive(st.get('pid')) and st.get('stage') != 'stopped'
        if item['problem']:
            status = item['problem']
        elif m:
            status = STATUS_TEXT.get(m.get('status'), m.get('status'))
        else:
            status = 'работает вне супервизора' if alive else 'не запущен'
        version = st.get('daemon_version') if alive else None
        rows.append({
            'name': (cfg.get('general') or {}).get('name') or item['name'],
            'config': os.path.relpath(item['path'], PROJECT_DIR),
            'pid': (m.get('pid') or (st.get('pid') if alive else None)),
            'status': status,
            'stage': STAGE_TEXT.get(st.get('stage'), st.get('stage') or '') if alive else '',
            'issue': (st.get('issue') or '') if alive else '',
            'restarts': m.get('restarts', 0),
            'version': version or ('?' if alive else ''),
            'outdated': bool(alive and version != __version__),
        })
    return sup, rows


def print_status():
    sup, rows = status_rows()
    pid = supervisor_pid()
    print(f"Супервизор: {'работает, pid ' + str(pid) if pid else 'не запущен'} · версия кода демонов {__version__}")
    if not rows:
        print(f"Конфигов нет: положите их в {CONFIG_DIR}")
        return 0
    header = ('ДЕМОН', 'КОНФИГ', 'PID', 'СОСТОЯНИЕ', 'ЭТАП', 'ЗАДАЧА', 'ПЕРЕЗАП.', 'ВЕРСИЯ')
    table = [header] + [(r['name'], r['config'], str(r['pid'] or '—'), r['status'], r['stage'] or '—',
                         r['issue'] or '—', str(r['restarts']),
                         (r['version'] or '—') + (' ⚠ устарел' if r['outdated'] else '')) for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for row in table:
        print('  '.join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    if any(r['outdated'] for r in rows):
        print("\n⚠ Часть демонов работает на старой версии кода. Перезапустить их: python3 artel.py restart --outdated")
    return 0


def cmd_start():
    pid = supervisor_pid()
    if pid:
        print(f"Супервизор уже работает (pid {pid}).")
        return print_status()
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as out:
        subprocess.Popen([sys.executable, os.path.join(PROJECT_DIR, 'artel.py'), 'run'], cwd=PROJECT_DIR,
                         stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **session_options(detached=True),
                         env=dict(os.environ, PYTHONUNBUFFERED='1', PYTHONUTF8='1'))
    for _ in range(20):
        time.sleep(0.25)
        if supervisor_pid():
            break
    if not supervisor_pid():
        print(f"Супервизор не запустился — смотрите {LOG_FILE}")
        return 1
    time.sleep(1.5)
    print(f"Супервизор запущен. Журнал: {LOG_FILE}")
    return print_status()


def cmd_stop(timeout=None):
    pid = supervisor_pid()
    if not pid:
        print("Супервизор не запущен.")
        return 0
    timeout = timeout or int(os.environ.get('ARTEL_STOP_TIMEOUT') or 120) + 15
    if os.name == 'nt':
        Path(os.path.join(LOGS_DIR, 'artel-stop')).touch()
    else:
        os.kill(pid, signal.SIGTERM)
    print(f"Останавливаю супервизор (pid {pid}) и демонов…", end='', flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline and pid_alive(pid):
        time.sleep(0.5)
        print('.', end='', flush=True)
    print(' готово.' if not pid_alive(pid) else f' не остановился за {timeout} с.')
    return 0 if not pid_alive(pid) else 1


def cmd_restart(names):
    if not supervisor_pid():
        print("Супервизор не запущен: python3 artel.py start")
        return 1
    known = {item['name'] for item in load_configs()}
    targets = ['outdated' if n == '--outdated' else n for n in names] or ['all']
    for name in targets:
        if name not in ('all', 'outdated') and name not in known:
            print(f"Нет конфига {name}.json в {CONFIG_DIR}")
            return 1
        os.makedirs(LOGS_DIR, exist_ok=True)
        open(RESTART_PREFIX + name, 'w').close()
    print("Запрос на перезапуск отправлен: " + ', '.join(targets))
    return 0


def cmd_check():
    worst = 0
    for item in load_configs():
        if item['problem']:
            print(f"·  {item['name']}: {item['problem']}")
            continue
        proc = subprocess.run([sys.executable, ENTRY, item['path'], '--check'], cwd=PROJECT_DIR,
                              capture_output=True, text=True)
        mark = '✅' if proc.returncode == 0 else '❌'
        worst = max(worst, proc.returncode)
        print(f"{mark} {item['name']}")
        for line in proc.stdout.splitlines():
            if '❌' in line or '⚠️' in line:
                print('     ' + line.split(' - ', 2)[-1].strip())
    return 1 if worst else 0


def memory_files():
    """Файлы опыта всех демонов: memory/*.md и папки из memory.path конфигов (с учётом сервисов)."""
    from .experience import memory_path
    from .routing import config_for_service, services
    dirs = {os.path.join(PROJECT_DIR, 'memory')}
    for item in load_configs():
        cfg = item['config']
        if not isinstance(cfg, dict):
            continue
        for c in [cfg] + [config_for_service(cfg, svc) for svc in services(cfg)]:
            try:
                dirs.add(os.path.dirname(memory_path(c)))
            except Exception:
                pass
    legacy = {p for d in dirs for p in glob.glob(os.path.join(d, '*.md')) if not p.endswith('.rules.md')}
    stores = {p[:-len('.store.json')] for d in dirs for p in glob.glob(os.path.join(d, '*.store.json'))}
    return sorted(legacy | stores)


def cmd_archive():
    done = log_archive.sweep()
    print(f"Заархивировано файлов: {len(done)}" + ''.join(f"\n  {p}" for p in done))
    rows = log_archive.summary()
    if rows:
        print(f"\nАрхив {log_archive.archive_dir()}:")
        for month, count, size in rows:
            print(f"  {month}: {count} файл(ов), {size / 1024 / 1024:.1f} МБ")
    return 0


def cmd_memory(args):
    from .experience import forget_source
    if args and args[0] in ('list', 'approve', 'reject', 'sweep', 'retry'):
        from .memory_store import command
        return command(args)
    if not args or args[0] != 'forget-explore':
        print("Использование: python3 artel.py memory forget-explore [--dry-run]", file=sys.stderr)
        return 2
    dry = '--dry-run' in args[1:]
    total = 0
    for path in memory_files():
        n = forget_source(path, 'исследование', dry_run=dry)
        if n:
            total += n
            print(f"{'найдено' if dry else 'убрано'} записей: {n:3d}  {os.path.relpath(path, PROJECT_DIR)}")
    if not total:
        print("Записей из исследования бэклога в файлах опыта нет.")
    elif dry:
        print(f"Всего {total}. Убрать: python3 artel.py memory forget-explore")
    else:
        print(f"Готово, убрано {total}. Прежние версии файлов — рядом, *.md.bak")
    return 0


USAGE = __doc__.split('Правила перезапуска:')[0].strip()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ('up', 'down'):
        from .launcher import command
        return command(cmd, rest)
    if cmd == 'run':
        return Supervisor().run()
    if cmd == 'start':
        return cmd_start()
    if cmd == 'stop':
        return cmd_stop()
    if cmd == 'status':
        return print_status()
    if cmd == 'restart':
        return cmd_restart(rest)
    if cmd == 'check':
        return cmd_check()
    if cmd == 'pr':
        from .pr_review import command
        return command(rest)
    if cmd == 'retry':
        from .retry_control import entries, decide, path_for
        if len(rest) < 2 or rest[0] not in ('list', 'block', 'pause', 'resume'):
            print('artel.py retry list ID | block/pause/resume ID ISSUE (pause: 1 час)')
            return 2
        path = path_for(LOGS_DIR, rest[1])
        if rest[0] == 'list':
            print(json.dumps(entries(path), ensure_ascii=False, indent=2))
            return 0
        if len(rest) != 3:
            print('Укажите ID демона и ключ задачи')
            return 2
        decide(path, rest[2], rest[0])
        print('Решение сохранено. Применится перед следующей попыткой; текущая работа не прерывается.')
        return 0
    if cmd == 'memory':
        return cmd_memory(rest)
    if cmd == 'archive':
        return cmd_archive()
    if cmd == '--version':
        print(__version__)
        return 0
    print(f"Неизвестная команда: {cmd}\n\n{USAGE}", file=sys.stderr)
    return 2
