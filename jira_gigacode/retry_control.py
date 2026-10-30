"""Persistent, per-instance attempt ledger and operator decisions."""
import contextlib
from .platform_support import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time


def path_for(logs, instance):
    if not re.fullmatch(r'[a-z0-9_.-]+', instance):
        raise ValueError('Некорректный идентификатор демона')
    return Path(logs) / (instance + '-retries.json')


@contextlib.contextmanager
def transaction(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError('Некорректный журнал попыток')
        except FileNotFoundError:
            data = {}
        before = json.dumps(data, sort_keys=True)
        yield data
        if json.dumps(data, sort_keys=True) != before:
            fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix='.retries-')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(temp, path)
            finally:
                if os.path.exists(temp): os.unlink(temp)


def entries(path):
    with transaction(path) as data:
        return {key:dict(value) for key,value in data.items()}


def decide(path, key, action, seconds=3600):
    key = key.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', key):
        raise ValueError('Нужен ключ задачи, например ARTEL-123')
    if action not in ('block', 'pause', 'resume'):
        raise ValueError('Неизвестное действие')
    if action == 'pause' and (type(seconds) is not int or not 1 <= seconds <= 2592000):
        raise ValueError('Пауза должна быть от 1 секунды до 30 дней')
    with transaction(path) as data:
        row = data.setdefault(key, {})
        row.update(mode='blocked' if action == 'block' else 'paused' if action == 'pause' else 'auto',
                   decision_at=time.time(), approved=action == 'resume')
        if action == 'pause':
            row['pause_until'] = time.time() + seconds
        if action == 'resume':
            row.update(approved=True, until=0, fails=0, reason='', needs_review=False)
    return key


def begin(path, key, scope, pending=False, now=None):
    """Atomic claim and final decision check immediately before an attempt."""
    now = time.time() if now is None else now
    with transaction(path) as data:
        row = data.setdefault(key, {})
        if row.get('mode') == 'blocked':
            return 'Исключена владельцем'
        if row.get('mode') == 'paused' and row.get('pause_until', 0) > now:
            return 'Пауза владельца'
        approved = row.get('approved', False)
        if not approved:
            reason = ''
            if row.get('scope') and row['scope'] != scope:
                reason = 'Изменился конфиг или область поиска — подтвердите повтор'
            elif row.get('status') == 'running':
                reason = 'Предыдущая попытка прервана — подтвердите повтор'
            elif pending and not row.get('scope'):
                reason = 'Старый незавершённый перевод Jira — подтвердите повтор'
            if reason:
                row.update(reason=reason, needs_review=True)
                return reason
            if row.get('needs_review'):
                return row.get('reason') or 'Требуется решение владельца'
        if row.get('until', 0) > now:
            return 'Кулдаун после ошибок'
        row.update(scope=scope, approved=False, needs_review=False, reason='', status='running',
                   started_at=now, attempts=row.get('attempts',0)+1, kind='transition' if pending else 'task')
        return None


def outcome(path, key, ok, cooldown, now=None):
    now = time.time() if now is None else now
    with transaction(path) as data:
        row = data.setdefault(key, {})
        fails = 0 if ok else row.get('fails',0)+1
        activated = fails >= 2
        row.update(status='done' if ok else 'failed', finished_at=now,
                   fails=0 if activated else fails, until=now+cooldown if activated else 0)
        return activated
