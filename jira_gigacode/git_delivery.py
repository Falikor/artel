"""Доставка работы агента в remote: временные файлы, коммиты, пуш.

После генерации суб-агент мог оставить незакоммиченные файлы, свои коммиты (в том числе
прямо в develop — инцидент PERFREVIEW-5822) и мусор. Здесь всё это приводится к одной
канонической ветке задачи и пушится; временные файлы в PR не попадают.
"""
import fnmatch
import subprocess

from .base import logger
from .config import base_branch, resolve_param_list


# Временные файлы суб-агента не должны попадать в PR: GigaCode CLI держит
# свою диагностику в .gigacode/ (например .gigacode/tmp/*.py) — это содержимое
# инструмента, а не проекта. Прочие шаблоны задаёт конфиг (general.temp_files /
# TEMP_FILES, через запятую); непустой список заменяет дефолты целиком.
DEFAULT_TEMP_FILE_PATTERNS = ('.gigacode', '.gigacode/*', 'tmp*.py', '*_tmp.py', 'tmp_*.py')


def resolve_temp_patterns(config):
    patterns = resolve_param_list('general.temp_files', 'TEMP_FILES', config, [])
    return tuple(patterns) or DEFAULT_TEMP_FILE_PATTERNS


def collect_temp_files(paths, patterns):
    """Пути, подпадающие под шаблоны временных файлов.

    Шаблон со слэшем сверяется с путём от корня репозитория ('.gigacode/*'),
    без слэша — с именем файла в любом каталоге ('tmp*.py').
    """
    targets = []
    for raw in paths:
        path = str(raw).strip().strip('"')
        if path.endswith('/'):
            path = path[:-1]
        if not path:
            continue
        for pattern in patterns:
            probe = path if '/' in pattern else path.rsplit('/', 1)[-1]
            if fnmatch.fnmatchcase(probe, pattern):
                targets.append(path)
                break
    return targets


def drop_temp_untracked_files(issue_key, repo_path, status_porcelain, config):
    """Удаляет незакоммиченные временные файлы агента ДО git add .

    Слепой add уносил в PR диагностические скрипты суб-агента (.gigacode/tmp/*.py,
    скратч-файлы в корне). Удалить не смогли — останавливаем пайплайн: мусор в PR
    хуже, чем повторная попытка.
    """
    untracked = [line[3:] for line in status_porcelain.splitlines()
                 if line.startswith('??') and line[3:].strip()]
    targets = collect_temp_files(untracked, resolve_temp_patterns(config))
    for path in targets:
        clean_proc = subprocess.run(['git', 'clean', '-fd', '--', path],
                                    cwd=repo_path, capture_output=True, timeout=30)
        if clean_proc.returncode != 0:
            err = (f"Временный файл суб-агента '{path}' не удалось удалить "
                   f"(не пущу его в коммит): {clean_proc.stderr.decode('utf-8').strip()}")
            logger.error(f"[{issue_key}] {err}")
            return False
        logger.warning(f"[{issue_key}] Временный файл суб-агента удалён и не попал в коммит: {path}")
    return True


