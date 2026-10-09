#!/usr/bin/env python3
"""Select one repeated, observed collection-state read before the target guard."""

from __future__ import annotations

import json
from pathlib import Path

from build import HERE

FIELDS = ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')
SOURCE = 'SOLR/REPLICA/collection1/shard1/core_node3'


def events(directory: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / directory / 'events.jsonl').open()]


def main() -> None:
    first, second = events('healthy-01'), events('healthy-02')
    cutoff = min(event['seq'] for event in first
                 if event['event'] == 'TARGET_CHECK' and event['sourceKey'] == SOURCE)
    repeated = {tuple(event[field] for field in FIELDS) for event in second
                if event['event'] == 'IO_OBSERVED'}
    candidates = [event for event in first
                  if event['event'] == 'IO_OBSERVED' and event['seq'] < cutoff
                  and event['sourceKey'] == SOURCE
                  and event['resource'] == '/collections/collection1/state.json'
                  and event['marker'] == 'FAULT:ZK_NATIVE:getData'
                  and 'fetchCollectionState' in event['siteId']
                  and tuple(event[field] for field in FIELDS) in repeated]
    if not candidates:
        raise RuntimeError('no repeated direct collection-state read before target')
    selected = candidates[-1]
    point = {field: selected[field] for field in FIELDS}
    directory = HERE / 'calibration'
    directory.mkdir(exist_ok=True)
    report = {'selection': point, 'first_healthy_seq': selected['seq'],
              'first_healthy_target_seq': cutoff,
              'evidence': ['healthy-01/events.jsonl', 'healthy-02/events.jsonl']}
    (directory / 'selection.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    properties = ['count=1'] + [f'step.1.{field}={point[field]}' for field in FIELDS]
    (directory / 'fault.properties').write_text('\n'.join(properties) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
