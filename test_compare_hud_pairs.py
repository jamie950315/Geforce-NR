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
                meta = dict(width=1, height=1, frame_index=index, capture_kind='wgc',
                            same_command_list=True, source_fresh=True, nvofa_used=True)
                for key, pixel in [('source', bytes([100, 200, 50, 255])),
                                   ('pre_hud', bytes([90, 180, 30, 255])),
                                   ('post_hud', bytes([100, 200, 50, 255]))]:
                    name = f'{index}-{key}.rgba'
                    (pairs/name).write_bytes(pixel)
                    meta[key] = name
                (pairs/f'pair-{index}.json').write_text(json.dumps(meta))
            regions = root/'regions.json'
            regions.write_text(json.dumps(dict(pixel=[0, 0, 1, 1])))
            with patch('sys.argv', ['compare_hud_pairs.py', folder, '--regions', str(regions)]):
                main()
            result = json.loads((root/'hud-comparison/metrics.json').read_text())
            self.assertEqual(result['sample_count'], 3)
            self.assertAlmostEqual(result['rows'][0]['roi_rgb_mae'], 50/3)
            self.assertEqual(result['rows'][0]['guard_roi_max'], 0)
            regions.write_text(json.dumps({'../escape': [0, 0, 1, 1]}))
            with patch('sys.argv', ['compare_hud_pairs.py', folder, '--regions', str(regions)]):
                with self.assertRaisesRegex(ValueError, 'Unsafe region output name'):
                    main()


if __name__ == '__main__':
    unittest.main()
