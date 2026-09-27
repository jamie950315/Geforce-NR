"""Validated application appearance controls, not NVIDIA performance modes.

Only the isolated launcher consumes these settings; Core/Lab files and model
runtime binaries are never modified. Clean is the panel's appearance default.
"""
import json
import math


APPEARANCE_LABELS = {'Clean': 'clean', 'Faithful': 'faithful', 'Natural': 'natural',
                     'Strong / Cinematic': 'strong', 'Extreme / Overdrive': 'extreme',
                     'Custom': 'custom'}
APPEARANCE_PRESETS = ('inherited', *APPEARANCE_LABELS.values())
SLIDER_RANGES = dict(intensity=(0.0, 1.0), local_tone=(0.0, 2.0),
                     local_structure=(0.0, 2.0), skin_structure=(-1.0, 2.5))
_PRESETS = {
    'clean': dict(style=1, auto_mask=1, intensity=1.0, local_tone=0.25,
                  local_structure=0.0, skin_structure=0.0),
    'faithful': dict(style=0, auto_mask=1, intensity=0.7, local_tone=0.25,
                     local_structure=0.75, skin_structure=-1.0),
    'natural': dict(style=1, auto_mask=1, intensity=1.0, local_tone=0.5,
                    local_structure=1.0, skin_structure=-1.0),
    'strong': dict(style=2, auto_mask=1, intensity=1.0, local_tone=0.9,
                   local_structure=1.5, skin_structure=1.0),
    'extreme': dict(style=2, auto_mask=1, intensity=1.0, local_tone=1.5,
                    local_structure=1.5, skin_structure=1.5),
}


def validate_appearance_values(values):
    if not isinstance(values, dict) or set(values) != {'style', 'auto_mask', *SLIDER_RANGES}:
        raise ValueError('Appearance values must contain exactly the six supported fields')
    for key, options in (('style', (0, 1, 2)), ('auto_mask', (0, 1))):
        if type(values[key]) is not int or values[key] not in options:
            raise ValueError('Invalid appearance field: ' + key)
    for key, (lower, upper) in SLIDER_RANGES.items():
        number = values[key]
        if type(number) not in (int, float) or not lower <= number <= upper or not math.isfinite(number):
            raise ValueError(f'Appearance {key} must be a finite number from {lower} to {upper}')
    return dict(values)


def preset_config(name):
    if not isinstance(name, str) or name not in APPEARANCE_LABELS.values():
        raise ValueError('Unsupported appearance preset: ' + str(name))
    return dict(preset=name, values=dict(_PRESETS['clean' if name == 'custom' else name]))


def validate_appearance_config(config):
    if not isinstance(config, dict) or set(config) != {'preset', 'values'}:
        raise ValueError('Appearance configuration must contain only preset and values')
    canonical = preset_config(config['preset'])
    values = validate_appearance_values(config['values'])
    if config['preset'] != 'custom' and values != canonical['values']:
        raise ValueError('Named appearance preset values differ; select Custom for edited values')
    return dict(preset=config['preset'], values=values)


def strict_json_loads(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate appearance JSON field: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite appearance JSON value: ' + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def parse_appearance_json(text):
    """The custom CLI payload is the six-value object, not a settings path."""
    return validate_appearance_values(strict_json_loads(text))


def appearance_cli_args(config):
    config = validate_appearance_config(config)
    args = ['--appearance-preset', config['preset']]
    if config['preset'] == 'custom':
        args += ['--appearance-json', json.dumps(config['values'], separators=(',', ':'), allow_nan=False)]
    return args


def resolve_appearance(preset, inherited, custom=None):
    """Return fresh values, retaining the legacy inherited CLI behavior."""
    if not isinstance(preset, str) or preset not in APPEARANCE_PRESETS:
        raise ValueError('Unsupported appearance preset: ' + str(preset))
    if not isinstance(inherited, dict):
        raise ValueError('Inherited appearance must be a dictionary')
    if preset == 'custom':
        return validate_appearance_values(custom)
    if custom is not None:
        raise ValueError('Custom appearance values require the custom preset')
    if preset == 'inherited':
        return dict(inherited)
    return preset_config(preset)['values']
