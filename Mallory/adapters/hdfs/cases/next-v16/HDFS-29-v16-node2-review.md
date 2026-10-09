# HDFS-29 v16: one healthy MiniDFSCluster seed and source gate

**Disposition:** healthy seed validated; fault pilot held after source review. No
exception was injected and no bug was found. The earlier v15 seed remains
invalid because its JUnit timed out in `DelayAnswer.waitForCall` despite Maven
returning success.

## Reproducible healthy evidence

The original Hadoop 3.4.3
`TestPipelinesFailover#testLeaseRecoveryAfterFailover` starts an HA
MiniDFSCluster with three DataNodes, writes an under-construction file,
fails over the active NameNode, and recovers the lease. The selected product
check is `BlockRecoveryWorker.getActiveNamenodeForBP` at
`BlockRecoveryWorker.java:577`: `if (bpos == null)`, followed by the
`IOException` at line 578. Its caller `RecoveryTaskContiguous.syncBlock`
reaches the check before committing block synchronization.

Node0 was held because only about 259 MiB remained above the 5 GiB disk
floor, with no defensible margin for MiniDFSCluster transient files. Dispatch
approved **one** healthy-only run on node2 after the source lock, output
freshness, disk, and exact runtime artifacts passed a separate preflight.
The node2 source copy has incomplete Git metadata; its relevant test and
product source files, compiled classes, distribution JAR, site catalog,
adapter, agent, and frozen core manifest were verified by SHA-256. This is
content-hash provenance, not a node2 Git HEAD claim.

The sole trial took **21.893 seconds**. Surefire recorded one JUnit test,
zero failures, zero errors, zero skipped, with process exit 0 and no timeout.
The target event `HDFS-29-r0000:2941` executed at the exact line-577 site on
`hdfs-cluster-1/dn0`, epoch 0, occurrence `hdfs-block-recovery:1:1`; there
was no `TARGET_THROW`. The compiled target class matched the pinned SHA-256.
The frozen offline audit passed and counted two named I/O doors with fully
observed paths into that target. The paths contain neither candidate edges
nor a root occurrence:

| Door | Observed message edge | Observed parent edge |
| --- | --- | --- |
| dn2 `DOOR_OBSERVED` event 2872 | dn2 response 2905 → dn0 receive 2907 | dn0 recovery task 2718 → target region 2938 |
| dn1 `DOOR_OBSERVED` event 2929 | dn1 response 2935 → dn0 receive 2937 | dn0 recovery task 2718 → target region 2938 |

The door instances are `Server$RpcCall.run` at line 1246 on the two
secondary DataNodes. Their response correlations and full occurrence
addresses are in `HDFS-29-v16-node2-observed-paths.json`. The frozen audit
counted 12 observed closure edges and two observed-path doors. An initial
postrun gate rejected a bytewise config comparison because the controller
reserialized identical JSON with sorted keys; the original rejection is
preserved. The corrected gate pins the approved input SHA and compares the
controller copy as parsed JSON. It admits the healthy seed without changing
the trial or its evidence.

## Why the observed doors are not a valid HDFS-29 fault frontier

At `Server.java:1246`, the generic door wraps an inbound RPC `call()` on
dn1 or dn2. During this workload, dn0's `RecoveryTaskContiguous.recover`
calls `initReplicaRecovery` on replicas. An `IOException` from those remote
calls is counted as a failed replica; all failures abort recovery, while a
surviving replica lets `syncBlock` continue (`BlockRecoveryWorker.java:120–189`).
That can affect *whether* the selected check is reached or the replica set.

The HDFS-29 predicate instead reads dn0's own
`DataNode.getBPOfferService(bpid)` →
`BlockPoolManager.bpByBlockPoolId.get(bpid)`
(`DataNode.java:2235–2236`, `BlockPoolManager.java:85–86`). The map is added
after block-pool registration and removed on offer-service teardown or
nameservice refresh (`BlockPoolManager.java:65–72,89–110,175–252`). A
generic replica RPC exception on dn1/dn2 has no source path to removing
that entry on dn0. The graph proves communication into the recovery task,
but not influence on this local map lookup. We therefore stop before fault
injection; a target-retaining fault at either observed door would be weak
evidence for the `bpos == null` check.

The complete local mirror of node2 raw files is
`data/mallory/calibration_v16_node2/HDFS-29` plus
`data/mallory/calibration_v16_node2_artifacts/HDFS-29`.
`HDFS-29-v16-node2-evidence-manifest.json` records size and SHA-256 for all
23 files and confirms every hash equals the node2 original. Key hashes are:
trial result `d14edbe96b83cae40648a1688ee80a5e692e20693227e0d0614881cc4c0a000e`,
compressed event trace `dab69ac708f5b028d329e076a5879d77871c5669c9afe55d9eece3b607a5000`,
offline audit `0d93e890da58a2fc7b0d246dc42cf94298f75c1de4e8dfa6bfe60f8ca538016d`,
and final gate `9ccd8d6c733378a20e7b939362692847794a0d6bbcf28fadb967ca4575c9a35c`.
