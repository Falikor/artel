"""Bounded repository knowledge. Agent observations never promote themselves.

The old .md file is preserved. Rules live in .rules.md; structured knowledge in
.store.json; bounded audit history in .history.jsonl (+ one rotated file).
"""
import contextlib
import difflib
from .platform_support import fcntl
import hashlib
import json
import os
import re
import tempfile
import time

from .config import resolve_param_int
from .logs import mask_secrets


def normalize(text):
    return re.sub(r'[\W_]+', ' ', text.lower()).strip()


def paths(path):
    return path + '.store.json', path + '.rules.md', path + '.history.jsonl'


def _limit(config, key, default):
    return max(1, resolve_param_int('memory.' + key, 'MEMORY_' + key.upper(), config, default))


def _save(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix='.memory-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _event(path, event, config):
    event = dict(event, at=time.time())
    line = json.dumps(event, ensure_ascii=False) + '\n'
    cap = max(16384, _limit(config, 'history_max_bytes', 1_000_000))
    if len(line.encode()) > cap:
        line = json.dumps({'at': event['at'], 'action': event.get('action'),
                           'entry_id': (event.get('entry') or {}).get('id'),
                           'details_omitted': 'event exceeds history_max_bytes'}) + '\n'
    if os.path.exists(path) and os.path.getsize(path) + len(line.encode()) > cap:
        os.replace(path, path + '.1')
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line)


def _entry(text, issue, source, now):
    text = mask_secrets(str(text)).strip()[:300]
    return {'id': hashlib.sha256(' '.join(text.split()).encode()).hexdigest()[:16],
            'text': text, 'status': 'candidate', 'issue': str(issue)[:200],
            'source': str(source)[:100], 'created': now, 'last_seen': now,
            'observations': 1, 'scope': [], 'evidence': ''}


def _maintenance(data, audit, config, now):
    entries = data['entries']
    for e in list(entries):
        stamp = e.get('verified_at', e['created']) if e['status'] == 'confirmed' else e['created']
        days = _limit(config, 'review_after_days', 90) if e['status'] == 'confirmed' else _limit(config, 'candidate_days', 30)
        if now - stamp >= days * 86400:
            _event(audit, {'action': 'expired', 'entry': dict(e)}, config)
            if e['status'] == 'confirmed':
                e.update(status='candidate', needs_review=True, created=now)
                e.pop('verification', None)
            else:
                entries.remove(e)
    for status, cap in [('candidate', _limit(config, 'max_candidates', 100)),
                        ('confirmed', _limit(config, 'max_confirmed', 40)),
                        ('rejected', _limit(config, 'max_candidates', 100))]:
        group = sorted((e for e in entries if e['status'] == status),
                       key=lambda e: e.get('verified_at', e['created']), reverse=True)
        for e in group[cap:]:
            entries.remove(e)
            _event(audit, {'action': 'capacity', 'entry': e}, config)


