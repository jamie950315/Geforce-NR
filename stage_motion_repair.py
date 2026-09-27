"""Stage subpixel-motion and bounded gray-history fixes in an isolated worker."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from stage_hdr import patch_once


# These previously unlisted headers were copied and SHA-256 verified against
# the deployed parent. A changed source needs a new explicit source audit.
PINNED_INPUTS = {
    'nvofa.inl':'28d87488c5757d7d30cc4c8b582e9d7cb38b84e98557358ac5a73cd446f02708',
    'gfn_flow_control.hpp':'8da305a4ea8398a8badf43fa0281cb4aa145f540b0ab990ed8ceb7528a5c32d0',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_sources(files):
    output = dict(files)
    output['nvofa.inl'] = patch_once(files['nvofa.inl'],
        'motion[p.xy]=reset || dot(v,v)<.25 ? float2(0,0) : v;',
        'motion[p.xy]=reset ? float2(0,0) : v;')
    history = patch_once(files['gfn_flow_control.hpp'], 'namespace gfn_core {',
        '''namespace gfn_core {
// One byte per gray pixel, bounded by the same 8K limits as VideoHeader.
constexpr std::size_t max_gray_bytes = 7680u * 4320u;''')
    output['gfn_flow_control.hpp'] = patch_once(history,
        'bytes > 1024u * 1024u', 'bytes > max_gray_bytes')
    output['dlss5-feed-host64.cpp'] = patch_once(files['dlss5-feed-host64.cpp'],
        '''    if (gc.width == 0 || gc.height == 0) { Log("[gray] off"); return true; }
    const size_t need = static_cast<size_t>(gc.width) * gc.height;''',
        '''    if (gc.width == 0 || gc.height == 0) { Log("[gray] off"); return true; }
    if (gc.width > 7680u || gc.height > 4320u) {
        Log("[gray] dimensions exceed supported capture bounds");
        return false;
    }
    const size_t need = static_cast<size_t>(gc.width) * gc.height;
    if (need > gfn_core::max_gray_bytes) {
        Log("[gray] mapping exceeds supported history capacity");
        return false;
    }''')
    return output


def verified_inputs(root, source, parent):
    queued_path = root/'hdr-color-queued-build.json'
    if digest(queued_path) != parent['parent_build_sha256']:
        raise RuntimeError('Queued parent build record changed since capture staging')
    queued = json.loads(queued_path.read_text(encoding='utf-8-sig'))
    if queued.get('mapping') != 'color-preserving' or queued.get('queued') is not True:
        raise RuntimeError('Unexpected queued ancestor policy')
    # The capture stage changes only the CPP. All other patched ancestor
    # headers must still match, rather than trusting the current CPP alone.
    checks = dict(queued['patched'])
    checks.update(parent['patched'])
    checks.update({'nvngx.dll':parent['worker_sha256'], 'nvngx_dlssnr.dll':parent['runtime_sha256'],
                   'dlss5-feed-host64.cpp':parent['source_sha256']})
    for name, expected in checks.items():
        if Path(name).name != name or digest(source/name) != expected:
            raise RuntimeError('Motion repair parent integrity mismatch: '+name)
    for name, expected in PINNED_INPUTS.items():
        if digest(source/name) != expected:
            raise RuntimeError('Motion repair pinned source mismatch: '+name)
    return dict(checks, **PINNED_INPUTS)


def main():
    root = Path(__file__).resolve().parent
    source = root/'native-hdr-color-capture-queued'
    dest = root/'native-hdr-color-motion-repaired'
    record_path = root/'hdr-color-motion-repaired-build.json'
    if dest.exists() or record_path.exists():
        raise RuntimeError('Preserve the existing motion-repaired build before staging another')
    parent_path = root/'hdr-color-capture-queued-build.json'
    parent = json.loads(parent_path.read_text(encoding='utf-8-sig'))
    if (parent.get('mapping') != 'color-preserving' or parent.get('queued') is not True
            or parent.get('capture_queued') is not True or parent.get('d3d11_cpu_wait') is not True):
        raise RuntimeError('Expected the attested capture-queued HDR parent')
    inputs = verified_inputs(root, source, parent)
    names = ('nvofa.inl','gfn_flow_control.hpp','dlss5-feed-host64.cpp')
    patched = patch_sources({name:(source/name).read_text(encoding='utf-8-sig') for name in names})
    command_text = (root/'Build-HDR-COLOR-CAPTURE-QUEUED.cmd').read_text()
    if str(source) not in command_text:
        raise RuntimeError('Build template does not reference the attested source directory')
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp','*.log'))
    for name, text in patched.items():
        (dest/name).write_text(text,encoding='utf-8-sig')
    command = root/'Build-HDR-COLOR-MOTION-REPAIRED.cmd'
    command.write_text(command_text.replace(str(source),str(dest)),encoding='utf-8')
    with (root/'hdr-color-motion-repaired-build.log').open('wb') as log:
        result = subprocess.run(['cmd.exe','/d','/c',str(command)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:
        raise RuntimeError('Motion-repaired build failed; inspect hdr-color-motion-repaired-build.log')
    if digest(dest/'nvngx_dlssnr.dll') != parent['runtime_sha256']:
        raise RuntimeError('Motion-repaired build changed the neural runtime')
    record = dict(mapping='color-preserving',queued=True,capture_queued=True,motion_repaired=True,
        d3d11_cpu_wait=True,worker_sha256=digest(dest/'nvngx.dll'),
        runtime_sha256=digest(dest/'nvngx_dlssnr.dll'),source_sha256=digest(dest/'dlss5-feed-host64.cpp'),
        inputs=inputs,patched={name:digest(dest/name) for name in names},
        parent_build_sha256=digest(parent_path),staging_sha256=digest(Path(__file__)))
    record_path.write_text(json.dumps(record,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
