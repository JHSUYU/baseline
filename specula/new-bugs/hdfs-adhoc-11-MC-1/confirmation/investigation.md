# MC-1 investigation (Phase 1: evidence only)

Finding: "Safe mode suppresses key pushes while keys roll and DEKs are issued"
Source: model checking, Scenario 1, invariant `TargetSafe`, counterexample
`spec/output/hunt/gated/G_S1_synced.out` (config `G_S1_synced.cfg`, a pruning-only
variant of `MC_hunt_S1_safemode.cfg`).

Target (`/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-11/target.yaml`):
`BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])`,
`BlockTokenSecretManager.java:559`, throws `InvalidEncryptionKeyException` when
`key == null` (`key = allKeys.get(keyId)`). Workload:
`TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]` (resolver = null).

Source: worktree at base_commit 734dd8a67cd. All line numbers below are from the
pristine tree (`git show HEAD:<path>`). The worktree arrived with the harness trace
instrumentation applied (9 modified files, 8 untracked Specula* files, one of which
routed `BlockPoolTokenSecretManager.retrieveDataEncryptionKey` through
`SpeculaKeys.lookup`). It was backed up to `instrumentation-backup/` and removed so
the reproduction runs unmodified code; `git diff --quiet HEAD` is clean.

## Step 1: code audit

### Counterexample (11 states)
1. Init: n1 active in startup safe mode, d1 connecting.
2. `MCMonitorFirstPass(n1)`: Monitor's first pass.
3. `MCNNRegisterDatanode(n1,d1)`: registration reply carries keys (top = 2).
4. `MCDNRegistrationSucceeded`: d1 holds keys {1, 2}, current 1.
5. `MCDNBlockReport`: startup safe mode ends (`nnSafe = "off"`). DN synced.
6. `MCEnterSafeMode(n1)`: manual safe mode (`faults.safe = 1`).
7. `MCRollKeys(n1)`: rolls = 1, NN keys {1..3}, current 2.
8. `MCSweepNeedKeyUpdate(n1)`: needKU[n1][d1] = TRUE.
9. `MCRollKeys(n1)`: rolls = 2, NN keys {1..4}, current 3.
10. `MCClientGetDek(n1)`: client DEK names key 3.
11. `MCClientConnect(d1)`: d1 holds {1, 2}; lookup of 3 fails -> `targetFired`.
Faults used: one safe-mode entry on the active NN; two time-driven rolls. Nothing else
(no loss, restarts, failover).

### Cited code (pristine)
- `DatanodeManager.handleHeartbeat`, `DatanodeManager.java:1879-1886`: after
  `heartbeatManager.updateHeartbeat(...)` (the heartbeat is accounted),
  `if (namesystem.isInSafeMode()) { return new DatanodeCommand[0]; }`, with comment
  "If we are in safemode, do not send back any recovery / replication requests.
  Don't even drain the existing queue of work."
- The key push comes later, at `DatanodeManager.java:1970-1971`
  (`// key update command` / `blockManager.addKeyUpdateCommand(cmds, nodeinfo);`).
  `BlockManager.addKeyUpdateCommand`, `BlockManager.java:1671-1677`, adds
  `new KeyUpdateCommand(blockTokenSecretManager.exportKeys())` only when
  `nodeinfo.needKeyUpdate()` and then clears the flag. In safe mode it is never reached,
  so the flag stays set but nothing is delivered.
- `FSNamesystem.isInSafeMode`, `FSNamesystem.java:5270-5272`: manual OR resource-low OR
  block (startup) safe mode. Manual entry: `enterSafeMode(false)` via
  `ClientProtocol.setSafeMode` (`hdfs dfsadmin -safemode enter`,
  `DistributedFileSystem.setSafeMode`, `DistributedFileSystem.java:1650`). Resource-low
  entry: `NameNodeResourceMonitor`, `FSNamesystem.java:4597-4604`.
- `HeartbeatManager.Monitor.run`, `HeartbeatManager.java:543-573`: every 5 s
  (`:564`), `if (blockManager.shouldUpdateBlockKey(now - lastBlockKeyUpdate))` (`:552`)
  sets `d.setNeedKeyUpdate(true)` for every DN (`:553-557`). There is no safe-mode check.
- `BlockManager.shouldUpdateBlockKey`, `BlockManager.java:808-810` ->
  `BlockTokenSecretManager.updateKeys(long)`, `BlockTokenSecretManager.java:250-255`
  (roll when `updateTime > keyUpdateInterval`) -> `updateKeys()`, `:260-281`: the old
  current key is retired, `currentKey = nextKey` (`:272-274`), and a new `nextKey` with a
  new serial is generated (`:276-279`). After roll 1, current = the old next key (which
  the DN already has). After roll 2, current = the key created by roll 1, which only a
  push after roll 1 could have delivered.
- `BlockTokenSecretManager.exportKeys`, `:201-208`: exports current + all keys
  (registration and KeyUpdateCommand payload).
