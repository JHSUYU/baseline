#!/usr/bin/env bash
set -euo pipefail

# Run in an isolated Hadoop 3.4.3 worktree. One invocation owns one trial directory.
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
baseline=$(cd "$here/../../../../.." && pwd)
source_root=${MALLORY_HDFS_SOURCE_ROOT:-/users/ZhenyuLi/.mallory-worktrees/hdfs}
trial_dir=${1:?usage: run_healthy.sh ABSOLUTE_TRIAL_DIR}
mkdir -p "$trial_dir"
trial_dir=$(cd "$trial_dir" && pwd)

agent="$baseline/Mallory/instrumentation/target/mallory-agent.jar"
adapter="$baseline/Mallory/adapters/hdfs/target/mallory-hdfs-adapter.jar"
test -f "$agent"
test -f "$adapter"
test -f "$source_root/pom.xml"

cat > "$trial_dir/agent.properties" <<EOF
run.id=HDFS-01-healthy
events=$trial_dir/events.jsonl
site.catalog=$trial_dir/sites.jsonl
site.file=$here/sites.json
include=org.apache.hadoop.hdfs.DFSInputStream,org.apache.hadoop.ipc.Server\$RpcCall,org.apache.hadoop.hdfs.server.namenode.NameNodeRpcServer
adapter.jar=$adapter
adapter.transformer=edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer
auto.io.doors=false
coverage.methods=true
coverage.branches=true
state.fields=false
state.maps=false
EOF

sha256sum "$agent" "$adapter" "$here/sites.json" > "$trial_dir/input-sha256.txt"
(
  cd "$source_root"
  mvn -B -ntp -pl hadoop-hdfs-project/hadoop-hdfs -am \
    '-Dtest=TestPread#testPreadDFS' \
    '-Dsurefire.failIfNoSpecifiedTests=false' \
    "-Dmaven-surefire-plugin.argLine=-javaagent:$agent=config=$trial_dir/agent.properties" \
    '-Dcheckstyle.skip=true' '-Dspotbugs.skip=true' '-Dfindbugs.skip=true' \
    '-Dmaven.javadoc.skip=true' test
) > "$trial_dir/maven.log" 2>&1
