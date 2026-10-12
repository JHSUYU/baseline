#!/usr/bin/env bash
set -euo pipefail
cd /users/ZhenyuLi/baseline
mkdir -p /tmp/mallory-lanes data/mallory
exec flock -n /tmp/mallory-lanes/solr-node0-v1.lock \
  flock -n /tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock \
  python3 -m Mallory.core.campaign \
    --config Mallory/adapters/solr/cases/SOLR-40/graph-auto-v8/config.json \
    --out data/mallory/solr40_graph_auto_v8_node0/SOLR-40
