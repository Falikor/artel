"""История: запуски из history.jsonl (и по логам старых версий) → задачи Jira, предложения в простое,
стоимость, CSV."""
import csv
import glob
import io
import json
import os
import re
import time

from .common import tail_lines
from .daemons import ISSUE_IN_LINE, LOG_LINE


def task_cost(tokens, prices):
    """(стоимость | None, оценка_по_общему_числу). Кэш считается частью входящих токенов:
    вход по цене входа берётся без кэша, кэш — по своей цене. Если GigaCode сообщил только общее
    число токенов, оно оценивается по цене входа (помечается как оценка)."""
    if not tokens or not any(prices.get(k) for k in ('input', 'output', 'cached')):
        return None, False
    inp, out, cached = tokens.get('input'), tokens.get('output'), tokens.get('cached') or 0
    if inp is None and out is None:
        total = tokens.get('total')
        return (total * prices['input'] / 1e6, True) if total else (None, False)
    billable = max(0, (inp or 0) - cached)
    cached = min(cached, inp or cached)
    return (billable * prices['input'] + cached * prices['cached'] + (out or 0) * prices['output']) / 1e6, False


# ---------------------------------------------------------------- история задач
_log_history_cache = {}


def history_from_log(path):
    """История для инстансов без history.jsonl: восстанавливаем задачи по строкам лога."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (path, st.st_mtime, st.st_size)
    if key in _log_history_cache:
        return _log_history_cache[key]
    project = os.path.basename(path)[:-len('-agent.log')].upper()
    records, cur = [], None

    def close(result, t, message=None):
        nonlocal cur
        if not cur:
            return
        gen_end = cur.get('gen_end') or t
        records.append({
            'project': project, 'issue': cur['issue'], 'result': result,
            'started_at': cur['started_at'], 'finished_at': t,
            'gen_seconds': round(gen_end - cur['started_at'], 1), 'total_seconds': round(t - cur['started_at'], 1),
            'stand': cur.get('stand'), 'migration': cur.get('migration', False), 'branch': None,
            'message': message or cur.get('error'), 'source': 'log', 'tokens': cur.get('tokens'),
        })
        cur = None

    for line in tail_lines(path, 20 * 1024 * 1024):
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
        if '▶️ Переделка постановки' in body:
            close('ok' if cur and cur.get('post') else 'fail', t)
            continue
        start = re.search(r'▶️ Обработка задачи (\S+?)\.*$', body)
        if start:
            close('ok' if cur and cur.get('post') else 'fail', t)
            cur = {'issue': start.group(1), 'started_at': t}
            continue
        if not cur:
            continue
        if 'GigaCode успешно завершил' in body:
            cur['gen_end'] = t
        elif 'Запуск пост-обработки' in body:
            cur['post'] = True
            cur.setdefault('gen_end', t)
        elif level == 'ERROR':
            cur['error'] = body[:300]
            if 'Пропуск пост-обработки' in body or 'Ошибка Git' in body or 'Ошибка пуша' in body or 'Не удалось создать ветку' in body:
                close('fail', t, cur['error'])
            elif 'Нет безопасного перехода' in body or 'Превышен лимит шагов' in body or 'Ошибка перехода' in body:
                close('warn', t, cur['error'])
        tm = re.search(r'Токены GigaCode: всего (\d+)', body)
        if tm and cur:
            cur['tokens'] = {'total': int(tm.group(1)), 'input': None, 'output': None, 'source': 'log'}
        jm = re.search(r"Лейбл jenkins_\* найден: стенд='([^']+)', миграция=(да|нет)", body)
        if jm and cur:
            cur['stand'], cur['migration'] = jm.group(1), jm.group(2) == 'да'
        if cur and '✅ Цель достигнута' in body:
            close('warn' if cur.get('error') else 'ok', t)
    _log_history_cache.clear()
    _log_history_cache[key] = records
    return records


def read_history(logs_dir, since=0):
    records, covered = [], {}
    for path in glob.glob(os.path.join(logs_dir, '*-history.jsonl')):
        project_id = os.path.basename(path)[:-len('-history.jsonl')].lower()
        first = None
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(r, dict) or not r.get('finished_at'):
                        continue
                    r['id'] = project_id
                    started = r.get('started_at') or r['finished_at']
                    first = started if first is None else min(first, started)
                    if not r.get('request'):
                        records.append(r)
        except OSError:
            continue
        covered[project_id] = first
    # Задачи из лога — только до начала history.jsonl (старая версия скрипта или период до обновления)
    for path in glob.glob(os.path.join(logs_dir, '*-agent.log')):
        project_id = os.path.basename(path)[:-len('-agent.log')].lower()
        limit = covered.get(project_id)
        for r in history_from_log(path):
            if limit is None or r['finished_at'] < limit:
                records.append(dict(r, id=project_id))
    records = [r for r in records if r.get('finished_at', 0) >= since]
    records.sort(key=lambda r: r.get('finished_at', 0), reverse=True)
    return records



RESULT_LABELS = {'ok': 'готово', 'warn': 'с замечаниями', 'fail': 'ошибка', 'blocked': 'ждёт уточнения'}


def runs_cost(item, prices):
    """(стоимость | None, есть_оценка) задачи — сумма по попыткам (у каждой свои токены);
    для записи без попыток (предложение, старая история) — по её токенам."""
    runs = item.get('runs') or [item]
    total, estimate, counted = 0.0, False, False
    for run in runs:
        cost, est = task_cost(run.get('tokens') or {}, prices)
        if cost is not None:
            total += cost
            estimate = estimate or est
            counted = True
    return (total if counted else None), estimate


def history_csv(tasks, names, ci_ids, prices, language='ru'):
    """CSV задач для Excel (разделитель «;», BOM — чтобы Excel понял кириллицу): строка на задачу Jira,
    время, токены и стоимость — сумма всех попыток. names — {id: имя}, ci_ids — {id: КЭ}."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    english = language in ('en', 'en-US')
    headers = (['Daemon', 'CI / project', 'Service', 'Issue', 'Outcome', 'Attempts', 'Failed attempts',
                'Started', 'Finished', 'Generation, min', 'Total, min', 'Tokens', 'Input', 'Output', 'Cache',
                f"Cost, {prices['currency']}", 'Environment', 'Migration', 'Message'] if english else
               ['Демон', 'КЭ / проект', 'Сервис', 'Задача', 'Итог', 'Попыток', 'Неудачных', 'Начало', 'Окончание',
                'Генерация, мин', 'Всего, мин', 'Токены', 'Вход', 'Выход', 'Кэш', f"Стоимость, {prices['currency']}",
                'Стенд', 'Миграция', 'Сообщение'])
    labels = ({'ok': 'done', 'warn': 'with findings', 'fail': 'failed', 'blocked': 'awaiting clarification'}
              if english else RESULT_LABELS)
    w.writerow(headers)

    def fmt(ts):
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else ''

    for r in tasks:
        tokens = r.get('tokens') or {}
        cost, estimate = runs_cost(r, prices)
        key = (("CI " if english else "КЭ ") + str(ci_ids[r['id']])) if ci_ids.get(r['id']) else (r.get('project') or r['id'].upper())
        w.writerow([names.get(r['id'], ''), key, r.get('service') or '', r.get('issue'),
                    labels.get(r.get('result'), r.get('result')), r.get('attempts') or 1, r.get('failed_attempts') or 0,
                    fmt(r.get('started_at')), fmt(r.get('finished_at')),
                    round((r.get('gen_seconds') or 0) / 60, 1), round((r.get('total_seconds') or 0) / 60, 1),
                    tokens.get('total') or '', tokens.get('input') or '', tokens.get('output') or '',
                    tokens.get('cached') or '', ('≈' if estimate else '') + (f'{cost:.2f}'.replace('.', '.' if english else ',') if cost is not None else ''),
                    r.get('stand') or '', ('yes' if english else 'да') if r.get('migration') else '', r.get('message') or ''])
    return ('\ufeff' + buf.getvalue()).encode('utf-8')


