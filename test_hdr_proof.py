"""Focused integrity checks for the bounded native HDR proof validator."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
    import numpy as np
except ImportError:
    np = None

from validate_hdr_proof import validate


@unittest.skipIf(np is None, 'NumPy is required for FP16 proof validation')
class HdrProofTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name)
        self.proof = self.run/'hdr-proof'
        self.proof.mkdir()
        self.manifest = dict(hdr=True, hdr_proof=True, mode='bypass', mask=None,
                             target=dict(hwnd=123, pid=456))
        self.write_json(self.run/'manifest.json', self.manifest)

        source = np.empty((64, 64, 4), dtype='<f2')
        source[:] = [4.0, 0.5, -0.125, 1.0]
        proxy = np.empty((64, 64, 4), dtype='u1')
        proxy[:] = [220, 100, 0, 255]
        hashes = {}
        for name, values in (('source.fp16', source), ('output.fp16', source),
                             ('proxy-in.rgba', proxy), ('proxy-out.rgba', proxy)):
            data = values.tobytes()
            (self.proof/name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        self.meta = dict(width=64, height=64, white=1.0, bypass=True, fence=30,
                         capture_format=10, output_format=10, hwnd=123, pid=456,
                         generation=1, capture=30, source_qpc=10000,
                         manifest_sha256=hashlib.sha256((self.run/'manifest.json').read_bytes()).hexdigest(),
                         sha256=hashes, timing_evidence=False)
        self.write_json(self.proof/'proof.json', self.meta)

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_valid_bypass_preserves_hdr_and_signed_values_exactly(self):
        result = validate(self.run)
        self.assertTrue(result['valid'])
        self.assertTrue(result['bypass_exact'])
        self.assertFalse(result['timing_evidence'])
        self.assertEqual(result['source_above_sdr_white'], 64*64)
        self.assertEqual(result['max_error'], 0)
        self.assertEqual(result['hashes'], self.meta['sha256'])

    def test_changed_manifest_is_rejected(self):
        self.manifest['target']['pid'] = 789
        self.write_json(self.run/'manifest.json', self.manifest)
        with self.assertRaises(AssertionError):
            validate(self.run)

    def test_mapping_mismatch_is_rejected(self):
        self.meta['mapping'] = 'color-preserving'
        self.write_json(self.proof/'proof.json',self.meta)
        with self.assertRaises(AssertionError):
            validate(self.run)

    def test_color_mapping_checks_proxy_encoding_even_in_bypass(self):
        self.manifest['hdr_mapping'] = 'color-preserving'
        self.write_json(self.run/'manifest.json',self.manifest)
        self.meta.update(mapping='color-preserving',
            manifest_sha256=hashlib.sha256((self.run/'manifest.json').read_bytes()).hexdigest())
        self.write_json(self.proof/'proof.json',self.meta)
        # This fixture's arbitrary proxy matches the hashes but not the new
        # encoding function. Numerical HDR bypass equality alone is insufficient.
        with self.assertRaisesRegex(AssertionError,'proxy encoding mismatch'):
            validate(self.run)

    def test_changed_raw_file_is_rejected(self):
        # Alter only alpha in a proxy: numerical bypass checks cannot detect it,
        # so this explicitly exercises the byte-integrity contract.
        path = self.proof/'proxy-out.rgba'
        data = bytearray(path.read_bytes())
        data[3] = 254
        path.write_bytes(data)
        with self.assertRaisesRegex(AssertionError, 'HDR capture hash mismatch'):
            validate(self.run)

    def test_queued_nr_requires_one_retired_fence_marker(self):
        self.manifest.update(mode='nr', hdr_queued=True)
        self.write_json(self.run/'manifest.json', self.manifest)
        self.meta.update(bypass=False,
            manifest_sha256=hashlib.sha256((self.run/'manifest.json').read_bytes()).hexdigest())
        self.write_json(self.proof/'proof.json', self.meta)
        (self.run/'logs').mkdir()
        log = self.run/'logs'/'test.native.log'
        marker = '[hdr-tail] queued motion/NR retired at present fence 42\n'
        for text in ('', marker.replace('42', '0'), marker*2):
            log.write_text(text)
            with self.assertRaisesRegex(AssertionError, 'Queued HDR branch'):
                validate(self.run)
        log.write_text(marker)
        self.assertTrue(validate(self.run)['queued_tail_confirmed'])

    def test_capture_queue_requires_ordered_retired_fences(self):
        self.manifest['hdr_capture_queued'] = True
        self.write_json(self.run/'manifest.json', self.manifest)
        self.meta['manifest_sha256'] = hashlib.sha256((self.run/'manifest.json').read_bytes()).hexdigest()
        self.write_json(self.proof/'proof.json', self.meta)
        (self.run/'logs').mkdir()
        log = self.run/'logs'/'test.native.log'
        marker = '[capture-queue] swizzle=31 gray=32 retired; dedicated gray heap; D3D11 wait retained\n'
        for text in ('', marker.replace('31', '0'), marker.replace('32', '31'), marker*2):
            log.write_text(text)
            with self.assertRaisesRegex(AssertionError, 'Capture queue branch'):
                validate(self.run)
        log.write_text(marker)
        self.assertTrue(validate(self.run)['capture_queue_confirmed'])

    def test_invalid_capture_identity_is_rejected(self):
        for key in ('generation', 'capture', 'source_qpc', 'fence'):
            for value in (True, 0, -1, 1.0, '1', None):
                with self.subTest(key=key, value=value):
                    self.write_json(self.proof/'proof.json', dict(self.meta, **{key: value}))
                    with self.assertRaises(AssertionError):
                        validate(self.run)


if __name__ == '__main__':
    unittest.main()
