#!/usr/bin/env python3
"""Scoped hbase:meta scan RPC faults in the unchanged original hbck JUnit."""
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
KINDS = ('IOException', 'EOFException', 'SocketTimeoutException', 'ConnectException')
SELECTED = 'java.io.IOException:Two entries in hbase:meta are same '


def selector(scan_id, kinds):
    return ','.join('META_SCAN:%d:%d:%s' % (scan_id, ordinal, kind)
                    for ordinal, kind in enumerate(kinds, 1))


def seeds():
    first = [selector(1, ('IOException',)), selector(2, ('IOException',)),
             selector(3, ('IOException',)), selector(1, ('IOException',) * 4),
             selector(1, ('IOException',) * 8)]
    rng = random.Random(35)
    pool = []
    for scan_id in (1, 2, 3):
        for kind in KINDS:
            pool.append(selector(scan_id, (kind,)))
    for length, take in ((2, 16), (3, 28), (4, 20), (5, 8)):
        candidates = list(itertools.product(KINDS, repeat=length))
        rng.shuffle(candidates)
        for scan_id in (1, 2, 3):
            pool.extend(selector(scan_id, values) for values in candidates[:take])
    out = list(dict.fromkeys(first + pool))[:80]
    assert len(out) == 80 and len(set(out)) == 80
    assert all(len(x.split(',')) <= 8 for x in out)
    return out


def extension_seeds():
    rng = random.Random(350128)
    candidates = list(itertools.product(KINDS, repeat=5))
    rng.shuffle(candidates)
    out = []
    for scan_id in (1, 2, 3):
        out.extend(selector(scan_id, values) for values in candidates[:24])
    out = [x for x in out if x not in seeds()][:48]
    assert len(out) == 48 and len(set(out)) == 48
    return out


def mutations(item, limit):
    fields = [part.split(':', 3) for part in item['plan'].split(',')]
    scan_id = int(fields[0][1])
    kinds = [part[3] for part in fields]
    variants = []
    for kind in KINDS:
        variants.append(kinds[:-1] + [kind])
        variants.append([kind] + kinds[1:])
        if len(kinds) < limit:
            variants.append(kinds + [kind])
            variants.append([kind] + kinds)
    if len(kinds) > 1:
        variants.append(kinds[1:] + kinds[:1])
    return list(dict.fromkeys(selector(scan_id, values) for values in variants
                              if 1 <= len(values) <= limit))


def save(data):
    temp = RESULT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(temp, RESULT)


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


