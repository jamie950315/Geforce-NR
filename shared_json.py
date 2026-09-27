"""Read atomic JSON snapshots without blocking Windows file replacement."""
import json
import os
from pathlib import Path
import sys


def read_json(path, *, loads=json.loads):
    if sys.platform != 'win32':
        return loads(Path(path).read_text(encoding='utf-8-sig'))
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # READ | WRITE | DELETE sharing: the reader keeps the old complete snapshot
    # while a writer atomically replaces its directory entry with the new one.
    handle = kernel.CreateFileW(str(Path(path)), 0x80000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, 'r', encoding='utf-8-sig') as file:
        return loads(file.read())
