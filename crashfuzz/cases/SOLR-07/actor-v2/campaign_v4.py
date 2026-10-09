#!/usr/bin/env python3
"""Resume SOLR-07 with every stable healthy actor-bound I/O root.

V2 initially kept the last 20 and first eight pre-target I/O points per
target. V4 adds the omitted points observed in *both* healthy JUnit runs and
spends three of four selections on one-fault roots. The original checkpoint,
target identity, fault model, coverage feedback, and effective-trial rule are
unchanged.
"""

from __future__ import annotations

import argparse
import json
import random

import campaign_v2 as v2
from build_v2 import sha
from calibrate_v2 import SEEDS, rows, selected, target_signature


POLICY = 'all_stable_actor_roots_v4'
V2_CHOOSE = v2.choose


def full_roots() -> list[dict]:
    first, second = (rows(seed) for seed in SEEDS)
    receipt = json.loads((v2.HERE / 'calibration-receipt.json').read_text())
    common = set(map(tuple, receipt['common_target_signatures']))
    roots = []
    seen = set()
    for target in sorted(common):
        a_guards = [row for row in first if selected(row)
                    and target_signature(row) == target]
        b_guards = [row for row in second if selected(row)
                    and target_signature(row) == target]
        if not a_guards or not b_guards:
            continue
        cutoff_a = min(row['seq'] for row in a_guards)
        cutoff_b = min(row['seq'] for row in b_guards)
        clients_a = {v2.client_id(row) for row in a_guards}
        clients_b = {v2.client_id(row) for row in b_guards}
        second_points = {v2.identity(v2.point(row)) for row in second
                         if v2.relevant(row) and row['seq'] < cutoff_b
                         and row['actorKey'] == target[0]
                         and v2.client_id(row) in clients_b}
        for row in first:
            if not (v2.relevant(row) and row['seq'] < cutoff_a
                    and row['actorKey'] == target[0]
                    and v2.client_id(row) in clients_a):
                continue
            item = v2.point(row)
            if v2.identity(item) not in second_points:
                continue
            key = v2.identity((target, [item]))
            if key in seen:
                continue
            seen.add(key)
            roots.append({'target': list(target), 'sequence': [item],
                          'parent_gain': 0, 'wait': 0,
                          'origin': POLICY,
                          'healthy_distance': cutoff_a - row['seq']})
    return roots


def pending_roots(state: dict, roots: list[dict]) -> list[dict]:
    known = set(state['seen'])
    known.update(v2.identity((item['target'], item['sequence']))
                 for item in state['queue'])
    return [item for item in roots
            if v2.identity((item['target'], item['sequence'])) not in known]


def choose(state: dict) -> dict:
    queue = state['queue']
    roots = [i for i, entry in enumerate(queue)
             if len(entry['sequence']) == 1]
    if roots and state['selected_count'] % 4 != 3:
        for entry in queue:
            entry['wait'] += 1
        if state['selected_count'] % 4 in (0, 1):
            fresh = [i for i in roots if queue[i].get('origin') == POLICY]
            if fresh:
                roots = fresh
        randomizer = random.Random(707400 + state['selected_count'])
        index = max(roots, key=lambda i: (queue[i]['wait'], randomizer.random()))
        return queue.pop(index)
    return V2_CHOOSE(state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    state = json.loads(v2.STATE.read_text())
    v2.verify_state(state)
    if state['selected_count'] != len(state['trials']):
        raise RuntimeError('checkpoint trial count mismatch')
    roots = full_roots()
    additions = pending_roots(state, roots)
    print(json.dumps({'selected': state['selected_count'],
                      'effective': sum(item['effective'] for item in state['trials']),
                      'healthy_roots': len(roots), 'new_roots': len(additions),
                      'queue': len(state['queue'])}, sort_keys=True), flush=True)
    if args.dry_run:
        return
    policy_hash = sha(v2.HERE / 'campaign_v4.py')
    existing = state.get('scheduler_v4')
    if existing is not None:
        if existing['policy'] != POLICY or existing['sha256'] != policy_hash:
            raise RuntimeError('V4 scheduler changed after handoff')
    else:
        state['scheduler_v4'] = {
            'policy': POLICY, 'sha256': policy_hash,
            'handoff_selected': state['selected_count'],
            'handoff_effective': sum(item['effective'] for item in state['trials']),
            'healthy_roots': len(roots), 'added_roots': len(additions),
            'rule': 'two fresh roots, one other root, one V2 feedback choice per four',
        }
    state['queue'].extend(additions)
    state.pop('stopped', None)
    state.pop('stop_reason', None)
    state.pop('effective_count', None)
    v2.atomic(v2.STATE, state)
    v2.choose = choose
    v2.campaign()


if __name__ == '__main__':
    main()
