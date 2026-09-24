"""Render same-frame source/unprotected NR/Guard comparisons without enhancement."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from validate_live_pairs import local_artifact


def capture_metadata(pairs):
    paths = sorted(pairs.glob('pair-*.json'))
    if len(paths) != 3:
        raise ValueError('Expected three actual captured pairs; an empty run is not evidence')
    captures = []
    used_files = set()
    for path in paths:
        meta = json.loads(path.read_text(encoding='utf-8'))
        required = dict(schema=1, capture_kind='wgc', same_command_list=True,
                        source_fresh=True, nvofa_used=True, hud_guard=True)
        if any(meta.get(key) != value for key, value in required.items()):
            raise ValueError('Comparison requires verified fresh same-command-list WGC/NVOFA frames')
        for key in ('width', 'height', 'hwnd', 'frame_index', 'capture_serial',
                    'source_qpc', 'copy_submission_fence'):
            if type(meta.get(key)) is not int or meta[key] <= 0:
                raise ValueError(f'{path.name}: invalid {key}')
        files = [local_artifact(pairs, meta[key]) for key in ('source', 'pre_hud', 'post_hud')]
        if any(file in used_files for file in files) or len(set(files)) != 3:
            raise ValueError('Capture files must be unique across all three frames')
        used_files.update(files)
        expected_bytes = meta['width'] * meta['height'] * 4
        if any(file.stat().st_size != expected_bytes for file in files):
            raise ValueError('Invalid packed frame length')
        captures.append((meta, files))
    captures.sort(key=lambda item: item[0]['frame_index'])
    if len({(meta['width'], meta['height'], meta['hwnd']) for meta, _ in captures}) != 1:
        raise ValueError('Capture geometry or WGC target changed')
    for key in ('frame_index', 'capture_serial', 'source_qpc', 'copy_submission_fence'):
        values = [meta[key] for meta, _ in captures]
        if any(b <= a for a, b in zip(values, values[1:])):
            raise ValueError(f'{key} must increase across captured frames')
    return captures


def verify_validation(run, captures, manifest):
    if (manifest.get('mode') != 'guard' or not isinstance(manifest.get('live_pair'), dict)
            or manifest['live_pair'].get('performance_evidence') is not False):
        raise ValueError('Comparison requires a Guard live-pair run manifest')
    target = manifest.get('target')
    mask = manifest.get('mask')
    if (not isinstance(target, dict) or target.get('hwnd') != captures[0][0]['hwnd']
            or not isinstance(mask, dict) or not isinstance(mask.get('sha256'), str)):
        raise ValueError('Run target or mask does not match the captured pairs')
    path = run/'live-pair-result.json'
    if not path.is_file():
        raise ValueError('Run validate_live_pairs.py before comparing captured frames')
    validated = json.loads(path.read_text(encoding='utf-8'))
    width, height = captures[0][0]['width'], captures[0][0]['height']
    mask_result = validated.get('mask')
    rows = validated.get('rows')
    if (validated.get('passed') is not True or not isinstance(mask_result, dict)
            or mask_result.get('sha256') != mask['sha256']
            or (mask_result.get('width'), mask_result.get('height')) != (width, height)
            or not isinstance(rows, list) or len(rows) != len(captures)):
        raise ValueError('Pixel validation does not match this run and mask')
    by_frame = {row.get('frame_index'): row for row in rows if isinstance(row, dict)}
    if len(by_frame) != len(captures):
        raise ValueError('Pixel validation has missing or duplicate frame identities')
    for meta, paths in captures:
        row = by_frame.get(meta['frame_index'])
        if (not isinstance(row, dict) or row.get('passed') is not True
                or any(row.get(key) != meta[key] for key in
                       ('frame_index', 'capture_serial', 'source_qpc', 'copy_submission_fence'))):
            raise ValueError('Pixel validation does not match the captured frame identities')
        files = row.get('files')
        if not isinstance(files, dict):
            raise ValueError('Pixel validation has no file hashes')
        for key, frame_path in zip(('source', 'pre_hud', 'post_hud'), paths):
            expected = files.get(key)
            if (not isinstance(expected, dict) or expected.get('name') != frame_path.name
                    or expected.get('sha256') != hashlib.sha256(frame_path.read_bytes()).hexdigest()):
                raise ValueError('Captured frame changed after pixel validation')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path)
    ap.add_argument('--regions', type=Path)
    ap.add_argument('--all-frames', action='store_true', help='Write source, NR, and Guard PNGs for every captured frame')
    args = ap.parse_args()
    pairs = args.run/'live-pairs'
    out = args.run/'hud-comparison'
    regions = json.loads(args.regions.read_text()) if args.regions else {}
    captures = capture_metadata(pairs)
    width, height = captures[0][0]['width'], captures[0][0]['height']
    if not isinstance(regions, dict):
        raise ValueError('Regions must map safe names to pixel bounds')
    for name, bounds in regions.items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9-]+', name):
            raise ValueError('Unsafe region output name')
        if (not isinstance(bounds, list) or len(bounds) != 4
                or any(type(value) is not int for value in bounds)):
            raise ValueError('ROI requires four integer pixel bounds')
        x0, y0, x1, y1 = bounds
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('ROI is outside the matched source')
    manifest_path = args.run/'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    validation_sha256 = verify_validation(args.run, captures, manifest)
    out.mkdir(exist_ok=True)
    results = []
    frame_records = []
    for index, (meta, paths) in enumerate(captures):
        width, height = meta['width'], meta['height']
        frames = {}
        files = {}
        for key, path in zip(('source', 'pre_hud', 'post_hud'), paths):
            blob = path.read_bytes()
            frames[key] = Image.frombytes('RGBA', (width, height), blob).convert('RGB')
            files[key] = dict(name=path.name, sha256=hashlib.sha256(blob).hexdigest())
        frame_records.append(dict(frame_index=meta['frame_index'], capture_serial=meta['capture_serial'],
                                  source_qpc=meta['source_qpc'], files=files))
        first = index == 0
        if first:
            frames['source'].save(out/'source.png')
            frames['pre_hud'].save(out/'unprotected-nr.png')
            frames['post_hud'].save(out/'guard.png')
        if args.all_frames:
            frame_dir = out/'frames'
            frame_dir.mkdir(exist_ok=True)
            for key, label in (('source', 'source'), ('pre_hud', 'unprotected-nr'), ('post_hud', 'guard')):
                frames[key].save(frame_dir/f'{meta["frame_index"]:010d}-{label}.png')
        for name, bounds in regions.items():
            x0, y0, x1, y1 = bounds
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
    summary = dict(rows=results, sample_count=len(captures), frames=frame_records,
        settings=manifest['settings'], worker_sha256=manifest['integrity']['worker_sha256'],
        run_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        pixel_validation_sha256=validation_sha256,
        scope='Identical live frames/history. ROI metrics include background; '
        'the color-selected subset is a declared proxy, not perceptual quality or ground-truth HUD pixels.',
        regions_sha256=hashlib.sha256(args.regions.read_bytes()).hexdigest() if args.regions else None)
    (out/'metrics.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(str(out))


if __name__ == '__main__':
    main()
