#!/usr/bin/env python3
"""Apply HBase 2.6.6 wire/meta hooks backed by the original GraphChecker runtime.

This reuses the vetted HBase source anchors from the isolated protocol overlay,
while replacing its runtime dependency and bridge implementations. All anchors
are checked before any source file is written.
"""

import argparse
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "graphchecker_port" / "apply.py"
spec = importlib.util.spec_from_file_location("hbase_graphchecker_anchors", OLD)
anchors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anchors)

NATIVE_DEPENDENCY = """    <dependency>
      <groupId>org.example</groupId>
      <artifactId>GraphChecker</artifactId>
      <version>1.0-SNAPSHOT</version>
    </dependency>
"""

BRIDGES = {
    "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseProtocol.java":
        "GraphCheckerHBaseProtocol.java",
    "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseSaslProtocol.java":
        "GraphCheckerHBaseSaslProtocol.java",
    "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseDoors.java":
        "GraphCheckerHBaseDoors.java",
    "hbase-client/src/main/java/edu/uva/liftlab/graphchecker/runtime/HBaseRuntimeSource.java":
        "HBaseRuntimeSource.java",
    "hbase-client/src/main/java/org/apache/hadoop/hbase/GraphCheckerHBaseMetaState.java":
        "GraphCheckerHBaseMetaState.java",
    "hbase-procedure/src/main/java/org/apache/hadoop/hbase/procedure2/GraphCheckerHBaseProcedureScope.java":
        "GraphCheckerHBaseProcedureScope.java",
    "hbase-client/src/main/java/org/apache/hadoop/hbase/client/GraphCheckerContextThreadPoolExecutor.java":
        "GraphCheckerContextThreadPoolExecutor.java",
}


def native_after(relative: str, after: str) -> str:
    after = after.replace(anchors.DEPENDENCY, NATIVE_DEPENDENCY)
    after = after.replace("edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors",
                          "org.apache.hadoop.hbase.ipc.GraphCheckerHBaseDoors")
    if relative.endswith("BlockingRpcCallback.java"):
        after = after.replace("MessageDoors.stored(", "GraphCheckerHBaseDoors.stored(")
        after = after.replace("MessageDoors.fetched(", "GraphCheckerHBaseDoors.fetched(")
    if relative.endswith("NettyRpcConnection.java"):
        after = after.replace(
            "                call.setException(toIOE(future.cause()));\n",
            "                GraphCheckerHBaseProtocol.requestWriteFailed(call);\n"
            "                call.setException(toIOE(future.cause()));\n")
    if relative.endswith("NettyHBaseSaslRpcClientHandler.java"):
        after = after.replace(
            "      if (future.isSuccess()) frame.sent();\n",
            "      if (future.isSuccess()) frame.sent();\n"
            "      else frame.aborted();\n")
    return after


def changed_sources(root: Path) -> dict[Path, str]:
    changes = {}
    for relative, replacements in anchors.patches().items():
        path = root / relative
        content = path.read_text(encoding="utf-8")
        for before, after in replacements:
            content = anchors.edit(content, before, native_after(relative, after),
                                   relative)
        changes[path] = content
    for relative, bridge in BRIDGES.items():
        path = root / relative
        if path.exists():
            raise ValueError(f"already patched: {path}")
        changes[path] = (HERE / "src" / bridge).read_text(encoding="utf-8")
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hbase_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.hbase_root.resolve(strict=True)
    changes = changed_sources(root)
    if not args.check:
        for path, content in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    print(f"{'checked' if args.check else 'patched'} {len(changes)} HBase source files")


if __name__ == "__main__":
    main()
