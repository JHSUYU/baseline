#!/usr/bin/env python3
"""Observed SASL I/O faults in the unchanged original HBase cluster JUnit."""
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


def selector(kinds, first=1):
    return ','.join('SASL_IN:%d:%s' % (i, kind)
                    for i, kind in enumerate(kinds, first))


def seeds():
    first = ['SASL_IN:2:IOException', 'SASL_IN:1:IOException',
             selector(('IOException',) * 4), selector(('IOException',) * 8)]
    rng = random.Random(34)
    pool = []
    for kind in KINDS:
        pool.extend(('SASL_IN:1:' + kind, 'SASL_IN:2:' + kind))
    for length in (2, 3, 4, 5, 6):
        candidates = [selector(values) for values in itertools.product(KINDS, repeat=length)]
        rng.shuffle(candidates)
        pool.extend(candidates[:{2: 16, 3: 32, 4: 24, 5: 12, 6: 8}[length]])
    out = list(dict.fromkeys(first + pool))[:80]
    assert len(out) == 80 and len(set(out)) == 80
    assert all(len(x.split(',')) <= 8 for x in out)
    return out


def extension_seeds():
    rng = random.Random(340128)
    pool = [selector(values) for values in itertools.product(KINDS, repeat=5)]
    rng.shuffle(pool)
    out = [x for x in pool if x not in seeds()][:48]
    assert len(out) == 48
    return out


