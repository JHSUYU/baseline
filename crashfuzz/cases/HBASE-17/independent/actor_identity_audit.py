#!/usr/bin/env python3
"""Audit legacy fault plans against per-run source/destination RS roles.

This is read-only: it does not edit the campaign checkpoint or count a trial.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
IO_RE = re.compile(r'HBASE17 IO seq=\d+ selector=(\S+) originalError=\S+ peer=(\S+)')
SRC_RE = re.compile(r'ABORTING region server ([^\s]+): For testing!')
DST_RE = re.compile(r'Adding [^\n]+ move to ([^\s]+) record at close')


def address(server_name):
    # ServerName is host,port,startcode; the RPC probe logs host:port.
    fields = server_name.split(',')
    return fields[0] + ':' + fields[1] if len(fields) >= 2 else None


def read_trace(name):
    text = (HERE / 'logs' / (name + '.log')).read_text(errors='replace')
    source = SRC_RE.findall(text)
    destination = DST_RE.findall(text)
    events = {}
    for selector, peer in IO_RE.findall(text):
        events.setdefault(selector, []).append(peer)
    return {'source': address(source[0]) if source else None,
            'destination': address(destination[0]) if destination else None,
            'events': events}


def role(selector, peer, trace):
    if not selector.startswith('RPC_'):
        return 'LOCAL' if peer == 'local' else None
    if 'RegionServerStatusService.' in selector:
        return 'MASTER'
    if peer == trace['source']:
        return 'SOURCE_RS'
    if peer == trace['destination']:
        return 'MOVE_DEST_RS'
    if trace['source'] and trace['destination'] and peer:
        return 'THIRD_RS'
    return None


def audit(state):
    traces = {'seed': read_trace('seed')}
    by_plan = {}
    for trial in state['trials']:
        traces[trial['id']] = read_trace(trial['id'])
        by_plan[tuple(trial['plan'])] = trial['id']
    rows = []
    for trial in state['trials']:
        child = traces[trial['id']]
        steps = []
        for index, fault in enumerate(trial['plan']):
            selector = fault.rsplit('~', 1)[0]
            parent_id = 'seed' if index == 0 else by_plan.get(tuple(trial['plan'][:index]))
            parent = traces.get(parent_id)
            parent_peers = parent['events'].get(selector, []) if parent else []
            child_peers = child['events'].get(selector, [])
            expected_role = role(selector, parent_peers[0], parent) if len(parent_peers) == 1 else None
            observed_role = role(selector, child_peers[0], child) if len(child_peers) == 1 else None
            steps.append({'step': index + 1, 'selector': selector,
                          'parent_id': parent_id,
                          'parent_peers': parent_peers,
                          'child_peers': child_peers,
                          'expected_role': expected_role,
                          'observed_role': observed_role,
                          'role_proven': bool(expected_role and observed_role
                                              and expected_role == observed_role)})
        full = bool(trial['strict'] and trial['target_after_final_fault'])
        rows.append({'id': trial['id'], 'legacy_strict': trial['strict'],
                     'legacy_target_after_fault': trial['target_after_final_fault'],
                     'actor_proven_effective': full and all(s['role_proven'] for s in steps),
                     'steps': steps})
    return rows


def main():
    state = json.loads((HERE / 'checkpoint.json').read_text())
    rows = audit(state)
    eligible = [row for row in rows if row['legacy_strict'] and row['legacy_target_after_fault']]
    proven = [row for row in eligible if row['actor_proven_effective']]
    print(f'legacy attempts={len(rows)} target-retaining={len(eligible)} role-proven={len(proven)}')
    for row in eligible:
        if not row['actor_proven_effective']:
            mismatches = [f"{s['step']}:{s['expected_role']}->{s['observed_role']}"
                          for s in row['steps'] if not s['role_proven']]
            print(row['id'], ','.join(mismatches))
    print('role-proven ids:', ','.join(row['id'] for row in proven))
    (HERE / 'legacy_actor_audit.json').write_text(json.dumps({
        'state_trials': len(rows),
        'legacy_target_retaining': len(eligible),
        'actor_proven_target_retaining': len(proven),
        'criteria': 'Every fault step must match the same original-parent-trace logical endpoint role; role labels from TestReportRegionStateTransitionFromDeadServer original move/abort logs.',
        'rows': rows
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
