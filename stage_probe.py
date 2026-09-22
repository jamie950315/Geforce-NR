"""Build a separate worker with bounded capture-stage diagnostics."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'gfn-nvofa-lab-20260920/logs/hud-guard-20260921-r1/engine/native'
DEST=ROOT/'native-probe'
if DEST.exists():raise RuntimeError('Preserve existing diagnostic build')
shutil.copytree(SOURCE,DEST,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp'))
p=DEST/'dlss5-feed-host64.cpp'
s=p.read_text(encoding='utf-8-sig')
def replace(old,new):
    global s
    if s.count(old)!=1:raise RuntimeError('Ambiguous patch anchor: '+old[:70])
    s=s.replace(old,new,1)
replace('struct GfnWgcSignal {','''struct GfnWgcSignal {
    std::atomic<UINT64> arrivals{0}, previous_qpc{0};''')
replace('''        s->arrival_token = s->pool.FrameArrived([wake](auto const&, auto const&) {
            SetEvent(wake->event);
        });''','''        s->arrival_token = s->pool.FrameArrived([wake](auto const&, auto const&) {
            LARGE_INTEGER now; QueryPerformanceCounter(&now);
            const UINT64 previous = wake->previous_qpc.exchange(now.QuadPart);
            ++wake->arrivals;
            SetEvent(wake->event);
            const double gap = previous ? (now.QuadPart-previous)*1000.0/g_qpf.QuadPart : 0;
            if (gap > 40) Log("[capture-diag] callback-gap-ms=%.3f qpc=%llu arrivals=%llu", gap, (UINT64)now.QuadPart, (UINT64)wake->arrivals.load());
        });''')
replace('''    g_capture_visual_changed = false;
    const HMONITOR monitor = MonitorFromWindow(g_wgc_hwnd, MONITOR_DEFAULTTONEAREST);''','''    g_capture_visual_changed = false;
    const double diag_start = PhaseNow();
    const HMONITOR monitor = MonitorFromWindow(g_wgc_hwnd, MONITOR_DEFAULTTONEAREST);''')
replace('''        g_capture_display = QueryHdrDisplay(monitor);
        last_mode_query = GetTickCount64();''','''        const double query_start = PhaseNow();
        g_capture_display = QueryHdrDisplay(monitor);
        const double query_ms = PhaseNow()-query_start;
        if (query_ms > 5) Log("[capture-diag] hdr-query-ms=%.3f qpc-ms=%.3f", query_ms, query_start);
        last_mode_query = GetTickCount64();''')
replace('''        const double t_acq = PhaseNow();
        auto frame = g_wgc->pool.TryGetNextFrame();''','''        const double t_acq = PhaseNow();
        if (t_acq-diag_start > 5) Log("[capture-diag] pre-acquire-ms=%.3f", t_acq-diag_start);
        const UINT64 diag_arrivals = g_wgc->wake->arrivals.load();
        auto frame = g_wgc->pool.TryGetNextFrame();''')
replace('''        PhaseAdd(PH_ACQ, t_acq);
        // Nothing new: the window has not redrawn.''','''        PhaseAdd(PH_ACQ, t_acq);
        const double diag_acquire_ms = PhaseNow()-t_acq;
        if (diag_acquire_ms > 35) Log("[capture-diag] acquire-ms=%.3f arrivals-before=%llu after=%llu frame=%u", diag_acquire_ms, diag_arrivals, (UINT64)g_wgc->wake->arrivals.load(), frame != nullptr ? 1u : 0u);
        // Nothing new: the window has not redrawn.''')
p.write_text(s,encoding='utf-8-sig')
cmd=ROOT/'Build-Probe.cmd'
cmd.write_text('@echo off\ncall "C:\\Program Files\\Microsoft Visual Studio\\18\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul\nif errorlevel 1 exit /b 1\ncd /d "'+str(DEST)+'"\ncl /nologo /utf-8 /O2 /EHsc /W3 /MD /std:c++17 /Iinclude /Isrc dlss5-feed-host64.cpp spout_bridge.cpp /Fe:nvngx.dll /link lib\\Windows_x86_64\\x64\\nvsdk_ngx_d.lib SpoutDX.lib version.lib kernel32.lib user32.lib gdi32.lib advapi32.lib ole32.lib d3d11.lib d3d12.lib dxgi.lib d3dcompiler.lib WindowsApp.lib dwmapi.lib\nexit /b %errorlevel%\n',encoding='utf-8')
with (ROOT/'probe-build.log').open('wb') as log:
    r=subprocess.run(['cmd.exe','/d','/c',str(cmd)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
if r.returncode:raise RuntimeError('Build failed; see probe-build.log')
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
(ROOT/'probe-build.json').write_text(json.dumps(dict(worker_sha256=digest(DEST/'nvngx.dll'),runtime_sha256=digest(DEST/'nvngx_dlssnr.dll'),source_sha256=digest(p)),indent=2),encoding='utf-8')
