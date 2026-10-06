#!/usr/bin/env python3
"""Requalify earlier trials after excluding pre-FOLLOWERINFO peer=0 selectors."""

import hashlib
import json
from pathlib import Path
import time

import campaign


def ambiguous(plan):
    return any('LearnerHandler#' in exact and '@@peer=0@@' in exact for exact in plan)


def main():
    raw = campaign.STATE.read_bytes()
    archive = campaign.HERE / 'pre-identity-audit-checkpoint.json'
    if not archive.exists():
        archive.write_bytes(raw)
    state = json.loads(raw)
    seed_ev = campaign.events(campaign.HERE / 'healthy/events.tsv')
    seed_cov = campaign.coverage(campaign.HERE / 'healthy/coverage.tsv')
    seed_fam = {campaign.family(e) for e in seed_ev if campaign.eligible_io(e)}
    admitted_cov = set(seed_cov)
    admitted_fam = set(seed_fam)
    repaired = []
    for old in state['trials']:
        folder = campaign.HERE / 'trial-evidence' / old['id']
        row, _, cov, families, _ = campaign.analyze(old['id'], old['fault_plan'],
                                                    folder, admitted_cov, admitted_fam)
        row['parent'] = old['parent']
        if row['identity_ambiguous']:
            row['exclusion_reason'] = 'pre-FOLLOWERINFO sid=0 merges distinct LearnerHandler sockets'
        else:
            row['identity_audit_retained'] = True
        repaired.append(row)
        if row['target_guard_after_final_fault']:
            admitted_cov.update(cov)
            admitted_fam.update(families)
    abandoned = state['inflight']
    state['abandoned_inflight'] = [{'trial': abandoned['id'],
                                  'plan': abandoned['plan'],
                                  'reason': 'excluded ambiguous peer=0 selector before JVM start'}]
    state['inflight'] = None
    state['trials'] = repaired
    state['queue'] = [q for q in state['queue'] if not ambiguous(q['plan'])]
    state['admitted_cov'] = sorted(admitted_cov)
    state['admitted_families'] = sorted(admitted_fam)
    state['identity_audit'] = {'timestamp': time.time(),
                               'pre_audit_checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
                               'excluded_trial_count': sum(r['identity_ambiguous'] for r in repaired),
                               'excluded_selector': 'LearnerHandler#run:472 peer=0'}
    campaign.publish(state, seed_cov, seed_fam)
    print(json.dumps(state['identity_audit'], indent=2))


if __name__ == '__main__':
    main()
