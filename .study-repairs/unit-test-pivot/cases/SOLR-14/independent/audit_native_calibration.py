#!/usr/bin/env python3
"""Verify that a strict native ZooKeeper fault is retried before the split guards."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE


def main() -> None:
    root = HERE / 'native/calibration/first-read'
    run = json.loads((root / 'run.json').read_text())
    events = [json.loads(line) for line in (root / 'events.jsonl').open()]
    applied = [event for event in events if event['event'] == 'IO_OBSERVED'
               and event['matched'] and event['applied']]
    assert len(applied) == 1, len(applied)
    selected = applied[0]
    assert selected['marker'] == 'FAULT:ZK_NATIVE:exists'
    assert 'SplitShardCmd.split#L164->SolrZkClient.lambda$exists$' in selected['siteId']
    assert selected['sourceKey'].endswith('/shard1/PARENT_LEADER')
    assert selected['resource'] == '/live_nodes/NODE'
    same = [event for event in events if event['event'] == 'IO_OBSERVED'
            and all(event[name] == selected[name] for name in
                    ('marker', 'siteId', 'sourceKey', 'resource', 'threadId'))]
    retried = [event for event in same if event['seq'] > selected['seq']
               and event['hitOrdinal'] == selected['hitOrdinal'] + 1
               and not event['applied']]
    assert retried, 'original Solr did not retry the selected native operation'
    targets = [event for event in events if event['event'] == 'TARGET_CHECK'
               and event['seq'] > selected['seq']
               and event['sourceKey'] == selected['sourceKey']]
    markers = {event['marker'] for event in targets}
    assert {'TARGET:SOLR14:CHECK', 'TARGET:SOLR15_16:OUTER'} <= markers
    exact_throws = [event for event in events if event['event'] == 'TARGET_THROW'
                    and event['sourceKey'] == selected['sourceKey']]
    junit = re.search(r'SOLR_SPLIT_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)',
                      (root / 'console.log').read_text())
    assert junit and tuple(map(int, junit.groups())) == (1, 0, 0)
    assert run['exit_code'] == 0 and not run['classpath_contains_graphchecker']
    result = {
        'test': run['test'],
        'agent_sha256': run['agent_sha256'],
        'elapsed_seconds': run['elapsed_seconds'],
        'junit': {'ran': 1, 'ignored': 0, 'failures': 0},
        'strict_applied_count': 1,
        'selected': selected,
        'same_thread_retry': retried[0],
        'post_fault_target_markers': sorted(markers),
        'selected_target_throw_count': len(exact_throws),
        'fault_semantics': 'KeeperException.ConnectionLoss at original SolrZkClient retry lambda entry',
    }
    path = HERE / 'native/calibration/audit.json'
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(path)


if __name__ == '__main__':
    main()
