#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32
base_dir="$case_dir/work"
upstream_dir="$case_dir/work-upstream"
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
asm_jar=/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$upstream_dir/classes:$base_dir/classes:$base_dir/junit-platform-launcher-1.13.4.jar:$asm_jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$upstream_dir/classes:/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar:$asm_jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.6/asm-tree-9.6.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.6/asm-commons-9.6.jar"

case "${1:?build or run}" in
  build)
    bash "$base_dir/run.sh" build
    mkdir -p "$upstream_dir/classes" "$upstream_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$upstream_dir/classes" \
      "$upstream_dir/src/HBase32UpstreamAgent.java"
    "$javac_bin" -cp "$coverage_cp" -d "$upstream_dir/classes" \
      "$upstream_dir/src/UpstreamCoverageReport.java"
    printf 'Premain-Class: HBase32UpstreamAgent\n' > "$upstream_dir/manifest.mf"
    jar cfm "$upstream_dir/agent.jar" "$upstream_dir/manifest.mf" -C "$upstream_dir/classes" .
    ;;
  run)
    suffix="${2:?suffix}"
    base_plan="${3:-}"
    upstream_plan="${4:-}"
    data_dir="$upstream_dir/data-$suffix"
    rm -rf -- "$data_dir"
    mkdir -p "$data_dir/tmp" "$upstream_dir/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout \
      "${HBASE32_UPSTREAM_TIMEOUT:-360}s" \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$upstream_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.regionserver.handler.RegionReplicaFlushHandler:org.apache.hadoop.hbase.client.FlushRegionCallable:org.apache.hadoop.hbase.MetaTableAccessor:org.apache.hadoop.hbase.client.ConnectionImplementation:org.apache.hadoop.hbase.client.ScannerCallable:org.apache.hadoop.hbase.client.ClientServiceCallable:org.apache.hadoop.hbase.regionserver.HRegionServer:org.apache.hadoop.hbase.regionserver.RSRpcServices:org.apache.hadoop.hbase.regionserver.wal.WALUtil" \
      -javaagent:"$base_dir/agent.jar" \
      -javaagent:"$upstream_dir/agent.jar" \
      -Dhbase32.fault.plan="$base_plan" \
      -Dhbase32.upstream.fault.plan="$upstream_plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover testLotsOfRegionReplicas
    ;;
  coverage)
    exec "$java_bin" -cp "$coverage_cp" UpstreamCoverageReport \
      "${2:?comma separated exec files}" \
      "$hbase_dist/lib/hbase-server-2.6.6.jar" "$hbase_dist/lib/hbase-client-2.6.6.jar"
    ;;
  *) exit 2 ;;
esac
