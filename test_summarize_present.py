import csv
import hashlib
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from summarize_present import summarize


class PresentSummaryTests(unittest.TestCase):
    def run_rows(self, times_and_gaps):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.csv'
            fields = ['ProcessID', 'SwapChainAddress', 'QPCTime',
                      'msBetweenPresents', 'msBetweenDisplayChange', 'Dropped', 'PresentMode']
            with path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for time, gap in times_and_gaps:
                    writer.writerow(dict(ProcessID=7, SwapChainAddress='0x1', QPCTime=time,
                        msBetweenPresents=gap, msBetweenDisplayChange=gap,
                        Dropped=0, PresentMode='Hardware Composed: Independent Flip'))
            return summarize(path, 7)

    def test_real_present_gap(self):
        result = self.run_rows([(10, 8), (10.008, 8), (10.108, 100)])
        self.assertTrue(result['coverage_contiguous'])
        self.assertEqual(result['gaps_at_least_90ms'], 1)

    def test_missing_rows_are_not_stalls(self):
        result = self.run_rows([(10, 8), (12, 8)])
        self.assertFalse(result['coverage_contiguous'])
        self.assertEqual(result['gaps_at_least_90ms'], 0)

    def test_completed_rows_can_arrive_out_of_order(self):
        result = self.run_rows([(10, 8), (10.108, 100), (10.008, 8)])
        self.assertTrue(result['input_rows_reordered'])
        self.assertTrue(result['coverage_contiguous'])
        self.assertEqual(result['gaps_at_least_90ms'], 1)

    def test_nonfinite_and_negative_times_do_not_establish_coverage(self):
        for bad in ('nan', 'inf', '-inf', -1):
            with self.subTest(qpc=bad):
                with self.assertRaisesRegex(ValueError, 'Invalid timestamp'):
                    self.run_rows([(10, 8), (bad, 8)])
            with self.subTest(interval=bad):
                with self.assertRaisesRegex(ValueError, 'Invalid timestamp'):
                    self.run_rows([(10, 8), (10.008, bad)])

    def test_hash_identifies_the_analyzed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.csv'
            raw=(b'ProcessID,SwapChainAddress,QPCTime,msBetweenPresents,msBetweenDisplayChange,Dropped,PresentMode\n'
                 b'7,0x1,10,8,8,0,Flip\n7,0x1,10.008,8,8,0,Flip\n')
            path.write_bytes(raw)
            def replaced(_):
                path.write_bytes(b'changed after read')
                return raw
            with patch.object(Path, 'read_bytes', replaced):
                result=summarize(path,7)
            self.assertEqual(result['rows'],2)
            self.assertEqual(result['sha256'],hashlib.sha256(raw).hexdigest())


if __name__ == '__main__':
    unittest.main()
