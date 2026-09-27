from types import SimpleNamespace
import unittest
from unittest.mock import patch

from daily_ui import DailyApp, RECOMMENDED_SETTINGS, fit_window_bounds


class Variable:
    def __init__(self):
        self.value = ''

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class CloseRecoveryTests(unittest.TestCase):
    def test_hdr_preference_round_trip_and_legacy_default(self):
        app = DailyApp.__new__(DailyApp)
        for name in ('mode', 'mask_enabled', 'mask_profile', 'hdr', 'hdr_mapping', 'hdr_queued', 'nr_height',
                     'flow_width', 'flow_grid', 'flow_preset'):
            setattr(app, name + '_var', Variable())
        for saved, expected in (({}, False), ({'hdr': True}, True),
                                ({'hdr': False}, False), (RECOMMENDED_SETTINGS, False)):
            with self.subTest(saved=saved):
                app._apply_settings_to_form(saved)
                self.assertIs(app._settings_from_form()['hdr'], expected)
                self.assertEqual(app._settings_from_form()['hdr_mapping'], saved.get('hdr_mapping', 'legacy'))
                self.assertFalse(app._settings_from_form()['hdr_queued'])
        for mapping in ('color-preserving', 'legacy'):
            app._apply_settings_to_form(dict(RECOMMENDED_SETTINGS, hdr=True, hdr_mapping=mapping))
            self.assertEqual(app._settings_from_form()['hdr_mapping'], mapping)
            self.assertTrue(app._settings_from_form()['hdr'])
        app._apply_settings_to_form(dict(RECOMMENDED_SETTINGS, hdr=True, hdr_queued=True, nr_height=900))
        self.assertTrue(app._settings_from_form()['hdr_queued'])
        self.assertEqual(app._settings_from_form()['nr_height'],900)

    def test_incompatible_hdr_changes_explicitly_clear_queue_selection(self):
        app = DailyApp.__new__(DailyApp)
        app.hdr_var, app.hdr_mapping_var, app.hdr_queued_var = Variable(), Variable(), Variable()
        calls=[]
        app._refresh_mask_status=lambda: calls.append(True)
        for hdr, mapping, expected in ((True,'Color-preserving',True), (True,'Legacy',False),
                                       (False,'Color-preserving',False)):
            app.hdr_var.set(hdr)
            app.hdr_mapping_var.set(mapping)
            app.hdr_queued_var.set(True)
            app._hdr_options_changed()
            self.assertIs(app.hdr_queued_var.get(),expected)
        self.assertEqual(len(calls),3)

    def test_loading_existing_preferences_preserves_legacy_mapping(self):
        app = DailyApp.__new__(DailyApp)
        loaded = []
        app._apply_settings_to_form = loaded.append
        old = dict(RECOMMENDED_SETTINGS, hdr=True)
        old.pop('hdr_mapping')
        for settings, expected in ((old, 'legacy'), (RECOMMENDED_SETTINGS, 'color-preserving'),
                                   ({}, 'color-preserving')):
            app.controller = SimpleNamespace(settings=settings)
            app._load_settings()
            self.assertEqual(loaded[-1]['hdr_mapping'], expected)

    def test_poll_displays_reported_hdr_status_and_legacy_sdr(self):
        app = DailyApp.__new__(DailyApp)
        app._last_state = 'running'
        app._closing = False
        app.root = SimpleNamespace(after=lambda *args: None)
        snapshots = []
        app._set_status = lambda **kwargs: snapshots.append(kwargs)
        for extra, expected in (({}, 'SDR'), ({'hdr_status': 'HDR FP16'}, 'HDR FP16')):
            app.controller = SimpleNamespace(poll=lambda: dict(
                state='running', detail='Active', geometry='1280x720 → 2560x1440', **extra))
            app._poll_controller()
            self.assertEqual(snapshots[-1]['geometry'], f'1280x720 → 2560x1440 · {expected}')

    def test_hdr_control_disabled_while_busy_or_closing(self):
        app = DailyApp.__new__(DailyApp)
        states = {}
        for name in ('target_combo', 'mode_combo', 'refresh_button', 'save_button',
                     'restore_button', 'hdr_check', 'hdr_mapping_combo', 'hdr_queued_check', 'mask_check', 'mask_combo',
                     'edit_mask_button', 'start_button', 'stop_button', 'open_run_button'):
            setattr(app, name, SimpleNamespace(configure=lambda name=name, **kwargs: states.update({name: kwargs['state']})))
        for name in ('nr_height_frame', 'flow_width_frame', 'flow_grid_frame', 'flow_preset_frame'):
            setattr(app, name, SimpleNamespace(winfo_children=lambda: []))
        app.mode_var = Variable()
        app.hdr_var = Variable()
        app.hdr_mapping_var = Variable()
        app.hdr_mapping_var.set('Color-preserving')
        app.target_var = Variable()
        app.target_by_display = {}
        app._mask_ready = True
        app._run_path = None
        app._last_state = 'idle'
        for busy, closing, hdr, expected, mapping_expected in (
                (False, False, False, 'normal', 'disabled'),
                (False, False, True, 'normal', 'readonly'),
                (True, False, True, 'disabled', 'disabled'),
                (False, True, True, 'disabled', 'disabled')):
            app._controller_busy = lambda: busy
            app._closing = closing
            app.hdr_var.set(hdr)
            app._sync_controls()
            self.assertEqual(states['hdr_check'], expected)
            self.assertEqual(states['hdr_mapping_combo'], mapping_expected)
            self.assertEqual(states['hdr_queued_check'], 'normal' if mapping_expected=='readonly' else 'disabled')
        app._controller_busy=lambda: False
        app._closing=False
        app.hdr_mapping_var.set('Legacy')
        app._sync_controls()
        self.assertEqual(states['hdr_queued_check'],'disabled')

    def test_new_list_requires_explicit_selection_and_shows_executable(self):
        app = DailyApp.__new__(DailyApp)
        app.target_var = Variable()
        app.target_by_display = {}
        app.target_combo = SimpleNamespace(configure=lambda **kwargs: None)
        app.controller = SimpleNamespace(list_targets=lambda: [dict(hwnd=1, pid=2, created=3,
            title='Document', exe=r'C:\Apps\editor.exe', width=960, height=640)], busy=False)
        app._refresh_mask_status = lambda: None
        app.refresh_targets()
        self.assertEqual(app.target_var.get(), '')
        self.assertIn('editor.exe', next(iter(app.target_by_display)))

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
                self.assertIn('selected window changed', app.status_detail_var.value)

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
            detail='The selected application window closed.', end_reason='target_closed'))
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
