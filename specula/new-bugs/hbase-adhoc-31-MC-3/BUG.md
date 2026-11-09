# hbase-adhoc-31 MC-3 (tier B): crashed RS both online and dead after failover; stays online for good, cluster shutdown never completes

System: hbase. Found by Specula's ad hoc run `hbase-adhoc-31`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hbase-adhoc-31/MC-3
- **defect:** after a failover, a crashed RS with a pending SCP and a lingering znode is recorded online (`RegionServerTracker` L148-155) and also dead; `expireServer` returns early for a dead server (`ServerManager` L675-678) before `moveFromOnlineToDeadServers`, the only `onlineServers.remove` (L734), so it stays online for good and `Admin#shutdown` never completes
- **why tier B:** level 0 fired 0 of 2; needs a master abort within ms of the SCP

**Specula's finding MC-3:** After failover a crashed RS read from ZK with a pending SCP stays online: stale RPCs hit the target check and cluster shutdown never completes

- **Cause:** RegionServerTracker.upgrade records a crashed predecessor online from its lingering znode and dead from its unfinished SCP; ServerManager.expireServer returns early for a dead server before removing it from onlineServers.
- **Trigger:** RS crashes with its znode lingering, dispatcher fail-fast expires it and stores an SCP, the master hands off promptly, and a same-port successor registers before the new master is initialized. For the permanent form the znode also expires before the dead entry is cleared.
- **Consequence:** The restored close reaches the successor and RSRpcServices.throwOnWrongStartCode throws. If the session expires before initialization the predecessor is never retired: Admin#getRegionServers lists it and Admin#shutdown leaves the master running because onlineServers never empties.
- **Premises:** The fault is a kill -9 with the znode lingering, realized by parking the RS exit between rpcServices.stop and deleteMyEphemeralNode in a test subclass. The master hands off promptly (abort or stop). A master kill -9 with an equal session timeout is argued not to reach this. SCP is still pending at the handoff: one of eight default-limit runs lost that race. The successor registers before initialized, using HBase's default wait-on-regionservers settings, not the mini-cluster's pinned ones. The permanent form needs session expiry inside the window before the dead entry is cleared; the test chose that moment.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_s3_late_register.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hbase-adhoc-31` (all phases) | 4h21m | 99.3M | $79.00 |
| of which: confirming this finding | | 7.3M | $6.25 |

Time is active time; quota sleeps are excluded.
