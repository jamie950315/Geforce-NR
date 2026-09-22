"""Record bounded device/profile facts without copying account credentials."""
import ctypes
import json
import os
from pathlib import Path
import sys
import win32api
import win32con

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'gfn-hud-live-20260921-7b03'))
from live_hud import verify, digest, LAB, STABLE

qpf=ctypes.c_longlong()
ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(qpf))
session=ctypes.c_ulong()
ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session))
mode=win32api.EnumDisplaySettings(None,win32con.ENUM_CURRENT_SETTINGS)
p=Path.home()/'AppData/Local/NVIDIA Corporation/GeForceNOW/sharedstorage.json'
data=json.loads(p.read_text(encoding='utf-8-sig'))
profile=data.get('appSettingsConfig',{}).get('customProfile',{})
doc=dict(integrity=verify(),qpc_frequency=qpf.value,windows_session=session.value,
         display=dict(width=mode.PelsWidth,height=mode.PelsHeight,hz=mode.DisplayFrequency),
         gfn_profile={k:profile.get(k) for k in ('width','height','fps','maxBitrate','maxBitrateAuto')},
         original_workers={str(r):digest(r/'engine/native/nvngx.dll') for r in (LAB,STABLE)},
         core_lab_have_git={str(r):(r/'.git').exists() for r in (LAB,STABLE)})
(ROOT/'environment.json').write_text(json.dumps(doc,indent=2),encoding='utf-8')
print(json.dumps(doc,indent=2))
