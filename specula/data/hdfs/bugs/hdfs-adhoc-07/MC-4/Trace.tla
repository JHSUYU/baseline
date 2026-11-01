--------------------------------- MODULE Trace ---------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-07), Category A: one linear    *)
(* NDJSON trace, cursor l.  The workload is TestQuorumJournalManager#       *)
(* testRecoverAfterIncompleteRecovery and its variants; the spying QJM runs *)
(* every channel call synchronously (SpyQJournalUtil 59-63), so the trace is *)
(* one total order.  Event schema and capture points: instrumentation-spec.md *)
(*                                                                          *)
(*   {"tag":"trace","ts":"<nanos>","event":{"name":N,"nid":ID,              *)
(*                                          "msg":{...},"state":{...}}}     *)
(*                                                                          *)
(* JN handler events (one per Journal RPC handler run) are matched to the   *)
(* in-flight call of channel (msg.w, nid); a silent ChDispatch/ChHeartbeat  *)
(* first moves the channel's head task in flight (the executor thread).     *)
(* Every wrapper calls the base action and then checks the post-state.      *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                 /\ x.tag = "trace"
                                 /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0

VARIABLE l           \* next trace line to match (1-indexed)
traceVars == <<vars, l>>

E == TraceLog[l].event

IsEvent(name) == l <= Len(TraceLog) /\ E.name = name

Has(rec, f) == f \in DOMAIN rec

SeqToSet(q) == {q[i] : i \in DOMAIN q}

(***************************************************************************)
(* Post-state checks                                                        *)
(***************************************************************************)

FilesSet(rec) ==
    {[s |-> sg, end |-> rec.files[sg].end, ip |-> rec.files[sg].ip] :
        sg \in {x \in Seg : rec.files[x].ex}}
PaxosSet(rec) ==
    {[s |-> sg, ep |-> rec.paxos[sg].ep, end |-> rec.paxos[sg].end,
      ip |-> rec.paxos[sg].ip] : sg \in {x \in Seg : rec.paxos[x].ex}}

\* The JN snapshot taken right after the handler (instrumentation-spec 1.2).
\* nextTxId is only meaningful while a segment is open (base.tla keeps it 0
\* otherwise).
JNStateMatches(rec, st) ==
    /\ rec.pr  = st.pr
    /\ rec.lwe = st.lwe
    /\ rec.c   = st.c
    /\ rec.cs  = st.cs
    /\ rec.cs # 0 => rec.nx = st.nx
    /\ rec.fc  = st.fc
    /\ FilesSet(rec) = SeqToSet(st.files)
    /\ PaxosSet(rec) = SeqToSet(st.paxos)
    /\ rec.tmp = SeqToSet(st.tmp)

\* The request as received by the JN (RequestInfo and arguments): every field
\* the harness captured must equal the model's in-flight call.
ReqMatches(r, m) ==
    \A f \in DOMAIN m.req : r[f] = m.req[f]

\* The reply recorded by the writer's QuorumCall, when the writer was waiting
\* for this call: outcome and every captured payload field.
RespMatches(resp, m) ==
    /\ resp.k = m.outcome
    /\ Has(m, "resp") => \A f \in DOMAIN m.resp : resp[f] = m.resp[f]

RespChecked(w, j, r) ==
    IF /\ wr[w].pc \in WaitPC
       /\ SameCall(wr[w].call, r)
       /\ wr[w].resp[j].k = "none"
       /\ r.rop # "hb"
    THEN RespMatches(wr'[w].resp[j], E.msg)
    ELSE TRUE

\* Writer-side snapshot (instrumentation-spec 1.3): the outOfSync flag of each
\* of the writer's channels (IPCLoggerChannel.isOutOfSync, ILC 306-308).  The
\* writer's epoch and committedTxId are checked through the events' own
\* fields (WCreateNewUniqueEpoch.epoch, WSendEditsDone.c) and through every
\* request a JN receives (req.ep, req.c).
WStateMatches(w, st) ==
    Has(st, "oos") => \A j \in JN : ch'[w][j].oos = st.oos[j]

(***************************************************************************)
(* JN handler events                                                        *)
(***************************************************************************)

HandlerOp ==
    [GetJournalState    |-> "gjs",
     NewEpoch           |-> "ne",
     PrepareRecovery    |-> "prep",
     AcceptRecovery     |-> "acc",
     Journal            |-> "jrnl",
     Heartbeat          |-> "hb",
     StartLogSegment    |-> "start",
     FinalizeLogSegment |-> "fin",
     PurgeLogsOlderThan |-> "purge"]

IsHandlerEvent == l <= Len(TraceLog) /\ E.name \in DOMAIN HandlerOp

RunHandler(j, w, op) ==
    CASE op = "gjs"   -> JNGetJournalState(j, w, "in", FALSE)
      [] op = "ne"    -> JNNewEpoch(j, w, "in", FALSE)
      [] op = "prep"  -> JNPrepareRecovery(j, w, "in", FALSE)
      [] op = "acc"   -> JNAcceptRecovery(j, w, "in", FALSE) \/ TargetCheck(j, w, "in")
      [] op = "jrnl"  -> JNJournal(j, w, "in", FALSE)
      [] op = "hb"    -> JNHeartbeat(j, w, "in", FALSE)
      [] op = "start" -> JNStartLogSegment(j, w, "in", FALSE)
      [] op = "fin"   -> JNFinalizeLogSegment(j, w, "in", FALSE)
      [] op = "purge" -> JNPurgeLogsOlderThan(j, w, "in", FALSE)

TraceJNHandler ==
    /\ IsHandlerEvent
    /\ LET w  == E.msg.w
           j  == E.nid
           op == HandlerOp[E.name]
           r  == ch[w][j].inf
       IN /\ r.rop = op
          /\ Has(E.msg, "req") => ReqMatches(r, E.msg)
          /\ RunHandler(j, w, op)
          /\ JNStateMatches(jn'[j], E.state)
          /\ RespChecked(w, j, r)
    /\ l' = l + 1

\* ILC 527-535: a prepareRecovery task whose channel has no HTTP endpoint
\* (its getJournalState failed or was stubbed) first sends a raw
\* getJournalState.  It changes nothing at the JN and nothing in the model.
TracePrepareInnerGetJournalState ==
    /\ IsEvent("GetJournalState")
    /\ LET w == E.msg.w
           j == E.nid
       IN /\ ch[w][j].inf.rop = "prep"
          /\ JNStateMatches(jn[j], E.state)
    /\ UNCHANGED vars
    /\ l' = l + 1

(***************************************************************************)
(* Silent action: the channel executor thread starts the head task (or its  *)
(* heartbeat).  Only for the channel the next event is about, only when    *)
(* nothing is in flight on it: deterministic.                              *)
(***************************************************************************)
NextNeedsInflight(w, j) ==
    \/ /\ E.name \in DOMAIN HandlerOp
       /\ E.msg.w = w /\ E.nid = j
    \/ /\ E.name = "ClientFail"
       /\ E.msg.w = w /\ E.msg.j = j
       /\ E.msg.kind \in {"down", "drop", "late"}

TraceSilentDispatch ==
    /\ l <= Len(TraceLog)
    /\ \E w \in W, j \in JN :
         /\ NextNeedsInflight(w, j)
         /\ ch[w][j].inf = NoReq
         /\ IF E.name = "Heartbeat" THEN ChHeartbeat(w, j) ELSE ChDispatch(w, j)
    /\ UNCHANGED l

(***************************************************************************)
(* Client-side failures that never ran a JN handler                         *)
(*   stub  the call failed before its task ran (Mockito futureThrows,      *)
(*         LoggerTooFarBehindException)                     -> ChReject     *)
(*   down  connection refused, JN stopped                   -> RpcConnectFail *)
(*   drop  call lost on the wire                            -> RpcDrop      *)
(*   late  writer saw a failure, JN may still run it        -> RpcLate      *)
(*   oos   JournalOutOfSyncException without heartbeat      -> ChOutOfSync  *)
(***************************************************************************)
TraceClientFail ==
    /\ IsEvent("ClientFail")
    /\ LET w == E.msg.w
           j == E.msg.j
           k == E.msg.kind
           q == ch[w][j].q
       IN /\ CASE k = "stub" -> /\ q # <<>>
                                /\ q[Len(q)].op = E.msg.op
                                /\ ChReject(w, j)
               [] k = "down" -> /\ ch[w][j].inf.op = E.msg.op
                                /\ RpcConnectFail(w, j)
               [] k = "drop" -> /\ ch[w][j].inf.op = E.msg.op
                                /\ RpcDrop(w, j)
               [] k = "late" -> /\ ch[w][j].inf.op = E.msg.op
                                /\ RpcLate(w, j)
               [] k = "oos"  -> /\ q # <<>>
                                /\ Head(q).op = E.msg.op
                                /\ ChOutOfSync(w, j)
          /\ Has(E, "state") => WStateMatches(w, E.state)
    /\ l' = l + 1

(***************************************************************************)
(* Writer events (QuorumJournalManager / QuorumOutputStream)                *)
(***************************************************************************)
EvW == E.msg.w
EvR == SeqToSet(E.msg.R)

WEnd == /\ Has(E, "state") => WStateMatches(EvW, E.state)
        /\ l' = l + 1

TraceWRecoverUnfinalizedSegments ==
    /\ IsEvent("WRecoverUnfinalizedSegments")
    /\ WRecoverUnfinalizedSegments(EvW)
    /\ WEnd

TraceWCreateNewUniqueEpoch ==
    /\ IsEvent("WCreateNewUniqueEpoch")
    /\ WCreateNewUniqueEpoch(EvW, EvR)
    /\ wr'[EvW].ep = E.msg.epoch
    /\ WEnd

TraceWRecoverPrepare ==
    /\ IsEvent("WRecoverPrepare")
    /\ WRecoverPrepare(EvW, EvR)
    /\ IF E.msg.S = 0 THEN wr'[EvW].pc = "act"
       ELSE wr'[EvW].pc = "prep" /\ wr'[EvW].S = E.msg.S
    /\ WEnd

TraceWRecoverDecide ==
    /\ IsEvent("WRecoverDecide")
    /\ WRecoverDecide(EvW, EvR)
    /\ CASE E.msg.outcome = "accept" ->
              /\ wr'[EvW].pc = "acc"
              /\ wr'[EvW].dec = [end |-> E.msg.end, ip |-> E.msg.ip, src |-> E.msg.src]
         [] E.msg.outcome = "nothing" -> wr'[EvW].pc = "act"
         [] E.msg.outcome = "client386" -> "client386" \in otherFired'
         [] E.msg.outcome = "cmp76" -> "cmp76" \in otherFired'
    /\ WEnd

TraceWRecoverFinalize ==
    /\ IsEvent("WRecoverFinalize")
    /\ WRecoverFinalize(EvW)
    /\ WEnd

TraceWRecoveryDone ==
    /\ IsEvent("WRecoveryDone")
    /\ WRecoveryDone(EvW)
    /\ WEnd

TraceWStartLogSegment ==
    /\ IsEvent("WStartLogSegment")
    /\ WStartLogSegment(EvW)
    /\ wr'[EvW].call.s = E.msg.t
    /\ WEnd

TraceWStartLogSegmentDone ==
    /\ IsEvent("WStartLogSegmentDone")
    /\ WStartLogSegmentDone(EvW)
    /\ WEnd

TraceWSendEdits ==
    /\ IsEvent("WSendEdits")
    /\ E.msg.first = wr[EvW].last + 1
    /\ WSendEdits(EvW, E.msg.last - E.msg.first + 1)
    /\ wr'[EvW].call.s = E.msg.seg
    /\ WEnd

TraceWSendEditsDone ==
    /\ IsEvent("WSendEditsDone")
    /\ WSendEditsDone(EvW)
    /\ wr'[EvW].c = E.msg.c
    /\ WEnd

TraceWFinalizeLogSegment ==
    /\ IsEvent("WFinalizeLogSegment")
    /\ WFinalizeLogSegment(EvW)
    /\ wr'[EvW].call.s = E.msg.s /\ wr'[EvW].call.e = E.msg.e
    /\ WEnd

TraceWFinalizeLogSegmentDone ==
    /\ IsEvent("WFinalizeLogSegmentDone")
    /\ WFinalizeLogSegmentDone(EvW)
    /\ WEnd

TraceWPurgeLogsOlderThan ==
    /\ IsEvent("WPurgeLogsOlderThan")
    /\ WPurgeLogsOlderThan(EvW, E.msg.min)
    /\ WEnd

TraceWQuorumFail ==
    /\ IsEvent("WQuorumFail")
    /\ WQuorumFail(EvW)
    /\ WEnd

TraceWQuorumAssertRethrow ==
    /\ IsEvent("WQuorumAssertRethrow")
    /\ WQuorumAssertRethrow(EvW)
    /\ WEnd

TraceWCrash ==
    /\ IsEvent("WCrash")
    /\ WCrash(EvW)
    /\ WEnd

(***************************************************************************)
(* JN process events                                                        *)
(***************************************************************************)
TraceJNCrash ==
    /\ IsEvent("JNCrash")
    /\ JNCrash(E.nid)
    /\ l' = l + 1

TraceJNRestart ==
    /\ IsEvent("JNRestart")
    /\ JNRestart(E.nid)
    /\ Has(E, "state") => JNStateMatches(jn'[E.nid], E.state)
    /\ l' = l + 1

\* The harness's first line maps node names (java-harness.md "Node identity");
\* every JN it names must be in JN.
TraceInitEvent ==
    /\ IsEvent("Init")
    /\ Has(E, "msg") /\ Has(E.msg, "jns") => SeqToSet(E.msg.jns) \subseteq JN
    /\ UNCHANGED vars
    /\ l' = l + 1

(***************************************************************************)
(* Spec                                                                     *)
(***************************************************************************)
TraceInit ==
    /\ Init                 \* formatted, empty JNs (the test's qjm.format())
    /\ l = 1

TraceNext ==
    \/ TraceInitEvent
    \/ TraceJNHandler
    \/ TracePrepareInnerGetJournalState
    \/ TraceClientFail
    \/ TraceWRecoverUnfinalizedSegments
    \/ TraceWCreateNewUniqueEpoch
    \/ TraceWRecoverPrepare
    \/ TraceWRecoverDecide
    \/ TraceWRecoverFinalize
    \/ TraceWRecoveryDone
    \/ TraceWStartLogSegment
    \/ TraceWStartLogSegmentDone
    \/ TraceWSendEdits
    \/ TraceWSendEditsDone
    \/ TraceWFinalizeLogSegment
    \/ TraceWFinalizeLogSegmentDone
    \/ TraceWPurgeLogsOlderThan
    \/ TraceWQuorumFail
    \/ TraceWQuorumAssertRethrow
    \/ TraceWCrash
    \/ TraceJNCrash
    \/ TraceJNRestart
    \* silent (consumes no trace line)
    \/ TraceSilentDispatch

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

TraceView == <<vars, l>>

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [l       |-> l,
     len     |-> Len(TraceLog),
     event   |-> IF l <= Len(TraceLog) THEN E.name ELSE "DONE",
     nid     |-> IF l <= Len(TraceLog) THEN E.nid ELSE "DONE",
     msg     |-> IF l <= Len(TraceLog) THEN E.msg ELSE "DONE",
     tstate  |-> IF l <= Len(TraceLog) /\ Has(E, "state") THEN E.state ELSE "none",
     jn      |-> jn,
     ch      |-> ch,
     wr      |-> wr,
     targetFired |-> targetFired,
     otherFired  |-> otherFired]
=============================================================================
