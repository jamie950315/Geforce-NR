"""Render same-frame source/unprotected NR/Guard comparisons without enhancement."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from validate_live_pairs import local_artifact


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path)
    ap.add_argument('--regions', type=Path)
    args = ap.parse_args()
    pairs = args.run/'live-pairs'
    out = args.run/'hud-comparison'
    out.mkdir(exist_ok=True)
    regions = json.loads(args.regions.read_text()) if args.regions else {}
    results = []
    metadata_files = sorted(pairs.glob('pair-*.json'))
    if len(metadata_files) != 3:
        raise ValueError('Expected three actual captured pairs; an empty run is not evidence')
    for metadata in metadata_files:
        meta = json.loads(metadata.read_text())
        if not all(meta.get(key) is True for key in ('same_command_list', 'source_fresh', 'nvofa_used')) or meta.get('capture_kind') != 'wgc':
            raise ValueError('Comparison requires verified fresh same-command-list WGC/NVOFA frames')
        width, height = meta['width'], meta['height']
        frames = {}
        for key in ('source', 'pre_hud', 'post_hud'):
            path = local_artifact(pairs, meta[key])
            blob = path.read_bytes()
            if len(blob) != width*height*4:
                raise ValueError('Invalid packed frame length')
            frames[key] = Image.frombytes('RGBA', (width, height), blob).convert('RGB')
        first = metadata == metadata_files[0]
        if first:
            frames['source'].save(out/'source.png')
            frames['pre_hud'].save(out/'unprotected-nr.png')
            frames['post_hud'].save(out/'guard.png')
        for name, bounds in regions.items():
            if not re.fullmatch(r'[a-z0-9-]+', name):
                raise ValueError('Unsafe region output name')
            x0, y0, x1, y1 = bounds
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError('ROI is outside the matched source')
            crops = {key: image.crop(bounds) for key, image in frames.items()}
            source = np.asarray(crops['source'], dtype=np.int16)
            nr = np.asarray(crops['pre_hud'], dtype=np.int16)
            guard = np.asarray(crops['post_hud'], dtype=np.int16)
            error = np.abs(nr-source)
            # Saturated bright marks are a declared color-selected proxy, not
            # an automatically detected/ground-truth HUD segmentation.
            hi, lo = source.max(axis=2), source.min(axis=2)
            marks = (hi >= 140) & (hi-lo >= 65)
            marked_error = error[marks]
            results.append(dict(frame=meta['frame_index'], region=name, bounds=bounds,
                roi_rgb_mae=float(error.mean()), roi_rgb_p95=float(np.percentile(error, 95)),
                roi_max=int(error.max()), guard_roi_max=int(np.abs(guard-source).max()),
                color_proxy_pixels=int(marks.sum()),
                color_proxy_rgb_mae=float(marked_error.mean()) if marked_error.size else None,
                color_proxy_rgb_p95=float(np.percentile(marked_error, 95)) if marked_error.size else None,
                source_rgb_mean=source.mean(axis=(0, 1)).tolist(), nr_rgb_mean=nr.mean(axis=(0, 1)).tolist()))
            if first:
                scale = 2
                tile_width, tile_height = (x1-x0)*scale, (y1-y0)*scale
                sheet = Image.new('RGB', (tile_width*3, tile_height+40), '#152126')
                draw = ImageDraw.Draw(sheet)
                font = ImageFont.load_default(size=16)
                labels = ('Source', 'NR, no mask', 'Guard') if tile_width < 250 else ('Original source', 'NR without HUD mask', 'NR + fixed HUD mask')
                for i, (key, label) in enumerate(zip(('source', 'pre_hud', 'post_hud'), labels)):
                    draw.text((i*tile_width+8, 10), label, fill='white', font=font)
                    sheet.paste(crops[key].resize((tile_width, tile_height), Image.Resampling.NEAREST), (i*tile_width, 40))
                sheet.save(out/(name+'.png'))
    if not results and regions:
        raise ValueError('No captured pairs were found')
    manifest_path = args.run/'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    summary = dict(rows=results, sample_count=len(metadata_files),
        settings=manifest['settings'], worker_sha256=manifest['integrity']['worker_sha256'],
        run_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        scope='Identical live frames/history. ROI metrics include background; '
        'the color-selected subset is a declared proxy, not perceptual quality or ground-truth HUD pixels.',
        regions_sha256=hashlib.sha256(args.regions.read_bytes()).hexdigest() if args.regions else None)
    (out/'metrics.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(str(out))


if __name__ == '__main__':
    main()
