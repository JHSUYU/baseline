#!/usr/bin/env python3
"""Checkpointed graph-free fault search for the original region-replica replication JUnit."""
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
from collections import Counter

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
CHECKPOINT = HERE / 'checkpoint.json'
INFLIGHT = HERE / 'inflight.json'
KINDS = ('IOEXCEPTION', 'EOF', 'NOTFOUND')
MAX_EFFECTIVE = int(os.environ.get('HBASE29_MAX_EFFECTIVE', '80'))
MAX_ATTEMPTS = int(os.environ.get('HBASE29_MAX_ATTEMPTS', '240'))
MAX_FAULTS = int(os.environ.get('HBASE29_MAX_FAULTS', '8'))
RNG = random.Random(29)


def atomic_json(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def parse_log(path):
    trace = {'io': [], 'applied': [], 'targets': [], 'guards': [], 'exits': [],
             'junit': None, 'elapsed_seconds': None}
    for line_no, line in enumerate(path.read_text(errors='replace').splitlines()):
        m = re.search(r'HBASE29 IO seq=(\d+) selector=(\S+)', line)
        if m:
            trace['io'].append({'line': line_no, 'seq': int(m[1]), 'selector': m[2]})
        m = re.search(r'HBASE29 FAULT_APPLIED seq=(\d+) step=(\d+) selector=(\S+) kind=(\S+)', line)
        if m:
            trace['applied'].append({'line': line_no, 'seq': int(m[1]),
                                     'step': int(m[2]), 'selector': m[3], 'kind': m[4]})
        m = re.search(r'HBASE29 REPLAY_ENTER call=(\d+) table=(\S+) replica=(-?\d+) entries=(\d+) distinct_regions=(\d+)', line)
        if m:
            trace['targets'].append({'line': line_no, 'call': int(m[1]), 'table': m[2],
                                     'replica': int(m[3]), 'entries': int(m[4]),
                                     'distinct_regions': int(m[5])})
        m = re.search(r'HBASE29 ENTRY_AFTER_GUARD call=(\d+) region=(\S+)', line)
        if m:
            trace['guards'].append({'line': line_no, 'call': int(m[1]), 'region': m[2]})
        m = re.search(r'HBASE29 REPLAY_EXIT call=(\d+) thrown=(\S+) cause=(\S+) mixed_region=(true|false)', line)
        if m:
            trace['exits'].append({'line': line_no, 'call': int(m[1]), 'thrown': m[2],
                                   'cause': m[3], 'mixed_region': m[4] == 'true'})
        m = re.search(r'HBASE29 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', line)
        if m:
            trace['junit'] = {'found': int(m[1]), 'succeeded': int(m[2]), 'failed': int(m[3])}
        m = re.search(r'ELAPSED_SECONDS=([\d.]+)', line)
        if m:
            trace['elapsed_seconds'] = float(m[1])
    return trace


def cov(paths):
    p = subprocess.run(['bash', str(HERE / 'run.sh'), 'coverage', ','.join(map(str, paths))],
                       capture_output=True, text=True, check=False)
    if p.returncode:
        return {'error': p.stderr[-1500:]}
    classes = {}
    for line in p.stdout.splitlines():
        m = re.fullmatch(r'COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)', line)
        if m:
            classes[m[1]] = {'methods': int(m[2]), 'branches': int(m[3]), 'lines': int(m[4])}
    if len(classes) != 4:
        return {'error': 'Expected four production classes, got ' + repr(classes)}
    return {'classes': classes,
            'methods': sum(x['methods'] for x in classes.values()),
            'branches': sum(x['branches'] for x in classes.values()),
            'lines': sum(x['lines'] for x in classes.values())}


def io_site(selector):
    return '~'.join(selector.split('~')[:3])


def available(trace, after=-1):
    stop = max((x['line'] for x in trace['guards']), default=-1)
    return [x['selector'] for x in trace['io'] if after < x['line'] < stop]


def mutate(state, prefix, selectors, novelty, parent_seconds):
    unique = list(dict.fromkeys(selectors))
    RNG.shuffle(unique)
    seen = set(state['seen_plans'])
    for selector in unique:
        for kind in KINDS:
            plan = prefix + [selector + '~' + kind]
            key = ';'.join(plan)
            if key in seen or len(plan) > MAX_FAULTS:
                continue
            seen.add(key)
            state['queue'].append({'plan': plan, 'score': 4 * novelty + 3 * len(plan),
                                   'parent_seconds': parent_seconds, 'wait': 0})
    state['seen_plans'] = sorted(seen)


def priority(q, trials):
    final = q['plan'][-1]
    ordinal = int(final.split('~')[3])
    site_kind = '~'.join(final.split('~')[:3] + final.split('~')[4:])
    tried = Counter('~'.join(x['plan'][-1].split('~')[:3]
                             + x['plan'][-1].split('~')[4:]) for x in trials)
    same_prefix = [x for x in trials if x['strict'] and x['plan'][:-1] == q['plan'][:-1]]
    dead_prefix = len(same_prefix) >= 4 and all(not x['target_after_fault'] for x in same_prefix)
    depth = len(q['plan'])
    effective_deep = sum(x['effective'] and len(x['plan']) >= 3 for x in trials)
    effective_deeper = sum(x['effective'] and len(x['plan']) >= 4 for x in trials)
    deep_quota = max(0, (len(trials) - 35) // 4)
    deeper_quota = max(0, (len(trials) - 55) // 8)
    depth_bonus = (55 if depth >= 3 and effective_deep < deep_quota else 0)
    depth_bonus += 35 if depth >= 4 and effective_deeper < deeper_quota else 0
    return (q['score'] + (22 if not tried[site_kind] else 0)
            + (12 if len(q['plan']) >= 2 and len(trials) >= 20 else 0) * (len(q['plan']) - 1)
            + depth_bonus - 15 * max(0, depth - 4)
            + min(q['wait'] // 8, 8) - (80 if dead_prefix else 0)
            - min(q['parent_seconds'] / 25, 8) - min(ordinal, 120))


def effective_count(state):
    return sum(x['effective'] for x in state['trials'])


def publish(state, status='running_coverage_io_campaign'):
    atomic_json(CHECKPOINT, state)
    trials = state['trials']
    elapsed = state['healthy']['elapsed_seconds'] + sum(x['elapsed_seconds'] or 0 for x in trials)
    result = json.loads((CASE / 'result.json').read_text())
    result.update({'status': status,
                   'cluster_test': 'org.apache.hadoop.hbase.replication.regionserver.TestRegionReplicaReplicationEndpoint#testRegionReplicaReplicationWith2Replicas',
                   'target_reached': True,
                   'fault_trials': len(trials),
                   'strict_injections': sum(x['strict'] for x in trials),
                   'target_after_fault': sum(x['target_after_fault'] for x in trials),
                   'elapsed_seconds': elapsed,
                   'coverage_gain': state['coverage_union']['branches'] - state['healthy_coverage']['branches'],
                   'bug_mark': 'candidate_review' if any(x['unexpected_mixed_region'] for x in trials) else 'none',
                   'methodology': 'graph_free_original_junit_replay_rpc_io_jacoco_feedback',
                   'evidence': ['work/checkpoint.json', 'work/logs/healthy.log',
                                'work/src/HBase29Agent.java', 'work/run.sh']})
    result['current_campaign'] = {
        'healthy_elapsed_seconds': state['healthy']['elapsed_seconds'],
        'healthy_replay_calls': len(state['healthy']['targets']),
        'healthy_entry_guard_passes': len(state['healthy']['guards']),
        'healthy_related_io_events': len(state['healthy']['io']),
        'healthy_coverage': state['healthy_coverage'],
        'attempted_trials': len(trials), 'strict_trials': sum(x['strict'] for x in trials),
        'effective_trials': effective_count(state),
        'strict_post_fault_target_trials': sum(x['target_after_fault'] for x in trials),
        'strict_post_fault_mixed_region_trials': sum(x['unexpected_mixed_region'] for x in trials),
        'requested_fault_events': sum(x['requested_fault_events'] for x in trials),
        'applied_fault_events': sum(x['applied_fault_events'] for x in trials),
        'new_production_methods': state['coverage_union']['methods'] - state['healthy_coverage']['methods'],
        'new_production_branches': state['coverage_union']['branches'] - state['healthy_coverage']['branches'],
        'new_io_sites': len({io_site(x) for x in state['observed_selectors']}
                            - {io_site(x) for x in state['healthy_selectors']}),
        'elapsed_seconds': elapsed, 'queue_length': len(state['queue']),
        'budget': {'effective_trials': MAX_EFFECTIVE, 'max_attempts': MAX_ATTEMPTS,
                   'max_faults': MAX_FAULTS},
        'checkpoint': 'work/checkpoint.json'}
    atomic_json(CASE / 'result.json', result)


def expand_depth(state):
    old = state.get('depth_expanded_to', 8)
    if old >= MAX_FAULTS:
        return
    for t in state['trials']:
        if t['effective'] and old <= len(t['plan']) < MAX_FAULTS:
            trace = parse_log(CASE / t['log'])
            after = trace['applied'][-1]['line']
            novelty = sum(t.get(k, 0) for k in
                          ('new_production_methods', 'new_production_branches', 'new_io_sites'))
            mutate(state, t['plan'], available(trace, after), novelty,
                   t['elapsed_seconds'] or 60)
    state['depth_expanded_to'] = MAX_FAULTS
    publish(state)


def main():
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
        expand_depth(state)
    else:
        healthy = parse_log(HERE / 'logs/healthy.log')
        if (healthy['junit'] != {'found': 1, 'succeeded': 1, 'failed': 0}
                or not healthy['targets'] or not healthy['guards']
                or any(x['mixed_region'] for x in healthy['exits'])
                or not available(healthy)):
            raise RuntimeError('Original healthy replication JUnit did not reach replay guard')
        baseline = cov([HERE / 'logs/healthy.exec'])
        if 'error' in baseline:
            raise RuntimeError(baseline['error'])
        state = {'healthy': healthy, 'healthy_coverage': baseline,
                 'coverage_union': baseline,
                 'coverage_execs': [str(HERE / 'logs/healthy.exec')],
                 'healthy_selectors': sorted({x['selector'] for x in healthy['io']}),
                 'observed_selectors': sorted({x['selector'] for x in healthy['io']}),
                 'trials': [], 'queue': [], 'seen_plans': [], 'depth_expanded_to': MAX_FAULTS}
        mutate(state, [], available(healthy), 0, healthy['elapsed_seconds'])
        publish(state)
    while (effective_count(state) < MAX_EFFECTIVE and len(state['trials']) < MAX_ATTEMPTS
           and state['queue']):
        number = len(state['trials']) + 1
        trial_id = f'r{number:03d}'
        for q in state['queue']:
            q['wait'] += 1
        inflight = json.loads(INFLIGHT.read_text()) if INFLIGHT.exists() else None
        if inflight and inflight['id'] == trial_id:
            entry = next((q for q in state['queue'] if q['plan'] == inflight['plan']), None)
            if entry is None:
                raise RuntimeError('Inflight plan missing from queue')
            state['queue'].remove(entry)
        else:
            INFLIGHT.unlink(missing_ok=True)
            state['queue'].sort(key=lambda q: (-priority(q, state['trials']),
                                               q['parent_seconds'], ';'.join(q['plan'])))
            entry = state['queue'].pop(0)
            atomic_json(INFLIGHT, {'id': trial_id, 'plan': entry['plan']})
        log = HERE / 'logs' / f'{trial_id}.log'
        exit_path = HERE / 'logs' / f'{trial_id}.exit'
        existing = parse_log(log) if log.exists() else None
        completed = existing and existing['elapsed_seconds'] is not None and exit_path.exists()
        if not completed:
            with log.open('w') as out:
                proc = subprocess.run(['bash', str(HERE / 'run.sh'), 'run', trial_id,
                                       ';'.join(entry['plan'])], stdout=out,
                                      stderr=subprocess.STDOUT, check=False)
            exit_path.write_text(str(proc.returncode) + '\n')
        trace = parse_log(log)
        applied = trace['applied']
        strict = (len(applied) == len(entry['plan'])
                  and all(x['step'] == i and x['selector'] + '~' + x['kind'] == plan
                          for i, (x, plan) in enumerate(zip(applied, entry['plan']), 1)))
        last = applied[-1]['line'] if applied else -1
        post_guards = [x for x in trace['guards'] if x['line'] > last] if strict else []
        post_mixed = [x for x in trace['exits'] if x['line'] > last and x['mixed_region']] if strict else []
        exe = HERE / 'logs' / f'{trial_id}.exec'
        post_target = bool(post_guards or post_mixed)
        effective = post_target and exe.exists()
        item = {'id': trial_id, 'plan': entry['plan'],
                'requested_fault_events': len(entry['plan']),
                'applied_fault_events': len(applied), 'strict': strict,
                'target_after_fault': strict and post_target,
                'post_fault_entry_guard_passes': len(post_guards),
                'unexpected_mixed_region': strict and bool(post_mixed),
                'effective': effective, 'junit': trace['junit'],
                'junit_exit': int(exit_path.read_text().strip()),
                'elapsed_seconds': trace['elapsed_seconds'],
                'observed_io_events': len(trace['io']),
                'log': str(log.relative_to(CASE)),
                'disposition': ('unmatched' if not strict else
                                'target_lost' if not post_target else
                                'target_retained_coverage_missing' if not exe.exists() else
                                'admitted_for_feedback')}
        if effective:
            prior = state['coverage_union']
            combined = cov(state['coverage_execs'] + [str(exe)])
            if 'error' in combined:
                item['coverage_error'] = combined['error']
                item['effective'] = False
                item['disposition'] = 'target_retained_coverage_error'
            else:
                item['new_production_methods'] = combined['methods'] - prior['methods']
                item['new_production_branches'] = combined['branches'] - prior['branches']
                state['coverage_union'] = combined
                state['coverage_execs'].append(str(exe))
                old_sites = {io_site(x) for x in state['observed_selectors']}
                state['observed_selectors'] = sorted(set(state['observed_selectors'])
                                                     | {x['selector'] for x in trace['io']})
                item['new_io_sites'] = len({io_site(x) for x in state['observed_selectors']} - old_sites)
                if len(entry['plan']) < MAX_FAULTS:
                    novelty = sum(item.get(k, 0) for k in
                                  ('new_production_methods', 'new_production_branches', 'new_io_sites'))
                    mutate(state, entry['plan'], available(trace, last), novelty,
                           item['elapsed_seconds'] or 60)
        state['trials'].append(item)
        publish(state)
        INFLIGHT.unlink(missing_ok=True)
        shutil.rmtree(HERE / ('data-' + trial_id), ignore_errors=True)
        if item['unexpected_mixed_region']:
            break
    status = ('candidate_review' if any(x['unexpected_mixed_region'] for x in state['trials']) else
              'budget_complete_pending_source_review' if effective_count(state) >= MAX_EFFECTIVE else
              'attempt_cap_pending_source_review' if len(state['trials']) >= MAX_ATTEMPTS else
              'queue_exhausted_pending_source_review')
    publish(state, status)


if __name__ == '__main__':
    main()
