"""Fail-closed phase-log timing assessment; no scanout or input-latency claims."""
import json
import math
from pathlib import Path
import re
import sys


def quantile(values, p):
    if not values:
        return None
    values = sorted(values)
    x = (len(values) - 1) * p
    i = int(x)
    return values[i] + (values[min(i + 1, len(values) - 1)] - values[i]) * (x - i)


def evaluate(text, outcome, mode, duration):
    records = []
    for line in text.splitlines():
        if '[phase] frame ' not in line:
            continue
        fields = dict(re.findall(r'([\w-]+)=([^\s]+)', line))
        if fields.get('fresh') == '1' and fields.get('kind') == 'wgc' and fields.get('result') == ('bypass' if mode == 'bypass' else 'enhanced'):
            records.append(fields)
    if not records:
        return dict(passed=False, reason='No matching fresh WGC frame records')
    first = float(records[0]['present-call']) + 4000
    rows = [r for r in records if float(r['present-call']) >= first]
    if len(rows) < 2:
        return dict(passed=False, reason='Insufficient steady frames')
    times = [float(r['present-call']) for r in rows]
    intervals = [b - a for a, b in zip(times, times[1:])]
    ages = [float(r['source-age']) for r in rows]
    states = [r.get('source-state', 'valid' if float(r['source-age']) >= 0 else 'invalid') for r in rows]
    signed_deltas = [float(r.get('source-delta', r['source-age'])) for r,s in zip(rows,states) if s in ('valid','future-at-present')]
    latency_ages = [age for age,state in zip(ages,states) if state == 'valid' and age >= 0]
    captures = [int(r['capture']) for r in rows]
    sources = [int(r['source-qpc']) for r in rows]
    generations = {r['generation'] for r in rows}
    seconds = (times[-1] - times[0]) / 1000
    begin, end = math.ceil(times[0] / 1000), math.floor(times[-1] / 1000)
    buckets = [0] * max(0, end - begin)
    for t in times:
        i = math.floor(t / 1000) - begin
        if 0 <= i < len(buckets):
            buckets[i] += 1
    summary = dict(steady_seconds=seconds, fresh_fps=(len(rows)-1)/seconds,
                   interval_ms=dict(p95=quantile(intervals,.95), p99=quantile(intervals,.99), maximum=max(intervals)),
                   source_age_ms=dict(p95=quantile(latency_ages,.95), p99=quantile(latency_ages,.99)),
                   signed_source_to_present_ms=dict(minimum=min(signed_deltas) if signed_deltas else None,p95=quantile(signed_deltas,.95)),
                   future_source_samples=states.count('future-at-present'),
                   invalid_source_ages=sum(s not in ('valid','future-at-present') for s in states), full_second_min=min(buckets) if buckets else None,
                   full_seconds=len(buckets), fresh_frames=len(rows))
    checks = dict(normal_exit=outcome.get('exit_code') == 0 and outcome.get('state') == 'duration_complete',
        sufficient_duration=seconds >= (590 if duration >= 600 else 30),
        throughput=summary['fresh_fps'] >= 118.8,
        every_second=bool(buckets) and min(buckets) >= 114,
        interval_p95=summary['interval_ms']['p95'] <= 12.5,
        interval_p99=summary['interval_ms']['p99'] <= 16.8,
        interval_max=max(intervals) <= 50,
        valid_source_ages=summary['invalid_source_ages'] == 0 and (mode == 'bypass' or summary['future_source_samples'] == 0),
        source_age_p95=mode == 'bypass' or (summary['source_age_ms']['p95'] is not None and summary['source_age_ms']['p95'] <= 25),
        source_age_p99=mode == 'bypass' or (summary['source_age_ms']['p99'] is not None and summary['source_age_ms']['p99'] <= 35),
        source_increasing=all(a > 0 and b > a for a,b in zip(sources,sources[1:])),
        capture_increasing=all(b > a for a,b in zip(captures,captures[1:])),
        single_generation=len(generations) == 1)
    return dict(passed=all(checks.values()), checks=checks, source_latency_gate_applicable=mode != 'bypass', **summary,
                scope='WGC surfaces and CPU Present calls only. Bypass is a source reference, not source-latency qualification; signed future timestamps remain explicit. NR requires valid nonnegative source age. Visual acceptance is separate.')


def main():
    root = Path(sys.argv[1])
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('live_pair'):
        raise ValueError('Live-pair readback runs are visual diagnostics, not timing qualification')
    outcome = json.loads((root/'outcome.json').read_text(encoding='utf-8'))
    logs = list((root/'logs').glob('*.native.log'))
    if len(logs) != 1:
        raise ValueError('Expected exactly one native log')
    result = evaluate(logs[0].read_text(encoding='utf-8'), outcome, manifest['mode'], manifest['settings']['duration'])
    (root/'timing.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
