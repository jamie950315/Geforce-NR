"""Application-window selection for the isolated daily launcher only.

Core/Lab's GFN-only enumeration and diagnostic capture policy stay unchanged.
"""
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import os


@dataclass(frozen=True)
class ApplicationTarget:
    hwnd: int
    pid: int
    exe: str
    created: int
    title: str

    def to_dict(self):
        return asdict(self)


INTERNAL_TITLES = {'Geforce NR', 'Geforce NR — Output', 'Geforce NR — HUD Mask Editor',
                   'NeuralScreen'}
SHELL_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}


def enumerate_application_windows(win, excluded_pids=()):
    """Return restored, visible top-level windows with verifiable identities."""
    excluded = {os.getpid(), *excluded_pids}
    win.u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    win.u.GetClassNameW.restype = ctypes.c_int
    win.u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    win.u.GetWindowLongW.restype = wintypes.LONG
    targets = []

    def visit(hwnd, _):
        try:
            if not win.u.IsWindowVisible(hwnd) or win.u.IsIconic(hwnd):
                return True
            title = ctypes.create_unicode_buffer(1024)
            win.u.GetWindowTextW(hwnd, title, len(title))
            if not title.value.strip() or title.value in INTERNAL_TITLES:
                return True
            kind = ctypes.create_unicode_buffer(256)
            if not win.u.GetClassNameW(hwnd, kind, len(kind)) or kind.value in SHELL_CLASSES:
                return True
            # Tool windows are auxiliary surfaces, unless explicitly app windows.
            style = win.u.GetWindowLongW(hwnd, -20)
            if style & 0x80 and not style & 0x40000:
                return True
            cloaked = wintypes.DWORD()
            if (win.d.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) != 0
                    or cloaked.value):
                return True
            if min(win.rect(hwnd)[2:]) < 64:
                return True
            pid = win.pid(hwnd)
            if not pid or pid in excluded:
                return True
            exe, created = win.identity(pid)
            if not exe or not created:
                return True
            target = ApplicationTarget(int(hwnd), pid, exe, created, title.value)
            if win.valid(target):
                targets.append(target)
        except OSError:
            # A window may disappear while EnumWindows visits it.
            pass
        except RuntimeError:
            # The adapter reports unavailable geometry as RuntimeError.
            pass
        return True

    callback = win.callback(visit)
    if not win.u.EnumWindows(callback, 0):
        raise RuntimeError('Could not enumerate application windows')
    return sorted(targets, key=lambda target: (target.title.casefold(), target.pid, target.hwnd))
