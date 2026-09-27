import unittest
from unittest.mock import patch
import chiaki_connect as c


class ChiakiConnectTests(unittest.TestCase):
    def test_registry_mac_is_not_a_credential(self):
        self.assertEqual(c._mac('@ByteArray(ABCDEF)'), b'ABCDEF'.hex())
        with self.assertRaises(c.ChiakiConnectionError):
            c._mac('@ByteArray(short)')

    def test_only_awake_ps5_discovery(self):
        packet = b'HTTP/1.1 200 Ok\ndevice-discovery-protocol-version:00030010\nhost-id:112233445566\n'
        self.assertEqual(c.parse_discovery(packet, '192.0.2.1'), ('112233445566', '192.0.2.1'))
        for bad in (packet.replace(b'200', b'620'), packet.replace(b'00030010', b'00020020'),
                    packet + b'host-id:667788990011\n', packet.replace(b'112233445566', b'bad')):
            self.assertIsNone(c.parse_discovery(bad, '192.0.2.1'))

    def test_console_selection_is_exact_and_unambiguous(self):
        one = c.Console('Example PS5', '112233445566')
        two = c.Console('Other PS5', '667788990011')
        self.assertEqual(c.choose_console([one, two], {(one.mac, '192.0.2.1')}), (one, '192.0.2.1'))
        for discovery in (set(), {(one.mac, '192.0.2.1'), (two.mac, '192.0.2.2')},
                          {(one.mac, '192.0.2.1'), (one.mac, '192.0.2.2')}):
            with self.assertRaises(c.ChiakiConnectionError):
                c.choose_console([one, two], discovery)

    def test_duplicate_nicknames_rejected(self):
        with self.assertRaises(c.ChiakiConnectionError):
            c.choose_console([c.Console('Same', '112233445566'), c.Console('Same', '667788990011')],
                             {('112233445566', '192.0.2.1')})

    def test_decoder_initialization_is_not_video(self):
        self.assertFalse(c.received_video('Using hardware decoder "vulkan"'))
        self.assertFalse(c.received_video('StreamConnection successfully received streaminfo'))

    def test_received_video_and_disconnect(self):
        ready = 'StreamConnection successfully received streaminfo\nSwitched to profile 0, resolution: 1920x1080\n'
        self.assertTrue(c.received_video(ready))
        self.assertFalse(c.received_video(ready.replace('1920x1080', '1280x720')))
        for marker in ('Session has quit', 'StreamConnection is disconnecting', 'StreamConnection closed takion'):
            self.assertFalse(c.received_video(ready + marker))
        self.assertFalse(c.received_video(ready + 'Session has quit\nStreamConnection successfully received streaminfo'))

    def test_settings_contract(self):
        settings = dict(placebo_preset='high_quality', resolution_local_ps5='1080p',
                        fps_local_ps5=60, codec_local_ps5='h265_hdr')
        c.validate_configuration(settings)
        for key in settings:
            with self.assertRaises(c.ChiakiConnectionError):
                c.validate_configuration(dict(settings, **{key: 'wrong'}))

    def test_active_connection_without_video_does_not_launch(self):
        target = dict(pid=42, exe='chiaki.exe')
        with patch.object(c, 'read_configuration', return_value=[c.Console('Example', '112233445566')]), \
             patch.object(c, 'is_streaming', return_value=False), \
             patch.object(c, 'tcp_stream_pids', return_value={42}), \
             patch.object(c.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(c.ChiakiConnectionError, 'awaiting login'):
                c.acquire_stream(None, lambda: [target])
            launch.assert_not_called()

    def test_active_stream_is_reused_without_any_launch(self):
        target = dict(pid=42, exe='chiaki.exe')
        with patch.object(c, 'read_configuration', return_value=[]), \
             patch.object(c, 'is_streaming', return_value=True), \
             patch.object(c, 'tcp_stream_pids', return_value={42}), \
             patch.object(c.subprocess, 'Popen') as launch:
            self.assertEqual(c.acquire_stream(None, lambda: [target]), target)
            launch.assert_not_called()

    def test_hidden_stream_blocks_competing_connection(self):
        from unittest.mock import Mock
        win = Mock()
        win.identity.return_value = ('chiaki.exe', 1)
        with patch.object(c, 'read_configuration', return_value=[]), \
             patch.object(c, 'tcp_stream_pids', return_value={42}), \
             patch.object(c.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(c.ChiakiConnectionError, 'minimized'):
                c.acquire_stream(win, lambda: [])
            launch.assert_not_called()

    def test_idle_home_reuses_stream_from_same_installation(self):
        from unittest.mock import Mock
        home = dict(pid=41, exe='chiaki.exe', created=1)
        stream = dict(pid=42, exe='chiaki.exe', created=2)
        win = Mock()
        win.identity.return_value = ('chiaki.exe', 1)
        with patch.object(c, 'read_configuration', return_value=[]), \
             patch.object(c, 'tcp_stream_pids', return_value={42}), \
             patch.object(c, 'is_streaming', side_effect=lambda pid: pid == 42), \
             patch.object(c.subprocess, 'Popen') as launch:
            self.assertEqual(c.acquire_stream(win, lambda: [home, stream], selected=home), stream)
            launch.assert_not_called()
            win.identity.return_value = ('chiaki.exe', 99)
            with self.assertRaises(c.ChiakiConnectionError):
                c.acquire_stream(win, lambda: [home, stream], selected=home)


if __name__ == '__main__':
    unittest.main()
