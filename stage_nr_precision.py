"""Stage a file-fed NR work-texture precision experiment, never a daily default."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from stage_hdr import patch_once


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_source(source):
    source = patch_once(source, '    v.nr_small = v.upscale && asked;',
        '''    v.nr_small = v.upscale && asked;
    if (!v.nr_small || (hgt != 720 && hgt != 1080)) {
        Log("[nr-precision] experiment requires reduced NR720 or NR1080; refusing fallback");
        return false;
    }
    D3D12_FEATURE_DATA_FORMAT_SUPPORT fp16 = {DXGI_FORMAT_R16G16B16A16_FLOAT};
    const UINT fp16_srv = D3D12_FORMAT_SUPPORT1_TEXTURE2D |
        D3D12_FORMAT_SUPPORT1_SHADER_LOAD | D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE |
        D3D12_FORMAT_SUPPORT1_TYPED_UNORDERED_ACCESS_VIEW;
    const UINT fp16_uav = D3D12_FORMAT_SUPPORT2_UAV_TYPED_LOAD | D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE;
    if (FAILED(h.dev->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &fp16, sizeof(fp16))) ||
        (fp16.Support1 & fp16_srv) != fp16_srv || (fp16.Support2 & fp16_uav) != fp16_uav) {
        Log("[nr-precision] FP16 texture views unsupported; refusing fallback");
        return false;
    }''')
    source = patch_once(source, 'if (!EnsureScalePipeline()) { v.nr_small = false; }',
        'if (!EnsureScalePipeline()) { Log("[nr-precision] scale pipeline failed"); return false; }')
    source = patch_once(source, '            nd.Width = v.nr_w; nd.Height = v.nr_h;',
        '            nd.Width = v.nr_w; nd.Height = v.nr_h;\n            nd.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;')
    source = patch_once(source,
        'Log("[nr] %ux%u working textures failed - staying at full resolution",',
        'Log("[nr-precision] %ux%u FP16 working textures failed - refusing fallback",')
    source = patch_once(source, '                v.nr_small = false;', '                return false;')
    # Restrict changes to these view builders: full proxy/output and motion
    # resources intentionally retain their existing formats and semantics.
    begin = source.index('static void BindScale4Descriptors(')
    end = source.index('static void ScaleColorInto(', begin)
    scale = source[begin:end]
    scale = patch_once(scale, 'sd.Format = DXGI_FORMAT_R8G8B8A8_UNORM;', 'sd.Format = src->GetDesc().Format;')
    scale = patch_once(scale, 'ud.Format = DXGI_FORMAT_R8G8B8A8_UNORM;', 'ud.Format = dst->GetDesc().Format;')
    source = source[:begin]+scale+source[end:]
    begin = source.index('static void BindResidualDescriptors(')
    end = source.index('static void ResidualCompose(', begin)
    residual = source[begin:end]
    residual = patch_once(residual,
        '        h.dev->CreateShaderResourceView(i == 0 ? native : (i == 1 ? nr_in : nr_out),\n                                        &sd, cpu);',
        '''        ID3D12Resource *input = i == 0 ? native : (i == 1 ? nr_in : nr_out);
        sd.Format = input->GetDesc().Format;
        h.dev->CreateShaderResourceView(input, &sd, cpu);''')
    source = source[:begin]+residual+source[end:]
    source = patch_once(source, '    if (!HudGuardPrepare(v)) return false;',
        '''    if (!v.nr_small || !v.nr_in || !v.nr_out ||
        v.nr_in->GetDesc().Format != DXGI_FORMAT_R16G16B16A16_FLOAT ||
        v.nr_out->GetDesc().Format != DXGI_FORMAT_R16G16B16A16_FLOAT ||
        v.color.tex->GetDesc().Format != DXGI_FORMAT_R8G8B8A8_UNORM ||
        v.output->GetDesc().Format != DXGI_FORMAT_R8G8B8A8_UNORM) {
        Log("[nr-precision] texture format contract failed; refusing evaluate");
        return false;
    }
    static bool precision_reported = false;
    if (!precision_reported) {
        Log("[nr-precision] nr_in_format=%u nr_out_format=%u full_color_format=%u full_output_format=%u size=%ux%u",
            unsigned(v.nr_in->GetDesc().Format), unsigned(v.nr_out->GetDesc().Format),
            unsigned(v.color.tex->GetDesc().Format), unsigned(v.output->GetDesc().Format), v.nr_w, v.nr_h);
        precision_reported = true;
    }
    if (!HudGuardPrepare(v)) return false;''')
    return source


def main():
    root = Path(__file__).resolve().parent
    source, dest = root/'native-hdr-color', root/'native-face-fp16'
    record_path = root/'face-fp16-build.json'
    if dest.exists() or record_path.exists():
        raise RuntimeError('Preserve the existing precision experiment before staging another build')
    build = json.loads((root/'hdr-color-build.json').read_text(encoding='utf-8-sig'))
    if build.get('mapping') != 'color-preserving' or build.get('queued', False):
        raise RuntimeError('Expected the attested synchronous color-preserving HDR build')
    checks = dict(build['patched'])
    checks.update({'nvngx.dll':build['worker_sha256'], 'nvngx_dlssnr.dll':build['runtime_sha256'],
                   'dlss5-feed-host64.cpp':build['source_sha256']})
    for name, expected in checks.items():
        if Path(name).name != name or digest(source/name) != expected:
            raise RuntimeError('Precision source integrity mismatch: '+name)
    patched = patch_source((source/'dlss5-feed-host64.cpp').read_text(encoding='utf-8-sig'))
    template = root/'Build-HDR-COLOR.cmd'
    command_text = template.read_text()
    if str(source) not in command_text:
        raise RuntimeError('Build template does not reference the attested source directory')
    inputs = {name:digest(source/name) for name in (*checks, 'quality_shaders.h')}
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns('*.obj','*.pdb','*.ilk','*.exp','*.log'))
    (dest/'dlss5-feed-host64.cpp').write_text(patched,encoding='utf-8-sig')
    command = root/'Build-FACE-FP16.cmd'
    command.write_text(command_text.replace(str(source),str(dest)),encoding='utf-8')
    with (root/'face-fp16-build.log').open('wb') as log:
        result = subprocess.run(['cmd.exe','/d','/c',str(command)],stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:
        raise RuntimeError('Precision build failed; inspect face-fp16-build.log')
    if digest(dest/'nvngx_dlssnr.dll') != build['runtime_sha256']:
        raise RuntimeError('Precision build changed the neural runtime')
    record = dict(experiment='fp16-nr-work-textures',mapping='color-preserving',queued=False,
        worker_sha256=digest(dest/'nvngx.dll'),runtime_sha256=digest(dest/'nvngx_dlssnr.dll'),
        source_sha256=digest(dest/'dlss5-feed-host64.cpp'),
        parent_build_sha256=digest(root/'hdr-color-build.json'), inputs=inputs,
        patched={'dlss5-feed-host64.cpp':digest(dest/'dlss5-feed-host64.cpp')},
        staging_sha256=digest(Path(__file__)))
    record_path.write_text(json.dumps(record,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
