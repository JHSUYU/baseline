# node1 namespace V2 preflight (2026-10-07 08:04 UTC)

No HBase MiniCluster JUnit or fault trial was started in this preflight.
The original `TestNamespaceAuditor` remains the workload. The staged copy is
isolated at `/users/ZhenyuLi/baseline/crashfuzz/hbase-namespace-actor-v2-node1/`;
the older `hbase-namespace-actor-v2/` directory on node1 was not overwritten.

## Reproducibility

- The staged copy built with node1 Java 8 and passed `run.sh smoke`, including
  actual transformed ZK exists/delete and max-region calls. No cluster started.
- SHA-256 matched node0 for all 27 staged source/script/compiled-class/JUnit
  launcher files. Examples: `NamespaceActorAgent.java`
  `952c25908957b02eabac9de2c54381512285207ea51e39fcbafa23fd6e4a0161`,
  `NamespaceActorAgent.class`
  `2fcec56a6ba1de543c7f582622f1b931e870ab1aca79ca3e5b245d28fb9019b5`,
  `CoverageNamespace.class`
  `d8f148b9af03584c1c87d6066f8725dc7570cff6caa384d15c573e3d794bdb49`,
  launcher JAR
  `0b0beaeb6880a31149641d2d848b863712885469670c12099586d7f798522564`.
- The locally repackaged agent JAR had a different ZIP timestamp despite
  identical classes. The byte-identical node0 JAR was copied into this isolated
  node1 staging directory. Both now have SHA-256
  `f6ac63c8ad2e07499f99f93e1b04f9cf53c5f849274b98828277b3fc159b8601`.
  Node1 `run.sh smoke` passed again with that exact JAR, including transformed
  Advice calls and fail-closed manager rotation.
- The HBase 2.6.6 server/test JARs, Hadoop 2.10.0 common tests JAR,
  JaCoCo 0.8.15 agent/core, and ASM 9.10.1 core/tree/commons JARs match
  node0 by SHA-256. The three ASM JARs were absent on node1 and were copied
  into the matching per-user Maven cache paths. A historical 394-byte
  JaCoCo exec file produced the same offline production report on both
  nodes: `ClusterSchemaServiceImpl methods=10 branches=5 lines=32`.

## Capacity and ports

- At preflight, node1 had about 23 GiB disk free and 57 GiB memory available.
- At the last pre-start check, node1 had 22 GiB disk free and four Java JVMs,
  including the still-active HDFS-01 campaign. The HBase JUnit has not started.
- The original test calls `StartMiniClusterOption.builder().numMasters(2)`.
  `MiniZooKeeperCluster` defaults to a randomly selected client port in
  49152–65535 and retries a bind collision. `LocalHBaseCluster` sets default
  Master, RegionServer, and info ports to `0`, letting the OS allocate ports.
  No fixed reservation is required. Each run receives its own
  `test.build.data.basedirectory` and `java.io.tmpdir` from `run.sh`.
- Other node1 Java campaigns were active at preflight. The HBase JUnit must
  wait for the parent-assigned single-cluster slot, initially after HDFS-01
  completes 80 effective trials and exits. A four-gigabyte heap is configured
  per sequential HBase run, bounded at 240 seconds.

## Planned calibration after slot release

Run only `healthy table h1` and `healthy table h2` first, one at a time.
Inspect JUnit pass, `GUARD_OPERAND`, same active Master/manager target identity,
I/O selector stability, port collisions, and elapsed time before starting
`healthy restore h1` and `healthy restore h2`. HBASE-08 and HBASE-22 may share
the two immutable table seed receipts; HBASE-21 uses the restore seeds.
No V2 campaign checkpoint exists yet, so its effective-trial denominator is 0.
