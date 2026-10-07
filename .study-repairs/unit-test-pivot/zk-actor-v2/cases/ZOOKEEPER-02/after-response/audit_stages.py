#!/usr/bin/env python3
"""Independent raw audit for both isolated ZK02 after-I/O campaign stages."""

import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
V2 = HERE.parents[2]
sys.path.insert(0, str(V2))
from receipt_validator import ReceiptError, parse_events, validate_rows

CHECK = 'SessionTrackerImpl#checkSession:322:ownerMismatch'
TARGET = {'check': CHECK, 'actor': '*', 'role': 'leader',
          'peer': '*', 'session_tag': 'movedSession'}
STAGES = (
    ('client_after_write', Path('/users/ZhenyuLi/zk02-actor-v2-afterio-runs'),
     'afterio-campaign.json', 'AFTER_WRITE_RESULT',
     'org.apache.zookeeper.ClientCnxnSocketNIO#doIO:119:'),
    ('server_after_sync_response',
     Path('/users/ZhenyuLi/zk02-actor-v2-after-response-runs'),
     'after-response-campaign.json', 'AFTER_RESPONSE_SENT',
     'org.apache.zookeeper.server.NIOServerCnxn#handleWrite:299:packetSent()V'),
)


def audit_stage(name, root, checkpoint_name, marker_kind, site_prefix):
    state = json.loads((root / checkpoint_name).read_text())
    seed = json.loads((root / 'healthy-a/run.json').read_text())
    seed_b = json.loads((root / 'healthy-b/run.json').read_text())
    errors = []
    for key in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                'classpath_sha256', 'original_source_commit', 'original_test'):
        if seed[key] != seed_b[key]:
            errors.append('healthy seeds differ in ' + key)
    if seed['exit_code'] or seed_b['exit_code']:
        errors.append('original healthy JUnit failed')
    planned = set()
    effective = 0
    postfault_guards = 0
    target_throws = 0
    junit_failures = 0
    depth_max = 0
    for item in state['results']:
        run_id = item['run_id']
        dest = root / run_id
        run = json.loads((dest / 'run.json').read_text())
        rows = parse_events(dest / 'events.tsv')
        for key in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                    'classpath_sha256', 'original_source_commit', 'original_test'):
            if run[key] != seed[key]:
                errors.append(run_id + ': artifact mismatch: ' + key)
        if run['plan'] != item['plan'] or run['exit_code'] != item['junit_exit']:
            errors.append(run_id + ': run receipt differs from checkpoint')
        # Early stage runners retained their pilot-only membership label.
        # The checkpoint's independently validated effective bit is the
        # denominator; the original run receipt is preserved verbatim.
        plan_key = tuple(item['plan'])
        if plan_key in planned:
            errors.append(run_id + ': duplicate fault plan in stage')
        planned.add(plan_key)
        if not all(selector.startswith(site_prefix) for selector in item['plan']):
            errors.append(run_id + ': fault outside stage-specific complete I/O boundary')
        matched = [(seq, fields) for seq, kind, fields in rows if kind == 'FAULT_MATCHED']
        applied = [(seq, fields) for seq, kind, fields in rows if kind == 'FAULT_APPLIED']
        if item['effective'] and (len(matched) != len(item['plan'])
                                  or len(applied) != len(item['plan'])):
            errors.append(run_id + ': applied/matched fault count differs from plan')
        for (seq, fault), (applied_seq, _) in zip(matched, applied):
            if applied_seq <= seq:
                errors.append(run_id + ': nonmonotonic matched/applied sequence')
            marker = [(prior, fields) for prior, kind, fields in rows
                      if kind == marker_kind and prior < seq and seq - prior <= 8
                      and len(fields) >= 3 and fields[0] == fault[0]
                      and fields[-1] == fault[-1]]
            if not marker:
                errors.append(run_id + ': matched fault lacks same-thread post-I/O marker')
                continue
            if marker_kind == 'AFTER_WRITE_RESULT':
                fields = marker[-1][1]
                if not (int(fields[1]) > 0 and int(fields[2]) == 0
                        and int(fields[3]) in (5, 9)):
                    errors.append(run_id + ': client fault followed partial/non-workload write')
                if not fault[1].startswith('client:handle:') or fault[6] != 'movedSession':
                    errors.append(run_id + ': client actor or moved session is unbound')
            else:
                if marker[-1][1][1] != 'packetSent-after-complete-write':
                    errors.append(run_id + ': server packetSent boundary unproven')
                if (not fault[1].startswith('peer:')
                        or fault[1].split(':')[1] != fault[4]
                        or fault[6] != 'movedSession' or fault[3] != '3'):
                    errors.append(run_id + ': server actor/ordinal/session differs')
        try:
            strict = validate_rows(rows, {'plan': item['plan'],
                                          'fault_relations': item['relations'],
                                          'target': TARGET})
        except (ReceiptError, ValueError, IndexError):
            strict = None
        leaders = [fields[0] for _, kind, fields in rows
                   if kind == 'LEADER_BIND' and fields]
        raw_sessions = {fields[0] for _, kind, fields in rows
                        if kind == 'SESSION_BIND' and len(fields) >= 3
                        and fields[2] == 'movedSession'}
        owner_verified = False
        if strict and len(leaders) == 1 and len(raw_sessions) == 1:
            guard_seq = strict['target_sequence']
            guards = [fields for seq, kind, fields in rows
                      if seq == guard_seq and kind == 'TARGET_GUARD']
            owners = [fields for seq, kind, fields in rows
                      if kind == 'OWNER_BIND' and 0 < guard_seq - seq <= 12]
            if guards and owners:
                target = guards[0]
                owner = owners[-1]
                owner_verified = (target[1] == 'peer:' + leaders[0]
                                  and target[3] == leaders[0]
                                  and target[4] == 'movedSession'
                                  and owner[0] == leaders[0]
                                  and owner[1] in raw_sessions
                                  and owner[2] == owner[3]
                                  and owner[4] == target[5] == 'same-object'
                                  and owner[-1] == target[-1])
        raw_effective = bool(strict and owner_verified)
        if raw_effective != item['effective']:
            errors.append(run_id + ': raw owner/target/effectiveness differs')
        if raw_effective:
            effective += 1
            postfault_guards += 1
            depth_max = max(depth_max, len(item['plan']))
        throws = [fields for seq, kind, fields in rows
                  if kind == 'TARGET_THROW' and seq > max((a for a, _ in applied), default=0)
                  and len(fields) >= 6 and fields[0] == CHECK
                  and fields[4] == 'movedSession']
        target_throws += len(throws)
        if len(throws) != item['selected_target_throw_count']:
            errors.append(run_id + ': target throw count differs')
        if run['exit_code'] != 0 and not throws:
            junit_failures += 1
            if item['bug_mark'] != 'none':
                errors.append(run_id + ': non-target JUnit failure was bug-marked')
    if effective != state['effective_count']:
        errors.append('checkpoint effective count differs from raw audit')
    tail = [item for item in state['results'] if item['effective']][-8:]
    late_novelty = any(item['new_coverage_lines'] or item['new_io_families']
                       or item['selected_target_throw_count'] for item in tail)
    if state['extended'] != late_novelty and name == 'server_after_sync_response':
        errors.append('conditional 128/10 extension decision differs from final eight')
    healthy_coverage = set((root / 'healthy-a/coverage.tsv').read_text().splitlines())
    cumulative_coverage = set(state['seen_coverage'])
    if not healthy_coverage <= cumulative_coverage:
        errors.append('effective coverage lost healthy source lines')
    elapsed_trials = round(sum(item['elapsed_seconds'] for item in state['results']), 3)
    elapsed_healthy = round(seed['elapsed_seconds'] + seed_b['elapsed_seconds'], 3)
    return {'stage': name, 'status': state['status'], 'attempts': len(state['results']),
            'effective': effective, 'budget': state['budget_effective'],
            'max_depth': depth_max, 'postfault_owner_guard_proven': postfault_guards,
            'selected_target_throws': target_throws,
            'non_target_junit_failures': junit_failures,
            'agent_sha256': seed['agent_sha256'], 'distinct_plans': len(planned),
            'healthy_elapsed_seconds': elapsed_healthy,
            'trial_elapsed_seconds': elapsed_trials,
            'fault_campaign_wall_seconds': round((root / checkpoint_name).stat().st_mtime
                                                  - state['created_at'], 3),
            'healthy_coverage_lines': len(healthy_coverage),
            'effective_cumulative_coverage_lines': len(cumulative_coverage),
            'effective_coverage_gain': len(cumulative_coverage - healthy_coverage),
            'target_related_io_families': len(state['seen_families']),
            'new_target_related_io_families': sum(item['new_io_families']
                                                   for item in state['results']),
            'late_eight_new_feedback': late_novelty,
            'last_eight_effective': [item['run_id'] for item in tail],
            'errors': errors, 'pass': not errors}


