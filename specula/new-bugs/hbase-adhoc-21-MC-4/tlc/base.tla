---------------------------------- MODULE base ----------------------------------
(*
 * Base specification for hbase-adhoc-21: can the master reach the failing branch of
 *   NamespaceStateManager.checkAndUpdateNamespaceRegionCount(TableName, int)
 *   (namespace/NamespaceStateManager.java:130, QuotaExceededException)?
 *
 * Source pinned at apache/hbase 1790942bb2. Unless a path names another module, paths
 * are relative to hbase-server/src/main/java/org/apache/hadoop/hbase/.
 *
 * Scope: one namespace with a fixed KEY_MAX_REGIONS and non-system tables, so the guards
 * at NamespaceStateManager:118 (isSystemTable) and :123 (nspdesc /= null) always pass.
 * Lowering the quota is out of scope (brief 3.2), so MaxRegions is a constant.
 *
 * Every procedure holds the table's exclusive lock or the region locks across the steps
 * that matter here, and the manager's methods are synchronized, so each action below is
 * one atomic step from the point of view of the guard.
 *)
EXTENDS Integers, FiniteSets, TLC

CONSTANTS
    Tables,             \* Table names in the namespace
    Snapshots,          \* Snapshot names
    MaxRegions,         \* TableNamespaceManager.getMaxRegions(nspdesc)
    CreateSizes,        \* Region counts a client may pass to createTable
    Replications,       \* Region replication factors a client may set
    MergeWidths,        \* Region counts a client may pass to mergeRegions
    MobChoices          \* {0} or {0, 1}: 1 means the manifest has the MOB pseudo-region

ASSUME MaxRegions \in Nat /\ MaxRegions > 0
ASSUME CreateSizes \subseteq Nat \ {0}
ASSUME Replications \subseteq Nat \ {0}
ASSUME \A n \in MergeWidths : n \in Nat /\ n >= 2    \* MergeTableRegionsProcedure:126
ASSUME MobChoices \subseteq {0, 1}

\* A manifest stored by a completed snapshot, or a clone or restore in flight.
\* online = non-parent regions, parents = offline split parents, mob = MOB pseudo-region.
Manifest(t, on, par, mob, r) ==
    [table |-> t, online |-> on, parents |-> par, mob |-> mob, replication |-> r]

\* online is at least 1 in every real manifest, so online = 0 marks "no manifest".
NoManifest == Manifest("none", 0, 0, 0, 0)
HasManifest(m) == m.online > 0

\* RestoreSnapshotProcedure:380 and CloneSnapshotProcedure:422 count every manifest entry,
\* with no filter (snapshot/SnapshotManifest:477-486).
ManifestSize(m) == m.online + m.parents + m.mob

VARIABLES
    \* ---- Meta and table state: what is really there ----
    tableState,      \* [Tables -> {"absent", "creating", "enabled", "disabled"}]
                     \*   "creating": PRE_OPERATION done, descriptor not written yet
    online,          \* [Tables -> Nat] primary, non-parent regions in meta
    parents,         \* [Tables -> Nat] offline split parents in meta (Scenario 1)
    replication,     \* [Tables -> Nat] descriptor's region replication (Scenario 3)
    snapManifest,    \* [Snapshots -> manifest record] completed snapshots (Scenario 1)
    \* ---- Master memory ----
    cache,           \* Partial function Tables -> Int, the namespace's
                     \*   tableAndRegionInfo (NamespaceTableAndRegionInfo:37). A live table
                     \*   can be missing from it (Scenario 5)
    masterReady,     \* MasterQuotaManager published (master/HMaster:1622-1624) (Scenario 3)
    \* ---- Procedures in flight; they survive a master crash ----
    inflightCreate,  \* [Tables -> Nat] regions a create has reserved (Scenario 5)
    inflightSplit,   \* [Tables -> 0..1] split past PRE_OPERATION (Scenario 4)
    inflightMerge,   \* [Tables -> Nat] width of a merge past PRE_MERGE, or 0 (Scenarios 2, 3)
    inflightRestore, \* [Tables -> manifest record] restore past prepareRestore (Scenario 3)
    pendingClone,    \* [Tables -> manifest record] clone admitted, not yet run (Scenario 5)
    \* ---- Oracle ----
    targetFired      \* The throw at NamespaceStateManager:130 executed

