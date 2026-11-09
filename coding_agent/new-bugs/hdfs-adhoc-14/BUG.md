# hdfs-adhoc-14: With overwrite-downstream-derived-QOP, the pipeline head re-signs block tokens with its current key while keeping the original keyId, so downstream DNs reject valid tokens around every block-key roll and pipelines lose replicas or fail.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:418`, `BlockTokenSecretManager.checkAccess(Token<BlockTokenIdentifier>, String, ExtendedBlock, BlockTokenIdentifier.AccessMode, StorageType[], String[])`, throws `org.apache.hadoop.security.token.SecretManager.InvalidToken` when `!MessageDigest.isEqual(retrievePassword(id), token.getPassword())`
- Starting test: `org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** With encrypted transfer, block tokens and dfs.encrypt.data.overwrite.downstream.derived.qop on, the NN rolls its block key (one updateKeys plus needKeyUpdate, exactly what HeartbeatManager.Monitor does) while the DNs' heartbeats have not yet delivered the KeyUpdateCommand (delayed heartbeats). A client then writes a 3-replica file.

**Why (root cause in the source):** DataXceiver.writeBlock (DataXceiver.java:824-828) re-signs the downstream token with the DN's own getCurrentKey(), and SaslDataTransferClient.updateToken (SaslDataTransferClient.java:450-459) recomputes the password with that key but keeps the identifier's keyId, the key the NN used. When the two differ, the downstream DN's BlockTokenSecretManager.checkAccess (BlockTokenSecretManager.java:417-418) recomputes with the key named by keyId and rejects a genuine, unexpired token. They differ in the window between every NN key roll and the DN's next heartbeat, for tokens issued before a roll, and for longer if a DN misses an update. The client wrongly excludes healthy downstream DNs and the write ends with fewer replicas or fails. The trigger is one real rotation step plus a heartbeat delay, which is a reachable state.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The token the client presented is genuine and unexpired, signed by the NN with a key every DN holds. The rejection is caused only by the DN-to-DN coordination of block keys. The pipeline head re-signs downstream tokens with whatever key it currently treats as 'current', but the identifier still names the key the NN used. Those two keys differ whenever the NN's key roll and a DN's KeyUpdateCommand are not in sync. That always happens for a window of up to a heartbeat interval after each roll (default every 10h). It also happens for a client holding a token issued before the roll, and for the whole key interval if a DN misses the heartbeat response that carries the update. A correct coordination would re-sign with the key identified by the token's keyId, or set keyId to the re-signing key. Consequence in a real deployment with encrypted transfer and overwrite-downstream-QOP enabled: multi-replica writes fail around every block-key roll. Clients wrongly blame and exclude healthy downstream DataNodes. Writes retry, then end with fewer replicas than requested (here one), or fail when exclusions run out (e.g. small clusters or replace-datanode-on-failure policies). This degrades durability.

**Execution (agent):** Config: the starting test's setup (dfs.encrypt.data.transfer=true, dfs.block.access.token.enable=true) plus dfs.encrypt.data.overwrite.downstream.derived.qop=true, with 1 NN and 3 DNs. (1) The cluster starts, and every DN registers and receives the NN's exported block keys {K_n (current), K_n+1 (next)}, with currentKey=K_n. A 3-replica write succeeds. (2) DN heartbeats are delayed, or the heartbeat response carrying the KeyUpdateCommand is lost; the test models this with DataNodeTestUtils.setHeartbeatsDisabledForTests. (3) The NN does its periodic block-key roll, the same step HeartbeatManager.Monitor runs once keyUpdateInterval has elapsed: BlockTokenSecretManager.updateKeys() makes K_n+1 the current key and creates K_n+2, and every DatanodeDescriptor is marked needKeyUpdate. The DNs still have currentKey=K_n but already know K_n+1. (4) A client creates a file with replication 3. addBlock returns a block token signed by the NN with K_n+1 (keyId=K_n+1). (5) DN1, the pipeline head, accepts the token: it has K_n+1, so its check at line 418 passes. Before forwarding WRITE_BLOCK to DN2, DataXceiver.writeBlock (overwriteDownstreamDerivedQOP) takes DN1's *current* key K_n, and SaslDataTransferClient.updateToken re-signs the token with K_n's secret while keeping keyId=K_n+1 in the identifier. (6) DN2 runs BlockTokenSecretManager.checkAccess: retrievePassword(id) computes the HMAC with the key named by the keyId, K_n+1, which does not match the K_n-based password. It throws InvalidToken 'doesn't have the correct token password' at BlockTokenSecretManager.java:418. (7) DN2 replies ERROR_ACCESS_TOKEN with firstBadLink=DN2. The client abandons the block, excludes the healthy DN2, and retries. The 2-node pipeline fails the same way at the next DN. The write only succeeds on a single-DN pipeline, where nothing is forwarded downstream.

**Stack frame (agent):** at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.checkAccess(BlockTokenSecretManager.java:418)

## Reproduction

- Test: `org.apache.hadoop.hdfs.TestEncryptedTransferKeyRollDownstreamQOP#testWriteAfterBlockKeyRollBeforeDNKeyUpdate`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.TestEncryptedTransferKeyRollDownstreamQOP#testWriteAfterBlockKeyRollBeforeDNKeyUpdate' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestEncryptedTransferKeyRollDownstreamQOP.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.security.token.SecretManager$InvalidToken: Block token with block_token_identifier (expiryDate=1794108780737, keyId=1324005614, userId=agent, blockPoolId=BP-438282041-172.18.0.4-1794072777094, blockId=1073741826, access modes=[WRITE], storageTypes= [DISK, DISK, DISK], storageIds= [DS-5f1a3b31-f7e6-430b-a315-3be5c8185f24, DS-ab5c960e-4fb0-4c0a-a5d7-95ed29cef7d3, DS-b37c860b-b125-4`, frame `at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.checkAccess(BlockTokenSecretManager.java:418)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h07m | 1 | 1,591,198 | 52 | 27,609 | 78,802 | 1,484,735 | $1.48 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
