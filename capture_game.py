"""Capture raw gameplay samples only when no local NR overlay is active."""
import ctypes
import json
from pathlib import Path
import time
import win32gui
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
if (ROOT/'active.json').exists():
    raise RuntimeError('Wait for the current NR test to finish')
if 'GeForce NOW' not in win32gui.GetWindowText(win32gui.GetForegroundWindow()):
    raise RuntimeError('GFN must be foreground')
visible = []
win32gui.EnumWindows(lambda h,_: visible.append(win32gui.GetWindowText(h)) if win32gui.IsWindowVisible(h) else None, None)
if 'NeuralScreen' in visible:
    raise RuntimeError('Local overlay must be stopped')
out = ROOT/'raw-game-samples'
out.mkdir(exist_ok=False)
rows=[]
for i in range(12):
    if 'GeForce NOW' not in win32gui.GetWindowText(win32gui.GetForegroundWindow()):
        raise RuntimeError('Foreground changed')
    image=ImageGrab.grab()
    if image.size != (2560,1440):
        raise RuntimeError('Desktop geometry changed')
    path=out/f'frame-{i:03d}.png'
    image.convert('RGB').save(path,compress_level=1)
    rows.append(dict(path=str(path),time=time.time()))
    time.sleep(.1)
(out/'manifest.json').write_text(json.dumps(dict(frames=rows,scope='Desktop captures of visible GFN without local NR; not a live paired WGC capture'),indent=2),encoding='utf-8')
