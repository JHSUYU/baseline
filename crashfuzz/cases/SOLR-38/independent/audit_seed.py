#!/usr/bin/env python3
"""Summarize exact original-JUnit target reach and observed pretarget I/O."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re


def audit(run_dir: Path) -> dict:
    console = (run_dir / 'console.log').read_text(errors='replace')
    match = re.search(r'SOLR38_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', console)
    junit_gate = tuple(map(int, match.groups())) if match else None
    run_meta = json.loads((run_dir / 'run.json').read_text())
    events = [json.loads(line) for line in (run_dir / 'events.jsonl').read_text().splitlines()]
    checks = [event for event in events if event['event'] == 'TARGET_CHECK'
              and event['marker'] == 'SOLR38:LEADER_IDENTITY_GUARD']
    throws = [event for event in events if event['event'] == 'TARGET_THROW'
              and event['marker'] == 'SOLR38:LEADER_IDENTITY_THROW']
    cutoff = max((event['seq'] for event in checks), default=-1)
    io = [event for event in events if event['event'] == 'IO_OBSERVED'
          and event['seq'] < cutoff and not event['sourceKey'].startswith('UNRESOLVED:')
          and not event['siteId'].startswith('UNRESOLVED:')]
    selectors = {
        (event['marker'], event['siteId'], event['sourceKey'], event['resource'],
         event['hitOrdinal']) for event in io
    }
    report = {
        'original_junit': {
            'ran_ignored_failures': junit_gate,
            'passed': junit_gate == (1, 0, 0) and run_meta['exit_code'] == 0,
            'elapsed_seconds': run_meta['elapsed_seconds'],
            'exit_code': run_meta['exit_code'],
            'agent_sha256': run_meta['agent_sha256'],
        },
        'target_check_count': len(checks),
        'target_throw_count': len(throws),
        'target_logical_replicas': dict(Counter(event['sourceKey'] for event in checks)),
        'target_physical_nodes': dict(Counter(event['physicalNode'] for event in checks)),
        'target_guard_values': dict(Counter(event['detail'] for event in checks)),
        'pretarget_resolved_io_count': len(io),
        'pretarget_exact_selector_count': len(selectors),
        'pretarget_io_families': len({selector[:4] for selector in selectors}),
        'pretarget_io_by_api': dict(Counter(event['marker'] for event in io)),
        'graphchecker_classpath': run_meta['classpath_contains_graphchecker'],
        'methodology': 'coverage_io_no_graph',
    }
    (run_dir / 'seed-audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    audit(parser.parse_args().run_dir)
