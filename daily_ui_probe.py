"""Bounded interactive-desktop UI verification; never sends input to other apps."""
import argparse
import ctypes
import json
import os
import re
from pathlib import Path
import time

import win32api
import win32con
import win32gui
import win32process
from PIL import ImageGrab
from gfn_window_identity import is_gfn_window

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--click', nargs=2, type=int)
    ap.add_argument('--key', choices=['home', 'down', 'enter', 'escape', 'end', 'delete'])
    ap.add_argument('--close', action='store_true')
    ap.add_argument('--open-shortcut', action='store_true')
    ap.add_argument('--confirm-close', action='store_true')
    ap.add_argument('--panel-hotkey', action='store_true')
    ap.add_argument('--editor', action='store_true')
    ap.add_argument('--drag', nargs=4, type=int)
    ap.add_argument('--save-mask', action='store_true')
    ap.add_argument('--numeric-value')
    ap.add_argument('--discard-changes', choices=['yes', 'no'])
    args = ap.parse_args()
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    if args.panel_hotkey:
        foreground = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(foreground)
        if not is_gfn_window(foreground) or title.strip().lower() == 'geforce now':
            raise RuntimeError('Panel hotkey test requires the game in foreground')
        for key in (17, 18, 0x78):
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), 0, 0)
        for key in (0x78, 18, 17):
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(2)
    if args.open_shortcut:
        from win32com.shell import shell, shellcon
        desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, 0, 0))
        os.startfile(desktop/'Geforce NR.lnk')
        time.sleep(2)
    candidates = []
    expected_title = 'Geforce NR — HUD Mask Editor' if args.editor else 'Geforce NR'
    win32gui.EnumWindows(lambda h, _: candidates.append(h) if win32gui.IsWindowVisible(h)
                         and win32gui.GetWindowText(h) == expected_title
                         and win32gui.GetClassName(h) != '#32770' else None, None)
    if len(candidates) != 1:
        raise RuntimeError('Expected one visible Geforce NR panel')
    hwnd = candidates[0]
    if args.discard_changes:
        if not args.editor:
            raise RuntimeError('Discard verification is restricted to the editor')
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        dialogs = []
        win32gui.EnumWindows(lambda h, _: dialogs.append(h) if win32gui.GetClassName(h) == '#32770'
            and win32gui.GetWindowText(h) == 'Discard unsaved changes?'
            and win32process.GetWindowThreadProcessId(h)[1] == pid else None, None)
        if len(dialogs) != 1:
            raise RuntimeError('Expected this editor\'s discard confirmation')
        button = win32gui.GetDlgItem(dialogs[0], win32con.IDYES if args.discard_changes == 'yes' else win32con.IDNO)
        if not button:
            raise RuntimeError('Expected confirmation button is missing')
        win32gui.SendMessage(button, win32con.BM_CLICK, 0, 0)
        time.sleep(1)
        (ROOT/'daily-probe.json').write_text(json.dumps(dict(discard_answer=args.discard_changes, editor_exists=bool(win32gui.IsWindow(hwnd)))))
        return
    if args.panel_hotkey:
        rect = win32gui.GetWindowRect(hwnd)
        (ROOT/'daily-probe.json').write_text(json.dumps(dict(panel_focused=win32gui.GetForegroundWindow() == hwnd,
            pid=win32process.GetWindowThreadProcessId(hwnd)[1], rect=rect)))
        ImageGrab.grab(bbox=rect).save(ROOT/'daily-probe.png')
        return
    if args.confirm_close:
        dialogs = []
        owner_pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        def find_dialog(h, _):
            if win32gui.GetClassName(h) != '#32770' or win32process.GetWindowThreadProcessId(h)[1] != owner_pid:
                return
            texts = []
            win32gui.EnumChildWindows(h, lambda child, _: texts.append(win32gui.GetWindowText(child)), None)
            if any('pipeline is still active' in text for text in texts):
                dialogs.append(h)
        win32gui.EnumWindows(find_dialog, None)
        if len(dialogs) != 1:
            raise RuntimeError('Expected this panel\'s explicit stop-and-close confirmation')
        win32gui.PostMessage(dialogs[0], win32con.WM_COMMAND, win32con.IDYES, 0)
        time.sleep(2)
        (ROOT/'daily-probe.json').write_text(json.dumps(dict(close_confirmed=True, panel_exists=bool(win32gui.IsWindow(hwnd)))))
        return
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    focus_error = None
    if win32gui.GetForegroundWindow() != hwnd:
        source_thread = win32api.GetCurrentThreadId()
        foreground_thread = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[0]
        win32gui.PumpWaitingMessages()
        attached = ctypes.windll.user32.AttachThreadInput(source_thread, foreground_thread, True)
        try:
            win32gui.BringWindowToTop(hwnd)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception as exc:
                focus_error = str(exc)
        finally:
            if attached:
                ctypes.windll.user32.AttachThreadInput(source_thread, foreground_thread, False)
    time.sleep(.3)
    rect = win32gui.GetWindowRect(hwnd)
    if args.drag:
        if not args.editor:
            raise RuntimeError('Drag verification is restricted to the mask editor')
        x0, y0, x1, y1 = args.drag
        if any(not (0 <= x < rect[2]-rect[0] and 0 <= y < rect[3]-rect[1]) for x, y in ((x0,y0),(x1,y1))):
            raise ValueError('Drag leaves the editor')
        if win32gui.GetForegroundWindow() != hwnd:
            raise RuntimeError('Editor lost foreground; drag refused')
        win32api.SetCursorPos((rect[0]+x0, rect[1]+y0))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        try:
            for step in range(1, 11):
                win32api.SetCursorPos((rect[0]+round(x0+(x1-x0)*step/10), rect[1]+round(y0+(y1-y0)*step/10)))
                time.sleep(.025)
        finally:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    if args.close:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    if args.click:
        x, y = args.click
        if not (0 <= x < rect[2]-rect[0] and 0 <= y < rect[3]-rect[1]):
            raise ValueError('Click is outside the panel')
        if win32gui.GetForegroundWindow() != hwnd:
            raise RuntimeError('Panel lost foreground; input refused')
        win32api.SetCursorPos((rect[0]+x, rect[1]+y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    if args.key:
        foreground = win32gui.GetForegroundWindow()
        if win32process.GetWindowThreadProcessId(foreground)[1] != win32process.GetWindowThreadProcessId(hwnd)[1]:
            raise RuntimeError('Panel lost foreground; key refused')
        key = dict(home=36, down=40, enter=13, escape=27, end=35, delete=46)[args.key]
        win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), 0, 0)
        win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), win32con.KEYEVENTF_KEYUP, 0)
    if args.numeric_value is not None:
        if not args.editor or win32gui.GetForegroundWindow() != hwnd or not re.fullmatch(r'-?[0-9]{1,6}', args.numeric_value):
            raise RuntimeError('Only numeric editor input is supported')
        for key in (17, 65):
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), 0, 0)
        for key in (65, 17):
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), win32con.KEYEVENTF_KEYUP, 0)
        for char in args.numeric_value:
            key = 0xBD if char == '-' else ord(char)
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), 0, 0)
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), win32con.KEYEVENTF_KEYUP, 0)
    if args.save_mask:
        if not args.editor or win32gui.GetForegroundWindow() != hwnd:
            raise RuntimeError('Mask save shortcut requires the foreground editor')
        for key in (17, 83):
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), 0, 0)
        for key in (83, 17):
            win32api.keybd_event(key, win32api.MapVirtualKey(key, 0), win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(1)
    info = dict(hwnd=hwnd, pid=win32process.GetWindowThreadProcessId(hwnd)[1] if win32gui.IsWindow(hwnd) else None,
                rect=rect, foreground=win32gui.GetForegroundWindow(), focus_error=focus_error)
    (ROOT/'daily-probe.json').write_text(json.dumps(info, indent=2))
    ImageGrab.grab(bbox=rect).save(ROOT/'daily-probe.png')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        (ROOT/'daily-probe.json').write_text(json.dumps(dict(error=str(exc))))
        raise
