"""Qwen/GigaCode JSONL adapter. Schema supplied for corporate CLI v26.9.64.

No thinking blocks are retained. Browser-facing summaries are fixed vocabulary,
never arbitrary CLI text. Technical details are bounded and secrets are redacted.
"""
import codecs
from collections import deque, OrderedDict
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .logs import mask_secrets

MAX_LINE = 1024 * 1024
MAX_EVENTS = 256
MAX_DETAIL = 6000
MAX_OUTPUT = 2 * 1024 * 1024
SENSITIVE = re.compile(r'token|password|secret|authorization|cookie|api[_-]?key|credential|signature|thinking', re.I)


def redact(value, depth=0):
    if depth > 5:
        return '[truncated]'
    if isinstance(value, dict):
        return {str(k)[:100]: '[redacted]' if SENSITIVE.search(str(k)) else redact(v, depth + 1)
                for k, v in list(value.items())[:60]}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:60]]
    if isinstance(value, str):
        text = value
        for key, secret in os.environ.items():
            if SENSITIVE.search(key) and len(secret) >= 6:
                text = text.replace(secret, '[redacted]')
        return mask_secrets(text)[:MAX_DETAIL]
    return value


def detail(value):
    return json.dumps(redact(value), ensure_ascii=False)[:MAX_DETAIL]


def tool_label(name):
    if name in ('list_directory', 'glob'):
        return 'Изучает структуру проекта'
    if name in ('read_file', 'read_many_files', 'grep_search'):
        return 'Анализирует исходный код'
    if name in ('write_file', 'edit', 'replace'):
        return 'Вносит изменения в файлы'
    if name in ('run_shell_command', 'shell'):
        return 'Выполняет команду'
    return 'Вызывает инструмент'


class Execution:
    def __init__(self, reporter, issue, purpose):
        self.reporter = reporter
        self.info = dict(run=uuid.uuid4().hex, issue=issue, purpose=purpose or 'generation',
                         started_at=time.time(), active=True, status='running')
        self.events = deque(maxlen=MAX_EVENTS)
        self.seq = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.error = None
        path = getattr(reporter, 'path', None)
        self.path = Path(path[:-len('-state.json')] + '-cli-events.json') if isinstance(path, str) and path.endswith('-state.json') else None
        self.emit('execution_started', 'Агент начал выполнение')
        if self.path:
            reporter.set_cli(self.info)
            self.flush()
        self.writer = threading.Thread(target=self._write_loop, daemon=True)
        self.writer.start()

    def emit(self, kind, summary, data=None, **ids):
        with self.lock:
            self.seq += 1
            event = dict(executionId=self.info['run'], seq=self.seq, timestamp=time.time(), kind=kind, summary=summary)
            event.update({k: str(v)[:200] for k, v in ids.items() if v is not None})
            if data is not None:
                event['detail'] = detail(data)
            self.events.append(event)

    def flush(self):
        if not self.path:
            return
        with self.lock:
            payload = dict(executionId=self.info['run'], cli=dict(self.info), events=list(self.events),
                           firstSeq=self.events[0]['seq'], lastSeq=self.seq)
        temporary = self.path.with_name(self.path.name + '.' + self.info['run'] + '.tmp')
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.path)
        except OSError:
            self.error = 'Не удалось сохранить журнал мониторинга'
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_loop(self):
        while not self.stop.wait(.25):
            self.flush()

    def finish(self, status, code):
        self.info.update(active=False, status=status, returncode=code, finished_at=time.time())
        summaries = {'success': 'GigaCode завершил выполнение; Артель проверяет результат',
                     'error': 'Выполнение GigaCode завершилось с ошибкой',
                     'interrupted': 'Выполнение прервано', 'timeout': 'Истекло время выполнения'}
        self.emit('execution_finished', summaries[status], {'returncode': code, 'status': status, 'monitoring_error': self.error})
        self.stop.set()
        self.writer.join(2)
        self.flush()
        if self.path:
            self.reporter.set_cli(dict(self.info))


