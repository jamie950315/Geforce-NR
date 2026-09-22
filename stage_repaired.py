"""Build the minimal timing repair without diagnostic capture or opacity changes."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'gfn-nvofa-lab-20260920/logs/hud-guard-20260921-r1/engine/native'
DEST=ROOT/'native-repaired'
if DEST.exists():raise RuntimeError('Preserve existing repaired build')
shutil.copytree(SOURCE,DEST,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp'))
shutil.copy2(ROOT/'native_timing.hpp',DEST/'native_timing.hpp')
p=DEST/'dlss5-feed-host64.cpp'
s=p.read_text(encoding='utf-8-sig')
def replace(old,new):
    global s
    if s.count(old)!=1:raise RuntimeError('Ambiguous patch anchor: '+old[:70])
    s=s.replace(old,new,1)
replace('#include <memory>','#include <memory>\n#include "native_timing.hpp"')
replace('''    if (source_qpc && g_qpf.QuadPart > 0 && source_qpc >= g_previous_source_qpc)
    {
        const double source_ms = static_cast<double>(source_qpc) * 1000.0 / g_qpf.QuadPart;
        if (source_ms <= g_frame_stamp.acquired) g_frame_stamp.source_time = source_ms;
    }
    if (source_qpc) g_previous_source_qpc = source_qpc;''','''    std::uint64_t previous = g_previous_source_qpc;
    const auto retained = gfn_timing::RetainSourceTimestamp(source_qpc, g_qpf.QuadPart, previous);
    g_previous_source_qpc = previous;
    g_frame_stamp.source_time = retained.valid ? retained.milliseconds : 0.0;''')
replace('''    const double source_age = age >= 0 && g_frame_stamp.source_time > 0
        ? g_frame_stamp.present_call - g_frame_stamp.source_time : -1.0;''','''    const gfn_timing::RetainedSourceTimestamp retained{g_frame_stamp.source_qpc, g_frame_stamp.source_time, g_frame_stamp.source_time > 0};
    const auto source = gfn_timing::EvaluateSourceAge(retained, fresh ? g_frame_stamp.present_call : 0.0);
    const double source_age = source.state == gfn_timing::SourceState::Invalid ? -1.0 : source.milliseconds;''')
replace('''        "clock=%s fence=%llu color=%ux%u neural=%ux%u output=%ux%u",''','''        "clock=%s fence=%llu color=%ux%u neural=%ux%u output=%ux%u source-state=%s source-delta=%.3f",''')
replace('''        cw, ch, v.nr_small ? v.nr_w : cw, v.nr_small ? v.nr_h : ch, cw, ch);''','''        cw, ch, v.nr_small ? v.nr_w : cw, v.nr_small ? v.nr_h : ch, cw, ch,
        gfn_timing::SourceStateName(source.state), source_age);''')
p.write_text(s,encoding='utf-8-sig')
cmd=ROOT/'Build-Repaired.cmd'
cmd.write_text((SOURCE.parents[1]/'Build-HUD.cmd').read_text().replace(str(SOURCE),str(DEST)),encoding='utf-8')
with (ROOT/'repaired-build.log').open('wb') as log:
    r=subprocess.run(['cmd.exe','/d','/c',str(cmd)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
if r.returncode:raise RuntimeError('Build failed; see repaired-build.log')
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
(ROOT/'repaired-build.json').write_text(json.dumps(dict(worker_sha256=digest(DEST/'nvngx.dll'),runtime_sha256=digest(DEST/'nvngx_dlssnr.dll'),source_sha256=digest(p),source_original_sha256=digest(SOURCE/'dlss5-feed-host64.cpp'),timing_header_sha256=digest(DEST/'native_timing.hpp')),indent=2),encoding='utf-8')
