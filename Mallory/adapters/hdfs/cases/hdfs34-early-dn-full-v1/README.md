# HDFS-34 early DataNode full fault campaign

The existing Hadoop 3.4.3 cluster test is
`TestDFSUpgradeFromImage#testUpgradeFromRel22Image`. The exact target is the
`DataStorage.doTransition` namespace ID mismatch check at lines 739–744. The
same DataNode's `BPServiceActor.retrieveNamespaceInfo` calls
`versionRequest` at line 260. Its `IOException` is caught and retried. The
`Properties.load` door remains a diagnostic site; it can abort before the
selected target. The package uses the early DataNode registration adapter
from `hdfs34-early-dn-v3`, which binds the actor before the version RPC.

The sealed v3 healthy JUnit passed 1/0/0 in 14.368 seconds, with four named
`versionRequest` doors, eight exact nonthrowing target checks on four named
DataNodes, and eight strict same-DataNode event-time paths. The paths cross
observed RPC request and reply edges, then a region-parent edge. The offline
causal audit passed. Evidence is pinned in
`data/mallory/evidence_archives/HDFS-34-early-dn-v3.tar.gz` (SHA-256
`ba878beb4f91ac850a69fc909f2bf99de2c0a279972485595ecdf99864e3e43e`).

The full run starts a **fresh** r0000 on node2. `run_campaign.py` admits fault
trials only after its r0000 has a passing JUnit, exact loaded class, named
target, and at least one observed, same-actor event path from the typed door
to the later target check. The old healthy evidence is context, not a seed
substituted into the full run. The frozen controller expands a fault sequence
only when all physical faults match and apply with valid runtime identity and
the exact target is reached after the final fault. The wrapper checks this
postfault rule and writes one receipt per fault trial; a target-losing
sequence is recorded and abandoned. Exact target exceptions are candidates
for separate source review, not automatic new-bug claims.

The cap is 80 fault trials or 3600 seconds, at most three faults per trial,
and 300 seconds for one trial. The queue may naturally exhaust sooner. The
campaign includes only graph-closure doors, with periodic one-fault breadth
exploration. It writes a resumable checkpoint and unique evidence in
`/tmp/mallory-hdfs34-early-dn-v3-node2-full`. Dispatch owns node2 execution,
sealing, and checklist import. No Docker is involved.

`python3 -B preflight.py --static` checks pinned source and artifacts without
starting a Hadoop JVM. Dispatch runs `MALLORY_DISPATCH_ADMITTED=1 ./run_full.sh`
on node2 after lane admission. The runner acquires the shared HDFS lane lock.
