#!/usr/bin/env python3
"""No-JVM classfile check for SolrZkClient retry-lambda path locals."""

import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path

CLASS = "org/apache/solr/common/cloud/SolrZkClient.class"
CLASS_SHA256 = "51b3131fed142509b80da408d0d3f8d036045237b51a48c2a4dd9cf574a72dc0"
SOLRJ_SHA256 = "b274e65f3607224b3337e9fc797137d8093c7981bcb54b695644dfd5d2242517"
SOURCE_SHA256 = "4a256a0fb563515451b5b733dbb4e320fceb9fa5dcc04912e4dd003d1a109c32"
METHODS = {
    "lambda$exists$2": "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;",
    "lambda$getData$6": "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B",
}


class Reader:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def take(self, size):
        part = self.data[self.at:self.at + size]
        if len(part) != size:
            raise ValueError("truncated classfile")
        self.at += size
        return part

    def u1(self):
        return self.take(1)[0]

    def u2(self):
        return struct.unpack(">H", self.take(2))[0]

    def u4(self):
        return struct.unpack(">I", self.take(4))[0]


def members(reader, utf8):
    rows = []
    for _ in range(reader.u2()):
        access = reader.u2()
        name = utf8[reader.u2()]
        descriptor = utf8[reader.u2()]
        for _ in range(reader.u2()):
            reader.u2()
            reader.take(reader.u4())
        rows.append((access, name, descriptor))
    return rows


def method_rows(data):
    r = Reader(data)
    if r.u4() != 0xCAFEBABE:
        raise ValueError("not a JVM classfile")
    r.u2()
    r.u2()
    utf8 = {}
    count = r.u2()
    index = 1
    while index < count:
        tag = r.u1()
        if tag == 1:
            utf8[index] = r.take(r.u2()).decode("utf-8")
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            r.take(4)
        elif tag in (5, 6):
            r.take(8)
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            r.take(2)
        elif tag == 15:
            r.take(3)
        else:
            raise ValueError(f"unsupported constant pool tag {tag}")
        index += 1
    r.u2()
    r.u2()
    r.u2()
    r.take(2 * r.u2())
    members(r, utf8)  # fields
    return members(r, utf8)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--solrj", type=Path, default=Path(
        "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-solrj-8.11.4.jar"))
    p.add_argument("--source", type=Path, default=Path(
        "/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"))
    args = p.parse_args()
    sha = lambda data: hashlib.sha256(data).hexdigest()
    if sha(args.solrj.read_bytes()) != SOLRJ_SHA256:
        raise ValueError("compiled SolrJ JAR changed")
    source = args.source.read_bytes()
    if sha(source) != SOURCE_SHA256:
        raise ValueError("SolrZkClient source changed")
    lines = source.decode().splitlines()
    if "keeper.exists(" not in lines[300] or "keeper.getData(" not in lines[348]:
        raise ValueError("native retry-attempt source lines changed")
    with zipfile.ZipFile(args.solrj) as jar:
        classfile = jar.read(CLASS)
    if sha(classfile) != CLASS_SHA256:
        raise ValueError("compiled SolrZkClient class changed")
    rows = []
    for name, expected in METHODS.items():
        matches = [(access, descriptor) for access, method, descriptor
                   in method_rows(classfile) if method == name]
        if len(matches) != 1 or matches[0][1] != expected:
            raise ValueError(f"retry lambda descriptor changed: {name}: {matches}")
        access = matches[0][0]
        rows.append({"method": name, "descriptor": expected,
                     "static": bool(access & 0x0008),
                     "path_local_slot": 0 if access & 0x0008 else 1})
    print(json.dumps({"status": "passed", "class_sha256": CLASS_SHA256,
                      "source_sha256": SOURCE_SHA256, "methods": rows}, sort_keys=True))


if __name__ == "__main__":
    main()
