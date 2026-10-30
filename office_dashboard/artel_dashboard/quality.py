"""Что стало со сданными задачами — по данным ретроспективы демонов.

Источники в logs/:
  {id}-delivered.jsonl — каждая сданная задача (пишет демон при сдаче);
  {id}-outcomes.json   — исход, который нашла ретроспектива (слита, правили ли люди, брошена…).

Категории задачи:
  as_is    — слита без правок людей (merge как есть или squash без отличий от работы демона);
  changed  — слита, но люди правили код (коммиты поверх ветки или squash с отличиями);
  dropped  — ветку удалили без слияния;
  open     — проверена, но ещё не слита;
  waiting  — сдана, ретроспектива её ещё не проверяла (или задачу сдали заново после проверки);
  unknown  — коммита демона больше нет (история переписана).
Доля «без правок» считается по задачам с исходом: as_is / (as_is + changed + dropped).
"""
import glob
import json
import os
import time

CATEGORIES = ('as_is', 'changed', 'dropped', 'open', 'waiting', 'unknown')
RESOLVED = ('as_is', 'changed', 'dropped')
WEEK = 7 * 86400


def _deliveries(path):
    latest = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get('issue') and e.get('at'):
                    latest[e['issue']] = e
    except OSError:
        pass
    return latest


def _outcomes(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def category(outcome):
    if not outcome:
        return 'waiting'
    kind = outcome.get('outcome')
    if kind in ('merged', 'merged_changed', 'squashed'):
        return 'changed' if outcome.get('changed') else 'as_is'
    if kind == 'dropped':
        return 'dropped'
    if kind == 'open':
        return 'open'
    return 'unknown'


def load_rows(logs_dir):
    """Строка на каждую сданную задачу каждого демона (последняя сдача задачи)."""
    rows = []
    for path in glob.glob(os.path.join(logs_dir, '*-delivered.jsonl')):
        daemon_id = os.path.basename(path)[:-len('-delivered.jsonl')].lower()
        outcomes = _outcomes(os.path.join(logs_dir, f'{daemon_id}-outcomes.json'))
        for issue, e in _deliveries(path).items():
            o = outcomes.get(issue)
            if o and o.get('head') and e.get('head') and o['head'] != e['head']:
                o = None   # задачу сдали заново после проверки — исход относится к прошлой сдаче
            rows.append({
                'id': daemon_id, 'issue': issue, 'service': e.get('service') or (o or {}).get('service'),
                'branch': e.get('branch'), 'head': e.get('head'), 'base': e.get('base'),
                'delivered_at': e['at'], 'checked_at': (o or {}).get('checked_at'), 'category': category(o),
                'human_commits': (o or {}).get('human_commits') or 0, 'human_lines': (o or {}).get('human_lines') or 0,
                'followups': (o or {}).get('followups') or 0, 'jira_status': (o or {}).get('jira_status'),
            })
    rows.sort(key=lambda r: r['delivered_at'], reverse=True)
    return rows


def _counts(rows):
    c = {k: 0 for k in CATEGORIES}
    for r in rows:
        c[r['category']] += 1
    resolved = sum(c[k] for k in RESOLVED)
    c['total'] = len(rows)
    c['resolved'] = resolved
    c['as_is_share'] = round(c['as_is'] / resolved, 4) if resolved else None
    c['followups'] = sum(1 for r in rows if r['followups'])
    c['human_lines'] = sum(r['human_lines'] for r in rows if r['category'] == 'changed')
    return c


def week_start(ts):
    """Понедельник 00:00 по местному времени для момента ts."""
    t = time.localtime(ts)
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    return midnight - t.tm_wday * 86400


def summarize(rows, since=0, daemon_id='', now=None, max_weeks=12):
    """Итоги для вкладки «Статистика»: всего, по неделям сдачи и по демонам/сервисам."""
    now = now if now is not None else time.time()
    rows = [r for r in rows if r['delivered_at'] >= since and (not daemon_id or r['id'] == daemon_id)]
    first_week = week_start(now) - (max_weeks - 1) * WEEK
    if since:
        first_week = max(first_week, week_start(since))
    weeks = []
    t = first_week
    while t <= now:
        # time.mktime через календарь: неделя с переходом на летнее время не съезжает на час
        nxt = week_start(t + WEEK + 3 * 3600)
        part = [r for r in rows if t <= r['delivered_at'] < nxt]
        weeks.append(dict(_counts(part), start=t))
        t = nxt
    groups = {}
    for r in rows:
        groups.setdefault((r['id'], r['service'] or ''), []).append(r)
    by_daemon = [dict(_counts(items), id=key[0], service=key[1] or None)
                 for key, items in sorted(groups.items())]
    checks = [r['checked_at'] for r in rows if r['checked_at']]
    return {'totals': _counts(rows), 'weeks': weeks, 'by_daemon': by_daemon,
            'last_check': max(checks) if checks else None, 'since': since}