def main():
    stages = [audit_stage(*args) for args in STAGES]
    distinct_agents = stages[0]['agent_sha256'] != stages[1]['agent_sha256']
    total = sum(stage['effective'] for stage in stages)
    roots = [stage[1] for stage in STAGES]
    states = [json.loads((root / stage[2]).read_text())
              for root, stage in zip(roots, STAGES)]
    healthy_coverage = set().union(*(
        set((root / 'healthy-a/coverage.tsv').read_text().splitlines()) for root in roots))
    cumulative_coverage = set().union(*(set(state['seen_coverage']) for state in states))
    result = {'status': 'pass' if all(stage['pass'] for stage in stages)
              and distinct_agents else 'fail',
              'case': 'ZOOKEEPER-02', 'stages': stages,
              'aggregate_effective': total, 'default_budget': 80,
              'aggregate_attempts': sum(stage['attempts'] for stage in stages),
              'aggregate_elapsed_seconds': round(sum(
                  stage['healthy_elapsed_seconds'] + stage['trial_elapsed_seconds']
                  for stage in stages), 3),
              'aggregate_effective_coverage_gain': len(cumulative_coverage - healthy_coverage),
              'aggregate_effective_coverage_lines': len(cumulative_coverage),
              'aggregate_healthy_coverage_lines': len(healthy_coverage),
              'aggregate_target_related_io_families': len(set().union(
                  *(set(state['seen_families']) for state in states))),
              'conditional_extension_required': stages[-1]['late_eight_new_feedback'],
              'aggregate_distinct_agent_variants': distinct_agents,
              'old_pre_io_attempts_counted': 0,
              'coverage_backend': 'case-local ASM production line probes'}
    print(json.dumps(result, indent=2, sort_keys=True))
    if result['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
