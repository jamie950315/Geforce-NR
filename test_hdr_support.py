import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from daily_backend import DEFAULTS, DailyController, migrate_settings, validated
from hdr_support import require_hdr_display, verify_hdr_build
from stage_hdr import patch_once


class HdrTests(unittest.TestCase):
    def test_existing_preferences_migrate_to_hdr_off_without_losing_mask_choice(self):
        old = dict(DEFAULTS, mode='guard', nr_height=900)
        old.pop('hdr')
        self.assertEqual(migrate_settings(old), dict(old, hdr=False))
        old.pop('mask_profile')
        self.assertEqual(migrate_settings(old), dict(DEFAULTS, mode='nr', nr_height=900, mask_profile='cyberpunk'))

    def test_hdr_is_strict_boolean(self):
        for value in (1, 'true', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validated(dict(DEFAULTS, hdr=value))

    def test_hdr_requires_attested_files(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                verify_hdr_build(folder)

    def test_queued_variant_rejects_legacy_mapping(self):
        with self.assertRaisesRegex(ValueError,'requires color-preserving'):
            verify_hdr_build('.',mapping='legacy',queued=True)
        with self.assertRaisesRegex(ValueError,'requires queued HDR'):
            verify_hdr_build('.',mapping='color-preserving',capture_queued=True)

    def probe(self, doc, returncode=0):
        with patch('hdr_support.verify_hdr_build', return_value=(Path('native-hdr'), {})), \
             patch('hdr_support.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(doc), returncode=returncode)):
            return require_hdr_display(Path('.'), 123)

    def test_hdr_disabled_or_unknown_is_not_sdr_fallback(self):
        with self.assertRaisesRegex(RuntimeError, 'Enable Windows HDR'):
            self.probe(dict(known=True, enabled=False, white=1))
        with self.assertRaisesRegex(RuntimeError, 'Could not verify'):
            self.probe(dict(known=False, enabled=True, white=1))
        for white in (0, float('nan'), True):
            with self.subTest(white=white), self.assertRaisesRegex(RuntimeError, 'Could not verify'):
                self.probe(dict(known=True, enabled=True, white=white))
        self.assertEqual(self.probe(dict(known=True, enabled=True, white=5))['white'], 5)

    def test_failed_hdr_preflight_does_not_save_preferences_or_launch(self):
        c = DailyController.__new__(DailyController)
        c.root = Path('.')
        c.process = None
        c._current_target = lambda _: dict(hwnd=123)
        with patch('hdr_support.require_hdr_display', side_effect=RuntimeError('HDR disabled')), \
             patch.object(c, 'save_settings') as save, patch('daily_backend.subprocess.Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'HDR disabled'):
                c.start({}, dict(DEFAULTS, hdr=True))
            save.assert_not_called()
            launch.assert_not_called()

    def test_patch_contract_rejects_missing_and_duplicate_anchors(self):
        for source in ('none', 'old old'):
            with self.assertRaisesRegex(RuntimeError, 'Ambiguous'):
                patch_once(source, 'old', 'new')


if __name__ == '__main__':
    unittest.main()
