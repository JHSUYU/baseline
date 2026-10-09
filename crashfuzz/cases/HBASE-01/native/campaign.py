#!/usr/bin/env python3
"""Resumable graph-independent original-JUnit exception campaign for HBASE-01."""
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
KINDS = ('IOException', 'SocketTimeoutException', 'EOFException', 'ConnectException')


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
            'total_lines': sum(v['lines'] for v in classes.values()),
            'total_methods': sum(v['methods'] for v in classes.values())}


def save(data):
    temp = RESULT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(temp, RESULT)


def plan_string(plan):
    hits = {'GET': 0, 'SCAN': 0}
    items = []
    for door, kind in plan:
        hits[door] += 1
        items.append('%s:%d:%s' % (door, hits[door], kind))
    return ','.join(items)


def plans():
    # Each sequence is distinct. Both doors were seen in the selected healthy request.
    for door in ('GET', 'SCAN'):
        for kind in KINDS:
            yield ((door, kind),)
    for door in ('SCAN', 'GET'):
        for a, b in itertools.product(KINDS, repeat=2):
            yield ((door, a), (door, b))
    for a, b in itertools.product(KINDS, repeat=2):
        yield (('GET', a), ('SCAN', b))
    for a in KINDS:
        yield (('SCAN', a), ('SCAN', a), ('SCAN', a))
        yield (('SCAN', a), ('SCAN', KINDS[(KINDS.index(a) + 1) % 4]), ('SCAN', a))


def extra_plans_to_80():
    # The original JUnit sets five retries per door. Mixed doors can apply eight
    # faults while still leaving a successful fifth attempt at each door.
    for a in KINDS:
        b = KINDS[(KINDS.index(a) + 1) % 4]
        yield tuple([('GET', a)] * 2 + [('SCAN', a)] * 2)
        yield tuple([('GET', a)] * 3 + [('SCAN', b)] * 2)
        yield tuple([('GET', a)] * 3 + [('SCAN', a)] * 3)
        yield tuple([('GET', a)] * 4 + [('SCAN', b)] * 4)


def extension_plans():
    # Six attempts are available at each independent door; the sixth fault at
    # either door loses the target, while five plus five leaves a final success.
    for get_count, scan_count in ((5, 4), (4, 5), (5, 5)):
        for a, b in itertools.product(KINDS, repeat=2):
            yield tuple([('GET', a)] * get_count + [('SCAN', b)] * scan_count)


def parse(name, plan):
    log_path = HERE / (name + '.log')
    exit_path = HERE / (name + '.exit')
    if not exit_path.exists():
        with log_path.open('w') as stream:
            p = subprocess.run(['bash', str(RUN), 'run', name, plan],
                               stdout=stream, stderr=subprocess.STDOUT)
        exit_path.write_text(str(p.returncode) + '\n')
    exit_code = int(exit_path.read_text())
    log = log_path.read_text(errors='replace')
    events = []
    guards = []
    exits = []
    for lineno, line in enumerate(log.splitlines()):
        m = re.search(r'HBASE01 IO door=(GET|SCAN) hit=(\d+) matched=(true|false) '
                      r'applied=(true|false) fault=(\w*) .*thread=(.*)$', line)
        if m:
            events.append({'line': lineno, 'door': m[1], 'hit': int(m[2]),
                           'matched': m[3] == 'true', 'applied': m[4] == 'true',
                           'fault': m[5], 'thread': m[6]})
        m = re.search(r'HBASE01 GUARD_DEAD_SERVER server=(.*?) value=(true|false) '
                      r'exception=(\S+) thread=(.*)$', line)
        if m:
            guards.append({'line': lineno, 'server': m[1], 'value': m[2] == 'true',
                           'exception': m[3], 'thread': m[4]})
        m = re.search(r'HBASE01 TARGET_EXIT exception=(.*?) thread=(.*)$', line)
        if m:
            exits.append({'line': lineno, 'exception': m[1], 'thread': m[2]})
    faults = [e for e in events if e['applied']]
    requested = len(plan.split(','))
    applied_sequence = ['%s:%d:%s' % (e['door'], e['hit'], e['fault']) for e in faults]
    after = ([g for g in guards if g['line'] > faults[-1]['line']
              and g['thread'] == faults[-1]['thread'] and g['exception'] == 'none']
             if faults else [])
    junit = re.search(r'HBASE01 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', log)
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', log)
    return {'id': name, 'plan': plan, 'requested_fault_events': requested,
            'matched_fault_events': sum(e['matched'] for e in events),
            'applied_fault_events': len(faults), 'applied_faults': faults,
            'applied_selector_sequence': applied_sequence,
            'observed_io': events, 'strict': applied_sequence == plan.split(','),
            'target_after_final_fault': bool(after), 'post_fault_guards': after,
            'target_exception_observed': any(g['value'] for g in after),
            'exact_target_exceptions': exits,
            'junit_passed': bool(junit and junit[1] == '1' and junit[3] == '0' and exit_code == 0),
            'junit_exit': exit_code,
            'elapsed_seconds': float(elapsed[1]) if elapsed else None,
            'log': str(log_path.relative_to(CASE))}


