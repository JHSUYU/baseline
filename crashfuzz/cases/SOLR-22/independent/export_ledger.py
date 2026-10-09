#!/usr/bin/env python3
"""Export a compact per-trial ledger from the resumable SOLR-22 checkpoint."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from build import HERE


FIELDS = (
    'trial_number', 'attempts', 'planned_faults', 'applied_faults',
    'strict_injection', 'target_check_after_last_fault',
    'target_check_same_faulted_core_after_last_fault',
    'exact_target_exception_after_last_fault', 'target_exception_count',
    'junit_exit', 'elapsed_seconds', 'new_production_probes',
    'new_io_families', 'status', 'first_family', 'last_family',
    'fault_sequence',
)


def main() -> None:
    state = json.loads((HERE / 'campaign/state.json').read_text())
    output = HERE / 'trial-ledger.csv'
    temporary = output.with_suffix('.csv.tmp')
    with temporary.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for trial in state['completed']:
            row = {field: trial.get(field) for field in FIELDS}
            row['fault_sequence'] = json.dumps(trial['fault_sequence'],
                                               sort_keys=True, separators=(',', ':'))
            writer.writerow(row)
    temporary.replace(output)
    print(output, len(state['completed']))


if __name__ == '__main__':
    main()
