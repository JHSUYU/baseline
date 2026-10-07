# HDFS-11: encrypted transfer key lookup

**Actor V2 recheck running on node1.** Two fresh original Hadoop
3.4.3 JUnit seeds of
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]` passed.
The isolated [V2 follow-up](../../hdfs-key-actor-v2/README.md) binds the actual
SASL receiver and key manager to the same DataNode startup episode and block
pool. Its [87-attempt raw audit](actor-v2-segment-87-attempts.json) verifies 87
fully ordered fault sequences, 46 strict same-actor target-retaining sequences,
and zero selected `InvalidEncryptionKeyException` throws. The other 41
sequences lose the target after an injected-I/O checksum or block-read failure;
they are recorded but not effective. The audit hashes each original JUnit
manifest, raw trace, fault plan, result, and JaCoCo file. It reports 238 added
probes, 28 methods, and 123 branch-count buckets relative to healthy seed A,
and no new I/O family beyond the two healthy seeds' union. The already
finished in-flight JUnit manifest from the
[coexistence pause](../../hdfs-key-actor-v2/evidence/HDFS-11/coexistence-pause.json)
was consumed without starting another JVM, moving the durable node1 checkpoint
from 53/28 to 54/29. The
[supervisor](../../hdfs-key-actor-v2/run_hdfs11_budget_gate.py) now continues in
tmux `hdfs11_key_v2_fuzz` only when its startup gate sees fewer than five Java
processes. A selected target exception sets a durable review latch before any
later plan can start. The budget remains 80 effective sequences with up to
eight faults, conditionally extending to 128/ten for recent new coverage or I/O.
At attempt 87, four exact SASL `readMagic` exceptions exhausted the original
test's only DataNode and caused a `BlockMissingException` before a later target
check. Its [source and raw-event review](actor-v2-trial87-review.json) classifies
this as target loss, then the same checkpoint resumed without replaying it.

## Historical campaigns

The 208 archived fault trials and their reported coverage/time remain
historical observations. Their SASL selector hard-coded `hdfs/datanode/0` and
a global call-site ordinal; the original JUnit creates two MiniDFSCluster
incarnations, so those traces cannot prove that each post-fault guard ran on
the faulted DataNode incarnation. The counts below are excluded from V2.

The archived campaign ran the original Hadoop 3.4.3 embedded-cluster JUnit
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]` in a
fresh test directory for each trial. Its `MiniDFSCluster` has one NameNode and
one DataNode. The healthy original JUnit passed, and the independent
instrumented healthy runs observed the selected
`BlockTokenSecretManager.retrieveDataEncryptionKey` check twice. The target
is the `key = allKeys.get(keyId); if (key == null)` branch, whose selected
exception is `InvalidEncryptionKeyException`.

Case-local ASM hooks record that branch and the actual socket read call sites
in `SaslDataTransferServer.doSaslHandshake`. JaCoCo records production method,
branch-count, and probe coverage. Each fault plan specifies the I/O marker,
call site, logical DataNode source, hit ordinal, and exception type. The
controller verifies every requested match and application in order, then
requires another execution of the target check after the final fault before a
trial contributes feedback. The logical source identity is the fixture's sole
DataNode; this case does not claim coverage of a larger HDFS topology.

The independent campaign runs in tmux session `hdfs11-independent-campaign`.
It checkpoints every trial in `independent/campaign-state.json`, writes
per-trial times to `independent-trial-ledger.csv`, and updates `result.json`.
The initial budget is 80 trials and at most eight ordered exceptions. It grows
to 128 trials and ten exceptions only if recent valid trials add production
method or branch coverage, or a stable I/O family. A selected target exception
is a candidate for replay and source review; an ordinary JUnit failure is not
counted as that exception.

The normal-read campaign finished all 80 trials: 79 exact ordered injections,
37 trials that reached the check after the last fault, and zero selected
exceptions. Every target-retaining trial passed the original JUnit. The 43
remaining trials lost the selected check and are excluded from feedback. The
last eight trials added no production method or branch outcome and no new I/O
family, so the conditional 128-trial extension was not activated. This result
only covers the ordinary-read workload; it does not resolve the expired-key
control-plane scenario below.

The original workload accesses one short test file on the fixture's sole
DataNode. In each of the 37 target-retaining trials, all post-fault target
checks in the recorded trace used one key ID. This supports matching the
post-fault checks to that workload's block/key context; the recorder does not
claim a general cross-request identity mechanism for larger clusters.

The earlier 19 trials used a static-analysis/region-woven recorder. They are
preserved in [legacy-graph-result.json](legacy-graph-result.json) and excluded
from the current graph-independent result.