def parse(name, plan):
    raw = (HERE / (name + '.log')).read_text(errors='replace')
    lines = raw.splitlines()
    exit_code = int((HERE / (name + '.exit')).read_text())
    scans, io, targets = {}, [], []
    test_enter = test_exit = 0
    active = {}
    for line_no, line in enumerate(lines):
        if line.startswith('HBASE35 TEST_ENTER method=test'):
            test_enter += 1
        elif line.startswith('HBASE35 TEST_EXIT exception='):
            test_exit += 1
        m = re.match(r'HBASE35 FULL_SCAN_ENTER id=(\d+)$', line)
        if m:
            scans[int(m[1])] = {'enter_line': line_no, 'exit_line': None,
                                'exception': None}
        m = re.match(r'HBASE35 FULL_SCAN_EXIT id=(\d+) exception=(.*)$', line)
        if m and int(m[1]) in scans:
            scans[int(m[1])].update({'exit_line': line_no, 'exception': m[2]})
        m = re.match(r'HBASE35 IO door=SCAN_OPEN hit=(\d+) scanId=(\d+) ordinal=(\d+) '
                     r'region=(\S+) regionType=(\S+) matched=(true|false) '
                     r'applied=(true|false) fault=(\w*) thread=(.*)$', line)
        if m:
            io.append({'line': line_no, 'door': 'META_SCAN_OPEN',
                       'global_hit': int(m[1]), 'scan_id': int(m[2]),
                       'ordinal': int(m[3]), 'region': m[4], 'region_type': m[5],
                       'matched': m[6] == 'true', 'applied': m[7] == 'true',
                       'fault': m[8], 'thread': m[9]})
        m = re.match(r'HBASE35 TARGET_ENTER visit=(\d+) scanId=(\d+) '
                     r'row=(.*?) cells=(\d+)$', line)
        if m:
            call = {'enter_line': line_no, 'visit': int(m[1]),
                    'scan_id': int(m[2]), 'row': m[3], 'cells': int(m[4]),
                    'guard': [], 'exit_line': None, 'exception': None}
            targets.append(call)
            active[int(m[1])] = call
        m = re.match(r'HBASE35 GUARD_META_ENTRY visit=(\d+) null=(true|false)$', line)
        if m and int(m[1]) in active:
            active[int(m[1])]['guard'].append({'line': line_no,
                                                'null': m[2] == 'true'})
        m = re.match(r'HBASE35 TARGET_EXIT visit=(\d+) exception=(.*)$', line)
        if m and int(m[1]) in active:
            active[int(m[1])].update({'exit_line': line_no, 'exception': m[2]})
    applied = [event for event in io if event['applied']]
    actual = ['META_SCAN:%d:%d:%s' %
              (event['scan_id'], event['ordinal'], event['fault']) for event in applied]
    last = applied[-1] if applied else None
    same_scan = bool(last) and test_enter == test_exit == 1 and all(
        event['scan_id'] == last['scan_id'] and event['scan_id'] in scans
        and scans[event['scan_id']]['enter_line'] < event['line']
        and scans[event['scan_id']]['exit_line'] is not None
        and event['line'] < scans[event['scan_id']]['exit_line']
        for event in applied)
    post = [call for call in targets if last and same_scan
            and call['scan_id'] == last['scan_id'] and call['exit_line'] is not None
            and call['enter_line'] > last['line']
            and any(guard['line'] > last['line'] for guard in call['guard'])
            and call['exit_line'] < scans[last['scan_id']]['exit_line']]
    selected = [call for call in post if (call['exception'] or '').startswith(SELECTED)]
    other = [call for call in post if call['exception'] not in (None, 'none')
             and call not in selected]
    junit = re.search(r'HBASE35 JUNIT found=(\d+) succeeded=(\d+) '
                      r'failed=(\d+) aborted=(\d+)', raw)
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', raw)
    # r001 predates FAULT_THROW but its applied=true probe immediately precedes
    # the ServiceException throw in the archived agent source. Later rounds also
    # carry a direct throw marker and exact cause class/message.
    direct_throw = [
        'HBASE35 FAULT_THROW scanId=%d ordinal=%d exception=' %
        (event['scan_id'], event['ordinal']) for event in applied]
    throw_evidence = all(marker in raw for marker in direct_throw) or name == 'r001'
    return {'id': name, 'plan': plan, 'requested_fault_events': len(plan.split(',')),
            'matched_fault_events': sum(event['matched'] for event in io),
            'applied_fault_events': len(applied),
            'injected_exception_evidence': bool(applied) and throw_evidence,
            'applied_selector_sequence': actual, 'strict': actual == plan.split(','),
            'same_full_scan_faults': same_scan,
            'observed_io': io, 'full_scan_calls': scans, 'target_calls': targets,
            'post_final_fault_guard_calls': post,
            'post_final_fault_selected_exception_calls': selected,
            'post_final_fault_other_exception_calls': other,
            'target_after_final_fault': bool(post),
            'selected_exception_observed': bool(selected),
            'junit_passed': bool(junit and junit.groups() == ('1', '1', '0', '0')
                                 and exit_code == 0),
            'junit_exit': exit_code,
            'elapsed_seconds': float(elapsed[1]) if elapsed else None,
            'log': 'native/' + name + '.log'}


