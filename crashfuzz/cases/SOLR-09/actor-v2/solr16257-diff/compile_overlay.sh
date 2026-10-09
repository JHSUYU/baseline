#!/usr/bin/env bash
set -euo pipefail

version=${1:?expected parent or fix}
case "$version" in
  parent|fix) ;;
  *) printf 'unknown version: %s\n' "$version" >&2; exit 2 ;;
esac

root=/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-09/actor-v2/solr16257-diff
trap 'printf "%s\n" "$?" > "$root/$version-overlay.exit"' EXIT
source_dir="$root/$version-source"
overlay_dir="$root/$version-overlay-src"
classes_dir="$root/$version-overlay-classes"
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
export GRADLE_USER_HOME="$root/gradle-home"
export SOLR09_CP_OUT="$root/$version-classpath.txt"

cd "$source_dir"
nice -n 15 ./gradlew -I "$root/classpath.init.gradle" \
  :solr:core:testClasses :solr:core:jar :solr:solrj:jar \
  :solr:test-framework:jar :solr:modules:analysis-extras:jar \
  :solr:core:writeResearchTestClasspath \
  --no-daemon --max-workers=2 --console=plain > "$root/$version-classpath-build.log" 2>&1

test -s "$SOLR09_CP_OUT"
runtime_cp=$(cat "$SOLR09_CP_OUT")
mkdir -p "$classes_dir"
compiler=("$JAVA_HOME/bin/java" --module jdk.compiler/com.sun.tools.javac.Main)
"${compiler[@]}" -cp "$runtime_cp" -d "$classes_dir" \
  "$root/FeedbackProbe.java" "$root/RunSingleJUnit.java"
"${compiler[@]}" -cp "$classes_dir:$runtime_cp" -d "$classes_dir" \
  "$overlay_dir/solr/core/src/java/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.java" \
  "$overlay_dir/solr/core/src/java/org/apache/solr/handler/component/HttpShardHandler.java" \
  "$overlay_dir/solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java" \
  "$overlay_dir/solr/core/src/java/org/apache/solr/cloud/ZkController.java" \
  "$overlay_dir/solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java" \
  > "$root/$version-overlay-compile.log" 2>&1

test -s "$classes_dir/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class"
test -s "$classes_dir/org/apache/solr/common/cloud/ZkStateReader.class"
test -s "$classes_dir/baseline/solr09/FeedbackProbe.class"
sha256sum \
  "$source_dir/solr/core/build/classes/java/test/org/apache/solr/cloud/DeleteReplicaTest.class" \
  "$classes_dir/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class" \
  "$classes_dir/org/apache/solr/common/cloud/ZkStateReader.class" \
  "$classes_dir/baseline/solr09/FeedbackProbe.class" \
  > "$root/$version-bytecode-sha256.txt"
