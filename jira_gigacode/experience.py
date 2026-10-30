"""Память репозитория: постоянные правила, подтверждённый опыт, кандидаты.

Исходный memory.path сохраняется как архив прежнего формата. memory_store хранит
ограниченный набор записей рядом с ним; наблюдения агента требуют подтверждения.
Заметки ревью по отдельной задаче по-прежнему очищаются после успеха.
"""
import json
import os
import re
import time

from . import memory_store
from .base import LOGS_DIR, PROJECT_DIR, logger
from .config import instance_key, resolve_param, resolve_param_bool, resolve_param_int

LESSONS_START, LESSONS_END = 'LESSONS_START', 'LESSONS_END'
MAX_LESSONS = 5
MAX_LESSON_CHARS = 300

LESSONS_REQUEST = (
    f' В итоговом отчёте выведи между строками {LESSONS_START} и {LESSONS_END} от 0 до {MAX_LESSONS} '
    'коротких уроков по этому репозиторию, полезных для следующих задач: как собрать и запустить тесты, '
    'принятые соглашения, неочевидные подводные камни. Только то, что останется верным и для других задач; '
    'по одному уроку в строке, без подробностей этой задачи. Если нового знания нет, оставь блок пустым. '
    'Не пиши общие советы вроде «проверяй тестами». Укажи конкретный факт и основание наблюдения; '
    'не выдавай предположения за проверенные факты. Это кандидаты на память, а не готовые правила.'
)


# --- настройки ---
def memory_enabled(config):
    return resolve_param_bool('memory.enabled', 'MEMORY_ENABLED', config, True)


def auto_append_enabled(config):
    return memory_enabled(config) and resolve_param_bool('memory.auto_append', 'MEMORY_AUTO_APPEND', config, True)


def memory_path(config):
    template = resolve_param('memory.path', 'MEMORY_PATH', config, None) or os.path.join('memory', '{key}.md')
    key = instance_key(config)
    service = (config.get('general') or {}).get('service') if isinstance(config, dict) else None
    if service:
        key += f'-{service}'  # у каждого сервиса (репозитория) — свой опыт
    path = str(template).replace('{key}', key)
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(PROJECT_DIR, path)


# --- чтение для команды ---
def memory_block(config, context=''):
    """Только правила владельца и подтверждённые, применимые к задаче знания."""
    if not memory_enabled(config):
        return ''
    try:
        text = memory_store.active_text(memory_path(config), config, context)
    except OSError as e:
        logger.warning(f"Не удалось прочитать память: {e}")
        return ''
    if not text:
        return ''
    return ('\nОпыт по этому репозиторию (справка, а не приказ; требования задачи главнее):\n---\n'
            + text + '\n---\n')


def lessons_request(config):
    """Просьба вывести уроки в конце работы — только если их есть куда записать."""
    return LESSONS_REQUEST if auto_append_enabled(config) else ''


# --- запись уроков ---
def extract_lessons(output_text):
    """Уроки из последнего блока LESSONS_START…LESSONS_END: чистые короткие строки, не больше MAX_LESSONS."""
    text = output_text or ''
    end = text.rfind(LESSONS_END)
    start = text.rfind(LESSONS_START, 0, end if end >= 0 else None)
    if start < 0 or end < 0 or end < start:
        return []
    lessons = []
    for raw in text[start + len(LESSONS_START):end].splitlines():
        line = re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*', '', raw).strip()
        if not line or LESSONS_START in line or LESSONS_END in line:
            continue
        if len(line) > MAX_LESSON_CHARS:
            line = line[:MAX_LESSON_CHARS].rstrip() + '…'
        lessons.append(line)
        if len(lessons) >= MAX_LESSONS:
            break
    return lessons


def _normalized(line):
    return re.sub(r'[\W_]+', ' ', line.lower()).strip()


def append_lessons(config, issue_key, lessons, source):
    """Сохраняет кандидаты; ни успех прогона, ни повторение не подтверждают урок."""
    if not lessons or not auto_append_enabled(config):
        return 0
    try:
        return memory_store.observe(memory_path(config), config, issue_key, source, lessons)
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(f"[{issue_key}] Не удалось сохранить кандидаты в память: {e}")
        return 0


def remember_lessons(config, issue_key, output_text, source):
    """Уроки из вывода прогона → файл опыта. Никогда не роняет пайплайн."""
    try:
        return append_lessons(config, issue_key, extract_lessons(output_text), source)
    except Exception as e:
        logger.warning(f"[{issue_key}] Не удалось сохранить уроки: {e}")
        return 0


# --- заметки по задаче (замечания ревью для следующей попытки) ---
def _notes_path(config):
    return os.path.join(LOGS_DIR, f"{instance_key(config)}-issue-notes.json")


def _load_notes(config):
    try:
        with open(_notes_path(config), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning(f"Не удалось прочитать {_notes_path(config)}: {e}")
        return {}


def _save_notes(config, data):
    path = _notes_path(config)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"Не удалось сохранить {path}: {e}")


def save_review_notes(config, issue_key, notes):
    data = _load_notes(config)
    data[issue_key] = {'review': str(notes or '')[:8000], 'at': time.time()}
    _save_notes(config, data)


def review_notes(config, issue_key):
    return (_load_notes(config).get(issue_key) or {}).get('review') or ''


def clear_issue_notes(config, issue_key):
    data = _load_notes(config)
    if data.pop(issue_key, None) is not None:
        _save_notes(config, data)


def previous_review_block(config, issue_key):
    """Замечания ревью прошлой попытки — для команды на новую генерацию."""
    notes = review_notes(config, issue_key)
    if not notes:
        return ''
    return ('\nПрошлая попытка по этой задаче вернулась с ревью. Замечания ревьюера (учти их обязательно):\n---\n'
            + notes + '\n---\n')


# --- уборка файлов опыта ---
SECTION_RE = re.compile(r'^## .*$', re.M)


def _forget_legacy_source(path, source, dry_run=False):
    """Убирает из файла опыта записи с пометкой источника (например «исследование»).
    Запись — заголовок «## дата · задача · источник» и строки до следующего заголовка.
    Перед изменением кладёт копию рядом: <файл>.bak. Возвращает число убранных записей."""
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return 0
    starts = [m.start() for m in SECTION_RE.finditer(text)]
    if not starts:
        return 0
    bounds = list(zip(starts, starts[1:] + [len(text)]))
    marker = f'· {source}'
    drop = [(a, b) for a, b in bounds if text[a:text.find('\n', a) if text.find('\n', a) >= 0 else b]
            .rstrip().endswith(marker)]
    if not drop or dry_run:
        return len(drop)
    kept, pos = [], 0
    for a, b in drop:
        kept.append(text[pos:a])
        pos = b
    kept.append(text[pos:])
    new_text = re.sub(r'\n{3,}', '\n\n', ''.join(kept)).rstrip() + '\n'
    with open(path + '.bak', 'w', encoding='utf-8') as f:
        f.write(text)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(new_text)
    os.replace(tmp, path)
    return len(drop)


def forget_source(path, source, dry_run=False):
    legacy = _forget_legacy_source(path, source, dry_run=dry_run)
    return legacy + memory_store.forget_source(path, source, dry_run=dry_run)