- `NameNodeRpcServer.getDataEncryptionKey`, `NameNodeRpcServer.java:1939-1943`: only
  `checkNNStartup()` (`:2371-2376`, throws only if the NN is not started), then
  `BlockManager.generateDataEncryptionKey` (`BlockManager.java:1680-1686`) ->
  `BlockTokenSecretManager.generateDataEncryptionKey`, `:532-543`: uses `currentKey`
  (`:536-538`). There is no safe-mode check and no check that DNs hold that key.
- DN key installation: registration (`DatanodeManager.java:1209`
  `nodeReg.setExportedKeys(blockManager.getBlockKeys())` ->
  `BPOfferService.registrationSucceeded`, `BPOfferService.java:436-440` `addKeys`) and
  `DNA_ACCESSKEYUPDATE` (`BPOfferService.java:788-793` `addKeys(..., true)`). No other
  path installs block keys on a DN.
- Target: `BlockTokenSecretManager.retrieveDataEncryptionKey`, `:553-565`; the throw is at
  `:559`.

### Call chain to the target (consumer side)
Client read -> `DFSInputStream.blockSeekTo` (`DFSInputStream.java:609-684`) ->
`getBlockReader` -> SASL client -> `DFSClient.newDataEncryptionKey`
(`DFSClient.java:1855-1868`, cached per DFSClient until expiry; a fresh client calls
`namenode.getDataEncryptionKey()`) -> DN `DataXceiver.run` (`DataXceiver.java:236`) ->
`SaslDataTransferServer.receive` (`:117-124`) -> `getEncryptedStreams` (`:170-194`) ->
SASL callback -> `getEncryptionKeyFromUserName` (`:282-294`) ->
`BlockPoolTokenSecretManager.retrieveDataEncryptionKey` ->
`BlockTokenSecretManager.retrieveDataEncryptionKey` -> throw at `:559`.
DN side: `doSaslHandshake` catches it (`SaslDataTransferServer.java:454-462`), sends
`ERROR_UNKNOWN_KEY`, and `DataXceiver.run` logs it with the stack trace
(`DataXceiver.java:303-333`, `LOG.error(s, t)`).
Client side: `DFSInputStream.java:663-669`: on `InvalidEncryptionKeyException` with
`refetchEncryptionKey > 0` (initialized to 1 at `:625`), clear the DEK and retry once.
Afterwards the DN goes to the dead-node list (`:673-680`), and the read ends in
`BlockMissingException` once every replica has failed.

### Reachability
Every step uses normal operations: a running encrypted cluster, manual (admin) or
resource-low safe mode on the active NN, the Monitor's periodic roll (default interval 600
minutes, `hdfs-default.xml:643-647`), and a client read. No fault outside normal
operation is needed. Timing condition: safe mode must span two roll events. With default
settings that means it lasts somewhere between 1 and 2 key intervals (10-20 h) or longer,
depending on phase.

### Safeguards encountered (recorded; Phase 2 tests whether they fire)
- Client DEK refetch (`DFSInputStream.java:663-669`, once per `blockSeekTo`). The refetch
  goes to the same NN, which returns a DEK under the same (or a newer) current key.
- Long-lived clients keep a cached DEK until expiry (`DFSClient.java:1858-1861`). This
  helps only clients whose DEK predates the second roll.
- Exiting safe mode makes the next heartbeat deliver the push, because `needKeyUpdate`
  stays set (`BlockManager.java:1674-1676`). That limits the harm to the safe-mode
  window, but it does not undo reads that already failed.
- `checkNNStartup()` on the DEK RPC only guards NN startup.

## Step 2: developer knowledge (pinned tree only; tracker/history deferred, see below)
- `BlockTokenSecretManager.java:178-189` (generateKeys comment): "...Since we require
  keyUpdInterval to be long enough so that all live DN's and Balancer will sync their
  keys with NN at least once during the period, the estimated expiry date for currentKey
  is set to now() + 2 * keyUpdateInterval + tokenLifetime." The design assumes every live
  DN syncs with the NN at least once per key interval. Safe mode stops that sync while
  the roll continues.
- `SaslDataTransferServer.java:458-461`: "This could just be because the client is
  long-lived and hasn't gotten a new encryption key from the NN in a while. Upon
  receiving this error, the client will get a new encryption key from the NN and retry
  connecting to this DN." The designed recovery assumes the NN's current key is known to
  the DN, so only a stale client key can trigger this error. In MC-1 the NN's newest key
  is the one the DN lacks, so the refetch cannot help.
- `DatanodeManager.java:1882-1883`: the safe-mode early return is commented as
  suppressing "recovery / replication requests" and "the existing queue of work". Key
  updates are not mentioned.
- `FSNamesystem.java:5286-5288` (enterSafeMode): "Stop the secret manager, since rolling
  the master key would try to write to the edit log". The delegation-token secret
  manager's roll is stopped in safe mode (for edit-log reasons). The block-key roll in
  `HeartbeatManager.Monitor` is not.
- Tests: only `TestEncryptedTransfer` and `ha/TestFailoverWithBlockTokensEnabled` use
  key-update hooks (`setKeyUpdateIntervalForTesting`, KeyUpdateCommand). Neither
  combines safe mode with key rolls (grep of `src/test/java` for safe mode within these
  files returned nothing). No test asserts the current behavior for this scenario.
