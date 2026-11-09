--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (solr-adhoc-k2).                     *)
(* The only action that introduces non-determinism from outside the        *)
(* system is the operator's CLUSTERPROP call (CH:237-252); it is bounded by *)
(* MaxPropChanges.  Every other step is reactive and unbounded.             *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxPropChanges,   \* bound on CLUSTERPROP legacyCloud calls (Scenario 1, 2)
    SplitReplicas     \* 0 or 1 extra replica per sub-shard (parent repFactor - 1)

VARIABLE propChanges

mcVars == <<vars, propChanges>>

----------------------------------------------------------------------------
(* Constants *)

MCNodes == {"n1", "n2"}

\* Scenario 1: SPLITSHARD of collection1/shard1, parent leader on n1
\* (OCP:1316-1320 sub-shard names; OCP:1461-1464 replica names).
SplitSpec ==
    [kind |-> "split", coll |-> "collection1", leaderNode |-> "n1",
     leaders  |-> << [core |-> "collection1_shard1_0_replica1", slice |-> "shard1_0"],
                     [core |-> "collection1_shard1_1_replica1", slice |-> "shard1_1"] >>,
     replicas |-> IF SplitReplicas = 0 THEN << >>
                  ELSE << [core |-> "collection1_shard1_0_replica2", slice |-> "shard1_0"],
                          [core |-> "collection1_shard1_1_replica2", slice |-> "shard1_1"] >>]

\* Scenario 2: CREATE collection c2 with numShards=1, replicationFactor=1
\* (OCP:2125-2131), placed on n2.
CCSpec ==
    [kind |-> "createcollection", coll |-> "c2",
     cores |-> << [core |-> "c2_shard1_replica1", slice |-> "shard1", node |-> "n2"] >>]

\* Scenario 2: ADDREPLICA to collection1/shard1 on n2; core name assigned
\* at OCP:2251-2266 (two existing replicas -> replica3).
ARSpec ==
    [kind |-> "addreplica", coll |-> "collection1", slice |-> "shard1",
     core |-> "collection1_shard1_replica3", node |-> "n2"]

MCOpSpec == [op \in {"split", "cc", "ar"} |->
                CASE op = "split" -> SplitSpec
                  [] op = "cc"    -> CCSpec
                  [] op = "ar"    -> ARSpec]

MCInitColls  == {"collection1"}
MCInitSlices == {<<"collection1", "shard1">>}

----------------------------------------------------------------------------
(* Bounded wrapper *)

MCClientSetClusterProp(v) ==
    /\ propChanges < MaxPropChanges
    /\ ClientSetClusterProp(v)
    /\ propChanges' = propChanges + 1

MCInit ==
    /\ Init
    /\ propChanges = 0

MCNext ==
    \/ /\ ~targetFired
       /\ SystemNext
       /\ UNCHANGED propChanges
    \/ /\ ~targetFired
       /\ \E v \in PropVals : MCClientSetClusterProp(v)
    \/ /\ Terminating
       /\ UNCHANGED propChanges

MCSpec == MCInit /\ [][MCNext]_mcVars

----------------------------------------------------------------------------
(* Invariants (re-exported for cfg) *)

MCTypeOK == TypeOK /\ propChanges \in 0..MaxPropChanges

\* Message-buffer pruning is unnecessary: every core gets at most one CREATE
\* and the state queue is bounded by the number of modeled cores + props.

=============================================================================
