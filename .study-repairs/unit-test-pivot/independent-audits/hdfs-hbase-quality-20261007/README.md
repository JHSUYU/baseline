# Independent audit: completed HDFS and HBase checks

Generated 2026-10-07 02:15 UTC. Scope: the 56 HDFS/HBase rows currently marked `quality_complete` in `checklist102.json` (22 HBase, 34 HDFS). This is an evidence audit; it did not rerun a JVM, change a checklist status, or claim a new bug.

## Method and limits

- Read each case `result.json` and its case or shared README/source review; checked named original JUnit, target site, trial counts, post-final-fault target count, coverage feedback, elapsed seconds, and exception classification. Result/README claims were cross-checked against on-disk ledgers, logs, JaCoCo or archived raw receipts where present. Every listed case reports a positive elapsed time, positive strict injection count, positive post-fault target count, and a production-coverage metric (a zero gain is legitimate).
- Rehashed 38 raw or supplementary archives (265,038,283 bytes) into [`archive-sha256.json`](archive-sha256.json). This confirms current archive bytes, not the semantics of every trace. The 31/32 external raw roots were hashed into [`external-raw-sha256.json`](external-raw-sha256.json) without copying 1.11 GB of data.
- Independently parsed all 160 HDFS-31/32 `events.tsv` files: exact applied-count totals equal the result (61/74); every selected post-fault guard in the result has a later raw `TARGET_GUARD` event. HDFS-32 trials 30, 33, 70 timed out before target, so their empty JaCoCo files do not support coverage feedback and are excluded from the target-retaining count.
- This audit does not assert exhaustive semantic review of every one of the thousands of plan events. `strict→target` below is the case result count, checked against case-level raw receipts and, for 31/32, directly against every raw trial. A target exception is a bug candidate until the original JUnit, source state and replay establish a contract violation.

**Later actor audit:** The table below is a historical snapshot. A subsequent
[runtime actor identity review](actor-identity-screen.md) found that nine HDFS
storage cases used a normalized RPC selector without a DN/storage/startup
episode key at the target. Their current case results are
`actor_identity_recheck_pending`; old counts remain under
`legacy_coarse_actor` and no longer count as high-quality completion.

## Case-by-case evidence

