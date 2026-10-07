#!/usr/bin/env python3
"""Recompute completed V2 trials from raw artifacts before a queue handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import campaign_v2 as v2
from build_v2 import sha
from calibrate_v2 import rows, selected, target_signature


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
                        default=v2.HERE / 'handoff-v3-audit.json')
    args = parser.parse_args()
    state = json.loads(v2.STATE.read_text())
    errors = []
    coverage = set(state['baseline_coverage'])
    families = set(state['baseline_families'])
    exact_count = 0
    effective_count = 0
    target_throws = 0
    for number, saved in enumerate(state['trials'], 1):
        directory = v2.ROOT / f'trial-{number:03d}'
        trace = rows(directory)
        try:
            v2.audit_trial(trace)
        except Exception as error:
            errors.append(f'{number}: actor audit: {error}')
        plan = saved['sequence']
        strict = v2.exact(trace, plan)
        applied = [row for row in trace if row['event'] == 'IO_APPLIED']
        last = applied[-1]['seq'] if applied else -1
        target = tuple(saved['target'])
        guards = [row for row in trace if selected(row)
                  and target_signature(row) == target and row['seq'] > last
                  and all(v2.client_id(item) == v2.client_id(row)
                          and item['actorKey'] == row['actorKey'] for item in applied)]
        throws = [row for row in trace if row['event'] == 'TARGET_THROW'
                  and target_signature(row) == target and row['seq'] > last]
        effective = strict and bool(guards)
        metadata = json.loads((directory / 'run.json').read_text())
        trial = json.loads((directory / 'trial.json').read_text())
        for key, computed in (('exact_injection', strict),
                              ('target_after_fault', bool(guards) if strict else False),
                              ('target_exception', bool(throws) if strict else False),
                              ('effective', effective)):
            if saved[key] != computed or trial[key] != computed:
                errors.append(f'{number}: {key} mismatch')
        if saved['number'] != number or trial != saved:
            errors.append(f'{number}: saved checkpoint/trial mismatch')
        if metadata['agent_sha256'] != state['agent_sha256']:
            errors.append(f'{number}: build identity mismatch')
        if strict:
            exact_count += 1
        if effective:
            effective_count += 1
            probes = v2.coverage(directory)
            observed_families = {v2.family(v2.point(row)) for row in trace
                                 if v2.relevant(row)}
            if saved['new_coverage'] != len(probes - coverage):
                errors.append(f'{number}: coverage gain mismatch')
            if saved['new_families'] != len(observed_families - families):
                errors.append(f'{number}: I/O gain mismatch')
            coverage |= probes
            families |= observed_families
        if strict and throws:
            target_throws += 1
    if state['selected_count'] != len(state['trials']):
        errors.append('selected count differs from completed trial count')
    if coverage != set(state['seen_coverage']):
        errors.append('cumulative JaCoCo coverage mismatch')
    if families != set(state['seen_families']):
        errors.append('cumulative I/O family mismatch')
    output = {
        'case_id': 'SOLR-07', 'checkpoint_sha256': sha(v2.STATE),
        'selected': len(state['trials']), 'strict': exact_count,
        'effective': effective_count, 'exact_target_throws': target_throws,
        'errors': errors,
    }
    v2.atomic(args.output, output)
    print(json.dumps(output, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
