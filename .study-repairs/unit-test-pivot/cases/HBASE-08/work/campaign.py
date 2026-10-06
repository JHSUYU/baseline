#!/usr/bin/env python3
"""Resume-safe, graph-free fault-sequence search for the original HBASE-08 JUnit."""
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time
from collections import Counter

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
CHECKPOINT = HERE / 'checkpoint.json'
INFLIGHT = HERE / 'inflight.json'
KINDS = ('CONNECTIONLOSS', 'OPERATIONTIMEOUT', 'SYSTEMERROR')
RNG = random.Random(8)
MAX_TRIALS = int(os.environ.get('HBASE08_MAX_TRIALS', '64'))
MAX_FAULTS = int(os.environ.get('HBASE08_MAX_FAULTS', '6'))


def atomic_json(path, obj):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def parse_log(text):
    events = []
    targets = []
    applied = []
    matched = []
    for idx, line in enumerate(text.splitlines()):
        m = re.search(r'HBASE08 IO seq=(\d+) selector=(\S+)', line)
        if m:
            events.append({'line': idx, 'seq': int(m.group(1)), 'selector': m.group(2)})
        m = re.search(r'HBASE08 FAULT_MATCHED seq=(\d+) step=(\d+) selector=(\S+) kind=(\S+)', line)
        if m:
            matched.append({'line': idx, 'seq': int(m.group(1)), 'step': int(m.group(2)), 'selector': m.group(3), 'kind': m.group(4)})
        m = re.search(r'HBASE08 FAULT_APPLIED seq=(\d+) step=(\d+) selector=(\S+) kind=(\S+)', line)
        if m:
            applied.append({'line': idx, 'seq': int(m.group(1)), 'step': int(m.group(2)), 'selector': m.group(3), 'kind': m.group(4)})
        m = re.search(r'HBASE08 TARGET_EXIT name=(\S+) exception=(\S+)', line)
        if m:
            targets.append({'line': idx, 'name': m.group(1), 'exception': m.group(2)})
    junit = re.search(r'HBASE08 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', text)
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', text)
    return {'io': events, 'matched': matched, 'applied': applied, 'targets': targets,
            'junit': {'found': int(junit.group(1)), 'succeeded': int(junit.group(2)),
                      'failed': int(junit.group(3))} if junit else None,
            'elapsed_seconds': float(elapsed.group(1)) if elapsed else None}


def coverage(paths):
    proc = subprocess.run(['bash', str(HERE / 'run.sh'), 'coverage', ','.join(map(str, paths))],
                          text=True, capture_output=True, check=False)
    if proc.returncode:
        return {'error': proc.stderr[-1200:]}
    classes = {}
    for line in proc.stdout.splitlines():
        m = re.match(r'COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)', line)
        if m:
            classes[m.group(1)] = {'methods': int(m.group(2)), 'branches': int(m.group(3)),
                                   'lines': int(m.group(4))}
    return {'classes': classes,
            'methods': sum(c['methods'] for c in classes.values()),
            'branches': sum(c['branches'] for c in classes.values()),
            'lines': sum(c['lines'] for c in classes.values())}


def available_events(trace, after_line=-1):
    last_target = max((x['line'] for x in trace['targets'] if guard_executed(x)), default=-1)
    if last_target < 0:
        return []
    return [x['selector'] for x in trace['io'] if after_line < x['line'] < last_target]


def guard_executed(target):
    # Source method has just the lookup followed by the selected null check.
    # A normal return or this exact throw establishes execution of the check;
    # any other exception can arise from the lookup before the check.
    return target['exception'] == 'none' or target['exception'] == 'org.apache.hadoop.hbase.NamespaceNotFoundException'


def io_site(selector):
    """Stable I/O point; the final ordinal is used only for exact fault matching."""
    return '~'.join(selector.split('~')[:3])


def mutate(queue, seen, prefix, candidates, novelty, parent_seconds):
    unique = list(dict.fromkeys(candidates))
    # A deterministic shuffle spreads trials across site, path, and hit ordinal.
    RNG.shuffle(unique)
    for selector in unique:
        for kind in KINDS:
            plan = prefix + [selector + '~' + kind]
            key = ';'.join(plan)
            if key in seen or len(plan) > MAX_FAULTS:
                continue
            seen.add(key)
            family = selector.split('~', 1)[0]
            queue.append({'plan': plan, 'score': novelty * 4 + len(plan) * 2
                          + (3 if family == 'ZK_WRITE' else 0)
                          + (2 if family == 'ZK_CHILDREN_READ' else 0),
                          'parent_seconds': parent_seconds, 'wait': 0})


