---- MODULE MC_TTrace_1794187164 ----
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC, MC_TEConstants

_expression ==
    LET MC_TEExpression == INSTANCE MC_TEExpression
    IN MC_TEExpression!expression
----

_trace ==
    LET MC_TETrace == INSTANCE MC_TETrace
    IN MC_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        replication = ((T1 :> 1 @@ T2 :> 2))
        /\
        cache = ((T1 :> 2 @@ T2 :> 2))
        /\
        snapManifest = ((S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]))
        /\
        targetFired = (TRUE)
        /\
        tableState = ((T1 :> "disabled" @@ T2 :> "enabled"))
        /\
        masterReady = (TRUE)
        /\
        faults = ([parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 1, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0])
        /\
        pendingClone = ((T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]))
        /\
        inflightCreate = ((T1 :> 0 @@ T2 :> 0))
        /\
        online = ((T1 :> 2 @@ T2 :> 1))
        /\
        inflightMerge = ((T1 :> 0 @@ T2 :> 0))
        /\
        inflightRestore = ((T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]))
        /\
        inflightSplit = ((T1 :> 0 @@ T2 :> 0))
        /\
        parents = ((T1 :> 0 @@ T2 :> 0))
    )
----

_init ==
    /\ tableState = _TETrace[1].tableState
    /\ targetFired = _TETrace[1].targetFired
    /\ faults = _TETrace[1].faults
    /\ inflightRestore = _TETrace[1].inflightRestore
    /\ parents = _TETrace[1].parents
    /\ inflightMerge = _TETrace[1].inflightMerge
    /\ masterReady = _TETrace[1].masterReady
    /\ online = _TETrace[1].online
    /\ pendingClone = _TETrace[1].pendingClone
    /\ inflightCreate = _TETrace[1].inflightCreate
    /\ snapManifest = _TETrace[1].snapManifest
    /\ inflightSplit = _TETrace[1].inflightSplit
    /\ replication = _TETrace[1].replication
    /\ cache = _TETrace[1].cache
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ tableState  = _TETrace[i].tableState
        /\ tableState' = _TETrace[j].tableState
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ inflightRestore  = _TETrace[i].inflightRestore
        /\ inflightRestore' = _TETrace[j].inflightRestore
        /\ parents  = _TETrace[i].parents
        /\ parents' = _TETrace[j].parents
        /\ inflightMerge  = _TETrace[i].inflightMerge
        /\ inflightMerge' = _TETrace[j].inflightMerge
        /\ masterReady  = _TETrace[i].masterReady
        /\ masterReady' = _TETrace[j].masterReady
        /\ online  = _TETrace[i].online
        /\ online' = _TETrace[j].online
        /\ pendingClone  = _TETrace[i].pendingClone
        /\ pendingClone' = _TETrace[j].pendingClone
        /\ inflightCreate  = _TETrace[i].inflightCreate
        /\ inflightCreate' = _TETrace[j].inflightCreate
        /\ snapManifest  = _TETrace[i].snapManifest
        /\ snapManifest' = _TETrace[j].snapManifest
        /\ inflightSplit  = _TETrace[i].inflightSplit
        /\ inflightSplit' = _TETrace[j].inflightSplit
        /\ replication  = _TETrace[i].replication
        /\ replication' = _TETrace[j].replication
        /\ cache  = _TETrace[i].cache
        /\ cache' = _TETrace[j].cache

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187164.json", _TETrace)

