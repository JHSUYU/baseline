-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-08), Category A: one linear   *)
(* NDJSON trace, cursor l.                                                 *)
(*                                                                         *)
(* Workload: TestQuorumJournalManager#testSingleWriter (3 JNs, spying QJM   *)
(* with DirectExecutorService, so the whole run is one total order). Up to *)
(* two variants in the same module (instrumentation-spec.md §3).           *)
(*                                                                         *)
(* Line format (instrumentation-spec.md §1):                               *)
(*   {"tag":"trace","ts":"<nanos>","event":{"name":N,"nid":ID,             *)
(*     "state":{...},"msg":{...}}}                                         *)
(*   writer events : nid "w<k>", msg.w = k, state.epoch = ALS epoch or -1   *)
(*   JN events     : nid "jn<i>", msg.w = k or -1, state.promise (cached   *)
(*                   lastPromisedEpoch after the handler), state.disk       *)
(*                   (current/last-promised-epoch file after the handler)  *)
(*                                                                         *)
(* Every event maps to exactly one base action; no silent actions.         *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, Naturals, FiniteSets, TLC

-----------------------------------------------------------------------------
(* Trace loading *)

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x :
          /\ "tag" \in DOMAIN x
          /\ x.tag = "trace"
          /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0

\* Events emitted on behalf of a writer (they all carry msg.w = k >= 1).
WriterEventNames ==
    {"GetJournalState", "NewEpoch", "Establish", "AcceptRecovery",
     "RecoveryNoLog", "FinalizeLogSegment", "RecoveryDone", "StartLogSegment",
     "SendEdits", "SegmentFinalized", "QuorumFail", "WriterStop", "Recv",
     "Upgrade"}

TraceWriterIds == TLCEval(
    { TraceLog[k].event.msg.w :
        k \in { i \in 1..Len(TraceLog) :
                  TraceLog[i].event.name \in WriterEventNames } })

\* Constant overrides (Trace.cfg): writer indices are 1..max index in the
\* trace; the number of startLogSegment fan-outs bounds the write rounds.
TraceMaxWriters ==
    IF TraceWriterIds = {} THEN 1 ELSE Max(TraceWriterIds)

TraceReqRounds == TLCEval(
    Cardinality({ i \in 1..Len(TraceLog) :
                    TraceLog[i].event.name = "StartLogSegment" }))

-----------------------------------------------------------------------------
(* Cursor *)

VARIABLE l

traceVars == <<l>>

logline == TraceLog[l]

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ logline.event.name = name

EvMsg   == logline.event.msg
EvState == logline.event.state
EvNid   == logline.event.nid

\* Writer index of a writer event.
EvW == EvMsg.w

\* JN events may not know the writer (-1); then any writer may match.
WriterMatches(w) == EvMsg.w \in {-1, w}

StepTrace == l' = l + 1

-----------------------------------------------------------------------------
(* Post-state validation *)

\* Writer events: the AsyncLoggerSet epoch after the step (ALS:61-68, -1 before
\* setEpoch). Captured from ALS.isEpochEstablished()/getEpoch().
ValidateWriter(w) ==
    wEpoch'[w] = EvState.epoch

\* JN events: the cached promise right after the handler (every handler calls
\* PersistentLongFile.get(), so the cache is loaded) and the on-disk value.
ValidateJN(j) ==
    /\ cache'[j] = EvState.promise
    /\ disk'[j]  = EvState.disk

-----------------------------------------------------------------------------
(* Writer (client) event wrappers *)

\* ALS.getJournalState fan-out (QJM:232-234).
WriterStartIfLogged ==
    /\ IsEvent("GetJournalState")
    /\ EvW \in Writer
    /\ WriterStart(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

\* ALS.newEpoch fan-out with myEpoch (QJM:242-244).
ChooseEpochIfLogged ==
    /\ IsEvent("NewEpoch")
    /\ EvW \in Writer
    /\ ChooseEpoch(EvW)
    /\ wCand'[EvW] = EvMsg.epoch
    /\ ValidateWriter(EvW)
    /\ StepTrace

\* QJM:485-495: epoch established (setEpoch done at QJM:247) and the recovery
\* decision taken.
EstablishIfLogged ==
    /\ IsEvent("Establish")
    /\ EvW \in Writer
    /\ Establish(EvW)
    /\ wEpoch'[EvW] = EvMsg.epoch
    /\ (wst'[EvW] = "pr") = EvMsg.recover
    /\ ValidateWriter(EvW)
    /\ StepTrace

AcceptRecoveryIfLogged ==
    /\ IsEvent("AcceptRecovery")
    /\ EvW \in Writer
    /\ AcceptRecovery(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

RecoveryNoLogIfLogged ==
    /\ IsEvent("RecoveryNoLog")
    /\ EvW \in Writer
    /\ RecoveryNoLog(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

\* ALS.finalizeLogSegment fan-out: from recoverUnclosedSegment (QJM:402-403,
\* msg.recovery = true) or from QJM.finalizeLogSegment (QJM:445-446).
FinalizeLogSegmentIfLogged ==
    /\ IsEvent("FinalizeLogSegment")
    /\ EvW \in Writer
    /\ IF EvMsg.recovery
         THEN RecoveryFinalize(EvW)
         ELSE FinalizeLogSegment(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

RecoveryDoneIfLogged ==
    /\ IsEvent("RecoveryDone")
    /\ EvW \in Writer
    /\ RecoveryDone(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

StartLogSegmentIfLogged ==
    /\ IsEvent("StartLogSegment")
    /\ EvW \in Writer
    /\ StartLogSegment(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

SendEditsIfLogged ==
    /\ IsEvent("SendEdits")
    /\ EvW \in Writer
    /\ SendEdits(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

SegmentFinalizedIfLogged ==
    /\ IsEvent("SegmentFinalized")
    /\ EvW \in Writer
    /\ SegmentFinalized(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

\* Phase 2.5: the harness captures state.epoch on every writer event, so it is
\* validated here too (QuorumFail leaves wEpoch unchanged).
QuorumFailIfLogged ==
    /\ IsEvent("QuorumFail")
    /\ EvW \in Writer
    /\ QuorumFail(EvW)
    /\ wst'[EvW] = "stopped"
    /\ ValidateWriter(EvW)
    /\ StepTrace

\* QJM.close (QJM:501-505). Closing a writer that already failed its quorum
\* (QuorumException in a test that catches it) has no protocol effect.
\* Phase 2.5: state.epoch is validated in both branches.
WriterStopIfLogged ==
    /\ IsEvent("WriterStop")
    /\ EvW \in Writer
    /\ IF wst[EvW] = "stopped"
         THEN UNCHANGED vars
         ELSE WriterStop(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

\* A QuorumCall completion for (writer, JN) (QC:78-88). With a JN-side event
\* before it, it is the reply of the handled request (RecvReply); without one,
\* the request never reached the JN (LoseRequest, e.g. futureThrows).
RecvIfLogged ==
    /\ IsEvent("Recv")
    /\ EvW \in Writer
    /\ EvMsg.j \in JN
    /\ LET w == EvW
           j == EvMsg.j
       IN /\ \/ /\ rep[w][j] # NoReply
                /\ rep[w][j].kind = EvMsg.kind
                /\ rep[w][j].ok = EvMsg.ok
                /\ EvMsg.ok => rep[w][j].val = EvMsg.val
                /\ RecvReply(w, j)
             \/ /\ ~EvMsg.ok
                /\ rep[w][j] = NoReply
                /\ chan[w][j] # <<>>
                /\ Head(chan[w][j]).kind = EvMsg.kind
                /\ LoseRequest(w, j)
          /\ ValidateWriter(w)
    /\ StepTrace

\* QJM.doPreUpgrade + QJM.doUpgrade completed (QJM:669-700).
UpgradeIfLogged ==
    /\ IsEvent("Upgrade")
    /\ EvW \in Writer
    /\ Upgrade(EvW)
    /\ ValidateWriter(EvW)
    /\ StepTrace

\* QJM.doRollback completed (QJM:754-769), issued by a non-writer QJM.
RollbackIfLogged ==
    /\ IsEvent("Rollback")
    /\ Rollback
    /\ StepTrace

-----------------------------------------------------------------------------
(* JournalNode event wrappers *)

\* JNRS:178-188.
HandleGetJournalStateIfLogged ==
    /\ IsEvent("HandleGetJournalState")
    /\ EvNid \in JN
    /\ \E w \in Writer :
         /\ WriterMatches(w)
         /\ HandleGetJournalState(EvNid, w)
         /\ rep'[w][EvNid].val = EvMsg.val
         /\ ValidateJN(EvNid)
    /\ StepTrace

\* J:339-365.
HandleNewEpochIfLogged ==
    /\ IsEvent("HandleNewEpoch")
    /\ EvNid \in JN
    /\ \E w \in Writer :
         /\ WriterMatches(w)
         /\ chan[w][EvNid] # <<>>
         /\ Head(chan[w][EvNid]).epoch = EvMsg.epoch
         /\ HandleNewEpoch(EvNid, w)
         /\ rep'[w][EvNid].ok = EvMsg.ok
         /\ EvMsg.ok => rep'[w][EvNid].val = EvMsg.seg
         /\ ValidateJN(EvNid)
    /\ StepTrace

\* J:484-512 at each RequestInfo call site (kind label), fired = the throw at
\* J:487-489 ran.
TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ EvNid \in JN
    /\ \E w \in Writer :
         /\ WriterMatches(w)
         /\ chan[w][EvNid] # <<>>
         /\ Head(chan[w][EvNid]).kind = EvMsg.kind
         /\ Head(chan[w][EvNid]).epoch = EvMsg.epoch
         /\ TargetCheck(EvNid, w)
         /\ targetFired' = EvMsg.fired
         /\ ValidateJN(EvNid)
    /\ StepTrace

\* MiniJournalCluster.restartJournalNode(i) returned (new JournalNode started).
JNRestartIfLogged ==
    /\ IsEvent("JNRestart")
    /\ EvNid \in JN
    /\ JNRestart(EvNid)
    /\ disk'[EvNid] = EvState.disk
    /\ StepTrace

-----------------------------------------------------------------------------
(* Specification *)

TraceInit ==
    /\ Init
    /\ l = 1

\* No ~targetFired guard here: a trace is replayed as recorded.
TraceNext ==
    \/ WriterStartIfLogged
    \/ ChooseEpochIfLogged
    \/ EstablishIfLogged
    \/ AcceptRecoveryIfLogged
    \/ RecoveryNoLogIfLogged
    \/ FinalizeLogSegmentIfLogged
    \/ RecoveryDoneIfLogged
    \/ StartLogSegmentIfLogged
    \/ SendEditsIfLogged
    \/ SegmentFinalizedIfLogged
    \/ QuorumFailIfLogged
    \/ WriterStopIfLogged
    \/ RecvIfLogged
    \/ UpgradeIfLogged
    \/ RollbackIfLogged
    \/ HandleGetJournalStateIfLogged
    \/ HandleNewEpochIfLogged
    \/ TargetCheckIfLogged
    \/ JNRestartIfLogged

TraceSpec ==
    TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l        |-> l,
      len      |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN logline.event.name ELSE "DONE",
      nid      |-> IF l <= Len(TraceLog) THEN logline.event.nid ELSE "DONE",
      tmsg     |-> IF l <= Len(TraceLog) THEN logline.event.msg ELSE "DONE",
      tstate   |-> IF l <= Len(TraceLog) THEN logline.event.state ELSE "DONE",
      cache    |-> cache,
      disk     |-> disk,
      wst      |-> wst,
      wEpoch   |-> wEpoch,
      wCand    |-> wCand,
      wResp    |-> wResp,
      chan     |-> chan,
      rep      |-> rep,
      fired    |-> targetFired ]

=============================================================================
