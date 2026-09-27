"""Identity-bound Windows operations for the optional Chiaki/NR/LS chain.

No console input, Chiaki termination, registry writes, or global DPI changes.
The caller owns the session journal and invokes recovery after stopping NR.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET


LS_PROFILE = dict(ScalingMode='Auto', ScalingFitMode='AspectRatio',
    WindowedMode='false', ScalingType='LS1', LS1Type='BALANCED',
    FrameGeneration='LSFG3', LSFG3Mode1='FIXED', LSFG3Multiplier='2',
    LSFG3Target='120', LSFGFlowScale='75', LSFGSize='PERFORMANCE',
    HdrSupport='true', CaptureApi='WGC', QueueTarget='1', MaxFrameLatency='1',
    ResizeBeforeScaling='false', MultiDisplayMode='false', DrawFps='true',
    HideCursor='true', CropInput='false')
CHIAKI_DEFAULTS = dict(placebo_preset='high_quality', resolution_local_ps5='1080p',
                      fps_local_ps5=60, codec_local_ps5='h265', keyboard_enabled='false')
CHIAKI_REQUIRED = dict(CHIAKI_DEFAULTS, codec_local_ps5='h265_hdr')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_ls_settings(data):
    """Reject ambiguous schemas and automatic scaling before any mutation."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RuntimeError('Lossless Scaling settings are not valid XML; preserved.') from exc
    if root.tag != 'Settings':
        raise RuntimeError('Unsupported Lossless Scaling settings schema.')
    for element in root.iter():
        names = [child.tag for child in element]
        if element.tag != 'GameProfiles' and len(names) != len(set(names)):
            raise RuntimeError('Duplicate Lossless Scaling settings fields; preserved.')
    profiles = root.find('GameProfiles')
    if profiles is None or not len(profiles) or any(p.tag != 'Profile' for p in profiles):
        raise RuntimeError('Lossless Scaling default profile is missing.')
    if root.findtext('Hotkey') != 'S' or root.findtext('HotkeyModifierKeys') != 'Alt Control':
        raise RuntimeError('Set the Lossless Scaling shortcut to Ctrl+Alt+S before starting.')
    if root.findtext('CloseToTray', '').lower() != 'false':
        raise RuntimeError('Turn off Lossless Scaling Close to tray before starting.')
    if root.findtext('StartAsAdmin', '').lower() != 'false':
        raise RuntimeError('Run Lossless Scaling without Start as administrator for this chain.')
    if any(p.findtext('AutoScale', '').lower() != 'false' for p in profiles):
        raise RuntimeError('Disable automatic scaling in all Lossless Scaling profiles first.')
    if profiles[0].findtext('Path', '').strip():
        raise RuntimeError('The first Lossless Scaling profile must be the default profile.')
    missing = set(LS_PROFILE) - {child.tag for child in profiles[0]}
    if missing:
        raise RuntimeError('Unsupported Lossless Scaling profile fields: ' + ', '.join(sorted(missing)))
    return root


def configured_ls_settings(data):
    root = parse_ls_settings(data)
    for key, value in LS_PROFILE.items():
        root.find('GameProfiles')[0].find(key).text = value
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def xml_semantics(data):
    """Ignore serializer formatting, never ignore user settings or profiles."""
    def node(element):
        return (element.tag, tuple(sorted(element.attrib.items())),
                (element.text or '').strip(), tuple(node(child) for child in element))
    return node(ET.fromstring(data))


def restore_ls_bytes(current, original, configured):
    if current == original:
        return original
    try:
        owned = xml_semantics(current) == xml_semantics(configured)
    except ET.ParseError:
        owned = False
    if not owned:
        raise RuntimeError('Lossless Scaling settings changed outside this session; preserved. '
                           'The original settings backup is available in the session folder.')
    return original


def validate_chiaki_settings(settings):
    mismatched = [key for key, value in CHIAKI_REQUIRED.items()
                  if str(settings.get(key, CHIAKI_DEFAULTS[key])).lower() != str(value).lower()]
    if mismatched:
        raise RuntimeError('Chiaki must use High Quality, 1080p / 60 FPS, H.265 HDR, '
                           'and keyboard controls off. Check: ' + ', '.join(mismatched))
    return {key: settings.get(key, default) for key, default in CHIAKI_DEFAULTS.items()}


def same_identity(actual, record):
    return (os.path.normcase(str(actual[0])) == os.path.normcase(record['exe'])
            and actual[1] == record['created'])


