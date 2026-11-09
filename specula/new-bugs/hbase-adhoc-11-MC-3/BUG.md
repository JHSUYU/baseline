# hbase-adhoc-11 MC-3 (tier A): truncate_region force-detaches a concurrent move's TRSP; region stuck CLOSING, unserved

System: hbase. Found by Specula's ad hoc run `hbase-adhoc-11`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as 10/CR-1.

## Explanation (verified)

- **case/finding:** hbase-adhoc-11/MC-3 (=10/CR-1)
- **defect:** `truncate_region` force-unassigns: `AssignmentManager` L1012-1018 unsets a concurrent move's TRSP without cancelling it, and the detached TRSP keeps running
- **consequence:** the close report is dropped, so the region stays CLOSING and unserved, surviving failover; requests fail at `preTransitCheck` L769
- **trigger:** `truncate_region` racing a move; default config, no held window. Tier confidence medium; HBCK2 bypass as recovery was not tested

**Specula's finding MC-3:** Truncate force-detaches a concurrent move TRSP, which later strands the region in CLOSING and makes operator requests fail at AssignmentManager:769

- **Cause:** preTransitCheck ignores the scheduler region lock, so a move can attach a TRSP while truncate holds that lock. Truncate's forced unassign unsets the TRSP without stopping it, and the TRSP never checks that it still owns the region node.
- **Trigger:** A balancer or Admin.move request attaches a move TRSP between truncate taking the region lock and running MAKE_OFFLINE, using public APIs and no fault.
- **Consequence:** After truncate succeeds, the detached TRSP closes the region and the RS report is dropped because no procedure is attached. The region stays CLOSING and unserved, Admin.move, assign and unassign throw DoNotRetryRegionException at AssignmentManager:769, and client I/O fails.
- **Premises:** Recovery snapshots before destructive actions are disabled (the default), so truncate holds the region lock throughout. A move request lands inside the window between truncate taking the lock and MAKE_OFFLINE; hit in 5 of 5 Level 0 mini-cluster runs, frequency on a real multi-host cluster not measured. Reproduced on a two-RegionServer mini cluster at pristine base_commit, not on a multi-host cluster. Permanence rests on bounded observation (180s idle, 150s after master failover, 180s after RS crash) plus the absence of a timeout or wake path in the code; HBCK2 bypass was not tested.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_forced_detach.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hbase-adhoc-11` (all phases) | 6h41m | 159.1M | $132.53 |
| of which: confirming this finding | | 2.3M | $5.26 |

Time is active time; quota sleeps are excluded.
