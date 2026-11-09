----------------------------------- MODULE MC -----------------------------------
(*
 * Model checking wrapper for hbase-adhoc-21.
 *
 * Each Scenario's mechanism sits behind its own counter. With every counter at 0 the model is
 * the fault-free baseline: normal operations stay enabled, and they include the accurate paths
 * of the same procedures (two-way merge, truncate with preserved splits, a snapshot with no
 * parents, replication 1).
 *
 * Normal client operations are not counted. The state space stays finite because the cache
 * refuses growth at MaxRegions and MCStateBound caps parents.
 *)
EXTENDS base

CONSTANTS
    MaxParentSnapshots,    \* Scenario 1: snapshots that capture split parents
    MaxMobSnapshots,       \* Scenario 1: snapshots with the MOB pseudo-region
    MaxLossyTruncates,     \* Scenario 2: truncate with preserveSplits = false that drops regions
    MaxWideMerges,         \* Scenario 2: merges of more than two regions
    MaxMasterCrashes,      \* Scenarios 3 and 5: active master failover
    MaxCrashesInCreate,    \* Scenario 5: of those, crashes while a create has no descriptor yet
    MaxReplicatedCreates,  \* Scenario 3: tables created with replication above 1
    MaxSplitFailures,      \* Scenario 4: split rollback after the +1
    MaxCloneRaces,         \* Scenario 5: clones admitted against a table name
    MaxParentsPerTable     \* State bound on offline parents; not a fault

VARIABLE faults

mcvars == <<vars, faults>>

\* Checked and incremented on the same transition.
Bump(k, cond) == faults' = IF cond THEN [faults EXCEPT ![k] = @ + 1] ELSE faults

\* ---- Scenario 1 ----
MCTakeSnapshot(t, s, mob) ==
    /\ parents[t] > 0 => faults.parentSnapshots < MaxParentSnapshots
    /\ mob = 1 => faults.mobSnapshots < MaxMobSnapshots
    /\ TakeSnapshot(t, s, mob)
    /\ faults' = [faults EXCEPT
           !.parentSnapshots = @ + (IF parents[t] > 0 THEN 1 ELSE 0),
           !.mobSnapshots = @ + mob]

\* ---- Scenario 2 ----
MCTruncateTable(t, preserve) ==
    LET lossy == ~preserve /\ online[t] > 1 IN
    /\ lossy => faults.lossyTruncates < MaxLossyTruncates
    /\ TruncateTable(t, preserve)
    /\ Bump("lossyTruncates", lossy)

MCMergePrepare(t, n) ==
    /\ n > 2 => faults.wideMerges < MaxWideMerges
    /\ MergePrepare(t, n)
    /\ Bump("wideMerges", n > 2)

\* ---- Scenario 3 ----
MCCreatePrepare(t, n, r) ==
    /\ r > 1 => faults.replicatedCreates < MaxReplicatedCreates
    /\ CreatePrepare(t, n, r)
    /\ Bump("replicatedCreates", r > 1)

\* A crash during a create is Scenario 5's mechanism, not Scenario 3's, so it has its own budget.
\* Without this, the Scenario 3 hunt returns the shorter Scenario 5 witness and stops.
MCMasterCrash ==
    LET inCreate == \E t \in Tables : tableState[t] = "creating" IN
    /\ faults.masterCrashes < MaxMasterCrashes
    /\ inCreate => faults.crashesInCreate < MaxCrashesInCreate
    /\ MasterCrash
    /\ faults' = [faults EXCEPT
           !.masterCrashes = @ + 1,
           !.crashesInCreate = @ + (IF inCreate THEN 1 ELSE 0)]

\* ---- Scenario 4 ----
MCSplitFailRollback(t) ==
    /\ faults.splitFailures < MaxSplitFailures
    /\ SplitFailRollback(t)
    /\ Bump("splitFailures", TRUE)

\* ---- Scenario 5 ----
MCCloneAdmit(t, s) ==
    /\ faults.cloneRaces < MaxCloneRaces
    /\ CloneAdmit(t, s)
    /\ Bump("cloneRaces", TRUE)

\* ---- Real-quota envelope (brief 3.1), on both exits of prepareRestore ----
MCTargetCheck(t, s) ==
    /\ HasManifest(snapManifest[s])
    /\ RealQuotaEnvelope(t, s)
    /\ TargetCheck(t, s)
    /\ UNCHANGED faults

