#!/usr/bin/env python3
"""Original MiniHBaseCluster JUnit with request-scoped Open RPC faults."""
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
TEST = ('org.apache.hadoop.hbase.master.assignment.TestExceptionInAssignRegion',
        'testExceptionInAssignRegion')
KINDS = ('DoNotRetryIOException', 'IOException', 'ConnectException',
         'SocketTimeoutException', 'EOFException')
SELECTED_EXCEPTION = 'org.apache.hadoop.hbase.HBaseIOException:Failed confirm OPEN of '


def selector(kinds):
    return ','.join('OPEN_RPC:%d:%s' % (i, kind)
                    for i, kind in enumerate(kinds, 1))


def plans():
    out = [selector((KINDS[0],)), selector((KINDS[0],) * 4)]
    out.extend(selector((kind,)) for kind in KINDS[1:])
    out.extend(selector(pair) for pair in itertools.product(KINDS, repeat=2))
    rng = random.Random(18)
    fours = list(itertools.product(KINDS, repeat=4))
    out.extend(selector(item) for item in rng.sample(
        [item for item in fours if item != (KINDS[0],) * 4], 30))
    eights = [item * 2 for item in fours]
    out.extend(selector(item) for item in rng.sample(eights, 18))
    out.append(selector((KINDS[0],) * 8))
    assert len(out) == 80 and len(set(out)) == 80
    assert all(len(item.split(',')) <= 8 for item in out)
    return out


def extension_plans():
    rng = random.Random(12818)
    fives = list(itertools.product(KINDS, repeat=5))
    out = [selector(item * 2) for item in rng.sample(fives, 48)]
    assert len(set(out)) == 48 and not set(out) & set(plans())
    return out


def mutations(item, max_faults):
    """Prioritize nearby ordered I/O sequences after valid production feedback."""
    kinds = [step.rsplit(':', 1)[-1] for step in item['plan'].split(',')]
    variants = []
    for kind in KINDS:
        if len(kinds) < max_faults:
            variants.append(kinds + [kind])
            variants.append([kind] + kinds)
        variants.append(kinds[:-1] + [kind])
        variants.append([kind] + kinds[1:])
    if len(kinds) * 2 <= max_faults:
        variants.append(kinds * 2)
    if len(kinds) > 1:
        variants.append(kinds[1:] + kinds[:1])
    if item['selected_exception_observed']:
        variants.append([KINDS[0]] * min(max_faults, len(kinds) + 1))
    return list(dict.fromkeys(selector(value) for value in variants
                              if 1 <= len(value) <= max_faults))


def enqueue_feedback(data, item):
    valid = item['strict'] and item['same_request_faults'] and item['target_after_final_fault']
    if not valid:
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
    if item['selected_exception_observed']:
        reasons.append('selected_recovery_branch')
    issued = {entry['plan'] for entry in data['issued_plans']}
    queued = {entry['plan'] for entry in data['feedback_queue']}
    additions = []
    for plan in mutations(item, data['fault_budget']['max_faults_per_trial']):
        if plan in issued or plan in queued:
            continue
        additions.append({'plan': plan, 'parent': item['id'], 'reason': reasons})
        queued.add(plan)
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
        candidate = data['feedback_queue'].pop(0)
        if (candidate['plan'] in issued or
                len(candidate['plan'].split(',')) > data['fault_budget']['max_faults_per_trial']):
            continue
        data['issued_plans'].append({'id': name, 'plan': candidate['plan'],
                                    'source': 'coverage_feedback',
                                    'parent': candidate['parent'],
                                    'reason': candidate['reason']})
        return candidate['plan']
    seeds = plans() + (extension_plans() if data['fault_budget']['trials'] == 128 else [])
    for plan in seeds:
        if plan not in issued and len(plan.split(',')) <= data['fault_budget']['max_faults_per_trial']:
            data['issued_plans'].append({'id': name, 'plan': plan,
                                        'source': 'observed_io_seed'})
            return plan
    raise RuntimeError('No unique observed-I/O candidate remains for ' + name)


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
            'total_branches': sum(value['branches'] for value in classes.values()),
            'total_methods': sum(value['methods'] for value in classes.values()),
            'total_lines': sum(value['lines'] for value in classes.values())}


def save(data):
    temp = RESULT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(temp, RESULT)


