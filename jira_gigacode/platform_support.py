"""Small OS boundary: locks, process probes, child groups and temporary files."""
import errno
import os
import signal
import subprocess
import time

if os.name != 'nt':
    import fcntl
else:
    import msvcrt

    class fcntl:
        LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8

        @staticmethod
        def flock(file, operation):
            # msvcrt locks a byte range; closing the file releases it.
            fd = file if isinstance(file, int) else file.fileno()
            if os.fstat(fd).st_size == 0:
                os.write(fd, b'\0')
            while True:
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK if operation & 8 else msvcrt.LK_NBLCK, 1)
                    return
                except OSError as exc:
                    if operation & 8 or exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if operation & 4:
                        raise BlockingIOError(errno.EAGAIN, 'File is locked') from None
                    time.sleep(.05)


def pid_alive(pid):
    try:
        pid = int(pid)
        if pid <= 0:
            return False
    except (TypeError, ValueError):
        return False
    if os.name == 'nt':
        # os.kill(pid, 0) on Windows can terminate a process. Use a read-only handle.
        import ctypes
        from ctypes import wintypes
        dll = ctypes.WinDLL('kernel32', use_last_error=True)
        dll.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        dll.OpenProcess.restype = wintypes.HANDLE
        dll.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        dll.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = dll.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied: conservatively alive.
        try:
            code = wintypes.DWORD()
            return not dll.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            dll.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def session_options(detached=False):
    if os.name == 'nt':
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        if detached:
            flags |= subprocess.DETACHED_PROCESS
        return {'creationflags': flags}
    return {'start_new_session': True}


def kill_tree(pid, force=False):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(int(pid)), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    else:
        try:
            os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass


def child_command(argv):
    if os.name != 'nt':
        return argv
    import sys
    return [sys.executable, os.path.join(os.path.dirname(__file__), 'windows_runner.py'), *argv]
