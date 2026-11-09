# MC-1 investigation (Phase 1 — evidence only)

Target (target.yaml): `BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])` throws
`InvalidEncryptionKeyException` at `BlockTokenSecretManager.java:482` when `allKeys.get(keyId) == null`.
Pinned tree: base_commit 595e4680154 (worktree HEAD `595e468 base`). The worktree held the harness's
trace instrumentation; it was saved to `instrumentation.patch` / `instrumentation-untracked/` and
reverted so the reproduction runs on pristine code. The throw is at line 482 in both versions.

Counterexample: `spec/output/MC_hunt_stale_balancer_dek_final.out`, 68 states, `faults` all 0 (no
fault used). The Balancer starts at now=3 with `balCur=11`, and its DEK is minted from key 11 (`balDEK=11`).
The NN rolls keys at 4, 6 and 8 (I=L=2); at the roll at now=9, d1's addKeys drops key 11
(`dnKeys[d1]` = {12,13,14,15}). A Balancer connection `[dst |-> d1, keyId |-> 11]` is then checked → `targetFired`.

## Step 1 — code audit

- `KeyManager.newDataEncryptionKey` (KeyManager.java:113-124 pristine): `if (encryptionKey == null) encryptionKey =
  blockTokenSecretManager.generateDataEncryptionKey(); return encryptionKey;`. No expiry check, and nothing
  in KeyManager or anywhere in src/main (grep `encryptionKey = null`) ever resets the field.
- `BlockTokenSecretManager.generateDataEncryptionKey` (455-466) uses the worker's `currentKey.getKeyId()`
  and sets expiryDate = now + tokenLifetime. Nobody ever reads that expiryDate on the Balancer side.
- NN roll `updateKeys()` (225-245) gives the retiring currentKey the final expiry `now + I + L` (232-234).
  The roll is triggered from HeartbeatManager.Monitor (HeartbeatManager.java:439-445, 5 s poll), and it sets
  `needKeyUpdate` on every DN. The KeyUpdateCommand is sent in the heartbeat reply (BlockManager.java:1300-1305).
- DN `addKeys` (196-209) calls `removeExpiredKeys()` (182-191) first, which drops keys with expiry < now.
- Call chain of the check: `Balancer.run` (Balancer.java:670-725, one NameNodeConnector/KeyManager for the
  whole run) → `Balancer.runOneIteration` → `Dispatcher.PendingMove.dispatch` (Dispatcher.java:336-405) →
  `saslClient.socketSend(sock, …, km, accessToken, target)` (361) → `SaslDataTransferClient.checkTrustAndSend`
  (209: `encryptionKeyFactory.newDataEncryptionKey()` = KeyManager) → target DN `DataXceiver.run`
  (233 `saslServer.receive`) → `SaslDataTransferServer` → `BlockPoolTokenSecretManager.retrieveDataEncryptionKey`
  → `BlockTokenSecretManager.retrieveDataEncryptionKey` :482.
  The Mover uses the same NameNodeConnector/KeyManager/Dispatcher.
- Safeguards checked:
  - DFSClient has both safeguards: `newDataEncryptionKey` refreshes when `expiryDate < now`
    (DFSClient.java:1725-1726), and DataStreamer/DFSInputStream call `clearDataEncryptionKey()` on
    InvalidEncryptionKeyException (DataStreamer.java:139,1786; DFSInputStream.java:580,1066).
  - KeyManager/Dispatcher have neither. Dispatcher's catch (375-392) only logs "Failed to move", marks
    failure and delays the nodes. It does not retry with a new key.
  - SaslDataTransferServer (414-426) sends the invalid-key status back to the client. The comment says
    "the client will get a new encryption key from the NN and retry". The Balancer never does that.
  - The BlockKeyUpdater (KeyManager.java ~150-190) refreshes the worker's *block keys* every I/4, so block
    tokens stay fresh. The cached DEK is not regenerated.
- Reachable by normal use: yes. Any encrypted-transfer Balancer/Mover run that lasts past the DN-side expiry of
  the key current at its first move hits it: about 2I+L after that key became current, dropped at the
  next DN addKeys (a roll). That is ~20-35 h at the 600-min defaults, and a Balancer run on a large cluster
  can last that long.
- Trigger scenario: (1) cluster with encrypted data transfer + block tokens. (2) Balancer starts; its first move
  mints the DEK from current key K. (3) NN rolls: K retires with final expiry R+I+L. (4) At the next roll after
  that time, every DN's addKeys removes K. (5) Every later Balancer move presents keyId K. Every target DN
  throws at :482, and every move fails. The Balancer makes no progress and exits NO_MOVE_PROGRESS.

## Step 2 — developer knowledge
- Comment at SaslDataTransferServer.java:418-421 (verbatim): "This could just be because the client is
  long-lived and hasn't gotten a new encryption key from the NN in a while. Upon receiving this error, the
  client will get a new encryption key from the NN and retry connecting to this DN." This is the intended
  contract. DFSClient implements it, and KeyManager does not.
- Git history: the worktree has a single squashed commit (`595e468 base`), so blame gives nothing.
- Tests: TestBalancerWithEncryptedTransfer runs for <60 s at the default 600-min interval, so it never
  crosses a key roll. No existing test covers a Balancer run that spans key rolls. (TestEncryptedTransfer
  testLongLivedClient/Writer cover the DFSClient path only.)

## Step 3 — known status
Source is MC with an actual counterexample, so the code-review pre-filter does not apply → Phase 2.
The tracker search for Novelty runs after the verdict is settled (adhoc Shared Rule 2). Queries are recorded below.

## Novelty search (after verdict)
(see bottom of file — appended after reproduction)

### Queries (run after the reproduction verdict was settled; they set the Novelty field only)
1. WebSearch "HDFS JIRA long running balancer fails expired DataEncryptionKey KeyManager InvalidEncryptionKeyException"
   → HDFS-11741, HDFS-10609, HDFS-16136, HDFS-9698
2. WebSearch "HDFS-11741 balancer encryption key expire" → HDFS-11741 (Resolved), mail-archive msg184804 / msg187006
Result: **KNOWN**. https://issues.apache.org/jira/browse/HDFS-11741, "Long running balancer may fail due to
expired DataEncryptionKey" (Resolved/fixed upstream), reports the same mechanism at the same site: the
balancer KeyManager syncs block keys with the NN but never refreshes its DataEncryptionKey, so a long Balancer
run fails with InvalidEncryptionKeyException (after 20-30 h at 10 h settings). The upstream fix makes
KeyManager.newDataEncryptionKey regenerate the DEK aggressively (expiry-checked). The pinned tree
(595e4680154, 3.0.0-alpha4-SNAPSHOT) does not contain that fix: KeyManager.java:116 still has `if (encryptionKey == null)` only.
Related but different: HDFS-10609 (DFSClient pipeline-recovery retry); HDFS-16136 (open; residual unretried IEKE after these fixes).
