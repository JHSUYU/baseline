#!/usr/bin/env python3
"""Offline HBASE-24 source, bytecode, and selector admission check."""

import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SRC = Path('/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6')
DIST = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib')
TARGET = 'org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs'
RECOVERABLE = 'org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper'
ZKUTIL = 'org/apache/hadoop/hbase/zookeeper/ZKUtil'
WATCHER_GETDATA = '(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B'
EXPECTED = {
    'target_source': ('hbase-server/src/main/java/org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs.java', 'ba0ee569fccf2a69057860800bc05a2fe1db0d5a4b368c490485ee542b0c55b2'),
    'junit_source': ('hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestZKProcedure.java', '0cc57f0c0d21b679997580cc8169e1b8f70ed0bb77e8bbb6bb6d41e5bca8a2b2'),
    'recoverable_source': ('hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper.java', 'f946cd3195c5969b55ce5d079c272a7b12d673c5406a98ef026dc8fcea18fa88'),
    'zkutil_source': ('hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKUtil.java', '413a0487863e7b7c8c5299f939eaec45ac33321fec8af2c5d160b64c7cf04b40'),
    'server_jar': (DIST / 'hbase-server-2.6.6.jar', '27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696'),
    'zookeeper_jar': (DIST / 'hbase-zookeeper-2.6.6.jar', '6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957'),
    'zk_dependency_jar': (DIST / 'zookeeper-3.8.6.jar', 'a00943a87b9c83379267ebda487be1ddb83e9997a03e59f9199338a033b71ed7'),
    'agent_jar': (ROOT / 'Mallory/instrumentation/target/mallory-agent.jar', '07c23da7699217aa4f51c389cde3539ee241ece05efa5d11575bc5d804cf4e80'),
    'adapter_jar': (ROOT / 'Mallory/adapters/hbase/target/mallory-hbase-adapter.jar', '5f83ae1146141c3559073c13fd5b9b952f09af87e4c9d83d2288fbd2c4fd2827'),
    'prior_actor_audit': (ROOT / 'data/mallory/triage/HBASE-24-5a-actor-audit-v1.json', 'e8170a76851755caf05de4d2c90cebaeb77534c190615dda12775edced7f8121'),
    'core_release_manifest': (ROOT / 'Mallory/dispatch/releases/5a35547d57dd66c29b15260f04cf52941b907e28bc07f0ceb0f1d4b3782c4040/manifest.json', '765d6f19a7dc425457d567a71193dec2722a83d8c0140e20fc85dd9bb80230ae'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        data = self.data[self.pos:self.pos + n]
        assert len(data) == n
        self.pos += n
        return data

    def u1(self):
        return self.take(1)[0]

    def u2(self):
        return struct.unpack('>H', self.take(2))[0]

    def u4(self):
        return struct.unpack('>I', self.take(4))[0]


def parse_class(data):
    rd = Reader(data)
    assert rd.u4() == 0xCAFEBABE
    rd.take(4)
    cp = [None] * rd.u2()
    index = 1
    while index < len(cp):
        tag = rd.u1()
        if tag == 1:
            cp[index] = rd.take(rd.u2()).decode('utf-8')
        elif tag in (3, 4):
            rd.take(4)
        elif tag in (5, 6):
            rd.take(8)
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            cp[index] = (tag, rd.u2())
        elif tag in (9, 10, 11, 12, 17, 18):
            cp[index] = (tag, rd.u2(), rd.u2())
        elif tag == 15:
            cp[index] = (tag, rd.u1(), rd.u2())
        else:
            raise AssertionError(f'unknown constant pool tag {tag}')
        index += 1

    def class_name(i):
        assert cp[i][0] == 7
        return cp[cp[i][1]]

    def method_ref(i):
        ref = cp[i]
        if not isinstance(ref, tuple) or ref[0] not in (10, 11):
            return None
        nt = cp[ref[2]]
        return class_name(ref[1]), cp[nt[1]], cp[nt[2]]

    rd.u2()  # access flags
    rd.u2()  # this class
    superclass = class_name(rd.u2())
    rd.take(2 * rd.u2())
    for _ in range(rd.u2()):
        rd.take(6)
        for _ in range(rd.u2()):
            rd.take(2)
            rd.take(rd.u4())

    methods = {}
    for _ in range(rd.u2()):
        rd.take(2)
        name, descriptor = cp[rd.u2()], cp[rd.u2()]
        body = {}
        for _ in range(rd.u2()):
            attr_name = cp[rd.u2()]
            attr = Reader(rd.take(rd.u4()))
            if attr_name != 'Code':
                continue
            attr.take(4)
            code = attr.take(attr.u4())
            catches = []
            for _ in range(attr.u2()):
                start, end, handler, caught = (attr.u2() for _ in range(4))
                catches.append((start, end, handler, class_name(caught) if caught else None))
            lines = []
            for _ in range(attr.u2()):
                nested_name = cp[attr.u2()]
                nested = Reader(attr.take(attr.u4()))
                if nested_name == 'LineNumberTable':
                    lines = [(nested.u2(), nested.u2()) for _ in range(nested.u2())]
            body = {'code': code, 'catches': catches, 'lines': lines}
        methods[(name, descriptor)] = body
    return {'superclass': superclass, 'methods': methods, 'method_ref': method_ref}


def calls(parsed, body):
    code = body['code']
    found = []
    for offset in range(len(code) - 2):
        if code[offset] not in (0xB6, 0xB7, 0xB8, 0xB9):
            continue
        ref = parsed['method_ref'](struct.unpack('>H', code[offset + 1:offset + 3])[0])
        if ref is None:
            continue
        line = next((number for start, number in reversed(body['lines']) if start <= offset), None)
        found.append((offset, code[offset], ref, line))
    return found


def read_class(jar, clazz):
    with zipfile.ZipFile(jar) as archive:
        return archive.read(clazz + '.class')


def main():
    hashes = {}
    for name, (path, expected) in EXPECTED.items():
        path = Path(path) if Path(path).is_absolute() else SRC / path
        actual = sha(path)
        assert actual == expected, f'{name} SHA mismatch: {actual}'
        hashes[name] = actual

    server_bytes = read_class(DIST / 'hbase-server-2.6.6.jar', TARGET)
    assert hashlib.sha256(server_bytes).hexdigest() == '845ed06384339ccc65b1d33c38d75a7265f4245c4b4871454a6662c24814f48b'
    target = parse_class(server_bytes)
    target_body = target['methods'][('startNewSubprocedure', '(Ljava/lang/String;)V')]
    target_calls = calls(target, target_body)
    getdata_calls = [(offset, line) for offset, _, ref, line in target_calls
                     if ref == (ZKUTIL, 'getData', '(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)[B')]
    prefix_calls = [(offset, line) for offset, _, ref, line in target_calls
                    if ref == ('org/apache/hadoop/hbase/shaded/protobuf/ProtobufUtil',
                               'isPBMagicPrefix', '([B)Z')]
    assert getdata_calls == [(143, 204)], getdata_calls
    assert prefix_calls == [(150, 205)], prefix_calls
    # ASTORE 5 then ALOAD 5 proves the read result is the predicate operand.
    assert target_body['code'][146:150] == bytes((0x3a, 5, 0x19, 5))

    zkutil_bytes = read_class(DIST / 'hbase-zookeeper-2.6.6.jar', ZKUTIL)
    assert hashlib.sha256(zkutil_bytes).hexdigest() == 'c355fd476e81ec304bb968eb909c725dfea59e3a5f24e62382bdc2c93b68bac6'
    zkutil = parse_class(zkutil_bytes)
    util_calls = calls(zkutil, zkutil['methods'][('getData', '(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)[B')])
    assert any(ref == (RECOVERABLE, 'getData', WATCHER_GETDATA) for _, _, ref, _ in util_calls)

    recoverable_bytes = read_class(DIST / 'hbase-zookeeper-2.6.6.jar', RECOVERABLE)
    recoverable = parse_class(recoverable_bytes)
    body = recoverable['methods'][('getData', WATCHER_GETDATA)]
    selected = [(offset, opcode, line) for offset, opcode, ref, line in calls(recoverable, body)
                if ref == ('org/apache/zookeeper/ZooKeeper', 'getData', WATCHER_GETDATA)]
    assert selected == [(40, 0xB6, 405)], selected
    catches = [entry for entry in body['catches'] if entry[0] <= 40 < entry[1]
               and entry[3] == 'org/apache/zookeeper/KeeperException']
    assert len(catches) == 1, catches
    assert any(ref[0] == RECOVERABLE and ref[1] == 'retryOrThrow' and line == 414
               for _, _, ref, line in calls(recoverable, body))
    # The source hash fixes the ConnectionLoss switch arm and the backward retry loop.
    source_text = (SRC / EXPECTED['recoverable_source'][0]).read_text()
    assert 'case CONNECTIONLOSS:' in source_text and 'retryOrThrow(retryCounter, e, "getData")' in source_text
    assert 'retryCounter.sleepUntilNextRetry();' in source_text

    error = parse_class(read_class(DIST / 'zookeeper-3.8.6.jar',
                                   'org/apache/zookeeper/KeeperException$ConnectionLossException'))
    assert error['superclass'] == 'org/apache/zookeeper/KeeperException'
    assert ('<init>', '()V') in error['methods']
    sites = json.loads((HERE / 'sites.json').read_text())
    assert len(sites['doors']) == 1 and sites['doors'][0]['line'] == 405
    assert sites['doors'][0]['callee'] == 'org.apache.zookeeper.ZooKeeper#getData' + WATCHER_GETDATA
    assert sites['doors'][0]['exception_class'] == 'org.apache.zookeeper.KeeperException$ConnectionLossException'
    config = json.loads((HERE / 'healthy.json').read_text())
    assert config['calibration_only'] is True and config['budget']['trials'] == 1
    assert config['agent_properties']['auto.io.doors'] is False
    assert config['cluster_test'] == 'org.apache.hadoop.hbase.procedure.TestZKProcedure#testMultipleMembers'
    assert RECOVERABLE.replace('/', '.') in config['agent_include']
    assert config['runtime_artifacts'][-1]['sha256'] == sha(HERE / 'sites.json')
    test_text = (SRC / EXPECTED['junit_source'][0]).read_text()
    assert 'runCommit("one", "two", "three", "four")' in test_text
    assert test_text.index('comms.start(member, procMember)') < test_text.index(
        'coordinator.startProcedure(new ForeignExceptionDispatcher(), opName, data, expected)')

    result = {
        'case_id': 'HBASE-24', 'kind': 'offline_recoverable_zk_read_preflight',
        'status': 'source_bytecode_selector_valid', 'jvm_workloads_run': 0,
        'healthy_admitted': False, 'fault_pilot_admitted': False,
        'source_sha256': hashes, 'target_class_sha256': hashlib.sha256(server_bytes).hexdigest(),
        'zkutil_class_sha256': hashlib.sha256(zkutil_bytes).hexdigest(),
        'recoverable_class_sha256': hashlib.sha256(recoverable_bytes).hexdigest(),
        'site_catalog_sha256': sha(HERE / 'sites.json'), 'healthy_config_sha256': sha(HERE / 'healthy.json'),
        'rpc_call': {'owner': RECOVERABLE.replace('/', '.'), 'method': 'getData',
                     'descriptor': WATCHER_GETDATA, 'source_line': 405,
                     'bytecode_offset': 40, 'keeper_catch': catches[0]},
        'compiled_dataflow': {'read_call_offset': 143, 'local_slot': 5,
                              'pb_prefix_call_offset': 150, 'same_start_region': True},
        'source_chain': ['ZKProcedureMemberRpcs.startNewSubprocedure:204',
                         'ZKUtil.getData', 'RecoverableZooKeeper.getData:405',
                         'ZooKeeper.getData', 'RecoverableZooKeeper retry on ConnectionLoss',
                         'ZKProcedureMemberRpcs.startNewSubprocedure:205'],
        'limits': ['Node1 runtime hashes must be rechecked immediately before a healthy run.',
                   'Healthy named door and same-member target after a fault remain unobserved.',
                   'A retry of an idempotent read does not itself corrupt PB bytes; target exception requires separate evidence.']}
    rendered = json.dumps(result, indent=2) + '\n'
    if '--write' in sys.argv:
        (HERE / 'preflight.json').write_text(rendered)
    print(rendered, end='')


if __name__ == '__main__':
    main()
