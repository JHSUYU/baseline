#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-10/independent
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$case_dir/classes:$case_dir/junit-platform-launcher-1.13.4.jar:$case_dir/byte-buddy-1.12.16.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$case_dir/classes:$case_dir/org.jacoco.core-0.8.15.jar:$case_dir/asm-9.10.1.jar:$case_dir/asm-tree-9.10.1.jar:$case_dir/asm-commons-9.10.1.jar"
coverage_includes="org.apache.hadoop.hbase.master.assignment.AssignmentManager:org.apache.hadoop.hbase.master.assignment.RegionStateNode:org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure:org.apache.hadoop.hbase.master.MasterRpcServices:org.apache.hadoop.hbase.client.HBaseAdmin:org.apache.hadoop.hbase.client.RpcRetryingCallerImpl:org.apache.hadoop.hbase.client.MasterCallable:org.apache.hadoop.hbase.ipc.AbstractRpcClient"

case "${1:?build, run, or coverage}" in
  build)
    mkdir -p "$case_dir/classes"
    "$javac_bin" -cp "$classpath" -d "$case_dir/classes" \
      "$case_dir/src/HBase10Agent.java" "$case_dir/src/NativeJUnit.java"
    "$javac_bin" -cp "$coverage_cp" -d "$case_dir/classes" \
      "$case_dir/src/CoverageReport.java"
    printf 'Premain-Class: HBase10Agent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$case_dir/manifest.mf"
    jar cfm "$case_dir/agent.jar" "$case_dir/manifest.mf" -C "$case_dir/classes" .
    ;;
  run)
    suffix="${2:?run suffix}"
    plan="${3:-}"
    data_dir="$case_dir/data-$suffix"
    mkdir -p "$data_dir/tmp"
    export HBASE_HOME="$hbase_dist"
    exec timeout 480s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
      "$java_bin" -Xmx5g \
        -javaagent:"$case_dir/org.jacoco.agent-0.8.15-runtime.jar=destfile=$case_dir/$suffix.exec,includes=$coverage_includes" \
        -javaagent:"$case_dir/agent.jar" \
        -Dhbase10.fault.plan="$plan" \
        -Djava.io.tmpdir="$data_dir/tmp" \
        -Dtest.build.data.basedirectory="$data_dir" \
        -cp "$classpath" NativeJUnit \
        org.apache.hadoop.hbase.regionserver.TestRegionMove testDisableAndMove
    ;;
  coverage)
    suffix="${2:?coverage suffix}"
    exec "$java_bin" -cp "$coverage_cp" CoverageReport \
      "$case_dir/$suffix.exec" \
      "$hbase_dist/lib/hbase-server-2.6.6.jar" \
      "$hbase_dist/lib/hbase-client-2.6.6.jar"
    ;;
  *) exit 2 ;;
esac