# ---------------------------------------------------------------- задачи Jira (а не запуски)
def _sum_tokens(runs):
    """Токены задачи — сумма по всем попыткам. input/output/cached — только если их сообщили все
    попытки с токенами (иначе стоимость считается по попыткам, см. runs)."""
    with_tokens = [r['tokens'] for r in runs if isinstance(r.get('tokens'), dict) and r['tokens'].get('total')]
    if not with_tokens:
        return None
    out = {'total': sum(int(t.get('total') or 0) for t in with_tokens)}
    for key in ('input', 'output', 'cached'):
        if all(t.get(key) is not None for t in with_tokens):
            out[key] = sum(int(t.get(key) or 0) for t in with_tokens)
        else:
            out[key] = None
    return out


def group_tasks(records):
    """Запуски → задачи Jira. Одна задача демона — одна строка, сколько бы попыток ни было:
    итог — по последней попытке (2 ошибки и потом успех = успех), время и токены — сумма всех
    попыток, стенд и ветка — из последней удачной. Попытки — в runs (старые первыми)."""
    by_task = {}
    for r in sorted(records, key=lambda x: x.get('finished_at') or 0):
        if r.get('issue'):
            by_task.setdefault((r['id'], r['issue']), []).append(r)
    tasks = []
    for (daemon_id, issue), runs in by_task.items():
        last = runs[-1]
        good = [x for x in runs if x.get('result') in ('ok', 'warn')]
        best = good[-1] if good else last
        tasks.append({
            'id': daemon_id, 'issue': issue, 'project': last.get('project'),
            'service': last.get('service') or next((x.get('service') for x in reversed(runs) if x.get('service')), None),
            'result': last.get('result'), 'attempts': len(runs),
            'failed_attempts': sum(1 for x in runs if x.get('result') == 'fail'),
            'started_at': runs[0].get('started_at') or runs[0].get('finished_at'),
            'finished_at': last.get('finished_at'),
            'gen_seconds': round(sum(x.get('gen_seconds') or 0 for x in runs), 1),
            'total_seconds': round(sum(x.get('total_seconds') or 0 for x in runs), 1),
            'stand': best.get('stand'), 'migration': bool(best.get('migration')), 'branch': best.get('branch'),
            'message': last.get('message'), 'source': last.get('source'),
            'tokens': _sum_tokens(runs),
            'runs': [{k: x.get(k) for k in ('result', 'started_at', 'finished_at', 'gen_seconds', 'total_seconds',
                                            'tokens', 'message', 'stand')} for x in runs],
        })
    tasks.sort(key=lambda t: t.get('finished_at') or 0, reverse=True)
    return tasks


def read_tasks(logs_dir, since=0):
    """Задачи, последняя попытка которых закончилась не раньше since. Группировка — по всей истории:
    задача, начатая до периода и законченная в нём, попадает в период со всеми попытками."""
    return [t for t in group_tasks(read_history(logs_dir)) if (t.get('finished_at') or 0) >= since]


# ---------------------------------------------------------------- предложения в простое
def read_proposals(logs_dir, since=0):
    """Прогоны исследования бэклога из logs/{id}-proposals.jsonl (новые первыми)."""
    out = []
    for path in glob.glob(os.path.join(logs_dir, '*-proposals.jsonl')):
        daemon_id = os.path.basename(path)[:-len('-proposals.jsonl')].lower()
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and r.get('issue') and (r.get('finished_at') or 0) >= since:
                        out.append(dict(r, id=daemon_id))
        except OSError:
            continue
    out.sort(key=lambda r: r.get('finished_at') or 0, reverse=True)
    return out
