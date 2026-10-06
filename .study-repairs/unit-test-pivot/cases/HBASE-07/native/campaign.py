#!/usr/bin/env python3
"""Concurrent original-JUnit runs, admitted in order with graph-free feedback."""
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
RUN = HERE / 'run.sh'
DOORS = ('MASTER', 'EXISTS', 'CHECK', 'STATE')
KINDS = ('IOException', 'SocketTimeoutException', 'EOFException', 'ConnectException')


def plan_string(plan):
    hits = {door: 0 for door in DOORS}
    out = []
    for door, kind in plan:
        hits[door] += 1
        out.append('%s:%d:%s' % (door, hits[door], kind))
    return ','.join(out)


def plans():
    for door in DOORS:
        for kind in KINDS:
            yield ((door, kind),)
    for d1, d2 in itertools.combinations(DOORS, 2):
        for kind in KINDS:
            yield ((d1, kind), (d2, kind))
    for door in DOORS:
        for a in range(4):
            yield ((door, KINDS[a]), (door, KINDS[a]))
            yield ((door, KINDS[a]), (door, KINDS[(a + 1) % 4]))
    for kind in KINDS:
        yield tuple((door, kind) for door in DOORS)
        yield tuple((door, kind) for door in DOORS for _ in range(2))


def extension_plans():
    for a, b in itertools.product(KINDS, repeat=2):
        for counts in ((2, 2, 2, 2), (2, 2, 3, 2), (3, 2, 3, 2)):
            kinds = (a, b, a, b)
            if counts == (2, 2, 2, 2) and a == b:
                kinds = (a, b, a, KINDS[(KINDS.index(a) + 1) % 4])
            yield tuple((door, kind) for door, kind, count in zip(
                DOORS, kinds, counts) for _ in range(count))


def coverage(paths):
    p = subprocess.run(['bash', str(RUN), 'coverage', ','.join(map(str, paths))],
                       capture_output=True, text=True)
    if p.returncode:
        return {'error': p.stderr[-1000:]}
    classes, lines = {}, {}
    for line in p.stdout.splitlines():
        m = re.match(r'COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)', line)
        if m:
            classes[m[1].rsplit('/', 1)[-1]] = dict(zip(('methods', 'branches', 'lines'),
                                                        map(int, m.groups()[1:])))
        m = re.match(r'COVERAGE line=(\d+) instructions=(\d+)(?: branches=(\d+))?', line)
        if m:
            lines[m[1]] = {'instructions': int(m[2]), 'branches': int(m[3] or 0)}
    return {'classes': classes, 'target_lines': lines,
            'total_branches': sum(v['branches'] for v in classes.values()),
            'total_methods': sum(v['methods'] for v in classes.values()),
            'total_lines': sum(v['lines'] for v in classes.values())}


def save(data):
    temp = RESULT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(temp, RESULT)


def run_one(name, plan):
    log_path = HERE / (name + '.log')
    exit_path = HERE / (name + '.exit')
    if exit_path.exists():
        return
    with log_path.open('w') as output:
        p = subprocess.run(['bash', str(RUN), 'run', name, plan],
                           stdout=output, stderr=subprocess.STDOUT)
    exit_path.write_text(str(p.returncode) + '\n')


