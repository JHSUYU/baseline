#!/usr/bin/env python3
"""Source-free, JVM-free check of the staged HBASE-24 call-site mapping."""

import hashlib
import json
import struct
import zipfile
from pathlib import Path


SERVER_JAR = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar')
ZK_JAR = Path('/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/zookeeper-3.8.6.jar')
CLASS = 'org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs'
ERROR_CLASS = 'org/apache/zookeeper/KeeperException$ConnectionLossException'


class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, count):
        data = self.data[self.offset:self.offset + count]
        assert len(data) == count
        self.offset += count
        return data

    def u1(self):
        return self.take(1)[0]

    def u2(self):
        return struct.unpack('>H', self.take(2))[0]

    def u4(self):
        return struct.unpack('>I', self.take(4))[0]


def parse_class(data):
    reader = Reader(data)
    assert reader.u4() == 0xCAFEBABE
    reader.take(4)  # class-file version
    count = reader.u2()
    cp = [None] * count
    index = 1
    while index < count:
        tag = reader.u1()
        if tag == 1:
            cp[index] = reader.take(reader.u2()).decode('utf-8')
        elif tag in (3, 4):
            reader.take(4)
        elif tag in (5, 6):
            reader.take(8)
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            cp[index] = (tag, reader.u2())
        elif tag in (9, 10, 11, 12, 17, 18):
            cp[index] = (tag, reader.u2(), reader.u2())
        elif tag == 15:
            cp[index] = (tag, reader.u1(), reader.u2())
        else:
            raise AssertionError('unsupported constant-pool tag ' + str(tag))
        index += 1

    def class_name(index):
        entry = cp[index]
        assert entry[0] == 7
        return cp[entry[1]]

    def method_ref(index):
        entry = cp[index]
        if not isinstance(entry, tuple) or entry[0] not in (10, 11):
            return None
        name_type = cp[entry[2]]
        return (class_name(entry[1]), cp[name_type[1]], cp[name_type[2]])

    reader.u2()  # access flags
    reader.u2()  # this class
    superclass = class_name(reader.u2())
    for _ in range(reader.u2()):
        reader.u2()
    for _ in range(reader.u2()):
        reader.take(6)
        for _ in range(reader.u2()):
            reader.u2()
            reader.take(reader.u4())

    methods = {}
    for _ in range(reader.u2()):
        reader.u2()
        name, descriptor = cp[reader.u2()], cp[reader.u2()]
        method = {}
        for _ in range(reader.u2()):
            attr_name = cp[reader.u2()]
            attr = Reader(reader.take(reader.u4()))
            if attr_name != 'Code':
                continue
            attr.take(4)  # max_stack and max_locals
            code = attr.take(attr.u4())
            catches = []
            for _ in range(attr.u2()):
                start, end, handler, caught = (attr.u2() for _ in range(4))
                catches.append((start, end, handler,
                                class_name(caught) if caught else None))
            lines = []
            for _ in range(attr.u2()):
                nested_name = cp[attr.u2()]
                nested = Reader(attr.take(attr.u4()))
                if nested_name == 'LineNumberTable':
                    lines = [(nested.u2(), nested.u2()) for _ in range(nested.u2())]
            method = {'code': code, 'catches': catches, 'lines': lines}
        methods[(name, descriptor)] = method
    return {'superclass': superclass, 'methods': methods, 'method_ref': method_ref}


def invocations(parsed, method):
    code = method['code']
    found = []
    # The constant-pool index and opcode together identify the instruction.
    # On this pinned class every matching byte sequence is an actual invoke.
    for offset in range(len(code) - 2):
        if code[offset] not in (0xB6, 0xB7, 0xB8, 0xB9):
            continue
        ref = parsed['method_ref'](struct.unpack('>H', code[offset + 1:offset + 3])[0])
        if ref is None:
            continue
        line = next((number for start, number in reversed(method['lines']) if start <= offset), None)
        found.append((offset, code[offset], ref, line))
    return found


def main():
    with zipfile.ZipFile(SERVER_JAR) as archive:
        server_class = archive.read(CLASS + '.class')
    parsed = parse_class(server_class)
    watch = parsed['methods'][('watchForAbortedProcedures', '()V')]
    selected = [item for item in invocations(parsed, watch)
                if item[2] == (
                    'org/apache/hadoop/hbase/zookeeper/ZKUtil',
                    'listChildrenAndWatchForNewChildren',
                    '(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)Ljava/util/List;')]
    assert len(selected) == 1, selected
    offset, opcode, _, line = selected[0]
    assert opcode == 0xB8 and line == 137, selected
    keeper_catches = [catch for catch in watch['catches']
                      if catch[0] <= offset < catch[1]
                      and catch[3] == 'org/apache/zookeeper/KeeperException']
    assert len(keeper_catches) == 1, keeper_catches
    start = parsed['methods'][('start',
        '(Ljava/lang/String;Lorg/apache/hadoop/hbase/procedure/ProcedureMember;)V')]
    start_calls = [(item[2][1], item[3]) for item in invocations(parsed, start)
                   if item[2][0] == CLASS]
    assert ('watchForAbortedProcedures', 360) in start_calls, start_calls
    assert ('waitForNewProcedures', 361) in start_calls, start_calls
    assert start_calls.index(('watchForAbortedProcedures', 360)) < start_calls.index(
        ('waitForNewProcedures', 361))
    with zipfile.ZipFile(ZK_JAR) as archive:
        error_class = parse_class(archive.read(ERROR_CLASS + '.class'))
    assert error_class['superclass'] == 'org/apache/zookeeper/KeeperException'
    constructors = [descriptor for name, descriptor in error_class['methods'] if name == '<init>']
    assert '()V' in constructors or '(Ljava/lang/String;)V' in constructors, constructors
    print(json.dumps({
        'server_jar_sha256': hashlib.sha256(SERVER_JAR.read_bytes()).hexdigest(),
        'target_class_sha256': hashlib.sha256(server_class).hexdigest(),
        'watch_invokestatic_offset': offset,
        'watch_source_line': line,
        'keeper_catch': keeper_catches[0],
        'start_call_order': start_calls,
        'injected_exception_superclass': error_class['superclass'],
        'injected_exception_constructors': constructors,
        'status': 'bytecode_mapping_valid',
    }, indent=2))


if __name__ == '__main__':
    main()
