"""Attest the optional exact duplicate-frame worker before saving or launching."""
import json
from pathlib import Path
from stage_hdr import digest


def verify_static_build(root):
    root=Path(root); native=root/'native-static-stable'
    try:
        build=json.loads((root/'static-stable-build.json').read_text(encoding='utf-8-sig'))
        policy=dict(static_stable=True,mapping='color-preserving',queued=True,capture_queued=True,
                    motion_repaired=True,d3d11_cpu_wait=True)
        for key,value in policy.items():
            if type(build.get(key)) is not type(value) or build[key]!=value:
                raise RuntimeError('Static-stable build policy mismatch: '+key)
        for name,key in (('nvngx.dll','worker_sha256'),('nvngx_dlssnr.dll','runtime_sha256')):
            if digest(native/name)!=build[key]:
                raise RuntimeError('Static-stable binary integrity mismatch: '+name)
    except (OSError,ValueError,KeyError) as exc:
        raise RuntimeError('Hold identical frames requires the attested static-stable worker. Stage it first.') from exc
    return native,build
