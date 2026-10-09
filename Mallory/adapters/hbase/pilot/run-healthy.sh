#!/usr/bin/env bash
set -euo pipefail

stage_dir=${1:?isolated staging directory required}
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$stage_dir/classes:$stage_dir/adapter.jar:$stage_dir/junit-platform-launcher.jar:$hbase_dist/conf:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"

mkdir -p "$stage_dir/classes" "$stage_dir/trial/tmp"
"$javac_bin" -cp "$classpath" -d "$stage_dir/classes" "$stage_dir/SelectedJUnit.java"
export HBASE_HOME="$hbase_dist"
cat > "$stage_dir/agent.properties" <<EOF
run.id=HBASE-01-healthy
events=$stage_dir/trial/events.jsonl
site.catalog=$stage_dir/trial/sites.jsonl
site.file=$stage_dir/hbase01-sites.json
include=org.apache.hadoop.hbase.client.ConnectionImplementation,org.apache.hadoop.hbase.ipc.RpcServer
adapter.transformer=edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer
auto.io.doors=false
coverage.methods=true
coverage.branches=true
state.fields=false
state.maps=false
EOF
timeout 300s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
  "$java_bin" -Xmx4g \
  -javaagent:"$stage_dir/agent.jar=config=$stage_dir/agent.properties" \
  -Djava.io.tmpdir="$stage_dir/trial/tmp" \
  -Dtest.build.data.basedirectory="$stage_dir/trial" \
  -cp "$classpath" edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit \
  org.apache.hadoop.hbase.client.TestConnectionImplementation testMetaLookupThreadPoolCreated \
  > "$stage_dir/trial/stdout.log" 2> "$stage_dir/trial/stderr.log"
