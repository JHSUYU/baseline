#!/usr/bin/env bash
set -euo pipefail

root=/users/ZhenyuLi/.mallory-worktrees/zookeeper-ackepoch-retry-door-node1
receipt=/users/ZhenyuLi/baseline/data/mallory/admissions/ZOOKEEPER-06-ackepoch-retry-door-node1-source-v2.json
output=/users/ZhenyuLi/baseline/data/mallory/calibration/ZOOKEEPER-06/ackepoch-retry-door-node1-compile-v2
lock=/tmp/mallory-lanes/zookeeper-node1-source.lock
floor=5997854720

if [[ -e "$output" ]]; then
    printf 'compile output already exists: %s\n' "$output" >&2
    exit 73
fi
mkdir -p /tmp/mallory-lanes
exec 9>"$lock"
flock -n 9 || { printf 'ZooKeeper source lock busy\n' >&2; exit 75; }

python3 - "$root" "$receipt" <<'PY'
import hashlib, json, pathlib, sys
root, receipt_path = map(pathlib.Path, sys.argv[1:])
receipt = json.loads(receipt_path.read_text())
assert receipt["host"] == "node1" and pathlib.Path(receipt["patched_root"]) == root
for relative, expected in receipt["modified_files"].items():
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"source hash mismatch: {relative}")
PY

free_before=$(df -B1 --output=avail "$root" | tail -1 | tr -d ' ')
if (( free_before < floor )); then
    printf 'disk below compilation reserve: %s\n' "$free_before" >&2
    exit 75
fi
mkdir -p "$output"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
set +e
(cd "$root" && timeout 900 mvn -B -ntp -pl zookeeper-server -am -DskipTests test-compile) >"$output/compile.log" 2>&1
status=$?
set -e
finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
free_after=$(df -B1 --output=avail "$root" | tail -1 | tr -d ' ')
python3 - "$output/compile-exit.json" "$started" "$finished" "$status" "$free_before" "$free_after" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
value = {"started_utc": sys.argv[2], "finished_utc": sys.argv[3],
         "exit_code": int(sys.argv[4]), "free_before_bytes": int(sys.argv[5]),
         "free_after_bytes": int(sys.argv[6]), "test_execution": False}
path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
PY
exit "$status"
