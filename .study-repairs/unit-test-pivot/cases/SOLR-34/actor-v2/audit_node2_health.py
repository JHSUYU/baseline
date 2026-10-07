#!/usr/bin/env python3
"""Check cross-host actor-relative selectors before checkpoint continuation."""

import hashlib
import json
import re
import socket
from pathlib import Path

from build import HERE, SOURCE
from fuzz_v2 import ACTOR, GUARD, TARGET, point, point_id, validate_actor_trace

JUNIT = re.compile(r'SOLR_COORD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)')


def read(name, instrumented):
    directory = HERE / name
    run = json.loads((directory / 'run.json').read_text())
    match = JUNIT.search((directory / 'console.log').read_text())
    if run['exit_code'] or match is None or tuple(map(int, match.groups())) != (1, 0, 0):
        raise RuntimeError(f'original JUnit failed: {name}')
    if run['classpath_contains_graphchecker']:
        raise RuntimeError(f'GraphChecker classpath: {name}')
    result = {'name': name, 'execution_host': socket.gethostname(),
              'test_seed': run['test_seed'], 'elapsed_seconds': run['elapsed_seconds'],
              'original_junit': [1, 0, 0],
              'agent_sha256': run['agent_sha256']}
    if not instrumented:
        return result, None
    rows = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    binding = validate_actor_trace(rows)
    guards = [event for event in rows if event['event'] == 'TARGET_CHECK'
              and event['marker'] == GUARD and event['sourceKey'] == TARGET
              and event['actorKey'] == ACTOR]
    throws = [event for event in rows if event['event'] == 'TARGET_THROW']
    if len(guards) != 1 or throws or 'syntheticCollection=.sys.COORDINATOR-COLL-conf' not in guards[0]['detail']:
        raise RuntimeError(f'exact guard failed: {name}')
    pre = [event for event in rows if event['event'] == 'IO_OBSERVED'
           and event['actorKey'] == ACTOR and event['seq'] < guards[0]['seq']]
    result.update({'binding': binding, 'same_client_preguard_io': len(pre),
                   'exact_guard_count': len(guards), 'exact_target_throws': len(throws),
                   'different_client_io_excluded': sum(event['event'] == 'IO_OBSERVED'
                                                       and event['actorKey'] != ACTOR
                                                       for event in rows)})
    return result, {point_id(point(event)) for event in pre}


def main():
    if not socket.gethostname().startswith('node2.'):
        raise RuntimeError('must audit node2 execution on node2')
    test = SOURCE / 'solr/core/src/test/org/apache/solr/search/TestCoordinatorRole.java'
    expected_test = '2e2c6a24b8f2ea37bb1dc4b95842e7974b166e000acf8393ba7d1342bddb59b3'
    if hashlib.sha256(test.read_bytes()).hexdigest() != expected_test:
        raise RuntimeError('original JUnit source differs')
    agent = HERE / 'solrcoord-actor-v2-agent.jar'
    expected_agent = json.loads((HERE / 'agent-build.json').read_text())['agent_sha256']
    if hashlib.sha256(agent.read_bytes()).hexdigest() != expected_agent:
        raise RuntimeError('agent jar differs')
    clean = [read(f'node2-clean-0{i}', False)[0] for i in (1, 2)]
    healthy = [read(f'node2-healthy-0{i}', True) for i in (1, 2)]
    if [item['test_seed'] for item in clean] != [item[0]['test_seed'] for item in healthy]:
        raise RuntimeError('clean/instrumented seeds differ')
    common = healthy[0][1] & healthy[1][1]
    node0 = json.loads((HERE / 'health-audit.json').read_text())
    previous = {point_id(item) for item in node0['common_exact_same_client_preguard_selectors']}
    if not common or common != previous:
        raise RuntimeError(f'cross-host selector mismatch node0={len(previous)} node2={len(common)}')
    receipt = {'host': socket.gethostname(), 'original_test_sha256': expected_test,
               'agent_sha256': expected_agent, 'clean': clean,
               'instrumented': [item for item, _ in healthy],
               'same_exact_actor_relative_selectors_as_node0': True,
               'common_selectors': [json.loads(item) for item in sorted(common)]}
    (HERE / 'node2-health-audit.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'node2_clean_passes': len(clean),
                      'node2_instrumented_passes': len(healthy),
                      'common_same_client_selectors': len(common)}, sort_keys=True))


if __name__ == '__main__':
    main()
