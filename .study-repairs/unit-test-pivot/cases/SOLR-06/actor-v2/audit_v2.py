#!/usr/bin/env python3
"""Recount completed SOLR-06 trials from the original JUnit artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import campaign_v2 as campaign
from build_v2 import HERE, sha
from calibrate_v2 import rows, selected, target_signature
from run_v2 import verify_build


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recount() -> dict:
    build = verify_build()
    state_bytes = campaign.STATE.read_bytes()
    state = json.loads(state_bytes)
    campaign.verify_state(state)
    issues: list[str] = []
    coverage = set(state['baseline_coverage'])
    families = set(state['baseline_families'])
    receipts = []
    if state['selected_count'] != len(state['trials']):
        issues.append('selected_count differs from completed trial rows')
    seen_plans = set()
    for index, saved in enumerate(state['trials'], 1):
        directory = campaign.ROOT / f'trial-{index:03d}'
        plan = directory / 'fault.properties'
        log = directory / 'junit.log'
        metadata = json.loads((directory / 'run.json').read_text())
        trace = rows(directory)
        actor = campaign.audit_trial(trace)
        sequence = saved['sequence']
        key = campaign.identity((saved['target'], sequence))
        if key in seen_plans:
            issues.append(f'trial {index}: repeated target/plan')
        seen_plans.add(key)
        strict = campaign.exact(trace, sequence)
        applied = [item for item in trace if item['event'] == 'IO_APPLIED']
        final_seq = applied[-1]['seq'] if applied else -1
        guards = [item for item in trace if selected(item)
                  and target_signature(item) == tuple(saved['target'])
                  and item['seq'] > final_seq]
        throws = [item for item in trace if item['event'] == 'TARGET_THROW'
                  and target_signature(item) == tuple(saved['target'])
                  and item['seq'] > final_seq]
        effective = strict and bool(guards)
        raw_families = {campaign.family(campaign.point(item)) for item in trace
                        if campaign.relevant(item)}
        raw_probes = campaign.coverage(directory) if effective else set()
        gained_probes = len(raw_probes - coverage) if effective else 0
        gained_families = len(raw_families - families) if effective else 0
        if effective:
            coverage |= raw_probes
            families |= raw_families
        expected = {
            'number': index, 'exact_injection': strict,
            'applied_faults': len(applied), 'target_after_fault': strict and bool(guards),
            'target_exception': strict and bool(throws), 'effective': effective,
            'new_coverage': gained_probes, 'new_families': gained_families,
            'junit_exit': metadata['exit_code'], 'actor_audit': actor,
        }
        for field, value in expected.items():
            if saved.get(field) != value:
                issues.append(f'trial {index}: {field} saved={saved.get(field)!r} raw={value!r}')
        if saved != json.loads((directory / 'trial.json').read_text()):
            issues.append(f'trial {index}: trial.json differs from checkpoint')
        if metadata['agent_sha256'] != build['agent_sha256']:
            issues.append(f'trial {index}: wrong agent build')
        if metadata['source_revision'] != build['source_revision']:
            issues.append(f'trial {index}: wrong Solr revision')
        if metadata['plan'] != str(plan.resolve()):
            issues.append(f'trial {index}: run.json points at another fault plan')
        if abs(metadata['elapsed_seconds'] - saved['elapsed_seconds']) > 0.001:
            issues.append(f'trial {index}: elapsed time differs')
        if metadata['exit_code'] == 0 and not re.search(
                r'SOLR05_JUNIT_RESULT run=2 failures=0 ignored=0', log.read_text()):
            issues.append(f'trial {index}: exit 0 lacks passing original JUnit receipt')
        receipts.append({
            'number': index, 'effective': effective, 'strict': strict,
            'postfault_target': bool(guards) if strict else False,
            'exact_target_throw': bool(throws) if strict else False,
            'junit_exit': metadata['exit_code'],
            'elapsed_seconds': metadata['elapsed_seconds'],
            'new_coverage': gained_probes, 'new_families': gained_families,
            'plan_sha256': sha(plan), 'trace_sha256': digest(directory / 'events.jsonl'),
            'jacoco_sha256': sha(directory / 'jacoco.exec')
            if (directory / 'jacoco.exec').is_file() else None,
            'junit_log_sha256': sha(log),
        })
    if coverage != set(state['seen_coverage']):
        issues.append('production probe union differs from checkpoint')
    if families != set(state['seen_families']):
        issues.append('I/O family union differs from checkpoint')
    return {
        'case_id': 'SOLR-06', 'state_sha256': hashlib.sha256(state_bytes).hexdigest(),
        'source_revision': build['source_revision'], 'agent_sha256': build['agent_sha256'],
        'selected': len(receipts), 'strict': sum(r['strict'] for r in receipts),
        'effective': sum(r['effective'] for r in receipts),
        'exact_target_throws': sum(r['exact_target_throw'] for r in receipts),
        'elapsed_seconds': round(sum(r['elapsed_seconds'] for r in receipts), 3),
        'coverage_union_size': len(coverage), 'io_family_union_size': len(families),
        'issues': issues, 'trials': receipts,
    }


if __name__ == '__main__':
    result = recount()
    output = HERE / 'audit-receipt.json'
    campaign.atomic(output, result)
    print(json.dumps({key: result[key] for key in
                      ('selected', 'strict', 'effective', 'exact_target_throws',
                       'elapsed_seconds', 'issues')}, sort_keys=True))
    if result['issues']:
        raise SystemExit(1)
