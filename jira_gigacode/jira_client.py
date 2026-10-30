"""Jira REST API: запросы, поиск задач, поля, комментарии и переходы статусов.
"""
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import runtime
from .base import logger
from .config import normalized_ci_id, resolve_param, resolve_param_list
from .issue_report import report_set


# --- HTTP-запрос к Jira ---
def jira_request(method, path, data=None, params=None, max_retries=3, config=None, return_error=False):
    jira_url = resolve_param('jira.url', 'JIRA_URL', config, '')
    jira_token = resolve_param('jira.token', 'JIRA_TOKEN', config, '')
    if not jira_url or not jira_token:
        logger.error("Jira URL или токен не заданы.")
        return None
    url = jira_url.rstrip('/') + path
    if params: url += '?' + urllib.parse.urlencode(params)
    headers = {
        'Authorization': f'Bearer {jira_token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    attempt = 0
    while attempt <= max_retries:
        req = urllib.request.Request(url, headers=headers, method=method)
        if data: req.data = json.dumps(data).encode('utf-8')
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, context=context, timeout=60) as resp:
                body = resp.read().decode('utf-8')
                if not body or not body.strip(): return {"_status": resp.status}
                try: return json.loads(body)
                except json.JSONDecodeError: return {"_status": resp.status, "_raw": body[:200]}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                time.sleep(min(60, 2 ** attempt))
                attempt += 1
                continue
            err_body = ''
            try:
                err_body = e.read().decode('utf-8', errors='ignore')
            except Exception:
                pass
            logger.error(f"Jira HTTP {e.code} при {method} {path}")
            if err_body:
                logger.error(f"  Jira ответ: {err_body[:500]}")
            if return_error:
                error_info = {'_http_error': e.code, '_error_messages': [], '_errors': {}}
                try:
                    parsed_body = json.loads(err_body)
                    error_info['_error_messages'] = parsed_body.get('errorMessages') or []
                    error_info['_errors'] = parsed_body.get('errors') or {}
                except Exception:
                    pass
                return error_info
            return None
        except Exception as e:
            logger.error(f"Jira error: {e}")
            if attempt < max_retries:
                time.sleep(min(60, 2 ** attempt))
                attempt += 1
            else:
                return None
    return None


# Статусы, отвергнутые самим поиском Jira («value does not exist») — кэш на процесс.
# Пред-фильтрация по инвентарным эндпоинтам не работает: и /rest/api/2/status,
# и /rest/api/2/project/{key}/statuses на больших инстансах возвращают неполные списки
_invalid_status_names = set()


def extract_unknown_status_values(error_messages):
    prefix = "The value '"
    suffix = "' does not exist for the field 'status'."
    unknown = []
    for msg in error_messages:
        if isinstance(msg, str) and msg.startswith(prefix) and msg.endswith(suffix):
            unknown.append(msg[len(prefix):-len(suffix)])
    return unknown


def get_issues_by_statuses(statuses, config=None):
    """Ключи задач на реализацию: проект + статусы + эпик, КЭ и исполнитель, если заданы."""
    # Read every page: waiting front-end tasks must not hide their backend on page 2.
    keys, seen, start = [], set(), 0
    while runtime.running:
        issues, total = search_by_statuses(statuses, config, lambda statuses_jql: task_jql(statuses_jql, config),
                                           start_at=start, max_results=100, order_by='key ASC')
        fresh = [i['key'] for i in issues if i['key'] not in seen]
        keys.extend(fresh)
        seen.update(fresh)
        start += len(issues)
        if not fresh or start >= total:
            break
    return keys


