#!/usr/bin/env python3
"""Verify exact original ZkController/SolrZkClient ASM hooks offline."""

from pathlib import Path
import subprocess
import zipfile

from build_v2 import DIST, HERE, JAVA8, asm_jars, classpath
from calibrate_v2 import audit, selected


def main() -> None:
    directory = HERE / 'original-class-bytes'
    directory.mkdir(exist_ok=True)
    pairs = (
        ('org/apache/solr/cloud/ZkController', DIST / 'solr-core-8.11.4.jar'),
        ('org/apache/solr/common/cloud/SolrZkClient', DIST / 'solr-solrj-8.11.4.jar'),
    )
    arguments = []
    for name, jar in pairs:
        path = directory / (name.replace('/', '_') + '.class')
        with zipfile.ZipFile(jar) as archive:
            path.write_bytes(archive.read(name + '.class'))
        arguments.extend((name, str(path)))
    cp = ':'.join((str(HERE / 'agent-classes'), classpath(),
                   *(str(p) for p in asm_jars())))
    subprocess.run([str(JAVA8 / 'java'), '-cp', cp,
                    'research.solraddv2.Smoke', *arguments], check=True)
    try:
        audit([])
    except RuntimeError as failure:
        if 'three Jetty roles' not in str(failure):
            raise
    else:
        raise AssertionError('absent target/actor binding passed healthy audit')
    target = {
        'event': 'TARGET_CHECK', 'sourceKey': 'SOLR/COLLECTION/testAddMultipleReplicas',
        'targetKey': 'SOLR/CORE/testAddMultipleReplicas/shard1/core_node5/core_p1',
        'actorKey': 'JETTY/node1', 'leaderKey': 'JETTY/node2/core_n1',
        'operation': 'CORE_AVAILABILITY', 'siteId': 'ZkController.register:1325',
        'detail': 'eligible=true;replicaType=PULL',
    }
    if not selected(target) or selected({**target, 'actorKey': 'UNBOUND:ZKCONTROLLER'}) or \
            selected({**target, 'leaderKey': 'UNBOUND:LEADER_URL'}):
        raise AssertionError('selected target actor/leader fail-close gate broken')
    print('SOLR07_V2_TARGET_FAIL_CLOSED_OK')


if __name__ == '__main__':
    main()
