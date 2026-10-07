#!/usr/bin/env bash
# Run on node0 only after node2's campaign has exited at a complete trial.
# This freezes, audits and copies V5 to node1. It never starts a JUnit run.
set -euo pipefail

key="$HOME/.ssh/id_ed25519_nodes"
ssh_opts=(-i "$key" -o IdentitiesOnly=yes -o BatchMode=yes)
source_host=ZhenyuLi@node2
dest_host=ZhenyuLi@node1
base=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-10
actor="$base/actor-v2"
campaign="$actor/evidence/campaign-v4"
stage="$base/.actor-v2-v5-stage"
previous="$base/.actor-v2-v5-previous"

ssh "${ssh_opts[@]}" "$source_host" \
    "python3 '$actor/probe/migrate.py' manifest"
ssh "${ssh_opts[@]}" "$source_host" \
    "python3 '$actor/probe/audit.py' '$campaign'"
ssh "${ssh_opts[@]}" "$source_host" \
    "python3 '$actor/probe/migrate.py' manifest"
source_preflight=$(ssh "${ssh_opts[@]}" "$source_host" \
    "python3 '$actor/probe/migrate.py' preflight")
dest_preflight=$(ssh "${ssh_opts[@]}" "$dest_host" \
    "python3 '$actor/probe/migrate.py' preflight")
SOURCE_PREFLIGHT="$source_preflight" DEST_PREFLIGHT="$dest_preflight" python3 - <<'PY'
import json, os
a=json.loads(os.environ['SOURCE_PREFLIGHT'])
b=json.loads(os.environ['DEST_PREFLIGHT'])
if a['static_receipt_sha256'] != b['static_receipt_sha256']:
    raise SystemExit('Per-file source/classpath/JUnit/hook receipt differs')
if b['active_campaign_pids']:
    raise SystemExit('Destination campaign or JUnit is running')
print(json.dumps({'static_receipt_sha256': a['static_receipt_sha256'],
                  'classpath_file_count': a['classpath_file_count']}))
PY

ssh "${ssh_opts[@]}" "$dest_host" \
    "python3 - <<'PY'
from pathlib import Path
import shutil
base=Path('$base')
assert not Path('$stage').exists(), 'staging directory already exists'
assert not Path('$previous').exists(), 'previous directory already exists'
assert shutil.disk_usage(base).free >= 8 * 1024**3, 'node1 below 8 GiB'
Path('$stage').mkdir()
PY"

ssh "${ssh_opts[@]}" "$source_host" "tar -C '$base' -cf - actor-v2" | \
    ssh "${ssh_opts[@]}" "$dest_host" "tar -C '$stage' -xf -"
ssh "${ssh_opts[@]}" "$dest_host" \
    "python3 '$stage/actor-v2/probe/migrate.py' verify-files"

ssh "${ssh_opts[@]}" "$dest_host" \
    "set -eu
     mv '$actor' '$previous'
     mv '$stage/actor-v2' '$actor'
     rmdir '$stage'
     if ! python3 '$actor/probe/migrate.py' verify; then
       mv '$actor' '$stage'
       mv '$previous' '$actor'
       echo 'Full destination verification failed; old actor-v2 restored' >&2
       exit 1
     fi
     python3 '$actor/probe/migrate.py' verify > '$campaign/migration-v5-verified.json'
     python3 - <<'PY'
import json
from pathlib import Path
p=Path('$campaign/migration-v5-verified.json')
r=json.loads(p.read_text())
print(json.dumps({'ready_on_node1': True, 'junit_started': False,
                  'trial_count': r['trial_count'], 'effective': r['effective'],
                  'manifest_sha256': r['manifest_sha256'],
                  'state_sha256': r['state_sha256']}))
PY"
