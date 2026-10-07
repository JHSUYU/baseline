#!/usr/bin/env python3
"""Audit two original JUnit seeds for follower2 revalidation, not any peer's guard."""

import json
from pathlib import Path

from calibrate_healthy import AGENT, ROOT, sha

CHECK = 'ZooKeeperServer#processConnectRequest:1431:CLIENT_ZXID_AHEAD'
RUNS = ('healthy-final-a', 'healthy-final-b')


def events(path):
    rows = []
    for line in path.read_text().splitlines():
        cells = line.split('\t')
        if len(cells) < 3:
            raise ValueError('malformed event: ' + line)
        rows.append((int(cells[0]), cells[1], cells[2:-1]))
    return rows


def one(run_id):
    dest = ROOT / run_id
    if not (dest / 'run.json').is_file() or not (dest / 'events.tsv').is_file():
        return {'run_id': run_id, 'status': 'pending'}
    receipt = json.loads((dest / 'run.json').read_text())
    rows = events(dest / 'events.tsv')
    errors = []
    if receipt.get('exit_code') != 0 or receipt.get('plan') != []:
        errors.append('original healthy JUnit did not pass with empty plan')
    if receipt.get('agent_sha256') != sha(AGENT):
        errors.append('active agent JAR differs from healthy receipt')
    if any(kind == 'BINDING_ERROR' for _, kind, _ in rows):
        errors.append('runtime receiver mapping reported a binding error')
    peers = [fields for _, kind, fields in rows if kind == 'PEER_BIND']
    ports = {fields[0]: int(fields[1]) for fields in peers}
    if len(peers) != 3 or set(ports) != {'1', '2', '3'} or len(set(ports.values())) != 3:
        errors.append('three actual peer receivers/SIDs/ports not uniquely bound')
    roles = [fields for _, kind, fields in rows if kind == 'ROLE_BIND']
    if len(roles) != 1 or roles[0][0] == roles[0][1] \
            or roles[0][0] not in ports or roles[0][1] not in ports:
        errors.append('distinct follower1 and follower2 roles not bound')
    first, second = roles[0][:2] if roles else ('', '')
    binds = [fields for _, kind, fields in rows if kind == 'SESSION_BIND']
    if len(binds) != 1 or binds[0][1] != 'revalidate-client' or int(binds[0][0]) == 0:
        errors.append('original ZooKeeper client raw session not uniquely bound')
    raw = binds[0][0] if len(binds) == 1 else ''
    guards = [(seq, fields) for seq, kind, fields in rows if kind == 'TARGET_GUARD']
    if len(guards) != 1 or guards[0][1][:6] != [CHECK, 'peer-role:follower2',
                                                 'follower2', second,
                                                 'revalidateSession', 'normal']:
        errors.append('one selected follower2 same-session normal-arm guard not proven')
    owners = [(seq, fields) for seq, kind, fields in rows if kind == 'TARGET_OWNER_BIND']
    if len(owners) != 1 or owners[0][1][:2] != [second, raw] \
            or owners[0][1][3] != 'peer-role:follower2' \
            or owners[0][0] >= (guards[0][0] if guards else 0):
        errors.append('guard lacks immediate raw-session/peer/server receiver receipt')
    source_port = int(owners[0][1][2]) if owners else 0
    channels = [(seq, fields) for seq, kind, fields in rows if kind == 'CHANNEL_BIND'
                and fields[0] == str(source_port) and fields[1] == second]
    if not channels or channels[0][0] >= (owners[0][0] if owners else 0):
        errors.append('server remote source port did not join preceding client channel')
    initial = [(seq, fields) for seq, kind, fields in rows if kind == 'UNBOUND_TARGET']
    if len(initial) != 1 or initial[0][0] >= (guards[0][0] if guards else 0):
        errors.append('initial unselected first-follower connect guard not excluded')
    if any(kind == 'TARGET_THROW' for _, kind, _ in rows):
        errors.append('healthy selected test unexpectedly threw CLIENT_ZXID_AHEAD')
    coverage = (dest / 'coverage.tsv').read_text().splitlines()
    if 'org.apache.zookeeper.server.ZooKeeperServer#processConnectRequest:1431' not in coverage:
        errors.append('target source line lacks actual instrumented production coverage')
    io = [fields for _, kind, fields in rows if kind == 'IO']
    families = sorted({'@@'.join(fields[:3]) for fields in io if len(fields) >= 7
                       and fields[6] == 'revalidateSession'
                       and (fields[5] == second or fields[4] == second)})
    if len(families) < 2:
        errors.append('fewer than two actor-bound target-related I/O families')
    return {'run_id': run_id, 'status': 'pass' if not errors else 'fail',
            'errors': errors, 'follower1_sid': first, 'follower2_sid': second,
            'peer_ports': ports, 'raw_session_id': raw,
            'selected_guard_count': len(guards), 'unselected_initial_guard_count': len(initial),
            'client_ephemeral_port': source_port, 'bound_io_count': len(io),
            'target_related_io_families': families, 'coverage_lines': len(coverage),
            'junit_elapsed_seconds': receipt['elapsed_seconds']}


def main():
    runs = [one(run_id) for run_id in RUNS]
    common = sorted(set(runs[0].get('target_related_io_families', ()))
                    & set(runs[1].get('target_related_io_families', ())))
    errors = []
    if all(run['status'] == 'pass' for run in runs):
        metadata = [json.loads((ROOT / run_id / 'run.json').read_text()) for run_id in RUNS]
        for field in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                      'classpath_sha256', 'original_source_commit'):
            if metadata[0][field] != metadata[1][field]:
                errors.append(field + ' differs across healthy seeds')
        if len(common) < 2:
            errors.append('no stable target-related I/O family overlap')
    status = 'pending' if any(run['status'] == 'pending' for run in runs) else (
        'pass' if all(run['status'] == 'pass' for run in runs) and not errors else 'fail')
    result = {'status': status, 'runs': runs, 'common_families': common,
              'cross_run_errors': errors}
    output = Path(__file__).resolve().parent / 'calibration-audit.json'
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))
    if status == 'fail':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
