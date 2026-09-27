"""Build isolated, fail-closed HDR output from the attested repaired worker."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError('Ambiguous HDR patch anchor: '+old[:90])
    return source.replace(old, new, 1)


def patch_sources(files):
    display = files['hdr_display.h']
    display = patch_once(display, 'bool enabled = false;', 'bool known = false;\n    bool enabled = false;')
    display = patch_once(display, '"NS_HDR"', '"GFN_NR_HDR"')
    display = patch_once(display, 'result.enabled = color.advancedColorEnabled && !color.wideColorEnforced;',
        '{ result.known = true; result.enabled = color.advancedColorEnabled && !color.wideColorEnforced; }')
    display = patch_once(display, 'result.white = white.SDRWhiteLevel / 1000.0f;',
        'result.white = white.SDRWhiteLevel / 1000.0f;\n            else result.known = false;')
    files['hdr_display.h'] = display
    source = files['dlss5-feed-host64.cpp']
    source = patch_once(source, 'int main(int argc, char **argv)\n{',
        'int main(int argc, char **argv)\n{\n    if (argc == 3 && strcmp(argv[1], "--hdr-display") == 0)\n        return GfnHdrDisplayCommand(argv[2]);')
    source = patch_once(source, 's->hdr = HdrEnabled() && g_capture_display.enabled;',
        '''s->hdr = HdrEnabled() && g_capture_display.enabled;
        if (HdrEnabled() && (!g_capture_display.known || !s->hdr)) {
            Log("[hdr] Windows HDR is not enabled on the selected display; refusing SDR fallback");
            delete s; return false;
        }''')
    source = patch_once(source, 'if (g_wgc->hdr != (HdrEnabled() && g_capture_display.enabled))',
        '''if (HdrEnabled() && (!g_capture_display.known || !g_capture_display.enabled))
            return FailGpuWork("hdr-display", "Windows-HDR-disabled-or-unavailable", E_FAIL);
        if (g_wgc->hdr != (HdrEnabled() && g_capture_display.enabled))''')
    files['dlss5-feed-host64.cpp'] = source
    present = files['hdr_present.inl']
    present = patch_once(present, 'static ID3D12Resource *g_hdr_output = nullptr;',
        'static ID3D12Resource *g_hdr_output = nullptr;\n#include "hdr_runtime.inl"')
    present = patch_once(present, '    g_present_space_set = true;\n    g_present_space = space;\n', '')
    present = patch_once(present, '        return hdr ? false : true;\n    }\n    return true;',
        '        return hdr ? false : true;\n    }\n    g_present_space_set = true;\n    g_present_space = space;\n    return true;')
    present = patch_once(present, '    const bool framegen = FgRequested() && !bypass;',
        '''    if (!g_capture_display.known || !g_capture_display.enabled || !g_capture_float)
        return FailGpuWork("hdr-present", "HDR-contract-lost", E_FAIL);
    const bool framegen = FgRequested() && !bypass;''')
    present = patch_once(present, '    const bool ok = PresentStatus(g_present_swap->Present(0, 0), "hdr present");',
        '''    if (PhaseEnabled()) { g_frame_stamp.present_call = PhaseNow(); g_frame_stamp.fence = fence; }
    const bool ok = PresentStatus(g_present_swap->Present(0, 0), "hdr present");''')
    present = patch_once(present, '    if (ok) { RevealOnFirstPresent(); SpoutBridgeSend(); }',
        '''    if (ok) {
        RevealOnFirstPresent(); SpoutBridgeSend();
        if (!GfnHdrStatus(w, height) || !GfnHdrProof(v, bypass))
            return FailGpuWork("hdr-evidence", "HDR-status-or-proof-failed", E_FAIL);
    }''')
    files['hdr_present.inl'] = present
    hud = files['hud_guard.inl']
    if hud.count('g_hdr_capture || ') != 2:
        raise RuntimeError('Unexpected HUD proxy contract')
    # Both textures remain full-resolution RGBA8 SDR proxies. Protected pixels
    # copy proxyIn to proxyOut, so the HDR residual is zero and native FP16 wins.
    hud = hud.replace('g_hdr_capture || ', '')
    hud = hud.replace('Source/result must be the same frame and SDR RGBA8.',
        'Source/result must be same-frame RGBA8 proxies; zero HDR residual preserves native FP16.')
    files['hud_guard.inl'] = hud
    return files


def main():
    root = Path(__file__).resolve().parent
    source, dest = root/'native-repaired', root/'native-hdr'
    if dest.exists():
        raise RuntimeError('Preserve the existing HDR build; move it to a versioned backup before rebuilding')
    repaired = json.loads((root/'repaired-build.json').read_text(encoding='utf-8-sig'))
    for name, key in (('nvngx.dll','worker_sha256'), ('nvngx_dlssnr.dll','runtime_sha256'),
                      ('dlss5-feed-host64.cpp','source_sha256')):
        if digest(source/name) != repaired[key]:
            raise RuntimeError('Repaired source/build integrity mismatch: '+name)
    names = ('dlss5-feed-host64.cpp','hdr_display.h','hdr_present.inl','hdr_shaders.h','hud_guard.inl')
    inputs = {name:digest(source/name) for name in names}
    patched = patch_sources({name:(source/name).read_text(encoding='utf-8-sig') for name in names})
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp','*.log'))
    for name, text in patched.items():
        (dest/name).write_text(text,encoding='utf-8-sig')
    shutil.copy2(root/'hdr_runtime.inl',dest/'hdr_runtime.inl')
    command = root/'Build-HDR.cmd'
    command.write_text((root/'Build-Repaired.cmd').read_text().replace(str(source),str(dest)),encoding='utf-8')
    with (root/'hdr-build.log').open('wb') as log:
        result = subprocess.run(['cmd.exe','/d','/c',str(command)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:
        raise RuntimeError('HDR build failed; inspect hdr-build.log')
    record = dict(worker_sha256=digest(dest/'nvngx.dll'),runtime_sha256=digest(dest/'nvngx_dlssnr.dll'),
        source_sha256=digest(dest/'dlss5-feed-host64.cpp'),inputs=inputs,
        patched={name:digest(dest/name) for name in (*names,'hdr_runtime.inl')},
        staging_sha256=digest(Path(__file__)))
    (root/'hdr-build.json').write_text(json.dumps(record,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
