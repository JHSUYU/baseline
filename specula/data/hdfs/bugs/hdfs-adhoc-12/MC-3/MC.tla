---------------------------------- MODULE MC ----------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-12).                    *)
(*                                                                         *)
(* Only actions that introduce non-determinism of the fault model are      *)
(* counter-bounded: safe-mode entry (Scenario 1), lost heartbeat replies   *)
(* (Scenarios 2 and 4), CPT stalls (Scenario 2 variant), dead-node rejoins *)
(* (Scenario 3a), NN restarts (Scenario 5) and DN restarts (Scenario 6).   *)
(* Which DNs a fault may hit is set by the base scope constants LossyDNs,  *)
(* StallDNs, DeadDNs, RestartDNs.  Transfers are bounded by the slot set   *)
(* XferIds, the clock by MaxTime (rotations follow from the clock).        *)
(* Reactive and normal-operation steps are not bounded.                    *)
(*                                                                         *)
(* Every wrapper is guarded by Live == ~targetFired, so a run stops at the *)
(* first firing (adhoc tla-patterns 1) and TLC labels each counterexample  *)
(* step with the wrapper's name.                                           *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxSafeModeEpisodes,   \* Scenario 1 (and 3b): manual safe-mode entries
    MaxLostResponses,      \* Scenarios 2, 4: lost heartbeat replies (at LossyDNs)
    MaxCPTStalls,          \* Scenario 2 variant: CPT stalls (at StallDNs)
    MaxDeadRejoins,        \* Scenario 3a: dead declarations (of DeadDNs)
    MaxNNRestarts,         \* Scenario 5
    MaxDNRestarts,         \* Scenario 6 (of RestartDNs)
    SafeModeMaxRotations,  \* hunt scope, Scenario 3b isolation: rotations allowed
                           \* inside one safe-mode episode (pruning only)
    HbInRotationGap,       \* realism guide: FALSE = no heartbeat is handled between a
                           \* rotation and its marking (pruning only)
    HbRaceIsolation        \* hunt scope, Scenario 3b isolation: TRUE = a rotation waits
                           \* until every pending push to a live DN is being exported
                           \* (pruning only)

ASSUME MaxNNRestarts < MaxEpoch
ASSUME HbInRotationGap \in BOOLEAN /\ HbRaceIsolation \in BOOLEAN

VARIABLE fc                \* fault counters

mcVars == <<vars, fc>>

FcInit == [sm |-> 0, smrot |-> 0, lost |-> 0, stall |-> 0, dead |-> 0, nnr |-> 0, dnr |-> 0]

MCInit == Init /\ fc = FcInit

Live == ~targetFired

-----------------------------------------------------------------------------
(* Normal operation and reactive steps: not bounded. *)

MCTick == Live /\ Tick /\ UNCHANGED fc

\* SafeModeMaxRotations only removes behaviors: a rotation due inside a safe-mode
\* episode that already had SafeModeMaxRotations rotations waits for the episode
\* to end (the clock waits with it, TickRealism).  Every cfg but
\* MC_hunt_hbrace.cfg sets it high enough never to bind.  fc.smrot counts the
\* rotations of the current episode; it is reset when an episode starts or ends.
\* HbRaceIsolation (MC_hunt_hbrace.cfg only) keeps Scenario 1's trigger out of
\* the Scenario 3b hunt: a DN whose push is still pending when the next
\* rotation comes lacks the new current key until that push lands, with no
\* erased mark at all.  With the guide, a rotation waits until every pending
\* push to a live DN is between its export (BM:1675) and its clear (BM:1676),
\* which is exactly the window Scenario 3b needs; MCTargetCheck holds the
\* other half (no check while a push to the verifier is in flight).  It only
\* removes behaviors.
MCRotate ==
    /\ Live
    /\ IF InSafeMode THEN fc.smrot < SafeModeMaxRotations ELSE TRUE
    /\ HbRaceIsolation =>
          \A d \in DN : (needKeyUpdate[d] /\ inHM[d]) => hbStage[d] = "exported"
    /\ Rotate
    /\ fc' = [fc EXCEPT !.smrot = IF InSafeMode THEN @ + 1 ELSE @]

MCMark == Live /\ Mark /\ UNCHANGED fc

\* HbInRotationGap = FALSE (the hunt cfgs) is a realism guide.  The Monitor runs
\* the rotation (HBM:552 -> BTSM:260-281) and the marking loop (HBM:553-557) as
\* consecutive statements, so a heartbeat handler reaching the flag check
\* (BM:1674) between them is a microsecond window.  Base.tla keeps the two
\* steps apart so that registrations (Scenario 3a) and in-progress heartbeat
\* handlers (Scenario 3b) can straddle them; the guide only stops a new
\* heartbeat from being handled in between.  It only removes behaviors.
MCHandleHeartbeat(d, c) ==
    Live /\ (HbInRotationGap \/ ~rotPending) /\ HandleHeartbeat(d, c) /\ UNCHANGED fc
MCHbClear(d, c)         == Live /\ HbClear(d, c) /\ UNCHANGED fc
MCDeliverResp(d)        == Live /\ DeliverResp(d) /\ UNCHANGED fc
MCProcessCommand(d)     == Live /\ ProcessCommand(d) /\ UNCHANGED fc

MCRegExport(d)    == Live /\ RegExport(d) /\ UNCHANGED fc
MCRegInsert(d)    == Live /\ RegInsert(d) /\ UNCHANGED fc
MCDnPublishReg(d) == Live /\ DnPublishReg(d) /\ UNCHANGED fc
MCDnCreateBTSM(d) == Live /\ DnCreateBTSM(d) /\ UNCHANGED fc
MCDnAddRegKeys(d) == Live /\ DnAddRegKeys(d) /\ UNCHANGED fc

MCScheduleTransfer(src, dst) == Live /\ ScheduleTransfer(src, dst) /\ UNCHANGED fc
MCClientOp                   == Live /\ ClientOp /\ UNCHANGED fc
MCMint(i)                    == Live /\ Mint(i) /\ UNCHANGED fc
\* HbRaceIsolation, second half: the check waits until no key push is in flight
\* or queued at the verifier.  With the MCRotate half, a verifier can then lack
\* the token's key only if a push was cleared without delivering that key:
\* in MC_hunt_hbrace.cfg (no losses, stalls, rejoins or restarts) only the
\* erased mark of Scenario 3b does that.  It only removes behaviors.
NoKeyPushAt(v) ==
    /\ hbStage[v] = "idle"
    /\ \A k \in 1..Len(cmdQ[v]) : ~IsKuc(cmdQ[v][k])

MCTargetCheck(v, i) ==
    /\ Live
    /\ HbRaceIsolation => NoKeyPushAt(v)
    /\ TargetCheck(v, i)
    /\ UNCHANGED fc

MCUnstallCPT(d)  == Live /\ UnstallCPT(d) /\ UNCHANGED fc
MCLeaveSafeMode  == Live /\ LeaveSafeMode /\ fc' = [fc EXCEPT !.smrot = 0]

-----------------------------------------------------------------------------
(* Fault and environment steps: bounded, counter checked and incremented   *)
(* on the same transition.                                                 *)

MCEnterSafeMode ==
    /\ Live
    /\ fc.sm < MaxSafeModeEpisodes
    /\ EnterSafeMode
    /\ fc' = [fc EXCEPT !.sm = @ + 1, !.smrot = 0]

MCLoseResp(d) ==
    /\ Live
    /\ fc.lost < MaxLostResponses
    /\ LoseResp(d)
    /\ fc' = [fc EXCEPT !.lost = @ + 1]

MCStallCPT(d) ==
    /\ Live
    /\ fc.stall < MaxCPTStalls
    /\ StallCPT(d)
    /\ fc' = [fc EXCEPT !.stall = @ + 1]

MCDeclareDead(d) ==
    /\ Live
    /\ fc.dead < MaxDeadRejoins
    /\ DeclareDead(d)
    /\ fc' = [fc EXCEPT !.dead = @ + 1]

MCNNRestart ==
    /\ Live
    /\ fc.nnr < MaxNNRestarts
    /\ NNRestart
    /\ fc' = [fc EXCEPT !.nnr = @ + 1, !.smrot = 0]

MCDNRestart(d) ==
    /\ Live
    /\ fc.dnr < MaxDNRestarts
    /\ DNRestart(d)
    /\ fc' = [fc EXCEPT !.dnr = @ + 1]

-----------------------------------------------------------------------------
(* Workload-test actions (TestRotate, TestMark, TestRecvResp,              *)
(* TestProcessCmd, TestTransfer, the "test" heartbeat channel) are not part *)
(* of MCNext: they are test-only mutators used for trace validation.       *)

MCNext ==
    \/ MCTick
    \/ MCRotate
    \/ MCMark
    \/ \E d \in DN :
          \/ MCHandleHeartbeat(d, "actor")
          \/ MCHbClear(d, "actor")
          \/ MCDeliverResp(d)
          \/ MCProcessCommand(d)
          \/ MCRegExport(d)
          \/ MCRegInsert(d)
          \/ MCDnPublishReg(d)
          \/ MCDnCreateBTSM(d)
          \/ MCDnAddRegKeys(d)
          \/ MCUnstallCPT(d)
          \/ MCLoseResp(d)
          \/ MCStallCPT(d)
          \/ MCDeclareDead(d)
          \/ MCDNRestart(d)
    \/ \E src \in DN, dst \in DN : MCScheduleTransfer(src, dst)
    \/ MCClientOp
    \/ \E i \in XferIds : MCMint(i)
    \/ \E v \in DN, i \in XferIds : MCTargetCheck(v, i)
    \/ MCLeaveSafeMode
    \/ MCEnterSafeMode
    \/ MCNNRestart

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(* Structural sanity on the counters. *)
MCTypeOK ==
    /\ TypeOK
    /\ fc.sm \in 0..MaxSafeModeEpisodes
    /\ fc.lost \in 0..MaxLostResponses
    /\ fc.stall \in 0..MaxCPTStalls
    /\ fc.dead \in 0..MaxDeadRejoins
    /\ fc.nnr \in 0..MaxNNRestarts
    /\ fc.dnr \in 0..MaxDNRestarts
    /\ fc.smrot \in Nat

=============================================================================
