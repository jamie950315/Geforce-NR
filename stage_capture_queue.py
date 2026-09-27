"""Isolated same-queue swizzle/gray experiment; preserve D3D11 source retirement."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from stage_hdr import patch_once


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_source(source):
    source = patch_once(source, 'static void CloseGray()\n{',
        '''static ID3D12DescriptorHeap *g_capture_gray_heap = nullptr;

static void CloseGray()
{''')
    source = patch_once(source,
        '    if (g_gray_readback) { g_gray_readback->Release(); g_gray_readback = nullptr; }',
        '''    if (g_gray_readback) { g_gray_readback->Release(); g_gray_readback = nullptr; }
    if (g_capture_gray_heap) { g_capture_gray_heap->Release(); g_capture_gray_heap = nullptr; }''')
    source = patch_once(source, '    if (!EnsureGrayPipeline()) return false;',
        '''    if (!EnsureGrayPipeline()) return false;
    // Swizzle and gray may be in flight together. Never overwrite swizzle's
    // shader-visible descriptors before its GPU fence has retired.
    D3D12_DESCRIPTOR_HEAP_DESC gray_heap = {};
    gray_heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    gray_heap.NumDescriptors = 2;
    gray_heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    if (FAILED(h.dev->CreateDescriptorHeap(&gray_heap, IID_PPV_ARGS(&g_capture_gray_heap)))) {
        Log("[capture-queue] dedicated gray descriptor heap creation failed");
        return false;
    }''')
    source = patch_once(source,
        '// Called from DdaGrab after the swizzle (it cannot be in the same Begin/End\n// block - a separate fence is needed), hence its own Begin/End here.',
        '// Kept as a separate submission for independent GPU timestamps. Its\n// later fence retires both passes; descriptors are on a dedicated heap.')
    start = source.index('static bool AreaToGray()\n{')
    end = source.index('// Adaptive exposure ', start)
    gray = source[start:end]
    gray = patch_once(gray, 'static bool AreaToGray()', 'static bool AreaToGray(UINT64 swizzle_fence)')
    gray = patch_once(gray, '    if (!g_gray_mapped || !g_dda_dst) return false;',
        '''    if (!g_gray_mapped || !g_dda_dst || !g_capture_gray_heap || !swizzle_fence)
        return FailGpuWork("capture-gray", "invalid-queued-contract", E_FAIL);''')
    gray = patch_once(gray, '    if (!BeginCommands()) return false;',
        '    if (!BeginCommands()) return FailGpuWork("capture-gray", "begin-after-swizzle", E_FAIL);')
    if gray.count('g_dda_heap') != 3:
        raise RuntimeError('Unexpected gray descriptor binding count')
    gray = gray.replace('g_dda_heap', 'g_capture_gray_heap')
    gray = patch_once(gray, '    const UINT64 fence = EndCommands();',
        '''    const UINT64 fence = EndCommands();
    if (!fence || fence <= swizzle_fence)
        return FailGpuWork("capture-gray", "submission-order", E_FAIL);''')
    gray = patch_once(gray,
        '    if (!ProfileWait(PS_GRAY, fence, 10000)) { Log("[gray] fence timeout"); return false; }',
        '''    if (!ProfileWait(PS_GRAY, fence, 10000)) { Log("[gray] fence timeout"); return false; }
    static bool queued_reported = false;
    if (!queued_reported) {
        Log("[capture-queue] swizzle=%llu gray=%llu retired; dedicated gray heap; D3D11 wait retained",
            swizzle_fence, fence);
        queued_reported = true;
    }''')
    source = source[:start]+gray+source[end:]
    source = patch_once(source,
        '''    if (!ProfileWait(PS_SWIZZLE, fence, 10000)) { Log("[cap] swizzle fence timeout"); return false; }
    // Hand the client the luminance frame (320x180) for the optical flow
    g_capture_gray_ok = AreaToGray() && g_gray_mapped;''',
        '''    if (!fence) return false;
    // The following gray submission shares h.queue and consumes this swizzle.
    // Its final fence must retire before readback, exposure, or another capture.
    if (g_gray_mapped) {
        g_capture_gray_ok = AreaToGray(fence);
        if (!g_capture_gray_ok)
            return FailGpuWork("capture-gray", "queued-readback-failed", E_FAIL);
    } else {
        // No gray consumer means there is no later fence to retire the swizzle.
        if (!ProfileWait(PS_SWIZZLE, fence, 10000)) { Log("[cap] swizzle fence timeout"); return false; }
        g_capture_gray_ok = false;
    }''')
    return source


def main():
    root = Path(__file__).resolve().parent
    source = root/'native-hdr-color-queued'
    dest = root/'native-hdr-color-capture-queued'
    record_path = root/'hdr-color-capture-queued-build.json'
    if dest.exists() or record_path.exists():
        raise RuntimeError('Preserve the existing capture-queue experiment before staging another build')
    parent_path = root/'hdr-color-queued-build.json'
    build = json.loads(parent_path.read_text(encoding='utf-8-sig'))
    if build.get('mapping') != 'color-preserving' or build.get('queued') is not True:
        raise RuntimeError('Expected the attested color-preserving queued-tail HDR build')
    checks = dict(build['patched'])
    checks.update({'nvngx.dll':build['worker_sha256'], 'nvngx_dlssnr.dll':build['runtime_sha256'],
                   'dlss5-feed-host64.cpp':build['source_sha256']})
    for name, expected in checks.items():
        if Path(name).name != name or digest(source/name) != expected:
            raise RuntimeError('Capture-queue source integrity mismatch: '+name)
    patched = patch_source((source/'dlss5-feed-host64.cpp').read_text(encoding='utf-8-sig'))
    template = root/'Build-HDR-COLOR-QUEUED.cmd'
    command_text = template.read_text()
    if str(source) not in command_text:
        raise RuntimeError('Build template does not reference the attested source directory')
    inputs = {name:digest(source/name) for name in checks}
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp','*.log'))
    (dest/'dlss5-feed-host64.cpp').write_text(patched,encoding='utf-8-sig')
    command = root/'Build-HDR-COLOR-CAPTURE-QUEUED.cmd'
    command.write_text(command_text.replace(str(source),str(dest)),encoding='utf-8')
    with (root/'hdr-color-capture-queued-build.log').open('wb') as log:
        result = subprocess.run(['cmd.exe','/d','/c',str(command)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:
        raise RuntimeError('Capture-queue build failed; inspect hdr-color-capture-queued-build.log')
    if digest(dest/'nvngx_dlssnr.dll') != build['runtime_sha256']:
        raise RuntimeError('Capture-queue build changed the neural runtime')
    record = dict(experiment='queued-swizzle-gray',mapping='color-preserving',queued=True,
        capture_queued=True, d3d11_cpu_wait=True,
        worker_sha256=digest(dest/'nvngx.dll'),runtime_sha256=digest(dest/'nvngx_dlssnr.dll'),
        source_sha256=digest(dest/'dlss5-feed-host64.cpp'),parent_build_sha256=digest(parent_path),inputs=inputs,
        patched={'dlss5-feed-host64.cpp':digest(dest/'dlss5-feed-host64.cpp')},
        staging_sha256=digest(Path(__file__)))
    record_path.write_text(json.dumps(record,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
