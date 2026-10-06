#!/usr/bin/env python3
"""Bounded graph-free trials; atomically publish one case result after each run."""
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
RESULT = HERE.parent / 'result.json'
RUN = HERE / 'run.sh'
KINDS = ['IOException', 'SocketTimeoutException', 'EOFException', 'ConnectException']


def coverage(paths):
    proc = subprocess.run(['bash', str(RUN), 'coverage', ','.join(map(str, paths))],
                          capture_output=True, text=True, check=False)
    if proc.returncode:
        return {'error': proc.stderr[-1000:]}
    classes = {}
    target = {}
    for line in proc.stdout.splitlines():
        m = re.match(r'COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)', line)
        if m:
            classes[m.group(1).rsplit('/', 1)[-1]] = {
                'methods': int(m.group(2)), 'branches': int(m.group(3)),
                'lines': int(m.group(4))}
        m = re.match(r'COVERAGE line=(\d+) instructions=(\d+)(?: branches=(\d+))?', line)
        if m:
            target[m.group(1)] = {'instructions': int(m.group(2)),
                                  'branches': int(m.group(3) or 0)}
    return {'classes': classes, 'target_lines': target,
            'total_branches': sum(x['branches'] for x in classes.values()),
            'total_lines': sum(x['lines'] for x in classes.values()),
            'total_methods': sum(x['methods'] for x in classes.values())}


def save(data):
    tmp = RESULT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, RESULT)


def parse_run(name, plan, execute=True):
    output = HERE / (name + '.log')
    if execute:
        with output.open('w') as f:
            proc = subprocess.run(['bash', str(RUN), 'run', name, plan], stdout=f,
                                  stderr=subprocess.STDOUT, check=False)
        exit_code = proc.returncode
        (HERE / (name + '.exit')).write_text(str(exit_code) + '\n')
    else:
        exit_code = int((HERE / (name + '.exit')).read_text().strip())
    log = output.read_text(errors='replace')
    matches = re.findall(r'HBASE02 META_RPC_GET hit=(\d+) matched=(true|false) applied=(true|false) fault=(\w*)', log)
    faulted = [int(hit) for hit, matched, applied, kind in matches if matched == 'true' and applied == 'true']
    requested = len(plan.split(','))
    last_fault = log.rfind('HBASE02 META_RPC_GET hit=' + str(max(faulted)) + ' matched=true') if faulted else -1
    guard_after = last_fault >= 0 and bool(re.search(
        r'HBASE02 GUARD_TABLE_DISABLED value=(?:true|false) exception=none', log[last_fault:]))
    exits = re.findall(r'HBASE02 TARGET_EXIT exception=([^\n]+)', log)
    guard_values = re.findall(r'HBASE02 GUARD_TABLE_DISABLED value=(true|false) exception=([^\n]+)', log)
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', log)
    junit = re.search(r'HBASE02 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', log)
    return {
        'id': name, 'plan': plan, 'requested_fault_events': requested,
        'matched_fault_events': sum(m == 'true' for _, m, _, _ in matches),
        'applied_fault_events': len(faulted), 'applied_hit_ordinals': faulted,
        'observed_rpc_hit_ordinals': [int(m[0]) for m in matches],
        'strict': len(faulted) == requested,
        'target_entries': log.count('HBASE02 TARGET_ENTER'),
        'target_after_final_fault': guard_after,
        'guard_outcomes': guard_values,
        'exact_target_exception': exits[-1] if exits else None,
        'target_exception_observed': any('TableNotEnabledException' in x for x in exits),
        'junit_passed': bool(junit and junit.group(1) == '1' and junit.group(3) == '0' and exit_code == 0),
        'junit_exit': exit_code,
        'elapsed_seconds': float(elapsed.group(1)) if elapsed else None,
        'log': str(output.relative_to(HERE.parent))}


def plans():
    combos = [(k,) for k in KINDS]
    combos += list(itertools.product(KINDS, repeat=2))
    combos += [(KINDS[a], KINDS[b], KINDS[(a + b) % 4]) for a in range(4) for b in range(4)]
    combos += [(KINDS[a], KINDS[b], KINDS[(a + b) % 4], KINDS[(a + 2*b) % 4])
               for a in range(3) for b in range(4)]
    assert len(combos) == 48
    for i, combo in enumerate(combos, 1):
        yield 'r%02d' % i, ','.join('%d:%s' % (j, kind) for j, kind in enumerate(combo, 1))


