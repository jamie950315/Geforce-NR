"""Owned Chiaki/NR/LS session supervision and crash-recovery journal.

The UI owns this supervisor; the supervisor owns NR and the LS process it
starts. Chiaki and console power are never part of shutdown ownership.
"""
from pathlib import Path
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from shared_json import read_json as read


def atomic(path, data):
    from daily_backend import atomic_json
    atomic_json(Path(path), data)


def valid_token(value):
    return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


def alive(win, pid, created):
    try:
        return type(pid) is int and type(created) is int and win.identity(pid)[1] == created
    except (OSError, RuntimeError):
        return False


def job_path(root, value):
    path = Path(value).resolve()
    if path.parent != (Path(root)/'runs').resolve() or not path.name.startswith('chiaki-chain-'):
        raise RuntimeError('Invalid chain recovery folder; preserved')
    return path


class ChainController:
    def __init__(self, root, win):
        self.root = Path(root).resolve()
        self.win = win
        self.process = None
        self.job = None
        self.token = None
        self.last = dict(state='idle', detail='Choose Chiaki to start the complete playback chain.',
                         geometry='Not running', nr_confirmed=False, hardware_flow_active=False)

    @property
    def busy(self):
        return self.process is not None and self.process.poll() is None

    def start(self, target):
        if self.busy:
            raise RuntimeError('This panel already owns a Chiaki chain')
        python = self.root.parent/'gfn-nr-overlay/.venv/Scripts/pythonw.exe'
        if not python.is_file():
            raise RuntimeError('The Windows overlay Python runtime is required for Chiaki + LS')
        self.token = uuid.uuid4().hex
        self.job = self.root/'runs'/('chiaki-chain-'+time.strftime('%Y%m%d-%H%M%S')+'-'+self.token[:8])
        self.job.mkdir(parents=True)
        request = dict(token=self.token, target=target, owner_pid=os.getpid(),
                       owner_created=self.win.identity(os.getpid())[1])
        atomic(self.job/'request.json', request)
        self.last = dict(state='starting', detail='Checking Chiaki, HDR and Lossless Scaling...',
                         geometry='Preparing physical 1920 x 1080 → 2560 x 1440',
                         nr_confirmed=False, hardware_flow_active=False, run=str(self.job))
        atomic(self.job/'status.json', dict(self.last, token=self.token))
        with (self.job/'supervisor.log').open('wb') as log:
            self.process = subprocess.Popen([str(python), str(self.root/'chain_controller.py'),
                '--job', str(self.job)], cwd=self.root, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def stop(self):
        if self.busy:
            atomic(self.job/'stop.json', dict(token=self.token))
            self.last.update(state='stopping', detail='Stopping LS and NR; restoring the window and preferences...')

    def poll(self):
        if self.job and (self.job/'status.json').exists():
            value = read(self.job/'status.json')
            if value.get('token') != self.token:
                raise RuntimeError('Chain status ownership mismatch')
            self.last = value
        if self.process and not self.busy and self.last.get('state') not in ('stopped', 'error'):
            self.last = dict(self.last, state='error', nr_confirmed=False, hardware_flow_active=False,
                detail='Playback supervisor exited before restoration was confirmed. Start again to recover its journal.')
        return dict(self.last)


def recover(root, native, win, pointer):
    """Restore only a dead supervisor's attested resources, never a live chain."""
    previous = read(pointer)
    if not valid_token(previous.get('token')):
        raise RuntimeError('Invalid chain ownership record; preserved')
    if alive(win, previous.get('pid'), previous.get('created')):
        raise RuntimeError('Another Chiaki chain is active; it has been preserved')
    folder = job_path(root, previous['run'])
    journal = read(folder/'journal.json')
    if journal.get('token') != previous['token']:
        raise RuntimeError('Recovery token mismatch; resources preserved')
    # A child whose supervisor died exits through the normal owner-lifetime check.
    until = time.monotonic()+10
    while (root/'active.json').exists() and time.monotonic() < until:
        current = read(root/'active.json')
        if current.get('owner_token') != journal.get('nr_owner_token'):
            raise RuntimeError('Another NR controller is active; recovery deferred')
        time.sleep(.2)
    if (root/'active.json').exists():
        raise RuntimeError('Previous NR worker is still retiring; recovery deferred')
    if journal.get('ls_process'):
        native.stop_ls(journal['ls_process'])
    if journal.get('ls_config'):
        native.restore_ls_config(journal['ls_config'])
    if journal.get('window'):
        native.restore_window(journal['window'])
    if journal.get('preflight', {}).get('idle_ls'):
        native.reopen_ls(journal['preflight'])
    atomic(folder/'recovery.json', dict(token=previous['token'], restored=True))
    if read(pointer).get('token') == previous['token']:
        pointer.unlink()


def supervise(root, folder):
    import win32gui
    from daily_backend import DailyController, DEFAULTS
    from chiaki_chain_native import NativeChain
    from chiaki_connect import acquire_stream, is_streaming

    request = read(folder/'request.json')
    token = request.get('token')
    if not valid_token(token):
        raise RuntimeError('Invalid chain request token')
    controller = DailyController(root)
    win = controller.win
    native = NativeChain(root, win)
    pointer = root/'chiaki-chain-active.json'
    journal = dict(token=token, pid=os.getpid(), created=win.identity(os.getpid())[1], run=str(folder))
    claimed = False
    ls_process = None
    reason = 'stopped'
    failure = None
    cleanup_errors = []
    last_detail = [None]

    def save(key, value):
        journal[key] = value
        atomic(folder/'journal.json', journal)

    def status(state, detail, snapshot=None):
        if detail != last_detail[0]:
            print(state+': '+detail, flush=True)
            last_detail[0] = detail
        value = dict(token=token, state=state, detail=detail, run=str(folder),
            geometry='Chiaki 1920 x 1080 → NR1080 → LS1 2560 x 1440 → LSFG 2x',
            nr_confirmed=False, hardware_flow_active=False, hdr_status='HDR / Color-preserving / queued',
            chain_target=journal.get('target'))
        if snapshot:
            value.update(nr_confirmed=snapshot.get('nr_confirmed', False),
                         hardware_flow_active=snapshot.get('hardware_flow_active', False))
        atomic(folder/'status.json', value)

    def cancelled():
        if not alive(win, request.get('owner_pid'), request.get('owner_created')):
            return True
        stop = folder/'stop.json'
        return stop.exists() and read(stop).get('token') == token

    def check_cancel():
        if cancelled():
            raise InterruptedError('Playback startup cancelled')

    try:
        if pointer.exists():
            status('starting', 'Recovering the previous interrupted playback session...')
            recover(root, native, win, pointer)
        # Exclusive claim survives crashes. A malformed/foreign claim is never removed.
        atomic(folder/'journal.json', journal)
        with pointer.open('x', encoding='utf-8') as lock:
            json.dump(journal, lock)
        claimed = True
        for path in (root, root.parent/'gfn-nr-core', root.parent/'gfn-nvofa-lab-20260920',
                     root.parent/'gfn-hud-live-20260921-7b03'):
            if (path/'active.json').exists():
                raise RuntimeError('Another NR controller is active; it has been preserved')
        check_cancel()
        target = acquire_stream(win, controller.list_targets, selected=request['target'], cancelled=cancelled,
            status=lambda text: status('starting', text))
        save('target', target)
        check_cancel()
        status('starting', 'Checking the tested HDR playback configuration...')
        preflight = native.preflight(target)
        save('preflight', preflight)
        # Persist every restore record before its first external mutation.
        status('starting', 'Correcting DPI scaling to a physical 1920 x 1080 window...')
        target, window = native.prepare_window(target, lambda value: save('window', value))
        save('window', window)
        check_cancel()
        native.configure_ls(preflight, folder, lambda value: save('ls_config', value))
        check_cancel()
        status('starting', 'Starting NR1080 and hardware optical flow at 60 source FPS...')
        preset = dict(DEFAULTS, nr_height=1080, hdr=True, hdr_mapping='color-preserving', hdr_queued=True)
        controller.start(target, preset, persist=False, fps=60,
                         panel_owner=(request['owner_pid'], request['owner_created']))
        save('nr_run', str(controller.run));save('nr_owner_token', controller.owner_token)
        until = time.monotonic()+30
        while controller.busy and time.monotonic() < until:
            check_cancel()
            snapshot = controller.poll()
            if snapshot.get('nr_confirmed') and snapshot.get('hardware_flow_active'):
                break
            time.sleep(.2)
        else:
            snapshot = controller.poll()
            raise RuntimeError('NR initialization failed: '+snapshot.get('detail', 'No active worker'))
        renderer = controller.metrics['renderer_pid']
        status('starting', 'Starting LS1 + LSFG 2x on the verified NR output...')
        ls_process, ls_record = native.launch_ls(preflight)
        save('ls_process', ls_record)
        # The LS UI may briefly suspend NR. Restore the owned source before binding it.
        until = time.monotonic()+10
        while not any(w['title'] == 'Lossless Scaling' for w in native.windows(ls_record['pid'])):
            check_cancel()
            if ls_process.poll() is not None or time.monotonic() >= until:
                raise RuntimeError('Lossless Scaling did not open its owned control window')
            time.sleep(.1)
        save('ls_ready', native.wait_ls_ready(ls_record))
        native.focus(target)
        until = time.monotonic()+5
        while time.monotonic() < until:
            check_cancel()
            snapshot = controller.poll()
            if snapshot.get('nr_confirmed') and snapshot.get('hardware_flow_active'):
                break
            time.sleep(.1)
        else:
            raise RuntimeError('NR did not resume after the LS control window opened')
        output = native.start_scaling(renderer, ls_record, preflight['monitor_rect'])
        save('outputs', output)
        check_cancel()
        while True:
            if cancelled():
                reason = 'owner_closed' if not alive(win, request['owner_pid'], request['owner_created']) else 'stop_requested'
                break
            snapshot = controller.poll()
            if not controller.busy:
                if snapshot.get('state') == 'error':
                    raise RuntimeError(snapshot.get('detail', 'NR stopped unexpectedly'))
                reason = snapshot.get('end_reason') or 'nr_stopped'
                break
            if ls_process.poll() is not None:
                reason = 'ls_closed'
                break
            scaled = output['ls_output']
            if (not win.u.IsWindow(scaled['hwnd']) or win.pid(scaled['hwnd']) != ls_record['pid']
                    or not win.u.IsWindowVisible(scaled['hwnd'])
                    or list(win32gui.GetWindowRect(scaled['hwnd'])) != list(preflight['monitor_rect'])):
                reason = 'ls_scaling_stopped'
                break
            if not win.u.IsWindow(target['hwnd']) or win.pid(target['hwnd']) != target['pid']:
                reason = 'target_closed'
                break
            native.require_window(target)
            if not is_streaming(target['pid']):
                reason = 'stream_disconnected'
                break
            if win.rect(target['hwnd'])[2:] != (1920, 1080):
                reason = 'target_resized'
                break
            foreground = win.pid(win32gui.GetForegroundWindow())
            if foreground not in (target['pid'], renderer, ls_record['pid']):
                reason = 'foreground_changed'
                break
            if snapshot.get('state') == 'suspended':
                reason = 'capture_suspended'
                break
            status('running', 'Chiaki + NR1080 + LS1 + LSFG 2x active. Ctrl+Alt+Q stops; Ctrl+Alt+F9 opens the panel.', snapshot)
            time.sleep(.5)
    except InterruptedError:
        reason = 'stop_requested'
    except Exception as exc:
        failure = str(exc)
    finally:
        if claimed:
            try:
                status('stopping', 'Stopping owned LS/NR and restoring the window and preferences...')
            except OSError as exc:
                # A failed status publication must never prevent resource cleanup.
                failure = failure or 'Status update failed: '+str(exc)
            if journal.get('ls_process'):
                try:
                    native.stop_ls(journal['ls_process'])
                except Exception as exc:
                    cleanup_errors.append('Lossless Scaling: '+str(exc))
            try:
                if controller.busy:
                    controller.stop()
                    until = time.monotonic()+20
                    while controller.busy and time.monotonic() < until:
                        controller._send_stop();time.sleep(.1)
                    if controller.busy:
                        raise RuntimeError('NR shutdown is still pending; restoration journal retained')
            except Exception as exc:
                cleanup_errors.append('NR: '+str(exc))
            if not controller.busy:
                if journal.get('window'):
                    try:
                        native.restore_window(journal['window'])
                    except Exception as exc:
                        cleanup_errors.append('Chiaki window: '+str(exc))
                if journal.get('ls_config'):
                    try:
                        native.restore_ls_config(journal['ls_config'])
                    except Exception as exc:
                        cleanup_errors.append('LS preferences: '+str(exc))
                if not cleanup_errors and journal.get('preflight', {}).get('idle_ls'):
                    try:
                        native.reopen_ls(journal['preflight'])
                    except Exception as exc:
                        cleanup_errors.append('LS panel: '+str(exc))
            save('cleanup_errors', cleanup_errors)
            if not cleanup_errors and pointer.exists() and read(pointer).get('token') == token:
                pointer.unlink()
        detail = failure or {
            'foreground_changed': 'Playback stopped after switching apps. Window and LS preferences restored; Chiaki stays connected.',
            'stream_disconnected': 'Chiaki disconnected. The playback chain stopped without any console power action.',
            'target_closed': 'The Chiaki window closed. The owned playback chain stopped without any console power action.',
            'owner_closed': 'The panel closed. The owned playback chain was stopped and restored.',
        }.get(reason, 'Playback stopped; window and LS preferences restored. Chiaki stays open; no console sleep command was sent.')
        if cleanup_errors:
            detail += ' Restoration needs attention: '+'; '.join(cleanup_errors)+'. Start again to retry journal recovery.'
        status('error' if failure or cleanup_errors else 'stopped', detail)
        atomic(folder/'outcome.json', dict(token=token, reason=reason, error=failure,
                                         cleanup_errors=cleanup_errors, chiaki_closed_by_supervisor=False))
    return 1 if failure or cleanup_errors else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    folder = job_path(root, args.job)
    # Use physical pixels without changing the user's global display scaling.
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    return supervise(root, folder)


if __name__ == '__main__':
    raise SystemExit(main())
