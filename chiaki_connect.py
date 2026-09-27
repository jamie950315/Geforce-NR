"""Acquire a registered, awake LAN PS5 stream without game or power input.

Registration secrets and PINs stay in Chiaki. Restart Manager is used only to
identify the process holding a session log; no shutdown/restart API is called.
Transport and received-video evidence are not a claim of decoded-frame quality.
"""
import ctypes
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time


class ChiakiConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Console:
    nickname: str
    mac: str


def _mac(value):
    if isinstance(value, str) and value.startswith('@ByteArray(') and value.endswith(')'):
        value = value[11:-1].encode('latin-1')
    if isinstance(value, bytes) and len(value) == 6:
        return value.hex()
    raise ChiakiConnectionError('Unsupported Chiaki console identity encoding.')


def read_configuration():
    """Read only public console identity and the required video settings."""
    import winreg
    base = r'Software\Chiaki\Chiaki'
    def value(key, name, default=None):
        try:
            return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return default
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r'\settings') as key:
            if value(key, 'current_profile', ''):
                raise ChiakiConnectionError('Select the default Chiaki profile before using one-click launch.')
            settings = {name: value(key, name, default) for name, default in {
                'placebo_preset': 'high_quality', 'resolution_local_ps5': '1080p',
                'fps_local_ps5': 60, 'codec_local_ps5': 'h265',
            }.items()}
        validate_configuration(settings)
        result = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r'\registered_hosts') as key:
            count = winreg.QueryInfoKey(key)[0]
            for index in range(count):
                name = winreg.EnumKey(key, index)
                with winreg.OpenKey(key, name) as host:
                    if int(value(host, 'target', 0)) < 1000000:
                        continue
                    nickname = value(host, 'server_nickname', '')
                    if not isinstance(nickname, str) or not nickname or '\0' in nickname:
                        raise ChiakiConnectionError('A registered PS5 has an invalid nickname.')
                    result.append(Console(nickname, _mac(value(host, 'server_mac'))))
        if not result:
            raise ChiakiConnectionError('Register a PS5 in Chiaki before using one-click launch.')
        return result
    except FileNotFoundError as exc:
        raise ChiakiConnectionError('Configure and register a PS5 in Chiaki first.') from exc


def validate_configuration(settings):
    expected = {'placebo_preset': 'high_quality', 'resolution_local_ps5': '1080p',
                'fps_local_ps5': 60, 'codec_local_ps5': 'h265_hdr'}
    if any(str(settings.get(k)) != str(v) for k, v in expected.items()):
        raise ChiakiConnectionError('Set Chiaki local PS5 video to 1080p, 60 FPS, H.265 HDR and High Quality first.')


def parse_discovery(payload, address):
    """Accept an awake PS5 response, using the packet source as its address."""
    try:
        lines = payload.decode('ascii', errors='strict').replace('\r', '').split('\n')
        if lines[0].split()[:2] != ['HTTP/1.1', '200']:
            return None
        fields = {}
        for line in lines[1:]:
            if ':' in line:
                key, val = line.split(':', 1)
                if key.lower() in fields:
                    return None
                fields[key.lower()] = val.strip()
        if fields.get('device-discovery-protocol-version') != '00030010':
            return None
        mac = fields.get('host-id', '').lower()
        if not re.fullmatch(r'[0-9a-f]{12}', mac):
            return None
        addr = ipaddress.IPv4Address(address)
        if addr.is_multicast or addr.is_unspecified or addr.is_loopback:
            return None
        return (mac, str(addr))
    except (UnicodeError, ValueError, IndexError):
        return None