def main():
    while not (HERE / 'healthy_cov.exit').exists():
        time.sleep(2)
    healthy_exec = HERE / 'healthy_cov.exec'
    healthy_cov = coverage([healthy_exec]) if healthy_exec.exists() else {'error': 'missing healthy exec'}
    data = json.loads(RESULT.read_text())
    healthy_log = (HERE / 'healthy_cov.log').read_text(errors='replace')
    healthy_elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', healthy_log)
    data['healthy_elapsed_seconds'] = float(healthy_elapsed.group(1)) if healthy_elapsed else None
    data['healthy_coverage'] = healthy_cov
    data['fault_trial_details'] = []
    data['coverage_type'] = 'JaCoCo production method/branch/line counts for ConnectionImplementation, MetaTableAccessor and RpcRetryingCallerImpl'
    data['fault_budget'] = {'trials': 48, 'max_faults_per_trial': 4}
    data['pilot_trial'] = {'id': 'io01', 'plan': '1:IOException', 'elapsed_seconds': 39.92,
                           'matched': 1, 'applied': 1, 'target_after_fault': True,
                           'note': 'Jacoco agent was registered after the target probe, so transformed class coverage did not match the production jar; repeated as r01.'}
    data['elapsed_seconds'] = data['healthy_elapsed_seconds'] or 0
    save(data)
    prior_paths = [healthy_exec]
    baseline_branches = healthy_cov.get('total_branches', 0)
    prior_union = baseline_branches
    for name, plan in plans():
        item = parse_run(name, plan)
        exe = HERE / (name + '.exec')
        if exe.exists():
            item['production_coverage'] = coverage([exe])
            union = coverage(prior_paths + [exe])
            item['new_production_branches_vs_prior_trials'] = max(0, union.get('total_branches', 0) - prior_union)
            item['production_branch_union'] = union.get('total_branches')
            prior_union = max(prior_union, union.get('total_branches', 0))
            prior_paths.append(exe)
        else:
            item['production_coverage'] = {'error': 'missing JaCoCo exec'}
            item['new_production_branches_vs_prior_trials'] = 0
        item['new_meta_rpc_hit_ordinals_vs_healthy'] = sorted(set(item['observed_rpc_hit_ordinals']) - {1})
        data['fault_trial_details'].append(item)
        data['fault_trials'] = len(data['fault_trial_details'])
        data['strict_injections'] = sum(x['strict'] for x in data['fault_trial_details'])
        data['requested_fault_events'] = sum(x['requested_fault_events'] for x in data['fault_trial_details'])
        data['matched_fault_events'] = sum(x['matched_fault_events'] for x in data['fault_trial_details'])
        data['applied_fault_events'] = sum(x['applied_fault_events'] for x in data['fault_trial_details'])
        data['target_after_fault'] = sum(x['target_after_final_fault'] for x in data['fault_trial_details'])
        data['coverage_gain'] = max(0, prior_union - baseline_branches)
        data['fault_union_production_branches'] = prior_union
        data['elapsed_seconds'] = (data['healthy_elapsed_seconds'] or 0) + sum(x['elapsed_seconds'] or 0 for x in data['fault_trial_details'])
        data['bug_mark'] = 'candidate_review' if any(x['target_exception_observed'] and x['target_after_final_fault'] for x in data['fault_trial_details']) else 'none'
        data['new_io_marker_types'] = 0
        data['new_meta_rpc_hit_ordinals'] = sorted(set().union(*(set(x['new_meta_rpc_hit_ordinals_vs_healthy']) for x in data['fault_trial_details'])))
        save(data)
        if data['bug_mark'] == 'candidate_review':
            data['status'] = 'candidate_review'
            save(data)
            break
    else:
        data['status'] = 'quality_complete'
        data['campaign_finished'] = True
        save(data)


if __name__ == '__main__':
    main()
