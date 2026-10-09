#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
java8=/usr/lib/jvm/java-8-openjdk-amd64/bin
asm=/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar
core=/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar
launcher=/users/ZhenyuLi/.m2/repository/org/junit/platform/junit-platform-launcher/1.6.2/junit-platform-launcher-1.6.2.jar
engine=/users/ZhenyuLi/.m2/repository/org/junit/platform/junit-platform-engine/1.6.2/junit-platform-engine-1.6.2.jar
commons=/users/ZhenyuLi/.m2/repository/org/junit/platform/junit-platform-commons/1.6.2/junit-platform-commons-1.6.2.jar
api=/users/ZhenyuLi/.m2/repository/org/apiguardian/apiguardian-api/1.1.0/apiguardian-api-1.1.0.jar
mkdir -p "$here/agent/classes" "$here/runner/classes" "$here/coverage/classes"
"$java8/javac" -source 8 -target 8 -cp "$asm" -d "$here/agent/classes" "$here"/agent/src/zk07/*.java
printf 'Premain-Class: zk07.CoverageAgent\nCan-Redefine-Classes: false\n' > "$here/agent/manifest.mf"
"$java8/jar" cfm "$here/agent/zk07-agent.jar" "$here/agent/manifest.mf" -C "$here/agent/classes" .
"$java8/javac" -source 8 -target 8 -cp "$launcher:$engine:$commons:$api" -d "$here/runner/classes" "$here/runner/src/zk07/OriginalJUnitRunner.java"
"$java8/jar" cf "$here/runner/zk07-runner.jar" -C "$here/runner/classes" .
"$java8/javac" -source 8 -target 8 -cp "$core" -d "$here/coverage/classes" "$here/coverage/src/zk07/CoverageDump.java"
"$java8/jar" cf "$here/coverage/zk07-coverage-dump.jar" -C "$here/coverage/classes" .
sha256sum "$here/agent/zk07-agent.jar" "$here/runner/zk07-runner.jar" "$here/coverage/zk07-coverage-dump.jar"
