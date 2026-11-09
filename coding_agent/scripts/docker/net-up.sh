#!/usr/bin/env bash
# net-up.sh -- on this node: the internal network for agent containers and the allowlist proxy on it.
set -euo pipefail
docker network inspect ca-internal >/dev/null 2>&1 || docker network create --internal ca-internal >/dev/null
if ! docker ps --format '{{.Names}}' | grep -qx ca-proxy; then
  docker rm -f ca-proxy >/dev/null 2>&1 || true
  docker run -d --name ca-proxy --restart unless-stopped --network bridge codingagent-proxy:1 >/dev/null
  docker network connect ca-internal ca-proxy
fi
echo "ca-proxy up on $(hostname -s)"
