"""Обработка задач: генерация → Git → Jenkins → перевод в Jira → отчёт.

poll_once — один проход опроса Jira, process_issue — одна задача целиком,
run_post_generation_steps — всё, что после успешной генерации.
"""
import subprocess
import hashlib
import json
import time

from . import retry, retry_control, maintenance, experience, issue_report, jira_client, retro, review, runtime, memory_verify, pr_review, dependencies, blocked, notifications
from .agent_contract import result_status
from .requirements_snapshot import fetch_snapshot
from .base import logger
from .config import base_branch, issue_branch, repo_path, resolve_param_list
from .explore import explore_idle
from .gigacode import STOPPED, run_gigacode_orchestrator
from .git_delivery import (deliver_agent_commits, deliver_dirty_worktree, drop_temp_untracked_files,
                           inspect_after_generation, remote_work_count)
from .git_workspace import _base_ref_cache, resolve_base_ref
from .issue_report import report_add_tokens, report_set, report_start
from .jenkins import deploy_for_issue
from .reports import post_result_comment
from .routing import resolve_issue_service
from .retry import (RETRY_FAILURES_LIMIT, _RETRY_STATE, note_retry_outcome, pending_transition_active,
                    pending_transition_add, pending_transition_done, retry_blocked)
from .tokens import extract_token_usage


# =====================================================================
# Основной цикл: один проход опроса
# =====================================================================
def poll_once(config, retry_cooldown_sec):
    from . import feature_control, prompt_control
    config = feature_control.apply(config)
    runtime.state.set_features(config.get('_feature_revision', 0), feature_control.effective(config))
    values = prompt_control.effective(config)
    runtime.state.set_prompts(config.get('_prompt_revision', 0), values['profile'], values['subagent'])
    return _poll_once(config, retry_cooldown_sec)


def _poll_once(config, retry_cooldown_sec):
    """Ищет задачи в статусах-источниках и обрабатывает их по очереди."""
    maintenance.checkpoint(lambda: runtime.running)
    from .requirements_rework import maybe_run
    from .feature_control import enabled, changed
    if enabled(config, 'jira.enabled'):
        notifications.flush(config, logs_dir=blocked.path_for(config).parent)
    if enabled(config, 'jira.enabled') and enabled(config, 'requirements.enabled') and maybe_run(config, retry_cooldown_sec):
        return
    statuses = resolve_param_list('jira.status_analysis', 'JIRA_STATUS_ANALYSIS', config, [])
    runtime.state.emit('polling')
    issues = jira_client.get_issues_by_statuses(statuses, config=config) if enabled(config, 'jira.enabled') else []
    if enabled(config, 'jira.enabled'):
        issues = list(dict.fromkeys(issues + blocked.candidate_keys(config)))
    if not issues:
        _idle(config)
        return
    logger.info(f"Найдены задачи в статусах [{', '.join(statuses)}]: {', '.join(issues)}")
    worked = False
    for key in dependencies.order_candidates(issues, config):
        maintenance.checkpoint(lambda: runtime.running)
        if not runtime.running:
            break
        if changed(config):
            return
        if enabled(config, 'requirements.enabled') and maybe_run(config, retry_cooldown_sec):
            return
        if retry.control_path():
            decision = retry_control.entries(retry.control_path()).get(key, {})
            if decision.get('mode') == 'blocked' or (decision.get('mode') == 'paused' and decision.get('pause_until', 0) > time.time()):
                logger.info(f"[{key}] Пропуск по решению владельца")
                continue
        # Resolve service again even for transition-only retries: use the current config.
        task_config = resolve_issue_service(key, config)
        if task_config is None:
            continue
        task_config = blocked.admit(key, task_config)
        if task_config is None:
            continue
        try:
            task_config = dependencies.admit(key, task_config, owner_config=config)
        except dependencies.DependencyBlocked:
            continue
        pending = pending_transition_active(key)
        if retry.control_path():
            scope = hashlib.sha256(json.dumps({'config':{k:v for k,v in task_config.items() if not k.startswith('_')},
                'jql':jira_client.task_jql(', '.join(statuses), config),
                'repo':repo_path(task_config),
                'ready':resolve_param_list('jira.status_ready', 'JIRA_STATUS_READY', task_config, [])}, sort_keys=True, default=str).encode()).hexdigest()
            reason = retry_control.begin(retry.control_path(), key, scope, pending)
            if reason:
                logger.info(f"[{key}] Пропуск: {reason}")
                if retry_control.entries(retry.control_path()).get(key, {}).get('needs_review'):
                    notifications.notify(task_config, key, 'retry-confirmation', reason,
                        action='Откройте демона → «Повторы»: разрешите повтор, поставьте паузу или исключите задачу. Ответ в Jira сам по себе не разрешает повтор после смены конфига.',
                        logs_dir=blocked.path_for(config).parent)
                continue
        elif retry_blocked(key):
            continue
        notifications.resolve(task_config, key, 'retry-confirmation', logs_dir=blocked.path_for(config).parent)
        worked = True
        if pending:
            retry_pending_transition(key, task_config, retry_cooldown_sec)
        else:
            process_issue(key, task_config, retry_cooldown_sec)
        time.sleep(5)
    if not worked and runtime.running:
        _idle(config)


