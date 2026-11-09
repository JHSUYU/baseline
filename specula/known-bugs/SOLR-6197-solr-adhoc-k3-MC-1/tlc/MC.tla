------------------------------- MODULE MC -------------------------------
\* Model-checking wrapper for solr-adhoc-k3 (target CoreAdminHandler.java:563).
\*
\* Bounds the two actions that inject non-determinism the workload does not
\* perform by itself:
\*   CollectionsHandlerHandleProp  -- a concurrent operator CLUSTERPROP
\*                                    (Scenario 3), at most MaxPropFlips times
\*   NodeCheckStateInZkTimeout     -- checkStateInZk's 3 s timeout
\*                                    (ZkController.java:1440-1451), at most
\*                                    MaxCheckTimeouts times
\* Every other action is reactive (handlers, queue consumer, polls) and is not
\* bounded.  The Scenario 1/2 precondition legacyCloud=false is a supported
\* configuration applied before the workload starts (InitLegacyCloud), not a
\* fault.

EXTENDS base

CONSTANT MaxPropFlips, MaxCheckTimeouts
ASSUME MaxPropFlips \in Nat /\ MaxCheckTimeouts \in Nat

VARIABLE faults     \* [propFlips |-> n, checkTimeouts |-> n]

mcVars == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [propFlips |-> 0, checkTimeouts |-> 0]

MCCollectionsHandlerHandleProp(v) ==
    /\ faults.propFlips < MaxPropFlips
    /\ CollectionsHandlerHandleProp(v)
    /\ faults' = [faults EXCEPT !.propFlips = @ + 1]

MCNodeCheckStateInZkTimeout(c) ==
    /\ faults.checkTimeouts < MaxCheckTimeouts
    /\ NodeCheckStateInZkTimeout(c)
    /\ faults' = [faults EXCEPT !.checkTimeouts = @ + 1]

MCNodeStep(c) ==
    \/ TargetCheck(c)
    \/ NodeCheckStateInZk(c)
    \/ NodePublishDown(c)
    \/ NodeWaitForShardId(c)

MCNext ==
    /\ ~targetFired
    /\ \/ /\ \/ OcpStep
             \/ \E c \in Cores : MCNodeStep(c)
             \/ ClusterStateUpdaterStep
             \/ OverseerWatchRefresh
          /\ UNCHANGED faults
       \/ \E c \in Cores : MCNodeCheckStateInZkTimeout(c)
       \/ \E v \in FlipValues : MCCollectionsHandlerHandleProp(v)

MCSpec == MCInit /\ [][MCNext]_mcVars

\* Fault counters are not part of the protocol state.
MCView == vars

\* --- Structural sanity ------------------------------------------------------
\* A message carries only values its sender held: every CREATE's coreNodeName
\* is the name the OCP read from a pre-registered replica.
MCTypeOK ==
    /\ TypeOK
    /\ faults.propFlips \in 0..MaxPropFlips
    /\ faults.checkTimeouts \in 0..MaxCheckTimeouts

\* Diagnostic: which sender's CREATE fired the target (used to attribute a
\* TargetSafe counterexample to its Scenario).
FiredBy == IF firedCore = NoCore THEN "none" ELSE Sender[firedCore]

\* Scenario attribution of a TargetSafe violation, for reports only.
\*   S1  migrateKey replica2 CREATE (never carries coreNodeName)
\*   S2  createShard CREATE         (never carries coreNodeName)
\*   S3  createCollection / addReplica CREATE sent without coreNodeName because
\*       the OCP's legacyCloud read (OCP:2111 / 2286) saw legacy mode
MCAlias == [clusterProps |-> clusterProps, cupLegacy |-> cupLegacy, stateQ |-> stateQ,
            cs |-> cs, ocpView |-> ocpView, ocp |-> ocp, opIdx |-> opIdx, req |-> req,
            nodeCores |-> nodeCores, targetFired |-> targetFired, firedCore |-> firedCore,
            firedBy |-> FiredBy, faults |-> faults]

=============================================================================
