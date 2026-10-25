import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crashfuzz import report  # noqa: E402
from crashfuzz.report import (apply_candidate_review, apply_target_exception_review,  # noqa: E402
                              enrich_live_summary, enrich_live_trials, enrich_result_metrics,
                              infer_healthy_target_reach, reconcile_elapsed)


class ReportTest(unittest.TestCase):
    def test_exact_target_throw_does_not_imply_new_bug(self):
        row = {'case_id': 'CHECK-01', 'bug_mark': 'none', 'target_exception_candidates': 0}
        apply_target_exception_review(row, {'CHECK-01': {
            'fault_trial_numbers': [3], 'evidence_kind': 'EXPLICIT_THROW',
            'healthy_expected': 'yes', 'first_trigger_elapsed_seconds': 24.5,
            'evidence': 'trace'}})
        self.assertTrue(row['target_exception_triggered'])
        self.assertEqual(row['target_exception_trigger_trials'], [3])
        self.assertEqual(row['bug_mark'], 'none')
        self.assertEqual(row['target_exception_candidates'], 0)

    def test_missing_healthy_reach_is_recovered_from_exact_check_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            trace = base / 'healthy/runtime_trace.jsonl'
            trace.parent.mkdir()
            trace.write_text('\n'.join([
                json.dumps({'event': 'CHECK_REACHED', 'siteId': 'other'}),
                json.dumps({'event': 'CHECK_REACHED', 'siteId': 'target'})]) + '\n')
            row = {'target_site_id': 'target'}
            infer_healthy_target_reach(row, base)
            self.assertTrue(row['healthy_target_reached'])
            row['healthy_target_reached'] = False
            infer_healthy_target_reach(row, base)
            self.assertFalse(row['healthy_target_reached'])

    def test_review_rejects_only_the_examined_candidates(self):
        reviews = {'CHECK-01': {'reviewed_candidate_count': 2,
                                'verdict': 'rejected_expected_failure',
                                'reason': 'documented shutdown', 'evidence': 'trial evidence'}}
        row = {'case_id': 'CHECK-01', 'bug_mark': 'candidate', 'target_exception_candidates': 2}
        apply_candidate_review(row, reviews)
        self.assertEqual(row['bug_mark'], 'rejected')
        self.assertEqual(row['review_verdict'], 'rejected_expected_failure')
        row['target_exception_candidates'] = 3
        row['bug_mark'] = 'candidate'
        apply_candidate_review(row, reviews)
        self.assertEqual(row['bug_mark'], 'candidate')
        self.assertEqual(row['review_verdict'], 'pending_source_review')

    def test_completed_statuses_match_campaign_result_counts(self):
        summary = {'bug_mark': 'none'}
        enrich_live_trials(summary, {'completed': [
            {'status': 'unmatched'}, {'status': 'lost_target'}, {'status': 'checked'},
            {'status': 'target_exception_candidate'}]})
        self.assertEqual(summary['fault_trials'], 4)
        self.assertEqual(summary['strict_injections'], 3)
        self.assertEqual(summary['post_fault_target_reach_trials'], 2)
        self.assertEqual(summary['target_exception_candidates'], 1)
        self.assertEqual(summary['bug_mark'], 'candidate')

    def test_elapsed_never_undercounts_resumed_trials(self):
        summary = {'total_elapsed_seconds': 824.426, 'active_runtime_seconds': 4969.506}
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
                'static_selection_digest': 'expanded', 'completed': [{'status': 'checked'}],
                'active': {'number': 2}, 'active_runtime_seconds': 12.5}))
            summary = {'case_id': 'CHECK-01', 'status': 'fuzzing', 'finished': False,
                       'selection_profile': 'caller_expanded'}
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
            'target_outcome_changed_trials': 1, 'coverage_gain_methods': 5,
            'coverage_gain_branches': 2})

    def test_table_merges_summaries_campaign_results_and_reviews(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            location = {'file': 'src/T.java', 'enclosing_function': 'T.check',
                        'selected_line': 12, 'site_id': '<T: void check()>#u3'}
            checklist = root / 'checklist.json'
            checklist.write_text(json.dumps({'rows': [
                {'case_id': 'X-01', 'system': 'Solr 8.11.4', 'selection_group': 'original_102',
                 'exact_check_location': location, 'cluster_test': 'T#test'},
                {'case_id': 'X-02', 'system': 'Solr 8.11.4', 'selection_group': 'original_102',
                 'exact_check_location': location, 'cluster_test': 'T#test'},
                {'case_id': 'X-03', 'system': 'Solr 8.11.4',
                 'selection_group': 'added_known_issue_check',
                 'exact_check_location': location}]}))
            results = root / 'results'
            record = results / 'X-01/campaign/X-01/result.json'
            record.parent.mkdir(parents=True)
            record.write_text(json.dumps({'target_reached': True, 'lost_target_trials': 2,
                                          'total_elapsed_seconds': 50.0}))
            (results / 'X-01/case-summary.json').write_text(json.dumps({
                'case_id': 'X-01', 'status': 'candidate_review', 'finished': True,
                'target_exception_candidates': 1, 'bug_mark': 'candidate',
                'campaign_result': str(record), 'total_elapsed_seconds': 40.0}))
            reviews = root / 'reviews.json'
            reviews.write_text(json.dumps({'cases': {'X-01': {
                'reviewed_candidate_count': 1, 'verdict': 'rejected_expected',
                'reason': 'r', 'evidence': 'e'}}}))
            with patch.object(report, 'CANDIDATE_REVIEWS', reviews):
                rows = report.table(results, checklist)
            self.assertEqual([row['case_id'] for row in rows], ['X-01', 'X-02'])
            self.assertEqual(rows[0]['bug_mark'], 'rejected')
            self.assertEqual(rows[0]['lost_target_trials'], 2)
            self.assertEqual(rows[0]['total_elapsed_seconds'], 50.0)
            self.assertEqual(rows[1]['status'], 'pending')
            output = root / 'table.tsv'
            report.write_tsv(rows, output)
            lines = output.read_text().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0].split('\t'), list(report.COLUMNS))


if __name__ == '__main__':
    unittest.main()
