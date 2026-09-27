import ctypes
from ctypes import wintypes
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from application_windows import enumerate_application_windows


class ApplicationWindowTests(unittest.TestCase):
    def adapter(self, changes):
        rows = {hwnd: dict(title='Document', visible=True, iconic=False, kind='AppWindow',
                          style=0, cloaked=0, geometry=(0, 0, 960, 640), pid=hwnd+100,
                          exe=r'C:\Apps\editor.exe', created=99, valid=True)
                for hwnd in changes}
        for hwnd, values in changes.items():
            rows[hwnd].update(values)

        def text(hwnd, buffer, count, field):
            buffer.value = rows[hwnd][field]
            return len(buffer.value)

        def attribute(hwnd, attr, pointer, size):
            self.assertEqual(attr, 14)
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))[0] = rows[hwnd]['cloaked']
            return 0

        def enum(callback, _):
            for hwnd in rows:
                callback(hwnd, 0)
            return True

        return SimpleNamespace(
            callback=lambda f: f, rect=lambda h: rows[h]['geometry'],
            pid=lambda h: rows[h]['pid'],
            identity=lambda pid: next((r['exe'], r['created']) for r in rows.values() if r['pid'] == pid),
            valid=lambda t: rows[t.hwnd]['valid'],
            d=SimpleNamespace(DwmGetWindowAttribute=attribute),
            u=SimpleNamespace(IsWindowVisible=lambda h: rows[h]['visible'], IsIconic=lambda h: rows[h]['iconic'],
                GetWindowTextW=lambda h, b, n: text(h, b, n, 'title'),
                GetClassNameW=Mock(side_effect=lambda h, b, n: text(h, b, n, 'kind')),
                GetWindowLongW=Mock(side_effect=lambda h, index: rows[h]['style']), EnumWindows=enum))

    def test_accepts_non_gfn_and_gfn_applications(self):
        win = self.adapter({1: {}, 2: dict(title='GeForce NOW', exe=r'C:\GFN\GeForceNOW.exe')})
        targets = enumerate_application_windows(win)
        self.assertEqual([t.hwnd for t in targets], [1, 2])
        self.assertEqual(targets[0].to_dict()['exe'], r'C:\Apps\editor.exe')

    def test_excludes_unsafe_or_non_application_surfaces(self):
        cases = [dict(visible=False), dict(iconic=True), dict(title=''), dict(kind='Shell_TrayWnd'),
                 dict(kind='WorkerW'), dict(style=0x80), dict(cloaked=1),
                 dict(geometry=(0, 0, 63, 640)), dict(pid=os.getpid()), dict(pid=999),
                 dict(exe=''), dict(created=0), dict(valid=False), dict(title='Geforce NR'),
                 dict(title='Geforce NR — Output'), dict(title='NeuralScreen')]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(enumerate_application_windows(self.adapter({1: case}), (999,)), [])

    def test_appwindow_style_can_override_toolwindow_style(self):
        self.assertEqual(len(enumerate_application_windows(self.adapter({1: dict(style=0x40080)}))), 1)

    def test_enumeration_failure_is_not_reported_as_empty_list(self):
        win = self.adapter({})
        win.u.EnumWindows = lambda *_: False
        with self.assertRaisesRegex(RuntimeError, 'enumerate application'):
            enumerate_application_windows(win)


if __name__ == '__main__':
    unittest.main()