MCPrepareRestoreSkipQuota(t, s) ==
    /\ HasManifest(snapManifest[s])
    /\ RealQuotaEnvelope(t, s)
    /\ PrepareRestoreSkipQuota(t, s)
    /\ UNCHANGED faults

MCInit ==
    /\ Init
    /\ faults = [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0,
                 wideMerges |-> 0, masterCrashes |-> 0, crashesInCreate |-> 0,
                 replicatedCreates |-> 0,
                 splitFailures |-> 0, cloneRaces |-> 0]

MCNext ==
    /\ ~targetFired
    /\ \/ \E t \in Tables, n \in CreateSizes, r \in Replications : MCCreatePrepare(t, n, r)
       \/ \E t \in Tables, p \in BOOLEAN : MCTruncateTable(t, p)
       \/ \E t \in Tables, n \in MergeWidths : MCMergePrepare(t, n)
       \/ \E t \in Tables, s \in Snapshots, m \in MobChoices : MCTakeSnapshot(t, s, m)
       \/ \E t \in Tables : MCSplitFailRollback(t)
       \/ \E t \in Tables, s \in Snapshots : MCCloneAdmit(t, s)
       \/ \E t \in Tables, s \in Snapshots :
              MCTargetCheck(t, s) \/ MCPrepareRestoreSkipQuota(t, s)
       \/ MCMasterCrash
       \/ /\ \/ \E t \in Tables : CreateCommit(t) \/ DisableTable(t) \/ EnableTable(t)
                                  \/ DeleteTable(t) \/ SplitPrepare(t) \/ SplitCommit(t)
                                  \/ MergeCommit(t) \/ JanitorClean(t) \/ RestoreCommit(t)
                                  \/ CloneFailExists(t) \/ CloneRun(t) \/ CloneQuotaReject(t)
             \/ \E s \in Snapshots : DeleteSnapshot(s)
             \/ RebuildScan
          /\ UNCHANGED faults

MCSpec == MCInit /\ [][MCNext]_mcvars

\* ---- State bound and symmetry ----
MCStateBound == \A t \in Tables : parents[t] <= MaxParentsPerTable

MCSymmetry == Permutations(Tables) \cup Permutations(Snapshots)

\* ---- Witness shaping (Phase 3): optional CONSTRAINTs for the MC_hunt_s*.cfg sub-path configs ----
\* They only remove behaviours, so a violation found under them is also a violation without them.
\* They separate one root cause from another and give counterexamples a sequential client.
BusyTables ==
    {t \in Tables : \/ inflightCreate[t] > 0 \/ inflightSplit[t] > 0 \/ inflightMerge[t] > 0
                    \/ HasManifest(inflightRestore[t]) \/ HasManifest(pendingClone[t])}

\* One table has a procedure in flight at a time; a clone and a create on one name still race.
MCSequentialClient == Cardinality(BusyTables) <= 1

\* The master is down only while nothing is in flight: the variant_failover trace's shape.
MCQuiescentCrash == ~masterReady => BusyTables = {}

\* The master is down with no merge in flight, which isolates the resumed restore.
MCCrashNoMerge == ~masterReady => \A t \in Tables : inflightMerge[t] = 0

\* The master is down with no restore in flight, which isolates the resumed merge.
MCCrashNoRestore == ~masterReady => \A t \in Tables : ~HasManifest(inflightRestore[t])

\* ---- Sanity invariants ----
FaultCountersZero == \A k \in DOMAIN faults : faults[k] = 0

\* MC.cfg only. Refines brief 5: MergePrepare applies its -1 before MergeCommit changes meta,
\* so a merge in flight is an accurate transient too. A live table also has an entry.
BaselineCacheAccurate ==
    FaultCountersZero =>
        /\ \A t \in Tables : TableExists(t) => t \in DOMAIN cache
        /\ \A t \in DOMAIN cache :
              (inflightCreate[t] = 0 /\ ~HasManifest(inflightRestore[t])) =>
                  cache[t] = online[t] + inflightSplit[t]
                             - (IF inflightMerge[t] > 0 THEN 1 ELSE 0)

\* Temporary check (adhoc tla-patterns.md, section 2), run only by MC_sanity_reached.cfg. TLC must
\* violate it: a model that never reaches TargetCheck proves nothing.
TargetReached ==
    ~ \E t \in Tables, s \in Snapshots :
        /\ HasManifest(snapManifest[s])
        /\ RestoreReady(t, s)
        /\ QuotaPathTaken(t, s)
        /\ RealQuotaEnvelope(t, s)

================================================================================