def initial_result():
    while not (HERE / 'healthy_final.exit').exists():
        time.sleep(2)
    healthy = parse('healthy_final', '')
    if not healthy['junit_passed'] or not healthy['post_fault_guards'] and not any(
            g['value'] is False and g['exception'] == 'none'
            for g in reparse_healthy_guards()):
        raise RuntimeError('Selected healthy original JUnit did not pass and reach guard')
    healthy_exec = HERE / 'healthy_final.exec'
    cov = coverage([healthy_exec])
    if 'error' in cov:
        raise RuntimeError('Healthy JaCoCo coverage failed: ' + cov['error'])
    data = {
        'case_id': 'HBASE-01', 'status': 'running', 'system': 'HBase 2.6.6',
        'source_file': 'hbase-client/src/main/java/org/apache/hadoop/hbase/client/ConnectionImplementation.java',
        'function': 'ConnectionImplementation.locateRegionInMeta(TableName, byte[], boolean, boolean, int)',
        'selection_line': 1106, 'guard_line': 1104, 'throw_line': 1105,
        'target_exception': 'org.apache.hadoop.hbase.regionserver.RegionServerStoppedException',
        'cluster_test': 'org.apache.hadoop.hbase.client.TestConnectionImplementation#testMetaLookupThreadPoolCreated',
        'cluster_type': 'HBaseTestingUtility MiniHBaseCluster with two region servers',
        'workload': 'Unmodified original JUnit method launched with JUnit Platform',
        'instrumentation': 'Case-local ByteBuddy agent and JaCoCo; no GraphChecker prewoven jar, region skeleton, or static scope map',
        'target_reached': True,
        'healthy_junit_passed': True, 'healthy_target_guard_count': len(reparse_healthy_guards()),
        'healthy_guard_values': [g['value'] for g in reparse_healthy_guards()],
        'healthy_fatal_guard_count': sum(g['value'] for g in reparse_healthy_guards()),
        'healthy_observed_io': healthy['observed_io'],
        'healthy_elapsed_seconds': healthy['elapsed_seconds'], 'healthy_coverage': cov,
        'coverage_type': 'JaCoCo production branch, method and line counts in six HBase classes',
        'fault_budget': {'trials': 64, 'max_faults_per_trial': 6},
        'fault_trials': 0, 'strict_injections': 0, 'target_after_fault': 0,
        'coverage_gain': 0, 'bug_mark': 'none', 'fault_trial_details': [],
        'legacy_graphchecker': {'fault_trials': 3, 'counted_in_native_budget': False,
                                'result_copy': 'native/legacy-graphchecker-result.json',
                                'readme_copy': 'native/legacy-graphchecker-README.md',
                                'origin': 'native/legacy-origin.json'},
        'evidence': {'readme': 'README.md', 'runner': 'native/run.sh',
                     'agent_source': 'native/src/HBase01Agent.java',
                     'healthy_log': 'native/healthy_final.log',
                     'healthy_exec': 'native/healthy_final.exec'},
    }
    save(data)
    return data


def reparse_healthy_guards():
    log = (HERE / 'healthy_final.log').read_text(errors='replace')
    return [{'value': m[1] == 'true', 'exception': m[2]}
            for m in re.finditer(r'HBASE01 GUARD_DEAD_SERVER .*? value=(true|false) exception=(\S+)', log)]