def task_jql(statuses_jql, config):
    """JQL поиска задач на реализацию (без ORDER BY)."""
    project_key = resolve_param('jira.project', 'JIRA_PROJECT', config, '')
    epic_name = resolve_param('jira.epic_name', 'JIRA_EPIC_NAME', config, '')
    epic_link_field = resolve_param('jira.epic_link_field', 'JIRA_EPIC_LINK_FIELD', config, '')
    # Исполнитель — только явная настройка конфига/окружения. Фильтр по эпику
    # («AI – задачи») уже сужает поиск до задач команды, поэтому assignee
    # не обязателен и по умолчанию не применяется
    assignee = resolve_param('jira.assignee', 'JIRA_ASSIGNEE', config, None)
    jql = f'project={project_key} AND status IN ({statuses_jql})'
    # Эпик — опциональный фильтр: без обоих ключей берутся все задачи проекта
    if epic_name and epic_link_field:
        jql += f' AND "{epic_link_field}" = "{epic_name}"'
    elif epic_name or epic_link_field:
        logger.warning("Задан только один из ключей jira.epic_name / jira.epic_link_field — "
                       "фильтр по эпику пропущен.")
    ci = ci_condition(config)
    if ci:
        jql += f' AND {ci}'
    if assignee:
        jql += f' AND assignee = "{assignee}"'
    return jql


def ci_condition(config):
    """Условие JQL по КЭ сервиса: jira.ci_field + general.ci_id сужают поиск до задач
    своего сервиса (в одном проекте могут жить задачи нескольких сервисов). None — КЭ не задан."""
    ci_field = resolve_param('jira.ci_field', 'JIRA_CI_FIELD', config, None)
    num = normalized_ci_id(config)
    if ci_field and num:
        return f'cf[{ci_field}] = "{num}"'
    return None


def search_by_statuses(statuses, config, jql_for, fields=('summary', 'status'), start_at=0,
                       max_results=10, order_by=None, label='JQL'):
    """Поиск по статусам: (задачи [{'key', 'fields'}], всего найдено). При ошибке Jira — ([], 0).

    jql_for(statuses_jql) строит JQL без ORDER BY. Статусы, которых нет в Jira
    («value does not exist»), выбрасываются из поиска до перезапуска демона."""
    statuses = [s for s in statuses if s.lower() not in _invalid_status_names]

    while statuses:
        jql = jql_for(', '.join(f'"{s}"' for s in statuses))
        if order_by:
            jql += f' ORDER BY {order_by}'
        if start_at == 0:
            logger.info(f"{label}: {jql}")
        data = {'jql': jql, 'startAt': start_at, 'maxResults': max_results, 'fields': list(fields)}
        result = jira_request('POST', '/rest/api/2/search', data=data, config=config, return_error=True)

        if result is None:
            logger.error("Поиск задач не выполнен: сетевая ошибка/недоступность Jira.")
            return [], 0

        if isinstance(result, dict) and result.get('_http_error'):
            unknown = extract_unknown_status_values(result.get('_error_messages') or [])
            if unknown:
                _invalid_status_names.update(u.lower() for u in unknown)
                filtered = [s for s in statuses if s.lower() not in _invalid_status_names]
                if len(filtered) == len(statuses):
                    logger.error("Поиск задач не выполнен: Jira отклонила запрос, но статус-виновники не определены.")
                    return [], 0
                logger.warning(f"Статусы {unknown} не существуют в Jira — исключены из поиска до перезапуска.")
                statuses = filtered
                continue
            logger.error("Поиск задач не выполнен: Jira вернула ошибку (подробности выше).")
            return [], 0

        issues = [i for i in result.get('issues') or [] if isinstance(i, dict) and i.get('key')]
        total = result.get('total')
        return issues, (total if isinstance(total, int) else start_at + len(issues))

    logger.warning("Все статусы-источники исключены как несуществующие — искать нечего.")
    return [], 0


def fetch_issue_fields(issue_key, config):
    """Поля задачи (summary/description) тем же REST-токеном, что и поллинг демона.

    Текст прикладывается к команде суб-агента напрямую: его jira-MCP периодически
    недоступен (шлюз обрывает рукопожатие), а требования должны доходить до агента
    независимо от этого. None — задача недоступна: генерация продолжается,
    суб-агент попробует прочитать её сам."""
    result = jira_request('GET', f'/rest/api/2/issue/{issue_key}',
                          params={'fields': 'summary,description'}, config=config)
    if not isinstance(result, dict) or not isinstance(result.get('fields'), dict):
        logger.warning(f"[{issue_key}] Не удалось получить текст задачи из Jira — "
                       f"суб-агент прочитает её сам, если сможет.")
        return None
    return result['fields']


