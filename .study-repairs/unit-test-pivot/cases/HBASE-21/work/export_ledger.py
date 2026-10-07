#!/usr/bin/env python3
"""Export the completed HBASE-21 trial ledger without the pending fuzz queue."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
checkpoint = json.loads((HERE / 'checkpoint.json').read_text())
rows = []
for trial in checkpoint['trials']:
    log = HERE.parent / trial['log']
    completed = (datetime.fromtimestamp(log.stat().st_mtime, timezone.utc).isoformat()
                 if log.exists() else None)
    rows.append({
        'id': trial['id'],
        'completed_utc': completed,
        'elapsed_seconds': trial['elapsed_seconds'],
        'fault_plan': trial['plan'],
        'requested_fault_events': trial['requested_fault_events'],
        'matched_fault_events': trial['matched_fault_events'],
        'applied_fault_events': trial['applied_fault_events'],
        'strict': trial['strict'],
        'target_after_final_fault': trial['target_after_final_fault'],
        'exact_target_exception': trial['exact_target_exception'],
        'expected_target_exception': trial['expected_target_exception'],
        'unexpected_target_exception': trial['unexpected_target_exception'],
        'target_guard_count': trial['target_guard_count'],
        'junit': trial['junit'],
        'junit_exit': trial['junit_exit'],
        'observed_io_events': trial['observed_io_events'],
        'new_production_methods': trial['new_production_methods'],
        'new_production_branches': trial['new_production_branches'],
        'new_io_selectors': trial['new_io_selectors'],
        'new_io_sites': trial['new_io_sites'],
        'disposition': trial['disposition'],
        'log': trial['log'],
    })

out = HERE / 'trial_ledger.json'
temp = out.with_suffix('.tmp')
temp.write_text(json.dumps({'case_id': 'HBASE-21',
                            'methodology': 'coverage_io_no_graph',
                            'source': 'work/checkpoint.json',
                            'completed_attempts': len(rows),
                            'effective_trials': sum(x['strict'] and x['target_after_final_fault']
                                                    for x in rows),
                            'trials': rows}, indent=2) + '\n')
os.replace(temp, out)
print(out, len(rows))
