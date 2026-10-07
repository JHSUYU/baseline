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
