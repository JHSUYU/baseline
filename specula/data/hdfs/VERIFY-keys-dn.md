# Independent verification: hdfs-adhoc-11, -14, -20 (block keys / DataNode HA state)

Source: `/bulk/specula-adhoc/src/hadoop` at 734dd8a67cd (read-only). All file:line references are to that tree.
Abbreviations: BTSM = `hadoop-hdfs/.../security/token/block/BlockTokenSecretManager.java`,
DM = `.../blockmanagement/DatanodeManager.java`, HBM = `.../blockmanagement/HeartbeatManager.java`,
BM = `.../blockmanagement/BlockManager.java`, BPOS = `.../server/datanode/BPOfferService.java`,
FCH = `hadoop-hdfs-client/.../hdfs/FileChecksumHelper.java`, SDTC = `hadoop-hdfs-client/.../sasl/SaslDataTransferClient.java`.

Upstream check: `git log 734dd8a67cd..origin/trunk` (169 commits, to 2026-10-26) on every touched file. The only relevant changes are
HDFS-17899 (62729b06d70) and HDFS-17967 (5b7e28c1679). Both add a retry-once-on-InvalidEncryptionKeyException to DN-side
connection paths (Balancer, SPS, DataTransfer, writeBlock mirror, replaceBlock). Neither changes key delivery, the
`overwriteDownstreamDerivedQOP` re-sign (it still uses `getCurrentKey()`), FileChecksumHelper's `remaining`
bookkeeping, or BPOfferService. No commit touches BPOfferService/BPServiceActor or the heartbeat txid.

Candidates: every REPRODUCED MC-* finding with a TargetSafe* invariant, plus CR-3 of case 11 (its reproduction throws at
BTSM:559/561). Other CR-* findings were skipped: case 11 CR-4 throws NPE/IAE, not the target; case 20 CR-2 never reaches
BPOS:615. CR-2 is mentioned under case 20 because it shares the root cause.

Target-frame note (case 11): the throw statement spans BTSM:559-561. The JVM attributes the frame to :561, where the
constructor call sits. A frame at `retrieveDataEncryptionKey(BlockTokenSecretManager.java:561)` is the target throw.

---

## hdfs-adhoc-11: `BTSM.retrieveDataEncryptionKey` L559, `allKeys.get(keyId) == null`

Designed behaviour, for reference:
- A DN learns block keys only from registration (`DM.registerDatanode` L1209 `setExportedKeys`, applied at BPOS:436-441)
  and from `KeyUpdateCommand`.
- `KeyUpdateCommand` is added to a heartbeat reply only when `needKeyUpdate` is set (`BM.addKeyUpdateCommand` L1671-1677).
  That flag is set by the roll sweep (HBM:552-557) and on failover (DM:2092-2100).
- On every roll the DN already holds the NN's new current key, because the previous export carried it as `nextKey`
  (BTSM:268-279).
- The client refetches the DEK once on InvalidEncryptionKeyException (DFSInputStream:663-669, 1263-1269; FCH:536-546).
  `DFSClient.newDataEncryptionKey` (DFSClient:1855-1863) returns `namenode.getDataEncryptionKey()`, which is always the
  NN's current key (BTSM:532-542).
- So a transient stale-DEK rejection is by design. The failure is real only when the refetched DEK still names a key the
  DN lacks, or when the retry is mishandled.

### MC-1: safe mode suppresses the key push while keys keep rolling. **KEEP** (representative; MC-5 is a duplicate)

Code path:
1. Synced DN: it holds current K1 and next K2 from the last export.
2. NN enters manual or resource-low safe mode. Startup safe mode takes the same branch: `FSNamesystem.isInSafeMode` covers all.
3. `HBM.Monitor.run` (L538-560) has no safe-mode check. `BM.shouldUpdateBlockKey` (L808-810) calls `BTSM.updateKeys`
   (L260-281), which rolls K2 to current and makes K3 next. The sweep sets `needKeyUpdate=true` (L552-557).
