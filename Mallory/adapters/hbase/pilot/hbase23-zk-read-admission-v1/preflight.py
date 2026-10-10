#!/usr/bin/env python3
"""HBASE-23 typed ZooKeeper-read admission checks; never starts a JVM."""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PRIMARY_SRC = Path('/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6')
SRC = PRIMARY_SRC if PRIMARY_SRC.is_dir() else Path(json.loads((HERE / 'healthy.json').read_text())['source_equivalent_root'])
DIST = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib')
CORE = ROOT / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f'
BYTECODE = ROOT / 'Mallory/adapters/hbase/pilot/hbase24-recoverable-read-v1/preflight.py'
TARGET = 'org/apache/hadoop/hbase/procedure/ZKProcedureCoordinator'
COORD = 'org/apache/hadoop/hbase/procedure/ProcedureCoordinator'
RECOVERABLE = 'org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper'
ZKUTIL = 'org/apache/hadoop/hbase/zookeeper/ZKUtil'
WATCHER_GETDATA = '(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B'
CHECK = ('org.apache.hadoop.hbase.procedure.ZKProcedureCoordinator'
         '#sendGlobalBarrierReached(Lorg/apache/hadoop/hbase/procedure/Procedure;Ljava/util/List;)V@127:branch:5')
DOOR = ('org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper'
        '#getData(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B@405:door:1')
