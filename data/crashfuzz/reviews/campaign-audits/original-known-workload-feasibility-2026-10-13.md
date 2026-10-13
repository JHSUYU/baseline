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
| HDFS-17967 mirror and HDFS-17899 DataNode transfer | `TestEncryptedTransfer.testLongLivedClientPipelineRecovery[0]`; `DataXceiver.writeBlock` mirror SASL and `DataNode.DataTransfer.run` | This original four-DataNode JUnit enables encrypted transfer, reduces the key-update interval and token lifetime to 2 seconds, clears old keys, and induces pipeline recovery after stopping a DataNode (`TestEncryptedTransfer.java:376-437`). Its passing healthy trace observes both outbound I/O methods, the NameNode heartbeat RPC, and one expected receiver-side `InvalidEncryptionKeyException` from the client retry path. Soot selects 138 I/O calls and 400 coverage methods without a manual I/O list. A post-call heartbeat failure can prevent a `DNA_ACCESSKEYUPDATE` reply from being queued on one DataNode (`BPServiceActor.java:703-739`), while `BPOfferService.java:779-784` updates local keys only when the command is processed. | **Target exception triggered under the specified oracle after 55.859 seconds of measured work** (27.151-second healthy seed + 28.708-second first trial). In the original campaign's first strict trial, the fault applied at trace seq 698 and the exact `BlockTokenSecretManager.retrieveDataEncryptionKey` throw at source line 555 followed at seq 954. It was labeled `lost_target` because the separate `CHECK_REACHED` hook did not fire; the exact throw is recorded in the trace. At a later 162-trial snapshot, 93 strict runs reached the same exact throw after a fault. The healthy JUnit also throws this exception once as part of client retry, so these observations establish target-check reach and throw, while the relation to the missing outbound mirror/transfer retry remains a separate source-level question. |
| SOLR-40 | `TimeRoutedAliasUpdateProcessorTest.test` | The original four-node JUnit creates a time-routed alias and immediately adds a document (`TimeRoutedAliasUpdateProcessorTest.java:132-139`). `ZkStateReader.AliasesManager.process` reads the watched alias data; on `ConnectionLossException` it logs and leaves the local cache as-is (`ZkStateReader.java:2302-2317`). The generic Soot selection includes that callback's `getData` I/O sites. | The previous generic campaign stopped at 98 trials with no target exception. Trial 61 strictly injected `ConnectionLossException` at the alias-watch `getData` call and reached the target, but the JUnit passed. Other callback selectors often failed to match because the `zkCallback` pool number changed between runs. A new generic campaign uses stable, distinct `node1`–`node4` identities derived from the embedded cluster's Solr homes; its unchanged JUnit healthy run passed. A separate precise replay triggered the target and remains a different result. |

The original HDFS-17897 JUnit choices each cover only one half of the required
encrypted striped-checksum path. The encrypted pipeline-recovery JUnit is the
strongest unchanged workload for the DataNode mirror and transfer paths because
it combines key rotation with observed outbound SASL I/O. The Balancer and Solr
workloads reach their relevant operations; their remaining question is whether
a generic fault sequence produces the necessary state and reaches the target
afterward.

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
