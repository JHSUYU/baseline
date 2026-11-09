# MC-2 — Phase 1 investigation (evidence only)

Target: `HMaster.addColumn` throws `InvalidFamilyOperationException` at
`hbase-server/src/main/java/org/apache/hadoop/hbase/master/HMaster.java:2255`
(guard `old.hasColumnFamily(column.getName())` at :2254, `old = getTableDescriptors().get(tableName)` at :2253).
Tree: worktree at base_commit 6e53c90 plus trace-only Specula instrumentation (logging is off unless
`-Dspecula.trace.file` is set; line numbers of HMaster.addColumn unchanged vs pristine — the
instrumentation edits in place, `git diff --stat` HMaster.java = 6+/6-).

## Step 1: Code audit

Cited code (worktree line numbers):
- `HMaster.addColumn` :2243-2262: checkInitialized → checkTableExists → `old = getTableDescriptors().get(tableName)` (:2253)
  → `if (old.hasColumnFamily(...)) throw new InvalidFamilyOperationException(...)` (:2254-2256)
  → `modifyTable(tableName, newDesc, nonceGroup, nonce)`. The guard runs **before** any nonce
  handling; nonce dedup lives in `modifyTable` → `MasterProcedureUtil.submitProcedure` →
  `procExec.registerNonce` (MPU:126-128, PE:~735).
- `HMaster.modifyTable` :2437-2470: submits `ModifyTableProcedure` with
  `ProcedurePrepareLatch.createBlockingLatch()` (CompatibilityLatch, PPL:63-65, 94-) and `latch.await()` (:2459).
  The latch is released only in `ModifyTableProcedure.completionCleanup` → `releaseSyncLatch()` (MTP:169-171),
  i.e. the RPC reply is sent only after the whole procedure has finished.
- `ModifyTableProcedure.executeFromState`: PREPARE → PRE_OPERATION → UPDATE_TABLE_DESCRIPTOR
  (`updateTableDescriptor` → `TableDescriptors.add` → `FSTableDescriptors.updateTableDescriptor`,
  HDFS write at FSTD:590-592, then cache put) → REMOVE_REPLICA_COLUMN → POST_OPERATION
  (`cpHost.postCompletedModifyTableAction`, MTP:430-432) → REOPEN_ALL_REGIONS → done.
  So the new tableinfo is durable on HDFS several states before the reply.
- New master startup: `HMaster.finishActiveMasterInitialization` enables the descriptor cache and,
  with `hbase.master.preload.tabledescriptors` (default true) calls `tableDescriptors.getAll()`
  (HM:851-856) → reads tableinfo from HDFS, which already contains cf1. The procedure store is
  reloaded (`ProcedureExecutor.loadProcedures` PE:360-394), so the unfinished MTP resumes and
  its nonce key is re-registered — but the retried client request carries a **fresh** nonce.
- Client: `HBaseAdmin.addColumnFamilyAsync` (HBaseAdmin:1023-1039) builds the request inside
  `MasterCallable.rpcCall()` with `ng.newNonce()` — every retry attempt gets a new nonce, so even
  a working nonce dedup could not match the original request. A connection reset / call timeout
  / PleaseHoldException is retriable in `RpcRetryingCallerImpl`; the MasterCallable re-resolves the
  active master via ZK on each attempt.

Call chain: `Admin.addColumnFamily` → `HBaseAdmin.addColumnFamilyAsync` → `MasterRpcServices.addColumn`
→ `HMaster.addColumn` (target). Reachable during normal usage; the workload test
`TestTableDescriptorModificationFromClient#testAddColumn` exercises it.

Trigger scenario (= counterexample MC_hunt_s2_failover_bfs.out, 16 states):
1. Client sends addColumn(cf1), nonce n1, to master M1. Guard passes (old={cf0}). MTP submitted; handler blocks on the latch.
2. MTP reaches UPDATE_TABLE_DESCRIPTOR and writes tableinfo {cf0,cf1} to HDFS.
3. M1 crashes before MTP completes (no reply).
4. Client call fails retriably; backup master M2 becomes active, preloads descriptors from HDFS ({cf0,cf1}), reloads MTP.
5. HBaseAdmin retries addColumn(cf1) with fresh nonce n2 at M2; guard sees cf1 → InvalidFamilyOperationException at HM:2255.
6. Reloaded MTP completes on M2: cf1 really was added — by the client's own request.

