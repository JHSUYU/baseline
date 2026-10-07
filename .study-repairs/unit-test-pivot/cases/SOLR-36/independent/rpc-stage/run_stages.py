#!/usr/bin/env python3
"""Resume the HTTP pilot into a target-retaining effective campaign."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

from fuzz_rpc import CHECKS, ROOT, SEEDS, point, point_id, rpc_events


HERE = Path(__file__).resolve().parent
PILOT_SELECTED = 24
DEFAULT_EFFECTIVE = 80
NOVEL_EFFECTIVE = 128
MAX_SELECTED = 256


def atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def summarize(state: dict | None) -> dict:
    rows = [] if state is None else state['completed']
    effective = {case_id: sum(bool(row['strict_injection'])
                              and row['postfault_same_child_guards'][case_id] > 0
                              for row in rows)
                 for case_id in CHECKS}
    return {
        'selected_plans': len(rows),
        'attempted_junits': sum(row['attempts'] for row in rows),
        'strict_injections': sum(bool(row['strict_injection']) for row in rows),
        'effective_by_case': effective,
        'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in rows), 3),
        'unmatched_plans': sum(not row['strict_injection'] for row in rows),
        'fault_depths': dict(Counter(str(row['planned_faults']) for row in rows)),
    }


def late_novelty(state: dict) -> dict:
    rows = [row for row in state['completed']
            if row['strict_injection']
            and all(row['postfault_same_child_guards'][case_id] > 0
                    for case_id in CHECKS)][-8:]
    production = [row['trial_number'] for row in rows
                  if row['new_production_probes'] > 0]
    healthy = {point_id(point(event)) for seed in SEEDS
               for event in rpc_events(seed)}
    counts: Counter[str] = Counter()
    for row in rows:
        trace = Path(row['trace'])
        unique: set[str] = set()
        for event in rpc_events(trace.parent):
            identity = point_id(point(event))
            if identity not in healthy:
                unique.add(identity)
        counts.update(unique)
    stable_new = sorted(identity for identity, count in counts.items()
                        if count >= 2)
    return {'last_effective_trial_numbers': [row['trial_number'] for row in rows],
            'production_probe_gain_trial_numbers': production,
            'stable_new_rpc_selector_count': len(stable_new),
            'stable_new_rpc_selector_ids': stable_new,
            'extend': len(rows) == 8 and bool(production or stable_new)}


def decide(state: dict | None, *, novel: bool = False) -> tuple[str, int, int, str]:
    """Return action, selected cap, max faults, and explanation without mutation."""
    if state is None:
        return ('run', PILOT_SELECTED, 2, 'fresh 24-plan pilot')
    budget = state['budget']
    selected = len(state['completed'])
    summary = summarize(state)
    effective = min(summary['effective_by_case'].values())
    if state['status'] == 'candidate_target_exception':
        return ('candidate', budget['max_trials'], budget['max_faults'],
                'exact target throw requires source review and replay')
    if state['status'] == 'running':
        return ('run', budget['max_trials'], budget['max_faults'],
                'resume current checkpoint and active plan')
    if state['status'] not in ('budget_complete', 'queue_exhausted'):
        raise ValueError(f"unexpected fuzzer status {state['status']}")
    if state['status'] == 'queue_exhausted' or not state['queue']:
        if budget['max_faults'] >= 8 and effective >= (NOVEL_EFFECTIVE
                                                     if budget['max_faults'] >= 10
                                                     else DEFAULT_EFFECTIVE):
            return ('complete', budget['max_trials'], budget['max_faults'],
                    'effective target reached; exact HTTP queue exhausted')
        return ('queue_exhausted', budget['max_trials'], budget['max_faults'],
                'no further exact HTTP selectors')
    if budget['max_faults'] == 2:
        if selected < PILOT_SELECTED:
            return ('run', PILOT_SELECTED, 2,
                    'finish 24-plan pilot from bounded selected-plan checkpoint')
        return ('run', max(DEFAULT_EFFECTIVE, selected + 1), 8,
                'pilot checkpoint; retain completed plans')
    target = NOVEL_EFFECTIVE if budget['max_faults'] >= 10 else DEFAULT_EFFECTIVE
    if effective >= target:
        if target == DEFAULT_EFFECTIVE and novel:
            return ('run', max(NOVEL_EFFECTIVE, selected + 1), 10,
                    'late effective production/I-O novelty')
        return ('complete', budget['max_trials'], budget['max_faults'],
                f'{target} same-child postfault effective trials per check')
    if selected >= MAX_SELECTED:
        return ('incomplete_budget_limit', budget['max_trials'], budget['max_faults'],
                f'{effective}/{target} effective after {selected} selected plans')
    next_cap = min(MAX_SELECTED, max(budget['max_trials'] + 16,
                                     selected + (target - effective) + 8))
    return ('run', next_cap, budget['max_faults'],
            f'extend selected plans to reach {target} effective')


def campaign(root: Path, *, runner: Callable[[int, int], None] | None = None,
             novelty_fn: Callable[[dict], dict] = late_novelty) -> dict:
    state_path = root / 'state.json'
    control_path = root / 'stage-status.json'
    if runner is None:
        if root != ROOT:
            raise ValueError('a non-production root requires an isolated runner')
        def runner(max_trials: int, max_faults: int) -> None:
            subprocess.run((sys.executable, str(HERE / 'fuzz_rpc.py'),
                            '--max-trials', str(max_trials),
                            '--max-faults', str(max_faults)), check=True)
    while True:
        state = json.loads(state_path.read_text()) if state_path.is_file() else None
        novelty = (novelty_fn(state) if state is not None
                   and state['status'] == 'budget_complete'
                   and state['budget']['max_faults'] == 8
                   and min(summarize(state)['effective_by_case'].values()) >= DEFAULT_EFFECTIVE
                   else None)
        action, cap, faults, reason = decide(
            state, novel=bool(novelty and novelty['extend']))
        report = {'status': 'running' if action == 'run' else action,
                  'reason': reason, 'selected_cap': cap, 'max_faults': faults,
                  'target_effective': (NOVEL_EFFECTIVE if faults >= 10
                                       else DEFAULT_EFFECTIVE if faults >= 8
                                       else None),
                  'counts': summarize(state), 'late_novelty': novelty,
                  'updated_at': time.time()}
        atomic(control_path, report)
        print(json.dumps(report, sort_keys=True), flush=True)
        if action != 'run':
            return report
        try:
            runner(cap, faults)
        except Exception as error:
            report.update(status='interrupted', reason=str(error),
                          updated_at=time.time())
            atomic(control_path, report)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    campaign(args.root)


if __name__ == '__main__':
    main()
