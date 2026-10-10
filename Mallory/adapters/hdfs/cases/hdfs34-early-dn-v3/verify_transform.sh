#!/usr/bin/env bash
set -euo pipefail

task_here=$(cd "$(dirname "$0")" && pwd)
task_agent=/users/ZhenyuLi/baseline/Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar
task_adapter="$task_here/release/adapter.jar"
task_source=${MALLORY_HDFS_SOURCE_ROOT:-/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2}
task_hdfs="$task_source/hadoop-hdfs-project/hadoop-hdfs"
task_temp=$(mktemp -d /tmp/mallory-hdfs34-transform-XXXXXX)
trap 'rm -rf "$task_temp"' EXIT

javac -d "$task_temp" -cp "$task_adapter:$task_agent" "$task_here/TransformOne.java"
java -cp "$task_temp:$task_adapter:$task_agent" TransformOne \
  org/apache/hadoop/hdfs/MiniDFSCluster \
  "$task_hdfs/target/test-classes/org/apache/hadoop/hdfs/MiniDFSCluster.class" \
  "$task_temp/org/apache/hadoop/hdfs/MiniDFSCluster.class"
java -cp "$task_temp:$task_adapter:$task_agent" TransformOne \
  org/apache/hadoop/hdfs/server/datanode/DataNode \
  "$task_hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/DataNode.class" \
  "$task_temp/org/apache/hadoop/hdfs/server/datanode/DataNode.class"

python3 - "$task_here/source-receipt.json" "$task_temp" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

receipt = json.loads(Path(sys.argv[1]).read_text())
root = Path(sys.argv[2])
proof = receipt["offline_bytecode_proof"]
for relative, pin in (
    ("org/apache/hadoop/hdfs/MiniDFSCluster.class",
     proof["transformed_minicluster_class_sha256"]),
    ("org/apache/hadoop/hdfs/server/datanode/DataNode.class",
     proof["transformed_datanode_class_sha256"]),
):
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if actual != pin:
        raise SystemExit(f"Transformed class changed: {relative}: {actual}")
print("HDFS-34 offline transformed bytecode SHA check passed")
PY
