#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-32
role_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
base_dir="$case_dir/work"
upstream_dir="$case_dir/work-upstream"
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
asm_jar=/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$role_dir/classes:$base_dir/classes:$base_dir/junit-platform-launcher-1.13.4.jar:$asm_jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"

case "${1:?build or run}" in
  build)
    mkdir -p "$role_dir/classes" "$role_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$role_dir/classes" \
      "$role_dir/src/HBase32RoleBaseAgent.java" \
      "$role_dir/src/HBase32RoleUpstreamAgent.java" \
      "$role_dir/src/RoleSelectorSmoke.java"
    printf 'Premain-Class: HBase32RoleBaseAgent\n' > "$role_dir/manifest-base.mf"
    printf 'Premain-Class: HBase32RoleUpstreamAgent\n' > "$role_dir/manifest-upstream.mf"
    jar cfm "$role_dir/base-agent.jar" "$role_dir/manifest-base.mf" \
      -C "$role_dir/classes" .
    jar cfm "$role_dir/upstream-agent.jar" "$role_dir/manifest-upstream.mf" \
      -C "$role_dir/classes" .
    ;;
  smoke)
    exec timeout 15s "$java_bin" -Xmx256m -cp "$classpath" RoleSelectorSmoke
    ;;
  run)
    suffix="${2:?suffix}"
    base_plan="${3-}"
    upstream_plan="${4-}"
    if [[ "$suffix" == healthy-* ]]; then
      [[ -z "$base_plan" && -z "$upstream_plan" ]] || {
        echo "Healthy calibration requires empty fault plans" >&2; exit 2;
      }
    else
      [[ -n "$base_plan" && -n "$upstream_plan" ]] || {
        echo "Fault trial requires both role-bound plans" >&2; exit 2;
      }
    fi
    data_dir="$role_dir/data-$suffix"
    [[ ! -e "$data_dir" && ! -e "$role_dir/logs/$suffix.exec" ]] || {
      echo "Role run output exists; refusing overwrite" >&2; exit 2;
    }
    free_bytes=$(df -B1 --output=avail "$role_dir" | tail -1)
    (( free_bytes >= 3221225472 )) || {
      echo "Role run requires 3 GiB free; available=$free_bytes" >&2; exit 2;
    }
    mkdir -p "$data_dir/tmp" "$role_dir/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout \
      "${HBASE32_ROLE_TIMEOUT:-600}s" \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$role_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.regionserver.handler.RegionReplicaFlushHandler:org.apache.hadoop.hbase.client.FlushRegionCallable:org.apache.hadoop.hbase.MetaTableAccessor:org.apache.hadoop.hbase.client.ConnectionImplementation:org.apache.hadoop.hbase.client.ScannerCallable:org.apache.hadoop.hbase.client.ClientServiceCallable:org.apache.hadoop.hbase.regionserver.HRegionServer:org.apache.hadoop.hbase.regionserver.RSRpcServices:org.apache.hadoop.hbase.regionserver.wal.WALUtil" \
      -javaagent:"$role_dir/base-agent.jar" \
      -javaagent:"$role_dir/upstream-agent.jar" \
      -javaagent:"$upstream_dir/diag-s203/agent.jar" \
      -Dhbase32.fault.plan="$base_plan" \
      -Dhbase32.upstream.fault.plan="$upstream_plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover testLotsOfRegionReplicas
    ;;
  *) exit 2 ;;
esac
