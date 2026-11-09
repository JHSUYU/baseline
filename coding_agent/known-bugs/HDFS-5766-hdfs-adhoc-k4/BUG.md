# HDFS-5766 (Healthy DataNode marked dead): not detected

Case `hdfs-adhoc-k4`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:424`, `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`, throws `org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException` when `key == null   (key = allKeys.get(keyId))`
- Starting test: `org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedRead`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** no

**What the agent found:** A long-running Balancer with encrypted data transfer caches one DataEncryptionKey forever in NameNodeConnector; after block keys roll, DataNodes reject it in BlockTokenSecretManager.retrieveDataEncryptionKey and every replaceBlock fails (this is HDFS-11741, not HDFS-5766).

**Same root cause as HDFS-5766?** No. The agent's failing execution goes through the balancer: NameNodeConnector.getDataEncryptionKey (server/balancer/NameNodeConnector.java:155-162, generates the key once when encryptionKey == null and never checks expiry) used by Balancer.dispatch (Balancer.java:344-347, logs 'Failed to move' at :361). The HDFS-5766 fix only adds `continue;` after dfsClient.clearDataEncryptionKey() in DFSInputStream.fetchBlockByteRange (DFSInputStream.java:965-971 in the buggy tree, hunk @@ -969,6 +969,7). The agent's test never performs a client positional read; the logs contain no DFSInputStream/fetchBlockByteRange frames, and the defect it hits (no key renewal in the balancer) is untouched by the fix.

**Realistic?** Mostly realistic for the defect it does hit: MiniDFSCluster, throttled balancer bandwidth, and shortened key-update interval/token lifetime via the same test setters TestEncryptedTransfer uses (compressing the real 10h defaults). No reflection or mocks. But it is irrelevant to HDFS-5766.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **REPRODUCED**. The test still fails identically on the fixed tree (REPRODUCED, same InvalidEncryptionKeyException at BlockTokenSecretManager.java:426 from DataXceiver during balancer moves), confirming the HDFS-5766 fix does not affect this execution.

**Reason:** The agent found a different real bug (the balancer's stale cached DataEncryptionKey, HDFS-11741) that happens to fail the same check. It never exercises DFSInputStream.fetchBlockByteRange or the missing `continue` that marks a healthy DataNode dead, and the fixed version still fails. Not a detection of HDFS-5766.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The coordination is: the NN rolls block keys, DNs and the balancer sync them, and anyone deriving a data encryption key from a block key must renew it before the block key expires on the DNs. DataEncryptionKey carries expiryDate = creation + tokenLifetime precisely for this, and DFSClient refreshes on expiry and also refetches and retries on InvalidEncryptionKeyException. The Balancer's NameNodeConnector caches the key forever and ignores its expiry. So after at most about keyUpdateInterval + keyUpdateInterval + tokenLifetime (around 30 h with defaults), the DNs have legitimately deleted the block key and reject a key the balancer itself should never have still been using. The request is not invalid: it comes from a legitimate, authorized balancer, and the rejected state was produced by the balancer's broken key renewal. In a real deployment with encrypted data transfer, any balancer run that lasts longer than that (normal for large clusters with throttled balancer bandwidth) stops moving blocks: every replaceBlock fails, and the balancer exits with NO_MOVE_PROGRESS while the cluster is still unbalanced. Upstream later fixed the same issue by making the balancer's KeyManager regenerate the encryption key when it expires (HDFS-11741, 'Long running balancer may fail due to expired DataEncryptionKey').

**Execution (agent):** 1. A MiniDFSCluster (1 NN, simulated storage) is started with dfs.encrypt.data.transfer=true and dfs.block.access.token.enable=true. DN0 (capacity 2000 B) is filled to 60% with a replication-1 file (10-byte blocks). Then an empty DN1 is added, so the cluster is unbalanced. 2. The balancer bandwidth (dfs.datanode.balance.bandwidthPerSec) is set to 10 B/s, and the NN's block-key update interval and token lifetime are set to 2 s with the same test setters TestEncryptedTransfer#testLongLivedClient uses. This compresses the real defaults (10 h / 10 h, against balancer runs that last hours or days). 3. Balancer.run starts. Its NameNodeConnector pulls block keys from the NN and keeps them up to date (BlockKeyUpdater every interval/4). On the first block move, NameNodeConnector.getDataEncryptionKey() builds a DataEncryptionKey from the balancer's current block key (keyID=961002921) and caches it. It never checks that key's expiryDate again, unlike DFSClient.getDataEncryptionKey(). 4. The first moves (DN0 -> DN1 via replaceBlock) succeed (5 'Successfully moved'). Because of the throttle they are slow. Meanwhile the NN's HeartbeatManager rolls block keys every ~5 s (key 961002921 is retired, then given expiry retire+interval+lifetime) and pushes KeyUpdateCommands to the DNs. 5. On a later key update, DN1's BlockTokenSecretManager.addKeys -> removeExpiredKeys drops block key 961002921. 6. The balancer's next replaceBlock connections still use the cached encryption key with keyId 961002921. DN1's DataXceiver runs the SASL handshake: DataTransferEncryptor -> BlockPoolTokenSecretManager.retrieveDataEncryptionKey -> BlockTokenSecretManager.retrieveDataEncryptionKey finds allKeys.get(961002921) == null and throws InvalidEncryptionKeyException ('required block key (keyID=961002921) doesn't exist. Current key: 961002923'). 7. Balancer.dispatch only logs 'Failed to move' and does not refetch or regenerate the key. Every later move fails (84 failures). After 5 iterations without progress the Balancer exits with NO_MOVE_PROGRESS (-3) and the cluster stays unbalanced. The test captures the DataNode log and fails with the stack trace.

**Stack frame (agent):** at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:426)  [this is the throw statement of the check that starts at line 424 and runs to 426; javac puts the InvalidEncryptionKeyException constructor call (bytecode offset 57-66) on line 426, so the frame of the check's throw always shows :426. The condition key == null is evaluated on line 423 and the 'throw new' starts on line 424]

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.balancer.TestBalancerWithExpiredEncryptionKey#testLongRunningBalancerWithEncryptedTransfer`
- Command: `source /bulk/codingagent/cases/hdfs-adhoc-k4/agent/env.sh && mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.balancer.TestBalancerWithExpiredEncryptionKey#testLongRunningBalancerWithEncryptedTransfer' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/balancer/TestBalancerWithExpiredEncryptionKey.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException: Can't re-compute encryption key for nonce, since the required block key (keyID=1732427026) doesn't exist. Current key: 1732427028`, frame `at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:426)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h05m | 1 | 1,046,659 | 44 | 22,291 | 62,107 | 962,217 | $1.14 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
