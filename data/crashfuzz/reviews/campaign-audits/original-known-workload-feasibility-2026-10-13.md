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
| HDFS-17899 target-check control / HDFS-11 | Same unchanged Balancer JUnit; `BlockTokenSecretManager.retrieveDataEncryptionKey` at `allKeys.get(keyId)` | The Soot selection includes the Balancer SASL call, DataNode handshake, key-updater RPC, and the exact `InvalidEncryptionKeyException` throw. The default block-key update interval and token lifetime are both 600 minutes (`DFSConfigKeys.java:1060-1063`, interpreted as minutes in `BlockManager.java:710-718`); the JUnit timeout is 60 seconds. A natural key rotation is therefore not expected in this workload. | Running in an isolated campaign. Reaching the key lookup alone does not count as the PR bug; the exact throw and failed recovery must be observed. |
| SOLR-40 | `TimeRoutedAliasUpdateProcessorTest.test` | The original four-node JUnit creates a time-routed alias and immediately adds a document (`TimeRoutedAliasUpdateProcessorTest.java:132-139`). `ZkStateReader.AliasesManager.process` reads the watched alias data; on `ConnectionLossException` it logs and leaves the local cache as-is (`ZkStateReader.java:2302-2317`). The generic Soot selection includes that callback's `getData` I/O sites. | Running in an isolated site-diversity campaign. The current completed trials have not yet injected at the alias-watch callback; no generic-fuzz target exception. A separate precise replay did trigger the target and is recorded separately. |

The original HDFS-17897 JUnit choices each cover only one half of the required
encrypted striped-checksum path. The Balancer and Solr workloads do reach their
relevant operations; their remaining question is whether a generic fault
sequence produces the necessary state and reaches the target afterward.

Evidence roots: `static-rerun/original-known/HDFS-54`, `HDFS-55`,
`HDFS-11-balancer` on node0 and `static-rerun/original-known/SOLR-40` on node2.
The audited Soot artifacts and exact JUnit identities are retained beside
each campaign. The generic trials remain distinct from the known-bug
calibrations in `crashfuzz/known-bug-controls/`.
