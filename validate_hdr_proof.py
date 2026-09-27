"""Validate opt-in same-frame FP16 readbacks; never classify them as timing proof."""
import argparse
import hashlib
import json
from pathlib import Path


def validate(run):
    if not __debug__:
        raise RuntimeError('HDR proof validation requires Python assertions; do not use -O')
    import numpy as np
    run = Path(run)
    manifest = json.loads((run/'manifest.json').read_text(encoding='utf-8-sig'))
    assert manifest['hdr'] is True and manifest['hdr_proof'] is True
    proof = run/'hdr-proof'
    meta = json.loads((proof/'proof.json').read_text())
    for key in ('hwnd','pid','capture_format','output_format'):
        assert type(meta[key]) is int and meta[key] > 0, key
    assert hashlib.sha256((run/'manifest.json').read_bytes()).hexdigest() == meta['manifest_sha256']
    assert (meta['hwnd'],meta['pid']) == (manifest['target']['hwnd'],manifest['target']['pid'])
    for key in ('generation','capture','source_qpc'):
        assert type(meta[key]) is int and meta[key] > 0, key
    assert meta['capture_format'] == meta['output_format'] == 10  # RGBA16F
    assert type(meta['fence']) is int and meta['fence'] > 0
    w, h = meta['width'], meta['height']
    assert type(w) is int and type(h) is int and 64 <= w <= 7680 and 64 <= h <= 4320
    assert type(meta['bypass']) is bool and meta['bypass'] == (manifest['mode'] == 'bypass')
    assert type(meta['white']) in (int,float) and np.isfinite(meta['white']) and meta['white'] > 0
    hashes = {}
    def read(name, dtype):
        data = (proof/name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        assert hashes[name] == meta['sha256'][name], 'HDR capture hash mismatch: '+name
        values = np.frombuffer(data, dtype=dtype)
        assert values.size == w*h*4, name
        result = values.reshape(h,w,4).astype(np.float32)
        assert np.isfinite(result).all(), name
        return result
    source, output = read('source.fp16','<f2'), read('output.fp16','<f2')
    a, b = read('proxy-in.rgba','u1')/255, read('proxy-out.rgba','u1')/255
    linear = lambda x: np.where(x <= .04045, x/12.92, ((x+.055)/1.055)**2.4)
    original = source[:,:,:3]
    scale = meta['white'] + np.maximum(0, original.max(axis=2,keepdims=True))
    expected = original if meta['bypass'] else original + scale*np.clip(linear(b[:,:,:3])-linear(a[:,:,:3]),-.25,.25)
    expected = np.clip(expected,-65504,65504)
    tolerance = np.maximum(.002, np.abs(expected)*.0015)
    error = np.abs(output[:,:,:3]-expected)
    assert np.all(error <= tolerance), f'HDR composition mismatch: max error {error.max()}'
    assert np.all(output[:,:,3] == 1)
    result = dict(valid=True, timing_evidence=False, width=w,height=h, source_max=float(original.max()),
        output_max=float(output[:,:,:3].max()), max_error=float(error.max()), hashes=hashes,
        source_above_sdr_white=int(np.any(original > meta['white'],axis=2).sum()))
    if meta['bypass']:
        assert np.array_equal(original,output[:,:,:3]), 'HDR bypass did not preserve source exactly'
        result['bypass_exact'] = True
    if manifest.get('mask'):
        data = Path(manifest['mask']['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == manifest['mask']['sha256']
        import struct
        assert struct.unpack('<4I',data[:16]) == (0x314d4748,1,w,h)
        mask = np.frombuffer(data[16:],dtype='u1').reshape(h,w)
        core = mask == 255
        assert core.any()
        assert np.array_equal(original[core],output[:,:,:3][core]), 'Masked HDR pixels changed'
        result['masked_core_exact'] = True
        result['masked_hdr_pixels'] = int(np.any(original[core] > meta['white'],axis=1).sum())
    return result


if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('run',type=Path)
    args=ap.parse_args()
    result=validate(args.run)
    print(json.dumps(result,indent=2))
