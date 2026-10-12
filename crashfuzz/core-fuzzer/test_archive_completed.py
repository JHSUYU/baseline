import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_completed import archive_case, eligible


class ArchiveCompletedTest(unittest.TestCase):
    def summary(self, result):
        return {'finished': True, 'status': 'budget_or_queue_complete',
                'fault_trials': 80, 'target_exception_candidates': 0,
                'bug_mark': 'none', 'campaign_result': str(result)}

    def fixture(self, root):
        base = root / 'HDFS-01'
        result = base / 'campaign' / 'HDFS-01' / 'result.json'
        result.parent.mkdir(parents=True)
        result.write_text('{"fault_trials":80}\n')
        summary = self.summary(result)
        (base / 'case-summary.json').write_text(json.dumps(summary))
        return base, result, summary

    def test_only_completed_noncandidate_budgeted_cases_are_eligible(self):
        row = self.summary('/tmp/result.json')
        self.assertTrue(eligible(row, 80))
        for change in ({'finished': False}, {'fault_trials': 79},
                       {'target_exception_candidates': 1},
                       {'status': 'no_valid_target_trial'},
                       {'archive_path': '/remote/HDFS-01'}):
            self.assertFalse(eligible({**row, **change}, 80))

    def test_checksum_difference_preserves_original_campaign(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, result, summary = self.fixture(Path(temporary))
            calls = [subprocess.CompletedProcess([], 0, '', ''),
                     subprocess.CompletedProcess([], 0, '', ''),
                     subprocess.CompletedProcess([], 0, '>f+++++++++ result.json\n', '')]
            with patch('archive_completed.subprocess.run', side_effect=calls):
                with self.assertRaisesRegex(RuntimeError, 'checksum verification'):
                    archive_case(base, summary, 'node1', Path('/remote'), Path('/key'))
            self.assertTrue(result.is_file())
            self.assertFalse((base / 'archive.json').exists())
            self.assertEqual(json.loads((base / 'case-summary.json').read_text())
                             ['campaign_result'], str(result))

    def test_verified_archive_keeps_local_summary_and_final_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, result, summary = self.fixture(Path(temporary))
            success = subprocess.CompletedProcess([], 0, '', '')
            with patch('archive_completed.subprocess.run', return_value=success):
                archive_case(base, summary, 'node1', Path('/remote'), Path('/key'))
            self.assertFalse(result.exists())
            self.assertTrue((base / 'campaign-result.json').is_file())
            updated = json.loads((base / 'case-summary.json').read_text())
            self.assertEqual(updated['archive_path'], '/remote/HDFS-01')
            self.assertTrue(Path(updated['campaign_result']).is_file())


if __name__ == '__main__':
    unittest.main()
