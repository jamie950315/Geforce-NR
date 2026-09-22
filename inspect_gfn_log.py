"""Extract only endpoint labels and numeric performance fields from GFN logs."""
from pathlib import Path
import re

root=Path.home()/'AppData/Local/NVIDIA Corporation/GeForceNOW'
for filename in ('CxNative_GeForceNOW.log','debug.log'):
    path=root/filename
    text=path.read_text(encoding='utf-8',errors='replace')[-3000000:]
    endpoints=[]
    for line in text.splitlines():
        if re.search(r'server|remote|peer|rtp|rtsp',line,re.I):
            ips=re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',line)
            if ips:
                labels=re.findall(r'\b\w*(?:server|remote|peer|rtp|rtsp)\w*\b',line,re.I)
                pair=(tuple(labels[:5]),tuple(ips))
                if pair not in endpoints:endpoints.append(pair)
    print(filename,'endpoints',endpoints[-15:])
    metrics=re.findall(r'\b(?:rtt|latency|packetLoss|frameLoss|frameDrop|fps|decodeTime|presentTime)\b[\s"=:]+[\d.]+',text,re.I)
    print('numeric_metrics',metrics[-20:])
