#!/usr/bin/env python3
"""Run original Solr JUnit with only case-local exact-site ASM and JaCoCo."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from build import (ASM, ASM_COMMONS, ASM_TREE, JACOCO_CORE, CLASSES, DIST,
                   HERE, JAVA, SOURCE, TEST_CLASS, TEST_METHOD, classpath)

RUN_ROOT = Path('/users/ZhenyuLi/solr18-independent-runs')
JACOCO = Path('/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar')
SOLRJ = DIST / 'dist/solr-solrj-8.11.4.jar'
CORE = DIST / 'dist/solr-core-8.11.4.jar'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(run_id='healthy-instrumented', plan=(), timeout=300):
    out = RUN_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)
    # A checkpoint may replay an interrupted run_id. Discard partial trace and
    # coverage before that replay; completed runs are handled by campaign.py.
    for name in ('events.tsv', 'jacoco.exec', 'covered_probes.txt',
                 'covered_methods.txt', 'covered_lines.txt', 'coverage.log'):
        (out / name).unlink(missing_ok=True)
    scratch = out / 'scratch'
    scratch.mkdir(exist_ok=True)
    cp = classpath()
    assert not any(any(word in Path(entry).name.lower() for word in
                       ('graphchecker', 'skeleton', 'causynth'))
                   for entry in cp.split(':') if Path(entry).suffix == '.jar')
    cmd = [str(JAVA / 'java'), '-ea', '-Xmx4g',
           '-Djava.awt.headless=true', '-Djava.io.tmpdir=' + str(scratch),
           '-DtempDir=' + str(scratch), '-Dtests.seed=D82A1912E3C1791F',
           '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
           '-Dcommon.dir=' + str(SOURCE / 'lucene'),
           '-Dtests.asserts=true', '-Dtests.slow=true', '-Dtests.nightly=true',
           '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
           '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
           '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
           '-Djdk.map.althashing.threshold=0',
           '-Djava.security.egd=file:/dev/./urandom',
           '-Dsolr18.trace=' + str(out / 'events.tsv'),
           '-Dsolr18.plan=' + '|||'.join(plan),
           '-javaagent:' + str(JACOCO) + '=destfile=' + str(out / 'jacoco.exec')
           + ',includes=org.apache.solr.*,dumponexit=true,append=false',
           '-cp', cp, 'research.solr18.OriginalJUnit', TEST_CLASS, TEST_METHOD]
    start = time.monotonic()
    with (out / 'console.log').open('w') as log:
        try:
            code = subprocess.run(cmd, cwd=SOURCE, env=os.environ.copy(),
                                  stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    text = (out / 'console.log').read_text(errors='replace')
    overlay_manager = CLASSES / 'org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class'
    overlay_client = CLASSES / 'org/apache/solr/common/cloud/SolrZkClient.class'
    manifest = {
        'case_id': 'SOLR-18', 'run_id': run_id,
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'original_junit': True, 'junit_exit': code,
        'elapsed_seconds': round(time.monotonic() - start, 3),
        'plan': list(plan), 'seed': 'D82A1912E3C1791F',
        'observed_io_scope': 'SolrZkClient_getData_setData_exists_all_paths',
        'test_started_count': text.count('SOLR18_TEST_STARTED '),
        'assumption_failure_count': text.count('SOLR18_ASSUMPTION_FAILURE '),
        'junit_summary_present': 'SOLR18_ORIGINAL_JUNIT ran=1 ignored=0 failures=0' in text,
        'instrumentation': 'case_local_asm_jacoco',
        'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
        'classpath_has_graphchecker_or_skeleton_jar': False,
        'original_source_commit': json.loads((HERE / 'build.json').read_text())['source_revision'],
        'original_solrj_jar_sha256': sha(SOLRJ),
        'original_core_jar_sha256': sha(CORE),
        'overlay_alias_manager_sha256': sha(overlay_manager),
        'overlay_solr_zk_client_sha256': sha(overlay_client),
        'probe_class_sha256': sha(CLASSES / 'research/solr18/Solr18Probe.class'),
    }
    if (out / 'jacoco.exec').exists() and (out / 'jacoco.exec').stat().st_size:
        report_cp = ':'.join(map(str, (CLASSES, JACOCO_CORE, ASM, ASM_TREE, ASM_COMMONS)))
        with (out / 'coverage.log').open('w') as log:
            subprocess.run([str(JAVA / 'java'), '-cp', report_cp,
                            'research.solr18.CoverageSolr18', str(out / 'jacoco.exec'),
                            str(CLASSES), str(SOLRJ), str(CORE)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        manifest['covered_probes'] = len((out / 'covered_probes.txt').read_text().splitlines())
        manifest['production_probe_filter'] = 'exact_class_membership_in_original_solrj_or_core_jar'
    temp = out / 'run.json.tmp'
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    os.replace(temp, out / 'run.json')
    print(json.dumps(manifest, sort_keys=True), flush=True)
    return manifest


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'healthy-instrumented')
