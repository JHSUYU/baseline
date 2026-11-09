# hbase-adhoc-13: Under accepted master/RS clock skew, the merge-qualifier delete (RS timestamp) does not cover the qualifiers written with the master timestamp, so a fully GC'd merged region keeps blocking new merges.

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/master/assignment/MergeTableRegionsProcedure.java:499`, `MergeTableRegionsProcedure.prepareMergeRegion(MasterProcedureEnv)`, throws `org.apache.hadoop.hbase.exceptions.MergeRegionException` when `regionStateStore.hasMergeRegions(ri)   (for a region ri to merge)`
- Starting test: `org.apache.hadoop.hbase.master.assignment.TestAdhocWorkload13#run`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** The master's clock is 5s ahead of the meta RegionServer's clock, below the 10s warning and 30s rejection thresholds. The test simulates this with a per-thread EnvironmentEdge. The catalog janitor GCs a freshly merged, reference-free region within that skew window, and the merged region is then merged again.

**Why (root cause in the source):** RegionStateStore.mergeRegions writes the info:merge* qualifiers with an explicit master timestamp (RegionStateStore.java:419,433-434). deleteMergeQualifiers deletes them with LATEST_TIMESTAMP (RegionStateStore.java:497), which the meta RS resolves with its own, earlier clock. The DeleteColumn marker therefore does not cover the cells, so GCMultipleMergedRegionsProcedure reports success and archives the parents while the qualifiers survive. The next merge is rejected at MergeTableRegionsProcedure.java:492-499 with a misleading 'major compact it' message that compaction cannot fix. Clock skew where the system reads wall-clock time is an allowed trigger. The effect lasts until a later janitor run re-deletes with a timestamp past the original (about one janitor period, 5 min by default), and the user's merge fails in the meantime.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The check is supposed to block merging a region only while it still references its merge parents, i.e. before the janitor's GC has run. Here the GC has fully completed: parents archived, parent rows deleted from meta, procedure SUCCESS, and a log line saying the merge qualifiers were deleted. The qualifiers survive only because RegionStateStore mixes timestamp sources. mergeRegions writes the qualifiers with an explicit master-clock timestamp, while deleteMergeQualifiers deletes them with LATEST_TIMESTAMP, which the meta RegionServer resolves with its own clock (HBASE-13875 fixed this kind of problem for overwriteRegions by using the master time for both the Delete and the Put, but not here). Any clock skew the cluster accepts (up to 30 s) where the master is ahead of the meta host, combined with a janitor run within that skew of the merge, turns the delete into a silent no-op. Consequence: the merged region is reported as having outstanding merge references even though none exist. Merges of it, by an admin or the normalizer, are rejected with a misleading 'major compact it' message that a compaction cannot fix. Every later janitor run sees the region as merged again and resubmits GC procedures for parents that no longer exist. This lasts until a later GC deletes the qualifiers with a RegionServer timestamp past Tm, i.e. at the next janitor period (5 min by default). The fix is to delete with the explicit master timestamp (or Tm+1).

**Execution (agent):** Cluster: 1 master + 1 RegionServer (which hosts hbase:meta), same set-up as TestAdhocWorkload13. The master host's clock is 5 s ahead of the meta RegionServer host's clock. That is below ServerManager's 10 s warning and 30 s rejection thresholds (hbase.master.warningclockskew / maxclockskew), so it is accepted without even a warning. In the single test JVM the skew is simulated with an injected EnvironmentEdge (a test hook): the RegionServer's RPC handler threads (thread name 'RpcServer.*port=<rsPort>') see now-5s, and every other thread sees real time. 1) Create a 5-region table. Merge regions R0+R1 into M with MergeTableRegionsProcedure. In MERGE_TABLE_REGIONS_UPDATE_META, RegionStateStore.mergeRegions writes M's row, including info:merge0000/merge0001, with an explicit master timestamp Tm = EnvironmentEdgeManager.currentTime() on the master. 2) Right afterwards the catalog janitor runs (here CatalogJanitor.scan() is called directly; in production it is the periodic chore or the operator's runCatalogJanitor). M has no reference files, so it submits GCMultipleMergedRegionsProcedure. That procedure archives R0/R1 and deletes their meta rows (GCRegionProcedure, using master timestamps), then calls RegionStateStore.deleteMergeQualifiers(M). That Delete uses addColumns(..., LATEST_TIMESTAMP), so the meta RegionServer stamps it with its own clock, about Tm+0.2s-5s < Tm. The DeleteColumn marker therefore does not cover the merge qualifier cells written at Tm. The procedure logs 'Deleted merge references ... deleted qualifiers merge0000, merge0001' and finishes with SUCCESS. Its parents are gone, but M's meta row still carries info:merge0000/merge0001 (the test reads them back). 3) A merge of M with its neighbour R2 is submitted. prepareMergeRegion finds regionStateStore.hasMergeRegions(M) == true and throws MergeRegionException ('... has a merge qualifier ...') at MergeTableRegionsProcedure.java:499. The procedure fails and rolls back.

**Stack frame (agent):** at org.apache.hadoop.hbase.master.assignment.MergeTableRegionsProcedure.prepareMergeRegion(MergeTableRegionsProcedure.java:499)

## Reproduction

- Test: `org.apache.hadoop.hbase.master.assignment.TestMergeQualifierClockSkew#testMergeAfterGcWithMasterClockAhead`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.master.assignment.TestMergeQualifierClockSkew#testMergeAfterGcWithMasterClockAhead' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/master/assignment/TestMergeQualifierClockSkew.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hbase.exceptions.MergeRegionException: Skip merging [a4ca276d49b65ec20d345e73a4ae9d9c, 28422bd7da5601a40e83a479c0975109], because a parent, [a4ca276d49b65ec20d345e73a4ae9d9c], has a merge qualifier (if a 'merge column' in parent, it was recently merged but still has outstanding references to its parents that must be cleared before it can participate in merge -- major compact it t`, frame `at org.apache.hadoop.hbase.master.assignment.MergeTableRegionsProcedure.prepareMergeRegion(MergeTableRegionsProcedure.java:499)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h10m | 1 | 1,367,481 | 50 | 24,303 | 68,621 | 1,274,507 | $1.29 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
