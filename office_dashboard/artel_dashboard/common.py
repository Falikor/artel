"""Пути по умолчанию и общие мелочи сервера."""
import json
import os
import socket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # office_dashboard/
STATIC_DIR = os.path.join(ROOT, 'static')
DEFAULT_LOGS = os.path.join(os.path.dirname(ROOT), 'logs')
# Ассеты лежат в проекте (office_dashboard/assets); OFFICE_ASSETS или --assets — чтобы взять другой пак
BUNDLED_ASSETS = os.path.join(ROOT, 'assets')
DEFAULT_ASSETS = os.environ.get('OFFICE_ASSETS') or BUNDLED_ASSETS
HOSTNAME = socket.gethostname()


from jira_gigacode.platform_support import pid_alive


def tail_lines(path, max_bytes=256 * 1024):
    """Последние строки файла (читается не больше max_bytes с конца)."""
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read().decode('utf-8', errors='replace')
    lines = data.splitlines()
    return lines[1:] if size > max_bytes else lines


def write_json(path, data):
    """Атомарная запись: читатель никогда не видит полуфайл."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
