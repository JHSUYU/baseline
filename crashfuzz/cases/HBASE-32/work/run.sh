#!/usr/bin/env bash
set -euo pipefail

work_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-32/work
run_root=${HBASE32_RUN_ROOT:-$work_dir}
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
asm_jar=/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$work_dir/classes:$work_dir/junit-platform-launcher-1.13.4.jar:$asm_jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$work_dir/classes:/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar:$asm_jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.6/asm-tree-9.6.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.6/asm-commons-9.6.jar"

case "${1:?build or run}" in
  build)
    mkdir -p "$work_dir/classes" "$work_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$work_dir/classes" "$work_dir/src/HBase32Agent.java" "$work_dir/src/NativeJUnit.java"
    "$javac_bin" -cp "$coverage_cp" -d "$work_dir/classes" "$work_dir/src/CoverageReport.java"
    printf 'Premain-Class: HBase32Agent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$work_dir/manifest.mf"
    jar cfm "$work_dir/agent.jar" "$work_dir/manifest.mf" -C "$work_dir/classes" .
    ;;
  run)
    suffix="${2:?suffix}"
    plan="${3:-}"
    data_dir="$run_root/data-$suffix"
    rm -rf -- "$data_dir"
    mkdir -p "$data_dir/tmp" "$run_root/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout "${HBASE32_RUN_TIMEOUT:-360}s" \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$run_root/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.regionserver.handler.RegionReplicaFlushHandler:org.apache.hadoop.hbase.client.FlushRegionCallable" \
      -javaagent:"$work_dir/agent.jar" \
      -Dhbase32.fault.plan="$plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover "${HBASE32_TEST_METHOD:-testSecondaryRegionKill}"
    ;;
  coverage)
    exec "$java_bin" -cp "$coverage_cp" CoverageReport "${2:?comma separated exec files}" \
      "$hbase_dist/lib/hbase-server-2.6.6.jar" "$hbase_dist/lib/hbase-client-2.6.6.jar"
    ;;
  *) exit 2 ;;
esac
