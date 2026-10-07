#!/usr/bin/env python3
"""Export an auditable per-check HTTP role-V2 trial table at a terminal checkpoint."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_campaign import raw_actor_receipts
from fuzz_rpc import CHECKS

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'campaign'
SOURCE = 'solr/core/src/java/org/apache/solr/update/processor/DistributedZkUpdateProcessor.java'
LINES = {'SOLR-36': 987, 'SOLR-37': 995}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path: Path, value: object) -> None:
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def rows_for_trial(entry: dict) -> list[dict]:
    directory = Path(entry['trace']).parent
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()
              if line.strip()]
    selected = [event for event in events if event['event'] == 'IO_OBSERVED'
                and event['applied']]
    strict = bool(entry['strict_injection'])
    if strict and len(selected) != entry['planned_faults']:
        raise RuntimeError(f"trial {entry['trial_number']}: applied fault count changed")
    boundary = entry['fault_effect_boundary_seq'] if strict else -1
    last_child = entry['last_fault_source'] if strict else ''
    physical = urlsplit(selected[-1]['physicalNode']).netloc + '_' if strict else ''
    if strict and physical == '_':
        raise RuntimeError(f"trial {entry['trial_number']}: no child physical endpoint")
    receipt = json.loads((directory / 'run.json').read_text())
    trace_hash = digest(directory / 'events.jsonl')
    jacoco = directory / 'jacoco.exec'
    jacoco_hash = digest(jacoco) if jacoco.is_file() else ''
    result = []
    for case_id, (guard_marker, throw_marker) in CHECKS.items():
        guards = [event for event in events if strict
                  and event['event'] == 'TARGET_CHECK'
                  and event['marker'] == guard_marker
                  and event['sourceKey'] == last_child
                  and event['seq'] > boundary]
        throws = [event for event in events if strict
                  and event['event'] == 'TARGET_THROW'
                  and event['marker'] == throw_marker
                  and event['sourceKey'] == last_child
                  and event['seq'] > boundary]
        if len(guards) != entry['postfault_same_child_guards'][case_id]:
            raise RuntimeError(f"trial {entry['trial_number']} {case_id}: guard ledger mismatch")
        if len(throws) != entry['postfault_same_child_throws'][case_id]:
            raise RuntimeError(f"trial {entry['trial_number']} {case_id}: throw ledger mismatch")
        same_physical_guards = [event for event in guards
                                if event['physicalNode'] == physical]
        same_physical_throws = [event for event in throws
                                if event['physicalNode'] == physical]
        result.append({
            'case_id': case_id,
            'source_check': SOURCE + ':' + str(LINES[case_id]),
            'function': 'DistributedZkUpdateProcessor.doDefensiveChecks',
            'trial_number': entry['trial_number'],
            'attempts': entry['attempts'],
            'elapsed_seconds': entry['elapsed_seconds'],
            'planned_faults': entry['planned_faults'],
            'applied_faults': len(selected),
            'strict_actor_injection': strict,
            'same_child_postfault_guard': len(guards),
            'same_physical_child_postfault_guard': len(same_physical_guards),
            'effective': strict and bool(same_physical_guards),
            'exact_target_throw': len(same_physical_throws),
            'reviewed_protective_rejection': bool(
                case_id == 'SOLR-36' and same_physical_throws
                and entry.get('reviewed_expected_target_rejection')),
            'junit_exit': receipt['exit_code'],
            'junit_gate': str(entry['junit_gate']),
            'new_production_probes_raw': entry['new_production_probes'],
            'trace_sha256': trace_hash,
            'jacoco_sha256': jacoco_hash,
        })
    return result


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    stage = json.loads((ROOT / 'stage-status.json').read_text())
    if state['status'] not in ('budget_complete', 'queue_exhausted'):
        raise RuntimeError('fault campaign has not reached a complete trial boundary')
    if stage['status'] not in ('complete', 'queue_exhausted', 'incomplete_budget_limit'):
        raise RuntimeError('stage controller is still running')
    if state['active'] is not None:
        raise RuntimeError('active trial still present')
    actor = raw_actor_receipts(state)
    rows = [row for entry in state['completed'] for row in rows_for_trial(entry)]
    path = ROOT / 'final-trial-table.csv'
    with path.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    per_case = {case_id: {
        'effective': sum(row['effective'] for row in rows if row['case_id'] == case_id),
        'same_physical_mismatch_trials': actor['by_case'][case_id]['physical_mismatch_trials'],
        'exact_target_throw_trials': sum(bool(row['exact_target_throw'])
                                         for row in rows if row['case_id'] == case_id),
        'unreviewed_exact_target_throw_trials': [row['trial_number'] for row in rows
            if row['case_id'] == case_id and row['exact_target_throw']
            and not row['reviewed_protective_rejection']],
    } for case_id in CHECKS}
    for case_id in CHECKS:
        if per_case[case_id]['effective'] != actor['by_case'][case_id]['same_physical_postfault']:
            raise RuntimeError(f'{case_id}: per-trial physical audit differs')
    report = {
        'method': 'original-JUnit raw actor, physical target, per-attempt time and SHA audit',
        'stage_status': stage['status'],
        'campaign_status': state['status'],
        'selected_plans': len(state['completed']),
        'attempted_junits': sum(row['attempts'] for row in state['completed']),
        'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in state['completed']), 3),
        'table': str(path), 'table_sha256': digest(path),
        'cases': per_case, 'raw_actor_receipts': actor,
    }
    atomic(ROOT / 'final-trial-table-audit.json', report)
    print(json.dumps({'selected_plans': report['selected_plans'],
                      'attempted_junits': report['attempted_junits'],
                      'cases': per_case}, sort_keys=True))


if __name__ == '__main__':
    main()