=============================================================================

 Note that you can extract this module `MC_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `MC_TEExpression.tla` file takes precedence 
  over the module `MC_TEExpression` below).

---- MODULE MC_TEExpression ----
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC, MC_TEConstants

expression == 
    [
        \* To hide variables of the `MC` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        tableState |-> tableState
        ,targetFired |-> targetFired
        ,faults |-> faults
        ,inflightRestore |-> inflightRestore
        ,parents |-> parents
        ,inflightMerge |-> inflightMerge
        ,masterReady |-> masterReady
        ,online |-> online
        ,pendingClone |-> pendingClone
        ,inflightCreate |-> inflightCreate
        ,snapManifest |-> snapManifest
        ,inflightSplit |-> inflightSplit
        ,replication |-> replication
        ,cache |-> cache
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_tableStateUnchanged |-> tableState = tableState'
        
        \* Format the `tableState` variable as Json value.
        \* ,_tableStateJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(tableState)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_tableStateModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].tableState # _TETrace[s-1].tableState
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE MC_TETrace ----
\*EXTENDS IOUtils, MC, TLC, MC_TEConstants
\*
\*trace == IODeserialize("MC_TTrace_1794187164.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC, MC_TEConstants

trace == 
    <<
    ([replication |-> (T1 :> 0 @@ T2 :> 0),cache |-> <<>>,snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "absent" @@ T2 :> "absent"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 0, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 0 @@ T2 :> 0),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 0),cache |-> (T1 :> 3),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "creating" @@ T2 :> "absent"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 0, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 3 @@ T2 :> 0),online |-> (T1 :> 0 @@ T2 :> 0),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 0),cache |-> (T1 :> 3),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "absent"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 0, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 3 @@ T2 :> 0),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 3 @@ T2 :> 1),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "creating"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 1),online |-> (T1 :> 3 @@ T2 :> 0),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 3 @@ T2 :> 1),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "creating"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 1),online |-> (T1 :> 3 @@ T2 :> 0),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 3 @@ T2 :> 1),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "enabled"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 3 @@ T2 :> 1),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 2 @@ T2 :> 1),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "enabled"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 3 @@ T2 :> 1),inflightMerge |-> (T1 :> 2 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 2 @@ T2 :> 1),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "enabled"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 0, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 2 @@ T2 :> 1),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> <<>>,snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "enabled"),masterReady |-> FALSE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 1, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 2 @@ T2 :> 1),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 2 @@ T2 :> 2),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "enabled" @@ T2 :> "enabled"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 1, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 2 @@ T2 :> 1),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 2 @@ T2 :> 2),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> FALSE,tableState |-> (T1 :> "disabled" @@ T2 :> "enabled"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 1, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 2 @@ T2 :> 1),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)]),
    ([replication |-> (T1 :> 1 @@ T2 :> 2),cache |-> (T1 :> 2 @@ T2 :> 2),snapManifest |-> (S1 :> [mob |-> 0, parents |-> 0, online |-> 3, table |-> T1, replication |-> 1] @@ S2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),targetFired |-> TRUE,tableState |-> (T1 :> "disabled" @@ T2 :> "enabled"),masterReady |-> TRUE,faults |-> [parentSnapshots |-> 0, mobSnapshots |-> 0, lossyTruncates |-> 0, wideMerges |-> 0, replicatedCreates |-> 1, masterCrashes |-> 1, crashesInCreate |-> 0, splitFailures |-> 0, cloneRaces |-> 0],pendingClone |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightCreate |-> (T1 :> 0 @@ T2 :> 0),online |-> (T1 :> 2 @@ T2 :> 1),inflightMerge |-> (T1 :> 0 @@ T2 :> 0),inflightRestore |-> (T1 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0] @@ T2 :> [mob |-> 0, parents |-> 0, online |-> 0, table |-> "none", replication |-> 0]),inflightSplit |-> (T1 :> 0 @@ T2 :> 0),parents |-> (T1 :> 0 @@ T2 :> 0)])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS T1, T2, S1, S2

=============================================================================

---- CONFIG MC_TTrace_1794187164 ----
CONSTANTS
    Tables = { T1 , T2 }
    Snapshots = { S1 , S2 }
    MaxRegions = 4
    CreateSizes = { 1 , 2 , 3 }
    Replications = { 1 , 2 }
    MergeWidths = { 2 }
    MobChoices = { 0 }
    MaxParentSnapshots = 0
    MaxMobSnapshots = 0
    MaxLossyTruncates = 0
    MaxWideMerges = 0
    MaxMasterCrashes = 1
    MaxCrashesInCreate = 0
    MaxReplicatedCreates = 1
    MaxSplitFailures = 0
    MaxCloneRaces = 0
    MaxParentsPerTable = 2
    T1 = T1
    S2 = S2
    S1 = S1
    T2 = T2

INVARIANT
    _inv

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Mon Nov 09 01:19:26 UTC 2026