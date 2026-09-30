"""Summarize PresentMon v1 metrics without treating missing rows as stalls."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path


def summarize(path, pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Select a positive process ID')
    raw = path.read_bytes()
    rows = [row for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
            if int(row['ProcessID']) == pid]
    if len(rows) < 2:
        raise ValueError('Insufficient rows for the explicitly selected process')
    chains = {row['SwapChainAddress'] for row in rows}
    if len(chains) != 1:
        raise ValueError('Multiple swap chains require separate analysis')
    for row in rows:
        for column in ('QPCTime', 'msBetweenPresents', 'msBetweenDisplayChange'):
            value = float(row[column])
            if not math.isfinite(value) or value < 0 or (column == 'QPCTime' and value == 0):
                raise ValueError('Invalid timestamp or interval: ' + column)
    input_times = [float(row['QPCTime']) for row in rows]
    reordered = any(b < a for a, b in zip(input_times, input_times[1:]))
    rows.sort(key=lambda row: float(row['QPCTime']))
    # PresentMon 2.5.1 --v1_metrics writes QPCTime in seconds, including when
    # --qpc_time_ms is selected. Relative deltas are cross-checked below.
    times = [float(row['QPCTime']) for row in rows]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Non-increasing QPC timestamps')
    missing = []
    for a, b, row in zip(times, times[1:], rows[1:]):
        observed = (b - a) * 1000
        recorded = float(row['msBetweenPresents'])
        if abs(observed - recorded) > 0.1:
            missing.append(dict(qpc_seconds=b, row_gap_ms=observed,
                                reported_present_gap_ms=recorded))
    events = []
    for row in rows[1:]:
        gap = float(row['msBetweenPresents'])
        if gap >= 90:
            events.append(dict(qpc_seconds=float(row['QPCTime']),
                elapsed_seconds=float(row['QPCTime']) - times[0],
                present_gap_ms=gap,
                display_change_ms=float(row['msBetweenDisplayChange']),
                dropped=row['Dropped'], present_mode=row['PresentMode']))
    span = times[-1] - times[0]
    return dict(csv=path.name, sha256=hashlib.sha256(raw).hexdigest(),
        process_id=pid, rows=len(rows), span_seconds=span,
        recorded_fps=(len(rows)-1)/span,
        input_rows_reordered=reordered,
        coverage_contiguous=not missing, discontinuities=missing,
        gaps_at_least_90ms=len(events), events=events,
        maximum_reported_present_gap_ms=max(float(row['msBetweenPresents']) for row in rows[1:]),
        scope='PresentMon v1 process presents; missing ETW rows are not counted as stalls. '
              'No claim about decoded-content uniqueness or network root cause.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv', type=Path)
    ap.add_argument('--pid', required=True, type=int)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = json.dumps(summarize(args.csv, args.pid), indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    else:
        print(result)


if __name__ == '__main__':
    main()
