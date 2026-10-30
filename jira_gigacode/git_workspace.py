"""Подготовка репозитория к генерации: базовая ветка, рабочая ветка задачи, восстановление.

- resolve_base_ref — база задачи из конфига или ветка из комментария «branch: …»;
- prepare_working_branch — чистая ветка от базы или донесение незапушенной работы прошлой попытки;
- метка «генерация в процессе» — чтобы оборванный прогон не выдать за готовую работу.
"""
import os
import re
import subprocess
import time

from . import jira_client, runtime
from .base import logger
from .config import base_branch, default_base_ref
from .git_delivery import strip_temp_committed_files
from .issue_report import ARTEL_REPORT_TAG


# --- Базовая ветка задачи: develop по умолчанию, override из комментария ---
# В комментарии к задаче можно указать «branch: <имя_ветки>» или «ветка: <имя_ветки>»;
# действует последний маркер по хронологии. Если указанной ветки нет на remote,
# она создаётся от general.base_branch_create_from (master) и публикуется в origin.
BASE_BRANCH_MARKER = re.compile(r'\b(branch|ветка)\b\s*[:=]\s*`?\s*([A-Za-z0-9_][A-Za-z0-9._/\-]*)', re.IGNORECASE)

# База одного цикла обработки задачи: подготовка и пост-обработка обязаны использовать
# одну и ту же ветку, даже если комментарий с маркером поправили во время генерации.
# Сбрасывается в основном цикле при новом заходе по задаче.
_base_ref_cache = {}


def resolve_base_ref(issue_key, repo_path, config):
    """(base_ref, err): base_ref вида 'origin/develop' | 'origin/<имя>'; err=None при успехе."""
    if config and config.get('_requirements'):
        return config['_requirements']['base'], None
    resume = (config or {}).get('_clarification_resume') or {}
    if re.fullmatch(r'[0-9a-f]{40,64}', str(resume.get('commit') or '')):
        return resume['commit'], None
    if issue_key in _base_ref_cache:
        return _base_ref_cache[issue_key]

    comments = jira_client.fetch_comments(issue_key, config)
    if comments is None:
        return None, f"Не удалось получить комментарии задачи {issue_key} из Jira"

    base_name = None
    base_marker = None
    # Свои автоотчёты демон не читает: в них упоминается ветка задачи, и она не должна
    # становиться базой следующего прогона
    comments = [c for c in comments if ARTEL_REPORT_TAG not in str(c.get('body') or '')]
    for c in sorted(comments, key=lambda c: str(c.get('created') or '')):
        for m in BASE_BRANCH_MARKER.finditer(str(c.get('body') or '')):
            keyword, raw = m.group(1), m.group(2)
            name = raw.strip('`').rstrip('/')
            while name.startswith('refs/heads/'):
                name = name[len('refs/heads/'):]
            if name:
                base_name = name  # последний маркер по хронологии выигрывает
                base_marker = f"{keyword.lower()}: {raw.strip('`').rstrip('/')}"
    if not base_name:
        try:
            ref = default_base_ref(config)
        except ValueError as exc:
            return None, str(exc)
        found = subprocess.run(['git', 'rev-parse', '--verify', '--quiet',
                                f'refs/remotes/{ref}^{{commit}}'], cwd=repo_path, capture_output=True)
        if found.returncode:
            return None, f'Базовая ветка {ref} из general.base_branch не найдена; проверьте конфиг и git fetch origin'
        logger.info(f'[{issue_key}] Базовая ветка задачи: {ref} (general.base_branch).')
        _base_ref_cache[issue_key] = (ref, None)
        return _base_ref_cache[issue_key]

    try:
        creation_ref = 'origin/' + base_branch(config, creation=True)
    except ValueError as exc:
        return None, str(exc)

    # Аудит: фиксируем маркер так, как он написан в комментарии, до нормализации имени
    logger.info(f"[{issue_key}] Маркер базовой ветки в комментарии: \"{base_marker}\" → база {base_name}.")

    # Требуется свежий git fetch origin до вызова (делают оба вызывающих)
    rmt = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', f'origin/{base_name}'],
                         cwd=repo_path, capture_output=True)
    if rmt.returncode == 0:
        logger.info(f"[{issue_key}] Базовая ветка {base_name} есть на remote.")
        _base_ref_cache[issue_key] = (f'origin/{base_name}', None)
        return _base_ref_cache[issue_key]

    if runtime.DRY_RUN:
        logger.info(f"[{issue_key}] [DRY-RUN] Базовой ветки {base_name} нет на remote — создал бы её "
                    f"(от {creation_ref}, если её нет и локально) и запушил в origin.")
        return f'origin/{base_name}', None

    # Нет на remote: существующую локальную публикуем как есть, иначе создаём от origin/master
    loc = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', base_name],
                         cwd=repo_path, capture_output=True)
    created_here = loc.returncode != 0
    if created_here:
        mk = subprocess.run(['git', 'branch', base_name, creation_ref],
                            cwd=repo_path, capture_output=True)
        if mk.returncode != 0:
            return None, f"Не удалось создать базовую ветку {base_name} от {creation_ref}: {mk.stderr.decode('utf-8').strip()}"
        logger.info(f"[{issue_key}] Базовой ветки {base_name} нет на remote — создана от {creation_ref}.")
    else:
        logger.info(f"[{issue_key}] Базовой ветки {base_name} нет на remote, но есть локально — публикую как есть.")

    push_proc = subprocess.run(['git', 'push', 'origin', base_name],
                               cwd=repo_path, capture_output=True, timeout=120)
    if push_proc.returncode != 0:
        if created_here:
            subprocess.run(['git', 'branch', '-D', base_name], cwd=repo_path, capture_output=True)
        return None, f"Не удалось опубликовать базовую ветку {base_name} в origin: {push_proc.stderr.decode('utf-8').strip()}"
    logger.info(f"[{issue_key}] ✅ Базовая ветка {base_name} опубликована в origin.")
    _base_ref_cache[issue_key] = (f'origin/{base_name}', None)
    return _base_ref_cache[issue_key]


