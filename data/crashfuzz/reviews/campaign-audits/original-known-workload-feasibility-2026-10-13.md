# Original JUnit workload feasibility for known HDFS and Solr cases

Source reviewed: Hadoop 3.4.3 and Solr 8.11.4 release trees. These controls use
unchanged upstream JUnit methods and the generic Soot-selected CrashFuzz runner.
The separately adapted or precisely replayed controls are not counted as
generic-fuzz detections.

| Case | Unchanged JUnit and source path | Necessary path reached by the workload | Current generic-fuzz result |
| --- | --- | --- | --- |
| HDFS-17897 / HDFS-54 | `TestFileChecksum.testStripedAndReplicatedFileChecksum2[0]`; `FileChecksumHelper.StripedFileNonStripedChecksumComputer.checksumBlocks` | Striped checksum runs, but `TestFileChecksum.setup` sets block access tokens without setting `dfs.encrypt.data.transfer`. The configuration default is `false` (`DFSConfigKeys.java:1382`), so this JUnit does not create a stale data-encryption-key SASL failure. | No target `PathIOException` after the tested faults as of this audit. A failure produced by an unrelated I/O exception would not establish HDFS-17897. |
| HDFS-17897 alternative | `TestEncryptedTransfer.testFileChecksumWithInvalidEncryptionKey` | This original test enables encrypted transfer, expires the client's key, and checks the replicated-file checksum. It never creates an erasure-coded file. The replicated checksum path already catches `InvalidEncryptionKeyException`, clears the key, and retries (`FileChecksumHelper.java:536-545`). | It exercises the recovery counterpart, not the missing striped-file catch. No unchanged JUnit found in the Hadoop 3.4.3 HDFS test tree that both enables encrypted transfer and performs a striped-file checksum. |
| HDFS-17899 / HDFS-55 | `TestBalancerWithEncryptedTransfer.testEncryptedBalancer0`; `Dispatcher.PendingMove.dispatch` | The JUnit enables encrypted transfer and executes Balancer block moves. The release `dispatch` catches general `IOException` without clearing the cached key (`Dispatcher.java:394-429`). Its current HDFS-55 target is a cache branch in `KeyManager.newDataEncryptionKey`, which has no target exception oracle. | 80 completed generic-fuzz trials; typed one-shot SASL exceptions were injected, but this is not evidence of a stale key retained across moves. No target exception candidate. |
| HDFS-17899 Balancer and HDFS-17967 proxy / HDFS-11 | Same unchanged Balancer JUnit; `Dispatcher.PendingMove.dispatch`, `DataXceiver.replaceBlock`, and `BlockTokenSecretManager.retrieveDataEncryptionKey` at `allKeys.get(keyId)` | The healthy trace observes 15 Balancer dispatches and 15 `replaceBlock` proxy SASL calls. The Soot selection includes these calls, DataNode handshake, key-updater RPC, and the exact `InvalidEncryptionKeyException` throw. The default block-key update interval and token lifetime are both 600 minutes (`DFSConfigKeys.java:1060-1063`, interpreted as minutes in `BlockManager.java:710-718`); the JUnit timeout is 60 seconds. A natural key rotation is therefore not expected in this workload. | Running in an isolated campaign. This Balancer workload has not itself produced the exact target throw after a fault; its result must remain separate from the pipeline-recovery workload below. |
| HDFS-17967 mirror and HDFS-17899 DataNode transfer | `TestEncryptedTransfer.testLongLivedClientPipelineRecovery[0]`; `DataXceiver.writeBlock` mirror SASL and `DataNode.DataTransfer.run` | This original four-DataNode JUnit enables encrypted transfer, reduces the key-update interval and token lifetime to 2 seconds, clears old keys, and induces pipeline recovery after stopping a DataNode (`TestEncryptedTransfer.java:376-437`). Its passing healthy trace observes both outbound I/O methods, the NameNode heartbeat RPC, and one expected receiver-side `InvalidEncryptionKeyException` from the client retry path. Soot selects 138 I/O calls and 400 coverage methods without a manual I/O list. A post-call heartbeat failure can prevent a `DNA_ACCESSKEYUPDATE` reply from being queued on one DataNode (`BPServiceActor.java:703-739`), while `BPOfferService.java:779-784` updates local keys only when the command is processed. | **No fault-induced target exception detected in the first 174 trials.** The 55.859-second figure is only the first post-fault *observation* of the same exception the healthy JUnit deliberately triggers once: seed 27.151 seconds and trial 1 28.708 seconds. In that trial, a synthetic handshake failure applied at trace seq 698 on one DataXceiver, while the exact `BlockTokenSecretManager.retrieveDataEncryptionKey` throw at source line 555 occurred later at seq 954 on another DataXceiver. The healthy trace already has the same exact throw at seq 932. No strictly injected trial through 174 has more than the healthy run's one target throw. The separate `CHECK_REACHED` hook missed trial 1, but repairing that bookkeeping does not make its exception new. The campaign resumed from its checkpoint after this correction. |
| HDFS HA alternative | `TestFailoverWithBlockTokensEnabled.TestFailoverAfterAccessKeyUpdate` | This original JUnit shortens block-key update intervals and fails over between NameNodes, but its setup creates only one DataNode and enables block access tokens without `dfs.encrypt.data.transfer` (`TestFailoverWithBlockTokensEnabled.java:67-77, 157-205`). | Excluded for the `DataXceiver.writeBlock` encrypted mirror and `allKeys.get(keyId)` target: no downstream DataNode or encrypted data-transfer handshake exists in this workload. |
| SOLR-40 | `TimeRoutedAliasUpdateProcessorTest.test` | The original four-node JUnit creates a time-routed alias and immediately adds a document (`TimeRoutedAliasUpdateProcessorTest.java:132-139`). `ZkStateReader.AliasesManager.process` reads the watched alias data; on `ConnectionLossException` it logs and leaves the local cache as-is (`ZkStateReader.java:2302-2317`). The generic Soot selection includes that callback's `getData` I/O sites. | **Detected by the generic selector and unchanged JUnit.** The healthy run had zero target `SolrException` throws. In campaign trial 31, the first of two selected faults applied to alias-watch `getData` on `node2` at trace seq 3776; the same node reached `getAliasProps` at seq 3805 and threw at seq 3810. The second planned fault did not occur, so the full two-fault plan is `unmatched`. Replaying its tool-selected, actually applied one-fault prefix as a strict single-fault plan reproduced the same target throw in attempt 3 of 3; attempts 1 and 2 injected successfully and reached the check without a throw. The failing replay trace shows fault seq 3777, target check seq 3805, and target throw seq 3810. This is a reproducible fault-induced target exception, not a healthy-run recurrence. |

