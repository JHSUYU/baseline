#!/usr/bin/env bash
set -euo pipefail
case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-22/work
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$case_dir/classes:$case_dir/junit-platform-launcher-1.13.4.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$case_dir/classes:/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.10.1/asm-tree-9.10.1.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.10.1/asm-commons-9.10.1.jar"
if [[ "${1:?stage}" == build ]]; then
  mkdir -p "$case_dir/classes"
  "$javac_bin" -cp "$classpath" -d "$case_dir/classes" "$case_dir/src/HBase22Agent.java" "$case_dir/src/NativeJUnit.java"
  "$javac_bin" -cp "$coverage_cp" -d "$case_dir/classes" "$case_dir/src/CoverageReport.java"
  printf 'Premain-Class: HBase22Agent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$case_dir/manifest.mf"
  jar cfm "$case_dir/agent.jar" "$case_dir/manifest.mf" -C "$case_dir/classes" .
elif [[ "$1" == run ]]; then
  suffix="${2:?suffix}"
  plan="${3:-}"
  data_dir="$case_dir/data-$suffix"
  mkdir -p "$data_dir/tmp"
  export HBASE_HOME="$hbase_dist"
  exec timeout 180s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
    "$java_bin" -Xmx4g \
    -javaagent:"$jacoco_agent=destfile=$case_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.namespace.NamespaceStateManager:org.apache.hadoop.hbase.master.TableNamespaceManager:org.apache.hadoop.hbase.ZKNamespaceManager:org.apache.hadoop.hbase.master.procedure.CreateNamespaceProcedure" \
    -javaagent:"$case_dir/agent.jar" \
    -Dhbase22.fault.plan="$plan" \
    -Djava.io.tmpdir="$data_dir/tmp" \
    -Dtest.build.data.basedirectory="$data_dir" \
    -cp "$classpath" NativeJUnit \
    org.apache.hadoop.hbase.namespace.TestNamespaceAuditor testTableOperations
elif [[ "$1" == coverage ]]; then
  exec "$java_bin" -cp "$coverage_cp" CoverageReport "${2:?comma separated exec files}" \
    "$hbase_dist/lib/hbase-server-2.6.6.jar"
else
  exit 2
fi
