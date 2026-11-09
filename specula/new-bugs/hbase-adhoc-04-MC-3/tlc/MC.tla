--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model checking wrapper for base.tla (hbase-adhoc-04).                    *)
(*                                                                          *)
(* Each fault action of the base spec is bounded by its own counter         *)
(* (brief §4). Every other action reacts to existing state and is not       *)
(* bounded: handlers, worker poll/acquire/execute, child completion, master *)
(* startup and initialization.                                              *)
(*                                                                          *)
(*   counter     constant                  base actions            Scenario *)
(*   noEffect    MaxObsRpcFailNoEffect     ObsPutFail,             S1       *)
(*                                         ObsEnableTableFailNoEffect       *)
(*   lateEffect  MaxObsRpcFailLateEffect   ObsEnableTableFailLateEffect S2  *)
(*   crash       MaxMasterCrash            MasterCrash             S3       *)
(*                                                                          *)
(* MC.cfg sets every counter to 0 (the workload as written). Each           *)
(* MC_hunt_<scenario>.cfg sets only its Scenario's counter.                 *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxObsRpcFailNoEffect,     \* S1: an observer RPC fails without effect
    MaxObsRpcFailLateEffect,   \* S2: the observer's enable fails but takes effect
    MaxMasterCrash             \* S3: master crash and failover

ASSUME /\ MaxObsRpcFailNoEffect \in Nat
       /\ MaxObsRpcFailLateEffect \in Nat
       /\ MaxMasterCrash \in Nat

VARIABLE faults
faultVars == <<faults>>

MCInit ==
    /\ Init
    /\ faults = [noEffect |-> 0, lateEffect |-> 0, crash |-> 0]

-----------------------------------------------------------------------------
(* Counter-bounded faults                                                   *)
-----------------------------------------------------------------------------

\* S1: the Put at QuotaObserverChore.java:323 fails (control case: recovers)
MCObsPutFail ==
    /\ faults.noEffect < MaxObsRpcFailNoEffect
    /\ ObsPutFail
    /\ faults' = [faults EXCEPT !.noEffect = @ + 1]

\* S1: the enable at QuotaObserverChore.java:333 fails before E exists
MCObsEnableTableFailNoEffect ==
    /\ faults.noEffect < MaxObsRpcFailNoEffect
    /\ ObsEnableTableFailNoEffect
    /\ faults' = [faults EXCEPT !.noEffect = @ + 1]

\* S2: the enable reports failure; E is or will be submitted
MCObsEnableTableFailLateEffect ==
    /\ faults.lateEffect < MaxObsRpcFailLateEffect
    /\ ObsEnableTableFailLateEffect
    /\ faults' = [faults EXCEPT !.lateEffect = @ + 1]

\* S3: the master dies; MasterStartup/MasterFinishInit (unbounded) bring up the next
MCMasterCrash ==
    /\ faults.crash < MaxMasterCrash
    /\ MasterCrash
    /\ faults' = [faults EXCEPT !.crash = @ + 1]

MCFaultNext ==
    \/ MCObsPutFail
    \/ MCObsEnableTableFailNoEffect
    \/ MCObsEnableTableFailLateEffect
    \/ MCMasterCrash

-----------------------------------------------------------------------------
(* Next state                                                               *)
-----------------------------------------------------------------------------

MCNext ==
    \/ /\ ~targetFired
       /\ \/ SystemNext /\ UNCHANGED faultVars
          \/ MCFaultNext
    \/ Quiescent /\ UNCHANGED faultVars

MCSpec == MCInit /\ [][MCNext]_<<vars, faultVars>>

\* Worker threads are interchangeable (WorkerThread.run is the same loop for all).
Symmetry == Permutations(Workers)

=============================================================================
