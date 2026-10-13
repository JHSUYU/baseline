#!/usr/bin/env bash
# Run the unchanged Hadoop JUnit selector and check its causal IPC handoffs.
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo 'usage: check_original_junit.sh <overlay> <graph-runtime.jar> <hadoop-3.4.3-checkout> <trace.jsonl>' >&2
  exit 2
fi
overlay=$(realpath "$1")
runtime_jar=$(realpath "$2")
hadoop_dir=$(realpath "$3")
trace_file=$4
hdfs_module=$hadoop_dir/hadoop-hdfs-project/hadoop-hdfs
for required in "$overlay/org/apache/hadoop/ipc/MalloryEmbeddedIpcBridge.class" \
    "$runtime_jar" "$hdfs_module/target/test-classes" \
    "$hdfs_module/target/classes"; do
  [[ -e $required ]] || { echo "missing prerequisite: $required" >&2; exit 2; }
done
[[ ! -e $trace_file ]] || { echo "refusing to replace trace: $trace_file" >&2; exit 2; }
mkdir -p "$(dirname "$trace_file")"
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT

(cd "$hadoop_dir" && mvn -q -pl hadoop-hdfs-project/hadoop-hdfs \
  dependency:build-classpath -Dmdep.outputFile="$scratch/classpath" \
  -Dmdep.includeScope=test -DskipTests)
test_classpath=$(cat "$scratch/classpath")
java_home=${JAVA_HOME:-/usr/lib/jvm/java-8-openjdk-amd64}
mkdir -p "$scratch/logs" "$scratch/test-data"
"$java_home/bin/java" \
  -Dhadoop.log.dir="$scratch/logs" \
  -Dtest.build.data="$scratch/test-data" \
  -Dmallory.graphchecker.trace.file="$trace_file" \
  -cp "$overlay:$runtime_jar:$hdfs_module/target/test-classes:$hdfs_module/target/classes:$test_classpath" \
  edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.RunOriginalJUnit \
  org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool \
  testDfsAdminDeleteBlockPool

python3 "$(dirname "${BASH_SOURCE[0]}")/check_trace.py" "$trace_file"
