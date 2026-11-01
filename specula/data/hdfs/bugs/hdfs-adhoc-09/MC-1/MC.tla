---------------------------------- MODULE MC ----------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-09).                    *)
(*                                                                         *)
(* Fault-injection actions are bounded by per-fault counters in `faults`;  *)
(* reactive steps (channel tasks, JN handlers, quorum resolution, JN       *)
(* restart, late delivery) are not bounded.  Scope constants keep each     *)
(* Scenario's hunt to its own mechanism:                                   *)
(*   S1  MaxReadFail, StandbyTail, InProgressTailing                       *)
(*   S2  LaunchModes = {"rollback"}; MaxPowerLoss with PowerLossAfterRewind*)
(*       (S2a); MaxWCrash + MaxLate with MaxPartition and                  *)
(*       PartitionInRollback (S2b)                                         *)
(*   S3  MaxWCrash, MaxJNCrash, MaxMsgLoss, MaxPurge (no rewind/read fault)*)
(* ZombieWriters = FALSE makes incarnations hand over sequentially.        *)
(* Every step is guarded by Live == ~targetFired, so a counterexample ends *)
(* at the TargetCheck step that throws.                                    *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxWCrash,     \* writer (NN process) crashes
    MaxJNCrash,    \* JN process crashes (page cache survives)
    MaxPowerLoss,  \* JN host power losses (unflushed committed-txid lost)
    MaxMsgLoss,    \* lost RPC requests or replies
    MaxPartition,  \* JN host network partitions (healed by a reactive step)
    MaxReadFail,   \* failed NN-side QJM reads (catch-up, openForWrite check) while a read
                   \*   quorum is up; reads with no quorum up fail without using this budget
    MaxLate,       \* RPCs left on the wire by a crashed writer
    MaxPurge,      \* purgeLogsOlderThan fan-outs
    StandbyTail,   \* TRUE: a standby NN tails edits before it fails over (Scenario 1)
    PowerLossAfterRewind, \* TRUE: power losses only after a successful discardSegments (S2a)
    PartitionInRollback,  \* TRUE: partitions start only while a rollback writer runs (S2b)
    ZombieWriters, \* TRUE: writer w may launch while writer w-1 is still alive (it is then
                   \*   fenced only by epochs); FALSE: w launches after w-1 died or closed
    MaxQueue       \* pruning: at most this many tasks queued on one channel

VARIABLE faults

mcVars == <<jn, wr, ch, targetFired, faults>>

NoFaults == [wcrash |-> 0, jncrash |-> 0, power |-> 0, loss |-> 0, part |-> 0,
             readfail |-> 0, late |-> 0, purge |-> 0]

MCInit == Init /\ faults = NoFaults

Live == ~targetFired

ReadQuorumUp == Cardinality({j \in JN : Reach(jn[j])}) >= Majority

\* ---- writer control flow (not bounded: driven by the NN / QJM program) ----
\* Pruning scope: without zombies an incarnation takes over only after its predecessor died
\* (crash, abort) or closed.
PredecessorGone(w) == IF w = 1 THEN TRUE ELSE wr[w - 1].ph = "dead"

MCLaunch(w)                 == Live /\ (ZombieWriters \/ PredecessorGone(w)) /\ Launch(w)
                               /\ UNCHANGED faults
MCDoTailEdits(w)            == Live /\ StandbyTail /\ DoTailEdits(w) /\ UNCHANGED faults
MCResolveGetJournalState(w) == Live /\ ResolveGetJournalState(w) /\ UNCHANGED faults
MCResolveNewEpoch(w)        == Live /\ ResolveNewEpoch(w) /\ UNCHANGED faults
MCResolvePrepareRecovery(w) == Live /\ ResolvePrepareRecovery(w) /\ UNCHANGED faults
MCResolveAcceptRecovery(w)  == Live /\ ResolveAcceptRecovery(w) /\ UNCHANGED faults
MCResolveRecoveryFinalize(w) == Live /\ ResolveRecoveryFinalize(w) /\ UNCHANGED faults
MCRollingRollbackDiscard(w) == Live /\ RollingRollbackDiscard(w) /\ UNCHANGED faults
MCResolveDiscardSegments(w) == Live /\ ResolveDiscardSegments(w) /\ UNCHANGED faults
MCResolveStartLogSegment(w) == Live /\ ResolveStartLogSegment(w) /\ UNCHANGED faults
MCSendEdits(w, n)           == Live /\ SendEdits(w, n) /\ UNCHANGED faults
MCResolveSendEdits(w)       == Live /\ ResolveSendEdits(w) /\ UNCHANGED faults
MCFinalizeLogSegment(w)     == Live /\ FinalizeLogSegment(w) /\ UNCHANGED faults
MCResolveFinalizeLogSegment(w) == Live /\ ResolveFinalizeLogSegment(w) /\ UNCHANGED faults
MCStartLogSegment(w)        == Live /\ StartLogSegment(w) /\ UNCHANGED faults
MCCloseWriter(w)            == Live /\ CloseWriter(w) /\ UNCHANGED faults

\* A failed read is a fault only while a read quorum is up; otherwise it is the only outcome.
ReadOutcome(ok) ==
    IF ok \/ ~ReadQuorumUp
    THEN UNCHANGED faults
    ELSE /\ faults.readfail < MaxReadFail
         /\ faults' = [faults EXCEPT !.readfail = @ + 1]

MCCatchupDuringFailover(w, ok) == Live /\ CatchupDuringFailover(w, ok) /\ ReadOutcome(ok)
MCOpenForWrite(w, ok)          == Live /\ OpenForWrite(w, ok) /\ ReadOutcome(ok)

MCPurgeLogsOlderThan(w) ==
    /\ Live
    /\ faults.purge < MaxPurge
    /\ PurgeLogsOlderThan(w)
    /\ faults' = [faults EXCEPT !.purge = @ + 1]

MCWriterCrash(w, keep) ==
    /\ Live
    /\ faults.wcrash < MaxWCrash
    /\ faults.late + Cardinality(keep) <= MaxLate
    /\ WriterCrash(w, keep)
    /\ faults' = [faults EXCEPT !.wcrash = @ + 1, !.late = @ + Cardinality(keep)]

\* ---- channel tasks and JN handlers (reactive) ----
MCChannelCall(w, j)      == Live /\ ChannelCall(w, j) /\ UNCHANGED faults
MCChannelHeartbeat(w, j) == Live /\ ChannelHeartbeat(w, j) /\ UNCHANGED faults
MCChannelSkip(w, j)      == Live /\ ChannelSkip(w, j) /\ UNCHANGED faults
MCChannelDown(w, j)      == Live /\ ChannelDown(w, j) /\ UNCHANGED faults
MCDeliverLate(w, j)      == Live /\ DeliverLate(w, j) /\ UNCHANGED faults

MCMsgLoss(w, j, lostReply) ==
    /\ Live
    /\ faults.loss < MaxMsgLoss
    /\ MsgLoss(w, j, lostReply)
    /\ faults' = [faults EXCEPT !.loss = @ + 1]

\* ---- JN process and host faults ----
MCJNCrash(j) ==
    /\ Live
    /\ faults.jncrash < MaxJNCrash
    /\ JNCrash(j)
    /\ faults' = [faults EXCEPT !.jncrash = @ + 1]

\* Hunt scope: with PowerLossAfterRewind, a power loss is explored only after some rollback
\* writer's discardSegments succeeded (the lowering S2(a) asks about).  A rollback writer's next
\* txid stays 1 until ResolveDiscardSegments sets it to ckpt + 1 (ckpt >= 1) and never shrinks.
RewindDone == \E w \in Writer : wr[w].mode = "rollback" /\ wr[w].next > wr[w].ckpt

MCPowerLoss(j) ==
    /\ Live
    /\ faults.power < MaxPowerLoss
    /\ (PowerLossAfterRewind => RewindDone)
    /\ PowerLoss(j)
    /\ faults' = [faults EXCEPT !.power = @ + 1]

\* Hunt scope: with PartitionInRollback, a partition starts only while a rollback writer is
\* running (S2(b) needs a JN to miss that writer's epoch-carrying RPCs).
RollbackRunning == \E w \in Writer : wr[w].mode = "rollback" /\ wr[w].ph \notin {"idle", "dead"}

MCPartition(j) ==
    /\ Live
    /\ faults.part < MaxPartition
    /\ (PartitionInRollback => RollbackRunning)
    /\ Partition(j)
    /\ faults' = [faults EXCEPT !.part = @ + 1]

MCHeal(j)      == Live /\ Heal(j) /\ UNCHANGED faults
MCJNRestart(j) == Live /\ JNRestart(j) /\ UNCHANGED faults

\* ctHist is read only by PowerLoss: without power losses it is not tracked (cfg: HistAdd <-
\* MCHistAdd), which merges states that differ only in it.
MCHistAdd(H, v) == IF MaxPowerLoss > 0 THEN H \cup {v} ELSE H

MCNext ==
    \/ \E w \in Writer :
         \/ MCLaunch(w)
         \/ MCDoTailEdits(w)
         \/ MCResolveGetJournalState(w)
         \/ MCResolveNewEpoch(w)
         \/ MCResolvePrepareRecovery(w)
         \/ MCResolveAcceptRecovery(w)
         \/ MCResolveRecoveryFinalize(w)
         \/ \E ok \in BOOLEAN : MCCatchupDuringFailover(w, ok)
         \/ MCRollingRollbackDiscard(w)
         \/ MCResolveDiscardSegments(w)
         \/ \E ok \in BOOLEAN : MCOpenForWrite(w, ok)
         \/ MCResolveStartLogSegment(w)
         \/ \E n \in 1..MaxBatch : MCSendEdits(w, n)
         \/ MCResolveSendEdits(w)
         \/ MCFinalizeLogSegment(w)
         \/ MCResolveFinalizeLogSegment(w)
         \/ MCStartLogSegment(w)
         \/ MCPurgeLogsOlderThan(w)
         \/ MCCloseWriter(w)
         \/ \E keep \in SUBSET JN : MCWriterCrash(w, keep)
    \/ \E w \in Writer, j \in JN :
         \/ MCChannelCall(w, j)
         \/ MCChannelHeartbeat(w, j)
         \/ MCChannelSkip(w, j)
         \/ MCChannelDown(w, j)
         \/ \E lr \in BOOLEAN : MCMsgLoss(w, j, lr)
         \/ MCDeliverLate(w, j)
    \/ \E j \in JN :
         \/ MCJNCrash(j)
         \/ MCJNRestart(j)
         \/ MCPowerLoss(j)
         \/ MCPartition(j)
         \/ MCHeal(j)

MCSpec == MCInit /\ [][MCNext]_mcVars

\* JournalNodes are interchangeable: identical initial state and every action is quantified
\* over JN.  Writers are not (incarnations launch in id order; writer 1 starts first).
JNSymmetry == Permutations(JN)

\* Pruning constraint: a channel lagging by more than MaxQueue tasks is not explored.
QueueBound == \A w \in Writer, j \in JN : Len(ch[w][j].q) <= MaxQueue

\* Counters stay within their bounds (sanity on the MC layer itself).
FaultsOK ==
    /\ faults.wcrash <= MaxWCrash /\ faults.jncrash <= MaxJNCrash
    /\ faults.power <= MaxPowerLoss /\ faults.loss <= MaxMsgLoss
    /\ faults.part <= MaxPartition
    /\ faults.readfail <= MaxReadFail /\ faults.late <= MaxLate
    /\ faults.purge <= MaxPurge
================================================================================
