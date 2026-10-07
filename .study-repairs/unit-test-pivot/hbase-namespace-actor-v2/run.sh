#!/usr/bin/env bash
set -euo pipefail
actor_dir=$(cd "$(dirname "$0")" && pwd)
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
launcher_jar=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-08/work/junit-platform-launcher-1.13.4.jar
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$actor_dir/classes:$launcher_jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
case "${1:?build, smoke, or healthy}" in
  build)
    mkdir -p "$actor_dir/classes"
    "$javac_bin" -cp "$classpath" -d "$actor_dir/classes" \
      "$actor_dir/src/NamespaceActorAgent.java" \
      "$actor_dir/src/NamespaceActorSmoke.java" \
      "$actor_dir/src/NativeNamespaceJUnit.java"
    jar cfm "$actor_dir/agent.jar" "$actor_dir/manifest.mf" -C "$actor_dir/classes" .
    ;;
  smoke)
    "$java_bin" -Xmx256m -javaagent:"$actor_dir/agent.jar" \
      -cp "$classpath" NamespaceActorSmoke
    ;;
  healthy)
    test_kind="${2:?table or restore}"
    seed="${3:?unique seed}"
    if [[ ! "$seed" =~ ^[A-Za-z0-9_-]+$ ]]; then
      echo "Seed must contain only letters, digits, _ or -" >&2
      exit 2
    fi
    case "$test_kind" in
      table) test_method=testTableOperations ;;
      restore) test_method=testRestoreSnapshotQuotaExceed ;;
      *) echo "Unknown original JUnit kind: $test_kind" >&2; exit 2 ;;
    esac
    data_dir="$actor_dir/runs/$test_kind-$seed"
    if [[ -e "$data_dir/healthy.log" ]]; then
      echo "Seed already started: $data_dir" >&2
      exit 2
    fi
    mkdir -p "$data_dir/tmp"
    export HBASE_HOME="$hbase_dist"
    if timeout 240s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$data_dir/healthy.exec,append=false,includes=org.apache.hadoop.hbase.master.ClusterSchemaServiceImpl:org.apache.hadoop.hbase.namespace.NamespaceStateManager:org.apache.hadoop.hbase.master.TableNamespaceManager:org.apache.hadoop.hbase.ZKNamespaceManager" \
      -javaagent:"$actor_dir/agent.jar" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeNamespaceJUnit \
      org.apache.hadoop.hbase.namespace.TestNamespaceAuditor "$test_method" \
      > "$data_dir/healthy.log" 2>&1; then
      run_exit=0
    else
      run_exit=$?
    fi
    printf '%s\n' "$run_exit" > "$data_dir/healthy.exit"
    exit "$run_exit"
    ;;
  *)
    echo "Usage: $0 {build|smoke|healthy table|restore unique-seed}" >&2
    exit 2
    ;;
esac
