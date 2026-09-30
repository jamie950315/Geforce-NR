"""Isolated daily-session ownership, preferences, and authenticated stop control."""
from pathlib import Path
import json
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import time
import uuid
from application_windows import enumerate_application_windows
from processing_support import NR_HEIGHTS
from appearance_presets import (APPEARANCE_PRESETS, appearance_cli_args, preset_config,
                                strict_json_loads, validate_appearance_config)
from shared_json import read_json

DEFAULTS = dict(nr_height=720, flow_width=1280, flow_grid=2, flow_preset='fast', mode='nr', mask_profile='custom', hdr=False, hdr_mapping='color-preserving', hdr_queued=False, hold_identical_frames=False)
CHOICES = dict(nr_height=NR_HEIGHTS, flow_width=(320, 640, 960, 1280),
               flow_grid=(2, 4), flow_preset=('fast', 'medium', 'slow'), mode=('guard', 'nr', 'bypass'),
               mask_profile=('custom', 'cyberpunk'), hdr=(False, True), hdr_mapping=('legacy','color-preserving'), hdr_queued=(False, True), hold_identical_frames=(False,True))


def validated(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Preferences must contain only the supported settings')
    for key, options in CHOICES.items():
        if type(value[key]) is not type(DEFAULTS[key]) or value[key] not in options:
            raise ValueError('Unsupported setting: ' + key)
    if value['hdr_queued'] and (not value['hdr'] or value['hdr_mapping'] != 'color-preserving'):
        raise ValueError('Queued HDR + capture requires HDR with color-preserving mapping')
    if value['hold_identical_frames'] and value['hdr'] and not value['hdr_queued']:
        raise ValueError('Hold identical HDR frames requires queued HDR + capture')
    return dict(value)


def atomic_json(path, value):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
        # Windows can briefly refuse replacement during concurrent snapshot
        # reads, even with delete-sharing. Keep replacement atomic and bound
        # only the observed sharing/access-denied case; never rewrite in place.
        deadline = time.monotonic()+.5
        while True:
            try:
                tmp.replace(path)
                break
            except OSError as exc:
                if sys.platform != 'win32' or getattr(exc, 'winerror', None) not in (5, 32) or time.monotonic() >= deadline:
                    raise
                time.sleep(.01)
    finally:
        tmp.unlink(missing_ok=True)


def migrate_settings(value):
    if isinstance(value,dict) and 'hold_identical_frames' not in value:
        value=dict(value,hold_identical_frames=False)
    if isinstance(value, dict) and 'hdr_queued' not in value:
        value = dict(value, hdr_queued=False)
    if isinstance(value, dict) and 'hdr_mapping' not in value:
        value = dict(value, hdr_mapping='legacy')
    if isinstance(value, dict) and 'hdr' not in value:
        value = dict(value, hdr=False)
    if isinstance(value, dict) and set(value) == set(DEFAULTS)-{'mask_profile'}:
        value = validated(dict(value, mask_profile='cyberpunk' if value['mode'] == 'guard' else 'custom'))
        if value['mode'] == 'guard':
            value['mode'] = 'nr'
        return value
    return validated(value)


class DailyController:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.appearance_file = self.root / 'nr-appearance.json'
        self.appearance_settings = (validate_appearance_config(read_json(
            self.appearance_file, loads=strict_json_loads))
            if self.appearance_file.exists() else preset_config('clean'))
        self.preference_file = self.root / 'daily-settings.json'
        if self.preference_file.exists():
            previous = read_json(self.preference_file)
            self.settings = migrate_settings(previous)
            if self.settings != previous:
                backup = self.root/('daily-settings-before-static-stable.json' if 'hold_identical_frames' not in previous and 'hdr_queued' in previous
                                    else 'daily-settings-before-hdr-queued.json' if 'hdr_queued' not in previous
                                    else 'daily-settings-before-hdr-color.json' if 'hdr' in previous
                                    else 'daily-settings-before-hdr.json' if 'mask_profile' in previous
                                    else 'daily-settings-before-optional-mask.json')
                if not backup.exists():
                    atomic_json(backup, previous)
                atomic_json(self.preference_file, self.settings)
        else:
            self.settings = dict(DEFAULTS)
        self.process = None
        self.chain = None
        self.run = None
        self.stop_pending = False
        self.stop_sent = False
        self.state = 'idle'
        self.detail = 'Choose an application window, then start.'
        self.launch_log = None
        self.metrics = {}
        self.owner_token = None
        sys.path.insert(0, str(self.root.parent / 'gfn-nvofa-lab-20260920'))
        from gfn_core.windows import Win32
        self.win = Win32()

    @property
    def busy(self):
        chain = getattr(self, 'chain', None)
        return bool((chain is not None and chain.busy) or
                    (self.process is not None and self.process.poll() is None))

    def list_targets(self):
        result = []
        for target in enumerate_application_windows(self.win):
            try:
                _, _, width, height = self.win.rect(target.hwnd)
            except (OSError, RuntimeError):
                continue
            result.append(dict(target.to_dict(), width=width, height=height))
        return result

    def save_settings(self, settings):
        value = validated(settings)
        if self.busy:
            raise RuntimeError('Stop the current session before changing settings')
        atomic_json(self.preference_file, value)
        self.settings = value
        self.detail = 'Preferences saved for future launches.'

    def save_appearance(self, config):
        value = validate_appearance_config(config)
        if self.busy:
            raise RuntimeError('Stop the current session before changing appearance')
        atomic_json(self.appearance_file, value)
        self.appearance_settings = value
        self.detail = 'Appearance saved for future launches.'

    def _current_target(self, target):
        current = next((t for t in self.list_targets() if
            (t['hwnd'], t['pid'], t['created'], t.get('exe')) ==
            (target['hwnd'], target['pid'], target['created'], target.get('exe'))), None)
        if current is None or current['title'] != target['title'] or self.win.u.IsIconic(current['hwnd']):
            raise RuntimeError('The selected window changed, closed, or was minimized. Restore it and refresh.')
        if (current['width'], current['height']) != (target['width'], target['height']):
            raise RuntimeError('The selected window size changed. Refresh the window list before starting.')
        return current

    def load_mask_profile(self, target):
        from mask_profiles import load_profile
        return load_profile(self.root, target)

    def mask_status(self, target, settings):
        value = validated(settings)
        if value['mode'] == 'bypass':
            return dict(usable=True, detail='HUD Mask is not used in bypass mode.')
        enabled = value['mode'] == 'guard'
        if not target:
            return dict(usable=not enabled, detail='Choose an application window to inspect its mask profile.')
        prefix = 'Mask enabled. ' if enabled else 'Mask off. '
        try:
            if value['mask_profile'] == 'cyberpunk':
                if '2077' not in target['title'] or (target['width'], target['height']) != (2560, 1440):
                    raise ValueError('This preset requires Cyberpunk 2077 at 2560 x 1440; draw custom regions instead.')
                from mask_profiles import validate_mask
                validate_mask(self.root/'cyberpunk-1440p.hgm', 2560, 1440)
                return dict(usable=True, detail=prefix+'Built-in gameplay preset is available. Menus and captions may need a custom mask.')
            profile = self.load_mask_profile(target)
            count = len(profile['rectangles']) if profile else 0
            if count:
                detail = f'{count} saved region(s) for {target["width"]} x {target["height"]}.'
            else:
                detail = 'No saved regions for this window and size. Draw regions before enabling the mask.'
            return dict(usable=not enabled or count > 0, detail=prefix+detail)
        except (OSError, ValueError) as exc:
            return dict(usable=not enabled, detail=prefix+'Profile unavailable: '+str(exc))

    def save_mask_profile(self, target, rectangles):
        from mask_profiles import save_profile
        if self.busy:
            raise RuntimeError('Stop processing before editing the mask')
        current = self._current_target(target)
        if (current['width'], current['height']) != (target['width'], target['height']):
            raise ValueError('Window size changed. Refresh and capture a new preview before saving.')
        return save_profile(self.root, target, rectangles)

    def capture_target(self, target):
        from window_preview import capture_rectangle
        if self.busy:
            raise RuntimeError('Stop processing before capturing a mask preview')
        for folder in (self.root, self.root.parent/'gfn-nr-core', self.root.parent/'gfn-nvofa-lab-20260920',
                       self.root.parent/'gfn-hud-live-20260921-7b03'):
            if (folder/'active.json').exists():
                raise RuntimeError('Stop the active renderer before capturing an unprocessed preview')
        current = self._current_target(target)
        if (current['width'], current['height']) != (target['width'], target['height']):
            raise ValueError('Window size changed. Refresh the window list first.')
        self.win.u.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.win.u.SetForegroundWindow.restype = wintypes.BOOL
        if self.win.u.GetForegroundWindow() != current['hwnd']:
            self.win.u.SetForegroundWindow(current['hwnd'])
        time.sleep(.25)
        if self.win.u.GetForegroundWindow() != current['hwnd']:
            raise RuntimeError('The window lost foreground; no preview was captured')
        x, y, width, height = self.win.rect(current['hwnd'])
        if (width, height) != (target['width'], target['height']):
            raise ValueError('Window size changed during capture. Refresh and capture again.')
        preview = capture_rectangle(x, y, width, height)
        self._current_target(current)
        if (self.win.u.GetForegroundWindow() != current['hwnd']
                or self.win.rect(current['hwnd']) != (x, y, width, height)):
            raise RuntimeError('The window changed during capture; preview discarded')
        return dict(width=width, height=height, ppm=preview)

    def start_chiaki_chain(self, target=None, appearance_config=None, hold_identical_frames=False):
        if self.busy:
            raise RuntimeError('This panel already owns a running session')
        appearance = validate_appearance_config(self.appearance_settings if appearance_config is None else appearance_config)
        current = self._current_target(target) if target is not None else None
        from chain_controller import ChainController
        chain = ChainController(self.root, self.win)
        # Retain ownership even if start raises after partially launching, so
        # the panel can still poll cleanup and request an authenticated stop.
        self.chain = chain
        chain.start(current, appearance_config=appearance, hold_identical_frames=hold_identical_frames)

    def start(self, target, settings, *, persist=True, fps=120, panel_owner=None,
              appearance_preset='inherited', appearance_config=None):
        if self.busy:
            raise RuntimeError('This panel already owns a running session')
        if type(fps) is not int or fps not in (60, 120):
            raise ValueError('FPS must be 60 or 120')
        if type(persist) is not bool:
            raise ValueError('Preference persistence must be a boolean')
        appearance = validate_appearance_config(appearance_config) if appearance_config is not None else None
        if appearance is None and (appearance_preset not in APPEARANCE_PRESETS or appearance_preset == 'custom'):
            raise ValueError('Unsupported appearance preset or missing custom configuration')
        appearance_args = (appearance_cli_args(appearance) if appearance is not None else
                           ['--appearance-preset', appearance_preset])
        if panel_owner is not None and (not isinstance(panel_owner, tuple) or len(panel_owner) != 2
                or any(type(part) is not int or part <= 0 for part in panel_owner)):
            raise ValueError('Panel owner must be a positive PID and process creation identity')
        self.chain = None
        value = validated(settings)
        current = self._current_target(target)
        if value['hold_identical_frames']:
            from static_support import verify_static_build
            verify_static_build(self.root)
        if value['hdr']:
            from hdr_support import require_hdr_display
            extra = {'static_stable':True} if value['hold_identical_frames'] else {}
            require_hdr_display(self.root, current['hwnd'], value['hdr_mapping'],
                                queued=value['hdr_queued'], capture_queued=value['hdr_queued'], **extra)
        if value['mode'] == 'guard':
            from mask_profiles import build_mask, validate_mask
            if value['mask_profile'] == 'cyberpunk':
                if '2077' not in current['title'] or (current['width'], current['height']) != (2560, 1440):
                    raise ValueError('The built-in preset requires Cyberpunk 2077 at 2560x1440. Draw custom regions instead.')
                mask = self.root/'cyberpunk-1440p.hgm'
            else:
                profile = self.load_mask_profile(current)
                if not profile or not profile['rectangles']:
                    raise ValueError('No custom regions for this window and size. Draw and save regions, or turn off HUD Mask.')
                mask = build_mask(self.root, current)
            validate_mask(mask, current['width'], current['height'])
        for folder in (self.root, self.root.parent/'gfn-nr-core', self.root.parent/'gfn-nvofa-lab-20260920',
                       self.root.parent/'gfn-hud-live-20260921-7b03'):
            if (folder/'active.json').exists():
                raise RuntimeError('Another controller is active; it has been preserved. Stop it first.')
        if persist:
            self.save_settings(value)
            if appearance is not None:
                self.save_appearance(appearance)
        name = 'daily-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        self.run = self.root/'runs'/name
        self.metrics = {}
        self.stop_pending = self.stop_sent = False
        self.owner_token = uuid.uuid4().hex
        owner_created = self.win.identity(os.getpid())[1]
        python = self.root.parent/'gfn-nr-core/.venv/Scripts/pythonw.exe'
        args = [str(python), str(self.root/'live_run.py'), '--name', name,
                '--hwnd', str(current['hwnd']), '--mode', value['mode'], '--seconds', '0', '--daily',
                '--fps', str(fps),
                '--owner-pid', str(os.getpid()), '--owner-created', str(owner_created), '--owner-token', self.owner_token,
                '--target-pid', str(current['pid']), '--target-created', str(current['created']),
                '--target-title', current['title'], '--target-width', str(current['width']),
                '--target-height', str(current['height']),
                '--height', str(value['nr_height']), '--flow-width', str(value['flow_width']),
                '--flow-grid', str(value['flow_grid']), '--flow-preset', value['flow_preset']]
        args += appearance_args
        if panel_owner is not None:
            args += ['--panel-pid', str(panel_owner[0]), '--panel-created', str(panel_owner[1])]
        if value['mode'] == 'guard':
            args += ['--mask', str(mask)]
        if value['hdr']:
            args += ['--hdr', '--hdr-mapping', value['hdr_mapping']]
        if value['hdr_queued']:
            args += ['--queued-hdr', '--capture-queued-hdr']
        if value['hold_identical_frames']:
            args += ['--hold-identical-frames']
        # This log is created outside the run, which the launcher creates exclusively.
        self.launch_log = self.root/'runs'/(name + '-launch.log')
        self.launch_log.parent.mkdir(exist_ok=True)
        with self.launch_log.open('wb') as log:
            self.process = subprocess.Popen(args, cwd=self.root, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.state, self.detail = 'starting', 'Verifying the mainline build and initializing the GPU...'
        try:
            self.win.u.SetForegroundWindow.argtypes = [wintypes.HWND]
            self.win.u.SetForegroundWindow.restype = wintypes.BOOL
            if not self.win.u.SetForegroundWindow(current['hwnd']):
                raise RuntimeError('Windows declined foreground activation')
        except Exception:
            self.detail += ' Switch to the application window to resume processing.'

    def stop(self):
        if getattr(self, 'chain', None) is not None:
            self.chain.stop()
            return
        if self.busy:
            self.stop_pending = True
            self.state, self.detail = 'stopping', 'Waiting for the controller and GPU worker to exit safely...'
            self._send_stop()

    def _send_stop(self):
        if not self.stop_pending or self.stop_sent or not self.run or not (self.run/'active.json').exists():
            return
        try:
            session = read_json(self.run/'active.json')
            pointer = read_json(self.root/'active.json')
        except FileNotFoundError:
            # Initialization or teardown can remove either ownership record.
            return
        control = Path(session['control']).resolve()
        if (pointer.get('owner_token') != self.owner_token or not self.owner_token
                or Path(pointer['run']).resolve() != self.run.resolve()
                or session['pid'] != pointer['pid']
                or control.parent != (self.run/'logs').resolve()):
            raise RuntimeError('Stop target identity mismatch; no foreign process is touched')
        atomic_json(control, dict(token=session['token'], id=uuid.uuid4().hex, action='stop'))
        self.stop_sent = True

    def poll(self):
        if getattr(self, 'chain', None) is not None:
            return dict(self.chain.poll(), chain=True)
        end_reason = None
        if self.process:
            if self.run.exists():
                files = list((self.run/'logs').glob('*.metrics.json'))
                if len(files) == 1:
                    self.metrics = read_json(files[0])
            if self.busy:
                self._send_stop()
                if not self.stop_pending and self.metrics:
                    self.state = 'suspended' if self.metrics.get('suspended') else 'running'
                    self.detail = ('Paused while another window is foreground. Return to the selected window to resume.'
                        if self.state == 'suspended' else 'Processing the selected window. Ctrl+Alt+Q stops; Ctrl+Alt+F9 opens this panel.')
                    if self.state == 'running' and self.metrics.get('settings', {}).get('bypass'):
                        self.detail = 'Bypass is active: showing the original source. Ctrl+Alt+F8 toggles NR.'
            else:
                outcome = self.run/'outcome.json'
                result = read_json(outcome) if outcome.exists() else {}
                end_reason = result.get('state')
                if self.process.returncode == 0 and result.get('exit_code') == 0:
                    self.state = 'stopped'
                    self.detail = {
                        'target_resized': 'Application window size changed. Refresh the window list before starting again.',
                        'target_closed': 'The selected application window closed. Open an application and refresh the window list.',
                    }.get(end_reason, 'Session ended: ' + result.get('state', 'stopped'))
                else:
                    warnings = self.metrics.get('warnings', [])
                    detail = '; '.join(warnings[-3:])
                    if not detail:
                        detail = {
                            'vram_pressure': 'Stopped because GPU memory became too low. Close other GPU-heavy apps before restarting.',
                            'worker_exit_error': 'The native worker exited unexpectedly. Open the run folder for diagnostics.',
                            'cleanup_error': 'The controller reported a shutdown error. Inspect the run folder before restarting.',
                        }.get(result.get('state'), '')
                    if not detail and self.launch_log.exists():
                        lines = self.launch_log.read_text(encoding='utf-8', errors='replace').strip().splitlines()
                        detail = (lines[-1] + ' Open the run folder for the launch log.') if lines else ''
                    self.state, self.detail = 'error', detail or 'The controller could not start. Open the run folder for details.'
        shape = lambda value: ' x '.join(map(str, value)) if value else '—'
        geometry = 'NR: ' + shape(self.metrics.get('processing_size')) + '   Flow: ' + shape(self.metrics.get('flow_input_size')) + '   Output: ' + shape(self.metrics.get('output_size'))
        processing = self.busy and not self.metrics.get('suspended') and not self.metrics.get('settings', {}).get('bypass')
        evidence = self.run if self.run and self.run.exists() else (self.launch_log.parent if self.launch_log and self.launch_log.exists() else None)
        hdr_status = 'SDR'
        if self.run and (self.run/'manifest.json').exists():
            manifest = read_json(self.run/'manifest.json')
            if manifest.get('hdr'):
                color = read_json(self.run/'color.json') if (self.run/'color.json').exists() else {}
                hdr_status = ('HDR scRGB active' if self.busy and self.state == 'running' and color.get('active') is True
                              else 'HDR paused' if self.busy and self.state == 'suspended'
                              else 'HDR initializing' if self.busy else 'HDR stopped')
                hdr_status += ' / '+manifest.get('hdr_mapping','legacy')
                if manifest.get('hdr_capture_queued'):
                    hdr_status += ' / queued HDR + capture'
        return dict(state=self.state, detail=self.detail, end_reason=end_reason, hdr_status=hdr_status,
                    run=str(evidence) if evidence else None,
                    geometry=geometry, nr_confirmed=bool(processing and self.metrics.get('nr_confirmed')),
                    hardware_flow_active=bool(processing and self.metrics.get('hardware_flow_active')))