def parse(name, plan):
    log_path = HERE / (name + '.log')
    exit_code = int((HERE / (name + '.exit')).read_text())
    log = log_path.read_text(errors='replace')
    events, guards, exits = [], [], []
    for lineno, line in enumerate(log.splitlines()):
        m = re.search(r'HBASE07 IO door=(MASTER|EXISTS|CHECK|STATE) hit=(\d+) '
                      r'matched=(true|false) applied=(true|false) fault=(\w*) thread=(.*)$', line)
        if m:
            events.append({'line': lineno, 'door': m[1], 'hit': int(m[2]),
                           'matched': m[3] == 'true', 'applied': m[4] == 'true',
                           'fault': m[5], 'thread': m[6]})
        m = re.search(r'HBASE07 GUARD_TABLE_DISABLED table=(.*?) value=(true|false) '
                      r'exception=(\S+) thread=(.*)$', line)
        if m:
            guards.append({'line': lineno, 'table': m[1], 'value': m[2] == 'true',
                           'exception': m[3], 'thread': m[4]})
        m = re.search(r'HBASE07 TARGET_EXIT exception=(.*?) thread=(.*)$', line)
        if m:
            exits.append({'line': lineno, 'exception': m[1], 'thread': m[2]})
    faults = [e for e in events if e['applied']]
    applied_sequence = ['%s:%d:%s' % (e['door'], e['hit'], e['fault']) for e in faults]
    after = ([g for g in guards if g['line'] > faults[-1]['line']
              and g['thread'] == faults[-1]['thread'] and g['exception'] == 'none']
             if faults else [])
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', log)
    junit = re.search(r'HBASE07 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', log)
    return {'id': name, 'plan': plan, 'requested_fault_events': len(plan.split(',')),
            'matched_fault_events': sum(e['matched'] for e in events),
            'applied_fault_events': len(faults), 'applied_selector_sequence': applied_sequence,
            'applied_faults': faults, 'observed_io': events,
            'strict': applied_sequence == plan.split(','),
            'target_entries': log.count('HBASE07 TARGET_ENTER'),
            'target_after_final_fault': bool(after), 'post_fault_guards': after,
            'target_exception_observed': any(not g['value'] for g in after),
            'exact_target_exceptions': exits,
            'junit_passed': bool(junit and junit[1] == '1' and junit[3] == '0'
                                 and exit_code == 0), 'junit_exit': exit_code,
            'elapsed_seconds': float(elapsed[1]) if elapsed else None,
            'log': str(log_path.relative_to(CASE))}


def healthy_result():
    while not (HERE / 'healthy_final.exit').exists():
        time.sleep(2)
    log = (HERE / 'healthy_final.log').read_text(errors='replace')
    exit_code = int((HERE / 'healthy_final.exit').read_text())
    junit = re.search(r'HBASE07 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', log)
    guard = re.findall(r'HBASE07 GUARD_TABLE_DISABLED table=(.*?) value=(true|false) '
                       r'exception=(\S+) thread=(.*)', log)
    doors = re.findall(r'HBASE07 IO door=(MASTER|EXISTS|CHECK|STATE) hit=(\d+)', log)
    if exit_code or not junit or junit.groups() != ('1', '1', '0') or len(guard) != 1 \
            or guard[0][1:3] != ('true', 'none') or [d for d, _ in doors] != list(DOORS):
        raise RuntimeError('Original JUnit healthy target/I-O baseline invalid')
    cov = coverage([HERE / 'healthy_final.exec'])
    if 'error' in cov:
        raise RuntimeError('JaCoCo healthy coverage invalid: ' + cov['error'])
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', log)
    data = json.loads(RESULT.read_text())
    data.update({
        'status': 'running', 'cluster_test':
          'org.apache.hadoop.hbase.snapshot.TestRestoreFlushSnapshotFromClient#testRestoreSnapshot',
        'target_guard': 'HBaseAdmin.restoreSnapshot(String,boolean,boolean):2787',
        'target_exception': 'org.apache.hadoop.hbase.TableNotDisabledException',
        'target_reached': True, 'healthy_junit_passed': True,
        'healthy_target_guard_count': len(guard), 'healthy_guard_values': [True],
        'healthy_observed_io_doors': [d for d, _ in doors],
        'healthy_elapsed_seconds': float(elapsed[1]) if elapsed else None,
        'healthy_coverage': cov, 'fault_budget': {'trials': 80, 'max_faults_per_trial': 8},
        'fault_trials': 0, 'strict_injections': 0, 'target_after_fault': 0,
        'coverage_gain': 0, 'bug_mark': 'none', 'fault_trial_details': [],
        'coverage_type': 'JaCoCo original production methods/branches/lines in six HBase client classes',
        'instrumentation': 'Original JUnit Platform test, case-local ByteBuddy, JaCoCo; no GraphChecker runtime',
        'evidence': {'healthy_log': 'native/healthy_final.log',
                     'healthy_exec': 'native/healthy_final.exec',
                     'runner': 'native/run.sh', 'agent_source': 'native/src/HBase07Agent.java'}})
    save(data)
    return data