## Expired-key control-plane supplement

The normal read workload does not exercise key expiry. An independent second
campaign uses the original Hadoop JUnit
`TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey[0]`. Its
healthy embedded cluster deliberately expires the client's key, reaches the
selected `allKeys.get(keyId)` check with the old key absent, throws one
`InvalidEncryptionKeyException`, refreshes the key, and passes. Therefore one
such target exception is expected in every successful run and is **not** a bug
candidate by itself. The supplementary oracle flags additional target throws
after a matched fault for replay and source review.

The case-local ASM overlay also observes the DataNode heartbeat RPC and the
received active-NameNode key-update command, besides the SASL socket reads.
The healthy run saw two key-update commands before the stale-key check. A
checked exception at the received command killed the command processor and
removed the target, so that fault is excluded from further mutation. A
heartbeat `IOException` smoke matched exactly, left the target reachable,
observed the expected one stale-key exception, and passed the original JUnit.
This is a valid feedback seed, not a new bug.

The supplementary 80-trial, eight-exception campaign runs in tmux session
`hdfs11-expiry-campaign`. Its independent checkpoint, ledger, and result are
`independent/expiry/campaign-state.json`, `expiry-trial-ledger.csv`, and
`expiry-result.json`. The main result remains separate while both workloads
are running. No GraphChecker runtime or graph closure is involved.
After 32 completed trials, the campaign moved from node0 to node2 to avoid
node0's overloaded test queue. The original embedded-cluster JUnit passed on
node2 with the same five target checks, one expected stale-key exception, and
the same 15 SASL reads, six heartbeat RPCs, and two received key-update
commands. The first 32 sequence IDs and trial-32 trace match across hosts;
node2 resumed the previously active trial 33. The node0 tmux session
`hdfs11-expiry-sync` mirrors completed evidence and regenerates this case's
result and trial ledger every 30 seconds. The fixed migration boundary is in
`independent/expiry/migration-boundary.json`. On reconnect, inspect node2's
`hdfs11-expiry-campaign` and the local sync session before starting a writer.
The case-local `independent/expiry/audit.py` additionally checks every strict,
target-retaining trial for extra selected exceptions, absence of a successful
new-key lookup after a rejection, and original-JUnit failure after a selected
exception. It reports such outcomes as source-review candidates, not confirmed
bugs.

At completed trial 72, the expiry campaign's selection policy was updated at
the checkpoint without repeating a completed trial. The unfinished trial 73
remains the active sequence to replay. Subsequent choices favor I/O families
whose earlier strict trials preserved the target, with every fifth choice
reserved for broader exploration. If fewer than 24 of the first 80 trials
retain the target, the budget extends to 128 trials and ten faults; the
existing novelty-based extension also remains. The exact resume boundary is
in `independent/expiry/scheduler-handoff.json`.

The supplement finished all 128 trials under the ten-fault limit: 121 exact
ordered injections and 46 strict runs that reached the selected key lookup
after the final fault. All 46 passed the original JUnit. Every such run had
exactly the one stale-key exception expected by this JUnit, followed by a
successful lookup with a present replacement key. The independent trace audit
found no additional selected exception or unresolved key-refresh failure.
The supplement took 3,584.545 seconds. Together with the 80-trial ordinary
read campaign, this check has 208 trials, 200 exact injections, 83
target-retaining trials, and 6,032.198 seconds of measured execution.

The original Hadoop source establishes the oracle: the JUnit waits until the
old key disappears on the DataNode, calls `getFileChecksum`, asserts that the
client cleared its cached key exactly once, then retries and compares the
checksum. `BlockTokenSecretManager.retrieveDataEncryptionKey` throws when
`allKeys.get(keyId)` is null. Therefore the one stale-key exception is the
tested recovery behavior, not a newly discovered failure. The per-trial
records are in `expiry-trial-ledger.csv`; the full audit is in
`independent/expiry/audit-result.json`, with compact original traces and
manifests in `expiry-evidence.tar.gz`. Those workloads were previously marked
`quality_complete` under the coarse actor identity; the actor V2 recheck
above is now in progress. No new bug is confirmed for HDFS-11.

The separate [HDFS-17967 outbound-path calibration](known-bug-calibration/README.md)
shows a workload limit of those two campaigns: they do not exercise the
DataNode-to-DataNode mirror and proxy SASL paths fixed by that known PR.
Original multi-DN cluster JUnits reach both paths. A synthetic outbound
exception produces a local operation error but does not itself execute the
missing-key target branch, so it is not counted as an extra HDFS-11 target
exception or a new bug.
