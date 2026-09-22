"""Capture bounded interactive-session evidence without changing game state."""
import ctypes
import json
import os
from pathlib import Path
import sys
import time
import argparse

import win32api
import win32con
import win32gui
import win32process
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('--focus-gfn', action='store_true')
ap.add_argument('--click', nargs=2, type=int)
ap.add_argument('--key', choices=['escape', 'space', 'enter', 'up', 'down', 'stats', 'advanced', 'overlay'])
args = ap.parse_args()
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
rows = []


def visit(hwnd, _):
    title = win32gui.GetWindowText(hwnd)
    if title and win32gui.IsWindowVisible(hwnd):
        rows.append(dict(hwnd=hwnd, title=title, rect=win32gui.GetWindowRect(hwnd),
                         pid=win32process.GetWindowThreadProcessId(hwnd)[1]))


win32gui.EnumWindows(visit, None)
result = dict(pid=os.getpid(), windows=rows)
if args.focus_gfn:
    targets = [r for r in rows if r['title'] == 'GeForce NOW']
    if len(targets) == 1:
        try:
            win32gui.ShowWindow(targets[0]['hwnd'], win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(targets[0]['hwnd'])
        except Exception as exc:
            result['focus_error'] = str(exc)
        time.sleep(1)
if args.click or args.key:
    foreground = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(foreground)
    if 'GeForce NOW' not in title:
        raise RuntimeError('Refusing click outside the observed GFN window')
    if args.click:
        win32api.SetCursorPos(tuple(args.click))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    else:
        def key_event(key, flags=0):
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), flags, 0)
        vk = {'escape': 27, 'space': 32, 'enter': 13, 'up': 38, 'down': 40, 'stats': 78, 'advanced': 117, 'overlay': 71}[args.key]
        if args.key in ('stats','advanced','overlay'):key_event(17)
        if args.key == 'advanced':key_event(18)
        key_event(vk)
        time.sleep(.05)
        key_event(vk, win32con.KEYEVENTF_KEYUP)
        if args.key == 'advanced':key_event(18, win32con.KEYEVENTF_KEYUP)
        if args.key in ('stats','advanced','overlay'):key_event(17, win32con.KEYEVENTF_KEYUP)
    time.sleep(2)
result['foreground'] = win32gui.GetForegroundWindow()
result['foreground_title'] = win32gui.GetWindowText(result['foreground'])
try:
    im = ImageGrab.grab()
    im.save(ROOT / 'desktop.png')
    result['screenshot_size'] = im.size
except Exception as exc:
    result['capture_error'] = str(exc)
(ROOT / 'desktop.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
