# HDFS-11: encrypted transfer key lookup

The current campaign runs the original Hadoop 3.4.3 embedded-cluster JUnit
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

The earlier 19 trials used a static-analysis/region-woven recorder. They are
preserved in [legacy-graph-result.json](legacy-graph-result.json) and excluded
from the current graph-independent result.
