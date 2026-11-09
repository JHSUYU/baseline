# MC-4 investigation (evidence only)

Source tree: worktree at base_commit 1790942bb2, plus trace-only instrumentation. Target NamespaceStateManager.java:130.
The only behavior-adjacent edit is RestoreSnapshotProcedure's try/catch around the check, which logs and rethrows.

## Step 1: code audit
- Rebuild: NamespaceStateManager.initialize :232-234 uses `MetaTableAccessor.getTableRegions(conn, table, true)` and `addTable(table, regions.size())`.
- getTableRegions -> getTableRegionsAndLocations -> ClientMetaTableAccessor.CollectRegionLocationsVisitor.add (:481-490) adds one Pair per non-null HRegionLocation in the row, so one per located replica.
- Live create: CreateTableProcedure.preCreate :336-337 passes newRegions.size() (primaries); replicas are added later in addTableToMeta via RegionReplicaUtil.addReplicas.
- Target: Admin.restoreSnapshot -> SnapshotManager.restoreOrCloneSnapshot -> RestoreSnapshotProcedure.prepareRestore (state PRE_OPERATION; snapshotRegionCount from manifest, tableRegionCount from cache; check runs only if they differ) -> MasterQuotaManager.checkAndUpdateNamespaceRegionQuota -> NamespaceAuditor.checkQuotaToUpdateRegion -> NamespaceStateManager.checkAndUpdateNamespaceRegionCount :126-130.
- Failure handling: PRE_OPERATION supports rollback, so setFailure("master-restore-snapshot", e) (:188); the failure reaches the client.

## Reachability / trigger
Ordinary operations plus one master failover, nothing in flight:
create A (3); create B (4 regions, replication 2); snapshot A; merge A to 2; fail over master; disable A; restore.
Safeguards recorded: guard is skipped if cached table count == snapshot count; a replica without a location is not counted (visitor :486).

## Step 2: developer knowledge (non-history part)
- Comment at NamespaceStateManager:221 "Initialize namespace state cache by scanning meta table." No mention of replicas in hbase-server/.../namespace/ (grep "replica|getRegionReplication": no hits).
- Existing namespace tests set no region replication (only the Specula variant does); no test asserts either count semantics with replicas.
- Tracker/history search is deferred until the reproduction verdict is settled (adhoc-coordination Shared Rule 2).

## Reproduction outcome (recorded before the tracker search)
REPRODUCED at Level 0, runs 4 and 5 identical modulo ports/timestamps. See repro/MC-4.log, repro/MC-4.javap.txt.
Stack frame reads NamespaceStateManager.java:133: the target `throw new` statement spans :130-133 and the line table maps pc 70-81 (including <init> at 78 and athrow at 81) to line 133. It is the only QuotaExceededException site in the (TableName,int) overload.
Runs 1-3 failed on test-harness issues, not on the system: stale client registry after both initial masters died (run 1), client wraps the exception as RestoreSnapshotException (run 2), frame line 133 vs 130 (run 3).

## Step 2/3: tracker and history search (run after the verdict; sets Novelty only)
Queries:
- git log on NamespaceStateManager.java; git blame -L 232,234; git log -i --grep 'namespace.*replica|replica.*namespace|quota.*replica|replica.*quota'
- GitHub search/issues, sort=updated, repo:apache/hbase: "NamespaceStateManager"; "namespace quota replica"; "namespace region quota"; "NamespaceAuditor replica"
- GitHub pulls/8792, its files and comments; commits on NamespaceStateManager.java at upstream master; raw upstream master NamespaceStateManager.java
- Apache JIRA JQL (project = HBASE AND ...): text ~ "namespace quota" AND text ~ "replica"; text ~ "NamespaceStateManager"; summary ~ "namespace" AND summary ~ "replica"; text ~ "NamespaceAuditor" AND updated >= -365d; text ~ "region replica" AND text ~ "namespace" AND text ~ "quota" AND created >= -730d; text ~ "getTableRegions" AND text ~ "replica" AND text ~ "quota"
- HBASE-30483 and HBASE-22013 read directly
- Web: "HBase namespace quota region count includes region replicas after master restart NamespaceStateManager initialize"; "HBASE JIRA namespace quota hbase.namespace.quota.maxregions region replicas counted restore snapshot QuotaExceededException master failover"

Results:
- No report of this mechanism (rebuild at initialize counts located replicas). JQL summary namespace+replica: 0 hits.
- Upstream master initialize() is unchanged at :232-234; last commit on the file is HBASE-29005 (2024-12-05).
- HBASE-30483 / PR #8792 (open, updated 2026-11-03) and closed PR #8787: truncate path, different site and mechanism. The diff adds only setRegionCountForTable to NamespaceStateManager; initialize() is untouched.
  Quote from PR #8792 body: "namespace region quota accounting (table creation, split, merge) only counts default replicas."
- HBASE-22013: space quotas, QuotaObserverChore; different site.
- HBASE-28559, HBASE-28560, HBASE-15433, HBASE-13593: titles concern merge/split rollback/restore accounting, not the rebuild's replica count. Not read in full.
- git blame: :232 a11a35a113 (2017), :233 9c8c9e7fbf (2022 format), :234 bb0068893d (2015). No stated intent about replicas.
Novelty: NEW.
