"""Пробный запуск --dry-run: что демон сделал бы с каждой задачей, без изменений.

Только чтение: Jira (поиск, поля, лейблы, переходы) и git (fetch, rev-list, status).
Ни генерации, ни пушей, ни деплоя, ни переводов, ни комментариев.
"""
import os
import shutil
import subprocess

from . import jira_client, routing
from .base import logger
from .explore import explore_statuses, iter_backlog, should_explore
from .config import issue_branch, repo_path, resolve_param, resolve_param_bool, resolve_param_int, resolve_param_list
from .gigacode import MAX_TASK_TEXT_CHARS
from .git_delivery import remote_work_count
from .git_workspace import generation_was_interrupted, resolve_base_ref
from .jenkins import deploy_params, jenkins_job_path, jenkins_settings, parse_jenkins_label
from .retry import _load_pending_transitions


def run_dry_run(config):
    logger.info("=" * 60)
    logger.info("DRY-RUN: один проход без генерации, пушей, деплоя, переводов и комментариев")
    logger.info("=" * 60)
    statuses = resolve_param_list('jira.status_analysis', 'JIRA_STATUS_ANALYSIS', config, [])
    issues = jira_client.get_issues_by_statuses(statuses, config=config)
    if not issues:
        logger.info(f"[DRY-RUN] В статусах [{', '.join(statuses)}] задач нет — демон бы ждал.")
        _explain_explore(config)
    else:
        logger.info(f"[DRY-RUN] Нашёл бы задачи: {', '.join(issues)}")
        for key in issues:
            try:
                dry_run_issue(key, config)
            except Exception as e:
                logger.error(f"[{key}] [DRY-RUN] Ошибка разбора: {e}")
        if explore_statuses(config):
            logger.info("[DRY-RUN] Бэклог изучается только в простое — пока есть задачи, исследования не будет.")
    logger.info("DRY-RUN завершён: в Jira, репозитории и Jenkins ничего не изменено (кроме git fetch).")


def _explain_explore(config):
    """Какие задачи бэклога демон изучил бы в простое."""
    statuses = explore_statuses(config)
    if not statuses:
        logger.info("[DRY-RUN] Исследование бэклога выключено (нет explore.statuses).")
        return
    found = 0
    for key, meta in iter_backlog(config):
        found += 1
        ok, why = should_explore(key, meta, config)
        verdict = 'изучил бы' if ok else 'пропустил бы'
        logger.info(f"[{key}] [DRY-RUN] Простой: {verdict} — {why}. «{meta.get('summary')}»")
    if not found:
        logger.info(f"[DRY-RUN] В статусах [{', '.join(statuses)}] задач для исследования нет.")


def dry_run_issue(key, config):
    """Что демон сделал бы с одной задачей."""
    P = f"[{key}] [DRY-RUN]"
    owner_config = config
    logger.info(f"{P} ─── {key} ───")
    if routing.services(config):
        fields = jira_client.fetch_issue_routing(key, config)
        service, reason = routing.route(*(fields or ('', [])), config)
        if service is None:
            logger.warning(f"{P} Не взял бы задачу: {reason} — спросил бы в задаче, к какому сервису она относится.")
            return
        logger.info(f"{P} {reason} → репозиторий {service['repo_path']}")
        config = routing.config_for_service(config, service)
    from .dependencies import admit, DependencyBlocked
    try:
        config = admit(key, config, comment=False, owner_config=owner_config)
    except DependencyBlocked as exc:
        logger.info(f'{P} Не взял бы задачу: {exc}')
        return
    branch_name = issue_branch(key, config)

    if key in _load_pending_transitions():
        logger.info(f"{P} Есть запись «осталось только перевести»: генерацию бы НЕ запускал, повторил бы только перевод.")
    elif not _explain_generation(P, key, repo_path(config), branch_name, config):
        return
    _explain_jenkins(P, key, branch_name, config)
    _explain_transition(P, key, config)
    if resolve_param_bool('jira.result_comments', 'JIRA_RESULT_COMMENTS', config, True):
        logger.info(f"{P} Оставил бы в задаче комментарий-отчёт.")