4. Each DN heartbeat goes through `DM.handleHeartbeat`. In safe mode it returns `new DatanodeCommand[0]` at L1884-1886,
   before `blockManager.addKeyUpdateCommand` (L1971). The flag stays set, but no key leaves the NN.
   The comment at L1882-1883 is about "recovery / replication requests". The key push is collateral, not intent.
   It predates block tokens (HADOOP-3002).
5. The second roll makes K3 current. The DN has never seen K3.
6. `NameNodeRpcServer.getDataEncryptionKey` (L1940-1942) has only `checkNNStartup()`. It issues a DEK under K3
   (BTSM:537-540). Reads are allowed in safe mode.
7. On the DN, `SaslDataTransferServer.getEncryptionKeyFromUserName` calls BPTSM:173, then BTSM:557 finds `allKeys.get(K3)`
   null and throws at **L559**.
8. The client refetch gets another DEK naming K3 and fails the same way. The read ends in BlockMissingException on
   healthy data.

Reproduction (`repro/test_bugMC-1_safemode_keyroll_dek.sh`, log `.log`):
- Workload: the workload's own setup (TestEncryptedTransfer `[1]`), copied.
- Fault: one call to the public `DistributedFileSystem.setSafeMode(ENTER)`.
- Time compression: the public config `dfs.block.access.key.update.interval=1` (min) at Level 0. Level 1 uses the
  `setKeyUpdateIntervalForTesting` hook that TestEncryptedTransfer itself uses.
- No guard operand is written: no `clearAllKeysForTesting`, `addKeys` or reflection. State is only read.
- A negative control (same rolls, no safe mode) reads OK with 0 target frames.
- The log shows `retrieveDataEncryptionKey(BlockTokenSecretManager.java:561)` with keyID = the fresh DEK's key, and a
  fresh-client read failing with BlockMissingException after about 22 s. 3/3 tests passed.
- Realistic.

Bug, not design: DEKs are minted from a key the NN knows it has not delivered. The client's single refetch cannot help,
because it gets the same key. No comment, test or JIRA treats key delivery in safe mode as intended.

Severity:
- Every fresh-DEK encrypted read (and the encrypted read side of `getFileChecksum` and similar operations) fails at every
  DN, cluster-wide, from the second roll until the NN leaves safe mode.
- Retries do not recover it. It heals on exit, because `needKeyUpdate` is still set and the next heartbeat pushes the keys.
- Clients that cached a DEK earlier keep working until it expires (token lifetime, 600 min).
- Reachable with default config apart from enabling encryption. However, with the default 600-minute interval, failures
  start only 10-20 h into a single safe-mode period. Plausible cases are a long manual maintenance window, a
  resource-low safe mode left over a weekend, or a standby/observer (MC-5).
- Medium severity: lasting unavailability of reads, which is the one service safe mode is supposed to keep, but it needs
  a long safe-mode period.

