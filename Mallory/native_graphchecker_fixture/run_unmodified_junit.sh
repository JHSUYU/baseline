#!/usr/bin/env bash
set -euo pipefail

fixture_dir=$(cd "$(dirname "$0")" && pwd)
mallory_dir=$(cd "$fixture_dir/.." && pwd)
engine_dir="$mallory_dir/static_scope_port/original_engine"
vm_dir=${GC_ZERO_VM:-/proj/silentfailure-PG0/ZhenyuLi/tools/graphchecker-vm-c4a90033-20261013}
work_dir=$(mktemp -d /dev/shm/mallory-native-junit-fixture-XXXXXXXX)
mkdir -p "$work_dir/original" "$work_dir/tools" "$work_dir/harness" "$work_dir/post"

if [[ ! -x "$vm_dir/bin/java" ]]; then
    echo "GraphChecker Zero VM is required: set GC_ZERO_VM" >&2
    exit 2
fi
python3 "$mallory_dir/instrumentation/graphchecker_port/native_original_weave.py" \
    --prepare-engine > "$work_dir/engine-receipt.json"
vendor_jar="$engine_dir/target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
dependencies=$(cat "$engine_dir/target/native-original-dependencies.txt")
classpath="$vendor_jar:$dependencies"

javac -cp "$classpath" -d "$work_dir/original" \
    "$fixture_dir/PlainFixture.java" "$fixture_dir/PlainFixtureTest.java"
javac -cp "$work_dir/original:$classpath" -d "$work_dir/tools" \
    "$fixture_dir/DumpJimple.java" "$fixture_dir/ReadNativeSession.java"
javac -d "$work_dir/post" "$fixture_dir/NativePostWeaveProbe.java"
java -cp "$work_dir/tools:$work_dir/original:$classpath" DumpJimple \
    "$work_dir/original" "$classpath" > "$work_dir/original-jimple.txt"
if ! rg -q '^2[[:space:]]+JAssignStmt' "$work_dir/original-jimple.txt" \
    || ! rg -q '^3[[:space:]]+JAssignStmt' "$work_dir/original-jimple.txt" \
    || ! rg -q '^4[[:space:]]+JIfStmt' "$work_dir/original-jimple.txt"; then
    echo "PlainFixture's original Jimple unit identities changed" >&2
    exit 1
fi

python3 - "$work_dir" <<'PY'
import json
from pathlib import Path
import sys

work = Path(sys.argv[1])
method = '<edu.uva.liftlab.graphchecker.runtime.PlainFixture: int run(int)>'
field = '<edu.uva.liftlab.graphchecker.runtime.PlainFixture: int value>'
vm_site = 'edu.uva.liftlab.graphchecker.runtime.PlainFixture#run(I)I'
occurrence = ('dn0#epoch0/region/REGION.1/ctx:Root:CLIENT/plain-junit#1/'
              'idx:plain-junit@0/'
              '<edu.uva.liftlab.graphchecker.runtime.PlainFixtureTest: '
              'void healthyOperation()>@0/' + method + '@0')
skeleton = {
    'schemaVersion': 3, 'kind': 'REGION_SKELETON', 'regionId': 'REGION.1',
    'rootMethod': method, 'rootAuthority': 'METHOD_ENTRY',
    'anchorMethod': method, 'anchorMethods': [method], 'methods': [method],
}
(work / 'skeletons.jsonl').write_text(json.dumps(skeleton) + '\n')
task = {
    'taskId': 'TASK.1', 'goalId': 'GOAL.1',
    'goalKind': 'TARGET_REACH_CLOSURE', 'regionId': 'REGION.1',
    'relationKey': 'REL.1', 'sourceKey': 'dn0#epoch0',
    'occurrenceId': occurrence, 'rootMethod': method,
    'instrumentationSelector': 'sel', 'admission': {'state': 'EXECUTABLE'},
    'rootSelector': {
        'kind': 'GLOBAL_INVOCATION', 'invocationOrdinal': 1,
        'causalAnchor': {'sourceKey': 'dn0#epoch0',
                         'kind': 'REGISTERED_SOURCE'},
        'method': method,
    },
    'branchMethods': [method],
    'inputActions': [{'mode': 'SYMBOLIC', 'bindingMode': 'METHOD_ARGUMENT',
                      'method': method, 'index': 0}],
    'observedSites': [
        {'method': method, 'unitIndex': unit, 'siteId': method + '#u' + str(unit),
         'declaredCallee': '', 'cell': field, 'read': read,
         'static': False, 'field': True, 'container': False}
        for unit, read in ((2, False), (3, True))
    ],
    'loopBound': {'schemaVersion': 1, 'defaultBackedgeTraversals': 8},
    'targetBranch': {'siteId': method + '#u4', 'occurrence': 1,
                     'requiredOutcome': True},
}
(work / 'task.jsonl').write_text(json.dumps(task) + '\n')
with (work / 'static_scope_map.jsonl').open('w') as stream:
    for role, unit in (('WRITE_SITE', 2), ('READ_SITE', 3)):
        stream.write(json.dumps({
            'schemaVersion': 1, 'kind': 'STATIC_SCOPE_SITE', 'role': role,
            'regionId': 'REGION.1', 'siteId': method + '#u' + str(unit),
            'vmSite': vm_site, 'cell': field, 'carrier': field,
            'portId': '', 'guards': [],
        }) + '\n')
