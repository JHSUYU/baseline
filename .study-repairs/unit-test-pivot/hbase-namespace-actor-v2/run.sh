#!/usr/bin/env bash
set -euo pipefail
actor_dir=$(cd "$(dirname "$0")" && pwd)
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
launcher_jar="$actor_dir/junit-platform-launcher-1.13.4.jar"
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$actor_dir/classes:$launcher_jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$actor_dir/classes:/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.10.1/asm-tree-9.10.1.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.10.1/asm-commons-9.10.1.jar"
case "${1:?build, smoke, healthy, trial, or coverage}" in
  build)
    mkdir -p "$actor_dir/classes"
    "$javac_bin" -cp "$classpath" -d "$actor_dir/classes" \
      "$actor_dir/src/NamespaceActorAgent.java" \
      "$actor_dir/src/NamespaceActorSmoke.java" \
      "$actor_dir/src/NativeNamespaceJUnit.java"
    "$javac_bin" -cp "$coverage_cp" -d "$actor_dir/classes" \
      "$actor_dir/src/CoverageNamespace.java"
    jar cfm "$actor_dir/agent.jar" "$actor_dir/manifest.mf" -C "$actor_dir/classes" .
    ;;
  smoke)
    "$java_bin" -Xmx256m -javaagent:"$actor_dir/agent.jar" \
      -cp "$classpath" NamespaceActorSmoke
    ;;
  healthy|trial)
    mode="$1"
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
    if [[ "$mode" == trial ]]; then
      plan="${4:?ordered fault plan}"
      if ! grep -Eq '^[A-Za-z0-9_~;:=.-]+$' <<< "$plan"; then
        echo "Invalid fault plan characters" >&2
        exit 2
      fi
      data_dir="$actor_dir/runs/$test_kind-$seed"
      stem=trial
    else
      plan=""
      data_dir="$actor_dir/runs/$test_kind-$seed"
      stem=healthy
    fi
    mkdir -p "$actor_dir/runs"
    if ! mkdir "$data_dir"; then
      echo "Run directory already exists: $data_dir" >&2
      exit 2
    fi
    mkdir "$data_dir/tmp"
    printf '%s\n' "$plan" > "$data_dir/$stem.plan"
    sha256sum "$actor_dir/agent.jar" > "$data_dir/agent.sha256"
    export HBASE_HOME="$hbase_dist"
    if python3 "$actor_dir/jvm_gate.py" "$data_dir/$stem.log" \
      /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' timeout 240s \
      "$java_bin" -Xmx4g \
      -javaagent:"$jacoco_agent=destfile=$data_dir/$stem.exec,append=false,includes=org.apache.hadoop.hbase.master.ClusterSchemaServiceImpl:org.apache.hadoop.hbase.namespace.NamespaceStateManager:org.apache.hadoop.hbase.master.TableNamespaceManager:org.apache.hadoop.hbase.ZKNamespaceManager" \
      -javaagent:"$actor_dir/agent.jar" \
      -Dns.actor.fault.plan="$plan" \
      -Djava.io.tmpdir="$data_dir/tmp" \
      -Dtest.build.data.basedirectory="$data_dir" \
      -cp "$classpath" NativeNamespaceJUnit \
      org.apache.hadoop.hbase.namespace.TestNamespaceAuditor "$test_method"; then
      run_exit=0
    else
      run_exit=$?
    fi
    printf '%s\n' "$run_exit" > "$data_dir/$stem.exit.tmp"
    mv "$data_dir/$stem.exit.tmp" "$data_dir/$stem.exit"
    exit "$run_exit"
    ;;
  coverage)
    "$java_bin" -cp "$coverage_cp" CoverageNamespace "${2:?comma-separated exec files}" \
      "$hbase_dist/lib/hbase-server-2.6.6.jar"
    ;;
  *)
    echo "Usage: $0 {build|smoke|healthy table|restore seed|trial table|restore id plan|coverage execs}" >&2
    exit 2
    ;;
esac
