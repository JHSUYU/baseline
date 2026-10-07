#!/usr/bin/env python3
"""Independent raw archive audit for the unchanged MultiOp quorum JUnit."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / 'evidence/raw-pilot.tar.gz'
CHECK = 'SessionTrackerImpl#setOwner:329:missingOrClosing'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    out = {'source_test': 'org.apache.zookeeper.test.QuorumTest#testSessionMovedWithMultiOp',
           'old_stages_pooled': False, 'runs': [], 'healthy': []}
    with tarfile.open(ARCHIVE, 'r:gz') as archive:
        def read(path):
            member = archive.extractfile(path)
            if member is None:
                raise RuntimeError('missing ' + path)
            return member.read()
        pilot = json.loads(read('pilot-checkpoint.json'))
        if pilot['status'] != 'pilot_complete' or len(pilot['results']) != 10:
            raise RuntimeError('pilot checkpoint not terminal')
        seen = set()
        for name in ('healthy-a', 'healthy-b') + tuple('pilot-{:02d}'.format(i) for i in range(1, 11)):
            receipt_bytes = read(name + '/run.json')
            event_bytes = read(name + '/events.tsv')
            coverage_bytes = read(name + '/coverage.tsv')
            receipt = json.loads(receipt_bytes)
            rows = []
            for line in event_bytes.decode().splitlines():
                cells = line.split('\t')
                rows.append((int(cells[0]), cells[1], cells[2:-1]))
            rows.sort()
            leaders = [f[0] for _, k, f in rows if k == 'LEADER_BIND']
            peers = [f for _, k, f in rows if k == 'PEER_BIND']
            bindings = [(f[0], f[1]) for _, k, f in rows if k == 'SESSION_BIND'
                        and len(f) >= 3 and f[2] == 'movedSession']
            raw = {x[0] for x in bindings}
            guards = [(s, f) for s, k, f in rows if k == 'TARGET_GUARD'
                      and len(f) >= 6 and f[0] == CHECK]
            if len(peers) != 5 or len(leaders) != 1 or len(raw) != 1 \
                    or set(x[1] for x in bindings) != {'handle:0', 'handle:1'}:
                raise RuntimeError(name + ': five-peer or raw-session binding failed')
            leader = leaders[0]
            for _, fields in guards:
                if fields[:5] != [CHECK, 'peer:' + leader, 'leader', leader,
                                  'movedSession']:
                    raise RuntimeError(name + ': wrong target actor/session')
            coverage = set(coverage_bytes.decode().splitlines())
            if name.startswith('healthy'):
                if receipt['exit_code'] or receipt['plan'] or len(guards) != 2 \
                        or any(f[5] != 'present-open' for _, f in guards):
                    raise RuntimeError(name + ': original JUnit calibration failed')
                between = [('@@'.join(f[:4]), f[1], f[6]) for s, k, f in rows
                           if k == 'IO' and len(f) >= 7 and guards[0][0] < s < guards[1][0]
                           and f[6] == 'movedSession']
                out['healthy'].append({'run_id': name, 'elapsed_seconds': receipt['elapsed_seconds'],
                                       'guards': len(guards), 'bound_io_between_guards': len(between),
                                       'raw_session': next(iter(raw)), 'leader': leader,
                                       'events_sha256': sha(event_bytes),
                                       'coverage_sha256': sha(coverage_bytes),
                                       'receipt_sha256': sha(receipt_bytes)})
                seen.update(coverage)
                continue
            matched = [(s, f) for s, k, f in rows if k == 'FAULT_MATCHED']
            applied = [(s, f) for s, k, f in rows if k == 'FAULT_APPLIED']
            exact = ['@@'.join(f[:4]) for _, f in matched] == receipt['plan'] and \
                    ['@@'.join(f[:4]) for _, f in applied] == receipt['plan'] and \
                    len(applied) == 1 and matched[0][0] < applied[0][0]
            if not exact or applied[0][1][6] != 'movedSession' or \
                    'session:movedSession' not in applied[0][1][1]:
                raise RuntimeError(name + ': fault selector/actor/session mismatch')
            last = applied[-1][0]
            later = [(s, f) for s, f in guards if s > last]
            owners = [(s, f) for s, k, f in rows if k == 'OWNER_BIND' and s > last
                      and len(f) >= 4 and f[:2] == [leader, next(iter(raw))]
                      and f[2].startswith(('local:', 'forwarder:'))]
            effective = any(last < os < gs for gs, _ in later for os, _ in owners)
            throws = [(s, f) for s, k, f in rows if k == 'TARGET_THROW' and s > last
                      and len(f) >= 6 and f[:5] ==
                      [CHECK, 'peer:' + leader, 'leader', leader, 'movedSession']]
            gain = len(coverage - seen) if effective else 0
            if effective:
                seen.update(coverage)
            expected = next(x for x in pilot['results'] if x['run_id'] == name)
            if (effective != expected['effective'] or gain != expected['new_coverage_lines']
                    or len(throws) != expected['selected_target_throws']):
                raise RuntimeError(name + ': raw audit/checkpoint discrepancy')
            out['runs'].append({'run_id': name, 'exact': exact, 'effective': effective,
                                'target_after_fault': bool(later), 'owner_after_fault': bool(owners),
                                'selected_target_throws': len(throws), 'new_coverage_lines': gain,
                                'elapsed_seconds': receipt['elapsed_seconds'],
                                'junit_exit': receipt['exit_code'],
                                'plan': receipt['plan'], 'events_sha256': sha(event_bytes),
                                'coverage_sha256': sha(coverage_bytes),
                                'receipt_sha256': sha(receipt_bytes)})
    out['selected_attempts'] = len(out['runs'])
    out['effective'] = sum(x['effective'] for x in out['runs'])
    out['coverage_gain'] = sum(x['new_coverage_lines'] for x in out['runs'])
    out['selected_target_throws'] = sum(x['selected_target_throws'] for x in out['runs'])
    out['elapsed_seconds'] = sum(x['elapsed_seconds'] for x in out['runs']) + \
                             sum(x['elapsed_seconds'] for x in out['healthy'])
    out['raw_archive_sha256'] = sha(ARCHIVE.read_bytes())
    path = HERE / 'evidence/pilot-independent-audit.json'
    path.write_text(json.dumps(out, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: out[k] for k in ('selected_attempts', 'effective',
          'coverage_gain', 'selected_target_throws', 'elapsed_seconds')}, sort_keys=True))


if __name__ == '__main__':
    main()
