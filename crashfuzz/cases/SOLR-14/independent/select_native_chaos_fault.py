#!/usr/bin/env python3
"""Select an exact second live-node read shared by two original chaos tests."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE
from fuzz import load_events, point, point_id, write_plan


ROOT = HERE / 'supplemental/shardsplit'
SOURCE = 'SOLR/SPLIT/collection1/shard1/PARENT_LEADER'
SITE = 'SplitShardCmd.split#L523->SolrZkClient.lambda$exists$'


def read(name: str) -> tuple[list[dict], dict]:
    directory = ROOT / name
    run = json.loads((directory / 'run.json').read_text())
    junit = re.search(r'SOLR_SPLIT_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)',
                      (directory / 'console.log').read_text())
    assert junit and tuple(map(int, junit.groups())) == (1, 0, 0)
    assert run['exit_code'] == 0 and not run['classpath_contains_graphchecker']
    events = load_events(directory)
    first = [event for event in events if event['event'] == 'TARGET_CHECK'
             and event['marker'] == 'TARGET:SOLR14:CHECK'
             and event['sourceKey'] == SOURCE]
    outer = [event for event in events if event['event'] == 'TARGET_CHECK'
             and event['marker'] == 'TARGET:SOLR15_16:OUTER'
             and event['sourceKey'] == SOURCE]
    assert len(first) == len(outer) == 1
    assert first[0]['seq'] < outer[0]['seq']
    return events, run


def main() -> None:
    runs = ('native-chaos-02', 'native-chaos-03')
    traces = [read(name) for name in runs]
    chosen = []
    for events, run in traces:
        direct = [event for event in events if event['event'] == 'IO_OBSERVED'
                  and SITE in event['siteId'] and event['sourceKey'] == SOURCE]
        assert len(direct) == 1, direct
        item = direct[0]
        assert item['marker'] == 'FAULT:ZK_NATIVE:exists'
        assert item['resource'] == '/live_nodes/NODE'
        chosen.append(item)
    selector = point(chosen[0])
    assert point_id(selector) == point_id(point(chosen[1]))
    assert traces[0][1]['agent_sha256'] == traces[1][1]['agent_sha256']
    plan = ROOT / 'native-chaos-plan-01.properties'
    write_plan(plan, [selector])
    report = {
        'test': traces[0][1]['test'],
        'agent_sha256': traces[0][1]['agent_sha256'],
        'strict_selector': selector,
        'stable_healthy_seeds': [
            {'run': name, 'seed': run['test_seed'],
             'elapsed_seconds': run['elapsed_seconds'],
             'seq': event['seq'], 'threadId': event['threadId'],
             'physicalNode': event['physicalNode'], 'detail': event['detail']}
            for name, (events, run), event in zip(runs, traces, chosen)],
        'fault_model': 'one KeeperException.ConnectionLoss inside original SolrZkClient retry lambda',
        'target_oracle': 'exact SplitShardCmd.java:536/539 guard and 538/543 SolrException throw after applied fault',
    }
    selection = ROOT / 'native-chaos-plan-01-selection.json'
    selection.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(selection)


if __name__ == '__main__':
    main()
