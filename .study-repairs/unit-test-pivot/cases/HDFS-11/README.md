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