metaVars == <<tableState, online, parents, replication, snapManifest>>
inflightVars == <<inflightCreate, inflightSplit, inflightMerge, inflightRestore, pendingClone>>
vars == <<metaVars, cache, masterReady, inflightVars, targetFired>>

--------------------------------------------------------------------------------
\* Cache helpers, one per method of NamespaceTableAndRegionInfo.

RECURSIVE SumCache(_)
SumCache(ts) ==
    IF ts = {} THEN 0
    ELSE LET t == CHOOSE x \in ts : TRUE IN cache[t] + SumCache(ts \ {t})

\* NamespaceTableAndRegionInfo.getRegionCount, :64-70
CacheTotal == SumCache(DOMAIN cache)

\* NamespaceTableAndRegionInfo.getRegionCountOfTable, :72-78. The -1 sentinel is literal.
RegionCountOfTable(t) == IF t \in DOMAIN cache THEN cache[t] ELSE -1

\* NamespaceTableAndRegionInfo.removeTable, :96-98
CacheRemove(t) == [x \in DOMAIN cache \ {t} |-> cache[x]]

\* NamespaceTableAndRegionInfo.addTable, :84-94, after the removal the callers do first
CacheSet(t, n) ==
    [x \in DOMAIN cache \cup {t} |-> IF x = t THEN n ELSE cache[x]]

\* The table has a descriptor: getTableDescriptors().exists(t)
TableExists(t) == tableState[t] \in {"enabled", "disabled"}

\* HMaster.checkTableModifiable, master/HMaster:3038-3048: exists and DISABLED
TableModifiable(t) == tableState[t] = "disabled"

NoRegionProcedure(t) == inflightSplit[t] = 0 /\ inflightMerge[t] = 0

--------------------------------------------------------------------------------
(* Real-quota envelope (brief 3.1).

   The branch is reachable by design: testRestoreSnapshotQuotaExceed
   (TestNamespaceAuditor:708-747) expects this exception. A firing is informative only
   when the restore really fits, so MC.tla constrains the environment with this predicate.
   TargetCheck itself still evaluates the guard exactly as the code does.

   Reserved(t) is what table t really holds or has legitimately reserved:
   - a split's +1 before commit is the designed transient (NamespaceStateManager:93);
   - a create's reservation counts for the same reason;
   - a restore in flight counts as the larger of its old and new sizes, so a transient
     reservation of a growing restore never looks like drift. *)
Reserved(t) ==
    LET base0 == IF HasManifest(inflightRestore[t])
                 THEN IF inflightRestore[t].online > online[t]
                      THEN inflightRestore[t].online ELSE online[t]
                 ELSE online[t]
    IN base0 + inflightSplit[t] + inflightCreate[t]

RECURSIVE SumReserved(_)
SumReserved(ts) ==
    IF ts = {} THEN 0
    ELSE LET t == CHOOSE x \in ts : TRUE IN Reserved(t) + SumReserved(ts \ {t})

\* After this restore, the namespace would really hold no more than MaxRegions. Parents and
\* the MOB pseudo-region do not count: RestoreSnapshotHelper:212 removes the MOB region and
\* the rebuild filter (NamespaceStateManager:233) skips parents.
RealQuotaEnvelope(t, s) ==
    SumReserved(Tables \ {t}) + snapManifest[s].online <= MaxRegions

--------------------------------------------------------------------------------
(* TARGET: RestoreSnapshotProcedure.prepareRestore, master/procedure/RestoreSnapshotProcedure:350-389.

   prepareRestore runs at RESTORE_SNAPSHOT_PRE_OPERATION (:148-152). *)

\* Everything prepareRestore checks before it reads the counts.
RestoreReady(t, s) ==
    /\ masterReady                                 \* ProcedureSyncWait.getMasterQuotaManager waits, :261-270
    /\ HasManifest(snapManifest[s])
    /\ snapManifest[s].table = t                   \* restore targets the snapshot's own table, master/snapshot/SnapshotManager:1012-1014
    /\ TableExists(t)                              \* RestoreSnapshotProcedure:353
    /\ TableModifiable(t)                          \* RestoreSnapshotProcedure:366
    /\ ~HasManifest(inflightRestore[t])            \* master/snapshot/SnapshotManager:1094

