#!/usr/bin/env python3
"""
Отчёт о состоянии демона для офис-дашборда.

Каждый инстанс пишет logs/{проект}-state.json (атомарно, через os.replace):
текущий этап, задачу, heartbeat и последние события. Дашборд читает только
этот файл — сам демон о дашборде ничего не знает и от него не зависит.

Этапы: starting, polling, idle, generating, reviewing, rework, git, jenkins, jira,
       exploring, success, error, stopped.
  reviewing — независимый ревьюер читает изменения; rework — доработка по замечаниям ревью;
  exploring — в простое демон изучает задачу из бэклога (OpenSpec explore);
  retro — ночная ретроспектива: демон разбирает, что стало с его сданными задачами.

Каждая закрытая задача дописывается строкой в logs/{проект}-history.jsonl —
из этого файла дашборд строит статистику (переживает перезапуски демона).
"""

import json
import logging
import os
import socket
import threading
import time

STAGES = (
    'starting', 'polling', 'idle', 'generating', 'reviewing', 'rework', 'git',
    'jenkins', 'jira', 'exploring', 'retro', 'success', 'error', 'stopped',
)
# Этапы пост-обработки наследуют задачу от предыдущего события
ISSUE_STAGES = ('generating', 'reviewing', 'rework', 'git', 'jenkins', 'jira', 'success', 'error')


class NullReporter:
    """Заглушка: демон работает и без дашборда."""

    def emit(self, *args, **kwargs):
        pass

    def finish_issue(self, *args, **kwargs):
        pass

    def finish_blocked(self, *args, **kwargs):
        pass

    def attach_logging(self, *args, **kwargs):
        pass

    def close(self, *args, **kwargs):
        pass

    def set_features(self, *args, **kwargs):
        pass

    def set_prompts(self, *args, **kwargs):
        pass

    def set_cli(self, *args, **kwargs):
        pass

    def poke_requested(self):
        return False

    def note_tokens(self, *args, **kwargs):
        pass


class _ErrorCapture(logging.Handler):
    def __init__(self, reporter):
        super().__init__(level=logging.ERROR)
        self.reporter = reporter

    def emit(self, record):
        try:
            self.reporter._on_error_log(record.getMessage())
        except Exception:
            pass


