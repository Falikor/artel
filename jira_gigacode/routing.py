"""Несколько сервисов под одним КЭ: к какому сервису относится задача (бек, фронт…).

В конфиге — список сервисов, у каждого свой репозиторий (и при желании своя джоба Jenkins):

    "services": [
      {"name": "back", "repo_path": "/work/hr-back",
       "keywords": ["бек", "бэк", "back", "backend", "бэкенд"], "labels": ["back", "backend"],
       "jenkins": {"job_name": "hr/deploy-back"},
       "compare_url": "https://git.example.com/hr-back/compare?from={branch}&to={base}"},
      {"name": "web", "repo_path": "/work/hr-web",
       "keywords": ["web", "веб", "фронт", "front", "frontend"], "labels": ["web", "front"]}
    ]

Сервис задачи определяется по её лейблам (точное совпадение без учёта регистра) и по словам
в названии (целые слова: «[Бек] Добавить поле», «WEB: кнопка»). Все совпадения складываются:
  - ровно один сервис — задача идёт в его репозиторий;
  - ни одного или несколько — демон задачу не берёт и один раз пишет в неё комментарий с просьбой
    поставить лейбл (или разбить задачу на две). Когда название или лейблы поменяются, задача
    снова проверяется и, если сервис стал понятен, берётся в работу.

Настройки сервиса накладываются поверх общих: repo_path, base_branch, base_branch_create_from, branch_prefix, compare_url заменяют
общие, а jenkins, memory и review сливаются с одноимёнными разделами (ключи сервиса главнее). Переменные
окружения (REPO_PATH, JENKINS_JOB, COMPARE_URL…) главнее и того и другого — с сервисами их не задают.

Без раздела "services" демон работает как раньше — с одним general.repo_path.
"""
import copy
import json
import os
import re
import time

from . import jira_client, runtime
from .base import LOGS_DIR, logger
from .config import instance_key, resolve_param, resolve_param_bool
from .issue_report import ARTEL_REPORT_TAG

ROUTING_TAG = 'Артель демонов · какой сервис'

# Слова и лейблы по умолчанию для типовых имён сервисов (если в конфиге не заданы свои)
DEFAULT_MARKERS = {
    'back': ['back', 'backend', 'beck', 'бек', 'бэк', 'бекенд', 'бэкенд'],
    'web': ['web', 'веб', 'front', 'frontend', 'фронт', 'фронтенд'],
    'front': ['front', 'frontend', 'web', 'веб', 'фронт', 'фронтенд'],
    'mobile': ['mobile', 'мобилка', 'ios', 'android'],
}
WORD_RE = re.compile(r'[0-9A-Za-zА-Яа-яЁё]+')


def services(config):
    """Список сервисов из конфига (пустой — режим одного репозитория)."""
    raw = (config or {}).get('services') if isinstance(config, dict) else None
    result = []
    for item in raw or []:
        if isinstance(item, dict) and item.get('name') and item.get('repo_path'):
            result.append(item)
    return result


def _norm_list(values, fallback):
    items = values if isinstance(values, list) else ([values] if values else [])
    items = [str(x).strip().lower().replace('ё', 'е') for x in items if str(x).strip()]
    return items or DEFAULT_MARKERS.get(fallback, [fallback])


def match_services(summary, labels, config):
    """[(сервис, причины)] — какие сервисы подходят задаче и почему."""
    words = {w.lower().replace('ё', 'е') for w in WORD_RE.findall(summary or '')}
    label_set = {str(x).strip().lower().replace('ё', 'е') for x in labels or []}
    matched = []
    for svc in services(config):
        name = str(svc['name']).lower()
        why = []
        hit_labels = sorted(label_set & set(_norm_list(svc.get('labels'), name)))
        if hit_labels:
            why.append('лейбл ' + ', '.join(hit_labels))
        hit_words = sorted(words & set(_norm_list(svc.get('keywords'), name)))
        if hit_words:
            why.append('в названии «' + '», «'.join(hit_words) + '»')
        if why:
            matched.append((svc, why))
    return matched


def route(summary, labels, config):
    """(сервис | None, описание). None — сервис непонятен или их несколько."""
    matched = match_services(summary, labels, config)
    if len(matched) == 1:
        svc, why = matched[0]
        return svc, f"сервис {svc['name']}: {'; '.join(why)}"
    if not matched:
        return None, 'ни в названии, ни в лейблах нет признаков сервиса'
    names = ', '.join(svc['name'] for svc, _ in matched)
    return None, f'задача подходит сразу нескольким сервисам: {names}'


