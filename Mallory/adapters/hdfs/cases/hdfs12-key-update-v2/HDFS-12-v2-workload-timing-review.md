# HDFS-12 workload timing review

Source: Hadoop 3.4.3, commit `9d50c6884666e794e45102260a4017bb31802e1b`.
Selected check: `BlockTokenSecretManager.retrievePassword(BlockTokenIdentifier)` at line 511, where the DataNode reads `allKeys.get(identifier.getKeyId())` under the manager lock and throws `InvalidToken` only if the entry is absent. `addKeys(ExportedBlockKeys)` installs the received keys at lines 224–238. The DataNode heartbeat receives commands and enqueues them for processing in `BPServiceActor.offerService` at lines 703–743.

The unchanged `TestEncryptedTransfer#testLongLivedClient[0]` is a valid one-test MiniDFSCluster workload that reaches this exact check on a named DataNode. It sets a two-second key-update interval, clears keys, performs a first read/checksum, **sleeps 15 seconds**, then performs a second read/checksum (`TestEncryptedTransfer.java:300–321`). The selected target is reached after the sleep, but heartbeat attempts continue during it. The SHA-bound one-, two-, and three-fault diagnostics demonstrate the consequence: each injected `sendHeartBeat` IOException is followed by a later successful heartbeat and `addKeys` before the selected DataNode lookup. The three-fault trace has exact applied ordinals 5/6/7; heartbeat 4 after those faults installs older keys at events 367–372, heartbeat 5 installs selected key 1246626942 at event 414, the NameNode mints a token using that key at event 429, and the DataNode reads its installed map entry at event 446 before the nonthrowing check at event 448. A second target occurrence likewise reads its latest installed entry at events 490–493. The JUnit passes and no selected throw occurs. Consecutive higher heartbeat ordinals are therefore not a justified next test on this workload.

Nearby existing MiniDFSCluster tests reviewed:

| Existing test | Source observation | Limit for this exact guard |
| --- | --- | --- |
| `TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey` | Waits until a cached **data encryption key** is absent on all DataNodes, then checks client key clearing and checksum retry (`:325–373`). | Exercises `SaslDataTransferServer.retrieveDataEncryptionKey` before block-token authentication; its missing-key expectation is a different key/guard. Any later `retrievePassword` reach needs separate healthy proof. |
| `TestEncryptedTransfer#testLongLivedClientPipelineRecovery` | Waits for cached data encryption key invalidation, stops the first DataNode, and induces pipeline recovery (`:376–441`). | Primarily tests encryption-key retry/pipeline replacement; does not specify a block-token lookup during a missed `DNA_ACCESSKEYUPDATE` window. |
| `TestFailoverWithBlockTokensEnabled#TestFailoverAfterAccessKeyUpdate` | Lowers update interval and clears keys, sleeps 10 seconds to guarantee heartbeats, then writes through both NameNodes (`:169–208`). | Deliberately waits for key delivery before the I/O; likely closes the missing-block-key window. |
| `TestBlockTokenWithDFS#testRead` | Uses a MiniDFSCluster and tests expired cached block tokens, including intentionally failing reads, then valid fresh tokens (`:337–470`). | The expected expired-token failure is the earlier expiry guard; it does not force a newly minted key to arrive at the DataNode before its key-update command. |
| `TestSaslDataTransferExpiredBlockToken` | Starts a secure MiniDFSCluster with one-second block-token lifetime (`:50–90`). | Focuses on expiry and retry, not a proven `allKeys` absent entry at the selected guard. |

The source search for direct key-update controls (`setKeyUpdateIntervalForTesting`, `clearAllKeysForTesting`, `DNA_ACCESSKEYUPDATE`) found no unmodified test in this reviewed set that explicitly overlaps a new block-token read with a delayed key-update heartbeat. This is a **workload-timing limitation**, not a claim that no suitable test exists anywhere in Hadoop. A test-local variant that drives an I/O immediately after NameNode key rotation while the named DataNode heartbeat is faulted could test the suspected window, but it would be a changed workload and would require its own healthy JUnit, exact target, and causal-path attestation. No such variant was run.

## Evidence and source hashes

- Three-fault negative receipt: `HDFS-12-v2-three-fault-negative.json`, SHA-256 `a11c25df3050ef5428cb1d81656c4cbd3b21adf8fcd0e62986c522a1bc12b66f`; raw manifest SHA-256 `6fe9f7287649391382da966b622b1b6c951384b9c569b6d1ce767922968f7127`.
- `TestEncryptedTransfer.java`: `8272862b11d4a645ffa6029c3f1462a14dcfce7b873815fcccc949d74a4bc0a5`.
- `TestFailoverWithBlockTokensEnabled.java`: `425c6d71d05f696c48ecd898cd8ac7ead76fd1a77cfa739e491fb09373b4b85e`.
- `TestBlockTokenWithDFS.java`: `6f1bcf553da3930d339885c2228f4f66c157dd75671ee7fcfe6a722f5815fd0a`.
- `TestSaslDataTransferExpiredBlockToken.java`: `843c02826106a78226d7986af95f9060ea45d03c3a797d10f02cfe750d2b7d52`.
- `BlockTokenSecretManager.java`: `d6f2dd33b2cb82484ab52262a05bf4445113e168de08479af00ad93969911957`.
- `BPServiceActor.java`: `fbcb03b86822e71e451242142752706b61c3f3f096d0219f5d90344bc59bb833`.
- `SaslDataTransferServer.java`: `a4c6deff36933bb0eb4c89c3b218a355f88297ddd434572b41fcd38e43418c97`.
