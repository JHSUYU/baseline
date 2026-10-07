#!/usr/bin/env python3
"""Recount exact actor/target receipts and original production coverage."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'independent'
sys.path.insert(0, str(PARENT))
from audit_campaign_coverage import totals  # noqa: E402
sys.path.insert(0, str(HERE))
from fuzz_v2 import (AGENT, CORE, GUARD, SEEDS, TARGET, THROW, family, guard_events,
                     load_events, point, point_id, relevant, validate_actor_trace)


ROOT = HERE / 'campaign'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recount(state: dict, allow_running: bool) -> dict:
    if not allow_running and (state['status'] == 'running'
                              or state['active'] is not None):
        raise RuntimeError('campaign has an in-flight original JUnit')
    if state['agent_sha256'] != digest(AGENT):
        raise RuntimeError('campaign actor agent differs from the recorded build')
    healthy = [directory / 'jacoco.exec' for directory in SEEDS]
    healthy_families = {family(point(event)) for directory in SEEDS
                        for event in load_events(directory)
                        if event['event'] == 'IO_OBSERVED' and relevant(point(event))}
    families = set(healthy_families)
    rows = []
    valid_coverage = []
    for number, trial in enumerate(state['completed'], 1):
        if trial['trial_number'] != number:
            raise RuntimeError('completed plan order changed')
        path = Path(trial['trace'])
        events = load_events(path.parent)
        actor = validate_actor_trace(events)
        applied = [event for event in events if event['event'] == 'IO_OBSERVED'
                   and event['applied']]
        planned = trial['fault_sequence']
        summaries = [event for event in events if event['event'] == 'SUMMARY']
        exact = len(applied) == len(planned) and all(
            point_id(point(event)) == point_id(plan)
            for event, plan in zip(applied, planned)) and len(summaries) == 1 \
            and summaries[0]['detail'] == f'applied={len(planned)}/{len(planned)}'
        if exact != trial['strict_injection']:
            raise RuntimeError(f'trial {number}: strict identity recount differs')
        boundary = applied[-1]['seq'] if exact else -1
        guards = [event for event in guard_events(events)
                  if event['seq'] > boundary]
        exact_guard = [event for event in guards
                       if event['marker'] == GUARD
                       and event['sourceKey'] == TARGET
                       and event['resource'] == CORE]
        same_actor = bool(applied and any(
            event['actorKey'] == applied[-1]['actorKey'] == 'JETTY/node1'
            and event['physicalNode'] == applied[-1]['physicalNode']
            for event in exact_guard))
        effective = exact and same_actor
        if effective != trial['target_preserved']:
            raise RuntimeError(f'trial {number}: post-fault exact actor recount differs')
        exact_throws = [event for event in events
                        if event['event'] == 'TARGET_THROW'
                        and event['marker'] == THROW
                        and event['sourceKey'] == TARGET
                        and event['resource'] == CORE
                        and event['actorKey'] == 'JETTY/node1'
                        and 'java.lang.AssertionError' in event['detail']]
        post_throws = sum(event['seq'] > boundary for event in exact_throws) if exact else 0
        if post_throws != trial['exact_target_throw_after_last_fault']:
            raise RuntimeError(f'trial {number}: target assertion recount differs')
        jacoco = Path(trial['jacoco'])
        if not jacoco.is_file() or jacoco.stat().st_size == 0:
            raise RuntimeError(f'trial {number}: missing JaCoCo execution')
        semantic = {family(point(event)) for event in events
                    if event['event'] == 'IO_OBSERVED' and relevant(point(event))}
        gain = len(semantic - families) if effective else 0
        if effective:
            families |= semantic
            valid_coverage.append(jacoco)
        rows.append({
            'trial_number': number,
            'attempts': trial['attempts'],
            'strict_injection': exact,
            'post_final_target_same_actor_and_physical_node': effective,
            'exact_target_assertion_after_fault': post_throws,
            'junit_exit': trial['junit_exit'],
            'junit_gate': trial['junit_gate'],
            'elapsed_seconds': trial['elapsed_seconds'],
            'new_production_probes': trial['new_production_probes'] if effective else 0,
            'new_semantic_io_families': gain,
            'last_fault_marker': applied[-1]['marker'] if applied else None,
            'last_fault_actor': applied[-1]['actorKey'] if applied else None,
            'actor_binding_count': actor['bindings'],
            'trace_sha256': digest(path),
            'jacoco_sha256': digest(jacoco),
        })
    base = totals(healthy)
    combined = totals(healthy + valid_coverage)
    return {
        'methodology': 'original Solr/Lucene release-JAR JaCoCo union and independent raw actor recount',
        'excluded_runtime_woven_classes': [
            'CoreContainer', 'CorePropertiesLocator', 'SolrZkClient'],
        'campaign_status': state['status'],
        'budget': state['budget'],
        'selected_plans': len(rows),
        'attempted_original_junits': sum(row['attempts'] for row in rows),
        'strict_injections': sum(row['strict_injection'] for row in rows),
        'effective_postfinal_same_actor_and_physical_node': sum(
            row['post_final_target_same_actor_and_physical_node'] for row in rows),
        'exact_target_assertion_after_fault_trials': sum(
            row['strict_injection'] and row['exact_target_assertion_after_fault'] > 0
            for row in rows),
        'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in rows), 3),
        'fault_depths': dict(Counter(str(trial['planned_faults'])
                             for trial in state['completed'])),
        'last_fault_markers': dict(Counter(row['last_fault_marker'] for row in rows)),
        'healthy_semantic_io_families': len(healthy_families),
        'new_semantic_io_families': len(families - healthy_families),
        'healthy_coverage': base,
        'healthy_plus_effective_coverage': combined,
        'new_production_methods': (combined['covered_production_methods']
                                   - base['covered_production_methods']),
        'new_production_branch_outcomes': (
            combined['covered_production_branch_outcomes']
            - base['covered_production_branch_outcomes']),
        'trial_receipts': rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-running', action='store_true')
    arguments = parser.parse_args()
    state = json.loads((ROOT / 'state.json').read_text())
    report = recount(state, arguments.allow_running)
    output = ROOT / ('interim-audit.json' if state['status'] == 'running'
                     else 'final-audit.json')
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ('trial_receipts', 'healthy_coverage',
                                     'healthy_plus_effective_coverage')}, sort_keys=True))


if __name__ == '__main__':
    main()
