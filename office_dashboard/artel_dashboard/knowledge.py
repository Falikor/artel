"""Dashboard memory access: opaque IDs resolve only to configured stores."""
import hashlib
import json
import os
from jira_gigacode import memory_store
from jira_gigacode.config import instance_key
from jira_gigacode.experience import memory_path
from jira_gigacode.routing import services, config_for_service
from jira_gigacode.supervisor import load_configs
from jira_gigacode.logs import mask_secrets


def sources():
    result = {}
    for item in load_configs():
        cfg = item['config']
        if not isinstance(cfg, dict):
            continue
        scoped = [config_for_service(cfg, svc) for svc in services(cfg)] or [cfg]
        for config in scoped:
            path = os.path.realpath(memory_path(config))
            key = hashlib.sha256((item['name'] + '\0' + path).encode()).hexdigest()[:24]
            service = (config.get('general') or {}).get('service') or ''
            result[key] = {'key': key, 'id': instance_key(config), 'name': item['name'], 'service': service,
                           'path': path, 'config': config}
    return result


def listing(allowed_ids=None):
    rows = []
    for source in sources().values():
        if allowed_ids is not None and source['id'] not in allowed_ids:
            continue
        row = {k:source[k] for k in ('key', 'id', 'name', 'service')}
        path = memory_store.paths(source['path'])[0]
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if data.get('version') != 1 or not isinstance(data.get('entries'), list):
                raise ValueError('Неизвестный формат памяти')
            # GET does not import legacy notes or expire records.
            row['entries'] = json.loads(mask_secrets(json.dumps(data['entries'], ensure_ascii=False)))
            for entry in row['entries']:
                entry['needs_review'] = entry.get('status') == 'candidate' and (entry.get('needs_review') or (entry.get('verification') or {}).get('result') == 'disputed')
        except FileNotFoundError:
            row['entries'] = []
            row['legacy'] = os.path.exists(source['path'])
        except (OSError, ValueError) as exc:
            row.update(entries=[], error='Не удалось прочитать хранилище: ' + type(exc).__name__)
        rows.append(row)
    return rows


def decide(body):
    source = sources().get(str(body.get('source', '')))
    if not source:
        raise ValueError('Хранилище отсутствует в текущих конфигах')
    path, config = source['path'], source['config']
    entry_id = str(body.get('entry', ''))
    action = body.get('action')
    if action == 'approve':
        evidence = body.get('evidence')
        scope = body.get('scope', [])
        if not isinstance(evidence, str) or not isinstance(scope, list) or not all(isinstance(s, str) for s in scope):
            raise ValueError('Нужно текстовое основание и список областей применения')
        memory_store.approve(path, config, entry_id, evidence, scope)
    elif action == 'reject':
        memory_store.reject(path, config, entry_id)
    elif action == 'retry':
        memory_store.retry_verification(path, config, entry_id)
    else:
        raise ValueError('Неизвестное действие с памятью')
    return {'ok': True}
