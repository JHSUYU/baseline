# hbase-adhoc-04 MC-3 (tier B): new master forgets a quota DISABLE; raising the limit does nothing

System: hbase. Found by Specula's ad hoc run `hbase-adhoc-04`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hbase-adhoc-04/MC-3
- **defect:** a new master forgets a quota DISABLE; raising the limit does nothing and a manual enable is denied
- **why tier B:** space quota is off by default; only `prodShape_masterRestart` counts

**Specula's finding MC-3:** Master crash before the observer's enable loses it: the map has advanced, nothing retries, and flush fails at L163 on a table left DISABLED

- **Cause:** QuotaObserverChore.updateTableQuota writes the observance row and advances its in-memory snapshot before its single enable attempt, and the pending enable is not recorded anywhere that survives a failure.
- **Trigger:** The active master is killed after the observer's put and map update, or before a run whose connection already knows hbase:quota. The enable fails, the next run is a no-op, and the next master initializes with the table still DISABLED.
- **Consequence:** admin.flush fails with TableNotEnabledException thrown at AbstractStateMachineTableProcedure.java:163, and the table stays DISABLED until an operator acts.
- **Premises:** The observer's single enable attempt fails because no master is running; in the workload it has client retries = 0. In the workload the observer's map outlives the crash because it lives in the test JVM; the same no-retry follows from any failed enable. A master kill is in the fault model; the reproduction injects only SingleProcessHBaseCluster.killMaster and restarts the master on its old port. The E-stored-but-never-locked branch was not reached on the real system; the confirmation rests on the E-never-stored branch.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S3_master_failover.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hbase-adhoc-04` (all phases) | 2h38m | 101.1M | $67.38 |
| of which: confirming this finding | | 3.2M | $3.63 |

Time is active time; quota sleeps are excluded.
