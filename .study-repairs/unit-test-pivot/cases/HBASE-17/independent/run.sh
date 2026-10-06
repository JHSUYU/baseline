#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-17/independent
shared_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-10/independent
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$case_dir/classes:$shared_dir/classes:$shared_dir/junit-platform-launcher-1.13.4.jar:$shared_dir/byte-buddy-1.12.16.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"

case "${1:?build or run}" in
  build)
    mkdir -p "$case_dir/classes"
    "$javac_bin" -cp "$classpath" -d "$case_dir/classes" \
      "$case_dir/src/HBase17TargetAgent.java"
    printf 'Premain-Class: HBase17TargetAgent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$case_dir/manifest.mf"
    jar cfm "$case_dir/agent.jar" "$case_dir/manifest.mf" -C "$case_dir/classes" .
    ;;
  run)
    suffix="${2:?run suffix}"
    test_class="${3:-org.apache.hadoop.hbase.master.assignment.TestRaceBetweenSCPAndTRSP}"
    test_method="${4:-test}"
    data_dir="$case_dir/data-$suffix"
    mkdir -p "$data_dir/tmp"
    export HBASE_HOME="$hbase_dist"
    exec timeout 360s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
      "$java_bin" -ea -Xmx5g \
        -javaagent:"$case_dir/agent.jar" \
        -Djava.io.tmpdir="$data_dir/tmp" \
        -Dtest.build.data.basedirectory="$data_dir" \
        -cp "$classpath" NativeJUnit "$test_class" "$test_method"
    ;;
  *) exit 2 ;;
esac
