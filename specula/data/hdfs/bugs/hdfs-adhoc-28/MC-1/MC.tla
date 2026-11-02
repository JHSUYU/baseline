---------------------------------- MODULE MC ----------------------------------
(***************************************************************************)
(* Model checking wrapper for hdfs-adhoc-28 (BRW:565 null-BPOS check).     *)
(*                                                                         *)
(* Bounded (they introduce faults or operator actions):                    *)
(*   DnStop               DataNode shutdown, disk failure, fatal xceiver   *)
(*                        error (Scenario 1)                               *)
(*   RefreshNodesDisallow a DataNode removed from the NameNode's include   *)
(*                        list; its next heartbeat is rejected (Scenario 1)*)
(*   RefreshStartNew      refreshNamenodes re-homing the NameNode under    *)
(*                        nameservice ns1 (Scenario 2)                     *)
(* Not bounded (reactive): the rest of shutdown, refresh Steps 4-5, actor  *)
(* handshake / heartbeat / exit, command thread, recovery daemons, the     *)
(* NameNode's recovery attempts (bounded by MaxAttempts in base.tla).      *)
(*                                                                         *)
(* Every step has a named wrapper so TLC labels counterexample steps, and  *)
(* the stop-after-target rule is a CONSTRAINT, not a Next conjunct         *)
(* (modeling-brief.md Section 7).                                          *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxDnStops,               \* DnStop budget
    MaxNNRejects,             \* RefreshNodesDisallow budget
    MaxNsMoves,               \* RefreshStartNew budget
    RecoveryAfterRefresh,     \* Scenario 2 persistent variant: the NameNode
                              \* starts lease recovery only after every
                              \* started refresh finished and at least one
                              \* did (modeling-brief.md Scenario 2,
                              \* "Attribution")
    RefreshAfterRegistration  \* Scenario 2 persistent variant: the refresh
                              \* runs only once the old BPOS registered and
                              \* its actor is in offerService (the workload's
                              \* state after cluster.waitActive(), the
                              \* brief's reproduction plan); FALSE also lets
                              \* it race the old BPOS's startup handshake

ASSUME /\ MaxDnStops \in Nat /\ MaxNNRejects \in Nat /\ MaxNsMoves \in Nat
       /\ RecoveryAfterRefresh \in BOOLEAN
       /\ RefreshAfterRegistration \in BOOLEAN

VARIABLE fc     \* fault counters

mc_vars == <<vars, fc>>

----------------------------------------------------------------------------
\* Bounded wrappers

MCDnStop(d) ==
    /\ fc.dnStop < MaxDnStops
    /\ DnStop(d)
    /\ fc' = [fc EXCEPT !.dnStop = @ + 1]

MCRefreshNodesDisallow(d) ==
    /\ fc.nnReject < MaxNNRejects
    /\ RefreshNodesDisallow(d)
    /\ fc' = [fc EXCEPT !.nnReject = @ + 1]

MCRefreshStartNew(d) ==
    /\ fc.nsMove < MaxNsMoves
    /\ RefreshAfterRegistration =>
         /\ bpReg[<<d, 1>>]
         /\ actPc[<<d, 1>>] \in {"loop", "hb"}
    /\ RefreshStartNew(d)
    /\ fc' = [fc EXCEPT !.nsMove = @ + 1]

----------------------------------------------------------------------------
\* Reactive steps (unbounded), named so counterexamples keep their labels.

MCDnShutDownAll(d)       == DnShutDownAll(d)       /\ UNCHANGED fc
MCRefreshStopOld(d)      == RefreshStopOld(d)      /\ UNCHANGED fc
MCRefreshJoinOld(d)      == RefreshJoinOld(d)      /\ UNCHANGED fc
MCActorVersionRequest(b) == ActorVersionRequest(b) /\ UNCHANGED fc
MCActorVerifyNsInfo(b)   == ActorVerifyNsInfo(b)   /\ UNCHANGED fc
MCHsAddBlockPool(b)      == HsAddBlockPool(b)      /\ UNCHANGED fc
MCHsInitStorage(b)       == HsInitStorage(b)       /\ UNCHANGED fc
MCActorRegister(b)       == ActorRegister(b)       /\ UNCHANGED fc
MCActorLoop(b)           == ActorLoop(b)           /\ UNCHANGED fc
MCActorHeartbeat(b)      == ActorHeartbeat(b)      /\ UNCHANGED fc
MCActorCleanUp(b)        == ActorCleanUp(b)        /\ UNCHANGED fc
MCActorShutdownActor(b)  == ActorShutdownActor(b)  /\ UNCHANGED fc
MCActorExitRemove(b)     == ActorExitRemove(b)     /\ UNCHANGED fc
MCActorExitRelease(b)    == ActorExitRelease(b)    /\ UNCHANGED fc
MCCptLoop(b)             == CptLoop(b)             /\ UNCHANGED fc
MCCptTake(b)             == CptTake(b)             /\ UNCHANGED fc
MCCptOtherBatch(b)       == CptOtherBatch(b)       /\ UNCHANGED fc
MCCptInterrupted(b)      == CptInterrupted(b)      /\ UNCHANGED fc
MCCptAssert(b)           == CptAssert(b)           /\ UNCHANGED fc
MCCptRead(b)             == CptRead(b)             /\ UNCHANGED fc
MCCptDispatch(b)         == CptDispatch(b)         /\ UNCHANGED fc
MCRecStart(i)            == RecStart(i)            /\ UNCHANGED fc
MCTargetCheck(i)         == TargetCheck(i)         /\ UNCHANGED fc
MCRecRpc(i)              == RecRpc(i)              /\ UNCHANGED fc
MCRecPost(i)             == RecPost(i)             /\ UNCHANGED fc
MCRecActive(i)           == RecActive(i)           /\ UNCHANGED fc
MCRecCommit(i)           == RecCommit(i)           /\ UNCHANGED fc
MCNNRetryRecovery        == NNRetryRecovery        /\ UNCHANGED fc

\* With RecoveryAfterRefresh, any daemon is dispatched after the refresh,
\* so no daemon of the old BPOS exists and a TargetSafe violation can only
\* come from a live BPOS that lost its entry (Scenario 2's persistent
\* outcome), not from Scenario 1's transient teardown window.
MCNNStartRecovery ==
    /\ RecoveryAfterRefresh =>
         /\ \A d \in DN : refreshPc[d] \in {"idle", "done"}
         /\ \E d \in DN : refreshPc[d] = "done"
    /\ NNStartRecovery
    /\ UNCHANGED fc

----------------------------------------------------------------------------

MCInit ==
    /\ Init
    /\ fc = [dnStop |-> 0, nnReject |-> 0, nsMove |-> 0]

MCNext ==
    \/ \E d \in DN : MCDnStop(d)
    \/ \E d \in DN : MCDnShutDownAll(d)
    \/ \E d \in DN : MCRefreshNodesDisallow(d)
    \/ \E d \in DN : MCRefreshStartNew(d)
    \/ \E d \in DN : MCRefreshStopOld(d)
    \/ \E d \in DN : MCRefreshJoinOld(d)
    \/ \E b \in Bpos : MCActorVersionRequest(b)
    \/ \E b \in Bpos : MCActorVerifyNsInfo(b)
    \/ \E b \in Bpos : MCHsAddBlockPool(b)
    \/ \E b \in Bpos : MCHsInitStorage(b)
    \/ \E b \in Bpos : MCActorRegister(b)
    \/ \E b \in Bpos : MCActorLoop(b)
    \/ \E b \in Bpos : MCActorHeartbeat(b)
    \/ \E b \in Bpos : MCActorCleanUp(b)
    \/ \E b \in Bpos : MCActorShutdownActor(b)
    \/ \E b \in Bpos : MCActorExitRemove(b)
    \/ \E b \in Bpos : MCActorExitRelease(b)
    \/ \E b \in Bpos : MCCptLoop(b)
    \/ \E b \in Bpos : MCCptTake(b)
    \/ \E b \in Bpos : MCCptOtherBatch(b)
    \/ \E b \in Bpos : MCCptInterrupted(b)
    \/ \E b \in Bpos : MCCptAssert(b)
    \/ \E b \in Bpos : MCCptRead(b)
    \/ \E b \in Bpos : MCCptDispatch(b)
    \/ \E i \in Rec : MCRecStart(i)
    \/ \E i \in Rec : MCTargetCheck(i)
    \/ \E i \in Rec : MCRecRpc(i)
    \/ \E i \in Rec : MCRecPost(i)
    \/ \E i \in Rec : MCRecActive(i)
    \/ \E i \in Rec : MCRecCommit(i)
    \/ MCNNStartRecovery
    \/ MCNNRetryRecovery

MCSpec == MCInit /\ [][MCNext]_mc_vars

----------------------------------------------------------------------------
\* Symmetry: the DataNodes are interchangeable (Init, the NameNode's primary
\* choice and every action treat them alike).
Symm == Permutations(DN)

\* Stop exploring once the target fired (TLC still checks the invariants of
\* the first state that violates the constraint).
StopAfterTarget == ~targetFired

\* Sanity (adhoc tla-patterns Section 2): expected to be VIOLATED, which
\* shows that some explored state enables TargetCheck (a daemon is at L131).
TargetReached == ~(\E i \in Rec : rec[i].st = "check")

\* Counters stay within their bounds (structural).
CountersOK ==
    /\ fc.dnStop <= MaxDnStops
    /\ fc.nnReject <= MaxNNRejects
    /\ fc.nsMove <= MaxNsMoves

=============================================================================
