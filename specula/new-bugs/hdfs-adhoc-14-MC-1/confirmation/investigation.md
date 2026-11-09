# MC-1 — Phase 1 investigation (evidence only)

Finding: a mirroring DataNode re-signs a forwarded write token with its own
`currentKey` but keeps the token's `keyId`; after a block-key rotation, the
next DN fails `BlockTokenSecretManager.checkAccess` at BTSM:418.

Pinned tree: `734dd8a67cd` (target.yaml `base_commit`). All line numbers below
are from `git show HEAD:<file>`, i.e. the un-instrumented tree. The confirmation
worktree was instrumented by the harness phase; it was reverted to the pinned
commit before building. The diff and untracked harness files are backed up in
`instrumentation-backup/`.

Ad hoc target (target.yaml): `BlockTokenSecretManager.java:418`,
`checkAccess(Token, String, ExtendedBlock, AccessMode, StorageType[], String[])`,
thrown `SecretManager.InvalidToken`, guard
`!MessageDigest.isEqual(retrievePassword(id), token.getPassword())`.

Persistent-findings lookup: `specula findings lookup --query
BlockTokenSecretManager.checkAccess --query TargetSafe --query updateToken
--query DataXceiver` returned `[]`. No prior record.

## Step 1 — Code audit

### Counterexample (spec/output/hunt/guided/s1_rotation_skew_w1_steady.out, 12 states, no fault)
1. Init: NN `nnCur=1`, `nnNext=2`; all DNs `dnCur=1`, `dnKeys={1,2}`. The NN's nextKey is already distributed.
2. `MCNNRotate(n1)`: NN `nnCur=2`, `nnNext=3`.
3. `MCNNMarkKeyUpdate(n1)`: `needKU={d1,d2,d3}`. No DN has applied the update.
4. `MCClientAddBlock(n1,<<d1,d2>>)`: write token `[kid 2, sk 2]`, signed by the NN with its new key.
5. `MCClientFetchDEK`: client DEK keyId 2.
6–8. Client→d1 encrypted SASL, then `MCTargetCheck` at d1 passes (`allKeys[2]` exists).
9. `MCDNWriteBlockMirrorSecret`: d1 (`dnCur=1`) re-signs the token. Result `[kid 2, sk 1]`, d1's own DEK keyId 1.
10–11. d1→d2 encrypted SASL succeeds (d2 has key 1).
12. `MCTargetCheck` at d2: HMAC(allKeys[2]) ≠ password(sk 1) → `targetFired`. `fireInfo=[k write, rsr d1, kid 2, sk 1, dn d2]`.

### Code path (pinned tree)
- NN rotation: `HeartbeatManager.Monitor.run` (HeartbeatManager.java:543-561) calls
  `blockManager.shouldUpdateBlockKey(now - lastBlockKeyUpdate)` → `BlockTokenSecretManager.updateKeys(long)` (BTSM:247-252) → `updateKeys()` (BTSM:257-281):
  `currentKey = nextKey`, and a new nextKey is generated. Then `setNeedKeyUpdate(true)` on every DN in the list (HBM:552-557). The Monitor loop sleeps 5 s (HBM:562).