| Case / selected source line | Original JUnit | Strict / attempts → postfault target | JUnit time | Raw evidence | Assessment |
| --- | --- | ---: | ---: | --- | --- |
| [HBASE-01](../../cases/HBASE-01/result.json) · ConnectionImplementation.java:1106 | `TestConnectionImplementation#testMetaLookupThreadPoolCreated` | 80/80 → 80 | 65.9 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-02](../../cases/HBASE-02/result.json) · ConnectionImplementation.java:911 | `TestConnectionImplementation#testMetaLookupThreadPoolCreated` | 65/65 → 61 | 46.5 min | case raw / archive | 65 trials; queue exhaustion is documented after the six-RPC retry limit. |
| [HBASE-04](../../cases/HBASE-04/result.json) · HBaseAdmin.java:1263 | `TestMobStoreScanner#testMobStoreScanner` | 84/84 → 80 | 73.2 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-07](../../cases/HBASE-07/result.json) · HBaseAdmin.java:2788 | `TestRestoreFlushSnapshotFromClient#testRestoreSnapshot` | 80/80 → 80 | 109.6 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-08](../../cases/HBASE-08/result.json) · ClusterSchemaServiceImpl.java:116 | `TestNamespaceAuditor#testTableOperations` | 80/80 → 65 | 70.1 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-10](../../cases/HBASE-10/result.json) · AssignmentManager.java:757 | `testDisableAndMove` | 128/129 → 128 | 102.7 min | node1 raw (not mirrored locally) | No contradictory evidence found in this audit. |
| [HBASE-11](../../cases/HBASE-11/result.json) · AssignmentManager.java:760 | `testDisableAndMove` | 128/129 → 128 | 95.7 min | node1 raw (not mirrored locally) | Expected B2 exception; two response-loss replays and source review leave a client candidate unconfirmed. |
| [HBASE-12](../../cases/HBASE-12/result.json) · AssignmentManager.java:763 | `testDisableAndMove` | 209/211 → 98 | 174.7 min | node1 raw (not mirrored locally) | Shared RPC phase plus META supplement; later table-state writes occur after the last B3 evaluation. |
| [HBASE-13](../../cases/HBASE-13/result.json) · MergeTableRegionsProcedure.java:495 | `TestMergeTableRegionsProcedure#testMergeTwoRegions` | 80/80 → 80 | 91.1 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-14](../../cases/HBASE-14/result.json) · MergeTableRegionsProcedure.java:500 | `TestMergeTableRegionsProcedure#testMergeTwoRegions` | 80/80 → 80 | 91.1 min | shared HBASE-13 raw | No contradictory evidence found in this audit. |
| [HBASE-15](../../cases/HBASE-15/result.json) · MergeTableRegionsProcedure.java:503 | `TestMergeTableRegionsProcedure#testMergeTwoRegions` | 80/80 → 80 | 91.1 min | shared HBASE-13 raw | No contradictory evidence found in this audit. |
| [HBASE-16](../../cases/HBASE-16/result.json) · TransitRegionStateProcedure.java:371 | `TestCloseRegionWhileRSCrash#testRetryBackoff` | 80/80 → 80 | 134.8 min | case raw / archive | Target HBaseIOException already occurs in the healthy retry path. |
| [HBASE-18](../../cases/HBASE-18/result.json) · TransitRegionStateProcedure.java:325 | `TestExceptionInAssignRegion#testExceptionInAssignRegion` | 80/80 → 80 | 92.8 min | case raw / archive | 23 target recovery exceptions are expected; independent same-region replay passed. |
| [HBASE-19](../../cases/HBASE-19/result.json) · ModifyTableProcedure.java:135 | `TestModifyTableProcedure#testModifyWillNotReopenRegions` | 80/80 → 80 | 82.4 min | case raw / archive | Original JUnit intentionally catches the column-family rejection. |
| [HBASE-20](../../cases/HBASE-20/result.json) · ModifyTableProcedure.java:139 | `TestModifyTableProcedure#testModifyWillNotReopenRegions` | 80/80 → 80 | 82.4 min | shared HBASE-19 raw | Original JUnit intentionally catches the coprocessor rejection. |
| [HBASE-21](../../cases/HBASE-21/result.json) · NamespaceStateManager.java:133 | `testRestoreSnapshotQuotaExceed` | 143/144 → 128 | 192.5 min | node1 raw (not mirrored locally) | Quota exception is expected; two manifest faults lost the target and were excluded. |
| [HBASE-22](../../cases/HBASE-22/result.json) · NamespaceStateManager.java:172 | `TestNamespaceAuditor#testTableOperations` | 80/80 → 63 | 84.5 min | case raw / archive | Quota rejection is expected by the original JUnit. |
| [HBASE-24](../../cases/HBASE-24/result.json) · ZKProcedureMemberRpcs.java:210 | `TestZKProcedure#testMultipleMembers` | 85/92 → 80 | 40.9 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-29](../../cases/HBASE-29/result.json) · RSRpcServices.java:2263 | `TestRegionReplicaReplicationEndpoint#testRegionReplicaReplicationWith2Replicas` | 80/81 → 80 | 95.4 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-30](../../cases/HBASE-30/result.json) · RSRpcServices.java:2298 | `TestRegionReplicaReplicationEndpoint#testRegionReplicaReplicationWith2Replicas` | 80/80 → 80 | 83.0 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-34](../../cases/HBASE-34/result.json) · AuthenticationTokenSecretManager.java:160 | `TestGenerateDelegationToken#testOnlyToken` | 80/80 → 80 | 113.1 min | case raw / archive | No contradictory evidence found in this audit. |
| [HBASE-35](../../cases/HBASE-35/result.json) · HBaseFsck.java:2720 | `TestHBaseFsckReplication#test` | 80/80 → 80 | 64.4 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-01](../../cases/HDFS-01/result.json) · DFSInputStream.java:518 | `TestPread#testPreadDFS` | 128/128 → 98 | 41.7 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-07](../../cases/HDFS-07/result.json) · Journal.java:932 | `TestQuorumJournalManager#testRecoverAfterIncompleteRecovery` | 80/80 → 53 | 17.5 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-08](../../cases/HDFS-08/result.json) · Journal.java:489 | `TestQuorumJournalManager#testChangeWritersLogsInSync` | 77/80 → 69 | 24.5 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-09](../../cases/HDFS-09/result.json) · Journal.java:504 | `TestQuorumJournalManager#testSingleWriter` | 128/128 → 113 | 25.0 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-10](../../cases/HDFS-10/result.json) · Journal.java:520 | `TestQuorumJournalManager#testSingleWriter` | 80/80 → 66 | 22.2 min | case raw / archive | 13 post-fault epoch rejections; source and two smoke replays support intended guard response. |
| [HDFS-11](../../cases/HDFS-11/result.json) · BlockTokenSecretManager.java:555 | `TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey[0]` | 200/208 → 83 | 100.5 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-12](../../cases/HDFS-12/result.json) · BlockTokenSecretManager.java:514 | `TestEncryptedTransfer#testLongLivedClient[0]` | 242/256 → 136 | 142.9 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-14](../../cases/HDFS-14/result.json) · BlockTokenSecretManager.java:412 | `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]` | 128/128 → 51 | 68.9 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-15](../../cases/HDFS-15/result.json) · BlockInfo.java:447 | `TestBlockToken#testBlockTokenInLastLocatedBlockLegacy` | 73/80 → 53 | 30.1 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-16](../../cases/HDFS-16/result.json) · BlockInfo.java:428 | `TestClientProtocolForPipelineRecovery#testUpdatePipeLineAfterDNReg` | 63/80 → 40 | 51.1 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-20](../../cases/HDFS-20/result.json) · BPOfferService.java:606 | `TestStandbyIsHot#testStandbyIsHot` | 62/80 → 59 | 50.2 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-21](../../cases/HDFS-21/result.json) · BPServiceActor.java:290 | `TestDFSInputStream#testSkipWithRemoteBlockReader` | 80/80 → 79 | 73.8 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-22](../../cases/HDFS-22/result.json) · BlockPoolSliceStorage.java:396 | `TestDFSStartupVersions#testVersions` | 78/80 → 57 | 54.1 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-23](../../cases/HDFS-23/result.json) · BlockPoolSliceStorage.java:401 | `TestDFSStartupVersions#testVersions` | 78/80 → 57 | 54.1 min | shared HDFS-22 raw | No contradictory evidence found in this audit. |
| [HDFS-24](../../cases/HDFS-24/result.json) · BlockPoolSliceStorage.java:424 | `TestDFSUpgrade#testUpgrade` | 78/80 → 53 | 51.5 min | case raw / archive | 123 storage-version rejections are expected incompatibility cases. |
| [HDFS-25](../../cases/HDFS-25/result.json) · BlockPoolSliceStorage.java:186 | `TestDFSStartupVersions#testVersions` | 78/80 → 57 | 54.1 min | shared HDFS-22 raw | No contradictory evidence found in this audit. |
| [HDFS-26](../../cases/HDFS-26/result.json) · BlockPoolSliceStorage.java:626 | `TestDFSRollback#testRollback` | 78/80 → 69 | 66.2 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-27](../../cases/HDFS-27/result.json) · BlockPoolSliceStorage.java:510 | `TestDFSUpgrade#testUpgrade` | 78/80 → 48 | 51.5 min | shared HDFS-24 raw | No contradictory evidence found in this audit. |
| [HDFS-28](../../cases/HDFS-28/result.json) · BlockRecoveryWorker.java:539 | `TestBlockRecovery2#testRecoveryTimeout` | 63/128 → 18 | 62.0 min | shared hdfs_recovery_shared raw | Only 18 of 128 attempts retained this exact check; result is bounded to those observations. |
| [HDFS-29](../../cases/HDFS-29/result.json) · BlockRecoveryWorker.java:578 | `TestBlockRecovery2#testRecoveryTimeout` | 63/128 → 39 | 62.0 min | shared hdfs_recovery_shared raw | Only 39 of 128 attempts retained this exact check; result is bounded to those observations. |
| [HDFS-30](../../cases/HDFS-30/result.json) · BlockRecoveryWorker.java:583 | `TestBlockRecovery2#testRecoveryTimeout` | 74/152 → 41 | 78.2 min | shared hdfs_recovery_shared raw | 39 main + 2 HA target-retaining trials; shared raw receipts are separate. |
| [HDFS-31](../../cases/HDFS-31/result.json) · DataNode.java:1835 | `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` | 61/80 → 41 | 41.7 min | host raw + SHA receipt | 80 raw trial directories outside the repository; 61 strict and 41 exact-context postfault trials independently reconciled. |
| [HDFS-32](../../cases/HDFS-32/result.json) · DataNode.java:3822 | `TestDeleteBlockPool#testDeleteBlockPool` | 74/80 → 47 | 53.4 min | host raw + SHA receipt | 80 raw trial directories outside the repository; 74 strict and 47 exact-context postfault trials independently reconciled. Three target-lost timeout runs have zero-byte JaCoCo. |
| [HDFS-33](../../cases/HDFS-33/result.json) · DataStorage.java:259 | `TestDataNodeHotSwapVolumes#testAddOneNewVolume` | 100/102 → 80 | 39.9 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-34](../../cases/HDFS-34/result.json) · DataStorage.java:744 | `TestDFSStartupVersions#testVersions` | 78/80 → 20 | 54.1 min | shared HDFS-22 raw | 32 expected VERSION incompatibility throws after fault; original test expects rejection. |
| [HDFS-35](../../cases/HDFS-35/result.json) · DataStorage.java:752 | `TestDFSStartupVersions#testVersions` | 78/80 → 62 | 54.1 min | shared HDFS-22 raw | No contradictory evidence found in this audit. |
| [HDFS-37](../../cases/HDFS-37/result.json) · DataStorage.java:947 | `TestDFSRollback#testRollback` | 77/80 → 61 | 73.1 min | case raw / archive | Expected rollback VERSION rejection; no novel state claimed. |
| [HDFS-39](../../cases/HDFS-39/result.json) · FSDirAppendOp.java:132 | `TestFileAppend#testMultipleAppends` | 171/205 → 128 | 95.8 min | case raw / archive | Four reported candidates were source reviewed and rejected as expected retry states. |
| [HDFS-40](../../cases/HDFS-40/result.json) · FSDirAppendOp.java:138 | `TestFileAppend#testFailedAppendBlockRejection` | 123/128 → 122 | 63.7 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-43](../../cases/HDFS-43/result.json) · FSDirTruncateOp.java:117 | `TestFileTruncate#testTruncateTwiceTogether` | 78/80 → 49 | 44.7 min | case raw / archive | The original test expects unequal-length truncate rejection; equal-branch supplement is separate. |
| [HDFS-48](../../cases/HDFS-48/result.json) · INodeDirectory.java:356 | `TestRenameWithSnapshots#testRenameUndo_1` | 179/183 → 128 | 72.6 min | case raw / archive | No contradictory evidence found in this audit. |
| [HDFS-50](../../cases/HDFS-50/result.json) · DirectorySnapshottableFeature.java:199 | `TestSnapshotCommands#testCreateSnapshot` | 40/48 → 22 | 8.7 min | case raw / archive | Older preset 48 trials/max 4 faults, rather than current 80/max 8; target is local duplicate-name guard. |
| [HDFS-54](../../cases/HDFS-54/result.json) · FileChecksumHelper.java:629 | `adapted TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey` | 6/6 → 6 | 3.6 min | case raw; adapted workload | MATERIAL GAP: workload is a case-local striped-file adaptation of original TestEncryptedTransfer, not the unchanged original test method; known-bug control only. |
| [HDFS-55](../../cases/HDFS-55/result.json) · KeyManager.java:123 | `TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` | 33/46 → 29 | 47.2 min | case raw / archive | Original 46-trial JUnit campaign is separate from the adapted final differential control; known HDFS-17899. |

