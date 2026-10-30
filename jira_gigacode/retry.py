"""Повторные попытки: кулдаун после серии неудач и «осталось только перевести задачу».
"""
import json
import os
import time

from .base import logger
from . import retry_control


# --- Кулдаун повторных попыток: серия неудач -> пауза, чтобы не долбить одной ошибкой ---
RETRY_FAILURES_LIMIT = 2  # сколько неудач подряд включают кулдаун

_RETRY_STATE = {}         # issue_key -> {'fails': int, 'until': ts}; живёт в рамках процесса


def retry_blocked(issue_key, now=None):
    """True — задача на кулдауне, пропустить до его окончания."""
    st = retry_control.entries(control_path()).get(issue_key) if control_path() else _RETRY_STATE.get(issue_key)
    return bool(st and st.get('until', 0) > (now if now is not None else time.time()))


def note_retry_outcome(issue_key, ok, cooldown_seconds, now=None):
    """Фиксирует исход попытки; True — кулдаун только что включился."""
    if control_path():
        activated = retry_control.outcome(control_path(), issue_key, ok, cooldown_seconds, now)
        _RETRY_STATE[issue_key] = retry_control.entries(control_path())[issue_key]
        return activated
    st = _RETRY_STATE.setdefault(issue_key, {'fails': 0, 'until': 0})
    if ok:
        st['fails'] = 0
        st['until'] = 0
        return False
    st['fails'] += 1
    if st['fails'] >= RETRY_FAILURES_LIMIT:
        st['until'] = (now if now is not None else time.time()) + cooldown_seconds
        st['fails'] = 0
        return True
    return False


# --- «Осталось только перевести»: код уже в remote, перевод в Jira не удался ---
# Хранится в logs/{КЭ|проект}-pending-transitions.json, чтобы пережить перезапуск демона:
# иначе после рестарта задача снова ушла бы в генерацию с перезаписью ветки.
# Запись сохраняется до успешного перевода: пауза не должна запускать генерацию заново.
PENDING_TRANSITION_TTL = 24 * 3600

_pending_transitions_path = None


def control_path():
    if not _pending_transitions_path:
        return None
    if _pending_transitions_path.endswith('-pending-transitions.json'):
        return _pending_transitions_path[:-len('-pending-transitions.json')] + '-retries.json'
    return _pending_transitions_path + '.retries.json'


def set_pending_path(path):
    """Файл записей «осталось только перевести» (задаётся при старте по ключу инстанса)."""
    global _pending_transitions_path
    _pending_transitions_path = path


def _load_pending_transitions():
    if not _pending_transitions_path:
        return {}
    try:
        with open(_pending_transitions_path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('Некорректный журнал переводов Jira')
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning(f"Не удалось прочитать {_pending_transitions_path}: {e}")
        raise


def _save_pending_transitions(data):
    if not _pending_transitions_path:
        return
    tmp = _pending_transitions_path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _pending_transitions_path)
    except OSError as e:
        logger.warning(f"Не удалось сохранить {_pending_transitions_path}: {e}")
        raise


def pending_transition_add(issue_key):
    """True — запись новая (о застрявшем переводе ещё не сообщали)."""
    data = _load_pending_transitions()
    is_new = issue_key not in data
    data.setdefault(issue_key, time.time())
    _save_pending_transitions(data)
    return is_new


def pending_transition_done(issue_key):
    data = _load_pending_transitions()
    if data.pop(issue_key, None) is not None:
        _save_pending_transitions(data)


def pending_transition_active(issue_key, now=None):
    """True — код уже доставлен; пауза не должна возвращать задачу в генерацию."""
    data = _load_pending_transitions()
    since = data.get(issue_key)
    if since is None:
        return False
    return True
