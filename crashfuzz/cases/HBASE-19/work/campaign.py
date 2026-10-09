#!/usr/bin/env python3
"""Checkpointed, graph-free fault search for the original HBASE-19/20 JUnit."""
import json
import os
from pathlib import Path
import random
import re
import subprocess
from collections import Counter

HERE = Path(__file__).resolve().parent
CASE19 = HERE.parent
CASE20 = CASE19.parent / 'HBASE-20'
CHECKPOINT = HERE / 'checkpoint.json'
INFLIGHT = HERE / 'inflight.json'
KINDS = ('IOEXCEPTION', 'EOF', 'NOTFOUND')
MAX_TRIALS = int(os.environ.get('HBASE1920_MAX_TRIALS', '80'))
MAX_FAULTS = int(os.environ.get('HBASE1920_MAX_FAULTS', '8'))
RNG = random.Random(1920)


def atomic_json(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def parse_log(path):
    trace = {'io': [], 'applied': [], 'cf': [], 'coproc': [], 'targets': [],
             'junit': None, 'elapsed_seconds': None}
    for line_no, line in enumerate(path.read_text(errors='replace').splitlines()):
        m = re.search(r'HBASE1920 IO seq=(\d+) selector=(\S+)', line)
        if m:
            trace['io'].append({'line': line_no, 'seq': int(m[1]), 'selector': m[2]})
        m = re.search(r'HBASE1920 FAULT_APPLIED seq=(\d+) step=(\d+) selector=(\S+) kind=(\S+)', line)
        if m:
            trace['applied'].append({'line': line_no, 'seq': int(m[1]),
                                     'step': int(m[2]), 'selector': m[3], 'kind': m[4]})
        m = re.search(r'HBASE1920 CF_GUARD call=(\d+) ordinal=(\d+) count=(\d+)', line)
        if m:
            trace['cf'].append({'line': line_no, 'call': int(m[1]),
                                'ordinal': int(m[2]), 'count': int(m[3])})
        m = re.search(r'HBASE1920 COPROC_GUARD call=(\d+) modified=(true|false)', line)
        if m:
            trace['coproc'].append({'line': line_no, 'call': int(m[1]),
                                    'modified': m[2] == 'true'})
        m = re.search(r'HBASE1920 TARGET_EXIT call=(\d+) no_reopen=(true|false) cf_reads=(\d+) exception=(\S+) outcome=(\S+)', line)
        if m:
            trace['targets'].append({'line': line_no, 'call': int(m[1]),
                                     'no_reopen': m[2] == 'true', 'cf_reads': int(m[3]),
                                     'exception': m[4], 'outcome': m[5]})
        m = re.search(r'HBASE1920 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', line)
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
    return {'classes': classes,
            'methods': sum(v['methods'] for v in classes.values()),
            'branches': sum(v['branches'] for v in classes.values()),
            'lines': sum(v['lines'] for v in classes.values())}


def io_site(selector):
    return '~'.join(selector.split('~')[:3])


def target_signatures(trace, outcome):
    by_call = {}
    for x in trace['cf']:
        by_call.setdefault(x['call'], {})[x['ordinal']] = x['count']
    coproc = {x['call']: x['modified'] for x in trace['coproc']}
    return {(x['call'], by_call.get(x['call'], {}).get(1),
             by_call.get(x['call'], {}).get(2), coproc.get(x['call']),
             x['exception'], x['outcome']) for x in trace['targets']
            if x['outcome'] == outcome}


def target_line(trace):
    # Limit all mutations to I/O before the original coprocessor-reject check.
    rejected = [x['call'] for x in trace['targets'] if x['outcome'] == 'coproc_reject']
    guard = [x['line'] for x in trace['coproc'] if x['call'] in rejected]
    return max(guard) if guard else max((x['line'] for x in trace['coproc']), default=-1)


def available(trace, after=-1):
    stop = target_line(trace)
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
            state['queue'].append({'plan': plan,
                                   'score': 4 * novelty + 2 * len(plan)
                                   + (5 if selector.startswith('FS_WRITE') else 0),
                                   'parent_seconds': parent_seconds, 'wait': 0})
    state['seen_plans'] = sorted(seen)


def priority(q, trials):
    final = q['plan'][-1]
    site_kind = '~'.join(final.split('~')[:3] + final.split('~')[4:])
    tried = Counter('~'.join(x['plan'][-1].split('~')[:3]
                             + x['plan'][-1].split('~')[4:]) for x in trials)
    same_prefix = [x for x in trials if x['strict'] and x['plan'][:-1] == q['plan'][:-1]]
    dead_prefix = len(same_prefix) >= 4 and all(
        not (x['post19'] or x['post20']) for x in same_prefix)
    depth = len(q['plan'])
    return (q['score'] + (24 if not tried[site_kind] else 0)
            + (15 if depth >= 2 and len(trials) >= 20 else 0) * (depth - 1)
            + min(q['wait'] // 8, 8) - (85 if dead_prefix else 0)
            - min(q['parent_seconds'] / 30, 10))


def publish(state, status='running_coverage_io_campaign'):
    atomic_json(CHECKPOINT, state)
    trials = state['trials']
    elapsed = state['healthy']['elapsed_seconds'] + sum(t['elapsed_seconds'] or 0 for t in trials)
    common = {'methodology': 'graph_free_original_junit_observed_descriptor_fs_io_jacoco_feedback',
              'healthy_elapsed_seconds': state['healthy']['elapsed_seconds'],
              'healthy_io_events': len(state['healthy']['io']),
              'healthy_coverage': state['healthy_coverage'],
              'attempted_trials': len(trials),
              'strict_trials': sum(t['strict'] for t in trials),
              'requested_fault_events': sum(t['requested_fault_events'] for t in trials),
              'applied_fault_events': sum(t['applied_fault_events'] for t in trials),
              'new_production_methods': state['coverage_union']['methods']
                  - state['healthy_coverage']['methods'],
              'new_production_branches': state['coverage_union']['branches']
                  - state['healthy_coverage']['branches'],
              'new_io_sites': len({io_site(x) for x in state['observed_selectors']}
                                  - {io_site(x) for x in state['healthy_selectors']}),
              'elapsed_seconds': elapsed,
              'queue_length': len(state['queue']),
              'budget': {'trials': MAX_TRIALS, 'max_faults': MAX_FAULTS},
              'checkpoint': '../HBASE-19/work/checkpoint.json'}
    for case, short, outcome in ((CASE19, '19', 'cf_reject'), (CASE20, '20', 'coproc_reject')):
        result = json.loads((case / 'result.json').read_text())
        result['status'] = status
        result['methodology'] = common['methodology']
        data = dict(common)
        data.update({'healthy_target_guard_calls': len(state['healthy']['cf'] if short == '19'
                                                     else state['healthy']['coproc']),
                     'healthy_exact_target_throws': sum(t['outcome'] == outcome
                                                       for t in state['healthy']['targets']),
                     'strict_post_fault_target_trials': sum(t['strict'] and t['post' + short]
                                                            for t in trials),
                     'strict_post_fault_exact_target_throws': sum(t['strict'] and t['exact' + short]
                                                                 for t in trials),
                     'unexpected_exact_target_signatures': sum(t['unexpected' + short]
                                                              for t in trials)})
        result['current_campaign'] = data
        result['target_reached'] = True
        result['fault_trials'] = len(trials)
        result['strict_injections'] = data['strict_trials']
        result['target_after_fault'] = data['strict_post_fault_target_trials']
        result['elapsed_seconds'] = elapsed
        result['coverage_gain'] = data['new_production_branches']
        result['bug_mark'] = ('candidate_review' if data['unexpected_exact_target_signatures']
                              else 'none')
        result['evidence'] = ['../HBASE-19/README.md', '../HBASE-19/work/checkpoint.json',
                              '../HBASE-19/work/logs/healthy3.log',
                              '../HBASE-19/work/src/HBase1920Agent.java']
        atomic_json(case / 'result.json', result)


def expand_depth(state):
    old = state.get('depth_expanded_to', 4)
    if old >= MAX_FAULTS:
        return
    for t in state['trials']:
        if t['strict'] and (t['post19'] or t['post20']) and old <= len(t['plan']) < MAX_FAULTS:
            trace = parse_log(CASE19 / t['log'])
            after = trace['applied'][-1]['line']
            novelty = t.get('new_production_methods', 0) + t.get('new_production_branches', 0)
            novelty += t.get('new_io_sites', 0)
            mutate(state, t['plan'], available(trace, after), novelty,
                   t['elapsed_seconds'] or 240)
    state['depth_expanded_to'] = MAX_FAULTS
    publish(state)


def main():
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
        expand_depth(state)
    else:
        healthy_file = HERE / 'logs/healthy3.log'
        healthy = parse_log(healthy_file)
        if ((HERE / 'logs/healthy3.exit').read_text().strip() != '0'
                or healthy['junit'] != {'found': 1, 'succeeded': 1, 'failed': 0}
                or not target_signatures(healthy, 'cf_reject')
                or not target_signatures(healthy, 'coproc_reject')
                or not available(healthy)):
            raise RuntimeError('Original healthy JUnit or either selected guard did not run')
        baseline = cov([HERE / 'logs/healthy3.exec'])
        if 'error' in baseline:
            raise RuntimeError(baseline['error'])
        state = {'healthy': healthy, 'healthy_coverage': baseline,
                 'healthy19': sorted(target_signatures(healthy, 'cf_reject')),
                 'healthy20': sorted(target_signatures(healthy, 'coproc_reject')),
                 'coverage_union': baseline, 'coverage_execs': [str(HERE / 'logs/healthy3.exec')],
                 'healthy_selectors': sorted({x['selector'] for x in healthy['io']}),
                 'observed_selectors': sorted({x['selector'] for x in healthy['io']}),
                 'trials': [], 'queue': [], 'seen_plans': [], 'depth_expanded_to': MAX_FAULTS}
        mutate(state, [], available(healthy), 0, healthy['elapsed_seconds'])
        publish(state)
    while len(state['trials']) < MAX_TRIALS and state['queue']:
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
        exact_events = all(x['step'] == i and x['selector'] + '~' + x['kind'] == plan
                           for i, (x, plan) in enumerate(zip(applied, entry['plan']), 1))
        strict = len(applied) == len(entry['plan']) and exact_events
        last_fault_line = applied[-1]['line'] if applied else -1
        cf_calls = {x['call'] for x in trace['cf']
                    if x['ordinal'] == 2 and x['line'] > last_fault_line}
        coproc_calls = {x['call'] for x in trace['coproc'] if x['line'] > last_fault_line}
        post19, post20 = strict and bool(cf_calls), strict and bool(coproc_calls)
        signatures19 = target_signatures(trace, 'cf_reject')
        signatures20 = target_signatures(trace, 'coproc_reject')
        after19 = {x for x in signatures19 if x[0] in cf_calls} if post19 else set()
        after20 = {x for x in signatures20 if x[0] in coproc_calls} if post20 else set()
        unexpected19 = bool(after19 - {tuple(x) for x in state['healthy19']})
        unexpected20 = bool(after20 - {tuple(x) for x in state['healthy20']})
        item = {'id': trial_id, 'plan': entry['plan'],
                'requested_fault_events': len(entry['plan']),
                'applied_fault_events': len(applied), 'strict': strict,
                'post19': post19, 'post20': post20,
                'exact19': bool(after19), 'exact20': bool(after20),
                'unexpected19': unexpected19, 'unexpected20': unexpected20,
                'junit': trace['junit'], 'junit_exit': int(exit_path.read_text().strip()),
                'elapsed_seconds': trace['elapsed_seconds'],
                'observed_io_events': len(trace['io']),
                'log': str(log.relative_to(CASE19))}
        item['disposition'] = ('unmatched' if not strict else
                               'both_targets_lost' if not (post19 or post20) else
                               'unexpected_exact_target_exception_candidate'
                               if (unexpected19 or unexpected20) else
                               'admitted_for_feedback')
        if post19 or post20:
            exe = HERE / 'logs' / f'{trial_id}.exec'
            prior = state['coverage_union']
            combined = cov(state['coverage_execs'] + [str(exe)]) if exe.exists() else {'error': 'missing exec'}
            if 'error' in combined:
                item['coverage_error'] = combined['error']
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
                novelty = item.get('new_production_methods', 0) + item.get('new_production_branches', 0)
                mutate(state, entry['plan'], available(trace, last_fault_line),
                       novelty + item['new_io_sites'], item['elapsed_seconds'] or 240)
        state['trials'].append(item)
        publish(state)
        INFLIGHT.unlink(missing_ok=True)
        if unexpected19 or unexpected20:
            break
    status = ('candidate_review' if any(t['unexpected19'] or t['unexpected20'] for t in state['trials'])
              else 'budget_complete_pending_source_review' if len(state['trials']) >= MAX_TRIALS
              else 'queue_exhausted_pending_source_review')
    publish(state, status)


if __name__ == '__main__':
    main()
