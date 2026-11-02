--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for hdfs-adhoc-33 (spec-generation               *)
(* mc-spec-pattern.md, adhoc-coordination tla-patterns.md).                *)
(*                                                                         *)
(* Bounded (they introduce the nondeterminism, one counter per Scenario):  *)
(*   Scenario 1  OfferServiceRejected, CommandProcessorRejected  MaxNNReject*)
(*   Scenario 2  RefreshNamenodesRemove                          MaxNsRemove*)
(*   Scenario 3  DNShutdown, DNStopMonitorGate                   MaxDnStop  *)
(* Unbounded (reactive, or the workload itself): the reconfiguration and   *)
(* its workers, ActorExit (an actor noticing shouldRun() == false) and     *)
(* DNStopClearShouldRun (second half of a gated stop).                     *)
(*                                                                         *)
(* Each hunt cfg sets only its own Scenario's counter, so its              *)
(* counterexamples can only use that Scenario's trigger; ActorExit is the  *)
(* mechanism the three Scenarios share (modeling-brief section 2).         *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxNNReject,   \* Scenario 1 (MC-1): NameNode rejections
    MaxNsRemove,   \* Scenario 2 (MC-2): refreshNamenodes removals
    MaxDnStop      \* Scenario 3 (MC-3): DataNode stops (direct or monitor-gated)

VARIABLE faults    \* trigger counters

mcVars == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [nnReject |-> 0, nsRemove |-> 0, stop |-> 0]

(***************************************************************************)
(* Every step has its own named wrapper, so TLC names the steps of a       *)
(* counterexample.  Every wrapper stops once the check failed (adhoc       *)
(* tla-patterns 1).                                                        *)
(***************************************************************************)

\* --- Counter-bounded triggers: the counter is checked and incremented in the
\* --- same step.
MCOfferServiceRejected(b) ==
    /\ ~targetFired
    /\ faults.nnReject < MaxNNReject
    /\ OfferServiceRejected(b)
    /\ faults' = [faults EXCEPT !.nnReject = @ + 1]

MCCommandProcessorRejected(b) ==
    /\ ~targetFired
    /\ faults.nnReject < MaxNNReject
    /\ CommandProcessorRejected(b)
    /\ faults' = [faults EXCEPT !.nnReject = @ + 1]

MCRefreshNamenodesRemove(b) ==
    /\ ~targetFired
    /\ faults.nsRemove < MaxNsRemove
    /\ RefreshNamenodesRemove(b)
    /\ faults' = [faults EXCEPT !.nsRemove = @ + 1]

MCDNShutdown ==
    /\ ~targetFired
    /\ faults.stop < MaxDnStop
    /\ DNShutdown
    /\ faults' = [faults EXCEPT !.stop = @ + 1]

MCDNStopMonitorGate ==
    /\ ~targetFired
    /\ faults.stop < MaxDnStop
    /\ DNStopMonitorGate
    /\ faults' = [faults EXCEPT !.stop = @ + 1]

\* --- Unbounded steps: the workload and the reactions to a trigger.
MCRefreshVolumesSnapshot     == ~targetFired /\ RefreshVolumesSnapshot     /\ UNCHANGED faults
MCRefreshVolumesReadNsInfo   == ~targetFired /\ RefreshVolumesReadNsInfo   /\ UNCHANGED faults
MCRefreshVolumesSubmit       == ~targetFired /\ RefreshVolumesSubmit       /\ UNCHANGED faults
MCRefreshVolumesFinish       == ~targetFired /\ RefreshVolumesFinish       /\ UNCHANGED faults
MCLoadStorageDirectory(w)    == ~targetFired /\ LoadStorageDirectory(w)    /\ UNCHANGED faults
MCGetBlockPoolSliceStorage(w) == ~targetFired /\ GetBlockPoolSliceStorage(w) /\ UNCHANGED faults
MCAddBpStorageDirectories(w) == ~targetFired /\ AddBpStorageDirectories(w) /\ UNCHANGED faults
MCAddBlockPoolAndScan(w)     == ~targetFired /\ AddBlockPoolAndScan(w)     /\ UNCHANGED faults
MCTargetCheck(w)             == ~targetFired /\ TargetCheck(w)             /\ UNCHANGED faults
MCActivateVolume(w)          == ~targetFired /\ ActivateVolume(w)          /\ UNCHANGED faults
MCActorExit(b)               == ~targetFired /\ ActorExit(b)               /\ UNCHANGED faults
MCDNStopClearShouldRun       == ~targetFired /\ DNStopClearShouldRun       /\ UNCHANGED faults

\* Expected end states: the check failed, or the reconfiguration returned and no
\* reactive step is due.  With CHECK_DEADLOCK TRUE, TLC reports any other state
\* with no successor, which would be a modeling error.
Quiescent ==
    \/ targetFired
    \/ /\ rpc = "done"
       /\ \A b \in NS : bpos[b].alive => ActorShouldRun(b)
       /\ ~(dnStop = "gated" /\ dnRun)

MCQuiescent == Quiescent /\ UNCHANGED mcVars

MCNext ==
    \/ MCRefreshVolumesSnapshot
    \/ MCRefreshVolumesReadNsInfo
    \/ MCRefreshVolumesSubmit
    \/ MCRefreshVolumesFinish
    \/ \E w \in Vols : \/ MCLoadStorageDirectory(w)
                       \/ MCGetBlockPoolSliceStorage(w)
                       \/ MCAddBpStorageDirectories(w)
                       \/ MCAddBlockPoolAndScan(w)
                       \/ MCTargetCheck(w)
                       \/ MCActivateVolume(w)
    \/ \E b \in NS : \/ MCOfferServiceRejected(b)
                     \/ MCCommandProcessorRejected(b)
                     \/ MCRefreshNamenodesRemove(b)
                     \/ MCActorExit(b)
    \/ MCDNShutdown
    \/ MCDNStopMonitorGate
    \/ MCDNStopClearShouldRun
    \/ MCQuiescent

MCSpec == MCInit /\ [][MCNext]_mcVars

(***************************************************************************)
(* MC-level invariant and probes                                           *)
(***************************************************************************)
FaultsOK ==
    /\ faults.nnReject \in 0..MaxNNReject
    /\ faults.nsRemove \in 0..MaxNsRemove
    /\ faults.stop \in 0..MaxDnStop

\* Sanity (adhoc tla-patterns 2): some reachable state enables TargetCheck.
\* Must be VIOLATED with MC_sanity_reach.cfg.
TargetReached == ~(\E w \in Vols : wpc[w] = "build")

\* A worker is between the start of its prepare loop (DS:337) and build()
\* (FDI:559): the window, for every pool it already recorded.
InWindow == \E w \in Vols : wpc[w] \in {"get", "dirs", "scan", "build"}

\* Mechanism probes, one per hunt cfg; each must be VIOLATED with its
\* MC_probe_*.cfg (the hunt cfg with TargetSafe replaced, nothing else changed).
\* Each says: the Scenario's trigger fired and the actor's exit is still due
\* while a worker is in its window.  A violation shows that the hunt's fault
\* setup reaches the window; whether build() then fails is the hunt's question.
\* Scenario 1: the actor's own flag was cleared while the DataNode runs and the
\* nameservice is still configured, which only an NN rejection does.
ProbeS1 == ~(InWindow /\ \E b \in NS : /\ bpos[b].alive /\ ~bpos[b].svcRun
                                       /\ dnRun /\ b \in configured)
\* Scenario 2: refreshNamenodes stopped a nameservice that left the conf.
ProbeS2 == ~(InWindow /\ \E b \in NS : /\ bpos[b].alive /\ ~bpos[b].svcRun
                                       /\ b \notin configured)
\* Scenario 3: the DataNode cleared shouldRun and an actor has not exited yet.
ProbeS3 == ~(InWindow /\ ~dnRun /\ \E b \in NS : bpos[b].alive)
\* Scenario 3, monitor-gated stop paths only (RPC, upgrade, fatal disk error).
ProbeS3Gated == ~(InWindow /\ dnStop = "gated" /\ ~dnRun
                  /\ \E b \in NS : bpos[b].alive)

=============================================================================
