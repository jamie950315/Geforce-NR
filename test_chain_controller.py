import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from chain_controller import ChainController, alive, atomic, job_path, recover, valid_token
from shared_json import read_json


class ChainOwnershipTests(unittest.TestCase):
    def test_atomic_status_updates_with_concurrent_reader(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'status.json';atomic(path,dict(counter=0))
            done=threading.Event();errors=[]
            def reader():
                try:
                    while not done.is_set():
                        self.assertIsInstance(read_json(path)['counter'],int)
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=reader);thread.start()
            try:
                for count in range(200):atomic(path,dict(counter=count))
            finally:
                done.set();thread.join(timeout=3)
            self.assertFalse(errors,errors)
            self.assertEqual(read_json(path)['counter'],199)

    def test_tokens_and_paths_fail_closed(self):
        self.assertTrue(valid_token('a'*32))
        for invalid in ('a'*31, 'g'*32, None, 1):
            self.assertFalse(valid_token(invalid))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for bad in (root/'elsewhere',root/'runs'/'other',root/'runs'/'chiaki-chain-a'/'nested'):
                with self.assertRaises(RuntimeError):job_path(root,bad)
            self.assertEqual(job_path(root,root/'runs'/'chiaki-chain-a'),(root/'runs'/'chiaki-chain-a').resolve())

    def test_pid_reuse_is_not_alive(self):
        win=SimpleNamespace(identity=lambda pid:('app',200))
        self.assertFalse(alive(win,42,100))
        self.assertTrue(alive(win,42,200))

    def test_start_and_stop_are_bound_to_own_job(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'app';root.mkdir()
            runtime=root.parent/'gfn-nr-overlay/.venv/Scripts/pythonw.exe'
            runtime.parent.mkdir(parents=True);runtime.touch()
            c=ChainController(root,SimpleNamespace(identity=lambda pid:('python',123)))
            process=Mock();process.poll.return_value=None
            with patch('chain_controller.subprocess.Popen',return_value=process):
                c.start(dict(hwnd=1,pid=2,created=3,title='chiaki-ng'))
            self.assertTrue(c.busy)
            self.assertEqual(json.loads((c.job/'request.json').read_text())['token'],c.token)
            c.stop()
            self.assertEqual(json.loads((c.job/'stop.json').read_text()),{'token':c.token})
            with self.assertRaises(RuntimeError):c.start({})
            atomic(c.job/'status.json',dict(token='b'*32,state='running'))
            with self.assertRaisesRegex(RuntimeError,'ownership'):c.poll()

    def test_unexpected_supervisor_exit_is_not_success(self):
        c=ChainController('.',None)
        c.process=SimpleNamespace(poll=lambda:1)
        c.last=dict(state='running',nr_confirmed=True)
        self.assertEqual(c.poll()['state'],'error')
        self.assertFalse(c.poll()['nr_confirmed'])

    def test_recovery_never_touches_live_foreign_chain(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pointer=root/'chiaki-chain-active.json'
            atomic(pointer,dict(token='a'*32,pid=10,created=20,run=str(root/'runs'/'chiaki-chain-old')))
            native=Mock()
            with self.assertRaisesRegex(RuntimeError,'active'):
                recover(root,native,SimpleNamespace(identity=lambda pid:('app',20)),pointer)
            native.stop_ls.assert_not_called()
            self.assertTrue(pointer.exists())

    def test_dead_chain_recovery_restores_only_journaled_resources(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'runs'/'chiaki-chain-old';folder.mkdir(parents=True)
            pointer=root/'chiaki-chain-active.json'
            old=dict(token='a'*32,pid=10,created=20,run=str(folder))
            atomic(pointer,old)
            atomic(folder/'journal.json',dict(old,ls_process={'pid':30},ls_config={'id':1},window={'hwnd':2},preflight={}))
            native=Mock()
            recover(root,native,SimpleNamespace(identity=lambda pid:('app',99)),pointer)
            native.stop_ls.assert_called_once_with({'pid':30})
            native.restore_window.assert_called_once_with({'hwnd':2})
            native.restore_ls_config.assert_called_once_with({'id':1})
            self.assertFalse(pointer.exists())
            self.assertTrue(json.loads((folder/'recovery.json').read_text())['restored'])

    def test_recovery_failure_preserves_journal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'runs'/'chiaki-chain-old';folder.mkdir(parents=True)
            pointer=root/'chiaki-chain-active.json';old=dict(token='a'*32,pid=10,created=20,run=str(folder))
            atomic(pointer,old);atomic(folder/'journal.json',dict(old,window={'hwnd':2}))
            native=Mock();native.restore_window.side_effect=RuntimeError('User resized window')
            with self.assertRaises(RuntimeError):recover(root,native,SimpleNamespace(identity=lambda pid:('app',99)),pointer)
            self.assertTrue(pointer.exists())


if __name__=='__main__':unittest.main()
