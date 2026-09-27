from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from daily_ui import DailyApp, FLOW_HEIGHT_LABELS, NR_HEIGHTS, RECOMMENDED_SETTINGS, fit_window_bounds


class Variable:
    def __init__(self):
        self.value = ''

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class CloseRecoveryTests(unittest.TestCase):
    def test_chiaki_chain_requires_unique_or_explicit_chiaki(self):
        app = DailyApp.__new__(DailyApp)
        app.target_var = Variable()
        chiaki = dict(hwnd=1, exe=r'C:\Apps\chiaki.exe')
        second = dict(hwnd=2, exe=r'C:\Apps\chiaki-ng.exe')
        other = dict(hwnd=3, exe=r'C:\Apps\editor.exe')
        app.targets = [chiaki, other]
        app.target_by_display = {'first': chiaki, 'second': second, 'other': other}
        self.assertEqual(app._chiaki_target(), chiaki)
        app.targets.append(second)
        self.assertIsNone(app._chiaki_target())
        app.target_var.set('second')
        self.assertEqual(app._chiaki_target(), second)
        app.target_var.set('other')
        self.assertIsNone(app._chiaki_target())

    def test_chiaki_chain_dispatch_does_not_use_daily_preferences(self):
        app = DailyApp.__new__(DailyApp)
        target = dict(hwnd=1, exe='chiaki.exe')
        app._chiaki_target = lambda: target
        app.controller = SimpleNamespace(start_chiaki_chain=Mock())
        app._settings_from_form = Mock(side_effect=AssertionError('Must not read daily settings'))
        app.status_state_var, app.status_detail_var = Variable(), Variable()
        app._sync_controls = Mock()
        app.start_chiaki_chain()
        app.controller.start_chiaki_chain.assert_called_once_with(target)
        app._settings_from_form.assert_not_called()
        self.assertEqual(app._last_state, 'starting')

    def test_cold_start_enabled_without_chiaki_but_not_unrelated_selection(self):
        app = DailyApp.__new__(DailyApp)
        app.target_var = Variable()
        other = dict(hwnd=1, exe='editor.exe')
        app.targets, app.target_by_display = [other], {'other': other}
        self.assertTrue(app._chiaki_can_start())
        self.assertIsNone(app._chiaki_target())
        app.controller = SimpleNamespace(start_chiaki_chain=Mock())
        app.status_state_var, app.status_detail_var = Variable(), Variable()
        app._sync_controls = Mock()
        app.start_chiaki_chain()
        app.controller.start_chiaki_chain.assert_called_once_with(None)
        app.target_var.set('other')
        self.assertFalse(app._chiaki_can_start())

    def test_same_installation_home_and_stream_can_seed_backend_resolution(self):
        app = DailyApp.__new__(DailyApp)
        app.target_var = Variable()
        app.target_by_display = {}
        home = dict(hwnd=1, exe=r'C:\Apps\chiaki.exe')
        stream = dict(hwnd=2, exe=r'c:\apps\CHIAKI.EXE')
        app.targets = [home, stream]
        self.assertEqual(app._chiaki_target(), home)
        app.targets.append(dict(hwnd=3, exe=r'C:\Other\chiaki.exe'))
        self.assertIsNone(app._chiaki_target())
        self.assertFalse(app._chiaki_can_start())

    def test_finished_chain_refreshes_restored_geometry_once(self):
        app = DailyApp.__new__(DailyApp)
        app._last_state, app._closing = 'running', False
        app.root = SimpleNamespace(after=Mock())
        app.controller = SimpleNamespace(busy=False, poll=lambda: dict(
            chain=True, state='stopped', detail='Original settings restored.', end_reason='foreground_changed'))
        app._set_status = lambda **kwargs: setattr(app, '_last_state', kwargs['state'])
        app.status_detail_var = Variable()
        app.refresh_targets = Mock()
        app._poll_controller()
        app._poll_controller()
        app.refresh_targets.assert_called_once_with()
        self.assertEqual(app.status_detail_var.get(), 'Original settings restored.')

    def test_finished_chain_reselects_actual_stream_but_not_reused_identity(self):
        stream = dict(hwnd=2, pid=3, created=4, exe=r'C:\Apps\chiaki.exe', width=1920, height=1080)
        for restored, expected in ((dict(stream, width=2400, height=1350), 'stream'),
                                   (dict(stream, created=5), '')):
            with self.subTest(restored=restored):
                app = DailyApp.__new__(DailyApp)
                app._last_state, app._closing = 'running', False
                app.root = SimpleNamespace(after=Mock())
                app.controller = SimpleNamespace(busy=False, poll=lambda: dict(
                    chain=True, chain_target=stream, state='stopped', detail='Restored.'))
                app._set_status = lambda **kwargs: setattr(app, '_last_state', kwargs['state'])
                app.status_detail_var, app.target_var = Variable(), Variable()
                app.target_by_display = {'stream': restored}
                app.refresh_targets, app._refresh_mask_status = Mock(), Mock()
                app._poll_controller()
                self.assertEqual(app.target_var.get(), expected)
                self.assertEqual(app._refresh_mask_status.call_count, int(bool(expected)))

    def test_flow_height_labels_keep_width_values_and_selection(self):
        app = DailyApp.__new__(DailyApp)
        app.ttk = SimpleNamespace(Frame=Mock(), Radiobutton=Mock())
        variable = Variable()
        app._radio_row(None, 4, variable, tuple(FLOW_HEIGHT_LABELS), labels=FLOW_HEIGHT_LABELS)
        calls = app.ttk.Radiobutton.call_args_list
        self.assertEqual([(c.kwargs['text'], c.kwargs['value']) for c in calls],
                         [('180',320),('360',640),('540',960),('720',1280)])
        self.assertTrue(all(c.kwargs['variable'] is variable for c in calls))

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
        self.assertEqual(NR_HEIGHTS,(720,900,1080,1440))
        app._apply_settings_to_form(dict(RECOMMENDED_SETTINGS,nr_height=1440))
        self.assertEqual(app._settings_from_form()['nr_height'],1440)
        for width in FLOW_HEIGHT_LABELS:
            saved=dict(RECOMMENDED_SETTINGS, flow_width=width)
            app._apply_settings_to_form(saved)
            self.assertEqual(app._settings_from_form(),saved)

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

    def test_enabling_hdr_selects_color_preserving_and_queued(self):
        app = DailyApp.__new__(DailyApp)
        app.hdr_var, app.hdr_mapping_var, app.hdr_queued_var = Variable(), Variable(), Variable()
        calls=[]
        app._refresh_mask_status=lambda: calls.append(True)
        app.hdr_mapping_var.set('Legacy')
        app.hdr_queued_var.set(False)
        app.hdr_var.set(True)
        app._hdr_toggled()
        self.assertEqual(app.hdr_mapping_var.get(),'Color-preserving')
        self.assertIs(app.hdr_queued_var.get(),True)
        app.hdr_var.set(False)
        app._hdr_toggled()
        self.assertIs(app.hdr_queued_var.get(),False)
        self.assertEqual(app.hdr_mapping_var.get(),'Color-preserving')
        self.assertEqual(len(calls),2)

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
                     'edit_mask_button', 'start_button', 'chain_button', 'stop_button', 'open_run_button'):
            setattr(app, name, SimpleNamespace(configure=lambda name=name, **kwargs: states.update({name: kwargs['state']})))
        for name in ('nr_height_frame', 'flow_width_frame', 'flow_grid_frame', 'flow_preset_frame'):
            setattr(app, name, SimpleNamespace(winfo_children=lambda: []))
        app.mode_var = Variable()
        app.hdr_var = Variable()
        app.hdr_mapping_var = Variable()
        app.hdr_mapping_var.set('Color-preserving')
        app.target_var = Variable()
        app.target_by_display = {}
        app.targets = [dict(exe='chiaki.exe')]
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
            self.assertEqual(states['chain_button'], 'disabled' if busy or closing else 'normal')
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
