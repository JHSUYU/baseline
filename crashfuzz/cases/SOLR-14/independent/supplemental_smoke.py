#!/usr/bin/env python3
"""Healthy-smoke another unchanged original multi-node shard-split cluster test."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import run as primary
from build import HERE, JAVA8, SOURCE, original_classpath


TEST_CLASS = 'org.apache.solr.cloud.api.collections.ShardSplitTest'
TEST_METHOD = os.environ.get('SOLRSPLIT_SUPPLEMENTAL_METHOD', 'testSplitStaticIndexReplication')
SOURCE_FILE = SOURCE / 'solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java'
TEST_PLUGIN_SOURCE = SOURCE / 'solr/core/src/test/org/apache/solr/search/function/NvlValueSourceParser.java'
TEST_FACET_SOURCE = SOURCE / 'solr/core/src/test/org/apache/solr/search/facet/DebugAgg.java'
CLASSES = HERE / 'supplemental/shardsplit/classes'
OUT = HERE / 'supplemental/shardsplit' / os.environ.get('SOLRSPLIT_SUPPLEMENTAL_RUN', 'healthy-01')
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4')
EXTRA_JARS = [DIST / 'dist/solr-analysis-extras-8.11.4.jar',
              DIST / 'contrib/analysis-extras/lucene-libs/lucene-analyzers-icu-8.11.4.jar']


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', original_classpath(),
                    '-sourcepath', str(SOURCE / 'solr/core/src/test'),
                    '-d', str(CLASSES), str(SOURCE_FILE), str(TEST_PLUGIN_SOURCE),
                    str(TEST_FACET_SOURCE)], check=True)
    primary.TEST_CLASS = TEST_CLASS
    primary.TEST_METHOD = TEST_METHOD
    original_cp = primary.original_classpath
    primary.original_classpath = lambda: ':'.join(
        [str(CLASSES), original_cp(), *(str(path) for path in EXTRA_JARS)])
    plan = os.environ.get('SOLRSPLIT_SUPPLEMENTAL_FAULT_PLAN')
    agent = os.environ.get('SOLRSPLIT_SUPPLEMENTAL_AGENT')
    exit_code = primary.run(
        OUT, fault_plan=Path(plan) if plan else None,
        nightly=TEST_METHOD == 'testSplitWithChaosMonkey',
        test_seed=os.environ.get('SOLRSPLIT_SUPPLEMENTAL_SEED', 'F0993D5343E20BA4'),
        agent_path=Path(agent) if agent else None)
    meta = json.loads((OUT / 'run.json').read_text())
    meta.update({'original_test_source_sha256': hashlib.sha256(SOURCE_FILE.read_bytes()).hexdigest(),
                 'original_test_class_sha256': hashlib.sha256((CLASSES / 'org/apache/solr/cloud/api/collections/ShardSplitTest.class').read_bytes()).hexdigest(),
                 'supplemental_kind': 'unchanged_original_multinode_cluster_test',
                 'original_release_extra_jars': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                                 for path in EXTRA_JARS}})
    (OUT / 'run.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
