# HDFS-16 exact actor recheck

The workload is the unchanged Hadoop 3.4.3 JUnit
`TestClientProtocolForPipelineRecovery#testUpdatePipeLineAfterDNReg` in its
original 1 NameNode/2 DataNode `MiniDFSCluster`. It chooses the first actual
DataNode, marks that DataNode dead, re-registers its real
`DatanodeRegistration`, then updates the same pipeline twice. The selected
check is `BlockInfo.setGenerationStampAndVerifyReplicas(long)` line 428:
`Preconditions.checkState(uc != null && !isComplete())`. This is a local
under-construction block invariant reached from the distributed recovery
workload; its presence alone does not establish an ad hoc coordination bug.

The historical 80-trial source-probe campaign remains in
`../independent-coverage-io/`. Its global RPC response ordinals could not
distinguish the two background DataNode registration actors. Its 40
target-retaining trials are historical observations, not V3 effective trials.
The read-only audit is `../actor-identity-readonly-audit.md`.

V3 registers each `DataNode` object before its BP actor starts, then binds the
actual `BPServiceActor.run` to that object and original NN endpoint. The
released `DatanodeProtocolClientSideTranslatorPB.registerDatanode` receives
the raw `DatanodeRegistration` UUID and block-pool ID. The actual
`Client.getRpcResponse` provides the raw NN endpoint and IPC call ID; the
NameNode edit-log flush is a separate local I/O door. The original target
reports block ID, generation-stamp phase, and the selected DN's raw UUID,
normalized actor key, and block-pool class. Fault plans match marker, API,
actor, peer class, pool class, actor-local ordinal, and exception. Runtime
gating also compares the raw NN endpoint and selected DN UUID within the
same run. No ordinal or normalized actor alone proves an actor match.

The `RPC_RESPONSE` marker is emitted on entry to `Client.getRpcResponse`,
before that method waits for the reply. A matched exception can therefore
occur while the NameNode is still processing the same request. A target event
after the fault proves temporal, same-actor, same-block reachability under the
stated gate; it does not by itself prove the fault caused that target event.
The target site is also called from `BlockInfo.commitBlock` while the test
closes its stream or cluster. The trial ledger retains the target caller so
these cleanup reaches are distinguishable from
`BlockManager.updateLastBlock` pipeline-update reaches in the final review.

Two fresh healthy original JUnit runs on node1 passed under the shared
`jvm-start.lock`: 2026-10-07 10:56:47–10:57:20 UTC and
10:58:23–10:58:57 UTC, with 29.556/30.414 seconds of JUnit execution.
Both reached the same block ID 1073741825 target three times; registration
UUIDs varied across seeds but each seed's DN0 background registration,
manual registration, and target UUID matched. DN1 had a separate UUID and
object actor. All 36 admitted pretarget I/O selectors were stable across the
seeds. Offline wrong actor, UUID, block pool, and NN peer controls rejected.
The receipt and raw traces are in node1's `actor-v3/healthy/` and
`healthy-receipt.json`.

The `campaign.py` queue is independent of the historical 80 plans. It
mutates ordered I/O exception sequences using new observed I/O families and
JaCoCo production probe, method, and branch feedback. A V3 effective trial
requires all planned faults to match and apply in order, the same actual DN
registration to join the target, the same raw NN endpoint, and the selected
block's target check after the final fault. An injected workload failure is
recorded separately. The bug oracle is the selected
`IllegalStateException` after a strict fault and target match; a candidate
pauses for source review and exact replay. The budget is 80 effective trials
with at most 8 faults, extended to 128/10 only if the final eight effective
trials at 80 reveal new coverage or I/O families. The checkpoint and every
trial's time, trace, plan, JUnit log, and coverage live under node1's
`actor-v3/campaign/`. `audit_v3.py` reconstructs counts from those raw
artifacts.

Launch from node1 after the two healthy seeds and resource gate:

```sh
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HDFS-16/actor-v3
tmux new-session -d -s hdfs16_actor_v3_campaign \
  'python3 campaign.py >> campaign/controller.log 2>&1'
```

The controller uses a case-local lock and the shared JVM launch lock,
requires at most four existing Java processes and at least 10 GiB free disk
before launching each JUnit, and resumes from `campaign/checkpoint.json`.

The bounded five-trial pilot ended at 2026-10-07 11:09:43 UTC. All five
faults matched and applied, the same selected block's target ran after each
fault, and no target exception occurred. All five original JUnit methods
exited with an injected exception, recorded as workload failures rather than
target bugs. The initial pilot controller mistakenly required JUnit exit zero
for feedback. `migrate_target_only_oracle.py` preserved its checkpoint and
all original logs, then reclassified the five raw trials as 5/5 effective
with **zero JUnit reruns**. Independent JaCoCo feedback against the union of
the two healthy seeds found 343 new production probes, 71 methods, and 174
branch units; no new I/O family. The pilot audit and migration receipt are
`campaign/audit-v3.json` and
`campaign/oracle-migration-target-only/receipt.json`. The full campaign
resumed from this same five-trial checkpoint in node1 tmux
`hdfs16_actor_v3_campaign` at 2026-10-07 11:11:39 UTC.

## Terminal result

The original-JUnit campaign ended naturally at 2026-10-07 14:03:43 UTC:
92 attempted sequences, 92 exact ordered injections (257 matched/applied fault
events), and 80 same-actor, same-block postfault target-retaining sequences.
Twelve attempts lost the selected target and were excluded from the effective
budget. All 85 JUnit workload failures contained the injected exception;
there was no bind, port, out-of-memory, or selected target exception event.
The longest original faulted JUnit was 32.172 seconds. The measured JUnit sum
was 2,242.103 seconds; the elapsed wall time from the first healthy seed to
the terminal trial was 11,216.122 seconds, including shared-node queueing.

Independent raw replay of the gate and JaCoCo feedback passed for all 92
trials. The gain over the union of the two healthy seeds was 386 production
probes, 74 methods, and 195 branch units, with no new I/O family. The final
eight effective trials added no coverage or I/O family, so the predeclared
budget stopped at 80 effective trials and at most eight faults. In all 80
effective trials the target ran through `BlockInfo.commitBlock` after the
final fault; 55 also ran through `BlockManager.updateLastBlock`. The remaining
25 had only the commit/cleanup caller after the final fault. This is target
reachability under the specified gate, not evidence that an injected fault
caused the target to execute. Source review identifies the selected check as
a local under-construction invariant; no new bug is confirmed.

The node0 snapshot under `final-evidence/` contains the independent audit,
per-trial ledger, compressed terminal checkpoint, healthy receipt, and
terminal SHA receipt. All 92 original trace, plan, JUnit, and JaCoCo files
remain under this case path on node1. The tmux campaign exited at the
terminal budget boundary.