# --- Метка «генерация в процессе» ---
# Ставится перед запуском CLI и снимается только после успешной генерации.
# Если метка осталась (таймаут, ошибка CLI, kill -9 демона, перезагрузка), коммиты
# в локальной ветке — недоделанная работа: её нельзя «восстанавливать» и пушить как готовую.
# Метка лежит в .git репозитория: привязана к его состоянию и не попадает в коммиты.
def _inflight_marker_path(repo_path, issue_key):
    try:
        proc = subprocess.run(['git', 'rev-parse', '--absolute-git-dir'],
                              cwd=repo_path, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    git_dir = proc.stdout.strip()
    if proc.returncode != 0 or not git_dir:
        return None
    safe_key = re.sub(r'[^A-Za-z0-9._-]', '_', issue_key)
    return os.path.join(git_dir, f'ai_team_inflight_{safe_key}')


def mark_generation_started(repo_path, issue_key):
    path = _inflight_marker_path(repo_path, issue_key)
    if not path:
        logger.warning(f"[{issue_key}] Не удалось поставить метку генерации — "
                       f"защита от пуша недоделанной работы для этого прогона не действует.")
        return
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
    except OSError as e:
        logger.warning(f"[{issue_key}] Не удалось поставить метку генерации {path}: {e}")


def mark_generation_finished(repo_path, issue_key):
    path = _inflight_marker_path(repo_path, issue_key)
    if path:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"[{issue_key}] Не удалось снять метку генерации {path}: {e}")


def generation_was_interrupted(repo_path, issue_key):
    """True — прошлая генерация по задаче не завершилась успешно (метка осталась)."""
    path = _inflight_marker_path(repo_path, issue_key)
    return bool(path and os.path.exists(path))


def stash_interrupted_work(issue_key, repo_path, branch_name):
    """Недоделанные коммиты не выбрасываются бесследно: ссылка refs/ai-team-interrupted/...
    не видна как ветка и не пушится, но работу можно посмотреть и достать вручную."""
    ref = f"refs/ai-team-interrupted/{issue_key}-{time.strftime('%Y%m%d-%H%M%S')}"
    proc = subprocess.run(['git', 'update-ref', ref, branch_name],
                          cwd=repo_path, capture_output=True, timeout=30)
    if proc.returncode == 0:
        logger.warning(f"[{issue_key}] Недоделанная работа прерванного прогона сохранена в {ref} "
                       f"(посмотреть: git log {ref}).")
    else:
        logger.warning(f"[{issue_key}] Не удалось сохранить недоделанную работу в {ref}: "
                       f"{proc.stderr.decode('utf-8', errors='replace').strip()}")


