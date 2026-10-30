"""Ротация логов и архив: логи не растут бесконечно, но и не пропадают.

Куда уходят старые логи — logs/archive/ГГГГ-ММ/, сжатые gzip, хранятся бессрочно:
  - лог демона, его stdout под супервизором, журнал супервизора, jira-agent.log — когда файл
    больше logs.max_mb (по умолчанию 20 МБ): содержимое уходит в архив, файл начинается заново;
  - логи GigaCode (/tmp/gigacode_<KEY>*.log) — старше logs.cli_keep_days (по умолчанию 14 дней),
    в logs/archive/ГГГГ-ММ/gigacode/; и сразу, если задачу запускают заново, — прошлый прогон
    не затирается новым.

История задач (*-history.jsonl) и журнал сданных задач (*-delivered.jsonl) не архивируются:
по ним считается статистика, а растут они на строку за задачу.

Архиватор запускают супервизор (раз в 10 минут), каждый демон (раз в час) и команда
`python3 artel.py archive`. Одновременно работает только один — остальные пропускают ход (flock).
Старый файл обрезается на месте (copytruncate): пишущий в него процесс ничего не замечает.
"""
import glob
import gzip
import os
import time

from .base import LOGS_DIR, PROJECT_DIR, logger
from .config import resolve_param_int

try:
    from .platform_support import fcntl
except ImportError:  # Windows: без блокировки, архиватор всё равно безопасен для одного процесса
    fcntl = None

import tempfile
CLI_LOG_GLOB = os.path.join(tempfile.gettempdir(), 'gigacode_*.log')
DEFAULT_MAX_MB = 20
DEFAULT_CLI_KEEP_DAYS = 14
CHUNK = 1024 * 1024


def archive_dir(logs_dir=None):
    return os.path.join(logs_dir or LOGS_DIR, 'archive')


def settings(config=None):
    """(макс. размер лога в байтах | 0 — без ротации, сколько дней держать логи GigaCode в /tmp)."""
    max_mb = resolve_param_int('logs.max_mb', 'LOG_MAX_MB', config or {}, DEFAULT_MAX_MB)
    keep = resolve_param_int('logs.cli_keep_days', 'LOG_CLI_KEEP_DAYS', config or {}, DEFAULT_CLI_KEEP_DAYS)
    return max(0, max_mb) * 1024 * 1024, max(0, keep)


def _target(name, when, logs_dir=None, subdir=''):
    """logs/archive/ГГГГ-ММ[/subdir]/<имя>-ГГГГММДД-ЧЧММСС.log.gz (без перезаписи существующих)."""
    stamp = time.localtime(when)
    folder = os.path.join(archive_dir(logs_dir), time.strftime('%Y-%m', stamp), subdir)
    os.makedirs(folder, exist_ok=True)
    stem = name[:-4] if name.endswith('.log') else name
    base = os.path.join(folder, f"{stem}-{time.strftime('%Y%m%d-%H%M%S', stamp)}")
    path, n = base + '.log.gz', 1
    while os.path.exists(path):
        n += 1
        path = f"{base}-{n}.log.gz"
    return path


def _gzip_range(src, dst, length):
    tmp = dst + '.part'
    left = length
    with open(src, 'rb') as fin, gzip.open(tmp, 'wb') as fout:
        while left > 0:
            chunk = fin.read(min(CHUNK, left))
            if not chunk:
                break
            fout.write(chunk)
            left -= len(chunk)
    os.replace(tmp, dst)


