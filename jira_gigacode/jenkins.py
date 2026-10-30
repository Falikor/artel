"""Деплой в Jenkins по лейблам задачи jenkins_{стенд} / jenkins_{стенд}_migration.

Деплой запускается, только если в задаче есть такой лейбл. Миграция включается
boolean-параметром билда (JENKINS_MIGRATION_PARAM).
"""
import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from . import jira_client, runtime
from .base import logger
from .config import resolve_param
from .issue_report import report_set

JENKINS_MIGRATION_PARAM = 'MIGRATION'  # имя boolean-параметра джобы, включающего миграцию (сверить с конфигом джобы)

# Стенд из лейбла → значение параметра filter джобы
JENKINS_STAND_FILTERS = {'dev': 'Деплой на ДЕВ', 'ift': 'Деплой на IFT', 'nt': 'Деплой на НТ', 'hr-draft': 'Деплой на HR-DRAFT'}

USER_AGENT = 'Python-urllib/3.9'


# --- Разбор лейблов и параметров ---
def parse_jenkins_label(labels):
    """Лейблы jenkins_{стенд}_migration / jenkins_{стенд} -> [(стенд, миграция)]."""
    matches = []
    for label in labels:
        value = str(label).strip().lower()
        if not value.startswith('jenkins_'):
            continue
        if value.endswith('_migration'):
            stand, migration = value[len('jenkins_'):-len('_migration')], True
        else:
            stand, migration = value[len('jenkins_'):], False
        if stand:
            matches.append((stand, migration))
    return matches


def jenkins_job_path(j_job):
    """'folder/job/name' → 'folder/job/name' в URL-виде: мусорные 'job' и пустые сегменты убираются."""
    job_parts = [p for p in str(j_job).split("/") if p and p.lower() != "job"]
    return "/job/".join(urllib.parse.quote(p) for p in job_parts)


def deploy_params(branch_name, stand, migration):
    """Параметры билда: ветка задачи, стенд из лейбла, миграция через boolean-параметр джобы."""
    params = {'refName': branch_name, 'filter': JENKINS_STAND_FILTERS.get(stand, stand)}
    if migration:
        params[JENKINS_MIGRATION_PARAM] = 'true'
    return params


def jenkins_settings(config):
    """{'url', 'user', 'token', 'job_name'} из конфига/окружения; пустые строки — не задано."""
    settings = {
        'url': resolve_param('jenkins.url', 'JENKINS_URL', config, ''),
        'user': resolve_param('jenkins.user', 'JENKINS_USER', config, ''),
        'token': resolve_param('jenkins.token', 'JENKINS_TOKEN', config, ''),
        'job_name': resolve_param('jenkins.job_name', 'JENKINS_JOB', config, ''),
    }
    settings['url'] = str(settings['url']).rstrip('/')
    return settings


# --- HTTP ---
def _auth_header(user, token):
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _jenkins_get(url, user, token, timeout=20):
    req = urllib.request.Request(url, headers={'Authorization': _auth_header(user, token), 'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _fetch_crumb(issue_key, settings):
    """CSRF crumb Jenkins: (поле, значение) или (None, None), если выдать не удалось."""
    try:
        data = _jenkins_get(f"{settings['url']}/crumbIssuer/api/json", settings['user'], settings['token'], timeout=30)
        logger.info(f"[{issue_key}] ✅ CSRF crumb получен")
        return data["crumbRequestField"], data["crumb"]
    except Exception as e:
        logger.warning(f"[{issue_key}] Не удалось получить CSRF crumb: {e}")
        return None, None


def trigger_build(issue_key, settings, params):
    """Запускает джобу; True — Jenkins принял запуск."""
    auth = _auth_header(settings['user'], settings['token'])
    crumb_field, crumb_value = _fetch_crumb(issue_key, settings)

    encoded_path = jenkins_job_path(settings['job_name'])
    logger.info(f"[{issue_key}] Путь джоба (очищен): /job/{encoded_path}")
    job_url = f"{settings['url']}/job/{encoded_path}"

    # Fallback endpoints: buildWithParameters -> build -> build с токеном в URL
    endpoints = [
        (f"{job_url}/buildWithParameters", True),
        (f"{job_url}/build", True),
        (f"{job_url}/buildWithParameters?token={urllib.parse.quote(settings['token'])}", False),
    ]
    for endpoint, use_params_body in endpoints:
        try:
            logger.info(f"[{issue_key}] Попытка запуска: {endpoint[:120]}...")
            if use_params_body:
                req = urllib.request.Request(endpoint, method="POST", data=urllib.parse.urlencode(params).encode())
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            else:
                # Токен уже в URL, параметры тоже
                req = urllib.request.Request(endpoint + "&" + urllib.parse.urlencode(params), method="POST", data=b'')
            req.add_header("Authorization", auth)
            req.add_header("User-Agent", USER_AGENT)
            if crumb_field and crumb_value:
                req.add_header(crumb_field, crumb_value)
            with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
                logger.info(f"[{issue_key}] ✅ Jenkins джоб запущен (Status: {resp.status})")
                return True
        except urllib.error.HTTPError as e:
            body = e.read().decode() if hasattr(e, "read") else ""
            logger.warning(f"[{issue_key}] Endpoint вернул {e.code}: {body[:200]}")
    logger.error(f"[{issue_key}] ❌ Все endpoints Jenkins вернули ошибки")
    return False


# --- Шаг пайплайна ---
def deploy_for_issue(issue_key, branch_name, config):
    """Деплой ветки задачи по её лейблу jenkins_*. Ошибки деплоя не останавливают пайплайн:
    они попадают в лог и в комментарий-отчёт."""
    from .feature_control import enabled
    if not enabled(config, 'jenkins.enabled'):
        report_set(issue_key, jenkins='disabled')
        return
    try:
        matches = parse_jenkins_label(jira_client.fetch_labels(issue_key, config))
        if not matches:
            logger.info(f"[{issue_key}] Лейбл jenkins_* не найден — деплой Jenkins пропущен.")
            report_set(issue_key, jenkins='no_label')
            return
        if len(matches) > 1:
            logger.warning(f"[{issue_key}] Несколько jenkins_* лейблов ({matches}) — используется первый.")
        stand, migration = matches[0]
        logger.info(f"[{issue_key}] Лейбл jenkins_* найден: стенд='{stand}', миграция={'да' if migration else 'нет'}")
        runtime.state.emit('jenkins', issue_key, stand=stand, migration=migration)
        report_set(issue_key, jenkins='failed', stand=stand, migration=migration)

        settings = jenkins_settings(config)
        if not all(settings.values()):
            logger.warning(f"[{issue_key}] Лейбл найден, но настройки Jenkins неполные (url/token/user/job_name) — деплой пропущен.")
            report_set(issue_key, jenkins='incomplete')
            return
        logger.info(f"[{issue_key}] Инициация Jenkins деплоя...")
        if trigger_build(issue_key, settings, deploy_params(branch_name, stand, migration)):
            report_set(issue_key, jenkins='started')
    except Exception as e:
        logger.error(f"[{issue_key}] Ошибка запуска Jenkins: {e}")
