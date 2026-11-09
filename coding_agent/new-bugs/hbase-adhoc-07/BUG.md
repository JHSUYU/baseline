# hbase-adhoc-07: A clone racing with an in-progress clone of the same name is sent down the restore path, which validates (and would restore) the snapshot's source table instead of the clone target.

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/master/snapshot/SnapshotManager.java:1046`, `SnapshotManager.restoreSnapshot(SnapshotDescription, TableName, SnapshotDescription, TableDescriptor, NonceKey, boolean)`, throws `java.lang.UnsupportedOperationException` when `master.getTableStateManager().isTableState(TableName.valueOf(snapshot.getTable()), TableState.State.ENABLED)`
- Starting test: `org.apache.hadoop.hbase.snapshot.TestAdhocWorkload07#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Two clients clone the same snapshot into the same new table at the same time. A latch on the hbase:meta region holds the first CloneSnapshotProcedure's meta write (a slow meta RS). The second clone passes the client tableExists check because there is no table-state row yet.

**Why (root cause in the source):** SnapshotManager.restoreOrCloneSnapshot (SnapshotManager.java:1013-1018) sends the request down the restore path whenever master.getTableDescriptors().exists(target) is true. The first clone's WRITE_FS_LAYOUT step has already written that descriptor, while the client-side check in RawAsyncHBaseAdmin.cloneSnapshot (line 2311) reads the meta table-state row, which does not exist yet. The private restoreSnapshot then checks the state of snapshot.getTable(), the snapshot's SOURCE table, instead of the requested target (line 1044-1046). The enabled source table makes it throw an unchecked UnsupportedOperationException about a table the client never touched. The second clone would have to fail anyway, so the visible result here is only a wrong, misleading exception. The same misrouting is worse in a case the test did not show: if the source table is disabled, the inner restoreSnapshot(snapshot, snapshotTableDesc, ...) (line 1083-1104) would restore over the SOURCE table on a request to clone into a new name.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Client B asked for a clone into a new table and never asked for a restore. A correct protocol would reject B with TableExistsException, or a 'clone already in progress' error, for T2. Instead, two existence checks disagree during a normal, unbounded window of CloneSnapshotProcedure: the client checks the meta table-state row, while the master checks the filesystem descriptor written earlier in WRITE_FS_LAYOUT. Because of that, a clone request is sent down the restore path. The restore check then validates the wrong table (the snapshot's source table instead of the requested destination), so the client gets a misleading 'Table T must be disabled' UnsupportedOperationException about a table it never touched. That is an unchecked RuntimeException surfaced through the RPC instead of a proper HBaseIOException. The same routing has a worse outcome when the source table T happens to be disabled: the check passes, and the inner restoreSnapshot uses snapshotTableDesc.getTableName() (= T), so a request to clone into T2 silently restores and overwrites the source table T from the snapshot. The race needs only two clients cloning to the same name, or a clone racing with createTable of the same name, plus a meta write that is not instantaneous. All of these happen in real deployments, for example retried automation jobs or several operators.

**Execution (agent):** Mini cluster with 1 master and 1 RS, same configuration as TestAdhocWorkload07. (1) Create table T (adhoc_workload_07, ENABLED), load 10 rows, take FLUSH snapshot S. T stays enabled. (2) Client A calls cloneSnapshot(S, T2) where T2 is a new table. Its client-side tableExists(T2) check (the table-state row in hbase:meta) returns false. The master runs restoreOrCloneSnapshot, sees no descriptor for T2, and submits CloneSnapshotProcedure. The procedure runs CLONE_SNAPSHOT_WRITE_FS_LAYOUT, which writes T2's region dirs and table descriptor to the filesystem and caches it in TableDescriptors. It then reaches CLONE_SNAPSHOT_ADD_TO_META, whose region-row put to hbase:meta is slow. The test holds that put with a latch in a RegionObserver.preBatchMutate on the meta region, which stands in for a slow or GC-paused meta region server. The table-state row of T2 is written later still, in CLONE_SNAPSHOT_ASSIGN_REGIONS. (3) While A is in that window, client B issues the same cloneSnapshot(S, T2). B's tableExists(T2) reads the meta table-state row, which does not exist yet, so B gets false and sends the RestoreSnapshot RPC as a clone. On the master, restoreOrCloneSnapshot finds master.getTableDescriptors().exists(T2) == true and routes B's clone into the private restoreSnapshot(...) path. There the check at line 1046 tests the state of TableName.valueOf(snapshot.getTable()), which is the SOURCE table T, not the destination T2. T is ENABLED, so the check throws UnsupportedOperationException("Table 'adhoc_workload_07' must be disabled in order to perform a restore operation."), and the exception reaches client B. (4) The latch is released and A's clone completes normally.

**Stack frame (agent):** at org.apache.hadoop.hbase.master.snapshot.SnapshotManager.restoreSnapshot(SnapshotManager.java:1046)

## Reproduction

- Test: `org.apache.hadoop.hbase.snapshot.TestAdhocConcurrentCloneSnapshot07#run`
- Command: `source /bulk/codingagent/cases/hbase-adhoc-07/agent/env.sh && mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.snapshot.TestAdhocConcurrentCloneSnapshot07#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/snapshot/TestAdhocConcurrentCloneSnapshot07.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: java.lang.UnsupportedOperationException: Table 'adhoc_workload_07' must be disabled in order to perform a restore operation.`, frame `at org.apache.hadoop.hbase.master.snapshot.SnapshotManager.restoreSnapshot(SnapshotManager.java:1046)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h04m | 1 | 548,495 | 28 | 15,442 | 47,105 | 485,920 | $0.78 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
