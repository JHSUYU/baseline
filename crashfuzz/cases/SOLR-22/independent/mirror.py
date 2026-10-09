#!/usr/bin/env python3
"""Mirror node2 independent campaign progress into the 102-check ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
CHECKLIST = CASE.parent.parent / 'checklist.py'
RESULT = CASE / 'result.json'
REMOTE_PROGRESS = str(HERE / 'campaign/progress.json')
SSH = ['ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'ZhenyuLi@node2']


def remote_progress() -> dict | None:
    result = subprocess.run(SSH + ['cat', REMOTE_PROGRESS], capture_output=True,
                            text=True, timeout=10, check=False)
    if result.returncode:
        return None
    return json.loads(result.stdout)


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def publish(progress: dict) -> None:
    atomic(HERE / 'live-progress.json', progress)
    result = json.loads(RESULT.read_text())
    if result.get('case_id') != 'SOLR-22':
        raise RuntimeError('wrong checklist row')
    completed = progress['fault_trials']
    last = progress['latest'] or {}
    seed_seconds = result.get('independent_seed_seconds', 0)
    status = progress['status']
    if status == 'candidate_target_exception':
        row_status = 'candidate_exception_source_review'
    elif status in ('budget_complete', 'queue_exhausted'):
        row_status = ('target_relevant_io_not_observed'
                      if progress['applied_faults_in_onCommit_window'] == 0
                      else 'budget_complete_pending_source_review')
    else:
        row_status = 'fuzzing'
    result.update({
        'methodology': 'coverage_io_independent_asm_jacoco',
        'status': row_status,
        'quality_complete': False,
        'fault_trials': completed,
        'strict_injections': progress['strict_injections'],
        'post_fault_target_reach_trials': progress['post_fault_target_reach_trials'],
        'target_after_fault': progress['post_fault_target_reach_trials'],
        'target_exception_after_fault_trials': progress['target_exception_after_fault_trials'],
        'coverage_gain': progress['production_probe_gain'],
        'elapsed_seconds': round(progress['elapsed_seconds'] + seed_seconds, 3),
        'evidence': 'crashfuzz/cases/SOLR-22/independent/live-progress.json',
        'bug_mark': 'candidate' if status == 'candidate_target_exception' else 'none',
        'target_reached': True,
        'run_state': 'node2:tmux:solr22_independent_fuzz',
        'independent_campaign': {
            'host': 'node2',
            'original_junit': 'org.apache.solr.cloud.TestPullReplica#testAddDocs',
            'selected_sequences': completed,
            'total_attempts': progress['total_attempts'],
            'strict_injections': progress['strict_injections'],
            'same_faulted_core_post_target_trials': progress['same_faulted_core_post_target_trials'],
            'target_exception_after_fault_trials': progress['target_exception_after_fault_trials'],
            'production_probe_gain': progress['production_probe_gain'],
            'io_family_gain': progress['io_family_gain'],
            'applied_faults_in_onCommit_window': progress['applied_faults_in_onCommit_window'],
            'target_checks_in_onCommit_window': progress['target_checks_in_onCommit_window'],
            'first_fault_families': progress['first_fault_families'],
            'budget': progress['budget'],
            'last_completed': last.get('trial_number'),
            'last_elapsed_seconds': last.get('elapsed_seconds'),
            'status': status,
        },
        'target_relevant_io_overlap': {
            'status': 'observed' if progress['applied_faults_in_onCommit_window']
            else 'target_relevant_io_not_observed',
            'applied_faults_during_latest_to_known_window':
                progress['applied_faults_in_onCommit_window'],
            'target_checks_during_window': progress['target_checks_in_onCommit_window'],
            'scope': 'independent direct Directory hooks and precise onCommit delegate window',
        },
        'updated_at': time.time(),
    })
    atomic(RESULT, result)
    subprocess.run(['python3', str(CHECKLIST), 'render'], cwd=CASE.parent.parent,
                   check=True, stdout=subprocess.DEVNULL)


def main() -> None:
    last = -1
    while True:
        progress = remote_progress()
        if progress is not None and (progress['fault_trials'] != last or
                                     progress['status'] in
                                     ('budget_complete', 'queue_exhausted',
                                      'candidate_target_exception')):
            publish(progress)
            last = progress['fault_trials']
            if progress['status'] in ('budget_complete', 'queue_exhausted',
                                      'candidate_target_exception'):
                return
        time.sleep(12)


if __name__ == '__main__':
    main()
