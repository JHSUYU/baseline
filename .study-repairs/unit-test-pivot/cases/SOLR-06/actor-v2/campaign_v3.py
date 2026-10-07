#!/usr/bin/env python3
"""Resume SOLR-06 with periodic fresh, actor-bound single-fault seeds.

This changes only queue selection.  The calibrated JUnit, Java agent, fault
matching, effective-trial oracle, mutation and 80/128 budget remain in V2.
Run this only after the V2 process has stopped at a complete checkpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
import random

import campaign_v2 as v2
from build_v2 import sha


OLD_CHOOSE = v2.choose
POLICY = 'solr06-periodic-fresh-root-v3'


def choose(state: dict) -> dict:
    # V2's coverage/depth choice remains in effect on alternating selections.
    # A fresh root prevents high-scoring, mostly unmatched descendants from
    # starving the many untried I/O families observed in both healthy seeds.
    if state['selected_count'] % 2:
        return OLD_CHOOSE(state)

    roots = [(i, item) for i, item in enumerate(state['queue'])
             if len(item['sequence']) == 1]
    if not roots:
        return OLD_CHOOSE(state)

    for item in state['queue']:
        item['wait'] += 1
    tested_roots = [trial for trial in state['trials']
                    if len(trial['sequence']) == 1]
    tried_families = {v2.family(trial['sequence'][0]) for trial in tested_roots}
    target_counts: dict[tuple[str, ...], int] = {}
    for trial in tested_roots:
        target = tuple(trial['target'])
        target_counts[target] = target_counts.get(target, 0) + 1

    rng = random.Random(606003 + state['selected_count'])
    def rank(entry: dict) -> tuple[int, int, int, float]:
        return (int(v2.family(entry['sequence'][0]) not in tried_families),
                -target_counts.get(tuple(entry['target']), 0),
                min(entry['wait'], 100), rng.random())

    index, _ = max(roots, key=lambda pair: rank(pair[1]))
    return state['queue'].pop(index)


def main() -> None:
    if not v2.STATE.is_file():
        raise RuntimeError('V3 requires an existing complete V2 checkpoint')
    state = json.loads(v2.STATE.read_text())
    if state.get('scheduler_policy') not in (None, POLICY):
        raise RuntimeError('unexpected scheduler policy in checkpoint')
    policy_hash = sha(Path(__file__))
    if state.get('scheduler_policy_sha256') not in (None, policy_hash):
        raise RuntimeError('scheduler policy changed after V3 checkpoint')
    if state['selected_count'] != len(state['trials']):
        raise RuntimeError('incomplete V2 checkpoint')
    if len(state['seen']) != len(state['trials']):
        raise RuntimeError('V2 seen/trial mismatch')
    if state['selected_count'] >= state['budget']['max_selected']:
        raise RuntimeError('attempt cap reached; review before raising it')
    if state.get('stopped'):
        raise RuntimeError('terminal campaign; review before resumption')
    v2.verify_state(state)
    state['scheduler_policy'] = POLICY
    state['scheduler_policy_sha256'] = policy_hash
    v2.atomic(v2.STATE, state)
    v2.choose = choose
    v2.campaign()


if __name__ == '__main__':
    main()
