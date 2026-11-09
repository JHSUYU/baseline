# MC-4 investigation (Phase 1: evidence only)

Finding: "An NN restart plus a DN restart invalidate a long-lived client's cached DEK"
(model checking, Scenario 4 sub-case (a), invariant `TargetSafe` via the gated
variant `TargetSafeBackward`; counterexample `spec/output/hunt/gated/G_S4a_backward.out`,
cfg `G_S4a_backward.cfg`: NNs = {n1}, DNs = {d1, d2}, MaxNNRestart = 1, MaxDNRestart = 1,
MaxRolls = 0).

Target (`/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-11/target.yaml`):
`BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`, throw of
`InvalidEncryptionKeyException` at `BlockTokenSecretManager.java:559` (statement spans
559-561), guard `key == null (key = allKeys.get(keyId))`. Pinned tree: `734dd8a67cd`.

## Counterexample (13 states)

| CE state | action | effect |
|---|---|---|
| 3 | `MCClientGetDek(n1)` | client caches DEK keyed `<<n1,1,1>>` (NN incarnation 1) |
| 4-7 | `MCNNRegisterDatanode` / `MCDNRegistrationSucceeded` for d1, d2 | both DNs hold `{<<n1,1,1>>,<<n1,1,2>>}` |
| 8 | `MCNNRestart(n1)` | `nnInc = 2` |
| 10 | `MCDNRestart(d1)` | `dnKeys[d1] = {}` |
| 11-12 | d1 re-registers | `dnKeys[d1] = {<<n1,2,1>>,<<n1,2,2>>}` |
| 13 | `MCClientConnect(d1)` | cached key `<<n1,1,1>>` not in d1's keys -> `targetFired` |

## Step 1: code audit (pinned tree, `git show HEAD:<path>`)

Key space on the NN, in memory only:
- `BlockTokenSecretManager.java:140-158` master constructor: `allKeys = new HashMap` (148),
  `setSerialNo(new SecureRandom().nextInt(Integer.MAX_VALUE))` (154), `generateKeys()` (157).
  `generateKeys` (174-198) creates `currentKey`/`nextKey` from the fresh serial. Nothing is
  persisted, so a restarted NN issues keys from a new random serial.

DN worker:
- `DataNode.java:1942` `startDataNode`: `this.blockPoolTokenSecretManager = new BlockPoolTokenSecretManager();`
  A restarted DN is a new `DataNode` object with an empty manager.
- `DataNode.java:2115-2146` `registerBlockPoolWithSecretManager`: a new worker
  `new BlockTokenSecretManager(0, lifetime, bpid, alg, proto)` (2141-2144) only if the pool
  is not registered yet (2130).
- `BPOfferService.java:422-445` `registrationSucceeded`: `addKeys(bpid, reg.getExportedKeys(), updateCurrentKey)` (436-440).
- `BlockTokenSecretManager.java:228-244` `addKeys` merges keys (old keys stay until
  `removeExpiredKeys`). Consequence: a NON-restarted DN that re-registers with the restarted
  NN keeps the old incarnation's keys plus the new ones; a restarted DN has only the new ones.

Client DEK cache:
- `DFSClient.java:1855-1868` `newDataEncryptionKey`: refetch from the NN only when
  `encryptionKey == null || expiryDate < now`. The DEK lifetime is the block-token lifetime
  (`BlockTokenSecretManager.java:540-542`, `timer.now() + tokenLifetime`; default 600 min).
  An NN restart does not invalidate it on the client.
- `DFSClient.java:1836-1842` `clearDataEncryptionKey`.

The check:
- `BlockTokenSecretManager.java:553-565` `retrieveDataEncryptionKey`: `allKeys.get(keyId)` (557);
  `null` -> `throw new InvalidEncryptionKeyException(... keyID ... Current key ...)` (559-561).
  javac attributes the constructor call to line 561 (`currentKey.getKeyId()` is the last
  call in the multi-line expression), so the stack frame reads `BlockTokenSecretManager.java:561`.

Call chain to the check (DN side):
`DataXceiver.run` (`DataXceiver.java:236-238` `saslServer.receive`) ->
`SaslDataTransferServer.getEncryptedStreams` (170-...) -> `doSaslHandshake` (380-476) ->
SASL DIGEST-MD5 server callback -> `PasswordFunction.apply` (189) ->
`getEncryptionKeyFromUserName` (282-293) -> `BlockPoolTokenSecretManager.retrieveDataEncryptionKey`
(`BlockPoolTokenSecretManager.java:171-174`) -> `BlockTokenSecretManager.retrieveDataEncryptionKey`.
The keyId and nonce come from the client's DEK (SASL user name).

What happens after the throw:
- `SaslDataTransferServer.java:454-462`: SaslException caused by InvalidEncryptionKeyException ->
  `sendInvalidKeySaslErrorMessage` (status ERROR_UNKNOWN_KEY), rethrow.