def strip_temp_committed_files(issue_key, repo_path, base_ref, config):
    """Суб-агент закоммитил временные файлы — пересобираем историю без них.

    ('none'|'stripped'|'error', err): none — временных файлов в коммитах нет,
    история суб-агента сохраняется как есть; stripped — коммиты задачи сплющены
    в один канонический (ветка принадлежит пайплайну и пушится --force);
    error — пересборка не удалась, пушить нельзя.
    """
    diff_proc = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=A', f'{base_ref}..HEAD'],
                               cwd=repo_path, capture_output=True, text=True, timeout=30)
    if diff_proc.returncode != 0:
        # Не смогли просмотреть состав коммитов — не блокируем доставку работы
        logger.warning(f"[{issue_key}] Не удалось проверить коммиты на временные файлы: "
                       f"{diff_proc.stderr.strip()}")
        return 'none', None
    targets = collect_temp_files(diff_proc.stdout.splitlines(), resolve_temp_patterns(config))
    if not targets:
        return 'none', None

    # Мягкий сброс к базе оставляет всю работу в индексе; выкидываем из неё
    # временные файлы (из индекса и с диска) и оформляем заново одним коммитом
    reset_proc = subprocess.run(['git', 'reset', '--soft', base_ref],
                                cwd=repo_path, capture_output=True, timeout=30)
    if reset_proc.returncode != 0:
        logger.error(f"[{issue_key}] Не удалось пересобрать коммиты: {reset_proc.stderr.decode('utf-8')}")
        return 'error', 'Не удалось пересобрать коммиты суб-агента'
    for path in targets:
        rm_proc = subprocess.run(['git', 'rm', '-rf', '--ignore-unmatch', '--', path],
                                 cwd=repo_path, capture_output=True, timeout=30)
        if rm_proc.returncode != 0:
            logger.error(f"[{issue_key}] Не удалось убрать временный файл '{path}' из коммитов: "
                         f"{rm_proc.stderr.decode('utf-8')}")
            return 'error', f"Не удалось убрать временный файл '{path}' из коммитов"
        logger.warning(f"[{issue_key}] Временный файл убран из коммитов суб-агента: {path}")

    subprocess.run(['git', 'add', '-A'], cwd=repo_path, capture_output=True, timeout=30)
    # HEAD после soft-reset указывает на базу: индекс против него — вся оставшаяся работа
    staged = subprocess.run(['git', 'diff', '--cached', '--name-only', 'HEAD'],
                            cwd=repo_path, capture_output=True, text=True, timeout=30)
    if staged.returncode == 0 and not staged.stdout.strip():
        # Агент закоммитил только временные файлы — работы не осталось.
        # collapsed (а не stripped): пустую ветку в origin пушить нельзя
        subprocess.run(['git', 'reset', '--hard', base_ref], cwd=repo_path, capture_output=True, timeout=30)
        return 'collapsed', None
    commit_msg = f"{issue_key}: Automated code generation via AI"
    commit_proc = subprocess.run(['git', 'commit', '-m', commit_msg],
                                 cwd=repo_path, capture_output=True, timeout=30)
    if commit_proc.returncode != 0:
        logger.error(f"[{issue_key}] Не удалось закоммитить чистую работу: {commit_proc.stderr.decode('utf-8')}")
        return 'error', 'Не удалось закоммитить работу суб-агента после очистки'
    logger.info(f"[{issue_key}] ✅ Коммиты суб-агента пересобраны одним коммитом без временных файлов.")
    return 'stripped', None


def inspect_after_generation(repo_path, base_ref):
    """Снимок рабочей области после генерации: (status, ahead, agent_branch)."""
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo_path, capture_output=True, text=True).stdout
    ahead = subprocess.run(['git', 'rev-list', '--count', f'{base_ref}..HEAD'],
                           cwd=repo_path, capture_output=True, text=True).stdout.strip()
    agent_branch = subprocess.run(['git', 'branch', '--show-current'],
                                  cwd=repo_path, capture_output=True, text=True).stdout.strip()
    return status, ahead, agent_branch


def remote_work_count(repo_path, base_ref, branch_name, fetch=False):
    """Сколько коммитов поверх базы лежит в origin/<ветка задачи> (0 — ветки нет или пуста)."""
    if fetch:
        subprocess.run(['git', 'fetch', 'origin', f'+refs/heads/{branch_name}:refs/remotes/origin/{branch_name}'],
                       cwd=repo_path, capture_output=True, timeout=60)
    proc = subprocess.run(['git', 'rev-list', '--count', f'{base_ref}..origin/{branch_name}'],
                          cwd=repo_path, capture_output=True, text=True, timeout=30)
    try:
        return int(proc.stdout.strip()) if proc.returncode == 0 else 0
    except ValueError:
        return 0


def describe_agent_work(issue_key, repo_path, base_ref, branch_name, config):
    """Что агент оставил после себя, без учёта его временных файлов. Пустая строка — ничего."""
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo_path,
                            capture_output=True, text=True, timeout=30).stdout
    changed = []
    temp_patterns = resolve_temp_patterns(config)
    for line in status.splitlines():
        path = line[3:].strip()
        if path and not collect_temp_files([path], temp_patterns):
            changed.append(path)
    ahead = subprocess.run(['git', 'rev-list', '--count', f'{base_ref}..HEAD'], cwd=repo_path,
                           capture_output=True, text=True, timeout=30).stdout.strip()
    parts = []
    if changed:
        parts.append(f"изменённых файлов: {len(changed)}")
    if ahead not in ('', '0'):
        parts.append(f"коммитов поверх базы: {ahead}")
    if not parts:
        remote = remote_work_count(repo_path, base_ref, branch_name)
        if remote:
            parts.append(f"в origin/{branch_name} уже {remote} коммит.")
    return ', '.join(parts)


