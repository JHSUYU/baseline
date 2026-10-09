#!/usr/bin/env bash
set -euo pipefail
case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-34/native
hbase_dist=/users/ZhenyuLi/.baseline-deps/hbase-2.6.6
hadoop_dist=/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0
jacoco_agent=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar
java_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
javac_bin=/usr/lib/jvm/java-8-openjdk-amd64/bin/javac
classpath="$case_dir/classes:$case_dir/junit-platform-launcher-1.13.4.jar:$hbase_dist/conf:$hbase_dist/lib/api-asn1-api-1.0.0-M20.jar:$hbase_dist/lib/api-i18n-1.0.0-M20.jar:/users/ZhenyuLi/.m2/repository/org/bouncycastle/bcprov-jdk15on/1.60/bcprov-jdk15on-1.60.jar:/users/ZhenyuLi/.m2/repository/org/bouncycastle/bcpkix-jdk15on/1.60/bcpkix-jdk15on-1.60.jar:$hbase_dist/lib/*:$hbase_dist/lib/client-facing-thirdparty/*:$hadoop_dist/share/hadoop/common/hadoop-common-2.10.0-tests.jar:$hadoop_dist/share/hadoop/common/lib/*"
coverage_cp="$case_dir/classes:/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.10.1/asm-9.10.1.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.10.1/asm-tree-9.10.1.jar:/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.10.1/asm-commons-9.10.1.jar"
if [[ "${1:?stage}" == build ]]; then
  mkdir -p "$case_dir/classes"
  "$javac_bin" -cp "$classpath" -d "$case_dir/classes" "$case_dir/src/HBase34Agent.java" "$case_dir/src/NativeJUnit.java"
  "$javac_bin" -cp "$classpath" -d "$case_dir/classes" "$case_dir/src/org/apache/hadoop/hbase/http/ssl/KeyStoreTestUtil.java"
  "$javac_bin" -cp "$coverage_cp" -d "$case_dir/classes" "$case_dir/src/CoverageReport.java"
  printf 'Premain-Class: HBase34Agent\nCan-Redefine-Classes: true\nCan-Retransform-Classes: true\n' > "$case_dir/manifest.mf"
  jar cfm "$case_dir/agent.jar" "$case_dir/manifest.mf" -C "$case_dir/classes" HBase34Agent.class -C "$case_dir/classes" 'HBase34Agent$TestScope.class' -C "$case_dir/classes" 'HBase34Agent$TestTokenCall.class' -C "$case_dir/classes" 'HBase34Agent$WhoAmI.class' -C "$case_dir/classes" 'HBase34Agent$Retrieve.class' -C "$case_dir/classes" 'HBase34Agent$SaslInbound.class'
elif [[ "$1" == run ]]; then
  suffix="${2:?suffix}"
  data_dir="$case_dir/data-$suffix"
  mkdir -p "$data_dir/tmp"
  export HBASE_HOME="$hbase_dist"
  exec timeout 1200s /usr/bin/time -f 'ELAPSED_SECONDS=%e MAX_RSS_KB=%M' \
    "$java_bin" -Xmx4g \
    -javaagent:"$jacoco_agent=destfile=$case_dir/$suffix.exec,includes=org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager:org.apache.hadoop.hbase.ipc.NettyHBaseSaslRpcServerHandler:org.apache.hadoop.hbase.security.HBaseSaslRpcServer:org.apache.hadoop.hbase.security.provider.DigestSaslServerAuthenticationProvider*" \
    -javaagent:"$case_dir/agent.jar" \
    -Dhbase34.fault.plan="${HBASE34_FAULT_PLAN:-}" \
    -Djava.io.tmpdir="$data_dir/tmp" \
    -Dtest.build.data.basedirectory="$data_dir" \
    -cp "$classpath" NativeJUnit \
    org.apache.hadoop.hbase.security.token.TestGenerateDelegationToken testOnlyToken
elif [[ "$1" == coverage ]]; then
  exec "$java_bin" -cp "$coverage_cp" CoverageReport "${2:?exec path list}" "$hbase_dist/lib/hbase-server-2.6.6.jar"
else
  exit 2
fi
