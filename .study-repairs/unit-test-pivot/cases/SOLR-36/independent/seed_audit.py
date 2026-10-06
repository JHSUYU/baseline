#!/usr/bin/env python3
"""Compact reproducible audit of the two original healthy JUnit records."""

from __future__ import annotations

from collections import Counter
import json

from fuzz import (HERE, SEEDS, GUARDS, guard_events, throw_events,
                  junit_gate, load_events, seed_candidates, family, point,
                  point_id, relevant)


def main() -> None:
    output: dict = {'test': 'org.apache.solr.cloud.api.collections.ShardSplitTest#test',
                    'source': 'unchanged Solr 8.11.4 original JUnit',
                    'runs': []}
    traces = []
    for directory in SEEDS:
        events = load_events(directory)
        traces.append(events)
        meta = json.loads((directory / 'run.json').read_text())
        row = {
            'run': directory.name,
            'junit_gate': junit_gate((directory / 'console.log').read_text()),
            'elapsed_seconds': meta['elapsed_seconds'],
            'exit_code': meta['exit_code'],
            'source_revision': meta['original_source_revision'],
            'agent_sha256': meta['agent_sha256'],
            'classpath_contains_graphchecker': meta['classpath_contains_graphchecker'],
            'targets': {},
        }
        for case_id in GUARDS:
            checks = guard_events(events, case_id)
            row['targets'][case_id] = {
                'guard_count': len(checks),
                'throw_count': len(throw_events(events, case_id)),
                'logical_sources': dict(Counter(x['sourceKey'] for x in checks)),
                'guard_details': dict(Counter(x['detail'] for x in checks)),
                'physical_nodes': sorted({x['physicalNode'] for x in checks}),
            }
        output['runs'].append(row)
    points = seed_candidates(*traces)
    stable_full = []
    for events in traces:
        last_guard = max(event['seq'] for case_id in GUARDS
                         for event in guard_events(events, case_id))
        stable_full.append({point_id(point(event)) for event in events
                            if event['event'] == 'IO_OBSERVED'
                            and event['seq'] < last_guard
                            and relevant(point(event))})
    output['stable_precursor_io'] = {
        'full_exact_intersection_count': len(stable_full[0] & stable_full[1]),
        'selector_count': len(points),
        'family_count': len({family(item) for item in points}),
        'logical_sources': dict(Counter(item['sourceKey'] for item in points)),
        'marker_counts': dict(Counter(item['marker'] for item in points)),
        'examples': [point(event) for event in traces[0]
                     if event['event'] == 'IO_OBSERVED'
                     and event['siteId'].endswith('ZkDistribStateManager.setData#L157->SolrZkClient.lambda$setData$7(Ljava/lang/String;[BI)Lorg/apache/zookeeper/data/Stat;')
                     and event['resource'].startswith('/collections/collection1')][:3],
    }
    destination = HERE / 'seed-audit.json'
    destination.write_text(json.dumps(output, indent=2, sort_keys=True) + '\n')
    print(destination)


if __name__ == '__main__':
    main()