def run_one(name, plan):
    exit_path = HERE / (name + '.exit')
    if exit_path.exists():
        return
    env = os.environ.copy()
    env['HBASE18_TARGET_TABLE'] = 'test'
    env['HBASE18_FAULT_PLAN'] = plan
    with (HERE / (name + '.log')).open('w') as output:
        p = subprocess.run(['bash', str(RUN), 'run', name, *TEST], env=env,
                           stdout=output, stderr=subprocess.STDOUT)
    exit_path.write_text(str(p.returncode) + '\n')


def parse(name, plan):
    lines = (HERE / (name + '.log')).read_text(errors='replace').splitlines()
    exit_code = int((HERE / (name + '.exit')).read_text())
    children, io, calls, active = {}, [], [], {}
    test_enter, test_exit = [], []
    for line_no, line in enumerate(lines):
        m = re.search(r'Initialized subprocedures=\[\{pid=(\d+), ppid=(\d+), '
                      r'state=[^;]+; OpenRegionProcedure ([0-9a-f]{32})', line)
        if m:
            value = {'parent': int(m[2]), 'region': m[3]}
            prior = children.setdefault(int(m[1]), value)
            assert prior == value
        if line.startswith('HBASE18 TEST_ENTER '):
            test_enter.append(line_no)
        if line.startswith('HBASE18 TEST_EXIT '):
            test_exit.append(line_no)
        m = re.match(r'HBASE18 IO door=OPEN_RPC hit=(\d+) table=(\w+) regionId=(\d+) '
                     r'openProcId=(\d+) matched=(true|false) applied=(true|false) '
                     r'fault=(\w*) thread=(.*)$', line)
        if m:
            io.append({'line': line_no, 'door': 'OPEN_RPC', 'hit': int(m[1]),
                       'table': m[2], 'region_id': int(m[3]),
                       'open_proc': int(m[4]), 'matched': m[5] == 'true',
                       'applied': m[6] == 'true', 'fault': m[7], 'thread': m[8]})
        m = re.match(r'HBASE18 TARGET_ENTER proc=(\d+) region=([0-9a-f]+) '
                     r'regionId=(\d+) state=(\w+) thread=(.*)$', line)
        if m:
            key = (int(m[1]), m[2], m[5])
            active.setdefault(key, []).append({'enter_line': line_no,
                'proc': int(m[1]), 'region': m[2], 'region_id': int(m[3]),
                'state': m[4], 'thread': m[5], 'guard': []})
        m = re.match(r'HBASE18 GUARD_MAX proc=(\d+) region=([0-9a-f]+) '
                     r'max=(\d+) thread=(.*)$', line)
        if m:
            key = (int(m[1]), m[2], m[4])
            if active.get(key):
                active[key][-1]['guard'].append({'line': line_no, 'max': int(m[3])})
        m = re.match(r'HBASE18 TARGET_EXIT flow=(\S+) exception=(.*?) '
                     r'proc=(\d+) region=([0-9a-f]+) thread=(.*)$', line)
        if m:
            key = (int(m[3]), m[4], m[5])
            if active.get(key):
                call = active[key].pop(0)
                call.update({'exit_line': line_no, 'flow': m[1], 'exception': m[2]})
                calls.append(call)
    for event in io:
        event['parent_proc'] = children.get(event['open_proc'], {}).get('parent')
        event['region'] = children.get(event['open_proc'], {}).get('region')
    applied_events = [event for event in io if event['applied']]
    applied = ['OPEN_RPC:%d:%s' % (event['hit'], event['fault'])
               for event in applied_events]
    last = applied_events[-1] if applied_events else None
    same_request = bool(last) and all(
        event['parent_proc'] is not None
        and event['parent_proc'] == last['parent_proc']
        and event['region'] == last['region']
        and event['region_id'] == last['region_id']
        for event in applied_events)
    post = [call for call in calls if last and same_request
            and call['proc'] == last['parent_proc']
            and call['region'] == last['region']
            and call['region_id'] == last['region_id']
            and any(guard['line'] > last['line'] for guard in call['guard'])]
    selected = [call for call in post
                if call['exception'].startswith(SELECTED_EXCEPTION)]
    other = [call for call in post if call['exception'] != 'none'
             and not call['exception'].startswith(SELECTED_EXCEPTION)]
    junit = re.search(r'HBASE18 JUNIT found=(\d+) succeeded=(\d+) '
                      r'failed=(\d+) aborted=(\d+)', '\n'.join(lines))
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', '\n'.join(lines))
    return {'id': name, 'plan': plan, 'requested_fault_events': len(plan.split(',')),
            'matched_fault_events': sum(event['matched'] for event in io),
            'applied_fault_events': len(applied_events),
            'applied_selector_sequence': applied, 'strict': applied == plan.split(','),
            'same_request_faults': same_request, 'test_enter_lines': test_enter,
            'test_exit_lines': test_exit, 'observed_io': io, 'child_parent_map': children,
            'target_calls': calls, 'target_entries': len(calls),
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
    log = (HERE / 'healthy_counted.log').read_text(errors='replace')
    assert int((HERE / 'healthy_counted.exit').read_text()) == 0
    assert 'HBASE18 JUNIT found=1 succeeded=1 failed=0 aborted=0' in log
    assert log.count('HBASE18 TEST_ENTER method=testExceptionInAssignRegion') == 1
    assert log.count('HBASE18 TEST_EXIT exception=none') == 1
    doors = re.findall(r'^HBASE18 IO door=OPEN_RPC hit=(\d+) table=test '
                       r'regionId=(\d+) openProcId=(\d+)', log, re.MULTILINE)
    assert len(doors) == 2 and [int(x[0]) for x in doors] == [1, 2]
    assert len({x[1] for x in doors}) == 1
    guard = re.findall(r'^HBASE18 GUARD_MAX proc=(\d+) region=([0-9a-f]+) '
                       r'max=(\d+) thread=', log, re.MULTILINE)
    assert len(guard) == 1 and guard[0][2] == '3'
    assert SELECTED_EXCEPTION not in log
    cov = coverage([HERE / 'healthy_counted.exec'])
    assert 'error' not in cov
    assert len(cov['classes']) == 8
    assert cov['target_lines']['323']['instructions'] > 0
    assert cov['target_lines']['325']['instructions'] == 0
    elapsed = float(re.search(r'ELAPSED_SECONDS=([\d.]+)', log)[1])
    data = json.loads(RESULT.read_text())
    data.update({'status': 'running', 'cluster_test': TEST[0] + '#' + TEST[1],
        'original_mapping_test': 'TestTransitRegionStateProcedure#testRecoveryAndDoubleExecutionUnassignAndAssign',
        'original_mapping_healthy_guard_reached': False,
        'original_mapping_note': 'Original mapped MiniCluster JUnit passed but target line 323 and throw line 325 were uncovered; its three selected-table confirmOpened calls entered OPEN.',
        'target_reached': True, 'healthy_junit_passed': True,
        'healthy_guard_marker_count': len(guard),
        'healthy_guard_max': int(guard[0][2]),
        'healthy_selected_exception_observed': False,
        'healthy_target_guard_line_323_covered': True,
        'healthy_target_throw_line_325_covered': False,
        'healthy_observed_io_doors': ['OPEN_RPC'],
        'healthy_observed_test_body_open_rpc_count': len(doors),
        'healthy_elapsed_seconds': elapsed, 'healthy_coverage': cov,
        'fault_budget': {'trials': 80, 'max_faults_per_trial': 8},
        'fault_trials': 0, 'strict_injections': 0, 'target_after_fault': 0,
        'coverage_gain': 0, 'bug_mark': 'none', 'fault_trial_details': [],
        'coverage_type': 'JaCoCo selected production methods/branches/lines in eight HBase master assignment/dispatch classes',
        'instrumentation': 'Unchanged original JUnit, case-local ByteBuddy and JaCoCo; no GraphChecker runtime',
        'target_guard': 'TransitRegionStateProcedure.confirmOpened:323 retries > immediate max',
        'target_exception': SELECTED_EXCEPTION,
        'baseline_exception_note': 'Original test deliberately throws in its region preOpen coprocessor once; selected confirmOpened HBaseIOException is absent in healthy execution.',
        'selector_scope': 'Only OpenRegion RPC requests for table test while original testExceptionInAssignRegion method is active, with child OpenRegionProcedure mapped to parent TRSP and encoded region.',
        'evidence': {'healthy_log': 'native/healthy_counted.log',
                     'healthy_exec': 'native/healthy_counted.exec',
                     'runner': 'native/run.sh',
                     'agent_source': 'native/src/HBase18Agent.java'}})
    save(data)
    return data


def main():
    data = json.loads(RESULT.read_text())
    if 'healthy_coverage' not in data:
        data = healthy_result()
    if 'issued_plans' not in data:
        # Preserve the exact first queue already issued by the seed-only runner.
        completed_files = [i for i in range(1, 81)
                           if (HERE / ('r%03d.exit' % i)).exists()]
        last_issued = max(completed_files + [len(data['fault_trial_details'])])
        assert completed_files == list(range(1, last_issued + 1))
        data['issued_plans'] = [
            {'id': 'r%03d' % i, 'plan': plans()[i - 1],
             'source': 'initial_observed_io_seed_before_adaptive_switch'}
            for i in range(1, last_issued + 1)]
        data['feedback_queue'] = []
        data['feedback_generation_events'] = []
        data['adaptive_switch'] = {
            'ledger_completed_before_switch': len(data['fault_trial_details']),
            'already_issued_seed_trials': last_issued,
            'aborted_unfinished_prefetch': ['r061', 'r062'],
            'policy': 'After the preserved issued queue, prioritize unique mutations of valid trials with new production method/branch, new observed I/O family, or selected recovery branch; then draw the next unused deterministic observed-I/O seed.'}
        for prior in data['fault_trial_details']:
            enqueue_feedback(data, prior)
        save(data)
    if 'adaptive_queue_refinement' not in data:
        prior_queue = data['feedback_queue']
        productive = [entry for entry in prior_queue if any(
            reason in entry['reason'] for reason in
            ('new_production_branch', 'new_production_method',
             'new_observed_io_family'))]
        productive.sort(key=lambda entry: int(entry['parent'][1:]), reverse=True)
        data['feedback_queue'] = productive
        data['adaptive_queue_refinement'] = {
            'ledger_completed_before_refinement': len(data['fault_trial_details']),
            'already_issued_plans_preserved': len(data['issued_plans']),
            'queued_before': len(prior_queue),
            'queued_after': len(productive),
            'discarded_selected_recovery_only': len(prior_queue) - len(productive),
            'policy': 'Preserve already issued plans; use unique mutations only after valid new production method/branch or observed I/O family, newest feedback parent first; selected recovery alone does not generate candidates.'}
        save(data)
    prior_paths = [HERE / 'healthy_counted.exec'] + [
        HERE / (item['id'] + '.exec') for item in data['fault_trial_details']
        if item['strict'] and item['same_request_faults']
        and item['target_after_final_fault']]
    prior_cov = coverage(prior_paths)
    workers = int(os.environ.get('HBASE18_WORKERS', '3'))
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
            item = parse('r%03d' % index, plan_for(data, index))
            exe = HERE / (item['id'] + '.exec')
            item['production_coverage'] = coverage([exe]) if exe.exists() else {'error': 'missing exec'}
            valid = (item['strict'] and item['same_request_faults']
                     and item['target_after_final_fault'] and exe.exists())
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
            item['new_io_family'] = any(
                event['door'] not in data['healthy_observed_io_doors']
                for event in item['observed_io'])
            item['production_branch_union_valid_feedback'] = prior_cov['total_branches']
            item['bug_mark'] = ('candidate_review' if valid
                and (item['post_final_fault_other_exception_calls'] or not item['junit_passed'])
                else 'none')
            enqueue_feedback(data, item)
            data['fault_trial_details'].append(item)
            items = data['fault_trial_details']
            data['fault_trials'] = len(items)
            data['strict_injections'] = sum(x['strict'] for x in items)
            data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
            data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
            data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
            data['target_after_fault'] = sum(x['strict'] and x['same_request_faults']
                                             and x['target_after_final_fault'] for x in items)
            data['lost_target_trials'] = sum(x['strict'] and x['same_request_faults']
                                              and not x['target_after_final_fault'] for x in items)
            data['selected_exception_trials'] = sum(
                x['strict'] and x['same_request_faults']
                and x['target_after_final_fault'] and x['selected_exception_observed']
                for x in items)
            data['unexpected_target_exception_trials'] = sum(
                x['strict'] and x['same_request_faults']
                and x['target_after_final_fault']
                and bool(x['post_final_fault_other_exception_calls']) for x in items)
            data['fault_union_production_branches'] = prior_cov['total_branches']
            data['coverage_gain'] = max(0, prior_cov['total_branches']
                                        - data['healthy_coverage']['total_branches'])
            data['elapsed_seconds'] = round(data['healthy_elapsed_seconds']
                + sum(x['elapsed_seconds'] or 0 for x in items), 2)
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
                futures[next_index] = pool.submit(run_one, 'r%03d' % next_index,
                                                  next_plan)
    if data['fault_trials'] == 80:
        recent = data['fault_trial_details'][-8:]
        fresh = any(x['new_production_branches_vs_prior_trials'] > 0
                    or x['new_production_methods_vs_prior_trials'] > 0
                    or x['new_io_family'] for x in recent)
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