def queue_priority(entry, trials):
    """CrashFuzz-style novelty, with breadth across related runtime I/O sites."""
    last = entry['plan'][-1]
    fields = last.split('~')
    family = fields[0]
    site_and_kind = '~'.join(fields[:3] + fields[4:])
    tried = Counter('~'.join(x['plan'][-1].split('~')[:3]
                             + x['plan'][-1].split('~')[4:]) for x in trials)
    families = Counter(x['plan'][-1].split('~', 1)[0] for x in trials)
    try:
        ordinal = int(fields[3])
    except (ValueError, IndexError):
        ordinal = 1
    novelty = 25 if tried[site_and_kind] == 0 else 0
    breadth = 18 if families[family] == 0 else max(0, 8 - 2 * families[family])
    target_namespace = 5 if 'TestNamespaceAuditor_np2' in last else 0
    prefix = entry['plan'][:-1]
    site = '~'.join(fields[:3])
    equivalent_target_loss = any(
        x['strict'] and not x['target_after_final_fault']
        and x['plan'][:-1] == prefix
        and '~'.join(x['plan'][-1].split('~')[:3]) == site
        for x in trials)
    prefix_trials = [x for x in trials if x['strict'] and x['plan'][:-1] == prefix]
    exhausted_prefix = len(prefix_trials) >= 4 and all(
        not x['target_after_final_fault'] for x in prefix_trials)
    root_site = '~'.join(entry['plan'][0].split('~')[:3])
    same_root_multifaults = [x for x in trials if x['strict'] and len(x['plan']) >= 2
                             and '~'.join(x['plan'][0].split('~')[:3]) == root_site]
    exhausted_root = len(entry['plan']) >= 2 and len(same_root_multifaults) >= 8 \
        and all(not x['target_after_final_fault'] for x in same_root_multifaults)
    depth = len(entry['plan'])
    depth_bonus = (18 if len(trials) >= 40 else 10 if len(trials) >= 24 else 0) * (depth - 1)
    return entry['score'] + novelty + breadth + min(ordinal, 4) * 2 + target_namespace \
        + min(entry['wait'] // 8, 5) - (100 if equivalent_target_loss else 0) \
        - (60 if exhausted_prefix else 0) - (80 if exhausted_root else 0) + depth_bonus


def publish(state):
    atomic_json(CHECKPOINT, state)
    result = json.loads(RESULT.read_text())
    result['status'] = 'running_coverage_io_campaign'
    result['methodology'] = 'graph_free_original_junit_observed_zk_io_jacoco_feedback'
    result['current_campaign'] = {
        'healthy_elapsed_seconds': state['healthy']['elapsed_seconds'],
        'healthy_target_checks': sum(guard_executed(t) for t in state['healthy']['targets']),
        'healthy_fatal_target_checks': sum('NamespaceNotFoundException' in t['exception'] for t in state['healthy']['targets']),
        'healthy_io_events': len(state['healthy']['io']),
        'healthy_coverage': state['healthy_coverage'],
        'attempted_trials': len(state['trials']),
        'strict_trials': sum(x['strict'] for x in state['trials']),
        'strict_post_fault_target_trials': sum(x['strict'] and x['target_after_final_fault'] for x in state['trials']),
        'requested_fault_events': sum(x['requested_fault_events'] for x in state['trials']),
        'applied_fault_events': sum(x['applied_fault_events'] for x in state['trials']),
        'new_production_methods': state['coverage_union']['methods'] - state['healthy_coverage']['methods'],
        'new_production_branches': state['coverage_union']['branches'] - state['healthy_coverage']['branches'],
        'new_io_selectors': len(state['observed_selectors'] - set(state['healthy_selectors'])) if isinstance(state['observed_selectors'], set) else len(set(state['observed_selectors']) - set(state['healthy_selectors'])),
        'new_io_sites': len(set(map(io_site, state['observed_selectors']))
                            - set(map(io_site, state['healthy_selectors']))),
        'elapsed_seconds': state['healthy']['elapsed_seconds'] + sum(x['elapsed_seconds'] or 0 for x in state['trials']),
        'queue_length': len(state['queue']),
        'budget': {'trials': MAX_TRIALS, 'max_faults': MAX_FAULTS},
        'checkpoint': str(CHECKPOINT.relative_to(CASE))}
    result['fault_trials'] = 5 + len(state['trials'])
    result['strict_injections'] = 4 + result['current_campaign']['strict_trials']
    result['target_after_fault'] = 4 + result['current_campaign']['strict_post_fault_target_trials']
    result['elapsed_seconds'] = 761.55 + result['current_campaign']['elapsed_seconds']
    result['coverage_gain'] = result['current_campaign']['new_production_branches']
    result['bug_mark'] = 'candidate_review' if any(x['exact_target_exception'] for x in state['trials']) else 'none'
    result['evidence'] = ['evidence/legacy-trials/coverage-v3.json', 'evidence/legacy-trials/coverage-v6.json',
                          'work/checkpoint.json', 'work/logs/healthy2.log']
    atomic_json(RESULT, result)


def save_state(state):
    # JSON cannot encode sets; keep lists in the persistent checkpoint.
    atomic_json(CHECKPOINT, state)
    publish(state)


def expand_completed_depth(state):
    """Resume at a larger depth from completed trial logs, without rerunning a trial."""
    previous = state.get('depth_expanded_to', 4)
    if previous >= MAX_FAULTS:
        return
    seen = set(state['seen_plans'])
    for item in state['trials']:
        if not item['strict'] or not item['target_after_final_fault']:
            continue
        if not previous <= len(item['plan']) < MAX_FAULTS:
            continue
        trace = parse_log((CASE / item['log']).read_text(errors='replace'))
        if not trace['applied']:
            continue
        last_fault_line = trace['applied'][-1]['line']
        novelty = item.get('new_production_methods', 0) + item.get('new_production_branches', 0)
        novelty += item.get('new_io_selectors', 0)
        mutate(state['queue'], seen, item['plan'], available_events(trace, last_fault_line),
               novelty, item['elapsed_seconds'] or 300)
    state['seen_plans'] = sorted(seen)
    state['depth_expanded_to'] = MAX_FAULTS
    save_state(state)


def main():
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
        expand_completed_depth(state)
    else:
        healthy_log = HERE / 'logs/healthy2.log'
        healthy_exit = HERE / 'logs/healthy2.exit'
        while not healthy_exit.exists():
            time.sleep(3)
        trace = parse_log(healthy_log.read_text(errors='replace'))
        if healthy_exit.read_text().strip() != '0' or not any(map(guard_executed, trace['targets'])) or trace['junit'] != {'found': 1, 'succeeded': 1, 'failed': 0}:
            raise RuntimeError('Healthy original JUnit failed or did not reach target')
        healthy_exec = HERE / 'logs/healthy2.exec'
        base_cov = coverage([healthy_exec])
        if 'error' in base_cov:
            raise RuntimeError(base_cov['error'])
        queue = []
        seen = set()
        mutate(queue, seen, [], available_events(trace), 0, trace['elapsed_seconds'])
        state = {'healthy': trace, 'healthy_coverage': base_cov,
                 'coverage_union': base_cov, 'coverage_execs': [str(healthy_exec)],
                 'healthy_selectors': sorted(set(x['selector'] for x in trace['io'])),
                 'observed_selectors': sorted(set(x['selector'] for x in trace['io'])),
                 'queue': queue, 'seen_plans': sorted(seen), 'trials': [],
                 'depth_expanded_to': MAX_FAULTS}
        save_state(state)
    while len(state['trials']) < MAX_TRIALS and state['queue']:
        for q in state['queue']:
            q['wait'] += 1
        number = len(state['trials']) + 1
        suffix = 'r%03d' % number
        inflight = json.loads(INFLIGHT.read_text()) if INFLIGHT.exists() else None
        if inflight and inflight.get('id') == suffix:
            entry = next((q for q in state['queue'] if q['plan'] == inflight['plan']), None)
            if entry is None:
                raise RuntimeError('In-flight sequence is absent from checkpoint queue')
            state['queue'].remove(entry)
        else:
            if inflight:
                INFLIGHT.unlink()
            state['queue'].sort(key=lambda q: (-queue_priority(q, state['trials']),
                                               q['parent_seconds'], ';'.join(q['plan'])))
            entry = state['queue'].pop(0)
            atomic_json(INFLIGHT, {'id': suffix, 'plan': entry['plan']})
        plan = ';'.join(entry['plan'])
        out = HERE / 'logs' / (suffix + '.log')
        exit_file = HERE / 'logs' / (suffix + '.exit')
        completed_trace = parse_log(out.read_text(errors='replace')) if out.exists() else None
        completed = bool(completed_trace and completed_trace['elapsed_seconds'] is not None
                         and (completed_trace['junit'] is not None or exit_file.exists()))
        if completed:
            returncode = int(exit_file.read_text().strip()) if exit_file.exists() else \
                (0 if completed_trace['junit'] == {'found': 1, 'succeeded': 1, 'failed': 0} else 1)
        else:
            with out.open('w') as f:
                proc = subprocess.run(['bash', str(HERE / 'run.sh'), 'run', suffix, plan],
                                      stdout=f, stderr=subprocess.STDOUT, check=False)
            returncode = proc.returncode
            exit_file.write_text(str(returncode) + '\n')
        trace = parse_log(out.read_text(errors='replace'))
        requested = len(entry['plan'])
        applied = trace['applied']
        strict = len(applied) == requested and [x['step'] for x in applied] == list(range(1, requested + 1))
        last_fault_line = applied[-1]['line'] if applied else -1
        target_after = strict and any(x['line'] > last_fault_line and guard_executed(x) for x in trace['targets'])
        target_exception = strict and any(x['line'] > last_fault_line and 'NamespaceNotFoundException' in x['exception'] for x in trace['targets'])
        item = {'id': suffix, 'plan': entry['plan'], 'requested_fault_events': requested,
                'matched_fault_events': len(trace['matched']), 'applied_fault_events': len(applied),
                'strict': strict, 'target_after_final_fault': target_after,
                'exact_target_exception': target_exception,
                'target_guard_count': len(trace['targets']),
                'fatal_target_guard_count': sum('NamespaceNotFoundException' in t['exception'] for t in trace['targets']),
                'observed_io_events': len(trace['io']), 'elapsed_seconds': trace['elapsed_seconds'],
                'junit': trace['junit'], 'junit_exit': returncode,
                'log': str(out.relative_to(CASE))}
        item['disposition'] = ('unmatched' if not strict else
                               'target_lost_abandoned' if not target_after else
                               'target_exception_candidate' if target_exception else
                               'admitted_for_feedback')
        if strict and target_after:
            exe = HERE / 'logs' / (suffix + '.exec')
            prior = state['coverage_union']
            union = coverage(state['coverage_execs'] + [str(exe)]) if exe.exists() else {'error': 'missing exec'}
            if 'error' not in union:
                item['new_production_methods'] = union['methods'] - prior['methods']
                item['new_production_branches'] = union['branches'] - prior['branches']
                state['coverage_union'] = union
                state['coverage_execs'].append(str(exe))
            else:
                item['coverage_error'] = union['error']
            old = set(state['observed_selectors'])
            state['observed_selectors'] = sorted(old | set(x['selector'] for x in trace['io']))
            item['new_io_selectors'] = len(set(state['observed_selectors']) - old)
            item['new_io_sites'] = len(set(map(io_site, state['observed_selectors']))
                                       - set(map(io_site, old)))
            if requested < MAX_FAULTS:
                seen = set(state['seen_plans'])
                mutate(state['queue'], seen, entry['plan'], available_events(trace, last_fault_line),
                       item.get('new_production_branches', 0) + item.get('new_production_methods', 0)
                       + item['new_io_sites'], trace['elapsed_seconds'] or 300)
                state['seen_plans'] = sorted(seen)
        state['trials'].append(item)
        save_state(state)
        INFLIGHT.unlink(missing_ok=True)
        if target_exception:
            break
    result = json.loads(RESULT.read_text())
    if result['bug_mark'] == 'candidate_review':
        result['status'] = 'candidate_review'
    elif len(state['trials']) == MAX_TRIALS:
        result['status'] = 'budget_complete_pending_source_review'
    else:
        result['status'] = 'queue_exhausted_pending_source_review'
    atomic_json(RESULT, result)


if __name__ == '__main__':
    main()
