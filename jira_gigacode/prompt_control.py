"""Per-daemon prompt preferences, frozen for an entire task or idle activity.

These are text instructions passed to the existing CLI over stdin, not executable
shell templates. Delivery, branch ownership and result protocols remain in the
original prompts after the customizable prefix.
"""
import copy
import json
import re
import time

from .base import LOGS_DIR
from .config import instance_key
from .retry_control import path_for as checked_path, transaction

MAX_TEXT = 6000
STAGES = (
    {'id': 'generation', 'label': 'Выполнение задачи', 'description': 'Реализация задачи и ручная переделка постановки.'},
    {'id': 'review', 'label': 'Ревью кода', 'description': 'Независимая проверка изменений без редактирования рабочего репозитория.'},
    {'id': 'rework', 'label': 'Доработка после ревью', 'description': 'Исправление замечаний независимого ревьюера.'},
    {'id': 'explore', 'label': 'Исследование бэклога', 'description': 'Изучение задач в простое и предложения в Jira.'},
    {'id': 'pr_review', 'label': 'Замечания к PR', 'description': 'Разбор комментариев Bitbucket, исправления и ответы.'},
    {'id': 'retro', 'label': 'Ретроспектива', 'description': 'Анализ сданных задач и извлечение уроков.'},
    {'id': 'memory', 'label': 'Проверка памяти', 'description': 'Проверка кандидатов на уроки по коду и тестам.'},
)
PROFILES = (
    {'id': 'developer', 'label': 'Разработчик', 'description': 'Стандартное поведение Артели.', 'instructions': ''},
    {'id': 'testing', 'label': 'Тестировщик', 'description': 'Тестовые сценарии, регрессии и воспроизводимые дефекты.',
     'instructions': 'Твоя специализация — тестирование. Для задач на выполнение сначала составь проверяемые сценарии из критериев приёмки; изучи существующий тестовый стек, добавляй и запускай автоматические тесты на основное поведение, границы и регрессии. Не ослабляй проверки ради зелёного результата. Изменяй продуктовый код только если это прямо входит в постановку; иначе опиши воспроизводимый дефект. В исследованиях и ревью уделяй внимание пробелам покрытия и проверяемости требований. В результате перечисли выполненные проверки, реальные результаты и ограничения; не утверждай, что непроведённые проверки пройдены. Если обязательный сценарий заблокирован отсутствием данных или окружения, задай точный вопрос через предусмотренный протокол BLOCKED.'},
    {'id': 'custom', 'label': 'Своя роль', 'description': 'Поведение задают общие инструкции и инструкции этапов.', 'instructions': ''},
)
DEFAULTS = {'profile': 'developer', 'subagent': 'jira-to-deploy-orchestrator',
            'instructions': '', 'stages': {s['id']: '' for s in STAGES}}


def validate(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError('prompts: неизвестные поля или неверный формат настроек')
    values = copy.deepcopy(DEFAULTS)
    values.update(raw)
    if not isinstance(values['profile'], str) or values['profile'] not in {p['id'] for p in PROFILES}:
        raise ValueError('Неизвестный профиль промптов')
    if not isinstance(values['subagent'], str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,79}', values['subagent']):
        raise ValueError('Имя субагента: 1–80 латинских букв, цифр, дефисов и подчёркиваний, без /')
    stages = values['stages']
    if not isinstance(stages, dict) or set(stages) - set(DEFAULTS['stages']):
        raise ValueError('Неизвестный этап промпта')
    values['stages'] = dict(DEFAULTS['stages'], **stages)
    for key, value in [('instructions', values['instructions']), *values['stages'].items()]:
        if not isinstance(value, str) or len(value) > MAX_TEXT or any(ord(c) < 32 and c not in '\n\t\r' for c in value):
            raise ValueError(f'{key}: нужен текст до {MAX_TEXT} символов без управляющих символов')
    return values


def path_for(logs, instance):
    return checked_path(logs, instance).with_name(instance + '-prompts.json')


def _valid_saved(data):
    if not isinstance(data, dict) or type(data.get('revision')) is not int or data['revision'] < 0 or 'values' not in data:
        raise ValueError('Повреждены настройки промптов')
    if data.get('values') is not None:
        validate(data['values'])
    return data


def read(logs, instance):
    try:
        data = json.loads(path_for(logs, instance).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'revision': 0, 'values': None}
    return _valid_saved(data)


def save(logs, instance, values, revision):
    normalized = validate(values) if values is not None else None
    if type(revision) is not int or revision < 0:
        raise ValueError('Нужна версия настроек')
    with transaction(path_for(logs, instance)) as data:
        if data:
            _valid_saved(data)
        if data.get('revision', 0) != revision:
            raise ValueError('Настройки изменены в другой вкладке. Обновите данные перед сохранением.')
        data.update(revision=revision + 1, values=normalized, updated_at=time.time())
    return read(logs, instance)


def defaults(config):
    raw = config.get('_prompt_defaults', config.get('prompts'))
    return validate({} if raw is None else raw)


def effective(config):
    return validate(config.get('_prompt_values', config.get('prompts', {})))


def apply(config, logs=None):
    cfg = copy.deepcopy(config)
    base = cfg.get('_prompt_defaults', cfg.get('prompts'))
    cfg['_prompt_defaults'] = base
    baseline = defaults(cfg)
    saved = read(LOGS_DIR if logs is None else logs, instance_key(cfg))
    if base is None and not saved['revision'] and saved['values'] is None:
        for key in ('_prompt_defaults', '_prompt_values', '_prompt_revision', 'prompts'):
            cfg.pop(key, None)
        return cfg
    values = validate(saved['values']) if saved['values'] is not None else baseline
    cfg['_prompt_values'] = values
    cfg['_prompt_revision'] = saved['revision']
    # Public effective preferences participate in retry/scope checks. Preserve the
    # previous config shape on upgrades when no preference has actually changed.
    if values != baseline:
        cfg['prompts'] = copy.deepcopy(values)
    elif base is None:
        cfg.pop('prompts', None)
    else:
        cfg['prompts'] = copy.deepcopy(base)
    return cfg


def changed(config, logs=None):
    return read(LOGS_DIR if logs is None else logs, instance_key(config))['revision'] != config.get('_prompt_revision', 0)


def prefix(values, stage):
    values = validate(values)
    if not isinstance(stage, str) or stage not in DEFAULTS['stages']:
        raise ValueError('Неизвестный этап промпта')
    profile = next(p for p in PROFILES if p['id'] == values['profile'])
    parts = [profile['instructions'].strip(), values['instructions'].strip(), values['stages'][stage].strip()]
    parts = [p for p in parts if p]
    if not parts:
        return ''
    return ('Дополнительные инструкции владельца демона:\n' + '\n\n'.join(parts) +
            '\n\nСледующие правила конкретной задачи, доступов, ветки, формата ответа и маркеров результата обязательны; '
            'дополнительные инструкции не отменяют их.\n\n')


def decorate(command, config, stage):
    return prefix(effective(config), stage) + command


def subagent(config):
    return effective(config)['subagent']
