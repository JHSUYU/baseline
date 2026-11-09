# MC-3 investigation (evidence record)

Source tree: base commit 1790942bb2. Line numbers are from the pristine tree (`git archive 1790942bb2`).
Evidence runs used that pristine tree; early runs used the instrumented worktree and gave the same results.
Target: `AbstractStateMachineTableProcedure.java:163`, `TableNotEnabledException`, oracle `TargetSafe`.

## Step 1: code audit

Call chain to the target:
- Client `AdminOverAsyncAdmin.flush` -> `RawAsyncHBaseAdmin.flush` -> `HMaster.flushTable` (HMaster.java:4672)
- `FlushTableProcedure.executeFromState` (FlushTableProcedure.java:96) -> `preflightChecks` (:119)
- `AbstractStateMachineTableProcedure.preflightChecks` (:162-163) throws when the table is not ENABLED/ENABLING.

Observer path, `QuotaObserverChore.updateTableQuota` (QuotaObserverChore.java:316):
- :323 `snapshotNotifier.transitionTable` writes the observance row to hbase:quota (a Put to the region server).
- :325 `tableSnapshotStore.setCurrentState` advances the in-memory map.
- :333 `QuotaUtil.enableTableIfNotEnabled` is the only enable attempt, and it needs a live master.
- A later run compares the advanced map to the same target, so it is a no-op: the enable is never retried.

Workload shape: `TestAdhocWorkload04` keeps the observer in the test JVM with client retries = 0, so its map outlives
a master crash. Each of its two runs catches IOException ("the next run retries").

Production shape: the observer runs in the master. `tableQuotaSnapshots` (QuotaObserverChore.java:88) is memory only,
and `getTableQuotaSnapshot` (:538) answers NO_QUOTA ("No tracked state implies observance") on a new master.
A disabled table has no region reports, so it is filtered into limbo (:177), and limbo only acts on tables the
in-memory state shows in violation (:187). Nothing re-issues the enable.
`HMaster.enableTable` (:2857) also refuses an enable while the hbase:quota row says DISABLE violation.

Safeguards checked:
- Client retries on `admin.flush`: they wait for the new master, then surface the failure.
- Procedure recovery (`Procedure.restoreLock`, Procedure.java:991): covers a stored E only, not an E that was never submitted.
- No recovery path for a lost enable was found in the master startup or the chore.

Trigger: see the counterexample `spec/output/MC_hunt_S3_master_failover_bfs.out`, states 15-29.

## Step 2: developer knowledge

- Code comment at QuotaObserverChore.java:541: "No tracked state implies observance."
- Workload comment: "Observer run {} failed; the next run retries". That retry does not happen once the map has advanced.
- Commits on the file reviewed through `git log`: HBASE-20662, HBASE-22012 and others. None addresses this ordering.
- HBASE-30484 / PR #8791 (see Step 3) states the same no-retry mechanism and calls the restart window out of scope.
- `TestSpaceQuotaBasicFunctioning.testNoEnableAfterDisablePolicy` asserts the manual-enable denial during a violation.

## Step 3: known status

The search ran after the reproduction verdict was settled (Shared Rule 2). It set Novelty only.

Queries:
1. WebSearch: `HBASE JIRA space quota DISABLE policy table remains disabled after master restart failover QuotaObserverChore enableTable`
2. WebSearch (issues.apache.org, github.com, lists.apache.org): `QuotaObserverChore in-memory snapshot lost master crash table not re-enabled updateTableQuota enableTableIfNotEnabled HBASE issue`
3. git, at 1790942bb2: `git log -- QuotaObserverChore.java`; `git log -i --grep="space quota\|QuotaObserver\|DISABLE policy"`; `git log -i --grep="quota.*\(restart\|failover\|crash\)\|\(restart\|failover\|crash\).*quota"` (no hits)
4. JIRA REST JQL: `project=HBASE AND (text~"QuotaObserverChore" OR (text~"space quota" AND (text~"master restart" OR text~"failover"))) ORDER BY updated DESC`
5. JIRA REST JQL: `project=HBASE AND text~"space quota" AND (text~"master restart" OR text~"failover" OR text~"master crash") AND text~"disable" ORDER BY updated DESC`
6. JIRA REST: issue HBASE-30484. GitHub REST: apache/hbase pull 8791. (`gh` is not installed here.)

Result: KNOWN. https://issues.apache.org/jira/browse/HBASE-30484 reports the same mechanism at the same site.
Status Open with no fix version. https://github.com/apache/hbase/pull/8791 is open and unmerged (updated 2026-11-03).
Base commit 1790942bb2 has the old order. The report's trigger is a failed enable call (for example a coprocessor hook);
master death is another way to fail that call.
PR #8791 says recovery across a Master restart in the put-to-enable window is out of scope. No filed report was found
for the production-shape outcome: stale violation row, no re-enable after raising the limit, manual enable denied.

## Reproduction notes

- Driver: `repro/test_bugMC-3_master_crash_enable.sh <tree> [methods]`. Test: `repro/test_bugMC-3_SpeculaAdhoc04MC3Test.java`.
- Pristine tree recipe: `git archive 1790942bb2 | tar -x -C <dir>`, copy the test in, then in `<dir>` run
  `mvn -B -o -q test-compile -pl hbase-common,hbase-client,hbase-procedure,hbase-server -Denforcer.skip=true -Dcheckstyle.skip`.
- Output: `repro/MC-3.pristine.part1.log`, `repro/MC-3.pristine.part2.log`.
- First attempt failed for an environment reason: a new master took a new port, and the client registry lists only the
  old address (`MasterRegistryFetchException`, attempts=15). Restarting on the same port, as a real restart does, fixed it.
- First branch-3 attempt timed out: once E is submitted and its id returned, the client polls for the result, so the
  observer blocked while no master was running. The test now restarts the master during the observer's run.