def deliver_dirty_worktree(issue_key, repo_path, branch_name, base_ref, status_porcelain, config=None):
    """Классический путь: незакоммиченные изменения — оформляем в каноническую ветку сами.
    Временные файлы агента (диагностические скрипты и пр.) удаляются до коммита."""
    if not drop_temp_untracked_files(issue_key, repo_path, status_porcelain, config):
        return False

    checkout_proc = subprocess.run(['git', 'checkout', '-B', branch_name, base_ref], cwd=repo_path, capture_output=True, timeout=30)
    if checkout_proc.returncode != 0:
        logger.error(f"[{issue_key}] Не удалось создать ветку {branch_name}: {checkout_proc.stderr.decode('utf-8')}")
        return False

    logger.info(f"[{issue_key}] Коммит изменений...")
    subprocess.run(['git', 'add', '.'], cwd=repo_path, capture_output=True, timeout=30)
    commit_msg = f"{issue_key}: Automated code generation via AI"
    commit_proc = subprocess.run(['git', 'commit', '-m', commit_msg], cwd=repo_path, capture_output=True, timeout=30)
    if commit_proc.returncode != 0:
        staged = subprocess.run(['git', 'diff', '--cached', '--name-only', 'HEAD'],
                               cwd=repo_path, capture_output=True, text=True, timeout=30)
        if staged.returncode == 0 and not staged.stdout.strip():
            # Вся «грязь» была временным мусором и уже удалена: коммитить нечего.
            # Пушить пустую ветку (= базу) нельзя — она затрёт remote и даст
            # пустой PR (инцидент PERFREVIEW-5822); продолжаем как при «изменений нет»
            logger.warning(f"[{issue_key}] После очистки рабочей области не осталось изменений — пуш отменён.")
            return True
        logger.error(f"[{issue_key}] Не удалось закоммитить изменения: {commit_proc.stderr.decode('utf-8')}")
        return False

    logger.info(f"[{issue_key}] Пуш ветки {branch_name}...")
    push_proc = subprocess.run(['git', 'push', '-u', 'origin', branch_name, '--force'], cwd=repo_path, capture_output=True, timeout=120)
    if push_proc.returncode != 0:
        logger.error(f"[{issue_key}] Ошибка пуша: {push_proc.stderr.decode('utf-8')}")
        return False
    logger.info(f"[{issue_key}] ✅ Git операции выполнены.")
    return True


