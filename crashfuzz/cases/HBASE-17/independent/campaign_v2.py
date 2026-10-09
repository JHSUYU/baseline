#!/usr/bin/env python3
"""Resume-safe coverage/I/O mutation on an unchanged original cluster JUnit."""
import json
import os
import random
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
STATE = HERE / 'checkpoint_v2.json'
INFLIGHT = HERE / 'inflight_v2.json'
LOGS = HERE / 'logs_v2'
RUNNER = HERE / 'fuzz_v2.sh'
RNG = random.Random(1702)
TARGET_EFFECTIVE = int(os.environ.get('HBASE17_V2_EFFECTIVE_BUDGET', '80'))
MAX_FAULTS = int(os.environ.get('HBASE17_V2_MAX_FAULTS', '8'))
MAX_ATTEMPTS = int(os.environ.get('HBASE17_V2_MAX_ATTEMPTS', '180'))
MAX_WALL_SECONDS = int(os.environ.get('HBASE17_V2_MAX_WALL_SECONDS', '11000'))
MAX_SEED_SPECIFIC_ATTEMPTS = 4
RECEIPT = HERE / 'healthy_receipt_v2.json'


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(temp, path)


def now():
    return datetime.now(timezone.utc).isoformat()


def parse_log(path):
    text = path.read_text(errors='replace')
    out = {'io': [], 'matched': [], 'applied': [], 'b5': [], 'confirm_errors': []}
    for line_no, line in enumerate(text.splitlines(), 1):
        event = re.search(r'HBASE17 IO seq=(\d+) selector=(\S+) originalError=(\S+)', line)
        if event:
            out['io'].append({'line': line_no, 'seq': int(event.group(1)),
                              'selector': event.group(2), 'original_error': event.group(3)})
        for kind in ('MATCHED', 'APPLIED'):
            match = re.search(r'HBASE17 FAULT_' + kind
                              + r' seq=(\d+) step=(\d+) selector=(\S+) kind=(\S+)', line)
            if match:
                out[kind.lower()].append({'line': line_no, 'seq': int(match.group(1)),
                                          'step': int(match.group(2)),
                                          'selector': match.group(3), 'kind': match.group(4)})
        b5 = re.search(r'HBASE17 B5_EXIT ordinal=(\d+) outcome=(true|false)', line)
        if b5:
            out['b5'].append({'line': line_no, 'ordinal': int(b5.group(1)),
                              'outcome': b5.group(2) == 'true'})
        confirm = re.search(r'HBASE17 CONFIRM_EXIT ordinal=(\d+) exception=(\S+)', line)
        if confirm and confirm.group(2) != 'none':
            out['confirm_errors'].append({'line': line_no, 'ordinal': int(confirm.group(1)),
                                          'exception': confirm.group(2)})
    junit = re.search(r'HBASE17 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)', text)
    elapsed = re.search(r'ELAPSED_SECONDS=([\d.]+)', text)
    out['junit'] = {'found': int(junit.group(1)), 'succeeded': int(junit.group(2)),
                    'failed': int(junit.group(3))} if junit else None
    out['elapsed_seconds'] = float(elapsed.group(1)) if elapsed else None
    out['role_maps'] = re.findall(
        r'HBASE17V2 ROLE_MAP source=(\S+) destination=(\S+) third=(\S+) '
        r'region=(\S+) initialOwnerMatchesSource=(true|false)', text)
    out['initial_owner'] = re.findall(
        r'HBASE17V2 INITIAL_OWNER peer=(\S+) region=(\S+)', text)
    return out


def coverage(paths):
    available = [str(path) for path in paths if path.exists() and path.stat().st_size]
    if not available:
        return {'classes': {}, 'methods': 0, 'branches': 0, 'lines': 0}
    proc = subprocess.run(['bash', str(RUNNER), 'coverage', ','.join(available)],
                          text=True, capture_output=True, timeout=90)
    if proc.returncode:
        raise RuntimeError('Coverage report failed: ' + proc.stderr[-1200:])
    classes = {}
    for line in proc.stdout.splitlines():
        m = re.match(r'COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)', line)
        if m:
            classes[m.group(1)] = {'methods': int(m.group(2)),
                                   'branches': int(m.group(3)), 'lines': int(m.group(4))}
    return {'classes': classes,
            'methods': sum(value['methods'] for value in classes.values()),
            'branches': sum(value['branches'] for value in classes.values()),
            'lines': sum(value['lines'] for value in classes.values())}


