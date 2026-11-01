------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-10), Category A: one linear   *)
(* NDJSON trace, cursor l. Every wrapper matches one event, calls the base *)
(* action, validates the post-state against the fields the event carries   *)
(* (instrumentation-spec.md), and advances l.                              *)
(*                                                                         *)
(* The workload (TestQuorumJournalManager#testSingleWriter) runs every     *)
(* channel on a DirectExecutorService (SpyQJournalUtil L51-69), so the     *)
(* trace is one total order: Dispatch(jn0), JNExec(jn0), Dispatch(jn1), ...*)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

\* ---------------------------------------------------------------------------
\* Trace loading
\* ---------------------------------------------------------------------------

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

\* Lines tagged "trace" only; anything else the harness writes is ignored.
TraceLog == TLCEval(
    SelectSeq(ndJsonDeserialize(JsonFile),
              LAMBDA x : "tag" \in DOMAIN x /\ x.tag = "trace"))

ASSUME Len(TraceLog) > 0

\* Every JournalNode id in the trace is one of the configured JN values.
TraceJN == TLCEval({TraceLog[k].jn : k \in {i \in 1..Len(TraceLog) :
                                                "jn" \in DOMAIN TraceLog[i]}})
ASSUME TraceJN \subseteq JN

\* Every writer id in the trace is a configured writer.
TraceW == TLCEval({TraceLog[k].w : k \in {i \in 1..Len(TraceLog) :
                                              "w" \in DOMAIN TraceLog[i]}})
ASSUME TraceW \subseteq Writers

\* ---------------------------------------------------------------------------
\* Cursor
\* ---------------------------------------------------------------------------

VARIABLE l

traceVars == <<vars, l>>

logline == TraceLog[l]

IsEvent(e) == l <= Len(TraceLog) /\ logline.event = e

Step == l' = l + 1

\* ---------------------------------------------------------------------------
\* Field checks
\* ---------------------------------------------------------------------------

\* FanOut: the op the model's writer decided matches the code's fan-out.
OpArgsOK(o, e) ==
    /\ o.op = e.op
    /\ CASE e.op = "gjs"                         -> TRUE
         [] e.op \in {"ne", "start", "prepare"}  -> o.a1 = e.a1
         [] e.op \in {"finalize", "accept"}      -> o.a1 = e.a1 /\ o.a2 = e.a2
         [] e.op = "journal"                     -> o.a1 = e.a1 /\ o.a2 = e.a2
                                                    /\ o.a3 = e.a3

\* The request the event names: RequestInfo epoch and serial (or the newEpoch
\* argument) identify it.
ReqMatches(r, e) ==
    /\ r.op = e.op
    /\ (e.op \in ReqInfoOps) => (r.epoch = e.epoch /\ r.serial = e.serial)
    /\ (e.op = "ne") => r.a1 = e.epoch

\* JN state after the handler (Journal fields read by the harness).
ValidateJN(j) ==
    LET s == logline.state IN
    /\ jn'[j].promised  = s.promised    \* lastPromisedEpoch.get()
    /\ jn'[j].lwMem     = s.lwe         \* lastWriterEpoch.get()
    /\ jn'[j].serial    = s.ipcSerial   \* currentEpochIpcSerial
    /\ jn'[j].curSeg    = s.curSeg      \* curSegmentTxId
    /\ jn'[j].nextTx    = s.nextTx      \* nextTxId
    /\ jn'[j].committed = s.committed   \* committedTxnId.get()

\* Response payload of a successful call.
RespOK(out, e) ==
    CASE e.res # "ok"     -> TRUE
      [] e.op = "gjs"     -> out.resp.promised = e.resp.promised
      [] e.op = "ne"      -> out.resp.lastSeg = e.resp.lastSeg
      [] e.op = "prepare" -> /\ out.resp.hasSeg = e.resp.hasSeg
                             /\ out.resp.segLast = e.resp.segLast
                             /\ out.resp.segInProg = e.resp.segInProg
                             /\ out.resp.lwe = e.resp.lwe
                             /\ out.resp.committed = e.resp.committed
      [] OTHER            -> TRUE

JNAction(w, j, op) ==
    CASE op = "gjs"      -> JNGetJournalState(w, j)
      [] op = "ne"       -> JNNewEpoch(w, j)
      [] op = "start"    -> JNStartLogSegment(w, j)
      [] op = "journal"  -> TargetCheck(w, j)
      [] op = "finalize" -> JNFinalizeLogSegment(w, j)
      [] op = "prepare"  -> JNPrepareRecovery(w, j)
      [] op = "accept"   -> JNAcceptRecovery(w, j)

QuorumAction(w, op) ==
    CASE op = "gjs"      -> CreateNewUniqueEpoch_GotJournalState(w)
      [] op = "ne"       -> CreateNewUniqueEpoch_GotNewEpoch(w)
      [] op = "prepare"  -> RecoverUnclosedSegment_GotPrepare(w)
      [] op = "accept"   -> RecoverUnclosedSegment_GotAccept(w)
      [] op = "start"    -> StartLogSegment_GotQuorum(w)
      [] op = "journal"  -> FlushAndSync_GotQuorum(w)
      [] op = "finalize" -> FinalizeLogSegment_GotQuorum(w)

\* ---------------------------------------------------------------------------
\* Action wrappers (one event each)
\* ---------------------------------------------------------------------------

\* QJM.recoverUnfinalizedSegments entry (QJM:474)
TWriterBegin ==
    /\ IsEvent("WriterBegin")
    /\ WriterBegin(logline.w)
    /\ Step

\* AsyncLoggerSet fan-out (ALS:208-263, 291-312)
TFanOut ==
    /\ IsEvent("FanOut")
    /\ wPhase[logline.w] = "fanout"
    /\ OpArgsOK(wOp[logline.w], logline)
    /\ WriterFanOut(logline.w)
    /\ Step

\* IPCLoggerChannel task start; RequestInfo stamped (IPCL:287-291)
TDispatch ==
    /\ IsEvent("Dispatch")
    /\ LET w == logline.w
           j == logline.jn
       IN /\ chQ[w][j] # <<>>
          /\ Head(chQ[w][j]).op = logline.op
          /\ ChannelDispatch(w, j)
          /\ (logline.op \in ReqInfoOps) =>
                /\ inflight'[w][j].epoch     = logline.epoch
                /\ inflight'[w][j].serial    = logline.serial
                /\ inflight'[w][j].committed = logline.committed
    /\ Step

\* IPCLoggerChannel.throwIfOutOfSync threw (IPCL:416-423)
TOutOfSyncFail ==
    /\ IsEvent("OutOfSyncFail")
    /\ LET w == logline.w
           j == logline.jn
       IN /\ chQ[w][j] # <<>>
          /\ Head(chQ[w][j]).op = logline.op
          /\ ChannelFailOutOfSync(w, j)
    /\ Step

\* A JN handler ran the request that is in flight on a channel.
\* res is the result code ("ok", "L518" = target, or the line of the other
\* throw). "L611io" is a failed lastWriterEpoch.set() (StartPersistFail).
TJNExec ==
    /\ IsEvent("JNExec")
    /\ LET j == logline.jn IN
       \E w \in Writers :
         LET req == inflight[w][j] IN
         /\ req.st = "sent"
         /\ ReqMatches(req, logline)
         /\ IF logline.res = "L611io"
            THEN /\ StartPersistFail(w, j)
                 /\ jn'[j].lwDisk = logline.state.lwDisk
            ELSE LET out == Handler(jn[j], req) IN
                 /\ out.res = logline.res
                 /\ RespOK(out, logline)
                 /\ JNAction(w, j, logline.op)
         /\ ValidateJN(j)
    /\ Step

\* A JN handler ran a call whose client had already timed out (S4).
TJNExecLate ==
    /\ IsEvent("JNExec")
    /\ LET j == logline.jn IN
       \E r \in srvPend[j] :
         /\ ReqMatches(r, logline)
         /\ Handler(jn[j], r).res = logline.res
         /\ JNExecLate(j)
         /\ srvPend'[j] = srvPend[j] \ {r}
         /\ ValidateJN(j)
    /\ Step

\* The RPC failed at the client without running on the JN.
TCallFailed ==
    /\ IsEvent("CallFailed")
    /\ inflight[logline.w][logline.jn].op = logline.op
    /\ CallFailed(logline.w, logline.jn)
    /\ Step

\* AsyncLoggerSet.waitForWriteQuorum returned (ok) or threw (ALS:124-148)
TQuorum ==
    /\ IsEvent("Quorum")
    /\ wPhase[logline.w] = "wait"
    /\ wOp[logline.w].op = logline.op
    /\ IF logline.ok THEN QuorumAction(logline.w, logline.op)
                     ELSE WriterQuorumFail(logline.w)
    /\ Step

\* Fault events
TLose ==            \* injected loss (e.g. TestQJMWithFaults-style proxy)
    /\ IsEvent("Lose")
    /\ inflight[logline.w][logline.jn].op = logline.op
    /\ LoseRequest(logline.w, logline.jn)
    /\ Step

TTimeout ==         \* client-side rpc timeout; the JN may still run the call
    /\ IsEvent("Timeout")
    /\ inflight[logline.w][logline.jn].op = logline.op
    /\ TimeoutLate(logline.w, logline.jn)
    /\ Step

TDropLate ==        \* IPC Server skipped a call of a closed connection
    /\ IsEvent("DropLate")
    /\ LET j == logline.jn IN
       \E r \in srvPend[j] :
         /\ ReqMatches(r, logline)
         /\ DropLate(j)
         /\ srvPend'[j] = srvPend[j] \ {r}
    /\ Step

TJNCrash ==
    /\ IsEvent("JNCrash")
    /\ Crash(logline.jn)
    /\ Step

\* No state check here: the Journal is re-created lazily by the first RPC
\* after the restart (JNd:98-125), whose JNExec event validates it.
TJNRestart ==
    /\ IsEvent("JNRestart")
    /\ Restart(logline.jn)
    /\ Step

TPowerLoss ==
    /\ IsEvent("PowerLoss")
    /\ PowerLoss(logline.jn)
    /\ jn'[logline.jn].lwDisk = logline.lwDisk
    /\ Step

TWriterCrash ==     \* the test abandons / kills a writer
    /\ IsEvent("WriterCrash")
    /\ WriterCrash(logline.w)
    /\ Step

\* ---------------------------------------------------------------------------
\* Silent action (no event consumed)
\* ---------------------------------------------------------------------------

\* A call failed at the client while the JN was up and no Crash/Lose/Timeout
\* event explains it: the request was lost on the network. Enabled only when
\* the next event is that channel's CallFailed and its request is still
\* marked "sent".
SilentLoseRequest ==
    /\ IsEvent("CallFailed")
    /\ inflight[logline.w][logline.jn].op = logline.op
    /\ inflight[logline.w][logline.jn].st = "sent"
    /\ LoseRequest(logline.w, logline.jn)
    /\ UNCHANGED l

\* ---------------------------------------------------------------------------
\* Specification
\* ---------------------------------------------------------------------------

\* The workload starts on freshly formatted JNs (qjm.format runs before the
\* first recorded event and is not modeled), which is base's Init.
TraceInit ==
    /\ Init
    /\ l = 1

TraceDone ==
    /\ l > Len(TraceLog)
    /\ UNCHANGED traceVars

TraceNext ==
    \/ TWriterBegin
    \/ TFanOut
    \/ TDispatch
    \/ TOutOfSyncFail
    \/ TJNExec
    \/ TJNExecLate
    \/ TCallFailed
    \/ TQuorum
    \/ TLose
    \/ TTimeout
    \/ TDropLate
    \/ TJNCrash
    \/ TJNRestart
    \/ TPowerLoss
    \/ TWriterCrash
    \/ SilentLoseRequest
    \/ TraceDone

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

\* Debug aid: how far the replay got.
TraceAlias == [l |-> l, len |-> Len(TraceLog),
               next |-> IF l <= Len(TraceLog) THEN logline ELSE "done",
               jn |-> jn, inflight |-> inflight, wPhase |-> wPhase,
               wOp |-> wOp, targetFired |-> targetFired]

=============================================================================
