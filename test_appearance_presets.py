import unittest

from appearance_presets import resolve_appearance


class AppearancePresetTests(unittest.TestCase):
    def test_inherited_preserves_values_without_reusing_dictionary(self):
        original = dict(style=2, auto_mask=0, intensity=0.5, local_tone=0.4,
                        local_structure=0.95, skin_structure=2.4)
        resolved = resolve_appearance('inherited', original)
        self.assertEqual(resolved, original)
        self.assertIsNot(resolved, original)
        resolved['intensity'] = 0
        self.assertEqual(original['intensity'], 0.5)

    def test_clean_is_fixed_and_does_not_mutate_inherited_or_later_calls(self):
        original = dict(style=2, auto_mask=0, intensity=0.1, local_tone=2,
                        local_structure=0.95, skin_structure=2.4)
        before = dict(original)
        expected = dict(style=1, auto_mask=1, intensity=1.0, local_tone=0.25,
                        local_structure=0.0, skin_structure=0.0)
        resolved = resolve_appearance('clean', original)
        self.assertEqual(resolved, expected)
        self.assertEqual(original, before)
        resolved['local_structure'] = 1.0
        self.assertEqual(resolve_appearance('clean', original), expected)

    def test_invalid_preset_or_inherited_container_fails_explicitly(self):
        for preset in ('automatic', '', None, [], True):
            with self.subTest(preset=preset), self.assertRaisesRegex(ValueError, 'Unsupported appearance preset'):
                resolve_appearance(preset, {})
        for inherited in (None, [], 'appearance.json'):
            with self.subTest(inherited=inherited), self.assertRaisesRegex(ValueError, 'dictionary'):
                resolve_appearance('inherited', inherited)


if __name__ == '__main__':
    unittest.main()
