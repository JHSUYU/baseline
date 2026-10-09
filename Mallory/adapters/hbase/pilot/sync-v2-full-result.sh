#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
release_id=5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
release_root="$repo_root/Mallory/dispatch/releases/$release_id"
remote_user=ZhenyuLi@node1
remote_root=/users/ZhenyuLi/.mallory-worktrees/hbase/lane1-v2/full-HBASE-01
remote_runtime=/users/ZhenyuLi/.mallory-worktrees/hbase/lane1-v2/runtime
archive_root="$repo_root/data/mallory/HBASE-01/campaigns"
v1_root="$archive_root/v1-full"
v2_root="$archive_root/v2-full"
canonical="$repo_root/data/mallory/cases/HBASE-01"
ssh_args=(-o BatchMode=yes -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes)

remote_hash() {
  ssh "${ssh_args[@]}" "$remote_user" "sha256sum '$1'" | awk '{print $1}'
}

verify_remote() {
  local expected=$1 actual
  actual=$(remote_hash "$2")
  if [[ "$expected" != "$actual" ]]; then
    echo "remote artifact SHA mismatch: $2 expected=$expected actual=$actual" >&2
    exit 1
  fi
}

while true; do
  if status=$(ssh "${ssh_args[@]}" "$remote_user" \
      "cat '$remote_root/checkpoint.json'" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'); then
    if [[ "$status" != running ]]; then
      if ssh "${ssh_args[@]}" "$remote_user" \
          'tmux has-session -t mallory-hbase01-v2-full 2>/dev/null'; then
        sleep 5
        continue
      fi
      break
    fi
  fi
  sleep 30
done

(cd "$repo_root" && python3 -m Mallory.dispatch.core_release --verify \
  "$release_root/manifest.json")
if [[ $(sha256sum "$release_root/manifest.json" | awk '{print $1}') != \
      101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f ]]; then
  echo 'fixed core release manifest SHA changed' >&2
  exit 1
fi
verify_remote 07c23da7699217aa4f51c389cde3539ee241ece05efa5d11575bc5d804cf4e80 \
  "$remote_runtime/agent.jar"
verify_remote cdbd1bda62dd23833e0f1bb62dd35fbfcff0f9dd1a1ec8fa982ba5cf722cb63f \
  "$remote_runtime/adapter.jar"
verify_remote 64c8def80af5a041df36638fb3c5d4fdfccbf1805bf34db7dd05ee9ea6a279ab \
  "$remote_runtime/cases/HBASE-01/sites.json"
verify_remote 9b44bf693a8365dd01364cc1641208c0a481902116e316830260b3f71c8d4445 \
  "$remote_runtime/classes/edu/uva/liftlab/mallory/hbase/pilot/SelectedJUnit.class"
verify_remote 93b7a78b3bc4e883c6dcc0bae3bddbfe5fde180613ba920783800e68959e778d \
  "$remote_runtime/cases/HBASE-01/v2-full.json"

mkdir -p "$v2_root"
rsync -az --checksum -e \
  'ssh -o BatchMode=yes -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes' \
  "$remote_user:$remote_root/" "$v2_root/"
remote_result_sha=$(remote_hash "$remote_root/result.json")
local_result_sha=$(sha256sum "$v2_root/result.json" | awk '{print $1}')
if [[ "$remote_result_sha" != "$local_result_sha" ]]; then
  echo 'v2 result.json SHA differs after rsync' >&2
  exit 1
fi

(cd "$release_root" && PYTHONPATH="$release_root:$repo_root" python3 -m Mallory.core.audit \
  --campaign "$v2_root" --out "$v2_root/offline-causal-audit.json")
python3 - "$v2_root" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
report = json.loads((root / "offline-causal-audit.json").read_text())
result = json.loads((root / "result.json").read_text())
attestation = result.get("runtime_attestation") or {}
assert report.get("report_gate_passed") is True, "v2 offline causal quality failed"
assert report.get("archive_integrity_valid") is True
assert report.get("applied_fault_identity_valid") is True
assert attestation.get("valid") is True, "loaded target identity invalid"
assert attestation.get("observed_target_class_sha256") == (
    "d04a6e5bad1b1933b343eccb7cb858072842df9498552c1cf548218a996abb1f")
print("HBASE-01 v2 quality passed", result.get("status"),
      result.get("fault_trials_completed"), report.get("trial_count"))
PY

if [[ -e "$v1_root" || -L "$v1_root" ]]; then
  echo "v1 archive already exists: $v1_root" >&2
  exit 1
fi
if [[ -L "$canonical" || ! -d "$canonical" ]]; then
  echo "unexpected canonical v1 path: $canonical" >&2
  exit 1
fi
if [[ $(sha256sum "$canonical/result.json" | awk '{print $1}') != \
      5b120971bc3dfc57dbc64d0b7a303e18ff262b1b38d82e47d15926dfc0bd9c29 ]]; then
  echo 'canonical v1 result SHA changed' >&2
  exit 1
fi
mv "$canonical" "$v1_root"
ln -s ../HBASE-01/campaigns/v2-full "$canonical"

python3 - "$v1_root" "$v2_root" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
for name in sys.argv[1:]:
    root = Path(name)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "sha256-receipt.json":
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {"schema_version": 1, "case_id": "HBASE-01",
               "campaign": root.name, "files": files}
    (root / "sha256-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(root, len(files), "files", files.get("result.json"))
PY

echo "HBASE-01 canonical now points to audited v2; v1 preserved at $v1_root"
