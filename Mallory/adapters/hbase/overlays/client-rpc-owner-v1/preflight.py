#!/usr/bin/env python3
"""No-JVM source, class, and overlay contract check for HBase client RPC ownership."""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6")
SOURCE_HASHES = {
    "hbase-client/src/main/java/org/apache/hadoop/hbase/client/ConnectionFactory.java":
        "d44b2f0d9ee042e4901543efad21dd287b7e1ce6571f0c0132ec235fd4698d94",
    "hbase-client/src/main/java/org/apache/hadoop/hbase/client/ConnectionImplementation.java":
        "f00ec999b43227553f89ecb859ccfe28e4f901adb0f2f37552096d1f72261184",
    "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/AbstractRpcClient.java":
        "5b2b5a4c808d15deb4589f72b5b7e8384331bad63e915474ec27278389faa0cb",
    "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/Call.java":
        "ffef0e5810c02d6c415661bfc4f43e5dc789c8e0be182d3f7c7f9890b5cb0720",
    "hbase-server/src/test/java/org/apache/hadoop/hbase/HBaseTestingUtility.java":
        "6c8e5bf0053fce4dcac27594a73e9bb4173d14e52bb296dffef7c0bdea6cab45",
}
ADAPTER_HASHES = {
    "Mallory/adapters/hbase/src/main/java/edu/uva/liftlab/mallory/hbase/HBaseHooks.java":
        "6f77dd858bfe27f42b6ecc3c823d3c0df42f955c8366ebc20749ae5c85fd2944",
    "Mallory/adapters/hbase/src/main/java/edu/uva/liftlab/mallory/hbase/HBaseAdapterTransformer.java":
        "60ca093f6dddd7e0d07ff253175505c6e751c3e764320762edba6fb9272e55e0",
    "Mallory/instrumentation/src/main/java/edu/uva/liftlab/mallory/instrumentation/Probe.java":
        "8f6ac5f38f10ba05cf20e3455adfe9d06bcc008ebce3d8436a92c9ff471b10f0",
}
CLIENT_JAR = DIST / "lib/hbase-client-2.6.6.jar"
TESTS_JAR = DIST / "lib/hbase-server-2.6.6-tests.jar"
CLASS_HASHES = {
    "org/apache/hadoop/hbase/client/ConnectionImplementation.class":
        "d04a6e5bad1b1933b343eccb7cb858072842df9498552c1cf548218a996abb1f",
    "org/apache/hadoop/hbase/ipc/AbstractRpcClient.class":
        "dd82f14646d583363a98eccaebffd5bd71224b49be12675ee67b5abff2f85c9b",
    "org/apache/hadoop/hbase/ipc/Call.class":
        "7d19f1f50a0c485ea7ee7c000bc72dc867bce20cf4068d2239e84ef77352981a",
    "org/apache/hadoop/hbase/HBaseTestingUtility.class":
        "23179b4956ac56cb20bc3b5c2fc598f30b4b3ddb274fc46ca2127b04dc789ed8",
}
PROTO = "Lorg/apache/hbase/thirdparty/com/google/protobuf/"
CALL_METHOD_DESC = (
    "(" + PROTO + "Descriptors$MethodDescriptor;"
    "Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;"
    + PROTO + "Message;" + PROTO + "Message;"
    "Lorg/apache/hadoop/hbase/security/User;"
    "Lorg/apache/hadoop/hbase/net/Address;" + PROTO + "RpcCallback;)"
    "Lorg/apache/hadoop/hbase/ipc/Call;"
)
BLOCKING_DESC = (
    "(" + PROTO + "Descriptors$MethodDescriptor;"
    "Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;"
    + PROTO + "Message;" + PROTO + "Message;"
    "Lorg/apache/hadoop/hbase/security/User;"
    "Lorg/apache/hadoop/hbase/net/Address;)" + PROTO + "Message;"
)


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u2(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def u4(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def members(data: bytes, offset: int) -> tuple[list[tuple[int, int]], int]:
    count = u2(data, offset)
    offset += 2
    found = []
    for _ in range(count):
        _, name, descriptor, attributes = struct.unpack_from(">HHHH", data, offset)
        offset += 8
        found.append((name, descriptor))
        for _ in range(attributes):
            offset += 2
            length = u4(data, offset)
            offset += 4 + length
    return found, offset


def class_members(data: bytes) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    require(data[:4] == b"\xca\xfe\xba\xbe", "invalid class file")
    offset = 8
    count = u2(data, offset)
    offset += 2
    strings: list[str | None] = [None] * count
    index = 1
    while index < count:
        tag = data[offset]
        offset += 1
        if tag == 1:
            length = u2(data, offset)
            offset += 2
            strings[index] = data[offset:offset + length].decode()
            offset += length
        elif tag in (3, 4):
            offset += 4
        elif tag in (5, 6):
            offset += 8
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            offset += 2
        elif tag in (9, 10, 11, 12, 17, 18):
            offset += 4
        elif tag == 15:
            offset += 3
        else:
            raise ValueError(f"unknown constant-pool tag {tag}")
        index += 1
    offset += 6
    interfaces = u2(data, offset)
    offset += 2 + 2 * interfaces
    fields, offset = members(data, offset)
    methods, _ = members(data, offset)
    return ({(strings[name], strings[desc]) for name, desc in fields},
            {(strings[name], strings[desc]) for name, desc in methods})


def check_pins() -> None:
    for relative, expected in SOURCE_HASHES.items():
        path = SOURCE / relative
        require(sha(path.read_bytes()) == expected, f"source changed: {relative}")
    for relative, expected in ADAPTER_HASHES.items():
        path = REPO / relative
        require(sha(path.read_bytes()) == expected, f"base adapter changed: {relative}")
    for jar, expected in ((CLIENT_JAR,
                           "b3c9537a0c5f4b057134c59298b453ae207d2e6279be66d71c80da36d0d2de54"),
                          (TESTS_JAR,
                           "b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5")):
        require(sha(jar.read_bytes()) == expected, f"JAR changed: {jar}")
    with zipfile.ZipFile(CLIENT_JAR) as client, zipfile.ZipFile(TESTS_JAR) as tests:
        classes = {name: (tests if "HBaseTestingUtility" in name else client).read(name)
                   for name in CLASS_HASHES}
    for name, data in classes.items():
        require(sha(data) == CLASS_HASHES[name], f"class changed: {name}")
    fields, _ = class_members(
        classes["org/apache/hadoop/hbase/client/ConnectionImplementation.class"])
    require(("rpcClient", "Lorg/apache/hadoop/hbase/ipc/RpcClient;") in fields,
            "connection no longer owns an RpcClient field")
    _, utility_methods = class_members(
        classes["org/apache/hadoop/hbase/HBaseTestingUtility.class"])
    require(("getConnection", "()Lorg/apache/hadoop/hbase/client/Connection;")
            in utility_methods, "utility return hook missing")
    _, rpc_methods = class_members(
        classes["org/apache/hadoop/hbase/ipc/AbstractRpcClient.class"])
    require(("callMethod", CALL_METHOD_DESC) in rpc_methods and
            ("callBlockingMethod", BLOCKING_DESC) in rpc_methods,
            "RPC ownership scope descriptors changed")


def check_semantics() -> None:
    factory = (SOURCE / next(k for k in SOURCE_HASHES if k.endswith("ConnectionFactory.java"))).read_text()
    impl = (SOURCE / next(k for k in SOURCE_HASHES if k.endswith("ConnectionImplementation.java"))).read_text()
    rpc = (SOURCE / next(k for k in SOURCE_HASHES if k.endswith("AbstractRpcClient.java"))).read_text()
    utility = (SOURCE / next(k for k in SOURCE_HASHES if k.endswith("HBaseTestingUtility.java"))).read_text()
    hooks = (REPO / next(k for k in ADAPTER_HASHES if k.endswith("HBaseHooks.java"))).read_text()
    transformer = (REPO / next(k for k in ADAPTER_HASHES if k.endswith("HBaseAdapterTransformer.java"))).read_text()
    require("ConnectionImplementation.class.getName()" in factory and
            "private final RpcClient rpcClient;" in impl and
            "this.rpcClient = RpcClientFactory.createClient" in impl and
            "ConnectionFactory.createConnection(this.conf)" in utility,
            "explicit test connection ownership chain changed")
    require("Call call =" in rpc and "new Call(nextCallId()" in rpc and
            "callMethod(md, hrc, param, returnType, ticket, isa, done);" in rpc,
            "Call creation or blocking method nesting changed")
    require("Probe.registerCurrentNode(call);" in hooks and
            "Probe.withRegisteredNode(call)" in hooks and
            "Probe.taskSubmit(marker.completionToken" in hooks and
            "Probe.taskObserve(marker.completionToken" in hooks,
            "base response or blocking claim protocol changed")
    require("wrapScope(method, \"enterBlockingCall\", false);" in transformer and
            "clientResponse" in transformer and
            "registerReturnedClient(method);" in transformer,
            "base transformer handoff changed")
    owner_hooks = (HERE / "src/main/java/edu/uva/liftlab/mallory/hbase/clientowner/"
                   "ClientRpcOwnerHooks.java").read_text()
    owner_transformer = (HERE / "src/main/java/edu/uva/liftlab/mallory/hbase/clientowner/"
                         "ClientRpcOwnerTransformer.java").read_text()
    require('Probe.registerNode(rpcClient, "client", 0);' in owner_hooks and
            "if (!TEST_RPC_CLIENTS.containsKey(rpcClient)) return null;" in owner_hooks and
            "return Probe.withRegisteredNode(rpcClient);" in owner_hooks,
            "explicit receiver identity or unknown fallback changed")
    require("registerReturnedConnection(method);" in owner_transformer and
            "scopeRpcClient(method);" in owner_transformer and
            "method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, null));"
            in owner_transformer,
            "return registration or finally scope changed")


def main() -> None:
    receipt = json.loads((HERE / "stage-receipt.json").read_text())
    for relative, expected in receipt["overlay_sha256"].items():
        require(sha((HERE / relative).read_bytes()) == expected,
                f"overlay staged file changed: {relative}")
    require(receipt["status"] == "source_staged_no_jvm_build_or_runtime",
            "overlay stage status changed")
    check_pins()
    check_semantics()
    print("PASS HBase client RPC owner no-JVM preflight: explicit test connection -> "
          "RpcClient -> Call/response and blocking completion; build/runtime pending")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, struct.error, zipfile.BadZipFile) as exc:
        raise SystemExit(f"HBase client RPC owner preflight gap: {exc}")
