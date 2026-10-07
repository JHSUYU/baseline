#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-17/independent
shared_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-10/independent
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
jacoco_core=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$case_dir/classes:$shared_dir/classes:$shared_dir/junit-platform-launcher-1.13.4.jar:$shared_dir/byte-buddy-1.12.16.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$case_dir/classes:$case_dir/../../HBASE-21/work/lib/*:$jacoco_core"

case "${1:?build run or coverage}" in
  build)
    mkdir -p "$case_dir/classes" "$case_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$case_dir/classes" \
      "$case_dir/src/HBase17FuzzAgent.java" "$case_dir/src/NativeJUnit17.java"
    "$javac_bin" -cp "$coverage_cp" -d "$case_dir/classes" \
      "$case_dir/src/CoverageReport17.java"
    printf 'Premain-Class: HBase17FuzzAgent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' \
      > "$case_dir/fuzz_manifest.mf"
    jar cfm "$case_dir/fuzz_agent.jar" "$case_dir/fuzz_manifest.mf" -C "$case_dir/classes" .
    ;;
  run)
    suffix="${2:?suffix}"
    plan="${3:-}"
    data_dir="$case_dir/fuzz-data-$suffix"
    mkdir -p "$data_dir/tmp" "$case_dir/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout 360s \
      "$java_bin" -ea -Xmx5g \
        -Djava.library.path="$hadoop_dist/lib/native" \
        -javaagent:"$jacoco_agent=destfile=$case_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure:org.apache.hadoop.hbase.master.assignment.RegionStateNode:org.apache.hadoop.hbase.master.assignment.AssignmentManager:org.apache.hadoop.hbase.master.assignment.RegionStateStore:org.apache.hadoop.hbase.master.assignment.RegionRemoteProcedureBase:org.apache.hadoop.hbase.master.procedure.RSProcedureDispatcher:org.apache.hadoop.hbase.master.procedure.ServerCrashProcedure:org.apache.hadoop.hbase.ipc.AbstractRpcClient" \
        -javaagent:"$case_dir/fuzz_agent.jar" \
        -Dhbase17.fault.plan="$plan" \
        -Djava.io.tmpdir="$data_dir/tmp" \
        -Dtest.build.data.basedirectory="$data_dir" \
        -cp "$classpath" NativeJUnit17 \
        org.apache.hadoop.hbase.util.TestProcDispatcher testRetryLimitOnConnClosedErrors
    ;;
  coverage)
    exec "$java_bin" -cp "$coverage_cp" CoverageReport17 "${2:?comma-separated exec files}" \
      "$hbase_dist/lib/hbase-server-2.6.6.jar" \
      "$hbase_dist/lib/hbase-client-2.6.6.jar" \
      "$hbase_dist/lib/hbase-procedure-2.6.6.jar"
    ;;
  *) exit 2 ;;
esac
