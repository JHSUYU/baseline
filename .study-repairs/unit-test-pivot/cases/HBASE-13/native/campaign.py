#!/usr/bin/env python3
"""One unchanged merge JUnit per plan; three separate case ledgers and valid feedback."""
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = HERE / 'run.sh'
CASES = (13, 14, 15)
KINDS = ('IOException', 'SocketTimeoutException', 'EOFException', 'ConnectException')
THROW_LINES = {13: 495, 14: 500, 15: 503}
EXPECTED = {13: 'org.apache.hadoop.hbase.exceptions.MergeRegionException',
            14: 'org.apache.hadoop.hbase.UnknownRegionException',
            15: 'org.apache.hadoop.hbase.exceptions.MergeRegionException'}


def case_path(number):
    return ROOT / ('HBASE-%02d' % number)


def plan(start, kinds):
    return ','.join('META:%d:%s' % (start + index, kind)
                    for index, kind in enumerate(kinds))


def plans():
    all_plans = []
    for start in (1, 2):
        for kind in KINDS:
            candidate = plan(start, (kind,))
            if candidate != 'META:1:IOException':
                all_plans.append(candidate)
    for a, b in itertools.product(KINDS, repeat=2):
        for start in (1, 2):
            all_plans.append(plan(start, (a, b)))
    four = []
    for a, b in itertools.product(KINDS, repeat=2):
        for start in (1, 2):
            four.append(plan(start, (a, b, a, b)))
    all_plans.extend(four[:24])
    eight = []
    for a, b in itertools.product(KINDS, repeat=2):
        for start in (1, 2):
            candidate = plan(start, (a, b, a, b, a, b, a, b))
            if candidate != plan(1, (KINDS[0],) * 8):
                eight.append(candidate)
    all_plans.extend(eight[:17])
    assert len(all_plans) == 80 and len(set(all_plans)) == 80
    assert all(len(p.split(',')) <= 8 for p in all_plans)
    return all_plans


def extension_plans():
    extras = []
    for a, b in itertools.product(KINDS, repeat=2):
        for start in (1, 2):
            extras.append(plan(start, (a, b, a, b, a, b, a, b, a, b)))
    for a, b in itertools.product(KINDS, repeat=2):
        extras.append(plan(1, (a, b, a, b, a, b)))
    assert len(extras) == 48 and len(set(extras)) == 48
    assert not set(extras) & set(plans())
    return extras


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
            'total_branches': sum(x['branches'] for x in classes.values()),
            'total_methods': sum(x['methods'] for x in classes.values()),
            'total_lines': sum(x['lines'] for x in classes.values())}


def save(number, data):
    dest = case_path(number) / 'result.json'
    temp = dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(temp, dest)


def run_one(name, selector):
    exit_path = HERE / (name + '.exit')
    if exit_path.exists():
        return
    with (HERE / (name + '.log')).open('w') as out:
        p = subprocess.run(['bash', str(RUN), 'run', name, selector],
                           stdout=out, stderr=subprocess.STDOUT)
    exit_path.write_text(str(p.returncode) + '\n')


def parse(name, selector):
    source = HERE / (name + '.log')
    log = source.read_text(errors='replace')
    exit_code = int((HERE / (name + '.exit')).read_text())
    ios, checks, prepares = [], {number: [] for number in CASES}, []
    for line_no, line in enumerate(log.splitlines()):
        m = re.match(r'HBASE1315 IO door=(META|REGION_INFO) hit=(\d+) region=(\S+) '
                     r'matched=(true|false) applied=(true|false) fault=(\w*) thread=(.*)$', line)
        if m:
            ios.append({'line': line_no, 'door': m[1], 'hit': int(m[2]),
                        'region': m[3], 'matched': m[4] == 'true',
                        'applied': m[5] == 'true', 'fault': m[6], 'thread': m[7]})
        m = re.match(r'HBASE1315 CHECK(13|14|15) region=(\S+) (value|NULL|null)=(true|false) '
                     r'exception=(\S+) thread=(.*)$', line)
        if m:
            checks[int(m[1])].append({'line': line_no, 'region': m[2],
                                      'field': m[3].lower(), 'value': m[4] == 'true',
                                      'exception': m[5], 'thread': m[6]})
        m = re.match(r'HBASE1315 PREPARE_EXIT result=(true|false) exception=(.*?) thread=(.*)$', line)
        if m:
            prepares.append({'line': line_no, 'result': m[1] == 'true',
                             'exception': m[2], 'thread': m[3]})
    faults = [x for x in ios if x['applied']]
    applied = ['%s:%d:%s' % (x['door'], x['hit'], x['fault']) for x in faults]
    last = faults[-1] if faults else None
    post = {number: [x for x in checks[number]
                     if last and x['line'] > last['line'] and x['thread'] == last['thread']
                     and x['region'] == last['region'] and x['exception'] == 'none']
            for number in CASES}
    outcomes = {13: any(x['value'] for x in post[13]),
                14: any(x['value'] for x in post[14]),
                15: any(not x['value'] for x in post[15])}
    junit = re.search(r'HBASE1315 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', log)
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', log)
    return {'id': name, 'plan': selector, 'requested_fault_events': len(selector.split(',')),
            'matched_fault_events': sum(x['matched'] for x in ios),
            'applied_fault_events': len(faults), 'applied_selector_sequence': applied,
            'strict': applied == selector.split(','), 'observed_io': ios,
            'all_checks': checks, 'post_fault_checks': post,
            'target_after_final_fault': {n: bool(post[n]) for n in CASES},
            'selected_guard_failure': outcomes,
            'prepare_exits': prepares, 'prepare_entries': log.count('HBASE1315 PREPARE_ENTER'),
            'junit_passed': bool(junit and junit.groups() == ('1', '1', '0') and exit_code == 0),
            'junit_exit': exit_code, 'elapsed_seconds': float(elapsed[1]) if elapsed else None,
            'log': str(source.relative_to(ROOT))}