config = {
    'input_classes': str(work / 'original'),
    'output_classes': str(work / 'woven'),
    'task_plan': str(work / 'task.jsonl'), 'task_id': 'TASK.1',
    'region_skeletons': str(work / 'skeletons.jsonl'),
    'dependency_classpath': str(work / 'original'),
    'java': '/usr/lib/jvm/java-8-openjdk-amd64/bin/java',
    'timeout_seconds': 60,
    'post_weave': {
        'main_class': 'NativePostWeaveProbe',
        'classpath': str(work / 'post'),
        'args': ['--classes', '{woven_classes}'],
    },
}
(work / 'weave.json').write_text(json.dumps(config, indent=2) + '\n')
PY

python3 "$mallory_dir/instrumentation/graphchecker_port/native_original_weave.py" \
    --config "$work_dir/weave.json" > "$work_dir/weave-stdout.json"
if [[ ! -f "$work_dir/woven/post-weave-verified.txt" ]]; then
    echo "Optional post-weave adapter did not run" >&2
    exit 1
fi
python3 "$mallory_dir/instrumentation/graphchecker_port/native_original_weave.py" \
    --config "$work_dir/weave.json" --verify-only > "$work_dir/verify-stdout.json"
if ! javap -classpath "$work_dir/woven" -c -p \
    edu.uva.liftlab.graphchecker.runtime.PlainFixture \
    | rg -q 'System.markConcolicBranch'; then
    echo "Original GraphChecker branch marker is absent from woven class" >&2
    exit 1
fi
javac -cp "$work_dir/woven:$classpath" -d "$work_dir/harness" \
    "$fixture_dir/PlainFixtureRunner.java"

CAUSYNTH_STATIC_SCOPE_MAP="$work_dir/static_scope_map.jsonl" \
CAUSYNTH_CONCOLIC_SESSIONS="$work_dir/sessions" \
timeout 30s "$vm_dir/bin/java" \
    -Dcausynth.concolic.task.plan="$work_dir/task.jsonl" \
    -Dcausynth.concolic.task.id=TASK.1 \
    -Dcausynth.concolic.results="$work_dir/result.json" \
    -cp "$work_dir/harness:$work_dir/woven:$classpath" \
    edu.uva.liftlab.graphchecker.runtime.PlainFixtureRunner

manifest=$(find "$work_dir/sessions" -mindepth 2 -maxdepth 2 \
    -name manifest.json -print -quit)
if [[ -z "$manifest" ]]; then
    echo "Native GraphChecker session is absent" >&2
    exit 1
fi
session_dir=$(dirname "$manifest")
session_id=$(basename "$session_dir")
java -cp "$work_dir/tools:$classpath" ReadNativeSession \
    "$work_dir" "$session_id"
if ! rg -q 'VM_GUARDED_READ_FROM_V1' "$session_dir/expressions.jsonl"; then
    echo "Native exact read-from expression is absent" >&2
    exit 1
fi
if [[ $(wc -l < "$session_dir/writes.jsonl") -ne 1 ]]; then
    echo "Expected one native write row" >&2
    exit 1
fi
python3 "$mallory_dir/instrumentation/graphchecker_port/native_original_weave.py" \
    --config "$work_dir/weave.json" --verify-only > "$work_dir/verify-before-replay.json"
CAUSYNTH_STATIC_SCOPE_MAP="$work_dir/static_scope_map.jsonl" \
CAUSYNTH_CONCOLIC_SESSIONS="$work_dir/replay-root/sessions" \
timeout 30s "$vm_dir/bin/java" \
    -Dcausynth.concolic.task.plan="$work_dir/task.jsonl" \
    -Dcausynth.concolic.task.id=TASK.1 \
    -Dcausynth.concolic.results="$work_dir/replay-root/result.json" \
    -cp "$work_dir/harness:$work_dir/woven:$classpath" \
    edu.uva.liftlab.graphchecker.runtime.PlainFixtureRunner \
    > "$work_dir/replay.log" 2>&1
replay_manifest=$(find "$work_dir/replay-root/sessions" -mindepth 2 -maxdepth 2 \
    -name manifest.json -print -quit)
if [[ -z "$replay_manifest" ]]; then
    echo "Second native session is absent" >&2
    exit 1
fi
replay_id=$(basename "$(dirname "$replay_manifest")")
java -cp "$work_dir/tools:$classpath" ReadNativeSession \
    "$work_dir/replay-root" "$replay_id"
python3 "$mallory_dir/instrumentation/graphchecker_port/native_original_weave.py" \
    --config "$work_dir/weave.json" --verify-only > "$work_dir/verify-after-replay.json"
echo "TWO_DYNAMIC_TRIALS_ONE_STATIC_WEAVE"
python3 - "$work_dir" "$mallory_dir/instrumentation/graphchecker_port/native_original_weave.py" <<'PY'
import json
from pathlib import Path
import subprocess
import sys

work, launcher = map(Path, sys.argv[1:])
config = work / 'weave.json'
for name in ('original', 'woven', 'post'):
    clazz = ((work / name /
              'edu/uva/liftlab/graphchecker/runtime/PlainFixture.class')
             if name != 'post' else work / 'post/NativePostWeaveProbe.class')
    original = clazz.read_bytes()
    try:
        clazz.write_bytes(original + b'changed')
        result = subprocess.run(
            [sys.executable, str(launcher), '--config', str(config),
             '--verify-only'], capture_output=True, text=True)
        expected = ('post-weave adapter changed' if name == 'post' else
                    'immutable native weave input changed')
        if result.returncode == 0 or expected not in result.stderr:
            raise SystemExit('native weave verifier accepted tampered ' + name)
    finally:
        clazz.write_bytes(original)
    subprocess.run([sys.executable, str(launcher), '--config', str(config),
                    '--verify-only'], check=True, stdout=subprocess.DEVNULL)
print('IMMUTABLE_WEAVE_TAMPER_REJECTED')
PY
echo "UNCHANGED_JUNIT_OK $work_dir"
