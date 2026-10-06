#!/usr/bin/env python3
"""Original RS-crash JUnit with ordered master RPC faults and exact Backoff identity."""
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import os
from pathlib import Path
import random
import re
import subprocess

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
RUN = HERE / 'run.sh'
KINDS = ('IOException', 'SocketTimeoutException', 'EOFException', 'ConnectException')
EXPECTED = 'org.apache.hadoop.hbase.HBaseIOException:Failed to close region'


def selector(kinds):
    return ','.join('MOVE_MASTER_RPC:%d:%s' % (i, kind)
                    for i, kind in enumerate(kinds, 1))


def plans():
    out = [selector((KINDS[0],)), selector((KINDS[0],) * 8)]
    out.extend(selector((kind,)) for kind in KINDS[1:])
    out.extend(selector(pair) for pair in itertools.product(KINDS, repeat=2))
    rng = random.Random(16)
    fours = list(itertools.product(KINDS, repeat=4))
    out.extend(selector(item) for item in rng.sample(fours, 40))
    eights = [item * 2 for item in fours if item != (KINDS[0],) * 4]
    out.extend(selector(item) for item in rng.sample(eights, 19))
    assert len(out) == 80 and len(set(out)) == 80
    assert all(len(x.split(',')) <= 8 for x in out)
    return out


def extension_plans():
    rng = random.Random(12816)
    items = list(itertools.product(KINDS, repeat=5))
    out = [selector(item * 2) for item in rng.sample(items, 48)]
    assert len(set(out)) == 48 and not set(out) & set(plans())
    return out


def coverage(paths):
    p = subprocess.run(['bash', str(RUN), 'coverage', ','.join(map(str, paths))],
                       capture_output=True, text=True)
    if p.returncode:
        return {'error': p.stderr[-1000:]}
    classes, lines = {}, {}
    for line in p.stdout.splitlines():
        m = re.match(r'COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)', line)
        if m:
            classes[m[1].rsplit('/', 1)[-1]] = dict(zip(
                ('methods', 'branches', 'lines'), map(int, m.groups()[1:])))
        m = re.match(r'COVERAGE line=(\d+) instructions=(\d+) branches=(\d+)', line)
        if m:
            lines[m[1]] = {'instructions': int(m[2]), 'branches': int(m[3])}
    return {'classes': classes, 'target_lines': lines,
            'total_branches': sum(v['branches'] for v in classes.values()),
            'total_methods': sum(v['methods'] for v in classes.values()),
            'total_lines': sum(v['lines'] for v in classes.values())}


def save(data):
    temp = RESULT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(temp, RESULT)


def run_one(name, plan):
    exit_path = HERE / (name + '.exit')
    if exit_path.exists():
        return
    with (HERE / (name + '.log')).open('w') as output:
        p = subprocess.run(['bash', str(RUN), 'run', name, plan],
                           stdout=output, stderr=subprocess.STDOUT)
    exit_path.write_text(str(p.returncode) + '\n')