def healthy():
    log = (HERE / 'healthy_v2.log').read_text(errors='replace')
    assert int((HERE / 'healthy_v2.exit').read_text()) == 0
    assert re.search(r'HBASE1315 JUNIT found=1 succeeded=1 failed=0', log)
    for number in CASES:
        matches = re.findall(r'^HBASE1315 CHECK%d region=(\S+) .*exception=none thread=(.*)$' % number,
                             log, re.MULTILINE)
        assert len(matches) == 2 and len({x[0] for x in matches}) == 2, (number, matches)
    assert [x for x in re.findall(r'^HBASE1315 IO door=(\S+)', log, re.MULTILINE)] == [
        'META', 'REGION_INFO', 'META', 'REGION_INFO']
    cov = coverage([HERE / 'healthy_v2.exec'])
    assert 'error' not in cov
    assert cov['target_lines']['488']['instructions'] > 0
    assert cov['target_lines']['498']['instructions'] > 0
    assert cov['target_lines']['502']['instructions'] > 0
    assert all(cov['target_lines'][str(THROW_LINES[n])]['instructions'] == 0 for n in CASES)
    seconds = float(re.search(r'ELAPSED_SECONDS=([\d.]+)', log)[1])
    for number in CASES:
        data = json.loads((case_path(number) / 'result.json').read_text())
        data.update({'status': 'running', 'cluster_test':
                     'org.apache.hadoop.hbase.master.assignment.TestMergeTableRegionsProcedure#testMergeTwoRegions',
                     'target_reached': True, 'healthy_junit_passed': True,
                     'healthy_target_guard_count': 2, 'healthy_elapsed_seconds': seconds,
                     'healthy_guard_values': {13: [False, False], 14: [False, False],
                                              15: [True, True]}[number],
                     'healthy_observed_io_doors': ['META', 'REGION_INFO', 'META', 'REGION_INFO'],
                     'healthy_coverage': cov, 'fault_budget': {'trials': 80,
                                                               'max_faults_per_trial': 8},
                     'fault_trials': 0, 'strict_injections': 0, 'target_after_fault': 0,
                     'coverage_gain': 0, 'bug_mark': 'none', 'fault_trial_details': [],
                     'coverage_type': 'JaCoCo original production methods/branches/lines in six HBase client/server classes',
                     'instrumentation': 'Original JUnit Platform, case-local ByteBuddy and JaCoCo; no GraphChecker runtime',
                     'target_guard_line': {13: 488, 14: 498, 15: 502}[number],
                     'target_throw_line': THROW_LINES[number],
                     'target_exception': EXPECTED[number],
                     'evidence': {'shared_native': '../HBASE-13/native',
                                  'healthy_log': '../HBASE-13/native/healthy_v2.log',
                                  'runner': '../HBASE-13/native/run.sh'},
                     'excluded_probe': 'REGION_INFO:1:IOException precisely applied but no post-fault selected guard; original JUnit failed',
                     'uncounted_calibrations': [
                         'META:1:IOException',
                         plan(1, (KINDS[0],) * 8)]})
        save(number, data)


