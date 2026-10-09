#!/usr/bin/env python3
"""Audit two original healthy JUnit seeds for exact target actor binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import campaign_v2 as c


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    def receipt(local_name: str, remote_name: str) -> dict:
        path = c.HERE / local_name
        if not path.is_file():
            path = c.HERE / remote_name
        return json.loads(path.read_text())

    preflight = receipt('node2-preflight-v2.json', 'preflight-v2.json')
    build = receipt('node2-build-v2.json', 'build-v2.json')
    smoke = receipt('node2-offline-smoke-v2.json', 'offline-smoke-v2.json')
    if not preflight['hostname'].startswith('node2') or len(smoke['results']) != 4:
        raise RuntimeError('node2 provenance/smoke evidence absent')
    if not all(row['exit_code'] == 0 for row in smoke['results']):
        raise RuntimeError('node2 offline smoke failed')
    seeds = []
    for directory in c.SEEDS:
        events = c.load_events(directory)
        run = json.loads((directory / 'run.json').read_text())
        provenance = json.loads((directory / 'v2-provenance.json').read_text())
        log = (directory / 'console.log').read_text()
        enters = [event for event in events if event['event'] == 'TARGET_ENTER'
                  and event['sourceKey'] == c.TARGET]
        guards = c.guard_events(events)
        throws = [event for event in events if event['event'] == 'TARGET_THROW'
                  and event['sourceKey'] == c.TARGET]
        bound = [event for event in events if c.bound_event(event)]
        if (run['exit_code'] or c.junit_gate(log) != (1, 0, 0)
                or len(enters) != 1 or len(guards) != 1 or throws
                or not bound or any(event['applied'] for event in bound)
                or re.search(r'Address already in use|BindException', log)):
            raise RuntimeError(f'healthy original JUnit gate failed: {directory}')
        target = enters[0]
        if guards[0]['targetNode'] != target['targetNode'] or not (
                target['seq'] < min(event['seq'] for event in bound)
                < guards[0]['seq']):
            raise RuntimeError(f'target actor/ordering mismatch: {directory}')
        if (run['agent_sha256'] != build['agent_sha256']
                or provenance['agent_sha256'] != build['agent_sha256']
                or provenance['original_test_source_sha256']
                != preflight['original_test_source_sha256']
                or provenance['original_test_class_sha256']
                != preflight['original_test_class_sha256']
                or not provenance['assertions_enabled']
                or provenance['classpath_contains_graphchecker']):
            raise RuntimeError(f'provenance mismatch: {directory}')
        seeds.append({
            'name': directory.name,
            'test_seed': run['test_seed'],
            'elapsed_seconds': run['elapsed_seconds'],
            'junit_gate': c.junit_gate(log),
            'target_node': target['targetNode'],
            'target_client_id': target['targetClientId'],
            'target_guard_hits': len(guards),
            'target_throw_hits': len(throws),
            'bound_io_events': len(bound),
            'bound_pre_guard_events': sum(event['seq'] < guards[0]['seq'] for event in bound),
            'trace_sha256': sha(directory / 'events.jsonl'),
            'jacoco_sha256': sha(directory / 'jacoco.exec'),
        })
    points = c.seed_candidates(*(c.load_events(directory) for directory in c.SEEDS))
    receipt = {
        'case_id': 'SOLR-31',
        'node2_agent_sha256': build['agent_sha256'],
        'target': c.TARGET,
        'source_revision': preflight['source_revision'],
        'original_test_source_sha256': preflight['original_test_source_sha256'],
        'original_test_class_sha256': preflight['original_test_class_sha256'],
        'release_solr_core_jar_sha256': preflight['release_solr_core_jar_sha256'],
        'assertions_enabled': True,
        'classpath_contains_graphchecker': False,
        'seeds': seeds,
        'stable_pre_guard_actor_bound_selectors': points,
        'stable_selector_count': len(points),
        'healthy_elapsed_seconds': round(sum(item['elapsed_seconds'] for item in seeds), 3),
    }
    (c.HERE / 'calibration-v2.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'seeds': len(seeds), 'stable_selectors': len(points),
                      'healthy_elapsed_seconds': receipt['healthy_elapsed_seconds']},
                     sort_keys=True))


if __name__ == '__main__':
    main()