def config_for_service(config, service):
    """Конфиг демона для работы в репозитории сервиса: свой repo_path, branch_prefix, Jenkins
    и отдельный файл опыта memory/{КЭ}-{сервис}.md (у разных репозиториев — разный опыт)."""
    cfg = copy.deepcopy(config)
    general = cfg.setdefault('general', {})
    general['repo_path'] = service['repo_path']
    general['service'] = service['name']
    if 'role' in service:
        general['role'] = service['role']
    for key in ('base_branch', 'base_branch_create_from'):
        if key in service:
            general[key] = service[key]
    if service.get('branch_prefix'):
        general['branch_prefix'] = service['branch_prefix']
    if service.get('compare_url'):
        general['compare_url'] = service['compare_url']
    if isinstance(service.get('jenkins'), dict):
        cfg['jenkins'] = dict(cfg.get('jenkins') or {}, **service['jenkins'])
    if isinstance(service.get('memory'), dict):
        cfg['memory'] = dict(cfg.get('memory') or {}, **service['memory'])
    if isinstance(service.get('bitbucket'), dict):
        cfg['bitbucket'] = dict(cfg.get('bitbucket') or {}, **service['bitbucket'])
    if isinstance(service.get('review'), dict):
        cfg['review'] = dict(cfg.get('review') or {}, **service['review'])
    return cfg


# --- вопрос в задаче (один раз на каждое состояние названия и лейблов) ---
def _asked_path(config):
    return os.path.join(LOGS_DIR, f"{instance_key(config)}-routing.json")


def _load_asked(config):
    try:
        with open(_asked_path(config), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning(f"Не удалось прочитать {_asked_path(config)}: {e}")
        return {}


def _save_asked(config, data):
    path = _asked_path(config)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"Не удалось сохранить {path}: {e}")


def signature(summary, labels):
    return json.dumps([summary or '', sorted(str(x).lower() for x in labels or [])], ensure_ascii=False)


def ask_in_issue(issue_key, config, summary, labels, reason):
    """Комментарий «к какому сервису относится задача» — один раз, пока название и лейблы не изменятся."""
    sig = signature(summary, labels)
    asked = _load_asked(config)
    if (asked.get(issue_key) or {}).get('signature') == sig:
        return False
    asked[issue_key] = {'signature': sig, 'at': time.time()}
    _save_asked(config, asked)
    if runtime.DRY_RUN or not resolve_param_bool('jira.result_comments', 'JIRA_RESULT_COMMENTS', config, True):
        return False
    res = jira_client.add_comment(issue_key, build_question(config, reason), config)
    if res is None:
        logger.warning(f"[{issue_key}] Не удалось оставить вопрос о сервисе в задаче.")
        return False
    logger.info(f"[{issue_key}] В задаче оставлен вопрос: к какому сервису она относится.")
    return True


def forget_question(issue_key, config):
    asked = _load_asked(config)
    if asked.pop(issue_key, None) is not None:
        _save_asked(config, asked)


def build_question(config, reason):
    name = resolve_param('general.name', 'DAEMON_NAME', config, None) or instance_key(config)
    lines = [f'*Демон «{name}»: не понял, к какому сервису относится задача*',
             f'Причина: {reason}.']
    several = 'нескольким' in reason
    if several:
        lines.append('Оставьте один лейбл сервиса или разбейте задачу на несколько — по одной на сервис.')
    else:
        lines.append('Добавьте лейбл сервиса или уточните название задачи:')
    for svc in services(config):
        labels = ', '.join('{{' + x + '}}' for x in _norm_list(svc.get('labels'), str(svc['name']).lower()))
        words = ', '.join(_norm_list(svc.get('keywords'), str(svc['name']).lower()))
        lines.append(f"* *{svc['name']}* — лейбл {labels} или в названии: {words}")
    lines.append('Как только сервис станет понятен, демон возьмёт задачу сам.')
    lines.append(f'{{color:#97a0af}}{ARTEL_REPORT_TAG} · {ROUTING_TAG}{{color}}')
    return '\n'.join(lines)


def resolve_issue_service(issue_key, config):
    """Конфиг для задачи или None, если задачу брать нельзя (сервис непонятен — в задаче спросили).
    Без раздела services — исходный конфиг."""
    if not services(config):
        return config
    fields = jira_client.fetch_issue_routing(issue_key, config)
    if fields is None:
        logger.warning(f"[{issue_key}] Не удалось прочитать название и лейблы — задача пропущена до следующего опроса.")
        return None
    summary, labels = fields
    service, reason = route(summary, labels, config)
    if service is None:
        logger.warning(f"[{issue_key}] Задача пропущена: {reason}.")
        ask_in_issue(issue_key, config, summary, labels, reason)
        return None
    logger.info(f"[{issue_key}] {reason} → репозиторий {service['repo_path']}")
    forget_question(issue_key, config)
    return config_for_service(config, service)
