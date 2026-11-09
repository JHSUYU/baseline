---------------------------------- MODULE Trace ----------------------------------
(*
 * Trace validation for hbase-adhoc-21 (Category A: one linear NDJSON trace).
 *
 * Each trace line is {"tag":"trace","ts":..,"event":{"name":..,"nid":..,"state":{..},"msg":{..}}}
 * (adhoc java-harness.md). The first line must be "Init" and gives msg.maxRegions.
 *
 * Every wrapper calls the base action directly, then checks the post-state fields that
 * instrumentation-spec.md says the harness captures. There are no silent actions: every state
 * change has its own event. The real-quota envelope lives in MC.tla and is not applied here,
 * because a trace records what the system did. Fault budgets also do not apply.
 *)
EXTENDS base, Json, IOUtils, Sequences

\* ---- Trace loading ----
JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x :
        /\ "tag" \in DOMAIN x
        /\ x.tag = "trace"
        /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 1
ASSUME TraceLog[1].event.name = "Init"

\* ---- Constants derived from the trace ----
TraceEvents == {TraceLog[k].event : k \in 1..Len(TraceLog)}

TraceTables == TLCEval({e.msg.table : e \in {x \in TraceEvents : "table" \in DOMAIN x.msg}})

TraceSnapshots == TLCEval({e.msg.snapshot : e \in {x \in TraceEvents : "snapshot" \in DOMAIN x.msg}})

TraceMaxRegions == TraceLog[1].event.msg.maxRegions

ASSUME TraceTables /= {}

\* ---- Cursor ----
VARIABLE l

logline == TraceLog[l]
Msg == logline.event.msg
St == logline.event.state

IsEvent(name) == l <= Len(TraceLog) /\ logline.event.name = name

Advance == l' = l + 1

\* ---- Post-state validation ----

\* The harness reads a creating table's state as "absent": meta has no table state until
\* setEnablingState (CreateTableProcedure:127), so the two model states look alike.
ObservedState(ts) == IF ts = "creating" THEN "absent" ELSE ts

RECURSIVE SumFn(_, _)
SumFn(f, ts) ==
    IF ts = {} THEN 0
    ELSE LET t == CHOOSE x \in ts : TRUE IN f[t] + SumFn(f, ts \ {t})

\* The whole partial function, including which tables have an entry. An entry's absence is
\* exactly what Scenario 5 needs to observe.
ValidateCache ==
    /\ DOMAIN cache' = DOMAIN St.cache
    /\ \A t \in DOMAIN cache' : cache'[t] = St.cache[t]
    /\ SumFn(cache', DOMAIN cache') = St.cacheTotal