def _explain_generation(P, key, repo, branch_name, config):
    """База, судьба рабочей ветки, текст задачи, CLI. False — задача была бы пропущена."""
    subprocess.run(['git', 'fetch', 'origin'], cwd=repo, capture_output=True, timeout=60)
    base_ref, base_err = resolve_base_ref(key, repo, config)
    if base_err:
        logger.error(f"{P} {base_err} — задача была бы пропущена.")
        return False
    logger.info(f"{P} База: {base_ref}, ветка задачи: {branch_name}")

    parked = _count_commits(repo, f'{base_ref}..{branch_name}')
    if parked:
        if generation_was_interrupted(repo, key):
            logger.info(f"{P} Прошлая генерация оборвалась: отложил бы её {parked} коммит. в "
                        f"refs/ai-team-interrupted/ и сгенерировал заново.")
        else:
            unpushed = _count_commits(repo, f'origin/{branch_name}..{branch_name}')
            if unpushed is None or unpushed > 0:
                logger.info(f"{P} В локальной ветке {parked} незапушенных коммит. прошлой попытки — "
                            f"донёс бы их до origin без новой генерации.")
            else:
                logger.info(f"{P} Работа прошлой попытки уже в origin — переотвёл бы ветку от {base_ref} "
                            f"и запустил генерацию заново (с push --force).")
    else:
        logger.info(f"{P} Отвёл бы {branch_name} от {base_ref} и запустил GigaCode.")

    remote = remote_work_count(repo, base_ref, branch_name)
    if remote:
        logger.info(f"{P} Сейчас в origin/{branch_name}: {remote} коммит. поверх базы.")
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True, timeout=30)
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        logger.warning(f"{P} В рабочей области {len(dirty)} незакоммиченных изменений — смешались бы с работой агента.")

    fields = jira_client.fetch_issue_fields(key, config)
    if fields:
        description = str(fields.get('description') or '')
        note = ' — будет усечено' if len(description) > MAX_TASK_TEXT_CHARS else ''
        logger.info(f"{P} Тема: «{str(fields.get('summary') or '').strip()}», описание: {len(description)} симв.{note}")
    gigacode_path = str(resolve_param('general.gigacode_path', 'GIGACODE_PATH', config, 'gigacode'))
    timeout = resolve_param_int('general.gigacode_timeout_seconds', 'GIGACODE_TIMEOUT', config, 3600)
    found = shutil.which(os.path.expanduser(gigacode_path)) or f'{gigacode_path} (НЕ НАЙДЕН)'
    logger.info(f"{P} GigaCode: {found}, таймаут {timeout} с")
    return True


def _count_commits(repo, rev_range):
    proc = subprocess.run(['git', 'rev-list', '--count', rev_range], cwd=repo,
                          capture_output=True, text=True, timeout=30)
    out = proc.stdout.strip()
    return int(out) if proc.returncode == 0 and out.isdigit() else None


def _explain_jenkins(P, key, branch_name, config):
    matches = parse_jenkins_label(jira_client.fetch_labels(key, config))
    if not matches:
        logger.info(f"{P} Jenkins: лейбла jenkins_* нет — деплой не запускался бы.")
        return
    stand, migration = matches[0]
    settings = jenkins_settings(config)
    params = deploy_params(branch_name, stand, migration)
    if settings['url'] and settings['job_name']:
        logger.info(f"{P} Jenkins: запустил бы {settings['url']}/job/{jenkins_job_path(settings['job_name'])} c {params}")
    else:
        logger.warning(f"{P} Jenkins: лейбл {stand} есть, но настройки Jenkins неполные — деплой был бы пропущен.")
    if len(matches) > 1:
        logger.warning(f"{P} Несколько лейблов jenkins_* ({matches}) — взял бы первый.")


def _explain_transition(P, key, config):
    targets = resolve_param_list('jira.status_ready', 'JIRA_STATUS_READY', config, [])
    current = jira_client.fetch_status(key, config) or '?'
    transitions = jira_client.fetch_transitions(key, config) or []
    direct = jira_client.find_target_transition(transitions, targets)
    if direct:
        logger.info(f"{P} Перевод: из «{current}» через «{direct.get('name')}» → «{direct['to'].get('name')}».")
    else:
        logger.warning(f"{P} Перевод: из «{current}» нет прямого перехода в [{', '.join(targets)}] "
                       f"(доступно: {[(t.get('to') or {}).get('name') for t in transitions]}) — понадобился бы человек.")
