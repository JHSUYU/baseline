#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
remote_user=ZhenyuLi@node1
remote_root=/users/ZhenyuLi/.mallory-worktrees/hbase/full-HBASE-01
local_root="$repo_root/data/mallory/cases/HBASE-01"
ssh_args=(-o BatchMode=yes -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes)

while true; do
  if status=$(ssh "${ssh_args[@]}" "$remote_user" "cat $remote_root/checkpoint.json" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'); then
    if [[ "$status" != running ]]; then
      if ssh "${ssh_args[@]}" "$remote_user" \
          'tmux has-session -t mallory-hbase01 2>/dev/null'; then
        sleep 5
        continue
      fi
      mkdir -p "$local_root"
      rsync -az --checksum -e \
        'ssh -o BatchMode=yes -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes' \
        "$remote_user:$remote_root/" "$local_root/"
      remote_sha=$(ssh "${ssh_args[@]}" "$remote_user" \
        "sha256sum $remote_root/result.json" | awk '{print $1}')
      local_sha=$(sha256sum "$local_root/result.json" | awk '{print $1}')
      if [[ "$remote_sha" != "$local_sha" ]]; then
        echo "result.json checksum differs after rsync" >&2
        exit 1
      fi
      printf 'HBASE-01 terminal status=%s result_sha256=%s\n' "$status" "$local_sha"
      set +e
      (cd "$repo_root" && python3 -m Mallory.core.audit \
        --campaign "$local_root" \
        --out "$local_root/offline-causal-audit.json")
      audit_rc=$?
      set -e
      if [[ "$audit_rc" == 2 ]]; then
        echo 'HBASE-01 offline causal audit failed the report-quality gate; raw result remains synced' >&2
      elif [[ "$audit_rc" != 0 ]]; then
        echo "HBASE-01 offline causal audit could not complete (exit $audit_rc)" >&2
        exit "$audit_rc"
      fi
      exit 0
    fi
  fi
  sleep 30
done
