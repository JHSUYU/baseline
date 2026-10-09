# HDFS-12: block-token key lookup

The selected Hadoop 3.4.3 check is
`BlockTokenSecretManager.retrievePassword(BlockTokenIdentifier)`.
`allKeys.get(keyId)` is at source line 509, the null guard at 511,
and its `InvalidToken` throw at 512. The selection-list line 514 is
part of the error message.

Two unchanged `TestEncryptedTransfer` JUnit children supplied the
embedded `MiniDFSCluster` workloads:
`testEncryptedReadDefaultAlgorithmCipherSuite[0]` for encrypted reads
and `testLongLivedClient[0]` for key rotation. The healthy executions
reached the selected guard without taking its fatal outcome.

The historical campaign ran 22 fault trials: eight SASL read trials and
14 key-update trials across heartbeat and Hadoop IPC I/O. Eighteen
retained the target after injection; four lost it. The result records
44 injected fault events and 21 fully applied sequences under the old
accounting. No trial produced the selected `InvalidToken`.
Scoped coverage gained 12 branch outcome pairs in the SASL campaign and
16 in the key-update campaign; these used different instrumentation
scopes and cannot be added. Recorded elapsed time was 867.342 seconds.

The earlier 22 trials leave the current 48-trial budget and further
target-retaining I/O variants open. No new bug was confirmed. The
machine-readable [result](../cases/HDFS-12/result.json) retains trial
counts, measured times, and case evidence.