- NN signs new tokens with its new key at once: `BlockManager.setBlockToken` → `generateToken` (BM:1664-1667) → `createPassword` (BTSM:465-479). This sets `keyId = currentKey.getKeyId()` and HMACs with `currentKey`.
- The DN learns the new currentKey only from its next heartbeat. `DatanodeManager.handleHeartbeat` → `blockManager.addKeyUpdateCommand` (DM:1971 → BM:1671-1677) sends `KeyUpdateCommand(exportKeys())`. The DN enqueues it to the CommandProcessingThread (BPServiceActor.java:745-780), and `BPOfferService.processCommandFromActive` `DNA_ACCESSKEYUPDATE` (BPOS:787-793) → `addKeys(..., true)` sets `currentKey` (BTSM:221-239). The window is up to one `dfs.heartbeat.interval` (default 3 s; DFSConfigKeys:1025-1026) plus command processing.
- At registration the DN gets `ExportedBlockKeys` with the NN currentKey (DM:1209). `exportKeys` (BTSM:197-204) exports `currentKey` plus `allKeys`, and `allKeys` includes nextKey. So every DN already holds the NN's next key before rotation.
- Mirroring DN (`DataXceiver.writeBlock`, mirror setup DataXceiver.java:794-858). At :824-829, if `dnConf.overwriteDownstreamDerivedQOP` is set, it uses `secretKey = blockPoolTokenSecretManager.get(bpid).getCurrentKey().getKey()`. At :830-832 it calls `saslClient.socketSend(..., blockToken, targets[0], secretKey)`.
- `SaslDataTransferClient.socketSend` (:197-207) → `checkTrustAndSend` (:222-243) → `send` (:259-302) → `getEncryptedStreams` (:312-335). Here `secretKey != null` → `updateToken(accessToken, secretKey, saslProps)` (:320-324).
- `updateToken` (:450-460) sets `handshakeMsg` and `password = createPassword(bkid.getBytes(), secretKey)`. It never touches `keyId`, so `keyId` stays the NN signer's id. This mutates the same `blockToken` object, which is then sent downstream in `Sender.writeBlock` (DataXceiver.java:845-858).
- DN1→DN2 SASL uses DN1's own DEK. `DataNode.getDataEncryptionKeyFactoryForBlock` (DataNode.java:3174-3184) → `generateDataEncryptionKey` (BTSM:530-541) uses DN1's currentKey and its keyId. DN2 recomputes it from `allKeys[keyId]` (BTSM:551-563), so the handshake succeeds.
- Downstream DN (DN2): `DataXceiver.writeBlock` → `checkAccess(replyOut, isClient, block, blockToken, Op.WRITE_BLOCK, ...)` (DataXceiver.java:731) → private `checkAccess` (:1442-1479) → `blockPoolTokenSecretManager.checkAccess(t, null, blk, mode, storageTypes, storageIds)` (:1454) → `BlockPoolTokenSecretManager.checkAccess` (BPTSM:133-139) → **BTSM.checkAccess(Token, …, StorageType[], String[]) :404-421**. `retrievePassword(id)` (BTSM:489-523) uses `allKeys.get(id.getKeyId())` = the NN's new key. The token password was HMACed with DN1's old currentKey, so they differ and InvalidToken is thrown at **BTSM:418**.
- Consumer of the failure: DataXceiver.checkAccess catch (:1456-1473) replies `ERROR_ACCESS_TOKEN` with `firstBadLink = DN2 xfer addr`, logs WARN `Block token verification failed`, and rethrows. `DataXceiver.run` logs the InvalidToken at TRACE (:327-331). DN1 relays the connect-ack status to the client. The client `DataStreamer.createBlockOutputStream` (DataStreamer.java:1947, `checkBlockOpStatus`) throws `InvalidBlockTokenException`, marks the firstBadLink node bad (:1974-1985) and returns false. `setupPipelineForCreate` (:1816-1866) abandons the block, excludes that DN, and retries `dfs.client.block.write.retries` (default 3) more times. After that it throws `IOException("Unable to create new block.")` (:1864). In the create stage, `setupPipelineForAppendOrRecovery` returns false unless `replace-datanode-on-failure.min-replication > 0` (:1640-1655).

### Reachability
Every step is normal operation. Configuration:
- `dfs.block.access.token.enable=true`
- `dfs.encrypt.data.transfer=true` (algorithm / cipher suites unset or empty, as in the workload test)
- `dfs.encrypt.data.overwrite.downstream.derived.qop=true` (documented in hdfs-default.xml:6435-6445, default false)
- replication ≥ 2

Periodic key rotation always runs (`dfs.block.access.key.update.interval`, default 600 min, minimum 1 min via config). No fault is required.

The reverse direction needs a token signed before rotation, used after the head DN applied the update. The head DN then re-signs with the new key under the old keyId. This is reachable but needs a narrow token-issue → connect interleaving.

