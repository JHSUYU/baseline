# HDFS-29/30 source-only handoff

These are isolated, one-trial, fault-free calibration proposals. `prepare.py`
pins the original Hadoop 3.4.3 source and compiled classes, frozen Mallory
agent, v11 HDFS adapter, core release, site rules, and configs. It invokes only
Python and `git`; it does not run Hadoop or a JVM. `verify_bytecode.py` reads
classfiles directly and confirms the exact line/callee for both proposed doors
and the two selected `ifnonnull` guards at lines 577 and 582.

## Original JUnit and target reach

The checklist's original selector is
`TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization`. Its
existing identity-invalid calibration runs passed one JUnit test with no
errors according to their Maven stdout (HDFS-29: 14.918 s; HDFS-30: 17.867 s)
and each observed the exact guard twice without the selected throw. The
DataNode identity was `unknown`, so neither was an admissible healthy seed.
The later HDFS-29 v15 run bound a named DataNode and reached its guard, but
JUnit timed out at `DelayAnswer.waitForCall` after 60 seconds. The trace shows
a commit RPC reached NN0; it does not explain why the Mockito spy did not
release the latch. This is a workload synchronization failure for that run,
not evidence of either selected exception.

The staged alternate is the existing
`TestPipelinesFailover#testLeaseRecoveryAfterFailover` JUnit, which starts the
same three-DataNode HA MiniDFSCluster and drives lease recovery after a
failover without the delayed Mockito commit callback. Its recovery path calls
`RecoveryTaskContiguous.syncBlock`, then `getActiveNamenodeForBP`. A fresh
healthy run still must prove this path executes and passes JUnit.

## Candidate doors

| Case | Exact compiled call | Why a one-shot `IOException` can leave a recovery path |
| --- | --- | --- |
| HDFS-29 | `BlockRecoveryWorker.callInitReplicaRecovery` line 561 to `InterDatanodeProtocol.initReplicaRecovery` | `RecoveryTaskContiguous.recover` catches an I/O failure for each replica at lines 162-166, continues to other replicas, and can call `syncBlock` at line 183 if at least one succeeds. This is a target-reaching candidate, not a demonstrated cause of a missing block-pool service. |
| HDFS-30 | `BPServiceActor.sendHeartBeat` line 563 to `DatanodeProtocolClientSideTranslatorPB.sendHeartbeat` | `BPServiceActor.offerService` catches the I/O failure at lines 786-788 and retries. That response cannot update `BPOfferService.bpServiceToActive` at lines 725-726; a recovery already in flight may encounter the line-582 guard before the new active NN is acknowledged. This timing and graph path remain unverified. |

The target method performs no I/O: HDFS-29 checks whether
`DataNode.blockPoolManager.get(bpid)` is null; HDFS-30 checks whether
`BPOfferService.getActiveNN()` returns null. The proposed doors are upstream
exception points and cannot be treated as direct target throws. HDFS-29 in
particular has no source-backed claim that one failed replica RPC removes the
block-pool mapping.

## Admission for dispatch

Run only an isolated healthy calibration after allocating an idle source/build
lane and confirming node0 has at least 5 GiB free. Promote neither case from
these files. Require a passing JUnit (`tests=1`, `errors=failures=0`), the
case's exact check on a named DataNode, no selected target throw, and an
observed event-time path from its explicit door to the same recovery
occurrence. Inspect the offline causal audit before any faulted pilot. A
healthy run that only has a generic RPC or unrelated local timeline door is
insufficient. No fault-retention or target-exception claim is made here.

Recreate and validate the pins with:

```sh
python3 Mallory/adapters/hdfs/cases/pending-29-30-v2/prepare.py
python3 Mallory/adapters/hdfs/cases/pending-29-30-v2/verify_bytecode.py
```