\* RestoreSnapshotProcedure:384: the quota call happens only when this holds.
\* snapshotRegionCount = manifest size (:380), tableRegionCount = cached count or -1 (:381-382).
QuotaPathTaken(t, s) ==
    /\ ManifestSize(snapManifest[s]) > 0
    /\ RegionCountOfTable(t) /= ManifestSize(snapManifest[s])

\* The guard, NamespaceStateManager:126-128. regionCountOfTable (:125) is the sentinel if t
\* has no entry, and :127 uses it unchecked.
TargetGuard(t, incr) ==
    (CacheTotal - RegionCountOfTable(t) + incr) > MaxRegions

\* RestoreSnapshotProcedure:385 -> quotas/MasterQuotaManager:520-524 -> namespace/NamespaceAuditor:79-85
\* -> NamespaceStateManager.checkAndUpdateNamespaceRegionCount(TableName, int), :116-138
TargetCheck(t, s) ==
    /\ RestoreReady(t, s)
    /\ QuotaPathTaken(t, s)
    /\ LET incr == ManifestSize(snapManifest[s]) IN
       IF TargetGuard(t, incr)
       THEN \* throw new QuotaExceededException, NamespaceStateManager:130-133.
            \* The guard throws before any mutation, and rollback of this state does
            \* nothing (RestoreSnapshotProcedure:197-199).
            /\ targetFired' = TRUE
            /\ UNCHANGED <<metaVars, cache, masterReady, inflightVars>>
       ELSE \* removeTable, addTable: NamespaceStateManager:135-136
            /\ cache' = CacheSet(t, incr)
            /\ inflightRestore' = [inflightRestore EXCEPT ![t] = snapManifest[s]]
            /\ targetFired' = targetFired
            /\ UNCHANGED <<metaVars, masterReady, inflightCreate, inflightSplit,
                           inflightMerge, pendingClone>>

\* RestoreSnapshotProcedure:384 is false: the quota is not consulted and the cache is untouched.
PrepareRestoreSkipQuota(t, s) ==
    /\ RestoreReady(t, s)
    /\ ~QuotaPathTaken(t, s)
    /\ inflightRestore' = [inflightRestore EXCEPT ![t] = snapManifest[s]]
    /\ UNCHANGED <<metaVars, cache, masterReady, inflightCreate, inflightSplit,
                   inflightMerge, pendingClone, targetFired>>

\* RESTORE_SNAPSHOT_UPDATE_META, RestoreSnapshotProcedure:173-175 -> updateMETA :435-497.
\* No quota call: a master that rebuilt in between keeps the old count (Scenario 3).
\* Parents return to meta and to RegionStates (:463-466, :541-542).
\* The table stays disabled until the client enables it.
RestoreCommit(t) ==
    /\ HasManifest(inflightRestore[t])
    /\ online' = [online EXCEPT ![t] = inflightRestore[t].online]
    /\ parents' = [parents EXCEPT ![t] = inflightRestore[t].parents]
    /\ replication' = [replication EXCEPT ![t] = inflightRestore[t].replication]  \* :439, :396
    /\ inflightRestore' = [inflightRestore EXCEPT ![t] = NoManifest]
    /\ UNCHANGED <<tableState, snapManifest, cache, masterReady, inflightCreate,
                   inflightSplit, inflightMerge, pendingClone, targetFired>>

--------------------------------------------------------------------------------
(* Create. master/procedure/CreateTableProcedure.java. Scenario 5. *)

\* CREATE_TABLE_PRE_OPERATION, :94-105 -> preCreate :334-338 -> MasterQuotaManager:514-518
\* -> NamespaceAuditor.checkQuotaToCreateTable :61-71
\* -> NamespaceStateManager.checkAndUpdateNamespaceTableCount :149-181.
\* If :166 refuses the create, nothing changes and the rollback's removeTable (:180) finds no
\* entry, so that outcome is a stutter and has no action. KEY_MAX_TABLES is unset (:159).
CreatePrepare(t, n, r) ==
    /\ masterReady                              \* ProcedureSyncWait.getMasterQuotaManager waits
    /\ tableState[t] = "absent"                 \* prepareCreate; NamespaceAuditor:64
    /\ CacheTotal + n <= MaxRegions             \* NamespaceStateManager:165-167
    /\ cache' = CacheSet(t, n)                  \* NamespaceStateManager:180
    /\ tableState' = [tableState EXCEPT ![t] = "creating"]
    /\ inflightCreate' = [inflightCreate EXCEPT ![t] = n]
    /\ replication' = [replication EXCEPT ![t] = r]
    /\ UNCHANGED <<online, parents, snapManifest, masterReady, inflightSplit,
                   inflightMerge, inflightRestore, pendingClone, targetFired>>

