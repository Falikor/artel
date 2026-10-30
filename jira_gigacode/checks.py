"""Проверка окружения при старте (и флаг --check): репозиторий, GigaCode, Jira, Jenkins.
"""
import os
import shutil
import subprocess
import urllib.error
import urllib.parse

from . import jira_client
from .config import default_base_ref, base_branch
from .base import PROJECT_DIR, logger
from .config import env_override, resolve_param, resolve_param_int, resolve_param_list
from .experience import memory_enabled, memory_path
from .explore import explore_statuses
from .jenkins import JENKINS_MIGRATION_PARAM, _jenkins_get, jenkins_job_path
from .logs import mask_secrets
from .review import review_enabled
from .routing import services, config_for_service


def _git(repo, *args, timeout=30):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))  # не зависать на запросе пароля


def run_startup_checks(config):
    """Проверяет то, что иначе всплыло бы только на первой задаче.
    Возвращает (errors, warnings); errors блокируют старт демона."""
    errors, warnings = [], []
    def ok(msg): logger.info(f"  ✅ {msg}")
    def warn(msg): warnings.append(msg); logger.warning(f"  ⚠️  {msg}")
    def fail(msg): errors.append(msg); logger.error(f"  ❌ {msg}")
    logger.info("Проверка окружения:")

    heads = None  # ветки origin, если удалось их получить
    service_heads = []

    # --- репозиторий (или репозитории сервисов) ---
    svcs = services(config)
    if svcs:
        # Переменные окружения главнее конфига: при сервисах они перекрыли бы настройки каждого сервиса
        for env_name, key, used in (('REPO_PATH', 'repo_path', True),
                                    ('JENKINS_JOB', 'jenkins.job_name', any((s.get('jenkins') or {}).get('job_name') for s in svcs)),
                                    ('COMPARE_URL', 'compare_url', any(s.get('compare_url') for s in svcs)),
                                    ('BRANCH_PREFIX', 'branch_prefix', any(s.get('branch_prefix') for s in svcs)),
                                    ('BASE_BRANCH', 'base_branch', True),
                                    ('BASE_BRANCH_CREATE_FROM', 'base_branch_create_from', True)):
            var = env_override(env_name, config) if used else None
            if var:
                warn(f"Переменная окружения {var} перекрывает {key} всех сервисов — у них будет одно значение. "
                     f"Уберите её из окружения или tmp/.env")
        for svc in svcs:
            repo = os.path.abspath(os.path.expanduser(str(svc['repo_path'])))
            svc_heads = _check_repo(repo, f"[{svc['name']}] ", ok, warn, fail, config_for_service(config, svc))
            service_heads.append((config_for_service(config, svc), svc_heads))
        names = ', '.join(svc['name'] for svc in svcs)
        ok(f"Сервисы: {names} — сервис задачи определяется по названию и лейблам")
    else:
        repo = resolve_param('general.repo_path', 'REPO_PATH', config, None)
        if not repo:
            repo = os.getcwd()
            warn(f"general.repo_path не задан — GigaCode и git будут работать в директории запуска: {repo}")
        heads = _check_repo(os.path.abspath(os.path.expanduser(str(repo))), '', ok, warn, fail, config)

    # --- GigaCode CLI ---
    gigacode_path = str(resolve_param('general.gigacode_path', 'GIGACODE_PATH', config, 'gigacode'))
    resolved = shutil.which(os.path.expanduser(gigacode_path))
    if resolved:
        ok(f"GigaCode CLI: {resolved}")
    else:
        fail(f"GigaCode CLI не найден или не исполняемый: {gigacode_path} (general.gigacode_path / GIGACODE_PATH)")

    from .feature_control import enabled
    if enabled(config, 'jira.enabled'):
        # --- Jira ---
        me = jira_client.jira_request('GET', '/rest/api/2/myself', config=config, max_retries=0, return_error=True)
        if me is None:
            warn("Jira недоступна (сеть или URL) — демон будет пробовать на каждом опросе")
        elif me.get('_http_error') in (401, 403):
            fail(f"Jira отклонила токен (HTTP {me['_http_error']}) — проверьте jira.token / JIRA_TOKEN")
        elif me.get('_http_error'):
            warn(f"Jira вернула HTTP {me['_http_error']} на проверку токена")
        else:
            ok(f"Jira: вход как {me.get('displayName') or me.get('name') or '?'}")
            project = resolve_param('jira.project', 'JIRA_PROJECT', config, '')
            pr = jira_client.jira_request('GET', f'/rest/api/2/project/{urllib.parse.quote(str(project))}', config=config,
                              max_retries=0, return_error=True)
            if pr is None or pr.get('_http_error'):
                code = pr.get('_http_error') if pr else 'нет ответа'
                fail(f"Проект Jira {project} не найден или нет доступа ({code})")
            else:
                ok(f"Проект Jira: {project} — {pr.get('name', '')}")

    if enabled(config, 'jira.enabled') and enabled(config, 'jenkins.enabled'):
        # --- Jenkins (нужен только для задач с лейблами jenkins_*) ---
        j = {k: resolve_param(f'jenkins.{k}', env, config, '') for k, env in
             (('url', 'JENKINS_URL'), ('user', 'JENKINS_USER'), ('token', 'JENKINS_TOKEN'), ('job_name', 'JENKINS_JOB'))}
        if not any(j.values()):
            logger.info("  ·  Jenkins не настроен — задачи с лейблами jenkins_* будут без деплоя")
        elif not all(j.values()):
            missing = [k for k, v in j.items() if not v]
            warn(f"Настройки Jenkins неполные (нет: {', '.join(missing)}) — деплой по лейблам jenkins_* будет пропускаться")
        else:
            api = (f"{str(j['url']).rstrip('/')}/job/{jenkins_job_path(j['job_name'])}"
                   f"/api/json?tree=name,property[parameterDefinitions[name]]")
            try:
                data = _jenkins_get(api, j['user'], j['token'])
                params = {d.get('name') for prop in data.get('property') or []
                          for d in (prop.get('parameterDefinitions') or [])}
                ok(f"Jenkins: джоба {data.get('name') or j['job_name']}")
                if not params:
                    warn("У джобы Jenkins нет параметров — ветка и стенд не передадутся (buildWithParameters)")
                else:
                    missing = [p for p in ('refName', 'filter') if p not in params]
                    if missing:
                        warn(f"У джобы Jenkins нет параметров {', '.join(missing)} — демон передаёт именно их")
                    if JENKINS_MIGRATION_PARAM not in params:
                        warn(f"У джобы Jenkins нет параметра {JENKINS_MIGRATION_PARAM} — лейблы jenkins_*_migration не включат миграцию")
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    warn(f"Jenkins отклонил учётные данные (HTTP {e.code}) — деплой не сработает")
                elif e.code == 404:
                    warn(f"Джоба Jenkins не найдена: {j['job_name']} — деплой не сработает")
                else:
                    warn(f"Jenkins вернул HTTP {e.code} на проверку джобы")
            except Exception as e:
                warn(f"Jenkins недоступен: {mask_secrets(e)}")

    # --- ревью, опыт, исследование бэклога ---
    try:
        for extra_config, extra_heads in service_heads or [(config, heads)]:
            _check_extras(extra_config, ok, warn, extra_heads)
    except ValueError as exc:
        fail(str(exc))

    # Optional Bitbucket integration uses Python REST, never model MCP.
    from .bitbucket_client import Client
    from .config import resolve_param_bool
    for cfg in ([config_for_service(config, svc) for svc in svcs] or [config]):
        if resolve_param_bool('bitbucket.enabled', 'BITBUCKET_ENABLED', cfg, False):
            try:
                client = Client(cfg)
                client.request('GET')
                ok(f'Bitbucket: {client.project}/{client.repo}, PR-проверки включены')
            except Exception as exc:
                fail('Bitbucket: ' + mask_secrets(str(exc)))

    # --- прочее ---
    poll = resolve_param_int('general.poll_interval_seconds', 'POLL_INTERVAL', config, 600)
    if poll < 30:
        warn(f"poll_interval_seconds = {poll} — слишком частый опрос Jira")
    logs_dir = os.path.join(PROJECT_DIR, 'logs')
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except OSError:
        pass
    if not os.access(logs_dir, os.W_OK):
        fail(f"Нет прав на запись в {logs_dir}")

    if errors:
        logger.error(f"Проверка окружения: ошибок {len(errors)}, предупреждений {len(warnings)}.")
    else:
        logger.info("Проверка окружения пройдена" + (f", предупреждений: {len(warnings)}." if warnings else "."))
    return errors, warnings


