import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from evaluate_run import evaluate, main


def sample(invalid=False, stall=False):
    lines=[]
    for i in range(4800):
        t=i*1000/120+(100 if stall and i>=2400 else 0)
        age=-1 if invalid else 5
        lines.append(f'[phase] frame index={i} generation=1 capture={i+1} kind=wgc fresh=1 result=enhanced present-call={t:.6f} source-qpc={i+1} source-age={age}')
    return '\n'.join(lines)


class TimingTests(unittest.TestCase):
    def test_live_pair_readback_cannot_qualify_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'manifest.json').write_text(
                json.dumps({'live_pair': {'performance_evidence': False}}))
            with patch('sys.argv', ['evaluate_run.py', directory]):
                with self.assertRaisesRegex(ValueError, 'not timing qualification'):
                    main()

    def check(self, **kwargs):
        return evaluate(sample(**kwargs),dict(exit_code=0,state='duration_complete'),'nr',40)

    def test_regular_120_passes(self):
        self.assertTrue(self.check()['passed'])

    def test_invalid_ages_fail_even_when_throughput_passes(self):
        result=self.check(invalid=True)
        self.assertFalse(result['passed'])
        self.assertTrue(result['checks']['throughput'])
        self.assertFalse(result['checks']['valid_source_ages'])

    def test_stall_fails(self):
        result=self.check(stall=True)
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['interval_max'])

    def test_explicit_future_is_retained_not_clamped_for_bypass(self):
        text=sample().replace('result=enhanced','result=bypass').replace('source-age=5','source-age=-3 source-delta=-3 source-state=future-at-present')
        result=evaluate(text,dict(exit_code=0,state='duration_complete'),'bypass',40)
        self.assertTrue(result['passed'])
        self.assertFalse(result['source_latency_gate_applicable'])
        self.assertEqual(result['signed_source_to_present_ms']['minimum'],-3)
        self.assertIsNone(result['source_age_ms']['p95'])

    def test_future_does_not_qualify_nr_latency(self):
        text=sample().replace('source-age=5','source-age=-3 source-delta=-3 source-state=future-at-present')
        result=evaluate(text,dict(exit_code=0,state='duration_complete'),'nr',40)
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['valid_source_ages'])


if __name__=='__main__':unittest.main()
