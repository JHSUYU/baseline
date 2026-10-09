#!/usr/bin/env python3
"""Safety gates for the persistent selected-cap handoff watcher."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import handoff_child_balance as handoff


class HandoffTest(unittest.TestCase):
    def checkpoint(self) -> dict:
        return {'status': 'budget_complete',
                'budget': {'max_trials': 80, 'max_faults': 8},
                'completed': [{} for _ in range(80)], 'active': None}

    def test_migrates_only_after_child_exit_and_parent_stop(self) -> None:
        state = self.checkpoint()
        with (patch.object(handoff, 'parent_is_stopped', return_value=True),
              patch.object(handoff, 'child_active', return_value=True)):
            self.assertEqual(handoff.checkpoint_state(state, 2, 1), 'wait')
        with (patch.object(handoff, 'parent_is_stopped', return_value=True),
              patch.object(handoff, 'child_active', return_value=False)):
            self.assertEqual(handoff.checkpoint_state(state, 2, 1), 'migrate')
        with patch.object(handoff, 'parent_is_stopped', return_value=False):
            self.assertEqual(handoff.checkpoint_state(state, 2, 1),
                             'failed_parent_not_stopped')

    def test_candidate_and_bad_checkpoint_never_resume_parent(self) -> None:
        state = self.checkpoint()
        with patch.object(handoff, 'parent_is_stopped', return_value=True):
            state['status'] = 'candidate_target_exception'
            self.assertEqual(handoff.checkpoint_state(state, 2, 1),
                             'candidate_requires_review')
            state['status'] = 'budget_complete'
            state['active'] = {'id': 'inflight'}
            self.assertEqual(handoff.checkpoint_state(state, 2, 1),
                             'failed_unexpected_budget_checkpoint')
            state['active'] = None
            state['completed'].pop()
            self.assertEqual(handoff.checkpoint_state(state, 2, 1),
                             'failed_unexpected_budget_checkpoint')


if __name__ == '__main__':
    unittest.main()
