"""Source contracts for the isolated FP16 NR working-texture experiment."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stage_nr_precision import main, patch_source


SOURCE = '''
    v.nr_small = v.upscale && asked;
    if (!EnsureScalePipeline()) { v.nr_small = false; }
            nd.Width = v.nr_w; nd.Height = v.nr_h;
                Log("[nr] %ux%u working textures failed - staying at full resolution",
                v.nr_small = false;
static void BindScale4Descriptors() {
    sd.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    ud.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
}
static void ScaleColorInto() {}
static void BindResidualDescriptors() {
    sd.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    for (int i = 0; i < 3; ++i) {
        h.dev->CreateShaderResourceView(i == 0 ? native : (i == 1 ? nr_in : nr_out),
                                        &sd, cpu);
    }
    ud.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
}
static void ResidualCompose() {}
    if (!HudGuardPrepare(v)) return false;
'''


class PrecisionPatchTests(unittest.TestCase):
    def test_work_only_formats_and_marker(self):
        result = patch_source(SOURCE)
        self.assertIn('nd.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;', result)
        self.assertIn('sd.Format = src->GetDesc().Format;', result)
        self.assertIn('ud.Format = dst->GetDesc().Format;', result)
        self.assertIn('sd.Format = input->GetDesc().Format;', result)
        self.assertIn('ud.Format = DXGI_FORMAT_R8G8B8A8_UNORM;', result)
        self.assertIn('nr_in_format=%u nr_out_format=%u full_color_format=%u full_output_format=%u', result)

    def test_format_and_shape_failure_are_explicit(self):
        result = patch_source(SOURCE)
        self.assertIn('!v.nr_small || (hgt != 720 && hgt != 1080)', result)
        self.assertIn('D3D12_FORMAT_SUPPORT2_UAV_TYPED_LOAD | D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE', result)
        self.assertIn('v.nr_in->GetDesc().Format != DXGI_FORMAT_R16G16B16A16_FLOAT', result)
        self.assertIn('v.nr_out->GetDesc().Format != DXGI_FORMAT_R16G16B16A16_FLOAT', result)
        self.assertNotIn('staying at full resolution', result)
        self.assertNotIn('v.nr_small = false;', result)

    def test_missing_or_ambiguous_anchor_is_rejected(self):
        for value in ('changed', SOURCE+SOURCE):
            with self.assertRaisesRegex(RuntimeError, 'Ambiguous'):
                patch_source(value)

    def test_existing_experiment_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'native-face-fp16').mkdir()
            with patch('stage_nr_precision.__file__', str(root/'stage_nr_precision.py')), \
                 patch('stage_nr_precision.subprocess.run') as build:
                with self.assertRaisesRegex(RuntimeError, 'Preserve'):
                    main()
                build.assert_not_called()

    def test_local_source_preserves_full_proxy_and_shader_arithmetic(self):
        root = Path(__file__).parent
        candidates = [root/'native-hdr-color', root/'evidence/hdr-source']
        folder = next((p for p in candidates if (p/'dlss5-feed-host64.cpp').exists()
                       and (p/'quality_shaders.h').exists()), None)
        if folder is None:
            self.skipTest('Private source snapshot is not distributed')
        original = (folder/'dlss5-feed-host64.cpp').read_text(encoding='utf-8-sig')
        result = patch_source(original)
        self.assertIn('CreateVideoTex(v.color, cw, ch, DXGI_FORMAT_R8G8B8A8_UNORM, cw * 4)', result)
        self.assertIn('td.Format = DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count = 1;', result)
        start, end = original.index('static const char kResidualHlsl[]'), original.index('typedef HRESULT(WINAPI *PFN_D3DCompile_)')
        self.assertIn(original[start:end], result)
        shader = (folder/'quality_shaders.h').read_text()
        self.assertNotIn('round(', shader)
        self.assertNotIn('255', shader)
        self.assertIn('gDst[id.xy]=sum/((end.x-lo.x)*(end.y-lo.y));', shader)


if __name__ == '__main__':
    unittest.main()