def prepare_working_branch(issue_key, repo_path, base_ref, branch_name, config=None):
    """Готовит каноническую ветку до генерации.

    ('ready'|'recovered'|'error', err):
      ready     — чистая ветка от базы под новую генерацию;
      recovered — незапушенная работа прошлой попытки донесена до remote, генерация не нужна;
      error     — подготовка невозможна, err содержит причину.
    """
    # Незапушенная работа предыдущей попытки не должна молча затираться
    # переотведением ветки. Вместо слепого отказа пробуем донести её до remote:
    # права могли уже выдать (PERFREVIEW-5822) — тогда задача завершится
    # без повторной генерации, той же генерацией из прошлого цикла
    parked = subprocess.run(['git', 'rev-list', '--count', f'{base_ref}..{branch_name}'],
                            cwd=repo_path, capture_output=True, text=True, timeout=30)
    has_parked = parked.returncode == 0 and parked.stdout.strip() not in ('', '0')
    if generation_was_interrupted(repo_path, issue_key):
        # Прошлый прогон оборвался (таймаут, ошибка CLI, падение демона): его коммиты —
        # полуфабрикат. Восстанавливать и пушить их как готовую работу нельзя —
        # откладываем в служебную ссылку и генерируем заново
        if has_parked:
            logger.warning(f"[{issue_key}] Прошлая генерация не завершилась — её коммиты "
                           f"({parked.stdout.strip()}) не будут запушены.")
            stash_interrupted_work(issue_key, repo_path, branch_name)
        has_parked = False
        mark_generation_finished(repo_path, issue_key)
    if has_parked:
        pushed = subprocess.run(['git', 'rev-list', '--count', f'origin/{branch_name}..{branch_name}'],
                                cwd=repo_path, capture_output=True, text=True, timeout=30)
        if pushed.returncode != 0 or pushed.stdout.strip() not in ('', '0'):
            # Сначала переключаемся на восстанавливаемую ветку — до remote-мутаций
            co_proc = subprocess.run(['git', 'checkout', branch_name],
                                      cwd=repo_path, capture_output=True, timeout=60)
            if co_proc.returncode != 0:
                err = (f"Не удалось переключиться на восстановленную ветку {branch_name}: "
                       f"{co_proc.stderr.decode('utf-8').strip()}")
                logger.error(f"[{issue_key}] {err}")
                return 'error', err
            # Работа прошлой попытки чистится от временных файлов тем же аппаратом,
            # что и свежая генерация: мусор не должен доехать до PR и через recovery
            strip_state, strip_err = strip_temp_committed_files(issue_key, repo_path, base_ref, config)
            if strip_state == 'error':
                logger.error(f"[{issue_key}] Восстановление {branch_name} прервано: {strip_err}.")
                return 'error', strip_err
            if strip_state == 'collapsed':
                # В коммитах прошлой попытки были только временные файлы: ветка сброшена
                # на базу, восстанавливать нечего. Пушить её нельзя — --force затёр бы
                # remote базой и дал пустой PR (PERFREVIEW-5822). Генерируем заново
                logger.warning(f"[{issue_key}] В коммитах прошлой попытки только временные файлы — "
                               f"восстанавливать нечего, запускается генерация.")
                return _checkout_fresh_branch(issue_key, repo_path, base_ref, branch_name)
            rec_proc = subprocess.run(['git', 'push', '--force', 'origin', branch_name],
                                       cwd=repo_path, capture_output=True, timeout=120)
            if rec_proc.returncode != 0:
                err = (f"В локальной ветке {branch_name} незапушенные коммиты "
                       f"({parked.stdout.strip()}) прошлой попытки, донести их до origin не удалось: "
                       f"{rec_proc.stderr.decode('utf-8').strip()}")
                logger.error(f"[{issue_key}] {err}")
                return 'error', err
            logger.info(f"[{issue_key}] ✅ Коммиты прошлой попытки ({parked.stdout.strip()}) запушены "
                        f"в {branch_name} — повторная генерация не требуется.")
            return 'recovered', None
        # Работа прошлой попытки уже целиком на remote: тикет вернулся в рабочий статус —
        # считаем это осознанным до-делыванием и генерируем заново с перезаписью ветки
        logger.info(f"[{issue_key}] Работа прошлой попытки уже на remote ({branch_name}) — "
                    f"ветка переотводится от {base_ref}, запускается повторная генерация.")

    return _checkout_fresh_branch(issue_key, repo_path, base_ref, branch_name)


def _checkout_fresh_branch(issue_key, repo_path, base_ref, branch_name):
    """Чистая каноническая ветка от базы под новую генерацию."""
    prep_proc = subprocess.run(['git', 'checkout', '-B', branch_name, base_ref],
                               cwd=repo_path, capture_output=True, timeout=60)
    if prep_proc.returncode != 0:
        err = f"Не удалось подготовить ветку {branch_name} от {base_ref}: {prep_proc.stderr.decode('utf-8')}"
        logger.error(f"[{issue_key}] {err}")
        return 'error', err
    logger.info(f"[{issue_key}] Рабочая ветка {branch_name} готова (от {base_ref}).")
    return 'ready', None
