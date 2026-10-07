#!/usr/bin/env python3
"""Checkpointed graph-free observed-I/O campaign for the alternate original JUnit."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal

from audit import actor, normalized, parse
from calibrate import HERE, FIRST, ROOT, atomic_json, sha, stamp
from fault_run import run

STATE = HERE / 'full-state.json'
LEDGER = HERE / 'full-ledger.jsonl'
CONTROLLER_LOCK = HERE / 'full-controller.lock'
STOP = False
INITIAL_BUDGET = 80
INITIAL_MAX_FAULTS = 8
INITIAL_ATTEMPT_CAP = 320
EXTENDED_BUDGET = 128
EXTENDED_MAX_FAULTS = 10
EXTENDED_ATTEMPT_CAP = 512
MAX_PROMOTED_ROOTS = 24
FEEDBACK_POLICY = ('Same target ZKCLIENT and pretarget IO, exact selector seen in '
                   'at least two distinct effective full trials; deduplicate '
                   'normalized operation/path/thread family; promote at most 24 '
                   'new roots; add at most 16 ordered children per effective trial.')
SCHEDULER_POLICY = ('At each complete checkpoint, reserve two of five attempt '
                    'slots for singleton plans, two for ordered pairs, and one '
                    'for depth three or greater; empty depth fallbacks are '
                    '1->2->3, 2->1->3, or 3->2->1 respectively. '
                    'Within a depth, retain score and age priority.')
_OLD_PLANS = None


def request_stop(_number, _frame) -> None:
    global STOP
    STOP = True


def family(selector: str) -> str:
    return normalized(selector).rsplit('@@', 1)[0]


def old_plans() -> set[str]:
    global _OLD_PLANS
    if _OLD_PLANS is None:
        _OLD_PLANS = set(json.loads((FIRST / 'campaign-state.json').read_text())['known_plans'])
    return _OLD_PLANS


def priority(plan: list[str], novelty: int = 0) -> int:
    text = ' '.join(plan)
    score = 10 - 3 * len(plan) + min(novelty, 6) * 2
    if '/overseer_elect/leader:' in text:
        score += 12
    if '/autoscaling.json:' in text:
        score += 10
    if '/aliases.json:OverseerThreadFactory' in text:
        score -= 4
    if '/collections/' in text and ':zkCallback' in text:
        score -= 3
    return score


def enqueue(state: dict, plan: list[str], parent: str, novelty: int = 0) -> bool:
    if not plan or len(plan) != len(set(plan)) or len(plan) > state['max_faults']:
        return False
    key = '|||'.join(plan)
    if key in state['seen'] or key in old_plans():
        return False
    state['seen'].append(key)
    state['pending'].append({'plan': plan, 'parent': parent,
                             'score': priority(plan, novelty),
                             'queued_after_attempt': state['attempts']})
    return True


def ordered_io(path: Path, selected_actor: str, target_seq: int) -> list[tuple[int, str]]:
    return [(row[0], row[3][0] + '@@' + row[3][1]) for row in parse(path)
            if row[1] == 'IO' and len(row[3]) >= 3 and row[0] < target_seq
            and actor(row[3]) == selected_actor]


def seed_from_effective(state: dict, run_id: str, plan: list[str],
                        target_actor: str, target_seq: int, novelty: int) -> int:
    path = ROOT / run_id / 'events.tsv'
    rows = parse(path)
    fault_seq = [row[0] for row in rows if row[1] == 'FAULT_APPLIED']
    if len(fault_seq) != len(plan):
        return 0
    observed = ordered_io(path, target_actor, target_seq)
    promoted = set(state.get('promoted_observed_roots', []))
    stable = set(state['healthy_stable_roots']) | promoted
    candidates = [(seq, value) for seq, value in observed
                  if value not in plan and value in stable]
    # Choose distinct operation/path/thread families, then some near the guard.
    selected, used = [], set()
    for seq, value in sorted(candidates, key=lambda item: (item[1] not in promoted, item[0])):
        key = family(value)
        if key not in used:
            selected.append((seq, value))
            used.add(key)
    for seq, value in reversed(candidates):
        if value not in {item[1] for item in selected}:
            selected.append((seq, value))
        if len(selected) >= 16:
            break
    added = 0
    for seq, value in selected[:16]:
        index = sum(x < seq for x in fault_seq)
        child = plan[:index] + [value] + plan[index:]
        if enqueue(state, child, run_id, novelty):
            added += 1
    return added


def register_observed_roots(state: dict, roots: list[str]) -> list[str]:
    """Promote repeat exact selectors, retaining a bounded normalized frontier."""
    counts = state.setdefault('io_root_effective_observations', {})
    promoted = state.setdefault('promoted_observed_roots', [])
    healthy = set(state['healthy_stable_roots'])
    used_families = {family(value) for value in promoted}
    fresh = []
    for value in dict.fromkeys(roots):
        counts[value] = counts.get(value, 0) + 1
        if (counts[value] >= 2 and value not in healthy and value not in promoted
                and family(value) not in used_families
                and len(promoted) < MAX_PROMOTED_ROOTS):
            promoted.append(value)
            used_families.add(family(value))
            fresh.append(value)
    return fresh


def upgrade_feedback(state: dict) -> None:
    if state.get('feedback_policy_sha256'):
        return
    import hashlib
    assert state['inflight'] is None, 'upgrade only at complete checkpoint'
    previous = 'b6111fad1d747567ddda288b244b8612c5d60bd8900c34d1ec8985ecff53b760'
    state['feedback_policy_sha256'] = hashlib.sha256(FEEDBACK_POLICY.encode()).hexdigest()
    state['feedback_migration'] = {'at_utc': stamp(), 'prior_controller_sha256': previous,
                                   'new_controller_sha256': sha(Path(__file__)),
                                   'closed_attempts': state['attempts'],
                                   'closed_effective': state['effective'],
                                   'trial_ids': [row['run_id'] for row in state['trials']]}
    for row in state['trials']:
        if row['effective']:
            assert row['run_json_sha256'] == sha(ROOT / row['run_id'] / 'run.json')
            register_observed_roots(state, row['fault_audit']['same_actor_pretarget_roots'])
    for value in state['promoted_observed_roots']:
        enqueue(state, [value], 'repeat-observed-io')
    if state['promoted_observed_roots']:
        row = next(row for row in reversed(state['trials']) if row['effective'])
        audit = row['fault_audit']
        seed_from_effective(state, row['run_id'], row['plan'], audit['target_actor'],
                            audit['selected_target_sequence'],
                            len(row['new_production_methods_vs_campaign']))
    save(state)


def initial() -> dict:
    healthy = json.loads((HERE / 'healthy-audit.json').read_text())
    pilot = json.loads((HERE / 'pilot-audit.json').read_text())
    pilot_state = json.loads((HERE / 'pilot-state.json').read_text())
    assert pilot['attempts'] == 5 and pilot['effective'] == 3
    assert pilot_state['finished'] and pilot_state['inflight'] is None
    assert pilot['pilot_state_sha256'] == sha(HERE / 'pilot-state.json')
    assert healthy['frozen_attempts'] == 845 and healthy['frozen_effective'] == 68
    stable = json.loads((HERE / 'calibration-state.json').read_text())[
        'qualifying_candidates']['testDeleteAliasWithExistingCollectionName']['stable_novel_roots']
    assert len(stable) == 183
    old = json.loads((FIRST / 'campaign-state.json').read_text())
    assert old['attempts'] == 845 and old['effective'] == 68 and old['inflight'] is None
    state = {'schema_version': 1, 'phase': 'alternate_original_junit_full',
             'first_phase_campaign_state_sha256': sha(FIRST / 'campaign-state.json'),
             'first_phase_attempts_frozen': 845, 'first_phase_effective_frozen': 68,
             'healthy_audit_sha256': sha(HERE / 'healthy-audit.json'),
             'pilot_audit_sha256': sha(HERE / 'pilot-audit.json'),
             'pilot_attempts_separate': 5, 'pilot_effective_separate': 3,
             'original_junit_class_sha256': healthy['original_junit_class_sha256'],
             'healthy_stable_roots': stable, 'budget': INITIAL_BUDGET,
             'max_faults': INITIAL_MAX_FAULTS, 'attempt_cap': INITIAL_ATTEMPT_CAP,
             'extension_decided': False, 'attempts': 0, 'effective': 0,
             'next_trial': 1, 'pending': [], 'seen': [], 'trials': [],
             'inflight': None, 'finished': False, 'stop_reason': None,
             'campaign_methods_seen': [], 'campaign_lines_seen': [],
             'io_family_effective_observations': {}, 'started_at_utc': stamp()}
    for plan in pilot_state['plans']:
        state['seen'].append('|||'.join(plan))
    assert not any(key in old['known_plans'] for key in state['seen'])
    for root in sorted(stable, key=lambda value: (-priority([value]), value)):
        enqueue(state, [root], 'healthy-calibration')
    for case in pilot['cases']:
        if case['effective']:
            audit = json.loads((ROOT / case['run_id'] / 'run.json').read_text())['fault_audit']
            seed_from_effective(state, case['run_id'], case['plan'],
                                audit['target_actor'], audit['selected_target_sequence'],
                                case['new_production_methods_vs_healthy'])
    assert state['pending'] and len(state['pending']) >= 178
    return state


def save(state: dict) -> None:
    atomic_json(STATE, state)
    temp = LEDGER.with_suffix('.jsonl.tmp')
    temp.write_text(''.join(json.dumps(row, sort_keys=True) + '\n'
                            for row in state['trials']))
    os.replace(temp, LEDGER)


def select(state: dict) -> dict:
    # Age bonus keeps a waiting family reachable as feedback adds new plans.
    def key(item: dict) -> tuple[int, int, str]:
        age = state['attempts'] - item['queued_after_attempt']
        return (item['score'] + min(age // 12, 12), -len(item['plan']),
                '|||'.join(item['plan']))
    slot = state['attempts'] % 5
    preferred = (1, 1, 2, 2, 3)[slot]
    levels = (1, 2, 3) if preferred == 1 else ((2, 1, 3) if preferred == 2 else (3, 2, 1))
    candidates = []
    for level in levels:
        candidates = [item for item in state['pending']
                      if (len(item['plan']) >= 3 if level == 3 else len(item['plan']) == level)]
        if candidates:
            break
    assert candidates
    chosen = max(candidates, key=key)
    state['pending'].remove(chosen)
    return chosen


def upgrade_scheduler(state: dict) -> None:
    if state.get('scheduler_policy_sha256'):
        return
    import hashlib
    assert state['inflight'] is None, 'scheduler upgrade only at complete checkpoint'
    assert state['feedback_policy_sha256']
    state['scheduler_policy_sha256'] = hashlib.sha256(SCHEDULER_POLICY.encode()).hexdigest()
    state['scheduler_migration'] = {
        'at_utc': stamp(), 'prior_controller_sha256':
        '33f8aba546c4932eb56af4dcdca0260ed42fcf3c35eb04c40aa86692921f7a7c',
        'new_controller_sha256': sha(Path(__file__)),
        'closed_attempts': state['attempts'], 'closed_effective': state['effective'],
        'pending_by_depth': {str(depth): sum(len(item['plan']) == depth
                                             for item in state['pending'])
                             for depth in range(1, state['max_faults'] + 1)},
        'trial_ids': [row['run_id'] for row in state['trials']]}
    save(state)


def maybe_finish(state: dict) -> None:
    if state['finished'] or state['inflight'] is not None:
        return
    if state['effective'] >= state['budget']:
        if not state['extension_decided'] and state['budget'] == INITIAL_BUDGET:
            last = [row for row in state['trials'] if row['effective']][-8:]
            reason = any(row['new_production_methods_vs_campaign'] or
                         row['new_stable_io_families'] for row in last)
            state['extension_decided'] = True
            state['extension_reason'] = 'last_8_effective_novelty' if reason else 'no_last_8_effective_novelty'
            if reason:
                state['budget'] = EXTENDED_BUDGET
                state['max_faults'] = EXTENDED_MAX_FAULTS
                state['attempt_cap'] = EXTENDED_ATTEMPT_CAP
        if state['effective'] >= state['budget']:
            state['finished'] = True
            state['stop_reason'] = 'effective_budget_reached'
    elif state['attempts'] >= state['attempt_cap']:
        state['finished'] = True
        state['stop_reason'] = 'attempt_cap_inconclusive'
    elif not state['pending']:
        state['finished'] = True
        state['stop_reason'] = 'observed_io_plan_exhausted_inconclusive'
    if state['finished']:
        state['finished_at_utc'] = stamp()


def finish_trial(state: dict, manifest: dict) -> None:
    job = state['inflight']
    assert manifest['run_id'] == job['run_id'] and manifest['plan'] == job['plan']
    assert manifest['original_junit_class_sha256'] == state['original_junit_class_sha256']
    audit = manifest['fault_audit'] or {}
    effective = bool(audit.get('effective') and manifest['test_started_count'] == 1
                     and manifest['assumption_failure_count'] == 0)
    coverage = manifest['coverage']
    gains = coverage.get('new_vs_healthy', {})
    previous_methods = set(state['campaign_methods_seen'])
    previous_lines = set(state['campaign_lines_seen'])
    new_methods = sorted(set(gains.get('methods', [])) - previous_methods) if effective else []
    new_lines = sorted(set(gains.get('lines', [])) - previous_lines) if effective else []
    stable_families = []
    if effective:
        counts = state['io_family_effective_observations']
        for group in {family(x) for x in audit['same_actor_pretarget_roots']}:
            before = counts.get(group, 0)
            counts[group] = before + 1
            if before == 1 and group not in {family(x) for x in state['healthy_stable_roots']}:
                stable_families.append(group)
        state['campaign_methods_seen'] = sorted(previous_methods | set(gains.get('methods', [])))
        state['campaign_lines_seen'] = sorted(previous_lines | set(gains.get('lines', [])))
    fresh_roots = (register_observed_roots(state, audit['same_actor_pretarget_roots'])
                   if effective else [])
    row = {'run_id': job['run_id'], 'plan': job['plan'], 'parent': job['parent'],
           'junit_exit': manifest['junit_exit'], 'junit_summary_present': manifest['junit_summary_present'],
           'elapsed_seconds': manifest['elapsed_seconds'], 'fault_audit': audit,
           'effective': effective, 'coverage_available': coverage['available'],
           'new_production_methods_vs_healthy': gains.get('methods', []),
           'new_production_lines_vs_healthy': gains.get('lines', []),
           'new_production_methods_vs_campaign': new_methods,
           'new_production_lines_vs_campaign': new_lines,
           'new_stable_io_families': sorted(stable_families),
           'new_repeat_observed_io_roots': fresh_roots,
           'feedback_policy_sha256': state.get('feedback_policy_sha256'),
           'scheduler_policy_sha256': state.get('scheduler_policy_sha256'),
           'controller_sha256': sha(Path(__file__)),
           'run_json_sha256': sha(ROOT / job['run_id'] / 'run.json'),
           'finished_at_utc': stamp()}
    state['trials'].append(row)
    state['attempts'] += 1
    state['effective'] += int(effective)
    state['next_trial'] += 1
    state['inflight'] = None
    if effective:
        for value in fresh_roots:
            enqueue(state, [value], 'repeat-observed-io')
        seed_from_effective(state, row['run_id'], row['plan'], audit['target_actor'],
                            audit['selected_target_sequence'], len(new_methods))
    maybe_finish(state)
    save(state)


def once(state: dict) -> dict:
    assert state['first_phase_campaign_state_sha256'] == sha(FIRST / 'campaign-state.json')
    assert state['healthy_audit_sha256'] == sha(HERE / 'healthy-audit.json')
    assert state['pilot_audit_sha256'] == sha(HERE / 'pilot-audit.json')
    assert state['attempts'] == len(state['trials'])
    if state['inflight'] is None:
        maybe_finish(state)
        if state['finished']:
            save(state)
            return {'status': 'finished', 'reason': state['stop_reason'],
                    'attempts': state['attempts'], 'effective': state['effective']}
        selected = select(state)
        state['inflight'] = {'run_id': f"trial-{state['next_trial']:03d}",
                             'plan': selected['plan'], 'parent': selected['parent'],
                             'selected_at_utc': stamp()}
        save(state)
    job = state['inflight']
    out = ROOT / job['run_id']
    if (out / 'run.json').exists():
        manifest = json.loads((out / 'run.json').read_text())
    else:
        assert not out.exists(), f'partial raw needs manual reconciliation: {out}'
        manifest = run(job['run_id'], job['plan'], 'alternate_original_junit_full')
    finish_trial(state, manifest)
    item = state['trials'][-1]
    return {'status': 'trial_complete', 'run_id': item['run_id'],
            'attempts': state['attempts'], 'effective': state['effective'],
            'trial_effective': item['effective'], 'junit_exit': item['junit_exit'],
            'fault_count': len(item['plan']),
            'new_methods': len(item['new_production_methods_vs_campaign']),
            'target_outcome': item['fault_audit'].get('target_outcome'),
            'stop_reason': state['stop_reason']}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--init-only', action='store_true')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--continuous', action='store_true')
    args = parser.parse_args()
    assert sum((args.init_only, args.once, args.continuous)) == 1
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with CONTROLLER_LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.exists() else initial()
        if not STATE.exists():
            save(state)
        if state['inflight'] is None:
            upgrade_feedback(state)
            upgrade_scheduler(state)
        if args.init_only:
            print(json.dumps({'status': 'initialized', 'pending': len(state['pending']),
                              'attempts': state['attempts'], 'effective': state['effective']}), flush=True)
            return
        while not STOP:
            result = once(state)
            print(json.dumps(result, sort_keys=True), flush=True)
            if not args.continuous or state['finished']:
                break
        if STOP:
            print(json.dumps({'status': 'stopped_at_boundary',
                              'attempts': state['attempts'],
                              'effective': state['effective'],
                              'inflight': state['inflight']}), flush=True)


if __name__ == '__main__':
    main()