def parse(name, plan):
    log_path = HERE / (name + '.log')
    log = log_path.read_text(errors='replace')
    exit_code = int((HERE / (name + '.exit')).read_text())
    moves, io, calls, open_calls = [], [], [], {}
    for line_no, line in enumerate(log.splitlines()):
        m = re.match(r'HBASE16 MOVE_ENTER encoded=(\w+) thread=(.*)$', line)
        if m:
            moves.append({'line': line_no, 'encoded': m[1], 'thread': m[2]})
        m = re.match(r'HBASE16 IO door=MOVE_MASTER_RPC hit=(\d+) encoded=(\w+) '
                     r'matched=(true|false) applied=(true|false) fault=(\w*) thread=(.*)$', line)
        if m:
            io.append({'line': line_no, 'door': 'MOVE_MASTER_RPC', 'hit': int(m[1]),
                       'encoded': m[2], 'matched': m[3] == 'true',
                       'applied': m[4] == 'true', 'fault': m[5], 'thread': m[6]})
        m = re.match(r'HBASE16 IO door=CLOSE_RPC hit=(\d+) child=(\d+) region=(\S+) '
                     r'matched=(true|false) applied=(true|false) fault=(\w*) thread=(.*)$', line)
        if m:
            io.append({'line': line_no, 'door': 'CLOSE_RPC', 'hit': int(m[1]),
                       'child': int(m[2]), 'region': m[3], 'matched': m[4] == 'true',
                       'applied': m[5] == 'true', 'fault': m[6], 'thread': m[7]})
        m = re.match(r'HBASE16 TARGET_ENTER proc=(\d+) region=(\S+) encoded=(\w+) thread=(.*)$', line)
        if m:
            key = (m[1], m[2], m[4])
            open_calls.setdefault(key, []).append({'enter_line': line_no,
                'proc': int(m[1]), 'region': m[2], 'encoded': m[3], 'thread': m[4]})
        m = re.match(r'HBASE16 TARGET_EXIT proc=(\d+) region=(\S+) flow=(\S+) '
                     r'exception=(.*?) thread=(.*)$', line)
        if m:
            key = (m[1], m[2], m[5])
            pending = open_calls.get(key, [])
            if pending:
                call = pending.pop(0)
                call.update({'exit_line': line_no, 'flow': m[3], 'exception': m[4]})
                calls.append(call)
    faults = [x for x in io if x['applied']]
    applied = ['%s:%d:%s' % (x['door'], x['hit'], x['fault']) for x in faults]
    last = faults[-1] if faults else None
    post = [x for x in calls if last and x['enter_line'] > last['line']
            and x['encoded'] == last['encoded']]
    post_expected = [x for x in post if x['exception'] == EXPECTED]
    post_unexpected = [x for x in post if x['exception'] not in ('none', EXPECTED)]
    junit = re.search(r'HBASE16 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+) aborted=(\d+)', log)
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', log)
    return {'id': name, 'plan': plan, 'requested_fault_events': len(plan.split(',')),
            'matched_fault_events': sum(x['matched'] for x in io),
            'applied_fault_events': len(faults), 'applied_selector_sequence': applied,
            'strict': applied == plan.split(','), 'observed_io': io,
            'moves': moves, 'target_calls': calls, 'target_entries': len(calls),
            'target_expected_exception_count': sum(x['exception'] == EXPECTED for x in calls),
            'post_fault_target_calls': post, 'post_fault_expected_target_exits': post_expected,
            'post_fault_unexpected_target_exits': post_unexpected,
            'target_after_final_fault': bool(post_expected),
            'junit_passed': bool(junit and junit.groups() == ('1', '1', '0', '0')
                                 and exit_code == 0), 'junit_exit': exit_code,
            'elapsed_seconds': float(elapsed[1]) if elapsed else None,
            'log': str(log_path.relative_to(CASE))}


def healthy_result():
    log = (HERE / 'healthy_final.log').read_text(errors='replace')
    assert int((HERE / 'healthy_final.exit').read_text()) == 0
    assert re.search(r'HBASE16 JUNIT found=1 succeeded=1 failed=0 aborted=0', log)
    moves = re.findall(r'^HBASE16 MOVE_ENTER encoded=(\w+) thread=', log, re.MULTILINE)
    assert len(moves) == 1
    target = re.findall(r'^HBASE16 TARGET_ENTER proc=(\d+) region=(\S+) encoded=(\w+) thread=',
                        log, re.MULTILINE)
    assert target and all(x[2] == moves[0] for x in target)
    expected_count = len(re.findall(r'^HBASE16 TARGET_EXIT .* exception=' + re.escape(EXPECTED) + r' thread=', log, re.MULTILINE))
    assert expected_count > 0
    doors = re.findall(r'^HBASE16 IO door=(MOVE_MASTER_RPC|CLOSE_RPC)', log, re.MULTILINE)
    assert doors and doors[0] == 'MOVE_MASTER_RPC'
    cov = coverage([HERE / 'healthy_final.exec'])
    assert 'error' not in cov and cov['target_lines']['371']['instructions'] > 0
    elapsed = float(re.search(r'ELAPSED_SECONDS=([\d.]+)', log)[1])
    data = json.loads(RESULT.read_text())
    data.update({'status': 'running', 'cluster_test':
        'org.apache.hadoop.hbase.master.assignment.TestCloseRegionWhileRSCrash#testRetryBackoff',
        'target_reached': True, 'healthy_junit_passed': True,
        'healthy_target_entries': len(target),
        'healthy_expected_target_exception_count': expected_count,
        'healthy_target_throw_line_371_covered': True,
        'healthy_observed_io_doors': doors, 'healthy_elapsed_seconds': elapsed,
        'healthy_coverage': cov, 'fault_budget': {'trials': 80,
                                                  'max_faults_per_trial': 8},
        'fault_trials': 0, 'strict_injections': 0, 'target_after_fault': 0,
        'coverage_gain': 0, 'bug_mark': 'none', 'fault_trial_details': [],
        'coverage_type': 'JaCoCo selected production methods/branches/lines in nine HBase client/server classes',
        'instrumentation': 'Unchanged JUnit Platform test, case-local ByteBuddy and JaCoCo; no GraphChecker runtime',
        'target_guard': 'TransitRegionStateProcedure.confirmClosed:366 CLOSING branch',
        'target_exception': EXPECTED,
        'baseline_exception_note': 'The original test intentionally waits for close retry/backoff; the selected HBaseIOException is expected in healthy execution.',
        'selector_scope': 'Only HBaseAdmin.move invoked by testRetryBackoff lambda; request identity is its Backoff region encoded name.',
        'evidence': {'healthy_log': 'native/healthy_final.log',
                     'healthy_exec': 'native/healthy_final.exec',
                     'runner': 'native/run.sh', 'agent_source': 'native/src/HBase16Agent.java'}})
    save(data)
    return data