def fetch_issue_meta(issue_key, config):
    """summary, description, updated, status задачи (для исследования в простое); None — Jira не ответила."""
    result = jira_request('GET', f'/rest/api/2/issue/{issue_key}',
                          params={'fields': ','.join(META_FIELDS)}, config=config)
    fields = (result or {}).get('fields') if isinstance(result, dict) else None
    return meta_from_fields(fields)


# Поля задачи для исследования бэклога (берутся прямо из поиска, без лишних запросов)
META_FIELDS = ('summary', 'description', 'updated', 'status', 'labels')


def meta_from_fields(fields):
    """{'summary', 'description', 'updated', 'status'} из полей задачи Jira; None — полей нет."""
    if not isinstance(fields, dict):
        return None
    return {
        'summary': str(fields.get('summary') or '').strip(),
        'description': str(fields.get('description') or '').strip(),
        'updated': str(fields.get('updated') or ''),
        'status': ((fields.get('status') or {}).get('name') or ''),
        'labels': [str(x) for x in fields.get('labels') or []] if isinstance(fields.get('labels'), list) else [],
    }


def fetch_issue_routing(issue_key, config):
    """(название, лейблы) задачи — чтобы понять, к какому сервису она относится; None — Jira не ответила."""
    result = jira_request('GET', f'/rest/api/2/issue/{issue_key}', params={'fields': 'summary,labels'}, config=config)
    fields = (result or {}).get('fields') if isinstance(result, dict) else None
    if not isinstance(fields, dict):
        return None
    labels = fields.get('labels')
    return str(fields.get('summary') or ''), ([str(x) for x in labels] if isinstance(labels, list) else [])


def fetch_comments(issue_key, config):
    """Все комментарии задачи; None — ответ недоступен или пагинация неполна."""
    comments = []
    start_at = 0
    seen_ids = set()
    expected_total = None
    while True:
        page = jira_request('GET', f'/rest/api/2/issue/{issue_key}/comment',
                            params={'startAt': start_at, 'maxResults': 100}, config=config)
        if not isinstance(page, dict) or not isinstance(page.get('comments'), list):
            return None
        batch = page['comments']
        if any(not isinstance(comment, dict) for comment in batch):
            return None
        if 'startAt' in page and page['startAt'] != start_at:
            return None
        total = page.get('total')
        if not isinstance(total, int) or isinstance(total, bool) or total < start_at + len(batch):
            return None
        if expected_total is not None and total != expected_total:
            return None  # Thread changed while paging; retry a complete snapshot next poll.
        expected_total = total
        # A proxy/server returning the first page repeatedly is not a complete
        # thread. Never treat missing replies as deleted requirements.
        ids = [str(c['id']) for c in batch if c.get('id') is not None]
        if len(ids) != len(set(ids)) or seen_ids.intersection(ids):
            return None
        seen_ids.update(ids)
        comments.extend(batch)
        start_at += len(batch)
        if start_at >= total:
            return comments
        if not batch:
            return None


def fetch_labels(issue_key, config):
    """Лейблы задачи; пустой список, если Jira не ответила."""
    result = jira_request('GET', f'/rest/api/2/issue/{issue_key}', params={'fields': 'labels'}, config=config)
    labels = ((result or {}).get('fields') or {}).get('labels')
    return [str(x) for x in labels] if isinstance(labels, list) else []


def fetch_status(issue_key, config):
    """Имя текущего статуса задачи; None — Jira не ответила."""
    result = jira_request('GET', f"/rest/api/2/issue/{issue_key}", params={'fields': 'status'}, config=config)
    if not result:
        return None
    return ((result.get('fields') or {}).get('status') or {}).get('name', 'unknown')


def fetch_transitions(issue_key, config):
    """Доступные из текущего статуса переходы; None — Jira не ответила."""
    result = jira_request('GET', f"/rest/api/2/issue/{issue_key}/transitions", config=config)
    if not result or 'transitions' not in result:
        return None
    return result['transitions']


