"""Независимое ревью работы агента до деплоя и перевода задачи.

После того как работа доставлена в origin/<ветка задачи>, отдельный прогон GigaCode
(можно другой моделью — review.extra_args) читает diff и код и выносит вердикт:

    REVIEW_VERDICT: APPROVE          — работу можно отдавать людям;
    REVIEW_VERDICT: REQUEST_CHANGES  — есть что исправить (замечания между REVIEW_NOTES_START/END).

Ревьюер работает во временной копии ветки (worktree) и не может испортить рабочий клон.
При REQUEST_CHANGES агент дорабатывает ветку по замечаниям (review.max_rework_rounds раз),
после чего ревью повторяется. Если замечания остались, задача не переводится и не деплоится
(review.block_on_changes), в задаче появляется комментарий с замечаниями, а следующая
попытка получит их в команде.

Настройки (раздел "review" конфига):
    enabled            true
    gigacode_path      CLI ревьюера (по умолчанию general.gigacode_path)
    extra_args         доп. флаги CLI ревьюера, например ["--model", "GigaChat-2-Max"]
    prompt_prefix      начало команды, например "вызови суб агента /code-reviewer "
    timeout_seconds    1200
    max_rework_rounds  1     — сколько раз агент дорабатывает по замечаниям в том же прогоне
    block_on_changes   true  — с замечаниями задачу не переводить
    on_no_verdict      "pass" (не блокировать, если ревьюер не дал вердикта) или "block"
    max_diff_chars     40000
"""
import re
import subprocess
import time

from . import experience, runtime
from .base import logger
from .config import (repo_path, resolve_param, resolve_param_bool, resolve_param_int, resolve_param_list)
from .gigacode import (TEMP_FILES_RULE, run_cli, task_text_block)
from . import prompt_control
from .agent_contract import EXECUTION_CONTRACT, result_status
from .git_workspace import mark_generation_finished, mark_generation_started
from .issue_report import report_add_tokens, report_set
from .tokens import extract_token_usage
from .worktree import WorktreeError, temp_worktree, worktree_is_clean

APPROVE, CHANGES, NO_VERDICT = 'approve', 'changes', 'none'
VERDICT_RE = re.compile(r'REVIEW_VERDICT:\s*(APPROVE|REQUEST_CHANGES)\b')
NOTES_START, NOTES_END = 'REVIEW_NOTES_START', 'REVIEW_NOTES_END'


def review_enabled(config):
    return resolve_param_bool('review.enabled', 'REVIEW_ENABLED', config, True)


def review_and_rework(issue_key, config, branch_name, base_ref, redeliver):
    """Ревью с доработкой. Возвращает {'verdict', 'notes', 'rounds'} или None, если ревью выключено.

    redeliver(issue_key) — повторная доставка в remote после доработки (из pipeline)."""
    if not review_enabled(config):
        return None
    max_rounds = max(0, resolve_param_int('review.max_rework_rounds', 'REVIEW_MAX_REWORK_ROUNDS', config, 1))
    reworks = 0
    while True:
        result = run_review(issue_key, config, branch_name, base_ref)
        result['rounds'] = reworks
        if result['verdict'] != CHANGES or reworks >= max_rounds or not runtime.running:
            break
        logger.info(f"[{issue_key}] Ревью вернуло работу с замечаниями — доработка {reworks + 1}/{max_rounds}.")
        if not run_rework(issue_key, config, branch_name, base_ref, result['notes']) or not redeliver(issue_key):
            break
        reworks += 1
    report_set(issue_key, review=result)
    return result


def blocks_delivery(result, config):
    """True — по итогу ревью задачу нельзя переводить и деплоить."""
    if not result:
        return False
    if result['verdict'] == 'blocked':
        return True
    if result['verdict'] == CHANGES:
        return resolve_param_bool('review.block_on_changes', 'REVIEW_BLOCK_ON_CHANGES', config, True)
    if result['verdict'] == NO_VERDICT:
        return str(resolve_param('review.on_no_verdict', 'REVIEW_ON_NO_VERDICT', config, 'pass')).lower() == 'block'
    return False


