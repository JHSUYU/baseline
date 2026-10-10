#!/usr/bin/env python3
"""Verify existing TestZKProcedure four-member MiniZK selector without a JVM."""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
CORE = ROOT / ('Mallory/dispatch/releases/'
               'fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f')
PRIOR = HERE.parent / 'hbase23-zk-read-admission-v1'
SRC = Path('/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6')
TEST = SRC / 'hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestZKProcedure.java'
TESTS_JAR = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6-tests.jar')
TEST_CLASS = 'org/apache/hadoop/hbase/procedure/TestZKProcedure.class'
EXPECTED = {
    'test_source': '0cc57f0c0d21b679997580cc8169e1b8f70ed0bb77e8bbb6bb6d41e5bca8a2b2',
    'test_class': '7113aef4da384b134a5963f7bcfb2931b67cb85f9b6f0f2dc3194633c687ac3a',
    'tests_jar': 'b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5',
    'site': 'f406aa03e1681177fad5049f3747098e548ed109cf2a68ad38ce5e5af061284a',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def verify(strict_runtime=False):
    spec = importlib.util.spec_from_file_location('hbase23_prior_preflight', PRIOR / 'preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = module.verify(strict_runtime=strict_runtime)

    check(sha(TEST) == EXPECTED['test_source'], 'existing MiniZK test source changed')
    check(sha(TESTS_JAR) == EXPECTED['tests_jar'], 'existing compiled tests jar changed')
    with ZipFile(TESTS_JAR) as jar:
        check(hashlib.sha256(jar.read(TEST_CLASS)).hexdigest() == EXPECTED['test_class'],
              'selected compiled MiniZK test class changed')
    source = TEST.read_text()
    check('UTIL.startMiniZKCluster()' in source and
          'public void testMultipleMembers() throws Exception' in source and
          'runCommit("one", "two", "three", "four")' in source and
          'new ZKProcedureCoordinator(coordZkw, opDescription, COORDINATOR_NODE_NAME)' in source and
          'coordinator.startProcedure(new ForeignExceptionDispatcher(), opName, data, expected)' in source,
          'existing four-member real coordinator path changed')
    check(sha(HERE / 'sites.json') == EXPECTED['site'] and
          (HERE / 'sites.json').read_bytes() == (PRIOR / 'sites.json').read_bytes(),
          'typed ZooKeeper door changed')

    config = json.loads((HERE / 'healthy.json').read_text())
    prior = json.loads((PRIOR / 'healthy.json').read_text())
    check(config['case_id'] == 'HBASE-23' and
          config['cluster_test'] == 'org.apache.hadoop.hbase.procedure.TestZKProcedure#testMultipleMembers' and
          config['command'][-2:] == ['org.apache.hadoop.hbase.procedure.TestZKProcedure',
                                    'testMultipleMembers'] and
          config['command'][:-2] == prior['command'][:-2],
          'selector or unchanged classpath drifted')
    check(config['target'] == prior['target'] and
          config['agent_include'] == prior['agent_include'] and
          config['agent_properties'] == prior['agent_properties'] and
          config['core_release'] == prior['core_release'],
          'frozen target, instrumentation or core drifted')
    check(config['calibration_only'] is True and
          config['auto_promote_if_healthy'] is False and
          config['budget']['trials'] == 1 and
          config['budget']['max_faults_per_trial'] == 1,
          'configuration must run healthy JUnit only')
    check(config['site_file'] == str(HERE / 'sites.json') and
          config['mapping']['test_source_sha256'] == EXPECTED['test_source'] and
          config['mapping']['test_compiled_class_sha256'] == EXPECTED['test_class'],
          'test or typed site pin changed')
    check(any(row['path'] == str(HERE / 'sites.json') and row['sha256'] == EXPECTED['site']
              for row in config['runtime_artifacts']), 'typed site runtime pin missing')

    sys.path.insert(0, str(CORE))
    from Mallory.core.campaign import validate_config
    validate_config(dict(config, cwd=str(SRC)))
    deferred = []
    for pin in config['runtime_artifacts'] + [config['source_equivalence_receipt']]:
        path = Path(pin['path'])
        if path.is_file():
            check(sha(path) == pin['sha256'], f'runtime artifact changed: {path}')
        else:
            deferred.append(str(path))
    if strict_runtime:
        check(not deferred, f'node1 runtime artifacts absent: {deferred}')
        validate_config(config)
        equivalent_test = Path(config['source_equivalent_root']) / (
            'hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestZKProcedure.java')
        check(sha(equivalent_test) == EXPECTED['test_source'],
              'node1 equivalent existing MiniZK test source changed')
    return {
        'case_id': 'HBASE-23',
        'status': 'node1_runtime_verified' if strict_runtime else
                  'offline_existing_test_valid_node1_runtime_deferred',
        'selector': config['cluster_test'], 'jvm_workloads_run': 0, 'fault_trials_run': 0,
        'test_source_sha256': EXPECTED['test_source'],
        'test_class_sha256': EXPECTED['test_class'],
        'config_sha256': sha(HERE / 'healthy.json'),
        'exact_check': base['exact_check'], 'typed_door': base['typed_door'],
        'node1_runtime_deferred': deferred,
        'go_gate': 'dispatch-owned node1 lane only; one existing MiniZK JUnit, zero faults',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict-runtime', action='store_true')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    result = verify(strict_runtime=args.strict_runtime)
    rendered = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.write:
        (HERE / 'stage-preflight.json').write_text(rendered)
    print(rendered, end='')
