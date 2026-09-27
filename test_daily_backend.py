import json
from pathlib import Path
import tempfile
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from daily_backend import DEFAULTS, DailyController, atomic_json, validated, migrate_settings


class DailyTests(unittest.TestCase):
    def test_chain_cold_start_defers_target_discovery(self):
        c = DailyController.__new__(DailyController)
        c.root, c.win, c.process, c.chain = Path('/isolated'), Mock(), None, None
        c._current_target = Mock(side_effect=AssertionError('No existing target'))
        chain = SimpleNamespace(start=Mock())
        with patch.dict('sys.modules', {'chain_controller': SimpleNamespace(ChainController=lambda *args: chain)}):
            c.start_chiaki_chain()
        c._current_target.assert_not_called()
        chain.start.assert_called_once_with(None)

    def test_chain_dispatch_routes_status_stop_and_blocks_preferences(self):
        c = DailyController.__new__(DailyController)
        c.root, c.win, c.process, c.chain = Path('/isolated'), Mock(), None, None
        target = dict(hwnd=1)
        c._current_target = Mock(return_value=target)
        chain = SimpleNamespace(busy=True, start=Mock(), stop=Mock(), poll=Mock(return_value={'state': 'running'}))
        factory = Mock(return_value=chain)
        with patch.dict('sys.modules', {'chain_controller': SimpleNamespace(ChainController=factory)}):
            c.start_chiaki_chain(target)
        factory.assert_called_once_with(c.root, c.win)
        chain.start.assert_called_once_with(target)
        self.assertTrue(c.busy)
        self.assertEqual(c.poll(), {'state': 'running', 'chain': True})
        with self.assertRaisesRegex(RuntimeError, 'Stop the current session'):
            c.save_settings(DEFAULTS)
        with self.assertRaisesRegex(RuntimeError, 'already owns'):
            c.start(target, DEFAULTS)
        c.stop()
        chain.stop.assert_called_once_with()

    def test_temporary_60fps_launch_preserves_saved_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            c = DailyController.__new__(DailyController)
            c.root = Path(folder)/'isolated'
            c.root.mkdir()
            c.preference_file = c.root/'daily-settings.json'
            c.settings = dict(DEFAULTS)
            atomic_json(c.preference_file, c.settings)
            original = c.preference_file.read_bytes()
            c.process = None
            c.chain = SimpleNamespace(busy=False)
            target = dict(hwnd=123, pid=456, created=789, title='Chiaki', width=1920, height=1080)
            c._current_target = lambda _: target
            c.win = SimpleNamespace(identity=lambda _: ('python', 10), u=SimpleNamespace(SetForegroundWindow=Mock(return_value=True)))
            with patch('daily_backend.subprocess.Popen') as launch:
                c.start(target, dict(DEFAULTS, nr_height=1080), persist=False, fps=60, panel_owner=(50, 60))
            args = launch.call_args.args[0]
            self.assertEqual(args[args.index('--fps')+1], '60')
            self.assertEqual(args[args.index('--height')+1], '1080')
            self.assertEqual(args[args.index('--panel-pid')+1], '50')
            self.assertEqual(args[args.index('--panel-created')+1], '60')
            self.assertEqual(c.preference_file.read_bytes(), original)
            self.assertEqual(c.settings, DEFAULTS)
            self.assertIsNone(c.chain)

    def test_launch_rejects_invalid_fps_before_side_effects(self):
        c = DailyController.__new__(DailyController)
        c.process = None
        for fps in (True, 60.0, 30, 240):
            with self.subTest(fps=fps), self.assertRaisesRegex(ValueError, 'FPS'):
                c.start({}, DEFAULTS, fps=fps)
        for owner in ((1,), (1, 0), (True, 2), (1, 2, 3), '1,2'):
            with self.subTest(owner=owner), self.assertRaisesRegex(ValueError, 'Panel owner'):
                c.start({}, DEFAULTS, panel_owner=owner)

    def test_queued_preference_migration_preserves_choices_and_backs_up(self):
        old = dict(DEFAULTS, hdr=True, hdr_mapping='legacy', nr_height=1080, mode='guard')
        old.pop('hdr_queued')
        expected = dict(old, hdr_queued=False)
        self.assertEqual(migrate_settings(old), expected)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            atomic_json(root/'daily-settings.json', old)
            with patch.dict('sys.modules', {'gfn_core.windows':SimpleNamespace(Win32=lambda: Mock())}), \
                 patch.object(sys, 'path', list(sys.path)):
                c = DailyController(root)
            self.assertEqual(c.settings, expected)
            self.assertEqual(json.loads((root/'daily-settings-before-hdr-queued.json').read_text()), old)
            self.assertEqual(json.loads((root/'daily-settings.json').read_text()), expected)

    def test_queued_preference_requires_boolean_and_hdr_color_mapping(self):
        for change in ({'hdr_queued':1}, {'hdr_queued':'true'}, {'hdr_queued':None},
                       {'hdr_queued':True}, {'hdr_queued':True,'hdr':True,'hdr_mapping':'legacy'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validated(dict(DEFAULTS, **change))
        self.assertFalse(DEFAULTS['hdr_queued'])
        self.assertTrue(validated(dict(DEFAULTS, hdr=True, hdr_queued=True))['hdr_queued'])

    def test_queued_launch_preflights_and_passes_both_flags(self):
        for queued in (False, True):
            with self.subTest(queued=queued), tempfile.TemporaryDirectory() as folder:
                c = DailyController.__new__(DailyController)
                c.root = Path(folder)/'isolated'
                c.root.mkdir()
                c.preference_file = c.root/'daily-settings.json'
                c.process = None
                target = dict(hwnd=123, pid=456, created=789, title='Replay', width=2560, height=1440)
                c._current_target = lambda _: target
                c.win = SimpleNamespace(identity=lambda _: ('python', 10), u=SimpleNamespace(SetForegroundWindow=Mock(return_value=True)))
                with patch('hdr_support.require_hdr_display') as preflight, patch('daily_backend.subprocess.Popen') as launch:
                    c.start(target, dict(DEFAULTS, hdr=True, hdr_queued=queued))
                preflight.assert_called_once_with(c.root, 123, 'color-preserving', queued=queued, capture_queued=queued)
                args = launch.call_args.args[0]
                self.assertIn('--hdr', args)
                self.assertEqual('--queued-hdr' in args, queued)
                self.assertEqual('--capture-queued-hdr' in args, queued)
                self.assertEqual(c.settings['hdr_queued'], queued)
                self.assertEqual(args[args.index('--height')+1], '720')
                self.assertEqual(args[args.index('--fps')+1], '120')

    def test_poll_identifies_combined_capture_queue_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            c = DailyController.__new__(DailyController)
            c.run = Path(folder)
            atomic_json(c.run/'manifest.json', dict(hdr=True, hdr_mapping='color-preserving', hdr_capture_queued=True))
            c.process = None
            c.metrics = {}
            c.launch_log = None
            c.state, c.detail = 'stopped', 'Done'
            self.assertEqual(c.poll()['hdr_status'], 'HDR stopped / color-preserving / queued HDR + capture')

    def test_lists_general_application_targets(self):
        from application_windows import ApplicationTarget
        c = DailyController.__new__(DailyController)
        c.win = SimpleNamespace(rect=lambda _: (10, 20, 960, 640))
        target = ApplicationTarget(1, 2, r'C:\Apps\editor.exe', 3, 'Document')
        with patch('daily_backend.enumerate_application_windows', return_value=[target]):
            self.assertEqual(c.list_targets(), [dict(target.to_dict(), width=960, height=640)])

    def test_changed_executable_is_rejected(self):
        c = DailyController.__new__(DailyController)
        target = dict(hwnd=1, pid=2, created=3, title='Document', exe='editor.exe')
        c.list_targets = lambda: [dict(target, exe='other.exe')]
        with self.assertRaisesRegex(RuntimeError, 'selected window changed'):
            c._current_target(target)

    def test_preview_is_discarded_if_foreground_changes_during_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            c = DailyController.__new__(DailyController)
            c.root = Path(folder)
            c.process = None
            target = dict(hwnd=1, width=2560, height=1440)
            foreground = [1]
            c._current_target = lambda value: target
            c.win = SimpleNamespace(rect=lambda hwnd: (0, 0, 2560, 1440),
                u=SimpleNamespace(SetForegroundWindow=Mock(), GetForegroundWindow=lambda: foreground[0]))
            def capture(*args):
                foreground[0] = 2
                return b'private pixels must not reach the editor'
            with patch('window_preview.capture_rectangle', side_effect=capture), patch('time.sleep'):
                with self.assertRaisesRegex(RuntimeError, 'preview discarded'):
                    c.capture_target(target)

    def test_mask_status_empty_profile_blocks_only_enabled_mask(self):
        c = DailyController.__new__(DailyController)
        c.load_mask_profile = lambda target: None
        target = dict(title='Game', width=2560, height=1440)
        self.assertTrue(c.mask_status(target, DEFAULTS)['usable'])
        self.assertFalse(c.mask_status(target, dict(DEFAULTS, mode='guard'))['usable'])
        c.load_mask_profile = lambda target: dict(rectangles=[[10, 20, 30, 40]])
        status = c.mask_status(target, dict(DEFAULTS, mode='guard'))
        self.assertTrue(status['usable'])
        self.assertIn('1 saved region', status['detail'])

    def test_bad_mask_does_not_block_unmasked_nr(self):
        c = DailyController.__new__(DailyController)
        def failure(target):
            raise ValueError('Mask profile schema is invalid')
        c.load_mask_profile = failure
        target = dict(title='Game', width=2560, height=1440)
        self.assertTrue(c.mask_status(target, DEFAULTS)['usable'])
        self.assertFalse(c.mask_status(target, dict(DEFAULTS, mode='guard'))['usable'])
        self.assertTrue(c.mask_status(target, dict(DEFAULTS, mode='bypass'))['usable'])

    def test_changed_game_title_requires_refresh(self):
        c = DailyController.__new__(DailyController)
        target = dict(hwnd=1, pid=2, created=3, title='Game A')
        c.list_targets = lambda: [dict(target, title='Game B')]
        c.win = SimpleNamespace(u=SimpleNamespace(IsIconic=lambda hwnd: False))
        with self.assertRaisesRegex(RuntimeError, 'selected window changed'):
            c._current_target(target)

    def test_changed_game_size_requires_refresh(self):
        c = DailyController.__new__(DailyController)
        target = dict(hwnd=1, pid=2, created=3, title='Game A', width=2560, height=1440)
        c.list_targets = lambda: [dict(target, width=1920, height=1080)]
        c.win = SimpleNamespace(u=SimpleNamespace(IsIconic=lambda hwnd: False))
        with self.assertRaisesRegex(RuntimeError, 'window size changed'):
            c._current_target(target)

    def test_optional_mask_migration_preserves_processing(self):
        old = dict(DEFAULTS, mode='guard', nr_height=900)
        old.pop('mask_profile')
        new = migrate_settings(old)
        self.assertEqual(new['mode'], 'nr')
        self.assertEqual(new['nr_height'], 900)
        self.assertEqual(new['mask_profile'], 'cyberpunk')
        self.assertEqual(migrate_settings(dict(DEFAULTS, mode='guard')), dict(DEFAULTS, mode='guard'))

    def test_preferences_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'settings.json'
            atomic_json(path, DEFAULTS)
            self.assertEqual(validated(json.loads(path.read_text())), DEFAULTS)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_preferences_reject_unknown_and_invalid(self):
        for change in ({'nr_height': 2160}, {'flow_grid': True}, {'flow_preset': 'unknown'}, {'command': 'anything'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validated(dict(DEFAULTS, **change))

    def test_nr1440_preference_roundtrip_preserves_default(self):
        self.assertEqual(DEFAULTS['nr_height'],720)
        settings=dict(DEFAULTS,nr_height=1440)
        self.assertEqual(validated(settings),settings)
        self.assertEqual(migrate_settings(settings),settings)

    def controller(self, folder, pid=42):
        c = DailyController.__new__(DailyController)
        c.root = Path(folder)
        c.run = c.root/'runs'/'owned'
        (c.run/'logs').mkdir(parents=True)
        c.process = SimpleNamespace(pid=pid)
        c.stop_pending = True
        c.stop_sent = False
        c.owner_token = 'owned-session-token'
        atomic_json(c.root/'active.json', dict(run=str(c.run), pid=42, owner_token=c.owner_token))
        return c

    def test_stop_is_bound_to_child_and_own_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.controller(folder, pid=1000)  # Windows venv bootstrap PID differs.
            control = c.run/'logs'/'control.json'
            atomic_json(c.run/'active.json', dict(pid=42, token='test', control=str(control)))
            c._send_stop()
            self.assertEqual(json.loads(control.read_text())['action'], 'stop')
            self.assertTrue(c.stop_sent)

    def test_stop_rejects_foreign_process_or_path(self):
        for wrong_pid, wrong_path in ((True, False), (False, True)):
            with tempfile.TemporaryDirectory() as folder:
                c = self.controller(folder)
                control = c.root/'foreign.json' if wrong_path else c.run/'logs'/'control.json'
                atomic_json(c.run/'active.json', dict(pid=99 if wrong_pid else 42, token='test', control=str(control)))
                with self.assertRaises(RuntimeError):
                    c._send_stop()
                self.assertFalse(control.exists())

    def test_stop_rejects_another_ui_session(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.controller(folder)
            control = c.run/'logs'/'control.json'
            atomic_json(c.run/'active.json', dict(pid=42, token='test', control=str(control)))
            c.owner_token = 'foreign-session'
            with self.assertRaises(RuntimeError):
                c._send_stop()
            self.assertFalse(control.exists())

    def test_stop_waits_for_initialization(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.controller(folder)
            c._send_stop()
            self.assertFalse(c.stop_sent)

    def test_closed_target_reports_refresh_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            c = DailyController.__new__(DailyController)
            c.run = Path(folder)/'runs'/'owned'
            (c.run/'logs').mkdir(parents=True)
            atomic_json(c.run/'outcome.json', dict(exit_code=0, state='target_closed'))
            c.process = SimpleNamespace(poll=lambda: 0, returncode=0)
            c.metrics = {}
            c.launch_log = None
            c.state = 'running'
            c.detail = 'Processing'
            snapshot = c.poll()
            self.assertEqual(snapshot['state'], 'stopped')
            self.assertEqual(snapshot['end_reason'], 'target_closed')
            self.assertIn('Open an application and refresh', snapshot['detail'])


if __name__ == '__main__':
    unittest.main()
