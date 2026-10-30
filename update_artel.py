#!/usr/bin/env python3
"""Offline, code-only Artel update. Python 3.9+, macOS/Linux, no dependencies."""
import argparse
from jira_gigacode.platform_support import fcntl, pid_alive
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime

ROOT_FILES = ('README.md', 'README.ru.md', 'UPDATE.md', 'CHANGELOG.md', '.gitignore', '.gitattributes', 'build_artel_release.py', 'office_dashboard/README.md',
              'config/example.json.sample', 'config/example-services.json.sample', 'tests/README.md',
              'start-artel.cmd', 'stop-artel.cmd', 'artel.py', 'jira_to_gigacode.py', 'daemon_state.py', 'update_artel.py',
              'office_dashboard/server.py', 'office_dashboard/demo.py')
TREES = {'docs': {'.md'}, 'docs/images': {'.jpg', '.jpeg', '.png', '.webp', '.svg'},
         'subagents': {'.md'}, 'jira_gigacode': {'.py'}, 'office_dashboard/artel_dashboard': {'.py'},
         'office_dashboard/static': {'.js', '.css', '.html', '.woff', '.woff2', '.ttf', '.svg', '.png', '.ico'},
         'office_dashboard/assets': {'.json', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.txt', '.md'}}
RELEASE_MANIFEST = 'artel-release.json'
REQUIRED = ('artel.py', 'jira_to_gigacode.py', 'daemon_state.py', 'jira_gigacode/__init__.py',
            'office_dashboard/server.py', 'office_dashboard/artel_dashboard/handler.py',
            'office_dashboard/static/index.html')


def nested(path, parent):
    return path == parent or parent in path.parents


def release_files(source):
    for rel in REQUIRED:
        if not (source / rel).is_file():
            raise ValueError('Неполный источник обновления: ' + rel)
    candidates = [Path(r) for r in ROOT_FILES if (source / r).is_file()]
    for root, suffixes in TREES.items():
        candidates += [p.relative_to(source) for p in (source / root).rglob('*')
                       if p.is_file() and p.suffix.lower() in suffixes and '__pycache__' not in p.parts]
    return sorted(set(candidates))


def check_code_path(base, rel):
    p = base / rel
    while p != base:
        if p.is_symlink():
            raise ValueError('Символическая ссылка в пути кода: ' + str(p))
        p = p.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_source(source):
    files = release_files(source)
    for rel in files:
        check_code_path(source, rel)
    manifest_path = source / RELEASE_MANIFEST
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or manifest.get('format') != 1 or not isinstance(manifest.get('sha256'), dict):
            raise ValueError('Неверный манифест пакета: ' + str(manifest_path))
        expected = manifest['sha256']
        actual = {p.as_posix() for p in files}
        missing, extra = set(expected) - actual, actual - set(expected)
        if missing or extra:
            raise ValueError('Неполный или изменённый пакет обновления. Отсутствуют: ' +
                             ', '.join(sorted(missing)) + '; лишние файлы кода: ' + ', '.join(sorted(extra)))
        for rel in files:
            if digest(source / rel) != expected[rel.as_posix()]:
                raise ValueError('Контрольная сумма не совпадает: ' + str(rel) + '. Заново распакуйте полный архив.')
    return files


def plan(source, target):
    changed = []
    for rel in validate_source(source):
        src, dst = source / rel, target / rel
        # Never follow links into data or other checkouts, on either side.
        check_code_path(target, rel)
        if dst.exists() and not dst.is_file():
            raise ValueError('Вместо файла кода найдена папка: ' + str(dst))
        content = src.read_bytes()
        if rel.suffix == '.py':
            compile(content, str(src), 'exec')
        if not dst.exists() or dst.read_bytes() != content:
            changed.append(rel)
    return changed


def print_plan(source, target, changed):
    files = release_files(source)
    added = sum(not (target / p).exists() for p in changed)
    print('Источник: ' + str(source))
    print('Установка: ' + str(target))
    print(f'Файлов в пакете: {len(files)}; добавить: {added}; заменить: {len(changed) - added}; '
          f'уже совпадают: {len(files) - len(changed)}.')
    for root in ('jira_gigacode', 'office_dashboard/artel_dashboard', 'office_dashboard/static', 'office_dashboard/assets'):
        count = sum(Path(root) in p.parents for p in files)
        print(f'  {root}: {count} файлов в источнике')
    if not (source / RELEASE_MANIFEST).is_file():
        print('ВНИМАНИЕ: источник без artel-release.json. Полнота пакета не подтверждена; '
              'используйте архив из build_artel_release.py.')


def running(target):
    """Inspect matching processes and their cwd; never kill an unrelated process."""
    output = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    found = []
    names = ('artel.py', 'jira_to_gigacode.py', 'office_dashboard/server.py', 'server.py', 'gigacode')
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not any(n in parts[1] for n in names):
            continue
        pid, command = parts
        if int(pid) == os.getpid() or 'update_artel.py' in command:
            continue
        if str(target) in command:
            found.append(pid)
            continue
        # Relative invocations are common; ps alone is not sufficient.
        proc_cwd = Path('/proc') / pid / 'cwd'
        if proc_cwd.exists():
            cwd = proc_cwd.resolve()
        else:
            result = subprocess.run(['lsof', '-a', '-p', pid, '-d', 'cwd', '-Fn'],
                                    capture_output=True, text=True)
            dirs = [l[1:] for l in result.stdout.splitlines() if l.startswith('n')]
            if not dirs:
                raise ValueError('Не удалось проверить cwd процесса ' + pid + '. Остановите процессы Артели перед обновлением.')
            cwd = Path(dirs[0]).resolve()
        if nested(cwd, target):
            found.append(pid)
    return found


def replace_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.artel-update-', dir=str(dst.parent))
    os.close(fd)
    try:
        shutil.copy2(src, temporary)
        os.replace(temporary, dst)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(source, target, backup_root, extra=(), parked=(), on_write=None):
    changed = plan(source, target)
    print_plan(source, target, changed)
    if not changed:
        print('Код уже совпадает. Обновление не требуется.')
        return None
    expected = {rel: digest(source / rel) for rel in release_files(source)}
    added = [rel for rel in changed if not (target / rel).exists()]
    active = set(running(target)) - set(parked)
    if active:
        raise ValueError('Артель ещё работает (PID: ' + ', '.join(sorted(active)) + '). Остановите демонов и dashboard, отключите автоперезапуск.')
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('artel-%Y%m%d-%H%M%S-'), dir=str(backup_root)))
    print('Резервная копия: ' + str(backup), flush=True)
    shutil.copytree(target, backup / 'installation', symlinks=True,
                    ignore=lambda directory, names: ['.artel-update.lock', '.artel-maintenance'] if Path(directory) == target else [])
    for i, path in enumerate(extra):
        dest = backup / 'external' / str(i)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, dest, symlinks=True)
        else:
            shutil.copy2(path, dest)
    manifest = {'target': str(target), 'source': str(source), 'files': [str(p) for p in changed],
                'added': [str(p) for p in added],
                'replaced': [str(p) for p in changed if p not in added],
                'sha256': {p.as_posix(): value for p, value in expected.items()},
                'external': [str(p) for p in extra], 'status': 'backup_complete'}
    manifest_path = backup / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    # Stage and revalidate before changing any destination file.
    with tempfile.TemporaryDirectory(prefix='artel-release-') as temp:
        stage = Path(temp)
        for rel in changed:
            replace_file(source / rel, stage / rel)
            if digest(stage / rel) != expected[rel]:
                raise ValueError('Источник изменился во время подготовки: ' + str(rel))
            if rel.suffix == '.py':
                compile((stage / rel).read_bytes(), str(rel), 'exec')
        if set(running(target)) - set(parked):
            raise ValueError('Процессы запустились снова. Код не изменён; отключите автоперезапуск.')
        if on_write:
            on_write()
        touched = []
        try:
            for rel in changed:
                touched.append(rel)
                replace_file(stage / rel, target / rel)
            for rel, value in expected.items():
                check_code_path(target, rel)
                if not (target / rel).is_file() or digest(target / rel) != value:
                    raise ValueError('Проверка установленного файла не пройдена: ' + str(rel))
        except BaseException:
            failures = []
            for rel in reversed(touched):
                try:
                    original = backup / 'installation' / rel
                    if original.exists():
                        replace_file(original, target / rel)
                    elif (target / rel).exists():
                        (target / rel).unlink()
                except OSError as error:
                    failures.append(str(error))
            manifest['status'] = 'rollback_failed' if failures else 'rolled_back'
            manifest['rollback_errors'] = failures
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            if failures:
                print('Не удалось полностью откатить код. Восстановите installation из ' + str(backup), file=sys.stderr)
            raise
    manifest['status'] = 'installed'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Готово: добавлено — {len(added)}, заменено — {len(changed) - len(added)}. '
          f'Проверено файлов — {len(expected)}. Данные сохранены.')
    if not parked:
        print('Далее: python3 artel.py check, затем привычный запуск демонов и dashboard.')
    return backup