Known? No match:
- HDFS-13441 and HDFS-13473 cover lost pushes and the pull design, without safe mode.
- HDFS-17372 and HDFS-17882 (open; its PR #8250 keeps `addKeyUpdateCommand` after the safe-mode return) are about priority.
- Trunk is unchanged.

Confidence: high on mechanism and reproduction; medium on practical severity.

### MC-5: observer/standby in safe mode issues DEKs from undelivered keys. **DROP**, duplicate of MC-1

The root cause is the same early return at DM:1884-1886. Each HA NN rolls its own key range. An observer can serve
`getDataEncryptionKey` (`@ReadOnly(isCoordinated=true)`). It needs the observer/standby to sit in safe mode across two of
its own rolls (10-20 h), usually by a manual `-safemode enter` against it. A fix to MC-1 fixes it. It is reported only as
a manifestation of MC-1.

### MC-4: cached DEK rejected after NN restart and DN restart, then the checksum retry returns a wrong checksum. **KEEP** (wrong result)

Code path:
1. A long-lived client caches DEK(K_old) (DFSClient:1858-1862, valid 600 min).
2. The non-HA NN restarts and draws a fresh random serial (BTSM:154, 157). The DN holding the replica restarts after it
   and learns only the new keys (registration, BPOS:436-441).
3. The client calls `getFileChecksum` on a `/.snapshot/` path, or `getFileChecksum(path, len)`.
   `FileChecksumComputer` sets `remaining = length` (FCH:119), or `min(length, fileLength)` for snapshot paths (FCH:121-124).
4. `checksumBlock` (FCH:506-511) clamps `block.numBytes` to `remaining` and subtracts it **before** contacting the DN.
5. `tryDatanode` gets the DN's ERROR_UNKNOWN_KEY. On the DN this is BTSM:557, then the throw at **L559**. The client sees
   it as InvalidEncryptionKeyException.
6. The handler at FCH:536-546 sets `blockIdx--` and clears the DEK, but does **not** restore `remaining`.
7. The retry re-enters `checksumBlock`. Now `remaining` (0 for the last block) is less than `numBytes`, so
   `block.setNumBytes(0)` runs (FCH:508-509). The DN checksums 0 bytes.
8. `getFileChecksum` silently returns MD5 over zero CRCs, with no exception.
- Whole-file `getFileChecksum(Path)` passes Long.MAX_VALUE and stays correct, which matches the log.
- The InvalidBlockToken retry branch (FCH:525-535) has the same bookkeeping flaw. `refetchBlocks` (FCH:165-170) does not
  reset `remaining` either.

Reproduction (`repro/test_bugMC-4_cached_dek_nn_dn_restart.sh`, `MC-4.log`):
- Faults: only `MiniDFSCluster.restartNameNode` and `restartDataNode`. No reflection and no key writes.
- The log shows `BlockTokenSecretManager.java:561` with keyID = the cached DEK.
- Snapshot-path result: expected `...bea308dd...`, got `...454b7d1c...`. Explicit-length results are wrong too.
  Whole-file is correct.
- A fresh client gets the right value.
- Realistic: a rolling restart of a non-HA cluster with long-lived clients, such as HBase or services.

Bug, not design: the target firing is the designed stale-DEK path. The real defect is that the designed retry in FCH
corrupts its own length bookkeeping. This is a client-side bug exposed by the target check.

Severity:
- A silently wrong `getFileChecksum` result, reached with default config apart from encryption.
- Snapshot-path checksums are what DistCp `-diff`/`-rdiff` and snapshot-based copy validation compute. A wrong checksum
  there produces spurious checksum mismatches (failed or re-copied copies). An application that stores or compares
  checksums sees a wrong value.
- No data is lost.
- Medium-high (wrong result). Narrower trigger: it needs a bounded length or a snapshot path, plus a DN restarted after
  the NN while the client's DEK is cached.

Known? No JIRA found. HDFS-12931 and HDFS-17897 added these retries; HDFS-15367 and HDFS-1041 are unrelated. Trunk has
the same code. Confidence: high.

### MC-2: lost heartbeat reply drops the key push until the next roll. **DROP**, known

`BM.addKeyUpdateCommand` clears `needKeyUpdate` when it builds the reply (L1674-1676), with no acknowledgement. This is
exactly HDFS-13441 (Patch Available, unfixed) and the motivation for HDFS-13473. The measured window is about 1-3 s
after the next roll and is mostly masked by retries. A 10 h window needs a second lost push. The reproduction is
honest: a Mockito DN-to-NN spy, plus a no-Mockito variant using an IPC timeout and a held NN lock. Known and low severity.

### MC-3: registration export (DM:1209) precedes the heartbeat-set join (DM:1300/1332). **DROP**, low severity

The race is real: the roll and sweep (HBM:550-557) do not take the BM lock that registration holds. But the consequence
follows from the code:
- The DN joins holding {K1, K2} while the NN holds current K2, so nothing fails at once.
- At the next roll (about 10 h later) the sweep marks the node and the next heartbeat (≤3 s) delivers K3.
- So the harm is one window of at most 3 s, once, after a rare race between a 10-hourly roll and a registration.
- Reads fall back to other replicas. A write fails only on a one-DN cluster.
- The reproduction holds topology resolution to open the window, which is acceptable timing control.
- Transient and rare, so low severity.

### MC-6: restarted NN issues DEKs before DNs re-register. **DROP**, low severity (transient, self-healing)

- After the NN restart, `getDataEncryptionKey` (L1940-1942) mints from the new random range immediately.
- The DN learns that range only via heartbeat, then REGISTER, then `reRegister` and `addKeys` (BPOS:680-689, 436-441).
- Reads through cached locations fail at L559 and are retried; the measured stall is 6-20 s.
- The window closes as soon as the DN re-registers.
- It is part of the documented push-model limitation (HDFS-13473) and occurs during an NN restart, which is already an
  outage for non-HA.
- The reproduction is honest (`restartNameNode` plus heartbeats paused for timing, with a natural-timing variant that
  reproduced 5/5).
- Low severity.

### MC-7: DN-to-DN transfer from a not-yet-re-registered DN to a DN restarted after the NN. **DROP**, known / low severity

- The DN-side DEK comes from the sender's own `currentKey` (`DataNode.getDataEncryptionKeyFactoryForBlock`).
- The window lasts until the sender re-registers.
- It needs an NN restart, then a DN restart, then a sender heartbeat held back (the reproduction uses
  `setHeartbeatsDisabledForTests` and `failMirrorConnection`).
- The client excludes a healthy DN, so it is transient.
- It belongs to the HDFS-16136 (open) family. The trunk retry in HDFS-17967 does not help, but the condition self-heals
  within a heartbeat or two.
- Low severity.

### CR-3: a dead CommandProcessingThread never applies a delivered KeyUpdateCommand. **DROP**, known / not reachable with defaults

- It needs the DN command thread to die (HDFS-15651, open) plus an HA sibling actor.
- It also needs `dfs.block.access.key.update.interval` shorter than the NN heartbeat expiry (630 s). With the 600-minute
  default, the NN declares the DN dead before the second roll, which the finding itself acknowledges.
- Known root cause and non-default timing.

---

## hdfs-adhoc-14: `BTSM.checkAccess` L418, token password mismatch

All four findings (MC-1 to MC-4) are one defect. Representative: **MC-1**.

### MC-1: mirror DN re-signs the forwarded token with its own currentKey but keeps the token's keyId. **KEEP** (non-default config)

Code path:
1. With `dfs.encrypt.data.overwrite.downstream.derived.qop=true` (hdfs-default.xml:6436-6437, default **false**),
   `DataXceiver.writeBlock` takes `datanode.blockPoolTokenSecretManager.get(bpid).getCurrentKey().getKey()`
   (DataXceiver:823-829) and passes it to `saslClient.socketSend(..., secretKey)` (L830-832).
2. `SDTC.getSaslStreams` (L425-439) calls `updateToken` (L450-460). That function sets the handshake message, re-serializes
   the identifier with its **original keyId**, and sets `password = HMAC(identifier, DN currentKey)`.
3. The next DN's `writeBlock` calls `checkAccess` (DataXceiver:731), then L1454 `blockPoolTokenSecretManager.checkAccess`,
   then BTSM:404-421. `retrievePassword(id)` computes HMAC with `allKeys.get(id.keyId)` (BTSM:~512-522).
   This differs from the token password whenever the mirror's currentKey is not the key named by keyId, so it throws at
   **L418**.
4. When does the mirror's currentKey differ from the token's keyId? It is equal in steady state, and differs in these
   windows:
   - after each NN key roll, until that DN processes its push (≤ one heartbeat, 3 s);
   - after an HA failover, until the new active's push arrives, because the DN's currentKey comes only from the actor it
     treats as active (BPOS:436-440). This is MC-3;
   - for a DN-signed replication token, when source and target are skewed (MC-2);
   - after an NN restart (MC-4).
5. The second DN replies ERROR_ACCESS_TOKEN with firstBadLink = itself (DataXceiver:1456-1467). The client abandons the
   block and excludes a healthy DN. Retries inside the same window fail the same way, ending in
   "Unable to create new block."

Reproduction (`repro/test_bugMC-1_rotation_skew.java`; evidence in `confirmation/MC-1/run*-*.txt`):
- Config only: the flag on and `dfs.block.access.key.update.interval=1` (min), with ordinary writes through the
  FileSystem API. No fault injection and no state writes.
- Flag off (control): 27,359 writes, 0 target hits.
- Flag on, 6 DNs: 2,018 InvalidToken events with top frame `BlockTokenSecretManager.checkAccess(BlockTokenSecretManager.java:418)`
  and 502 application write failures. With 3 DNs: one-replica blocks.
- MC-3 (failover) reproduced unassisted 5/5. MC-4 needed a `DataNodeFaultInjector` stall, so it is the weakest variant.
- Realistic.

Bug, not design: the re-signed token cannot pass verification at the next hop unless keyId happens to name the mirror's
current key. The fix is to sign with `allKeys.get(id.getKeyId())`. Nothing documents the failure; the feature
(HDFS-13699 era) assumes the keys are equal.

Severity:
- Deterministic, with no fault needed.
- At every key roll (every 10 h) and every failover, writes started in the roughly 1-3 s window are rejected at the
  second DN. Healthy DNs are excluded, blocks close under-replicated, and on a busy cluster some application writes fail.
- It self-heals within one heartbeat. No data is lost or corrupted.
- Medium. Reach is **strongly limited** by the non-default flag, which only deployments using different inter-DN QOP
  (auxiliary-port / multi-QOP setups) enable.

Known? No: web and JIRA searches found nothing; HDFS-14509 is a different mismatch cause. Trunk still passes
`getCurrentKey()` (HDFS-17967 only wrapped the call in a retry loop, and that retry catches only
InvalidEncryptionKeyException, not the ERROR_ACCESS_TOKEN that results here).

Confidence: high on mechanism; medium on impact, because of the narrow config.

### MC-2, MC-3, MC-4. **DROP**, duplicates of 14/MC-1

They are the same `updateToken` re-sign with the same fix. MC-2 is a DN-signed replication token; harm: the block stays
one replica short until the pending-reconstruction timeout. MC-3 is the window after an HA failover. MC-4 is a
pre-NN-restart token and needed an injected stall.

---

## hdfs-adhoc-20: `BPOS.updateActorStatesFromHeartbeat` L615, `assert txid >= lastActiveClaimTxId`

Shared root cause, confirmed in code:
- The heartbeat's HA status carries `FSImage.getCorrectLastAppliedOrWrittenTxId()` (FSNamesystem:4505-4507 and
  FSImage:1564-1566), which is `max(lastApplied, FSEditLog.txid)`.
