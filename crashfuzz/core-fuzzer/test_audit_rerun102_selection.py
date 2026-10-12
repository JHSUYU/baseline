import json
import tempfile
import unittest
from pathlib import Path

from audit_rerun102_selection import audit


class SelectionAuditTest(unittest.TestCase):
    def test_runtime_digest_must_match_soot_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checklist = root / 'checklist.json'
            site = '<example.Target: void check()>#u2'
            checklist.write_text(json.dumps({'rows': [{
                'case_id': 'CHECK-01', 'selection_group': 'original_102',
                'exact_check_location': {'site_id': site}}]}))
            base = root / 'results/CHECK-01'
            healthy = base / 'healthy'
            healthy.mkdir(parents=True)
            (base / 'case-summary.json').write_text(json.dumps({
                'case_id': 'CHECK-01', 'status': 'budget_or_queue_complete',
                'static_io_calls': 1, 'static_coverage_methods': 1}))
            (base / 'soot-selection.json').write_text(json.dumps({
                'analysis_kind': 'crashfuzz_coarse_soot_selection',
                'schema_version': 1, 'target_method': site.split('#u')[0],
                'target_site_id': site, 'input_digest': 'expected',
                'coverage_methods': [site.split('#u')[0]],
                'io_methods': [site.split('#u')[0]],
                'io_calls': [{'method': site.split('#u')[0], 'site_id': site}]}))
            trace = healthy / 'runtime_trace.jsonl'
            trace.write_text('\n'.join(json.dumps(row) for row in (
                {'event': 'STATIC_SELECTION_APPLIED', 'digest': 'expected'},
                {'event': 'METHOD_ENTER', 'method': site.split('#u')[0]})) + '\n')
            (healthy / 'manifest.json').write_text(json.dumps({
                'returncode': 0, 'trace': str(trace)}))
            (base / 'campaign-config.json').write_text(json.dumps({
                'static_selection': {'artifact': str(base / 'soot-selection.json')},
                'target': {'method': site.split('#u')[0]}}))
            checkpoint = base / 'campaign/CHECK-01/state.json'
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(json.dumps({'static_selection_digest': 'expected'}))
            self.assertEqual(audit(root / 'results', checklist)['errors'], [])
            trace.write_text(json.dumps({'event': 'STATIC_SELECTION_APPLIED',
                                         'digest': 'expected'}) + '\n')
            self.assertIn('healthy JUnit executed no Soot-selected work',
                          audit(root / 'results', checklist)['errors'][0]['error'])
            trace.write_text('\n'.join(json.dumps(row) for row in (
                {'event': 'STATIC_SELECTION_APPLIED', 'digest': 'expected'},
                {'event': 'FAULT_POINT_OBSERVED', 'siteId':
                 '<example.Other: void run()>#u1'})) + '\n')
            self.assertIn('runtime I/O escaped Soot callsite selection',
                          audit(root / 'results', checklist)['errors'][0]['error'])
            trace.write_text(json.dumps({'event': 'STATIC_SELECTION_APPLIED',
                                         'digest': 'wrong'}) + '\n')
            self.assertIn('runtime selection digest differs',
                          audit(root / 'results', checklist)['errors'][0]['error'])
            selected = json.loads((base / 'soot-selection.json').read_text())
            selected['coverage_methods'].extend(
                f'<example.Extra{i}: void run()>' for i in range(400))
            (base / 'soot-selection.json').write_text(json.dumps(selected))
            self.assertIn('exceeds its method budget',
                          audit(root / 'results', checklist)['errors'][0]['error'])


if __name__ == '__main__':
    unittest.main()
