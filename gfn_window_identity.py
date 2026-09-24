"""Identify actual GeForce NOW windows before diagnostic input or capture."""
import ctypes
from ctypes import wintypes
from pathlib import PureWindowsPath

import win32process


GFN_EXECUTABLES = {'geforcenow.exe', 'geforcenowcontainer.exe', 'geforcenowstreamer.exe'}
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def is_gfn_window(hwnd):
    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            return False
        return PureWindowsPath(path.value).name.lower() in GFN_EXECUTABLES
    finally:
        kernel32.CloseHandle(handle)