def find_target_transition(transitions, targets):
    """Переход, ведущий прямо в один из целевых статусов (без учёта регистра), или None."""
    targets_lower = {t.lower() for t in targets}
    for t in transitions or []:
        if str((t.get('to') or {}).get('name', '')).lower() in targets_lower:
            return t
    return None


def add_comment(issue_key, body, config):
    """Комментарий в задачу. Без повторов: при таймауте ответа повтор мог бы задвоить комментарий."""
    return jira_request('POST', f'/rest/api/2/issue/{issue_key}/comment', data={'body': body},
                        config=config, max_retries=0)


def update_comment(issue_key, comment_id, body, config):
    """Заменяет тело существующего комментария; повтор PUT не создаёт дубликат."""
    return jira_request('PUT', f'/rest/api/2/issue/{issue_key}/comment/{comment_id}',
                        data={'body': body}, config=config)


# --- Переход статуса (динамический поиск по имени целевого статуса) ---
def transition_issue(issue_key, config):
    """Переводит задачу в один из jira.status_ready. True — задача в целевом статусе."""
    try:
        target_statuses = resolve_param_list('jira.status_ready', 'JIRA_STATUS_READY', config, [])
        targets_lower = {t.lower() for t in target_statuses}
        runtime.state.emit('jira', issue_key, targets=target_statuses)

        logger.info(f"[{issue_key}] Поиск пути к статусам [{', '.join(target_statuses)}]...")
        max_steps = 10
        for step in range(max_steps):
            current_status = fetch_status(issue_key, config)
            if current_status is None:
                logger.error(f"[{issue_key}] Не удалось получить текущий статус задачи")
                break
            logger.info(f"[{issue_key}] [Шаг {step+1}] Текущий статус: '{current_status}'")

            # Достигли цели?
            if current_status.lower() in targets_lower:
                logger.info(f"[{issue_key}] ✅ Цель достигнута: '{current_status}'")
                report_set(issue_key, final_status=current_status)
                return True

            available = fetch_transitions(issue_key, config)
            if available is None:
                logger.error(f"[{issue_key}] Не удалось получить список transitions")
                break
            logger.info(f"[{issue_key}] Доступно переходов: {len(available)} -> {[t.get('to', {}).get('name') for t in available]}")

            target_trans = find_target_transition(available, target_statuses)

            if not target_trans:
                # Прямого пути к целевому статусу нет. НЕ делаем произвольных переходов:
                # 'первый доступный' может оказаться деструктивным (Closed, On Hold, Canceled и т.п.),
                # что навсегда выводит задачу из работы. Стоп + алерт, задачу оставляем в текущем статусе.
                err = (f"Нет безопасного перехода к целевым статусам [{', '.join(target_statuses)}] "
                       f"из '{current_status}'. Доступно: {[t.get('to', {}).get('name') for t in available]}. "
                       f"Задача НЕ перенесена, требуется ручное вмешательство.")
                logger.error(f"[{issue_key}] {err}")
                report_set(issue_key, transition_error=err)
                break

            # Выполняем переход
            trans_id = target_trans['id']
            trans_name = target_trans.get('name', '')
            to_status = target_trans.get('to', {}).get('name', '')
            logger.info(f"[{issue_key}] Выполнение перехода '{trans_name}' (ID: {trans_id}) -> '{to_status}'")

            data = {"transition": {"id": trans_id}}
            res = jira_request('POST', f"/rest/api/2/issue/{issue_key}/transitions", data=data, config=config)

            # 204 No Content = успех
            if res and res.get('_status') in [200, 204]:
                logger.info(f"[{issue_key}] ✅ Переход выполнен")
                time.sleep(2)  # Ждём, пока Jira обновит статус
            else:
                logger.error(f"[{issue_key}] Ошибка перехода. Ответ: {res}")
                break
        else:
            logger.error(f"[{issue_key}] Превышен лимит шагов ({max_steps})")

    except Exception as e:
        logger.error(f"[{issue_key}] Ошибка обновления Jira: {e}")
    return False
