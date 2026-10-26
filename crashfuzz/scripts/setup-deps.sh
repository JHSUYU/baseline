#!/usr/bin/env bash
# setup-deps.sh: the Apache releases and sources CrashFuzz runs the original JUnits on, in the layout
# crashfuzz/settings.py expects under $CRASHFUZZ_DEPS (default /bulk/baseline-deps, shared by every node):
#   hadoop-3.4.3/ hadoop-2.10.0/ hbase-2.6.6/ solr-8.11.4/ apache-zookeeper-3.8.7-bin/    release binaries
#   sources/{hadoop-3.4.3,hbase-2.6.6,solr-8.11.4,zookeeper-3.8.7}/                        their sources
# plus the test-only jars the runners take from ~/.m2, the ZooKeeper tree built with one Surefire run of
# QuorumRestartTest (its runner reads that report's classpath), and the agent and selector jars.
# Every archive is checked against Apache's .sha512. Rerunning skips what is already in place.
set -euo pipefail
deps=${CRASHFUZZ_DEPS:-/bulk/baseline-deps}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
mkdir -p "${deps}/downloads" "${deps}/sources"
cd "${deps}/downloads"

fetch() {  # fetch <url>: download once, verify against the published sha512
  local url=$1 file want got
  file=$(basename "${url}")
  [[ -s "${file}" ]] || { curl -sSfL -o "${file}.part" "${url}" && mv -f "${file}.part" "${file}"; }
  [[ -s "${file}.sha512" ]] || curl -sSfL -o "${file}.sha512" "${url}.sha512"
  # Apache publishes sha512sum, BSD and gpg --print-md ("file: 7724 7039 ...") forms.
  want=$(sed 's/^[^:]*://' "${file}.sha512" | tr -d ' \t\n' | grep -oE '[0-9a-fA-F]{128}' |
         head -1 | tr 'A-F' 'a-f')
  got=$(sha512sum "${file}" | cut -d' ' -f1)
  [[ -n "${want}" && "${want}" == "${got}" ]] || { echo "sha512 mismatch: ${file}" >&2; exit 1; }
}

unpack() {  # unpack <archive> <directory it holds> <destination>
  local archive=$1 inner=$2 destination=$3
  [[ -d "${destination}" ]] && return 0
  tar -xzf "${archive}" -C "$(dirname "${destination}")"
  [[ "$(dirname "${destination}")/${inner}" == "${destination}" ]] ||
    mv "$(dirname "${destination}")/${inner}" "${destination}"
}

archive=https://archive.apache.org/dist
fetch "${archive}/hadoop/common/hadoop-3.4.3/hadoop-3.4.3.tar.gz"
fetch "${archive}/hadoop/common/hadoop-3.4.3/hadoop-3.4.3-src.tar.gz"
fetch "${archive}/hadoop/common/hadoop-2.10.0/hadoop-2.10.0.tar.gz"
fetch "${archive}/hbase/2.6.6/hbase-2.6.6-bin.tar.gz"
fetch "${archive}/hbase/2.6.6/hbase-2.6.6-src.tar.gz"
fetch "${archive}/lucene/solr/8.11.4/solr-8.11.4.tgz"
fetch "${archive}/lucene/solr/8.11.4/solr-8.11.4-src.tgz"
fetch "${archive}/zookeeper/zookeeper-3.8.7/apache-zookeeper-3.8.7-bin.tar.gz"
fetch "${archive}/zookeeper/zookeeper-3.8.7/apache-zookeeper-3.8.7.tar.gz"

unpack hadoop-3.4.3.tar.gz hadoop-3.4.3 "${deps}/hadoop-3.4.3"
unpack hadoop-2.10.0.tar.gz hadoop-2.10.0 "${deps}/hadoop-2.10.0"
unpack hbase-2.6.6-bin.tar.gz hbase-2.6.6 "${deps}/hbase-2.6.6"
unpack solr-8.11.4.tgz solr-8.11.4 "${deps}/solr-8.11.4"
unpack apache-zookeeper-3.8.7-bin.tar.gz apache-zookeeper-3.8.7-bin "${deps}/apache-zookeeper-3.8.7-bin"
unpack hadoop-3.4.3-src.tar.gz hadoop-3.4.3-src "${deps}/sources/hadoop-3.4.3"
unpack hbase-2.6.6-src.tar.gz hbase-2.6.6 "${deps}/sources/hbase-2.6.6"
unpack solr-8.11.4-src.tgz solr-8.11.4 "${deps}/sources/solr-8.11.4"
unpack apache-zookeeper-3.8.7.tar.gz apache-zookeeper-3.8.7 "${deps}/sources/zookeeper-3.8.7"

# Test-only jars the HBase and HDFS runners put on the classpath from CRASHFUZZ_M2
# (default ~/.m2/repository; a shared directory when the runners run on several nodes).
for artifact in org.bouncycastle:bcprov-jdk15on:1.60 org.bouncycastle:bcpkix-jdk15on:1.60 \
    org.jacoco:org.jacoco.agent:0.8.15:jar:runtime org.apache.hadoop:hadoop-minikdc:3.4.3 \
    org.mockito:mockito-core:4.9.0 net.bytebuddy:byte-buddy:1.12.16 \
    net.bytebuddy:byte-buddy-agent:1.12.16 org.objenesis:objenesis:3.3 \
    org.apache.kerby:kerb-simplekdc:2.0.3 \
    org.junit.platform:junit-platform-launcher:1.6.2; do
  mvn -q dependency:get -Dtransitive=true -Dartifact="${artifact}" \
    -Dmaven.repo.local="${CRASHFUZZ_M2:-${HOME}/.m2/repository}"
done

# The ZooKeeper runner reads QuorumRestartTest's Surefire classpath from a built tree.
report=${deps}/sources/zookeeper-3.8.7/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml
if [[ ! -s "${report}" ]]; then
  (cd "${deps}/sources/zookeeper-3.8.7" && mvn -q -DskipTests install &&
     mvn -q -pl zookeeper-server test -Dtest=QuorumRestartTest)
fi

(cd "${here}/runtime-agent" && mvn -q package)
(cd "${here}/static-selection" && mvn -q test package dependency:build-classpath \
  -Dmdep.outputFile=target/runtime-classpath.txt)
echo "CrashFuzz dependencies ready under ${deps}"
