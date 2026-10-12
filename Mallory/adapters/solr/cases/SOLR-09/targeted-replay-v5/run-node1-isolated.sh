#!/usr/bin/env bash
set -euo pipefail
cd /users/ZhenyuLi/mallory-solr09-v5-node1
mkdir -p data/mallory
exec python3 Mallory/adapters/solr/cases/SOLR-09/targeted-replay-v1/run.py \
  --trials 12 --data-scope all --data-hit 3 \
  --output data/mallory/solr09_targeted_replay_v5_node1/SOLR-09
