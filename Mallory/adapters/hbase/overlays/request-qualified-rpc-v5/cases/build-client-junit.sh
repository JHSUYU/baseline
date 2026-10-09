#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
overlay="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v5"
agent="$base/Mallory/instrumentation/releases/159c74ec50d0703e85cfdfd1b06451e961fc180db04d568926b990aa5458db7a/mallory-agent.jar"
launcher="$base/crashfuzz/vendor/0b0beaeb6880a311-junit-platform-launcher-1.13.4.jar"
classes="$overlay/target/client-junit-classes"
jar="$overlay/target/mallory-hbase-client-selected-junit-v1.jar"

printf '%s  %s\n' \
  '7415d7bf1ee4f64e423f2377be86a3af006e20b82dde7ab4e09c097011a9e816' "$agent" \
  '0b0beaeb6880a31149641d2d848b863712885469670c12099586d7f798522564' "$launcher" | sha256sum -c -
mkdir -p "$classes"
/usr/lib/jvm/java-8-openjdk-amd64/bin/javac -source 8 -target 8 \
  -cp "$agent:$launcher:/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/*" \
  -d "$classes" \
  "$overlay/src/main/java/edu/uva/liftlab/mallory/hbase/requestqualified/ClientSelectedJUnit.java"
/usr/lib/jvm/java-8-openjdk-amd64/bin/jar cf "$jar" -C "$classes" \
  edu/uva/liftlab/mallory/hbase/requestqualified/ClientSelectedJUnit.class
sha256sum "$jar"
