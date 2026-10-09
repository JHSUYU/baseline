#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-04/graphfree-validation
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
byte_buddy="$case_dir/byte-buddy-1.12.16.jar"
jacoco_agent="$case_dir/org.jacoco.agent-0.8.15-runtime.jar"
junit_launcher="$case_dir/junit-platform-launcher-1.13.4.jar"
classpath="$case_dir/classes:$junit_launcher:$byte_buddy:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$case_dir/classes:$case_dir/org.jacoco.core-0.8.15.jar:$case_dir/asm-9.10.1.jar:$case_dir/asm-tree-9.10.1.jar:$case_dir/asm-commons-9.10.1.jar"
campaign_coverage_includes="org.apache.hadoop.hbase.client.HBaseAdmin:org.apache.hadoop.hbase.MetaTableAccessor:org.apache.hadoop.hbase.ipc.AbstractRpcClient:org.apache.hadoop.hbase.client.RpcRetryingCallerImpl:org.apache.hadoop.hbase.client.ConnectionImplementation:org.apache.hadoop.hbase.client.ClientServiceCallable:org.apache.hadoop.hbase.client.MasterCallable"

if [[ "${1:?build or run}" == build ]]; then
  mkdir -p "$case_dir/classes"
  "$javac_bin" -cp "$classpath" -d "$case_dir/classes" \
    "$case_dir/src/HBase04Agent.java" "$case_dir/src/NativeJUnit.java"
  "$javac_bin" -cp "$coverage_cp" -d "$case_dir/classes" \
    "$case_dir/src/CoverageReport.java"
  printf 'Premain-Class: HBase04Agent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$case_dir/manifest.mf"
  jar cfm "$case_dir/agent.jar" "$case_dir/manifest.mf" -C "$case_dir/classes" .
elif [[ "$1" == build-campaign ]]; then
  mkdir -p "$case_dir/classes"
  "$javac_bin" -cp "$classpath" -d "$case_dir/classes" \
    "$case_dir/src/HBase04CampaignAgent.java" "$case_dir/src/NativeJUnit.java"
  "$javac_bin" -cp "$coverage_cp" -d "$case_dir/classes" \
    "$case_dir/src/CoverageReport.java"
  printf 'Premain-Class: HBase04CampaignAgent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$case_dir/campaign-manifest.mf"
  jar cfm "$case_dir/campaign-agent.jar" "$case_dir/campaign-manifest.mf" -C "$case_dir/classes" .
elif [[ "$1" == run ]]; then
  suffix="${2:?run suffix}"
  flush="${3:--1}"
  hit="${4:--1}"
  kind="${5:-}"
  plan="${6:-}"
  data_dir="$case_dir/data-$suffix"
  mkdir -p "$data_dir/tmp"
  export HBASE_HOME="$hbase_dist"
  exec timeout 300s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
    "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$case_dir/$suffix.exec,includes=org.apache.hadoop.hbase.client.HBaseAdmin:org.apache.hadoop.hbase.MetaTableAccessor:org.apache.hadoop.hbase.ipc.AbstractRpcClient" \
      -javaagent:"$case_dir/agent.jar" \
      -Dhbase04.fault.flush="$flush" -Dhbase04.fault.hit="$hit" \
      -Dhbase04.fault.kind="$kind" \
      -Dhbase04.fault.plan="$plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.mob.TestMobStoreScanner testMobStoreScanner
elif [[ "$1" == coverage ]]; then
  suffix="${2:?coverage suffix}"
  exec "$java_bin" -cp "$coverage_cp" CoverageReport \
    "$case_dir/$suffix.exec" "$hbase_dist/lib/hbase-client-2.6.6.jar"
elif [[ "$1" == run-campaign ]]; then
  suffix="${2:?run suffix}"
  plan="${3:-}"
  data_dir="$case_dir/data-campaign-$suffix"
  mkdir -p "$data_dir/tmp"
  export HBASE_HOME="$hbase_dist"
  exec timeout 300s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
    "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$case_dir/$suffix.exec,includes=$campaign_coverage_includes" \
      -javaagent:"$case_dir/campaign-agent.jar" \
      -Dhbase04.campaign.plan="$plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.mob.TestMobStoreScanner testMobStoreScanner
else
  exit 2
fi
