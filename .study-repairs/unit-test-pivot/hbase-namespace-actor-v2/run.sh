#!/usr/bin/env bash
set -euo pipefail
actor_dir=$(cd "$(dirname "$0")" && pwd)
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$actor_dir/classes:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/lib/*"
case "${1:?build or smoke}" in
  build)
    mkdir -p "$actor_dir/classes"
    "$javac_bin" -cp "$classpath" -d "$actor_dir/classes" \
      "$actor_dir/src/NamespaceActorAgent.java" \
      "$actor_dir/src/NamespaceActorSmoke.java"
    jar cfm "$actor_dir/agent.jar" "$actor_dir/manifest.mf" -C "$actor_dir/classes" .
    ;;
  smoke)
    "$java_bin" -Xmx256m -javaagent:"$actor_dir/agent.jar" \
      -cp "$classpath" NamespaceActorSmoke
    ;;
  *)
    echo "Usage: $0 {build|smoke}" >&2
    exit 2
    ;;
esac
