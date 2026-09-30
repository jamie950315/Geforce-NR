"""Version-bound HDR preflight. Never infer HDR from a stream codec or bit depth."""
import hashlib
import json
import math
from pathlib import Path
import subprocess


def hdr_build_kind(mapping='legacy', queued=False, capture_queued=False, static_stable=False):
    kinds = {'legacy':'hdr', 'color-preserving':'hdr-color'}
    if mapping not in kinds:
        raise ValueError('Unknown HDR mapping')
    kind = kinds[mapping]
    if queued:
        if mapping != 'color-preserving':
            raise ValueError('Queued HDR requires color-preserving mapping')
        kind += '-queued'
    if capture_queued:
        if not queued:
            raise ValueError('Capture queue requires queued HDR')
        kind = 'hdr-color-motion-repaired'
    if static_stable:
        if not capture_queued:
            raise ValueError('Hold identical HDR frames requires queued HDR + capture')
        kind = 'static-stable'
    return kind


def verify_hdr_build(root, mapping='legacy', queued=False, capture_queued=False, static_stable=False):
    root = Path(root)
    kind = hdr_build_kind(mapping, queued, capture_queued, static_stable)
    if static_stable:
        from static_support import verify_static_build
        return verify_static_build(root)
    native = root/('native-'+kind)
    try:
        build = json.loads((root/(kind+'-build.json')).read_text(encoding='utf-8-sig'))
        if build.get('mapping','legacy') != mapping:
            raise RuntimeError('HDR build mapping mismatch')
        if build.get('queued',False) is not queued:
            raise RuntimeError('HDR build queue policy mismatch')
        if build.get('capture_queued',False) is not capture_queued:
            raise RuntimeError('HDR build capture queue policy mismatch')
        if capture_queued and build.get('motion_repaired') is not True:
            raise RuntimeError('HDR build requires continuous subpixel motion and repaired history')
        for name, key in (('nvngx.dll', 'worker_sha256'), ('nvngx_dlssnr.dll', 'runtime_sha256')):
            actual = hashlib.sha256((native/name).read_bytes()).hexdigest()
            if actual != build[key]:
                raise RuntimeError('HDR binary integrity mismatch: '+name)
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError('HDR build is unavailable. Stage and verify the isolated HDR worker first.') from exc
    return native, build


def require_hdr_display(root, hwnd, mapping='legacy', queued=False, capture_queued=False, static_stable=False):
    native, _ = verify_hdr_build(root, mapping, queued, capture_queued, static_stable)
    result = subprocess.run([str(native/'nvngx.dll'), '--hdr-display', str(hwnd)],
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        data = json.loads(result.stdout)
        if result.returncode or data.get('known') is not True:
            raise ValueError('display query failed')
        white = data['white']
        if type(white) not in (int, float) or not math.isfinite(white) or white <= 0:
            raise ValueError('invalid display white level')
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Could not verify the selected window\'s HDR display. HDR was not started.') from exc
    if data.get('enabled') is not True:
        raise RuntimeError('Enable Windows HDR on the selected window\'s display, or turn off HDR output. No SDR fallback is used.')
    return data