def _idle(config):
    """Dependencies / owner holds mean idle even when Jira returned some keys."""
    from .feature_control import enabled, changed
    logger.info("Ожидание задач, доступных к выполнению...")
    pr_review.maybe_run(config)
    maintenance.checkpoint(lambda: runtime.running)
    if changed(config) or not runtime.running:
        return
    if enabled(config, 'jira.enabled'):
        retro.maybe_run(config)
    if changed(config) or not runtime.running:
        return
    if enabled(config, 'jira.enabled'):
        maintenance.checkpoint(lambda: runtime.running)
        explore_idle(config)
    if changed(config) or not runtime.running:
        return
    maintenance.checkpoint(lambda: runtime.running)
    memory_verify.maybe_run(config)


def _fmt_until(key):
    return time.strftime('%H:%M', time.localtime(_RETRY_STATE[key]['until']))


def _note_outcome(key, ok, config, retry_cooldown_sec, comment_on_cooldown=True):
    """Фиксирует исход попытки; после серии неудач — кулдаун и комментарий в задаче."""
    if not note_retry_outcome(key, ok, retry_cooldown_sec):
        return
    logger.warning(f"[{key}] {RETRY_FAILURES_LIMIT} неудачи подряд — пауза до {_fmt_until(key)}.")
    # «Застрявший перевод» уже описан своим комментарием — общий не дублируем
    if comment_on_cooldown and not pending_transition_active(key):
        post_result_comment(key, config, 'failed', until=_RETRY_STATE[key]['until'])


