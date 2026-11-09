# hbase-adhoc-11 MC-2 (tier B): split admits a CLOSED parent; rollback sets OPEN with no location; assign refused

System: hbase. Found by Specula's ad hoc run `hbase-adhoc-11`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hbase-adhoc-11/MC-2
- **defect:** split admits a CLOSED parent; `rollbackPrepareSplit` (L601-606) sets OPEN with no location, so `assign` is refused at L769
- **why tier B:** needs a saturated namespace quota or a coprocessor veto

**Specula's finding MC-2:** Split rollback turns a CLOSED parent's state node to OPEN with no location, so assign is rejected at AssignmentManager:769 and the region stays unserved

- **Cause:** prepareSplitRegion accepts a CLOSED parent and sets SPLITTING without recording the prior state; rollbackPrepareSplit then sets OPEN unconditionally, in memory only, while meta stays CLOSED and no server hosts the region.
- **Trigger:** A split request passes checkOnline while the region is OPEN and parks on the region xlock behind a concurrent unassign; PREPARE then sees CLOSED and PRE_OPERATION fails on a saturated namespace region quota or a coprocessor veto, rolling the split back.
- **Consequence:** Admin.assign throws DoNotRetryRegionException from preTransitCheck at AssignmentManager.java:769 while the region is not served, so client reads fail; unassign or move then kill a procedure worker with an NPE and leave a stuck CLOSING region. Recovery needs HBCK force assign or a master failover.
- **Premises:** A split request reaches SplitTableRegionProcedure's constructor checkOnline before the concurrent unassign's first step moves the state node off OPEN, and is queued behind that unassign on the region xlock. PRE_OPERATION fails: namespace region quota saturated with hbase.quota.enabled=true, or a master coprocessor vetoes preSplitRegionAction. Persistence was observed for 30 seconds with a 1 second RIT chore; longer durations rest on no code path other than failover, HBCK force or a new TRSP changing the node's state.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_split_owner_l2.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hbase-adhoc-11` (all phases) | 6h41m | 159.1M | $132.53 |
| of which: confirming this finding | | 3.7M | $3.68 |

Time is active time; quota sleeps are excluded.