### Safeguards encountered (to be tested in Phase 2, not dismissed)
- The client's `setupPipelineForCreate` retries with excluded nodes. The write may still succeed on another pipeline, for example a single-DN pipeline (no mirror) or one whose head DN has already applied the key update. This is a potential mask of the client-visible consequence; the check itself still fires.
- The lag closes on the head DN's next heartbeat (≤ 3 s by default), so the window is transient but recurs at every rotation.
- Healthy DNs excluded by the client are excluded only for this output stream (`dfs.client.write.exclude.nodes.cache.expiry.interval.millis`, 10 min). Under-replication is repaired later by NN re-replication. `DataNode.DataTransfer` uses DN-generated tokens without overwrite, so re-replication is unaffected.

### Trigger scenario (concrete)
1. Cluster: block tokens + encrypted data transfer + `overwrite.downstream.derived.qop=true`, ≥ 2 DNs.
2. HeartbeatManager.Monitor rotates the NN block key. The DNs' currentKey still holds the old key until their next heartbeat.
3. A client creates a file (replication ≥ 2) in that window. `addBlock` returns a token with the new keyId, signed with the new key.
4. Head DN1 verifies the token (it holds the new key as a pre-distributed nextKey). It then re-signs it with its old currentKey, keeping the new keyId, and forwards it to DN2.
5. DN2 throws InvalidToken at BTSM:418 and replies ERROR_ACCESS_TOKEN. The client abandons the block and excludes the healthy DN2.

## Step 2 — Developer knowledge (pinned tree only; no history/tracker yet)
Ad hoc Shared Rule 2: git history and tracker searches about the target are allowed only after the reproduction verdict is settled. They go in the Novelty section below.
- BTSM.generateKeys comment (BTSM:178-189): "NN will stop using the newly generated currentKey after the first keyUpdateInterval, however it may still be used by DN and Balancer to generate new tokens before they get a chance to sync their keys with NN. Since we require keyUpdInterval to be long enough so that all live DN's and Balancer will sync their keys with NN at least once during the period ...". The developers expect a DN's currentKey to lag the NN's. The design tolerates this because a token's `keyId` always names the key that signed it, and old keys are retained and the next key pre-distributed.
- SaslDataTransferClient.getSaslStreams comment (:425-430): "secretKey != null only happens when this is called by DN sending to downstream DN ... if a different QOP is desired for inter-DN communication, the check below will use new QOP to create a secret, which includes the new QOP." Neither this comment nor `updateToken` mentions keyId.
- hdfs-default.xml:6435-6455 documents `dfs.encrypt.data.overwrite.downstream.derived.qop` (default false) and `...new.qop`. This is a supported, documented option. Nothing says it is incompatible with key rotation.
- Tests:
  - `TestMultipleNNPortQOP#testMultipleNNPortOverwriteDownStream` (TestMultipleNNPortQOP.java:224-293) runs the overwrite flag only on a fresh cluster, where NN and DN currentKeys are equal. It has no key rotation.
  - `TestEncryptedTransfer#testLongLivedClient`, `#testFileChecksumWithInvalidEncryptionKey` and `#testLongLivedClientPipelineRecovery` (TestEncryptedTransfer.java:308-332, 355-399, 462-520) exercise key rotation via `btsm.setKeyUpdateIntervalForTesting(2 * 1000)`, but never with the overwrite flag.
  - No test combines the two.

## Step 3 — Known-status / pre-filter
Source is MC (a real TargetSafe violation trace exists), so the code-review × known drop does not apply. The tracker/history novelty search is deferred until the reproduction verdict is settled (ad hoc Shared Rule 2), and its result is recorded below.

## Phase 2 — Reproduction

Repro files:
- `repro/test_bugMC-1_rotation_skew.java`, installed as `SpeculaAdhoc14MC1Test` in package `org.apache.hadoop.hdfs`, module hadoop-hdfs.
- `repro/test_bugMC-1_rotation_skew.sh`, the runner.

