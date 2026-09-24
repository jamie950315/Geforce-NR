"""Validate three bounded live source/pre-HUD/post-HUD RGBA captures."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct

HGM1 = 0x314D4748

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_mask(path: Path) -> tuple[bytes, int, int]:
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError('Mask is shorter than the HGM1 header')
    magic, version, width, height = struct.unpack('<4I', data[:16])
    if magic != HGM1 or version != 1 or len(data) != 16 + width * height:
        raise ValueError('Invalid HGM1 mask')
    return data[16:], width, height

def load_rgba(path: Path, width: int, height: int) -> bytes:
    data = path.read_bytes()
    if len(data) != width * height * 4:
        raise ValueError(f'{path.name}: expected {width * height * 4} bytes, got {len(data)}')
    return data

def local_artifact(directory: Path, name: object) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError(f'Unsafe artifact name: {name!r}')
    path = directory / name
    if path.resolve().parent != directory.resolve():
        raise ValueError(f'Artifact escapes probe directory: {name!r}')
    return path

def validate(directory: Path, mask_path: Path) -> dict:
    mask, mask_w, mask_h = load_mask(mask_path)
    manifest_path = directory.parent / 'manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    run_manifest = json.loads(manifest_bytes.decode('utf-8-sig'))
    target = run_manifest.get('target')
    run_mask = run_manifest.get('mask')
    if (run_manifest.get('mode') != 'guard'
            or not isinstance(run_manifest.get('live_pair'), dict)
            or run_manifest['live_pair'].get('performance_evidence') is not False
            or not isinstance(target, dict) or type(target.get('hwnd')) is not int
            or target['hwnd'] <= 0 or not isinstance(run_mask, dict)
            or run_mask.get('sha256') != digest(mask_path)):
        raise ValueError('Run manifest target, mode, or mask does not match live-pair validation')
    manifests = sorted(directory.glob('pair-*.json'))
    if len(manifests) != 3:
        raise ValueError(f'Expected exactly three pair manifests, got {len(manifests)}')
    if not (255 in mask and 0 in mask and any(0 < value < 255 for value in mask)):
        raise ValueError('Mask must contain exact, outside, and feather pixels')
    rows = []
    identities = set()
    for manifest_path in manifests:
        meta = json.loads(manifest_path.read_text(encoding='utf-8'))
        if meta.get('schema') != 1:
            raise ValueError(f'{manifest_path.name}: unsupported schema')
        required = {
            'capture_kind': 'wgc', 'source_fresh': True, 'nvofa_used': True,
            'hud_guard': True, 'same_command_list': True,
        }
        for key, expected in required.items():
            if meta.get(key) != expected:
                raise ValueError(f'{manifest_path.name}: {key} is not {expected!r}')
        width, height = int(meta['width']), int(meta['height'])
        if (width, height) != (mask_w, mask_h):
            raise ValueError(f'{manifest_path.name}: geometry does not match mask')
        identity = (int(meta['frame_index']), int(meta['capture_serial']), int(meta['source_qpc']))
        if min(identity) <= 0 or identity in identities:
            raise ValueError(f'{manifest_path.name}: invalid or duplicate capture identity')
        identities.add(identity)
        paths = {key: local_artifact(directory, meta[key]) for key in ('source', 'pre_hud', 'post_hud')}
        source = load_rgba(paths['source'], width, height)
        pre = load_rgba(paths['pre_hud'], width, height)
        post = load_rgba(paths['post_hud'], width, height)
        exact_max = outside_max = feather_max = changed_exact_pre = 0
        for pixel, weight in enumerate(mask):
            base = pixel * 4
            for channel in range(4):
                offset = base + channel
                if weight == 255:
                    exact_max = max(exact_max, abs(post[offset] - source[offset]))
                    changed_exact_pre += pre[offset] != source[offset]
                elif weight == 0:
                    outside_max = max(outside_max, abs(post[offset] - pre[offset]))
                else:
                    expected = (pre[offset] * (255 - weight) + source[offset] * weight + 127) // 255
                    feather_max = max(feather_max, abs(post[offset] - expected))
        rows.append({
            'frame_index': identity[0], 'capture_serial': identity[1], 'source_qpc': identity[2],
            'copy_submission_fence': int(meta['copy_submission_fence']),
            'exact_max_error': exact_max, 'outside_max_error': outside_max,
            'feather_max_error': feather_max, 'pre_hud_diff_components_in_exact_mask': changed_exact_pre,
            'files': {key: {'name': path.name, 'sha256': digest(path)} for key, path in paths.items()},
            'passed': exact_max == 0 and outside_max == 0 and feather_max <= 1,
        })
    rows.sort(key=lambda row: row['frame_index'])
    for key in ('frame_index', 'capture_serial', 'source_qpc', 'copy_submission_fence'):
        values = [row[key] for row in rows]
        if any(b <= a for a, b in zip(values, values[1:])):
            raise ValueError(f'{key} values are not strictly increasing: {values}')
    hwnds = {int(json.loads(path.read_text(encoding='utf-8'))['hwnd']) for path in manifests}
    if hwnds != {target['hwnd']}:
        raise ValueError(f'Expected one nonzero WGC HWND, got {sorted(hwnds)}')
    result = {
        'passed': all(row['passed'] for row in rows),
        'scope': 'Three live WGC frames copied source/pre-HUD/post-HUD in each frame same GPU command list with NVOFA enabled.',
        'run_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'mask': {'name': mask_path.name, 'sha256': digest(mask_path), 'width': mask_w, 'height': mask_h},
        'rows': rows,
    }
    return result

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--mask', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = validate(args.directory, args.mask)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    return 0 if result['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
