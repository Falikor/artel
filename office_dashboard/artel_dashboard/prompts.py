"""Prompt editor API model; browser IDs resolve to configured local daemons."""
from pathlib import Path

from jira_gigacode import prompt_control as control
from jira_gigacode.config import instance_key
from jira_gigacode.supervisor import load_configs


def catalog():
    result = []
    seen = set()
    for item in load_configs():
        cfg = item['config']
        if not isinstance(cfg, dict):
            continue
        key = instance_key(cfg)
        if key not in seen:
            result.append({'id': key, 'project': (cfg.get('jira') or {}).get('project', ''),
                           'name': (cfg.get('general') or {}).get('name') or item.get('name') or key})
            seen.add(key)
    return result


def configuration(instance):
    configs = [item['config'] for item in load_configs()
               if isinstance(item.get('config'), dict) and instance_key(item['config']) == instance]
    if len(configs) != 1:
        raise ValueError('Не найден единственный конфиг этого демона')
    return configs[0]


def describe(logs, instance, state=None, *, demo=False, draft=None, stage='generation'):
    state = state or {}
    cfg = {} if demo else configuration(instance)
    saved = {'revision': 0, 'values': None} if demo else control.read(logs, instance)
    defaults = control.defaults(cfg)
    values = control.validate(saved['values']) if saved['values'] is not None else defaults
    preview_values = control.validate(draft) if draft is not None else values
    return {'revision': saved['revision'], 'values': values, 'defaults': defaults,
            'overridden': saved['values'] is not None, 'profiles': list(control.PROFILES),
            'stages': list(control.STAGES), 'max_text': control.MAX_TEXT,
            'applied': state.get('prompt_control'), 'alive': bool(state.get('alive')),
            'supported': 'prompt-control' in state.get('features', []),
            'preview': {'stage': stage, 'text': control.prefix(preview_values, stage),
                        'subagent': preview_values['subagent'] if stage in ('generation', 'rework') else None}}


def update(logs, instance, body, state=None, *, demo=False, writable=False):
    action = body.get('action')
    control.prefix({}, body.get('stage', 'generation'))  # Validate before any write.
    if action == 'preview':
        if 'values' not in body:
            raise ValueError('Нужны настройки для предпросмотра')
        return describe(logs, instance, state, demo=demo, draft=control.validate(body['values']), stage=body.get('stage', 'generation'))
    if action not in ('save', 'reset'):
        raise ValueError('Неизвестное действие')
    if not writable or demo:
        raise ValueError('Настройки доступны только для чтения')
    configuration(instance)
    if action == 'save' and not isinstance(body.get('values'), dict):
        raise ValueError('Нужны настройки промптов')
    data = control.save(logs, instance, body.get('values') if action == 'save' else None, body.get('revision'))
    # Wake an idle daemon; a busy one completes its current activity unchanged.
    Path(logs, instance + '-poke').write_text(str(data['updated_at']), encoding='utf-8')
    return describe(logs, instance, state, stage=body.get('stage', 'generation'))