def deliver_agent_commits(issue_key, repo_path, branch_name, agent_branch, ahead, base_ref, config=None):
    """Суб-агент закоммитил сам (кейс HRPPA-683; исторически прямо в develop — PERFREVIEW-5822):
    очистка от временных файлов, парковка при необходимости, выравнивание общего ствола,
    пуш канонической ветки."""
    # Закоммиченные временные файлы вырезаем до парковки: пересборка идёт на месте HEAD
    strip_state, strip_err = strip_temp_committed_files(issue_key, repo_path, base_ref, config)
    if strip_state == 'error':
        logger.error(f"[{issue_key}] Пуш отменён: {strip_err}.")
        return False
    if strip_state == 'collapsed':
        # Коммиты суб-агента оказались только временными файлами: работы не осталось.
        # Пушить пустую ветку (= базу) нельзя — она затрёт remote и даст пустой PR;
        # ствол, если агент коммитил в него, всё равно выравниваем
        logger.warning(f"[{issue_key}] После удаления временных файлов от коммитов "
                       f"суб-агента не осталось работы — пуш отменён.")
        if agent_branch != branch_name and agent_branch in (
            'develop', 'master', base_branch(config), base_ref.removeprefix('origin/')):
            reset_proc = subprocess.run(['git', 'reset', '--hard', f'origin/{agent_branch}'], cwd=repo_path, capture_output=True, timeout=30)
            if reset_proc.returncode != 0:
                logger.warning(f"[{issue_key}] Не удалось выровнять {agent_branch}: {reset_proc.stderr.decode('utf-8')}")
            else:
                logger.info(f"[{issue_key}] {agent_branch} выровнен с origin после чистки.")
        return True
    if strip_state == 'stripped':
        ahead = '1' if ahead not in ('', '0') else ahead  # история сплющена в один коммит

    # Незакоммиченные правки поверх коммитов прицепляем к вершине: без этого они
    # потерялись бы при возврате рабочей области на общий ствол (dirty-путь сюда
    # больше не попадает — у пост-обработки коммиты агента приоритетнее)
    status_proc = subprocess.run(['git', 'status', '--porcelain'], cwd=repo_path, capture_output=True, text=True, timeout=30)
    if status_proc.returncode == 0 and status_proc.stdout.strip():
        subprocess.run(['git', 'add', '-A'], cwd=repo_path, capture_output=True, timeout=30)
        staged = subprocess.run(['git', 'diff', '--cached', '--name-only', 'HEAD'],
                                cwd=repo_path, capture_output=True, text=True, timeout=30)
        if staged.returncode != 0:
            logger.error(f"[{issue_key}] Не удалось проверить индекс перед коммитом правок: {staged.stderr.strip()}")
            return False
        if staged.stdout.strip():
            commit_msg = f"{issue_key}: Automated code generation via AI"
            commit_proc = subprocess.run(['git', 'commit', '-m', commit_msg],
                                         cwd=repo_path, capture_output=True, timeout=30)
            if commit_proc.returncode != 0:
                logger.error(f"[{issue_key}] Не удалось прицепить незакоммиченные правки: {commit_proc.stderr.decode('utf-8')}")
                return False
            logger.info(f"[{issue_key}] Незакоммиченные правки агента добавлены к его коммитам.")

    # Парковка нужна только если коммитил НЕ в каноническую ветку:
    # git branch -f падает на активной в worktree ветке ('cannot force update'),
    # а когда HEAD уже на branch_name — парковать нечего, коммиты там и лежат
    if agent_branch != branch_name:
        park_proc = subprocess.run(['git', 'branch', '-f', branch_name, 'HEAD'], cwd=repo_path, capture_output=True, timeout=30)
        if park_proc.returncode != 0:
            logger.error(f"[{issue_key}] Не удалось запарковать коммиты в {branch_name}: {park_proc.stderr.decode('utf-8')}")
            return False

    # Коммитил прямо в общий develop/master — выравниваем эту ветку с её origin,
    # чтобы AI-коммиты не уехали в общий ствол при следующем ручном pull/push из IDE
    if agent_branch != branch_name and agent_branch in (
            'develop', 'master', base_branch(config), base_ref.removeprefix('origin/')):
        logger.info(f"[{issue_key}] Суб-агент коммитил в {agent_branch} — выравниваю локальный {agent_branch}...")
        reset_proc = subprocess.run(['git', 'reset', '--hard', f'origin/{agent_branch}'], cwd=repo_path, capture_output=True, timeout=30)
        if reset_proc.returncode != 0:
            logger.warning(f"[{issue_key}] Не удалось выровнять {agent_branch}: {reset_proc.stderr.decode('utf-8')}")

    # Пушим именно каноническую ветку (HEAD после сброса develop мог откатиться),
    # чтобы Jenkins (refName) и ревью видели работу.
    # --force как в классическом пути: каноническая ветка задачи принадлежит пайплайну,
    # повторный запуск по той же задаче переотводит её заново
    logger.info(f"[{issue_key}] Пуш коммитов суб-агента ({ahead}) в {branch_name}...")
    push_proc = subprocess.run(['git', 'push', '--force', 'origin', branch_name], cwd=repo_path, capture_output=True, timeout=120)
    if push_proc.returncode != 0:
        # Фейл пуша останавливает пайплайн: Jenkins и Jira-переходы допустимы, только когда
        # работа реально добралась до remote. Иначе тикет ложно уезжает в ST (PERFREVIEW-5822)
        logger.error(f"[{issue_key}] Пуш коммитов суб-агента не удался: {push_proc.stderr.decode('utf-8')}")
        return False
    logger.info(f"[{issue_key}] ✅ Коммиты суб-агента запушены в {branch_name}.")
    return True
