"""Read-only classfile checks for the HDFS-29/30 candidate door call sites.

Uses only Python's standard library; it does not start a JVM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2/hadoop-hdfs-project/hadoop-hdfs/target/classes")
EXPECTED = {
    "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.class": "030e863220ffd2e7df698322e9fedb68dc6cc89bb4ea302fb2cc7dcbafd2be88",
    "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class": "63802647e507cda8ac95931d386a25d963511d7a866222717f03025ba6856bc0",
}


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        result = self.data[self.pos:self.pos+n]
        if len(result) != n:
            raise ValueError("truncated classfile")
        self.pos += n
        return result

    def u1(self) -> int:
        return self.take(1)[0]

    def u2(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def u4(self) -> int:
        return struct.unpack(">I", self.take(4))[0]


def parse_class(path: Path) -> tuple[str, list[dict], list]:
    r = Reader(path.read_bytes())
    assert r.u4() == 0xCAFEBABE
    r.u2(); r.u2()
    cp = [None]
    count = r.u2()
    while len(cp) < count:
        tag = r.u1()
        if tag == 1:
            cp.append(r.take(r.u2()).decode("utf-8"))
        elif tag in (3, 4):
            cp.append(r.take(4))
        elif tag in (5, 6):
            cp.extend((r.take(8), None))
        elif tag in (7, 8, 16, 19, 20):
            cp.append((tag, r.u2()))
        elif tag in (9, 10, 11, 12, 17, 18):
            cp.append((tag, r.u2(), r.u2()))
        elif tag == 15:
            cp.append((tag, r.u1(), r.u2()))
        else:
            raise ValueError(f"unsupported constant-pool tag {tag}")
    r.u2()
    name = cp[cp[r.u2()][1]]
    r.u2()
    for _ in range(r.u2()):
        r.u2()
    for _ in range(r.u2()):
        r.u2(); r.u2(); r.u2()
        for _ in range(r.u2()):
            r.u2(); r.take(r.u4())
    methods = []
    for _ in range(r.u2()):
        r.u2()
        method_name = cp[r.u2()]
        desc = cp[r.u2()]
        for _ in range(r.u2()):
            attr_name = cp[r.u2()]
            body = Reader(r.take(r.u4()))
            if attr_name != "Code":
                continue
            body.u2(); body.u2()
            code = body.take(body.u4())
            for _ in range(body.u2()):
                body.take(8)
            lines = []
            for _ in range(body.u2()):
                sub_name = cp[body.u2()]
                sub = Reader(body.take(body.u4()))
                if sub_name == "LineNumberTable":
                    for _ in range(sub.u2()):
                        lines.append((sub.u2(), sub.u2()))
            methods.append({"name": method_name, "descriptor": desc,
                            "code": code, "lines": sorted(lines)})
    return name, methods, cp


# Operand byte counts. Variable-width switch and wide are handled below.
OPERANDS = {**{op: 1 for op in (16, 18, 21, 22, 23, 24, 25, 54, 55, 56, 57, 58,
                                  169, 188)},
            **{op: 2 for op in (17, 19, 20, 132, 153, 154, 155, 156, 157, 158,
                                  159, 160, 161, 162, 163, 164, 165, 166, 167, 168,
                                  178, 179, 180, 181, 182, 183, 184, 187, 189,
                                  192, 193, 198, 199)},
            **{op: 3 for op in (197,)},
            **{op: 4 for op in (185, 186, 200, 201)}}


def calls(method: dict, cp: list) -> list[dict]:
    code = method["code"]
    lines = method["lines"]
    found = []
    pc = 0
    while pc < len(code):
        op = code[pc]
        if op in (182, 183, 184, 185):
            ref = cp[int.from_bytes(code[pc+1:pc+3], "big")]
            owner = cp[cp[ref[1]][1]]
            pair = cp[ref[2]]
            line = next((ln for at, ln in reversed(lines) if at <= pc), None)
            found.append({"pc": pc, "line": line, "owner": owner,
                          "method": cp[pair[1]], "descriptor": cp[pair[2]]})
        if op == 170:
            start = pc + 1 + ((4 - ((pc + 1) % 4)) % 4)
            low = int.from_bytes(code[start+4:start+8], "big", signed=True)
            high = int.from_bytes(code[start+8:start+12], "big", signed=True)
            pc = start + 12 + 4 * (high - low + 1)
        elif op == 171:
            start = pc + 1 + ((4 - ((pc + 1) % 4)) % 4)
            pairs = int.from_bytes(code[start+4:start+8], "big")
            pc = start + 8 + 8 * pairs
        elif op == 196:
            pc += 6 if code[pc+1] == 132 else 4
        else:
            pc += 1 + OPERANDS.get(op, 0)
    assert pc == len(code), (method["name"], pc, len(code))
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    specs = [
        ("org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.class",
         "callInitReplicaRecovery", 561, "org/apache/hadoop/hdfs/server/protocol/InterDatanodeProtocol", "initReplicaRecovery"),
        ("org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class",
         "sendHeartBeat", 563, "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB", "sendHeartbeat"),
    ]
    result = {"root": str(args.root), "checks": []}
    for relative, enclosing, line, owner, callee in specs:
        path = args.root / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if relative in EXPECTED:
            assert digest == EXPECTED[relative]
        class_name, methods, cp = parse_class(path)
        hits = [call for method in methods if method["name"] == enclosing
                for call in calls(method, cp) if call["line"] == line
                and call["owner"] == owner and call["method"] == callee]
        assert len(hits) == 1, (relative, enclosing, line, owner, callee, hits)
        result["checks"].append({"class": class_name, "sha256": digest,
                                  "enclosing": enclosing, "call": hits[0]})
    target = args.root / "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.class"
    _, methods, _ = parse_class(target)
    guard = next(m for m in methods if m["name"] == "getActiveNamenodeForBP")
    for line in (577, 582):
        start = next(pc for pc, ln in guard["lines"] if ln == line)
        assert guard["code"][start+1] == 0xC7, (line, guard["code"][start:start+4].hex())
    result["guard_lines"] = [577, 582]
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
