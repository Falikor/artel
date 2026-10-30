"""Windows child runner: own job closes with this process and kills leftover descendants.

Executed as a script before the external CLI/test command; no repository imports.
Win32 Job Objects: https://learn.microsoft.com/windows/win32/procthread/job-objects
"""
import ctypes
from ctypes import wintypes
import subprocess
import sys


def own_job():
    class Basic(ctypes.Structure):
        _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                    ('Flags', wintypes.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                    ('MaxWorkingSet', ctypes.c_size_t), ('ActiveProcesses', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('Priority', wintypes.DWORD), ('Scheduling', wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ('ReadOperations', 'WriteOperations', 'OtherOperations', 'ReadBytes', 'WriteBytes', 'OtherBytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('Basic', Basic), ('IO', IO), ('ProcessMemory', ctypes.c_size_t),
                    ('JobMemory', ctypes.c_size_t), ('PeakProcessMemory', ctypes.c_size_t),
                    ('PeakJobMemory', ctypes.c_size_t)]

    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    dll.CreateJobObjectW.restype = wintypes.HANDLE
    dll.GetCurrentProcess.restype = wintypes.HANDLE
    dll.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    dll.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = dll.CreateJobObjectW(None, None)  # non-inheritable, private handle
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Extended()
    limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not dll.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not dll.AssignProcessToJobObject(handle, dll.GetCurrentProcess()):
        error = ctypes.get_last_error()
        dll.CloseHandle(handle)
        raise ctypes.WinError(error)
    # Keep it open for this process lifetime. OS closes it on normal exit and taskkill.
    return handle


def main():
    job = own_job()
    try:
        return subprocess.call(sys.argv[1:], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    except OSError as exc:
        print('Не удалось запустить команду: ' + str(exc), file=sys.stderr)
        return 127


if __name__ == '__main__':
    sys.exit(main())
