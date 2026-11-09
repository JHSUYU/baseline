-------------------------------- MODULE MC --------------------------------
(***************************************************************************)
(* Model checking wrapper for base.tla (ad hoc target QP:1236).            *)
(*                                                                         *)
(* Only fault-injecting actions are counter-bounded. Start is deliberately *)
(* unbounded and is not a fault: a late Start is what creates the lagging  *)
(* learner of brief section 2. MaxEpoch and MaxTxnPerEpoch bound the rest. *)
(*                                                                         *)
(* No SYMMETRY: Elect breaks ties on the numeric sid (FLE:738-742), so     *)
(* permuting Server is not a symmetry of the spec.                         *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxCrash,           \* Scenario 1: process crashes
    MaxEpochWriteFail,  \* Scenario 2: IOExceptions out of the currentEpoch write
    MaxShutdown,        \* Scenario 3: graceful stops at any moment
    MaxWorkloadStop     \* sanity only: stops in the workload's quiescent order

VARIABLE faults

mcVars == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0]

(***************************************************************************)
(* Fault wrappers: guard, base action, counter increment.                  *)
(***************************************************************************)
MCCrash(n) ==
    /\ faults.crash < MaxCrash
    /\ Crash(n)
    /\ faults' = [faults EXCEPT !.crash = @ + 1]

MCEpochWriteFail(n) ==
    /\ faults.write < MaxEpochWriteFail
    /\ \/ EpochWriteFail(n)
       \/ EpochRenameFail(n)
    /\ faults' = [faults EXCEPT !.write = @ + 1]

MCShutdownBegin(n) ==
    /\ faults.shutdown < MaxShutdown
    /\ ShutdownBegin(n)
    /\ faults' = [faults EXCEPT !.shutdown = @ + 1]

\* A quiet stop of all servers, as in the workload (CurrentEpochWriteFailureTest.java:78,
\* 98): nobody is in a sync and nothing is in flight. The workload stops in sid order
\* (QuorumPeerTestBase.java:427-430), whatever the roles; here followers stop before the
\* leader, so no new election starts during the stop. That keeps the Scenario 3 race
\* out of this sanity run, not out of the system.
WorkloadQuiescent(n) ==
    /\ \A m \in Server :
        /\ running[m]
        /\ q[m] = <<>>
        /\ wrStep[m] = "Idle"
        /\ role[m] \in {"Down", "Looking", "Following", "Leading"}
        /\ role[m] = "Following" => lstep[m] = "Broadcast"
        /\ role[m] = "Leading" => lstate[m] = "Started"
    /\ role[n] /= "Following" => \A m \in Server : role[m] /= "Following"

MCWorkloadStop(n) ==
    /\ faults.workloadStop < MaxWorkloadStop
    /\ WorkloadQuiescent(n)
    /\ ShutdownBegin(n)
    /\ faults' = [faults EXCEPT !.workloadStop = @ + 1]

MCFaultStep ==
    \E n \in Server :
        \/ MCCrash(n)
        \/ MCEpochWriteFail(n)
        \/ MCShutdownBegin(n)
        \/ MCWorkloadStop(n)

MCNext ==
    /\ ~targetFired
    /\ \/ LoadStep /\ UNCHANGED faults
       \/ ProtocolStep /\ UNCHANGED <<targetFired, faults>>
       \/ MCFaultStep /\ UNCHANGED targetFired

MCSpec == MCInit /\ [][MCNext]_mcVars

(***************************************************************************)
(* Sanity probes (adhoc tla-patterns.md section 2). Each is the negation   *)
(* of a state that must be reachable, so TLC must report a violation.      *)
(* Never enable these in a hunt config.                                    *)
(***************************************************************************)
\* TargetCheck is enabled at all (Start of a Down peer)
TargetReached == ~\E n \in Server : ENABLED Start(n)

\* TargetCheck runs on a non-empty disk: a restart that really loads history
TargetReachedOnData == ~\E n \in Server : role[n] = "Down" /\ DiskZxid(n) > 0

\* The persist-before-epoch order is visible with no fault at all: a learner
\* holds durable data of an epoch newer than its currentEpoch file while the
\* tmp does not exist yet. A fault then decides whether a load can see this.
PersistWindowSeen ==
    ~\E f \in Server :
        /\ lstep[f] = "EpochWrite"
        /\ wrStep[f] = "ToOpen"
        /\ EpochOf(DiskZxid(f)) > curFile[f]

\* New-epoch data reached a learner inside the sync loop, before its epoch write
LateJoinSeen ==
    ~\E f \in Server :
        /\ role[f] = "Following"
        /\ lstep[f] = "SyncLoop"
        /\ pNotLogged[f] /= {} \/ memZxid[f] >= ZxidBase
        /\ newEpoch[f] > curFile[f]

\* Scenario 2 reload: a LOOKING participant must go back to disk
ReloadSeen == ~\E n \in Server : role[n] = "Looking" /\ running[n] /\ ~zkDbInit[n]

\* TRUNC needs a learner holding an uncommitted proposal; a crash can make one
TruncSeen == ~\E f \in Server : syncMode[f] = "TRUNC"

\* Expected to HOLD with every Scenario counter at 0: no load ever finds the
\* failing condition. Stronger than TargetSafe only in that it also rules out
\* the tmp-rescued variant of the same disk state.
NoDownPeerAhead ==
    \A n \in Server :
        role[n] = "Down" /\ curFile[n] /= NoFile =>
            EpochOf(DiskZxid(n)) <= curFile[n]

=============================================================================
