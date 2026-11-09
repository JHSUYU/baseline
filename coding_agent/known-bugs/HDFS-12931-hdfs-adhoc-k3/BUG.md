# HDFS-12931 (File checksum fails): not detected

Case `hdfs-adhoc-k3`, run at the bug's buggy version (the parent of its fix, `../../data/known-fixes.json`), one commit `base`, no history.

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:490`, `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`, throws `org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException` when `key == null   (key = allKeys.get(keyId))`
- Starting test: `org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`

## Judgement (independent reviewer, `../../data/CRITERIA.md`)

**Detected:** no

**What the agent found:** In an HA cluster with encrypted transfer, the standby NN restarts and the DataNodes take its block key as currentKey; the standby then crashes and a target DN restarts with only the active NN's keys. NN-driven re-replication (DataNode.DataTransfer, DN->DN) then fails at the receiving DN's retrieveDataEncryptionKey check.

**Same root cause as HDFS-12931?** No. The failing execution is a DN-to-DN replication transfer. The sending DN builds its DataEncryptionKey in BlockTokenSecretManager.generateDataEncryptionKey (BlockTokenSecretManager.java:463-468) from a currentKey that the standby NN set through addKeys (BlockTokenSecretManager.java:204-210). The receiving DN rejects it at line 490-492. The stack trace is DataNode$DataTransfer.run (DataNode.java:2499) -> SaslDataTransferClient, and on the receiver DataXceiver.run -> SaslDataTransferServer. getFileChecksum and FileChecksumHelper are never called (no FileChecksum frames in the log). The HDFS-12931 fix changes only FileChecksumHelper.checksumBlock (buggy FileChecksumHelper.java:306-337), adding a catch for InvalidEncryptionKeyException that clears the client's key and retries once. That code is not on this path. The defect the agent found is the HA standby-key/currentKey divergence, which is HDFS-17383 (case k2), not this bug.

**Realistic?** Yes. Every step is allowed: an HA MiniDFSCluster, restarting and shutting down the standby NN, restarting a DN, and an ordinary setReplication call. The test uses no reflection or mocks to create state, and the test-side hasKey/generateDataEncryptionKey calls are only assertions. But the trigger exercises a different code path from the known bug.

**On the fixed version** (buggy tree + the fix's production changes, `fix/prod.diff`): **REPRODUCED**. On the buggy tree plus the fix, the check still fires at BlockTokenSecretManager.java:492 the same way (REPRODUCED, validate-fixed-1.log). The replication failure is not handled or removed, because the fix touches only the client checksum path. So the consequence remains, which agrees with the finding being a different bug.

**Reason:** The agent's reproduction is valid and realistic, but its root cause is the DataNode's currentKey coming from the standby NN, which breaks DN-to-DN replication. That is HDFS-17383's defect. It does not reach the missing InvalidEncryptionKeyException handling in FileChecksumHelper.checksumBlock that HDFS-12931 fixes, and the fixed version still fails the same way, so the known bug is not detected.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Block keys are coordinated separately with each NameNode: a DN merges the key sets of the active and the standby NN, but its single currentKey is whatever the last NN to send keys said, which can be the standby. A DN then builds DN->DN data-encryption keys from a block key that only one NN (and only the DNs that heard from it) knows. All DNs only share the keys that the live, active NN distributes. If that standby NN goes down, every DN that (re)starts or (re)registers afterwards gets only the active NN's keys and rejects transfers from DNs whose currentKey came from the dead standby. The client never sent anything wrong: the sending DN picked a key that the coordination never gave to the receiver. Nothing on the DN->DN path recovers from this. DataNode.DataTransfer just logs the failure, and the DN-side mirror connections in DataXceiver (writeBlock pipelines, replaceBlock/copy for balancer and mover, EC reconstruction through StripedBlockWriter) build keys the same way. The problem lasts until the active NN's next key roll (dfs.block.access.key.update.interval, 600 minutes by default) replaces the DN's currentKey. Consequence in a real deployment: an ordinary standby-NN outage plus a DN restart (rolling restarts, a DN crash) stops re-replication into the restarted DNs for hours. Under-replicated blocks stay under-replicated, risking data loss if more nodes fail. Pipelines through the affected DN pairs fail and need pipeline recovery, and balancer/decommission moves to those DNs fail.

**Execution (agent):** Setup: HA MiniDFSCluster (nn0 active, nn1 standby), 2 DataNodes, dfs.encrypt.data.transfer=true, dfs.block.access.token.enable=true (same config as TestEncryptedTransfer). (1) Client writes /file-to-replicate with replication 1; its only replica is on DN A, the other DN is B. (2) Standby nn1 is restarted (e.g. routine maintenance). On restart it generates fresh block keys. Both DNs re-register with nn1, and BPOfferService.registrationSucceeded -> BlockTokenSecretManager.addKeys sets each DN's currentKey to nn1's new current key. That is the key a DN uses in generateDataEncryptionKey() for its own outgoing DN->DN transfers. The test checks that A's generated key id is known to nn1 and not to nn0. (3) Standby nn1 crashes and stays down. (4) DN B restarts while nn1 is down, so it registers only with active nn0 and gets only nn0's block keys. (5) The client raises replication to 2. nn0 sends DNA_TRANSFER to A with target B. In DataNode.DataTransfer A runs the encrypted SASL handshake using a DataEncryptionKey built from its currentKey (nn1's key). B's SaslDataTransferServer.getEncryptionKeyFromUserName -> BlockPoolTokenSecretManager.retrieveDataEncryptionKey -> BlockTokenSecretManager.retrieveDataEncryptionKey finds allKeys.get(keyId)==null and throws InvalidEncryptionKeyException. B logs 'DataXceiver error processing unknown operation' with the stack, and A logs 'Failed to transfer ... got InvalidEncryptionKeyException'. The re-replication fails, the block stays at 1 replica, and later attempts fail the same way. Reproduced on 2 of 2 runs.

**Stack frame (agent):** at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:492)  -- this is the check at line 490: the statement `throw new InvalidEncryptionKeyException("Can't re-compute encryption key" + ... + currentKey.getKeyId());` spans lines 490-492 and javac attributes the constructor invocation (bytecode pc 66; the throw starts at pc 28 = line 490) to line 492 (verified with javap -l). Message: "Can't re-compute encryption key for nonce, since the required block key (keyID=...) doesn't exist"; the exception is created only at that statement.

## Reproduction

- Test: `org.apache.hadoop.hdfs.TestEncryptedTransferHAStandbyKey#testReplicationFailsAfterStandbyCrashAndDataNodeRestart`
- Command: `source /bulk/codingagent/cases/hdfs-adhoc-k3/agent/env.sh && cd /bulk/codingagent/cases/hdfs-adhoc-k3/agent/hadoop && mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.TestEncryptedTransferHAStandbyKey#testReplicationFailsAfterStandbyCrashAndDataNodeRestart' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestEncryptedTransferHAStandbyKey.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException: Can't re-compute encryption key for nonce, since the required block key (keyID=1332702302) doesn't exist. Current key: -643002747`, frame `at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:492)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h06m | 1 | 1,569,878 | 50 | 23,071 | 76,898 | 1,469,859 | $1.37 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