- `DataXceiver.java:303-334`: logged with `LOG.error(s, t)` (333). (The analogous
  `InvalidToken` case is demoted to TRACE at 327-331, "this is not a server error".)
- Client: `DataTransferSaslUtil.java:219-220` turns ERROR_UNKNOWN_KEY into
  `InvalidEncryptionKeyException`; `SaslDataTransferClient.java:606-621` rethrows it.

Client consumers of the cached DEK and their handling (all in hadoop-hdfs-client):

| path | site | handling |
|---|---|---|
| stateful read | `DFSInputStream.java:663-669` (`blockSeekTo`) | clear DEK, retry once |
| positional read | `DFSInputStream.java:1263-1269` | clear DEK, retry once |
| striped read | `DFSStripedInputStream.java:264-270` | clear DEK, retry |
| write pipeline setup / append | `DataStreamer.java:1961-1971` (`createBlockOutputStream`) | clear DEK, retry once |
| pipeline recovery transfer | `DataStreamer.java:122-154, 1586-1603` | clear DEK, retry once |
| replicated checksum | `FileChecksumHelper.java:536-546` (`checksumBlock`) | clear DEK, retry the block once |
| striped checksum | `FileChecksumHelper.java:669-679` (`checksumBlockGroup`) | clear DEK, retry the block group once |

Safeguards noted (recorded, not judged): every client consumer above has a clear-and-refetch
retry. Noted while auditing the checksum retry: `FileChecksumHelper.checksumBlock`
(`FileChecksumHelper.java:506-554`) subtracts the block length from `remaining` (508-511)
BEFORE `tryDatanode`, and the retry (`blockIdx--`, 543-545) does not restore it. With
`getFileChecksum(Path)` the length is `Long.MAX_VALUE` (`DistributedFileSystem.java:1965-1966`),
so `remaining` stays huge. With a snapshot path, `remaining = min(length, fileLength)`
(`FileChecksumHelper.java:121-124`); with `getFileChecksum(Path, long)` (`DistributedFileSystem.java:1978-1986`)
`remaining = length`. Then the retry runs with `remaining < numBytes` and sets
`block.setNumBytes(remaining)` (508-509), e.g. 0 for a one-block file. The DN computes the
MD5 over `requestLength` (`BlockChecksumHelper.java:177-182, 316-355`), i.e. over zero CRCs.
`checksumBlockGroup` (637-687) has the same pattern (`requestedNumBytes`, 641-644).
Phase 2 must test whether this path returns a wrong checksum after the target fires.

Reachability: every CE step is a normal operation. A client reads (caches DEK), the NN
restarts, a DN restarts and re-registers, the client reads again from that DN. This is the
in-tree test `TestEncryptedTransfer#testLongLivedReadClientAfterRestart` (268-284) with one DN.

Trigger scenario: long-lived DFSClient (e.g. a service, NFS gateway, DistCp mapper JVM)
with encrypted data transfer -> NN restart -> one DN restart -> the client reads, writes,
appends or computes a checksum on a block whose replica is on the restarted DN.

## Step 2: developer knowledge (pinned tree only)

Adhoc Shared Rule 2: tracker/history search only after the reproduction verdict
(recorded below in "Novelty search"). Evidence from the source tree:

- `SaslDataTransferServer.java:458-461`: "This could just be because the client is long-lived
  and hasn't gotten a new encryption key from the NN in a while. Upon receiving this error,
  the client will get a new encryption key from the NN and retry connecting to this DN."
- `SaslDataTransferClient.java:615-616`: "`ioe` can be InvalidEncryptionKeyException or
  InvalidBlockTokenException that indicates refresh key or token and are important for caller."
- `BlockReaderFactory.java:840-856` `isSecurityException`: "They don't indicate a communication
  problem. Instead, they mean that there is some action the client needs to take, such as
  refetching block tokens, renewing encryption keys, etc."
- Client handlers log at INFO "Will fetch a new encryption key and retry"
  (`DFSInputStream.java:664-666`, `DataStreamer.java:1963-1965`).
