#!/usr/bin/env python3
"""Independently re-read the raw exact-plan trial 38 replays."""

from __future__ import annotations

import json

import campaign_v2 as v2
from build_v2 import sha
from calibrate_v2 import rows, selected, target_signature


def main() -> None:
    state = json.loads(v2.STATE.read_text())
    original = state['trials'][37]
    plan = v2.ROOT / 'trial-038/fault.properties'
    target = tuple(original['target'])
    errors = []
    replays = []
    for suffix in 'abcde':
        directory = v2.ROOT / f'replay-trial-038-{suffix}'
        trace = rows(directory)
        actor = v2.audit_trial(trace)
        metadata = json.loads((directory / 'run.json').read_text())
        if metadata['agent_sha256'] != state['agent_sha256']:
            errors.append(f'{suffix}: agent identity changed')
        if metadata['source_revision'] != original_revision():
            errors.append(f'{suffix}: Solr source revision changed')
        if metadata['plan'] != str(plan.resolve()):
            errors.append(f'{suffix}: plan path changed')
        applied = [row for row in trace if row['event'] == 'IO_APPLIED']
        strict = v2.exact(trace, original['sequence'])
        last = applied[-1]['seq'] if applied else -1
        guards = [row for row in trace if selected(row)
                  and target_signature(row) == target and row['seq'] > last
                  and all(v2.client_id(item) == v2.client_id(row)
                          and item['actorKey'] == row['actorKey']
                          for item in applied)]
        throws = [row for row in trace if row['event'] == 'TARGET_THROW'
                  and target_signature(row) == target and row['seq'] > last]
        row = {
            'suffix': suffix, 'elapsed_seconds': metadata['elapsed_seconds'],
            'junit_exit': metadata['exit_code'], 'applied': len(applied),
            'strict': strict, 'effective': strict and bool(guards),
            'target_throw': strict and bool(guards) and bool(throws),
            'actor_audit': actor,
            'events_sha256': sha(directory / 'events.jsonl'),
            'junit_sha256': sha(directory / 'junit.log'),
            'run_sha256': sha(directory / 'run.json'),
        }
        receipt = directory / 'replay-receipt.json'
        if receipt.exists():
            recorded = json.loads(receipt.read_text())
            for key in ('applied', 'strict', 'events_sha256', 'junit_sha256',
                        'run_sha256'):
                if recorded[key] != row[key]:
                    errors.append(f'{suffix}: {key} receipt mismatch')
        replays.append(row)
    result = {
        'source_trial': 38, 'plan_sha256': sha(plan),
        'original_checkpoint_sha256': sha(v2.STATE),
        'replays': replays, 'errors': errors,
    }
    v2.atomic(v2.HERE / 'trial038-replays-audit.json', result)
    print(json.dumps(result, sort_keys=True))
    if errors:
        raise SystemExit(1)


def original_revision() -> str:
    return json.loads((v2.HERE / 'build-receipt.json').read_text())['source_revision']


if __name__ == '__main__':
    main()
