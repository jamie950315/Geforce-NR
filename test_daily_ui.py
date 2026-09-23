from types import SimpleNamespace
import unittest
from unittest.mock import patch

from daily_ui import DailyApp, fit_window_bounds


class Variable:
    def __init__(self):
        self.value = ''

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class CloseRecoveryTests(unittest.TestCase):
    def test_window_fit_includes_title_bar_and_work_area_origin(self):
        w, h, x, y = fit_window_bounds((854, 1052), (100, 30, 2660, 1420), (16, 39))
        self.assertEqual((w, h), (854, 1052))
        self.assertGreaterEqual(x, 100)
        self.assertGreaterEqual(y, 30)
        self.assertLessEqual(x+w+16, 2660)
        self.assertLessEqual(y+h+39, 1420)
        self.assertEqual(fit_window_bounds((854, 1052), (0, 0, 640, 480), (16, 39)), (624, 441, 0, 0))

    def test_failed_stop_metadata_does_not_lock_closing_panel(self):
        app = DailyApp.__new__(DailyApp)
        app._closing = True
        app._stop_requested_for_close = True
        app.status_state_var = Variable()
        app.status_detail_var = Variable()
        scheduled, destroyed = [], []
        app.root = SimpleNamespace(after=lambda *args: scheduled.append(args),
                                   destroy=lambda: destroyed.append(True))
        def failure():
            raise RuntimeError('Stop target identity mismatch')
        app.controller = SimpleNamespace(busy=True, poll=failure)
        app._sync_controls = lambda: None
        with patch('daily_ui._write_error_log'):
            app._poll_controller()
        self.assertFalse(app._closing)
        self.assertFalse(app._stop_requested_for_close)
        self.assertEqual(app.status_state_var.value, 'ERROR')
        self.assertIn('panel remains open', app.status_detail_var.value)
        self.assertFalse(destroyed)
        self.assertEqual(len(scheduled), 1)

    def test_refresh_does_not_select_reused_game_window(self):
        old = dict(hwnd=5, pid=7, created=10, title='Game A', width=2560, height=1440)
        for replacement in (dict(old, pid=8, created=11, title='Game B'),
                            dict(old, title='Game B'), dict(old, width=1920, height=1080)):
            with self.subTest(replacement=replacement):
                app = DailyApp.__new__(DailyApp)
                app.target_var = Variable()
                app.target_var.set('old')
                app.target_by_display = {'old': old}
                app.target_combo = SimpleNamespace(configure=lambda **kwargs: None)
                app.status_detail_var = Variable()
                app.controller = SimpleNamespace(list_targets=lambda: [replacement], busy=False)
                app._refresh_mask_status = lambda: None
                app.refresh_targets()
                self.assertEqual(app.target_var.value, '')
                self.assertIn('selected game changed', app.status_detail_var.value)

    def test_target_close_clears_stale_selection_once(self):
        app = DailyApp.__new__(DailyApp)
        app._last_state = 'running'
        app._closing = False
        app.targets = [dict(hwnd=5)]
        app.target_by_display = {'old': dict(hwnd=5)}
        app.target_var = Variable()
        app.target_var.set('old')
        combo_updates, mask_refreshes, polls = [], [], []
        app.target_combo = SimpleNamespace(configure=lambda **kwargs: combo_updates.append(kwargs))
        app.controller = SimpleNamespace(poll=lambda: dict(state='stopped',
            detail='The selected GFN window closed.', end_reason='target_closed'))
        app._set_status = lambda **kwargs: setattr(app, '_last_state', kwargs['state'])
        app._refresh_mask_status = lambda: mask_refreshes.append(True)
        app._controller_busy = lambda: False
        app.root = SimpleNamespace(after=lambda *args: polls.append(args))
        app._poll_controller()
        self.assertEqual(app.target_var.get(), '')
        self.assertEqual(app.target_by_display, {})
        self.assertEqual(combo_updates, [dict(values=[])])
        self.assertEqual(len(mask_refreshes), 1)
        app.target_var.set('new')
        app._poll_controller()
        self.assertEqual(app.target_var.get(), 'new')
        self.assertEqual(len(mask_refreshes), 1)


if __name__ == '__main__':
    unittest.main()