\* CREATE_TABLE_WRITE_FS_LAYOUT through CREATE_TABLE_UPDATE_DESC_CACHE, :106-137. The descriptor
\* is written at :388 and meta at :123. Replicas are added only here (:407), and the cache holds
\* primaries only. No quota call, so a crash before this step leaves a live table with no entry.
\* The window between the descriptor and meta is merged: a rebuild inside it would count 0,
\* an undercount that moves the guard away from firing (brief 3.2).
CreateCommit(t) ==
    /\ tableState[t] = "creating"
    /\ tableState' = [tableState EXCEPT ![t] = "enabled"]
    /\ online' = [online EXCEPT ![t] = inflightCreate[t]]
    /\ inflightCreate' = [inflightCreate EXCEPT ![t] = 0]
    /\ UNCHANGED <<parents, replication, snapManifest, cache, masterReady, inflightSplit,
                   inflightMerge, inflightRestore, pendingClone, targetFired>>

--------------------------------------------------------------------------------
(* Enable, disable, delete, truncate *)

\* master/procedure/DisableTableProcedure:128. It takes the table's exclusive lock, and split
\* and merge hold a shared lock for their whole run (master/procedure/AbstractStateMachineRegionProcedure:82-84,
\* master/assignment/MergeTableRegionsProcedure:426-428), so it waits for them.
DisableTable(t) ==
    /\ masterReady
    /\ tableState[t] = "enabled"
    /\ NoRegionProcedure(t)
    /\ tableState' = [tableState EXCEPT ![t] = "disabled"]
    /\ UNCHANGED <<online, parents, replication, snapManifest, cache, masterReady,
                   inflightVars, targetFired>>

\* master/procedure/EnableTableProcedure:142. The restore holds the table until it commits.
EnableTable(t) ==
    /\ masterReady
    /\ tableState[t] = "disabled"
    /\ ~HasManifest(inflightRestore[t])
    /\ tableState' = [tableState EXCEPT ![t] = "enabled"]
    /\ UNCHANGED <<online, parents, replication, snapManifest, cache, masterReady,
                   inflightVars, targetFired>>

\* master/procedure/DeleteTableProcedure. Atomic (brief 3.2). The entry is removed at
\* postDelete :316 -> deleteTableStates :448-453. Removing a missing entry is a no-op
\* (NamespaceTableAndRegionInfo:97).
DeleteTable(t) ==
    /\ masterReady                              \* :451 waits for the quota manager
    /\ TableModifiable(t)                       \* prepareDelete :298
    /\ ~HasManifest(inflightRestore[t])
    /\ tableState' = [tableState EXCEPT ![t] = "absent"]
    /\ online' = [online EXCEPT ![t] = 0]
    /\ parents' = [parents EXCEPT ![t] = 0]
    /\ replication' = [replication EXCEPT ![t] = 0]
    /\ cache' = CacheRemove(t)
    /\ UNCHANGED <<snapManifest, masterReady, inflightVars, targetFired>>

\* master/procedure/TruncateTableProcedure, Scenario 2. The whole procedure never calls the quota manager.
\* preserve = TRUE keeps the non-parent regions (:89 and RegionStates:213-216 filter parents;
\* :132). preserve = FALSE replaces all regions with one (:128-130). Meta is cleared either way
\* (:137-140), so parents do not survive. The table ends enabled (:161).
TruncateTable(t, preserve) ==
    /\ masterReady
    /\ TableModifiable(t)                       \* prepareTruncate :321
    /\ ~HasManifest(inflightRestore[t])
    /\ online' = [online EXCEPT ![t] = IF preserve THEN @ ELSE 1]
    /\ parents' = [parents EXCEPT ![t] = 0]
    /\ tableState' = [tableState EXCEPT ![t] = "enabled"]
    /\ UNCHANGED <<replication, snapManifest, cache, masterReady, inflightVars, targetFired>>

--------------------------------------------------------------------------------
(* Split. master/assignment/SplitTableRegionProcedure.java. Scenario 4. *)

