# HDFS-14: block token password comparison

The graph-independent campaign runs the original Hadoop 3.4.3 embedded
cluster JUnit `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
Its default `MiniDFSCluster` has one NameNode and one DataNode. Case-local ASM
hooks record the selected `BlockTokenSecretManager.checkAccess` comparison
`MessageDigest.isEqual(retrievePassword(id), token.getPassword())` at released
source line 411 and the corresponding `InvalidToken` throw at line 412.

Both independent healthy instrumented runs passed and reached the selected
comparison twice with matching passwords. Three actual socket-read call sites
in `SaslDataTransferServer.doSaslHandshake` supply I/O fault points; JaCoCo
supplies production coverage feedback. A calibration EOF at the first socket
read matched and applied exactly once. The original JUnit still passed, and
both comparison checks ran after the fault with matching passwords.

Fault plans identify an I/O marker, call site, logical DataNode source, hit
ordinal, and exception type. A sequence contributes coverage or I/O feedback
only when every requested exception matches and applies in order and the
selected comparison executes after the final exception. The fixture's only
DataNode is mapped to logical source `hdfs/datanode/0`; this case does not
claim a multi-DataNode run.

The tmux session `hdfs14-independent-campaign` uses the atomic checkpoint
`independent/campaign-state.json` and writes each trial's duration and outcome
to `independent-trial-ledger.csv`. Its initial budget is 80 trials and up to
eight ordered exceptions, with an extension to 128 trials and ten exceptions
only for recent valid production coverage or stable I/O novelty. An observed
selected throw is a candidate for replay and source review.

The prior two region-woven trials are preserved in
[legacy-graph-result.json](legacy-graph-result.json) and excluded from the
current campaign.
