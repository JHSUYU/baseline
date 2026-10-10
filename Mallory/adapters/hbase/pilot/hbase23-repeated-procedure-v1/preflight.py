#!/usr/bin/env python3
"""Check the HBASE-23 cluster-test overlay and frozen runtime without a JVM."""

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
OLD = HERE.parent / 'hbase23-zk-read-admission-v1'
SRC = HERE / 'src/org/apache/hadoop/hbase/procedure/TestProcedureManager.java'
JAR = HERE / 'release/test-overlay.jar'
CLASS = 'org/apache/hadoop/hbase/procedure/TestProcedureManager.class'
EXPECTED = {
    'source': '413a8c0a79a48801deffbac00ac4141b62d713ce4a9e2cb2c9bd3b9b0d0b09d9',
    'class': '64677c01307140d6ff376f0593d700f3cec4ecc83fdd091c97255a0a82060984',
    'jar': 'caffe63a22c53f0d93bcede813b033313b8784e40ef63fc1d3b27e6f0b53cabb',
    'site': 'f406aa03e1681177fad5049f3747098e548ed109cf2a68ad38ce5e5af061284a',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def verify(strict_runtime=False):
    # The prior physical-door package proves the unchanged production source,
    # bytecode, target site, retry handler, and accepted task handoff. Its
    # strict mode additionally checks node1's prepared release artifacts.
    spec = importlib.util.spec_from_file_location('hbase23_prior_preflight', OLD / 'preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = module.verify(strict_runtime=strict_runtime)
    check(sha(SRC) == EXPECTED['source'], 'test overlay source digest changed')
    check(sha(JAR) == EXPECTED['jar'], 'test overlay jar digest changed')
    check(sha(HERE / 'sites.json') == EXPECTED['site'], 'typed site digest changed')
    check((HERE / 'sites.json').read_bytes() == (OLD / 'sites.json').read_bytes(),
          'typed site differs from source-backed prior package')
    with ZipFile(JAR) as jar:
        names = set(jar.namelist())
        check(CLASS in names, 'test class absent from overlay jar')
        check(hashlib.sha256(jar.read(CLASS)).hexdigest() == EXPECTED['class'],
              'compiled test class digest changed')
        check(not any(name.endswith('.class') and name != CLASS for name in names),
              'overlay jar unexpectedly shadows another class')
    source = SRC.read_text()
    check('util.startMiniCluster(NUM_RS)' in source and
          'for (int i = 0; i < 16; i++)' in source and
          '"mytest-" + i' in source and
          'admin.execProcedureWithReturn(SimpleMasterProcedureManager.SIMPLE_SIGNATURE,' in source,
          'source does not run 16 distinct real cluster procedures')

    config = json.loads((HERE / 'healthy.json').read_text())
    prior = json.loads((OLD / 'healthy.json').read_text())
    check(config['target'] == prior['target'] and
          config['agent_include'] == prior['agent_include'] and
          config['agent_properties'] == prior['agent_properties'] and
          config['core_release'] == prior['core_release'],
          'instrumented production target or release changed')
    check(config['case_id'] == 'HBASE-23' and
          config['cluster_test'] == prior['cluster_test'] and
          config['calibration_only'] is True and
          config['auto_promote_if_healthy'] is False and
          config['budget']['trials'] == 1 and
          config['budget']['max_faults_per_trial'] == 1,
          'not the pinned healthy-only selected JUnit')
    check(config['site_file'] == str(HERE / 'sites.json'), 'site path changed')
    cp_idx = prior['command'].index('-cp') + 1
    check(config['command'][:cp_idx] == prior['command'][:cp_idx] and
          config['command'][cp_idx] == str(JAR) + ':' + prior['command'][cp_idx] and
          config['command'][cp_idx + 1:] == prior['command'][cp_idx + 1:],
          'command differs beyond shadowing the selected test class')
    check(config['mapping']['original_test_source_sha256'] ==
          prior['mapping']['test_source_sha256'] and
          config['mapping']['overlay_test_source_sha256'] == EXPECTED['source'] and
          config['mapping']['overlay_test_class_sha256'] == EXPECTED['class'] and
          config['mapping']['overlay_test_jar_sha256'] == EXPECTED['jar'] and
          config['mapping']['procedure_instances'] == 16,
          'test provenance or repeat bound changed')
    for artifact, expected in ((HERE / 'sites.json', EXPECTED['site']),
                               (JAR, EXPECTED['jar'])):
        check(any(row['path'] == str(artifact) and row['sha256'] == expected
                  for row in config['runtime_artifacts']),
              f'new runtime artifact not pinned: {artifact}')

    sys.path.insert(0, str(CORE))
    from Mallory.core.campaign import validate_config
    local_config = dict(config, cwd=str(module.SRC))
    validate_config(local_config)
    full = json.loads((HERE / 'full.json').read_text())
    expected_full = dict(config)
    expected_full['calibration_only'] = False
    expected_full['auto_promote_if_healthy'] = True
    expected_full['budget'] = {'max_faults_per_trial': 3, 'seconds': 3600,
                               'trial_timeout_seconds': 600, 'trials': 80}
    expected_full['mapping'] = dict(config['mapping'],
                                    status='staged_full_hold_pending_healthy_event_time_admission')
    check(full == expected_full, 'full configuration changed beyond gated budget')
    validate_config(dict(full, cwd=str(module.SRC)))
    deferred = []
    for item in config['runtime_artifacts'] + [config['source_equivalence_receipt']]:
        path = Path(item['path'])
        if path.exists():
            check(sha(path) == item['sha256'], f'runtime artifact digest changed: {path}')
        else:
            deferred.append(str(path))
    if strict_runtime:
        check(not deferred, f'node1 runtime artifact absent: {deferred}')
        validate_config(config)
    return {
        'case_id': 'HBASE-23',
        'status': 'node1_runtime_verified' if strict_runtime else
                  'offline_source_bytecode_valid_node1_runtime_deferred',
        'jvm_workloads_run': 0, 'fault_trials_run': 0,
        'overlay_test_source_sha256': EXPECTED['source'],
        'overlay_test_class_sha256': EXPECTED['class'],
        'overlay_test_jar_sha256': EXPECTED['jar'],
        'config_sha256': sha(HERE / 'healthy.json'),
        'full_config_sha256': sha(HERE / 'full.json'),
        'typed_door': base['typed_door'], 'exact_check': base['exact_check'],
        'node1_runtime_deferred': deferred,
        'go_gate': 'dispatch-owned node1 lane only; one healthy JUnit, zero faults',
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