def site(selector):
    return selector.rsplit('~', 1)[0]


def plan_key(plan):
    return ';'.join(plan)


def available_io(trace, after=-1):
    last_b5 = max((event['line'] for event in trace['b5']), default=-1)
    if last_b5 < 0:
        return []
    events = [event for event in trace['io'] if after < event['line'] < last_b5
              and event['original_error'] == 'none'
              and eligible_selector(event['selector'])]
    by_site = {}
    for event in events:
        by_site.setdefault(site(event['selector']), []).append(event)
    selected = []
    for group in by_site.values():
        # Keep bounded early and late occurrences; ordinal remains exact.
        selected.extend(group[:5])
        selected.extend(group[-5:])
    return list({event['selector']: event for event in selected}.values())


def eligible_selector(selector):
    # Full resource identity is known for the original test's one Report
    # region. Exclude setup/premove RPCs and opaque remote-procedure payloads.
    if ('Report_ROOT_r0' not in selector or '@PREMOVE' in selector
            or '@UNKNOWN_PEER' in selector):
        return False
    if selector.startswith('META_PUT~hbase:meta/Report_ROOT_r0~'):
        return True
    if not selector.startswith('RPC_'):
        return False
    return any(token in selector for token in
               ('#OPEN_Report_ROOT_r0~', '#CLOSE_Report_ROOT_r0~',
                '#REPORT_OPENED_Report_ROOT_r0~',
                '#REPORT_CLOSED_Report_ROOT_r0~',
                '#MUTATE_Report_ROOT_r0~'))


def fault_kinds(selector):
    if selector.startswith('RPC_RESPONSE~'):
        return ('IO', 'TIMEOUT')
    if selector.startswith('RPC_REQUEST~'):
        return ('IO', 'CONNECT')
    return ('IO',)


def enqueue(state, prefix, events, parent_gain=0):
    seen = set(state['seen_plans'])
    for event in events:
        selector = event['selector']
        for kind in fault_kinds(selector):
            plan = prefix + [selector + '~' + kind]
            key = plan_key(plan)
            if key in seen or len(plan) > MAX_FAULTS:
                continue
            seen.add(key)
            origin = ('recovery_observed' if prefix else
                      'healthy_common' if selector in state['common_healthy_selectors']
                      else 'healthy_seed_specific')
            state['queue'].append({'plan': plan,
                                   'parent_gain': parent_gain,
                                   'source_line': event['line'],
                                   'wait': 0, 'origin': origin})
    state['seen_plans'] = sorted(seen)


