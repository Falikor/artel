"""No paths or secrets accepted from the browser; resolve configured daemon IDs."""
import os
from jira_gigacode import feature_control as control
from jira_gigacode.config import instance_key
from jira_gigacode.supervisor import load_configs


def configuration(instance):
    configs = [item['config'] for item in load_configs() if instance_key(item['config']) == instance]
    if len(configs) != 1:
        raise ValueError('Не найден единственный конфиг этого демона')
    return configs[0]


def describe(logs, instance, state):
    cfg = configuration(instance)
    saved = control.read(logs, instance)
    cfg = dict(cfg, _feature_flags=saved['overrides'])
    return dict(saved, catalog=[dict(key=k,label=label,dependency=dep,
                supported=k!='dependencies.enabled' or 'task-dependencies' in state.get('features',[]))
                for k,env,default,label,dep in control.FEATURES],
                desired=control.effective(cfg), applied=state.get('feature_control'),
                supported='feature-control' in state.get('features',[]), alive=state.get('alive',False))


def update(logs, instance, body, state=None):
    configuration(instance)
    if body.get('key') == 'dependencies.enabled' and 'task-dependencies' not in (state or {}).get('features',[]):
        raise ValueError('Сначала запустите демон версии 2.19.0 или новее')
    data = control.save(logs, instance, body.get('key'), body.get('value'), body.get('revision'))
    with open(os.path.join(logs, instance+'-poke'),'w') as flag:
        flag.write(str(data['updated_at']))
    return data
