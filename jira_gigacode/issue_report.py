"""Факты о текущей обработке задачи для комментария-отчёта (ветка, деплой, статус, токены).

Отдельный маленький модуль: в него пишут jira_client, jenkins, review и pipeline, а читает reports.
"""
import time

from .logs import _issue_errors


# Метка автоотчёта: по ней демон пропускает свои комментарии при поиске маркера базовой ветки
ARTEL_REPORT_TAG = 'Артель демонов · автоотчёт'

_REPORT = {}  # issue_key -> факты текущего прохода (ветка, деплой, ревью, статус, токены…)


def report_start(issue_key):
    _REPORT[issue_key] = {'started_at': time.time()}
    _issue_errors.reset(issue_key)


def report_set(issue_key, **fields):
    _REPORT.setdefault(issue_key, {'started_at': time.time()}).update(fields)


def report_add_tokens(issue_key, usage):
    """Складывает расход токенов всех прогонов по задаче (генерация, ревью, доработка)."""
    if not usage:
        return
    total = _REPORT.setdefault(issue_key, {'started_at': time.time()}).setdefault('tokens', {})
    for k in ('input', 'output', 'cached', 'total'):
        if usage.get(k):
            total[k] = (total.get(k) or 0) + int(usage[k])
    total['source'] = usage.get('source') or total.get('source')
