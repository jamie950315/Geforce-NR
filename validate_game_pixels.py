"""Same-source/history composition test with captured game frames, not live FPS."""
import json
import os
from pathlib import Path
import sys
import time
import traceback
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
LIVE = ROOT.parent/'gfn-hud-live-20260921-7b03'
sys.path.insert(0,str(LIVE))
from live_hud import verify, LAB, GUARD, NATIVE, digest, load
sys.path.insert(0,str(GUARD))
from hud_masks import decode, compose
from gfn_core import wire
from gfn_core.config import Appearance, atomic_json
from gfn_core.transport import Transport


def main():
    integrity=verify()
    if (ROOT/'active.json').exists():
        raise RuntimeError('Live run must finish first')
    out=ROOT/('pixel-validation-'+time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(exist_ok=False)
    atomic_json(ROOT/'pixel-latest.json',dict(path=str(out)))
    sources=sorted((ROOT/'raw-game-samples').glob('frame-*.png'))
    if len(sources)!=12:
        raise ValueError('Expected twelve observed game frames')
    maskpath=ROOT/'cyberpunk-1440p.hgm'
    mask=decode(maskpath.read_bytes())
    full=(2560,1440); work=(1600,900)
    appearance=Appearance.from_dict(load(LAB/'appearance.json'))
    rows=[]
    baseline=[]
    for mode in ('nr','guard'):
        env={k:v for k,v in os.environ.items() if not k.startswith(('NS_','GFN_CORE_','GFN_HUD_'))}
        env.update(GFN_CORE_ABI='1',GFN_CORE_SUMMARY_ONLY='0',GFN_HUD_PROFILE='1',NS_PHASE='1',
                   NS_NR_SMALL='1',NS_NR_RESIDUAL='1',NS_MOTION_BACKEND='cpu',NS_FRAME_GENERATION='0',
                   NS_SPOUT='0',NS_HDR='0',NS_GPU='0',NS_PW='0')
        if mode=='guard':env['GFN_HUD_MASK']=str(maskpath)
        with (out/(mode+'.log')).open('w',encoding='utf-8',buffering=1) as log:
            transport=Transport([str(NATIVE/'nvngx.dll'),'--live'],NATIVE,env,log)
            try:
                transport.send_header(wire.header(work,full,appearance))
                for i,source in enumerate(sources):
                    rgba=np.asarray(Image.open(source).convert('RGBA'))
                    packet=wire.COMMAND.pack(wire.FRAME,i,int(i==0),wire.FG_EXPLICIT_OFF|2,i)+rgba.tobytes()+bytes(work[0]*work[1]*4)
                    reply=transport.request(packet,wire.OUTPUT,index=i,timeout=20)
                    if reply.pts!=i or len(reply.pixels)!=full[0]*full[1]*4:
                        raise RuntimeError('Unmatched frame identity or size')
                    result=np.frombuffer(reply.pixels,np.uint8).reshape(full[1],full[0],4).copy()
                    if mode=='nr':baseline.append(result)
                    else:
                        expected=compose(rgba,baseline[i],mask)
                        row=dict(frame=i,protected_max=int(np.abs(result[mask==255].astype(np.int16)-rgba[mask==255].astype(np.int16)).max()),
                                 outside_changed=int(np.count_nonzero(result[mask==0]!=baseline[i][mask==0])),
                                 reference_max=int(np.abs(result.astype(np.int16)-expected.astype(np.int16)).max()),
                                 unprotected_nr_hud_mae=float(np.abs(baseline[i][mask==255,:3].astype(np.int16)-rgba[mask==255,:3].astype(np.int16)).mean()))
                        rows.append(row)
                    if i in (0,5,11):Image.fromarray(result[:,:,:3]).save(out/f'{mode}-{i:03d}.png')
                if not transport.nr.is_set():raise RuntimeError('NR not confirmed')
            finally:
                transport.close()
            if transport.process.returncode!=0:raise RuntimeError('Worker shutdown failed')
    passed=all(r['protected_max']==0 and r['outside_changed']==0 and r['reference_max']<=1 for r in rows)
    atomic_json(out/'result.json',dict(passed=passed,rows=rows,integrity=integrity,mask_sha256=digest(maskpath),
                sources={p.name:digest(p) for p in sources},
                scope='Paired file-fed actual-game captures with identical zero-motion history. Validates HUD composition, not live NVOFA history or live same-frame capture.'))
    return 0 if passed else 1


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception:
        (ROOT/'pixel-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