class Parser:
    def __init__(self, execution):
        self.execution = execution
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.buffer = ''
        self.discard = False
        self.invalid = False
        self.result_seen = False
        self.success = False
        self.output = ''
        self.usage = None
        self.session = None
        self.seen = OrderedDict()
        self.tools = OrderedDict()

    def feed(self, raw, final=False):
        text = self.decoder.decode(raw, final=final)
        fragments = text.split('\n')
        for index, fragment in enumerate(fragments):
            complete = index < len(fragments) - 1
            if not self.discard:
                self.buffer += fragment
                if len(self.buffer) > MAX_LINE:
                    self.buffer = ''
                    self.discard = True
                    self.invalid = True
                    self.execution.emit('parse_error', 'Слишком большое событие CLI; требуется проверка')
            if complete:
                if not self.discard:
                    self.line(self.buffer)
                self.buffer, self.discard = '', False
        if final and self.buffer and not self.discard:
            self.line(self.buffer)
            self.buffer = ''

    def line(self, line):
        if not line.strip():
            return
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError()
        except (ValueError, RecursionError):
            self.invalid = True
            # Raw malformed records may contain reasoning or secrets: never retain them.
            self.execution.emit('parse_error', 'Не удалось прочитать событие CLI')
            return
        event_id = event.get('uuid')
        if isinstance(event_id, str):
            if event_id in self.seen:
                return
            self.seen[event_id] = True
            if len(self.seen) > 2048:
                self.seen.popitem(last=False)
        kind, parent = event.get('type'), event.get('parent_tool_use_id')
        session = event.get('session_id')
        if session is not None and not isinstance(session, str):
            self.invalid = True
            self.execution.emit('parse_error', 'Некорректный ID сессии CLI')
            return
        ids = {'sessionId': session, 'eventId': event_id, 'parentToolUseId': parent}
        if kind == 'system' and event.get('subtype') == 'init':
            if not parent and self.session is None:
                self.session = session
            self.execution.emit('session_started', 'Сессия GigaCode подключена',
                                {k: event.get(k) for k in ('model', 'permission_mode', 'qwen_code_version', 'tools', 'mcp_servers')}, **ids)
        elif kind in ('assistant', 'user'):
            message = event.get('message') or {}
            blocks = message.get('content', []) if isinstance(message, dict) else []
            if not isinstance(blocks, list):
                self.invalid = True
                self.execution.emit('parse_error', 'Неизвестный формат содержимого CLI')
                return
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get('type')
                if btype == 'thinking':
                    continue
                if btype == 'tool_use':
                    tool_id, name = block.get('id'), block.get('name')
                    if not isinstance(tool_id, str) or not isinstance(name, str):
                        self.invalid = True
                        self.execution.emit('parse_error', 'Вызов инструмента без имени или ID')
                        continue
                    self.tools[(session, tool_id)] = name
                    if len(self.tools) > 512:
                        self.tools.popitem(last=False)
                    self.execution.emit('tool_started', tool_label(name), {'name': name, 'input': block.get('input')}, toolUseId=tool_id, **ids)
                elif btype == 'tool_result':
                    tool_id = block.get('tool_use_id')
                    name = self.tools.get((session, tool_id)) if isinstance(tool_id, str) else None
                    self.execution.emit('tool_error' if block.get('is_error') else 'tool_finished',
                                        'Инструмент сообщил об ошибке' if block.get('is_error') else 'Инструмент завершил работу',
                                        {'name': name, 'is_error': block.get('is_error'), 'content': block.get('content')}, toolUseId=tool_id, **ids)
                elif btype == 'text':
                    self.execution.emit('message', 'Агент подготовил сообщение', {'text': block.get('text')}, **ids)
                else:
                    self.execution.emit('unknown_event', 'Получено неподдерживаемое событие CLI', {'block_type': btype}, **ids)
        elif kind == 'result':
            # Nested agents cannot complete the parent execution or supply its final marker.
            if parent or (self.session is not None and session != self.session):
                self.execution.emit('subagent_finished', 'Вложенный агент завершил ход', {'is_error': event.get('is_error')}, **ids)
                return
            self.result_seen = True
            value = event.get('result')
            self.success = event.get('subtype') == 'success' and event.get('is_error') is False and isinstance(value, str)
            if isinstance(value, str):
                self.output = value[-MAX_OUTPUT:]
                if len(value) > MAX_OUTPUT:
                    self.invalid = True
            self.usage = event.get('usage') if isinstance(event.get('usage'), dict) else None
            self.execution.emit('result', 'Получен итоговый ответ GigaCode' if self.success else 'GigaCode сообщил об ошибке',
                                {'subtype': event.get('subtype'), 'is_error': event.get('is_error'), 'result': value,
                                 'usage': self.usage, 'permission_denials': event.get('permission_denials')}, **ids)
        else:
            self.execution.emit('unknown_event', 'Получено неподдерживаемое событие CLI', {'type': kind, 'subtype': event.get('subtype')}, **ids)

    def final_text(self):
        # Keep the final success marker last and count only aggregate usage once.
        prefix = ''
        if self.usage:
            usage = dict(self.usage)
            if 'cache_read_input_tokens' in usage:
                usage['cached_tokens'] = usage.pop('cache_read_input_tokens')
            prefix = json.dumps({'executionSummary': usage}) + '\n'
        return prefix + self.output


def read_events(logs, instance):
    path = Path(logs) / (instance + '-cli-events.json')
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('Oversized event snapshot')
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'executionId': None, 'events': [], 'firstSeq': 0, 'lastSeq': 0, 'cli': None}
    return data