- `FSEditLog.txid` is incremented in `beginTransaction` (FSEditLog:541). For async logging this happens at enqueue
  (FSEditLogAsync:128-136), before the edit is durable. Sync logging has the same gap between `logEdit` and `logSync`.
- A crash loses advertised txids. The restarted or re-activated NN starts at durable end + 1, below the DN's
  `lastActiveClaimTxId`, which only a DN restart resets (BPOS:103, 616).

### MC-1: non-HA NN crash and restart. **DROP**, low severity in production (assert-only)

Code path:
1. The DN records L from a heartbeat (BPOS:614-616).
2. The NN dies before flushing. The reproduction uses `NameNodeAdapter.abortEditLogs` plus shutdown and restart, a
   standard crash emulation; it also fired under natural load with random crash timing.
3. The restarted NN reports ACTIVE with r+1 < L.
4. `bposThinksActive` is still true, because the actor was never shut down. Neither branch at L588-612 runs, and
   L614-615 trips the assert.
The reproduction writes no guard operands (a Mockito spy only delays flush) and shows the frame at BPOS:615. The guard is
genuinely reachable.

Consequences:
- With `-ea`, as in surefire tests: the AssertionError kills the actor (BPServiceActor catches Throwable), and the DN
  never re-registers.
- With `-da`, the production default: L615 is a no-op and L616 lowers `lastActiveClaimTxId` to r+1, which is the correct
  recovery. **No production consequence.** The target check never fails in production.