def discovery_broadcasts():
    # A VPN/default route can consume the limited broadcast. Send the same
    # read-only search to each actual IPv4 subnet instead of guessing a LAN.
    command = ('Get-NetIPAddress -AddressFamily IPv4 | Where-Object '
               '{$_.AddressState -eq "Preferred" -and -not $_.SkipAsSource} | '
               'Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
    rows = json.loads(result.stdout or '[]')
    if isinstance(rows, dict):
        rows = [rows]
    addresses = set()
    for row in rows:
        interface = ipaddress.IPv4Interface(f"{row['IPAddress']}/{int(row['PrefixLength'])}")
        if not interface.ip.is_loopback and interface.network.prefixlen < 31:
            addresses.add(str(interface.network.broadcast_address))
    if not addresses:
        raise ChiakiConnectionError('No usable IPv4 LAN interface was found for PS5 discovery.')
    return addresses


def discover(timeout=2.0, cancelled=lambda: False):
    found = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', 0))
        sock.settimeout(0.2)
        for address in discovery_broadcasts():
            sock.sendto(b'SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n',
                        (address, 9302))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not cancelled():
            try:
                data, remote = sock.recvfrom(8192)
            except socket.timeout:
                continue
            parsed = parse_discovery(data, remote[0])
            if parsed:
                found.add(parsed)
    return found


def choose_console(registered, discovered):
    eligible = {(c, address) for c in registered for mac, address in discovered if c.mac == mac}
    if len(eligible) != 1:
        raise ChiakiConnectionError('One-click launch requires exactly one awake registered LAN PS5. '
                                    'Connect the intended console in Chiaki first; no wake/sleep command was sent.')
    selected = next(iter(eligible))
    if sum(c.nickname == selected[0].nickname for c in registered) != 1:
        raise ChiakiConnectionError('Registered console nicknames are ambiguous. Connect in Chiaki first.')
    return selected


def tcp_stream_pids():
    """Return IPv4 processes with established PS5 control connections."""
    dword = ctypes.c_uint32
    iphlp = ctypes.WinDLL('iphlpapi', use_last_error=True)
    fn = iphlp.GetExtendedTcpTable
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(dword), ctypes.c_int,
                   dword, ctypes.c_int, dword]
    fn.restype = dword
    size = dword()
    result = fn(None, ctypes.byref(size), False, socket.AF_INET, 5, 0)
    if result != 122 or size.value < 4:
        raise ChiakiConnectionError('Cannot inspect the Windows stream connections.')
    data = ctypes.create_string_buffer(size.value)
    if fn(data, ctypes.byref(size), False, socket.AF_INET, 5, 0):
        raise ChiakiConnectionError('Windows stream connection inspection failed.')
    count = dword.from_buffer(data).value
    if 4 + count * 24 > len(data):
        raise ChiakiConnectionError('Invalid Windows connection table.')
    result = set()
    for index in range(count):
        row = (dword * 6).from_buffer(data, 4 + index * 24)
        if row[0] == 5 and socket.ntohs(row[4] & 0xffff) == 9295:
            result.add(int(row[5]))
    return result


def log_owners(path):
    """Read the Windows file-owner list without interfering with those processes."""
    from ctypes import wintypes as w
    class UniqueProcess(ctypes.Structure):
        _fields_ = [('pid', w.DWORD), ('created', w.FILETIME)]
    class ProcessInfo(ctypes.Structure):
        _fields_ = [('process', UniqueProcess), ('app', w.WCHAR * 256),
                    ('service', w.WCHAR * 64), ('kind', ctypes.c_int),
                    ('status', w.ULONG), ('session', w.DWORD), ('restartable', w.BOOL)]
    rm = ctypes.WinDLL('rstrtmgr', use_last_error=True)
    rm.RmStartSession.argtypes = [ctypes.POINTER(w.DWORD), w.DWORD, w.LPWSTR]
    rm.RmRegisterResources.argtypes = [w.DWORD, w.UINT, ctypes.POINTER(w.LPCWSTR),
                                      w.UINT, ctypes.c_void_p, w.UINT, ctypes.c_void_p]
    rm.RmGetList.argtypes = [w.DWORD, ctypes.POINTER(w.UINT), ctypes.POINTER(w.UINT),
                            ctypes.POINTER(ProcessInfo), ctypes.POINTER(w.DWORD)]
    rm.RmEndSession.argtypes = [w.DWORD]
    session = w.DWORD()
    key = ctypes.create_unicode_buffer(33)
    if rm.RmStartSession(ctypes.byref(session), 0, key):
        raise ChiakiConnectionError('Cannot verify the Chiaki session log owner.')
    try:
        files = (w.LPCWSTR * 1)(str(path))
        if rm.RmRegisterResources(session, 1, files, 0, None, 0, None):
            raise ChiakiConnectionError('Cannot register the Chiaki session log for inspection.')
        needed, count, reason = w.UINT(), w.UINT(), w.DWORD()
        code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        if code == 0:
            return set()
        if code != 234 or not 0 < needed.value <= 128:
            raise ChiakiConnectionError('Cannot identify the Chiaki session log owner.')
        count.value = needed.value
        rows = (ProcessInfo * count.value)()
        if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), rows, ctypes.byref(reason)):
            raise ChiakiConnectionError('Chiaki session ownership changed during inspection.')
        return {int(rows[i].process.pid) for i in range(count.value)}
    finally:
        rm.RmEndSession(session)