# =====================================================================
# Одна задача
# =====================================================================
def process_issue(key, config, retry_cooldown_sec):
    """Задача целиком: генерация, токены, пост-обработка, отчёт, учёт неудач."""
    logger.info(f"▶️ Переделка постановки {key}..." if config.get("_requirements") else f"▶️ Обработка задачи {key}...")
    _base_ref_cache.pop(key, None)  # новый заход по задаче — базу выбираем заново
    report_start(key)
    snapshot = config.get('_clarification') or fetch_snapshot(key, config)
    config = dict(config, _task_snapshot=snapshot)
    blocked.started(key, config)
    service = (config.get('general') or {}).get('service')
    if service:
        report_set(key, service=service)
    runtime.state.emit('generating', key, request=(config.get('_requirements') or {}).get('request'), **({'service': service} if service else {}))

    gen_started = time.time()
    success, output_text = run_gigacode_orchestrator(key, config=config)
    report_set(key, gen_seconds=time.time() - gen_started)
    _note_tokens(key, output_text, config, gen_started)
    if output_text == STOPPED:
        # Демон останавливается: попытка не засчитывается ни в статистику, ни в кулдаун
        logger.warning(f"[{key}] Обработка прервана остановкой демона — повтор потребует разрешения в панели ретраев.")
        notifications.notify(config, key, 'retry-confirmation', 'Выполнение остановлено. Подтвердите повтор после проверки незавершённой работы.',
            action='Демон → «Повторы» → разрешить повтор.', logs_dir=blocked.path_for(config).parent)
        return

    if result_status(output_text) == 'blocked':
        return _hold_blocked(key, config, output_text, snapshot)

    if success and config.get('_requirements'):
        fresh = jira_client.fetch_issue_fields(key, config)
        if fresh != config['_requirements']['fields']:
            logger.error(f'[{key}] Постановка изменилась или недоступна после генерации; публикация остановлена.')
            success = False
    if success:
        ok = run_post_generation_steps(key, config)
        blocked_output = (issue_report._REPORT.get(key) or {}).get('blocked_output')
        if blocked_output:
            return _hold_blocked(key, config, blocked_output, snapshot)
        if not ok and not runtime.running:
            # Остановили посреди пост-обработки (ревью, доработка): это не неудача задачи
            logger.warning(f"[{key}] Обработка прервана остановкой демона — повтор потребует разрешения в панели ретраев.")
            notifications.notify(config, key, 'retry-confirmation', 'Пост-обработка прервана. Проверьте состояние ветки и подтвердите повтор.',
                action='Демон → «Повторы» → разрешить повтор.', logs_dir=blocked.path_for(config).parent)
            return
        if ok:
            blocked.completed(key, config)
            experience.clear_issue_notes(config, key)
            post_result_comment(key, config, 'done')
            retro.record_delivery(key, config)
    else:
        logger.error(f"[{key}] ❌ Пропуск пост-обработки из-за ошибки генерации кода.")
        ok = False
    tokens = (issue_report._REPORT.get(key) or {}).get('tokens')
    if tokens and tokens.get('total'):
        runtime.state.note_tokens(key, tokens)
    runtime.state.finish_issue(key, ok)
    if not config.get('_requirements'):
        _note_outcome(key, success and ok, config, retry_cooldown_sec)
    return bool(success and ok)


def _hold_blocked(key, config, output, snapshot):
    row = blocked.hold(key, config, output, snapshot)
    tokens = (issue_report._REPORT.get(key) or {}).get('tokens')
    if tokens and tokens.get('total'):
        runtime.state.note_tokens(key, tokens)
    finish = getattr(runtime.state, 'finish_blocked', None)
    if finish:
        finish(key, row['question'])
    else:
        runtime.emit('polling', key, result='blocked', message=row['question'][:300])
    return False


def retry_pending_transition(key, config, retry_cooldown_sec):
    """Код уже запушен прошлой попыткой — повторяем только перевод, без генерации и перезаписи ветки."""
    logger.info(f"[{key}] Код уже в remote, не удался только перевод в Jira — повторяю перевод.")
    report_start(key)
    report_set(key, retry_only=True)
    ok = jira_client.transition_issue(key, config)
    if ok:
        pending_transition_done(key)
        post_result_comment(key, config, 'done')
    runtime.state.finish_issue(key, ok)
    _note_outcome(key, ok, config, retry_cooldown_sec, comment_on_cooldown=False)


def _note_tokens(key, output_text, config, gen_started):
    try:
        usage = extract_token_usage(output_text, config, gen_started)
    except Exception as e:
        logger.warning(f"[{key}] Не удалось посчитать токены: {e}")
        return
    if usage:
        logger.info(f"[{key}] Токены GigaCode: всего {usage['total']} "
                    f"(вход {usage.get('input') or '?'}, выход {usage.get('output') or '?'}, "
                    f"кэш {usage.get('cached') or '?'}), источник: {usage['source']}")
        report_add_tokens(key, usage)