def ls_ui_ready(state):
    """The WPF HWND alone does not establish a bound profile/GPU model."""
    return (state.get('scale_enabled') is True
            and state.get('default_profile_selected') is True
            and bool(state.get('profile_title'))
            and state.get('scaling') == ['LS1']
            and len(state.get('frame_generation', [])) == 1
            and state['frame_generation'][0].startswith('LSFG 3')
            and len(state.get('gpu', [])) == 1 and bool(state['gpu'][0])
            and len(state.get('display', [])) == 1 and bool(state['display'][0]))


def _read_chiaki_settings():
    import winreg
    settings = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Chiaki\Chiaki\settings') as key:
        for name in CHIAKI_DEFAULTS:
            try:
                settings[name] = winreg.QueryValueEx(key, name)[0]
            except FileNotFoundError:
                pass
    return validate_chiaki_settings(settings)


def find_ls_executable():
    """Locate the installed Steam application without embedding machine paths."""
    import winreg
    steam = []
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                             (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')):
        try:
            with winreg.OpenKey(hive, key) as handle:
                steam.append(Path(winreg.QueryValueEx(handle, value)[0]))
        except FileNotFoundError:
            pass
    for variable in ('ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(variable):
            steam.append(Path(os.environ[variable]) / 'Steam')
    libraries = set(steam)
    for folder in steam:
        listing = folder / 'steamapps/libraryfolders.vdf'
        if listing.is_file():
            for value in re.findall(r'"path"\s*"([^"\r\n]+)"', listing.read_text(encoding='utf-8-sig')):
                libraries.add(Path(value.replace('\\\\', '\\')))
    candidates = {p.resolve() for lib in libraries
                  if (p := lib / 'steamapps/common/Lossless Scaling/LosslessScaling.exe').is_file()}
    if len(candidates) != 1:
        raise RuntimeError('Expected one installed Lossless Scaling executable; found ' + str(len(candidates)))
    return next(iter(candidates))


class NativeChain:
    def __init__(self, root, win):
        import win32api
        import win32gui
        import win32process
        self.root, self.win = Path(root), win
        self.api, self.gui, self.process = win32api, win32gui, win32process
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        self.u.AttachThreadInput.restype = wintypes.BOOL
        self.d = ctypes.WinDLL('dwmapi')
        self.d.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self.d.DwmGetWindowAttribute.restype = ctypes.c_long

    @contextmanager
    def physical_pixels(self):
        previous = self.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        if not previous:
            raise RuntimeError('Windows declined per-monitor physical-pixel coordinates.')
        try:
            yield
        finally:
            self.u.SetThreadDpiAwarenessContext(previous)

    def record(self, pid):
        exe, created = self.win.identity(pid)
        return dict(pid=pid, exe=exe, created=created)

    def alive(self, record):
        try:
            return same_identity(self.win.identity(record['pid']), record)
        except (OSError, RuntimeError):
            return False

    def require_window(self, record):
        if not self.alive(record) or self.win.pid(record['hwnd']) != record['pid']:
            raise RuntimeError('Window process identity changed; no operation attempted.')
        if record.get('title') is not None and self.gui.GetWindowText(record['hwnd']) != record['title']:
            raise RuntimeError('Window title changed; no operation attempted.')

    def windows(self, pid=None):
        result = []
        with self.physical_pixels():
            def visit(hwnd, _):
                if pid is None or self.win.pid(hwnd) == pid:
                    result.append(dict(hwnd=hwnd, pid=self.win.pid(hwnd),
                        title=self.gui.GetWindowText(hwnd), class_name=self.gui.GetClassName(hwnd),
                        rect=list(self.gui.GetWindowRect(hwnd)), visible=bool(self.gui.IsWindowVisible(hwnd))))
            self.gui.EnumWindows(visit, None)
        return result

    def monitor_rect(self, hwnd):
        with self.physical_pixels():
            monitor = self.api.MonitorFromWindow(hwnd, 2)
            return list(self.api.GetMonitorInfo(monitor)['Monitor'])

    def geometry(self, hwnd):
        with self.physical_pixels():
            rect = wintypes.RECT()
            if self.d.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)):
                raise RuntimeError('Could not verify physical DWM capture bounds.')
            return dict(rect=list(self.gui.GetWindowRect(hwnd)),
                        client=list(self.gui.GetClientRect(hwnd)),
                        dwm=[rect.left, rect.top, rect.right, rect.bottom])

    def idle_ls(self, executable):
        records = {}
        for window in self.windows():
            try:
                record = self.record(window['pid'])
            except (OSError, RuntimeError):
                continue
            if Path(record['exe']).name.lower() != 'losslessscaling.exe':
                continue
            if os.path.normcase(record['exe']) != os.path.normcase(str(executable)):
                raise RuntimeError('A different Lossless Scaling installation is running; preserved.')
            records[record['pid']] = record
            if window['class_name'] == 'LosslessScaling' and window['title'] != 'Lossless Scaling':
                raise RuntimeError('Lossless Scaling is already scaling a window; existing session preserved.')
        # Include processes without a main window; never launch alongside an ambiguous instance.
        for pid in self.process.EnumProcesses():
            if not pid or pid in records:
                continue
            try:
                record = self.record(pid)
            except (OSError, RuntimeError):
                continue
            if Path(record['exe']).name.lower() == 'losslessscaling.exe':
                if os.path.normcase(record['exe']) != os.path.normcase(str(executable)):
                    raise RuntimeError('A different Lossless Scaling installation is running; preserved.')
                records[pid] = record
        if len(records) > 1:
            raise RuntimeError('Multiple Lossless Scaling instances are running; preserved.')
        if not records:
            return None
        record = next(iter(records.values()))
        mains = [w for w in self.windows(record['pid']) if w['title'] == 'Lossless Scaling']
        if len(mains) != 1:
            raise RuntimeError('Lossless Scaling has no unique idle main window; preserved.')
        return dict(record, hwnd=mains[0]['hwnd'], title='Lossless Scaling')

    def preflight(self, target):
        self.require_window(target)
        if Path(target['exe']).name.lower() != 'chiaki.exe':
            raise RuntimeError('Select the connected Chiaki game window first.')
        # The selected executable is the identity contract, not a process-name search.
        if not Path(target['exe']).is_file():
            raise RuntimeError('The selected Chiaki executable is unavailable.')
        if self.gui.IsIconic(target['hwnd']):
            raise RuntimeError('Restore the connected Chiaki window before starting.')
        monitor = self.monitor_rect(target['hwnd'])
        if (monitor[2]-monitor[0], monitor[3]-monitor[1]) != (2560, 1440):
            raise RuntimeError('This chain requires a 2560 x 1440 output display.')
        from hdr_support import require_hdr_display
        hdr = require_hdr_display(self.root, target['hwnd'], 'color-preserving', queued=True, capture_queued=True)
        executable = find_ls_executable()
        config = Path(os.environ['LOCALAPPDATA']) / 'Lossless Scaling/Settings.xml'
        parse_ls_settings(config.read_bytes())
        return dict(ls_exe=str(executable), config_path=str(config), monitor_rect=monitor,
                    chiaki_settings=_read_chiaki_settings(), hdr=hdr,
                    idle_ls=self.idle_ls(executable))

    def prepare_window(self, target, journal):
        self.require_window(target)
        hwnd = target['hwnd']
        with self.physical_pixels():
            geometry = self.geometry(hwnd)
            style, exstyle = self.gui.GetWindowLong(hwnd, -16), self.gui.GetWindowLong(hwnd, -20)
            placement = self.gui.GetWindowPlacement(hwnd)
            monitor = self.monitor_rect(hwnd)
            x, y = monitor[0]+(monitor[2]-monitor[0]-1920)//2, monitor[1]+(monitor[3]-monitor[1]-1080)//2
            changed_style = style & ~(0x00C00000 | 0x00040000 | 0x01000000)
            # User32 synchronously clears WS_EX_WINDOWEDGE when the caption and
            # sizing frame are removed. Include that owned side effect in the
            # journal rather than mistaking it for a later user modification.
            changed_exstyle = exstyle & ~0x00000100
            desired = [x, y, x+1920, y+1080]
            record = dict(target, original=geometry, style=style, exstyle=exstyle,
                          placement=placement, changed_style=changed_style,
                          changed_exstyle=changed_exstyle, desired_rect=desired,
                          allowed_rects=[geometry['rect'], desired])
            journal(record)
            self.require_window(target)
            self.gui.SetWindowLong(hwnd, -16, changed_style)
            self.gui.SetWindowPos(hwnd, 0, x, y, 1920, 1080, 0x0020 | 0x0004)
            deadline = time.monotonic()+3
            while True:
                self.require_window(target)
                current = self.geometry(hwnd)
                if current['client'] == [0, 0, 1920, 1080] and current['dwm'] == desired:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Chiaki did not accept an exact physical 1920 x 1080 client/capture area.')
                time.sleep(.05)
            self.focus(target)
            return dict(target, width=1920, height=1080), record

    def restore_window(self, record):
        if not self.alive(record):
            return False  # A closed/restarted Chiaki is never touched.
        self.require_window(record)
        hwnd = record['hwnd']
        with self.physical_pixels():
            current = self.geometry(hwnd)
            if (self.gui.GetWindowLong(hwnd, -16) == record['style'] and
                    self.gui.GetWindowLong(hwnd, -20) == record['exstyle'] and
                    current['rect'] == record['original']['rect']):
                return True
            if (self.gui.GetWindowLong(hwnd, -16) not in (record['style'], record['changed_style'])
                    or self.gui.GetWindowLong(hwnd, -20) not in (record['exstyle'], record['exstyle'] & ~0x00000100)
                    or current['rect'] not in record['allowed_rects']):
                raise RuntimeError('Chiaki window layout changed outside this session; preserved.')
            self.gui.SetWindowLong(hwnd, -16, record['style'])
            self.gui.SetWindowLong(hwnd, -20, record['exstyle'])
            placement = record['placement']
            placement = (placement[0], placement[1], tuple(placement[2]), tuple(placement[3]), tuple(placement[4]))
            self.gui.SetWindowPlacement(hwnd, placement)
            self.gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002 | 0x0004)
            deadline = time.monotonic()+2
            while self.geometry(hwnd)['rect'] != record['original']['rect']:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Chiaki original window bounds could not be verified after restoration.')
                time.sleep(.05)
            if (self.gui.GetWindowLong(hwnd, -16) != record['style']
                    or self.gui.GetWindowLong(hwnd, -20) != record['exstyle']):
                raise RuntimeError('Chiaki original window styles were not restored.')
        return True

    def configure_ls(self, preflight, run_dir, journal):
        idle = self.idle_ls(preflight['ls_exe'])
        if idle != preflight['idle_ls']:
            raise RuntimeError('Lossless Scaling changed after preflight; preserved.')
        # Journal the idle instance before closing it so recovery can reopen its UI.
        record = dict(config_path=preflight['config_path'], idle_ls=idle, ls_exe=preflight['ls_exe'])
        journal(record)
        if idle:
            self.stop_ls(idle)
        path = Path(preflight['config_path'])
        original = path.read_bytes()
        configured = configured_ls_settings(original)
        backup = Path(run_dir) / 'lossless-settings-original.xml'
        staged = Path(run_dir) / 'lossless-settings-configured.xml'
        with backup.open('xb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        with staged.open('xb') as stream:
            stream.write(configured)
            stream.flush()
            os.fsync(stream.fileno())
        record.update(session_dir=str(Path(run_dir).resolve()), backup=str(backup), configured=str(staged), original_sha256=digest(original),
                      configured_sha256=digest(configured))
        journal(record)
        if path.read_bytes() != original or self.idle_ls(preflight['ls_exe']) is not None:
            raise RuntimeError('Lossless Scaling changed before configuration; preserved.')
        atomic_bytes(path, configured)
        return record

    def restore_ls_config(self, record):
        if 'backup' not in record:
            return
        if self.idle_ls(record['ls_exe']) is not None:
            raise RuntimeError('Close the running Lossless Scaling UI before restoring its settings.')
        session = Path(record['session_dir']).resolve()
        expected_config = (Path(os.environ['LOCALAPPDATA']) / 'Lossless Scaling/Settings.xml').resolve()
        if (not session.is_relative_to((self.root / 'runs').resolve())
                or session == (self.root / 'runs').resolve()
                or Path(record['config_path']).resolve() != expected_config
                or Path(record['backup']).resolve() != session / 'lossless-settings-original.xml'
                or Path(record['configured']).resolve() != session / 'lossless-settings-configured.xml'):
            raise RuntimeError('Lossless Scaling recovery paths do not match this session; preserved.')
        original, configured = Path(record['backup']).read_bytes(), Path(record['configured']).read_bytes()
        if digest(original) != record['original_sha256'] or digest(configured) != record['configured_sha256']:
            raise RuntimeError('Lossless Scaling recovery backup changed; no settings overwritten.')
        path = Path(record['config_path'])
        current = path.read_bytes()
        restored = restore_ls_bytes(current, original, configured)
        if path.read_bytes() != current:
            raise RuntimeError('Lossless Scaling settings changed during recovery; preserved.')
        if current != restored:
            atomic_bytes(path, restored)

    def launch_ls(self, preflight):
        if self.idle_ls(preflight['ls_exe']) is not None:
            raise RuntimeError('Another Lossless Scaling instance appeared; preserved.')
        executable = Path(preflight['ls_exe'])
        process = subprocess.Popen([str(executable)], cwd=executable.parent)
        record = self.record(process.pid)
        if os.path.normcase(record['exe']) != os.path.normcase(str(executable)):
            raise RuntimeError('Launched Lossless Scaling executable identity mismatch.')
        return process, record

    def stop_ls(self, record):
        if not self.alive(record):
            return
        mains = [w for w in self.windows(record['pid']) if w['title'] == 'Lossless Scaling']
        if len(mains) != 1:
            raise RuntimeError('Owned Lossless Scaling main window is unavailable; no unrelated process stopped.')
        main = dict(record, hwnd=mains[0]['hwnd'], title='Lossless Scaling')
        self.require_window(main)
        self.gui.PostMessage(main['hwnd'], 0x10, 0, 0)
        deadline = time.monotonic()+10
        while self.alive(record):
            if time.monotonic() >= deadline:
                raise RuntimeError('Lossless Scaling did not exit safely; settings remain backed up.')
            time.sleep(.1)

    def focus(self, record):
        self.require_window(record)
        hwnd = record['hwnd']
        thread = self.api.GetCurrentThreadId()
        foreground = self.gui.GetForegroundWindow()
        foreground_thread = self.process.GetWindowThreadProcessId(foreground)[0] if foreground else thread
        attached = thread != foreground_thread and self.u.AttachThreadInput(thread, foreground_thread, True)
        try:
            self.gui.BringWindowToTop(hwnd)
            self.gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                self.u.AttachThreadInput(thread, foreground_thread, False)
        # Cross-input-queue activation completes asynchronously. Wait for that
        # one request to settle; never resend input to an unverified foreground.
        deadline = time.monotonic()+.5
        while True:
            self.require_window(record)
            if self.gui.GetForegroundWindow() == hwnd:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Windows declined the required foreground window; no hotkey sent.')
            time.sleep(.01)

    def start_scaling(self, renderer_pid, ls_record, monitor_rect):
        readiness = self.wait_ls_ready(ls_record)
        renderer = self.record(renderer_pid)
        deadline = time.monotonic()+10
        while True:
            if not self.alive(ls_record):
                raise RuntimeError('Owned Lossless Scaling exited before scaling started.')
            mains = [w for w in self.windows(ls_record['pid']) if w['title'] == 'Lossless Scaling']
            outputs = [w for w in self.windows(renderer_pid) if w['visible']
                       and w['title'] == 'Geforce NR — Output' and w['class_name'] == 'NeuralScreenPresent']
            if len(outputs) == 1 and len(mains) == 1:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Expected one NR output and one owned Lossless Scaling UI.')
            time.sleep(.1)
        output = dict(outputs[0], exe=renderer['exe'], created=renderer['created'])
        geometry = self.geometry(output['hwnd'])
        if geometry['client'] != [0, 0, 1920, 1080] or (
                geometry['dwm'][2]-geometry['dwm'][0], geometry['dwm'][3]-geometry['dwm'][1]) != (1920, 1080):
            raise RuntimeError('NR output is not the exact physical 1080p LS1 source.')
        self.focus(output)
        keys = (17, 18, 83)
        pressed = []
        try:
            for key in keys:
                self.require_window(output)
                if not self.alive(ls_record) or self.gui.GetForegroundWindow() != output['hwnd']:
                    raise RuntimeError('Foreground changed; scaling shortcut cancelled.')
                self.api.keybd_event(key, self.api.MapVirtualKey(key, 0), 0, 0)
                pressed.append(key)
        finally:
            for key in reversed(pressed):
                self.api.keybd_event(key, self.api.MapVirtualKey(key, 0), 2, 0)
        deadline = time.monotonic()+12
        while True:
            if not self.alive(ls_record):
                raise RuntimeError('Owned Lossless Scaling exited while starting.')
            self.require_window(output)
            scaled = [w for w in self.windows(ls_record['pid']) if w['visible']
                      and w['class_name'] == 'LosslessScaling' and w['title'] == ''
                      and w['rect'] == list(monitor_rect)]
            if len(scaled) == 1:
                if self.gui.GetForegroundWindow() != output['hwnd']:
                    raise RuntimeError('Foreground changed while enabling NR capture.')
                return dict(ls_readiness=readiness, nr_output=output,
                            ls_output=dict(scaled[0], exe=ls_record['exe'], created=ls_record['created']))
            if time.monotonic() >= deadline:
                raise RuntimeError('Lossless Scaling did not produce a verified 1440p output.')
            time.sleep(.1)

    def _ls_ui_snapshot(self, automation, module, main):
        self.require_window(main)
        root = automation.ElementFromHandle(main['hwnd'])
        if root.CurrentProcessId != main['pid']:
            raise RuntimeError('Lossless Scaling accessibility root identity changed.')
        controls = {}
        for identifier in ('ScaleButton', 'ProfileList', 'GameProfileTitle',
                           'FrameGeneration', 'ScalingType', 'PreferredGpu', 'OutputDisplay'):
            # AutomationId is stable across the installed UI languages.
            element = root.FindFirst(4, automation.CreatePropertyCondition(30011, identifier))
            if not element:
                return dict(ready=False, missing=identifier)
            if element.CurrentProcessId != main['pid']:
                raise RuntimeError('Lossless Scaling accessibility control identity changed.')
            controls[identifier] = element
        profiles = controls['ProfileList'].FindAll(2, automation.CreatePropertyCondition(30003, 50007))
        selected = [index for index in range(profiles.Length)
                    if profiles.GetElement(index).GetCurrentPropertyValue(30079) is True]
        state = dict(scale_enabled=bool(controls['ScaleButton'].CurrentIsEnabled),
                     default_profile_selected=selected == [0],
                     profile_title=controls['GameProfileTitle'].CurrentName)
        for identifier, key in (('FrameGeneration', 'frame_generation'), ('ScalingType', 'scaling'),
                                ('PreferredGpu', 'gpu'), ('OutputDisplay', 'display')):
            pattern = controls[identifier].GetCurrentPattern(10001).QueryInterface(module.IUIAutomationSelectionPattern)
            items = pattern.GetCurrentSelection()
            state[key] = [items.GetElement(index).CurrentName for index in range(items.Length)]
        self.require_window(main)
        return state

    def wait_ls_ready(self, record):
        """Wait for the actual Scale command's default profile and GPU bindings."""
        import comtypes.client
        from comtypes import COMError
        module = comtypes.client.GetModule('UIAutomationCore.dll')
        automation = comtypes.client.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
        deadline = time.monotonic() + 15
        state = dict(ready=False, missing='Lossless Scaling main window')
        while self.alive(record):
            mains = [w for w in self.windows(record['pid']) if w['title'] == 'Lossless Scaling']
            if len(mains) > 1:
                raise RuntimeError('Owned Lossless Scaling main window is ambiguous; no hotkey sent.')
            if len(mains) == 1:
                main = dict(record, hwnd=mains[0]['hwnd'], title='Lossless Scaling')
                try:
                    state = self._ls_ui_snapshot(automation, module, main)
                except COMError as exc:
                    # WPF can expose a partial/replaced tree during initial load.
                    # Wait for that specific UI transition; never send input early.
                    state = dict(ready=False, accessibility_error=str(exc))
                if ls_ui_ready(state):
                    return state
            if time.monotonic() >= deadline:
                raise RuntimeError('Lossless Scaling default LS1/LSFG3 profile and GPU controls are not ready; '
                                   'no hotkey sent. Readiness: ' + str(state))
            time.sleep(.1)
        raise RuntimeError('Owned Lossless Scaling exited before its Scale command became ready.')

    def reopen_ls(self, preflight):
        if preflight.get('idle_ls') and self.idle_ls(preflight['ls_exe']) is None:
            process, record = self.launch_ls(preflight)
            deadline = time.monotonic() + 10
            while self.alive(record):
                mains = [w for w in self.windows(record['pid']) if w['title'] == 'Lossless Scaling']
                if len(mains) == 1:
                    self.require_window(dict(record, hwnd=mains[0]['hwnd'], title='Lossless Scaling'))
                    return process, record
                if len(mains) > 1:
                    raise RuntimeError('Reopened Lossless Scaling has ambiguous main windows; preserved.')
                if time.monotonic() >= deadline:
                    raise RuntimeError('Reopened Lossless Scaling did not finish creating its idle UI; preserved.')
                time.sleep(.1)
            raise RuntimeError('Reopened Lossless Scaling exited before its idle UI became ready.')
        return None
