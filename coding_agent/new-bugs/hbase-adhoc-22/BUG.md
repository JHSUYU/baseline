# hbase-adhoc-22: truncateTable(preserveSplits=false) does not update the master's namespace quota cache, so the namespace stays overcounted and valid table creates/clones/splits are refused with QuotaExceededException.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/namespace/NamespaceStateManager.java:168`, `NamespaceStateManager.checkAndUpdateNamespaceTableCount(TableName, int)`, throws `org.apache.hadoop.hbase.quotas.QuotaExceededException` when `(currentStatus.getRegionCount() + numRegions) > TableNamespaceManager.getMaxRegions(nspdesc)`
- Starting test: `org.apache.hadoop.hbase.namespace.TestAdhocWorkload22#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Namespace maxregions=2. A 2-region table is created, disabled and truncated with preserveSplits=false, which leaves 1 region. Then an ordinary createTable of a 1-region table in the same namespace is issued.

**Why (root cause in the source):** TruncateTableProcedure with preserveSplits=false recreates the table with a single region (TruncateTableProcedure.java:128-130). It never notifies MasterQuotaManager/NamespaceAuditor: there is no quota call anywhere in TruncateTableProcedure, and nothing in quotas/namespace handles truncate. So NamespaceStateManager keeps 2 regions for the table. checkAndUpdateNamespaceTableCount (NamespaceStateManager.java:165-174) then computes 2(cached)+1=3>2 and rejects a create whose real usage is 1+1=2. Retrying never helps; the overcount lasts until the table is deleted or the master restarts. The trigger is plain client operations with valid config.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Namespace region-quota state is coordinated ad hoc between the table DDL procedures (create/delete/split/merge/restore) and the master's in-memory NamespaceStateManager cache, which is built from meta only at master start; there is no periodic chore that corrects it, despite the javadoc. TruncateTableProcedure with preserveSplits=false changes a table's region count but skips this coordination, so the cache overcounts the namespace's regions. The check then rejects a perfectly valid request (1 actual + 1 new = 2 regions, within the limit of 2). It is not a transient condition: the message says to retry later, but retrying never helps. The overcount stays until the table is deleted or the master restarts/fails over (re-initialization from meta), so users see their namespace region quota permanently shrunk. Creating tables, cloning snapshots and splitting regions in the namespace are all wrongly denied.

**Execution (agent):** Single-RS mini cluster with namespace quotas enabled (hbase.quota.enabled=true). 1) Client creates namespace adhoc_workload_22 with hbase.namespace.quota.maxregions=2. 2) Client creates table truncated with split key 'm' (2 regions); CreateTableProcedure.preCreate -> NamespaceStateManager.checkAndUpdateNamespaceTableCount caches truncated=2 regions. 3) Client disables the table and calls truncateTable(truncated, preserveSplits=false). TruncateTableProcedure deletes the 2 old regions from meta/FS and creates/assigns 1 new region (ModifyRegionUtils.createRegionInfos(desc, null)), but it never notifies the MasterQuotaManager/NamespaceAuditor, so the master's in-memory namespace cache keeps truncated=2. The test verifies hbase:meta lists 1 region for the table while the cache shows tableAndRegionInfo=adhoc_workload_22:truncated=2. 4) Client creates a 1-region table adhoc_workload_22:created. Real usage is 1+1=2 <= 2, but CreateTableProcedure.preCreate -> MasterQuotaManager.checkNamespaceTableAndRegionQuota -> NamespaceAuditor.checkQuotaToCreateTable -> NamespaceStateManager.checkAndUpdateNamespaceTableCount evaluates 2(cached)+1=3 > 2 and throws QuotaExceededException at line 168; the client's createTable fails. (In the original workload the subsequent delete removes the table from the cache before the create, which hides the stale count; any create/clone/split issued while the truncated table still exists, or while its delete is still in progress, hits the bad cached value.)

**Stack frame (agent):** at org.apache.hadoop.hbase.namespace.NamespaceStateManager.checkAndUpdateNamespaceTableCount(NamespaceStateManager.java:172)  -- this is the `throw new QuotaExceededException(...)` statement that begins at line 168 (javap: `new` at bci 95 = line 168; the multi-line message concatenation makes the <init> invokespecial at bci 119 carry line 172)

## Reproduction

- Test: `org.apache.hadoop.hbase.namespace.TestAdhocWorkload22Repro#run`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.namespace.TestAdhocWorkload22Repro#run' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/TestAdhocWorkload22Repro.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hbase.quotas.QuotaExceededException: The table adhoc_workload_22:created is not allowed to have 1 regions. The total number of regions permitted is only 2, while current region count is 2. This may be transient, please retry later if there are any ongoing split operations in the namespace.`, frame `at org.apache.hadoop.hbase.namespace.NamespaceStateManager.checkAndUpdateNamespaceTableCount(NamespaceStateManager.java:172)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h03m | 1 | 443,772 | 24 | 9,465 | 36,089 | 398,194 | $0.56 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