The original HDFS-17897 JUnit choices each cover only one half of the required
encrypted striped-checksum path. The encrypted pipeline-recovery JUnit is the
strongest unchanged workload for the DataNode mirror and transfer paths because
it combines key rotation with observed outbound SASL I/O. The Balancer
workload reaches its relevant operations; its remaining question is whether
a generic fault sequence produces a stale-key state and reaches the target
afterward.

SOLR-40 timing: the generic campaign first observed the fault-induced target
throw 2,102.391 seconds (35 minutes 2.391 seconds) after its checkpoint's
`started` timestamp, at trial 31. Because the second requested fault was
unmatched, this was a candidate observation. Three subsequent strict replays
of the automatically selected one-fault prefix took 24.690, 24.936, and
17.920 seconds of JUnit execution, respectively; the third reproduced the
target throw. Their combined execution time was 67.546 seconds. The replay
log shows `CREATEALIAS` returned status 0 before the original test's first
document add at line 138 failed with the routed-alias exception. The strict
replay evidence is on node2 in
`static-rerun/original-known/SOLR-40/replay-prefix31-general/attempt-03`;
the original trial is in
`static-rerun/original-known/SOLR-40/campaign-node-identity-v4/SOLR-40/trials/0031-a002453e128d7bc6206c`.
A compact event and timing record is in
`data/crashfuzz/evidence/SOLR-40/original-generic-fuzz-2026-10-13.json`.
The fuzzer now labels an unmatched full plan as a partial target exception
candidate when its actually applied faults exactly match a nonempty prefix
of the selected plan and the target exception exceeds the healthy count.
It retains the full-plan mismatch in the result, so strict full-sequence
statistics are not inflated. The node2 campaign loaded the older runner at
startup; this result was identified by direct audit of its saved trace and
validated by strict prefix replay.

The HDFS mirror campaign remains open. Its healthy JUnit intentionally causes
one exact `InvalidEncryptionKeyException` at `allKeys.get(keyId)`. A faulted
run that shows only that same expected throw is `baseline_exception_recurrence`
and has no detection time. Through trial 189, no strict faulted run produced
an additional exact target throw.