Safeguards considered (to be tested in Phase 2): nonce dedup (bypassed — fresh nonce, and it sits after the guard);
client could treat "already exists" as success (it does not: `InvalidFamilyOperationException` is a DoNotRetryIOException
and propagates to the caller).

## Step 2: Developer knowledge (code-local only, before verdict)
- HM:2452-2455 comment: "Execute the operation synchronously - wait for the operation completes before continuing.
  We need to wait for the procedure to potentially fail due to 'prepare' sanity checks. This will block only the
  beginning of the procedure. See HBASE-19953." (In this tree the CompatibilityLatch actually blocks until completion.)
- Existing tests: `TestTableDescriptorModificationFromClient#testAddSameColumnFamilyTwice` asserts that a *second,
  distinct* addColumn of an existing family throws InvalidFamilyOperationException — intended behaviour for a genuine
  duplicate, not for a retry of the same logical request.
- Tracker / history searches: deferred until after the reproduction verdict (adhoc-coordination Shared Rule 2); see
  "Step 3" below.

## Step 3: Known-status
Source is MC with an actual counterexample → not subject to the code-review × known drop; proceed to Phase 2.
Novelty search results are appended after the verdict.

## Phase 2 summary (recorded after reproduction)
- Level 0 (no timing help) not separately attempted as a pure race: the window between the HDFS write and procedure
  completion is a few ms, so a blind crash lands there with negligible probability. Level 1 used: a MasterObserver
  holding `postCompletedModifyTableAction` (first public hook after the HDFS write) + `MiniHBaseCluster.abortMaster`.
- Run 1 (2 in-process masters, hot standby): TARGET FIRED. Runs 2–3 with hot standby: harness stall — the standby's
  HDFS lease recovery of the procedure WAL never completed ("Lease recovery is in progress", same-JVM DFSClient), so
  the new master never initialised; not a different outcome. Harness changed to abort → wait for master thread exit
  → `cluster.startMaster()` (CE states 10-12: crash, then a master comes up). seq-runs 1,2,3: TARGET FIRED 3/3.
- Verdict: REPRODUCED (Level 1).

## Novelty search (performed AFTER the verdict, Shared Rule 2) — queries
1. WebSearch: `HBASE jira addColumn retry "already exists so cannot be added" master failover nonce`
   → HBASE-20642, HBASE-18415, HBASE-20657, HBASE-20408.
2. WebSearch: `HBASE issue admin addColumnFamily retry InvalidFamilyOperationException after master restart procedure completed` → nothing more specific.
3. Fetched https://issues.apache.org/jira/browse/HBASE-20642 ("IntegrationTestDDLMasterFailover throws
   'InvalidFamilyOperationException'", Resolved/Fixed 21-Jun-2018, fix versions 2.0.2, 2.1.0, 3.0.0-alpha-1; symptom:
   failure "while adding column family during the time master is restarting") and HBASE-20657 (open; MTP retry with
   new nonce after master kill can get stuck — different symptom).
4. GitHub API commit search `HBASE-20642 repo:apache/hbase` → 72784c2d836a4b977667449d3adec5e8d15453f5
   (2018-06-20, parent e989a99, i.e. just after base 6e53c90 2018-06-20 14:19). Its diff: HBaseAdmin reuses the same
   nonce across retries, and HMaster.addColumn/modifyColumn/deleteColumn move the `hasColumnFamily` guard into a
   `TableDescriptorGetter` evaluated inside the NonceProcedureRunnable (after nonce dedup). Commit message: "changes
   modify table operations to help the case where a MTP spans two master, avoiding the sanity-checks propagating back
   to the client unnecessarily." → same mechanism, same site.
- Local git history: the pinned checkout has a single squashed commit ("base"), no usable history.
- Novelty: KNOWN (HBASE-20642; fix-status: fixed upstream, not present in the pinned tree).
