"""Состояние демонов для офиса: state.json (демоны 2.x), разбор лога старых версий, последняя задача."""
import glob
import json
import os
import re
import time

from .common import HOSTNAME, pid_alive, tail_lines

LOST_AFTER_SEC = 45          # heartbeat state-файла пишется каждые 10 с
LOG_IDLE_LOST_SEC = 3 * 3600  # для режима «только лог»: без новых строк дольше — считаем пропавшим


def supervisor_alive(logs_dir):
    """True — супервизор Артели (artel.py) работает с этой папкой логов."""
    try:
        with open(os.path.join(logs_dir, 'artel-supervisor.pid')) as f:
            return pid_alive(int(f.read().strip()))
    except (OSError, ValueError):
        return False



def read_state_file(path, now):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    # id — имя файла ({КЭ|проект}-state.json): два демона одного Jira-проекта (разные КЭ) не сливаются,
    # и по нему же лежат poke-флажок и история демона
    data['id'] = os.path.basename(path)[:-len('-state.json')].lower()
    data.setdefault('project', data['id'].upper())
    data['source'] = 'state'
    stage = data.get('stage')
    age = now - float(data.get('heartbeat') or 0)
    alive = stage != 'stopped' and age < LOST_AFTER_SEC
    if alive and data.get('pid') and data.get('host') == HOSTNAME and not pid_alive(data['pid']):
        alive = False
    data['alive'] = alive
    data['heartbeat_age'] = round(age, 1)
    return data


# Разбор лога для инстансов без state-файла (старая версия скрипта)
LOG_LINE = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ - (\w+) - (.*)$')
LOG_RULES = [
    (re.compile(r'Запуск автономного мониторинга'), 'starting'),
    (re.compile(r'^JQL:'), 'polling'),
    (re.compile(r'Ожидание задач'), 'idle'),
    (re.compile(r'▶️ Обработка задачи (\S+?)\.*$'), 'generating'),
    (re.compile(r'GigaCode завершился с ошибкой|Истёк таймаут GigaCode|GigaCode не найден|Ошибка запуска GigaCode'), 'error'),
    (re.compile(r'Запуск пост-обработки'), 'git'),
    (re.compile(r"Лейбл jenkins_\* найден: стенд='([^']+)', миграция=(да|нет)"), 'jenkins'),
    (re.compile(r'Поиск пути к статусам'), 'jira'),
    (re.compile(r'✅ Цель достигнута'), 'success'),
    (re.compile(r'Нет безопасного перехода|Ошибка Git|Ошибка пуша|Не удалось создать ветку'), 'error'),
    (re.compile(r'Ошибка в основном цикле'), 'error'),
    (re.compile(r'Цикл мониторинга завершён'), 'stopped'),
]
ISSUE_IN_LINE = re.compile(r'^\[([A-Z][A-Z0-9_]*-\d+)\]')


def read_log_file(path, now):
    try:
        lines = tail_lines(path)
        mtime = os.path.getmtime(path)
    except Exception:
        return None
    project = os.path.basename(path)[:-len('-agent.log')]
    events, issue, last_error = [], None, None
    for line in lines:
        m = LOG_LINE.match(line)
        if not m:
            continue
        try:
            t = time.mktime(time.strptime(m.group(1), '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            continue
        level, msg = m.group(2), m.group(3)
        tagged = ISSUE_IN_LINE.match(msg)
        body = msg[tagged.end():].strip() if tagged else msg
        if level == 'ERROR':
            last_error = {'t': t, 'message': body[:300]}
        for rule, stage in LOG_RULES:
            rm = rule.search(body)
            if not rm:
                continue
            event = {'t': t, 'stage': stage}
            if stage == 'generating':
                issue = rm.group(1)
            elif stage in ('starting', 'polling', 'idle', 'stopped'):
                issue = None
            elif tagged:
                issue = tagged.group(1)
            if stage == 'jenkins':
                event.update(stand=rm.group(1), migration=rm.group(2) == 'да')
            if stage == 'error':
                event['message'] = body[:300]
            if issue:
                event['issue'] = issue
            # Повторная строка того же этапа подряд — не событие
            if not events or events[-1]['stage'] != stage or events[-1].get('issue') != event.get('issue'):
                events.append(event)
            break
    if not events:
        return None
    last = events[-1]
    stage = last['stage']
    age = now - mtime
    return {
        'id': project.lower(),
        'project': project.upper(),
        'source': 'log',
        'stage': stage,
        'stage_since': last['t'],
        'issue': last.get('issue'),
        'detail': {k: v for k, v in last.items() if k not in ('t', 'stage', 'issue', 'message')},
        'events': events[-40:],
        'last_error': last_error,
        'alive': stage != 'stopped' and age < LOG_IDLE_LOST_SEC,
        'heartbeat_age': round(age, 1),
    }

# ---------------------------------------------------------------- последняя задача демона
_last_task_cache = {}


def last_history_record(logs_dir, daemon_id):
    """Последняя закрытая задача из {id}-history.jsonl (читается только конец файла, с кэшем)."""
    path = os.path.join(logs_dir, f'{daemon_id}-history.jsonl')
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime, st.st_size)
    cached = _last_task_cache.get(path)
    if cached and cached[0] == key:
        return cached[1]
    record = None
    try:
        with open(path, 'rb') as f:
            f.seek(max(0, st.st_size - 16384))
            for line in reversed(f.read().decode('utf-8', errors='replace').splitlines()):
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if isinstance(data, dict) and data.get('finished_at'):
                    record = {'issue': data.get('issue'), 'finished_at': data['finished_at'], 'result': data.get('result')}
                    break
    except OSError:
        return None
    _last_task_cache[path] = (key, record)
    return record



def read_all(logs_dir, names=None, characters=None):
    """Все демоны из папки логов: {'now', 'daemons': [...]}. names/characters — хранилища из stores."""
    now = time.time()
    daemons = {}
    for path in glob.glob(os.path.join(logs_dir, '*-state.json')):
        data = read_state_file(path, now)
        if data:
            daemons[data['id']] = data
    for path in glob.glob(os.path.join(logs_dir, '*-agent.log')):
        project_id = os.path.basename(path)[:-len('-agent.log')].lower()
        if project_id in daemons:
            continue
        data = read_log_file(path, now)
        if data:
            daemons[data['id']] = data
    names = names.load() if names else {}
    for d in daemons.values():
        d['name'] = names.get(d['id']) or d.get('name') or None
        # Простой считается от последней реальной задачи (история), а не от последнего опроса Jira
        last = last_history_record(logs_dir, d['id'])
        res = d.get('last_result') or {}
        if res.get('t') and (not last or res['t'] > last['finished_at']):
            last = {'issue': res.get('issue'), 'finished_at': res['t'], 'result': res.get('result')}
        d['last_task'] = last
    if characters:
        characters.resolve(list(daemons.values()))
    return {'now': now, 'daemons': sorted(daemons.values(), key=lambda d: d['id'])}
