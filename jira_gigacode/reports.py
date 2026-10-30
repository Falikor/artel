"""Комментарии-отчёты в задаче Jira: «реализована», «нужна помощь», «не смог реализовать».
"""
import re
import time
import urllib.parse

from . import jira_client, runtime
from .base import logger
from .config import instance_key, resolve_param, resolve_param_bool, resolve_param_list
from .issue_report import ARTEL_REPORT_TAG, _REPORT
from .logs import _issue_errors, mask_secrets
from .retry import RETRY_FAILURES_LIMIT


_FAILURE_COMMENTED = set()  # о неудачах сообщаем раз на задачу до её успеха (без спама на каждую попытку)


def _jira_text(text, limit=600):
    """Текст для вики-разметки Jira: без секретов, без управляющих символов разметки, обрезанный."""
    text = mask_secrets(text).replace('{', '(').replace('}', ')').replace('|', '/')
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit] + '…'


def md_to_jira(text, limit=20000):
    """Markdown агента → вики-разметка Jira: заголовки, жирный, списки, `код`, блоки ```.
    Фигурные скобки вне кода экранируются: иначе Jira примет их за макросы."""
    text = mask_secrets(text or '').strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + '\n…(текст усечён)'
    out, in_code = [], False
    for line in text.splitlines():
        if line.strip().startswith('```'):
            out.append('{code}')
            in_code = not in_code
            continue
        if in_code:
            out.append(line.replace('{code}', '(code)'))
            continue
        line = line.replace('{', '\\{').replace('}', '\\}')
        line = re.sub(r'`([^`]+)`', lambda m: '{{' + m.group(1) + '}}', line)
        line = re.sub(r'\*\*(.+?)\*\*', r'*\1*', line)
        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        if heading:
            line = f"h{min(len(heading.group(1)) + 2, 6)}. {heading.group(2)}"
        else:
            bullet = re.match(r'^(\s*)[-*+]\s+(.*)$', line)
            numbered = re.match(r'^(\s*)\d+[.)]\s+(.*)$', line)
            if bullet:
                line = '*' * (1 + len(bullet.group(1)) // 2) + ' ' + bullet.group(2)
            elif numbered:
                line = '#' * (1 + len(numbered.group(1)) // 2) + ' ' + numbered.group(2)
        out.append(line)
    if in_code:
        out.append('{code}')
    return '\n'.join(out)


def _fmt_int(n):
    return f"{int(n):,}".replace(',', ' ')


def _fmt_duration(seconds):
    if seconds is None:
        return None
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return 'меньше минуты'
    if minutes < 60:
        return f'{minutes} мин'
    return f'{minutes // 60} ч {minutes % 60} мин'


def daemon_display_name(config):
    return str(resolve_param('general.name', 'DAEMON_NAME', config, None) or instance_key(config))


def compare_link(issue_key, config, branch, base):
    """Ссылка «сравнить ветки» по шаблону general.compare_url, например
    https://bitbucket.example.com/projects/HR/repos/backend/compare/diff?sourceBranch={branch}&targetBranch={base}"""
    template = resolve_param('general.compare_url', 'COMPARE_URL', config, None)
    if not template or not branch:
        return None
    base_name = str(base or '')
    if base_name.startswith('origin/'):
        base_name = base_name[len('origin/'):]
    try:
        return str(template).format(branch=urllib.parse.quote(branch, safe=''),
                                    base=urllib.parse.quote(base_name, safe=''),
                                    issue=issue_key)
    except (KeyError, IndexError, ValueError) as e:
        logger.warning(f"[{issue_key}] Шаблон general.compare_url не подошёл ({e}) — ссылка не добавлена.")
        return None


def _base_short(base):
    base = str(base or '')
    return base[len('origin/'):] if base.startswith('origin/') else base


def _review_line(rep):
    result = rep.get('review')
    if not result:
        return None
    rounds = result.get('rounds') or 0
    after = f' после доработки по замечаниям ({rounds})' if rounds else ''
    if result.get('verdict') == 'approve':
        return f'одобрено независимым ревьюером{after}'
    if result.get('verdict') == 'changes':
        return f'остались замечания{after} — см. лог демона'
    return 'ревьюер не дал вердикта'


def _jenkins_line(rep):
    jenkins = rep.get('jenkins')
    if not jenkins:
        return None
    if jenkins == 'disabled':
        return 'не запускался (Jenkins выключен в настройках демона)'
    if jenkins == 'no_label':
        return 'не запускался (в задаче нет лейбла jenkins_*)'
    if jenkins == 'incomplete':
        return '*пропущен*: в конфиге демона неполные настройки Jenkins'
    target = f"стенд {{{{{rep.get('stand')}}}}}" + (' с миграцией' if rep.get('migration') else '')
    if jenkins == 'started':
        return f'{target} — запущен'
    return f'{target} — *не запустился*, подробности в логе демона'


def build_result_comment(issue_key, config, kind, until=None):
    rep = _REPORT.get(issue_key, {})
    name = daemon_display_name(config)
    lines = []
    if kind == 'done':
        lines.append(f'*Задача реализована демоном «{name}»*')
        if rep.get('service'):
            lines.append(f"* Сервис — {rep['service']}")
        branch = rep.get('branch')
        if branch:
            line = f"* Ветка задачи — {{{{{branch}}}}}, от {{{{{_base_short(rep.get('base'))}}}}}"
            if rep.get('commits'):
                line += f", коммитов: {rep['commits']}"
            link = compare_link(issue_key, config, branch, rep.get('base'))
            if link:
                line += f' — [посмотреть изменения|{link}]'
            lines.append(line)
        jenkins = _jenkins_line(rep)
        if jenkins:
            lines.append(f'* Деплой Jenkins — {jenkins}')
        review = _review_line(rep)
        if review:
            lines.append(f'* Ревью — {review}')
        if rep.get('final_status'):
            lines.append(f"* Статус — {rep['final_status']}")
        gen, total = rep.get('gen_seconds'), time.time() - rep.get('started_at', time.time())
        if gen is not None:
            lines.append(f'* Время — генерация {_fmt_duration(gen)}, всего {_fmt_duration(total)}')
        tokens = rep.get('tokens') or {}
        if tokens.get('total'):
            detail = []
            if tokens.get('input'):
                detail.append(f"вход {_fmt_int(tokens['input'])}")
            if tokens.get('output'):
                detail.append(f"выход {_fmt_int(tokens['output'])}")
            lines.append(f"* Токены GigaCode — {_fmt_int(tokens['total'])}" + (f" ({', '.join(detail)})" if detail else ''))
        if rep.get('retry_only'):
            lines.append('* Код был запушен прошлой попыткой; в этот раз выполнен только перевод задачи')
    elif kind == 'stuck':
        targets = ', '.join(resolve_param_list('jira.status_ready', 'JIRA_STATUS_READY', config, []))
        lines.append('*Нужна помощь: код готов, но задача не переведена*')
        branch = rep.get('branch')
        where = f" в ветку {{{{{branch}}}}}" if branch else ''
        lines.append(f'Демон «{name}» запушил работу{where}, но не смог перевести задачу в «{targets}».')
        reason = rep.get('transition_error') or '; '.join(_issue_errors.reasons(issue_key))
        if reason:
            lines.append(f'Причина: {_jira_text(reason)}')
        lines.append('Переведите задачу вручную или поправьте workflow — повторно генерировать код демон не будет, '
                     'он только периодически пробует перевод.')
    elif kind == 'review_changes':
        result = rep.get('review') or {}
        branch = rep.get('branch')
        lines.append(f'*Демон «{name}»: работа не прошла независимое ревью*')
        where = f" в ветке {{{{{branch}}}}}" if branch else ''
        rounds = result.get('rounds') or 0
        after = f' (после доработок: {rounds})' if rounds else ''
        lines.append(f'Работа лежит{where}, но ревьюер вернул её с замечаниями{after}. '
                     'Задача не переведена, деплой не запускался.')
        if result.get('notes'):
            lines.append('Замечания ревьюера:')
            lines.append(md_to_jira(result['notes'], limit=6000))
        lines.append('Следующая попытка учтёт эти замечания. Если ревьюер неправ — допишите в задачу комментарий '
                     'или переведите её вручную.')
    elif kind == 'failed':
        lines.append(f'*Демон «{name}» не смог реализовать задачу*')
        lines.append(f'{RETRY_FAILURES_LIMIT} попытки подряд завершились неудачей'
                     + (f'; следующая — не раньше {time.strftime("%H:%M", time.localtime(until))}.' if until else '.'))
        reasons = _issue_errors.reasons(issue_key)
        if reasons:
            lines.append('Причина последней попытки:')
            lines.extend(f'* {_jira_text(r)}' for r in reasons)
        lines.append('Подробности — в логе демона и логе GigaCode (клик по демону на дашборде Артели).')
    lines.append(f'{{color:#97a0af}}{ARTEL_REPORT_TAG}{{color}}')
    return '\n'.join(lines)


def post_result_comment(issue_key, config, kind, until=None):
    """kind: 'done' — задача реализована; 'stuck' — код в remote, перевод не удался;
    'review_changes' — ревью вернуло работу; 'failed' — серия неудач, включился кулдаун.
    Выключается jira.result_comments = false."""
    if runtime.DRY_RUN or not resolve_param_bool('jira.result_comments', 'JIRA_RESULT_COMMENTS', config, True):
        return
    if kind in ('stuck', 'failed'):
        if (issue_key, kind) in _FAILURE_COMMENTED:
            return
        _FAILURE_COMMENTED.add((issue_key, kind))
    elif kind == 'done':
        for k in ('stuck', 'failed'):
            _FAILURE_COMMENTED.discard((issue_key, k))
    try:
        body = build_result_comment(issue_key, config, kind, until=until)
        res = jira_client.add_comment(issue_key, body, config)
        if res is None:
            logger.warning(f"[{issue_key}] Не удалось оставить комментарий-отчёт в задаче.")
        else:
            logger.info(f"[{issue_key}] Комментарий-отчёт оставлен в задаче ({kind}).")
    except Exception as e:
        logger.warning(f"[{issue_key}] Не удалось оставить комментарий-отчёт: {e}")


# --- исследование задачи (OpenSpec explore) ---
EXPLORE_TAG = 'Артель демонов · исследование'


def _explore_owner(config):
    return 'ARTEL_EXPLORE_OWNER=' + urllib.parse.quote(instance_key(config), safe='')


def _same_jira_user(author, user):
    # displayName не уникален: сравниваем только идентификаторы аккаунта.
    for field in ('accountId', 'key', 'name'):
        if author.get(field) and user.get(field):
            return author[field] == user[field]
    return False


def build_explore_comment(config, result_text):
    name = daemon_display_name(config)
    return '\n'.join([
        f'*Демон «{name}» изучил задачу и код — предложения*',
        md_to_jira(result_text),
        f'{{color:#97a0af}}{ARTEL_REPORT_TAG} · {EXPLORE_TAG}{{color}}',
        f'{{color:#97a0af}}{_explore_owner(config)}{{color}}',
    ])


def post_explore_comment(issue_key, config, result_text):
    """Создаёт первый комментарий или обновляет свой прежний. Возвращает id/True либо False."""
    if runtime.DRY_RUN:
        return False
    try:
        comments = jira_client.fetch_comments(issue_key, config)
        if comments is None:
            logger.warning(f"[{issue_key}] Не удалось прочитать комментарии — публикация пропущена.")
            return False
        user = jira_client.jira_request('GET', '/rest/api/2/myself', config=config)
        if not isinstance(user, dict) or not any(user.get(k) for k in ('accountId', 'key', 'name')):
            logger.warning(f"[{issue_key}] Не удалось определить автора Jira — публикация пропущена.")
            return False
        header = f'*Демон «{daemon_display_name(config)}» изучил задачу и код — предложения*'
        owner_line = f'{{color:#97a0af}}{_explore_owner(config)}{{color}}'
        matches = []
        for comment in comments:
            body = str(comment.get('body') or '')
            if EXPLORE_TAG not in body or not _same_jira_user(comment.get('author') or {}, user):
                continue
            # Старый формат узнаём по точному заголовку, новый — по стабильному инстансу.
            owned = owner_line in body.splitlines() if 'ARTEL_EXPLORE_OWNER=' in body else body.startswith(header + '\n')
            if owned:
                matches.append(comment)
        body = build_explore_comment(config, result_text)
        if matches:
            # Если дубли уже накопились, обновляем последний; старые не удаляем.
            previous = max(matches, key=lambda c: (str(c.get('created') or ''),
                                                  int(c['id']) if str(c.get('id', '')).isdigit() else 0))
            comment_id = previous.get('id')
            if not comment_id:
                logger.warning(f"[{issue_key}] У прежнего комментария нет id — публикация пропущена.")
                return False
            res = jira_client.update_comment(issue_key, comment_id, body, config)
            action = 'обновлён'
        else:
            res = jira_client.add_comment(issue_key, body, config)
            comment_id = None
            action = 'создан'
        if res is None:
            logger.warning(f"[{issue_key}] Не удалось опубликовать предложения; дубль не создаётся.")
            return False
        logger.info(f"[{issue_key}] Комментарий с предложениями {action}.")
        if comment_id:
            return str(comment_id)
        return str(res['id']) if isinstance(res, dict) and res.get('id') else True
    except Exception as e:
        logger.warning(f"[{issue_key}] Не удалось опубликовать предложения: {e}")
        return False
