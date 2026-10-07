#!/usr/bin/env python3
"""Audit two unchanged JUnit seeds for peer 1 and the first global session."""

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get('ZK13_RUN_ROOT', '/users/ZhenyuLi/zk13-actor-v2-runs'))
CHECK = 'ReadOnlyZooKeeperServer#validateSession:123:isGlobalSession'


def events(path):
    rows = []
    for line in path.read_text().splitlines():
        fields = line.split('\t')
        if len(fields) < 3:
            raise ValueError('short event: ' + line)
        rows.append((int(fields[0]), fields[1], fields[2:-1]))
    return rows


def one(run_id):
    path = ROOT / run_id
    if not (path / 'run.json').is_file() or not (path / 'events.tsv').is_file():
        return {'run_id': run_id, 'status': 'pending'}
    receipt = json.loads((path / 'run.json').read_text())
    rows = events(path / 'events.tsv')
    errors = []
    if receipt.get('exit_code') != 0 or receipt.get('plan') != []:
        errors.append('original JUnit did not pass with empty fault plan')
    peers = [(seq, fields) for seq, kind, fields in rows if kind == 'PEER_BIND']
    if len(peers) != 3 or {x[1][0] for x in peers} != {'1', '2', '3'}:
        errors.append('three original QuorumUtil receiver/SID joins absent')
    clients = [(seq, fields) for seq, kind, fields in rows if kind == 'CLIENT_BIND']
    if len(clients) != 1 or clients[0][1][0] != 'initialGlobalClient':
        errors.append('first ZooKeeper receiver not uniquely registered')
    sessions = [(seq, fields) for seq, kind, fields in rows if kind == 'SESSION_BIND']
    if len(sessions) != 1 or len(sessions[0][1]) < 3 or \
            sessions[0][1][1:] != ['initialGlobalClient', 'initialGlobalSession']:
        errors.append('first connected raw global session not uniquely bound')
    raw = sessions[0][1][0] if len(sessions) == 1 else ''
    phases = [(seq, fields) for seq, kind, fields in rows if kind == 'RO_PHASE']
    if len(phases) != 1 or phases[0][1] != ['peer:1', raw]:
        errors.append('peer-2 shutdown/read-only phase not bound to first session')
    phase_seq = phases[0][0] if phases else 0
    guards = [(seq, fields) for seq, kind, fields in rows
              if kind == 'TARGET_GUARD' and fields and fields[0] == CHECK]
    throws = [(seq, fields) for seq, kind, fields in rows
              if kind == 'TARGET_THROW' and fields and fields[0] == CHECK]
    if not guards or len(guards) != len(throws):
        errors.append('selected global-session guard/expected throw counts differ')
    expected_guard = [CHECK, 'peer:1', 'readOnlyPeer1', '1',
                      'initialGlobalSession', 'global']
    expected_throw = [CHECK, 'peer:1', 'readOnlyPeer1', '1',
                      'initialGlobalSession',
                      'org.apache.zookeeper.server.ServerCnxn$CloseRequestException']
    if any(seq <= phase_seq or fields != expected_guard for seq, fields in guards):
        errors.append('selected guard is not the first global session on peer-1 RO server')
    if any(seq <= phase_seq or fields != expected_throw for seq, fields in throws):
        errors.append('expected RO exception lacks selected actor/session identity')
    if any(tseq <= gseq for (gseq, _), (tseq, _) in zip(guards, throws)):
        errors.append('selected throw did not follow its guard')
    bound_io = [(seq, fields) for seq, kind, fields in rows
                if kind == 'IO' and seq > phase_seq]
    eligible = []
    for seq, fields in bound_io:
        if len(fields) < 7:
            errors.append('short bound I/O event')
            continue
        site, actor, resource, _, local, remote, tag = fields[:7]
        if tag != 'initialGlobalSession':
            errors.append('another client or session became bound I/O')
        if actor.startswith('client:') and (actor !=
                'client:initialGlobalClient:session:initialGlobalSession'
                or remote not in ('1', '2') or not resource.startswith('peer:' + remote + ':')):
            errors.append('client receiver/destination or session mismatch')
        if actor.startswith('peer:') and (actor != 'peer:1:session:initialGlobalSession'
                                          or local != '1'):
            errors.append('server receiver is not RO peer 1')
        if (actor.startswith('client:') and remote == '1') or \
                actor == 'peer:1:session:initialGlobalSession':
            eligible.append('@@'.join(fields[:3]))
    if len(set(eligible)) < 2:
        errors.append('fewer than two bound peer-1/global-session I/O families')
    if any(kind == 'FAULT_APPLIED' for _, kind, _ in rows):
        errors.append('healthy run applied a fault')
    if not (path / 'coverage.tsv').is_file() or not (path / 'coverage.tsv').read_text().strip():
        errors.append('no production line coverage')
    return {'run_id': run_id, 'status': 'pass' if not errors else 'fail',
            'errors': errors, 'raw_session_id': raw, 'ro_phase_sequence': phase_seq,
            'selected_guard_count': len(guards), 'expected_throw_count': len(throws),
            'eligible_io_families': sorted(set(eligible)),
            'eligible_io_events': len(eligible),
            'elapsed_seconds': receipt.get('elapsed_seconds')}


def main():
    seeds = [one('healthy-a'), one('healthy-b')]
    errors = []
    if all(x['status'] == 'pass' for x in seeds):
        receipts = [json.loads((ROOT / x / 'run.json').read_text())
                    for x in ('healthy-a', 'healthy-b')]
        for field in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                      'classpath_sha256', 'original_source_commit'):
            if receipts[0].get(field) != receipts[1].get(field):
                errors.append(field + ' changed between fresh healthy runs')
        shared = set(seeds[0]['eligible_io_families']) & set(seeds[1]['eligible_io_families'])
        if len(shared) < 2:
            errors.append('peer-1/global-session I/O families unstable across runs')
    else:
        shared = set()
    status = ('pending' if any(x['status'] == 'pending' for x in seeds)
              else 'pass' if not errors and all(x['status'] == 'pass' for x in seeds)
              else 'fail')
    print(json.dumps({'status': status, 'runs': seeds,
                      'shared_eligible_families': sorted(shared),
                      'cross_run_errors': errors}, sort_keys=True, indent=2))
    if status == 'fail':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
