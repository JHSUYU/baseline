#!/usr/bin/env python3
"""Record the graph-independent healthy seed and selector provenance."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

from build import HERE
from coverage import branch_totals, covered_probes
from fuzz import SEEDS, load_events, seed_candidates, target_sources, is_target_core


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    seeds = []
    records = []
    for path in SEEDS:
        events = load_events(path)
        records.append(events)
        run = json.loads((path / 'run.json').read_text())
        active = set()
        io_inside = target_inside = 0
        for event in events:
            key = (event['threadId'], event['policyId'])
            if event['event'] == 'ONCOMMIT_WINDOW_START':
                active.add(key)
            elif event['event'] == 'ONCOMMIT_WINDOW_END':
                active.discard(key)
            elif active:
                io_inside += event['event'] == 'FAULT_POINT_OBSERVED'
                target_inside += event['event'] == 'TARGET_CHECK'
        if active:
            raise RuntimeError('unclosed onCommit window in ' + str(path))
        seed = {
            'directory_io': sum(e['event'] == 'FAULT_POINT_OBSERVED' for e in events),
            'directory_io_by_family': dict(Counter(e['marker'] for e in events
                if e['event'] == 'FAULT_POINT_OBSERVED')),
            'directory_unresolved_source': sum(e['sourceKey'].startswith('UNRESOLVED')
                for e in events if e['event'] == 'FAULT_POINT_OBSERVED'),
            'target_checks': sum(e['event'] == 'TARGET_CHECK' for e in events),
            'target_check_sources': dict(Counter(e['sourceKey'] for e in events
                if e['event'] == 'TARGET_CHECK')),
            'target_check_physical_nodes': dict(Counter(e['physicalNode'] for e in events
                if e['event'] == 'TARGET_CHECK')),
            'target_throws': sum(e['event'] == 'TARGET_THROW' for e in events),
            'onCommit_windows': sum(e['event'] == 'ONCOMMIT_WINDOW_START' for e in events),
            'directory_io_inside_latest_to_known_window': io_inside,
            'target_checks_inside_latest_to_known_window': target_inside,
            'original_junit_exit': run['exit_code'],
            'original_test_revision': run['original_source_revision'],
            'classpath_contains_graphchecker': run['classpath_contains_graphchecker'],
            'elapsed_seconds': run['elapsed_seconds'],
            'production_probes': len(covered_probes(path / 'jacoco.exec')),
            'production_branch_totals': branch_totals(path / 'jacoco.exec'),
            'sha256': {name: sha(path / name) for name in
                       ('events.jsonl', 'jacoco.exec', 'run.json')},
        }
        seeds.append(seed)
    points, sources = seed_candidates(*records)
    build = json.loads((HERE / 'build.json').read_text())
    status = subprocess.check_output(['git', '-C', str(HERE / 'solr-pristine'),
                                      'status', '--porcelain'], text=True).strip()
    result = {
        'case_id': 'SOLR-22',
        'methodology': 'coverage_io_independent_asm_jacoco',
        'original_test': 'org.apache.solr.cloud.TestPullReplica#testAddDocs',
        'agent_sha256': build['agent_sha256'],
        'agent_graphchecker_classpath': build['classpath_contains_graphchecker'],
        'original_source_modified': bool(status),
        'healthy_seeds': seeds,
        'stable_io_selectors': len(points),
        'stable_target_core_selectors': sum(is_target_core(p, sources) for p in points),
        'stable_io_families': len(set((p['marker'], p['siteId'], p['sourceKey'])
                                      for p in points)),
        'target_logical_sources': sorted(sources),
        'selector_identity_fields': ['marker', 'ASM call site', 'logical Solr core path',
                                     'file resource', 'per-identity hit ordinal'],
        'physical_node_recorded_separately': True,
        'static_skeleton_loaded_or_woven': False,
    }
    (HERE / 'seed-audit.json').write_text(json.dumps(result, indent=2,
                                                   sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'healthy_seeds'},
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
