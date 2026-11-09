#!/bin/bash
# MC-1 reproduction driver. Runs the Level-0 variant of MigrateRouteKeyTest on the
# pristine base_commit tree (harness instrumentation stashed), in bug mode and control mode.
set -u
WT=/users/ZhenyuLi/Specula/runs/20261107-215441-cb9e/solr-adhoc-k3/.specula-output/confirmation/MC-1/worktree
R=/users/ZhenyuLi/Specula/runs/20261107-215441-cb9e/solr-adhoc-k3/.specula-output/repro
source /bulk/specula-adhoc/solr/cases/solr-adhoc-k3/env.sh
cp "$R/test_bugMC-1_SpeculaReproMC1MigrateRouteKeyTest.java" "$WT/solr/core/src/test/org/apache/solr/cloud/SpeculaReproMC1MigrateRouteKeyTest.java"
cd "$WT/solr/core"
run() { # $1=label $2=extra args
  timeout 15m ant -lib $IVY_USER_DIR/lib test -Dtestcase=SpeculaReproMC1MigrateRouteKeyTest -Dtests.jvms=1 \
    -Dtests.useSecurityManager=false -Dtests.showOutput=always -Divy_install_path=$IVY_USER_DIR/lib "$@" > "$R/MC-1.$label.log" 2>&1
  echo "== $label: ant exit=$?"
  grep -h "\[MC-1\]\|Tests summary" "$R/MC-1.$label.log" | sed 's/^ *\[junit4\] *1> //'
  grep -h -m1 "Caused by: org.apache.solr.common.SolrException: non legacy mode coreNodeName missing" -A1 "$R/MC-1.$label.log" | cut -c1-200
}
label=bug run
label=control run "-Dargs=-Dmc1.control=true -XX:TieredStopAtLevel=1"
