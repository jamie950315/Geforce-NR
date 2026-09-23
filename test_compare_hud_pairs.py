import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compare_hud_pairs import main


class ComparisonTests(unittest.TestCase):
    def test_empty_capture_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as folder, patch('sys.argv', ['compare_hud_pairs.py', folder]):
            with self.assertRaisesRegex(ValueError, 'three actual captured pairs'):
                main()

    def test_exact_known_pixel_difference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pairs = root/'live-pairs'
            pairs.mkdir()
            (root/'manifest.json').write_text(json.dumps(dict(settings={}, integrity=dict(worker_sha256='test'))))
            for index in (30, 60, 90):
                meta = dict(schema=1, width=1, height=1, hwnd=12,
                            frame_index=index, capture_serial=index, source_qpc=index,
                            copy_submission_fence=index, capture_kind='wgc',
                            same_command_list=True, source_fresh=True, nvofa_used=True,
                            hud_guard=True)
                for key, pixel in [('source', bytes([100, 200, 50, 255])),
                                   ('pre_hud', bytes([90, 180, 30, 255])),
                                   ('post_hud', bytes([100, 200, 50, 255]))]:
                    name = f'{index}-{key}.rgba'
                    (pairs/name).write_bytes(pixel)
                    meta[key] = name
                (pairs/f'pair-{index}.json').write_text(json.dumps(meta))
            regions = root/'regions.json'
            regions.write_text(json.dumps(dict(pixel=[0, 0, 1, 1])))
            with patch('sys.argv', ['compare_hud_pairs.py', folder, '--regions', str(regions), '--all-frames']):
                main()
            result = json.loads((root/'hud-comparison/metrics.json').read_text())
            self.assertEqual(result['sample_count'], 3)
            self.assertEqual(len(list((root/'hud-comparison/frames').glob('*.png'))), 9)
            self.assertAlmostEqual(result['rows'][0]['roi_rgb_mae'], 50/3)
            self.assertEqual(result['rows'][0]['guard_roi_max'], 0)
            regions.write_text(json.dumps({'../escape': [0, 0, 1, 1]}))
            with patch('sys.argv', ['compare_hud_pairs.py', folder, '--regions', str(regions)]):
                with self.assertRaisesRegex(ValueError, 'Unsafe region output name'):
                    main()

    def test_reused_capture_identity_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pairs = root/'live-pairs'
            pairs.mkdir()
            for index in (30, 60, 90):
                meta = dict(schema=1, width=1, height=1, hwnd=12, frame_index=index,
                            capture_serial=30, source_qpc=index, copy_submission_fence=index,
                            capture_kind='wgc', same_command_list=True, source_fresh=True,
                            nvofa_used=True, hud_guard=True)
                for key in ('source', 'pre_hud', 'post_hud'):
                    name = f'{index}-{key}.rgba'
                    (pairs/name).write_bytes(bytes([0, 0, 0, 255]))
                    meta[key] = name
                (pairs/f'pair-{index}.json').write_text(json.dumps(meta))
            with patch('sys.argv', ['compare_hud_pairs.py', folder]):
                with self.assertRaisesRegex(ValueError, 'capture_serial must increase'):
                    main()
            self.assertFalse((root/'hud-comparison').exists())


if __name__ == '__main__':
    unittest.main()
