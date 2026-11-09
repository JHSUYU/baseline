# HDFS-11741 (Balancer block moves fail): detected

Case `hdfs-adhoc-k1`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:482`, `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`, throws `org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException` when `key == null   (key = allKeys.get(keyId))`
- Starting test: `org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer#testEncryptedBalancer0`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** yes

**What the agent found:** A long-running encrypted balancer (one NameNodeConnector/KeyManager across iterations) keeps using the DataEncryptionKey it cached in iteration 0; after the NN rolls block keys and the DataNodes drop that key, every later replaceBlock SASL handshake fails BlockTokenSecretManager.retrieveDataEncryptionKey (allKeys.get(keyId)==null) and the balancer moves no more bytes.

**Same root cause as HDFS-11741?** The failing DEK comes from KeyManager.newDataEncryptionKey (server/balancer/KeyManager.java ~line 113-121 in the buggy tree), which generates encryptionKey only when it is null and never checks encryptionKey.expiryDate, so the DEK made from block key K is reused after K expired and was removed by the DataNodes' removeExpiredKeys; the DataNode then throws at BlockTokenSecretManager.java:482. This is exactly the hunk the fix changes in KeyManager.newDataEncryptionKey (`if (encryptionKey == null || encryptionKey.expiryDate < timer.now())` regenerates from the current block key); the BlockTokenSecretManager hunks only swap Time.now() for an injectable Timer.

**Realistic?** Yes. MiniDFSCluster with dfs.encrypt.data.transfer and block access tokens on; the balancer is driven exactly as Balancer#run does (one connector, a new Balancer per iteration). The only acceleration is setKeyUpdateIntervalForTesting/setTokenLifetime(2 s) on the NN before the balancer starts, which shrinks the configurable key-roll interval and token lifetime (the same hooks upstream TestEncryptedTransfer#testLongLivedClient uses); the balancer learns these values through the normal getBlockKeys export. Key rolling, DN key removal and the failing moves are all produced by the system's own protocol; the test only waits for the DNs to drop the key. No reflection, mocks or direct calls into the check.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **NOT_REPRODUCED**. On the buggy tree plus the fix's production changes, the test passes in both runs (NOT_REPRODUCED): no InvalidEncryptionKeyException in the output, and bytes moved go from 100 before the key expiry to 400 after, versus 100 -> 100 with 9 InvalidEncryptionKeyException occurrences on the buggy tree.

**Reason:** The agent's failing execution is driven by the exact defect HDFS-11741 fixes: the balancer's KeyManager caches its DataEncryptionKey forever without an expiry check, so once its block key expires on the DataNodes every encrypted block move fails. The trigger is realistic (only time-scaled key settings), and the consequence matches the JIRA (a long-running balancer stops moving blocks); the fixed version removes both the exception and the stall.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The balancer's KeyManager.newDataEncryptionKey() creates the DataEncryptionKey once and returns it for the rest of the process's life. It ignores the key's expiryDate and never replaces it when the BlockKeyUpdater pulls new block keys from the NN. A correct coordination would derive the DEK from a block key the DataNodes still hold: DFSClient does this by checking DEK expiry and refetching on InvalidEncryptionKeyException, and the DataNode refreshes its own key too. So the check is rejecting stale state the balancer should never send, not an invalid user request. This matches upstream HDFS-11741 ('Long running balancer may fail due to expired DataEncryptionKey'). Consequence in a real deployment: with encrypted data transfer (dfs.encrypt.data.transfer=true, common on secure clusters) and default key settings (10 min roll, 10 min token lifetime), a block key expires roughly 30-40 min after it was current. Balancer runs often last hours, so after about half an hour every block move fails. The balancer stops balancing, logs InvalidEncryptionKeyException on every DataNode it contacts, and eventually exits with NO_MOVE_PROGRESS, or keeps retrying without moving anything. The operator has to restart it over and over. The Mover shares the same KeyManager and is affected the same way.

**Execution (agent):** 1. MiniDFSCluster with encrypted data transfer and block access tokens on (the setup of TestBalancerWithEncryptedTransfer), 1 NN and 1 DN. The NN's block-key roll interval and token lifetime are set to 2 s with the existing test hooks setKeyUpdateIntervalForTesting/setTokenLifetime (the same hooks TestEncryptedTransfer#testLongLivedClient uses). This only shortens the default 10 min / 10 min so the test runs in seconds. 2. Write a file filling 30% of DN1 (replication 1), then add an empty DN2 so the cluster is unbalanced. dfs.balancer.max-size-to-move=1 block, so balancing takes several iterations. 3. Start a balancer the way Balancer#run does: one NameNodeConnector, and so one KeyManager, for the whole run, and a new Balancer per iteration. Iteration 0 moves one block. On that first SASL handshake the KeyManager creates a DataEncryptionKey from its currentKey (keyId K) and caches it in KeyManager.encryptionKey. 4. The balancer keeps running. Its BlockKeyUpdater keeps syncing block keys from the NN every interval/4. Meanwhile the NN's HeartbeatManager rolls the block keys: K is retired with expiry now+interval+lifetime and later expires. On the next KeyUpdateCommand each DN runs addKeys -> removeExpiredKeys and drops K. The test waits until no DN has K (hasKey). 5. Iterations 1..3 of the same balancer run: every replaceBlock to DN2 starts a SASL handshake with the cached DEK (keyId K). The DN's SaslDataTransferServer.getEncryptionKeyFromUserName -> BlockPoolTokenSecretManager -> BlockTokenSecretManager.retrieveDataEncryptionKey finds allKeys.get(K)==null and throws InvalidEncryptionKeyException at line 482. The Dispatcher logs 'Failed to move', puts both nodes on a 10 s delay, and never refreshes the key. No more bytes are moved (100 B before the expiry, 100 B after, 400 B left), and the test's assertion that the balancer keeps making progress fails.

**Stack frame (agent):** at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:484)  [this is the throw at line 482: the statement starts at 482 (bytecode 'new' at offset 28, LineNumberTable 'line 482: 28') but javac puts the constructor call (offset 57-66) on 484, the line of its last argument, so the frame captured in the exception's constructor reads :484; the output is in hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports/org.apache.hadoop.hdfs.server.balancer.TestBalancerEncryptionKeyExpiry-output.txt, under the DataNode's 'DataXceiver error processing unknown operation', Caused by: InvalidEncryptionKeyException: Can't re-compute encryption key for nonce, since the required block key (keyID=...) doesn't exist]

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.balancer.TestBalancerEncryptionKeyExpiry#testLongRunningEncryptedBalancer`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.balancer.TestBalancerEncryptionKeyExpiry#testLongRunningEncryptedBalancer' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/balancer/TestBalancerEncryptionKeyExpiry.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException: Can't re-compute encryption key for nonce, since the required block key (keyID=-989708322) doesn't exist. Current key: -989708320`, frame `at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:484)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h05m | 1 | 1,024,682 | 42 | 19,936 | 71,791 | 932,913 | $1.16 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
