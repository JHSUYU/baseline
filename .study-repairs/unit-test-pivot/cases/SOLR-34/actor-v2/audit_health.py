#!/usr/bin/env python3
"""Audit two clean and two instrumented original coordinator JUnit runs."""

import hashlib
import json
import re
from pathlib import Path

from build import HERE, SOURCE, TEST_CLASS, TEST_METHOD

ACTOR = 'SOLR34/COORDINATOR/test_coll'
SOURCE_KEY = 'SOLR/COORD_REQUEST/test_coll'
JUNIT = re.compile(r'SOLR_COORD_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)')
FIELDS = ('marker', 'siteId', 'sourceKey', 'actorKey', 'resource', 'hitOrdinal')


def read_run(name):
    directory = HERE / name
    run = json.loads((directory / 'run.json').read_text())
    match = JUNIT.search((directory / 'console.log').read_text())
    if run['exit_code'] or match is None or tuple(map(int, match.groups())) != (1, 0, 0):
        raise RuntimeError(f'original JUnit failed: {name}')
    if run['classpath_contains_graphchecker']:
        raise RuntimeError(f'GraphChecker in classpath: {name}')
    return {'name': name, 'elapsed_seconds': run['elapsed_seconds'],
            'test_seed': run['test_seed'], 'junit': [1, 0, 0]}


def instrumented(name):
    result = read_run(name)
    rows = [json.loads(line) for line in (HERE / name / 'events.jsonl').read_text().splitlines()]
    enters = [row for row in rows if row['event'] == 'TARGET_ENTER'
              and row['actorKey'] == ACTOR and row['sourceKey'] == SOURCE_KEY]
    guards = [row for row in rows if row['event'] == 'TARGET_CHECK'
              and row['marker'] == 'SOLR34:SYNTHETIC_COLLECTION_NONNULL_GUARD'
              and row['actorKey'] == ACTOR and row['sourceKey'] == SOURCE_KEY]
    throws = [row for row in rows if row['event'] == 'TARGET_THROW']
    if len(enters) != 1 or len(guards) != 1 or throws:
        raise RuntimeError(f'target reach failed: {name}')
    if 'syntheticCollection=.sys.COORDINATOR-COLL-conf' not in guards[0]['detail']:
        raise RuntimeError(f'wrong healthy synthetic collection: {name}')
    identity = enters[0]['detail'].removeprefix('clientIdentity=')
    if not identity.isdigit() or not enters[0]['physicalNode']:
        raise RuntimeError(f'missing target client/node: {name}')
    io = [row for row in rows if row['event'] == 'IO_OBSERVED']
    bound = [row for row in io if row['actorKey'] == ACTOR]
    pre = [row for row in bound if enters[0]['seq'] < row['seq'] < guards[0]['seq']]
    if not pre:
        raise RuntimeError(f'no same-client preguard I/O: {name}')
    for row in bound:
        if (row['physicalNode'] != enters[0]['physicalNode'] or
            'clientIdentity=' + identity not in row['detail'] or
            'targetClientIdentity=' + identity not in row['detail'] or
            'exactRequestClient=true' not in row['detail']):
            raise RuntimeError(f'client identity contradiction: {name}')
    for row in io:
        if row['actorKey'] != ACTOR and row['applied']:
            raise RuntimeError(f'wrong-client fault: {name}')
    result.update({'physical_node': enters[0]['physicalNode'],
                   'client_identity': identity,
                   'guard_detail': guards[0]['detail'],
                   'target_guard_count': len(guards), 'target_throw_count': len(throws),
                   'same_client_preguard_io': len(pre),
                   'different_client_io_excluded': len(io) - len(bound)})
    selectors = {json.dumps({field: row[field] for field in FIELDS}, sort_keys=True)
                 for row in pre}
    return result, selectors


def main():
    test = SOURCE / 'solr/core/src/test/org/apache/solr/search/TestCoordinatorRole.java'
    clean = [read_run(name) for name in ('clean-01', 'clean-02')]
    instrumented_runs = [instrumented(name) for name in ('healthy-01', 'healthy-02')]
    if [row['test_seed'] for row in clean] != [row[0]['test_seed'] for row in instrumented_runs]:
        raise RuntimeError('clean/instrumented seeds differ')
    result = {'test': TEST_CLASS + '#' + TEST_METHOD,
              'source_sha256': hashlib.sha256(test.read_bytes()).hexdigest(),
              'clean': clean,
              'instrumented': [row for row, _ in instrumented_runs],
              'common_exact_same_client_preguard_selectors':
                  [json.loads(item) for item in sorted(instrumented_runs[0][1] & instrumented_runs[1][1])],
              'wrong_client_fixture': 'SOLR34_ACTOR_IDENTITY_OK'}
    (HERE / 'health-audit.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'common_selectors': len(result['common_exact_same_client_preguard_selectors']),
                      'clean_passes': len(clean), 'instrumented_passes': len(instrumented_runs)},
                     sort_keys=True))


if __name__ == '__main__':
    main()
