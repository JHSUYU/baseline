import json
import tempfile
import unittest
from pathlib import Path

from collect_rerun102 import (enrich_live_summary, enrich_live_trials,
                              enrich_result_metrics, reconcile_elapsed)


class LiveTrialSummaryTest(unittest.TestCase):
    def test_completed_statuses_match_campaign_result_counts(self):
        summary = {'bug_mark': 'none'}
        state = {'completed': [
            {'status': 'unmatched'},
            {'status': 'lost_target'},
            {'status': 'checked'},
            {'status': 'target_exception_candidate'},
        ]}
        enrich_live_trials(summary, state)
        self.assertEqual(summary['fault_trials'], 4)
        self.assertEqual(summary['strict_injections'], 3)
        self.assertEqual(summary['post_fault_target_reach_trials'], 2)
        self.assertEqual(summary['target_exception_candidates'], 1)
        self.assertEqual(summary['bug_mark'], 'candidate')

    def test_elapsed_never_undercounts_resumed_trials(self):
        summary = {'total_elapsed_seconds': 824.426,
                   'active_runtime_seconds': 4969.506}
        reconcile_elapsed(summary)
        self.assertEqual(summary['total_elapsed_seconds'], 4969.506)

    def test_live_summary_reads_expanded_selection_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            artifact = base / 'caller-expanded/soot-selection.json'
            artifact.parent.mkdir()
            artifact.write_text(json.dumps({'input_digest': 'expanded'}))
            state_path = base / 'campaign-expanded/CHECK-01/state.json'
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({
                'static_selection_digest': 'expanded',
                'completed': [{'status': 'checked'}],
                'active': {'number': 2},
                'active_runtime_seconds': 12.5}))
            summary = {'case_id': 'CHECK-01', 'status': 'fuzzing',
                       'finished': False, 'selection_profile': 'caller_expanded'}
            enrich_live_summary(base, summary)
            self.assertEqual(summary['fault_trials'], 1)
            self.assertEqual(summary['active_trial'], 2)

    def test_result_metrics_expose_target_and_coverage_feedback(self):
        summary = {}
        enrich_result_metrics(summary, {
            'target_reached': True, 'lost_target_trials': 3,
            'target_outcome_changed_trials': 1,
            'coverage_gain_by_kind': {'methods': 5, 'branch_outcomes': 2}})
        self.assertEqual(summary, {
            'healthy_target_reached': True, 'lost_target_trials': 3,
            'target_outcome_changed_trials': 1,
            'coverage_gain_methods': 5, 'coverage_gain_branches': 2})


if __name__ == '__main__':
    unittest.main()