## Findings requiring action or explicit qualification

1. **HDFS-54 had an unchanged-JUnit provenance gap at audit time.** Its README explicitly describes a case-local XOR-2-1 striped-file adaptation of `TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey`. The runtime evidence establishes the exact HDFS-54 false check after six injected SASL faults and the known HDFS-17897 differential. A later, separate unchanged `TestFileChecksum#testStripedAndReplicatedFileChecksum2[0]` run now proves the original test reaches the selected check and retains it after one strict checksum-RPC fault; see [the supplemental pilot](../../cases/HDFS-54/original-junit/README.md). Its full original-JUnit fuzz budget remains pending, and the known-bug classification remains tied to the adapted control. HDFS-55 counts an unmodified original JUnit campaign and labels its adapted final differential separately.

   **HDFS-54 node2 handoff (2026-10-07):** The separate original-JUnit
   campaign is checkpointed at
   `/users/ZhenyuLi/hdfs54-original-campaign/runs/campaign-state.json` with
   `effective=1`, `attempts=1`, `queue=31`, and `in_flight=null`. The first
   strict trial ID is `01f09073125e7810`; its exact checksum-RPC fault was
   applied and the same target check completed after the fault. Resume with
   `/users/ZhenyuLi/hdfs54-original-campaign/resume_node2.sh`, which starts
   tmux `hdfs54_original_80` and continues from the queued plan, so the
   completed first trial is not repeated. Launch only after the Solr 36/37
   owner explicitly releases node2, its tmux session has exited, and `jps -l`
   shows no competing JVM. The script checks those conditions plus checkpoint
   consistency before starting. The 80-effective/8-fault campaign remains
   pending; any 128/10 extension requires late production-coverage or I/O
   novelty. Keep its result separate from the six-run adapted known-bug
   control in HDFS-54.
