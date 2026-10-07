#!/usr/bin/env python3
"""Bounded fresh-fixture replays of the exact SOLR-07 trial 38 plan."""

from __future__ import annotations

import json

import campaign_v2 as v2
from build_v2 import sha
from calibrate_v2 import rows, selected, target_signature


def main() -> None:
    state = json.loads(v2.STATE.read_text())
    original = state['trials'][37]
    if original['number'] != 38 or not original['exact_injection']:
        raise RuntimeError('trial 38 checkpoint identity changed')
    plan = v2.ROOT / 'trial-038/fault.properties'
    target = tuple(original['target'])
    for suffix in 'bcde':
        directory = v2.ROOT / f'replay-trial-038-{suffix}'
        if (directory / 'replay-receipt.json').exists():
            continue
        exit_code = v2.run(directory, plan)
        trace = rows(directory)
        actor = v2.audit_trial(trace)
        strict = v2.exact(trace, original['sequence'])
        applied = [row for row in trace if row['event'] == 'IO_APPLIED']
        last = applied[-1]['seq'] if applied else -1
        guards = [row for row in trace if selected(row)
                  and target_signature(row) == target and row['seq'] > last
                  and all(v2.client_id(item) == v2.client_id(row)
                          and item['actorKey'] == row['actorKey']
                          for item in applied)]
        throws = [row for row in trace if row['event'] == 'TARGET_THROW'
                  and target_signature(row) == target and row['seq'] > last]
        receipt = {
            'case_id': 'SOLR-07', 'source_trial': 38, 'plan_sha256': sha(plan),
            'exit_code': exit_code, 'actor_audit': actor,
            'applied': len(applied), 'strict': strict,
            'target_after_final_fault': strict and bool(guards),
            'exact_target_throw': strict and bool(guards) and bool(throws),
            'events_sha256': sha(directory / 'events.jsonl'),
            'junit_sha256': sha(directory / 'junit.log'),
            'run_sha256': sha(directory / 'run.json'),
        }
        v2.atomic(directory / 'replay-receipt.json', receipt)
        print(json.dumps(receipt, sort_keys=True), flush=True)
        if strict and guards:
            break


if __name__ == '__main__':
    main()
