# V5 hook and owner audit, offline 2026-10-07 UTC

The released Hadoop 3.4.3 source and bytecode used by `run_original.py`
match these operations:

| Point | Source and required relation | V5 hook result |
| --- | --- | --- |
| Active recovery command | `BPOfferService.java:783-786` obtains `BlockRecoveryCommand.getRecoveringBlocks()` and passes that collection to `dn.getBlockRecoveryWorker().recoverBlocks(...)`; method `processCommandFromActive` can throw `IOException`. | One ASM method-entry hook records exact registered DataNode, BP, block, recovery ID, episode, command-object token, and raw NN endpoint. A singleton command is required for fault eligibility. |
| Asynchronous recovery task | `BlockRecoveryWorker.java:615-630` iterates the passed `RecoveringBlock` objects and calls `new RecoveryTaskContiguous(b).recover()` in a daemon. | Entry hook now passes the actual `rBlock` object to `RecoveryProbe.beginRecovery`, preserving the producer's execution-local token. Missing token receives a distinct `direct:` token and cannot falsely match a command event. |
| HDFS-28 target | `BlockRecoveryWorker.RecoveryTaskContiguous.recover` calls `getDatanodeID(bpid)` at replica-loop entry. | Existing exact guard/throw hooks remain at `#u12`; a producer fault earns credit only when a later guard has the same seven-part owner. |
| HDFS-29/30 targets | `getActiveNamenodeForBP` guards `#u12` and `#u23` occur after replica RPCs. | Existing target hooks remain; a second fault is prioritized only when the strict parent's raw trace shows a later same-owner guard. |
| Replica file and RPC | `FsDatasetImpl.checkReplicaFiles`, `InterDatanodeProtocol.initReplicaRecovery`, `Client$Connection.sendRpcRequest`. | Existing V4 selectors and phase spelling are preserved; events additionally carry BP/recovery/episode/token. Unknown or ambiguous server owner is excluded. |

The released bytecode confirms exactly one `RecoveryProbe.ioRecoveryCommand`
call at the beginning of `BPOfferService.processCommandFromActive`, and the
`RecoveryTaskContiguous` entry loads its `rBlock` field before calling the
new `beginRecovery(RecoveringBlock, DataNode)` method. The ASM weaver checks
hook counts for all seven patched production/test classes and fails on a
mismatch. `offline_smoke.py` compiled the overlay, loaded BPOfferService
under `-Xverify:all`, and parsed synthetic TARGET_CHECK, BRANCH,
TARGET_THROW, and I/O JSON. It also compared independent controller/auditor
verdicts on a same-owner synthetic trace and rejected a BP or token mismatch.
No MiniDFSCluster or JUnit JVM was started by this audit.

The archived V4 healthy traces put `RECOVERY_BEGIN` at seq 3, the first
HDFS-28 check at seq 4, and the first existing V4 I/O point afterward. The
new command hook is therefore the only proposed pre-first-check I/O in this
workload, and its **runtime presence remains unproven** until the two V5
healthy calibrations. The independent migrated-queue audit found 0 pending
two-fault plans with a same-owner second I/O before HDFS-28, versus 196 for
both HDFS-29 and HDFS-30. This is a queue feasibility observation, not a
claim that HDFS-28 is unreachable under all workloads.

The old V4 `TARGET_THROW` JSON appended a quote after numeric `blockId`.
The isolated probe fixes that format and emits BP/recovery/episode/token on
the throw. The full V5 overlay digest is in `offline-smoke.json`; future
healthy and fault manifests must match it exactly.
