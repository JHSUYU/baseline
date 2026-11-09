# MC-3 investigation record

Line numbers are for the pinned tree `1790942bb2` unless marked. The harness worktree shifts some of them (RGU:117 is RGU:119 there, AM:2635 is AM:2638); CSSI:111 is the same in both.

## Code audit

- `HMaster#finishActiveMasterInitialization` waits for meta (HM:1179), then calls `initClusterSchemaService` (HM:1262).
- HM:1610 assigns `clusterSchemaService`. HM:1611 calls `startAsync`, which runs `doStart` on the calling thread. CSSI:58-65 calls `notifyStarted`, then `TableNamespaceManager#start`, whose `loadFromMeta` scans meta through the client.
- From HM:1610 until the scan ends, `getClusterSchema()` is non-null and the cache is empty.
- `RSGroupUtil#getRSGroupInfo` handles only a null service (RGU:107-116) and then calls `getNamespace` (RGU:117). CSSI:109-111 reads the cache only: `cache.get(name)` returning null throws `NamespaceNotFoundException`.
- Call chain: SCP -> TRSP#queueAssign -> AM#queueAssign -> AM assign thread -> AM#processAssignQueue -> AM#processAssignmentPlans (AM:2633) -> RSGroupBasedLoadBalancer#roundRobinAssignment -> generateGroupAssignments (RSGBLB:235) -> RGU:117 -> CSSI:111.
- With rsgroup off, `DisabledRSGroupInfoManager#determineRSGroupInfoForTable` returns the default group, so `getRSGroupInfo` returns before RGU:107.
- Meta is the one region whose plan depends on its own availability: the `hbase` row is only in meta, and meta's plan needs that row.

## Safeguards recorded

- AM:2634-2637 catches the IOException and re-queues the region. The next plan runs one dispatch wait later and fails the same way while the cache is empty.
- RGU:107-116 covers only the time before HM:1610.
- A later master starts with a null service and takes the RGU:108-115 path, so it can assign meta. Measured in Phase 2.

## Trigger scenario

rsgroup on. A master becomes active with meta open, and passes HM:1179. The RegionServer holding meta crashes. Before the scan completes, the master reaches HM:1610 and the scan blocks on the dead server. SCP queues meta's TRSP. The assign thread throws from CSSI:111 until the scan's retries run out. `doStart` calls `notifyFailed`, `awaitRunning` throws IllegalStateException (HM:1614), HM:1263-1272 rethrows it, and HM:2630 aborts the master.

## Developer evidence

- RGU:110-111 log text: "Can not get the namespace rs group config for meta table, since the meta table is not online yet, will use default group to assign meta first". The stated intent is that meta is assignable with no namespace lookup.
- RGU:113 log text: "ClusterSchema is null, can only use default rsgroup, should not happen?".
- `git blame`: the null guard came with 3709f335a8 (HBASE-22695, 2019-08-03). The namespace table was folded into meta by 1acbd36c90 (HBASE-21154, 2018-11-23).
- HM:1607 comment "Will be overridden in tests". The only override in tests is `TestShutdownBackupMaster$MockHMaster`, which aborts every RegionServer at that point with rsgroup off and asserts only a clean shutdown. No test found that crashes meta's host during the load with rsgroup on.
- No comment or test treats a throw at CSSI:111 during startup as expected.

## Known-status queries (run after the reproduction verdict was settled; Novelty only)

`specula findings lookup` with RSGroupUtil.getRSGroupInfo, NamespaceNotFoundException, ClusterSchemaServiceImpl: returned `[]`, and `persistent-findings-context.json` has no inherited records.

Local git: `git log` on RSGroupUtil.java and ClusterSchemaServiceImpl.java; `git blame -L 107,116` on RSGroupUtil.java; `git log --all -i --grep=ClusterSchema` on rsgroup/ and AssignmentManager.java.

Apache JIRA (JQL):
- `project=HBASE AND text~"RSGroupUtil" ORDER BY updated DESC`: HBASE-24591, HBASE-17654.
- `project=HBASE AND text~"getRSGroupInfo" AND text~"NamespaceNotFoundException"`: 0.
- `project=HBASE AND text~"initClusterSchemaService"`: 22, including HBASE-22089, HBASE-19992.
- `project=HBASE AND text~"rsgroup" AND text~"meta" AND text~"namespace" AND text~"assign" ORDER BY updated DESC`: 32, including HBASE-25255.
- `project=HBASE AND text~"ClusterSchema is null"`: HBASE-14888.
- `project=HBASE AND summary~"NamespaceNotFoundException" ORDER BY updated DESC`: HBASE-14254.
- `project=HBASE AND text~"Failed to generate group assignments"`: 6, none relevant.
- `project=HBASE AND text~"unable to round-robin assignment"`: 9, including HBASE-20919.
- `project=HBASE AND text~"NamespaceNotFoundException" AND text~"rsgroup"`: 2, annotation changes only.
- `project=HBASE AND text~"namespace" AND text~"cache" AND text~"master" AND text~"startup" AND updated>="2026-01-01" ORDER BY updated DESC`: HBASE-21154.
- `project=HBASE AND text~"TableNamespaceManager" ORDER BY updated DESC`: 98, top 10 read by title.

GitHub (REST search, `is:pr` in repo:apache/hbase; includes open and closed, sorted by updated): `RSGroupUtil` (8), `getRSGroupInfo namespace` (0), `initClusterSchemaService` (7), `NamespaceNotFoundException` (0), `ClusterSchemaService` (1). Commits API: RSGroupUtil.java newest 2022-05-01, ClusterSchemaServiceImpl.java newest 2024-03-10, HMaster.java since the base date: HBASE-30463, HBASE-30409. PR #8617 (HBASE-30348) does not change HMaster, RSGroupUtil, ClusterSchemaServiceImpl or TableNamespaceManager.

Closest reports, none the same mechanism at the same site:
- HBASE-20919 (Incomplete, 2.0.1): meta not assigned with rsgroup on, but through an NPE in an uninitialized RSGroupBasedLoadBalancer at `generateGroupMaps`, on a full restart with no crash.
- HBASE-22089 (Open): `getClusterSchema()` may return null. This finding is the non-null case with an empty cache, after RGU's null guard.
- HBASE-19992 (Open): same abort text, from an assign hole in the old hbase:namespace table.
- HBASE-30463 (Resolved): master abort from duplicate SCPs in `finishActiveMasterInitialization`.

Result: no prior report of this mechanism; no fix found upstream.