\* SPLIT_TABLE_REGION_PRE_OPERATION, :301-304 -> preSplitRegion :625 ->
\* MasterQuotaManager.onRegionSplit -> NamespaceAuditor.checkQuotaToSplitRegion :111-121 ->
\* NamespaceStateManager.checkAndUpdateNamespaceRegionCount(name, regionName, 1), :78-106.
\* - :90 refuses at the quota: the procedure fails with no change, so that is a stutter.
\* - No entry: :100 -> NamespaceTableAndRegionInfo:101 throws NullPointerException, which fails
\*   the procedure with no change (brief T-1), so that is a stutter too.
\* - A null quota manager skips the +1 (:624). That undercount is excluded (brief 3.2) by masterReady.
SplitPrepare(t) ==
    /\ masterReady
    /\ tableState[t] = "enabled"
    /\ inflightSplit[t] = 0
    \* The parent is a region no merge holds: per-region locks stay held for the whole procedure
    \* (master/procedure/AbstractStateMachineRegionProcedure:82-92, master/assignment/MergeTableRegionsProcedure:402-428),
    \* and a merge's parent then fails :551-565 before the +1.
    /\ online[t] > inflightMerge[t]
    /\ t \in DOMAIN cache
    /\ CacheTotal < MaxRegions                  \* NamespaceStateManager:88-90
    /\ cache' = [cache EXCEPT ![t] = @ + 1]     \* NamespaceStateManager:100
    /\ inflightSplit' = [inflightSplit EXCEPT ![t] = 1]
    /\ UNCHANGED <<metaVars, masterReady, inflightCreate, inflightMerge,
                   inflightRestore, pendingClone, targetFired>>

\* SPLIT_TABLE_REGION_UPDATE_META, :331-332 -> updateMeta :926-929. The parent stays in meta and in
\* RegionStates as an offline parent until the janitor cleans it, and two daughters replace it: +1.
SplitCommit(t) ==
    /\ inflightSplit[t] = 1
    /\ online' = [online EXCEPT ![t] = @ + 1]
    /\ parents' = [parents EXCEPT ![t] = @ + 1]
    /\ inflightSplit' = [inflightSplit EXCEPT ![t] = 0]
    /\ UNCHANGED <<tableState, replication, snapManifest, cache, masterReady, inflightCreate,
                   inflightMerge, inflightRestore, pendingClone, targetFired>>

\* A failure after the increment and before the point of no return: :306, :315, :320, :324, :328.
\* isRollbackSupported allows it (:419-431). Rollback of PRE_OPERATION only calls a coprocessor hook
\* (:396-398). The undo, MasterQuotaManager.onRegionSplitReverted :646, has no caller. The +1 stays.
SplitFailRollback(t) ==
    /\ inflightSplit[t] = 1
    /\ inflightSplit' = [inflightSplit EXCEPT ![t] = 0]
    /\ UNCHANGED <<metaVars, cache, masterReady, inflightCreate, inflightMerge,
                   inflightRestore, pendingClone, targetFired>>

--------------------------------------------------------------------------------
(* Merge. master/assignment/MergeTableRegionsProcedure.java. Scenarios 2, 3. *)

\* MERGE_TABLE_REGIONS_PRE_MERGE_OPERATION -> preMergeRegions :563 -> MasterQuotaManager.onRegionMerged
\* -> NamespaceAuditor.updateQuotaForRegionMerge :123-134, which applies a fixed -1 at :128-129,
\* whatever the width. :90 needs incr > 0, so it never refuses here. A missing entry is a
\* NullPointerException at NamespaceTableAndRegionInfo:101 and a stutter, as for split.
\* Merge rollback never restores the -1 (:295-297), an undercount left out by brief 3.2.
MergePrepare(t, n) ==
    /\ masterReady
    /\ tableState[t] = "enabled"
    /\ inflightMerge[t] = 0
    \* Every parent is free of a split: region locks as above, and :506 needs each one online.
    /\ online[t] - inflightSplit[t] >= n
    /\ t \in DOMAIN cache
    /\ cache' = [cache EXCEPT ![t] = @ - 1]
    /\ inflightMerge' = [inflightMerge EXCEPT ![t] = n]
    /\ UNCHANGED <<metaVars, masterReady, inflightCreate, inflightSplit,
                   inflightRestore, pendingClone, targetFired>>

