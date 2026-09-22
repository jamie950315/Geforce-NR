import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from mask_profiles import build_mask, load_profile, profile_key, save_profile, validate_mask


class MaskProfileTests(unittest.TestCase):
    def target(self, **changes):
        target = dict(title="Cyberpunk 2077", width=64, height=64, pid=10, hwnd=20)
        target.update(changes)
        return target

    def pixels(self, path):
        return path.read_bytes()[16:]

    def test_profile_key_ignores_process_identity_but_uses_title_and_geometry(self):
        target = self.target()
        restarted = dict(target, pid=999, hwnd=888)
        normalized = dict(target, title="  CYBERPUNK   2077  ")
        self.assertEqual(profile_key(target), profile_key(restarted))
        self.assertEqual(profile_key(target), profile_key(normalized))
        self.assertNotEqual(profile_key(target), profile_key(dict(target, title="Another Game")))
        self.assertNotEqual(profile_key(target), profile_key(dict(target, width=65)))

    def test_profile_roundtrip_and_content_addressed_mask_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.target()
            expected = save_profile(root, target, [[10, 10, 20, 20]])
            self.assertEqual(load_profile(root, target), expected)
            first = build_mask(root, target)
            before = first.stat().st_mtime_ns
            second = build_mask(root, target)
            self.assertEqual(first, second)
            self.assertEqual(first.stem, hashlib.sha256(first.read_bytes()).hexdigest())
            self.assertEqual(first.stat().st_mtime_ns, before)
            validate_mask(first, 64, 64)
            self.assertEqual(list((root / "masks").glob("*.tmp")), [])

    def test_core_and_four_pixel_feather(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            save_profile(root, self.target(), [[10, 10, 20, 20]])
            pixels = self.pixels(build_mask(root, self.target()))
            at = lambda x, y: pixels[y * 64 + x]
            self.assertEqual(at(10, 10), 255)
            self.assertEqual([at(10 - distance, 15) for distance in range(1, 6)],
                             [204, 153, 102, 51, 0])
            self.assertEqual(at(6, 6), 51)
            self.assertEqual(at(5, 5), 0)

    def test_overlap_uses_max_and_edge_feather_is_clipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.target()
            save_profile(root, target, [[0, 0, 3, 3], [7, 1, 10, 4]])
            pixels = self.pixels(build_mask(root, target))
            at = lambda x, y: pixels[y * 64 + x]
            self.assertEqual(at(0, 0), 255)
            self.assertEqual(at(3, 1), 204)
            self.assertEqual(at(4, 1), 153)
            self.assertEqual(at(6, 1), 204)  # The second rectangle's feather wins.
            self.assertEqual(at(7, 1), 255)

    def test_empty_profile_is_saved_but_cannot_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.target()
            self.assertEqual(save_profile(root, target, [])["rectangles"], [])
            with self.assertRaisesRegex(ValueError, "at least one"):
                build_mask(root, target)

    def test_invalid_targets_and_rectangles_are_rejected(self):
        invalid_targets = [
            self.target(width=63), self.target(height=4330), self.target(width=True),
            self.target(title="   "),
        ]
        invalid_rectangles = [
            "not-a-list", [[0, 0, 1, 2]], [[0, 0, 2, 1]], [[-1, 0, 2, 2]],
            [[0, 0, 65, 2]], [[False, 0, 2, 2]], [[0, 0, 2]], [[0, 0, 2, 2]] * 65,
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for target in invalid_targets:
                with self.subTest(target=target), self.assertRaises(ValueError):
                    save_profile(root, target, [])
            for rectangles in invalid_rectangles:
                with self.subTest(rectangles=rectangles), self.assertRaises(ValueError):
                    save_profile(root, self.target(), rectangles)

    def test_malformed_or_wrong_identity_profile_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.target()
            save_profile(root, target, [[1, 1, 3, 3]])
            profile = root / "masks" / f"{profile_key(target)}.json"
            value = json.loads(profile.read_text())
            value["title"] = "another game"
            profile.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "title"):
                load_profile(root, target)
            profile.write_text("{")
            with self.assertRaises(ValueError):
                load_profile(root, target)

    def test_validate_mask_rejects_header_geometry_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.hgm"
            cases = [
                struct.pack("<4I", 0, 1, 64, 64) + bytes(64 * 64),
                struct.pack("<4I", 0x314D4748, 2, 64, 64) + bytes(64 * 64),
                struct.pack("<4I", 0x314D4748, 1, 65, 64) + bytes(64 * 64),
                struct.pack("<4I", 0x314D4748, 1, 64, 64) + bytes(64 * 64 - 1),
            ]
            for payload in cases:
                path.write_bytes(payload)
                with self.subTest(header=payload[:16]), self.assertRaises(ValueError):
                    validate_mask(path, 64, 64)


if __name__ == "__main__":
    unittest.main()