def main():
    if 'healthy_coverage' not in json.loads((case_path(13) / 'result.json').read_text()):
        healthy()
    ledgers = {n: json.loads((case_path(n) / 'result.json').read_text()) for n in CASES}
    selectors = plans()
    if ledgers[13]['fault_budget']['trials'] == 128:
        selectors.extend(extension_plans())
    assert len(set(selectors)) == len(selectors)
    prior_paths = {}
    prior_cov = {}
    coverage_cache = {}
    def cached_coverage(paths):
        key = tuple(map(str, paths))
        if key not in coverage_cache:
            coverage_cache[key] = coverage(paths)
        return coverage_cache[key]
    for n in CASES:
        prior_paths[n] = [HERE / 'healthy_v2.exec'] + [
            HERE / (item['id'] + '.exec') for item in ledgers[n]['fault_trial_details']
            if item['strict'] and item['target_after_final_fault']]
        prior_cov[n] = cached_coverage(prior_paths[n])
        assert 'error' not in prior_cov[n]
    workers = int(os.environ.get('HBASE1315_WORKERS', '3'))
    start = len(ledgers[13]['fault_trial_details']) + 1
    limit = ledgers[13]['fault_budget']['trials']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {i: pool.submit(run_one, 'r%03d' % i, selectors[i - 1])
                   for i in range(start, min(start + workers, limit + 1))}
        for index in range(start, limit + 1):
            futures.pop(index).result()
            shared = parse('r%03d' % index, selectors[index - 1])
            exe = HERE / ('r%03d.exec' % index)
            single_cov = coverage([exe]) if exe.exists() else {'error': 'missing exec'}
            for n in CASES:
                data = ledgers[n]
                item = {k: v for k, v in shared.items() if k not in
                        ('all_checks', 'post_fault_checks', 'target_after_final_fault',
                         'selected_guard_failure')}
                item['all_checks'] = shared['all_checks']
                item['post_fault_checks'] = shared['post_fault_checks'][n]
                item['target_after_final_fault'] = shared['target_after_final_fault'][n]
                item['selected_guard_failure'] = shared['selected_guard_failure'][n]
                item['selected_exception_class'] = EXPECTED[n] if item['selected_guard_failure'] else 'none'
                item['production_coverage'] = single_cov
                valid = item['strict'] and item['target_after_final_fault'] and exe.exists()
                if valid:
                    union = cached_coverage(prior_paths[n] + [exe])
                    assert 'error' not in union
                    item['new_production_branches_vs_prior_trials'] = max(
                        0, union['total_branches'] - prior_cov[n]['total_branches'])
                    item['new_production_methods_vs_prior_trials'] = max(
                        0, union['total_methods'] - prior_cov[n]['total_methods'])
                    prior_cov[n] = union
                    prior_paths[n].append(exe)
                else:
                    item['new_production_branches_vs_prior_trials'] = 0
                    item['new_production_methods_vs_prior_trials'] = 0
                item['new_io_family'] = any(x['door'] not in ('META', 'REGION_INFO')
                                            for x in shared['observed_io'])
                item['production_branch_union_valid_feedback'] = prior_cov[n]['total_branches']
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
                data['selected_target_exception_trials'] = sum(
                    x['strict'] and x['target_after_final_fault'] and x['selected_guard_failure']
                    for x in items)
                data['fault_union_production_branches'] = prior_cov[n]['total_branches']
                data['coverage_gain'] = max(0, prior_cov[n]['total_branches']
                                            - data['healthy_coverage']['total_branches'])
                data['elapsed_seconds'] = round(data['healthy_elapsed_seconds']
                    + sum(x['elapsed_seconds'] or 0 for x in items), 2)
                data['bug_mark'] = 'candidate_review' if any(
                    x['strict'] and x['target_after_final_fault']
                    and (x['selected_guard_failure'] or not x['junit_passed'])
                    for x in items) else 'none'
                save(n, data)
            if any(ledgers[n]['bug_mark'] == 'candidate_review' for n in CASES):
                for future in futures.values():
                    future.cancel()
                for n in CASES:
                    ledgers[n]['status'] = 'candidate_review'
                    save(n, ledgers[n])
                return
            next_index = index + workers
            if next_index <= limit:
                futures[next_index] = pool.submit(run_one, 'r%03d' % next_index,
                                                  selectors[next_index - 1])
    if ledgers[13]['fault_trials'] == 80:
        fresh = any(any(x['new_production_branches_vs_prior_trials'] > 0
                        or x['new_production_methods_vs_prior_trials'] > 0 or x['new_io_family']
                        for x in ledgers[n]['fault_trial_details'][-8:]) for n in CASES)
        for n in CASES:
            recent = ledgers[n]['fault_trial_details'][-8:]
            ledgers[n]['extension_decision'] = {
                'fresh_coverage_or_io_in_trials_73_to_80': fresh,
                'recent_new_production_branches': sum(
                    x['new_production_branches_vs_prior_trials'] for x in recent),
                'recent_new_production_methods': sum(
                    x['new_production_methods_vs_prior_trials'] for x in recent)}
            if fresh:
                ledgers[n]['fault_budget'] = {'trials': 128, 'max_faults_per_trial': 10}
            save(n, ledgers[n])
        if fresh:
            return main()
    for n in CASES:
        ledgers[n]['status'] = 'quality_complete'
        ledgers[n]['campaign_finished'] = True
        ledgers[n]['stop_reason'] = ('Completed conditional 128-trial budget' if
            ledgers[n]['fault_budget']['trials'] == 128 else
            'Completed 80-trial budget; no new valid production method/branch or I/O family near limit')
        save(n, ledgers[n])


if __name__ == '__main__':
    main()
