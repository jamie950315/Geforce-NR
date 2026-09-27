"""Bounded source and native SceneHistory checks for the isolated repair."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from stage_motion_repair import PINNED_INPUTS, digest, main, patch_sources, verified_inputs


CPP = '''    if (gc.width == 0 || gc.height == 0) { Log("[gray] off"); return true; }
    const size_t need = static_cast<size_t>(gc.width) * gc.height;
    g_gray_file = OpenFileMappingA(FILE_MAP_WRITE, FALSE, name);
'''
FLOW = 'v=v/32.0*float2(w,h)/float2(iw,ih);\nmotion[p.xy]=reset || dot(v,v)<.25 ? float2(0,0) : v;'
HISTORY = 'namespace gfn_core {\nif (!gray || bytes == 0 || bytes > 1024u * 1024u) { clear(); return true; }\n}'


class MotionRepairTests(unittest.TestCase):
    def files(self):
        return {'dlss5-feed-host64.cpp':CPP,'nvofa.inl':FLOW,'gfn_flow_control.hpp':HISTORY}

    def test_subpixel_motion_is_preserved_without_changing_scale_or_reset(self):
        result=patch_sources(self.files())
        self.assertEqual(result['nvofa.inl'],FLOW.replace('reset || dot(v,v)<.25','reset'))
        self.assertIn('max_gray_bytes = 7680u * 4320u;',result['gfn_flow_control.hpp'])
        self.assertIn('bytes > max_gray_bytes',result['gfn_flow_control.hpp'])

    def test_gray_bounds_precede_mapping_and_preserve_off(self):
        result=patch_sources(self.files())['dlss5-feed-host64.cpp']
        off=result.index('gc.width == 0 || gc.height == 0')
        bounds=result.index('gc.width > 7680u || gc.height > 4320u')
        capacity=result.index('need > gfn_core::max_gray_bytes')
        mapping=result.index('OpenFileMappingA')
        self.assertEqual([off,bounds,capacity,mapping],sorted([off,bounds,capacity,mapping]))

    def test_changed_or_duplicate_source_is_rejected(self):
        for value in ('changed',FLOW+FLOW):
            files=self.files();files['nvofa.inl']=value
            with self.assertRaisesRegex(RuntimeError,'Ambiguous'):
                patch_sources(files)

    def test_existing_build_and_record_are_preserved(self):
        for exists in ('native-hdr-color-motion-repaired','hdr-color-motion-repaired-build.json'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                (root/exists).touch()
                with patch('stage_motion_repair.__file__',str(root/'stage_motion_repair.py')), \
                     patch('stage_motion_repair.subprocess.run') as build:
                    with self.assertRaisesRegex(RuntimeError,'Preserve'):
                        main()
                    build.assert_not_called()

    def test_changed_ancestor_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'hdr-color-queued-build.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'record changed'):
                verified_inputs(root,root,{'parent_build_sha256':'0'*64})

    def test_actual_pinned_sources_and_native_history_contract(self):
        root=Path(__file__).parent
        history=root/'evidence/flow-audit/gfn_flow_control.hpp'
        flow=root/'evidence/hdr-source/nvofa.inl'
        compiler=shutil.which('clang++') or shutil.which('g++')
        if not history.exists() or not flow.exists() or not compiler:
            self.skipTest('Pinned private source snapshots and a local C++ compiler are required')
        self.assertEqual(digest(history),PINNED_INPUTS['gfn_flow_control.hpp'])
        self.assertEqual(digest(flow),PINNED_INPUTS['nvofa.inl'])
        files=self.files()
        files['gfn_flow_control.hpp']=history.read_text()
        files['nvofa.inl']=flow.read_text()
        result=patch_sources(files)
        program='''#include "history.hpp"
#include <algorithm>
#include <cassert>
int main() {
    static_assert(gfn_core::max_gray_bytes == 7680u*4320u, "history bound");
    gfn_core::SceneHistory history;
    std::vector<std::uint8_t> gray(1600u*900u,0);
    assert(history.observe(gray.data(),gray.size(),0,true));
    assert(!history.observe(gray.data(),gray.size(),10,true));
    history.request_reset(true);
    assert(!history.observe(gray.data(),gray.size(),20,false));
    assert(history.observe(gray.data(),gray.size(),30,true));
    assert(!history.observe(gray.data(),gray.size(),40,true));
    std::fill(gray.begin(),gray.end(),255);
    assert(history.observe(gray.data(),gray.size(),50,true));
    assert(!history.observe(gray.data(),gray.size(),60,true));
    assert(history.observe(gray.data(),gray.size(),1061,true));
    assert(history.observe(gray.data(),gray.size(),900,true));
    assert(!history.observe(gray.data(),gray.size(),1900,true));
    assert(history.observe(gray.data(),gray.size(),2901,true));
    std::uint8_t byte=0;
    assert(history.observe(&byte,gfn_core::max_gray_bytes+1,2910,true));
    assert(history.observe(gray.data(),gray.size(),2920,true));
    assert(!history.observe(gray.data(),gray.size(),2930,true));
    assert(history.observe(nullptr,gray.size(),2940,true));
    assert(history.observe(&byte,0,2950,true));
}
'''
        with tempfile.TemporaryDirectory() as folder:
            temp=Path(folder)
            (temp/'history.hpp').write_text(result['gfn_flow_control.hpp'])
            (temp/'check.cpp').write_text(program)
            subprocess.run([compiler,'-std=c++17','-O1',str(temp/'check.cpp'),'-o',str(temp/'check')],
                           check=True,capture_output=True,text=True,timeout=30)
            subprocess.run([str(temp/'check')],check=True,capture_output=True,text=True,timeout=10)


if __name__=='__main__':
    unittest.main()