# --- ревьюер ---
def run_review(issue_key, config, branch_name, base_ref):
    """Один прогон ревьюера во временной копии origin/<ветка задачи>."""
    repo = repo_path(config)
    runtime.emit('reviewing', issue_key, branch=branch_name)
    subprocess.run(['git', 'fetch', 'origin', f'+refs/heads/{branch_name}:refs/remotes/origin/{branch_name}'],
                   cwd=repo, capture_output=True, timeout=60)
    head = f'origin/{branch_name}'
    prompt = prompt_control.decorate(build_review_prompt(issue_key, config, branch_name, base_ref,
                                     diff_for_review(repo, base_ref, head, config)), config, 'review')
    cli = resolve_param('review.gigacode_path', 'REVIEW_GIGACODE_PATH', config, None) or \
        resolve_param('general.gigacode_path', 'GIGACODE_PATH', config, 'gigacode')
    extra = resolve_param_list('review.extra_args', 'REVIEW_EXTRA_ARGS', config, [])
    timeout = resolve_param_int('review.timeout_seconds', 'REVIEW_TIMEOUT', config, 1200)
    started = time.time()
    try:
        with temp_worktree(repo, head, f'review-{issue_key}') as wt:
            logger.info(f"[{issue_key}] Независимое ревью {branch_name} (копия: {wt})...")
            returncode, output = run_cli(issue_key, cli, prompt, wt, timeout, extra_args=extra, purpose='review')
            if not worktree_is_clean(wt):
                logger.warning(f"[{issue_key}] Ревьюер изменил файлы во временной копии — изменения отброшены.")
    except (WorktreeError, OSError, subprocess.SubprocessError) as e:
        logger.error(f"[{issue_key}] Ревью не выполнено: {e}")
        return {'verdict': NO_VERDICT, 'notes': f'Ревью не выполнено: {e}'}
    _count_tokens(issue_key, output, config, started, 'ревью')
    if returncode is None:
        return {'verdict': NO_VERDICT, 'notes': 'Ревьюер не уложился в таймаут или демон останавливается.'}
    if result_status(output) == 'blocked':
        report_set(issue_key, blocked_output=output)
        return {'verdict': 'blocked', 'notes': output}
    result = parse_review(output)
    if result['verdict'] == APPROVE:
        logger.info(f"[{issue_key}] ✅ Ревью: одобрено.")
    elif result['verdict'] == CHANGES:
        logger.warning(f"[{issue_key}] Ревью: нужны исправления.")
    else:
        logger.warning(f"[{issue_key}] Ревьюер не дал вердикта (код {returncode}).")
    experience.remember_lessons(config, issue_key, output, 'ревью')
    return result


def build_review_prompt(issue_key, config, branch_name, base_ref, diff):
    prefix = str(resolve_param('review.prompt_prefix', 'REVIEW_PROMPT_PREFIX', config, '') or '')
    base_short = base_ref[len('origin/'):] if base_ref.startswith('origin/') else base_ref
    task_context = task_text_block(issue_key, config)
    return (
        f'{prefix}Ты — независимый ревьюер. Проверь изменения по задаче {issue_key}. '
        f'Текущая папка — копия ветки {branch_name}; база — {base_short}. '
        'Ничего не меняй в файлах и не коммить: только читай код и, если нужно, запускай тесты.'
        f'{task_context}'
        f'{experience.memory_block(config, task_context)}'
        f'\nИзменения (git diff {base_short}...{branch_name}, может быть усечён):\n---\n{diff}\n---\n'
        'Проверь: выполнены ли требования задачи; нет ли ошибок, регрессий и проблем безопасности; '
        'есть ли тесты на новое поведение; нет ли лишних файлов, секретов и отладочного кода.\n'
        'Ответ дай строго так:\n'
        'строка «REVIEW_VERDICT: » и одно из слов APPROVE (работу можно отдавать людям) '
        'или REQUEST_CHANGES (есть что исправить);\n'
        f'затем между строками {NOTES_START} и {NOTES_END} — замечания списком: что, где и как '
        'исправить (при APPROVE — короткое резюме).'
        f'{experience.lessons_request(config)}'
        f'{EXECUTION_CONTRACT}'
    )


def diff_for_review(repo, base_ref, head, config):
    limit = resolve_param_int('review.max_diff_chars', 'REVIEW_MAX_DIFF_CHARS', config, 40000)
    stat = subprocess.run(['git', 'diff', '--stat', f'{base_ref}...{head}'], cwd=repo,
                          capture_output=True, text=True, timeout=60).stdout
    diff = subprocess.run(['git', 'diff', f'{base_ref}...{head}'], cwd=repo,
                          capture_output=True, text=True, timeout=60, errors='replace').stdout
    if len(diff) > limit:
        diff = diff[:limit] + f'\n…(diff усечён: показано {limit} из {len(diff)} символов — остальное смотри в файлах)'
    return (stat + '\n' + diff).strip()


