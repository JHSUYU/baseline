#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-32
base_dir="$case_dir/work"
upstream_dir="$case_dir/work-upstream"
diag_dir="$upstream_dir/diag-s203"
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
asm_jar=/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$diag_dir/classes:$upstream_dir/classes:$base_dir/classes:$base_dir/junit-platform-launcher-1.13.4.jar:$asm_jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"

case "${1:?build or run}" in
  build)
    mkdir -p "$diag_dir/classes" "$diag_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$diag_dir/classes" \
      "$diag_dir/HBase32LockDiagAgent.java"
    printf 'Premain-Class: HBase32LockDiagAgent\n' > "$diag_dir/manifest.mf"
    jar cfm "$diag_dir/agent.jar" "$diag_dir/manifest.mf" -C "$diag_dir/classes" .
    ;;
  run)
    suffix="${2:?suffix}"
    base_plan="${3-}"
    upstream_plan="${4-}"
    data_dir="$diag_dir/data-$suffix"
    if [[ -e "$data_dir" || -e "$diag_dir/logs/$suffix.exec" ]]; then
      echo "Diagnostic output exists; refusing overwrite" >&2
      exit 2
    fi
    mkdir -p "$data_dir/tmp" "$diag_dir/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout \
      "${HBASE32_DIAG_TIMEOUT:-600}s" \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$diag_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.regionserver.handler.RegionReplicaFlushHandler:org.apache.hadoop.hbase.client.FlushRegionCallable:org.apache.hadoop.hbase.MetaTableAccessor:org.apache.hadoop.hbase.client.ConnectionImplementation:org.apache.hadoop.hbase.client.ScannerCallable:org.apache.hadoop.hbase.client.ClientServiceCallable:org.apache.hadoop.hbase.regionserver.HRegionServer:org.apache.hadoop.hbase.regionserver.RSRpcServices:org.apache.hadoop.hbase.regionserver.wal.WALUtil" \
      -javaagent:"$base_dir/agent.jar" \
      -javaagent:"$upstream_dir/agent.jar" \
      -javaagent:"$diag_dir/agent.jar" \
      -Dhbase32.fault.plan="$base_plan" \
      -Dhbase32.upstream.fault.plan="$upstream_plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover testLotsOfRegionReplicas
    ;;
  *) exit 2 ;;
esac
