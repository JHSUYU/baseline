# HDFS-32 V3 identity and coverage review

The original `TestDeleteBlockPool#testDeleteBlockPool` starts two DataNodes. The
selected check is the **second** DataNode's first
`deleteBlockPool(bpid1, true)` call. Its healthy outcome is an expected
`IOException` because `blockPoolManager.get(blockPoolId) != null` in
`DataNode.java:3819`.

## Registration phase boundary

In both healthy traces, `episode1/dn1` is already bound to the same
`DataNode` object and `namesServerId1` service before it has a UUID or raw
block pool ID. `healthy-a` seq 8 begins that BP service, and seq 10 observes
its `versionRequest` RPC with `uuid=""` and `rawBpid=""`. The subsequent
`registerDatanode` RPC at seq 18 carries a nonempty UUID and raw BPID;
`healthy-b` has the analogous seq 8, 10, and 17 events. Thus UUID equality
across these two startup phases would be an invalid physical actor test.

The current V3 `physical()` predicate deliberately admits only postregistration
I/O with the target actor, service, raw BPID, nonempty UUID, and matching RPC
endpoint or dataset mapping. Its effective criterion then compares the applied
fault and later selected check using that same UUID and BPID. As a read only
spot audit at completed attempt 85, all 85 traces contained two preregistration
`episode1/dn1` `versionRequest` points (170 total); all 224 applied faults had
nonempty UUID and raw BPID. The preregistration points are outside V3's
injection scope. This scope limitation does not alter the completed V3 counts.

## Trial 85 production coverage

Trial 85 applied four same actor faults, last at trace seq 82, and retained
the selected `episode1/dn1` guard at seq 88. The selected seq 89
`IOException` has the same type/message as healthy. JaCoCo added three
`BlockManager` probes and two branch counts in
`addStoredBlockUnderConstruction`. In Hadoop 3.4.3 source commit
`9d50c6884666e794e45102260a4017bb31802e1b`,
`BlockManager.processReport` calls this method for under construction
replicas (`BlockManager.java:3177,3687`). The selected target guard instead
reads the local DataNode `BlockPoolManager` (`DataNode.java:3819`). The run's
whole JUnit JaCoCo feedback establishes new production coverage, but the trace
does not establish a causal link from that NameNode branch to the target guard.
The campaign's predefined extension rule uses production coverage novelty;
this observation must not be described as proven target related coverage.

## Trial 100 production coverage and the 80-effective boundary

Trial 100 applied four `registerDatanode` RPC exceptions to
`episode1/dn1`, all on the same physical UUID and raw BPID. Its final fault
was at trace seq 61; the selected check followed at seq 118 and kept the
healthy `IOException` outcome. The run added two JaCoCo probes and one branch
count in `DatanodeStats.StorageTypeStatsMap.subtractNode`. In Hadoop 3.4.3
source, `DatanodeStats.subtract` invokes this helper while removing a node's
per-storage-type statistics (`DatanodeStats.java:80-108,219-227`);
`HeartbeatManager` calls `stats.subtract` when updating node accounting.
The reviewed `DatanodeStats.java` SHA-256 is
`08ccf0472c8bd8b2bd008b2dcf78e20bfa47f9167ab7637407e3bef2e5eb832c`.
The target check at `DataNode.java:3819` instead reads the local
`BlockPoolManager`. The raw trace records the fault and later target, but
does not record a data or control path from the NameNode accounting branch
to that local guard. This is a global production coverage gain, not a
proven target-related gain.

Trial 100 entered the last-eight-effective window at campaign attempt 101,
when the 80th effective run completed. The predefined novelty rule therefore
raised the effective goal from 80 to 128 and the maximum fault depth from 8
to 10. The extension is a mechanical budget decision; it does not establish
a new target outcome or bug.