The runner verifies that the worktree main sources are identical to `734dd8a67cd`. It builds hadoop-hdfs-client and hadoop-hdfs in one reactor, so the test does not pick up the instrumented client jar in the shared `deps` repo. It then runs each method with `timeout 30m`. Each run prints a classpath check showing the classes come from the worktree `target/classes` and that the Specula instrumentation is absent.

Variant of the workload `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]` (resolverClazz=null). `setEncryptionConfigKeys()` and `getFileSystem()` are copied verbatim. Additions:
- `dfs.encrypt.data.overwrite.downstream.derived.qop=true` (the CE config).
- `dfs.block.access.key.update.interval=1` (minutes). This is time compression through a documented key; the NN's own HeartbeatManager.Monitor performs the rotation.
- 4 writer threads doing normal `create` / `write` / `hflush` / `close`.
- Log levels: the DataNode logger at TRACE, so DataXceiver.run's `LOG.trace(s, t)` exposes the InvalidToken stack.
- Read-only `getCurrentKey()` getters to print key state.

There is no fault injection, sleep in system code, state injection or source patch.

### Escalation level reached: Level 0
Normal API and configuration only; the timing is the natural heartbeat lag.

### Runs
1. **run1** (`runs/run1-emptyalg/`, `run1-trigger3dn.txt`): first attempt with the workload's `algorithm=""`. Every DN→DN encrypted handshake failed with `DIGEST-MD5: Unable to negotiate a strength level for 'auth-conf'` (DataXceiver.run:333). The client maps "" to null (PBHelperClient.java:1739), but a DN uses `dnConf.encryptionAlgorithm` ("") for its own DEK (DNConf.java:253, DataNode.java:2142). All 1287 writes ended on 1-node pipelines and no InvalidToken occurred. This is NOT the finding. Side check run4 (`runs/side-emptyalg-flagoff/`, flag OFF, algorithm "") shows the same 10936 handshake failures and 1310/1310 degraded writes. So it is independent of the overwrite flag; it is reported separately as a side observation. The finding's configuration is a negotiable (unset) algorithm, so the variant leaves the key unset, as `testEncryptedWrite*` do.
2. **run2 — trigger, 3 DNs, flag on, algorithm unset** (`runs/evidence-trigger-3dn.txt`):
   - 2 NN rotations. All DNs applied the KeyUpdateCommand about 1.2 s after each rotation.
   - 80 InvalidToken with top frame `BlockTokenSecretManager.checkAccess(BlockTokenSecretManager.java:418)`. They fall in the two skew windows: 36 events at 11:36:58-59 and 44 at 11:37:58-59.
   - Rejected token keyId = the NN's new currentKey (255436309). Every DN's currentKey was still 255436308 at the instant of firing #1.
   - Client: 80 × `InvalidBlockTokenException: Got access token error ... firstBadLink as <healthy DN>`, 80 Abandoning, 80 Excluding datanode.
   - 40 writes completed on a 1/3-node pipeline; 0 application failures.
   - Steady state outside the windows: 28,830 writes, 57,687 mirror re-signs, no failure.
3. **run3a — negative control, flag OFF, same config** (`runs/evidence-control-3dn.txt`): 2 rotations with the same ~1.2 s windows. 27,359 writes, 0 InvalidToken, 0 abandon/exclude, 0 degraded. Raw log: 0 `Block token verification failed`, 0 `InvalidBlockTokenException`.
4. **run3b — consequence, 6 DNs, replication 3, flag on** (`runs/evidence-trigger-6dn.txt`):
   - 2018 InvalidToken at BTSM:418.
   - **502 application write failures** `java.io.IOException: Unable to create new block.` (DataStreamer.java:1864). Each failed stream shows 4 attempts within ~40 ms, each `InvalidBlockTokenException` → Abandoning → Excluding a different healthy DN.
   - All failures fall inside the two ~1.45 s post-rotation windows (84+146 at 11:46:12-13, 112+160 at 11:47:12-13).
