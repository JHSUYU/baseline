# hbase-adhoc-21: A rolled-back split never releases its namespace-quota region reservation (onRegionSplitReverted is never called), so later valid restore/create/split operations in the namespace are refused with QuotaExceededException until the master restarts.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/namespace/NamespaceStateManager.java:130`, `NamespaceStateManager.checkAndUpdateNamespaceRegionCount(TableName, int)`, throws `org.apache.hadoop.hbase.quotas.QuotaExceededException` when `nspdesc != null && (currentStatus.getRegionCount() - regionCountOfTable + incr) > TableNamespaceManager.getMaxRegions(nspdesc)`
- Starting test: `org.apache.hadoop.hbase.namespace.TestNamespaceAuditor#testRestoreSnapshot`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** With namespace maxregions=6, a split of a table1 region is aborted after SPLIT_TABLE_REGION_PRE_OPERATION by a master coprocessor that throws IOException in preSplitRegionBeforeMETAAction (a supported veto hook, and equivalent to any rollback-able failure after the reservation, such as recovered.edits or a close or FS error). The split rolls back. A later restoreSnapshot of a 4-region snapshot into another table (real total 2+4=6) is then refused.

**Why (root cause in the source):** SplitTableRegionProcedure.preSplitRegion calls masterQuotaManager.onRegionSplit (SplitTableRegionProcedure.java:625), which increments the namespace cache (NamespaceStateManager.java:~98, incRegionCountForTable). rollbackState for PRE_OPERATION only calls postRollBackSplitRegion, which runs the coprocessor hook (SplitTableRegionProcedure.java:396-397, 639-644). MasterQuotaManager.onRegionSplitReverted (MasterQuotaManager.java:646) has no caller in main code. So every rolled-back split permanently inflates the cached region count until a master restart. checkAndUpdateNamespaceRegionCount (NamespaceStateManager.java:126-133) then computes 4-1+4=7>6 from the stale cache and rejects a restore that actually fits the quota. This is a coordination leak, not a correct rejection, and it persists and accumulates.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The split acts as a reservation protocol: it reserves +1 region in the master's in-memory namespace cache before the split commits. On abort, a correct protocol must release the reservation. SplitTableRegionProcedure.rollbackState never calls onRegionSplitReverted/removeRegionFromNamespaceUsage, so every split rolled back after PRE_OPERATION permanently inflates the namespace region count. The only correction is a master restart or failover, which rebuilds the cache from meta. Nothing else re-syncs it. The check then rejects state that a correct coordination would not have produced: the cached count no longer matches meta. In a real deployment, splits roll back routinely, e.g. on region-close or HDFS errors, file-split timeouts, coprocessor vetoes, or a split switch flipped mid-way. Each rollback leaks one region of quota. The leaks add up until valid restore-snapshot operations (this check), table creates/clones, and later splits are refused with QuotaExceededException even though the namespace is under its quota. That blocks administrative recovery such as restoring a table from a snapshot.

**Execution (agent):** Single master + 1 RS mini cluster, namespace quota enabled. 1) Create namespace ns with hbase.namespace.quota.maxregions=6. 2) Create ns:table1 with 2 regions. Create ns:table2 with 4 regions, snapshot it, then delete it and re-create it with 1 region. The master's namespace cache now correctly says 3 regions. 3) Request a split of a table1 region. SplitTableRegionProcedure runs SPLIT_TABLE_REGION_PRE_OPERATION, where preSplitRegion -> MasterQuotaManager.onRegionSplit -> NamespaceStateManager.checkAndUpdateNamespaceRegionCount(name, regionName, +1) reserves one region in the cache (table1=3, total=4). The procedure then closes the parent, creates daughters, and fails at SPLIT_TABLE_REGION_PRE_OPERATION_BEFORE_META. In the test a master observer's preSplitRegionBeforeMETAAction throws an IOException, which stands in for any failure in the rollback-able steps such as a close failure or an HDFS/daughter-commit error or timeout. 4) The procedure rolls back: daughters are deleted, the parent is reopened, and table1 really has 2 regions again. No rollback step undoes the quota reservation (MasterQuotaManager.onRegionSplitReverted exists but is never called), so the cache stays at table1=3, total=4. 5) Disable table2 and restore the 4-region snapshot. Real usage after the restore would be 2+4=6, within the limit of 6. But RestoreSnapshotProcedure.prepareRestore -> checkAndUpdateNamespaceRegionQuota -> checkAndUpdateNamespaceRegionCount(table2, 4) computes 4 - 1 + 4 = 7 > 6 and throws QuotaExceededException. The procedure is ROLLEDBACK and the client gets a RestoreSnapshotException caused by QuotaExceededException.

**Stack frame (agent):** at org.apache.hadoop.hbase.namespace.NamespaceStateManager.checkAndUpdateNamespaceRegionCount(NamespaceStateManager.java:133)  (this is the 'throw new QuotaExceededException(' statement that starts at line 130; its message argument spans lines 130-133 and javac attributes the constructor call to line 133)

## Reproduction

- Test: `org.apache.hadoop.hbase.namespace.TestNamespaceAuditorSplitRollbackLeak#testRestoreSnapshotAfterRolledBackSplit`
- Command: `source /bulk/codingagent/cases/hbase-adhoc-21/agent/env.sh && mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.namespace.TestNamespaceAuditorSplitRollbackLeak#testRestoreSnapshotAfterRolledBackSplit' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/TestNamespaceAuditorSplitRollbackLeak.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.hadoop.hbase.quotas.QuotaExceededException: The table TestNamespaceAuditorSplitRollbackLeak_ns:table2 region count cannot be updated as it would exceed maximum number of regions allowed in the namespace.  The total number of regions permitted is 6`, frame `at org.apache.hadoop.hbase.namespace.NamespaceStateManager.checkAndUpdateNamespaceRegionCount(NamespaceStateManager.java:133)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h04m | 1 | 760,920 | 30 | 13,802 | 63,637 | 683,451 | $0.92 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