def main():
    data = json.loads(RESULT.read_text()) if RESULT.exists() else None
    if not data or 'legacy_graphchecker' not in data:
        data = initial_result()
    if data['fault_budget']['trials'] < 80:
        data['fault_budget'] = {'trials': 80, 'max_faults_per_trial': 8,
                                'observed_attempt_cap_per_door': 6}
        data['status'] = 'running'
        data['campaign_finished'] = False
        data.pop('stop_reason', None)
        save(data)
    plan_list = list(plans()) + list(extra_plans_to_80())
    assert len(plan_list) == 80 and len({plan_string(p) for p in plan_list}) == 80
    extended = data.get('fault_budget', {}).get('trials') == 128
    if extended:
        plan_list.extend(list(extension_plans()))
    accepted_paths = [HERE / 'healthy_final.exec']
    prior_branches = data['healthy_coverage']['total_branches']
    prior_methods = data['healthy_coverage']['total_methods']
    for item in data['fault_trial_details']:
        if item['strict'] and item['target_after_final_fault']:
            accepted_paths.append(HERE / (item['id'] + '.exec'))
    if len(accepted_paths) > 1:
        prior_union = coverage(accepted_paths)
        prior_branches = prior_union['total_branches']
        prior_methods = prior_union['total_methods']
    for index, plan in enumerate(plan_list[len(data['fault_trial_details']):],
                                 len(data['fault_trial_details']) + 1):
        if index > data['fault_budget']['trials']:
            break
        name = 'r%03d' % index
        item = parse(name, plan_string(plan))
        execution = HERE / (name + '.exec')
        item['production_coverage'] = coverage([execution]) if execution.exists() else {'error': 'missing exec'}
        valid_feedback = item['strict'] and item['target_after_final_fault'] and execution.exists()
        if valid_feedback:
            trial_union = coverage(accepted_paths + [execution])
            item['new_production_branches_vs_prior_trials'] = max(
                0, trial_union['total_branches'] - prior_branches)
            item['new_production_methods_vs_prior_trials'] = max(
                0, trial_union['total_methods'] - prior_methods)
            prior_branches = trial_union['total_branches']
            prior_methods = trial_union['total_methods']
            accepted_paths.append(execution)
        else:
            item['new_production_branches_vs_prior_trials'] = 0
            item['new_production_methods_vs_prior_trials'] = 0
        item['production_branch_union_valid_feedback'] = prior_branches
        item['new_io_family'] = False
        data['fault_trial_details'].append(item)
        items = data['fault_trial_details']
        data['fault_trials'] = len(items)
        data['strict_injections'] = sum(x['strict'] for x in items)
        data['requested_fault_events'] = sum(x['requested_fault_events'] for x in items)
        data['matched_fault_events'] = sum(x['matched_fault_events'] for x in items)
        data['applied_fault_events'] = sum(x['applied_fault_events'] for x in items)
        data['target_after_fault'] = sum(x['target_after_final_fault'] for x in items)
        data['fatal_target_trials'] = sum(x['target_exception_observed']
                                          and x['target_after_final_fault'] for x in items)
        data['lost_target_trials'] = sum(x['strict'] and not x['target_after_final_fault'] for x in items)
        data['fault_union_production_branches'] = prior_branches
        data['coverage_gain'] = max(0, prior_branches - data['healthy_coverage']['total_branches'])
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
        if index == 80:
            recent = items[-8:]
            fresh = any(x['new_production_branches_vs_prior_trials'] > 0
                        or x['new_production_methods_vs_prior_trials'] > 0
                        or x['new_io_family']
                        for x in recent)
            data['extension_decision'] = {'fresh_coverage_or_io_in_trials_73_to_80': fresh,
                                          'recent_new_production_branches': sum(
                                              x['new_production_branches_vs_prior_trials']
                                              for x in recent),
                                          'recent_new_production_methods': sum(
                                              x['new_production_methods_vs_prior_trials']
                                              for x in recent)}
            if fresh:
                data['fault_budget'] = {'trials': 128, 'max_faults_per_trial': 10,
                                        'candidate_depth_cap': 10,
                                        'observed_attempt_cap_per_door': 6}
            save(data)
            if fresh:
                return main()
    data['status'] = 'quality_complete'
    data['campaign_finished'] = True
    data['stop_reason'] = ('Completed conditional 128-trial budget' if extended
                           else 'Completed 80-trial budget; no new valid production method/branch coverage or I/O family near limit')
    save(data)


if __name__ == '__main__':
    main()
