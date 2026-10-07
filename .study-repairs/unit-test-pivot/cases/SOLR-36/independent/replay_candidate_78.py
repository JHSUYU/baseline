#!/usr/bin/env python3
"""Replay frozen SOLR-36 trial 78 without changing the campaign checkpoint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build import HERE
from fuzz import junit_gate, point
from run import run as run_junit


TRIAL = '0078-70db6987171e903945b7'
CASE = HERE / 'campaign'
SOURCE = CASE / 'trials' / TRIAL
PLAN = SOURCE / 'fault.properties'
AGENT = HERE / 'solrsubshard-independent-agent.jar'
DEST = CASE / 'candidate-0078-replay'
TARGET = 'SOLR/SUBSHARD/collection1/shard1_0/core_node11'


def audit(out: Path, selected: list[dict]) -> dict:
    events = [json.loads(line) for line in (out / 'events.jsonl').open()
              if line.strip()]
    applied = [event for event in events
               if event['event'] == 'IO_OBSERVED' and event['applied']]
    summaries = [event for event in events if event['event'] == 'SUMMARY']
    strict = (len(applied) == len(selected)
              and all(point(event) == chosen
                      for event, chosen in zip(applied, selected))
              and len(summaries) == 1
              and summaries[0]['detail'] == f'applied={len(selected)}/{len(selected)}')
    last_fault = applied[-1]['seq'] if applied else -1
    guard = [event for event in events
             if event['event'] == 'TARGET_CHECK'
             and event['marker'] == 'SOLR36:ACTIVE_SUBSHARD_GUARD'
             and event['sourceKey'] == TARGET and event['seq'] > last_fault]
    thrown = [event for event in events
              if event['event'] == 'TARGET_THROW'
              and event['marker'] == 'SOLR36:ACTIVE_SUBSHARD_THROW'
              and event['sourceKey'] == TARGET and event['seq'] > last_fault]
    metadata = json.loads((out / 'run.json').read_text())
    gate = junit_gate((out / 'console.log').read_text())
    return {
        'trial': TRIAL,
        'exact_plan_sha256': hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        'agent_sha256': hashlib.sha256(AGENT.read_bytes()).hexdigest(),
        'original_source_revision': metadata['original_source_revision'],
        'fault_plan_steps': len(selected),
        'applied_faults': len(applied),
        'strict_injection': strict,
        'same_child_postfault_guard_count': len(guard) if strict else 0,
        'same_child_postfault_active_guard_count':
            sum('state=active;' in event['detail'].lower() for event in guard)
            if strict else 0,
        'same_child_postfault_exact_throw_count': len(thrown) if strict else 0,
        'junit_gate': gate,
        'junit_exit': metadata['exit_code'],
        'elapsed_seconds': metadata['elapsed_seconds'],
        'trace_sha256': hashlib.sha256((out / 'events.jsonl').read_bytes()).hexdigest(),
    }


def main() -> None:
    state = json.loads((CASE / 'state.json').read_text())
    candidate = next(row for row in state['completed']
                     if row['trial_number'] == 78)
    if state['status'] != 'candidate_target_exception' or not PLAN.is_file():
        raise RuntimeError('frozen candidate checkpoint/plan is missing')
    selected = candidate['fault_sequence']
    DEST.mkdir(exist_ok=True)
    results = []
    for number in range(1, 5):
        out = DEST / f'replay-{number:02d}'
        existing = out / 'audit.json'
        if existing.is_file():
            row = json.loads(existing.read_text())
        else:
            run_junit(out, agent_path=AGENT, fault_plan=PLAN)
            row = audit(out, selected)
            existing.write_text(json.dumps(row, indent=2, sort_keys=True) + '\n')
        results.append(row)
        summary = {
            'source_trial': 78,
            'original_campaign_status': state['status'],
            'source_sequence': selected,
            'replay_attempts': results,
            'strict_replay_count': sum(item['strict_injection'] for item in results),
            'strict_exact_throw_replay_count': sum(
                item['strict_injection']
                and item['same_child_postfault_exact_throw_count'] > 0
                for item in results),
        }
        (DEST / 'summary.json').write_text(
            json.dumps(summary, indent=2, sort_keys=True) + '\n')
        print(json.dumps({key: row[key] for key in
                          ('strict_injection', 'same_child_postfault_active_guard_count',
                           'same_child_postfault_exact_throw_count', 'junit_gate',
                           'elapsed_seconds')}, sort_keys=True), flush=True)
        if summary['strict_exact_throw_replay_count'] >= 2:
            break


if __name__ == '__main__':
    main()
