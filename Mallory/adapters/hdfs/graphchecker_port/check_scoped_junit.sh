#!/usr/bin/env bash
# Weave the generated static scope into the unchanged HDFS-32 JUnit workload.
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo 'usage: check_scoped_junit.sh <weave_manifest.json> <merged-hdfs-classes> <overlay> <graph-runtime.jar> <hadoop-3.4.3-checkout> <new-run-directory>' >&2
  exit 2
fi
manifest=$(realpath "$1")
source_classes=$(realpath "$2")
overlay=$(realpath "$3")
runtime_jar=$(realpath "$4")
graph_analyzer_jar=${MALLORY_HDFS_GRAPH_JAR:-$runtime_jar}
graph_analyzer_jar=$(realpath "$graph_analyzer_jar")
hadoop_dir=$(realpath "$5")
run_dir=$6
port_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
baseline_dir=$(cd "$port_dir/../../../.." && pwd -P)
weaver_dir=$baseline_dir/Mallory/instrumentation/graphchecker_port
hdfs_module=$hadoop_dir/hadoop-hdfs-project/hadoop-hdfs
java_home=${JAVA_HOME:-/usr/lib/jvm/java-8-openjdk-amd64}
weaver_jar=${MALLORY_GC_WEAVE_JAR:-$weaver_dir/target/mallory-graphchecker-weave-1.0-SNAPSHOT.jar}

for required in "$manifest" "$source_classes/org/apache/hadoop/hdfs/server/datanode/DataNode.class" \
    "$overlay/org/apache/hadoop/ipc/MalloryEmbeddedIpcBridge.class" "$runtime_jar" \
    "$graph_analyzer_jar" \
    "$weaver_jar" \
    "$hdfs_module/target/test-classes" "$hdfs_module/target/classes"; do
  [[ -e $required ]] || { echo "missing prerequisite: $required" >&2; exit 2; }
done
for rel in \
    org/apache/hadoop/hdfs/server/datanode/DataNode.class \
    org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class \
    org/apache/hadoop/hdfs/tools/DFSAdmin.class; do
  cmp -s "$source_classes/$rel" "$overlay/$rel" || {
    echo "static process directory and adapter overlay disagree: $rel" >&2; exit 2;
  }
done
for rel in \
    org/apache/hadoop/ipc/Client.class \
    'org/apache/hadoop/ipc/Client$Connection.class' \
    'org/apache/hadoop/ipc/Client$Connection$RpcRequestSender.class' \
    'org/apache/hadoop/ipc/Server$RpcCall.class' \
    'org/apache/hadoop/ipc/Server$Connection.class'; do
  [[ -f $source_classes/$rel ]] || continue
  cmp -s "$source_classes/$rel" "$overlay/$rel" || {
    echo "static process directory and adapter overlay disagree: $rel" >&2; exit 2;
  }
done
[[ ! -e $run_dir ]] || { echo "refusing to replace run directory: $run_dir" >&2; exit 2; }
mkdir -p "$run_dir/input" "$run_dir/woven" "$run_dir/logs" "$run_dir/test-data"
run_dir=$(realpath "$run_dir")
if [[ -f $source_classes/MALLORY_HDFS_CLASS_BYTES.sha256 ]]; then
  (cd "$source_classes" && sha256sum -c MALLORY_HDFS_CLASS_BYTES.sha256) \
    > "$run_dir/source-class-verification.log"
  cp "$source_classes/MALLORY_HDFS_CLASS_BYTES.sha256" \
    "$run_dir/source-class-bytes.sha256"
fi
cp "$weaver_jar" "$run_dir/weave-tool.jar"
cp "$runtime_jar" "$run_dir/graph-runtime.jar"
cp "$graph_analyzer_jar" "$run_dir/graph-analyzer.jar"
sha256sum "$run_dir/weave-tool.jar" "$run_dir/graph-runtime.jar" \
  "$run_dir/graph-analyzer.jar" \
  > "$run_dir/tool-hashes.sha256"
runtime_jar=$run_dir/graph-runtime.jar
graph_analyzer_jar=$run_dir/graph-analyzer.jar

python3 - "$manifest" "$source_classes" "$run_dir/input" > "$run_dir/selected-classes.txt" <<'PY'
import json
import shutil
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
source = Path(sys.argv[2])
destination = Path(sys.argv[3])
classes = {site['clazz'] for family in ('regions', 'frames', 'targets', 'coverage',
                                       'doors', 'stateCandidates')
           for site in manifest.get(family, [])}
if not classes:
    raise SystemExit('manifest has no selected classes')
branches = [target for target in manifest.get('targets', [])
            if (target['clazz'], target['method'], target['line'], target['kind']) == (
                'org.apache.hadoop.hdfs.server.datanode.DataNode',
                'deleteBlockPool', 3819, 'BRANCH')]
if len(branches) != 1:
    raise SystemExit('manifest needs one HDFS-32 branch check at DataNode.deleteBlockPool:3819')
for clazz in sorted(classes):
    relative = Path(clazz.replace('.', '/') + '.class')
    original = source / relative
    if not original.is_file():
        raise SystemExit('selected class absent from exact static process directory: ' + str(original))
    copied = destination / relative
    copied.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, copied)
    print(clazz)
PY

cp "$manifest" "$run_dir/weave_manifest.json"
scope_map=$(dirname "$manifest")/static_scope_map.jsonl
if [[ -f $scope_map ]]; then cp "$scope_map" "$run_dir/static_scope_map.jsonl"; fi

