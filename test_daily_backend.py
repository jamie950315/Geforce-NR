import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from daily_backend import DEFAULTS, DailyController, atomic_json, validated, migrate_settings


class DailyTests(unittest.TestCase):
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
        with self.assertRaisesRegex(RuntimeError, 'selected game changed'):
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
        for change in ({'nr_height': 1440}, {'flow_grid': True}, {'flow_preset': 'unknown'}, {'command': 'anything'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validated(dict(DEFAULTS, **change))

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


if __name__ == '__main__':
    unittest.main()
