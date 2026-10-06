#!/usr/bin/env python3
"""Verify the exact one-shot coordinator ZK fault and later target guard."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE


def main() -> None:
    directory = HERE / 'calibration/coord-read'
    run = json.loads((directory / 'run.json').read_text())
    selected = json.loads((HERE / 'calibration/coord-read-selection.json').read_text())
    rows = [json.loads(line) for line in (directory / 'events.jsonl').open() if line.strip()]
    exact = selected['logical_identity']
    fields = tuple(exact)
    applied = [row for row in rows if row['event'] == 'IO_OBSERVED' and row['applied']]
    guards = [row for row in rows if row['event'] == 'TARGET_CHECK'
              and row['marker'] == 'SOLR34:SYNTHETIC_COLLECTION_NONNULL_GUARD'
              and row['sourceKey'] == 'SOLR/COORD_REQUEST/test_coll']
    throws = [row for row in rows if row['event'] == 'TARGET_THROW'
              and row['marker'] == 'SOLR34:SYNTHETIC_COLLECTION_MISSING'
              and row['sourceKey'] == 'SOLR/COORD_REQUEST/test_coll']
    summaries = [row for row in rows if row['event'] == 'SUMMARY']
    match = re.search(r'SOLR_COORD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)',
                      (directory / 'console.log').read_text())
    passed = (run['exit_code'] == 0 and match is not None and
              tuple(map(int, match.groups())) == (1, 0, 0))
    strict = (len(applied) == 1 and
              all(applied[0][field] == exact[field] for field in fields) and
              len(summaries) == 1 and summaries[0]['detail'] == 'applied=1/1')
    post = [guard for guard in guards if strict and guard['seq'] > applied[0]['seq']]
    if not (passed and strict and len(post) == 1 and not throws and
            post[0]['detail'] ==
            'syntheticCollection=.sys.COORDINATOR-COLL-conf'):
        raise RuntimeError('calibration does not satisfy exact injection and target gate')
    result = {
        'case_id': 'SOLR-34',
        'original_source_revision': run['original_source_revision'],
        'agent_sha256': run['agent_sha256'],
        'classpath_contains_graphchecker': run['classpath_contains_graphchecker'],
        'elapsed_seconds': run['elapsed_seconds'],
        'original_junit': {'ran': 1, 'ignored': 0, 'failures': 0},
        'exact_fault_applied': True,
        'fault': applied[0],
        'target_guard_after_fault': len(post),
        'target_guard_same_thread_after_fault': sum(
            guard['threadId'] == applied[0]['threadId'] for guard in post),
        'target_guard_details': [guard['detail'] for guard in post],
        'exact_target_exception_after_fault': 0,
    }
    output = HERE / 'calibration/coord-read-audit.json'
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
