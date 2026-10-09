# Trial 0057: HDFS-29 throw during JUnit teardown

**Decision:** The raw trace contains one HDFS-29 `TARGET_THROW`, but this is
not a selected same-actor postfault target exception. Keep the JUnit timeout
as a separate outcome for possible replay; do not mark a new coordination
bug from this throw.

The original `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization`
JUnit ran for 64.020 seconds and exited 1. Its own `@Test(timeout=60000)`
expired while `loopRecoverLease` waited for lease recovery. The selected
two-fault sequence matched and applied in order on the first coordinator's
`dn0/block:1073741825/attempt:1` recovery (`recoveryId=1002`):

| Trace sequence | Event | Physical actor / recovery |
| ---: | --- | --- |
| 17 | `SocketTimeoutException` at Hadoop IPC `initReplicaRecovery` send | `dn0`, recovery ID 1002 |
| 25 | `IOException` at remote `dn2` replica `blockDataExists` read | origin `dn0`, recovery ID 1002 |
| 26 | HDFS-29 guard `outcome=false` | `dn0`, recovery ID 1002 |
| 28 | HDFS-30 guard `outcome=false` | `dn0`, recovery ID 1002 |
| 39 | A new recovery begins | `dn2/block:1073741825/attempt:1`, recovery ID 1003 |
| 58, 60 | HDFS-29 guard `outcome=true`, then selected `IOException` | `dn2`, recovery ID 1003 |

The HDFS-29 throw belongs to a **different physical actor and recovery
attempt** from the injected sequence. The per-case strict oracle therefore
records one target-retaining HDFS-29 trial for `dn0` with zero selected
postfault throws; it does not count the `dn2` throw as a candidate.

The JUnit log places `MiniDFSCluster.shutdown` at
`2026-10-07 10:41:33.556 UTC`, followed by DataNode 2 shutdown. At
`10:41:33.609`, the background `dn2` recovery logs `No block pool offer
service for bpid=...` from `BlockRecoveryWorker.java:578`. Hadoop's
`DataNode.shutdownBlockPool` calls `blockPoolManager.remove(bpos)`
(`DataNode.java:2147–2148`); `BlockPoolManager.remove` deletes the entry
from `bpByBlockPoolId` (`BlockPoolManager.java:86–100`);
`getActiveNamenodeForBP` throws exactly this `IOException` when
`getBPOfferService(bpid)` returns null (`BlockRecoveryWorker.java:574–579`).
The shutdown preceding the throw explains this observation without evidence
of an incorrect live-cluster coordination state. Whether the injected
sequence contributes to the lease-recovery timeout is a separate question;
the JUnit timeout alone is not the target-exception oracle.

Read-only audit of the first 74 completed HA campaign trials found zero
plan/order/identity/target/manifest/trace-hash errors and zero qualifying
same-actor target-exception candidates. The trial-57 raw files on node1 have
these SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `runtime_trace.jsonl` | `899a12f141b3c7f6a51bcc8a3c2353fde435d289a3dcd5e3d613fdbf9c9fe5d7` |
| `manifest.json` | `fa3a3f43551a1f26fbb86be4fd338aa0a2203e7960e2f50326793ae1671ef24c` |
| `junit.log` | `b922b229188f2c4a16933a02b9bcb9371c8f7f0d4b6c9206109932a215ea01c3` |
| `fault-plan.tsv` | `16ba650d48fac73de9e4863a64ff8632e67f4af6d42f1c2ddfbc0a6c8c75c459` |
