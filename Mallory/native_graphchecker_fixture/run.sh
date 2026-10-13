#!/usr/bin/env bash
set -euo pipefail

fixture_dir=$(cd "$(dirname "$0")" && pwd)
engine_dir=$(cd "$fixture_dir/../static_scope_port/original_engine" && pwd)
vm_dir=${GC_ZERO_VM:-/proj/silentfailure-PG0/ZhenyuLi/tools/graphchecker-vm-c4a90033-20261013}
work_dir=$(mktemp -d /dev/shm/mallory-native-graphchecker-fixture-XXXXXXXX)

if [[ ! -x "$vm_dir/bin/java" || ! -x "$vm_dir/bin/javac" ]]; then
    echo "GraphChecker Zero VM is required: set GC_ZERO_VM" >&2
    exit 2
fi

(cd "$engine_dir" && mvn -q -DskipTests package dependency:build-classpath \
    -Dmdep.outputFile="$work_dir/dependencies.txt")
engine_jar="$engine_dir/target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
dependencies=$(cat "$work_dir/dependencies.txt")
classpath="$engine_jar:$dependencies"
mkdir -p "$work_dir/classes"
"$vm_dir/bin/javac" -cp "$classpath" -d "$work_dir/classes" \
    "$fixture_dir/NativeGraphCheckerSmoke.java"
javac -cp "$classpath" -d "$work_dir/classes" "$fixture_dir/ReadNativeSession.java"

method='<edu.uva.liftlab.graphchecker.runtime.NativeGraphCheckerSmoke: void run()>'
occurrence="dn0#epoch0/region/REGION.1/ctx:Root:CLIENT/smoke#1/idx:${method}#u0@0"
python3 - "$work_dir/task.jsonl" "$method" "$occurrence" <<'PY'
import json
import sys
out, method, occurrence = sys.argv[1:]
task = {
    "taskId": "TASK.1", "goalId": "GOAL.1", "goalKind": "TARGET_REACH_CLOSURE",
    "regionId": "REGION.1", "relationKey": "REL.1", "sourceKey": "dn0#epoch0",
    "occurrenceId": occurrence, "rootMethod": method, "instrumentationSelector": "sel",
    "admission": {"state": "EXECUTABLE"},
    "rootSelector": {"kind": "GLOBAL_INVOCATION", "invocationOrdinal": 1,
                     "causalAnchor": {"sourceKey": "dn0#epoch0", "kind": "REGISTERED_SOURCE"},
                     "method": method},
    "branchMethods": [method], "inputActions": [],
    "loopBound": {"schemaVersion": 1, "defaultBackedgeTraversals": 8},
    "targetBranch": {"siteId": method + "#u4", "occurrence": 1,
                     "requiredOutcome": False},
}
with open(out, "w", encoding="utf-8") as fp:
    fp.write(json.dumps(task, separators=(",", ":")) + "\n")
PY
: > "$work_dir/static_scope_map.jsonl"

CAUSYNTH_STATIC_SCOPE_MAP="$work_dir/static_scope_map.jsonl" \
CAUSYNTH_CONCOLIC_SESSIONS="$work_dir/sessions" \
timeout 30s "$vm_dir/bin/java" \
    -Dcausynth.concolic.task.plan="$work_dir/task.jsonl" \
    -Dcausynth.concolic.task.id=TASK.1 \
    -Dcausynth.concolic.results="$work_dir/result.json" \
    -cp "$work_dir/classes:$classpath" \
    edu.uva.liftlab.graphchecker.runtime.NativeGraphCheckerSmoke

session_manifest=$(find "$work_dir/sessions" -mindepth 2 -maxdepth 2 -name manifest.json -print -quit)
if [[ -z "$session_manifest" ]]; then
    echo "No native GraphChecker session was published" >&2
    exit 1
fi
session_id=$(basename "$(dirname "$session_manifest")")
java -cp "$work_dir/classes:$classpath" ReadNativeSession "$work_dir" "$session_id"
if ! rg -q 'VM_GUARDED_READ_FROM_V1' "$(dirname "$session_manifest")/expressions.jsonl"; then
    echo "No exact native ReadFrom expression was published" >&2
    exit 1
fi
echo "FIXTURE_OK $work_dir"