5. **final** (`runs/final/`, extract `runs/final/evidence-final.txt`): canonical re-run of all three methods with the exact final repro file. Runs 2–3 used a version that differed only in a default-off env-var guard for the side check.
   - **Trigger, 3 DNs:** 108 InvalidToken at BTSM:418 and 108 InvalidBlockTokenException / Abandoning / Excluding. 54 writes ended on 1/3-node pipelines; 34,171 writes OK; 0 application failures. At firing #1 the key state was `NN.currentKey=1098965503`, all DNs `currentKey=1098965502`, and the token keyId was 1098965503. DNs applied the update 1149 ms and 1124 ms after the two rotations. Same stack as below.
   - **Control, flag off:** 0 / 0 / 0 over 33,007 writes.
   - **6 DNs:** 1977 InvalidToken at BTSM:418 (230+728 and 271+748 per window-second). **492 application write failures** ("Unable to create new block."; DataStreamer Exception 56+182 and 65+189 per window-second). 34,248 writes OK.
   - Raw outputs are gzip-compressed in place (`runs/**/output-*.txt.gz`).

### Stack frame (run2, first firing; DataXceiver.run TRACE)
```
org.apache.hadoop.security.token.SecretManager$InvalidToken: Block token with block_token_identifier (... keyId=255436309 ... access modes=[WRITE] ...) doesn't have the correct token password
	at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.checkAccess(BlockTokenSecretManager.java:418)
	at org.apache.hadoop.hdfs.security.token.block.BlockPoolTokenSecretManager.checkAccess(BlockPoolTokenSecretManager.java:137)
	at org.apache.hadoop.hdfs.server.datanode.DataXceiver.checkAccess(DataXceiver.java:1454)
	at org.apache.hadoop.hdfs.server.datanode.DataXceiver.writeBlock(DataXceiver.java:731)
	at org.apache.hadoop.hdfs.protocol.datatransfer.Receiver.opWriteBlock(Receiver.java:176)
	at org.apache.hadoop.hdfs.protocol.datatransfer.Receiver.processOp(Receiver.java:110)
	at org.apache.hadoop.hdfs.server.datanode.DataXceiver.run(DataXceiver.java:299)
```
BPTSM:137 is the 6-argument overload, so this is the target method `checkAccess(Token, String, ExtendedBlock, AccessMode, StorageType[], String[])`.

### CE ↔ real-run mapping
| CE step | Real run |
|---|---|
| 2 NNRotate | `HeartbeatManager$Monitor` logs "Updating block keys"; NN key ...308→...309 |
| 3 MarkKeyUpdate | DNs get `DNA_ACCESSKEYUPDATE` ~1.2 s later (BPOfferService:789) |
| 4 ClientAddBlock | The rejected token has keyId 255436309, the NN's new key |
| 6-8 client→d1, d1 check passes | The head DN accepted the client and forwarded; firstBadLink is the downstream DN |
| 9 d1 re-sign with dnCur=1 keeping kid=2 | Mirror re-sign path ("DataNode overwriting downstream QOP"); head DN currentKey=...308 at the instant |
| 10-11 d1→d2 SASL ok | The downstream DN processes WRITE_BLOCK; no SASL error |
| 12 d2 TargetCheck fails | InvalidToken at BTSM:418 in DataXceiver.writeBlock→checkAccess |

### Verdict basis
REPRODUCED at Level 0.
- **Ad hoc same-bug test met:** InvalidToken is thrown from BTSM.java:418 in the target method. The repro starts from a workload variant in the same module. No faults are used, which matches the CE. Timing comes only from a config key; no guard operand is written and the target method is not edited.
- **Consumers with a wrong outcome:**
  - DataXceiver.checkAccess (:1454-1473) rejects an authorized WRITE_BLOCK with ERROR_ACCESS_TOKEN.
  - DataStreamer.createBlockOutputStream (:1947/1959) and setupPipelineForCreate (:1846-1864) abandon the block and exclude healthy DNs.
  - Writes completed with 1/3 replicas (run2). Application writes failed with "Unable to create new block." (run3b, 502 writes).
