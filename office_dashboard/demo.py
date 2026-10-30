"""Симуляция демонов для проверки дашборда без Jira/GigaCode."""

import json
import logging
import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daemon_state import StateReporter  # noqa: E402

PROJECTS = ['HRPPA', 'PAYMT', 'CRMX', 'DOCS', 'MOBI', 'BILL', 'AUTH', 'SRCH', 'NOTIF', 'GEO', 'ANLT', 'CORE']
STANDS = ['dev', 'ift', 'nt', 'hr-draft']
NAMES = ['Олег', 'Марина', 'Игорь', 'Света', 'Денис', 'Аня', 'Пётр', 'Катя', 'Миша', 'Лена', 'Артём', 'Оля']


# КЭ демо-демонов: у HRPPA и PAYMT один проект на двоих сервисов в реальности бывает часто
CI_IDS = ['3191860', '15172563', '2048411', '9900412', '5512007', '7300125', '4410098', '8812003',
          '1200456', '6603321', '3009871', '7745120']
SERVICES = ['back', 'web']


def demo_tokens(rnd, gen_seconds):
    total = int(gen_seconds * rnd.uniform(120, 420))
    inp = int(total * rnd.uniform(0.78, 0.9))
    return {'input': inp, 'output': total - inp, 'cached': int(inp * rnd.uniform(0.2, 0.6)), 'total': total,
            'source': 'demo'}


