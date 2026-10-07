#!/usr/bin/env python3
"""Check actor, server, and raw-session joins in two fresh ZK01 healthy receipts."""

import json
from pathlib import Path

ROOT = Path('/users/ZhenyuLi/zk01-actor-v2-runs')
ROLES = {'creatorCloser', 'verifier'}
CHECK = 'SessionTrackerImpl#checkSession:316:isClosing'


def events(path):
    result = []
    for line in path.read_text().splitlines():
        cells = line.split('\t')
        if len(cells) < 3:
            raise ValueError('malformed event line: ' + line)
        result.append((cells[1], cells[2:-1], cells[-1]))
    return result


def one(run_id):
    dest = ROOT / run_id
    if not (dest / 'run.json').exists() or not (dest / 'events.tsv').exists():
        return {'run_id': run_id, 'status': 'pending'}
    receipt = json.loads((dest / 'run.json').read_text())
    rows = events(dest / 'events.tsv')
    errors = []
    if receipt.get('exit_code') != 0 or receipt.get('plan') != []:
        errors.append('original healthy JUnit did not finish cleanly with empty plan')
    selected = [fields for kind, fields, _ in rows if kind == 'SELECTED_LEADER']
    if len(selected) != 1:
        errors.append('expected exactly one selected leader')
        slot, leader = '', ''
    else:
        slot, leader = selected[0][:2]
    peer_rows = [fields for kind, fields, _ in rows if kind == 'PEER_BIND']
    peers = {fields[0]: fields[1] for fields in peer_rows}
    ports = {fields[2]: fields[1] for fields in peer_rows}
    if len(peers) != 3 or len(ports) != 3 or peers.get(slot) != leader:
        errors.append('selected leader is not one of three distinct peer/port joins')
    clients = [fields for kind, fields, _ in rows if kind == 'CLIENT_BIND']
    if {fields[0] for fields in clients} != ROLES or any(fields[1] != slot for fields in clients):
        errors.append('both client roles must bind to selected leader slot')
    sessions = [fields for kind, fields, _ in rows if kind == 'SESSION_BIND']
    raw_to_role = {fields[0]: fields[1] for fields in sessions}
    if {fields[1] for fields in sessions} != ROLES or len(raw_to_role) != len(sessions):
        errors.append('each client role needs one distinct raw session binding')
    if any(fields[2] != leader for fields in sessions):
        errors.append('raw session bound under a different selected leader')
    io = [fields for kind, fields, _ in rows if kind == 'IO']
    client_keys = set()
    for fields in io:
        if len(fields) < 7:
            errors.append('short bound IO event')
            continue
        site, actor, resource, ordinal, local_peer, remote_peer, tag = fields[:7]
        if actor.startswith('client:'):
            if remote_peer != leader or not resource.startswith('peer-role:leader:channel:'):
                errors.append('bound client socket does not lead to selected leader')
            client_keys.add('@@'.join((site, actor, resource)))
        elif actor.startswith('peer-role:leader:'):
            if local_peer != leader:
                errors.append('server I/O local peer differs from selected leader')
    if not any(':creatorCloser:' in key for key in client_keys):
        errors.append('creatorCloser has no bound socket I/O')
    if not any(':verifier:' in key for key in client_keys):
        errors.append('verifier has no bound socket I/O')
    guards = [fields for kind, fields, _ in rows
              if kind == 'TARGET_GUARD' and fields[0] == CHECK]
    if not any(len(fields) >= 6 and fields[1] == 'peer-role:leader'
               and fields[2] == 'leader' and fields[3] == leader
               and fields[4] == 'creatorCloser' for fields in guards):
        errors.append('selected target guard lacks leader/creatorCloser session join')
    throws = [fields for kind, fields, _ in rows if kind == 'TARGET_THROW']
    if throws:
        errors.append('healthy run unexpectedly throws selected target exception')
    if not (dest / 'coverage.tsv').exists() or not (dest / 'coverage.tsv').read_text().strip():
        errors.append('no production line coverage')
    return {'run_id': run_id, 'status': 'pass' if not errors else 'fail',
            'errors': errors, 'selected_leader_sid': leader, 'selected_slot': slot,
            'peer_slot_to_sid': peers, 'port_to_sid': ports, 'raw_session_to_role': raw_to_role,
            'bound_io_events': len(io), 'selected_guard_events': len(guards),
            'stable_client_families': sorted(client_keys)}


def main():
    runs = [one('healthy-a'), one('healthy-b')]
    both = all(run['status'] == 'pass' for run in runs)
    common = sorted(set(runs[0].get('stable_client_families', ()))
                    & set(runs[1].get('stable_client_families', ()))) if both else []
    errors = []
    if both and not any(':creatorCloser:' in key for key in common):
        errors.append('creatorCloser has no stable actor/resource/site across runs')
    if both and not any(':verifier:' in key for key in common):
        errors.append('verifier has no stable actor/resource/site across runs')
    if both:
        a = json.loads((ROOT / 'healthy-a/run.json').read_text())
        b = json.loads((ROOT / 'healthy-b/run.json').read_text())
        for field in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                      'classpath_sha256', 'original_source_commit'):
            if a.get(field) != b.get(field):
                errors.append(field + ' differs between healthy calibrations')
    status = 'pending' if any(run['status'] == 'pending' for run in runs) else (
        'pass' if both and not errors else 'fail')
    summary = {'status': status, 'runs': runs, 'common_client_families': common,
               'cross_run_errors': errors}
    print(json.dumps(summary, indent=2, sort_keys=True))
    if status == 'fail':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
