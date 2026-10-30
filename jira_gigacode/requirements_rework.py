"""Owner-requested requirements changes. Durable queue; never retried implicitly."""
import copy
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from .base import LOGS_DIR, logger
from .config import instance_key, issue_branch, repo_path, default_base_ref, resolve_param
from .retry_control import transaction, entries, path_for as retry_path


def path_for(logs, instance):
    return retry_path(logs, instance).with_name(instance + '-requirements.json')


def scope(config):
    return hashlib.sha256(json.dumps({k:v for k,v in config.items() if not k.startswith('_')}, sort_keys=True).encode()).hexdigest()


def submit(logs, instance, config, issue, note):
    from .prompt_control import apply
    config = apply(config, logs)
    issue = str(issue).strip().upper()
    project = str(resolve_param('jira.project', 'JIRA_PROJECT', config, '')).upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', issue) or issue.rsplit('-', 1)[0] != project:
        raise ValueError('Укажите задачу из проекта выбранного демона')
    if not isinstance(note, str) or not note.strip() or len(note) > 2000:
        raise ValueError('Опишите изменение постановки (до 2000 символов)')
    with transaction(path_for(logs, instance)) as data:
        if any(r['issue'] == issue and r['status'] in ('queued', 'running') for r in data.values()):
            raise ValueError('Переделка этой задачи уже в очереди или выполняется')
        superseded = [r for r in data.values() if r['issue'] == issue and r['status'] == 'blocked']
        for old in superseded:
            old.update(status='cancelled', finished_at=time.time(), error='Заменена новым запросом переделки')
        hold_path = Path(logs) / (instance + '-blocked.json')
        if hold_path.exists():
            with transaction(hold_path) as holds:
                hold = holds.get(issue) or {}
                if not hold.get('request') or any(r.get('request') == hold['request'] and r['issue'] == issue
                                                 and r['status'] in ('cancelled', 'blocked') for r in data.values()):
                    holds.pop(issue, None)
        key = uuid.uuid4().hex
        data[key] = dict(request=key, id=instance, issue=issue, note=note.strip(),
                         scope=scope(config), status='queued', created_at=time.time())
    return key


def cancel(logs, instance, request):
    with transaction(path_for(logs, instance)) as data:
        row = data.get(request)
        if not row or row['status'] not in ('queued', 'blocked'):
            raise ValueError('Отменить можно только ожидающий запрос или запрос с вопросом в Jira')
        row.update(status='cancelled', finished_at=time.time())


def rows(logs):
    result = []
    for path in Path(logs).glob('*-requirements.json'):
        result.extend({k:v for k,v in r.items() if k != 'scope'} for r in entries(path).values())
    return sorted(result, key=lambda r:r['created_at'], reverse=True)


def git(repo, *args):
    p = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise ValueError('Не удалось выполнить Git: ' + ' '.join(args[:2]))
    return p.stdout.strip()


def prepare(config, row):
    """Pin a fresh branch to the latest delivery (or current base after merge)."""
    from . import jira_client, routing
    fields = jira_client.fetch_issue_fields(row['issue'], config)
    if not fields or not (fields.get('summary') or fields.get('description')):
        raise ValueError('Актуальная постановка Jira недоступна; запуск отменён')
    if len(str(fields.get('description') or '')) > 12000:
        raise ValueError('Описание длиннее 12000 символов: разделите постановку перед запуском')
    cfg = routing.resolve_issue_service(row['issue'], config)
    if cfg is None:
        raise ValueError('Не удалось однозначно определить сервис задачи')
    cfg = copy.deepcopy(cfg)
    from .dependencies import admit
    cfg = admit(row['issue'], cfg, owner_config=config)
    repo = repo_path(cfg)
    from . import blocked
    hold_path = blocked.path_for(cfg)
    hold = entries(hold_path).get(row['issue'], {}) if hold_path.exists() else {}
    resume = hold.get('resume') if hold.get('request') == row['request'] else None
    branch = issue_branch(row['issue'], cfg) + '-requirements-' + row['request']
    resume = resume if resume and resume.get('branch') == branch else None
    if git(repo, 'status', '--porcelain') and not (resume and git(repo, 'branch', '--show-current') == branch):
        raise ValueError('Рабочий репозиторий не чист; сначала сохраните изменения')
    git(repo, 'fetch', 'origin')
    if resume:
        base = git(repo, 'rev-parse', '--verify', (resume.get('commit') or resume['base']) + '^{commit}')
        cfg['_requirements'] = dict(request=row['request'], branch=branch, base=base, fields=fields, note=row['note'])
        return cfg
    base = git(repo, 'rev-parse', '--verify', default_base_ref(cfg) + '^{commit}')
    # An unmerged original implementation must remain part of the new work.
    previous = issue_branch(row['issue'], cfg)
    ledger = Path(LOGS_DIR) / (instance_key(config) + '-delivered.jsonl')
    if ledger.exists():
        for line in ledger.read_text(encoding='utf-8').splitlines():
            try:
                delivery = json.loads(line)
            except ValueError:
                continue
            if delivery.get('issue') == row['issue'] and os.path.realpath(delivery.get('repo', '')) == os.path.realpath(repo):
                previous = delivery['branch']
    found = subprocess.run(['git', 'rev-parse', '--verify', 'refs/remotes/origin/' + previous + '^{commit}'],
                           cwd=repo, capture_output=True, text=True, timeout=30)
    if found.returncode == 0:
        head = found.stdout.strip()
        merged = subprocess.run(['git', 'merge-base', '--is-ancestor', head, base], cwd=repo, capture_output=True, timeout=30)
        if merged.returncode not in (0, 1):
            raise ValueError('Не удалось проверить слияние предыдущей работы')
        if merged.returncode == 1:
            base = head
    cfg['_requirements'] = dict(request=row['request'], branch=branch, base=base, fields=fields, note=row['note'])
    return cfg


