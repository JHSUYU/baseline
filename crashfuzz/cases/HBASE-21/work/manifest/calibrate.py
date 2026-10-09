#!/usr/bin/env python3
"""Small, separate calibration of real snapshot-manifest DFS.open faults."""
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
RUN = HERE / 'run.sh'
LOGS = HERE / 'logs'
RESULT = HERE / 'result.json'
MAX_FAULT_TRIALS = 2


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)


def run(name, plan=''):
    LOGS.mkdir(parents=True, exist_ok=True)
    logfile = LOGS / (name + '.log')
    with logfile.open('w') as output:
        process = subprocess.run(['bash', str(RUN), 'run', name, plan],
                                 stdout=output, stderr=subprocess.STDOUT, check=False)
    (LOGS / (name + '.exit')).write_text(str(process.returncode) + '\n')
    return parse(logfile, process.returncode)


def parse(path, exit_code):
    events, matched, applied, guards, target_exits = [], [], [], [], []
    junit = None
    elapsed = None
    for index, line in enumerate(path.read_text(errors='replace').splitlines()):
        io = re.search(r'HBASE21 MANIFEST_IO seq=(\d+) selector=(\S+)', line)
        if io:
            events.append({'line': index, 'seq': int(io.group(1)), 'selector': io.group(2)})
        if 'HBASE21 MANIFEST_FAULT_MATCHED ' in line:
            matched.append(index)
        if 'HBASE21 MANIFEST_FAULT_APPLIED ' in line:
            applied.append(index)
        if 'HBASE21 REGION_GUARD ' in line:
            guards.append(index)
        if 'HBASE21 TARGET_EXIT ' in line:
            target_exits.append({'line': index,
                                 'region_quota': 'outcome=region_quota' in line,
                                 'text': line.strip()})
        match = re.search(r'HBASE21 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', line)
        if match:
            junit = {'found': int(match.group(1)), 'succeeded': int(match.group(2)),
                     'failed': int(match.group(3))}
        match = re.search(r'ELAPSED_SECONDS=([\d.]+)', line)
        if match:
            elapsed = float(match.group(1))
    return {'log': str(path.relative_to(HERE)), 'exit_code': exit_code,
            'elapsed_seconds': elapsed, 'io_events': events,
            'matched': len(matched), 'applied': len(applied),
            'last_applied_line': applied[-1] if applied else None,
            'guard_lines': guards, 'target_exits': target_exits, 'junit': junit}


def main():
    subprocess.run(['bash', str(RUN), 'build'], check=True)
    previous = json.loads(RESULT.read_text()) if RESULT.exists() else {}
    healthy = previous.get('healthy')
    if not healthy or not (HERE / healthy['log']).exists():
        healthy = run('healthy')
    result = {'case_id': 'HBASE-21', 'phase': 'manifest_dfs_open_supplement',
              'methodology': 'case_local_runtime_dfs_open_no_graph',
              'original_junit': 'TestNamespaceAuditor.testRestoreSnapshotQuotaExceed',
              'main_campaign_budget_counted': False, 'healthy': healthy,
              'healthy_reused_from_first_calibration': bool(previous.get('healthy')),
              'abandoned_calibration_trial': {
                  'id': 'm001', 'log': 'logs/m001.preempted_tmp_snapshot.log',
                  'reason': 'The initial picker selected a temporary snapshot-creation '
                            'manifest before the restore manifest. Stopped before '
                            'completion; not counted as a fault trial.'},
              'fault_trials': [], 'status': 'running'}
    atomic_json(RESULT, result)
    first_guard = min(healthy['guard_lines'], default=None)
    if healthy['exit_code'] != 0 or healthy['junit'] != {'found': 1, 'succeeded': 1, 'failed': 0} \
            or first_guard is None:
        result['status'] = 'healthy_failed_or_target_not_reached'
        atomic_json(RESULT, result)
        return
    selectors = list(dict.fromkeys(event['selector'] for event in healthy['io_events']
                                   if event['line'] < first_guard
                                   and event['selector'].startswith(
                                       'DFS_OPEN~snapshot_testRestoreSnapshotQuotaExceed/'
                                       'data.manifest~')))
    result['candidate_selectors'] = selectors
    atomic_json(RESULT, result)
    if not selectors:
        result['status'] = 'manifest_open_not_observed_before_target'
        atomic_json(RESULT, result)
        return
    for number, selector in enumerate(selectors[:MAX_FAULT_TRIALS], 1):
        name = 'm%03d' % (number + 2)
        trace = run(name, selector + '~IOEXCEPTION')
        last_fault = trace['last_applied_line']
        strict = trace['matched'] == 1 and trace['applied'] == 1
        target_after = strict and any(x > last_fault for x in trace['guard_lines'])
        expected_target = target_after and any(
            x['line'] > last_fault and x['region_quota'] for x in trace['target_exits'])
        result['fault_trials'].append({
            'id': name, 'selector': selector, 'strict': strict,
            'matched': trace['matched'], 'applied': trace['applied'],
            'target_after_fault': target_after,
            'expected_target_exception_after_fault': expected_target,
            'junit': trace['junit'], 'junit_exit': trace['exit_code'],
            'elapsed_seconds': trace['elapsed_seconds'], 'log': trace['log'],
            'disposition': 'unmatched' if not strict else
                           'target_lost_excluded' if not target_after else
                           'target_retained_source_review_needed'})
        atomic_json(RESULT, result)
    result['status'] = 'calibration_complete_pending_source_review'
    result['total_elapsed_seconds'] = healthy['elapsed_seconds'] + sum(
        x['elapsed_seconds'] or 0 for x in result['fault_trials'])
    atomic_json(RESULT, result)


if __name__ == '__main__':
    main()
