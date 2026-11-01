-------------------------------- MODULE MC --------------------------------
(***************************************************************************)
(* Model checking wrapper for base.tla (hdfs-adhoc-10).                    *)
(*                                                                         *)
(* Counter-bounded (fault injection, one counter per Scenario mechanism):  *)
(*   lost   LoseRequest            S1 (LostOps = all), S3 (LostOps = {ne}) *)
(*   crash  Crash                  S2                                      *)
(*   wcrash WriterCrash            S3                                      *)
(*   late   TimeoutLate            S4                                      *)
(*   disk   StartPersistFail,      S5 (a/b)                                *)
(*          PowerLoss              S5 (c)                                  *)
(*                                                                         *)
(* Unbounded (deterministic or reactive): writer quorum steps, channel     *)
(* dispatch and completion, JN handlers, Restart (only after a Crash or    *)
(* PowerLoss), JNExecLate / DropLate (only after a TimeoutLate).           *)
(*                                                                         *)
(* Every wrapper is guarded by Live == ~targetFired, so a counterexample   *)
(* ends at the step that throws at Journal.java:518.                       *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxLost,    \* S1/S3: requests dropped before the JN runs them
    MaxCrash,   \* S2: JN process crashes
    MaxWCrash,  \* S3: writer (NameNode) crashes
    MaxLate,    \* S4: calls failed at the client but run later by the JN
    MaxDisk     \* S5: persistence faults on last-writer-epoch

VARIABLE faults

mcVars == <<vars, faults>>

Live == ~targetFired

\* ---------------------------------------------------------------------------
\* Counter-bounded fault wrappers
\* ---------------------------------------------------------------------------

MCLoseRequest(w, j) ==
    /\ Live /\ faults.lost < MaxLost
    /\ LoseRequest(w, j)
    /\ faults' = [faults EXCEPT !.lost = @ + 1]

MCCrash(j) ==
    /\ Live /\ faults.crash < MaxCrash
    /\ Crash(j)
    /\ faults' = [faults EXCEPT !.crash = @ + 1]

MCWriterCrash(w) ==
    /\ Live /\ faults.wcrash < MaxWCrash
    /\ WriterCrash(w)
    /\ faults' = [faults EXCEPT !.wcrash = @ + 1]

MCTimeoutLate(w, j) ==
    /\ Live /\ faults.late < MaxLate
    /\ TimeoutLate(w, j)
    /\ faults' = [faults EXCEPT !.late = @ + 1]

MCStartPersistFail(w, j) ==
    /\ Live /\ faults.disk < MaxDisk
    /\ StartPersistFail(w, j)
    /\ faults' = [faults EXCEPT !.disk = @ + 1]

MCPowerLoss(j) ==
    /\ Live /\ faults.disk < MaxDisk
    /\ PowerLoss(j)
    /\ faults' = [faults EXCEPT !.disk = @ + 1]

\* ---------------------------------------------------------------------------
\* Unbounded wrappers (named, so TLC labels counterexample steps)
\* ---------------------------------------------------------------------------

MCWriterBegin(w)          == Live /\ WriterBegin(w)          /\ UNCHANGED faults
MCWriterFanOut(w)         == Live /\ WriterFanOut(w)         /\ UNCHANGED faults
MCGotJournalState(w)      == Live /\ CreateNewUniqueEpoch_GotJournalState(w) /\ UNCHANGED faults
MCGotNewEpoch(w)          == Live /\ CreateNewUniqueEpoch_GotNewEpoch(w)     /\ UNCHANGED faults
MCGotPrepare(w)           == Live /\ RecoverUnclosedSegment_GotPrepare(w)    /\ UNCHANGED faults
MCGotAccept(w)            == Live /\ RecoverUnclosedSegment_GotAccept(w)     /\ UNCHANGED faults
MCGotStart(w)             == Live /\ StartLogSegment_GotQuorum(w)            /\ UNCHANGED faults
MCGotJournal(w)           == Live /\ FlushAndSync_GotQuorum(w)               /\ UNCHANGED faults
MCGotFinalize(w)          == Live /\ FinalizeLogSegment_GotQuorum(w)         /\ UNCHANGED faults
MCWriterQuorumFail(w)     == Live /\ WriterQuorumFail(w)     /\ UNCHANGED faults

MCChannelDispatch(w, j)      == Live /\ ChannelDispatch(w, j)      /\ UNCHANGED faults
MCChannelFailOutOfSync(w, j) == Live /\ ChannelFailOutOfSync(w, j) /\ UNCHANGED faults
MCCallFailed(w, j)           == Live /\ CallFailed(w, j)           /\ UNCHANGED faults
MCJNGetJournalState(w, j)    == Live /\ JNGetJournalState(w, j)    /\ UNCHANGED faults
MCJNNewEpoch(w, j)           == Live /\ JNNewEpoch(w, j)           /\ UNCHANGED faults
MCJNStartLogSegment(w, j)    == Live /\ JNStartLogSegment(w, j)    /\ UNCHANGED faults
MCTargetCheck(w, j)          == Live /\ TargetCheck(w, j)          /\ UNCHANGED faults
MCJNFinalizeLogSegment(w, j) == Live /\ JNFinalizeLogSegment(w, j) /\ UNCHANGED faults
MCJNPrepareRecovery(w, j)    == Live /\ JNPrepareRecovery(w, j)    /\ UNCHANGED faults
MCJNAcceptRecovery(w, j)     == Live /\ JNAcceptRecovery(w, j)     /\ UNCHANGED faults

MCRestart(j)    == Live /\ Restart(j)    /\ UNCHANGED faults
MCJNExecLate(j) == Live /\ JNExecLate(j) /\ UNCHANGED faults
MCDropLate(j)   == Live /\ DropLate(j)   /\ UNCHANGED faults

\* ---------------------------------------------------------------------------
\* Specification
\* ---------------------------------------------------------------------------

MCInit ==
    /\ Init
    /\ faults = [lost |-> 0, crash |-> 0, wcrash |-> 0, late |-> 0, disk |-> 0]

MCNext ==
    \/ \E w \in Writers :
         \/ MCWriterBegin(w)
         \/ MCWriterFanOut(w)
         \/ MCGotJournalState(w)
         \/ MCGotNewEpoch(w)
         \/ MCGotPrepare(w)
         \/ MCGotAccept(w)
         \/ MCGotStart(w)
         \/ MCGotJournal(w)
         \/ MCGotFinalize(w)
         \/ MCWriterQuorumFail(w)
         \/ MCWriterCrash(w)
    \/ \E w \in Writers, j \in JN :
         \/ MCChannelDispatch(w, j)
         \/ MCChannelFailOutOfSync(w, j)
         \/ MCCallFailed(w, j)
         \/ MCJNGetJournalState(w, j)
         \/ MCJNNewEpoch(w, j)
         \/ MCJNStartLogSegment(w, j)
         \/ MCTargetCheck(w, j)
         \/ MCJNFinalizeLogSegment(w, j)
         \/ MCJNPrepareRecovery(w, j)
         \/ MCJNAcceptRecovery(w, j)
         \/ MCLoseRequest(w, j)
         \/ MCTimeoutLate(w, j)
         \/ MCStartPersistFail(w, j)
    \/ \E j \in JN :
         \/ MCCrash(j)
         \/ MCRestart(j)
         \/ MCPowerLoss(j)
         \/ MCJNExecLate(j)
         \/ MCDropLate(j)

MCSpec == MCInit /\ [][MCNext]_mcVars

\* JournalNodes are interchangeable in the model.
Symmetry == Permutations(JN)

\* Fault counters stay within their bounds.
FaultsBounded ==
    /\ faults.lost <= MaxLost /\ faults.crash <= MaxCrash
    /\ faults.wcrash <= MaxWCrash /\ faults.late <= MaxLate
    /\ faults.disk <= MaxDisk

=============================================================================