ValidateTable(t) ==
    /\ online'[t] = St.online
    /\ parents'[t] = St.parents
    /\ ObservedState(tableState'[t]) = St.tableState

ValidatePostState(t) == ValidateCache /\ ValidateTable(t)

\* ---- Action wrappers ----

TraceCreatePrepare ==
    /\ IsEvent("CreatePrepare")
    /\ CreatePrepare(Msg.table, Msg.n, Msg.replication)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceCreateCommit ==
    /\ IsEvent("CreateCommit")
    /\ CreateCommit(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceDisableTable ==
    /\ IsEvent("DisableTable")
    /\ DisableTable(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceEnableTable ==
    /\ IsEvent("EnableTable")
    /\ EnableTable(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceDeleteTable ==
    /\ IsEvent("DeleteTable")
    /\ DeleteTable(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceTruncateTable ==
    /\ IsEvent("TruncateTable")
    /\ TruncateTable(Msg.table, Msg.preserve)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceSplitPrepare ==
    /\ IsEvent("SplitPrepare")
    /\ SplitPrepare(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceSplitCommit ==
    /\ IsEvent("SplitCommit")
    /\ SplitCommit(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceSplitFailRollback ==
    /\ IsEvent("SplitFailRollback")
    /\ SplitFailRollback(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceMergePrepare ==
    /\ IsEvent("MergePrepare")
    /\ MergePrepare(Msg.table, Msg.n)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceMergeCommit ==
    /\ IsEvent("MergeCommit")
    /\ MergeCommit(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceTakeSnapshot ==
    /\ IsEvent("TakeSnapshot")
    /\ TakeSnapshot(Msg.table, Msg.snapshot, Msg.mob)
    /\ snapManifest'[Msg.snapshot].online = Msg.online
    /\ snapManifest'[Msg.snapshot].parents = Msg.parents
    /\ snapManifest'[Msg.snapshot].replication = Msg.replication
    /\ ManifestSize(snapManifest'[Msg.snapshot]) = Msg.manifestSize
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceDeleteSnapshot ==
    /\ IsEvent("DeleteSnapshot")
    /\ DeleteSnapshot(Msg.snapshot)
    /\ ValidateCache
    /\ Advance

TraceJanitorClean ==
    /\ IsEvent("JanitorClean")
    /\ JanitorClean(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

\* The target. msg.incr and msg.tableRegionCount are read before the call at
\* RestoreSnapshotProcedure:385, and msg.fired records whether that call threw.
TraceTargetCheck ==
    /\ IsEvent("TargetCheck")
    /\ ManifestSize(snapManifest[Msg.snapshot]) = Msg.incr
    /\ RegionCountOfTable(Msg.table) = Msg.tableRegionCount
    /\ TargetCheck(Msg.table, Msg.snapshot)
    /\ targetFired' = Msg.fired
    /\ ValidatePostState(Msg.table)
    /\ Advance

TracePrepareRestoreSkipQuota ==
    /\ IsEvent("PrepareRestoreSkipQuota")
    /\ ManifestSize(snapManifest[Msg.snapshot]) = Msg.incr
    /\ RegionCountOfTable(Msg.table) = Msg.tableRegionCount
    /\ PrepareRestoreSkipQuota(Msg.table, Msg.snapshot)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceRestoreCommit ==
    /\ IsEvent("RestoreCommit")
    /\ RestoreCommit(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceCloneAdmit ==
    /\ IsEvent("CloneAdmit")
    /\ CloneAdmit(Msg.table, Msg.snapshot)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceCloneFailExists ==
    /\ IsEvent("CloneFailExists")
    /\ CloneFailExists(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceCloneRun ==
    /\ IsEvent("CloneRun")
    /\ CloneRun(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

TraceCloneQuotaReject ==
    /\ IsEvent("CloneQuotaReject")
    /\ CloneQuotaReject(Msg.table)
    /\ ValidatePostState(Msg.table)
    /\ Advance

\* The test emits this before it kills the master, so no post-crash state can be captured.
\* The base action empties the cache, and the next event validates that.
TraceMasterCrash ==
    /\ IsEvent("MasterCrash")
    /\ MasterCrash
    /\ Advance

TraceRebuildScan ==
    /\ IsEvent("RebuildScan")
    /\ RebuildScan
    /\ ValidateCache
    /\ Advance

\* ---- Spec ----
TraceInit == Init /\ l = 2

TraceNext ==
    \/ TraceCreatePrepare \/ TraceCreateCommit
    \/ TraceDisableTable \/ TraceEnableTable \/ TraceDeleteTable \/ TraceTruncateTable
    \/ TraceSplitPrepare \/ TraceSplitCommit \/ TraceSplitFailRollback
    \/ TraceMergePrepare \/ TraceMergeCommit
    \/ TraceTakeSnapshot \/ TraceDeleteSnapshot \/ TraceJanitorClean
    \/ TraceTargetCheck \/ TracePrepareRestoreSkipQuota \/ TraceRestoreCommit
    \/ TraceCloneAdmit \/ TraceCloneFailExists \/ TraceCloneRun \/ TraceCloneQuotaReject
    \/ TraceMasterCrash \/ TraceRebuildScan

\* Weak fairness makes the cursor advance whenever a wrapper is enabled. If no wrapper matches
\* line N, the behavior stutters there and TraceMatched is reported violated.
TraceSpec ==
    TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

\* Every line was consumed.
TraceMatched == <>(l > Len(TraceLog))

================================================================================