def archive_file(path, logs_dir=None, subdir='', when=None):
    """Весь файл → архив (месяц — по последней записи в файл), исходник удаляется.
    Для файлов, в которые уже никто не пишет. Возвращает путь архива или None."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_size == 0:
        _remove(path)
        return None
    # Сначала забираем файл себе: если его одновременно архивирует кто-то ещё, rename удастся одному
    claimed = f"{path}.archiving-{os.getpid()}"
    try:
        os.rename(path, claimed)
    except OSError:
        return None
    try:
        dst = _target(os.path.basename(path), when or st.st_mtime, logs_dir, subdir)
        _gzip_range(claimed, dst, st.st_size)
        _remove(claimed)
        return dst
    except OSError as e:
        logger.warning(f"Не удалось заархивировать {path}: {e}")
        try:
            os.rename(claimed, path)
        except OSError:
            pass
        return None


def rotate_file(path, max_bytes, logs_dir=None, now=None):
    """Файл больше max_bytes → его содержимое в архив, файл обрезается (copytruncate).
    Процесс, который пишет в файл в режиме дозаписи, продолжает писать в тот же файл."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if not max_bytes or size <= max_bytes:
        return None
    try:
        dst = _target(os.path.basename(path), now or time.time(), logs_dir)
        _gzip_range(path, dst, size)
        with open(path, 'r+b') as f:
            f.seek(size)
            tail = f.read()          # то, что успели дописать, пока сжимали
            f.seek(0)
            f.truncate()
            f.write(tail)
        return dst
    except OSError as e:
        logger.warning(f"Не удалось повернуть лог {path}: {e}")
        return None


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _rotating_logs(logs_dir):
    files = glob.glob(os.path.join(logs_dir, '*.log'))
    root_log = os.path.join(PROJECT_DIR, 'jira-agent.log')
    if os.path.isfile(root_log):
        files.append(root_log)
    return sorted(files)


def sweep(config=None, logs_dir=None, now=None, cli_glob=CLI_LOG_GLOB):
    """Один проход архиватора. Список созданных архивов ([] — если работать не пришлось
    или архиватор сейчас занят другим процессом)."""
    logs_dir = logs_dir or LOGS_DIR
    now = now or time.time()
    max_bytes, keep_days = settings(config)
    os.makedirs(archive_dir(logs_dir), exist_ok=True)
    lock = open(os.path.join(archive_dir(logs_dir), '.lock'), 'w')
    try:
        if fcntl:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return []
        done = []
        for path in _rotating_logs(logs_dir):
            dst = rotate_file(path, max_bytes, logs_dir, now)
            if dst:
                done.append(dst)
        if keep_days:
            for path in glob.glob(cli_glob):
                try:
                    old = now - os.path.getmtime(path) > keep_days * 86400
                except OSError:
                    continue
                if old:
                    dst = archive_file(path, logs_dir, 'gigacode')
                    if dst:
                        done.append(dst)
        if done:
            logger.info(f"Архив логов: {len(done)} файл(ов) → {archive_dir(logs_dir)}")
        return done
    finally:
        lock.close()


def keep_previous_run(path, logs_dir=None):
    """Лог GigaCode сейчас будет перезаписан новым прогоном — прошлый уходит в архив."""
    try:
        if os.path.getsize(path) > 0:
            return archive_file(path, logs_dir, 'gigacode')
    except OSError:
        pass
    return None


class Periodic:
    """Запускает sweep не чаще раза в interval секунд (для основного цикла демона)."""

    def __init__(self, interval, config=None):
        self.interval, self.config, self.last = interval, config, 0.0

    def __call__(self, now=None):
        now = now or time.time()
        if now - self.last < self.interval:
            return []
        self.last = now
        try:
            return sweep(self.config, now=now)
        except Exception as e:  # архив — не повод останавливать демона
            logger.warning(f"Архиватор логов: {e}")
            return []


def summary(logs_dir=None):
    """[(месяц, файлов, байт)] — что лежит в архиве."""
    rows = []
    root = archive_dir(logs_dir)
    for month in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = os.path.join(root, month)
        if not os.path.isdir(folder):
            continue
        count = size = 0
        for dirpath, _, names in os.walk(folder):
            for name in names:
                if name.endswith('.gz'):
                    count += 1
                    size += os.path.getsize(os.path.join(dirpath, name))
        rows.append((month, count, size))
    return rows

