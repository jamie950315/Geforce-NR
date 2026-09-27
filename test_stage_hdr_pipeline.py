"""Queued HDR source-patch contracts; GPU execution is a separate validation."""
from pathlib import Path
import unittest

from stage_hdr import build_kind, patch_queued_tail, patch_sources


SOURCE = '''static bool PresentHdr(VideoState &v, bool bypass);
static bool PresentFrame(VideoState &v, UINT64 *submitted = nullptr) {
    if (g_hdr_capture) return PresentHdr(v, false);
}
static bool PresentBypass(VideoState &v) { return PresentHdr(v, true); }
defer_tail = !g_hdr_capture && warmup_done && h.feature != nullptr &&
    PresentModeActive(v) &&
    (fh.reserved & (FRAME_FLAG_BYPASS | FRAME_FLAG_SPLIT | FRAME_FLAG_WANT_PIXELS)) == 0;
if (defer_tail && eval_done <= upload_done) return 9;
if (defer_tail && present_done <= eval_done) return 9;
'''
PRESENT = '''static bool PresentHdr(VideoState &v, bool bypass)
{
    const bool framegen = FgRequested() && !bypass;
    const auto fence = EndCommands();
    if (!WaitFenceValue(h.fence, fence, 2000, "hdr-present"))
    {
        if (g_submission_failed) bb.detach();
        return false;
    }
    // The same status reading as the SDR path: a mode change is a SUCCESS
    if (framegen) return PresentHdr(v, bypass);
    const bool ok = PresentStatus(g_present_swap->Present(0, 0), "hdr present");
    if (ok && (!GfnHdrStatus(w, height) || !GfnHdrProof(v, bypass))) return false;
    return ok;
}
'''


class QueuedHdrPatchTests(unittest.TestCase):
    def test_build_is_opt_in_and_color_preserving_only(self):
        self.assertEqual(build_kind('legacy'), 'hdr')
        self.assertEqual(build_kind('color-preserving'), 'hdr-color')
        self.assertEqual(build_kind('color-preserving', True), 'hdr-color-queued')
        with self.assertRaisesRegex(ValueError, 'color-preserving'):
            build_kind('legacy', True)
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            build_kind('other', True)

    def test_frame_eligibility_and_synchronous_branches_are_preserved(self):
        source, present = patch_queued_tail(SOURCE, PRESENT)
        self.assertIn('(!g_hdr_capture || HdrQueuedTailAllowed()) && warmup_done', source)
        self.assertIn('FRAME_FLAG_BYPASS | FRAME_FLAG_SPLIT | FRAME_FLAG_WANT_PIXELS', source)
        self.assertIn('return !FgRequested();', present)
        self.assertNotIn('GetEnvironmentVariableW(L"GFN_HDR_PROOF_DIR"', present)
        self.assertIn('return PresentHdr(v, true);', source)
        self.assertIn('if (framegen) return PresentHdr(v, bypass);', present)
        self.assertIn('submitted && (bypass || !HdrQueuedTailAllowed())', present)

    def test_final_fence_wait_and_failure_lifetime_remain_mandatory(self):
        source, present = patch_queued_tail(SOURCE, PRESENT)
        self.assertIn('return PresentHdr(v, false, submitted);', source)
        self.assertIn('UINT64 *submitted = nullptr);', source)
        self.assertIn('eval_done <= upload_done', source)
        self.assertIn('present_done <= eval_done', source)
        reset = present.index('if (submitted) *submitted = 0;')
        submit = present.index('const auto fence = EndCommands();')
        token = present.index('if (submitted) *submitted = fence;')
        wait = present.index('WaitFenceValue(h.fence, fence, submitted ? 60000 : 2000')
        show = present.index('g_present_swap->Present(0, 0)')
        proof = present.index('GfnHdrProof(v, bypass)')
        self.assertEqual([reset, submit, token, wait, show, proof], sorted([reset, submit, token, wait, show, proof]))
        self.assertIn('if (g_submission_failed) bb.detach();\n        return false;', present)
        self.assertLess(wait, present.index('[hdr-tail] queued motion/NR retired'))

    def test_patch_rejects_changed_or_ambiguous_source(self):
        for source in (SOURCE.replace('!g_hdr_capture && warmup_done', 'warmup_done'), SOURCE+SOURCE):
            with self.assertRaisesRegex(RuntimeError, 'Ambiguous HDR patch anchor'):
                patch_queued_tail(source, PRESENT)

    def test_full_local_source_preserves_shader_and_proof_hooks(self):
        folder = Path(__file__).parent/'evidence/hdr-source'
        names = ('dlss5-feed-host64.cpp', 'hdr_display.h', 'hdr_present.inl', 'hdr_shaders.h', 'hud_guard.inl')
        if not all((folder/name).exists() for name in names):
            self.skipTest('Private repaired-source snapshot is not distributed')
        original = {name:(folder/name).read_text(encoding='utf-8-sig') for name in names}
        normal = patch_sources(dict(original), 'color-preserving')
        queued = patch_sources(dict(original), 'color-preserving', True)
        for name in ('hdr_shaders.h', 'hdr_display.h', 'hud_guard.inl'):
            self.assertEqual(queued[name], normal[name])
        self.assertIn('!GfnHdrStatus(w, height) || !GfnHdrProof(v, bypass)', queued['hdr_present.inl'])
        self.assertIn('if (present_done <= eval_done)', queued['dlss5-feed-host64.cpp'])


if __name__ == '__main__':
    unittest.main()