2. **Four HBase campaigns depend on node1 for the full raw record:** HBASE-10/11/12/21. Read-only SSH confirmed the HBASE-10/12 trial logs and coverage, HBASE-11 shared HBASE-10 records, and HBASE-21 `r001`/`r144` logs plus JaCoCo files on node1. Their local `result.json`/ledgers survive here, but the full raw record is not portable with this repository. HBASE-21 even points to a local `work/logs/healthy.log` that is absent locally (a copy exists inside its four-log manifest archive and on node1). Add a compact case-local raw archive or durable remote receipt before treating the evidence as independently recoverable after node1 loss.
3. **HDFS-31/32 raw evidence is outside the case directories:** `/users/ZhenyuLi/hdfs31-independent-runs` and `/users/ZhenyuLi/hdfs32-independent-runs`. The new SHA receipt makes this location and its 1,268 files explicit, but it cannot restore missing raw bytes. Three HDFS-32 target-lost timeout trials have empty JaCoCo files and were correctly excluded from target-retaining coverage.
4. **Coverage and budget bounds:** HDFS-28/29 retain the selected guard in 18/39 of 128 attempts; HDFS-30 has 41 postfault observations across its main and HA supplement. HDFS-50 used its documented older 48-trial/max-4-fault preset. These are valid bounded observations, not evidence that all potentially relevant I/O orders or branch states were exhausted. HBASE-02 stopped at 65 because the observed retry I/O queue was exhausted; its result explains that decision.
5. **Expected target exceptions were not promoted to new bugs.** The HBASE-11/16/18/19/20/21/22 and HDFS-10/24/32/34/37/39/43 case reviews tie their target throws to healthy expectations, protocol rejection, or successful original JUnit recovery. HBASE-11 additionally documents response-loss replays but retains `candidate_unconfirmed`. The two HDFS known-bug controls are marked known rather than new.

Line-number note: HDFS-07/08/10/39/40 list the throw location in the checklist while some result fields identify the preceding guard line. Source snippets and target code identify the same selected conditional; this is a metadata distinction, not a different check.
