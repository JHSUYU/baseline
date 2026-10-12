import unittest

from collect_rerun102 import enrich_live_trials, reconcile_elapsed


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


if __name__ == '__main__':
    unittest.main()
