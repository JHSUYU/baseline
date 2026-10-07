# HDFS-12: block token key lookup

**Actor V2 bounded campaign complete.** Two independent healthy runs of
Hadoop 3.4.3 `TestEncryptedTransfer#testLongLivedClient[0]` passed. The
case-local [V2 overlay](actor-producer-v2/) binds each fault and later selected
`BlockTokenSecretManager.retrievePassword` guard to the same concrete DataNode
startup episode and block pool. The durable node1 checkpoint is
`actor-producer-v2/evidence/HDFS-12/campaign-state.json`; tmux session
`hdfs12_actor_v2_budget` ran one JUnit child at a time. The
[full 117-attempt audit](actor-v2-final-117-attempts.json) verifies 99 ordered
full fault sequences and 80 strict same-actor target-retaining sequences. It
records each raw trace, JUnit manifest, fault plan, result, and JaCoCo hash.
The other 37 attempts lost the selected target after injection or failed to
match all requested faults; those do not count toward the effective budget.
No run took the selected null-key `InvalidToken` throw. All three observed
fault families were tested with a retained target: key-update RPC response
(71 sequences), local key apply (21), and SASL read (50); a sequence can contain
more than one family. Faulted runs added 253 probes, 29 methods, and 121
branch-count buckets relative to healthy seed A. No new I/O family appeared
relative to the two healthy seeds' union.

The original test sets 2-second key rotation and token lifetime, sleeps 15
seconds, then reads and checksums the file again. In Hadoop 3.4.3 source,
`retrievePassword` reads `allKeys.get(identifier.getKeyId())` at line 509 and
throws the selected `InvalidToken` only when the key is null at lines 511–514.
The earlier expiry exception at lines 503–505 is a separate branch. The
campaign reached 80 effective sequences with at most eight faults; its final
eight effective runs had no new coverage or I/O family, so the planned
128-sequence extension did not activate. The 2,040 queued mutations remain
untested under this budget; the result is no observed selected exception in
this bounded search, not a claim about all schedules.

## Historical campaigns

The 256 archived trials and their reported coverage/time remain historical
observations. Their SASL selector hard-coded `hdfs/datanode/0` and a global
call-site ordinal; the original JUnit recreates MiniDFSCluster, so those
traces cannot prove that each post-fault guard ran on the faulted DataNode
incarnation. Historical counts below are excluded from the V2 effective budget.

The archived graph-independent campaign ran the original Hadoop 3.4.3
embedded-cluster JUnit
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
The default `MiniDFSCluster` has one NameNode and one DataNode. Two independent
healthy instrumented runs both passed and each reached the selected
`BlockTokenSecretManager.retrievePassword` null-key check twice. Both checks
found the requested key. The shorter JUnit seeded the first bounded campaign.
The related original `testLongLivedClient[0]` was also run in an independent
supplement because it rotates block-token keys during a 15-second sleep and
then reaches this lookup with a new key ID.

Case-local ASM hooks record the precise `retrievePassword` null-key check and
its `InvalidToken` throw. Other hooks observe the three actual socket-read
calls in `SaslDataTransferServer.doSaslHandshake`, and JaCoCo records
production code coverage. Plans match the I/O marker, call site, logical
DataNode source, hit ordinal, and exception type. A trial contributes feedback
only when all requested exceptions match and apply in order and this target
check executes again after the final exception. The fixture has only one
logical DataNode; this case makes no claim about larger HDFS topologies.

The ordinary-read campaign completed 128 trials with up to ten ordered I/O
exceptions. All 128 injections matched in order; 50 trials reached the exact
target afterward. No trial observed the selected null-key `InvalidToken`
throw. Its checkpoint is `independent/campaign-state.json` and its per-trial
time and result ledger is `independent-trial-ledger.csv`.

The earlier 22 region-woven trials remain in
[legacy-graph-result.json](legacy-graph-result.json) and do not contribute to
the current campaign's counts.

## Long-lived-client control-plane supplement

The unchanged `testLongLivedClient[0]` passed under case-local instrumentation
and reached this selected lookup four times using two key IDs. Its healthy
trace also observed seven DataNode heartbeat RPCs and three received
active-NameNode key-update commands between the early and late checks. Two
exact one-fault calibrations, one at a heartbeat and one at a key-update
command, both preserved the late target checks and passed JUnit. The
control-plane campaign completed 128 additional trials with up to ten ordered
I/O exceptions. Raw-event audit found 114 exact ordered injections, 86
subsequent target checks, and 86 checks using a rotated key ID. None took the
selected null-key throw. Across both original JUnits, the total is 256
trials, 242 strict injections, and 136 target-retaining trials. Raw event
audits are in `independent/audit-all.json`, and the independent evidence is
archived with its SHA-256 recorded in `independent-archive-manifest.json`.
The [supplement details](independent/long-lived/control-plane/README.md)
give the runtime identities, checkpoint, and result files. This result is a
completed search within these two JUnit workloads and budgets, not a proof
that no defect exists elsewhere.
