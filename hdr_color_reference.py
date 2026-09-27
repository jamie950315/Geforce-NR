"""Scalar references for the color-preserving HDR proxy and edit limiter."""
import math

LUMA = (.2126, .7152, .0722)


def luminance(rgb):
    return sum(a*b for a,b in zip(rgb,LUMA))


def proxy_gamut(rgb):
    if len(rgb) != 3 or not all(math.isfinite(x) for x in rgb):
        raise ValueError('Expected three finite linear scRGB channels')
    low = min(rgb)
    if low >= 0:
        return tuple(rgb)
    y = luminance(rgb)
    if y <= 0:
        return (0.,0.,0.)
    scale = y/(y-low)
    return tuple(max(y+(x-y)*scale,0.) for x in rgb)


def limit_edit(delta):
    if len(delta) != 3 or not all(math.isfinite(x) for x in delta):
        raise ValueError('Expected three finite edit channels')
    peak = max(abs(x) for x in delta)
    if peak <= .25:
        return tuple(delta)
    return tuple(x*(.25/peak) for x in delta)