def _check_extras(config, ok, warn, heads):
    if review_enabled(config):
        cli = str(resolve_param('review.gigacode_path', 'REVIEW_GIGACODE_PATH', config, None) or
                  resolve_param('general.gigacode_path', 'GIGACODE_PATH', config, 'gigacode'))
        extra = resolve_param_list('review.extra_args', 'REVIEW_EXTRA_ARGS', config, [])
        if shutil.which(os.path.expanduser(cli)):
            ok(f"Ревью: включено ({cli}{' ' + ' '.join(extra) if extra else ''})")
        else:
            warn(f"Ревью включено, но CLI ревьюера не найден: {cli} (review.gigacode_path) — ревью не будет выполняться")
    else:
        logger.info("  ·  Ревью выключено (review.enabled = false)")

    if memory_enabled(config):
        path = memory_path(config)
        where = 'есть' if os.path.exists(path) else 'появится после первой задачи'
        ok(f"Опыт по репозиторию: {path} ({where})")

    statuses = explore_statuses(config)
    if statuses:
        base = str(resolve_param('explore.base', 'EXPLORE_BASE', config, default_base_ref(config)))
        branch = base[len('origin/'):] if base.startswith('origin/') else base
        if heads is not None and branch not in heads:
            warn(f"Исследование бэклога: ветки {branch} нет в origin (explore.base) — исследование будет падать")
        else:
            ok(f"Исследование бэклога в простое: статусы [{', '.join(statuses)}], копия от {base}")
        if jira_client.ci_condition(config):
            project = resolve_param('jira.project', 'JIRA_PROJECT', config, '')
            ok(f"Бэклог ищется в проекте {project} по КЭ: {jira_client.ci_condition(config)} (без эпика и исполнителя)")
        else:
            warn("Бэклог ищется по всему проекту: КЭ не задан (jira.ci_field + general.ci_id) — "
                 "демон будет изучать задачи всех сервисов проекта")
    else:
        logger.info("  ·  Исследование бэклога выключено (нет explore.statuses)")


