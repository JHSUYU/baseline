#!/usr/bin/env python3
"""Independently gate a full campaign's own r0000 before its first fault."""

from __future__ import annotations

import gzip
import argparse
import hashlib
import json
from pathlib import Path

from verify_healthy import CHECK, DOOR, EXCEPTION, HANDOFF, REGION


ACTOR = 'zk-coordinator:coordinator'
SELECTOR = 'org.apache.hadoop.hbase.procedure.TestZKProcedure#testMultipleMembers'
TARGET_CLASS_SHA = '8d43fa6f2820e626e9174810628b8ee1ecb841daf4e6736cf537c124ca75be41'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(campaign: Path, state: dict | None = None) -> dict:
    campaign = Path(campaign)
    result_path = campaign / 'trials/r0000/result.json'
    config_path = campaign / 'config.json'
    trial = json.loads(result_path.read_text())
    config = json.loads(config_path.read_text())
    state = state or json.loads((campaign / 'result.json').read_text())
    feedback = trial.get('feedback') or {}
    catalog = trial.get('site_catalog_validation') or {}
    junit = trial.get('junit_validation') or {}
    attestation = state.get('runtime_attestation') or {}
    reasons: list[str] = []

    def require(condition, reason):
        if not condition:
            reasons.append(reason)

    require(config.get('case_id') == trial.get('case_id') == 'HBASE-23',
            'case identity changed')
    require(config.get('cluster_test') == SELECTOR, 'existing MiniZK JUnit selector changed')
    require(config.get('target', {}).get('check_sites') == [CHECK], 'exact target changed')
    require(trial.get('trial_id') == 0 and trial.get('plan') == [],
            'r0000 is not a fault-free seed')
    require(junit.get('status') == 'passed' and junit.get('tests') == 1 and
            junit.get('failures') == 0 and junit.get('errors') == 0,
            'selected JUnit did not pass exactly once')
    require(catalog.get('valid') is True and catalog.get('class_hash_match') is True and
            catalog.get('observed_target_class_sha256') == TARGET_CLASS_SHA and
            len(catalog.get('target_class_loader_ids', [])) == 1,
            'exact compiled target or classloader unverified')
    require(feedback.get('status') == 'observed' and
            feedback.get('target_reached') is True and
            feedback.get('target_threw') is False and
            not feedback.get('trace_truncated'),
            'fresh exact nonthrowing target absent')
    require(feedback.get('eligible_doors_before_target', 0) > 0 and
            feedback.get('local_timeline_doors', 0) > 0,
            'fresh event-time typed door absent')
    require(any(i.get('node') == ACTOR for i in feedback.get('target_instances', [])) and
            any(c.get('node') == ACTOR for c in feedback.get('target_closures', [])),
            'named target occurrence/closure absent')
    require(attestation.get('valid') is True and
            ACTOR in attestation.get('bound_nodes', []),
            'fresh runtime attestation or actor binding absent')

    evidence = trial.get('events_evidence') or {}
    archive = campaign / 'trials/r0000' / str(evidence.get('gzip_path', ''))
    events: list[dict] = []
    if archive.is_file() and evidence.get('gzip_path') == 'events.jsonl.gz':
        require(sha(archive) == evidence.get('gzip_sha256'),
                'compressed trace SHA-256 mismatch')
        try:
            raw = gzip.decompress(archive.read_bytes())
            require(hashlib.sha256(raw).hexdigest() == evidence.get('raw_sha256'),
                    'decompressed trace SHA-256 mismatch')
            require(len(raw) == evidence.get('raw_bytes'),
                    'decompressed trace byte count mismatch')
            events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except (OSError, EOFError, ValueError, TypeError) as exc:
            reasons.append(f'trace unreadable: {exc}')
    else:
        reasons.append('compressed r0000 trace absent')

    submits = {e.get('correlation'): e for e in events if
               e.get('type') == 'TASK_SUBMIT' and e.get('site') == HANDOFF and
               e.get('correlation')}
    claims = {e.get('correlation'): e for e in events if
              e.get('type') == 'TASK_CLAIM' and e.get('site') == HANDOFF and
              e.get('correlation')}
    tokens = {token for token in submits.keys() & claims.keys() if
              submits[token].get('seq', 0) < claims[token].get('seq', 0)}
    require(bool(tokens), 'accepted Procedure submit/claim token absent')
    regions = [e for e in events if e.get('type') == 'REGION_ENTER' and
               e.get('site') == REGION and e.get('node') == ACTOR and
               e.get('parent_id') in tokens]
    checks = [e for e in events if e.get('type') == 'TARGET_CHECK' and
              e.get('site') == CHECK and e.get('node') == ACTOR]
    doors = [e for e in events if e.get('type') == 'DOOR_OBSERVED' and
             e.get('site') == DOOR and e.get('exception_class') == EXCEPTION and
             e.get('node') == ACTOR]
    typed = {d.get('event_id'): d.get('local_timeline_evidence') for d in
             feedback.get('doors', []) if d.get('site') == DOOR and
             d.get('exception_class') == EXCEPTION and d.get('in_closure') is True and
             (d.get('local_timeline_evidence') or {}).get('kind') ==
             'observed_local_timeline'}
    require(bool(regions) and bool(checks) and bool(doors) and bool(typed),
            'target region, check, physical typed read, or closure evidence absent')

    matched = []
    for region in regions:
        token = region['parent_id']
        if not submits[token]['seq'] < claims[token]['seq'] < region['seq']:
            continue
        for check in checks:
            if check.get('occurrence') != region.get('occurrence') or check.get('node') != ACTOR:
                continue
            for door in doors:
                local = typed.get(door.get('id'))
                if (local and local.get('door_event_id') == door.get('id') and
                    local.get('target_check_event_id') == check.get('id') and
                    local.get('occurrence') == region.get('occurrence') and
                    door.get('occurrence') == region.get('occurrence') and
                    isinstance(door.get('thread_id'), int) and
                    door.get('thread_id') == check.get('thread_id') == region.get('thread_id') and
                    region['seq'] < door['seq'] < check['seq']):
                    matched.append({'task_token': token, 'region_event': region['id'],
                                    'door_event': door['id'], 'check_event': check['id'],
                                    'actor': ACTOR, 'occurrence': region['occurrence']})
    require(bool(matched), 'no same-thread, same-occurrence typed door-to-target witness')

    return {
        'schema_version': 1, 'case_id': 'HBASE-23',
        'status': 'fresh_r0000_admitted' if not reasons else 'fresh_r0000_rejected',
        'fault_trials_started_at_gate': 0,
        'selector': SELECTOR, 'exact_check': CHECK, 'typed_door': DOOR,
        'result_sha256': sha(result_path), 'config_sha256': sha(config_path),
        'events_sha256': sha(archive) if archive.is_file() else None,
        'matched_witnesses': matched, 'reasons': reasons,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    args = parser.parse_args()
    receipt = review(args.campaign)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    raise SystemExit(0 if receipt['status'] == 'fresh_r0000_admitted' else 2)
