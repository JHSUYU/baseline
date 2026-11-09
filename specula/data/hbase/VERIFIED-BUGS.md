# HBase: verified bugs (high quality, severe, make the ad hoc check fail)

Same bar as `../hdfs/VERIFIED-BUGS.md`. Source: apache/hbase `1790942bb2`. Each was reviewed by an independent verifier (`../batches/VERIFY-batch4.md`, with the file:line citations). The operator then read parts of the decisive code. No test was rerun; hit rates and permanence come from the runs, on mini clusters. Novelty negatives are bounded.

## Tier A

| case/finding | defect | consequence | trigger |
| --- | --- | --- | --- |
| hbase-adhoc-11/MC-3 (=10/CR-1) | `truncate_region` force-unassigns: `AssignmentManager` L1012-1018 unsets a concurrent move's TRSP without cancelling it, and the detached TRSP keeps running | the close report is dropped, so the region stays CLOSING and unserved, surviving failover; requests fail at `preTransitCheck` L769 | `truncate_region` racing a move; default config, no held window. Tier confidence medium; HBCK2 bypass as recovery was not tested |

## Tier B

| case/finding | defect | why tier B |
| --- | --- | --- |
| hbase-adhoc-11/MC-2 | split admits a CLOSED parent; `rollbackPrepareSplit` (L601-606) sets OPEN with no location, so `assign` is refused at L769 | needs a saturated namespace quota or a coprocessor veto |
| hbase-adhoc-04/MC-3 | a new master forgets a quota DISABLE; raising the limit does nothing and a manual enable is denied | space quota is off by default; only `prodShape_masterRestart` counts |
| hbase-adhoc-08/MC-3 | with rsgroup on, a meta RS crash during master init makes meta's assignment need the namespace cache (`RSGroupUtil` L117), which needs meta; the master aborts | needs rsgroup on and a crash during init |
| hbase-adhoc-08/MC-1 | a recovered namespace delete races quota init (`NamespaceStateManager` L224-227 to `ClusterSchemaServiceImpl` L111); the new master aborts | weakest: 0/3 with the workload's namespace alone, 3/10 with extra tables |

## Dropped so far

The other findings of 04, 07, 08, 10, 11, 12, 13, 14, 15, 19: known (HBASE-30484, 30008, 21455, 30385, 19851, 13652), unrealistic, off-target, masked, or not severe. See the report's table.

**Owner may overrule:** 10/CR-4 + 12/MC-2 (real, severe if reached, but needs a held 200-800 ms handler stall, 0/250 unaided); 10/MC-3 (severe part comes from a known limitation).

**Off-target, not counted:** S1 from 14/CR-3 (a swallowed storage error makes `refresh_meta` delete a table's meta rows and directory with no archive); S2 from 11/CR-7 (a null target at `RegionRemoteProcedureBase` L406 kills a worker and leaves a region CLOSING).

**Note:** `hbase-adhoc-19`'s `target.yaml` says L134 but quotes the name guard, whose throw is at `ModifyTableProcedure` L127.

## Added from batch 5 (tier B; details and citations: `../batches/VERIFY-batch5.md`)

The operator re-read the decisive code at `1790942bb2`. No test was rerun.

| case/finding | defect | why tier B |
| --- | --- | --- |
| hbase-adhoc-21/MC-4 (=22/CR-1) | `CreateTableProcedure.preCreate` reserves `newRegions.size()` (primaries, L334-337), but the master's rebuild `NamespaceStateManager.initialize` (L223-235) counts every replica's region; each master restart inflates a replicated table's count, so valid create, restore and split are refused at L126-133 / L166-174, and the next restart recreates it | namespace quota is off by default |
| hbase-adhoc-31/MC-3 | after a failover, a crashed RS with a pending SCP and a lingering znode is recorded online (`RegionServerTracker` L148-155) and also dead; `expireServer` returns early for a dead server (`ServerManager` L675-678) before `moveFromOnlineToDeadServers`, the only `onlineServers.remove` (L734), so it stays online for good and `Admin#shutdown` never completes | level 0 fired 0 of 2; needs a master abort within ms of the SCP |

**Dropped from batch 5:** the other findings of 20, 21, 22, 24, 28, 31, 34, 35, 37: known (HBASE-30483, 28559, 28560, 13388, 17305, 26215), Kerberos-only, held windows, off-target, or not severe. hbase-34/MC-2's TLC config records MC-1's ordering (its trace came from a later-edited probe spec), so its model evidence cannot be regenerated.

**Owner may overrule:** 21/MC-7 (=22/CR-6), clone rollback removes a live table's quota entry; 20/MC-4, an acknowledged family removed, but 0 of 16 without hooks.

**Off-target, not counted:** from 34/CR-3, on a secure cluster a new key master reuses a key id with a new secret, so unexpired tokens fail everywhere until they expire.
