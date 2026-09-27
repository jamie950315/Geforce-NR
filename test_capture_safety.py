"""Exercise real probe entry points with fake windows and no desktop input."""
import ctypes
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parent


class CaptureSafetyTests(unittest.TestCase):
    def run_probe(self, script, args=(), *, click_target=1, change_during_capture=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = {'foreground': 1, 'alive': True}
            saves, inputs = [], []
            gui = SimpleNamespace(
                EnumWindows=lambda callback, arg: callback(1, arg),
                GetWindowText=lambda hwnd: ('Geforce NR' if script == 'daily_ui_probe.py' else 'Game - GeForce NOW') if hwnd == 1 else 'Other app',
                IsWindowVisible=lambda hwnd: True,
                IsWindow=lambda hwnd: state['alive'],
                GetClassName=lambda hwnd: 'TkTopLevel',
                ShowWindow=lambda *args: None,
                PostMessage=lambda *args: state.update(alive=False, foreground=2),
                GetWindowRect=lambda hwnd: (0, 0, 2560, 1440),
                GetForegroundWindow=lambda: state['foreground'],
                WindowFromPoint=lambda point: click_target,
                GetAncestor=lambda hwnd, flag: hwnd,
            )
            api = SimpleNamespace(GetSystemMetrics=lambda key: 2560 if key == 0 else 1440,
                SetCursorPos=lambda point: inputs.append(('move', point)),
                mouse_event=lambda *event: inputs.append(event))
            constants = SimpleNamespace(SM_CXSCREEN=0, SM_CYSCREEN=1,
                                        SW_RESTORE=9, WM_CLOSE=16,
                                        MOUSEEVENTF_LEFTDOWN=2, MOUSEEVENTF_LEFTUP=4)
            image = SimpleNamespace(size=(2560, 1440),
                                    save=lambda *a, **k: saves.append(a[0]))
            image.convert = lambda mode: image

            def grab(**kwargs):
                if change_during_capture:
                    state['foreground'] = 2
                return image

            modules = {'win32gui': gui, 'win32api': api, 'win32con': constants,
                'win32process': SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, hwnd * 10)),
                'gfn_window_identity': SimpleNamespace(is_gfn_window=lambda hwnd: hwnd == 1),
                'PIL': SimpleNamespace(ImageGrab=SimpleNamespace(grab=grab))}
            error = None
            with patch.dict(sys.modules, modules), patch.object(sys, 'argv', [script, *args]), \
                    patch.object(ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
                        SetProcessDpiAwarenessContext=lambda value: None)), create=True), \
                    patch('time.sleep'):
                try:
                    exec(compile((SOURCE / script).read_text(encoding='utf-8'), str(root / script), 'exec'),
                         {'__file__': str(root / script), '__name__': '__main__'})
                except RuntimeError as exc:
                    error = exc
            result_file = root / ('daily-probe.json' if script == 'daily_ui_probe.py' else 'desktop.json')
            result = json.loads(result_file.read_text()) if result_file.exists() else {}
            return error, saves, inputs, result

    def test_click_outside_gfn_is_refused_before_moving_cursor(self):
        error, _, inputs, _ = self.run_probe('desktop_probe.py', ['--click', '2600', '200'])
        self.assertIsNotNone(error)
        self.assertEqual(inputs, [])

    def test_click_on_another_window_over_gfn_is_refused(self):
        error, _, inputs, _ = self.run_probe('desktop_probe.py', ['--click', '100', '200'], click_target=2)
        self.assertIsNotNone(error)
        self.assertEqual(inputs, [])

    def test_click_inside_gfn_still_works(self):
        error, _, inputs, _ = self.run_probe('desktop_probe.py', ['--click', '100', '200'])
        self.assertIsNone(error)
        self.assertEqual(len(inputs), 3)

    def test_probe_discards_capture_after_foreground_changes(self):
        _, saves, _, result = self.run_probe('desktop_probe.py', change_during_capture=True)
        self.assertEqual(saves, [])
        self.assertFalse(result.get('screenshot_captured', False))

    def test_raw_capture_discards_frame_after_foreground_changes(self):
        error, saves, _, _ = self.run_probe('capture_game.py', change_during_capture=True)
        self.assertIsNotNone(error)
        self.assertEqual(saves, [])

    def test_panel_close_does_not_capture_the_app_behind_it(self):
        error, saves, _, result = self.run_probe('daily_ui_probe.py', ['--close'])
        self.assertIsNone(error)
        self.assertEqual(saves, [])
        self.assertFalse(result.get('screenshot_captured', False))

    def test_panel_capture_is_discarded_when_focus_changes(self):
        _, saves, _, result = self.run_probe('daily_ui_probe.py', change_during_capture=True)
        self.assertEqual(saves, [])
        self.assertFalse(result.get('screenshot_captured', False))


if __name__ == '__main__':
    unittest.main()