def healthy_result():
    raw = (HERE / 'healthy_final.log').read_text(errors='replace')
    assert (HERE / 'healthy_final.exit').read_text().strip() == '0'
    assert raw.count('HBASE35 TEST_ENTER method=test') == 1
    assert raw.count('HBASE35 FULL_SCAN_ENTER id=') == 3
    assert raw.count('HBASE35 FULL_SCAN_EXIT id=') == 3
    assert raw.count('HBASE35 TARGET_ENTER visit=') == 3
    assert raw.count('HBASE35 GUARD_META_ENTRY visit=') == 3
    assert raw.count('HBASE35 GUARD_META_ENTRY visit=1 null=true') == 1
    assert 'HBASE35 JUNIT found=1 succeeded=1 failed=0 aborted=0' in raw
    doors = re.findall(r'^HBASE35 IO door=SCAN_OPEN hit=(\d+) scanId=(\d+) '
                       r'ordinal=(\d+) region=(\S+) regionType=(\S+) '
                       r'matched=false applied=false fault=', raw, re.MULTILINE)
    scoped = [(int(x[1]), int(x[2])) for x in doors if int(x[1]) > 0]
    assert scoped == [(1, 1), (2, 1), (3, 1)]
    assert all(x[3] == 'hbase:meta,,1' and x[4] == 'REGION_NAME' for x in doors)
    cov = coverage([HERE / 'healthy_final.exec'])
    assert 'error' not in cov and len(cov['classes']) == 5
    assert cov['target_lines']['2717']['instructions'] > 0
    assert cov['target_lines']['2720']['instructions'] == 0
    data = json.loads(RESULT.read_text())
    data.update({'status': 'running',
        'cluster_test': 'org.apache.hadoop.hbase.util.TestHBaseFsckReplication#test',
        'target_reached': True, 'healthy_junit_passed': True,
        'healthy_guard_marker_count': 3,
        'healthy_guard_values': [True, True, True],
        'healthy_target_guard_line_2717_covered': True,
        'healthy_target_throw_line_2720_covered': False,
        'healthy_observed_io_doors': ['META_SCAN_OPEN'],
        'healthy_scoped_full_scan_open_rpc_count': len(scoped),
        'healthy_elapsed_seconds': float(re.search(r'ELAPSED_SECONDS=([\d.]+)', raw)[1]),
        'healthy_coverage': cov, 'fault_budget': {'trials': 80, 'max_faults_per_trial': 8},
        'fault_trials': 0, 'strict_injections': 0, 'target_after_fault': 0,
        'coverage_gain': 0, 'bug_mark': 'none', 'fault_trial_details': [],
        'issued_plans': [{'id': 'r001', 'plan': seeds()[0],
                          'source': 'observed_meta_scan_open_io_calibration'}],
        'feedback_queue': [], 'feedback_generation_events': [],
        'coverage_type': 'JaCoCo production method/branch/line coverage in five HBase hbck, meta scan, client scanner, and server RPC classes',
        'instrumentation': 'Unchanged original MiniHBaseCluster JUnit; case-local ByteBuddy and JaCoCo; no GraphChecker runtime',
        'selector_scope': 'hbase:meta scan-open RPC within one exact MetaTableAccessor.fullScanRegions invocation; selector identifies full-scan ID and retry ordinal.',
        'target_guard': 'HBaseFsck$3.visit line2717 previous.getMetaEntry()==null',
        'target_exception': SELECTED,
        'baseline_exception_note': 'Original test expects UNDELETED_REPLICATION_QUEUE reports after removing one peer; these are separate from the target duplicate-meta IOException.',
        'evidence': {'healthy_log': 'native/healthy_final.log',
                     'healthy_exec': 'native/healthy_final.exec',
                     'runner': 'native/run.sh',
                     'agent_source': 'native/src/HBase35Agent.java'}})
    save(data)
    return data


def enqueue_feedback(data, item):
    if not (item['strict'] and item['same_full_scan_faults']
            and item['target_after_final_fault'] and item['injected_exception_evidence']):
        return
    reasons = []
    if item['new_production_branches_vs_prior_trials'] > 0:
        reasons.append('new_production_branch')
    if item['new_production_methods_vs_prior_trials'] > 0:
        reasons.append('new_production_method')
    if item['new_io_family']:
        reasons.append('new_observed_io_family')
    if not reasons:
        return
    issued = {entry['plan'] for entry in data['issued_plans']}
    queued = {entry['plan'] for entry in data['feedback_queue']}
    additions = []
    for candidate in mutations(item, data['fault_budget']['max_faults_per_trial']):
        if candidate in issued or candidate in queued:
            continue
        additions.append({'plan': candidate, 'parent': item['id'], 'reason': reasons})
        queued.add(candidate)
    data['feedback_queue'] = additions + data['feedback_queue']
    data['feedback_generation_events'].append({
        'parent': item['id'], 'reason': reasons, 'new_candidates': len(additions)})


def plan_for(data, index):
    name = 'r%03d' % index
    for entry in data['issued_plans']:
        if entry['id'] == name:
            return entry['plan']
    issued = {entry['plan'] for entry in data['issued_plans']}
    while data['feedback_queue']:
        entry = data['feedback_queue'].pop(0)
        if entry['plan'] in issued or len(entry['plan'].split(',')) > data['fault_budget']['max_faults_per_trial']:
            continue
        data['issued_plans'].append({'id': name, 'plan': entry['plan'],
                                    'source': 'production_coverage_or_observed_io_feedback',
                                    'parent': entry['parent'], 'reason': entry['reason']})
        return entry['plan']
    pool = seeds() + (extension_seeds() if data['fault_budget']['trials'] == 128 else [])
    for candidate in pool:
        if candidate not in issued and len(candidate.split(',')) <= data['fault_budget']['max_faults_per_trial']:
            data['issued_plans'].append({'id': name, 'plan': candidate,
                                        'source': 'observed_meta_scan_open_seed'})
            return candidate
    raise RuntimeError('No unique observed-I/O plan for ' + name)


