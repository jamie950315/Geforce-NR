"""Contracts for complete-image duplicate detection and isolated staging."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from stage_static_capture import main, patch_source
from stage_hdr import digest
from static_support import verify_static_build
import json


class StaticCaptureTests(unittest.TestCase):
    def test_static_build_refuses_missing_policy_and_modified_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); native=root/'native-static-stable';native.mkdir()
            for name in ('nvngx.dll','nvngx_dlssnr.dll'): (native/name).write_bytes(name.encode())
            data=dict(static_stable=True,mapping='color-preserving',queued=True,capture_queued=True,
                motion_repaired=True,d3d11_cpu_wait=True,worker_sha256=digest(native/'nvngx.dll'),
                runtime_sha256=digest(native/'nvngx_dlssnr.dll'))
            record=root/'static-stable-build.json'
            record.write_text(json.dumps(data))
            self.assertEqual(verify_static_build(root)[0],native)
            for policy in ({'static_stable':1},{'motion_repaired':False},{'d3d11_cpu_wait':False}):
                record.write_text(json.dumps(dict(data,**policy)))
                with self.assertRaisesRegex(RuntimeError,'policy mismatch'): verify_static_build(root)
            record.write_text(json.dumps(data));(native/'nvngx.dll').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'integrity mismatch'): verify_static_build(root)

    def test_existing_build_is_preserved(self):
        for name in ('native-static-stable','static-stable-build.json'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder); (root/name).touch()
                with patch('stage_static_capture.__file__',str(root/'stage_static_capture.py')):
                    with self.assertRaisesRegex(RuntimeError,'Preserve'):
                        main()

    def test_capture_policy_does_not_reuse_unrendered_captures(self):
        compiler=shutil.which('clang++') or shutil.which('g++')
        if not compiler: self.skipTest('A C++ compiler is required')
        header=Path(__file__).parent/'static_compare.h'
        program='''#include "static_compare.h"
#include <cassert>
int main() {
    GfnStaticFramePolicy p;
    assert(!p.capture(false));
    assert(!p.capture(true));
    assert(!p.capture(false));
    p.rendered();
    assert(p.capture(false));
    assert(p.capture(false));
    assert(!p.capture(true));
    assert(!p.capture(false));
    p.rendered();
    assert(p.capture(false));
    p.clear();
    assert(!p.capture(false));
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); shutil.copy2(header,root/header.name)
            (root/'check.cpp').write_text(program)
            subprocess.run([compiler,'-std=c++17',str(root/'check.cpp'),'-o',str(root/'check')],
                           check=True,capture_output=True,timeout=30)
            subprocess.run([str(root/'check')],check=True,capture_output=True,timeout=10)

    def test_source_order_and_snapshot_reset_contract(self):
        source=Path(__file__).parent/'evidence/graphics-review/dlss5-feed-host64.cpp'
        if not source.exists(): self.skipTest('Private attested parent source is required')
        old=source.read_text(encoding='utf-8-sig'); new=patch_source(old)
        compare=new.index('if (!RecordStaticCapture(g_dda_d12))')
        fence=new.index('const UINT64 fence = EndCommands();',compare)
        gray=new.index('g_capture_gray_ok = AreaToGray(fence)',fence)
        read=new.index('if (!ReadStaticCapture())',gray)
        self.assertEqual([compare,fence,gray,read],sorted([compare,fence,gray,read]))
        self.assertIn('g_force_next_frame || fh.reset != 0',new)
        self.assertIn('g_static_equal && warmup_done && !out_changed',new)
        self.assertIn('CloseStaticCapture();',new)
        self.assertIn('if (CaptureActive()) g_static_policy.rendered();',new)
        with self.assertRaisesRegex(RuntimeError,'Ambiguous'):
            patch_source(new)


if __name__=='__main__': unittest.main()