def parse_review(output):
    """{'verdict': approve|changes|none, 'notes': str} из вывода ревьюера (берётся последний вердикт)."""
    text = output or ''
    matches = VERDICT_RE.findall(text)
    verdict = NO_VERDICT
    if matches:
        verdict = APPROVE if matches[-1] == 'APPROVE' else CHANGES
    end = text.rfind(NOTES_END)
    start = text.rfind(NOTES_START, 0, end) if end >= 0 else -1
    notes = text[start + len(NOTES_START):end].strip() if start >= 0 else ''
    if not notes and verdict == CHANGES:
        notes = text.strip()[-3000:]
    return {'verdict': verdict, 'notes': notes[:8000]}


# --- доработка по замечаниям ---
def run_rework(issue_key, config, branch_name, base_ref, notes):
    """Агент дорабатывает ветку задачи в рабочем клоне. True — появились новые изменения."""
    repo = repo_path(config)
    runtime.emit('rework', issue_key, branch=branch_name)
    checkout = subprocess.run(['git', 'checkout', '-B', branch_name, f'origin/{branch_name}'],
                              cwd=repo, capture_output=True, text=True, timeout=60)
    if checkout.returncode != 0:
        logger.error(f"[{issue_key}] Доработка невозможна: не удалось переключиться на {branch_name}: "
                     f"{checkout.stderr.strip()}")
        return False
    task_context = task_text_block(issue_key, config)
    command = (
        f'вызови суб агента /{prompt_control.subagent(config)} доработай задачу {issue_key} '
        f'в репозитории {repo}. Работа уже сделана в ветке {branch_name} (от {base_ref}), '
        'но независимый ревьюер вернул её с замечаниями. Исправь их, коммить только в эту ветку; '
        'коммитить в базовую и любые другие ветки запрещено.'
        f'{task_context}'
        f'\nЗамечания ревьюера:\n---\n{notes}\n---\n'
        f'{experience.memory_block(config, task_context)}'
        f'{TEMP_FILES_RULE}'
        f'{experience.lessons_request(config)}'
        f'{EXECUTION_CONTRACT}'
    )
    cli = resolve_param('general.gigacode_path', 'GIGACODE_PATH', config, 'gigacode')
    timeout = resolve_param_int('general.gigacode_timeout_seconds', 'GIGACODE_TIMEOUT', config, 3600)
    mark_generation_started(repo, issue_key)
    started = time.time()
    try:
        returncode, output = run_cli(issue_key, cli, prompt_control.decorate(command, config, 'rework'), repo, timeout, purpose='rework')
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f"[{issue_key}] Доработка не запустилась: {e}")
        return False
    _count_tokens(issue_key, output, config, started, 'доработка')
    if returncode is None:
        return False
    changed = _has_new_work(repo, branch_name)
    if result_status(output) == 'blocked':
        report_set(issue_key, blocked_output=output)
        return False
    if returncode != 0 or result_status(output) == 'failure':
        logger.error(f"[{issue_key}] Доработка завершилась с ошибкой (код {returncode}).")
        return False
    if resolve_param_bool('general.require_success_marker', 'REQUIRE_SUCCESS_MARKER', config, False) and result_status(output) != 'success':
        logger.error(f"[{issue_key}] Доработка без финального сигнала успеха — включён строгий режим.")
        return False
    if not changed:
        logger.warning(f"[{issue_key}] Доработка не внесла изменений.")
        return False
    mark_generation_finished(repo, issue_key)
    experience.remember_lessons(config, issue_key, output, 'доработка')
    logger.info(f"[{issue_key}] Доработка по замечаниям ревью выполнена.")
    return True


def _has_new_work(repo, branch_name):
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True, timeout=30)
    ahead = subprocess.run(['git', 'rev-list', '--count', f'origin/{branch_name}..HEAD'], cwd=repo,
                           capture_output=True, text=True, timeout=30)
    return bool(status.stdout.strip()) or ahead.stdout.strip() not in ('', '0')


def _count_tokens(issue_key, output, config, started, what):
    try:
        usage = extract_token_usage(output, config, started)
    except Exception:
        usage = None
    if usage:
        logger.info(f"[{issue_key}] Токены GigaCode ({what}): всего {usage['total']}")
        report_add_tokens(issue_key, usage)
