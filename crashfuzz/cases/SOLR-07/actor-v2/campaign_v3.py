#!/usr/bin/env python3
"""Continue the unchanged V2 checkpoint with periodic fresh one-fault roots."""

from __future__ import annotations

import json
import random

import campaign_v2 as v2
from build_v2 import sha


V2_CHOOSE = v2.choose
POLICY = 'periodic_fresh_actor_root_v3'


def choose(state: dict) -> dict:
    # A high-coverage ancestor can otherwise keep all healthy roots waiting
    # while its deep descendants repeatedly lose the selected core check.
    roots = [i for i, entry in enumerate(state['queue'])
             if len(entry['sequence']) == 1]
    if roots and state['selected_count'] % 2 == 0:
        for entry in state['queue']:
            entry['wait'] += 1
        randomizer = random.Random(707000 + state['selected_count'])
        index = max(roots, key=lambda i: (state['queue'][i]['wait'],
                                          randomizer.random()))
        return state['queue'].pop(index)
    return V2_CHOOSE(state)


def main() -> None:
    state = json.loads(v2.STATE.read_text())
    policy_hash = sha(v2.HERE / 'campaign_v3.py')
    existing = state.get('scheduler_v3')
    if existing is not None:
        if existing['policy'] != POLICY or existing['sha256'] != policy_hash:
            raise RuntimeError('V3 scheduler changed after handoff')
    else:
        state['scheduler_v3'] = {
            'policy': POLICY, 'sha256': policy_hash,
            'handoff_selected': state['selected_count'],
            'handoff_effective': sum(row['effective'] for row in state['trials']),
            'rule': 'every other selection takes a fresh one-fault actor-bound root',
        }
        v2.atomic(v2.STATE, state)
    v2.choose = choose
    v2.campaign()


if __name__ == '__main__':
    main()
