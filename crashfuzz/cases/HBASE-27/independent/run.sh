#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-27/independent
shared_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-10/independent
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
jacoco_core=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$case_dir/classes:$shared_dir/classes:$shared_dir/junit-platform-launcher-1.13.4.jar:$shared_dir/byte-buddy-1.12.16.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"

case "${1:?build healthy or trial}" in
  build)
    mkdir -p "$case_dir/classes" "$case_dir/logs"
    "$javac_bin" -cp "$classpath" -d "$case_dir/classes" \
      "$case_dir/src/HBase27TargetAgent.java" "$case_dir/src/NativeJUnit27.java"
    "$javac_bin" -cp "$case_dir/classes:$case_dir/../../HBASE-21/work/lib/*:$jacoco_core" \
      -d "$case_dir/classes" "$case_dir/src/CoverageLine27.java"
    printf 'Premain-Class: HBase27TargetAgent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' \
      > "$case_dir/manifest.mf"
    jar cfm "$case_dir/agent.jar" "$case_dir/manifest.mf" -C "$case_dir/classes" .
    ;;
  coverage)
    exec "$java_bin" -cp "$case_dir/classes:$case_dir/../../HBASE-21/work/lib/*:$jacoco_core" \
      CoverageLine27 "${2:?JaCoCo exec}" "$hbase_dist/lib/hbase-server-2.6.6.jar" \
      "$hbase_dist/lib/hbase-zookeeper-2.6.6.jar"
    ;;
  healthy|trial)
    suffix="${2:?run suffix}"
    selector="${3:-}"
    if [[ "$1" == trial && -z "$selector" ]]; then
      echo 'trial requires an exact observed selector' >&2
      exit 2
    fi
    data_dir="$case_dir/data-$suffix"
    mkdir -p "$data_dir/tmp" "$case_dir/logs"
    export HBASE_HOME="$hbase_dist"
    exec /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
      timeout "${HBASE27_TIMEOUT_SECONDS:-360}s" \
      "$java_bin" -ea -Xmx5g \
        -Djava.library.path="$hadoop_dist/lib/native" \
        -javaagent:"$jacoco_agent=destfile=$case_dir/logs/$suffix.exec,append=false,includes=org.apache.hadoop.hbase.regionserver.HRegionServer:org.apache.hadoop.hbase.zookeeper.ZKNodeTracker:org.apache.hadoop.hbase.zookeeper.ZKUtil" \
        -javaagent:"$case_dir/agent.jar" \
        -Dhbase27.fault.selector="$selector" \
        -Djava.io.tmpdir="$data_dir/tmp" \
        -Dtest.build.data.basedirectory="$data_dir" \
        -cp "$classpath" NativeJUnit27 \
        org.apache.hadoop.hbase.TestClusterBootOrder testBootRegionServerFirst
    ;;
  *) exit 2 ;;
esac