def main():
    data = json.loads(RESULT.read_text())
    if 'healthy_coverage' not in data:
        data = healthy_result()
    candidate_plans = list(plans())
    assert len(candidate_plans) == 80
    if data['fault_budget']['trials'] == 128:
        candidate_plans.extend(extension_plans())
    assert len({plan_string(p) for p in candidate_plans}) == len(candidate_plans)
    prior_paths = [HERE / 'healthy_final.exec']
    for old in data['fault_trial_details']:
        if old['strict'] and old['target_after_final_fault']:
            prior_paths.append(HERE / (old['id'] + '.exec'))
    prior_cov = coverage(prior_paths)
    workers = int(os.environ.get('HBASE07_WORKERS', '3'))
    start = len(data['fault_trial_details']) + 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {i: pool.submit(run_one, 'r%03d' % i, plan_string(plan))
                   for i, plan in enumerate(candidate_plans, 1)
                   if start <= i <= data['fault_budget']['trials']}
        for index in sorted(futures):
            futures[index].result()
            item = parse('r%03d' % index, plan_string(candidate_plans[index - 1]))
            execution = HERE / (item['id'] + '.exec')
            item['production_coverage'] = coverage([execution]) if execution.exists() \
                else {'error': 'missing exec'}
            valid = item['strict'] and item['target_after_final_fault'] and execution.exists()
            if valid:
                union = coverage(prior_paths + [execution])
                item['new_production_branches_vs_prior_trials'] = max(
                    0, union['total_branches'] - prior_cov['total_branches'])
                item['new_production_methods_vs_prior_trials'] = max(
                    0, union['total_methods'] - prior_cov['total_methods'])
                prior_cov = union
                prior_paths.append(execution)
            else:
                item['new_production_branches_vs_prior_trials'] = 0
                item['new_production_methods_vs_prior_trials'] = 0
            item['production_branch_union_valid_feedback'] = prior_cov['total_branches']
            item['new_io_family'] = False
            data['fault_trial_details'].append(item)
            items = data['fault_trial_details']
            data['fault_trials'] = len(items)
            data['strict_injections'] = sum(x['strict'] for x in items)
            data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
            data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
            data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
            data['target_after_fault'] = sum(x['strict'] and x['target_after_final_fault'] for x in items)
            data['lost_target_trials'] = sum(x['strict'] and not x['target_after_final_fault'] for x in items)
            data['selected_target_exception_trials'] = sum(
                x['strict'] and x['target_after_final_fault'] and x['target_exception_observed']
                for x in items)
            data['fault_union_production_branches'] = prior_cov['total_branches']
            data['coverage_gain'] = max(0, prior_cov['total_branches']
                                        - data['healthy_coverage']['total_branches'])
            data['elapsed_seconds'] = round((data['healthy_elapsed_seconds'] or 0)
                                            + sum(x['elapsed_seconds'] or 0 for x in items), 2)
            data['bug_mark'] = ('candidate_review' if any(
                x['strict'] and x['target_after_final_fault']
                and (x['target_exception_observed'] or not x['junit_passed'])
                for x in items) else 'none')
            save(data)
            if data['bug_mark'] == 'candidate_review':
                data['status'] = 'candidate_review'
                save(data)
                return
    if data['fault_trials'] == 80:
        recent = data['fault_trial_details'][-8:]
        fresh = any(x['new_production_branches_vs_prior_trials'] > 0
                    or x['new_production_methods_vs_prior_trials'] > 0 or x['new_io_family']
                    for x in recent)
        data['extension_decision'] = {
            'fresh_coverage_or_io_in_trials_73_to_80': fresh,
            'recent_new_production_branches': sum(
                x['new_production_branches_vs_prior_trials'] for x in recent),
            'recent_new_production_methods': sum(
                x['new_production_methods_vs_prior_trials'] for x in recent)}
        if fresh:
            data['fault_budget'] = {'trials': 128, 'max_faults_per_trial': 10}
            save(data)
            return main()
    data['status'] = 'quality_complete'
    data['campaign_finished'] = True
    data['stop_reason'] = ('Completed conditional 128-trial budget' if
                           data['fault_budget']['trials'] == 128 else
                           'Completed 80-trial budget; no new valid production method/branch or I/O family near limit')
    save(data)


if __name__ == '__main__':
    main()