def _check_repo(repo, p, ok, warn, fail, config=None):
    """Репозиторий, origin, настроенные базовые ветки, чистота рабочей области. Возвращает ветки origin или None.
    p — префикс строк («[back] » для сервиса)."""
    heads = None
    if not os.path.isdir(repo):
        fail(f"{p}Репозиторий не найден: {repo}")
    else:
        try:
            inside = _git(repo, 'rev-parse', '--is-inside-work-tree')
            if inside.returncode != 0 or inside.stdout.strip() != 'true':
                fail(f"{p}{repo} — не git-репозиторий")
            else:
                ok(f"{p}Репозиторий: {repo}")
                origin = _git(repo, 'remote', 'get-url', 'origin')
                if origin.returncode != 0:
                    fail(f"{p}В репозитории нет remote «origin» — пушить работу некуда")
                else:
                    ok(f"{p}origin: {mask_secrets(origin.stdout.strip())}")
                    try:
                        heads_proc = _git(repo, 'ls-remote', '--heads', 'origin', timeout=45)
                    except subprocess.TimeoutExpired:
                        heads_proc = None
                    if heads_proc is None or heads_proc.returncode != 0:
                        detail = (heads_proc.stderr.strip().splitlines() or [''])[0] if heads_proc else 'таймаут'
                        warn(f"{p}origin недоступен ({mask_secrets(detail)}) — проверьте сеть и доступ к git")
                    else:
                        heads = {line.split('refs/heads/', 1)[1] for line in heads_proc.stdout.splitlines()
                                 if 'refs/heads/' in line}
                        default = base_branch(config)
                        creation = base_branch(config, creation=True)
                        if default not in heads:
                            fail(f"{p}В origin нет ветки {default} — от неё отводятся задачи без маркера «branch:» в комментариях")
                        else:
                            ok(f"{p}origin доступен, ветка {default} на месте")
                        if creation not in heads:
                            warn(f"{p}В origin нет ветки {creation} — новые базовые ветки из комментариев «branch: …» создать не получится")
                dirty = _git(repo, 'status', '--porcelain')
                changed = [l for l in dirty.stdout.splitlines() if l.strip()]
                if changed:
                    warn(f"{p}В рабочей области {len(changed)} незакоммиченных изменений — они смешаются "
                         f"с работой агента в первой задаче. Проверьте: git -C {repo} status")
        except Exception as e:
            fail(f"{p}Не удалось проверить репозиторий {repo}: {e}")
    return heads
