# hbase-adhoc-08 MC-1 (tier B): recovered namespace delete races quota init; the new master aborts

System: hbase. Found by Specula's ad hoc run `hbase-adhoc-08`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hbase-adhoc-08/MC-1
- **defect:** a recovered namespace delete races quota init (`NamespaceStateManager` L224-227 to `ClusterSchemaServiceImpl` L111); the new master aborts
- **why tier B:** weakest: 0/3 with the workload's namespace alone, 3/10 with extra tables

**Specula's finding MC-1:** Namespace deletion recovered after failover races quota init: NamespaceStateManager.initialize throws from CSSI:111 and the new active master aborts

- **Cause:** A recovered DeleteNamespaceProcedure is released by setInitialized(true) at HMaster:1300, before initQuotaManager at HMaster:1335, and nothing orders it against NamespaceStateManager.initialize, which snapshots namespaces at NSM:224 and looks each up at NSM:227 with no handling of a namespace deleted in between.
- **Trigger:** Quota enabled. A master crashes after a DeleteNamespaceProcedure is persisted and before its meta delete. On the backup master the procedure removes the namespace from the cache between NSM:224 and NSM:227. Tables in namespaces sorting before the deleted one widen the window; 5 were enough.
- **Consequence:** NamespaceNotFoundException from ClusterSchemaServiceImpl.getNamespace:111 propagates uncaught to HMaster.startActiveMasterManager, which aborts the new active master. One master crash costs a second master; in a two-master cluster no active master remains and client master operations fail until another master starts.
- **Premises:** Quota support is enabled (hbase.quota.enabled); MasterQuotaManager.start returns early otherwise. The master dies between the DeleteNamespaceProcedure store insert and its meta delete, a window of a few ms on an idle mini cluster. The namespace cache lookup at NSM:227 happens after the procedure's cache.remove; a namespace with tables sorting earlier widens this window, and with none the race was not lost in 3 of 3 control rounds. Reproduced in a single-JVM mini cluster where the master crash is HMaster.abort, not an OS process kill.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S1a.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hbase-adhoc-08` (all phases) | 3h10m | 137.0M | $88.01 |
| of which: confirming this finding | | 3.3M | $3.60 |

Time is active time; quota sleeps are excluded.
