#!/usr/bin/env python3
"""Recompute ZK03 quorum-response pilot verdicts from raw original-JUnit events."""

from collections import Counter
import json

from pilot_quorum import (AGENT, CHECK, MAX_PILOT, ROOT, SITE_SUFFIX,
                          parse_events, sha, verify_assets, write_json)


def selector(fields):
    return '@@'.join(fields[:4])


def audit():
    build = verify_assets()
    calibration = json.loads((ROOT / 'calibration.json').read_text())
    if calibration['status'] != 'pass' or calibration['old_stages_pooled']:
        raise RuntimeError('fresh two-seed calibration not proven')
    raw_sessions = []
    for seed in ('healthy-a', 'healthy-b'):
        folder = ROOT / seed
        receipt = json.loads((folder / 'run.json').read_text())
        rows = parse_events(folder / 'events.tsv')
        raws = {f[0] for _, kind, f, _ in rows if kind == 'SESSION_BIND'
                and len(f) >= 3 and f[2] == 'movedSession'}
        if receipt['exit_code'] != 0 or receipt['plan'] or len(raws) != 1:
            raise RuntimeError(seed + ' changed original-JUnit/actor receipt')
        raw_sessions.append(next(iter(raws)))
        if sha(folder / 'events.tsv') != next(x['events_sha256'] for x in calibration['healthy']
                                              if x['run_id'] == seed):
            raise RuntimeError(seed + ' raw trace changed')
    state = json.loads((ROOT / 'pilot-checkpoint.json').read_text())
    if state['agent_sha256'] != sha(AGENT) or state['agent_sha256'] != build['agent_sha256'] \
            or state['old_stages_pooled'] or state['old_stage_plan_overlap'] != 0 \
            or len(state['queue']) > MAX_PILOT or len(state['queue']) != len(set(state['queue'])) \
            or state['next_index'] != len(state['results']):
        raise RuntimeError('pilot checkpoint/agent/budget changed')
    healthy_coverage = set().union(*(set((ROOT / x / 'coverage.tsv').read_text().splitlines())
                                     for x in ('healthy-a', 'healthy-b')))
    seen = healthy_coverage.copy()
    records = []
    for index, stored in enumerate(state['results']):
        run_id = 'pilot-{:02d}'.format(index + 1)
        folder = ROOT / run_id
        receipt = json.loads((folder / 'run.json').read_text())
        rows = parse_events(folder / 'events.tsv')
        plan = [state['queue'][index]]
        if receipt['run_id'] != run_id or receipt['plan'] != plan or \
                receipt['agent_sha256'] != build['agent_sha256'] or \
                stored['run_id'] != run_id or stored['plan'] != plan or \
                not plan[0].endswith(('@@1', '@@2')) or SITE_SUFFIX not in plan[0]:
            raise RuntimeError(run_id + ' receipt/plan is not the fresh post-flush family')
        matched = [(s, f, t) for s, kind, f, t in rows if kind == 'FAULT_MATCHED']
        applied = [(s, f, t) for s, kind, f, t in rows if kind == 'FAULT_APPLIED']
        exact = len(matched) == len(applied) == 1 and \
                selector(matched[0][1]) == selector(applied[0][1]) == plan[0] and \
                matched[0][0] < applied[0][0]
        leader = [f[0] for _, kind, f, _ in rows if kind == 'LEADER_BIND']
        raw = {f[0] for _, kind, f, _ in rows if kind == 'SESSION_BIND' and len(f) >= 3
               and f[2] == 'movedSession'}
        chain = None
        if exact and len(leader) == len(raw) == 1:
            seq, fault, thread = applied[0]
            if fault[1] == 'peer:' + leader[0] + ':session:movedSession' and \
                    fault[4] == leader[0] and fault[6] == 'movedSession' and fault[5]:
                binds = [(s, f) for s, kind, f, t in rows if kind == 'QUORUM_RESPONSE_BIND'
                         and t == thread and s < seq and len(f) >= 7 and f[0] == fault[0]
                         and f[1:4] == [leader[0], fault[5], next(iter(raw))]
                         and f[5:7] == fault[1:3]]
                if binds:
                    bs, binding = binds[-1]
                    flushed = [(s, f) for s, kind, f, t in rows if kind == 'QUORUM_FLUSH_COMPLETE'
                               and t == thread and s < bs and len(f) >= 4
                               and f[1:4] == [fault[0], next(iter(raw)), 'true']]
                    if flushed:
                        fs, flush = flushed[-1]
                        written = [(s, f) for s, kind, f, t in rows
                                   if kind == 'QUORUM_REVALIDATE_WRITTEN' and t == thread
                                   and s < fs and len(f) >= 3
                                   and f[:3] == [flush[0], next(iter(raw)), 'true']]
                        if written:
                            chain = {'written_seq': written[-1][0], 'flush_seq': fs,
                                     'bound_seq': bs, 'applied_seq': seq,
                                     'leader_sid': leader[0], 'follower_sid': fault[5],
                                     'raw_session_id': next(iter(raw)),
                                     'owner_key': binding[4], 'actor': fault[1]}
        last = applied[-1][0] if applied else 0
        target = [(s, f) for s, kind, f, _ in rows if s > last and kind == 'TARGET_GUARD'
                  and len(f) >= 6 and len(leader) == 1 and f[0] == CHECK
                  and f[1:5] == ['peer:' + leader[0], 'leader', leader[0], 'movedSession']]
        owner = [(s, f) for s, kind, f, _ in rows if s > last and kind == 'OWNER_BIND'
                 and len(leader) == len(raw) == 1 and len(f) >= 4
                 and f[:2] == [leader[0], next(iter(raw))]
                 and f[2].startswith(('local:', 'forwarder:'))]
        witness = next(((s, f) for s, f in target
                        if any(last < os < s for os, _ in owner)), None)
        effective = bool(exact and chain and witness)
        throws = [(s, f) for s, kind, f, _ in rows if effective and s > last
                  and kind == 'TARGET_THROW' and len(f) >= 6 and f[0] == CHECK
                  and f[1] == 'peer:' + leader[0] and f[4] == 'movedSession']
        coverage = set((folder / 'coverage.tsv').read_text().splitlines())
        gain = len(coverage - seen) if effective else 0
        if effective:
            seen |= coverage
        expected = {'exact': exact, 'bound_response': bool(chain), 'effective': effective,
                    'target_after_fault': bool(target), 'owner_after_fault': bool(owner),
                    'selected_target_throws': len(throws), 'new_coverage_lines': gain,
                    'events_sha256': sha(folder / 'events.tsv'),
                    'coverage_sha256': sha(folder / 'coverage.tsv'),
                    'receipt_sha256': sha(folder / 'run.json')}
        for key, value in expected.items():
            if stored[key] != value:
                raise RuntimeError(run_id + ' stored ' + key + ' differs from raw audit')
        records.append({'run_id': run_id, 'plan': plan, 'junit_exit': receipt['exit_code'],
                        'elapsed_seconds': receipt['elapsed_seconds'], **expected,
                        'response_chain': chain,
                        'target_guard_seq': witness[0] if witness else None})
    result = {'status': state['status'], 'selected': len(records),
              'effective': sum(x['effective'] for x in records),
              'selected_target_throws': sum(x['selected_target_throws'] for x in records),
              'new_coverage_lines': len(seen - healthy_coverage),
              'healthy_raw_session_ids': raw_sessions,
              'agent_sha256': sha(AGENT), 'checkpoint_sha256': sha(ROOT / 'pilot-checkpoint.json'),
              'original_source_commit': build['source_commit'],
              'old_stages_pooled': False, 'records': records}
    write_json(ROOT / 'pilot-audit.json', result)
    return result


if __name__ == '__main__':
    summary = audit()
    print(json.dumps({key: summary[key] for key in ('status', 'selected', 'effective',
          'selected_target_throws', 'new_coverage_lines')}, sort_keys=True))
