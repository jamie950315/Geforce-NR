import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == 'win32', 'Requires the deployed Windows Core/Lab runtime')
class DailyGeometryTests(unittest.TestCase):
    def test_failed_latest_record_removes_active_pointer(self):
        import live_run

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'overlay'
            root.mkdir()
            close_handle = Mock()
            target = SimpleNamespace(hwnd=1, title='Test game', to_dict=lambda: {'hwnd': 1})
            win = SimpleNamespace(mutex=lambda _: 42, enumerate=lambda: [target],
                                  rect=lambda _: (0, 0, 2560, 1440),
                                  u=SimpleNamespace(IsIconic=lambda _: False),
                                  k=SimpleNamespace(CloseHandle=close_handle))
            original_atomic_json = live_run.atomic_json

            def fail_latest(path, value):
                if path.name == 'latest.json':
                    raise OSError('Injected latest-record write failure')
                return original_atomic_json(path, value)

            def read_json(path):
                return {} if path.name == 'appearance.json' else json.loads(path.read_text())

            with ExitStack() as stack:
                stack.enter_context(patch.object(sys, 'argv', ['live_run.py', '--name', 'failure-check',
                    '--hwnd', '1', '--mode', 'bypass', '--seconds', '5', '--original-worker']))
                stack.enter_context(patch.dict(os.environ, {}, clear=False))
                for name, value in [('ROOT', root), ('LIVE', Path(folder) / 'live'),
                                    ('LAB', Path(folder) / 'lab'), ('STABLE', Path(folder) / 'stable'),
                                    ('Win32', lambda: win), ('verify', lambda: {}),
                                    ('digest', lambda _: 'sha'), ('load', read_json),
                                    ('atomic_json', fail_latest),
                                    ('Appearance', SimpleNamespace(from_dict=lambda _: None)),
                                    ('Settings', lambda **_: SimpleNamespace(to_dict=lambda: {}))]:
                    stack.enter_context(patch.object(live_run, name, value))
                with self.assertRaisesRegex(OSError, 'Injected latest-record write failure'):
                    live_run.main()
            self.assertFalse((root / 'active.json').exists())
            self.assertFalse((root / 'latest.json').exists())
            close_handle.assert_called_once_with(42)

    def test_daily_size_change_stops_before_reconfigure(self):
        from live_run import RecordedEngine

        engine = RecordedEngine.__new__(RecordedEngine)
        engine.owner = None
        engine.daily_geometry = (2560, 1440)
        engine.target = SimpleNamespace(hwnd=1)
        engine.win = SimpleNamespace(
            rect=lambda hwnd: (0, 0, 2578, 1398),
            u=SimpleNamespace(IsIconic=lambda hwnd: False),
        )
        engine.stop = threading.Event()
        engine.reason = 'running'
        self.assertTrue(engine._visibility())
        self.assertTrue(engine.stop.is_set())
        self.assertEqual(engine.reason, 'target_resized')

    def test_diagnostic_resize_keeps_existing_path(self):
        from live_run import Engine, RecordedEngine

        engine = RecordedEngine.__new__(RecordedEngine)
        engine.owner = None
        engine.daily_geometry = None
        engine.target = SimpleNamespace(hwnd=1)
        engine.win = SimpleNamespace(
            rect=lambda hwnd: (0, 0, 2578, 1398),
            u=SimpleNamespace(IsIconic=lambda hwnd: False),
        )
        engine.stop = threading.Event()
        engine.reason = 'running'
        engine.suspended = False
        with patch.object(Engine, '_visibility', return_value=False):
            self.assertFalse(engine._visibility())
        self.assertFalse(engine.stop.is_set())


if __name__ == '__main__':
    unittest.main()
