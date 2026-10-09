#!/usr/bin/env python3
"""Re-read every ZK04 V2 original-JUnit raw trace against its checkpoint row."""

import csv
import hashlib
import json
from pathlib import Path
import sys

from audit_calibration import CHECK, RUNS, one as audit_seed
from calibrate_healthy import AGENT, ROOT, sha

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from receipt_validator import ReceiptError, parse_events, validate_rows

CASE = Path(__file__).resolve().parent
CHECKPOINT = ROOT / 'v2-campaign.json'
TARGET = {'check': CHECK, 'actor': 'peer-role:follower2',
          'role': 'follower2', 'peer': '*', 'session_tag': 'revalidateSession'}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owner_proven(rows, target_seq):
    target = next((fields for seq, kind, fields in rows
                   if seq == target_seq and kind == 'TARGET_GUARD'), None)
    if target is None or len(target) < 7:
        return False
    roles = [fields for _, kind, fields in rows if kind == 'ROLE_BIND']
    sessions = [fields for _, kind, fields in rows if kind == 'SESSION_BIND']
    if len(roles) != 1 or len(sessions) != 1 or roles[0][1] != target[3]:
        return False
    owner = next(((seq, fields) for seq, kind, fields in reversed(rows)
                  if kind == 'TARGET_OWNER_BIND' and 0 < target_seq - seq <= 12
                  and len(fields) >= 6 and fields[-1] == target[-1]), None)
    if owner is None or owner[1][0] != target[3] or owner[1][1] != sessions[0][0] \
            or owner[1][3] != target[1]:
        return False
    port = owner[1][2]
    return any(kind == 'CHANNEL_BIND' and seq < owner[0] and len(fields) >= 4
               and fields[0] == port and fields[1] == target[3]
               for seq, kind, fields in rows)


def one(item, calibration_sha):
    dest = ROOT / item['run_id']
    errors = []
    paths = {name: dest / name for name in ('run.json', 'events.tsv',
                                          'coverage.tsv', 'junit.log')}
    if any(not path.is_file() for path in paths.values()):
        return {'run_id': item['run_id'], 'status': 'fail',
                'errors': ['missing original raw evidence']}
    receipt = json.loads(paths['run.json'].read_text())
    rows = parse_events(paths['events.tsv'])
    if receipt['plan'] != item['plan'] or receipt['exit_code'] != item['junit_exit'] \
            or receipt['elapsed_seconds'] != item['elapsed_seconds']:
        errors.append('run receipt differs from checkpoint plan/JUnit/time')
    if receipt['agent_sha256'] != calibration_sha or calibration_sha != sha(AGENT):
        errors.append('agent JAR provenance differs from healthy and trial receipts')
    try:
        strict = validate_rows(rows, {'plan': item['plan'],
                                      'fault_relations': item['relations'],
                                      'target': TARGET})
    except (ReceiptError, ValueError, IndexError):
        strict = None
    proven = strict is not None and owner_proven(rows, strict['target_sequence'])
    if proven != item['effective']:
        errors.append('effective denominator differs from raw actor/target receipt')
    if proven and item['strict_receipt'] != strict:
        errors.append('stored strict sequence differs from raw events')
    last_fault = max((seq for seq, kind, _ in rows if kind == 'FAULT_APPLIED'), default=0)
    throws = [fields for seq, kind, fields in rows if seq > last_fault
              and kind == 'TARGET_THROW' and len(fields) >= 6
              and fields[0] == CHECK and fields[1] == 'peer-role:follower2'
              and fields[2] == 'follower2' and fields[4] == 'revalidateSession']
    if len(throws) != item['selected_target_throw_count']:
        errors.append('selected target throw count differs from raw events')
    return {'run_id': item['run_id'], 'status': 'pass' if not errors else 'fail',
            'errors': errors, 'junit_exit': receipt['exit_code'],
            'elapsed_seconds': receipt['elapsed_seconds'],
            'fault_depth': len(item['plan']), 'effective': proven,
            'selected_target_throw_count': len(throws),
            'events_sha256': file_hash(paths['events.tsv']),
            'coverage_sha256': file_hash(paths['coverage.tsv']),
            'junit_log_sha256': file_hash(paths['junit.log'])}


def main():
    if not CHECKPOINT.is_file():
        raise SystemExit('campaign not prepared')
    state = json.loads(CHECKPOINT.read_text())
    seeds = [audit_seed(run_id) for run_id in RUNS]
    if any(seed['status'] != 'pass' for seed in seeds):
        raise SystemExit('final two original-JUnit healthy seeds failed audit')
    calibration_sha = json.loads((ROOT / RUNS[0] / 'run.json').read_text())['agent_sha256']
    trials = [one(item, calibration_sha) for item in state['results']]
    errors = []
    if len({trial['run_id'] for trial in trials}) != len(trials):
        errors.append('duplicate trial ID')
    if sum(trial['effective'] for trial in trials) != state['effective_count']:
        errors.append('checkpoint effective count differs from raw re-audit')
    if any(trial['status'] != 'pass' for trial in trials):
        errors.append('one or more raw trial receipts failed')
    report = {'case_id': 'ZOOKEEPER-04',
              'status': 'pass' if not errors else 'fail',
              'campaign_status': state['status'],
              'healthy_runs': list(RUNS), 'agent_sha256': calibration_sha,
              'attempts': len(trials), 'effective_count': state['effective_count'],
              'selected_target_throw_trials': sum(bool(trial['selected_target_throw_count'])
                                                   for trial in trials),
              'elapsed_seconds_sum': round(sum(trial['elapsed_seconds'] for trial in trials), 3),
              'errors': errors, 'trials': trials}
    (CASE / 'trial-raw-audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    with (CASE / 'trial-summary.csv').open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=['run_id', 'elapsed_seconds', 'junit_exit',
                                                    'fault_depth', 'effective',
                                                    'selected_target_throw_count', 'status'])
        writer.writeheader()
        for trial in trials:
            writer.writerow({key: trial[key] for key in writer.fieldnames})
    print(json.dumps({key: value for key, value in report.items() if key != 'trials'},
                     sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
