# hbase-adhoc-08 MC-3 (tier B): rsgroup: meta assignment needs the namespace cache, which needs meta; master aborts

System: hbase. Found by Specula's ad hoc run `hbase-adhoc-08`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hbase-adhoc-08/MC-3
- **defect:** with rsgroup on, a meta RS crash during master init makes meta's assignment need the namespace cache (`RSGroupUtil` L117), which needs meta; the master aborts
- **why tier B:** needs rsgroup on and a crash during init

**Specula's finding MC-3:** Meta's assignment throws NamespaceNotFoundException from CSSI:111 while the schema cache loads, and the master aborts after a RegionServer crash

- **Cause:** HMaster publishes clusterSchemaService (HM:1610) before its cache loads (HM:1611), and RSGroupUtil guards only a null service (RGU:107-116), so RGU:117 reads an empty cache.
- **Trigger:** With hbase.balancer.rsgroup.enabled=true, the RegionServer holding meta crashes after the master passes waitForMetaOnline and before the namespace scan completes.
- **Consequence:** The assign thread throws from CSSI:111 and re-queues meta until the scan's retries run out, about 60 s at default retries; ClusterSchemaServiceImpl fails and the master aborts. A cluster with one master stays down until a new master is started, which then assigns meta through the null-service path.
- **Premises:** hbase.balancer.rsgroup.enabled=true; with it off the same schedule initializes the master and the target does not fire. A RegionServer crash is in the fault model; no master crash is needed. Measured on a mini cluster with default client retries. The user-region path and a standby taking over after the abort were not exercised.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S2_meta.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hbase-adhoc-08` (all phases) | 3h10m | 137.0M | $88.01 |
| of which: confirming this finding | | 4.4M | $4.35 |

Time is active time; quota sleeps are excluded.
