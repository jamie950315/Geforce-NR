"""Build an opt-in live WGC/NVOFA/HUD same-frame proof worker."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'native-repaired'
DEST = ROOT / 'native-live-pair'
if not SOURCE.is_dir():
    raise RuntimeError('Build native-repaired first; the live-pair probe preserves that base')
if DEST.exists():
    raise RuntimeError('Preserve existing live-pair diagnostic build')
shutil.copytree(SOURCE, DEST, ignore=shutil.ignore_patterns('*.obj', '*.pdb', '*.ilk', '*.exp'))
shutil.copy2(ROOT / 'live_pair_probe.inl', DEST / 'live_pair_probe.inl')
p = DEST / 'dlss5-feed-host64.cpp'
s = p.read_text(encoding='utf-8-sig')

def replace(old, new):
    global s
    if s.count(old) != 1:
        raise RuntimeError('Ambiguous patch anchor: ' + old[:80])
    s = s.replace(old, new, 1)

replace('#include "hud_guard.inl"', '#include "hud_guard.inl"\n#include "live_pair_probe.inl"')
replace('''        ConfigureFgFrame(fh.reserved);
        const double t_frame = PhaseNow();''', '''        ConfigureFgFrame(fh.reserved);
        LivePairResetFrame();
        const double t_frame = PhaseNow();''')
replace('''            const bool nvofa_used = try_nvofa && RunNvofa(v, fh.reset != 0, defer_tail ? &upload_done : nullptr);
            if (gfn_hardware && !gfn_bypass && !nvofa_used) {''', '''            const bool nvofa_used = try_nvofa && RunNvofa(v, fh.reset != 0, defer_tail ? &upload_done : nullptr);
            LivePairSetNvofa(nvofa_used);
            if (gfn_hardware && !gfn_bypass && !nvofa_used) {''')
replace('''        if (!bypass)
        {
            const double t_eval = PhaseNow();''', '''        if (!bypass)
        {
            if (!LivePairSelect(fh.index, fh.pts, source_fresh)) return 9;
            const double t_eval = PhaseNow();''')
replace('''    int hud_slot = -1;
    if (!HudGuardRecord(v, hud_slot)) { AbortCommands(); return false; }
    if (ts) ProfileGpuEnd(PS_EVAL, 4);
    const UINT64 fence = EndCommands();
    HudGuardCommit(hud_slot, fence);''', '''    bool live_pair_sampled = false;
    if (!LivePairBegin(v, live_pair_sampled)) { AbortCommands(); return false; }
    int hud_slot = -1;
    if (!HudGuardRecord(v, hud_slot)) { AbortCommands(); return false; }
    if (!LivePairEnd(v, live_pair_sampled)) { AbortCommands(); return false; }
    if (ts) ProfileGpuEnd(PS_EVAL, 4);
    const UINT64 fence = EndCommands();
    HudGuardCommit(hud_slot, fence);
    if (!LivePairCommit(live_pair_sampled, fence)) return false;''')
replace('''    CloseHudGuard();
    CloseNvofa();''', '''    CloseHudGuard();
    CloseLivePair();
    CloseNvofa();''')
p.write_text(s, encoding='utf-8-sig')

cmd = ROOT / 'Build-Live-Pair.cmd'
base_cmd = ROOT / 'Build-Repaired.cmd'
if not base_cmd.is_file():
    raise RuntimeError('Build-Repaired.cmd is required to preserve the verified build contract')
build_text = base_cmd.read_text(encoding='utf-8').replace(str(SOURCE), str(DEST))
cmd.write_text(build_text, encoding='utf-8')
with (ROOT / 'live-pair-build.log').open('wb') as log:
    result = subprocess.run(['cmd.exe', '/d', '/c', str(cmd)], stdout=log,
                            stderr=subprocess.STDOUT, timeout=180)
if result.returncode:
    raise RuntimeError('Build failed; see live-pair-build.log')

digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
(ROOT / 'live-pair-build.json').write_text(json.dumps({
    'worker_sha256': digest(DEST / 'nvngx.dll'),
    'runtime_sha256': digest(DEST / 'nvngx_dlssnr.dll'),
    'source_sha256': digest(p),
    'source_base_sha256': digest(SOURCE / 'dlss5-feed-host64.cpp'),
    'probe_header_sha256': digest(DEST / 'live_pair_probe.inl'),
    'base': 'native-repaired',
    'scope': 'diagnostic-only same-command-list WGC source/pre-HUD/post-HUD capture',
}, indent=2), encoding='utf-8')