- **Permanence:** the key skew closes at the next heartbeat but recurs at every rotation. The client retry masks the failure only when it lands on a 1-node pipeline or an updated head DN. When it does not, the application write fails and is not retried by HDFS (run3b). The negative control proves the overwrite re-sign is the cause.

## Novelty search (performed AFTER the verdict was settled; ad hoc Shared Rule 2)
Queries and results. These set the Novelty field only.

Local git (pinned repo plus the local `trunk` ref; read-only, no checkout):
- G1 `git log -15 -- SaslDataTransferClient.java`: HDFS-13699 (feature), HDFS-14611, HDFS-14759, HDFS-16332, HDFS-17575, and others. None changes the keyId handling of `updateToken`.
- G2 `git log -S "updateToken(" -- SaslDataTransferClient.java`: HDFS-14611 only.
- G3 `git log -S overwriteDownstreamDerivedQOP -- DataXceiver.java`: HDFS-13699 only.
- G4 `git log --since=2019 --grep "downstream.*qop|derived.qop|HDFS-17195|HDFS-13699"`: HDFS-13699 only.
- G5-G8: local `trunk` has 167 commits after the base, tip 2026-10-24. Those touching the cited files are HDFS-17967 (2026-09-17; DataXceiver: InvalidEncryptionKeyException retry, which moves the overwrite block into a retry loop but leaves the `getCurrentKey()` re-sign unchanged), HDFS-17953 (IBR OOM) and HDFS-17899 (InvalidEncryptionKeyException in the Balancer and others). Trunk `updateToken` (SaslDataTransferClient.java:450-460) and DataXceiver:831-836 are unchanged, so the defect is unfixed on trunk.

Web and tracker:
- W1 WebSearch `HDFS "overwrite.downstream.derived.qop" block key InvalidToken`
- W2 WebSearch `HDFS JIRA DataNode overwrite downstream QOP updateToken keyId block token "correct token password" pipeline`
- W3 WebSearch `HDFS-13699 DataNode overwrite downstream QOP follow-up bug key rotation`
- W4 WebFetch HDFS-13699: resolved feature; only linked issue is HDFS-14759 (logging).
- W5 WebFetch HDFS-13541: sub-tasks HDFS-13547/13566/13617/13699/14611; links HDFS-16644 and HDFS-17025. None concerns keyId or rotation.
- W6 WebFetch PR #6089 / HDFS-17195: NPE in the same `writeBlock` overwrite branch when blockPoolTokenSecretManager is null. Different mechanism; closed stale 2025-10-12, not merged.
- W7 WebSearch `"SaslDataTransferClient" "updateToken" keyId currentKey DataNode block key mismatch HDFS`: HDFS-16136, HDFS-15651, HDFS-14305, HDFS-16332, HDFS-13473. All are different mechanisms: missing DEK key, dead command thread, serial collision, expired token, and a key-pull proposal.
- W8 WebSearch `HDFS selective encryption inter-DataNode QOP "InvalidToken" "doesn't have the correct token password" write pipeline after block key update`: HDFS-14509 (2.x/3.x identifier fields), HDFS-16332, HDFS-7394. Different mechanisms.
- W9 WebFetch HDFS-16136: InvalidEncryptionKeyException retry handling. Different.
- W10 GitHub PR search `is:pr derived.qop`: 0 results. `is:pr "overwrite downstream"`: #6089 only. `is:pr updateToken SaslDataTransferClient`: 0 results.
- W11 JIRA JQL `project=HDFS AND text~"overwrite.downstream"`: 0 results. `text~"updateToken" OR "DataNode overwriting downstream QOP" OR "derived.qop"`: HDFS-13699, HDFS-17195, HDFS-12431, HDFS-15756. None matches.

**Novelty: NEW.** No issue, PR or commit reports the mechanism "the mirror DN re-signs the forwarded block token with its own currentKey but keeps the token's keyId, so the next DN fails checkAccess when the keys differ (after a rotation)". The closest neighbours, HDFS-17195 (an NPE in the same branch) and HDFS-13473 (push-based key lag), are different defects.
