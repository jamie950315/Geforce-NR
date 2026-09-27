"""Capture queue patch safety contracts; live GPU correctness is separate."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stage_capture_queue import main, patch_source


SOURCE = '''static void CloseGray()
{
    if (g_gray_readback) { g_gray_readback->Release(); g_gray_readback = nullptr; }
}
    if (!EnsureGrayPipeline()) return false;
// Called from DdaGrab after the swizzle (it cannot be in the same Begin/End
// block - a separate fence is needed), hence its own Begin/End here.
static bool AreaToGray()
{
    if (!g_gray_mapped || !g_dda_dst) return false;
    if (!BeginCommands()) return false;
    auto cpu = g_dda_heap->GetCPUDescriptorHandleForHeapStart();
    ID3D12DescriptorHeap *heaps[] = { g_dda_heap };
    auto gpu = g_dda_heap->GetGPUDescriptorHandleForHeapStart();
    const UINT64 fence = EndCommands();
    if (!ProfileWait(PS_GRAY, fence, 10000)) { Log("[gray] fence timeout"); return false; }
    g_gray_readback->Map();
    return true;
}
// Adaptive exposure unchanged
static bool SwizzleCaptureIntoColor() {
    const UINT64 fence = EndCommands();
    if (!ProfileWait(PS_SWIZZLE, fence, 10000)) { Log("[cap] swizzle fence timeout"); return false; }
    // Hand the client the luminance frame (320x180) for the optical flow
    g_capture_gray_ok = AreaToGray() && g_gray_mapped;
    if (g_submission_failed) return false;
    UpdateAdaptiveExposure();
}
'''


class CaptureQueueTests(unittest.TestCase):
    def test_gray_owns_separate_heap_until_close(self):
        result = patch_source(SOURCE)
        gray = result[result.index('static bool AreaToGray'):result.index('// Adaptive exposure')]
        self.assertNotIn('g_dda_heap', gray)
        self.assertEqual(gray.count('g_capture_gray_heap'), 4)
        self.assertIn('gray_heap.NumDescriptors = 2;', result)
        self.assertIn('g_capture_gray_heap->Release(); g_capture_gray_heap = nullptr;', result)

    def test_final_gray_wait_precedes_cpu_readback(self):
        result = patch_source(SOURCE)
        self.assertIn('!fence || fence <= swizzle_fence', result)
        self.assertLess(result.index('ProfileWait(PS_GRAY'), result.index('g_gray_readback->Map()'))
        self.assertLess(result.index('AreaToGray(fence);'), result.index('UpdateAdaptiveExposure();'))
        self.assertIn('return FailGpuWork("capture-gray", "begin-after-swizzle", E_FAIL);', result)
        self.assertIn('return FailGpuWork("capture-gray", "queued-readback-failed", E_FAIL);', result)
        self.assertIn('} else {\n        // No gray consumer', result)
        self.assertIn('ProfileWait(PS_SWIZZLE, fence, 10000)', result)

    def test_changed_or_duplicate_anchor_is_rejected(self):
        for source in ('changed', SOURCE+SOURCE):
            with self.assertRaises((RuntimeError, ValueError)):
                patch_source(source)

    def test_existing_variant_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'native-hdr-color-capture-queued').mkdir()
            with patch('stage_capture_queue.__file__', str(root/'stage_capture_queue.py')), \
                 patch('stage_capture_queue.subprocess.run') as build:
                with self.assertRaisesRegex(RuntimeError, 'Preserve'):
                    main()
                build.assert_not_called()

    def test_actual_source_preserves_d3d11_lifetime_and_math(self):
        root = Path(__file__).parent
        candidates = [root/'native-hdr-color-queued/dlss5-feed-host64.cpp',
                      root/'evidence/hdr-source/dlss5-feed-host64.cpp']
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            self.skipTest('Private source snapshot is not distributed')
        original = path.read_text(encoding='utf-8-sig')
        result = patch_source(original)
        start = original.index('static StageResult StageCapturedFrame(')
        end = original.index('static bool SwizzleCaptureIntoColor(', start)
        self.assertIn(original[start:end], result)
        for name in ('kResidualHlsl', 'kScaleHlsl'):
            start = original.index('static const char '+name+'[]')
            end = original.index('"}\\n";', start)+len('"}\\n";')
            self.assertIn(original[start:end], result)
        self.assertIn('tex->Release();\n        frame.Close();', result)
        self.assertIn('g_capture_gray_ok = AreaToGray(fence);', result)


if __name__ == '__main__':
    unittest.main()