def registered(target):
    records = {}
    for path in (target / '.artel-maintenance').glob('[0-9]*.json'):
        record = json.loads(path.read_text())
        try:
            if not pid_alive(record['pid']):
                continue
        except ProcessLookupError:
            continue
        records[str(record['pid'])] = record
    return records


def managed_install(source, target, backup, extra, timeout):
    plan(source, target)  # Validate before asking any process to drain.
    directory = target / '.artel-maintenance'
    request = directory / 'request.json'
    if request.exists():
        raise ValueError('Незавершённое обслуживание: проверьте резервную копию и восстановите код перед удалением ' + str(request))
    records = registered(target)
    actual = set(running(target))
    # A running task may have GigaCode children. Only registered roots must cooperate.
    parents = {}
    for line in subprocess.check_output(['ps', '-axo', 'pid=,ppid='], text=True).splitlines():
        p, parent = line.split()
        parents[p] = parent
    def managed(pid):
        visited = set()
        while pid not in visited:
            if pid in records:
                return True
            visited.add(pid)
            pid = parents.get(pid, '0')
        return False
    unknown = [pid for pid in actual if not managed(pid)]
    if unknown:
        raise ValueError('Процессы без протокола ожидания: ' + ', '.join(unknown) +
                         '. Для первого перехода остановите Артель и выполните обычное обновление без --managed.')
    records = {pid:r for pid,r in records.items() if pid in actual}
    if not records:
        return install(source, target, backup, extra)
    directory.mkdir(mode=0o700, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = directory / ('request-' + token)
    temporary.write_text(json.dumps({'token':token, 'phase':'drain'}))
    os.link(temporary, request)
    temporary.unlink()
    safe_to_resume = True
    try:
        print('Новые задачи заблокированы. Ожидаю завершения текущей работы…', flush=True)
        deadline = time.monotonic() + timeout
        while True:
            current = registered(target)
            waiting = [pid for pid in records if pid in current and current[pid].get('ready') != token]
            if not waiting:
                break
            if time.monotonic() >= deadline:
                raise ValueError('Время ожидания истекло. Код не менялся; работа будет продолжена.')
            time.sleep(.5)
        temporary.write_text(json.dumps({'token':token, 'phase':'stop'}))
        os.replace(temporary, request)
        safe_to_resume = False
        stop_deadline = time.monotonic() + 60
        while True:
            current = registered(target)
            waiting = [pid for pid,r in current.items() if pid in records and
                       ((r['role'] == 'supervisor' and not r.get('stopped')) or
                        (r['role'] == 'daemon' and str(r['parent']) in records and records[str(r['parent'])]['role'] == 'supervisor'))]
            if not waiting:
                break
            if time.monotonic() >= stop_deadline:
                raise ValueError('Не все процессы подтвердили остановку. Обслуживание сохранено; код не изменён.')
            time.sleep(.25)
        parked = [pid for pid in records if pid in current]
        # Persisted recovery request deliberately remains after an unhandled hard failure.
        safe_to_resume = True
        def writing():
            nonlocal safe_to_resume
            safe_to_resume = False
        started = time.time()
        try:
            result = install(source, target, backup, extra, parked=parked, on_write=writing)
            safe_to_resume = True
        except BaseException:
            # install reports successful rollback explicitly in its manifest.
            manifests = sorted(backup.glob('*/manifest.json'), key=lambda p:p.stat().st_mtime)
            if not safe_to_resume and manifests and manifests[-1].stat().st_mtime >= started:
                last = json.loads(manifests[-1].read_text())
                safe_to_resume = last.get('target') == str(target) and last.get('status') == 'rolled_back'
            raise
    finally:
        if safe_to_resume:
            request.unlink(missing_ok=True)
        else:
            print('Процессы оставлены в обслуживании. Проверьте копию и восстановите код; затем удалите ' + str(request), file=sys.stderr)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        current = registered(target)
        children_restored = all(sum(r['role'] == 'daemon' and str(r['parent']) == pid for r in current.values()) >=
                                sum(r['role'] == 'daemon' and str(r['parent']) == pid for r in records.values())
                                for pid in parked if records[pid]['role'] == 'supervisor')
        if children_restored and all(pid in current and current[pid].get('ready') is None for pid in parked):
            print('Dashboard и управляющие процессы перезапущены с прежними argv, окружением и рабочей папкой.')
            return result
        time.sleep(.5)
    raise ValueError('Код обновлён, но не все процессы подтвердили повторный запуск. Проверьте artel.py status и логи.')


def main():
    parser = argparse.ArgumentParser(description='Обновление кода с резервной копией. Используйте --managed для автоматического ожидания задач; без него предварительно остановите Артель.')
    parser.add_argument('--source', required=True, type=Path, help='распакованная новая версия')
    parser.add_argument('--target', required=True, type=Path, help='существующая установка на минике')
    parser.add_argument('--backup-dir', type=Path, help='по умолчанию artel-backups рядом с установкой')
    parser.add_argument('--data-path', action='append', default=[], type=Path, help='дополнительный внешний путь данных для резервной копии; можно повторять')
    parser.add_argument('--managed', action='store_true', help='дождаться задач и автоматически возобновить прежние процессы (нужен протокол обслуживания)')
    parser.add_argument('--wait-timeout', type=float, default=14400, help='максимум ожидания задач, секунды; по умолчанию 4 часа')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='только показать список, без записи и остановки процессов')
    mode.add_argument('--verify-only', action='store_true', help='проверить совпадение всех файлов пакета и установки; ничего не менять')
    args = parser.parse_args()
    if os.name == 'nt':
        parser.error('Обновление через update_artel.py пока поддерживается только на Linux/macOS. На Windows остановите Артель и переносите только код, сохраняя config, tmp, memory, logs и JSON-настройки дашборда.')
    source, target = args.source.resolve(), args.target.resolve()
    backup = (args.backup_dir or target.parent / 'artel-backups').resolve()
    extra = [p.resolve(strict=True) for p in args.data_path]
    if not target.is_dir() or not (target / 'artel.py').is_file():
        raise ValueError('Цель должна быть существующей установкой Артели')
    if nested(source, target) or nested(target, source):
        raise ValueError('Источник и установка должны находиться в отдельных папках')
    if nested(backup, target) or nested(backup, source):
        raise ValueError('Резервные копии должны находиться вне установки и источника')
    if any(nested(backup, p) or nested(p, backup) for p in extra):
        raise ValueError('Внешние данные и каталог резервных копий не должны пересекаться')
    if args.dry_run or args.verify_only:
        files = plan(source, target)
        print_plan(source, target, files)
        for p in files:
            print(('ЗАМЕНИТЬ ' if (target / p).exists() else 'ДОБАВИТЬ ') + str(p))
        if args.verify_only:
            if files:
                raise ValueError('Установка не совпадает с пакетом: ' + str(len(files)) + ' файлов. Выполните обновление.')
            print('Все файлы пакета присутствуют в установке и совпадают по содержимому.')
            return
        print(f'Файлов к обновлению: {len(files)}. Резервные копии: {backup}')
        return
    with (target / '.artel-update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Другое обновление уже выполняется')
        if args.managed:
            if args.wait_timeout <= 0:
                raise ValueError("--wait-timeout должен быть положительным")
            managed_install(source, target, backup, extra, args.wait_timeout)
        else:
            install(source, target, backup, extra)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as exc:
        print('Обновление остановлено: ' + str(exc), file=sys.stderr)
        sys.exit(1)
