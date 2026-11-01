--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-08).                    *)
(*                                                                         *)
(* Counter-bounded (they introduce nondeterminism the code does not        *)
(* control):                                                               *)
(*   LoseRequest  - an RPC never reaches its JN (MaxLoss)                   *)
(*   WriterStop   - NN crash / quorum timeout / close (MaxStops)           *)
(*   JNRestart    - JN process restart, cache reloaded lazily (MaxRestarts)*)
(*   Upgrade      - admin shared-log upgrade (MaxUpgrades)     Scenario 2  *)
(*   Rollback     - admin shared-log rollback (MaxRollbacks)   Scenario 2  *)
(*                                                                         *)
(* Not bounded (normal operation / reactive): writer start (bounded by     *)
(* MaxWriters itself), epoch choice, establish, recovery and write rounds, *)
(* QuorumFail (reaction to a failed quorum), JN handlers, reply delivery.  *)
(*                                                                         *)
(* Hunt scope (Phase 3): StopInNewEpoch = FALSE forbids WriterStop while a *)
(* writer waits for its newEpoch quorum (Scenario 1's trigger, MC-1).      *)
(*                                                                         *)
(* Each wrapper is a named action guarded by NotFired, so TLC labels       *)
(* counterexample steps with the wrapper name.                             *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxLoss,       \* LoseRequest firings
    MaxStops,      \* WriterStop firings (crash / timeout / close)
    MaxRestarts,   \* JNRestart firings
    MaxUpgrades,   \* Upgrade firings
    MaxRollbacks,  \* Rollback firings
    StopInNewEpoch \* hunt scope (Phase 3): may WriterStop hit a writer that is
                   \* waiting for its newEpoch quorum (wst = "ne")? FALSE takes
                   \* Scenario 1's trigger (a failed attempt leaving an orphan
                   \* promise, finding MC-1) out of a hunt, so that a hunt can
                   \* test another Scenario on its own. It only removes behaviors.

ASSUME /\ MaxLoss \in Nat /\ MaxStops \in Nat /\ MaxRestarts \in Nat
       /\ MaxUpgrades \in Nat /\ MaxRollbacks \in Nat
       /\ StopInNewEpoch \in BOOLEAN

VARIABLE faults

mcVars == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [loss |-> 0, stop |-> 0, restart |-> 0,
                 upgrade |-> 0, rollback |-> 0]

\* Ad hoc tla-patterns §1: nothing moves after the target fired.
NotFired == ~targetFired

-----------------------------------------------------------------------------
(* Counter-bounded fault / admin wrappers *)

MCLoseRequest(w, j) ==
    /\ NotFired
    /\ faults.loss < MaxLoss
    /\ LoseRequest(w, j)
    /\ faults' = [faults EXCEPT !.loss = @ + 1]

MCWriterStop(w) ==
    /\ NotFired
    /\ faults.stop < MaxStops
    /\ StopInNewEpoch \/ wst[w] # "ne"
    /\ WriterStop(w)
    /\ faults' = [faults EXCEPT !.stop = @ + 1]

\* A restart of a JN whose cache is not loaded changes nothing in the model;
\* skip it so it does not consume the budget.
MCJNRestart(j) ==
    /\ NotFired
    /\ faults.restart < MaxRestarts
    /\ cache[j] # NotLoaded
    /\ JNRestart(j)
    /\ faults' = [faults EXCEPT !.restart = @ + 1]

MCUpgrade(w) ==
    /\ NotFired
    /\ faults.upgrade < MaxUpgrades
    /\ Upgrade(w)
    /\ faults' = [faults EXCEPT !.upgrade = @ + 1]

MCRollback ==
    /\ NotFired
    /\ faults.rollback < MaxRollbacks
    /\ Rollback
    /\ faults' = [faults EXCEPT !.rollback = @ + 1]

-----------------------------------------------------------------------------
(* Unbounded writer actions *)

MCWriterStart(w)        == NotFired /\ WriterStart(w)        /\ UNCHANGED faults
MCChooseEpoch(w)        == NotFired /\ ChooseEpoch(w)        /\ UNCHANGED faults
MCEstablish(w)          == NotFired /\ Establish(w)          /\ UNCHANGED faults
MCAcceptRecovery(w)     == NotFired /\ AcceptRecovery(w)     /\ UNCHANGED faults
MCRecoveryNoLog(w)      == NotFired /\ RecoveryNoLog(w)      /\ UNCHANGED faults
MCRecoveryFinalize(w)   == NotFired /\ RecoveryFinalize(w)   /\ UNCHANGED faults
MCRecoveryDone(w)       == NotFired /\ RecoveryDone(w)       /\ UNCHANGED faults
MCStartLogSegment(w)    == NotFired /\ StartLogSegment(w)    /\ UNCHANGED faults
MCSendEdits(w)          == NotFired /\ SendEdits(w)          /\ UNCHANGED faults
MCFinalizeLogSegment(w) == NotFired /\ FinalizeLogSegment(w) /\ UNCHANGED faults
MCSegmentFinalized(w)   == NotFired /\ SegmentFinalized(w)   /\ UNCHANGED faults
MCQuorumFail(w)         == NotFired /\ QuorumFail(w)         /\ UNCHANGED faults

(* Unbounded JN handlers and reply delivery *)

MCHandleGetJournalState(j, w) == NotFired /\ HandleGetJournalState(j, w) /\ UNCHANGED faults
MCHandleNewEpoch(j, w)        == NotFired /\ HandleNewEpoch(j, w)        /\ UNCHANGED faults
MCTargetCheck(j, w)           == NotFired /\ TargetCheck(j, w)           /\ UNCHANGED faults
MCRecvReply(w, j)             == NotFired /\ RecvReply(w, j)             /\ UNCHANGED faults

-----------------------------------------------------------------------------

MCNext ==
    \/ \E w \in Writer :
          \/ MCWriterStart(w)
          \/ MCChooseEpoch(w)
          \/ MCEstablish(w)
          \/ MCAcceptRecovery(w)
          \/ MCRecoveryNoLog(w)
          \/ MCRecoveryFinalize(w)
          \/ MCRecoveryDone(w)
          \/ MCStartLogSegment(w)
          \/ MCSendEdits(w)
          \/ MCFinalizeLogSegment(w)
          \/ MCSegmentFinalized(w)
          \/ MCQuorumFail(w)
          \/ MCWriterStop(w)
          \/ MCUpgrade(w)
    \/ \E w \in Writer, j \in JN :
          \/ MCHandleGetJournalState(j, w)
          \/ MCHandleNewEpoch(j, w)
          \/ MCTargetCheck(j, w)
          \/ MCRecvReply(w, j)
          \/ MCLoseRequest(w, j)
    \/ \E j \in JN : MCJNRestart(j)
    \/ MCRollback

MCSpec == MCInit /\ [][MCNext]_mcVars

\* JournalNodes are interchangeable: nothing in base.tla orders or names them.
\* (Do not combine with liveness checking.)
Symmetry == Permutations(JN)

-----------------------------------------------------------------------------
(* Sanity (ad hoc tla-patterns §2) *)

\* TEMPORARY. "No JN is about to process a RequestInfo RPC", i.e. TargetCheck
\* is never enabled. TLC must VIOLATE this in MC.cfg; otherwise the model never
\* reaches the target and proves nothing.
TargetReached ==
    ~ \E w \in Writer, j \in JN :
        /\ HeadInFlight(w, j)
        /\ Head(chan[w][j]).kind \in RIKinds

=============================================================================
