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

DEFAULTS = dict(nr_height=720, flow_width=1280, flow_grid=2, flow_preset='fast', mode='nr', mask_profile='custom')
CHOICES = dict(nr_height=(720, 900, 1080), flow_width=(320, 640, 960, 1280),
               flow_grid=(2, 4), flow_preset=('fast', 'medium', 'slow'), mode=('guard', 'nr', 'bypass'),
               mask_profile=('custom', 'cyberpunk'))


def validated(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Preferences must contain only the supported settings')
    for key, options in CHOICES.items():
        if type(value[key]) is not type(DEFAULTS[key]) or value[key] not in options:
            raise ValueError('Unsupported setting: ' + key)
    return dict(value)


def atomic_json(path, value):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def migrate_settings(value):
    if isinstance(value, dict) and set(value) == set(DEFAULTS)-{'mask_profile'}:
        value = validated(dict(value, mask_profile='cyberpunk' if value['mode'] == 'guard' else 'custom'))
        if value['mode'] == 'guard':
            value['mode'] = 'nr'
        return value
    return validated(value)


class DailyController:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.preference_file = self.root / 'daily-settings.json'
        if self.preference_file.exists():
            previous = read_json(self.preference_file)
            self.settings = migrate_settings(previous)
            if self.settings != previous:
                backup = self.root/'daily-settings-before-optional-mask.json'
                if not backup.exists():
                    atomic_json(backup, previous)
                atomic_json(self.preference_file, self.settings)
        else:
            self.settings = dict(DEFAULTS)
        self.process = None
        self.run = None
        self.stop_pending = False
        self.stop_sent = False
        self.state = 'idle'
        self.detail = 'Choose a running GFN game, then start.'
        self.launch_log = None
        self.metrics = {}
        self.owner_token = None
        sys.path.insert(0, str(self.root.parent / 'gfn-nvofa-lab-20260920'))
        from gfn_core.windows import Win32
        self.win = Win32()

    @property
    def busy(self):
        return self.process is not None and self.process.poll() is None

    def list_targets(self):
        result = []
        for target in self.win.enumerate():
            if target.title.strip().lower() == 'geforce now':
                continue
            _, _, width, height = self.win.rect(target.hwnd)
            result.append(dict(target.to_dict(), width=width, height=height))
        return result

    def save_settings(self, settings):
        value = validated(settings)
        if self.busy:
            raise RuntimeError('Stop the current session before changing settings')
        atomic_json(self.preference_file, value)
        self.settings = value
        self.detail = 'Preferences saved for future launches.'

    def _current_target(self, target):
        current = next((t for t in self.list_targets() if
            (t['hwnd'], t['pid'], t['created']) == (target['hwnd'], target['pid'], target['created'])), None)
        if current is None or current['title'] != target['title'] or self.win.u.IsIconic(current['hwnd']):
            raise RuntimeError('The selected game changed, closed, or was minimized. Restore it and refresh.')
        if (current['width'], current['height']) != (target['width'], target['height']):
            raise RuntimeError('The selected game size changed. Refresh the game list before starting.')
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
            return dict(usable=not enabled, detail='Choose a game window to inspect its mask profile.')
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
                detail = 'No saved regions for this game and size. Draw regions before enabling the mask.'
            return dict(usable=not enabled or count > 0, detail=prefix+detail)
        except (OSError, ValueError) as exc:
            return dict(usable=not enabled, detail=prefix+'Profile unavailable: '+str(exc))

    def save_mask_profile(self, target, rectangles):
        from mask_profiles import save_profile
        if self.busy:
            raise RuntimeError('Stop processing before editing the mask')
        current = self._current_target(target)
        if (current['width'], current['height']) != (target['width'], target['height']):
            raise ValueError('Game size changed. Refresh and capture a new preview before saving.')
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
            raise ValueError('Game size changed. Refresh the game list first.')
        self.win.u.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.win.u.SetForegroundWindow.restype = wintypes.BOOL
        if self.win.u.GetForegroundWindow() != current['hwnd']:
            self.win.u.SetForegroundWindow(current['hwnd'])
        time.sleep(.25)
        if self.win.u.GetForegroundWindow() != current['hwnd']:
            raise RuntimeError('The game lost foreground; no preview was captured')
        x, y, width, height = self.win.rect(current['hwnd'])
        if (width, height) != (target['width'], target['height']):
            raise ValueError('Game size changed during capture. Refresh and capture again.')
        return dict(width=width, height=height, ppm=capture_rectangle(x, y, width, height))

    def start(self, target, settings):
        if self.busy:
            raise RuntimeError('This panel already owns a running session')
        value = validated(settings)
        current = self._current_target(target)
        if value['mode'] == 'guard':
            from mask_profiles import build_mask, validate_mask
            if value['mask_profile'] == 'cyberpunk':
                if '2077' not in current['title'] or (current['width'], current['height']) != (2560, 1440):
                    raise ValueError('The built-in preset requires Cyberpunk 2077 at 2560x1440. Draw custom regions instead.')
                mask = self.root/'cyberpunk-1440p.hgm'
            else:
                profile = self.load_mask_profile(current)
                if not profile or not profile['rectangles']:
                    raise ValueError('No custom regions for this game and size. Draw and save regions, or turn off HUD Mask.')
                mask = build_mask(self.root, current)
            validate_mask(mask, current['width'], current['height'])
        for folder in (self.root, self.root.parent/'gfn-nr-core', self.root.parent/'gfn-nvofa-lab-20260920',
                       self.root.parent/'gfn-hud-live-20260921-7b03'):
            if (folder/'active.json').exists():
                raise RuntimeError('Another controller is active; it has been preserved. Stop it first.')
        self.save_settings(value)
        name = 'daily-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        self.run = self.root/'runs'/name
        self.metrics = {}
        self.stop_pending = self.stop_sent = False
        self.owner_token = uuid.uuid4().hex
        owner_created = self.win.identity(os.getpid())[1]
        python = self.root.parent/'gfn-nr-core/.venv/Scripts/pythonw.exe'
        args = [str(python), str(self.root/'live_run.py'), '--name', name,
                '--hwnd', str(current['hwnd']), '--mode', value['mode'], '--seconds', '0', '--daily',
                '--owner-pid', str(os.getpid()), '--owner-created', str(owner_created), '--owner-token', self.owner_token,
                '--target-pid', str(current['pid']), '--target-created', str(current['created']),
                '--target-title', current['title'], '--target-width', str(current['width']),
                '--target-height', str(current['height']),
                '--height', str(value['nr_height']), '--flow-width', str(value['flow_width']),
                '--flow-grid', str(value['flow_grid']), '--flow-preset', value['flow_preset']]
        if value['mode'] == 'guard':
            args += ['--mask', str(mask)]
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
            self.detail += ' Switch to the game window to resume processing.'

    def stop(self):
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
        if self.process:
            if self.run.exists():
                files = list((self.run/'logs').glob('*.metrics.json'))
                if len(files) == 1:
                    self.metrics = read_json(files[0])
            if self.busy:
                self._send_stop()
                if not self.stop_pending and self.metrics:
                    self.state = 'suspended' if self.metrics.get('suspended') else 'running'
                    self.detail = ('Paused while another app is foreground. Return to the game to resume.'
                        if self.state == 'suspended' else 'Processing the selected game. Ctrl+Alt+Q stops; Ctrl+Alt+F9 opens this panel.')
                    if self.state == 'running' and self.metrics.get('settings', {}).get('bypass'):
                        self.detail = 'Bypass is active: showing the original source. Ctrl+Alt+F8 toggles NR.'
            else:
                outcome = self.run/'outcome.json'
                result = read_json(outcome) if outcome.exists() else {}
                if self.process.returncode == 0 and result.get('exit_code') == 0:
                    self.state, self.detail = 'stopped', 'Session ended: ' + result.get('state', 'stopped')
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
        return dict(state=self.state, detail=self.detail, run=str(evidence) if evidence else None,
                    geometry=geometry, nr_confirmed=bool(processing and self.metrics.get('nr_confirmed')),
                    hardware_flow_active=bool(processing and self.metrics.get('hardware_flow_active')))
