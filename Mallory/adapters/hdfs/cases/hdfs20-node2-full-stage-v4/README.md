# HDFS-20 scheduler-depth-reserve full v4

Immutable successor to v3. Original selected JUnit, source, bytecode, I/O sites, fault budget and target are unchanged. The controller release is built from Mallory core including scheduler commit 12018488; its default reserves every fourth selection for an available depth>1 plan after replay/validated-site policy. Graph and exception results remain outcomes. The v3 package remains untouched.

Launch only after HDFS-19 natural terminal, collection, node2 JVM/source lock/resource gate, and dispatch GO. Raw output is isolated at `/tmp/mallory-hdfs20-heartbeat-v4-node2-full`.
