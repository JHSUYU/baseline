#!/usr/bin/env python3
"""Audit exact file read fault, original JUnit gate, and postfault assertion."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE


ROOT = HERE / 'calibration'
TARGET = 'SOLR/RELOAD/c8n_1x1/shard1/core_node2'
GUARD = 'SOLR21:REPLICA_NONNULL_GUARD'
THROW = 'SOLR21:REPLICA_NULL_ASSERTION'
FIELDS = ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')


def main() -> None:
    selected = json.loads((ROOT / 'file-read-selection.json').read_text())['logical_identity']
    directory = ROOT / 'file-read'
    rows = [json.loads(line) for line in (directory / 'events.jsonl').open() if line.strip()]
    metadata = json.loads((directory / 'run.json').read_text())
    console = (directory / 'console.log').read_text()
    match = re.search(r'SOLR_RELOAD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)',
                      console)
    junit = dict(zip(('ran', 'ignored', 'failures'), map(int, match.groups()))) if match else None
    applied = [row for row in rows if row['event'] == 'IO_OBSERVED' and row['applied']]
    exact = (len(applied) == 1
             and all(applied[0][field] == selected[field] for field in FIELDS)
             and rows[-1]['event'] == 'SUMMARY' and rows[-1]['detail'] == 'applied=1/1')
    faults = [row for row in rows if row['event'] == 'IO_OBSERVED'
              and row['marker'] == selected['marker']
              and row['siteId'] == selected['siteId']
              and row['sourceKey'] == selected['sourceKey']]
    guards = [row for row in rows if row['event'] == 'TARGET_CHECK'
              and row['marker'] == GUARD and row['sourceKey'] == TARGET]
    throws = [row for row in rows if row['event'] == 'TARGET_THROW'
              and row['marker'] == THROW and row['sourceKey'] == TARGET]
    result = {
        'case_id': 'SOLR-21',
        'agent_sha256': metadata['agent_sha256'],
        'classpath_contains_graphchecker': metadata['classpath_contains_graphchecker'],
        'original_source_revision': metadata['original_source_revision'],
        'elapsed_seconds': metadata['elapsed_seconds'],
        'junit_exit': metadata['exit_code'],
        'original_junit': junit,
        'exact_fault_applied': exact,
        'fault': applied[0] if applied else None,
        'same_site_attempts': faults,
        'target_guard_after_fault': sum(row['seq'] > applied[-1]['seq'] for row in guards)
                                    if exact else 0,
        'target_guard_same_thread_after_fault': sum(
            row['seq'] > applied[-1]['seq'] and row['threadId'] == applied[-1]['threadId']
            for row in guards) if exact else 0,
        'target_assertion_throw_after_fault': sum(row['seq'] > applied[-1]['seq']
                                                  for row in throws) if exact else 0,
        'target_guard_details': [row['detail'] for row in guards],
    }
    output = ROOT / 'file-read-audit.json'
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
