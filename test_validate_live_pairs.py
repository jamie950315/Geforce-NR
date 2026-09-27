import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from validate_live_pairs import HGM1, validate


class LivePairValidationTests(unittest.TestCase):
    def fixture(self, root):
        pairs = root / 'live-pairs'
        pairs.mkdir()
        mask = root / 'mask.hgm'
        mask.write_bytes(struct.pack('<4I', HGM1, 1, 3, 1) + bytes([255, 0, 128]))
        (root / 'manifest.json').write_text(json.dumps(dict(mode='guard',
            live_pair=dict(performance_evidence=False), target=dict(hwnd=12),
            mask=dict(sha256=hashlib.sha256(mask.read_bytes()).hexdigest()))))
        for index in (30, 60, 90):
            meta = dict(schema=1, width=3, height=1, hwnd=12, frame_index=index,
                capture_serial=index, source_qpc=index, copy_submission_fence=index,
                capture_kind='wgc', source_fresh=True, nvofa_used=True, hud_guard=True,
                same_command_list=True)
            for key, values in [('source', [100] * 12), ('pre_hud', [0] * 12),
                                ('post_hud', [100] * 4 + [0] * 4 + [50] * 4)]:
                meta[key] = f'{index}-{key}.rgba'
                (pairs / meta[key]).write_bytes(bytes(values))
            (pairs / f'pair-{index}.json').write_text(json.dumps(meta))
        return pairs, mask

    def test_valid_composition(self):
        with tempfile.TemporaryDirectory() as folder:
            pairs, mask = self.fixture(Path(folder))
            self.assertTrue(validate(pairs, mask)['passed'])

    def test_reused_files_cannot_be_three_distinct_captures(self):
        with tempfile.TemporaryDirectory() as folder:
            pairs, mask = self.fixture(Path(folder))
            path = pairs / 'pair-60.json'
            meta = json.loads(path.read_text())
            meta['source'] = '30-source.rgba'
            path.write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError, 'unique'):
                validate(pairs, mask)

    def test_metadata_requires_exact_types_and_positive_fences(self):
        for field, value in [('schema', True), ('nvofa_used', 1), ('width', '3'),
                             ('frame_index', 30.5), ('copy_submission_fence', -1)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                pairs, mask = self.fixture(Path(folder))
                path = pairs / 'pair-30.json'
                meta = json.loads(path.read_text())
                meta[field] = value
                path.write_text(json.dumps(meta))
                with self.assertRaises(ValueError):
                    validate(pairs, mask)


if __name__ == '__main__':
    unittest.main()