def run_one(name, plan):
    if (HERE / (name + '.exit')).exists():
        return
    env = os.environ.copy()
    env['HBASE35_FAULT_PLAN'] = plan
    with (HERE / (name + '.log')).open('w') as out:
        p = subprocess.run(['bash', str(RUN), 'run', name], env=env,
                           stdout=out, stderr=subprocess.STDOUT)
    (HERE / (name + '.exit')).write_text(str(p.returncode) + '\n')


def main():
    data = json.loads(RESULT.read_text())
    if 'healthy_coverage' not in data:
        data = healthy_result()
    valid_paths = [HERE / 'healthy_final.exec'] + [
        HERE / (item['id'] + '.exec') for item in data['fault_trial_details']
        if item['strict'] and item['same_full_scan_faults']
        and item['target_after_final_fault'] and item['injected_exception_evidence']]
    prior_cov = coverage(valid_paths)
    assert 'error' not in prior_cov
    workers = int(os.environ.get('HBASE35_WORKERS', '3'))
    start = len(data['fault_trial_details']) + 1
    limit = data['fault_budget']['trials']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for i in range(start, min(start + workers, limit + 1)):
            plan = plan_for(data, i)
            save(data)
            futures[i] = pool.submit(run_one, 'r%03d' % i, plan)
        for index in range(start, limit + 1):
            futures.pop(index).result()
            plan = plan_for(data, index)
            item = parse('r%03d' % index, plan)
            exe = HERE / (item['id'] + '.exec')
            item['production_coverage'] = coverage([exe]) if exe.exists() else {'error': 'missing exec'}
            item['target_after_final_fault'] = (item['target_after_final_fault']
                and item['production_coverage'].get('target_lines', {}).get('2717', {})
                .get('instructions', 0) > 0)
            valid = item['strict'] and item['same_full_scan_faults'] \
                and item['target_after_final_fault'] and item['injected_exception_evidence'] \
                and exe.exists()
            if valid:
                union = coverage(valid_paths + [exe])
                assert 'error' not in union
                item['new_production_branches_vs_prior_trials'] = max(
                    0, union['total_branches'] - prior_cov['total_branches'])
                item['new_production_methods_vs_prior_trials'] = max(
                    0, union['total_methods'] - prior_cov['total_methods'])
                prior_cov = union
                valid_paths.append(exe)
            else:
                item['new_production_branches_vs_prior_trials'] = 0
                item['new_production_methods_vs_prior_trials'] = 0
            item['new_io_family'] = False
            item['production_branch_union_valid_feedback'] = prior_cov['total_branches']
            item['bug_mark'] = ('candidate_review' if valid and
                (item['post_final_fault_other_exception_calls'] or
                 item['selected_exception_observed'] or not item['junit_passed'])
                else 'none')
            enqueue_feedback(data, item)
            data['fault_trial_details'].append(item)
            items = data['fault_trial_details']
            data['fault_trials'] = len(items)
            data['strict_injections'] = sum(x['strict'] for x in items)
            data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
            data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
            data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
            data['target_after_fault'] = sum(x['strict'] and x['same_full_scan_faults']
                and x['target_after_final_fault'] and x['injected_exception_evidence']
                for x in items)
            data['selected_exception_trials'] = sum(x['selected_exception_observed'] for x in items)
            data['unexpected_target_exception_trials'] = sum(
                bool(x['post_final_fault_other_exception_calls']) for x in items)
            data['fault_union_production_branches'] = prior_cov['total_branches']
            data['coverage_gain'] = max(0, prior_cov['total_branches']
                                        - data['healthy_coverage']['total_branches'])
            data['elapsed_seconds'] = round(data['healthy_elapsed_seconds'] +
                sum(x['elapsed_seconds'] or 0 for x in items), 2)
            data['bug_mark'] = ('candidate_review' if any(
                x['bug_mark'] == 'candidate_review' for x in items) else 'none')
            save(data)
            if data['bug_mark'] == 'candidate_review':
                for future in futures.values():
                    future.cancel()
                data['status'] = 'candidate_review'
                save(data)
                return
            next_index = index + workers
            if next_index <= limit:
                next_plan = plan_for(data, next_index)
                save(data)
                futures[next_index] = pool.submit(run_one, 'r%03d' % next_index, next_plan)
    if data['fault_trials'] == 80:
        recent = data['fault_trial_details'][-8:]
        fresh = any(x['new_production_branches_vs_prior_trials'] > 0 or
                    x['new_production_methods_vs_prior_trials'] > 0 or x['new_io_family']
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
