#!/usr/bin/env python3
"""Audit two original-JUnit healthy runs for actual moved-session/owner binding."""

import json
from pathlib import Path

ROOT = Path('/users/ZhenyuLi/zk02-actor-v2-runs')
CHECK = 'SessionTrackerImpl#checkSession:322:ownerMismatch'
HANDLES = {'handle:' + str(index) for index in range(11)}


def events(path):
    rows = []
    for line in path.read_text().splitlines():
        cells = line.split('\t')
        if len(cells) < 3:
            raise ValueError('malformed event: ' + line)
        rows.append((cells[1], cells[2:-1], cells[-1]))
    return rows


def one(run_id):
    dest = ROOT / run_id
    if not (dest / 'run.json').is_file() or not (dest / 'events.tsv').is_file():
        return {'run_id': run_id, 'status': 'pending'}
    receipt = json.loads((dest / 'run.json').read_text())
    rows = events(dest / 'events.tsv')
    errors = []
    if receipt.get('exit_code') != 0 or receipt.get('plan') != []:
        errors.append('healthy original JUnit did not finish with an empty fault plan')
    peers = [fields for kind, fields, _ in rows if kind == 'PEER_BIND']
    port_to_sid = {int(fields[1]): fields[0] for fields in peers}
    if len(peers) != 5 or {fields[0] for fields in peers} != {'1', '2', '3', '4', '5'}:
        errors.append('five distinct peer receiver/port joins not proven')
    leaders = [fields[0] for kind, fields, _ in rows if kind == 'LEADER_BIND']
    if len(leaders) != 1 or leaders[0] not in {'1', '2', '3', '4', '5'}:
        errors.append('healthy test did not select exactly one actual leader receiver')
    leader = leaders[0] if len(leaders) == 1 else ''
    handles = [fields for kind, fields, _ in rows if kind == 'HANDLE_BIND']
    handle_to_sid = {fields[0]: fields[1] for fields in handles}
    if {fields[0] for fields in handles} != HANDLES or len(handles) != 11:
        errors.append('initial and ten moved client handles not all bound')
    for index in range(11):
        role = 'handle:' + str(index)
        expected_sid = str(index % 5 + 1)
        if handle_to_sid.get(role) != expected_sid:
            errors.append(role + ' destination peer does not match original test loop')
    bindings = [fields for kind, fields, _ in rows if kind == 'SESSION_BIND']
    raw_ids = {fields[0] for fields in bindings}
    if {fields[1] for fields in bindings} != HANDLES or len(raw_ids) != 1:
        errors.append('all eleven handles must join one raw moved session')
    if any(fields[2] != 'movedSession' for fields in bindings):
        errors.append('a raw session maps to another logical session')
    raw = next(iter(raw_ids), '')
    bound_io = [fields for kind, fields, _ in rows if kind == 'IO']
    client_families = set()
    observed_roles = set()
    for fields in bound_io:
        if len(fields) < 7:
            errors.append('short bound IO event')
            continue
        site, actor, resource, ordinal, local, remote, tag = fields[:7]
        if actor.startswith('client:'):
            role = actor[len('client:'):].split(':session:', 1)[0]
            observed_roles.add(role)
            if (tag != 'movedSession' or remote != handle_to_sid.get(role)
                    or not resource.startswith('peer:' + remote + ':channel:')):
                errors.append('socket actor, raw-session tag, or actual destination mismatch')
            client_families.add('@@'.join((site, actor, resource)))
    if len(observed_roles) < 6 or 'handle:0' not in observed_roles:
        errors.append('too few moved handles have bound socket I/O')
    guards = [fields for kind, fields, _ in rows
              if kind == 'TARGET_GUARD' and fields[0] == CHECK]
    if not guards:
        errors.append('no bound selected owner-mismatch guard')
    for fields in guards:
        if (len(fields) < 6 or fields[1] != 'peer:' + leader or fields[2] != 'leader'
                or fields[3] != leader or fields[4] != 'movedSession'
                or fields[5] != 'same-object'):
            errors.append('target guard did not retain leader/moved-session/same-owner relation')
            break
    owner_rows = [fields for kind, fields, _ in rows if kind == 'OWNER_BIND']
    if len(owner_rows) < len(guards):
        errors.append('selected guards lack actual owner-object binding receipts')
    for fields in owner_rows:
        if (len(fields) < 5 or fields[0] != leader or fields[1] != raw
                or fields[2] != fields[3] or fields[4] != 'same-object'):
            errors.append('current/request owner identity or raw session differs')
            break
    if any(kind == 'TARGET_THROW' for kind, _, _ in rows):
        errors.append('healthy selected test unexpectedly threw SessionMovedException')
    if not (dest / 'coverage.tsv').is_file() or not (dest / 'coverage.tsv').read_text().strip():
        errors.append('no production line coverage')
    return {'run_id': run_id, 'status': 'pass' if not errors else 'fail',
            'errors': errors, 'leader_sid': leader, 'port_to_sid': port_to_sid,
            'handle_to_sid': handle_to_sid, 'raw_session_id': raw,
            'owner_receipts': len(owner_rows), 'selected_guard_events': len(guards),
            'bound_socket_roles': sorted(observed_roles),
            'client_families': sorted(client_families)}


def main():
    runs = [one('healthy-a'), one('healthy-b')]
    both = all(run['status'] == 'pass' for run in runs)
    common = sorted(set(runs[0].get('client_families', ()))
                    & set(runs[1].get('client_families', ()))) if both else []
    errors = []
    if both:
        a = json.loads((ROOT / 'healthy-a/run.json').read_text())
        b = json.loads((ROOT / 'healthy-b/run.json').read_text())
        for field in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                      'classpath_sha256', 'original_source_commit'):
            if a.get(field) != b.get(field):
                errors.append(field + ' differs between healthy runs')
        if len(common) < 2:
            errors.append('fewer than two stable actor/resource/site families across runs')
    status = 'pending' if any(run['status'] == 'pending' for run in runs) else (
        'pass' if both and not errors else 'fail')
    print(json.dumps({'status': status, 'runs': runs, 'common_client_families': common,
                      'cross_run_errors': errors}, indent=2, sort_keys=True))
    if status == 'fail':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