So the defect at this line is only an over-strong assertion in test JVMs.

### MC-2: re-activated HA NN with a lower txid. **DROP**, duplicate of 20/MC-1 (same assert-only consequence)

This is the same path, with the actor still `bpServiceToActive` because no relinquish heartbeat ran (that needs a
heartbeat-free window while the NN is down or standby). With `-da` the claim is lowered and things continue normally. The
reproduction uses a Mockito delay on `logSync` (timing only) plus heartbeats paused for timing.

Related production bug, not a candidate (case 20 CR-2): when the next active is a different actor, or the same NN after a
relinquish, the claim takes the split-brain branch (BPOS:588-598) instead of reaching L615.
- The DN routes the legitimate active's commands to `processCommandFromStandby` (BPOS:825-848), which drops DNA_TRANSFER,
  INVALIDATE, RECOVERBLOCK and others until the new active's txid exceeds L. The reproduction measured 39 s of ignored
  re-replication.
- That is the real production consequence of the shared root cause. It is transient: it clears once the new active writes
  past L, though slowly on an idle cluster.
- It does **not** make the target check fail, so it is listed here only for routing.

### MC-3: handshake installs a deposed ACTIVE NN without a txid check. **DROP**, not realistically reachable / contrived

- The code gap is real: `verifyAndSetNamespaceInfo` (BPOS:384-390) installs `bpServiceToActive` from a versionRequest
  reporting ACTIVE, with no comparison against `lastActiveClaimTxId`.
