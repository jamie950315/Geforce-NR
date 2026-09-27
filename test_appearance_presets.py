import unittest
import json

from appearance_presets import (APPEARANCE_LABELS, SLIDER_RANGES, appearance_cli_args,
    parse_appearance_json, preset_config, resolve_appearance, strict_json_loads,
    validate_appearance_config)


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

    def test_all_named_presets_match_verified_profiles(self):
        expected = {'clean': (1, 1, 1, .25, 0, 0), 'faithful': (0, 1, .7, .25, .75, -1),
                    'natural': (1, 1, 1, .5, 1, -1), 'strong': (2, 1, 1, .9, 1.5, 1),
                    'extreme': (2, 1, 1, 1.5, 1.5, 1.5)}
        keys = ('style', 'auto_mask', 'intensity', 'local_tone', 'local_structure', 'skin_structure')
        for name, values in expected.items():
            with self.subTest(name=name):
                config = preset_config(name)
                self.assertEqual(config['values'], dict(zip(keys, values)))
                self.assertEqual(validate_appearance_config(config), config)
                self.assertEqual(resolve_appearance(name, {}), config['values'])
        self.assertEqual(list(APPEARANCE_LABELS.values()), [*expected, 'custom'])

    def test_custom_preserves_style_and_masks_and_returns_independent_copy(self):
        values = dict(style=2, auto_mask=0, intensity=.32, local_tone=.45,
                      local_structure=.61, skin_structure=2.45)
        config = dict(preset='custom', values=values)
        normalized = validate_appearance_config(config)
        self.assertEqual(normalized, config)
        normalized['values']['intensity'] = 0
        self.assertEqual(values['intensity'], .32)
        resolved = resolve_appearance('custom', {}, values)
        resolved['style'] = 0
        self.assertEqual(values['style'], 2)
        args = appearance_cli_args(config)
        self.assertEqual(args[:2], ['--appearance-preset', 'custom'])
        self.assertEqual(parse_appearance_json(args[3]), values)
        self.assertNotIn(' ', args[3])

    def test_named_values_cannot_silently_become_custom(self):
        config = preset_config('clean')
        config['values']['intensity'] = .5
        with self.assertRaisesRegex(ValueError, 'select Custom'):
            validate_appearance_config(config)
        with self.assertRaisesRegex(ValueError, 'require the custom'):
            resolve_appearance('clean', {}, config['values'])

    def test_exact_schema_types_finite_values_and_ranges(self):
        valid = preset_config('custom')
        for field, bad in [('style', True), ('style', 1.0), ('style', 3), ('auto_mask', False),
                           ('auto_mask', 2), ('intensity', True), ('intensity', '0.5'),
                           ('intensity', float('nan')), ('local_tone', float('inf')),
                           ('skin_structure', float('-inf'))]:
            config = dict(preset='custom', values=dict(valid['values'], **{field: bad}))
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                validate_appearance_config(config)
        for field, (minimum, maximum) in SLIDER_RANGES.items():
            for number in (minimum, maximum):
                validate_appearance_config(dict(preset='custom', values=dict(valid['values'], **{field: number})))
            for number in (minimum-.01, maximum+.01):
                with self.subTest(field=field, number=number), self.assertRaises(ValueError):
                    validate_appearance_config(dict(preset='custom', values=dict(valid['values'], **{field: number})))
        for config in ({}, dict(valid, extra=1), dict(preset='custom', values={}),
                       dict(preset='custom', values=dict(valid['values'], PresetHint='fast'))):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_appearance_config(config)

    def test_json_rejects_duplicates_nonfinite_unknown_and_missing(self):
        text = json.dumps(preset_config('custom')['values'])
        bad = [text[:-1]+',"intensity":0.2}', text.replace('1.0', 'NaN'),
               text.replace('1.0', 'Infinity'), text.replace('1.0', '1e999'),
               '{"intensity":0.5}', text[:-1]+',"PresetHint":"fast"}']
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_appearance_json(payload)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            strict_json_loads('{"preset":"clean","preset":"custom","values":{}}')


if __name__ == '__main__':
    unittest.main()