def mutations(item, limit):
    steps = [(int(hit), kind) for hit, kind in
             (part.split(':')[1:] for part in item['plan'].split(','))]
    variants = []
    for kind in KINDS:
        variants.append(steps[:-1] + [(steps[-1][0], kind)])
        variants.append([(steps[0][0], kind)] + steps[1:])
        if len(steps) < limit:
            variants.append(steps + [(steps[-1][0] + 1, kind)])
            if steps[0][0] > 1:
                variants.append([(steps[0][0] - 1, kind)] + steps)
    if len(steps) > 1:
        variants.append(steps[1:] + steps[:1])
    plans = []
    for values in variants:
        hits = [hit for hit, _ in values]
        if len(values) > limit or hits != sorted(set(hits)):
            continue
        plans.append(','.join('SASL_IN:%d:%s' % step for step in values))
    return list(dict.fromkeys(plans))


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
    lines = (HERE / (name + '.log')).read_text(errors='replace').splitlines()
    exit_code = int((HERE / (name + '.exit')).read_text())
    io, targets = [], []
    test_enter = test_exit = token_enter = token_exit = whoami = 0
    scope_start = scope_end = token_start = token_end = -1
    for line_no, line in enumerate(lines):
        if line.startswith('HBASE34 TEST_ENTER method=testOnlyToken'):
            test_enter += 1
            scope_start = line_no
        elif line.startswith('HBASE34 TEST_EXIT exception='):
            test_exit += 1
            scope_end = line_no
        elif line == 'HBASE34 TEST_TOKEN_ENTER':
            token_enter += 1
            token_start = line_no
        elif line.startswith('HBASE34 TEST_TOKEN_EXIT exception='):
            token_exit += 1
            token_end = line_no
        elif line.startswith('HBASE34 WHOAMI_SERVICE_ENTER'):
            whoami += 1
        m = re.match(r'HBASE34 IO door=SASL_IN hit=(\d+) channel=(\S+) bytes=(\d+) '
                     r'applied=(true|false) fault=(\w*) thread=(.*)$', line)
        if m:
            io.append({'line': line_no, 'door': 'SASL_IN', 'hit': int(m[1]),
                       'channel': m[2], 'bytes': int(m[3]),
                       'applied': m[4] == 'true', 'fault': m[5], 'thread': m[6],
                       'family': 'SASL_IN:' + ('empty' if int(m[3]) == 0 else 'credential')})
        m = re.match(r'HBASE34 TARGET_ENTER keyId=(\d+) keyPresent=(true|false) '
                     r'channel=(\S+) thread=(.*)$', line)
        if m:
            targets.append({'enter_line': line_no, 'key_id': int(m[1]),
                            'key_present': m[2] == 'true', 'channel': m[3],
                            'thread': m[4], 'exit_line': None, 'exception': None})
        m = re.match(r'HBASE34 TARGET_EXIT exception=(.*)$', line)
        if m:
            for call in reversed(targets):
                if call['exit_line'] is None:
                    call['exit_line'] = line_no
                    call['exception'] = m[1]
                    break
    applied = [event for event in io if event['applied']]
    actual = ['SASL_IN:%d:%s' % (event['hit'], event['fault']) for event in applied]
    last = applied[-1] if applied else None
    post = [call for call in targets if last and call['enter_line'] > last['line']
            and call['key_id'] == 1 and call['exit_line'] is not None]
    selected = [call for call in post if call['exception'] and
                'Unknown master key for token' in call['exception']]
    other = [call for call in post if call['exception'] not in (None, 'none')
             and call not in selected]
    junit = re.search(r'HBASE34 JUNIT found=(\d+) succeeded=(\d+) '
                      r'failed=(\d+) aborted=(\d+)', '\n'.join(lines))
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', '\n'.join(lines))
    same_request = bool(last) and test_enter == test_exit == 1 and token_enter == token_exit == 1 \
        and whoami == 1 and scope_start < token_start < last['line'] < token_end < scope_end \
        and all(token_start < event['line'] < token_end for event in applied)
    return {'id': name, 'plan': plan, 'requested_fault_events': len(plan.split(',')),
            'matched_fault_events': len(applied), 'applied_fault_events': len(applied),
            'applied_selector_sequence': actual, 'strict': actual == plan.split(','),
            'same_logical_whoami_request': same_request,
            'test_body_entries': test_enter, 'test_body_exits': test_exit,
            'test_token_entries': token_enter, 'test_token_exits': token_exit,
            'whoami_service_entries': whoami, 'observed_io': io,
            'target_calls': targets, 'post_final_fault_target_calls': post,
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
    log = (HERE / 'healthy_ident.log').read_text(errors='replace')
    assert (HERE / 'healthy_ident.exit').read_text().strip() == '0'
    assert log.count('HBASE34 TEST_ENTER method=testOnlyToken') == 1
    assert log.count('HBASE34 TEST_TOKEN_ENTER') == 1
    assert log.count('HBASE34 WHOAMI_SERVICE_ENTER') == 1
    assert log.count('HBASE34 TARGET_ENTER keyId=1 keyPresent=true') == 1
    assert 'HBASE34 JUNIT found=1 succeeded=1 failed=0 aborted=0' in log
    events = re.findall(r'^HBASE34 IO door=SASL_IN hit=(\d+) channel=(\S+) bytes=(\d+) '
                        r'applied=false fault=', log, re.MULTILINE)
    assert len(events) == 2 and [int(x[0]) for x in events] == [1, 2]
    assert events[0][1] == events[1][1] and [int(x[2]) for x in events] == [0, 318]
    cov = coverage([HERE / 'healthy_ident.exec'])
    assert 'error' not in cov and len(cov['classes']) >= 5
    assert cov['target_lines']['159']['instructions'] > 0
    assert cov['target_lines']['160']['instructions'] == 0
    data = json.loads(RESULT.read_text())
    data.update({'status': 'running', 'cluster_test':
        'org.apache.hadoop.hbase.security.token.TestGenerateDelegationToken#testOnlyToken',
        'target_reached': True, 'healthy_junit_passed': True,
        'healthy_target_guard_line_159_covered': True,
        'healthy_target_throw_line_160_covered': False,
        'healthy_target_key_present': True,
        'healthy_io_channel': events[0][1],
        'healthy_observed_io_families': ['SASL_IN:empty', 'SASL_IN:credential'],
        'healthy_observed_sasl_inbound_count': 2,
        'healthy_elapsed_seconds': float(re.search(r'ELAPSED_SECONDS=([\d.]+)', log)[1]),
        'healthy_coverage': cov, 'fault_budget': {'trials': 80, 'max_faults_per_trial': 8},
        'fault_trials': 0, 'strict_injections': 0, 'target_after_fault': 0,
        'coverage_gain': 0, 'bug_mark': 'none', 'fault_trial_details': [],
        'issued_plans': [{'id': 'r001', 'plan': seeds()[0],
                          'source': 'observed_sasl_credential_io_calibration'}],
        'feedback_queue': [], 'feedback_generation_events': [],
        'coverage_type': 'JaCoCo production method/branch/line coverage in five HBase token authentication server classes',
        'instrumentation': 'Unchanged original JUnit; case-local ByteBuddy and JaCoCo; no GraphChecker runtime',
        'selector_scope': 'SASL inbound network frames during sole original testToken call, with one whoAmI service request; event indices are exact and ordered.',
        'target_guard': 'AuthenticationTokenSecretManager.retrievePassword line159 masterKey == null',
        'target_exception': 'InvalidToken:Unknown master key for token',
        'baseline_exception_note': 'Original test expects AccessDeniedException from requesting a new token while using token authentication; this is outside retrievePassword.',
        'evidence': {'healthy_log': 'native/healthy_ident.log',
                     'healthy_exec': 'native/healthy_ident.exec',
                     'runner': 'native/run.sh',
                     'agent_source': 'native/src/HBase34Agent.java'}})
    save(data)
    return data


def enqueue_feedback(data, item):
    if not (item['strict'] and item['same_logical_whoami_request']
            and item['target_after_final_fault']):
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
        entry = data['feedback_queue'].pop(0)
        if entry['plan'] in issued or len(entry['plan'].split(',')) > data['fault_budget']['max_faults_per_trial']:
            continue
        data['issued_plans'].append({'id': name, 'plan': entry['plan'],
                                    'source': 'production_coverage_or_observed_io_feedback',
                                    'parent': entry['parent'], 'reason': entry['reason']})
        return entry['plan']
    pool = seeds() + (extension_seeds() if data['fault_budget']['trials'] == 128 else [])
    for plan in pool:
        if plan not in issued and len(plan.split(',')) <= data['fault_budget']['max_faults_per_trial']:
            data['issued_plans'].append({'id': name, 'plan': plan,
                                        'source': 'observed_sasl_inbound_seed'})
            return plan
    raise RuntimeError('No unique observed-I/O plan for ' + name)


def run_one(name, plan):
    if (HERE / (name + '.exit')).exists():
        return
    env = os.environ.copy()
    env['HBASE34_FAULT_PLAN'] = plan
    with (HERE / (name + '.log')).open('w') as out:
        p = subprocess.run(['bash', str(RUN), 'run', name], env=env,
                           stdout=out, stderr=subprocess.STDOUT)
    (HERE / (name + '.exit')).write_text(str(p.returncode) + '\n')


def main():
    data = json.loads(RESULT.read_text())
    if 'healthy_coverage' not in data:
        data = healthy_result()
    valid_paths = [HERE / 'healthy_ident.exec'] + [
        HERE / (item['id'] + '.exec') for item in data['fault_trial_details']
        if item['strict'] and item['same_logical_whoami_request']
        and item['target_after_final_fault']]
    prior_cov = coverage(valid_paths)
    assert 'error' not in prior_cov
    seen_io = set(data['healthy_observed_io_families'])
    for item in data['fault_trial_details']:
        if item['strict'] and item['same_logical_whoami_request'] and item['target_after_final_fault']:
            seen_io.update(event['family'] for event in item['observed_io'])
    workers = int(os.environ.get('HBASE34_WORKERS', '3'))
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
            guarded = any(call['exception'] == 'none' or
                          'Unknown master key for token' in (call['exception'] or '')
                          for call in item['post_final_fault_target_calls'])
            item['target_after_final_fault'] = (item['target_after_final_fault'] and guarded
                and item['production_coverage'].get('target_lines', {}).get('159', {})
                .get('instructions', 0) > 0)
            valid = item['strict'] and item['same_logical_whoami_request'] \
                and item['target_after_final_fault'] and exe.exists()
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
            families = {event['family'] for event in item['observed_io']}
            item['new_io_family'] = bool(valid and families - seen_io)
            if valid:
                seen_io.update(families)
            item['production_branch_union_valid_feedback'] = prior_cov['total_branches']
            item['bug_mark'] = ('candidate_review' if valid and
                (item['post_final_fault_other_exception_calls'] or not item['junit_passed'])
                else 'none')
            enqueue_feedback(data, item)
            data['fault_trial_details'].append(item)
            items = data['fault_trial_details']
            data['fault_trials'] = len(items)
            data['strict_injections'] = sum(x['strict'] for x in items)
            data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
            data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
            data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
            data['target_after_fault'] = sum(x['strict'] and x['same_logical_whoami_request']
                                             and x['target_after_final_fault'] for x in items)
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
