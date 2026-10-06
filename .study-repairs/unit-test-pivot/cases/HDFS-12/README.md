# HDFS-12: block token key lookup

The current graph-independent campaign runs the original Hadoop 3.4.3
embedded-cluster JUnit
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
The default `MiniDFSCluster` has one NameNode and one DataNode. Two independent
healthy instrumented runs both passed and each reached the selected
`BlockTokenSecretManager.retrievePassword` null-key check twice. Both checks
found the requested key. The related original `testLongLivedClient[0]` also
passed without instrumentation, but its planned key expiry and 15-second sleep
make the shorter JUnit a better seed for this target.

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
