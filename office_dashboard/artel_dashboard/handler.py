"""HTTP дашборда: страница, ассеты, API (состояние, история, качество, имена, цены, персонажи), поток SSE
и кнопки управления демонами (проверить Jira сейчас, остановить, запустить)."""
import json
import mimetypes
import os
import re
import signal
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .assets import discover_assets
from .building import Building
from .common import HOSTNAME, STATIC_DIR, pid_alive, tail_lines
from .daemons import read_all, supervisor_alive
from .history import history_csv, read_proposals, read_tasks
from .quality import load_rows, summarize


class Handler(BaseHTTPRequestHandler):
    server_version = 'OfficeDashboard/1.0'

    def state(self):
        snap = read_all(self.server.logs, self.server.names, self.server.characters)
        snap['offices'] = self.server.building.resolve(snap['daemons'])
        snap['office_memberships'] = {k: self.server.building.room_id(v['group'], v['seat'])
                                      for k, v in self.server.building.load().items() if 'group' in v and 'seat' in v}
        return snap

    def visible_state(self):
        snapshot = self.state()
        return dict(snapshot, control=self.server.control, demo=self.server.demo)

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    def filter_office(self, rows, query):
        room = (query.get('office') or [''])[0]
        daemon = (query.get('id') or [''])[0]
        ids = None
        if room:
            self.state()  # Ensure persisted assignments exist for current residents.
            data = self.server.building.load()
            ids = {k for k, v in data.items() if 'group' in v and 'seat' in v
                   and self.server.building.room_id(v['group'], v['seat']) == room}
        return [r for r in rows if (ids is None or r['id'] in ids) and (not daemon or r['id'] == daemon)]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == '/api/cli-events':
                instance = (query.get('id') or [''])[0]
                if not re.fullmatch(r'[a-z0-9_.-]+', instance):
                    return self.send_error(400)
                return self.execution_stream(instance)
            if path in ('/', '/index.html'):
                return self.send_file(os.path.join(STATIC_DIR, 'index.html'), cache=False)
            if path.startswith('/static/'):
                return self.send_safe(STATIC_DIR, path[len('/static/'):], cache=False)
            if path.startswith('/assets/'):
                return self.send_safe(self.server.assets, path[len('/assets/'):], cache=True)
            if path == '/api/assets':
                return self.send_json(discover_assets(self.server.assets, self.server.cat))
            if path == '/api/state':
                return self.send_json(self.visible_state())
            if path == '/api/prompts':
                from . import prompts
                from .common import DEFAULT_LOGS
                available = self.server.demo or os.path.realpath(self.server.logs) == os.path.realpath(DEFAULT_LOGS)
                writable = self.server.control and available and not self.server.demo
                if not available:
                    return self.send_json({'available': False, 'control': False, 'daemons': []})
                instance = (query.get('id') or [''])[0]
                states = self.state()['daemons']
                if not instance:
                    daemons = [{'id': d['id'], 'project': d.get('project'), 'name': d.get('name')} for d in states] if self.server.demo else prompts.catalog()
                    return self.send_json({'available': True, 'control': writable, 'daemons': daemons, 'demo': self.server.demo})
                if not re.fullmatch(r'[a-z0-9_.-]+', instance):
                    return self.send_error(400)
                try:
                    state = next((d for d in states if d['id'] == instance), {})
                    data = prompts.describe(self.server.logs, instance, state, demo=self.server.demo)
                    return self.send_json(dict(data, available=True, control=writable, demo=self.server.demo))
                except ValueError as exc:
                    return self.send_json({'available': False, 'control': False, 'error': str(exc)})
            if path == '/api/stream':
                return self.stream()
            if path in ('/api/history', '/api/history.csv'):
                days = float((query.get('days') or ['0'])[0] or 0)
                since = time.time() - days * 86400 if days > 0 else 0
                tasks = self.filter_office(read_tasks(self.server.logs, since), query)
                if path.endswith('.csv'):
                    return self.send_csv(tasks)
                proposals = self.filter_office(read_proposals(self.server.logs, since), query)
                state = self.state()
                names = self.server.names.load()
                meta = {r['id']: {'name': names.get(r['id']), 'project': r.get('project'), 'jira_url': None}
                        for r in tasks + proposals}
                for d in state['daemons']:
                    meta[d['id']] = {'name': d.get('name'), 'project': d.get('project'), 'jira_url': d.get('jira_url')}
                # records — задачи Jira (одна строка на задачу, попытки — в runs), proposals — прогоны исследования
                return self.send_json({'now': time.time(), 'records': tasks, 'proposals': proposals, 'daemons': meta})
            if path in ('/api/features', '/api/cli-live'):
                instance = (query.get('id') or [''])[0]
                if not re.fullmatch(r'[a-z0-9_.-]+', instance):
                    return self.send_error(400)
                state = next((d for d in self.state()['daemons'] if d['id'] == instance), {})
                if path == '/api/cli-live':
                    from jira_gigacode.logs import mask_secrets
                    full = os.path.join(self.server.logs, instance + '-gigacode-live.log')
                    text = ''
                    if os.path.isfile(full):
                        with open(full,'rb') as stream:
                            stream.seek(0,2)
                            stream.seek(max(0,stream.tell()-128*1024))
                            text = stream.read().decode('utf-8',errors='replace')
                    return self.send_json({'cli':state.get('cli'), 'alive':state.get('alive',False),
                                           'text':mask_secrets(text), 'limit':131072})
                from . import features
                from .common import DEFAULT_LOGS
                available = not self.server.demo and os.path.realpath(self.server.logs) == os.path.realpath(DEFAULT_LOGS)
                if not available:
                    return self.send_json({'available':False,'control':False})
                try:
                    data = features.describe(self.server.logs,instance,state)
                    return self.send_json(dict(data,available=True,control=self.server.control))
                except ValueError as exc:
                    return self.send_json({'available':False,'control':False,'error':str(exc)})
            if path == '/api/requirements':
                from jira_gigacode.requirements_rework import rows
                days = float((query.get('days') or ['30'])[0])
                if not 0 <= days <= 36500:
                    return self.send_error(400)
                since = time.time() - days * 86400 if days else 0
                items = self.filter_office(rows(self.server.logs), query)
                items = [r for r in items if r['created_at'] >= since]
                from .common import DEFAULT_LOGS
                return self.send_json({'rows': items, 'control': self.server.control and not self.server.demo and os.path.realpath(self.server.logs) == os.path.realpath(DEFAULT_LOGS)})
            if path == '/api/memory':
                from .knowledge import listing
                from .common import DEFAULT_LOGS
                available = not self.server.demo and os.path.realpath(self.server.logs) == os.path.realpath(DEFAULT_LOGS)
                rows = listing() if available else []
                rows = self.filter_office(rows, query)
                return self.send_json({'sources': rows, 'control': self.server.control and available,
                                       'available': available})
            if path in ('/api/insights', '/api/retrospective'):
                from .insights import report
                days = float((query.get('days') or ['30'])[0])
                if not 0 <= days <= 36500:
                    return self.send_error(400)
                since = time.time() - days * 86400 if days else 0
                if path == '/api/insights':
                    tasks = self.filter_office(read_tasks(self.server.logs, since), query)
                    return self.send_json(report(tasks, self.server.prices.load()))
                rows = self.filter_office(load_rows(self.server.logs), query)
                rows = [r for r in rows if r['delivered_at'] >= since]
                return self.send_json({'rows': rows, 'summary': summarize(rows, since)})
            if path == '/api/quality':
                days = float((query.get('days') or ['0'])[0] or 0)
                since = time.time() - days * 86400 if days > 0 else 0
                daemon_id = (query.get('id') or [''])[0].lower()
                return self.send_json(summarize(self.filter_office(load_rows(self.server.logs), query), since, daemon_id))
            if path == '/api/retries':
                from jira_gigacode.retry_control import entries, path_for
                instance = (query.get('id') or [''])[0]
                rows = entries(path_for(self.server.logs, instance))
                pending_path = os.path.join(self.server.logs, instance + '-pending-transitions.json')
                try:
                    with open(pending_path) as f:
                        pending = json.load(f)
                except FileNotFoundError:
                    pending = {}
                for key in pending:
                    rows.setdefault(key, {'kind':'transition', 'needs_review':True,
                                          'reason':'Старый незавершённый перевод Jira — подтвердите повтор'})
                    rows[key]['pending_transition'] = True
                return self.send_json(rows)
            if path == '/api/prices':
                return self.send_json(self.server.prices.load())
            if path == '/api/names':
                return self.send_json(self.server.names.load())
            if path == '/api/log':
                project_id = (query.get('id') or [''])[0].lower()
                if not re.fullmatch(r'[a-z0-9_.-]+', project_id):
                    return self.send_error(400)
                lines = int((query.get('n') or ['300'])[0])
                return self.send_tail(os.path.join(self.server.logs, f'{project_id}-agent.log'), lines)
            if path == '/api/gigacode':
                issue = (query.get('issue') or [''])[0]
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*-\d+', issue):
                    return self.send_error(400)
                # Путь как в run_gigacode_orchestrator; файл появляется после завершения GigaCode
                from jira_gigacode.gigacode import cli_log_path
                return self.send_tail(cli_log_path(issue), 400)
            self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError):
            return self.send_error(400)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            origin = self.headers.get('Origin')
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlparse(origin).netloc != self.headers.get('Host')):
                return self.send_error(403)
            if parsed.path not in ('/api/prompts', '/api/features', '/api/requirements', '/api/memory', '/api/names', '/api/prices', '/api/characters', '/api/offices', '/api/buildings', '/api/retries', '/api/poke', '/api/stop', '/api/start'):
                return self.send_error(404)
            if parsed.path not in ('/api/prompts', '/api/names', '/api/prices', '/api/characters', '/api/offices', '/api/buildings') and not self.server.control:
                return self.send_json({'ok': False, 'reason': 'readonly'})
            if parsed.path in ('/api/prompts', '/api/memory', '/api/requirements', '/api/features'):
                origin = self.headers.get('Origin')
                if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlparse(origin).netloc != self.headers.get('Host')):
                    return self.send_error(403)
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.send_error(415)
            length = int(self.headers.get('Content-Length') or 0)
            if parsed.path == '/api/prompts' and not 0 <= length <= 400000:
                return self.send_error(413)
            body = json.loads(self.rfile.read(min(length, 400000 if parsed.path == '/api/prompts' else 10000)).decode('utf-8') or '{}')
            if not isinstance(body, dict):
                return self.send_error(400)
            if parsed.path == '/api/buildings':
                try:
                    if body.get('action') != 'rename':
                        raise ValueError('Неизвестное действие')
                    self.server.building.rename_building(body.get('building'), body.get('name'))
                except ValueError as exc:
                    return self.send_json({'error': str(exc)})
                return self.send_json(self.visible_state())
            if parsed.path == '/api/memory':
                from .knowledge import decide
                from .common import DEFAULT_LOGS
                if self.server.demo or os.path.realpath(self.server.logs) != os.path.realpath(DEFAULT_LOGS):
                    return self.send_error(403)
                try:
                    return self.send_json(decide(body))
                except ValueError as exc:
                    return self.send_json({'ok': False, 'error': str(exc)})
            if parsed.path == '/api/prices':
                try:
                    return self.send_json(self.server.prices.save(body))
                except ValueError as e:
                    return self.send_json({'error': str(e)})
            if parsed.path == '/api/offices' and body.get('action'):
                try:
                    self.server.building.edit_room(body.get('room'), body['action'], body.get('name'))
                except ValueError as e:
                    return self.send_json({'error': str(e)})
                return self.send_json(self.visible_state())
            project_id = str(body.get('id', '')).lower()
            if not re.fullmatch(r'[a-z0-9_.-]+', project_id):
                return self.send_error(400)
            if parsed.path == '/api/prompts':
                from . import prompts
                from .common import DEFAULT_LOGS
                available = self.server.demo or os.path.realpath(self.server.logs) == os.path.realpath(DEFAULT_LOGS)
                writable = self.server.control and available and not self.server.demo
                if not available:
                    return self.send_error(403)
                try:
                    state = next((d for d in self.state()['daemons'] if d['id'] == project_id), {})
                    data = prompts.update(self.server.logs, project_id, body, state, demo=self.server.demo, writable=writable)
                    return self.send_json(dict(data, ok=True, available=True, control=writable, demo=self.server.demo))
                except ValueError as exc:
                    return self.send_json({'ok': False, 'error': str(exc)})
            if parsed.path == '/api/features':
                from . import features
                from .common import DEFAULT_LOGS
                if self.server.demo or os.path.realpath(self.server.logs) != os.path.realpath(DEFAULT_LOGS):
                    return self.send_error(403)
                try:
                    state = next((d for d in self.state()['daemons'] if d['id'] == project_id), {})
                    data = features.update(self.server.logs,project_id,body,state)
                    return self.send_json(dict(data,ok=True))
                except ValueError as exc:
                    return self.send_json({'ok':False,'error':str(exc)})
            if parsed.path == '/api/requirements':
                from .common import DEFAULT_LOGS
                from jira_gigacode.supervisor import load_configs
                from jira_gigacode.config import instance_key
                from jira_gigacode.requirements_rework import submit, cancel
                if self.server.demo or os.path.realpath(self.server.logs) != os.path.realpath(DEFAULT_LOGS):
                    return self.send_error(403)
                configs = [x['config'] for x in load_configs() if instance_key(x['config']) == project_id]
                if len(configs) != 1:
                    return self.send_json({'ok':False, 'error':'Не найден единственный конфиг выбранного демона'})
                try:
                    if body.get('action') == 'cancel':
                        cancel(self.server.logs, project_id, str(body.get('request', '')))
                        return self.send_json({'ok':True})
                    if body.get('action') != 'submit':
                        raise ValueError('Неизвестное действие')
                    request = submit(self.server.logs, project_id, configs[0], body.get('issue'), body.get('note'))
                    # A busy daemon must also wake immediately after its current poll.
                    with open(os.path.join(self.server.logs, project_id + '-poke'), 'w') as flag:
                        flag.write(str(time.time()))
                    return self.send_json({'ok':True, 'request':request})
                except ValueError as exc:
                    return self.send_json({'ok':False, 'error':str(exc)})
            if parsed.path == '/api/retries':
                from jira_gigacode.retry_control import decide, path_for
                key = decide(path_for(self.server.logs, project_id), body.get('issue', ''),
                             body.get('action'), body.get('seconds', 3600))
                return self.send_json({'ok': True, 'issue': key})
            if parsed.path == '/api/offices':
                try:
                    self.server.building.move(project_id, body.get('room'), body.get('name'))
                except ValueError as e:
                    return self.send_json({'error': str(e)})
                return self.send_json(self.visible_state())
            if parsed.path == '/api/characters':
                try:
                    if 'variant' in body:
                        self.server.building.set_variant(project_id, body['variant'])
                    else:
                        self.server.characters.set(project_id, body.get('character'))
                except ValueError as e:
                    return self.send_json({'error': str(e)})
                return self.send_json({'ok': True})
            if parsed.path == '/api/poke':
                return self.send_json(self.poke(project_id))
            if parsed.path == '/api/stop':
                return self.send_json(self.stop(project_id))
            if parsed.path == '/api/start':
                return self.send_json(self.start(project_id))
            return self.send_json(self.server.names.set(project_id, body.get('name')))
        except (ValueError, OSError):
            return self.send_error(400)

    def poke(self, project_id):
        """Попросить демона проверить Jira сейчас: флажок logs/{id}-poke, демон снимает его в цикле ожидания."""
        d = next((x for x in self.state()['daemons'] if x['id'] == project_id), None)
        if not d:
            return {'ok': False, 'reason': 'unknown'}
        if d.get('source') != 'state':
            return {'ok': False, 'reason': 'old'}   # старая версия скрипта не умеет
        if not d.get('alive'):
            return {'ok': False, 'reason': 'offline'}
        if d.get('stage') not in ('idle', 'starting', 'polling'):
            return {'ok': False, 'reason': 'busy', 'stage': d.get('stage')}
        with open(os.path.join(self.server.logs, f'{project_id}-poke'), 'w') as f:
            f.write(str(time.time()))
        return {'ok': True}

    def stop(self, project_id):
        """Остановить демона: флажок logs/{id}-stop (демон 2.0.2+ прерывает GigaCode и выходит за секунды)
        или SIGTERM, если демон старый, но работает на этом же компьютере."""
        d = next((x for x in self.state()['daemons'] if x['id'] == project_id), None)
        if not d:
            return {'ok': False, 'reason': 'unknown'}
        if not d.get('alive'):
            return {'ok': False, 'reason': 'offline'}
        if 'stop' in (d.get('features') or []):
            with open(os.path.join(self.server.logs, f'{project_id}-stop'), 'w') as f:
                f.write(str(time.time()))
            return {'ok': True, 'how': 'flag', 'stage': d.get('stage')}
        pid = d.get('pid')
        if pid and d.get('host') == HOSTNAME and pid_alive(pid):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError as e:
                return {'ok': False, 'reason': 'signal', 'message': str(e)}
            return {'ok': True, 'how': 'signal', 'stage': d.get('stage')}
        return {'ok': False, 'reason': 'old'}

    def start(self, project_id):
        """Запустить остановленного демона. Запускает супервизор (artel.py): дашборд кладёт ему запрос
        logs/artel-restart-{конфиг}. Без супервизора запуск с дашборда невозможен."""
        d = next((x for x in self.state()['daemons'] if x['id'] == project_id), None)
        if not d:
            return {'ok': False, 'reason': 'unknown'}
        if d.get('alive'):
            return {'ok': False, 'reason': 'running'}
        if self.server.demo:
            open(os.path.join(self.server.logs, f'{project_id}-start'), 'w').close()
            return {'ok': True}
        if not supervisor_alive(self.server.logs):
            return {'ok': False, 'reason': 'no_supervisor'}
        config = os.path.basename(str(d.get('config') or ''))
        name = config[:-len('.json')] if config.endswith('.json') else ''
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            return {'ok': False, 'reason': 'no_config'}
        open(os.path.join(self.server.logs, f'artel-restart-{name}'), 'w').close()
        return {'ok': True}

    def send_csv(self, records):
        state = self.state()
        names = {d['id']: d['name'] for d in state['daemons'] if d.get('name')}
        names.update(self.server.names.load())
        ci_ids = {d['id']: d.get('ci_id') for d in state['daemons']}
        body = history_csv(records, names, ci_ids, self.server.prices.load())
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="daemon-history.csv"')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_safe(self, base, rel, cache):
        base = os.path.realpath(base)
        full = os.path.realpath(os.path.join(base, rel))
        if not full.startswith(base + os.sep) or not os.path.isfile(full):
            return self.send_error(404)
        return self.send_file(full, cache)

    def send_file(self, full, cache):
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        with open(full, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=3600' if cache else 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def send_tail(self, full, lines):
        if not os.path.isfile(full):
            text = f'Файл пока не создан: {full}\n'
        else:
            text = '\n'.join(tail_lines(full, 512 * 1024)[-max(1, min(lines, 5000)):]) + '\n'
        body = text.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def stream(self):
        self.connection.settimeout(5)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        last, last_ping = None, 0
        while not getattr(self.server, 'maintenance_paused', False):
            snapshot = self.visible_state()
            key = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            now = time.time()
            if key != last:
                payload = json.dumps(snapshot, ensure_ascii=False)
                self.wfile.write(f'data: {payload}\n\n'.encode('utf-8'))
                self.wfile.flush()
                last, last_ping = key, now
            elif now - last_ping > 15:
                self.wfile.write(b': ping\n\n')
                self.wfile.flush()
                last_ping = now
            time.sleep(1)

    def execution_stream(self, instance):
        from jira_gigacode.cli_events import read_events
        if not self.server.monitor_slots.acquire(blocking=False):
            return self.send_error(429, 'Too many observers')
        try:
            self.connection.settimeout(5)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            previous, ping = None, 0
            cursor = self.headers.get('Last-Event-ID', '')
            while not getattr(self.server, 'maintenance_paused', False):
                data = read_events(self.server.logs, instance)
                key = (data['executionId'], data['lastSeq'])
                if key != previous:
                    event_id = str(data['executionId']) + ':' + str(data['lastSeq'])
                    data['reset'] = bool(cursor and not cursor.startswith(str(data['executionId']) + ':'))
                    data['truncated'] = data['firstSeq'] > 1
                    # Each update is a bounded snapshot: reconnect restores the retained window.
                    self.wfile.write(('id: ' + event_id + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode())
                    self.wfile.flush()
                    previous, ping = key, time.monotonic()
                    cursor = event_id
                elif time.monotonic() - ping > 10:
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                    ping = time.monotonic()
                time.sleep(.5)
        except (OSError, ValueError):
            pass
        finally:
            self.server.monitor_slots.release()


def make_server(host, port, logs, assets, names, prices, characters, control=True, demo=False, cat=False, verbose=False):
    """HTTP-сервер дашборда. Хранилища (names, prices, characters) живут на сервере, а не в глобальных
    переменных: несколько серверов в одном процессе (тесты) не мешают друг другу."""
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.monitor_slots = threading.BoundedSemaphore(16)
    server.logs, server.assets = logs, assets
    server.names, server.prices, server.characters = names, prices, characters
    server.building = Building(os.path.join(os.path.dirname(characters.path) if characters else logs, 'building.json'))
    server.control, server.demo, server.cat, server.verbose = control, demo, cat, verbose
    return server
