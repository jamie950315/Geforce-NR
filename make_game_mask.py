"""Conservative fixed HUD regions observed in the current 2560x1440 game view."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
GUARD = ROOT.parent / 'gfn-nvofa-lab-20260920/logs/hud-guard-20260921-r1'
sys.path.insert(0, str(GUARD))
from hud_masks import encode, decode, feather

geometry = json.loads((ROOT / 'runs/gameplay-bypass-before/geometry.json').read_text())
width, height = geometry['wgc']
if (width, height) != (2560, 1440):
    raise ValueError('Profile only supports the observed 2560x1440 geometry')
regions = {
    'health_and_status': [30, 45, 720, 180],
    'map_and_stream_stats': [2080, 0, 2560, 405],
    'equipment_and_quick_actions': [15, 1120, 470, 1440],
    'control_hints_and_stance': [2310, 1090, 2560, 1440],
    'center_aim_union': [1245, 685, 1315, 755],
    'subtitle_and_interaction_union': [630, 1100, 1930, 1370],
}
support = np.zeros((height, width), dtype=bool)
for x0, y0, x1, y1 in regions.values():
    support[y0:y1, x0:x1] = True
mask = feather(support, padding=2, radius=4)
blob = encode(mask)
assert np.array_equal(mask, decode(blob))
(ROOT / 'cyberpunk-1440p.hgm').write_bytes(blob)
Image.fromarray(mask).save(ROOT / 'cyberpunk-mask.png')
(ROOT / 'cyberpunk-mask.json').write_text(json.dumps(dict(
    wgc=[width, height], regions=regions, sha256=hashlib.sha256(blob).hexdigest(),
    protected_fraction=float((mask == 255).mean()), affected_fraction=float((mask > 0).mean()),
    scope='Fixed conservative rectangles; includes source background. Not automatic HUD extraction. Moving world labels and menus are not covered.'
), indent=2), encoding='utf-8')
