"""Логи инстанса и всё, что связано с текстом ошибок.

- setup_logging — лог в logs/{КЭ|проект}-{agent|dryrun|check}.log;
- adopt_legacy_logs — разовый переезд файлов logs/{проект}-* → logs/{КЭ}-*;
- _issue_errors — сборщик ERROR-строк «[KEY] …»: причины неудач для комментария в Jira;
- mask_secrets — вычищает токены и пароли из текста перед показом людям.
"""
import logging
import os
import re
import sys

from .base import LOGS_DIR, logger
from .config import instance_key, normalized_ci_id, resolve_param

SUPERVISED_ENV = 'ARTEL_SUPERVISED'


def adopt_legacy_logs(logs_dir, config):
    """Разовый переезд logs/{проект}-* → logs/{КЭ}-*: история и статистика
    переезжают вместе с демоном при переходе на КЭ-идентификацию."""
    ci = normalized_ci_id(config)
    project = str(resolve_param('jira.project', None, config, None) or '').lower()
    if not ci or not project:
        return
    new_key = f"ci{ci}"
    for suffix in ('-state.json', '-history.jsonl', '-agent.log', '-poke'):
        src = os.path.join(logs_dir, project + suffix)
        dst = os.path.join(logs_dir, new_key + suffix)
        try:
            if os.path.exists(src) and not os.path.exists(dst):
                os.rename(src, dst)
                logger.info(f"Файл демона перенесён: {os.path.basename(src)} → {os.path.basename(dst)}")
        except OSError as e:
            logger.warning(f"Не удалось перенести {src} → {dst}: {e}")


def setup_logging(config, mode='agent'):
    """Лог каждого инстанса — в logs/{КЭ|проект}-agent.log, а не в общий файл.
    mode='dryrun'/'check' — отдельный лог: пробный запуск рядом с живым демоном
    не смешивает с ним записи и не трогает его файлы."""
    logs_dir = LOGS_DIR
    os.makedirs(logs_dir, exist_ok=True)
    if mode == 'agent':
        adopt_legacy_logs(logs_dir, config)
    log_path = os.path.join(logs_dir, f"{instance_key(config)}-{mode}.log")

    # Корневые обработчики (дефолтный jira-agent.log) заменяются на файл инстанса + stdout
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    # Под супервизором stdout демона пишется в logs/{конфиг}-stdout.log — дублировать туда
    # весь лог незачем: там остаются вывод GigaCode в терминал и аварийные трейсбеки
    if not os.environ.get(SUPERVISED_ENV):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    logger.info(f"Лог инстанса [{instance_key(config)}]: {log_path}")


class _IssueErrorCollector(logging.Handler):
    """Запоминает ERROR-записи вида «[KEY] …»: из них берётся причина неудачи для комментария."""
    KEY_RE = re.compile(r'^\[([A-Z][A-Z0-9_]*-\d+)\]\s*(.*)$', re.S)

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.errors = {}

    def emit(self, record):
        try:
            m = self.KEY_RE.match(record.getMessage())
        except Exception:
            return
        if m:
            text = m.group(2).strip().lstrip('❌').strip()
            if text:
                bucket = self.errors.setdefault(m.group(1), [])
                bucket.append(text)
                del bucket[:-10]

    def reset(self, issue_key):
        self.errors.pop(issue_key, None)

    def reasons(self, issue_key, limit=2):
        # Итоговые сводки «пропуск пост-обработки» — следствие, а не причина
        skip = ('Пропуск пост-обработки', 'Код запушен, но задача не переведена')
        out = []
        for text in reversed(self.errors.get(issue_key, [])):
            if any(text.startswith(x) for x in skip) or text in out:
                continue
            out.append(text)
            if len(out) >= limit:
                break
        return list(reversed(out))


_issue_errors = _IssueErrorCollector()

_SECRET_PATTERNS = (
    (re.compile(r'(://)[^/@\s]+@'), r'\1***@'),                      # https://user:token@host
    (re.compile(r'(?i)(token|password|passwd|secret|api[_-]?key)=([^&\s]+)'), r'\1=***'),
    (re.compile(r'(?i)(authorization:\s*)(bearer|basic)\s+\S+'), r'\1\2 ***'),
)


def mask_secrets(text):
    text = str(text)
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text