# =====================================================================
# После успешной генерации: Git → Jenkins → Jira
# =====================================================================
def run_post_generation_steps(issue_key, config):
    """True — работа в remote, прошла ревью и задача переведена в целевой статус."""
    logger.info(f"[{issue_key}] Запуск пост-обработки (Git -> ревью -> Jenkins -> Jira)...")
    repo, branch_name = repo_path(config), issue_branch(issue_key, config)

    # 1. GIT: работа агента должна оказаться в origin/<ветка задачи>
    if not deliver_work(issue_key, repo, branch_name, config):
        return False

    # 1½. НЕЗАВИСИМОЕ РЕВЬЮ (с доработкой по замечаниям) — до деплоя и перевода
    if not review_passed(issue_key, repo, branch_name, config):
        return False

    # 2. JENKINS (запуск только по лейблу в задаче: jenkins_{стенд} или jenkins_{стенд}_migration)
    deploy_for_issue(issue_key, branch_name, config)

    # 3. JIRA: перевод в целевой статус
    return transition_with_memory(issue_key, config)


def review_passed(issue_key, repo, branch_name, config):
    """False — ревью вернуло работу: задача не переводится, замечания уходят в задачу и в следующую попытку."""
    base_ref, base_err = resolve_base_ref(issue_key, repo, config)
    if base_err:
        logger.error(f"[{issue_key}] {base_err}")
        return False
    result = review.review_and_rework(
        issue_key, config, branch_name, base_ref,
        redeliver=lambda key: deliver_work(key, repo, branch_name, config))
    if (issue_report._REPORT.get(issue_key) or {}).get('blocked_output'):
        return False
    if not runtime.running:
        logger.warning(f"[{issue_key}] Демон останавливается — деплой и перевод отложены до следующего запуска.")
        return False
    if not review.blocks_delivery(result, config):
        if result:
            experience.clear_issue_notes(config, issue_key)
        return True
    logger.error(f"[{issue_key}] ❌ Работа не прошла ревью — задача НЕ переводится, Jenkins не запускается.")
    experience.save_review_notes(config, issue_key, result.get('notes'))
    post_result_comment(issue_key, config, 'review_changes')
    return False


def deliver_work(issue_key, repo, branch_name, config):
    """Доставка работы агента в remote. True — в origin/<ветка задачи> есть коммиты поверх базы."""
    try:
        subprocess.run(['git', 'fetch', 'origin'], cwd=repo, capture_output=True, timeout=60)

        # База та же, что при подготовке ветки: считаем коммиты агента относительно неё,
        # иначе для задач от релизной базы ahead захватил бы и сами релизные коммиты
        base_ref, base_err = resolve_base_ref(issue_key, repo, config)
        if base_err:
            logger.error(f"[{issue_key}] {base_err}")
            return False

        runtime.state.emit('git', issue_key, branch=branch_name, base=base_ref)
        report_set(issue_key, branch=branch_name, base=base_ref)

        if not _push_agent_work(issue_key, repo, branch_name, base_ref, config):
            return False

        # Единая проверка для всех путей доставки: переводить задачу и деплоить можно, только
        # если работа реально лежит в origin/<ветка задачи>. Ловит и «агент ничего не сделал»,
        # и случаи, когда после чистки временных файлов коммитить/пушить было нечего
        remote_ahead = remote_work_count(repo, base_ref, branch_name, fetch=True)
        if remote_ahead:
            report_set(issue_key, commits=remote_ahead, **_shas(repo, base_ref, branch_name))
            logger.info(f"[{issue_key}] В origin/{branch_name} работа есть ({remote_ahead} коммит. поверх {base_ref}).")
        else:
            logger.error(f"[{issue_key}] ❌ В origin/{branch_name} нет работы поверх {base_ref} — "
                         f"задача НЕ переводится в Jira, Jenkins не запускается.")

        _return_to_base(issue_key, repo, config)
        return bool(remote_ahead)
    except Exception as e:
        logger.error(f"[{issue_key}] Ошибка Git: {e}")
        return False


