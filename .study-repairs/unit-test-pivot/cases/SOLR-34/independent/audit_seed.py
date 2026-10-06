#!/usr/bin/env python3
"""Audit two unchanged coordinator-cluster JUnit seeds and stable I/O points."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE


TARGET = 'SOLR/COORD_REQUEST/test_coll'
SYNTHETIC = 'SOLR/COLLECTION/.sys.COORDINATOR-COLL-conf'
GUARD = 'SOLR34:SYNTHETIC_COLLECTION_NONNULL_GUARD'
FIELDS = ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')
JUNIT = re.compile(r'SOLR_COORD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)')


def read(directory: Path) -> tuple[list[dict], dict, dict]:
    rows = [json.loads(line) for line in (directory / 'events.jsonl').open() if line.strip()]
    run = json.loads((directory / 'run.json').read_text())
    match = JUNIT.search((directory / 'console.log').read_text())
    if run['exit_code'] or match is None or tuple(map(int, match.groups())) != (1, 0, 0):
        raise RuntimeError(f'original JUnit failed: {directory}')
    guards = [row for row in rows if row['event'] == 'TARGET_CHECK'
              and row['marker'] == GUARD and row['sourceKey'] == TARGET]
    throws = [row for row in rows if row['event'] == 'TARGET_THROW'
              and row['sourceKey'] == TARGET]
    if len(guards) != 1 or throws or guards[0]['detail'] != \
            'syntheticCollection=.sys.COORDINATOR-COLL-conf':
        raise RuntimeError(f'exact healthy target not established: {directory}')
    return rows, run, guards[0]


def relevant(row: dict) -> bool:
    return (row['event'] == 'IO_OBSERVED' and
            (row['sourceKey'] == TARGET or
             (row['sourceKey'] == SYNTHETIC and
              row['resource'].startswith('/collections/.sys.COORDINATOR-COLL-conf'))))


def selector(row: dict) -> dict:
    return {field: row[field] for field in FIELDS}


def main() -> None:
    directories = [HERE / 'healthy-04', HERE / 'healthy-05']
    pairs = [read(directory) for directory in directories]
    entries = []
    exact = []
    for directory, (rows, run, guard) in zip(directories, pairs):
        selected = [row for row in rows if row['seq'] < guard['seq'] and relevant(row)]
        entries.append({
            'run': directory.name,
            'test_seed': run['test_seed'],
            'elapsed_seconds': run['elapsed_seconds'],
            'original_junit_passed': True,
            'agent_sha256': run['agent_sha256'],
            'classpath_contains_graphchecker': run['classpath_contains_graphchecker'],
            'guard': guard,
            'eligible_io_events_before_guard': len(selected),
            'coordinator_request_io_events_before_guard': sum(
                row['sourceKey'] == TARGET for row in selected),
        })
        exact.append({json.dumps(selector(row), sort_keys=True) for row in selected})
    common = sorted(exact[0] & exact[1])
    result = {
        'case_id': 'SOLR-34',
        'test': pairs[0][1]['test'],
        'original_source_revision': pairs[0][1]['original_source_revision'],
        'runs': entries,
        'common_exact_pretarget_selector_count': len(common),
        'common_exact_pretarget_selectors': [json.loads(item) for item in common],
        'common_coordinator_request_selector_count': sum(
            json.loads(item)['sourceKey'] == TARGET for item in common),
        'physical_node_is_evidence_not_selector': True,
    }
    output = HERE / 'seed-audit.json'
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: value for key, value in result.items()
                      if key != 'common_exact_pretarget_selectors'}, sort_keys=True))


if __name__ == '__main__':
    main()