\* MERGE_TABLE_REGIONS_UPDATE_META, :225-228. n parents become one region, with no cache delta.
\* AssignmentManager:2417 removes merge parents, so they never count as offline split parents.
MergeCommit(t) ==
    /\ inflightMerge[t] > 0
    /\ online' = [online EXCEPT ![t] = @ - (inflightMerge[t] - 1)]
    /\ inflightMerge' = [inflightMerge EXCEPT ![t] = 0]
    /\ UNCHANGED <<tableState, parents, replication, snapManifest, cache, masterReady,
                   inflightCreate, inflightSplit, inflightRestore, pendingClone, targetFired>>

--------------------------------------------------------------------------------
(* Snapshot and janitor. Scenario 1. *)

\* master/procedure/SnapshotProcedure, default path (master/snapshot/SnapshotManager:169). Atomic.
\* prepareSnapshot waits for this table's split and merge procedures (:228, :266-273).
\* Enabled table: online regions (:137) plus split parents (:140-141, :329-332).
\* Disabled table: every default replica, parents included (:144-145, :335-337).
\* Both read RegionStates through getTableRegions(table, false) (:340-343), so both give
\* online + parents. Replicas are filtered out (:342).
\* mob = 1: the MOB pseudo-region (:363-377). SnapshotManifest:337-341 skips it if the MOB
\* directory does not exist, so 0 is always possible.
TakeSnapshot(t, s, mob) ==
    /\ masterReady
    /\ TableExists(t)
    /\ NoRegionProcedure(t)
    /\ ~HasManifest(inflightRestore[t])         \* master/snapshot/SnapshotManager:1094 keeps them apart
    /\ ~HasManifest(snapManifest[s])            \* the snapshot name must be free
    /\ online[t] > 0
    /\ snapManifest' = [snapManifest EXCEPT
            ![s] = Manifest(t, online[t], parents[t], mob, replication[t])]
    /\ UNCHANGED <<tableState, online, parents, replication, cache, masterReady,
                   inflightVars, targetFired>>

\* master/snapshot/SnapshotManager.deleteSnapshot :357. The workload's last step.
DeleteSnapshot(s) ==
    /\ HasManifest(snapManifest[s])
    /\ snapManifest' = [snapManifest EXCEPT ![s] = NoManifest]
    /\ UNCHANGED <<tableState, online, parents, replication, cache, masterReady,
                   inflightVars, targetFired>>

\* master/janitor/CatalogJanitor.cleanParent :326-380. Deletes a parent; the cache never counted it.
JanitorClean(t) ==
    /\ masterReady
    /\ parents[t] > 0
    /\ parents' = [parents EXCEPT ![t] = @ - 1]
    /\ UNCHANGED <<tableState, online, replication, snapManifest, cache, masterReady,
                   inflightVars, targetFired>>

--------------------------------------------------------------------------------
(* Clone. master/procedure/CloneSnapshotProcedure.java. Scenario 5. *)

\* master/snapshot/SnapshotManager:1012-1017. Admission reads exists(t) with no table lock, so
\* it can pass while a create that has not yet written its descriptor holds the table.
\* cloneSnapshot :947-960 checks only snapshots and restores in progress on t.
CloneAdmit(t, s) ==
    /\ masterReady
    /\ HasManifest(snapManifest[s])
    /\ ~TableExists(t)
    /\ ~HasManifest(pendingClone[t])
    /\ pendingClone' = [pendingClone EXCEPT ![t] = snapManifest[s]]
    /\ UNCHANGED <<metaVars, cache, masterReady, inflightCreate, inflightSplit,
                   inflightMerge, inflightRestore, targetFired>>

\* The clone runs after the descriptor exists: prepareClone :392-393 throws TableExistsException,
\* :219-221 fails it, and rollback runs deleteTableStates unconditionally (:264-265 ->
\* DeleteTableProcedure:451). CreateTableProcedure:176-180 has an exception for this case and clone
\* has none. The entry of a live table is gone.
\* Why a "creating" table blocks the clone: a create keeps its exclusive lock from PRE_OPERATION to
\* the descriptor write, because the state machine re-executes in a loop while it holds the lock
\* (hbase-procedure ProcedureExecutor:1818-1929), and it first gives the lock up when it adds child
\* procedures (:128), after the descriptor exists. A failed FS step that suspends the create
\* (:155) could open that window; that outcome is not modeled.
CloneFailExists(t) ==
    /\ masterReady
    /\ HasManifest(pendingClone[t])
    /\ TableExists(t)
    /\ cache' = CacheRemove(t)
    /\ pendingClone' = [pendingClone EXCEPT ![t] = NoManifest]
    /\ UNCHANGED <<metaVars, masterReady, inflightCreate, inflightSplit,
                   inflightMerge, inflightRestore, targetFired>>