EXPECTED = {
    'target_source': (SRC / 'hbase-server/src/main/java/org/apache/hadoop/hbase/procedure/ZKProcedureCoordinator.java',
                      '7f1ebc383086f82c98d0460d7c0504d5fd59e590176b65931c3061bcdac947b7'),
    'test_source': (SRC / 'hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestProcedureManager.java',
                    '35dee7363efa0ade2a906fb1b75bc1ab1396ae48c02ff75db0b18f676d6cd135'),
    'recoverable_source': (SRC / 'hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper.java',
                           'f946cd3195c5969b55ce5d079c272a7b12d673c5406a98ef026dc8fcea18fa88'),
    'zkutil_source': (SRC / 'hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKUtil.java',
                      '413a0487863e7b7c8c5299f939eaec45ac33321fec8af2c5d160b64c7cf04b40'),
    'coordinator_source': (SRC / 'hbase-server/src/main/java/org/apache/hadoop/hbase/procedure/ProcedureCoordinator.java',
                           'c08ab94bd55a3bdd54a93dce08dbacd4e13cccc99b760282bd66800512725e3a'),
    'server_jar': (DIST / 'hbase-server-2.6.6.jar',
                   '27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696'),
    'zookeeper_jar': (DIST / 'hbase-zookeeper-2.6.6.jar',
                      '6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957'),
    'zk_dependency_jar': (DIST / 'zookeeper-3.8.6.jar',
                          'a00943a87b9c83379267ebda487be1ddb83e9997a03e59f9199338a033b71ed7'),
    'bytecode_reader': (BYTECODE,
                        'f1d1835b8896a6dd45648aa2478093607e052587c64dae0f8e61d2ef0639a604'),
    'adapter_transformer_source': (ROOT / 'Mallory/adapters/hbase/src/main/java/edu/uva/liftlab/mallory/hbase/HBaseAdapterTransformer.java',
                                   '60ca093f6dddd7e0d07ff253175505c6e751c3e764320762edba6fb9272e55e0'),
    'adapter_hooks_source': (ROOT / 'Mallory/adapters/hbase/src/main/java/edu/uva/liftlab/mallory/hbase/HBaseHooks.java',
                             '6f77dd858bfe27f42b6ecc3c823d3c0df42f955c8366ebc20749ae5c85fd2944'),
    'core_manifest': (CORE / 'manifest.json',
                      '30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def bytecode_reader():
    spec = importlib.util.spec_from_file_location('hbase24_class_reader', BYTECODE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(strict_runtime=False):
    hashes = {}
    for name, (path, expected) in EXPECTED.items():
        actual = sha(path)
        check(actual == expected, f'{name} hash mismatch: {actual}')
        hashes[name] = actual
    config = json.loads((HERE / 'healthy.json').read_text())
    adapter_candidates = [ROOT / 'Mallory/adapters/hbase/releases/future-token-handoffs-v1/mallory-hbase-adapter.jar',
                          Path(config['agent_properties']['adapter.jar'])]
    available_adapter = next((path for path in adapter_candidates if path.is_file()), None)
    check(available_adapter is not None, 'pinned future-handoff adapter jar absent')
    check(sha(available_adapter) == 'ab943e3fda02126261f99703cafeb4b6b0f71b6b5d645a29abb3498d43851cd1',
          'future-handoff adapter jar hash mismatch')
    hashes['future_handoff_adapter_jar'] = sha(available_adapter)

    reader = bytecode_reader()
    server_jar = DIST / 'hbase-server-2.6.6.jar'
    zk_jar = DIST / 'hbase-zookeeper-2.6.6.jar'
    target_class = reader.read_class(server_jar, TARGET)
    check(hashlib.sha256(target_class).hexdigest() ==
          '8d43fa6f2820e626e9174810628b8ee1ecb841daf4e6736cf537c124ca75be41',
          'target compiled class changed')
    target = reader.parse_class(target_class)
    target_body = target['methods'][('sendGlobalBarrierReached',
                                     '(Lorg/apache/hadoop/hbase/procedure/Procedure;Ljava/util/List;)V')]
    target_calls = reader.calls(target, target_body)
    expected_target_calls = [
        (103, (ZKUTIL, 'watchAndCheckExists',
               '(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)Z'), 123),
        (118, (ZKUTIL, 'getData',
               '(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)[B'), 124),
        (136, ('org/apache/hadoop/hbase/shaded/protobuf/ProtobufUtil',
               'isPBMagicPrefix', '([B)Z'), 127),
    ]
    for offset, ref, line in expected_target_calls:
        check(any(c[0] == offset and c[2] == ref and c[3] == line for c in target_calls),
              f'missing target call {ref} at {offset}/{line}')
    target_text = EXPECTED['target_source'][0].read_text()
    check(target_text.index('if (ZKUtil.watchAndCheckExists') <
          target_text.index('byte[] dataFromMember = ZKUtil.getData') <
          target_text.index('if (!ProtobufUtil.isPBMagicPrefix(dataFromMember))'),
          'target source order changed')

    coord_class = reader.read_class(server_jar, COORD)
    check(hashlib.sha256(coord_class).hexdigest() ==
          '342fa281c6e4373831f40eb888a69061fcd778aab3f4283f936ebf4435e95a34',
          'ProcedureCoordinator compiled class changed')
    coord = reader.parse_class(coord_class)
    coord_calls = reader.calls(coord, coord['methods'][('submitProcedure',
                              '(Lorg/apache/hadoop/hbase/procedure/Procedure;)Z')])
    check(any(offset == 281 and ref == ('java/util/concurrent/ExecutorService', 'submit',
             '(Ljava/util/concurrent/Callable;)Ljava/util/concurrent/Future;') and line == 166
              for offset, _, ref, line in coord_calls), 'accepted worker submission changed')
    adapter_source = EXPECTED['adapter_transformer_source'][0].read_text()
    hooks_source = EXPECTED['adapter_hooks_source'][0].read_text()
    check('instrumentCoordinatorSubmit(method)' in adapter_source and
          'coordinatorCallable' in adapter_source and 'enterZkActor' in adapter_source and
          'registerZkCoordinatorAfterConstruction' in adapter_source,
          'adapter identity or worker handoff hooks changed')
    check('Probe.wrapCallable(procedure, "hbase:ProcedureCoordinator.submitProcedure")' in
          hooks_source and 'Probe.withRegisteredNode(rpcs)' in hooks_source,
          'exact worker token or actor propagation changed')

    recoverable_class = reader.read_class(zk_jar, RECOVERABLE)
    check(hashlib.sha256(recoverable_class).hexdigest() ==
          '0902568eb8ddf20c85c622de7a014d9c97b95588e1bb8c2cd75445670336726f',
          'RecoverableZooKeeper compiled class changed')
    recoverable = reader.parse_class(recoverable_class)
    read_body = recoverable['methods'][('getData', WATCHER_GETDATA)]
    read_calls = reader.calls(recoverable, read_body)
    check(any(offset == 40 and ref == ('org/apache/zookeeper/ZooKeeper',
          'getData', WATCHER_GETDATA) and line == 405 for offset, _, ref, line in read_calls),
          'physical ZooKeeper getData selector changed')
    check(any(start <= 40 < end and kind == 'org/apache/zookeeper/KeeperException'
              for start, end, _, kind in read_body['catches']),
          'physical read no longer enters KeeperException retry handler')
    check(any(ref[0] == RECOVERABLE and ref[1] == 'retryOrThrow' and line == 414
              for _, _, ref, line in read_calls), 'ConnectionLoss retry path changed')
    recoverable_text = EXPECTED['recoverable_source'][0].read_text()
    check('case CONNECTIONLOSS:' in recoverable_text and
          'retryOrThrow(retryCounter, e, "getData")' in recoverable_text and
          'conf.getInt("zookeeper.recovery.retry", 3)' in recoverable_text,
          'source-backed single-fault retry changed')
    error = reader.parse_class(reader.read_class(DIST / 'zookeeper-3.8.6.jar',
                               'org/apache/zookeeper/KeeperException$ConnectionLossException'))
    check(error['superclass'] == 'org/apache/zookeeper/KeeperException' and
          ('<init>', '()V') in error['methods'], 'typed fault class unavailable')

    site = json.loads((HERE / 'sites.json').read_text())
    check(len(site['doors']) == 1 and site['doors'][0] == {
        'clazz': RECOVERABLE.replace('/', '.'), 'method': 'getData',
        'descriptor': WATCHER_GETDATA, 'line': 405,
        'callee': 'org.apache.zookeeper.ZooKeeper#getData' + WATCHER_GETDATA,
        'exception_class': 'org.apache.zookeeper.KeeperException$ConnectionLossException'},
        'typed site differs from compiled read')
    check(config['case_id'] == 'HBASE-23' and config['cluster_test'] ==
          'org.apache.hadoop.hbase.procedure.TestProcedureManager#testSimpleProcedureManager',
          'selected unmodified JUnit changed')
    check(config['target']['check_sites'] == [CHECK] and config['target']['source_line'] == 131,
          'exact target changed')
    check(config['calibration_only'] is True and config['auto_promote_if_healthy'] is False and
          config['budget']['trials'] == 1 and config['budget']['max_faults_per_trial'] == 1,
          'config is not healthy-only')
    check(config['agent_properties']['auto.io.doors'] is False and
          config['require_event_time_paths'] is True and
          config['allow_local_timeline_doors'] is True,
          'typed, same-thread local event-time admission disabled')
    check(RECOVERABLE.replace('/', '.') in config['agent_include'] and
          TARGET.replace('/', '.') in config['agent_include'],
          'selected instrumented class missing')
    check(config['site_file'] == str(HERE / 'sites.json'), 'site file mismatch')
    check(any(row['path'] == str(HERE / 'sites.json') and row['sha256'] == sha(HERE / 'sites.json')
              for row in config['runtime_artifacts']), 'site digest not pinned')
    test_text = EXPECTED['test_source'][0].read_text()
    check('util.startMiniCluster(NUM_RS)' in test_text and
          'admin.execProcedureWithReturn(' in test_text, 'cluster test source changed')
    sys.path.insert(0, str(CORE))
    from Mallory.core.campaign import validate_config
    local_config = dict(config, cwd=str(SRC))
    validate_config(local_config)

    deferred = []
    for pin in config['runtime_artifacts'] + [config['source_equivalence_receipt']]:
        path = Path(pin['path'])
        if path.is_file():
            check(sha(path) == pin['sha256'], f'runtime artifact hash mismatch: {path}')
        else:
            deferred.append(str(path))
    if strict_runtime:
        check(not deferred, f'node1 runtime artifacts absent: {deferred}')
        validate_config(config)
        test_source = Path(config['source_equivalent_root']) / (
            'hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestProcedureManager.java')
        check(sha(test_source) == config['mapping']['test_source_sha256'],
              'node1 test source hash mismatch')

    return {
        'case_id': 'HBASE-23', 'status': 'node1_runtime_verified' if not deferred else
        'offline_source_bytecode_valid_node1_runtime_deferred', 'jvm_workloads_run': 0,
        'healthy_admitted': False, 'fault_trials_admitted': False,
        'selector': config['cluster_test'], 'exact_check': CHECK, 'typed_door': DOOR,
        'site_sha256': sha(HERE / 'sites.json'), 'config_sha256': sha(HERE / 'healthy.json'),
        'source_artifact_sha256': hashes, 'node1_runtime_deferred': deferred,
        'bytecode': {'watch_exists_offset': 103, 'read_offset': 118,
                     'pb_prefix_offset': 136, 'physical_read_offset': 40,
                     'coordinator_submit_offset': 281},
        'next_gate': 'Dispatch syncs package to node1, runs strict no-JVM preflight, then a bounded healthy-only MiniCluster calibration and an explicitly labeled same-thread local-timeline audit.'
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict-runtime', action='store_true')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    result = verify(args.strict_runtime)
    rendered = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.write:
        (HERE / 'stage-preflight.json').write_text(rendered)
    print(rendered, end='')
