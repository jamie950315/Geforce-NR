"""Correlate tunnel header arrivals with PresentMon stalls, not media payloads."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path)
    ap.add_argument('--component', required=True, type=int)
    ap.add_argument('--utc-offset-hours', required=True, type=int)
    args = ap.parse_args()
    clock = json.loads((args.run / 'clock.json').read_text(encoding='utf-8-sig'))
    local = datetime.fromisoformat(clock['utc']) + timedelta(hours=args.utc_offset_hours)
    anchor = local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6
    qpc_anchor = clock['qpc'] / clock['qpc_frequency']
    packets = []
    with (args.run / 'headers.txt').open(encoding='utf-16') as stream:
        header = next(stream)
        if 'EventsLost: 0,' not in header or 'BuffersLost: 0,' not in header:
            raise ValueError('Packet trace has missing or unknown event coverage')
        for line in stream:
            if '方向 Rx ' not in line or f'元件 {args.component}，' not in line:
                continue
            detail = next(stream)
            if f"{clock['peer']}.{clock['port']} > " not in detail:
                continue
            h, m, s = line.split()[0].split(':')
            seconds = int(h) * 3600 + int(m) * 60 + float(s)
            relative = (seconds - anchor + 43200) % 86400 - 43200
            size = int(re.search(r'OriginalSize (\d+)', line)[1])
            packets.append((qpc_anchor + relative, size))
    packets.sort()
    if len(packets) < 2:
        raise ValueError('No usable RX header sequence from the selected component')
    presents = json.loads((args.run / 'present-summary.json').read_text())
    if not presents['coverage_contiguous']:
        raise ValueError('Present trace coverage is incomplete')
    events = []
    for event in presents['events']:
        end = event['qpc_seconds']
        start = end - event['present_gap_ms'] / 1000
        inside = [(t, n) for t, n in packets if start <= t <= end]
        boundaries = [start] + [t for t, _ in inside] + [end]
        events.append(dict(present_gap_ms=event['present_gap_ms'], qpc_seconds=end,
            tunnel_rx_packets=len(inside), tunnel_rx_bytes=sum(n for _, n in inside),
            maximum_rx_silence_inside_ms=max(b-a for a, b in zip(boundaries, boundaries[1:])) * 1000))
    result = dict(component=args.component, packets=len(packets), events=events,
        scope='Approximate wall-clock/QPC alignment of encrypted exit-node UDP headers. '
              'Tunnel traffic is not uniquely GFN; arrivals do not prove zero media loss '
              'or decoder health. No application payload is interpreted.')
    (args.run / 'transport-summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