\* The clone runs with no competing table: preCloneSnapshot :411-423 adds the unfiltered manifest
\* size (:421-422), then the rest of the states run to an enabled table (:155-201). Atomic. Parents
\* go to RegionStates (:191-192). Parents and the MOB entry inflate the cache, as for restore (brief R-4).
CloneRun(t) ==
    /\ masterReady
    /\ HasManifest(pendingClone[t])
    /\ tableState[t] = "absent"
    /\ CacheTotal + ManifestSize(pendingClone[t]) <= MaxRegions   \* NamespaceStateManager:165-167
    /\ cache' = CacheSet(t, ManifestSize(pendingClone[t]))        \* NamespaceStateManager:180
    /\ tableState' = [tableState EXCEPT ![t] = "enabled"]
    /\ online' = [online EXCEPT ![t] = pendingClone[t].online]
    /\ parents' = [parents EXCEPT ![t] = pendingClone[t].parents]
    /\ replication' = [replication EXCEPT ![t] = pendingClone[t].replication]
    /\ pendingClone' = [pendingClone EXCEPT ![t] = NoManifest]
    /\ UNCHANGED <<snapManifest, masterReady, inflightCreate, inflightSplit,
                   inflightMerge, inflightRestore, targetFired>>

\* NamespaceStateManager:165-175 refuses the clone: :219-221 fails it, and the rollback's
\* removeTable finds no entry.
CloneQuotaReject(t) ==
    /\ masterReady
    /\ HasManifest(pendingClone[t])
    /\ tableState[t] = "absent"
    /\ CacheTotal + ManifestSize(pendingClone[t]) > MaxRegions
    /\ pendingClone' = [pendingClone EXCEPT ![t] = NoManifest]
    /\ UNCHANGED <<metaVars, cache, masterReady, inflightCreate, inflightSplit,
                   inflightMerge, inflightRestore, targetFired>>

--------------------------------------------------------------------------------
(* Master failover. Scenarios 3, 5. *)

\* The active master dies. The new master starts with an empty cache and has not published its
\* quota manager. Persistent procedures survive. The commit steps above have no masterReady guard:
\* they make no quota call, and they can land on either side of the rebuild. A resumed table
\* procedure waits for master/HMaster:1300 setInitialized (hbase-procedure Procedure:1021-1024,
\* master/procedure/AbstractStateMachineTableProcedure:89-90), which runs before the rebuild at :1335.
MasterCrash ==
    /\ masterReady
    /\ masterReady' = FALSE
    /\ cache' = [t \in {} |-> 0]
    /\ UNCHANGED <<metaVars, inflightVars, targetFired>>

\* MetaTableAccessor.getTableRegions(conn, t, true) at NamespaceStateManager:232-233 skips split
\* parents (MetaTableAccessor:375) and emits one entry per located replica
\* (hbase-client ClientMetaTableAccessor:485-488, CatalogFamilyFormat:183-197). Live paths count
\* primaries only.
\* The model counts replicas only for an enabled table. A closed replica keeps its old server column
\* (master/assignment/RegionStateStore:210-219), so a disabled table can also be over-counted, but
\* restore writes empty locations until the next enable. Under-approximating this loses no firing:
\* the table whose replicas inflate the total can stay enabled while another table is restored.
RebuiltCount(t) ==
    IF tableState[t] = "enabled" THEN online[t] * replication[t] ELSE online[t]

\* NamespaceStateManager.initialize :223-239, reached through master/HMaster:1335, :1621-1625.
\* listTableNamesByNamespace (master/HMaster:3758-3760) reads descriptors, so a create that has not
\* written one is missed and nothing adds its entry later (Scenario 5).
\* Atomic: commits on different tables commute, so a scan that interleaves per table can only
\* produce results this atomic scan also produces in some order.
RebuildScan ==
    /\ ~masterReady
    /\ masterReady' = TRUE
    /\ cache' = [t \in {x \in Tables : TableExists(x)} |-> RebuiltCount(t)]
    /\ UNCHANGED <<metaVars, inflightVars, targetFired>>

