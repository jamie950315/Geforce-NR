"""Request stop only for this workspace's currently recorded live controller."""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'gfn-nvofa-lab-20260920'))
from gfn_core.config import atomic_json

pointer=ROOT/'active.json'
if not pointer.exists():
    print('NO_ISOLATED_SESSION')
    raise SystemExit(0)
active=json.loads(pointer.read_text(encoding='utf-8'))
run=Path(active['run']).resolve()
if run.parent!=(ROOT/'runs').resolve():
    raise RuntimeError('Foreign run path')
session=json.loads((run/'active.json').read_text(encoding='utf-8'))
if session['pid']!=active['pid']:
    raise RuntimeError('Controller identity mismatch')
control=Path(session['control']).resolve()
if control.parent!=(run/'logs').resolve():
    raise RuntimeError('Foreign control path')
atomic_json(control,dict(token=session['token'],id=uuid.uuid4().hex,action='stop'))
print('ISOLATED_STOP_REQUESTED')