The original pipeline-recovery test explicitly waits until **every** DataNode
has discarded the client's cached key before it appends and forces recovery
(`TestEncryptedTransfer.java:407-437`). This explains the healthy target throw:
the first DataNode approached with that stale client key rejects it, and the
client clears the key. It also narrows the window for a distinct downstream
DataNode key mismatch. Such a mismatch would require a later divergence among
DataNodes after this wait, rather than just the stale client key that the test
deliberately creates. Faults that merely recreate the single client-retry
throw are therefore not counted even when they precede it in the trace.
For example, trial 70 failed its JUnit assertion because two synthetic
`InvalidEncryptionKeyException` failures made `clearDataEncryptionKey()` run
twice, while its exact `allKeys.get(keyId)` throw still occurred only once.
That is a failure of the chosen faulted workload, not evidence of the target
coordination bug.
The Soot-generated HDFS selection does include the relevant general RPC
families: `ClientNamenodeProtocolServerSideTranslatorPB.getDataEncryptionKey`
(`io_calls` site `#u5`), `BPServiceActor.sendHeartBeat` (`#u75`), and
`DataNode.DataTransfer.run` (`#u64`). It also includes
`KeyManager$BlockKeyUpdater.run` (`#u8`) for the Balancer path. These are
selected by the static scope rather than declared as manual fault sites.
After the cross-node scheduler began using confirmed runtime node identities,
trial 242 selected post-call heartbeat `IOException` faults on distinct
DataNodes `data7` and `data5`. Both faults applied in order and the target was
reached afterward, but the exact target throw count was still one, matching
the healthy test. This is a valid cross-node trial and not a detection.
The first HDFS mirror budget terminated after 261 completed trials, including
230 strict fault-plan matches, 113 trials with at least two applied faults,
and 180 retained target trials. Its result had zero target-exception
candidates: 239 trials had one exact target throw and 22 had none; no trial
had more than the healthy run's one throw. The confirmed logical-node
diversity rule was active only near the end of that budget. The same
checkpoint was therefore resumed with a larger budget of 300 retained target
trials and a 450-trial cap, without changing the original JUnit, target, or
Soot-selected I/O scope.

A separate identity validation used the unchanged
`TestEncryptedTransfer.testLongLivedClientPipelineRecovery[0]` JUnit with the
same Soot selection and a separately packaged runtime agent. The test passed
in 26.451 seconds. Both observed `DataNode.DataTransfer.run` I/O events now
carry the owning `hdfs:dn:data1` runtime identity, obtained from the task's
enclosing DataNode. This repairs a generic actor identity gap for outbound
DataNode replication; it does not select an I/O callsite or establish a bug.
The running 450-trial campaign retains its original agent and checkpoint so
its results are comparable. The validation trace is under
`static-rerun/original-known/HDFS-17967-mirror/identity-healthy-validation`.

I also audited the 249 saved trials that had exactly one target throw through
trial 271. In every corresponding JUnit log, the missing key ID from the
exact `allKeys.get(keyId)` throw appeared in the subsequent
`DataStreamer.continueRetryingOrThrow` message saying the client would fetch
a new encryption key and retry. Seven trials had an earlier client retry
caused by a synthetic `InvalidEncryptionKeyException`; I checked the later
retry separately and matched its key ID to the real target throw. Runs where
the current key advanced further still followed this expected client recovery
path. None shows a distinct mirror or DataTransfer key mismatch at the
target check.
Through trial 286, I separately inspected 50 mirror-transfer error log
sections in runs with one exact target throw. Twenty-six report a synthetic
injected exception, nineteen report EOF, and five report a connection reset.
None contains the missing key ID from that run's exact line-555 throw. The
mirror errors therefore do not identify the observed target throw as a
downstream mirror key mismatch.

The original JUnit explicitly waits until each DataNode has discarded the
client's cached key, then verifies one `clearDataEncryptionKey()` call after
pipeline recovery (`TestEncryptedTransfer.java:488-518`). That one target
throw is part of its expected client retry. In the NameNode's heartbeat
handler, `BlockManager.addKeyUpdateCommand` adds `KeyUpdateCommand` and clears
`needKeyUpdate` before the DataNode receives the response
(`BlockManager.java:1671-1678`); the DataNode enqueues that command only after
`sendHeartBeat` returns (`BPServiceActor.java:742-755`). This makes a lost
response a plausible source of key skew, but the current I/O trace does not
record whether a particular faulted response carried a key update command.
Through trial 293, 37 completed plans applied a fault at the selected
`sendHeartBeat` I/O site (77 such fault events in total; eight plans involved
multiple DataNodes). Thirty retained the target and each still had exactly
the one expected throw; six lost the target and one plan was unmatched. These
trials establish that the general selector reached the control-plane RPC,
not that it interrupted a key-bearing response or reproduced the bug.

A second isolated validation added actor-thread identity propagation for
DataXceiver and DataTransfer helper calls. The unchanged JUnit passed in
26.900 seconds. Its trace identifies all 27 selected server-side SASL I/O
events by DataNode, both outbound DataTransfer I/O events, and the exact
line-555 target throw's DataNode. The client-side SASL calls from ordinary
client threads remain unbound, as expected. The trace is under
`static-rerun/original-known/HDFS-17967-mirror/identity-healthy-validation-v3`.
An independent 80-trial campaign using this agent and the same Soot selection
was started in `campaign-identity-v2`; its original JUnit, target, and fault
types are unchanged. It is separate from the ongoing 450-trial checkpoint.

