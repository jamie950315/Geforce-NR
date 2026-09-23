import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch


@unittest.skipUnless(sys.platform == 'win32', 'Requires the deployed Windows Core/Lab runtime')
class DailyGeometryTests(unittest.TestCase):
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
