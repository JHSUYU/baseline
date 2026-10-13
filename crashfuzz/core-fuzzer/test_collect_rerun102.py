import json
import tempfile
import unittest
from pathlib import Path

from collect_rerun102 import (accepts_remote_case, apply_campaign_migration,
                              apply_candidate_review,
                              enrich_live_summary, enrich_live_trials,
                              enrich_result_metrics, reconcile_elapsed)


class LiveTrialSummaryTest(unittest.TestCase):
    def test_review_rejects_only_the_examined_candidates(self):
        reviews = {'CHECK-01': {'reviewed_candidate_count': 2,
                                'verdict': 'rejected_expected_failure',
                                'reason': 'documented shutdown',
                                'evidence': 'trial evidence'}}
        row = {'case_id': 'CHECK-01', 'bug_mark': 'candidate',
               'target_exception_candidates': 2}
        apply_candidate_review(row, reviews)
        self.assertEqual(row['bug_mark'], 'rejected')
        self.assertEqual(row['review_verdict'], 'rejected_expected_failure')
        row['target_exception_candidates'] = 3
        row['bug_mark'] = 'candidate'
        apply_candidate_review(row, reviews)
        self.assertEqual(row['bug_mark'], 'candidate')
        self.assertEqual(row['review_verdict'], 'pending_source_review')

    def test_cross_host_offload_is_reported_only_while_active(self):
        cases = {'HBASE-35': {'state': 'active', 'execution_host': 'node2'},
                 'HBASE-37': {'state': 'mirrored', 'execution_host': 'node2'}}
        self.assertTrue(accepts_remote_case('node2', 'HBASE-35', cases))
        self.assertFalse(accepts_remote_case('node2', 'HBASE-37', cases))
        self.assertFalse(accepts_remote_case('node2', 'HBASE-14', cases))
        self.assertTrue(accepts_remote_case('node1', 'HBASE-14', cases))

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

    def test_replacement_campaign_counts_only_new_trials_but_all_elapsed(self):
        migration = {'SOLR-36': {'replacement_campaign': 'identity-v3',
                                 'retired_campaigns': [
                                     {'campaign': 'nightly',
                                      'elapsed_seconds': 11693.061,
                                      'completed_trials': 54,
                                      'strict_injections': 5,
                                      'budget_trials': 80,
                                      'audit_path': 'node2:/nightly-audit.json'},
                                     {'campaign': 'identity-v2',
                                      'elapsed_seconds': 341.378,
                                      'completed_trials': 2,
                                      'strict_injections': 1,
                                      'budget_trials': 80,
                                      'audit_path': 'node2:/v2-audit.json'}]}}
        old = {'case_id': 'SOLR-36', 'healthy_manifest': '/healthy-expanded-nightly/manifest.json',
               'total_elapsed_seconds': 11693.061, 'fault_trials': 54}
        apply_campaign_migration(old, migration)
        self.assertEqual(old['total_elapsed_seconds'], 11693.061)
        self.assertNotIn('prior_campaign_elapsed_seconds', old)
        new = {'case_id': 'SOLR-36',
               'healthy_manifest': '/healthy-expanded-identity-v3/manifest.json',
               'total_elapsed_seconds': 250.0, 'active_runtime_seconds': 251.25,
               'fault_trials': 3, 'strict_injections': 2}
        apply_campaign_migration(new, migration)
        self.assertEqual(new['total_elapsed_seconds'], 12285.689)
        self.assertEqual(new['current_campaign_elapsed_seconds'], 251.25)
        self.assertEqual(new['prior_campaign_fault_trials'], 56)
        self.assertEqual(new['prior_campaign_strict_injections'], 6)
        self.assertEqual(new['current_campaign_fault_trials'], 3)
        self.assertEqual(new['fault_trials'], 3)
        self.assertEqual(new['strict_injections'], 2)

    def test_terminal_replacement_elapsed_is_not_counted_twice(self):
        migration = {'HBASE-13': {
            'replacement_campaign': 'identity-v2',
            'retired_campaigns': [{
                'campaign': 'original', 'elapsed_seconds': 6195.297,
                'completed_trials': 63, 'strict_injections': 2,
                'budget_trials': 80, 'audit_path': 'node1:/prior-audit.json'}]}}
        row = {'case_id': 'HBASE-13',
               'campaign_result': '/campaign-identity-v2/HBASE-13/result.json',
               'total_elapsed_seconds': 10531.819,
               'active_runtime_seconds': 4235.102,
               'fault_trials': 80}
        apply_campaign_migration(row, migration)
        self.assertEqual(row['prior_campaign_elapsed_seconds'], 6195.297)
        self.assertEqual(row['current_campaign_elapsed_seconds'], 4336.522)
        self.assertEqual(row['total_elapsed_seconds'], 10531.819)
        self.assertEqual(row['prior_campaign_fault_trials'], 63)
        self.assertEqual(row['current_campaign_fault_trials'], 80)

    def test_terminal_replacement_with_no_inherited_summary_elapsed(self):
        migration = {'SOLR-36': {
            'replacement_campaign': 'identity-v3',
            'retired_campaigns': [{
                'campaign': 'nightly', 'elapsed_seconds': 11693.061,
                'completed_trials': 54, 'strict_injections': 5,
                'budget_trials': 80, 'audit_path': 'node2:/nightly.json'}, {
                'campaign': 'identity-v2', 'elapsed_seconds': 341.378,
                'completed_trials': 2, 'strict_injections': 1,
                'budget_trials': 80, 'audit_path': 'node2:/v2.json'}]}}
        row = {'case_id': 'SOLR-36',
               'campaign_result': '/campaign-identity-v3/SOLR-36/result.json',
               'total_elapsed_seconds': 3710.0,
               'active_runtime_seconds': 3600.0,
               'fault_trials': 80}
        apply_campaign_migration(row, migration)
        self.assertEqual(row['prior_campaign_elapsed_seconds'], 12034.439)
        self.assertEqual(row['current_campaign_elapsed_seconds'], 3710.0)
        self.assertEqual(row['total_elapsed_seconds'], 15744.439)

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
