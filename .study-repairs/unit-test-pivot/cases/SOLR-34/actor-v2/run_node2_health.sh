#!/usr/bin/env bash
set -euo pipefail
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-34/actor-v2
test "$(hostname)" = node2.baseline.silentfailure-pg0.utah.cloudlab.us
python3 run.py node2-clean-01 --test-seed 54BB401E73EA9B17
python3 run.py node2-healthy-01 --test-seed 54BB401E73EA9B17 --agent solrcoord-actor-v2-agent.jar
python3 run.py node2-clean-02 --test-seed B002131FF00DDDD1
python3 run.py node2-healthy-02 --test-seed B002131FF00DDDD1 --agent solrcoord-actor-v2-agent.jar
python3 audit_node2_health.py