- Reaching it needs all of the following at once:
  - a deposed NN that still believes it is ACTIVE (a split brain that QJM and ZKFC fencing are designed to end, emulated
    with the TestDNFencing pattern `abortEditLogs` + `enterSafeMode` + `transitionToActive`);
  - a DN starting during that split brain;
  - `bpServiceToActive` cleared after the newer claim, because the new active's actor exits on
    DisallowedDatanodeException or because the new active goes standby;
  - the deposed NN's versionRequest answered late, which the reproduction forces by holding nn0's FS write lock.
- With `-ea` it trips the assert. The `-da` consequence (the DN obeys a deposed NN) is argued, not executed.
- Multi-fault and contrived, with production harm undemonstrated. Worth a hardening patch, not a severe bug report.

---

## Summary

| case/ID | verdict | reason |
|---|---|---|
| 11/MC-1 | **KEEP** | Safe mode returns before `addKeyUpdateCommand` while keys keep rolling; fresh DEKs fail at every DN until safe mode ends (retry cannot help) |
| 11/MC-5 | DROP | duplicate of 11/MC-1 (observer/standby in safe mode) |
| 11/MC-4 | **KEEP** | Designed stale-DEK retry in FileChecksumHelper does not restore `remaining`, so a silently wrong checksum for snapshot/explicit-length requests |
| 11/MC-2 | DROP | known (HDFS-13441); short window |
| 11/MC-3 | DROP | low severity (rare race, ≤3 s window once) |
| 11/MC-6 | DROP | low severity (transient until DN re-registers; HDFS-13473 class) |
| 11/MC-7 | DROP | known (HDFS-16136 family) / transient |
| 11/CR-3 | DROP | known (HDFS-15651) and needs non-default key interval < heartbeat expiry |
| 14/MC-1 | **KEEP** | Re-sign with mirror's currentKey but original keyId; writes rejected at 2nd DN at every roll/failover (non-default flag) |
| 14/MC-2,3,4 | DROP | duplicates of 14/MC-1 |
| 20/MC-1 | DROP | reachable, but assert-only: with -da the claim is just lowered, no production effect |
| 20/MC-2 | DROP | duplicate of 20/MC-1 (assert-only); production harm is CR-2, which bypasses L615 |
| 20/MC-3 | DROP | contrived multi-fault split brain plus a forced late handshake; -da harm only argued |
