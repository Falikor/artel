"""Durable clarification waits, distinct from failures and operator exclusions."""
import hashlib
import json
import re
import time
from pathlib import Path

from . import jira_client, retry, retry_control, runtime
from .base import LOGS_DIR, logger
from .config import instance_key, resolve_param_list
from .issue_report import report_set, _REPORT
from .logs import mask_secrets
from .requirements_snapshot import fetch_snapshot


def path_for(config):
    directory = Path(retry.control_path()).parent if retry.control_path() else Path(LOGS_DIR)
    return directory / (instance_key(config) + '-blocked.json')


def scope(config):
    public = {k: v for k, v in config.items() if not k.startswith('_')}
    return hashlib.sha256(json.dumps(public, sort_keys=True, default=str).encode()).hexdigest()


def question(output):
    match = re.search(r'(?ms)^BLOCKED_QUESTION_START\s*\n(.*?)^BLOCKED_QUESTION_END\s*$', output or '')
    text = match.group(1) if match else '\n'.join(line for line in (output or '').splitlines()
        if line.strip() not in ('CODE_GENERATION_BLOCKED', 'CODE_GENERATION_FAILED', 'CODE_GENERATION_SUCCESS'))
    return mask_secrets(text.strip() or 'Уточните постановку или устраните внешний блокер, затем сообщите об этом в комментарии.')[:10000]


def _notice(key, config, row):
    from .notifications import notify
    targets = resolve_param_list('explore.statuses', 'EXPLORE_STATUSES', config, [])
    action = ('Ответьте на вопрос в комментарии Jira или измените описание. Демон вернётся к задаче после изменения '
              'постановки в текущей области поиска; обычных ретраев до этого не будет.')
    if row.get('transition_error'):
        action += '\n' + row['transition_error']
    elif targets:
        action += '\nСтатусы ожидания: ' + ', '.join(targets) + '.'
    notify(config, key, 'blocked', row['question'], action=action, logs_dir=path_for(config).parent)


def _move_to_backlog(key, config):
    targets = resolve_param_list('explore.statuses', 'EXPLORE_STATUSES', config, [])
    if not targets:
        return False, 'Не заданы explore.statuses: задача оставлена в текущем статусе. Настройте статус ожидания.'
    current = jira_client.fetch_status(key, config)
    if current and current.lower() in {s.lower() for s in targets}:
        return True, ''
    transitions = jira_client.fetch_transitions(key, config) if current else None
    target = next((jira_client.find_target_transition(transitions, [name]) for name in targets
                   if jira_client.find_target_transition(transitions, [name])), None)
    if not target:
        return False, 'Не удалось безопасно перевести задачу в ' + ', '.join(targets) + '. Переведите её вручную или исправьте workflow.'
    response = jira_client.jira_request('POST', f'/rest/api/2/issue/{key}/transitions',
        data={'transition': {'id': target['id']}}, config=config, max_retries=0)
    if response and response.get('_status') in (200, 204):
        return True, ''
    return False, 'Jira не подтвердила перевод в статус ожидания. Проверьте текущий статус задачи.'


def hold(key, config, output, snapshot=None):
    """Persist before network writes: a restart must never turn BLOCKED into a retry."""
    row = dict(status='waiting', question=question(output), fingerprint=(snapshot or {}).get('fingerprint'),
               scope=scope(config), since=time.time(), transition_done=False, transition_checked=0,
               request=(config.get('_requirements') or {}).get('request'))
    report = _REPORT.get(key) or {}
    if report.get('branch') and report.get('base'):
        row['resume'] = {k: report[k] for k in ('branch', 'base')}
        if report.get('base_commit'):
            row['resume']['commit'] = report['base_commit']
    with retry_control.transaction(path_for(config)) as data:
        data[key] = row
    if retry.control_path():
        with retry_control.transaction(retry.control_path()) as ledger:
            ledger.setdefault(key, {}).update(status='blocked', reason='Ожидает уточнения в Jira',
                needs_review=False, approved=False, fails=0, until=0, finished_at=time.time())
    report_set(key, blocked=True, blocked_question=row['question'])
    _notice(key, config, row)
    _sync_transition(key, config, row)
    return row


def _sync_transition(key, config, row):
    if row.get('transition_done') or time.time()-row.get('transition_checked', 0)<300:
        return
    done, error = _move_to_backlog(key, config)
    row.update(transition_done=done, transition_error=error, transition_checked=time.time())
    with retry_control.transaction(path_for(config)) as data:
        if key in data:
            data[key].update(transition_done=done, transition_error=error, transition_checked=row['transition_checked'])
    if error:
        logger.warning('[%s] %s', key, error)
        _notice(key, config, row)


def candidate_keys(config, include_requests=False):
    """Only previously claimed tasks; reapply today's project/CI/epic/assignee scope."""
    path = path_for(config)
    if not path.exists():
        return []
    keys = [key for key, row in retry_control.entries(path).items()
            if (include_requests or not row.get('request')) and re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', key)]
    if not keys:
        return []
    statuses = resolve_param_list('jira.status_analysis', 'JIRA_STATUS_ANALYSIS', config, []) + \
        resolve_param_list('explore.statuses', 'EXPLORE_STATUSES', config, [])
    found = []
    for offset in range(0, len(keys), 100):
        batch = keys[offset:offset+100]
        quoted = ','.join('"'+key+'"' for key in batch)
        issues, _ = jira_client.search_by_statuses(statuses, config,
            lambda values: jira_client.task_jql(values, config) + f' AND key IN ({quoted})', max_results=100)
        found.extend(issue['key'] for issue in issues if issue['key'] in batch)
    return found


def admit(key, config):
    """None means keep waiting; a returned config carries the fresh clarification."""
    path = path_for(config)
    row = retry_control.entries(path).get(key) if path.exists() else None
    if not row:
        return config
    control = retry_control.entries(retry.control_path()).get(key, {}) if retry.control_path() else {}
    if control.get('mode') == 'blocked' or (control.get('mode') == 'paused' and control.get('pause_until', 0)>time.time()):
        return None
    if row.get('scope') != scope(config) and not control.get('approved'):
        from .notifications import notify
        reason = 'После блокировки изменился конфиг — подтвердите повтор в разделе «Повторы».'
        if retry.control_path():
            with retry_control.transaction(retry.control_path()) as ledger:
                ledger.setdefault(key, {}).update(needs_review=True, reason=reason)
        notify(config, key, 'retry-confirmation', reason, logs_dir=path.parent)
        return None
    if row.get('status') != 'waiting':
        snapshot = fetch_snapshot(key, config)
        return dict(config, _clarification=snapshot, _clarification_resume=row.get('resume')) if snapshot else None
    _sync_transition(key, config, row)
    snapshot = fetch_snapshot(key, config)
    if not snapshot:
        return None
    if not row.get('fingerprint'):
        # Missing pre-run data is not evidence that a human answered the question.
        with retry_control.transaction(path) as data:
            data[key]['fingerprint'] = snapshot['fingerprint']
        return None
    if row['fingerprint'] == snapshot['fingerprint']:
        return None
    return dict(config, _clarification=snapshot, _clarification_resume=row.get('resume'))


def started(key, config):
    path = path_for(config)
    if path.exists():
        with retry_control.transaction(path) as data:
            if key in data:
                data[key].update(status='resuming', scope=scope(config))
        from .notifications import resolve
        resolve(config, key, 'blocked', logs_dir=path.parent)


def completed(key, config):
    path = path_for(config)
    if path.exists():
        with retry_control.transaction(path) as data:
            data.pop(key, None)
