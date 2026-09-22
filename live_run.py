"""Isolated, version-bound live run; never changes Core/Lab launch defaults."""
import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
LIVE = ROOT.parent / 'gfn-hud-live-20260921-7b03'
sys.path.insert(0, str(LIVE))
from live_hud import verify, LAB, STABLE, NATIVE, load, digest
from gfn_core.config import Appearance, Settings, atomic_json
from gfn_core.engine import Engine
from gfn_core.windows import Win32


class RecordedEngine(Engine):
    owner = None

    def _visibility(self):
        if self.owner and self.win.identity(self.owner[0])[1] != self.owner[1]:
            self.reason = 'owner_closed'
            self.stop.set()
            return True
        previous = self.suspended
        hidden = super()._visibility()
        if previous != hidden:
            self._write_metrics()
        return hidden

    def _command(self, action, data):
        if action == 'panel' and self.owner:
            if self.win.identity(self.owner[0])[1] == self.owner[1]:
                for hwnd in self.win.worker_windows(self.owner[0]):
                    title = ctypes.create_unicode_buffer(256)
                    self.win.u.GetWindowTextW(hwnd, title, len(title))
                    if title.value == 'GFN HUD Guard':
                        self.win.u.ShowWindow(hwnd, 9)
                        self.win.u.SetForegroundWindow.argtypes = [wintypes.HWND]
                        self.win.u.SetForegroundWindow.restype = wintypes.BOOL
                        if not self.win.u.SetForegroundWindow(hwnd):
                            self.warnings.append('Windows declined panel focus; open it from the taskbar')
                        break
            return
        super()._command(action, data)

    def _configure(self):
        super()._configure()
        atomic_json(self.root / 'geometry.json', dict(wgc=self.full, work=self.work,
                     flow=self.gray_shape, window=self.win.rect(self.target.hwnd)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True)
    ap.add_argument('--hwnd', type=int, required=True)
    ap.add_argument('--mode', choices=['bypass', 'nr', 'guard'], required=True)
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--height', type=int, choices=[720, 900, 1080], default=720)
    ap.add_argument('--flow-width', type=int, choices=[320, 640, 960, 1280], default=1280)
    ap.add_argument('--flow-grid', type=int, choices=[2, 4], default=2)
    ap.add_argument('--flow-preset', choices=['fast', 'medium', 'slow'], default='fast')
    ap.add_argument('--mask', type=Path)
    ap.add_argument('--probe-worker', action='store_true')
    ap.add_argument('--fixed-worker', action='store_true')
    ap.add_argument('--overlay-alpha', type=int, choices=[0, 254, 255], default=255)
    ap.add_argument('--gpu-sample-interval', type=int, choices=[2, 600], default=2)
    ap.add_argument('--repaired-worker', action='store_true')
    ap.add_argument('--original-worker', action='store_true')
    ap.add_argument('--live-pair-worker', action='store_true')
    ap.add_argument('--daily', action='store_true')
    ap.add_argument('--owner-pid', type=int)
    ap.add_argument('--owner-created', type=int)
    ap.add_argument('--owner-token')
    a = ap.parse_args()
    if not a.name.replace('-', '').isalnum() or not (5 <= a.seconds <= 600 or (a.daily and a.seconds == 0)):
        raise ValueError('Invalid run name or duration')
    if a.daily and (not a.owner_pid or not a.owner_created or not a.owner_token or len(a.owner_token) != 32 or any(c not in '0123456789abcdef' for c in a.owner_token) or a.live_pair_worker or a.probe_worker or a.fixed_worker or a.original_worker):
        raise ValueError('Daily mode requires an owning UI and the mainline worker')
    if (a.mode == 'guard') != bool(a.mask):
        raise ValueError('Only guard mode requires a mask')
    if a.live_pair_worker and (a.mode != 'guard' or a.seconds > 30):
        raise ValueError('Live-pair readback is limited to short Guard diagnostics')
    if a.gpu_sample_interval != 2 and (a.seconds > 60 or a.mode != 'bypass'):
        raise ValueError('Sampler isolation is limited to short bypass diagnostics')
    integrity = verify()
    native = NATIVE
    if sum((a.probe_worker, a.fixed_worker, a.repaired_worker, a.original_worker, a.live_pair_worker)) > 1:
        raise ValueError('Select only one worker')
    if a.overlay_alpha != 255 and not a.fixed_worker:
        raise ValueError('Opacity experiment requires the repaired diagnostic worker')
    if not a.original_worker:
        kind = 'live-pair' if a.live_pair_worker else ('fixed' if a.fixed_worker else ('probe' if a.probe_worker else 'repaired'))
        native = ROOT / ('native-' + kind)
        build = load(ROOT / (kind + '-build.json'))
        if digest(native/'nvngx.dll') != build['worker_sha256'] or digest(native/'nvngx_dlssnr.dll') != integrity['runtime_sha256']:
            raise RuntimeError('Diagnostic binary integrity mismatch')
        integrity = dict(integrity, worker=str(native/'nvngx.dll'), worker_sha256=build['worker_sha256'], diagnostic=kind != 'repaired', timing_repaired=kind == 'repaired')
    win = Win32()
    launcher_mutex = win.mutex('Local\\Jamie_GFN_HUD_Guard_Launcher')
    for root in (ROOT, LIVE, LAB, STABLE):
        if (root / 'active.json').exists():
            raise RuntimeError('Existing controller preserved: ' + str(root))
    if a.daily and win.identity(a.owner_pid)[1] != a.owner_created:
        raise RuntimeError('Owning UI is unavailable')
    targets = [t for t in win.enumerate() if t.hwnd == a.hwnd and t.title.strip().lower() != 'geforce now']
    if len(targets) != 1 or win.u.IsIconic(a.hwnd):
        raise RuntimeError('Explicit game target is unavailable')
    target = targets[0]
    run = ROOT / 'runs' / a.name
    run.mkdir(parents=True, exist_ok=False)
    os.environ.pop('GFN_LIVE_PAIR_DIR', None)
    os.environ.pop('GFN_LIVE_PAIR_FRAMES', None)
    live_pair = None
    if a.live_pair_worker:
        pair_dir = run / 'live-pairs'
        pair_dir.mkdir(exist_ok=False)
        os.environ['GFN_LIVE_PAIR_DIR'] = str(pair_dir)
        os.environ['GFN_LIVE_PAIR_FRAMES'] = '30,60,90'
        live_pair = dict(directory=str(pair_dir), frames=[30, 60, 90],
                         performance_evidence=False)
    os.environ.pop('GFN_HUD_MASK', None)
    os.environ.pop('GFN_HUD_PROFILE', None)
    os.environ['GFN_DIAG_OVERLAY_ALPHA'] = str(a.overlay_alpha)
    mask = None
    if a.mask:
        mask = dict(path=str(a.mask.resolve()), sha256=digest(a.mask))
        os.environ['GFN_HUD_MASK'] = mask['path']
    appearance = Appearance.from_dict(load(LAB / 'appearance.json'))
    settings = Settings(fps=120, nr_height=a.height, duration=a.seconds,
                        bypass=a.mode == 'bypass', profile_frames=not a.daily,
                        appearance=appearance, pacing='source', capture_wait_ms=16,
                        flow_width=a.flow_width, flow_grid=a.flow_grid, flow_preset=a.flow_preset)
    atomic_json(run / 'manifest.json', dict(target=target.to_dict(), settings=settings.to_dict(),
                mode=a.mode, mask=mask, daily=a.daily,
                owner=dict(pid=a.owner_pid, created=a.owner_created, token=a.owner_token) if a.daily else None,
                live_pair=live_pair, overlay_alpha=a.overlay_alpha, gpu_sample_interval=a.gpu_sample_interval, integrity=integrity, controller_sha256=digest(Path(__file__)),
                dependencies={str(p): digest(p) for p in (LIVE / 'live_hud.py', LAB / 'gfn_core/engine.py', LAB / 'gfn_core/wire.py')}))
    atomic_json(ROOT / 'active.json', dict(run=str(run), pid=os.getpid(), owner_token=a.owner_token))
    atomic_json(ROOT / 'latest.json', dict(run=str(run)))
    try:
        with (run / 'controller.log').open('w', encoding='utf-8', buffering=1) as log:
            sys.stdout = sys.stderr = log
            engine = RecordedEngine(run, target, settings, win)
            if a.daily:
                engine.owner = (a.owner_pid, a.owner_created)
            engine.native = native
            engine.sampler.interval = a.gpu_sample_interval
            rc = engine.run()
            verify()
            atomic_json(run / 'outcome.json', dict(exit_code=rc, state=engine.reason))
            return rc
    finally:
        pointer = ROOT / 'active.json'
        if pointer.exists() and load(pointer).get('pid') == os.getpid():
            pointer.unlink()
        win.k.CloseHandle(launcher_mutex)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        (ROOT / 'launcher-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
