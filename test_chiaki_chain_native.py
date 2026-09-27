"""Safety contracts for the optional native Chiaki/NR/LS adapter."""
import unittest
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock

from chiaki_chain_native import (LS_PROFILE, NativeChain, atomic_bytes,
    configured_ls_settings, digest, parse_ls_settings, restore_ls_bytes,
    same_identity, validate_chiaki_settings, ls_ui_ready)


def settings_xml():
    root = ET.Element('Settings')
    for key, value in dict(Hotkey='S', HotkeyModifierKeys='Alt Control',
                           CloseToTray='false', StartAsAdmin='false', WindowWidth='800').items():
        ET.SubElement(root, key).text = value
    profiles = ET.SubElement(root, 'GameProfiles')
    for title in ('Default', 'Unrelated profile'):
        profile = ET.SubElement(profiles, 'Profile')
        ET.SubElement(profile, 'Title').text = title
        ET.SubElement(profile, 'AutoScale').text = 'false'
        for key, value in LS_PROFILE.items():
            ET.SubElement(profile, key).text = value
        profile.find('ScalingType').text = 'Off'
        profile.find('LSFG3Mode1').text = 'ADAPTIVE'
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def edit_xml(data, path, value):
    root = ET.fromstring(data)
    root.find(path).text = value
    return ET.tostring(root)


class FocusTests(unittest.TestCase):
    def test_hidden_foreign_scaling_output_is_preserved(self):
        native=NativeChain.__new__(NativeChain)
        native.windows=lambda:[dict(pid=5,visible=False,class_name='LosslessScaling',title='')]
        native.record=lambda pid:dict(pid=pid,exe='LosslessScaling.exe',created=100)
        with self.assertRaisesRegex(RuntimeError,'existing session preserved'):
            native.idle_ls('LosslessScaling.exe')

    def native(self, foreground):
        native=NativeChain.__new__(NativeChain)
        native.require_window=Mock()
        native.api=SimpleNamespace(GetCurrentThreadId=lambda:1)
        native.process=SimpleNamespace(GetWindowThreadProcessId=lambda hwnd:(2,3))
        native.u=SimpleNamespace(AttachThreadInput=Mock(return_value=True))
        native.gui=SimpleNamespace(GetForegroundWindow=Mock(side_effect=foreground),
            BringWindowToTop=Mock(),SetForegroundWindow=Mock())
        return native

    def test_asynchronous_foreground_completion_uses_one_activation(self):
        native=self.native([10,10,20])
        with patch('chiaki_chain_native.time.sleep'):
            native.focus({'hwnd':20})
        native.gui.SetForegroundWindow.assert_called_once_with(20)
        self.assertEqual(native.u.AttachThreadInput.call_args.args,(1,2,False))

    def test_foreign_foreground_is_not_accepted(self):
        native=self.native([10,10])
        with patch('chiaki_chain_native.time.monotonic',side_effect=[0,1]):
            with self.assertRaisesRegex(RuntimeError,'no hotkey sent'):
                native.focus({'hwnd':20})


