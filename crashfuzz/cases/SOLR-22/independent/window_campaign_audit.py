#!/usr/bin/env python3
"""Compare live window counters with thread-aware raw-trace recounts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from window_recount import recount


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    state = json.loads((args.campaign / 'state.json').read_text())
    rows = []
    for trial in state['completed']:
        trace = Path(trial['trace'])
        corrected = recount(trace)
        row = {
            'trial_number': trial['trial_number'],
            'trace': str(trace),
            'trace_sha256': hashlib.sha256(trace.read_bytes()).hexdigest(),
            'strict_injection': trial['strict_injection'],
            'raw_directory_io_in_window': trial['directory_io_during_onCommit_window'],
            'corrected_directory_io_in_window': corrected['directory_io_in_complete_windows'],
            'raw_applied_faults_in_window': trial['applied_faults_during_onCommit_window'],
            'corrected_applied_faults_in_window': corrected['applied_faults_in_window'],
            'raw_target_checks_in_window': trial['target_checks_during_onCommit_window'],
            'corrected_target_checks_in_window': corrected['target_checks_in_complete_windows'],
            'complete_windows': corrected['complete_windows'],
            'incomplete_windows': corrected['incomplete_windows'],
            'incomplete_window_applied_faults': corrected['incomplete_window_applied_faults'],
        }
        if (row['corrected_directory_io_in_window'] > row['raw_directory_io_in_window']
            or row['corrected_applied_faults_in_window'] > row['raw_applied_faults_in_window']
            or row['corrected_target_checks_in_window'] > row['raw_target_checks_in_window']):
            raise AssertionError('corrected window count exceeds permissive raw count: '
                                 + str(row['trial_number']))
        rows.append(row)
    fields = ('directory_io_in_window', 'applied_faults_in_window',
              'target_checks_in_window')
    report = {
        'case_id': 'SOLR-22',
        'schema_version': 1,
        'method': 'Directory on writer thread; target checks on same policy and logical core across threads; '
                  'incomplete windows count applied faults only',
        'trials_recounted': len(rows),
        'source_state_sha256': hashlib.sha256((args.campaign / 'state.json').read_bytes()).hexdigest(),
        'totals': {name: {
            'raw': sum(row['raw_' + name] for row in rows),
            'corrected': sum(row['corrected_' + name] for row in rows),
        } for name in fields},
        'rows': rows,
    }
    result = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
