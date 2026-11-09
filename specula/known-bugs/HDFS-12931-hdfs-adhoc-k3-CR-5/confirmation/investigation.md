# CR-5 investigation (Phase 1 — evidence only)

Finding: FileChecksumHelper never clears a stale DEK on InvalidEncryptionKeyException.
Source: Code Review (no model-checking counterexample; finding text says "never model-checked").
Tree: worktree at e19e80cc0dd (pinned base_commit; `git log` has a single squashed "base" commit, so blame/commit history is not available).

## Step 1: Code audit

Cited sites (all verified in the pinned tree):

- `hadoop-hdfs-client/.../FileChecksumHelper.java:321-341` (`ReplicatedFileChecksumComputer.checksumBlock`):
  per-DN loop; `catch (InvalidBlockTokenException)` → refetch block tokens once;
  `catch (IOException ie)` → `LOG.warn` and try the next DN. `InvalidEncryptionKeyException extends IOException`
  (`InvalidEncryptionKeyException.java:30`) and is NOT an `InvalidBlockTokenException`, so it lands in the generic
  branch. Nothing in the file references the DEK (`grep clearDataEncryptionKey|EncryptionKey FileChecksumHelper.java` → no hits).
  If all DNs fail, `checksumBlocks()` throws `IOException("Fail to get block MD5 for " + locatedBlock)` (line 297).
- `FileChecksumHelper.java:478-497` (`StripedFileNonStripedChecksumComputer.checksumBlockGroup`): same pattern.
- Contrast, every other data-transfer client path clears the cache and retries:
  `DFSInputStream.java:584-590` and `:1091-1097` (read / pread), `DFSStripedInputStream.java:260-265`,
  `DataStreamer.java:139` (write pipeline), `DataStreamer.java:1791-1798` (transfer).
- DEK cache: `DFSClient.java:229` `private DataEncryptionKey encryptionKey;`
  `DFSClient.newDataEncryptionKey()` (`DFSClient.java:1759-1771`) returns the cached key unless `null` or
  `expiryDate < now`; `clearDataEncryptionKey()` (`:1741`) is the only other reset.
  The expiry is `timer.now() + tokenLifetime` (`BlockTokenSecretManager.java:472`; default token lifetime 600 min).
- Server side: `BlockTokenSecretManager.retrieveDataEncryptionKey` throws `InvalidEncryptionKeyException` at
  `BlockTokenSecretManager.java:490` when `allKeys.get(keyId) == null`; `SaslDataTransferServer.java:414-426` sends an
  invalid-key SASL error to the client, which the client turns back into `InvalidEncryptionKeyException`
  (`DataTransferSaslUtil.java:217/238/419`).

Call chain: `DistributedFileSystem.getFileChecksum(Path)` (`DistributedFileSystem.java:1676-1683`) →
`DFSClient.getFileChecksum` (`DFSClient.java:1790-1811`) → `FileChecksumComputer.compute()` →
`checksumBlocks()` → `checksumBlock()` → `tryDatanode()` → `DFSClient.connectToDN` (`DFSClient.java:1830`) →
`SaslDataTransferClient` → `DFSClient.newDataEncryptionKey()` (cached DEK). Public API, normal usage.

How the target fires naturally: the DEK's `keyId` names an NN block key. After an NN restart the NN generates fresh
block keys (new random serial range); a restarted DN registers and receives only the new keys (`addKeys`,
`BlockTokenSecretManager.java:204-216`), so a long-lived client's cached DEK names a key absent from every DN's
`allKeys` → line 490 fires on every DN. The codebase's own test `TestEncryptedTransfer#testLongLivedReadClientAfterRestart`
(`TestEncryptedTransfer.java:260-274`) builds exactly this state with `restartNameNode()` + `restartDataNode(0)`.

Trigger scenario: (1) encrypted cluster, client does a data op (caches DEK); (2) NN restart + DN restart(s);
(3) client calls `getFileChecksum` *before* any read/write. Prediction: every DN rejects the stale DEK, nothing clears it,
`getFileChecksum` fails, and keeps failing until the DEK expires (~tokenLifetime) or some other op clears it.

