#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-21/work
manifest_dir="$case_dir/manifest"
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$case_dir/classes:$manifest_dir/classes:$case_dir/junit-platform-launcher-1.13.4.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"

case "${1:?build or run}" in
  build)
    mkdir -p "$manifest_dir/classes" "$manifest_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$manifest_dir/classes" \
      "$manifest_dir/src/HBase21ManifestAgent.java"
    printf 'Premain-Class: HBase21ManifestAgent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$manifest_dir/manifest.mf"
    jar cfm "$manifest_dir/agent.jar" "$manifest_dir/manifest.mf" -C "$manifest_dir/classes" .
    ;;
  run)
    suffix="${2:?suffix}"
    plan="${3:-}"
    data_dir="$manifest_dir/data-$suffix"
    mkdir -p "$data_dir/tmp" "$manifest_dir/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout 240s \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$manifest_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.namespace.NamespaceStateManager:org.apache.hadoop.hbase.namespace.NamespaceTableAndRegionInfo:org.apache.hadoop.hbase.master.TableNamespaceManager:org.apache.hadoop.hbase.ZKNamespaceManager:org.apache.hadoop.hbase.master.procedure.RestoreSnapshotProcedure:org.apache.hadoop.hbase.master.snapshot.SnapshotManager" \
      -javaagent:"$case_dir/agent.jar" \
      -javaagent:"$manifest_dir/agent.jar" \
      -Dhbase21.manifest.fault.plan="$plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeJUnit \
      org.apache.hadoop.hbase.namespace.TestNamespaceAuditor testRestoreSnapshotQuotaExceed
    ;;
  *) exit 2 ;;
esac
