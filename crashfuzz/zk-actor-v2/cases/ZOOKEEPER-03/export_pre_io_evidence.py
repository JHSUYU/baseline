#!/usr/bin/env python3
"""Render the terminal pre-I/O ZK03 raw audit as a per-trial time table."""

import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / 'evidence'
AUDIT = EVIDENCE / 'terminal-audit.json'
ARCHIVE = EVIDENCE / 'raw-runs.tar.gz'
TABLE = EVIDENCE / 'pre-io-trials.csv'
SUMMARY = EVIDENCE / 'pre-io-summary.json'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    audit = json.loads(AUDIT.read_text())
    if audit['status'] != 'attempt_cap' or audit['selected_attempts'] != 480 or \
            audit['effective'] != 37 or audit['exact_fault_plans'] != 478 or \
            audit['selected_target_throw_events']:
        raise RuntimeError('terminal pre-I/O audit differs from verified result')
    if sha(ARCHIVE) != 'caf826bc7ba3fde07e6770dbf54cfed9bf1e4e2992d9a882a605ee65eab5d686':
        raise RuntimeError('raw JUnit archive SHA changed')
    fields = ('run_id', 'elapsed_seconds', 'fault_depth', 'exact', 'effective',
              'postfault_target', 'selected_target_throws', 'junit_exit',
              'new_coverage_lines', 'new_io_families', 'invalid_reason',
              'events_sha256', 'coverage_sha256', 'receipt_sha256')
    with TABLE.open('w', newline='') as output:
        writer = csv.DictWriter(output, fields)
        writer.writeheader()
        for row in audit['trials']:
            writer.writerow({**{key: row[key] for key in fields if key in row},
                             'fault_depth': len(row['plan'])})
    summary = {key: audit[key] for key in
               ('status', 'selected_attempts', 'exact_fault_plans', 'effective',
                'effective_budget', 'max_faults', 'healthy_seconds',
                'trial_seconds', 'effective_coverage_gain',
                'effective_io_family_gain', 'selected_target_throw_events',
                'checkpoint_sha256', 'agent_sha256', 'original_source_commit')}
    summary.update({'bug_mark': 'none', 'new_bug': False,
                    'stop_reason': '480_attempt_cap_before_80_effective',
                    'audit_sha256': sha(AUDIT), 'raw_archive_sha256': sha(ARCHIVE),
                    'trial_table_sha256': sha(TABLE),
                    'elapsed_seconds': round(audit['healthy_seconds'] +
                                             audit['trial_seconds'], 3)})
    SUMMARY.write_text(json.dumps(summary, sort_keys=True, indent=2) + '\n')
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