Safeguards / masks recorded (to be tested in Phase 2):
- Any read through `DFSInputStream` or a write through `DataStreamer` clears the DEK as a side effect. The existing
  test `testLongLivedReadClientAfterRestart` calls `readFile` BEFORE `getFileChecksum` after restart (line 272-273), which
  is why it passes — the read masks the checksum path. No checksum-first variant exists in the test file.
- DEK expiry (`expiryDate < now`) eventually refreshes the key — up to `tokenLifetime` (10 h default) later.
- No retry in `DistributedFileSystem.getFileChecksum` / `DFSClient.getFileChecksum`.

## Step 2: Developer knowledge

- Comments: `SaslDataTransferServer.java:418-421`: "This could just be because the client is long-lived and hasn't gotten
  a new encryption key from the NN in a while. Upon receiving this error, the client will get a new encryption key from
  the NN and retry connecting to this DN." — states the intended client contract (clear + refetch + retry), which
  FileChecksumHelper does not implement.
- Tests: `TestEncryptedTransfer#testLongLivedReadClientAfterRestart` and `#testLongLivedClient` assert
  `getFileChecksum` equals the original after restart / key expiry — i.e. developers expect a long-lived client's
  getFileChecksum to succeed in this situation — but in both tests a `readFile` precedes the checksum call.
- Commit/blame: unavailable (single squashed base commit).
- Tracker search: deferred until after the reproduction verdict (adhoc Shared Rule 2) — see "Novelty search" below.

## Step 3: Known-status pre-filter

Per adhoc Shared Rule 2, tracker/history search is done only after the reproduction verdict is settled; the
pre-filter is therefore applied after Phase 2 (a DROPPED outcome would still be possible then). See below.

## Phase 2 result (recorded before the novelty search)

- Test: `repro/test_bugCR-5_checksum_stale_dek.sh` (Level 0). It is a variant of
  `TestEncryptedTransfer#testLongLivedReadClientAfterRestart` with 3 DNs and getFileChecksum called before readFile.
- Run 1 (`repro-run1.log`) and run 2 (`repro-run2.log`) gave the same result: getFileChecksum failed 3/3 with
  "Fail to get block MD5", and the cached DEK keyId was unchanged after each failure. A fresh client succeeded. On the
  long-lived client a readFile cleared the DEK (its keyId changed to the NN's current key), after which getFileChecksum
  succeeded with a checksum equal to the baseline.
- Target frame: `BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:492)`. This is the
  `throw` statement spanning lines 490-492; javac attributes the frame to its last line. There were 10 hits: 9 from the
  checksum attempts (3 attempts × 3 DNs) and 1 from the read's first try.
- Verdict settled: REPRODUCED.

## Novelty search (after the verdict; adhoc Shared Rule 2: it sets the Novelty field only)

Queries:
1. WebSearch: `HDFS getFileChecksum InvalidEncryptionKeyException clearDataEncryptionKey FileChecksumHelper`
2. WebSearch: `HDFS JIRA "getFileChecksum" encryption key invalid after restart long-lived client "Fail to get block MD5"`
3. Fetched https://issues.apache.org/jira/browse/HDFS-12931 and https://github.com/apache/hadoop/pull/8364
4. `specula findings lookup --query FileChecksumHelper --query clearDataEncryptionKey --query getFileChecksum` returned `[]`.

Findings:
- HDFS-12931 "Handle InvalidEncryptionKeyException during DistributedFileSystem#getFileChecksum". Resolved/Fixed,
  Fix Version 3.1.0, resolved 2018-01-03. This is the replicated path, `ReplicatedFileChecksumComputer.checksumBlock`
  (FileChecksumHelper.java:337). The pinned tree is 3.1.0-SNAPSHOT and does not contain the fix.
- HDFS-17897 / apache/hadoop PR #8364 "Handle InvalidEncryptionKeyException during striped file checksum". Merged to
  trunk 2026-03-25 (e23df4c4b84f). This is the striped path, `checksumBlockGroup` (FileChecksumHelper.java:494). Quote:
  "The stale DEK is never cleared, so every DataNode in the block group fails with the same error."
- Both match the same mechanism at the same sites, so Novelty is KNOWN with fix-status fixed. The generic code-review ×
  known pre-filter would have produced DROPPED. Under adhoc Shared Rule 2, the tracker search runs only after the
  verdict and must not change it, so the verdict stays REPRODUCED.
