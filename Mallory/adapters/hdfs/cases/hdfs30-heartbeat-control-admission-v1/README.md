# HDFS-30 heartbeat control-plane source audit

Status: **nonterminal source-review gap**. This receipt is offline only. No HDFS JVM, healthy probe, fault trial, or full campaign was started for this review.

## Exact check and existing JUnit

The selected check is `BlockRecoveryWorker.getActiveNamenodeForBP(String)` at line 582 (`activeNN == null`); line 583 throws `IOException`. `bpos.getActiveNN()` reads `BPOfferService.bpServiceToActive` under a read lock. The preceding line-577 guard first requires a non-null BPOfferService.

`TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` is an existing three-DataNode HA MiniDFSCluster JUnit. An archived no-fault run returned JUnit 1/0/0 and hit the exact line-582 check twice without throwing, but both target instances had node `unknown`, epoch 0. It is **not a named healthy admission**. A later HDFS-29 instrumented run of this same JUnit reached a named DN target yet timed out in the test's `DelayAnswer.waitForCall` synchronization, so its clean JUnit gate also failed. `testLeaseRecoveryAfterFailover` is a shorter three-DataNode HA JUnit without that callback; its source drives recovery after failover, but exact HDFS-30 target reach under that alternate selector remains unobserved.

## Heartbeat fault model

The candidate typed door is the `sendHeartbeat` RPC invoked by `BPServiceActor.sendHeartBeat` at line 563. `offerService` catches an `IOException` at line 786 and retries. On a successful reply, `offerService` calls `updateActorStatesFromHeartbeat` at line 725 **before** enqueuing that reply's commands at line 737. Consequently, a failed heartbeat skips both the state update and commands from that reply; the exception itself does not clear `bpServiceToActive`.

`BPOfferService.updateActorStatesFromHeartbeat` can set `bpServiceToActive` to a newer active actor or clear the prior actor after its standby reply. Its command processor handles `DNA_RECOVERBLOCK` only if the issuing actor is currently recognized as active. That launches a separate `BlockRecoveryWorker` daemon, whose `syncBlock` later calls the selected check. A newly delivered recovery command after a successful heartbeat thus follows the state update. A null `activeNN` at the check would require a particular cross-thread interleaving involving an already queued task and a later actor-state change. The source does not establish that interleaving for this test or tie the one-shot failed heartbeat to that task.

The pinned v11 adapter has recovery-task handoff hooks but no typed heartbeat reply/status hook. It cannot by itself attest the same heartbeat response, DataNode epoch, recovery command, and worker occurrence. A fault/full campaign is therefore not admitted. A future named healthy run, if dispatch grants a separate HDFS lane, must pass JUnit 1/0/0, reach the exact nonthrowing check on a named DataNode, and show a strict observed path. A separate causal correlation design would still be required before fault promotion.

Run `python3 -B check_offline.py` to verify the pinned source, class bytes, archived seed, call ordering, selector, and adapter gap without starting a JVM.