@contextlib.contextmanager
def transaction(path, config):
    store, _, audit = paths(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(store + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(store, encoding='utf-8') as f:
                data = json.load(f)
            if data.get('version') != 1 or not isinstance(data.get('entries'), list):
                raise ValueError('Неизвестный формат памяти; файл оставлен без изменений')
        except FileNotFoundError:
            data = {'version': 1, 'entries': [], 'legacy_imported': False}
        if not data['legacy_imported']:
            # Import only once. Never overwrite, truncate or automatically trust legacy text.
            if os.path.exists(path):
                source, issue = 'legacy', 'legacy'
                with open(path, encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('## '):
                            parts = line.strip().split(' · ')
                            issue = parts[1] if len(parts) > 1 else 'legacy'
                            source = parts[-1]
                        elif re.match(r'^\s*[-*] ', line):
                            e = _entry(re.sub(r'^\s*[-*] ', '', line), issue, source, time.time())
                            if not any(x['id'] == e['id'] for x in data['entries']):
                                data['entries'].append(e)
                                _maintenance(data, audit, config, time.time())
            data['legacy_imported'] = True
        _maintenance(data, audit, config, time.time())
        yield data, audit
        _maintenance(data, audit, config, time.time())
        _save(store, data)


def observe(path, config, issue, source, lessons):
    added = 0
    with transaction(path, config) as (data, audit):
        for lesson in lessons[:5]:
            e = _entry(lesson, issue, source, time.time())
            if not normalize(e['text']):
                continue
            old = next((x for x in data['entries'] if x['id'] == e['id']), None)
            if old:
                if old['status'] == 'rejected':
                    continue
                old['last_seen'] = time.time()
                old['observations'] += 1
                # Repetition never extends verification lifetime or promotes a candidate.
                continue
            data['entries'].append(e)
            _event(audit, {'action': 'observed', 'entry': e}, config)
            added += 1
    return added


def entries(path, config):
    with transaction(path, config) as (data, _):
        return [dict(e) for e in data['entries']]


def approve(path, config, entry_id, evidence, scope=(), replaces=None):
    evidence = mask_secrets(evidence).strip()
    if not evidence:
        raise ValueError('Нужно основание подтверждения: проверенная команда, код или решение человека')
    with transaction(path, config) as (data, audit):
        entry = next((e for e in data['entries'] if e['id'] == entry_id), None)
        if entry is None:
            raise ValueError('Запись не найдена или срок её пересмотра истёк')
        if replaces:
            old = next((e for e in data['entries'] if e['id'] == replaces), None)
            if old is None or replaces == entry_id:
                raise ValueError('Для замены укажите другую существующую запись')
            data['entries'].remove(old)
            _event(audit, {'action': 'superseded', 'entry': old, 'replacement': entry_id}, config)
        entry.update(status='confirmed', needs_review=False, evidence=evidence[:1000], verified_at=time.time(),
                     scope=[s.strip().lower()[:100] for s in scope if s.strip()][:10])
        _event(audit, {'action': 'confirmed_by_owner', 'entry': entry}, config)


def reject(path, config, entry_id):
    with transaction(path, config) as (data, audit):
        entry = next((e for e in data['entries'] if e['id'] == entry_id), None)
        if entry is None:
            raise ValueError('Запись не найдена')
        entry.update(status='rejected', created=time.time())
        _event(audit, {'action': 'rejected_by_owner', 'entry': entry}, config)


def similar(entries_, entry):
    """Suggestions only: similar wording may reverse a rule, so never merge automatically."""
    return [e['id'] for e in entries_ if e['id'] != entry['id'] and
            difflib.SequenceMatcher(None, normalize(e['text']), normalize(entry['text'])).ratio() >= .7]


def active_text(path, config, context=''):
    _, rules_path, _ = paths(path)
    cap = _limit(config, 'max_chars', 6000)
    try:
        with open(rules_path, encoding='utf-8') as f:
            rules = f.read(cap + 1).strip()
    except FileNotFoundError:
        rules = ''
    if len(rules) > cap:
        # Never silently drop pinned rules; require the owner to resolve the budget conflict.
        raise ValueError(f'Постоянные правила {rules_path} длиннее memory.max_chars={cap}')
    selected = [rules] if rules else []
    used = len(rules)
    terms = set(normalize(context).split())
    context = context.lower()
    eligible = [e for e in entries(path, config) if e['status'] == 'confirmed' and
                (not e['scope'] or any(s in context for s in e['scope']))]
    eligible.sort(key=lambda e: (len(terms & set(normalize(e['text']).split())), e['verified_at']), reverse=True)
    for e in eligible:
        line = '- ' + e['text']
        if used + len(line) + 1 <= cap:
            selected.append(line)
            used += len(line) + 1
    return '\n'.join(selected)


def command(args):
    import argparse
    parser = argparse.ArgumentParser(prog='artel.py memory')
    parser.add_argument('action', choices=['list', 'approve', 'reject', 'sweep', 'retry'])
    parser.add_argument('path', help='путь прежнего файла memory/<инстанс>.md')
    parser.add_argument('id', nargs='?')
    parser.add_argument('--evidence', default='')
    parser.add_argument('--scope', action='append', default=[])
    parser.add_argument('--replaces')
    parser.add_argument('--disputed', action='store_true', help='показать только спорные записи')
    parser.add_argument('--config', help='JSON конфиг демона: те же лимиты, что при работе')
    opts = parser.parse_args(args)
    config = {}
    try:
        if opts.config:
            with open(opts.config, encoding='utf-8') as f:
                config = json.load(f)
        if opts.action == 'approve':
            approve(opts.path, config, opts.id, opts.evidence, opts.scope, opts.replaces)
        elif opts.action == 'retry':
            retry_verification(opts.path, config, opts.id)
        elif opts.action == 'reject':
            reject(opts.path, config, opts.id)
        rows = entries(opts.path, config)
        if opts.action == 'list':
            for e in rows:
                check = e.get('verification') or {}
                if opts.disputed and (e['status'] != 'candidate' or check.get('result') != 'disputed'):
                    continue
                if check:
                    print('  Автопроверка: ' + check['result'] + ' — ' + check.get('reason', ''))
                print(f"{e['id']} [{e['status']}] {e['text']}\n  {e['issue']} / {e['source']}; область: {e['scope'] or 'весь репозиторий'}")
                if e['evidence']:
                    print('  Основание: ' + e['evidence'])
                matches = similar(rows, e)
                if matches:
                    print('  Похожие (проверьте перед объединением): ' + ', '.join(matches))
        print(f'Активных записей: {len(rows)}. Постоянные правила: {paths(opts.path)[1]}')
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Память не изменена либо операция не завершена: {exc}')
        return 1


def forget_source(path, source, dry_run=False):
    store, _, audit = paths(path)
    if not os.path.exists(store):
        return 0
    with open(store + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(store, encoding='utf-8') as f:
            data = json.load(f)
        removed = [e for e in data['entries'] if e['source'] == source]
        if removed and not dry_run:
            _save(store + '.bak', data)
            data['entries'] = [e for e in data['entries'] if e['source'] != source]
            _event(audit, {'action': 'forget_source', 'source': source, 'count': len(removed)}, {})
            _save(store, data)
        return len(removed)


def claim_verification(path, config):
    """Reserve one candidate under the store lock; crash recovery uses the retry timeout."""
    with transaction(path, config) as (data, _):
        now = time.time()
        if now - data.get('verify_last_run', 0) < _limit(config, 'verify_every_minutes', 60) * 60:
            return None
        pause = _limit(config, 'verify_retry_hours', 24) * 3600
        for e in data['entries']:
            check = e.get('verification') or {}
            if e['status'] != 'candidate' or check.get('result') == 'disputed':
                continue
            if now - check.get('at', 0) < pause:
                continue
            e['verification'] = {'result': 'running', 'at': now}
            data['verify_last_run'] = now
            return dict(e)
    return None


def record_verification(path, config, expected, result):
    """Do not override manual decisions or another verifier's newer result."""
    with transaction(path, config) as (data, audit):
        e = next((e for e in data['entries'] if e['id'] == expected['id']), None)
        if not e or e['status'] != 'candidate' or e['created'] != expected['created'] or \
                e.get('verification') != expected.get('verification'):
            return False
        result = dict(result, at=time.time())
        result['reason'] = mask_secrets(str(result.get('reason', '')))[:1000]
        result['scope'] = [s.lower().strip()[:100] for s in result.get('scope', [])][:10]
        e['verification'] = result
        if result['result'] == 'confirmed':
            e.update(status='confirmed', verified_at=time.time(), needs_review=False,
                     scope=result['scope'], evidence='Автопроверка ' + result.get('commit', '') + ': ' + result['reason'])
        _event(audit, {'action': 'automatic_verification', 'entry': e}, config)
        return True


def retry_verification(path, config, entry_id):
    with transaction(path, config) as (data, audit):
        e = next((e for e in data['entries'] if e['id'] == entry_id and e['status'] == 'candidate'), None)
        if not e:
            raise ValueError('Кандидат не найден')
        e.pop('verification', None)
        _event(audit, {'action': 'verification_retry_requested', 'id': entry_id}, config)
