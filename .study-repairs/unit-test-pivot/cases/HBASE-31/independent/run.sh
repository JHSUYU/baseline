#!/usr/bin/env bash
set -euo pipefail
case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-31/independent
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
classpath="$case_dir/classes:$case_dir/junit-platform-launcher-1.13.4.jar:$case_dir/byte-buddy-1.12.16.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
case "${1:?build, healthy, or regression}" in
  build)
    mkdir -p "$case_dir/classes"
    /usr/lib/jvm/java-8-openjdk-amd64/bin/javac -cp "$classpath" -d "$case_dir/classes" \
      "$case_dir/src/HBase31Probe.java" "$case_dir/src/NativeJUnit.java"
    printf 'Premain-Class: HBase31Probe\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$case_dir/manifest.mf"
    jar cfm "$case_dir/agent.jar" "$case_dir/manifest.mf" -C "$case_dir/classes" .
    ;;
  healthy|regression)
    suffix="$1"
    test_class=org.apache.hadoop.hbase.regionserver.TestRegionMove
    test_method=testDisableAndMove
    if [[ "$suffix" == regression ]]; then
      test_class=org.apache.hadoop.hbase.regionserver.TestRegionServerNoMaster
      test_method=testOpenCloseRegionRPCIntendedForPreviousServer
    fi
    data_dir="$case_dir/data-$suffix"
    mkdir -p "$data_dir/tmp"
    export HBASE_HOME="$hbase_dist"
    exec timeout 480s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
      /usr/lib/jvm/java-8-openjdk-amd64/bin/java -Xmx5g \
        -javaagent:"$case_dir/org.jacoco.agent-0.8.15-runtime.jar=destfile=$case_dir/$suffix.exec,includes=org.apache.hadoop.hbase.regionserver.RSRpcServices" \
        -javaagent:"$case_dir/agent.jar" \
        -Djava.io.tmpdir="$data_dir/tmp" \
        -Dtest.build.data.basedirectory="$data_dir" \
        -cp "$classpath" NativeJUnit \
        "$test_class" "$test_method"
    ;;
  *) exit 2 ;;
esac
