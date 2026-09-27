"""Version-bound HDR preflight. Never infer HDR from a stream codec or bit depth."""
import hashlib
import json
import math
from pathlib import Path
import subprocess


def verify_hdr_build(root):
    root = Path(root)
    native = root/'native-hdr'
    try:
        build = json.loads((root/'hdr-build.json').read_text(encoding='utf-8-sig'))
        for name, key in (('nvngx.dll', 'worker_sha256'), ('nvngx_dlssnr.dll', 'runtime_sha256')):
            actual = hashlib.sha256((native/name).read_bytes()).hexdigest()
            if actual != build[key]:
                raise RuntimeError('HDR binary integrity mismatch: '+name)
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError('HDR build is unavailable. Stage and verify the isolated HDR worker first.') from exc
    return native, build


def require_hdr_display(root, hwnd):
    native, _ = verify_hdr_build(root)
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
