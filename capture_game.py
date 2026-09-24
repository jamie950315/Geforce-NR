"""Capture raw gameplay samples only when no local NR overlay is active."""
import ctypes
import json
from pathlib import Path
import time
import win32api
import win32con
import win32gui
from PIL import ImageGrab
from gfn_window_identity import is_gfn_window

ROOT = Path(__file__).resolve().parent
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
if (ROOT/'active.json').exists():
    raise RuntimeError('Wait for the current NR test to finish')


def checked_game_window():
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if (not is_gfn_window(hwnd) or not title or title.strip().lower() == 'geforce now'
            or (width, height) != (2560, 1440) or left > 0 or top > 0
            or right < width or bottom < height - 80):
        raise RuntimeError('A full-screen GFN game must be foreground')
    return hwnd


target = checked_game_window()
visible = []
win32gui.EnumWindows(lambda h,_: visible.append(win32gui.GetWindowText(h)) if win32gui.IsWindowVisible(h) else None, None)
if any(title in visible for title in ('NeuralScreen', 'Geforce NR — Output')):
    raise RuntimeError('Local overlay must be stopped')
out = ROOT/'raw-game-samples'
out.mkdir(exist_ok=False)
rows=[]
for i in range(12):
    if checked_game_window() != target:
        raise RuntimeError('GFN game window changed')
    image=ImageGrab.grab(bbox=(0, 0, 2560, 1440))
    if image.size != (2560,1440):
        raise RuntimeError('Desktop geometry changed')
    path=out/f'frame-{i:03d}.png'
    image.convert('RGB').save(path,compress_level=1)
    rows.append(dict(path=str(path),time=time.time()))
    time.sleep(.1)
(out/'manifest.json').write_text(json.dumps(dict(frames=rows,scope='Desktop captures of visible GFN without local NR; not a live paired WGC capture'),indent=2),encoding='utf-8')