def main():
    data = json.loads(RESULT.read_text())
    if 'healthy_coverage' not in data:
        data = healthy_result()
    selectors = plans()
    if data['fault_budget']['trials'] == 128:
        selectors.extend(extension_plans())
    assert len(set(selectors)) == len(selectors)
    prior_paths = [HERE / 'healthy_final.exec'] + [
        HERE / (x['id'] + '.exec') for x in data['fault_trial_details']
        if x['strict'] and x['target_after_final_fault']]
    prior_cov = coverage(prior_paths)
    workers = int(os.environ.get('HBASE16_WORKERS', '3'))
    start = len(data['fault_trial_details']) + 1
    limit = data['fault_budget']['trials']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {i: pool.submit(run_one, 'r%03d' % i, selectors[i - 1])
                   for i in range(start, min(start + workers, limit + 1))}
        for index in range(start, limit + 1):
            futures.pop(index).result()
            item = parse('r%03d' % index, selectors[index - 1])
            exe = HERE / (item['id'] + '.exec')
            item['production_coverage'] = coverage([exe]) if exe.exists() else {'error': 'missing exec'}
            valid = item['strict'] and item['target_after_final_fault'] and exe.exists()
            if valid:
                union = coverage(prior_paths + [exe])
                assert 'error' not in union
                item['new_production_branches_vs_prior_trials'] = max(
                    0, union['total_branches'] - prior_cov['total_branches'])
                item['new_production_methods_vs_prior_trials'] = max(
                    0, union['total_methods'] - prior_cov['total_methods'])
                prior_cov = union
                prior_paths.append(exe)
            else:
                item['new_production_branches_vs_prior_trials'] = 0
                item['new_production_methods_vs_prior_trials'] = 0
            item['new_io_family'] = any(x['door'] not in data['healthy_observed_io_doors']
                                        for x in item['observed_io'])
            item['production_branch_union_valid_feedback'] = prior_cov['total_branches']
            data['fault_trial_details'].append(item)
            items = data['fault_trial_details']
            data['fault_trials'] = len(items)
            data['strict_injections'] = sum(x['strict'] for x in items)
            data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
            data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
            data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
            data['target_after_fault'] = sum(x['strict'] and x['target_after_final_fault']
                                             for x in items)
            data['lost_target_trials'] = sum(x['strict'] and not x['target_after_final_fault']
                                              for x in items)
            data['expected_target_exception_trials'] = sum(
                x['strict'] and x['target_after_final_fault'] for x in items)
            data['unexpected_target_exception_trials'] = sum(
                x['strict'] and x['target_after_final_fault']
                and bool(x['post_fault_unexpected_target_exits']) for x in items)
            data['fault_union_production_branches'] = prior_cov['total_branches']
            data['coverage_gain'] = max(0, prior_cov['total_branches']
                                        - data['healthy_coverage']['total_branches'])
            data['elapsed_seconds'] = round(data['healthy_elapsed_seconds']
                + sum(x['elapsed_seconds'] or 0 for x in items), 2)
            data['bug_mark'] = 'candidate_review' if any(
                x['strict'] and x['target_after_final_fault']
                and (x['post_fault_unexpected_target_exits'] or not x['junit_passed'])
                for x in items) else 'none'
            save(data)
            if data['bug_mark'] == 'candidate_review':
                for future in futures.values():
                    future.cancel()
                data['status'] = 'candidate_review'
                save(data)
                return
            next_index = index + workers
            if next_index <= limit:
                futures[next_index] = pool.submit(run_one, 'r%03d' % next_index,
                                                  selectors[next_index - 1])
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
        'Completed 80-trial budget; no new valid production method/branch or observed I/O family near limit')
    save(data)


if __name__ == '__main__':
    main()
