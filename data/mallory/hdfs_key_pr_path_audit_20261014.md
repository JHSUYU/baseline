# HDFS encryption-key path audit (2026-10-14)

System under test: Hadoop HDFS 3.4.3, with unchanged original JUnit tests. The common server-side target is `BlockTokenSecretManager.retrieveDataEncryptionKey`, where `allKeys.get(keyId) == null` throws `InvalidEncryptionKeyException` (`BlockTokenSecretManager.java:547-555`). The target exception alone does not identify the caller-specific missing retry addressed by a PR.

| Fix path | Original JUnit evidence | Current testing potential |
| --- | --- | --- |
| HDFS-17967 `DataXceiver.writeBlock`; HDFS-17899 `DataNode.DataTransfer.run` | `TestEncryptedTransfer#testLongLivedClientPipelineRecovery[0]` uses four DataNodes, shortens key lifetime/update to 2 seconds, and recovers a broken pipeline. The healthy trace enters `DataXceiver.writeBlock` at seq 744 and `DataNode.DataTransfer.run` at seq 966. | Highest among the available original tests. Generic, repeated registration/heartbeat/key-update RPC faults may delay key installation or propagation before a DataNode-to-DataNode SASL handshake. This is a hypothesis requiring runtime proof. The observed `writeBlock` entry may be from initial file creation; a later faulted-run entry must be verified. |
| HDFS-17899 Balancer `Dispatcher.PendingMove.dispatch`; HDFS-17967 `DataXceiver.replaceBlock` | `TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` passes in the healthy Mallory v22 record and reaches 75 target checks, including 30 correlated DataNode-to-DataNode SASL sends, as well as `replaceBlock`/`copyBlock` coverage. | Reachable, but short-term stale-key creation is less likely: the unmodified test times out after 60 seconds while the default block-key update interval is 600 minutes. A faulted initial-registration window is possible but unproven. |
| HDFS-17897 striped checksum | Available checksum tests with EC lack encrypted transfer; encrypted checksum tests use replicated files. | No matching unchanged original JUnit established. |
| HDFS-17899 SPS `BlockDispatcher.moveBlock` | Available SPS tests do not enable data-transfer encryption. | No matching unchanged original JUnit established. |
| HDFS-17967 `StripedBlockWriter` | No unchanged test combining EC reconstruction and encrypted transfer has been established. | No matching unchanged original JUnit established. |

The low-potential calls above are based on the *combination* required by each
defect, rather than on a missing operation alone. `TestFileChecksum` exercises
striped checksums but leaves data-transfer encryption at its default false
setting; `TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey`
enables encryption but checksums a replicated file. The SPS
`TestExternalStoragePolicySatisfier#testWithKeytabs` uses SASL authentication,
not an encrypted data-transfer key. `TestReconstructStripedFile` exercises
`StripedBlockWriter.init()` without enabling encrypted data transfer. The
encryption, EC, and SPS references in `TestWebHDFS` occur in separate test
methods, and its encryption-defaults test starts no DataNodes. This source
audit found no unchanged cluster JUnit combining the required operation and
encrypted outbound SASL path; it does not prove that no such JUnit exists.

The larger issue chain includes [HDFS-16136](https://issues.apache.org/jira/browse/HDFS-16136), which enumerates the remaining `socketSend` callers. Older [HDFS-10609](https://issues.apache.org/jira/browse/HDFS-10609), [HDFS-11741](https://issues.apache.org/jira/browse/HDFS-11741), and [HDFS-12931](https://issues.apache.org/jira/browse/HDFS-12931) addressed client pipeline recovery, Balancer key expiry, and replicated checksum, respectively. Their existing retry/expiry logic is already present in the HDFS 3.4.3 source (`DataStreamer.java:124-149,1598`, `KeyManager.java:120-144`, `FileChecksumHelper.java:536-547`); an exception from one of those already handled paths is useful as a positive control but does not establish that a later missing-retry path was found. The striped checksum branch still has only a generic `IOException` catch at `FileChecksumHelper.java:669`.

The pipeline-recovery healthy run already has one intentional target `EXPLICIT_THROW` at trace seq 936, caused by the client `DataStreamer$StreamerStreams` path; its retry recovers. Under the target-exception oracle, an additional fault-induced target throw is a detection candidate even when a caller subsequently catches it. PR-path attribution needs the caller chain; confirming the specific missing-retry defect additionally needs evidence that its caller failed to clear/retry the cached key. Record the key ID and relevant sender/receiver key sets for diagnosis. Earlier 80+40 diagnostic trials produced no extra target throw. They do not establish a detection or exhaust the revised generic multi-fault campaign.

Evidence: `.study-repairs/diagnostics/hdfs11-postcall-key-campaign/results/HDFS-11/healthy-postcall-key-v1/runtime_trace.jsonl`; `data/mallory/calibration_v22/HDFS-11/trials/r0000/result.json`; Hadoop 3.4.3 `TestEncryptedTransfer.java:376-433`, `BlockTokenSecretManager.java:547-555`, `DFSConfigKeys.java:1061`, and `KeyManager.java:166-190`. Fix descriptions: [HDFS-17897](https://issues.apache.org/jira/browse/HDFS-17897), [HDFS-17899](https://issues.apache.org/jira/browse/HDFS-17899), [HDFS-17967 / PR #8698](https://github.com/apache/hadoop/pull/8698).
