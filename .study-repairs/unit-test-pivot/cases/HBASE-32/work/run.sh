#!/usr/bin/env bash
set -euo pipefail

work_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/work
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
asm_jar=/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$work_dir/classes:$work_dir/junit-platform-launcher-1.13.4.jar:$asm_jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"

case "${1:?build or run}" in
  build)
    mkdir -p "$work_dir/classes" "$work_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$work_dir/classes" "$work_dir/src/HBase32Agent.java" "$work_dir/src/NativeJUnit.java"
    printf 'Premain-Class: HBase32Agent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$work_dir/manifest.mf"
    jar cfm "$work_dir/agent.jar" "$work_dir/manifest.mf" -C "$work_dir/classes" .
    ;;
  run)
    suffix="${2:?suffix}"
    plan="${3:-}"
    data_dir="$work_dir/data-$suffix"
    mkdir -p "$data_dir/tmp" "$work_dir/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout 360s \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$work_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.regionserver.handler.RegionReplicaFlushHandler:org.apache.hadoop.hbase.client.FlushRegionCallable" \
      -javaagent:"$work_dir/agent.jar" \
      -Dhbase32.fault.plan="$plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover testSecondaryRegionKill
    ;;
  *) exit 2 ;;
esac