def backfill_history(logs_dir, project, index, days=14):
    """История за прошлые дни, чтобы вкладка «Статистика» не была пустой."""
    rnd = random.Random(index * 104729)
    now = time.time()
    lines = []
    retry = None   # задача, которая упала: демон возьмёт её снова (2–3 попытки, потом обычно успех)
    t = now - days * 86400
    while True:
        t += rnd.uniform(0.6, 5.5) * 3600
        if t > now - 600:
            break
        lt = time.localtime(t)
        if lt.tm_hour < 8 or lt.tm_hour > 21 or (lt.tm_wday >= 5 and rnd.random() < 0.7):
            continue
        gen = rnd.uniform(4, 45) * 60
        r = rnd.random()
        result = 'fail' if r < 0.16 else 'warn' if r < 0.26 else 'ok'
        issue = retry or f'{project}-{rnd.randint(100, 9999)}'
        if retry and rnd.random() < 0.75:
            result = 'ok'
        retry = issue if result == 'fail' and rnd.random() < 0.8 else None
        stand = rnd.choice(STANDS) if result != 'fail' and rnd.random() < 0.6 else None
        total = gen + (0 if result == 'fail' else rnd.uniform(30, 120))
        lines.append({'project': project, 'issue': issue, 'result': result,
                      'started_at': round(t - total, 1), 'finished_at': round(t, 1), 'gen_seconds': round(gen, 1),
                      'total_seconds': round(total, 1), 'stand': stand, 'migration': bool(stand) and rnd.random() < 0.3,
                      'branch': None, 'tokens': demo_tokens(rnd, gen), 'service': rnd.choice(SERVICES) if index % 2 == 0 else None,
                      'message': ("Нет безопасного перехода к статусу 'Ревью'" if result == 'warn'
                                                  else 'GigaCode завершился с ошибкой (код 1)' if result == 'fail' else None)})
    with open(os.path.join(logs_dir, f'{project.lower()}-history.jsonl'), 'w', encoding='utf-8') as f:
        for rec in lines:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def _logger(logs_dir, project):
    log = logging.getLogger(f'demo.{project}')
    log.propagate = False
    log.setLevel(logging.INFO)
    handler = logging.FileHandler(os.path.join(logs_dir, f'{project.lower()}-agent.log'), encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    log.addHandler(handler)
    return log


def simulate(logs_dir, project, index, speed):
    rnd = random.Random(index * 7919)
    log = _logger(logs_dir, project)

    stop_flag = os.path.join(logs_dir, f'{project.lower()}-stop')
    start_flag = os.path.join(logs_dir, f'{project.lower()}-start')

    class Stopped(Exception):
        pass

    def wait(sec):
        # Кнопка «Остановить» на дашборде: демо-демон, как настоящий, бросает работу и уходит
        deadline = time.time() + max(0.2, sec / speed)
        while time.time() < deadline:
            if os.path.exists(stop_flag):
                os.remove(stop_flag)
                raise Stopped()
            time.sleep(min(0.25, max(0.0, deadline - time.time())))

    wait(index * 2.5)
    while True:
        reporter = None
        try:
            poll = rnd.choice([90, 150, 240])
            reporter = StateReporter.for_project(logs_dir, project, poll_interval=poll, heartbeat_sec=5,
                                                 ci_id=CI_IDS[index % len(CI_IDS)],
                                                 name=NAMES[index % len(NAMES)], jira_url='https://jira.example.com',
                                                 # один демон «забыли перезапустить» — на дашборде он помечен как устаревший
                                                 daemon_version='1.9.0' if index == 2 else '2.5.0')
            reporter.state['features'] = ['poke', 'stop']
            reporter.attach_logging(log)
            log.info('Запуск автономного мониторинга JIRA → GigaCode Orchestrator')
            wait(4)
            cycles = rnd.randint(4, 9)
            for _ in range(cycles):
                reporter.emit('polling')
                log.info(f'JQL: project={project} AND status IN ("Анализ")')
                wait(2)
                if rnd.random() < 0.45:
                    for _ in range(rnd.randint(1, 2)):
                        key = f'{project}-{rnd.randint(100, 999)}'
                        log.info(f'▶️ Обработка задачи {key}...')
                        reporter.emit('generating', key, **({'service': rnd.choice(SERVICES)} if index % 2 == 0 else {}))
                        gen = rnd.uniform(18, 50)
                        wait(gen)
                        usage = demo_tokens(rnd, gen * 30)
                        log.info(f"[{key}] Токены GigaCode: всего {usage['total']} (вход {usage['input']}, выход {usage['output']}), источник: demo")
                        reporter.note_tokens(key, usage)
                        if rnd.random() < 0.15:
                            log.error(f'[{key}] ❌ GigaCode завершился с ошибкой (код 1).')
                            reporter.finish_issue(key, False)
                            wait(4)
                            continue
                        branch = f'feature/ai_team/{key}'
                        reporter.emit('git', key, branch=branch)
                        log.info(f'[{key}] Пуш ветки {branch}...')
                        wait(5)
                        reporter.emit('reviewing', key, branch=branch)
                        log.info(f'[{key}] Независимое ревью {branch}...')
                        wait(rnd.uniform(8, 14))
                        if rnd.random() < 0.25:
                            log.warning(f'[{key}] Ревью: нужны исправления.')
                            reporter.emit('rework', key, branch=branch)
                            wait(rnd.uniform(10, 20))
                            reporter.emit('reviewing', key, branch=branch)
                            wait(6)
                        log.info(f'[{key}] ✅ Ревью: одобрено.')
                        if rnd.random() < 0.6:
                            stand = rnd.choice(STANDS)
                            migration = rnd.random() < 0.3
                            reporter.emit('jenkins', key, stand=stand, migration=migration)
                            log.info(f"[{key}] Лейбл jenkins_* найден: стенд='{stand}', миграция={'да' if migration else 'нет'}")
                            wait(6)
                        reporter.emit('jira', key, targets=['Ревью'])
                        log.info(f'[{key}] Поиск пути к статусам [Ревью]...')
                        wait(4)
                        if rnd.random() < 0.15:
                            log.error(f"[{key}] Нет безопасного перехода к целевым статусам [Ревью] из 'Анализ'.")
                        else:
                            log.info(f"[{key}] ✅ Цель достигнута: 'Ревью'")
                        reporter.finish_issue(key, True)
                        wait(5)
                else:
                    log.info('Ожидание задач...')
                    if rnd.random() < 0.08:
                        log.info('Ретроспектива: смотрю, что стало с задачами (3)...')
                        reporter.emit('retro', None, tasks=3)
                        wait(rnd.uniform(12, 20))
                    elif rnd.random() < 0.35:
                        backlog = f'{project}-{rnd.randint(1000, 1999)}'
                        log.info(f'[{backlog}] Простой: изучаю задачу из бэклога (ещё не изучалась).')
                        reporter.emit('exploring', backlog)
                        started = time.time()
                        wait(rnd.uniform(10, 18))
                        log.info(f'[{backlog}] Комментарий с предложениями оставлен в задаче.')
                        with open(os.path.join(logs_dir, f'{project.lower()}-proposals.jsonl'), 'a', encoding='utf-8') as f:
                            f.write(json.dumps({'issue': backlog, 'summary': rnd.choice(BACKLOG_TOPICS), 'result': 'posted',
                                                'started_at': started, 'finished_at': time.time(),
                                                'seconds': round(time.time() - started, 1), 'comment_id': None,
                                                'tokens': demo_tokens(rnd, 240)}, ensure_ascii=False) + '\n')
                reporter.emit('idle', next_poll_at=time.time() + poll / speed)
                deadline = time.time() + poll / speed
                while time.time() < deadline:
                    if reporter.poke_requested():
                        log.info('Внеочередная проверка Jira по запросу с дашборда')
                        break
                    wait(0.5 * speed)
            if rnd.random() < 0.5:
                # Падение без stopped: heartbeat прекращается -> «нет сигнала»
                log.error('Демон аварийно завершился (симуляция)')
                reporter._closed = True
                reporter._stop.set()
                wait(70)
            else:
                log.info('Цикл мониторинга завершён.')
                reporter.close()
                wait(20)
        except Stopped:
            log.info('Остановка по запросу с дашборда.')
            log.info('Цикл мониторинга завершён.')
            if reporter:
                reporter.close()
            # «Запустить» на дашборде — флажок {id}-start
            while not os.path.exists(start_flag):
                time.sleep(0.5)
            os.remove(start_flag)


def backfill_quality(logs_dir, project, index, weeks=12):
    """Сданные задачи за 12 недель и их исходы (как после ретроспектив): доля «без правок» растёт —
    демон учится."""
    rnd = random.Random(index * 7919 + 1)
    now = time.time()
    key = project.lower()
    delivered, outcomes = [], {}
    t = now - weeks * 7 * 86400
    while True:
        t += rnd.uniform(5, 26) * 3600
        if t > now - 3600:
            break
        issue = f'{project}-{rnd.randint(1000, 9999)}'
        head = f'{rnd.getrandbits(40):010x}'
        service = rnd.choice(SERVICES) if index % 2 == 0 else None
        delivered.append({'issue': issue, 'at': round(t, 1), 'head': head, 'branch': f'feature/ai_team/{issue}',
                          'base': 'origin/develop', 'service': service})
        age_days = (now - t) / 86400
        if age_days < 2.5 + index % 3:
            continue                                   # ретроспектива её ещё не видела
        progress = 1 - age_days / (weeks * 7)          # 0 — давно, 1 — сейчас
        r = rnd.random()
        as_is = 0.35 + 0.35 * progress
        if r < as_is:
            kind, changed = rnd.choice(['merged', 'merged', 'squashed']), False
        elif r < as_is + 0.08:
            kind, changed = 'dropped', False
        elif r < as_is + 0.14 and age_days < 20:
            kind, changed = 'open', False
        else:
            kind, changed = rnd.choice(['merged_changed', 'squashed']), True
        outcomes[issue] = {'issue': issue, 'head': head, 'service': service, 'delivered_at': round(t, 1),
                           'checked_at': now - rnd.uniform(0.5, 6) * 86400, 'outcome': kind, 'changed': changed,
                           'human_commits': rnd.randint(1, 4) if changed else 0,
                           'human_lines': rnd.randint(3, 140) if changed else 0,
                           'followups': 1 if kind != 'dropped' and rnd.random() < 0.12 else 0,
                           'jira_status': 'Готово' if kind != 'open' else 'Ревью'}
    with open(os.path.join(logs_dir, f'{key}-delivered.jsonl'), 'w', encoding='utf-8') as f:
        for e in delivered:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    with open(os.path.join(logs_dir, f'{key}-outcomes.json'), 'w', encoding='utf-8') as f:
        json.dump(outcomes, f, ensure_ascii=False, indent=2)


BACKLOG_TOPICS = ['Экспорт отчёта в Excel', 'Фильтр по дате в списке', 'Уведомления о статусе', 'Роль «аудитор»',
                  'Импорт справочника', 'Поиск по ФИО', 'Ограничение частоты запросов', 'Архив старых заявок']


def backfill_proposals(logs_dir, project, index, days=14):
    """Предложения в простое: прогоны исследования бэклога за две недели."""
    rnd = random.Random(index * 6151 + 3)
    now, t, lines = time.time(), time.time() - days * 86400, []
    while True:
        t += rnd.uniform(4, 30) * 3600
        if t > now - 900:
            break
        r = rnd.random()
        result = 'posted' if r < 0.84 else 'empty' if r < 0.92 else 'timeout' if r < 0.97 else 'not_posted'
        seconds = rnd.uniform(90, 600) if result != 'timeout' else 900
        lines.append({'issue': f'{project}-{rnd.randint(1000, 1999)}', 'summary': rnd.choice(BACKLOG_TOPICS),
                      'result': result, 'started_at': round(t - seconds, 1), 'finished_at': round(t, 1),
                      'seconds': round(seconds, 1), 'service': rnd.choice(SERVICES) if index % 2 == 0 else None,
                      'comment_id': str(rnd.randint(10000, 99999)) if result == 'posted' else None,
                      'tokens': demo_tokens(rnd, seconds * 0.6)})
    with open(os.path.join(logs_dir, f'{project.lower()}-proposals.jsonl'), 'w', encoding='utf-8') as f:
        for rec in lines:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def start_demo(logs_dir, count, speed=1.0):
    for i in range(count):
        project = PROJECTS[i % len(PROJECTS)] + ('' if i < len(PROJECTS) else str(i))
        backfill_history(logs_dir, project, i)
        backfill_quality(logs_dir, project, i)
        backfill_proposals(logs_dir, project, i)
        threading.Thread(target=simulate, args=(logs_dir, project, i, speed), daemon=True).start()
