"""Persistent operator switches, snapshotted at safe boundaries (not mid-task)."""
import copy
import json
import time
from pathlib import Path
from .base import LOGS_DIR
from .config import instance_key, resolve_param_bool
from .retry_control import transaction, path_for as checked_path

# key, env, default, label, dependency
FEATURES = (
    ('jira.enabled','JIRA_ENABLED',True,'Jira: получение и обработка задач',None),
    ('bitbucket.enabled','BITBUCKET_ENABLED',False,'Bitbucket: замечания к PR',None),
    ('memory.enabled','MEMORY_ENABLED',True,'Память: чтение и обучение',None),
    ('memory.auto_append','MEMORY_AUTO_APPEND',True,'Сохранять кандидатов на уроки','memory.enabled'),
    ('memory.auto_verify','MEMORY_AUTO_VERIFY',True,'Проверять уроки автоматически','memory.enabled'),
    ('review.enabled','REVIEW_ENABLED',True,'Независимое ревью кода',None),
    ('explore.enabled','EXPLORE_ENABLED',True,'Исследование бэклога','jira.enabled'),
    ('explore.learn','EXPLORE_LEARN',False,'Учиться при исследовании бэклога','explore.enabled'),
    ('retro.enabled','RETRO_ENABLED',True,'Ретроспектива сданных задач','jira.enabled'),
    ('jenkins.enabled','JENKINS_ENABLED',True,'Деплой Jenkins по лейблу задачи','jira.enabled'),
    ('requirements.enabled','REQUIREMENTS_ENABLED',True,'Ручные переделки постановки','jira.enabled'),
    ('dependencies.enabled','DEPENDENCIES_ENABLED',True,'Порядок связанных задач: бэкенд → фронтенд','jira.enabled'),
)


def path_for(logs, instance):
    return checked_path(logs, instance).with_name(instance + '-features.json')


def read(logs, instance):
    try:
        data = json.loads(path_for(logs, instance).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'revision':0, 'overrides':{}}
    if not isinstance(data, dict) or type(data.get('revision')) is not int or not isinstance(data.get('overrides'), dict):
        raise ValueError('Повреждены настройки функций')
    allowed = {f[0] for f in FEATURES}
    if any(k not in allowed or type(v) is not bool for k,v in data['overrides'].items()):
        raise ValueError('Некорректные переключатели функций')
    return data


def save(logs, instance, key, value, revision):
    if key not in {f[0] for f in FEATURES} or (value is not None and type(value) is not bool):
        raise ValueError('Неизвестная функция или значение')
    if type(revision) is not int:
        raise ValueError('Нужна версия настроек')
    with transaction(path_for(logs, instance)) as data:
        if data.get('revision',0) != revision:
            raise ValueError('Настройки изменены в другой вкладке. Обновите панель.')
        overrides = data.setdefault('overrides',{})
        if value is None:
            overrides.pop(key,None)
        else:
            overrides[key]=value
        data.update(revision=revision+1, updated_at=time.time())
    return read(logs,instance)


def enabled(config, key):
    spec = next(f for f in FEATURES if f[0] == key)
    return resolve_param_bool(spec[0], spec[1], config, spec[2])


def apply(config):
    from . import prompt_control
    data = read(LOGS_DIR, instance_key(config))
    cfg = copy.deepcopy(config)
    cfg.pop('_feature_flags', None)
    cfg.pop('_feature_revision', None)
    if data['revision'] or data['overrides']:
        cfg['_feature_flags'] = data['overrides']
        cfg['_feature_revision'] = data['revision']
    return prompt_control.apply(cfg, LOGS_DIR)


def effective(config):
    from .routing import services, config_for_service
    configs = [config_for_service(config,s) for s in services(config)] or [config]
    return [{'service':(c.get('general') or {}).get('service') or '',
             'values':{key:enabled(c,key) for key,*_ in FEATURES}} for c in configs]


def changed(config):
    from . import prompt_control
    return (read(LOGS_DIR, instance_key(config))['revision'] != config.get('_feature_revision',0)
            or prompt_control.changed(config, LOGS_DIR))
