#!/usr/bin/env bash
# Run two unchanged QJM JUnit methods and verify exact JournalNode RPC lineage.
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo 'usage: check_qjm_junit.sh <overlay> <graph-runtime.jar> <hadoop-3.4.3-checkout> <new-output-directory>' >&2
  exit 2
fi
overlay=$(realpath "$1")
runtime_jar=$(realpath "$2")
hadoop_dir=$(realpath "$3")
output=$4
hdfs_module=$hadoop_dir/hadoop-hdfs-project/hadoop-hdfs
for required in "$overlay/org/apache/hadoop/ipc/MalloryEmbeddedIpcBridge.class" \
    "$overlay/org/apache/hadoop/hdfs/qjournal/client/IPCLoggerChannel.class" \
    "$overlay/org/apache/hadoop/hdfs/qjournal/MiniJournalCluster.class" \
    "$runtime_jar" "$hdfs_module/target/test-classes" \
    "$hdfs_module/target/classes"; do
  [[ -e $required ]] || { echo "missing prerequisite: $required" >&2; exit 2; }
done
[[ ! -e $output ]] || { echo "refusing to replace output: $output" >&2; exit 2; }
mkdir -p "$output"

(cd "$hadoop_dir" && mvn -q -pl hadoop-hdfs-project/hadoop-hdfs \
  dependency:build-classpath -Dmdep.outputFile="$(realpath "$output")/classpath.txt" \
  -Dmdep.includeScope=test -DskipTests)
test_classpath=$(cat "$output/classpath.txt")
java_home=${JAVA_HOME:-/usr/lib/jvm/java-8-openjdk-amd64}
for method in testSingleWriter testSelectViaRpcAfterJNRestart; do
  run_dir=$output/$method
  mkdir -p "$run_dir/logs" "$run_dir/test-data"
  "$java_home/bin/java" -Xmx4g -ea \
    -Dhadoop.log.dir="$run_dir/logs" \
    -Dtest.build.data="$run_dir/test-data" \
    -Dmallory.graphchecker.trace.file="$run_dir/trace.jsonl" \
    -cp "$overlay:$runtime_jar:$hdfs_module/target/test-classes:$hdfs_module/target/classes:$test_classpath" \
    edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.RunOriginalJUnit \
    org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager "$method" \
    > "$run_dir/junit.log" 2>&1
  python3 - "$run_dir/trace.jsonl" "$method" <<'PY'
import json
import sys

trace, method = sys.argv[1:]
rows = [json.loads(line) for line in open(trace)]
assert not [row for row in rows if row.get('kind') == 'GAP'], 'causal trace contains a gap'
exports = {}
for row in rows:
    if row.get('kind') == 'EXPORT':
        key = (row['transport'], row['correlationId'], row['attemptId'], row['half'])
        exports[(key, row['producerEndpointId'])] = row['seq']
requests = set()
responses = 0
for row in rows:
    if row.get('kind') != 'ATTACH':
        continue
    key = (row['transport'], row['correlationId'], row['attemptId'], row['half'])
    send_seq = exports.get((key, row['producerEndpointId']))
    assert send_seq is not None and send_seq < row['seq'], 'ATTACH has no prior exact EXPORT'
    assert row['pairedBy'] == 'ENVELOPE', 'message was not paired by its transported identity'
    if row['half'] == 'REQUEST':
        requests.add(row['node'])
    elif row['half'] == 'RESPONSE':
        responses += 1
expected = {f'jn{i}#epoch0' for i in range(3)}
if method == 'testSelectViaRpcAfterJNRestart':
    expected |= {f'jn{i}#epoch1' for i in range(3)}
assert expected <= requests, f'missing JournalNode request epochs: {expected - requests}'
assert responses > 0, 'no exact response attachments'
print(f'QJM_TRACE_CHECK=PASS {method} request_nodes={len(requests)} responses={responses}')
PY
  tail -1 "$run_dir/junit.log"
done
