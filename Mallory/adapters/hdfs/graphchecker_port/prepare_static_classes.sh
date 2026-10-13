#!/usr/bin/env bash
# Give the static planner the same HDFS/client/IPC bytes the JUnit loads.
set -euo pipefail
if [[ $# -ne 3 ]]; then
  echo 'usage: prepare_static_classes.sh <hadoop-3.4.3-checkout> <adapter-overlay> <new-merged-classes-directory>' >&2
  exit 2
fi
hadoop_dir=$(realpath "$1")
overlay=$(realpath "$2")
output=$3
source_classes=$hadoop_dir/hadoop-hdfs-project/hadoop-hdfs/target/classes
client_classes=$hadoop_dir/hadoop-hdfs-project/hadoop-hdfs-client/target/classes
common_classes=$hadoop_dir/hadoop-common-project/hadoop-common/target/classes
legacy_include_common=${MALLORY_HDFS_INCLUDE_COMMON_CLASSES:-1}
[[ $legacy_include_common == 0 || $legacy_include_common == 1 ]] || {
  echo 'MALLORY_HDFS_INCLUDE_COMMON_CLASSES must be 0 or 1' >&2; exit 2;
}
common_scope=${MALLORY_HDFS_COMMON_SCOPE:-}
if [[ -z $common_scope ]]; then
  if [[ $legacy_include_common == 1 ]]; then common_scope=all; else common_scope=none; fi
fi
case $common_scope in
  all|ipc|none) ;;
  *) echo 'MALLORY_HDFS_COMMON_SCOPE must be all, ipc, or none' >&2; exit 2 ;;
esac
for classes in "$source_classes" "$client_classes"; do
  [[ -d $classes ]] || { echo "missing Hadoop classes: $classes" >&2; exit 2; }
done
if [[ $common_scope != none ]]; then
  [[ -d $common_classes ]] || { echo "missing Hadoop common classes: $common_classes" >&2; exit 2; }
fi
[[ ! -e $output ]] || { echo "refusing to replace $output" >&2; exit 2; }
patched_classes=(
  org/apache/hadoop/hdfs/server/datanode/DataNode.class
  org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class
  org/apache/hadoop/hdfs/tools/DFSAdmin.class
)
if [[ $common_scope != none ]]; then
  patched_classes+=(
    org/apache/hadoop/ipc/Client.class
    'org/apache/hadoop/ipc/Client$Connection.class'
    'org/apache/hadoop/ipc/Client$Connection$RpcRequestSender.class'
    'org/apache/hadoop/ipc/Server$RpcCall.class'
    'org/apache/hadoop/ipc/Server$Connection.class'
  )
fi
for rel in "${patched_classes[@]}"; do
  [[ -s $overlay/$rel ]] || { echo "missing patched class: $overlay/$rel" >&2; exit 2; }
done
cp -a "$source_classes" "$output"
cp -a "$client_classes/." "$output/"
if [[ $common_scope == all ]]; then
  cp -a "$common_classes/." "$output/"
elif [[ $common_scope == ipc ]]; then
  mkdir -p "$output/org/apache/hadoop"
  cp -a "$common_classes/org/apache/hadoop/ipc" "$output/org/apache/hadoop/"
fi
for rel in "${patched_classes[@]}"; do
  [[ -s $output/$rel ]] || { echo "patched class absent from merged Hadoop modules: $rel" >&2; exit 2; }
  cp "$overlay/$rel" "$output/$rel"
done
{
  case $common_scope in
    all) echo 'HDFS main, HDFS client, and all Hadoop common classes with Mallory GraphChecker adapter bytes' ;;
    ipc) echo 'HDFS main, HDFS client, and all Hadoop common org.apache.hadoop.ipc classes; other common classes remain dependencies' ;;
    none) echo 'HDFS main and HDFS client application classes; Hadoop common remains a classpath dependency and IPC runtime overlay' ;;
  esac
  (cd "$output" && sha256sum "${patched_classes[@]}")
} > "$output/MALLORY_HDFS_STATIC_INPUT_MANIFEST.sha256"
(cd "$output" && find . -type f -name '*.class' -print0 | LC_ALL=C sort -z |
  xargs -0 sha256sum) > "$output/MALLORY_HDFS_CLASS_BYTES.sha256"
echo "prepared $output"
