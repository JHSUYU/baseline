#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-05/receiver-read-v4
remote=ZhenyuLi@node2:/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-05/receiver-read-v4/
ssh_cmd='ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5'

sync_once() {
  rsync -a --delay-updates --exclude='scratch/' --exclude='generated/' \
    --exclude='classes/' --exclude='classes-original/' \
    -e "$ssh_cmd" "$case_dir/" "$remote"
  printf '%s mirrored SOLR-05 V4 completed raw and checkpoint\n' "$(date -u +%FT%TZ)"
}

while tmux has-session -t solr05_receiver_v4 2>/dev/null; do
  sync_once || true
  sleep 120
done
sync_once
