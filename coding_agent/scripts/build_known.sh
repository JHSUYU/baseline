#!/usr/bin/env bash
# build_known.sh <case> [golden|sanity] -- in the offline container:
#   golden: clean build of known/<case>/golden (drops every class Specula's instrumentation left behind);
#   sanity: a copy made like the agent's (prepare_known.py copy) runs the prompt's starting-test command.
set -euo pipefail
c=${1:?case}; mode=${2:-golden}
R=/bulk/codingagent; S=/bulk/specula-adhoc
k=$R/known/$c
case $c in hdfs-*) tree=hadoop;; hbase-*) tree=hbase;; zk-*) tree=zookeeper;; solr-*) tree=lucene-solr;; esac
if [[ $mode == golden || $mode == fixed ]]; then
  base=$k/$mode
  [[ $mode == fixed ]] && python3 -I $R/bin/prepare_known.py fixed "$c"
  case $c in
    hdfs-*)  cmd="find . -name target -type d -prune -exec rm -rf {} + && mvn -B -o install -DskipTests -Dmaven.javadoc.skip=true -pl hadoop-hdfs-project/hadoop-hdfs -am" ;;
    hbase-*) cmd="find . -name target -type d -prune -exec rm -rf {} + && mvn -B -o install -DskipTests -Dmaven.javadoc.skip=true -pl hbase-server -am" ;;
    zk-*)    cmd="ant clean compile-test" ;;
    solr-*)  cmd="(cd solr && ant -lib \$IVY_USER_DIR/lib clean -Divy_install_path=\$IVY_USER_DIR/lib) && cd solr/core && ant -lib \$IVY_USER_DIR/lib compile-test -Divy_install_path=\$IVY_USER_DIR/lib" ;;
  esac
else
  base=$k/sanity
  rm -rf "$base"
  python3 -I $R/bin/prepare_known.py copy "$c" "$base" >/dev/null
  cmd=$(python3 -I - "$R/known/targets/$c.yaml" <<'EOF'
import sys, yaml
t = yaml.safe_load(open(sys.argv[1])); cls, _, m = t["workload"]["test"].partition("#"); b = t["build"]["test_command"]
c = b.replace("<Class>", cls.rsplit(".", 1)[-1] if "ant " in b else cls).replace("<method>", m).replace(" -o surefire:test ", " -o test ")
if t["id"].startswith("hbase-") and "-PrunAllTests" not in c:
    c = c.replace(" -o test ", " -o test -PrunAllTests ")
print(c)
EOF
)
fi
mkdir -p "$base/tmp" "$base/home" "$k/etc"
printf 'root:x:0:0:root:/root:/bin/bash\nagent:x:20003:3160:agent:%s/home:/bin/bash\n' "$base" > "$k/etc/passwd"
printf 'root:x:0:\nagent:x:3160:\n' > "$k/etc/group"
name=ca-build-$c-$mode
docker rm -f "$name" >/dev/null 2>&1 || true
echo "$(date -u +%FT%TZ) $c $mode: $cmd" >> "$k/build.log"
start=$(date +%s)
set +e
docker run --rm --name "$name" --hostname agent-host --network ca-internal --user 20003:3160 \
  --cpus 24 --memory 96g --shm-size 4g --ulimit nofile=65536:65536 --ulimit nproc=65536:65536 \
  -v "$base:$base" -v "$base/tmp:/tmp" -v "$k/etc/passwd:/etc/passwd:ro" -v "$k/etc/group:/etc/group:ro" \
  -v "$S/jdk:/opt/tools/jdk:ro" -v "$S/apache-maven-3.9.15:/opt/tools/apache-maven-3.9.15:ro" \
  -v "$S/apache-ant-1.10.14:/opt/tools/apache-ant-1.10.14:ro" -v "$R/tools/jdk8:/opt/tools/jdk8:ro" \
  -v "$S/toolchain/jdk7:/opt/tools/jdk7:ro" -v "$S/toolchain/apache-ant-1.9.16:/opt/tools/apache-ant-1.9.16:ro" \
  -v "$S/toolchain/protoc-2.5.0:/opt/tools/protoc-2.5.0:ro" \
  -e HOME=$base/home -w "$base/$tree" codingagent-runtime:1 bash -c "source $base/env.sh; $cmd" > "$k/$mode.out" 2>&1
rc=$?
echo "$(date -u +%FT%TZ) $c $mode: rc=$rc $(( $(date +%s) - start ))s" >> "$k/build.log"
tail -n 3 "$k/build.log" | tail -n 1
exit $rc
