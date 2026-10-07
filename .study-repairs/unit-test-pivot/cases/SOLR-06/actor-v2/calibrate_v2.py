#!/usr/bin/env python3
"""Two independent assertion-enabled original JUnits before fault selection."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build_v2 import HERE, sha
from run_v2 import AGENT, run, verify_build

SEEDS = (HERE / 'healthy-01', HERE / 'healthy-02')
COLLECTION = 'pull_replica_test_create_delete'
SOURCE = 'SOLR/COLLECTION/' + COLLECTION


def rows(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()
            if line.strip()]


def detail(value: str) -> dict[str, str]:
    return dict(part.split('=', 1) for part in value.split(';') if '=' in part)


def selected(row: dict) -> bool:
    return (row['event'] == 'TARGET_CHECK' and row['sourceKey'] == SOURCE
            and row['targetKey'].startswith('SOLR/PULL/' + COLLECTION + '/')
            and row['actorKey'].startswith('JETTY/')
            and row['leaderKey'].startswith('JETTY/')
            and detail(row['detail']).get('eligible') == 'true'
            and detail(row['detail']).get('replicaType') == 'PULL')


def target_signature(row: dict) -> tuple[str, str, str]:
    return row['actorKey'], row['targetKey'], row['leaderKey']


def audit(trace: list[dict]) -> dict:
    clients: dict[str, tuple[str, str, str]] = {}
    controllers: dict[str, str] = {}
    nodes: dict[str, str] = {}
    for row in trace:
        if row['event'] != 'CLIENT_BIND':
            continue
        info = detail(row['detail'])
        client, controller = info.get('clientIdentity'), info.get('controllerIdentity')
        node = info.get('nodeName')
        actor = row['actorKey']
        if not client or not controller or not node or not actor.startswith('JETTY/'):
            raise RuntimeError('incomplete SolrZkClient/ZkController binding')
        value = (actor, node, controller)
        if client in clients and clients[client] != value:
            raise RuntimeError('SolrZkClient rebound to another actor')
        if controller in controllers and controllers[controller] != actor:
            raise RuntimeError('ZkController rebound to another actor')
        if node in nodes and nodes[node] != actor:
            raise RuntimeError('physical node rebound to another actor')
        clients[client] = value
        controllers[controller] = actor
        nodes[node] = actor
    if set(nodes.values()) != {'JETTY/node1', 'JETTY/node2'}:
        raise RuntimeError('original two Jetty roles not both bound')
    guards = [row for row in trace if selected(row)]
    if not guards:
        raise RuntimeError('selected assertion was absent or actor/leader unbound')
    for row in trace:
        if row['event'] == 'IO_APPLIED':
            raise RuntimeError('healthy seed applied a fault')
        if row['event'] == 'TARGET_THROW':
            raise RuntimeError('selected assertion threw in healthy run')
        if row['event'] == 'IO_OBSERVED' and row['actorKey'].startswith('JETTY/'):
            info = detail(row['detail'])
            bound = clients.get(info.get('clientIdentity'))
            if bound is None or bound[0] != row['actorKey'] or bound[1] != info.get('nodeName'):
                raise RuntimeError('ZK I/O actor contradicts raw SolrZkClient binding')
    for row in guards:
        info = detail(row['detail'])
        bound = clients.get(info.get('clientIdentity'))
        if (bound is None or bound[0] != row['actorKey'] or
                controllers.get(info.get('controllerIdentity')) != row['actorKey'] or
                bound[1] != info.get('nodeName')):
            raise RuntimeError('selected guard actor contradicts raw ZkController binding')
        if not row['leaderKey'].startswith('JETTY/'):
            raise RuntimeError('selected guard leader role unresolved')
    summaries = [row for row in trace if row['event'] == 'SUMMARY']
    if len(summaries) != 1 or summaries[0]['detail'] != 'applied=0/0':
        raise RuntimeError('healthy trace incomplete')
    return {'bindings': len(clients), 'selected_guard_count': len(guards),
            'selected_target_signatures': sorted({target_signature(row) for row in guards}),
            'bound_jetty_roles': sorted(set(nodes.values()))}


def locked_hashes() -> dict[str, str]:
    names = ('build_v2.py', 'run_v2.py', 'smoke_v2.py', 'calibrate_v2.py',
             'campaign_v2.py', 'build-receipt.json')
    return {name: sha(HERE / name) for name in names}


def calibrate() -> dict:
    receipt = verify_build()
    results = []
    for seed in SEEDS:
        metadata = json.loads((seed / 'run.json').read_text())
        log = (seed / 'junit.log').read_text()
        if (metadata['exit_code'] != 0 or metadata['plan'] is not None or
                not metadata['assertions_enabled'] or
                not re.search(r'SOLR05_JUNIT_RESULT run=2 failures=0 ignored=0', log)):
            raise RuntimeError(f'original assertion-enabled JUnit did not pass both iterations: {seed}')
        if metadata['agent_sha256'] != receipt['agent_sha256']:
            raise RuntimeError('healthy seed used another V2 agent')
        results.append({'trace_sha256': sha(seed / 'events.jsonl'),
                        'jacoco_sha256': sha(seed / 'jacoco.exec'),
                        'audit': audit(rows(seed))})
    common = (set(map(tuple, results[0]['audit']['selected_target_signatures'])) &
              set(map(tuple, results[1]['audit']['selected_target_signatures'])))
    if not common:
        raise RuntimeError('no stable PULL replica/leader/actor target across healthy runs')
    result = {'case_id': 'SOLR-06', 'test': receipt['test'],
              'agent_sha256': sha(AGENT), 'runner_hashes': locked_hashes(),
              'common_target_signatures': sorted(common), 'healthy': results}
    temp = HERE / 'calibration-receipt.json.tmp'
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    temp.replace(HERE / 'calibration-receipt.json')
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> None:
    verify_build()
    for seed in SEEDS:
        if not (seed / 'run.json').is_file():
            run(seed)
    calibrate()


if __name__ == '__main__':
    main()
