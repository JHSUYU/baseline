# HDFS-31 block-pool map identity diagnostic

The prior receiver-scoped healthy run passed the original
`TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` MiniDFSCluster
JUnit and reached `DataNode.getBPOSForBlock:1833` on the physical `dn0`.
Its trace had no `STATE_READ` or `STATE_WRITE` events because
`BlockPoolManager` was absent from `agent_include`. The target's backward
closure consequently contained only the target region. The heartbeat door
at `BPServiceActor.sendHeartBeat:563` was observed before the target, but
that order alone is not a causal path.

This healthy-only package adds `BlockPoolManager` to the existing pinned
instrumentation scope. The unchanged agent records its `HashMap.put` in
`addBlockPool` and `HashMap.get` in `get` as keyed state events. It also
marks `addBlockPool`, `get`, and `remove` as regions. The original target,
test, DataNode receiver identity hook, agent, and Hadoop class bytes remain
SHA pinned. The run contains no fault trial and cannot promote itself.

The case audit checks a passing JUnit, the exact nonthrowing target on
`hdfs-cluster-1/dn0`, a keyed `STATE_READ` inside the target's nested
`BlockPoolManager.get` region, and a prior matching map write. State
versions from the generic agent are sampled, so even a matched write/read
is **candidate** evidence rather than a proven event-time causal edge.
`HashMap.remove` is not covered by the current generic map instrumentation.
This diagnostic does not claim that an ordinary heartbeat `IOException`
removes the map entry or triggers the target exception.

Run `python3 -B preflight.py --static` on node0. Dispatch may run
`MALLORY_DISPATCH_ADMITTED=1 ./run_healthy.sh` on node2 after admitting
the HDFS lane. The runner takes the shared lock and writes to fresh
`/tmp/mallory-hdfs-31-map-healthy-v3`. Then run
`python3 -B audit.py /tmp/mallory-hdfs-31-map-healthy-v3`. Review the
printed evidence before any separate fault campaign is admitted.