(cd "$hadoop_dir" && mvn -q -pl hadoop-hdfs-project/hadoop-hdfs \
  dependency:build-classpath -Dmdep.outputFile="$run_dir/hdfs-test-classpath.txt" \
  -Dmdep.includeScope=test -DskipTests)
mvn -q -f "$weaver_dir/pom.xml" dependency:build-classpath \
  -Dmdep.outputFile="$run_dir/weaver-classpath.txt" -Dmdep.includeScope=runtime
hdfs_cp=$(cat "$run_dir/hdfs-test-classpath.txt")
weaver_cp=$(cat "$run_dir/weaver-classpath.txt")
tool_cp="$run_dir/weave-tool.jar:$runtime_jar:$weaver_cp"
graph_cp="$graph_analyzer_jar:$runtime_jar:$weaver_cp"
dependency_cp="$source_classes:$overlay:$hdfs_module/target/test-classes:$hdfs_module/target/classes:$hdfs_cp:$tool_cp"
if [[ -n ${MALLORY_HDFS_DEPENDENCY_CP_FILE:-} ]]; then
  [[ -s $MALLORY_HDFS_DEPENDENCY_CP_FILE ]] || {
    echo "missing exact static/weave classpath: $MALLORY_HDFS_DEPENDENCY_CP_FILE" >&2; exit 2;
  }
  dependency_cp=$(cat "$MALLORY_HDFS_DEPENDENCY_CP_FILE")
  cp "$MALLORY_HDFS_DEPENDENCY_CP_FILE" "$run_dir/static-weave-dependency-classpath.txt"
fi
printf '%s\n' "$dependency_cp" > "$run_dir/weave-dependency-classpath.txt"

timeout "${MALLORY_HDFS_WEAVE_TIMEOUT_SEC:-1800}s" \
  "$java_home/bin/java" -Xmx"${MALLORY_HDFS_WEAVE_HEAP:-4g}" -cp "$tool_cp" \
  edu.uva.liftlab.mallory.graphchecker.weave.WeaveMain \
  "$manifest" "$run_dir/input" "$run_dir/woven" "$dependency_cp" \
  > "$run_dir/weave.log" 2>&1 || {
    tail -80 "$run_dir/weave.log" >&2; exit 1;
  }

timeout "${MALLORY_HDFS_JUNIT_TIMEOUT_SEC:-600}s" "$java_home/bin/java" \
  -Xmx"${MALLORY_HDFS_JUNIT_HEAP:-4g}" \
  -Dhadoop.log.dir="$run_dir/logs" \
  -Dtest.build.data="$run_dir/test-data" \
  -Dmallory.graphchecker.trace.file="$run_dir/trace.jsonl" \
  -cp "$run_dir/woven:$overlay:$tool_cp:$hdfs_module/target/test-classes:$hdfs_module/target/classes:$hdfs_cp" \
  edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.RunOriginalJUnit \
  org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool \
  testDfsAdminDeleteBlockPool \
  > "$run_dir/junit.log" 2>&1 || {
    tail -100 "$run_dir/junit.log" >&2; exit 1;
  }

python3 "$port_dir/check_trace.py" "$run_dir/trace.jsonl" > "$run_dir/protocol-check.log"
target_site=$(python3 - "$manifest" <<'PY'
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
throw_site=$(python3 - "$manifest" <<'PY'
import json, sys
targets=json.load(open(sys.argv[1]))['targets']
oracle=[target for target in targets if target['kind']=='THROW' and target['line']==3822
        and target['clazz']=='org.apache.hadoop.hdfs.server.datanode.DataNode'
        and target['method']=='deleteBlockPool']
print(oracle[0]['siteId'] if len(oracle)==1 else '')
PY
)
if [[ -n $throw_site ]]; then
  timeout "${MALLORY_HDFS_GRAPH_TIMEOUT_SEC:-300}s" \
    "$java_home/bin/java" -Xmx"${MALLORY_HDFS_GRAPH_HEAP:-12g}" -cp "$graph_cp" \
    edu.uva.liftlab.mallory.graphchecker.runtime.TrialGraphMain \
    "$run_dir/trace.jsonl" "$run_dir/oracle-graph.jsonl" \
    "$run_dir/oracle-feedback.json" "$throw_site"
fi
python3 - "$run_dir" <<'PY'
import collections, json, pathlib, sys
root=pathlib.Path(sys.argv[1])
counts=collections.Counter()
with (root/'trace.jsonl').open() as trace:
    for line in trace:
        if line.strip():
            counts[json.loads(line).get('kind')] += 1
feedback=json.loads((root/'feedback.json').read_text())
print('JUNIT', [line for line in (root/'junit.log').read_text().splitlines() if line.startswith('JUNIT_')])
print('TRACE_COUNTS', dict(sorted(counts.items())))
summary_keys=('targetReached', 'targetChecks', 'targetCheckOutcomes',
              'targetThrows', 'nodes', 'edges', 'closureNodes',
              'closureEdges', 'closureCoverageSites', 'closureDoorSiteIds',
              'staticMayObservedDoorSiteIds')
summary={key:feedback.get(key) for key in summary_keys}
summary['gaps']={key:value for key,value in
                 sorted(feedback.get('gaps', {}).items(),
                        key=lambda item:-item[1])[:8]}
print('GRAPH_FEEDBACK', json.dumps(summary, sort_keys=True))
if (root/'oracle-feedback.json').exists():
    oracle=json.loads((root/'oracle-feedback.json').read_text())
    print('THROW_ORACLE', json.dumps({key:oracle[key] for key in
          ('targetReached','targetThrows','targetThrowClasses')}, sort_keys=True))
print('RUN_DIR', root)
PY
