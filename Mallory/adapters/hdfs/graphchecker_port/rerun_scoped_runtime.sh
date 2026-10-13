#!/usr/bin/env bash
# Rerun the unchanged JUnit against exactly the woven application bytes from
# a completed scope pilot, replacing only the GraphChecker runtime snapshot.
set -euo pipefail
if [[ $# -ne 5 ]]; then
  echo 'usage: rerun_scoped_runtime.sh <woven-pilot-dir> <adapter-overlay> <new-runtime.jar> <hadoop-3.4.3-checkout> <new-run-dir>' >&2
  exit 2
fi
pilot=$(realpath "$1")
overlay=$(realpath "$2")
runtime_jar=$(realpath "$3")
hadoop_dir=$(realpath "$4")
run_dir=$5
port_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
hdfs_module=$hadoop_dir/hadoop-hdfs-project/hadoop-hdfs
java_home=${JAVA_HOME:-/usr/lib/jvm/java-8-openjdk-amd64}
for required in "$pilot/woven" "$pilot/weave_manifest.json" "$pilot/weave-tool.jar" \
    "$pilot/input" "$pilot/weave-dependency-classpath.txt" \
    "$pilot/weaver-classpath.txt" "$pilot/hdfs-test-classpath.txt" \
    "$overlay/org/apache/hadoop/ipc/MalloryEmbeddedIpcBridge.class" \
    "$runtime_jar" "$hdfs_module/target/test-classes" "$hdfs_module/target/classes"; do
  [[ -e $required ]] || { echo "missing prerequisite: $required" >&2; exit 2; }
done
[[ ! -e $run_dir ]] || { echo "refusing to replace run directory: $run_dir" >&2; exit 2; }
mkdir -p "$run_dir/logs" "$run_dir/test-data"
run_dir=$(realpath "$run_dir")
cp "$runtime_jar" "$run_dir/graph-runtime.jar"
cp "$pilot/weave_manifest.json" "$run_dir/weave_manifest.json"
if [[ -f $pilot/static_scope_map.jsonl ]]; then
  cp "$pilot/static_scope_map.jsonl" "$run_dir/static_scope_map.jsonl"
fi
ln -s "$pilot/woven" "$run_dir/woven"
ln -s "$pilot/input" "$run_dir/input"
ln -s "$pilot/weave-tool.jar" "$run_dir/weave-tool.jar"
cp "$pilot/weaver-classpath.txt" "$pilot/hdfs-test-classpath.txt" \
  "$pilot/weave-dependency-classpath.txt" "$run_dir/"
sha256sum "$run_dir/graph-runtime.jar" "$pilot/weave-tool.jar" \
  "$run_dir/weave_manifest.json" > "$run_dir/tool-hashes.sha256"
printf 'wovenPilot=%s\noverlay=%s\nhadoop=%s\n' "$pilot" "$overlay" \
  "$hadoop_dir" > "$run_dir/inputs.txt"

weaver_cp=$(cat "$pilot/weaver-classpath.txt")
hdfs_cp=$(cat "$pilot/hdfs-test-classpath.txt")
graph_cp="$run_dir/graph-runtime.jar:$pilot/weave-tool.jar:$weaver_cp"
timeout "${MALLORY_HDFS_JUNIT_TIMEOUT_SEC:-600}s" "$java_home/bin/java" -Xmx4g \
  -Dhadoop.log.dir="$run_dir/logs" \
  -Dtest.build.data="$run_dir/test-data" \
  -Dmallory.graphchecker.trace.file="$run_dir/trace.jsonl" \
  -cp "$run_dir/woven:$overlay:$graph_cp:$hdfs_module/target/test-classes:$hdfs_module/target/classes:$hdfs_cp" \
  edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.RunOriginalJUnit \
  org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool \
  testDfsAdminDeleteBlockPool \
  > "$run_dir/junit.log" 2>&1 || {
    tail -100 "$run_dir/junit.log" >&2; exit 1;
  }

python3 "$port_dir/check_trace.py" "$run_dir/trace.jsonl" \
  > "$run_dir/protocol-check.log"
target_site=$(python3 - "$run_dir/weave_manifest.json" <<'PY'
import json, sys
targets=json.load(open(sys.argv[1]))['targets']
branch=[target for target in targets if target['kind']=='BRANCH' and target['line']==3819
        and target['clazz']=='org.apache.hadoop.hdfs.server.datanode.DataNode'
        and target['method']=='deleteBlockPool']
assert len(branch)==1
print(branch[0]['siteId'])
PY
)
graph_args=("$run_dir/trace.jsonl" "$run_dir/graph.jsonl" "$run_dir/feedback.json" "$target_site")
if [[ -f $run_dir/static_scope_map.jsonl ]]; then
  graph_args+=( - "$run_dir/static_scope_map.jsonl" )
fi
timeout "${MALLORY_HDFS_GRAPH_TIMEOUT_SEC:-300}s" \
  "$java_home/bin/java" -Xmx"${MALLORY_HDFS_GRAPH_HEAP:-12g}" -cp "$graph_cp" \
  edu.uva.liftlab.mallory.graphchecker.runtime.TrialGraphMain "${graph_args[@]}"
python3 - "$run_dir" <<'PY'
import collections, json, pathlib, sys
root=pathlib.Path(sys.argv[1])
counts=collections.Counter()
with (root/'trace.jsonl').open() as trace:
    for line in trace:
        if '"kind":"' in line:
            counts[json.loads(line).get('kind')]+=1
feedback=json.loads((root/'feedback.json').read_text())
print('JUNIT', [line for line in (root/'junit.log').read_text().splitlines() if line.startswith('JUNIT_')])
print('TRACE_COUNTS', dict(sorted(counts.items())))
print('GRAPH_FEEDBACK', {key:feedback.get(key) for key in
      ('targetReached','targetChecks','nodes','edges','closureNodes','closureEdges',
       'closureCoverageSites','closureDoorSiteIds','staticMayObservedDoorSiteIds')})
print('RUN_DIR', root)
PY