- Issue tracker / git history: per adhoc-coordination Shared Rule 2 (Phase 4), searched
  only after the reproduction verdict was settled. Queries and results are recorded in
  "Known-status" below.

## Step 3: known-status / pre-filter
This finding is MC-sourced with an actual counterexample, so the code-review x known drop
does not apply. It goes to Phase 2. The novelty search (after the verdict) is recorded
below.

## Phase 2 summary (verdict settled before the novelty search)
Driver: `repro/test_bugMC-1_safemode_keyroll_dek.sh` (writes and runs
`org.apache.hadoop.hdfs.SpeculaAdhocMC1SafeModeKeyRollTest`, a variant of the workload).
- Run 1 (`run1/`): the behavior reproduced at L0 and L1, but 2 of 3 tests failed. The
  only failing assertion was mine: it expected the literal frame `:559`, while the
  JVM reports `BlockTokenSecretManager.java:561`. javap of the pristine class shows
  `ifnonnull` (the `key == null` guard) at line 558, `new InvalidEncryptionKeyException`
  at line 559, and `<init>` + `athrow` at line 561. All three belong to the single throw
  statement at 559-561, the only one in the method. Its message ("Can't re-compute
  encryption key") appears nowhere else in main sources.
  Run 1 also showed that a "fresh client" can reuse a pooled encrypted connection (DEK
  null after a successful read), so run 2 waits 5 s before each read (socket cache 3 s,
  DN keepalive 4 s) and requires a non-null DEK on successful reads.
- Run 2: all 3 tests pass (control, L1, L0). The target fired at L0 with public
  config + public admin API only, and the consumer read failed with
  BlockMissingException. It persisted across heartbeats and a later client in safe
  mode, and recovered only after leaving safe mode.
- Verdict: REPRODUCED (settled before the search below; the search sets only Novelty).

## Known-status search (Phase 4, after the verdict; queries recorded per Shared Rule 2)
Local history (pinned tree, base 734dd8a67cd, 2026-05-13). Message-only queries; the
repo is a blobless partial clone. A first `git log -S addKeyUpdateCommand` attempt
lazily fetched blobs and triggered `git gc --auto` in the shared repo. It was stopped and
not used.
- `git log -i -E --grep="safe ?mode" --grep="key" --all-match`: no results.
- `git log -i -E --grep="KeyUpdateCommand|block key update|access key update|needKeyUpdate|update block keys|block keys"`:
  HDFS-17372 (KeyUpdateCommand processed at high priority on the DN, merged 2026-02-13)
  and HDFS-16264 (block keys per block pool). Neither involves safe mode.
- `git log -i -E --grep="InvalidEncryptionKey|DataEncryptionKey|encryption key"`:
  HDFS-17897, HDFS-12931, HDFS-11741, HDFS-10609, HDFS-5766. All are client-side
  handling of a stale or expired DEK. None is about the NN's current key missing on
  the DN.
Apache JIRA (REST search):
- `project=HDFS AND text~"KeyUpdateCommand"`: HDFS-17372 (Fixed), HDFS-17882 (Open,
  NN-side priority, no description), HDFS-13473 (Patch Available since 2018: DN pull or
  versioned key sync because pushes can be missed; no mention of safe mode), plus
  unrelated issues.
- `project=HDFS AND (text~"safemode key update" OR "safe mode block key" OR "safemode block keys" OR "safemode encryption key")`:
  25 results, none about key pushes in safe mode (closest: HDFS-2577, the secret
  manager at NN startup).
- `project=HDFS AND summary~safemode/"safe mode" AND text~(block key|blockkey|access key|block token|encryption key|KeyUpdate)`:
  5 results, none matching.
- HDFS-13441 (Patch Available): the DN misses a key update because a heartbeat response
  to the standby was dropped. Different trigger (lost response), no safe mode.
- HDFS-16136 (Open): handle InvalidEncryptionKeyException in all client paths. No root
  cause, no safe mode.
- HADOOP-3002 (Fixed 2008): origin of the safe-mode early return ("HDFS should not remove
  blocks while in safemode"). It predates block access tokens and does not mention keys.
GitHub apache/hadoop PRs (API search, sorted by update, includes merged and closed):
- `is:pr KeyUpdateCommand`: #6530 (HDFS-17372, merged 2026-02-13) and #8250 (HDFS-17372
  NN side, open, 2026-02-13). The #8250 diff keeps `addKeyUpdateCommand` after the
  safe-mode return and only marks responses high priority for the DN queue.
- `is:pr safemode key`: 11 results, none about key updates.
Upstream trunk (raw GitHub, read only, no checkout): `handleHeartbeat` still returns
`new DatanodeCommand[0]` under `isInSafeMode()` before
`blockManager.addKeyUpdateCommand(cmds, nodeinfo)`. The defect is unfixed upstream.
Web search: no report connecting safe mode, a missed KeyUpdateCommand, and
InvalidEncryptionKeyException.
Novelty: NEW. No issue or PR reports this mechanism at this site. The related
reports above concern different triggers (lost response, DN queue priority, client-side
stale DEK).
