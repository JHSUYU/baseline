#!/usr/bin/env python3
"""One original JUnit fault trial with the shared JVM gate and JaCoCo feedback."""
from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from calibrate import (HERE, FIRST, ROOT, LOCK, JAVA, SOURCE, TEST_CLASS,
                       alternate_classpath, command, compile_probe,
                       resource_gate, sha, stamp, validate_frozen, atomic_json)
from fault_audit import check

JACOCO_CORE = Path('/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar')
ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.6/asm-tree-9.6.jar')
ASM_COMMONS = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.6/asm-commons-9.6.jar')
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist')
SOLRJ = DIST / 'solr-solrj-8.11.4.jar'
CORE = DIST / 'solr-core-8.11.4.jar'
METHOD = 'testDeleteAliasWithExistingCollectionName'


def covered(path: Path, kind: str) -> set[str]:
    source = path / ('covered_' + kind + '.txt')
    return set(source.read_text().splitlines()) if source.is_file() else set()


def baseline() -> dict:
    output = {}
    for kind in ('probes', 'methods', 'lines'):
        roots = (ROOT / 'derived-coverage-healthy-a',
                 ROOT / 'derived-coverage-healthy-b')
        output[kind] = sorted(set().union(*(covered(root, kind) for root in roots)))
    return output


def prepare_baseline() -> dict:
    receipts = {}
    for label in ('a', 'b'):
        source = ROOT / (METHOD + '-instrumented-' + label)
        prior = json.loads((source / 'run.json').read_text())
        assert sha(source / 'jacoco.exec') == prior['raw_file_sha256']['jacoco.exec']
        out = ROOT / ('derived-coverage-healthy-' + label)
        receipt_path = out / 'derived-receipt.json'
        if not receipt_path.exists():
            assert not out.exists(), f'incomplete derived baseline: {out}'
            out.mkdir()
            shutil.copy2(source / 'jacoco.exec', out / 'jacoco.exec')
            report = coverage(out)
            assert report['available'], report
            atomic_json(receipt_path, {'source_run_id': prior['run_id'],
                        'source_jacoco_sha256': prior['raw_file_sha256']['jacoco.exec'],
                        'covered_file_sha256': {p.name: sha(p) for p in out.iterdir()
                                                if p.name.startswith('covered_')}})
        receipt = json.loads(receipt_path.read_text())
        assert receipt['source_run_id'] == prior['run_id']
        assert sha(out / 'jacoco.exec') == receipt['source_jacoco_sha256']
        assert all(sha(out / name) == expected for name, expected
                   in receipt['covered_file_sha256'].items())
        receipts[label] = receipt
    return receipts


def coverage(out: Path) -> dict:
    exec_file = out / 'jacoco.exec'
    if not exec_file.is_file() or not exec_file.stat().st_size:
        return {'available': False, 'reason': 'no nonempty jacoco.exec'}
    cp = ':'.join(map(str, (FIRST / 'classes', JACOCO_CORE, ASM, ASM_TREE, ASM_COMMONS)))
    with (out / 'coverage.log').open('w') as log:
        code = subprocess.run([str(JAVA / 'java'), '-cp', cp,
                               'research.solr18.CoverageSolr18', str(exec_file),
                               str(FIRST / 'classes'), str(SOLRJ), str(CORE)],
                              stdout=log, stderr=subprocess.STDOUT).returncode
    if code:
        return {'available': False, 'reason': 'coverage process failed', 'exit_code': code}
    prior = baseline()
    gains = {kind: sorted(covered(out, kind) - set(prior[kind]))
             for kind in ('probes', 'methods', 'lines')}
    return {'available': True,
            'production_filter': 'class_membership_in_original_solrj_or_core_jar',
            'covered_counts': {kind: len(covered(out, kind)) for kind in prior},
            'new_vs_healthy': gains}


def run(run_id: str, plan: list[str], phase: str) -> dict:
    assert plan and len(plan) == len(set(plan)) and len(plan) <= 10
    assert run_id.startswith(('pilot-', 'trial-'))
    frozen = validate_frozen()
    healthy = json.loads((HERE / 'healthy-audit.json').read_text())
    assert healthy['frozen_campaign_state_sha256'] == frozen['first_campaign_state_sha256']
    assert healthy['original_junit_class_sha256'] == frozen['original_junit_class_sha256']
    out = ROOT / run_id
    assert not out.exists(), f'uncleared trial directory: {out}'
    with LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        gate = resource_gate()
        probe_sha = compile_probe()
        assert probe_sha == healthy['alternate_probe_class_sha256']
        baseline_receipts = prepare_baseline()
        out.mkdir(parents=True)
        scratch = out / 'scratch'
        scratch.mkdir()
        cmd = command(METHOD, True, scratch, out)
        replacement = '-Dsolr18.plan=' + '|||'.join(plan)
        assert cmd.count('-Dsolr18.plan=') == 1
        cmd[cmd.index('-Dsolr18.plan=')] = replacement
        start = time.monotonic()
        with (out / 'console.log').open('w') as log:
            try:
                code = subprocess.run(cmd, cwd=SOURCE, stdout=log,
                                      stderr=subprocess.STDOUT, timeout=360).returncode
            except subprocess.TimeoutExpired:
                code = 124
        log_text = (out / 'console.log').read_text(errors='replace')
        fault_report = check(out / 'events.tsv', plan) if (out / 'events.tsv').is_file() else None
        coverage_report = coverage(out)
        manifest = {'schema_version': 1, 'run_id': run_id, 'phase': phase,
                    'test': TEST_CLASS + '#' + METHOD, 'original_junit': True,
                    'original_junit_class_sha256': frozen['original_junit_class_sha256'],
                    'original_source_revision': frozen['original_source_revision'],
                    'original_source_sha256': frozen['original_source_sha256'],
                    'alternate_probe_class_sha256': probe_sha,
                    'overlay_alias_manager_sha256': sha(FIRST / 'classes/org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class'),
                    'overlay_solr_zk_client_sha256': sha(FIRST / 'classes/org/apache/solr/common/cloud/SolrZkClient.class'),
                    'classpath_sha256': hashlib.sha256(alternate_classpath().encode()).hexdigest(),
                    'classpath_has_graphchecker_runtime': False,
                    'seed': 'D82A1912E3C1791F', 'plan': plan,
                    'started_at_utc': gate['checked_at_utc'], 'finished_at_utc': stamp(),
                    'elapsed_seconds': round(time.monotonic() - start, 3),
                    'junit_exit': code,
                    'junit_summary_present': 'SOLR18_ORIGINAL_JUNIT ran=1 ignored=0 failures=0' in log_text,
                    'test_started_count': log_text.count('SOLR18_TEST_STARTED '),
                    'assumption_failure_count': log_text.count('SOLR18_ASSUMPTION_FAILURE '),
                    'gate': gate, 'fault_audit': fault_report,
                    'healthy_coverage_baseline': baseline_receipts,
                    'coverage': coverage_report,
                    'raw_file_sha256': {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
        atomic_json(out / 'run.json', manifest)
        return manifest
