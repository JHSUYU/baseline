#!/usr/bin/env bash
set -euo pipefail

version=${1:?expected parent or fix}
case "$version" in
  parent|fix) ;;
  *) printf 'unknown version: %s\n' "$version" >&2; exit 2 ;;
esac

root=/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-09/actor-v2/solr16257-diff
source_dir="$root/$version-source"
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
export GRADLE_USER_HOME="$root/gradle-home"

cd "$source_dir"
set +e
nice -n 15 ./gradlew :solr:core:compileTestJava --no-daemon --max-workers=2 --console=plain > "$root/$version-build.log" 2>&1
status=$?
set -e
printf '%s\n' "$status" > "$root/$version-build.exit"
exit "$status"