- Tests: `TestEncryptedTransfer.java:268-284` testLongLivedReadClientAfterRestart ("Restart the
  NN and DN, after which the client's encryption key will no longer be valid"), asserts the
  read and `getFileChecksum` (whole file, after the read already refetched the DEK) succeed;
  `:286-306` testLongLivedWriteClientAfterRestart; `:337-386` testFileChecksumWithInvalidEncryptionKey
  (does not check the result of the first `getFileChecksum` after the key became invalid; it
  checks a second call, 379-385); `:390-456` striped checksum; `:460-521` pipeline recovery.
  No in-tree test computes a checksum on a snapshot path or with an explicit length while
  the DEK is stale.

## Step 3: known status

Source = MC (actual counterexample). No pre-filter applies; proceed to Phase 2.
Novelty decided after the verdict (adhoc Shared Rule 2); see below.

## Phase 2 outcome (recorded before any tracker/history search)

Reproduction `repro/test_bugMC-4_cached_dek_nn_dn_restart.sh` (Level 0; logs `repro/MC-4.log`,
`repro/MC-4.rerun.log`). Pristine tree (harness instrumentation reverted, backup in
`instrumentation-backup/`). Every stale-DEK client path made d1 throw
`InvalidEncryptionKeyException` at `BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:561)`
(statement 559-561), keyID = the client's cached incarnation-1 key. Every client cleared and
refetched its DEK. Results: stateful read, pread, whole-file checksum and append correct.
`getFileChecksum` on a snapshot path and `getFileChecksum(path, len)` returned a WRONG
checksum (`454b7d1c...` = MD5(MD5(empty) || 16 zero bytes)), i.e. the retry re-requested the
block with `numBytes = 0` (FileChecksumHelper.java:508-511). Controls: no restart -> 0 throws;
NN restart only -> 0 throws (d1 merged both key sets); fresh client / repeated call with the
refetched DEK -> correct checksums, 0 throws. Same outcome in a second run.
Real caller: DistCp `DistCpUtils.checksumsAreEqual` -> `sourceFS.getFileChecksum(source, sourceLen)`
(DistCpUtils.java:583), `CopyMapper.checkUpdate` (CopyMapper.java:351-352).

Verdict settled from this evidence: REPRODUCED.

## Novelty search (after the verdict; sets the Novelty field only)

Queries run on 2026-10-29:
- git (pinned tree): `git log -- .../FileChecksumHelper.java`; `git log -i --grep="InvalidEncryptionKey\|encryption key"`;
  `git show 3ba985997d1` (HDFS-12931), `e23df4c4b84` (HDFS-17897), `01a2e0f6bdc` (HDFS-16533).
- Apache JIRA REST `search` (jql, ORDER BY created DESC):
  `project = HDFS AND text ~ "getFileChecksum" AND text ~ "retry"`;
  `project = HDFS AND text ~ "InvalidEncryptionKeyException"`;
  `project = HDFS AND text ~ "FileChecksumHelper"`;
  `project = HDFS AND text ~ "checksum" AND text ~ "snapshot" AND text ~ "InvalidBlockToken"`;
  `project = HDFS AND text ~ "checksumBlock"`; `... "getFileChecksum" AND text ~ "wrong"`;
  `... "getFileChecksum" AND text ~ "snapshot"`; `... "lastRetriedIndex"`;
  `... "long-lived client" AND text ~ "encryption key"`; `... "testLongLivedReadClientAfterRestart"`;
  `project in (HDFS, HADOOP) AND text ~ "DistCp" AND text ~ "checksum mismatch" AND text ~ "encryption"`.
  Issue details read: HDFS-17967, HDFS-16136, HDFS-17992, HDFS-12931, HDFS-17899.
- GitHub search API (apache/hadoop PRs, sorted by created): `is:pr FileChecksumHelper`,
  `is:pr getFileChecksum retry`, `is:pr InvalidEncryptionKeyException`, `is:pr checksumBlock remaining`;
  PR #8364 body and comments read.

Results:
- HDFS-12931 (fixed 2018, in tree): added the InvalidEncryptionKeyException retry to
  `checksumBlock`, copying the InvalidBlockTokenException retry; reported the failure, not a
  wrong length.
- HDFS-17897 (fixed 2026-03-25, in tree): the same retry for striped checksums.
- HDFS-17899 (fixed 2026-05-14, after the base commit, not in tree): missing retries in Balancer
  Dispatcher, SPS BlockDispatcher, DataNode DataTransfer (other consumers).
- HDFS-17967 (fixed 2026-09-17, not in tree): DN writeBlock mirror, replaceBlock proxy,
  StripedBlockWriter (DN-originated DEK paths).
- HDFS-16136 (open): umbrella "Handle all occurrence of InvalidEncryptionKeyException" (missing retries).
- HDFS-17992 (open), HDFS-17803 (open), HDFS-16533, HDFS-7682: other checksum issues (empty
  blocks, empty files, composite CRC length, snapshot content), different mechanisms.
- No issue or PR reports that the checksum retry after InvalidEncryptionKeyException (or
  InvalidBlockTokenException) re-requests the block with a reduced length, or that a long-lived
  client's bounded-length/snapshot getFileChecksum returns a wrong checksum after an NN+DN restart.
  The in-tree restart behavior (testLongLivedReadClientAfterRestart, HDFS-3637 era) is designed
  behavior, not a filed bug.

Novelty: NEW.