def _shas(repo, base_ref, branch_name):
    """Коммиты на момент сдачи: вершина ветки задачи и база — по ним ретроспектива потом поймёт,
    что стало с работой (слита ли, что поменяли люди)."""
    out = {}
    for name, ref in (('head', f'origin/{branch_name}'), ('base_sha', base_ref)):
        proc = subprocess.run(['git', 'rev-parse', ref], cwd=repo, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            out[name] = proc.stdout.strip()
    return out


def _push_agent_work(issue_key, repo, branch_name, base_ref, config):
    """Оформляет то, что оставил агент, в ветку задачи и пушит. False — доставка сорвалась."""
    # Что суб-агент реально оставил после себя — фиксируем ДО сброса рабочей области:
    # незакоммиченные файлы, его собственные коммиты поверх базовой ветки, текущая ветка
    status, ahead, agent_branch = inspect_after_generation(repo, base_ref)

    # Временные файлы чистим ДО выбора пути доставки: единственной «грязью» мог
    # оказаться сам мусор (PERFREVIEW-5822: статус из-за него уводил пайплайн в
    # dirty-путь, где checkout -B затирал коммиты агента, а пустой коммит уезжал в remote)
    if not drop_temp_untracked_files(issue_key, repo, status, config):
        return False
    if status.strip():
        # после удаления мусора состав рабочей области изменился — смотрим заново
        status, ahead, agent_branch = inspect_after_generation(repo, base_ref)

    if ahead not in ('', '0'):
        # Коммиты суб-агента приоритетнее незакоммиченной грязи: dirty-путь обязан
        # сбрасывать ветку на базу (checkout -B) и потому не имеет права работать,
        # когда работа агента уже закоммичена
        return deliver_agent_commits(issue_key, repo, branch_name, agent_branch, ahead, base_ref, config)
    if status.strip():
        # Классический путь: есть незакоммиченные изменения — оформляем в каноническую ветку сами
        return deliver_dirty_worktree(issue_key, repo, branch_name, base_ref, status, config)
    logger.warning(f"[{issue_key}] Новых изменений нет ни в рабочей области, ни в коммитах.")
    return True


def _return_to_base(issue_key, repo, config):
    """Вернуть клон на настроенную базу; не выполнять pull, если checkout не удался."""
    branch = base_branch(config)
    checkout = subprocess.run(['git', 'checkout', branch], cwd=repo, capture_output=True, text=True, timeout=30)
    if checkout.returncode:
        logger.warning(f'[{issue_key}] Не удалось вернуться на {branch}: {checkout.stderr}')
        return
    update = subprocess.run(['git', 'pull', '--ff-only', 'origin', branch], cwd=repo,
                            capture_output=True, text=True, timeout=120)
    if update.returncode:
        logger.warning(f'[{issue_key}] Ошибка обновления {branch}: {update.stderr}')
        subprocess.run(['git', 'fetch', 'origin'], cwd=repo, capture_output=True, timeout=60)
        return
    logger.info(f'[{issue_key}] ✅ Проект обновлён ({branch}).')


def transition_with_memory(issue_key, config):
    """Перевод в Jira. Код уже в remote: если перевод не удался, задача остаётся в статусе-источнике,
    и без запоминания следующий опрос заново запустил бы генерацию и затёр ветку через --force.
    Поэтому запоминаем «осталось только перевести» и возвращаем неудачу."""
    if jira_client.transition_issue(issue_key, config):
        pending_transition_done(issue_key)
        return True
    if config.get('_requirements'):
        return False
    first_time = pending_transition_add(issue_key)
    logger.error(f"[{issue_key}] Код запушен, но задача не переведена в Jira. Следующие попытки "
                 f"будут повторять только перевод, без новой генерации.")
    if first_time:
        post_result_comment(issue_key, config, 'stuck')
    return False
