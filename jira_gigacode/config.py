"""Настройки инстанса: конфиг, tmp/.env и переменные окружения.

Порядок важности: переменная окружения с префиксом проекта (HRPPA_JIRA_TOKEN) →
общая переменная (JIRA_TOKEN) → значение из config/<проект>.json → значение по умолчанию.
"""
import json
import os
import sys
import subprocess

from .base import PROJECT_DIR, logger


def resolve_param(key, env_name, config, default):
    flags = config.get('_feature_flags', {}) if isinstance(config, dict) else {}
    if key in flags:
        return flags[key]
    if env_name:
        # Ключи с префиксом проекта (HRPPA_JIRA_TOKEN) главнее общих (JIRA_TOKEN) —
        # так в одном tmp/.env живут секреты нескольких демонов
        project = ''
        jira_cfg = config.get('jira') if isinstance(config, dict) else None
        if isinstance(jira_cfg, dict):
            project = str(jira_cfg.get('project') or '')
        variants = []
        for p in (project, project.upper()):
            if p and f'{p}_{env_name}' not in variants:
                variants.append(f'{p}_{env_name}')
        variants.append(env_name)
        for name in variants:
            if name in os.environ and os.environ[name].strip():
                return os.environ[name].strip()
    if config and key:
        parts = key.split('.')
        cursor = config
        for part in parts:
            if isinstance(cursor, dict) and part in cursor:
                cursor = cursor[part]
            else:
                cursor = None
                break
        if cursor is not None:
            return cursor
    return default


def env_override(env_name, config):
    """Имя переменной окружения, которая перекрывает этот ключ конфига (HRPPA_JIRA_TOKEN, JIRA_TOKEN…), или None."""
    project = ''
    jira_cfg = config.get('jira') if isinstance(config, dict) else None
    if isinstance(jira_cfg, dict):
        project = str(jira_cfg.get('project') or '')
    for name in dict.fromkeys([f'{project}_{env_name}', f'{project.upper()}_{env_name}', env_name] if project else [env_name]):
        if os.environ.get(name, '').strip():
            return name
    return None


def resolve_param_int(key, env_name, config, default):
    val = resolve_param(key, env_name, config, default)
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def resolve_param_bool(key, env_name, config, default):
    val = resolve_param(key, env_name, config, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ('1', 'true', 'yes', 'on', 'да'):
            return True
        if low in ('0', 'false', 'no', 'off', 'нет'):
            return False
    return default


def resolve_param_list(key, env_name, config, default):
    raw = resolve_param(key, env_name, config, default)
    if isinstance(raw, str):
        items = raw.split(',')
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    result = []
    seen = set()
    for item in items:
        value = str(item).strip()
        if value and value.lower() not in seen:
            seen.add(value.lower())
            result.append(value)
    return result


def normalized_ci_id(config):
    """КЭ в каноническом виде: 'CI03191860' / '03191860' → '3191860'; пусто — None."""
    ci_id = resolve_param('general.ci_id', None, config, None)
    if not ci_id:
        return None
    num = str(ci_id).strip().upper().removeprefix('CI').strip()
    if num.isdigit():
        num = str(int(num))  # '03191860' → '3191860'
    return num or None


def instance_key(config):
    """Идентификатор инстанса. КЭ уникален для сервиса даже внутри одного Jira-проекта
    (несколько сервисов могут жить в одном проекте), поэтому демон живёт «под КЭ».
    Без КЭ — ключ проекта, как раньше."""
    ci = normalized_ci_id(config)
    if ci:
        return f"ci{ci}"
    return str(resolve_param('jira.project', None, config, None) or 'instance').lower()


# --- Файлы: tmp/.env и config/<проект>.json ---
def load_env_file(path):
    """KEY=VALUE построчно (комментарии с #, кавычки снимаются) в os.environ.setdefault:
    реальное окружение главнее .env, .env главнее конфига."""
    try:
        with open(path, encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
        logger.info(f"Загружены переменные из {path}")
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"Не удалось прочитать {path}: {e}")
        return False


def load_config(config_path=None):
    script_dir = PROJECT_DIR
    if config_path is None:
        # Все конфиги живут в config/; старый корневой config.json — фолбэк для прежних установок
        for candidate in (os.path.join(script_dir, 'config', 'config.json'),
                          os.path.join(script_dir, 'config.json')):
            if os.path.exists(candidate):
                config_path = candidate
                break
    elif not os.path.exists(config_path):
        # Относительный путь сначала резолвится от директории запуска; если там пусто —
        # от папки скрипта, чтобы config/<проект>.json работал из любой директории
        candidate = os.path.join(script_dir, config_path)
        if os.path.exists(candidate):
            config_path = candidate
    if config_path is None:
        logger.error(f"Конфиг не найден: нет ни config/config.json, ни config.json рядом со скриптом "
                     f"({script_dir}). Укажите путь: python3 jira_to_gigacode.py config/<проект>.json")
        sys.exit(1)
    if not os.path.exists(config_path):
        logger.error(f"Конфиг не найден: {config_path} (запуск из {os.getcwd()}). Конфигурация обязательна.")
        sys.exit(1)
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки config.json: {e}")
        sys.exit(1)


def validate_config(config):
    from .prompt_control import effective
    effective(config)
    # Эпик опционален: без jira.epic_name/jira.epic_link_field демон берёт все задачи проекта
    required = (('jira.url', 'JIRA_URL'), ('jira.token', 'JIRA_TOKEN'), ('jira.project', None),
                ('jira.status_analysis', 'JIRA_STATUS_ANALYSIS'), ('jira.status_ready', 'JIRA_STATUS_READY'))
    if not resolve_param_bool('jira.enabled', 'JIRA_ENABLED', config, True):
        required = (('jira.project', None),)
    problems = [key for key, env_name in required if not resolve_param(key, env_name, config, None)]
    if problems:
        logger.error(f"В config.json отсутствуют или пусты ключи: {', '.join(problems)}")
        sys.exit(1)


# --- Производные настройки, нужные в нескольких местах ---
def repo_path(config):
    """Репозиторий, в котором работают GigaCode и git (по умолчанию — директория запуска)."""
    return resolve_param('general.repo_path', 'REPO_PATH', config, os.getcwd())


def issue_branch(issue_key, config):
    """Каноническая ветка задачи: {general.branch_prefix}/{KEY}."""
    if config.get('_requirements'):
        return config['_requirements']['branch']
    prefix = resolve_param('general.branch_prefix', 'BRANCH_PREFIX', config, 'feature/ai_team')
    return f"{prefix}/{issue_key}"


def base_branch(config, creation=False):
    """Имя ветки origin; отдельно задаётся база новых веток из Jira-комментариев."""
    key, env, default = ('base_branch_create_from', 'BASE_BRANCH_CREATE_FROM', 'master') if creation else (
        'base_branch', 'BASE_BRANCH', 'develop')
    raw = resolve_param('general.' + key, env, config, default)
    name = raw.strip() if isinstance(raw, str) else ''
    for prefix in ('refs/heads/', 'origin/'):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    # Full ref validation avoids Git revision expressions and option-like names.
    valid = name and not name.startswith('-') and name != 'HEAD' and subprocess.run(
        ['git', 'check-ref-format', 'refs/heads/' + name], capture_output=True, timeout=10).returncode == 0
    if not valid:
        raise ValueError(f'general.{key}: некорректное имя ветки {raw!r}')
    return name


def default_base_ref(config):
    return 'origin/' + base_branch(config)
