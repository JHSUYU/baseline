#!/usr/bin/env python3
"""Independent raw-event and coverage audit of the finished ZK01 V2 budget."""

import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
from campaign import CHECK, ROOT, TARGET, candidates
from receipt_validator import ReceiptError, parse_events, validate_rows


def audit():
    state = json.loads((ROOT / 'v2-campaign.json').read_text())
    seed = json.loads((ROOT / 'healthy-a/run.json').read_text())
    healthy_cov = set((ROOT / 'healthy-a/coverage.tsv').read_text().splitlines())
    seen_cov = set(healthy_cov)
    seen_families = {x['family'] for x in candidates(parse_events(ROOT / 'healthy-a/events.tsv'))}
    errors = []
    effective = 0
    target_throws = 0
    max_depth = 0
    max_raw_bytes = 0
    all_coverage = set(healthy_cov)
    by_depth = {}
    for item in state['results']:
        run_id = item['run_id']
        dest = ROOT / run_id
        run = json.loads((dest / 'run.json').read_text())
        if run['run_id'] != run_id or run['plan'] != item['plan']:
            errors.append(run_id + ': run receipt/plan mismatch')
        for key in ('agent_sha256', 'original_test_class_sha256', 'runner_sha256',
                    'classpath_sha256', 'original_source_commit', 'original_test'):
            if run[key] != seed[key]:
                errors.append(run_id + ': ' + key + ' differs from seed')
        if run['exit_code'] != item['junit_exit']:
            errors.append(run_id + ': JUnit status differs from checkpoint')
        rows = parse_events(dest / 'events.tsv')
        max_raw_bytes = max(max_raw_bytes, (dest / 'events.tsv').stat().st_size)
        leaders = [fields[1] for _, kind, fields in rows
                   if kind == 'SELECTED_LEADER' and len(fields) >= 2]
        if len(leaders) != 1:
            errors.append(run_id + ': selected leader not unique')
        try:
            raw = validate_rows(rows, {'plan': item['plan'],
                                       'fault_relations': item['relations'],
                                       'target': TARGET})
        except (ReceiptError, ValueError, IndexError):
            raw = None
        if bool(raw) != item['effective']:
            errors.append(run_id + ': raw effective verdict differs')
        if raw:
            effective += 1
            max_depth = max(max_depth, len(item['plan']))
            by_depth[len(item['plan'])] = by_depth.get(len(item['plan']), 0) + 1
            guards = [(seq, fields) for seq, kind, fields in rows
                      if kind == 'TARGET_GUARD' and len(fields) >= 6
                      and fields[0] == CHECK and seq == raw['target_sequence']]
            if len(guards) != 1 or guards[0][1][3] != leaders[0]:
                errors.append(run_id + ': target guard peer differs from selected leader')
            creator_raw = {fields[0] for _, kind, fields in rows
                           if kind == 'SESSION_BIND' and len(fields) >= 3
                           and fields[1] == 'creatorCloser' and fields[2] == leaders[0]}
            if len(creator_raw) != 1:
                errors.append(run_id + ': selected creator raw session absent/ambiguous')
            coverage = set((dest / 'coverage.tsv').read_text().splitlines())
            if item['new_coverage_lines'] != len(coverage - seen_cov):
                errors.append(run_id + ': coverage novelty differs')
            seen_cov |= coverage
            after = max(seq for seq, kind, _ in rows if kind == 'FAULT_APPLIED')
            family = {x['family'] for x in candidates(rows, after)}
            if item['new_io_families'] != len(family - seen_families):
                errors.append(run_id + ': I/O novelty differs')
            seen_families |= family
        else:
            if item['new_coverage_lines'] or item['new_io_families']:
                errors.append(run_id + ': invalid trial credited feedback')
        all_coverage |= set((dest / 'coverage.tsv').read_text().splitlines())
        throws = [fields for _, kind, fields in rows if kind == 'TARGET_THROW'
                  and len(fields) >= 6 and fields[0] == CHECK]
        target_throws += len(throws)
        if bool(throws) != item['needs_source_review']:
            errors.append(run_id + ': oracle review flag differs')
        expected_mark = 'candidate_needs_source_review' if throws else 'none'
        if item['bug_mark'] != expected_mark:
            errors.append(run_id + ': bug mark differs from selected target throw')
    if effective != state['effective_count']:
        errors.append('effective denominator differs from raw audit')
    if seen_cov != set(state['seen_coverage']):
        errors.append('cumulative effective coverage differs')
    if seen_families != set(state['seen_families']):
        errors.append('cumulative effective I/O families differ')
    effective_items = [x for x in state['results'] if x['effective']]
    last_eight = effective_items[-8:]
    late_novelty = any(x['new_coverage_lines'] or x['new_io_families'] for x in last_eight)
    if state['status'] != 'budget_complete' or state['extended'] or late_novelty:
        errors.append('terminal budget/conditional extension decision differs')
    jacoco = list(ROOT.glob('**/*.exec'))
    return {'status': 'pass' if not errors else 'fail', 'errors': errors,
            'case': 'ZOOKEEPER-01', 'source_commit': seed['original_source_commit'],
            'original_test': seed['original_test'], 'agent_sha256': seed['agent_sha256'],
            'campaign_status': state['status'], 'attempts': len(state['results']),
            'effective_raw_validated': effective, 'budget_effective': state['budget_effective'],
            'max_depth_raw_validated': max_depth, 'effective_by_depth': by_depth,
            'selected_target_throw_events': target_throws,
            'non_target_junit_failures': sum(x['junit_exit'] != 0 and
                                             not x['selected_target_throw_count']
                                             for x in state['results']),
            'coverage_backend': 'case-local ASM production line probes',
            'jacoco_exec_files': len(jacoco),
            'healthy_coverage_lines': len(healthy_cov),
            'effective_cumulative_coverage_lines': len(seen_cov),
            'all_attempt_coverage_lines': len(all_coverage),
            'effective_new_coverage_lines': len(seen_cov - healthy_cov),
            'effective_io_families': len(seen_families),
            'last_eight_effective': [{'trial': x['run_id'],
                                      'new_coverage_lines': x['new_coverage_lines'],
                                      'new_io_families': x['new_io_families']}
                                     for x in last_eight],
            'conditional_extension_needed': late_novelty,
            'raw_event_max_bytes': max_raw_bytes,
            'checkpoint_sha256': hashlib.sha256(
                (ROOT / 'v2-campaign.json').read_bytes()).hexdigest()}


if __name__ == '__main__':
    result = audit()
    print(json.dumps(result, sort_keys=True, indent=2))
    if result['status'] != 'pass':
        raise SystemExit(1)
