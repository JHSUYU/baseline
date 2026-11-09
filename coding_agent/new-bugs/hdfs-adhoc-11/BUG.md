# hdfs-adhoc-11: After a NameNode restart the Balancer/Mover keeps using a cached data encryption key derived from a lost block key, so all block moves to DataNodes that registered after the restart fail for up to the token lifetime (10h).

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:559`, `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`, throws `org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException` when `key == null   (key = allKeys.get(keyId))`
- Starting test: `org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Encrypted data transfer with block tokens; a balancer round is running (one NameNodeConnector/KeyManager for the whole doBalance), the NameNode restarts mid-round and regenerates its unpersisted block keys, and a DataNode added after the restart becomes a move target.

**Why (root cause in the source):** KeyManager.newDataEncryptionKey (server/balancer/KeyManager.java ~L120-145) caches the DataEncryptionKey until its expiry (token lifetime, 10h by default) and only regenerates it when it expires. BlockKeyUpdater refreshes only the BlockTokenSecretManager, and Balancer.doBalance (Balancer.java ~L899-930) reuses the same connectors for every iteration. The restarted NN has fresh block keys, and a DN that registers afterwards only gets those (BlockTokenSecretManager.addKeys L228-244 merges keys and never brings back old ones). So the new DN's SaslDataTransferServer -> retrieveDataEncryptionKey (BlockTokenSecretManager.java:559) cannot find the balancer's keyId. Nothing in the Dispatcher handles InvalidEncryptionKeyException, whereas DFSClient clears and refetches its key (DFSInputStream L663-669, DataStreamer L1961-1968). Every move to a post-restart DN therefore fails until the key expires or the balancer is restarted. The trigger is realistic: a mini cluster, an NN restart, a DN added, and the real balancer iteration code. The 500ms IPC idle time only stands in for a realistic restart duration.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The key the DN rejects is not invalid: the NameNode issued it from its own block key, it is within its lifetime (expiryDate is hours in the future), and the DNs that existed before the restart still accept it. The coordination contract (stated in KeyManager#newDataEncryptionKey and BlockTokenSecretManager#generateKeys) is that an unexpired data encryption key's block key is still known to all DataNodes. That contract breaks because NN block keys are not persisted across a restart and are not re-sent to DataNodes that register later, while the Balancer keeps the cached key and never invalidates it on an InvalidEncryptionKeyException or when the NN's key set changes. In a real deployment, adding new DataNodes is the main reason to run the balancer, and NN restarts (failover, rolling upgrade, crash) during a long balancing round are common. All block moves to every DataNode that joined or restarted after the NN restart then fail for up to the token lifetime (10h by default). The balancer either spins without progress or exits with NO_MOVE_PROGRESS after 5 idle iterations, so the new nodes stay empty and the cluster stays unbalanced. The Mover uses the same NameNodeConnector/KeyManager code and is very likely affected the same way (not tested).

**Execution (agent):** Setup: encrypted data transfer (dfs.encrypt.data.transfer=true) with block tokens, non-HA NameNode, SimulatedFSDataset, 100-byte blocks. 1) DN0 is filled to 60% with single-replica blocks; an empty DN1 is added. 2) A balancer round starts exactly as Balancer#doBalance does it: one NameNodeConnector (holding one KeyManager) for the whole round, a new Balancer per iteration. Iteration 1 moves 3 blocks DN0->DN1; for that KeyManager#newDataEncryptionKey derives a DataEncryptionKey from the NN's current block key K_old and caches it for the token lifetime (10h). 3) The NameNode restarts (crash/maintenance) while the balancer round is still running. Block keys are not persisted, so the new NN instance has a fresh random key set (K_new..). DN0/DN1 re-register and get K_new added, but they keep K_old because it is not expired. The balancer's BlockKeyUpdater also only updates its BlockTokenSecretManager, not the cached DataEncryptionKey; the cached key is unexpired, so it is reused. 4) A new DataNode DN2 is added (it would be the same with any DN that restarts after the NN restart). It registers with the restarted NN and only receives the new NN's keys. 5) The balancer's next iteration picks DN2 (underutilized) as target and dispatches replaceBlock moves DN0->DN2 and DN1->DN2. In the SASL handshake DN2's SaslDataTransferServer calls BlockPoolTokenSecretManager.retrieveDataEncryptionKey(keyId=K_old) -> BlockTokenSecretManager.retrieveDataEncryptionKey: allKeys.get(K_old)==null -> InvalidEncryptionKeyException ('required block key (keyID=K_old) doesn't exist. Current key: K_new'). The balancer logs 'Failed to move ...' with the InvalidEncryptionKeyException and moves 0 blocks to DN2. The Dispatcher has no handling for InvalidEncryptionKeyException (unlike DFSClient, which clears its key and refetches), so every later iteration fails the same way until the cached key expires hours later. The only test-specific setting is ipc.client.connection.maxidletime=500ms plus a 2s pause, so that the balancer does not reuse an IPC connection to the old NN process; in a real deployment an NN restart takes far longer than the default 10s idle time.

**Stack frame (agent):** at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:561)  -- this is the 'throw new InvalidEncryptionKeyException(...)' statement of the check at line 559; the statement spans lines 559-561 and javac attributes the constructor call (where the stack trace is filled in) to line 561 (javap line table: line 559 -> pc 28, line 561 -> pc 37, invokespecial <init> at pc 45).

## Reproduction

- Test: `org.apache.hadoop.hdfs.server.balancer.TestBalancerEncryptionKeyAfterNNRestart#testBalancerMoveFailsAfterNameNodeRestart`
- Command: `source /bulk/codingagent/cases/hdfs-adhoc-11/agent/env.sh && mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.server.balancer.TestBalancerEncryptionKeyAfterNNRestart#testBalancerMoveFailsAfterNameNodeRestart' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false   (stack trace in hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports/org.apache.hadoop.hdfs.server.balancer.TestBalancerEncryptionKeyAfterNNRestart-output.txt)`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/balancer/TestBalancerEncryptionKeyAfterNNRestart.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/4 tries hit the check); exception `Caused by: org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException: Can't re-compute encryption key for nonce, since the required block key (keyID=429315927) doesn't exist. Current key: 1062778719`, frame `at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:561)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h18m | 1 | 2,446,812 | 68 | 34,793 | 98,720 | 2,313,231 | $1.95 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
