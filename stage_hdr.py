"""Build isolated, fail-closed HDR output from the attested repaired worker."""
import hashlib
import argparse
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


def build_kind(mapping, queued=False):
    if mapping not in ('legacy', 'color-preserving'):
        raise ValueError('Unknown HDR mapping')
    if queued and mapping != 'color-preserving':
        raise ValueError('Queued HDR requires color-preserving mapping')
    return ('hdr-color' if mapping == 'color-preserving' else 'hdr') + ('-queued' if queued else '')


def patch_queued_tail(source, present):
    """Extend the existing single-queue SDR tail contract to ordinary HDR frames."""
    source = patch_once(source, 'static bool PresentHdr(VideoState &v, bool bypass);',
        'static bool PresentHdr(VideoState &v, bool bypass, UINT64 *submitted = nullptr);\n'
        'static bool HdrQueuedTailAllowed();')
    source = patch_once(source, 'if (g_hdr_capture) return PresentHdr(v, false);',
        'if (g_hdr_capture) return PresentHdr(v, false, submitted);')
    source = patch_once(source,
        'defer_tail = !g_hdr_capture && warmup_done && h.feature != nullptr &&',
        'defer_tail = (!g_hdr_capture || HdrQueuedTailAllowed()) && warmup_done && h.feature != nullptr &&')
    present = patch_once(present, 'static bool PresentHdr(VideoState &v, bool bypass)\n{',
        '''static bool HdrQueuedTailAllowed()
{
    // FG has a separate presenter. Ordinary HDR shares motion/NR's h.queue.
    return !FgRequested();
}

static bool PresentHdr(VideoState &v, bool bypass, UINT64 *submitted)
{
    if (submitted) *submitted = 0;''')
    present = patch_once(present, '    const bool framegen = FgRequested() && !bypass;',
        '''    const bool framegen = FgRequested() && !bypass;
    if (submitted && (bypass || !HdrQueuedTailAllowed()))
        return FailGpuWork("hdr-tail", "ineligible-deferred-frame", E_FAIL);''')
    present = patch_once(present,
        '    const auto fence = EndCommands();\n    if (!WaitFenceValue(h.fence, fence, 2000, "hdr-present"))',
        '''    const auto fence = EndCommands();
    if (submitted) *submitted = fence;
    // h.queue is shared with motion and NR. Waiting for this later fence also
    // retires their resources; no next-frame capture or descriptor reuse can
    // occur before return. A failed wait retains the existing fail-closed path.
    if (!WaitFenceValue(h.fence, fence, submitted ? 60000 : 2000, "hdr-present"))''')
    present = patch_once(present,
        '    // The same status reading as the SDR path: a mode change is a SUCCESS',
        '''    // Opt-in HDR proof may submit a synchronous readback below, but only
    // after this fence has retired. The caller retains this original token.
    static bool queued_reported = false;
    if (submitted && !queued_reported) {
        Log("[hdr-tail] queued motion/NR retired at present fence %llu", fence);
        queued_reported = true;
    }
    // The same status reading as the SDR path: a mode change is a SUCCESS''')
    return source, present


def patch_sources(files, mapping='legacy', queued=False):
    build_kind(mapping, queued)
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
    if queued:
        source, present = patch_queued_tail(source, present)
        files['dlss5-feed-host64.cpp'] = source
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
    if mapping == 'color-preserving':
        shader = files['hdr_shaders.h']
        shader = patch_once(shader, '#pragma once', '#pragma once\n#include "hdr_color_math.h"')
        tail = '"float Peak(float3 x) { return max(0, max(x.r, max(x.g, x.b))); }\\n"'
        shader = patch_once(shader, tail, tail+' \\\n    GFN_HDR_COLOR_FUNCTIONS')
        shader = patch_once(shader,
            'if(isFloat) c=float4(ToSrgb(max(c.rgb,0)/(white+Peak(c.rgb))),1);',
            'if(isFloat) { float3 gamut=ProxyGamut(c.rgb); c=float4(ToSrgb(gamut/(white+Peak(gamut))),1); }')
        shader = patch_once(shader,
            'original+(white+Peak(original))*clamp(b-a,-.25,.25)',
            'original+(white+Peak(ProxyGamut(original)))*LimitEdit(b-a)')
        files['hdr_shaders.h'] = shader
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mapping', choices=['legacy','color-preserving'], default='legacy')
    ap.add_argument('--queued', action='store_true', help='Build the isolated color-preserving HDR queued-tail experiment')
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    kind = build_kind(args.mapping, args.queued)
    source, dest = root/'native-repaired', root/('native-'+kind)
    if dest.exists():
        raise RuntimeError('Preserve the existing HDR build; move it to a versioned backup before rebuilding')
    repaired = json.loads((root/'repaired-build.json').read_text(encoding='utf-8-sig'))
    for name, key in (('nvngx.dll','worker_sha256'), ('nvngx_dlssnr.dll','runtime_sha256'),
                      ('dlss5-feed-host64.cpp','source_sha256')):
        if digest(source/name) != repaired[key]:
            raise RuntimeError('Repaired source/build integrity mismatch: '+name)
    names = ('dlss5-feed-host64.cpp','hdr_display.h','hdr_present.inl','hdr_shaders.h','hud_guard.inl')
    inputs = {name:digest(source/name) for name in names}
    patched = patch_sources({name:(source/name).read_text(encoding='utf-8-sig') for name in names}, args.mapping, args.queued)
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp','*.log'))
    for name, text in patched.items():
        (dest/name).write_text(text,encoding='utf-8-sig')
    shutil.copy2(root/'hdr_runtime.inl',dest/'hdr_runtime.inl')
    if args.mapping == 'color-preserving':
        shutil.copy2(root/'hdr_color_math.h',dest/'hdr_color_math.h')
    command = root/('Build-'+kind.upper()+'.cmd')
    command.write_text((root/'Build-Repaired.cmd').read_text().replace(str(source),str(dest)),encoding='utf-8')
    with (root/(kind+'-build.log')).open('wb') as log:
        result = subprocess.run(['cmd.exe','/d','/c',str(command)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:
        raise RuntimeError('HDR build failed; inspect hdr-build.log')
    extra = ('hdr_color_math.h',) if args.mapping == 'color-preserving' else ()
    record = dict(mapping=args.mapping,queued=args.queued,worker_sha256=digest(dest/'nvngx.dll'),runtime_sha256=digest(dest/'nvngx_dlssnr.dll'),
        source_sha256=digest(dest/'dlss5-feed-host64.cpp'),inputs=inputs,
        patched={name:digest(dest/name) for name in (*names,'hdr_runtime.inl',*extra)},
        staging_sha256=digest(Path(__file__)))
    (root/(kind+'-build.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
