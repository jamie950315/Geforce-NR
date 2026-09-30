"""Stage exact duplicate-frame suppression without replacing existing workers."""
import json
from pathlib import Path
import shutil
import subprocess

from stage_hdr import digest, patch_once


def patch_source(source):
    source = patch_once(source, 'static void CloseCaptureBridge()\n{',
        '#include "static_capture.inl"\n\nstatic void CloseCaptureBridge()\n{\n    CloseStaticCapture();')
    source = patch_once(source, '    ProfileGpuEnd(PS_SWIZZLE);\n    const UINT64 fence = EndCommands();',
        '    if (!RecordStaticCapture(g_dda_d12)) return false;\n'
        '    ProfileGpuEnd(PS_SWIZZLE);\n    const UINT64 fence = EndCommands();')
    # The original source has already returned COMMON at this point. Keep the
    # comparison in the same command list, with an explicit state round trip.
    source = patch_once(source, '    if (!RecordStaticCapture(g_dda_d12)) return false;',
        '''    auto static_srv = Transition(g_dda_d12,D3D12_RESOURCE_STATE_COMMON,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    h.list->ResourceBarrier(1,&static_srv);
    if (!RecordStaticCapture(g_dda_d12)) return false;
    auto static_common = Transition(g_dda_d12,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
        D3D12_RESOURCE_STATE_COMMON);
    h.list->ResourceBarrier(1,&static_common);''')
    source = patch_once(source, '    if (g_submission_failed) return false;\n    UpdateAdaptiveExposure();',
        '    if (g_submission_failed) return false;\n    if (!ReadStaticCapture()) return false;\n    UpdateAdaptiveExposure();')
    source = patch_once(source, '            source_fresh = got && g_capture_visual_changed;',
        '''            if (got && g_static_equal) {
                got = false;
                g_capture_visual_changed = false;
            }
            source_fresh = got && g_capture_visual_changed;''')
    source = patch_once(source, '                                         g_force_next_frame;',
        '                                         g_force_next_frame || fh.reset != 0;')
    source = patch_once(source, '                if (skip)\n                {\n                    ++g_skip_static_count;',
        '''                // Explicit diagnostic pixel requests receive the last
                // verified output, without advancing NR/flow history again.
                if (g_static_equal && warmup_done && !out_changed &&
                    (fh.reserved & FRAME_FLAG_SKIP_STATIC) != 0 &&
                    (fh.reserved & FRAME_FLAG_WANT_PIXELS) != 0) {
                    const bool pixels_ok = want_bypass
                        ? DownloadVideoFrame(v,output,v.color.tex,
                            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)
                        : DownloadVideoFrame(v,output);
                    if (!pixels_ok || !DeliverPixels(output,fh.index,fh.pts)) return 10;
                    ProfileFrameResult(v,fh,false,"static-repeat");
                    if (phase_on) ++g_ph_idle;
                    PhaseReport(want_bypass);
                    continue;
                }
                if (skip)
                {
                    ++g_skip_static_count;''')
    source = patch_once(source, '        PhaseAdd(PH_FRAME, t_frame);\n        ProfileFrameResult',
        '        if (CaptureActive()) g_static_policy.rendered();\n'
        '        PhaseAdd(PH_FRAME, t_frame);\n        ProfileFrameResult')
    return source


def main():
    root = Path(__file__).resolve().parent
    source = root/'native-hdr-color-motion-repaired'
    dest = root/'native-static-stable'
    record = root/'static-stable-build.json'
    if dest.exists() or record.exists():
        raise RuntimeError('Preserve the existing static-stable build before staging another')
    parent_path = root/'hdr-color-motion-repaired-build.json'
    parent = json.loads(parent_path.read_text(encoding='utf-8-sig'))
    required = dict(mapping='color-preserving', queued=True, capture_queued=True,
                    motion_repaired=True, d3d11_cpu_wait=True)
    if any(parent.get(k) != v for k,v in required.items()):
        raise RuntimeError('Static capture requires the attested motion-repaired parent')
    # Attest the complete patched ancestry, including headers carried unchanged
    # through the capture and motion stages.
    queued_path = root/'hdr-color-queued-build.json'
    capture_path = root/'hdr-color-capture-queued-build.json'
    capture = json.loads(capture_path.read_text(encoding='utf-8-sig'))
    if digest(capture_path) != parent['parent_build_sha256'] or digest(queued_path) != capture['parent_build_sha256']:
        raise RuntimeError('Static capture ancestor record changed')
    checks = dict(json.loads(queued_path.read_text(encoding='utf-8-sig'))['patched'])
    checks.update(capture['patched']); checks.update(parent['patched'])
    checks.update({'nvngx.dll':parent['worker_sha256'], 'nvngx_dlssnr.dll':parent['runtime_sha256']})
    for name,expected in checks.items():
        if Path(name).name != name or digest(source/name) != expected:
            raise RuntimeError('Static capture parent integrity mismatch: '+name)
    inputs = {p.name:digest(p) for p in source.iterdir() if p.is_file() and p.suffix in ('.h','.hpp','.inl','.cpp')}
    inputs.update(checks)
    patched = patch_source((source/'dlss5-feed-host64.cpp').read_text(encoding='utf-8-sig'))
    template = (root/'Build-HDR-COLOR-MOTION-REPAIRED.cmd').read_text()
    if str(source) not in template:
        raise RuntimeError('Build template does not reference the attested parent')
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp','*.log'))
    for name,expected in inputs.items():
        if digest(dest/name) != expected:
            raise RuntimeError('Static capture source changed during copy: '+name)
    (dest/'dlss5-feed-host64.cpp').write_text(patched,encoding='utf-8-sig')
    for name in ('static_capture.inl','static_compare.h'):
        shutil.copy2(root/name,dest/name)
    command = root/'Build-STATIC-STABLE.cmd'
    command.write_text(template.replace(str(source),str(dest)),encoding='utf-8')
    with (root/'static-stable-build.log').open('wb') as log:
        done = subprocess.run(['cmd.exe','/d','/c',str(command)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if done.returncode:
        raise RuntimeError('Static-stable build failed; inspect static-stable-build.log')
    if digest(dest/'nvngx_dlssnr.dll') != parent['runtime_sha256']:
        raise RuntimeError('Static capture build changed the neural runtime')
    data = dict(required, static_stable=True, worker_sha256=digest(dest/'nvngx.dll'),
                runtime_sha256=parent['runtime_sha256'], source_sha256=digest(dest/'dlss5-feed-host64.cpp'),
                inputs=inputs, patched={name:digest(dest/name) for name in
                    ('dlss5-feed-host64.cpp','static_capture.inl','static_compare.h')},
                parent_build_sha256=digest(parent_path), staging_sha256=digest(Path(__file__)))
    record.write_text(json.dumps(data,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
