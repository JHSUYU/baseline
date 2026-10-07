#!/usr/bin/env python3
"""Independently verify each V2 fault's observed peer and region identity."""
import json
import re
from pathlib import Path

from campaign_v2 import LOGS, parse_log

HERE = Path(__file__).resolve().parent
LEDGER = HERE / 'trial_ledger_v2.json'
OUTPUT = HERE / 'trial_actor_audit_v2.json'


def audit_trial(trial):
    trace = parse_log(LOGS / (trial['id'] + '.log'))
    role_maps = trace['role_maps']
    errors = []
    if len(role_maps) != 1 or len(trace['initial_owner']) != 1:
        errors.append('missing or ambiguous role map/initial owner')
        role_map = None
    else:
        source, destination, third, region, verified = role_maps[0]
        role_map = {'INITIAL_OWNER': source, 'SOURCE_RS': source,
                    'MOVE_DEST_RS': destination, 'THIRD_RS': third}
        if (len({source, destination, third}) != 3 or region != 'Report_ROOT_r0'
                or verified != 'true' or trace['initial_owner'][0] != (source, region)):
            errors.append('role map disagrees with the original test owner/region')
    events_by_seq = {}
    for line in (LOGS / (trial['id'] + '.log')).read_text(errors='replace').splitlines():
        match = re.search(r'HBASE17 IO seq=(\d+) selector=(\S+) '
                          r'originalError=(\S+) peer=(\S+)', line)
        if match:
            events_by_seq[int(match.group(1))] = {
                'selector': match.group(2), 'original_error': match.group(3),
                'peer': match.group(4).lstrip('/')}
    applied = trace['applied']
    for event in applied:
        step = event['step']
        if step < 1 or step > len(trial['plan']):
            errors.append('applied step outside plan: %d' % step)
            continue
        expected = trial['plan'][step - 1]
        selector, kind = expected.rsplit('~', 1)
        observed = events_by_seq.get(event['seq'])
        if event['selector'] != selector or event['kind'] != kind:
            errors.append('applied event disagrees with exact plan step %d' % step)
        if not observed or observed['selector'] != selector:
            errors.append('missing matching raw I/O event at step %d' % step)
            continue
        if 'Report_ROOT_r0' not in selector:
            errors.append('incomplete target-region resource at step %d' % step)
        peer = observed['peer']
        if selector.startswith('META_PUT~'):
            if peer != 'local' or '~MASTER_PROC~' not in selector:
                errors.append('META_PUT not local master procedure at step %d' % step)
            continue
        if not selector.startswith('RPC_'):
            errors.append('unsupported fault family at step %d' % step)
            continue
        role = selector.rsplit('~', 2)[-2].rsplit('@', 1)[-1]
        if role in ('PREMOVE', 'UNKNOWN_PEER'):
            errors.append('unresolved actor role at step %d' % step)
        elif role_map and role in role_map:
            if peer != role_map[role]:
                errors.append('peer disagrees with %s at step %d' % (role, step))
        elif role == 'MASTER':
            if (not ('MasterService.' in selector or
                     'RegionServerStatusService.' in selector)
                    or (role_map and peer in set(role_map.values()))):
                errors.append('MASTER descriptor/peer mismatch at step %d' % step)
        else:
            errors.append('unsupported actor role %s at step %d' % (role, step))
    controller_strict = bool(trial['strict'])
    actor_proven = (controller_strict and not errors
                    and len(applied) == len(trial['plan']))
    return {'id': trial['id'], 'controller_strict': controller_strict,
            'controller_target_after_fault': bool(trial['target_after_final_fault']),
            'actor_proven_strict': actor_proven,
            'actor_proven_target_after_fault':
                actor_proven and bool(trial['target_after_final_fault']),
            'applied_steps': len(applied), 'plan_steps': len(trial['plan']),
            'identity_errors': errors}


def main():
    trials = json.loads(LEDGER.read_text())
    audited = [audit_trial(item) for item in trials]
    out = {'trials_audited': len(audited),
           'controller_strict': sum(x['controller_strict'] for x in audited),
           'actor_proven_strict': sum(x['actor_proven_strict'] for x in audited),
           'actor_proven_target_after_fault': sum(
               x['actor_proven_target_after_fault'] for x in audited),
           'strict_with_identity_error': [x['id'] for x in audited
                                          if x['controller_strict'] and x['identity_errors']],
           'trials': audited}
    OUTPUT.write_text(json.dumps(out, indent=2) + '\n')
    print('ACTOR_AUDIT attempts=%d strict=%d proven=%d target=%d errors=%d' %
          (out['trials_audited'], out['controller_strict'],
           out['actor_proven_strict'], out['actor_proven_target_after_fault'],
           len(out['strict_with_identity_error'])))


if __name__ == '__main__':
    main()
