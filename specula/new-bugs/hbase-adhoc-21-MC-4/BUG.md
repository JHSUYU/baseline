# hbase-adhoc-21 MC-4 (tier B): master rebuild counts region replicas, creates reserve primaries; valid creates refused after every restart

System: hbase. Found by Specula's ad hoc run `hbase-adhoc-21`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as 22/CR-1.

## Explanation (verified)

- **case/finding:** hbase-adhoc-21/MC-4 (=22/CR-1)
- **defect:** `CreateTableProcedure.preCreate` reserves `newRegions.size()` (primaries, L334-337), but the master's rebuild `NamespaceStateManager.initialize` (L223-235) counts every replica's region; each master restart inflates a replicated table's count, so valid create, restore and split are refused at L126-133 / L166-174, and the next restart recreates it
- **why tier B:** namespace quota is off by default

**Specula's finding MC-4:** Master rebuild counts region replicas in the namespace cache while live paths count primaries, so restoreSnapshot is wrongly rejected after failover

- **Cause:** NamespaceStateManager.initialize uses MetaTableAccessor.getTableRegions, which returns one entry per located replica, while CreateTableProcedure.preCreate charges the quota with primaries only.
- **Trigger:** Quota 10: create A with 3 regions and B with 4 regions at replication 2, snapshot A, merge A to 2 regions, fail over the master, disable A, restore the snapshot.
- **Consequence:** The rebuilt cache holds B=8 against 4 primaries, the guard computes 10-2+3=11>10, and Admin.restoreSnapshot fails with QuotaExceededException although the restore would leave 7 primaries. The same operations are admitted without the failover.
- **Premises:** A table has region replication above 1 and its replicas have locations in meta when the new master scans it. The restore changes the table's region count, so RestoreSnapshotProcedure.prepareRestore runs the check. The inflation is enough to cross the namespace's hbase.namespace.quota.maxregions; the real primary total stays within it.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s3a_rebuild_replicas.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hbase-adhoc-21` (all phases) | 2h33m | 41.4M | $44.58 |
| of which: confirming this finding | | 2.0M | $2.42 |

Time is active time; quota sleeps are excluded.
