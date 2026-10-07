#!/usr/bin/env python3
"""Bounded new I/O class: stable moved-session reads before first guard."""

import argparse
import json
import os
from pathlib import Path

import pilot_multiop as base
import campaign_multiop as campaign

CHECKPOINT = base.ROOT / 'pre-first-checkpoint.json'


def queue():
    state = json.loads(campaign.CHECKPOINT.read_text())
    if state['status'] != 'queue_exhausted' or state['pending'] or state['inflight']:
        raise RuntimeError('interguard campaign is not terminal')
    seeds = []
    for name in ('healthy-a', 'healthy-b'):
        rows = base.parse_events(base.ROOT / name / 'events.tsv')
        guard = next(seq for seq, kind, fields, _ in rows
                     if kind == 'TARGET_GUARD' and fields[0] == base.CHECK)
        seeds.append({'@@'.join(f[:4]) for seq, kind, f, _ in rows
                      if kind == 'IO' and len(f) >= 7 and seq < guard
                      and f[6] == 'movedSession'
                      and f[1].startswith('client:handle:0:session:movedSession')})
    common = sorted(seeds[0] & seeds[1])
    seen = {tuple(x) for x in state['seen_plans']}
    remaining = [x for x in common if (x,) not in seen]
    if len(remaining) != 4:
        raise RuntimeError('expected four stable, previously untested pre-first selectors')
    return remaining, state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-id', type=int, default=14)
    parser.add_argument('--worker-count', type=int, default=16)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    base.verify_assets()
    selectors, state = queue()
    if CHECKPOINT.exists():
        checkpoint = json.loads(CHECKPOINT.read_text())
        if checkpoint['queue'] != selectors or \
                checkpoint['agent_sha256'] != base.sha(base.AGENT):
            raise RuntimeError('resumed class queue/agent changed')
    else:
        checkpoint = {'status': 'running', 'queue': selectors, 'next_index': 0,
                      'results': [], 'agent_sha256': base.sha(base.AGENT),
                      'prior_campaign_effective': state['effective_count'],
                      'prior_campaign_checkpoint_sha256': base.sha(campaign.CHECKPOINT)}
        campaign.write_json(CHECKPOINT, checkpoint)
    covered = set(state['seen_coverage'])
    for row in checkpoint['results']:
        if row['effective']:
            covered.update(row['coverage'])
    for index in range(checkpoint['next_index'], len(selectors)):
        run_id = 'pre-first-{:02d}'.format(index + 1)
        plan = [selectors[index]]
        base.run_one(run_id, plan, args.worker_id, args.worker_count, args.timeout)
        result = base.audit_trial_generic(run_id, plan, covered)
        if result['effective']:
            covered.update(result['coverage'])
        checkpoint['results'].append(result)
        checkpoint['next_index'] += 1
        campaign.write_json(CHECKPOINT, checkpoint)
        print(json.dumps({k: result[k] for k in ('run_id', 'exact', 'bound_same_session',
              'effective', 'target_after_fault', 'selected_target_throws',
              'new_coverage_lines', 'elapsed_seconds', 'junit_exit')}, sort_keys=True),
              flush=True)
    checkpoint['status'] = 'pilot_complete'
    campaign.write_json(CHECKPOINT, checkpoint)
    print(json.dumps({'status': checkpoint['status'],
                      'selected': checkpoint['next_index'],
                      'effective': sum(x['effective'] for x in checkpoint['results'])},
                     sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