def maybe_run(config, cooldown):
    from . import pipeline, runtime, retry, issue_report, blocked, routing, notifications
    from .feature_control import changed
    from .dependencies import DependencyBlocked
    path = path_for(LOGS_DIR, instance_key(config))
    if not path.exists() or not runtime.running:
        return False
    waiting = [r for r in entries(path).values() if r.get('status') == 'blocked']
    eligible = set(blocked.candidate_keys(config, include_requests=True)) if waiting else set()
    for row in waiting:
        if row['scope'] != scope(config):
            notifications.notify(config, row['issue'], 'retry-confirmation',
                'Конфиг изменился во время ожидания уточнения для переделки. Создайте новый запрос переделки после проверки настроек.',
                logs_dir=LOGS_DIR)
            continue
        if row['issue'] not in eligible:
            continue
        control = entries(retry_path(LOGS_DIR, instance_key(config))).get(row['issue'], {})
        if control.get('mode') == 'blocked' or (control.get('mode') == 'paused' and control.get('pause_until', 0)>time.time()):
            continue
        cfg = routing.resolve_issue_service(row['issue'], config)
        if cfg is not None and blocked.admit(row['issue'], cfg) is not None:
            with transaction(path) as data:
                if data[row['request']]['status'] == 'blocked':
                    data[row['request']].update(status='queued', clarified_at=time.time())
    with transaction(path) as data:
        # Only the daemon's serial poll loop claims requests. A running entry here
        # belongs to an interrupted previous invocation, never an automatic retry.
        for item in data.values():
            if item['status'] == 'running':
                item.update(status='interrupted', finished_at=time.time(), error='Предыдущий запуск прерван; создайте новый запрос')
        pending = [key for key, item in data.items() if item['status'] == 'queued']
    for key in pending:
        if not runtime.running or changed(config):
            return False
        with transaction(path) as data:
            item = data.get(key)
            if not item or item['status'] != 'queued':
                continue  # Owner may have cancelled it while another prerequisite was checked.
            item.update(status='running', started_at=time.time())
            item.pop('waiting_reason', None)
            row = dict(item)
        result = dict(status='failed')
        try:
            if row['scope'] != scope(config):
                raise ValueError('Конфиг изменился после постановки в очередь; создайте новый запрос')
            control = entries(retry_path(LOGS_DIR, instance_key(config))).get(row['issue'], {})
            if control.get('mode') == 'blocked' or (control.get('mode') == 'paused' and control.get('pause_until', 0) > time.time()):
                raise ValueError('Задача исключена или приостановлена в панели ретраев')
            cfg = prepare(config, row)
            cfg = blocked.admit(row['issue'], cfg)
            if cfg is None:
                result = dict(status='blocked', error='Ожидает уточнения в Jira')
                continue
            result['branch'] = cfg['_requirements']['branch']
            result['requirements_hash'] = hashlib.sha256(json.dumps(cfg['_requirements']['fields'], sort_keys=True).encode()).hexdigest()
            # Hold the ordinary polling path, including old transition-only retries.
            with transaction(retry_path(LOGS_DIR, instance_key(config))) as ledger:
                decision = ledger.setdefault(row['issue'], {})
                if decision.get('mode') == 'blocked' or (decision.get('mode') == 'paused' and decision.get('pause_until', 0)>time.time()):
                    result = dict(status='queued', waiting_reason='Ожидает снятия запрета или паузы владельца')
                    continue
                decision.update(needs_review=True, approved=False,
                    reason='Запрошена переделка постановки; обычный повтор требует решения владельца')
            ok = pipeline.process_issue(row['issue'], cfg, cooldown)
            rep = issue_report._REPORT.get(row['issue']) or {}
            result['status'] = 'blocked' if rep.get('blocked') else 'done' if ok else 'failed' if runtime.running else 'interrupted'
            result['tokens'] = rep.get('tokens')
            if not ok:
                result['error'] = rep.get('blocked_question') or 'Работа не завершена. Проверьте журнал; автоматического повтора нет.'
        except DependencyBlocked as exc:
            result = dict(status='queued', waiting_reason=str(exc))
        except Exception as exc:
            logger.warning('Переделка %s: %s', row['issue'], exc)
            result['error'] = str(exc)[:500]
        finally:
            if result['status'] != 'queued':
                result.update(finished_at=time.time(), total_seconds=round(time.time() - row['started_at'], 1))
            with transaction(path) as data:
                data[row['request']].update(result)
                if result['status'] == 'queued':
                    data[row['request']].pop('started_at', None)
        if result['status'] != 'queued':
            return True
    return False