A further generic post-call probe records the return object's class and the
element classes of its immediate object-array fields. With this probe, the
same unchanged JUnit passed in 27.096 seconds. Its healthy trace had 24
selected `sendHeartBeat` post-call events: eight responses contained
`KeyUpdateCommand` and sixteen had an empty command array. This gives the
fuzzer an observed, replayable distinction between key-bearing and empty
responses without naming the heartbeat callsite in the selector. The trace
is in `response-shape-healthy-validation/runtime_trace.jsonl`. This validation
is not a fault-injection result or a bug detection.
The separate `campaign-response-shape-v1` uses this healthy trace, the same
unchanged JUnit, and the same Soot-selected I/O sites, with a 40-trial pilot
and a 10-fault sequence cap. Trial 6 strictly applied a post-call reply-loss
fault to `data7`'s `sendHeartBeat` response whose recorded object array
contained `KeyUpdateCommand` (trace seq 896). The exact target throw later
occurred on `data7` (seq 960), but it was still the single expected stale
client-key rejection and was followed by the normal client retry. The trace
also shows another key-bearing response to `data7` at seq 922, before that
throw. Trial 8 automatically extended the sequence to lose `data7`'s two
key-bearing responses at hit ordinals 6 and 8, with one intervening empty
response; its one exact target throw occurred on `data3`. Neither trial is
a bug detection. The campaign checkpoint and per-trial evidence remain under
`campaign-response-shape-v1/HDFS-17967-MIRROR`.

The response-shape pilot completed its first 40 trials in 1,590.984 seconds
of wall time: 26 reproduced the healthy run's one expected target exception,
five did not reach the target, five did not fully match the requested fault
sequence, and four completed checks without a differential target exception.
No trial exceeded the healthy baseline of one exact target throw. The same
checkpoint has been resumed with a 120-trial base budget, an 80-trial
target-retained minimum, and a 160-trial cap; the first 40 trials are not
rerun. The separate runtime-identity pilot completed 80 trials with no
differential target exception (45 baseline recurrences, 14 lost target, ten
unmatched, and eleven checked). Its maximum exact target count was one.

Trial 64 exposed a generic replay limitation: its automatically selected
three-DataNode plan targeted the same nonempty `sendHeartBeat` response shape
on three distinct DataNodes, but their replies arrived in a different order
than in the seed trace. The ordered matcher therefore applied only one of
three requested faults. The runtime matcher and strict result checker now
accept any arrival order for a complete plan of equivalent post-call replies
on distinct nodes; all other plans retain ordered matching. Two direct
replays of trial 64 against the unchanged original JUnit applied all three
faults, including one replay whose applied order differed from the plan.
They finished in 33.865 and 33.519 seconds, respectively, and each still
observed exactly the one target exception present in the healthy run. These
are replay validation results, not bug detections. The response-shape
campaign resumed from its existing checkpoint with an isolated build of the
new matcher; completed trials 1–77 were retained without rerunning them.

To keep the three active HDFS runs within disk capacity, completed attempts
from the first 250 trials of `campaign-control-branch` were checksum-verified
on node1 before their local attempt directories were removed. Their final
`result.json` files, fault plans, and live checkpoint remain on node0. The
archive receipt is `.archive-attempts-0001-0250.json` in that campaign
directory.
The next 70 completed control-branch trials were verified and archived under
`.archive-attempts-0251-0320.json`. Completed attempt logs from the terminal
runtime-identity pilot were similarly verified and archived under
`.archive-attempts-0001-0080.json` in its campaign directory. Final results,
fault plans, and checkpoints remain on node0.

The response-shape pilot's completed attempts 1–40 were checksum-verified on
node1 before removal from node0; its receipt is
`campaign-response-shape-v1/HDFS-17967-MIRROR/.archive-attempts-0001-0040.json`.

Evidence roots: `static-rerun/original-known/HDFS-54`, `HDFS-55`,
`HDFS-11-balancer`, and `HDFS-17967-mirror` on node0, and
`static-rerun/original-known/SOLR-40` on node2.
The audited Soot artifacts and exact JUnit identities are retained beside
each campaign. The generic trials remain distinct from the known-bug
calibrations in `crashfuzz/known-bug-controls/`.

The previous SOLR-40 campaign is archived on node2 as
`static-rerun/original-known/SOLR-40/campaign-postcall-identity-v3.tar.gz`
(SHA-256 `f022a8eafcea3eeab75bca3d41d94f3bfc67c86c610f205356e1aa885c3d6b13`).
Its exact JUnit, selection, checkpoint, fault plans, results, and logs can be
restored from the archive; it was stopped after 98 trials to test the improved
runtime identity without filling the node's disk.
