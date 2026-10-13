#!/usr/bin/env bash
# install.sh <mallory-graph-runtime.jar> <hadoop-common.jar> <hadoop-hdfs.jar>
#            <hadoop-hdfs-tests.jar> <new-overlay-directory>
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo 'usage: install.sh <graph-runtime.jar> <hadoop-common.jar> <hadoop-hdfs.jar> <hadoop-hdfs-tests.jar> <new-overlay-directory>' >&2
  exit 2
fi
port_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runtime_jar=$(realpath "$1")
common_jar=$(realpath "$2")
hdfs_jar=$(realpath "$3")
hdfs_tests_jar=$(realpath "$4")
output_dir=$5
if [[ -e $output_dir ]]; then
  echo "refusing to replace existing overlay: $output_dir" >&2
  exit 2
fi
for archive in "$runtime_jar" "$common_jar" "$hdfs_jar" "$hdfs_tests_jar"; do
  [[ -f $archive ]] || { echo "missing jar: $archive" >&2; exit 2; }
done

java_home=${JAVA_HOME:-/usr/lib/jvm/java-8-openjdk-amd64}
javassist_jar=${JAVASSIST_JAR:-$HOME/.m2/repository/org/javassist/javassist/3.25.0-GA/javassist-3.25.0-GA.jar}
asm_jar=${ASM_JAR:-$HOME/.m2/repository/org/ow2/asm/asm/9.8/asm-9.8.jar}
commons_lang_jar=${COMMONS_LANG_JAR:-$HOME/.m2/repository/org/apache/commons/commons-lang3/3.9/commons-lang3-3.9.jar}
hadoop_protobuf_jar=${HADOOP_PROTOBUF_JAR:-$HOME/.m2/repository/org/apache/hadoop/thirdparty/hadoop-shaded-protobuf_3_25/1.5.0/hadoop-shaded-protobuf_3_25-1.5.0.jar}
hadoop_guava_jar=${HADOOP_GUAVA_JAR:-$HOME/.m2/repository/org/apache/hadoop/thirdparty/hadoop-shaded-guava/1.5.0/hadoop-shaded-guava-1.5.0.jar}
junit_jar=${JUNIT_JAR:-$HOME/.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar}
for archive in "$javassist_jar" "$asm_jar" "$commons_lang_jar" "$hadoop_protobuf_jar" "$hadoop_guava_jar" "$junit_jar"; do
  [[ -f $archive ]] || { echo "missing build dependency: $archive" >&2; exit 2; }
done

parent_dir=$(dirname "$output_dir")
mkdir -p "$parent_dir"
stage_dir=$(mktemp -d "$parent_dir/.hdfs-graph-port.XXXXXXXX")
cleanup() { rm -rf -- "$stage_dir"; }
trap cleanup EXIT
classes_dir=$stage_dir/classes
tools_dir=$stage_dir/tools
mkdir -p "$classes_dir" "$tools_dir"

source_paths=(
  "$port_dir/src/main/java/org/apache/hadoop/ipc/MalloryEmbeddedIpcBridge.java"
  "$port_dir/src/main/java/edu/uva/liftlab/mallory/adapters/hdfs/graphchecker/PatchEmbeddedIpc.java"
  "$port_dir/src/main/java/edu/uva/liftlab/mallory/adapters/hdfs/graphchecker/Reframe.java"
  "$port_dir/src/main/java/edu/uva/liftlab/mallory/adapters/hdfs/graphchecker/RunOriginalJUnit.java"
)
compile_cp="$runtime_jar:$common_jar:$hdfs_jar:$hdfs_tests_jar:$javassist_jar:$asm_jar:$commons_lang_jar:$hadoop_protobuf_jar:$hadoop_guava_jar:$junit_jar"
"$java_home/bin/javac" -source 8 -target 8 -cp "$compile_cp" -d "$tools_dir" "${source_paths[@]}"
cp -a "$tools_dir/org" "$classes_dir/"
mkdir -p "$classes_dir/edu/uva/liftlab/mallory/adapters/hdfs/graphchecker"
cp "$tools_dir/edu/uva/liftlab/mallory/adapters/hdfs/graphchecker/RunOriginalJUnit.class" \
  "$classes_dir/edu/uva/liftlab/mallory/adapters/hdfs/graphchecker/"

patch_cp="$tools_dir:$compile_cp"
"$java_home/bin/java" -cp "$patch_cp" \
  edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.PatchEmbeddedIpc \
  "$classes_dir" "$common_jar" "$hdfs_jar" "$hdfs_tests_jar"

for class_file in \
  'org/apache/hadoop/hdfs/MiniDFSCluster.class' \
  'org/apache/hadoop/hdfs/qjournal/MiniJournalCluster.class' \
  'org/apache/hadoop/hdfs/qjournal/MiniJournalCluster$Builder.class' \
  'org/apache/hadoop/hdfs/qjournal/client/IPCLoggerChannel.class' \
  'org/apache/hadoop/hdfs/server/datanode/DataNode.class' \
  'org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class' \
  'org/apache/hadoop/hdfs/tools/DFSAdmin.class' \
  'org/apache/hadoop/ipc/Client.class' \
  'org/apache/hadoop/ipc/Client$Connection.class' \
  'org/apache/hadoop/ipc/Client$Connection$RpcRequestSender.class' \
  'org/apache/hadoop/ipc/Server$RpcCall.class' \
  'org/apache/hadoop/ipc/Server$Connection.class'; do
  [[ -s $classes_dir/$class_file ]] || {
    echo "patcher did not produce $class_file" >&2; exit 1;
  }
  # ASM's generic common-superclass fallback can broaden unrelated Hadoop
  # constructor frames to Object. Javassist already rebuilt stack maps for
  # these two HDFS classes; retain those maps instead of reframing every
  # untouched method in the large classes.
  if [[ $class_file == 'org/apache/hadoop/hdfs/server/datanode/DataNode.class' \
      || $class_file == 'org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class' ]]; then
    continue
  fi
  "$java_home/bin/java" -cp "$patch_cp" \
    edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.Reframe \
    "$classes_dir/$class_file"
done

{
  echo 'Mallory HDFS GraphChecker IPC overlay v1'
  echo 'Generic MiniDFSCluster and MiniJournalCluster source and Hadoop IPC hooks'
  sha256sum "$runtime_jar" "$common_jar" "$hdfs_jar" "$hdfs_tests_jar" \
    "$javassist_jar" "$asm_jar" "$commons_lang_jar" "$hadoop_protobuf_jar" "$hadoop_guava_jar" "$junit_jar"
  (cd "$classes_dir" && find . -type f -name '*.class' -print0 \
    | sort -z | xargs -0 sha256sum)
} > "$classes_dir/MALLORY_HDFS_GRAPH_PORT_MANIFEST.sha256"

mv "$classes_dir" "$output_dir"
echo "installed $output_dir"