def received_video(text):
    # Profile switching is logged only after an actual video packet arrives.
    start = text.rfind('StreamConnection successfully received streaminfo')
    frame = re.search(r'Switched to profile \d+, resolution: 1920x1080', text[max(start, 0):])
    if start < 0 or not frame:
        return False
    return not any(marker in text[start:] for marker in (
        'Session has quit', 'StreamConnection is disconnecting',
        'StreamConnection was requested to stop', 'StreamConnection closing after Remote disconnected',
        'StreamConnection closed takion'))


def is_streaming(pid):
    if pid not in tcp_stream_pids():
        return False
    root = Path(os.environ['APPDATA']) / 'Chiaki' / 'Chiaki' / 'log'
    for path in sorted(root.glob('chiaki_session_*.log'), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
        if pid not in log_owners(path):
            continue
        # Bounded reading; raw logs can include secrets and must never be emitted.
        with path.open('rb') as file:
            head = file.read(1024 * 1024)
            file.seek(0, 2)
            if file.tell() > len(head):
                file.seek(max(len(head), file.tell() - 65536))
                head += file.read(65536)
        if received_video(head.decode('utf-8', errors='replace')):
            return True
    return False


def acquire_stream(win, list_targets, selected=None, cancelled=lambda: False,
                   status=None, timeout=45):
    """Reuse a verified stream or connect one unambiguous awake LAN console.

    The caller owns NR/LS, not Chiaki: cancellation, errors and Stop must leave
    Chiaki running, including a PIN dialog that requires the user's input.
    """
    notify = status or (lambda message: None)
    registered = read_configuration()
    targets = [t for t in list_targets() if Path(t['exe']).name.lower() == 'chiaki.exe']
    connected = tcp_stream_pids()
    # A minimized/hidden stream is excluded by application-window enumeration,
    # but must still prevent opening a competing Remote Play session.
    visible_pids = {t['pid'] for t in targets}
    for pid in connected - visible_pids:
        try:
            exe, _ = win.identity(pid)
        except (OSError, RuntimeError):
            continue
        if Path(exe).name.lower() == 'chiaki.exe':
            raise ChiakiConnectionError('A hidden or minimized Chiaki session is connected. Restore it first.')
    active = [t for t in targets if is_streaming(t['pid'])]
    if len(active) > 1:
        raise ChiakiConnectionError('More than one Chiaki stream window is active. Keep only the intended stream.')
    if active:
        if selected and selected['pid'] != active[0]['pid']:
            # The previous one-click launch intentionally leaves its stream
            # open. A still-selected idle home window may reuse that stream,
            # but a different installation or connecting window may not.
            if (selected['pid'] in connected or selected['exe'] != active[0]['exe'] or
                    win.identity(selected['pid']) != (selected['exe'], selected['created'])):
                raise ChiakiConnectionError('Another Chiaki window is already streaming. Select that stream first.')
        return active[0]
    # Never start another console while an existing connection is awaiting PIN
    # or negotiating video. This also avoids treating that UI as the game.
    if any(t['pid'] in connected for t in targets):
        raise ChiakiConnectionError('Chiaki is connecting or awaiting login. Complete its dialog, then start again.')
    executable = (Path(selected['exe']) if selected else Path(targets[0]['exe']) if targets else
                  Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'chiaki-ng' / 'chiaki.exe')
    if not executable.is_file() or executable.name.lower() != 'chiaki.exe':
        raise ChiakiConnectionError('The installed chiaki-ng executable was not found.')
    notify('Finding the awake registered PS5 on the local network...')
    console, address = choose_console(registered, discover(cancelled=cancelled))
    if cancelled():
        raise ChiakiConnectionError('Launch cancelled; Chiaki and PS5 were left unchanged.')
    # Only nickname/address are arguments. No PIN, registration key or PSN token.
    process = subprocess.Popen([str(executable), 'stream', console.nickname, address],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, cwd=str(executable.parent))
    notify('Connecting Chiaki. Complete any login dialog in Chiaki; no game input is sent.')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled():
            raise ChiakiConnectionError('Launch cancelled. Chiaki remains open; PS5 was not put to sleep.')
        if process.poll() is not None:
            raise ChiakiConnectionError('Chiaki exited before receiving video. Connect manually and try again.')
        current = [t for t in list_targets() if t['pid'] == process.pid and
                   Path(t['exe']) == executable]
        if len(current) == 1 and is_streaming(process.pid):
            target = current[0]
            if win.identity(process.pid) != (target['exe'], target['created']):
                raise ChiakiConnectionError('Chiaki identity changed while connecting.')
            return target
        time.sleep(0.4)
    raise ChiakiConnectionError('Chiaki has not received 1080p video. Complete any login dialog, then start again. '
                                'Chiaki remains open and no PS5 power command was sent.')
