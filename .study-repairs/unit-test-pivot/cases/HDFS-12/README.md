# HDFS-12: block token key lookup

The current graph-independent campaign runs the original Hadoop 3.4.3
embedded-cluster JUnit
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
The default `MiniDFSCluster` has one NameNode and one DataNode. Two independent
healthy instrumented runs both passed and each reached the selected
`BlockTokenSecretManager.retrievePassword` null-key check twice. Both checks
found the requested key. The shorter JUnit seeded the first bounded campaign;
the related original `testLongLivedClient[0]` is now also being run in an
independent supplement because it rotates block-token keys during a
15-second sleep and then reaches this lookup with a new key ID.

Case-local ASM hooks record the precise `retrievePassword` null-key check and
its `InvalidToken` throw. Other hooks observe the three actual socket-read
calls in `SaslDataTransferServer.doSaslHandshake`, and JaCoCo records
production code coverage. Plans match the I/O marker, call site, logical
DataNode source, hit ordinal, and exception type. A trial contributes feedback
only when all requested exceptions match and apply in order and this target
check executes again after the final exception. The fixture has only one
logical DataNode; this case makes no claim about larger HDFS topologies.

An initial EOF fault at the first SASL read matched and applied exactly; the
original JUnit passed and reached the target twice afterward. Its trace and
coverage seed the resumable campaign in tmux session
`hdfs12-independent-campaign`. The checkpoint is
`independent/campaign-state.json`; the per-trial time and result ledger is
`independent-trial-ledger.csv`. The initial budget is 80 trials with up to
eight ordered I/O exceptions; recent valid production coverage or stable I/O
novelty can extend it to 128 trials with up to ten exceptions. A target throw
is a candidate for replay and source review, not automatically a new bug.

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
independent 80-trial coverage/I/O campaign is live in node2 tmux
`hdfs12-control-campaign` and mirrored into the 102-case table by node0 tmux
`hdfs12-control-sync`. The [supplement details](independent/long-lived/control-plane/README.md)
give the runtime identities, budgets, checkpoint and result files. Its
trials remain separate from the 128 completed ordinary-read trials.