--------------------------------------------------------------------------------
Init ==
    /\ tableState = [t \in Tables |-> "absent"]
    /\ online = [t \in Tables |-> 0]
    /\ parents = [t \in Tables |-> 0]
    /\ replication = [t \in Tables |-> 0]
    /\ snapManifest = [s \in Snapshots |-> NoManifest]
    /\ cache = [t \in {} |-> 0]
    /\ masterReady = TRUE
    /\ inflightCreate = [t \in Tables |-> 0]
    /\ inflightSplit = [t \in Tables |-> 0]
    /\ inflightMerge = [t \in Tables |-> 0]
    /\ inflightRestore = [t \in Tables |-> NoManifest]
    /\ pendingClone = [t \in Tables |-> NoManifest]
    /\ targetFired = FALSE

\* Once the check has fired, everything stops: this keeps counterexamples short.
Next ==
    /\ ~targetFired
    /\ \/ \E t \in Tables, n \in CreateSizes, r \in Replications : CreatePrepare(t, n, r)
       \/ \E t \in Tables : CreateCommit(t)
       \/ \E t \in Tables : DisableTable(t) \/ EnableTable(t) \/ DeleteTable(t)
       \/ \E t \in Tables, p \in BOOLEAN : TruncateTable(t, p)
       \/ \E t \in Tables : SplitPrepare(t) \/ SplitCommit(t) \/ SplitFailRollback(t)
       \/ \E t \in Tables, n \in MergeWidths : MergePrepare(t, n)
       \/ \E t \in Tables : MergeCommit(t)
       \/ \E t \in Tables, s \in Snapshots, m \in MobChoices : TakeSnapshot(t, s, m)
       \/ \E s \in Snapshots : DeleteSnapshot(s)
       \/ \E t \in Tables : JanitorClean(t)
       \/ \E t \in Tables, s \in Snapshots : TargetCheck(t, s) \/ PrepareRestoreSkipQuota(t, s)
       \/ \E t \in Tables : RestoreCommit(t)
       \/ \E t \in Tables, s \in Snapshots : CloneAdmit(t, s)
       \/ \E t \in Tables : CloneFailExists(t) \/ CloneRun(t) \/ CloneQuotaReject(t)
       \/ MasterCrash
       \/ RebuildScan

Spec == Init /\ [][Next]_vars

--------------------------------------------------------------------------------
(* Properties *)

\* The oracle: the failing branch at NamespaceStateManager:130 is never taken.
TargetSafe == ~targetFired

\* Keeps base.cfg finite. Split and merge can cycle, so parents would otherwise grow without bound,
\* and with unlimited crashes a negative cache entry would let online grow without bound.
BaseStateBound ==
    \A t \in Tables : parents[t] <= MaxRegions /\ online[t] <= 2 * MaxRegions

ManifestOK(m) ==
    /\ m.online \in Nat /\ m.parents \in Nat /\ m.mob \in {0, 1} /\ m.replication \in Nat
    /\ m.table \in Tables \cup {"none"}

\* Structural sanity. A cache entry belongs to a live or in-flight table: no action can add an
\* entry for an absent table, and DeleteTable removes it.
TypeOK ==
    /\ tableState \in [Tables -> {"absent", "creating", "enabled", "disabled"}]
    /\ online \in [Tables -> Nat]
    /\ parents \in [Tables -> Nat]
    /\ replication \in [Tables -> Nat]
    /\ \A s \in Snapshots : ManifestOK(snapManifest[s])
    /\ DOMAIN cache \subseteq {t \in Tables : tableState[t] /= "absent"}
    \* Int, not Nat: merge's -1 has no floor (NamespaceTableAndRegionInfo:101), so an undercount
    \* left by a rebuild can go negative through later merges. TLC found this at base.cfg's bounds.
    /\ \A t \in DOMAIN cache : cache[t] \in Int
    /\ masterReady \in BOOLEAN
    /\ inflightCreate \in [Tables -> Nat]
    /\ inflightSplit \in [Tables -> 0..1]
    /\ inflightMerge \in [Tables -> Nat]
    /\ \A t \in Tables : ManifestOK(inflightRestore[t]) /\ ManifestOK(pendingClone[t])
    /\ targetFired \in BOOLEAN

================================================================================
