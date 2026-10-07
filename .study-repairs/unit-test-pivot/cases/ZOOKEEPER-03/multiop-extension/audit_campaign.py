#!/usr/bin/env python3
"""Recompute MultiOp formal-stage receipts from immutable raw archives."""

import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
PILOT = HERE / 'evidence/raw-pilot.tar.gz'
CAMPAIGN = HERE / 'evidence/raw-campaign.tar.gz'
CHECK = 'SessionTrackerImpl#setOwner:329:missingOrClosing'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    with tarfile.open(PILOT, 'r:gz') as old, tarfile.open(CAMPAIGN, 'r:gz') as new:
        def read(archive, name):
            member = archive.extractfile(name)
            if member is None:
                raise RuntimeError('missing raw member ' + name)
            return member.read()

        pilot = json.loads(read(old, 'pilot-checkpoint.json'))
        stage = json.loads(read(new, 'campaign/checkpoint.json'))
        before = json.loads(read(new, 'pre-first-checkpoint.json'))
        if pilot['status'] != 'pilot_complete' or len(pilot['results']) != 10 \
                or stage['status'] != 'queue_exhausted' or stage['pending'] \
                or stage['inflight'] or len(stage['results']) != 26 \
                or before['status'] != 'pilot_complete' or len(before['results']) != 4:
            raise RuntimeError('unexpected stage/pilot checkpoint terminal state')
        covered = set()
        for name in ('healthy-a', 'healthy-b'):
            covered.update(read(old, name + '/coverage.tsv').decode().splitlines())
        for item in pilot['results']:
            if item['effective']:
                covered.update(read(old, item['run_id'] + '/coverage.tsv').decode().splitlines())
        audit_rows = []
        for item in stage['results'] + before['results']:
            archive = new
            run_id = item['run_id']
            receipt_bytes = read(archive, run_id + '/run.json')
            event_bytes = read(archive, run_id + '/events.tsv')
            coverage_bytes = read(archive, run_id + '/coverage.tsv')
            receipt = json.loads(receipt_bytes)
            rows = []
            for line in event_bytes.decode().splitlines():
                cells = line.split('\t')
                rows.append((int(cells[0]), cells[1], cells[2:-1]))
            rows.sort()
            raw = {f[0] for _, k, f in rows if k == 'SESSION_BIND'
                   and len(f) >= 3 and f[2] == 'movedSession'}
            leaders = [f[0] for _, k, f in rows if k == 'LEADER_BIND']
            matched = [(s, f) for s, k, f in rows if k == 'FAULT_MATCHED']
            applied = [(s, f) for s, k, f in rows if k == 'FAULT_APPLIED']
            exact = ['@@'.join(f[:4]) for _, f in matched] == receipt['plan'] \
                    and ['@@'.join(f[:4]) for _, f in applied] == receipt['plan'] \
                    and len(applied) == len(receipt['plan']) \
                    and all(m[0] < a[0] for m, a in zip(matched, applied))
            if exact != item['exact'] or receipt['plan'] != item['plan'] or len(leaders) != 1:
                raise RuntimeError(run_id + ' ordered identity plan differs')
            last = applied[-1][0] if applied else 0
            guards = [(s, f) for s, k, f in rows if s > last and k == 'TARGET_GUARD'
                      and len(f) >= 6 and f[:5] ==
                      [CHECK, 'peer:' + leaders[0], 'leader', leaders[0], 'movedSession']]
            owners = [(s, f) for s, k, f in rows if s > last and k == 'OWNER_BIND'
                      and len(f) >= 4 and len(raw) == 1
                      and f[:2] == [leaders[0], next(iter(raw))]
                      and f[2].startswith(('local:', 'forwarder:'))]
            effective = exact and any(last < os < gs for gs, _ in guards for os, _ in owners)
            throws = [(s, f) for s, k, f in rows if s > last and k == 'TARGET_THROW'
                      and len(f) >= 6 and f[:5] ==
                      [CHECK, 'peer:' + leaders[0], 'leader', leaders[0], 'movedSession']]
            coverage = set(coverage_bytes.decode().splitlines())
            gain = len(coverage - covered) if effective else 0
            if effective:
                covered.update(coverage)
            if effective != item['effective'] or gain != item['new_coverage_lines'] \
                    or len(throws) != item['selected_target_throws'] \
                    or sha(event_bytes) != item['events_sha256'] \
                    or sha(receipt_bytes) != item['receipt_sha256'] \
                    or sha(coverage_bytes) != item['coverage_sha256']:
                raise RuntimeError(run_id + ' independent raw audit mismatch')
            audit_rows.append({'run_id': run_id, 'exact': exact, 'effective': effective,
                               'target_after_fault': bool(guards),
                               'owner_after_fault': bool(owners),
                               'selected_target_throws': len(throws),
                               'new_coverage_lines': gain,
                               'elapsed_seconds': receipt['elapsed_seconds'],
                               'junit_exit': receipt['exit_code'],
                               'fault_count': len(receipt['plan'])})
        formal = audit_rows[:len(stage['results'])]
        pre_first = audit_rows[len(stage['results']):]
        total = sum(x['effective'] for x in pilot['results']) + \
                sum(x['effective'] for x in formal)
        if total != stage['effective_count']:
            raise RuntimeError('effective denominator differs from raw runs')
        if any(x['effective'] for x in pre_first):
            raise RuntimeError('pre-first pilot unexpectedly retained selected target')
        result = {'status': 'queue_exhausted_before_80',
                  'pilot_selected': len(pilot['results']),
                  'pilot_effective': sum(x['effective'] for x in pilot['results']),
                  'formal_selected': len(formal),
                  'formal_effective': sum(x['effective'] for x in formal),
                  'new_stage_selected': len(pilot['results']) + len(formal),
                  'new_stage_effective': total,
                  'effective_budget': stage['budget_effective'],
                  'max_faults': stage['max_faults'],
                  'max_observed_faults': max(x['fault_count'] for x in formal),
                  'pre_first_selected': len(pre_first),
                  'pre_first_effective': 0,
                  'selected_target_throws': sum(x['selected_target_throws'] for x in audit_rows),
                  'formal_coverage_gain': sum(x['new_coverage_lines'] for x in formal),
                  'pilot_coverage_gain': sum(x['new_coverage_lines'] for x in pilot['results']),
                  'formal_trial_seconds': round(sum(x['elapsed_seconds'] for x in formal), 3),
                  'pre_first_trial_seconds': round(sum(x['elapsed_seconds'] for x in pre_first), 3),
                  'pilot_trial_seconds': round(sum(x['elapsed_seconds'] for x in pilot['results']), 3),
                  'raw_campaign_sha256': sha(CAMPAIGN.read_bytes()),
                  'raw_pilot_sha256': sha(PILOT.read_bytes()),
                  'runs': audit_rows}
        out = HERE / 'evidence/campaign-independent-audit.json'
        out.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
        print(json.dumps({k: result[k] for k in ('status', 'new_stage_selected',
              'new_stage_effective', 'pre_first_selected', 'pre_first_effective',
              'selected_target_throws')}, sort_keys=True))


if __name__ == '__main__':
    main()