def priority(entry, trials, seed_last_line):
    last = entry['plan'][-1]
    selector = last.rsplit('~', 1)[0]
    stable_site = site(selector)
    tried = Counter(site(item['plan'][-1].rsplit('~', 1)[0]) for item in trials)
    family = selector.split('~', 1)[0]
    depth = len(entry['plan'])
    relevance = (22 if '#CLOSE_Report_' in selector else
                 18 if '#REPORT_CLOSED_' in selector else
                 14 if '#OPEN_Report_' in selector else
                 12 if family == 'META_PUT' else 8)
    novelty = 22 if tried[stable_site] == 0 else 0
    timing = 14 * min(entry['source_line'], seed_last_line) // max(seed_last_line, 1)
    depth_bonus = min(depth, 5) * (5 if len(trials) > 24 else 3)
    target_loss = sum(item['strict'] and not item['target_after_final_fault']
                      and site(item['plan'][-1].rsplit('~', 1)[0]) == stable_site
                      for item in trials)
    stability = (28 if entry.get('origin') == 'healthy_common' else
                 -22 if entry.get('origin') == 'healthy_seed_specific' else 0)
    return (relevance + novelty + timing + depth_bonus + entry['parent_gain'] * 3
            + stability
            + min(entry['wait'] // 5, 12) - min(tried[stable_site] * 5, 55)
            - min(target_loss * 12, 80))


def effective(state):
    return sum(item['strict'] and item['target_after_final_fault'] for item in state['trials'])


def publish(state):
    atomic_json(STATE, state)
    atomic_json(HERE / 'trial_ledger_v2.json', state['trials'])
    result = json.loads(RESULT.read_text())
    trials = state['trials']
    strict = sum(item['strict'] for item in trials)
    retained = effective(state)
    delta_methods = state['coverage_union']['methods'] - state['seed_coverage']['methods']
    delta_branches = state['coverage_union']['branches'] - state['seed_coverage']['branches']
    result['status'] = state.get('status', 'running')
    result['methodology'] = 'coverage_io_no_graph_actor_identity'
    result['status_detail'] = 'V2 unchanged original JUnit; RegionPlan actor role and stable target-region I/O identity'
    result['fault_trials'] = len(trials)
    result['strict_injections'] = strict
    result['target_after_fault'] = retained
    result['coverage_gain'] = delta_branches
    result['elapsed_seconds'] = round(state['historical_elapsed_seconds']
                                      + state['seed']['elapsed_seconds']
                                      + sum(item['elapsed_seconds'] or 0 for item in trials), 2)
    result['bug_mark'] = ('candidate_review' if any(item['target_assertion_false']
                          or item['junit_failed_after_target'] for item in trials)
                          else 'none' if trials else 'not_evaluated')
    result['current_campaign'] = {
        'phase': 'actor_identity_v2',
        'original_cluster_junit':
            'TestReportRegionStateTransitionFromDeadServer.test',
        'instrumented_seed_junit': state['seed']['junit'],
        'instrumented_seed_elapsed_seconds': state['seed']['elapsed_seconds'],
        'instrumented_seed_exact_b5': len(state['seed']['b5']),
        'instrumented_seed_io_events': len(state['seed']['io']),
        'instrumented_seed_coverage': state['seed_coverage'],
        'healthy_seed_role_maps': state['healthy_seed_role_maps'],
        'selector_identity': 'operation + stable target-region resource + callsite + thread role + logical peer role + per-family occurrence',
        'unsupported_or_premove_io_excluded': True,
        'calibration_pilot_logs': state['calibration_pilot_logs'],
        'calibration_pilot_elapsed_seconds': state['calibration_pilot_elapsed_seconds'],
        'attempted_trials': len(trials),
        'strict_trials': strict,
        'strict_post_fault_target_trials': retained,
        'effective_budget_trials': retained,
        'junit_failures_after_target': sum(item['junit_failed_after_target'] for item in trials),
        'target_assertion_false_trials': sum(item['target_assertion_false'] for item in trials),
        'new_production_methods': delta_methods,
        'new_production_branches': delta_branches,
        'new_stable_io_sites': len(set(state['observed_sites']) - set(state['seed_sites'])),
        'seed_specific_attempts': sum(
            item.get('origin') == 'healthy_seed_specific' for item in trials),
        'seed_specific_attempt_cap': MAX_SEED_SPECIFIC_ATTEMPTS,
        'common_healthy_exact_selectors': len(state['common_healthy_selectors']),
        'budget': {'effective_trials': TARGET_EFFECTIVE, 'max_ordered_faults': MAX_FAULTS,
                   'max_attempts': MAX_ATTEMPTS, 'max_wall_seconds': MAX_WALL_SECONDS},
        'queue_length': len(state['queue']),
        'wall_seconds': round(time.time() - state['started_unix'], 2),
        'checkpoint': 'independent/checkpoint_v2.json',
        'trial_ledger': 'independent/trial_ledger_v2.json',
        'test_internal_faults_counted_as_campaign_injections': False,
    }
    atomic_json(RESULT, result)


def initialize():
    receipt = json.loads(RECEIPT.read_text())
    if not receipt.get('valid_for_v2_seed'):
        raise RuntimeError('V2 healthy identity receipt is not valid')
    pilot_a = parse_log(LOGS / 'seed_v2a.log')
    pilot_b = parse_log(LOGS / 'seed_v2b.log')
    first = parse_log(LOGS / 'seed_v2c.log')
    seed = parse_log(LOGS / 'seed_v2d.log')
    expected_junit = {'found': 1, 'succeeded': 1, 'failed': 0}
    for name, trace in [('seed_v2c', first), ('seed_v2d', seed)]:
        if trace['junit'] != expected_junit or not any(event['outcome'] for event in trace['b5']):
            raise RuntimeError(name + ' must pass unchanged JUnit and reach exact B5')
        if (len(trace['role_maps']) != 1
                or trace['role_maps'][0][3:] != ('Report_ROOT_r0', 'true')
                or len(trace['initial_owner']) != 1):
            raise RuntimeError(name + ' must record a verified original RegionPlan role map')
        relevant = available_io(trace)
        if not any('#OPEN_Report_ROOT_r0~' in event['selector'] for event in relevant):
            raise RuntimeError(name + ' has no target-region OPEN I/O before B5')
        if not any('#CLOSE_Report_ROOT_r0~' in event['selector'] for event in relevant):
            raise RuntimeError(name + ' has no target-region CLOSE I/O before B5')
    seed_cov = coverage([LOGS / 'seed_v2c.exec', LOGS / 'seed_v2d.exec'])
    seed_sites = sorted({site(event['selector']) for event in seed['io']
                         if eligible_selector(event['selector'])})
    legacy = json.loads(RESULT.read_text()).get('legacy_coarse_identity_phase', {})
    old_elapsed = legacy.get('elapsed_seconds_including_calibrations')
    if old_elapsed is None:
        raise RuntimeError('Missing separately archived legacy elapsed time')
    pilot_elapsed = sum(trace['elapsed_seconds'] for trace in (pilot_a, pilot_b, first))
    state = {'status': 'running', 'started_utc': now(), 'started_unix': time.time(),
             'historical_elapsed_seconds': round(old_elapsed + pilot_elapsed, 2),
             'calibration_pilot_logs': ['independent/logs_v2/seed_v2a.log',
                                        'independent/logs_v2/seed_v2b.log',
                                        'independent/logs_v2/seed_v2c.log'],
             'calibration_pilot_elapsed_seconds': round(pilot_elapsed, 2),
             'healthy_seed_role_maps': [first['role_maps'][0], seed['role_maps'][0]],
             'seed': seed,
             'seed_coverage': seed_cov, 'coverage_union': seed_cov,
             'coverage_execs': ['seed_v2c.exec', 'seed_v2d.exec'],
             'seed_sites': seed_sites,
             'common_healthy_selectors': receipt['common_exact_selectors'],
             'observed_sites': seed_sites, 'trials': [], 'queue': [],
             'seen_plans': []}
    enqueue(state, [], available_io(seed))
    if not state['queue']:
        raise RuntimeError('No observed I/O before exact B5')
    publish(state)
    return state


def run_one(state, entry):
    number = len(state['trials']) + 1
    trial_id = 'r%03d' % number
    plan = entry['plan']
    log = LOGS / (trial_id + '.log')
    exit_path = LOGS / (trial_id + '.exit')
    atomic_json(INFLIGHT, {'id': trial_id, 'plan': plan, 'started_utc': now()})
    if not exit_path.exists():
        with log.open('w') as output:
            try:
                proc = subprocess.run(['bash', str(RUNNER), 'run', trial_id, plan_key(plan)],
                                      stdout=output, stderr=subprocess.STDOUT, timeout=420)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = 124
                output.write('CAMPAIGN_DRIVER_TIMEOUT\n')
        exit_path.write_text(str(code) + '\n')
    else:
        code = int(exit_path.read_text().strip())
    trace = parse_log(log)
    requested = len(plan)
    matched = len(trace['matched'])
    applied = len(trace['applied'])
    strict = (matched == requested and applied == requested
              and len(trace['role_maps']) == 1
              and trace['role_maps'][0][3:] == ('Report_ROOT_r0', 'true'))
    after = trace['applied'][-1]['line'] if trace['applied'] else -1
    post_b5 = [event for event in trace['b5'] if event['line'] > after]
    retained = strict and bool(post_b5)
    false_guard = retained and any(not event['outcome'] for event in post_b5)
    junit_failed = retained and (code != 0 or not trace['junit']
                                  or trace['junit']['failed'] != 0)
    trial = {'id': trial_id, 'started_utc': json.loads(INFLIGHT.read_text())['started_utc'],
             'finished_utc': now(), 'plan': plan, 'requested_fault_events': requested,
             'origin': entry['origin'],
             'matched_fault_events': matched, 'applied_fault_events': applied,
             'strict': strict, 'target_after_final_fault': retained,
             'post_fault_exact_b5': len(post_b5),
             'target_assertion_false': bool(false_guard),
             'junit_failed_after_target': bool(junit_failed),
             'junit': trace['junit'], 'junit_exit': code,
             'elapsed_seconds': trace['elapsed_seconds'],
             'log': 'independent/logs_v2/' + log.name,
             'coverage_file': 'independent/logs_v2/' + trial_id + '.exec',
             'io_events': len(trace['io']), 'stable_io_sites': sorted(
                 {site(event['selector']) for event in trace['io']
                  if eligible_selector(event['selector'])}),
             'role_maps': trace['role_maps'],
             'target_errors': trace['confirm_errors']}
    old = state['coverage_union']
    exec_file = LOGS / (trial_id + '.exec')
    if exec_file.exists() and exec_file.stat().st_size:
        state['coverage_execs'].append(exec_file.name)
        state['coverage_union'] = coverage([LOGS / name for name in state['coverage_execs']])
    trial['new_production_methods'] = max(0, state['coverage_union']['methods'] - old['methods'])
    trial['new_production_branches'] = max(0, state['coverage_union']['branches'] - old['branches'])
    previous_sites = set(state['observed_sites'])
    state['observed_sites'] = sorted(previous_sites | set(trial['stable_io_sites']))
    trial['new_stable_io_sites'] = len(set(trial['stable_io_sites']) - previous_sites)
    state['trials'].append(trial)
    if retained and len(plan) < MAX_FAULTS:
        gain = trial['new_production_methods'] + trial['new_production_branches'] \
            + trial['new_stable_io_sites']
        enqueue(state, plan, available_io(trace, after), gain)
    INFLIGHT.unlink(missing_ok=True)
    publish(state)


def main():
    LOGS.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    # A checkpoint written by the first V2 controller may lack the seed
    # stability tag. Recover it from the immutable two-seed receipt.
    if 'common_healthy_selectors' not in state:
        receipt = json.loads(RECEIPT.read_text())
        state['common_healthy_selectors'] = receipt['common_exact_selectors']
    for item in [*state['queue'], *state['trials']]:
        if 'origin' not in item:
            item['origin'] = ('recovery_observed' if len(item['plan']) > 1 else
                              'healthy_common' if item['plan'][0].rsplit('~', 1)[0]
                              in state['common_healthy_selectors']
                              else 'healthy_seed_specific')
    while effective(state) < TARGET_EFFECTIVE:
        if len(state['trials']) >= MAX_ATTEMPTS:
            state['status'] = 'budget_exhausted_attempt_cap'
            break
        if time.time() - state['started_unix'] > MAX_WALL_SECONDS:
            state['status'] = 'budget_exhausted_wall_cap'
            break
        if not state['queue']:
            state['status'] = 'queue_exhausted'
            break
        seed_specific_attempts = sum(
            item['origin'] == 'healthy_seed_specific' for item in state['trials'])
        if seed_specific_attempts >= MAX_SEED_SPECIFIC_ATTEMPTS:
            state['queue'] = [entry for entry in state['queue']
                              if entry['origin'] != 'healthy_seed_specific']
            if not state['queue']:
                state['status'] = 'queue_exhausted_after_seed_specific_cap'
                break
        if INFLIGHT.exists():
            pending = json.loads(INFLIGHT.read_text())
            matches = [entry for entry in state['queue'] if entry['plan'] == pending['plan']]
            selector = pending['plan'][0].rsplit('~', 1)[0]
            fallback_origin = (
                'recovery_observed' if len(pending['plan']) > 1 else
                'healthy_common' if selector in state['common_healthy_selectors']
                else 'healthy_seed_specific')
            entry = matches[0] if matches else {
                'plan': pending['plan'], 'parent_gain': 0, 'source_line': 0,
                'wait': 0, 'origin': fallback_origin}
        else:
            for entry in state['queue']:
                entry['wait'] += 1
            seed_last_line = max((event['line'] for event in state['seed']['b5']), default=1)
            ranked = sorted(state['queue'],
                            key=lambda entry: priority(entry, state['trials'], seed_last_line),
                            reverse=True)
            top = ranked[:min(12, len(ranked))]
            entry = RNG.choice(top)
        if entry in state['queue']:
            state['queue'].remove(entry)
        run_one(state, entry)
    else:
        state['status'] = 'budget_complete_pending_source_review'
    publish(state)


if __name__ == '__main__':
    main()