class ConfigTests(unittest.TestCase):
    def test_only_default_profile_changes(self):
        original = settings_xml()
        configured = configured_ls_settings(original)
        before, after = ET.fromstring(original), ET.fromstring(configured)
        self.assertEqual(ET.tostring(before.find('GameProfiles')[1]),
                         ET.tostring(after.find('GameProfiles')[1]))
        self.assertEqual(after.findtext('WindowWidth'), '800')
        for key, value in LS_PROFILE.items():
            self.assertEqual(after.find('GameProfiles')[0].findtext(key), value)

    def test_automatic_profile_refused(self):
        root = ET.fromstring(settings_xml())
        root.find('GameProfiles')[1].find('AutoScale').text = 'true'
        with self.assertRaisesRegex(RuntimeError, 'automatic scaling'):
            configured_ls_settings(ET.tostring(root))

    def test_nondefault_first_profile_refused(self):
        root = ET.fromstring(settings_xml())
        ET.SubElement(root.find('GameProfiles')[0], 'Path').text = 'game.exe'
        with self.assertRaisesRegex(RuntimeError, 'default profile'):
            parse_ls_settings(ET.tostring(root))

    def test_shortcut_and_close_contracts(self):
        for path, value in (('Hotkey', 'G'), ('HotkeyModifierKeys', 'Control'),
                            ('CloseToTray', 'true'), ('StartAsAdmin', 'true')):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                configured_ls_settings(edit_xml(settings_xml(), path, value))

    def test_ambiguous_or_missing_schema_refused(self):
        root = ET.fromstring(settings_xml())
        ET.SubElement(root, 'Hotkey').text = 'S'
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
            parse_ls_settings(ET.tostring(root))
        root = ET.fromstring(settings_xml())
        profile = root.find('GameProfiles')[0]
        profile.remove(profile.find('LSFG3Mode1'))
        with self.assertRaisesRegex(RuntimeError, 'LSFG3Mode1'):
            parse_ls_settings(ET.tostring(root))
        for data in (b'<broken', b'<Unknown/>', b'<Settings/>'):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                parse_ls_settings(data)

    def test_serializer_roundtrip_restores_exact_original_bytes(self):
        original = settings_xml()
        configured = configured_ls_settings(original)
        root = ET.fromstring(configured)
        ET.indent(root)
        roundtrip = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        self.assertNotEqual(configured, roundtrip)
        self.assertEqual(restore_ls_bytes(roundtrip, original, configured), original)
        self.assertEqual(restore_ls_bytes(original, original, configured), original)

    def test_foreign_change_is_never_overwritten(self):
        original = settings_xml()
        configured = configured_ls_settings(original)
        for path, value in (('WindowWidth', '900'), ('Hotkey', 'Z'),
                            ('GameProfiles/Profile/LSFGFlowScale', '100')):
            changed = edit_xml(configured, path, value)
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'preserved'):
                restore_ls_bytes(changed, original, configured)
        with self.assertRaisesRegex(RuntimeError, 'preserved'):
            restore_ls_bytes(b'broken', original, configured)

    def test_atomic_replacement(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.xml'
            path.write_bytes(b'old')
            atomic_bytes(path, b'new')
            self.assertEqual(path.read_bytes(), b'new')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_chiaki_required_defaults_and_mismatch(self):
        self.assertEqual(validate_chiaki_settings({'codec_local_ps5': 'h265_hdr'})['fps_local_ps5'], 60)
        for settings in ({}, {'codec_local_ps5': 'h265_hdr', 'resolution_local_ps5': '720p'},
                         {'codec_local_ps5': 'h265_hdr', 'keyboard_enabled': 'true'},
                         {'codec_local_ps5': 'h265_hdr', 'placebo_preset': 'default'}):
            with self.subTest(settings=settings), self.assertRaises(RuntimeError):
                validate_chiaki_settings(settings)

    def test_identity_includes_creation(self):
        record = dict(exe='/application/chiaki.exe', created=44)
        self.assertTrue(same_identity(('/application/chiaki.exe', 44), record))
        self.assertFalse(same_identity(('/application/chiaki.exe', 45), record))
        self.assertFalse(same_identity(('/different/chiaki.exe', 44), record))

    def test_recovery_rejects_modified_backup(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            session = directory / 'runs' / 'owned'
            session.mkdir(parents=True)
            config_dir = directory / 'Lossless Scaling'
            config_dir.mkdir()
            original = settings_xml()
            configured = configured_ls_settings(original)
            backup = session / 'lossless-settings-original.xml'
            staged = session / 'lossless-settings-configured.xml'
            path = config_dir / 'Settings.xml'
            backup.write_bytes(original + b' ')
            staged.write_bytes(configured)
            path.write_bytes(configured)
            native = object.__new__(NativeChain)
            native.root = directory
            native.idle_ls = lambda _: None
            record = dict(ls_exe='example', backup=str(backup), configured=str(staged),
                          session_dir=str(session), config_path=str(path), original_sha256=digest(original),
                          configured_sha256=digest(configured))
            with patch.dict('os.environ', LOCALAPPDATA=str(directory)):
                with self.assertRaisesRegex(RuntimeError, 'backup changed'):
                    native.restore_ls_config(record)
                record['config_path'] = str(directory / 'unrelated')
                with self.assertRaisesRegex(RuntimeError, 'paths do not match'):
                    native.restore_ls_config(record)
            self.assertEqual(path.read_bytes(), configured)

    def test_recovery_preserves_running_ls(self):
        native = object.__new__(NativeChain)
        native.idle_ls = lambda _: {'pid': 44}
        with self.assertRaisesRegex(RuntimeError, 'running Lossless Scaling'):
            native.restore_ls_config(dict(ls_exe='example', backup='not-read'))


class WindowTests(unittest.TestCase):
    def fixture(self):
        native = object.__new__(NativeChain)
        state = dict(rect=[0, 0, 2560, 1440], style=0x11C40000, exstyle=256, alive=True, mutations=0)
        original = deepcopy(state)
        native.physical_pixels = nullcontext
        native.require_window = lambda _: None
        native.alive = lambda _: state['alive']
        native.monitor_rect = lambda _: [0, 0, 2560, 1440]
        native.focus = lambda _: None
        native.geometry = lambda _: dict(rect=list(state['rect']), dwm=list(state['rect']),
            client=[0, 0, state['rect'][2]-state['rect'][0], state['rect'][3]-state['rect'][1]])

        def set_long(hwnd, index, value):
            state['mutations'] += 1
            state['style' if index == -16 else 'exstyle'] = value
            if index == -16 and not value & (0x00C00000 | 0x00040000):
                state['exstyle'] &= ~0x100  # Observed User32 frame-style side effect.

        def set_position(hwnd, insert, x, y, width, height, flags):
            state['mutations'] += 1
            if not flags & 0x0001:
                state['rect'] = [x, y, x+width, y+height]

        def set_placement(hwnd, placement):
            state['mutations'] += 1
            state['rect'] = list(placement[4])

        native.gui = SimpleNamespace(GetWindowLong=lambda h, i: state['style' if i == -16 else 'exstyle'],
            GetWindowPlacement=lambda h: (0, 3, (0, 0), (0, 0), tuple(state['rect'])),
            SetWindowLong=set_long, SetWindowPos=set_position, SetWindowPlacement=set_placement)
        target = dict(hwnd=4, pid=8, exe='chiaki.exe', created=2, title='chiaki-ng', width=2560, height=1440)
        return native, state, original, target

    def test_window_journal_precedes_all_mutation_and_roundtrips(self):
        native, state, original, target = self.fixture()
        journals = []

        def journal(record):
            self.assertEqual(state['mutations'], 0)
            journals.append(deepcopy(record))

        updated, record = native.prepare_window(target, journal)
        self.assertEqual((updated['width'], updated['height']), (1920, 1080))
        self.assertEqual(state['rect'], [320, 180, 2240, 1260])
        self.assertEqual(journals[0], record)
        self.assertTrue(native.restore_window(record))
        self.assertEqual(state['rect'], original['rect'])
        self.assertEqual(state['style'], original['style'])
        self.assertEqual(state['exstyle'], original['exstyle'])

    def test_external_resize_is_preserved(self):
        native, state, original, target = self.fixture()
        _, record = native.prepare_window(target, lambda _: None)
        state['rect'] = [200, 100, 2100, 1150]
        count = state['mutations']
        with self.assertRaisesRegex(RuntimeError, 'layout changed'):
            native.restore_window(record)
        self.assertEqual(state['mutations'], count)


    def test_restarted_process_is_not_touched(self):
        native, state, original, target = self.fixture()
        _, record = native.prepare_window(target, lambda _: None)
        state['alive'] = False
        count = state['mutations']
        self.assertFalse(native.restore_window(record))
        self.assertEqual(state['mutations'], count)

    def test_unrelated_extended_style_change_is_preserved(self):
        native, state, original, target = self.fixture()
        _, record = native.prepare_window(target, lambda _: None)
        state['exstyle'] |= 0x80  # A new tool-window flag is not our frame change.
        count = state['mutations']
        with self.assertRaisesRegex(RuntimeError, 'layout changed'):
            native.restore_window(record)
        self.assertEqual(state['mutations'], count)


class ReopenTests(unittest.TestCase):
    def native(self):
        native = object.__new__(NativeChain)
        record = dict(pid=42, exe='LosslessScaling.exe', created=10)
        native.idle_ls = lambda _: None
        native.launch_ls = lambda _: ('owned-process', record)
        native.alive = lambda _: True
        native.require_window = lambda _: None
        return native, record

    def test_waits_for_exact_owned_main_window(self):
        native, record = self.native()
        visits = []
        def windows(pid):
            visits.append(pid)
            return [] if len(visits) == 1 else [dict(hwnd=55, title='Lossless Scaling')]
        native.windows = windows
        checked = []
        native.require_window = checked.append
        with patch('chiaki_chain_native.time.sleep'):
            result = native.reopen_ls(dict(idle_ls={'pid': 1}, ls_exe='LosslessScaling.exe'))
        self.assertEqual(result, ('owned-process', record))
        self.assertEqual(visits, [42, 42])
        self.assertEqual(checked, [dict(record, hwnd=55, title='Lossless Scaling')])

    def test_exit_and_timeout_are_reported(self):
        native, record = self.native()
        native.alive = lambda _: False
        with self.assertRaisesRegex(RuntimeError, 'exited before'):
            native.reopen_ls(dict(idle_ls={'pid': 1}, ls_exe='LosslessScaling.exe'))
        native.alive = lambda _: True
        native.windows = lambda _: []
        with patch('chiaki_chain_native.time.monotonic', side_effect=[0, 11]):
            with self.assertRaisesRegex(RuntimeError, 'did not finish'):
                native.reopen_ls(dict(idle_ls={'pid': 1}, ls_exe='LosslessScaling.exe'))


class ReadinessTests(unittest.TestCase):
    def test_bound_default_profile_and_gpu_required_not_just_hwnd(self):
        complete = dict(scale_enabled=True, default_profile_selected=True, profile_title='Default',
                        scaling=['LS1'], frame_generation=['LSFG 3.1'], gpu=['GPU'], display=['Auto'])
        self.assertTrue(ls_ui_ready(complete))
        self.assertFalse(ls_ui_ready({}))
        for key, bad in (('scale_enabled', False), ('default_profile_selected', False),
                         ('profile_title', ''), ('scaling', ['Off']), ('frame_generation', []),
                         ('frame_generation', ['LSFG 2']), ('gpu', []), ('display', [])):
            with self.subTest(key=key, bad=bad):
                self.assertFalse(ls_ui_ready(dict(complete, **{key: bad})))

if __name__ == '__main__':
    unittest.main()
