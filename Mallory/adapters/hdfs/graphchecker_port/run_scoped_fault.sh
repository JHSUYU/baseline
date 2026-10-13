#!/usr/bin/env bash
# Mutate one observed closure door using the native GraphChecker trace fault controller.
set -euo pipefail
if [[ $# -ne 5 ]]; then
  echo 'usage: run_scoped_fault.sh <healthy-run-dir> <overlay> <graph-runtime.jar> <hadoop-3.4.3-checkout> <new-fault-run-dir>' >&2
  exit 2
fi
healthy=$(realpath "$1")
overlay=$(realpath "$2")
runtime_jar=$(realpath "$3")
hadoop_dir=$(realpath "$4")
fault_dir=$5
hdfs_module=$hadoop_dir/hadoop-hdfs-project/hadoop-hdfs
java_home=${JAVA_HOME:-/usr/lib/jvm/java-8-openjdk-amd64}
for required in "$healthy/trace.jsonl" "$healthy/feedback.json" \
    "$healthy/weave_manifest.json" "$healthy/hdfs-test-classpath.txt" \
    "$healthy/weaver-classpath.txt" "$healthy/input" "$healthy/weave-tool.jar" \
    "$healthy/graph-runtime.jar" "$healthy/weave-dependency-classpath.txt" \
    "$runtime_jar"; do
  [[ -e $required ]] || { echo "missing prerequisite: $required" >&2; exit 2; }
done
cmp -s "$runtime_jar" "$healthy/graph-runtime.jar" || {
  echo 'fault trial runtime jar differs from healthy trial' >&2; exit 2;
}
[[ ! -e $fault_dir ]] || { echo "refusing to replace run directory: $fault_dir" >&2; exit 2; }
mkdir -p "$fault_dir/woven" "$fault_dir/logs" "$fault_dir/test-data"
fault_dir=$(realpath "$fault_dir")
runtime_jar=$healthy/graph-runtime.jar

python3 - "$healthy" "$fault_dir" <<'PY'
import json, pathlib, sys
healthy, output = map(pathlib.Path, sys.argv[1:])
feedback = json.loads((healthy/'feedback.json').read_text())
manifest = json.loads((healthy/'weave_manifest.json').read_text())
closure = set(feedback.get('closureDoorSiteIds', []))
closure_occurrences = set(feedback.get('closureOccurrenceIds', []))
closure_cutoffs = feedback.get('closureOccurrenceCutoffs', {})
declared = {door['siteId']: door for door in manifest.get('doors', [])}
chosen = None
with (healthy/'trace.jsonl').open() as trace:
    for line in trace:
        if not line.strip():
            continue
        row = json.loads(line)
        if (row.get('kind') == 'FAULT_DOOR'
                and row.get('siteId') in closure
                and row.get('occurrenceId') in closure_occurrences
                and isinstance(closure_cutoffs.get(row.get('occurrenceId')), int)
                and row.get('seq', -1) <= closure_cutoffs[row['occurrenceId']]
                and row.get('siteId') in declared
                and declared[row['siteId']].get('exceptionClass')
                and row.get('node') and row.get('occurrenceId')
                and row.get('doorOrdinal', 0) >= 1):
            chosen = row
            break
if chosen is None:
    raise SystemExit('no observed injectable fault door in the exact healthy target closure')
manifest['faultController'] = 'MALLORY_GC_FAULT_PLAN'
(output/'weave_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
plan = {'faults': [{
    'siteId': chosen['siteId'], 'node': chosen['node'],
    'occurrenceId': chosen['occurrenceId'], 'ordinal': chosen['doorOrdinal'],
    'exceptionClass': declared[chosen['siteId']]['exceptionClass']}]}
(output/'fault-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
(output/'selected-door.json').write_text(json.dumps({
    'door': chosen, 'selection': 'first observed injectable door in exact target closure'},
    indent=2) + '\n')
print('selected exact closure door:', chosen['siteId'], chosen['occurrenceId'],
      chosen['doorOrdinal'])
PY

tool_cp="$healthy/weave-tool.jar:$runtime_jar:$(cat "$healthy/weaver-classpath.txt")"
graph_analyzer_jar=$healthy/graph-analyzer.jar
[[ -f $graph_analyzer_jar ]] || graph_analyzer_jar=$runtime_jar
graph_cp="$graph_analyzer_jar:$runtime_jar:$(cat "$healthy/weaver-classpath.txt")"
hdfs_cp=$(cat "$healthy/hdfs-test-classpath.txt")
dependency_cp=$(cat "$healthy/weave-dependency-classpath.txt")
timeout "${MALLORY_HDFS_WEAVE_TIMEOUT_SEC:-1800}s" \
  "$java_home/bin/java" -Xmx"${MALLORY_HDFS_WEAVE_HEAP:-4g}" -cp "$tool_cp" \
  edu.uva.liftlab.mallory.graphchecker.weave.WeaveMain \
  "$fault_dir/weave_manifest.json" "$healthy/input" "$fault_dir/woven" "$dependency_cp" \
  > "$fault_dir/weave.log" 2>&1 || {
    tail -80 "$fault_dir/weave.log" >&2; exit 1;
  }

set +e
timeout "${MALLORY_HDFS_JUNIT_TIMEOUT_SEC:-600}s" "$java_home/bin/java" \
  -Xmx"${MALLORY_HDFS_JUNIT_HEAP:-4g}" \
  -Dhadoop.log.dir="$fault_dir/logs" \
  -Dtest.build.data="$fault_dir/test-data" \
  -Dmallory.graphchecker.trace.file="$fault_dir/trace.jsonl" \
  -Dmallory.gc.fault.plan="$fault_dir/fault-plan.json" \
  -cp "$fault_dir/woven:$overlay:$tool_cp:$hdfs_module/target/test-classes:$hdfs_module/target/classes:$hdfs_cp" \
  edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.RunOriginalJUnit \
  org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool \
  testDfsAdminDeleteBlockPool \
  > "$fault_dir/junit.log" 2>&1
junit_status=$?
set -e
echo "$junit_status" > "$fault_dir/junit-exit-code.txt"
[[ -s $fault_dir/trace.jsonl ]] || { tail -100 "$fault_dir/junit.log" >&2; exit 1; }
target_site=$(python3 - "$fault_dir/weave_manifest.json" <<'PY'
import json, sys
targets=json.load(open(sys.argv[1]))['targets']
branch=[target for target in targets if target['kind']=='BRANCH' and target['line']==3819
        and target['clazz']=='org.apache.hadoop.hdfs.server.datanode.DataNode'
        and target['method']=='deleteBlockPool']
assert len(branch)==1
print(branch[0]['siteId'])
PY
)
graph_args=("$fault_dir/trace.jsonl" "$fault_dir/graph.jsonl" "$fault_dir/feedback.json" \
  "$target_site" "$healthy/trace.jsonl")
if [[ -f $healthy/static_scope_map.jsonl ]]; then
  graph_args+=( "$healthy/static_scope_map.jsonl" )
fi
timeout "${MALLORY_HDFS_GRAPH_TIMEOUT_SEC:-300}s" \
  "$java_home/bin/java" -Xmx"${MALLORY_HDFS_GRAPH_HEAP:-12g}" -cp "$graph_cp" \
  edu.uva.liftlab.mallory.graphchecker.runtime.TrialGraphMain "${graph_args[@]}"
throw_site=$(python3 - "$fault_dir/weave_manifest.json" <<'PY'
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
    "$fault_dir/trace.jsonl" "$fault_dir/oracle-graph.jsonl" \
    "$fault_dir/oracle-feedback.json" "$throw_site" "$healthy/trace.jsonl"
fi
python3 - "$fault_dir" <<'PY'
import collections, json, pathlib, sys
root=pathlib.Path(sys.argv[1])
counts=collections.Counter()
feedback=json.loads((root/'feedback.json').read_text())
selected=json.loads((root/'fault-plan.json').read_text())['faults'][0]
applied_count=0
applied_seq=None
with (root/'trace.jsonl').open() as trace:
    for line in trace:
        if not line.strip():
            continue
        row=json.loads(line)
        counts[row.get('kind')]+=1
        if (row.get('kind') == 'FAULT_APPLIED'
                and all(row.get(key) == selected[key]
                        for key in ('siteId', 'node', 'occurrenceId'))
                and row.get('doorOrdinal') == selected['ordinal']
                and row.get('exceptionClass') == selected['exceptionClass']):
            applied_count+=1
            applied_seq=row.get('seq')
def in_pre_target_closure(result):
    occurrence=selected['occurrenceId']
    cutoff=result.get('closureOccurrenceCutoffs', {}).get(occurrence)
    return (applied_count == 1 and occurrence in result.get('closureOccurrenceIds', [])
            and isinstance(applied_seq, int) and isinstance(cutoff, int)
            and applied_seq <= cutoff)
path_target_reached=bool(feedback.get('targetReached') and in_pre_target_closure(feedback))
print('JUNIT_EXIT', (root/'junit-exit-code.txt').read_text().strip())
print('TRACE_COUNTS', dict(sorted(counts.items())))
print('EXACT_FAULT_APPLIED', applied_count == 1,
      'GLOBAL_TARGET_REACHED', feedback.get('targetReached'),
      'INJECTED_PATH_REACHED_TARGET', path_target_reached)
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
    path_throw=bool(oracle.get('targetReached') and in_pre_target_closure(oracle))
    print('THROW_ORACLE', json.dumps({key:oracle[key] for key in
          ('targetReached','targetThrows','targetThrowClasses')}, sort_keys=True))
else:
    path_throw=False
status={'exactFaultApplied':applied_count == 1,
        'globalTargetReached':bool(feedback.get('targetReached')),
        'faultOccurrenceInTargetClosure':
            selected['occurrenceId'] in feedback.get('closureOccurrenceIds', []),
        'injectedPathReachedTarget':path_target_reached,
        'injectedPathTargetThrow':path_throw,
        'classification':('FAULT_NOT_APPLIED' if applied_count != 1 else
                          'TARGET_LOST' if not path_target_reached else
                          'TARGET_THROW' if path_throw else 'TARGET_REACHED')}
(root/'trial-status.json').write_text(json.dumps(status, indent=2) + '\n')
print('TRIAL_STATUS', json.dumps(status, sort_keys=True))
print('RUN_DIR', root)
PY