class StateReporter:
    def __init__(self, path, project, config_path=None, poll_interval=None,
                 heartbeat_sec=10, max_events=40, name=None, jira_url=None, history_path=None,
                 ci_id=None, daemon_version=None):
        self.path = path
        self.history_path = history_path or path.replace('-state.json', '-history.jsonl')
        self.poke_path = path.replace('-state.json', '-poke')  # флажок «проверь Jira сейчас» от дашборда
        self._task = None  # таймлайн текущей задачи для истории
        self._issue_results = {}  # задача Jira → итог последней попытки (для счётчиков карточки)
        self.max_events = max_events
        self.heartbeat_sec = heartbeat_sec
        self._lock = threading.RLock()
        self._issue_errors = []
        self._closed = False
        self._stop = threading.Event()
        now = time.time()
        self.state = {
            'version': 1,
            'project': project,
            'name': name or None,
            'jira_url': (jira_url or '').rstrip('/') or None,
            'ci_id': ci_id or None,                  # КЭ сервиса (если демон живёт «под КЭ»)
            'daemon_version': daemon_version or None,  # версия кода демона: видно, кто не перезапущен
            'pid': os.getpid(),
            'host': socket.gethostname(),
            'config': config_path,
            'started_at': now,
            'stage': 'starting',
            'stage_since': now,
            'issue': None,
            'detail': {},
            'heartbeat': now,
            'poll_interval': poll_interval,
            'next_poll_at': None,
            'counters': {'done': 0, 'warn': 0, 'failed': 0, 'tokens': 0},
            'last_result': None,
            'last_error': None,
            'events': [],
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.emit('starting')
        self._thread = threading.Thread(target=self._heartbeat_loop, name='state-heartbeat', daemon=True)
        self._thread.start()

    @classmethod
    def for_project(cls, logs_dir, project, **kwargs):
        name = f"{str(project or 'instance').lower()}-state.json"
        return cls(os.path.join(logs_dir, name), project, **kwargs)

    def set_features(self, revision, effective):
        with self._lock:
            self.state['feature_control'] = {'revision':revision, 'effective':effective, 'applied_at':time.time()}
            self._write()

    def set_prompts(self, revision, profile, subagent):
        with self._lock:
            self.state['prompt_control'] = {'revision': revision, 'profile': profile,
                                            'subagent': subagent, 'applied_at': time.time()}
            self._write()

    def set_cli(self, info):
        with self._lock:
            self.state['cli'] = info
            self._write()

    # --- публичный API ---
    def emit(self, stage, issue=None, message=None, **detail):
        if stage not in STAGES:
            raise ValueError(f'unknown stage: {stage}')
        with self._lock:
            now = time.time()
            if issue is None and stage in ISSUE_STAGES and stage not in ('generating',):
                issue = self.state.get('issue')
            if stage == 'generating':
                self._issue_errors = []
                self._task = {'issue': issue, 'started_at': now, 'gen_end': None, 'stand': None,
                              'migration': False, 'branch': None, 'service': detail.get('service'), 'request': detail.get('request')}
            elif self._task and stage in ('git', 'jenkins', 'jira'):
                if self._task['gen_end'] is None:
                    self._task['gen_end'] = now
                if stage == 'git':
                    self._task['branch'] = detail.get('branch')
                if stage == 'jenkins':
                    self._task['stand'] = detail.get('stand')
                    self._task['migration'] = bool(detail.get('migration'))
            if stage in ('starting', 'polling', 'idle', 'stopped'):
                issue = None
            self.state['stage'] = stage
            self.state['stage_since'] = now
            self.state['issue'] = issue
            self.state['detail'] = detail
            if stage == 'idle':
                self.state['next_poll_at'] = detail.get('next_poll_at')
            event = {'t': now, 'stage': stage}
            if issue:
                event['issue'] = issue
            if message:
                event['message'] = str(message)[:300]
            event.update(detail)
            events = self.state['events']
            events.append(event)
            del events[:-self.max_events]
            self._write()

    def finish_issue(self, issue, ok):
        """Итог по задаче: ok + ошибки в логе -> 'warn'."""
        with self._lock:
            errors = list(self._issue_errors)
            result = 'fail' if not ok else ('warn' if errors else 'ok')
            # Счётчики — по задачам Jira, а не по запускам: две ошибки и потом успех — одна сделанная
            # задача. Итог задачи — по её последней попытке с момента запуска демона
            if self._task and self._task.get('request'):
                self._append_history(issue, result, errors[-1] if errors else None)
                self.emit('success' if ok else 'error', issue, result=result)
                return
            self._issue_results[issue] = result
            counts = {'done': 0, 'warn': 0, 'failed': 0}
            for res in self._issue_results.values():
                if res in ('ok', 'warn', 'fail'):
                    counts[{'ok': 'done', 'warn': 'warn', 'fail': 'failed'}[res]] += 1
            self.state['counters'].update(counts)
            self.state['counters']['attempts'] = self.state['counters'].get('attempts', 0) + 1
            message = errors[-1] if errors else None
            self.state['last_result'] = {
                'issue': issue, 'result': result, 't': time.time(), 'message': message,
            }
            self._append_history(issue, result, message)
            self.emit('success' if ok else 'error', issue, message=message, result=result)

    def finish_blocked(self, issue, question):
        """Waiting for requirements is a completed attempt, not an execution failure."""
        with self._lock:
            if not (self._task and self._task.get('request')):
                self._issue_results[issue] = 'blocked'
                results = list(self._issue_results.values())
                self.state['counters'].update(done=results.count('ok'), warn=results.count('warn'), failed=results.count('fail'))
                self.state['counters']['attempts'] = self.state['counters'].get('attempts', 0) + 1
            self.state['last_result'] = {'issue': issue, 'result': 'blocked', 't': time.time(), 'message': question[:300]}
            self._append_history(issue, 'blocked', question[:300])
            self.emit('polling', result='blocked', message=question[:300])

    def attach_logging(self, logger=None):
        """Перехватывает ERROR-записи лога: последняя ошибка видна на дашборде."""
        (logger or logging.getLogger()).addHandler(_ErrorCapture(self))

    def note_tokens(self, issue, usage):
        """Расход токенов GigaCode по задаче: попадёт в history.jsonl и общий счётчик."""
        with self._lock:
            usage = {k: usage.get(k) for k in ('input', 'output', 'cached', 'total', 'source')}
            if self._task and self._task.get('issue') == issue:
                self._task['tokens'] = usage
            self.state['counters']['tokens'] = self.state['counters'].get('tokens', 0) + int(usage.get('total') or 0)
            self.state['last_tokens'] = dict(usage, issue=issue)
            self._write()

    def poke_requested(self):
        """Дашборд попросил проверить Jira, не дожидаясь конца ожидания (двойной клик по демону)."""
        try:
            if os.path.exists(self.poke_path):
                os.remove(self.poke_path)
                return True
        except OSError:
            pass
        return False

    def close(self, stage='stopped'):
        with self._lock:
            if self._closed:
                return
            self.emit(stage)
            self._closed = True
        self._stop.set()

    # --- внутреннее ---
    def _append_history(self, issue, result, message):
        now = time.time()
        task = self._task if self._task and self._task.get('issue') == issue else {'started_at': now}
        started = task.get('started_at') or now
        gen_end = task.get('gen_end') or now
        record = {
            'request': task.get('request'),
            'project': self.state.get('project'),
            'issue': issue,
            'result': result,
            'started_at': round(started, 1),
            'finished_at': round(now, 1),
            'gen_seconds': round(gen_end - started, 1),
            'total_seconds': round(now - started, 1),
            'stand': task.get('stand'),
            'migration': task.get('migration', False),
            'branch': task.get('branch'),
            'message': message,
            'tokens': task.get('tokens'),
            'service': task.get('service'),
        }
        self._task = None
        try:
            with open(self.history_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception:
            pass


    def _on_error_log(self, message):
        with self._lock:
            msg = str(message)[:300]
            self.state['last_error'] = {'t': time.time(), 'message': msg}
            if self.state.get('stage') in ('generating', 'git', 'jenkins', 'jira'):
                self._issue_errors.append(msg)

    def _heartbeat_loop(self):
        while not self._stop.wait(self.heartbeat_sec):
            with self._lock:
                if self._closed:
                    return
                self._write()

    def _write(self):
        self.state['heartbeat'] = time.time()
        tmp = f'{self.path}.{os.getpid()}.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            # Дашборд не должен ронять демона
            try:
                os.remove(tmp)
            except Exception:
                pass
