"""Explicit appearance choices for isolated launches; Core/Lab stays untouched."""

APPEARANCE_PRESETS = ('inherited', 'clean')


def resolve_appearance(preset, inherited):
    """Return a fresh appearance dictionary without modifying inherited values.

    Field validation remains with Core's Appearance.from_dict. The clean preset
    disables structure enhancement while retaining neural-rendering intensity;
    it is not a separate denoiser or a model/runtime precision change.
    """
    if preset not in APPEARANCE_PRESETS:
        raise ValueError('Unsupported appearance preset: ' + str(preset))
    if not isinstance(inherited, dict):
        raise ValueError('Inherited appearance must be a dictionary')
    if preset == 'inherited':
        return dict(inherited)
    return dict(style=1, auto_mask=1, intensity=1.0, local_tone=0.25,
                local_structure=0.0, skin_structure=0.0)
