--------------------------------- MODULE Trace ---------------------------------
(***************************************************************************)
(* Trace validation for zk-adhoc-b3 (Category A: one linear NDJSON trace). *)
(*                                                                         *)
(* Each line: {"tag":"trace","ts":..,"event":{"name":..,"nid":..,          *)
(*             "state":{..},"msg":{..}}}                                    *)
(* Event names are the base.tla action names (instrumentation-spec.md).    *)
(* Optional lines named "Init" are metadata (node mapping, starting zxid)  *)
(* and are not replayed.                                                   *)
(*                                                                         *)
(* Every wrapper calls the base action unchanged, then checks the fields   *)
(* the harness captures against the post-state, then advances l.          *)
(***************************************************************************)
EXTENDS base, Integers, Json, IOUtils, Sequences, TLC

-----------------------------------------------------------------------------
\* Trace loading

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

IsTraceLine(x) ==
    /\ "tag" \in DOMAIN x
    /\ x.tag = "trace"
    /\ "event" \in DOMAIN x

RawLog == TLCEval(ndJsonDeserialize(JsonFile))

InitLines == TLCEval(SelectSeq(RawLog, LAMBDA x :
                IsTraceLine(x) /\ x.event.name = "Init"))

TraceLog == TLCEval(SelectSeq(RawLog, LAMBDA x :
                IsTraceLine(x) /\ x.event.name /= "Init"))

ASSUME Len(TraceLog) > 0

-----------------------------------------------------------------------------
\* Cursor

VARIABLE l       \* position in TraceLog (1-indexed)

traceVars == <<l>>

logline == TraceLog[l]
Msg     == logline.event.msg
St      == logline.event.state

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ logline.event.name = name

StepTrace == l' = l + 1

SeqToSet(s) == {s[i] : i \in DOMAIN s}

-----------------------------------------------------------------------------
(***************************************************************************)
(* Bootstrap.  The workload's session already exists when c1 starts       *)
(* (createSession used a zxid).  The starting hzxid is taken from an       *)
(* "Init" line if the harness writes one, else from the first prepped      *)
(* write: hzxid = its zxid - 1 (PRP:783/791/795 getNextZxid).              *)
(***************************************************************************)
PrepWriteEvents == {"PrepCreate", "PrepDelete", "PrepDeleteContainer"}

WriteIdxs == {k \in 1..Len(TraceLog) : TraceLog[k].event.name \in PrepWriteEvents}

TraceInitZxid ==
    IF Len(InitLines) > 0 /\ "zxid" \in DOMAIN InitLines[1].event.state
        THEN InitLines[1].event.state.zxid
    ELSE IF WriteIdxs /= {}
        THEN TraceLog[CHOOSE k \in WriteIdxs : \A j \in WriteIdxs : k <= j].event.msg.zxid - 1
    ELSE 0

TraceInit ==
    /\ l = 1
    /\ InitWith(TraceInitZxid)

-----------------------------------------------------------------------------
(***************************************************************************)
(* Post-state validation helpers.  A captured node record is              *)
(*   {"ex":bool, "type":EphemeralType name, "cv":cversion,                 *)
(*    "nch":children, "cz":czxid}                                          *)
(* and an absent node is captured as {false,"VOID",0,0,0} (= NoNode).      *)
(***************************************************************************)
RecMatches(s, r) ==
    /\ s.ex = r.ex
    /\ EphemeralTypeOf(s.owner) = r.type
    /\ s.cv = r.cv
    /\ s.nch = r.nch
    /\ s.cz = r.cz

\* getRecordForPath view, captured by PRP after pRequestHelper (PRP:763-766)
PviewMatches ==
    /\ RecMatches(pview'[P], St.pv.node)
    /\ RecMatches(pview'[C], St.pv.child)

\* DataTree, captured by FRP on the SyncThread (the only writer of the tree)
TreeMatches ==
    /\ RecMatches(tree'[P], St.tree.node)
    /\ RecMatches(tree'[C], St.tree.child)

\* PRP events: the request taken from PRP's queue, its outcome, hzxid, view.
ValidatePrep ==
    LET it == pipe'[Len(pipe')] IN
    /\ it.req.op = Msg.op
    /\ it.req.path = Msg.path
    /\ it.err = Msg.err
    /\ IF it.txn.kind = "none"
          THEN Msg.zxid = -1                    \* reads carry no hdr (PRP:759)
          ELSE it.txn.zxid = Msg.zxid           \* hdr zxid (PRP:313-316)
    /\ zxid' = St.zxid                          \* request.zxid = zks.getZxid() (PRP:766)
    /\ PviewMatches

-----------------------------------------------------------------------------
\* Action wrappers (one trace event each)

ClientSendIfLogged ==
    /\ IsEvent("ClientSend")
    /\ ClientSend
    /\ LET r == rtQ'[Len(rtQ')] IN
       /\ r.op = Msg.op
       /\ r.path = Msg.path
       /\ r.src = "client"
    /\ StepTrace

RtForwardIfLogged ==
    /\ IsEvent("RtForward")
    /\ RtForward
    /\ LET r == prepQ'[Len(prepQ')] IN
       /\ r.op = Msg.op
       /\ r.path = Msg.path
       /\ r.src = "client"
    /\ StepTrace

MgrPostIfLogged ==
    /\ IsEvent("MgrPost")
    /\ \E p \in Paths : MgrPost(p)
    /\ LET r == prepQ'[Len(prepQ')] IN
       /\ r.op = "deleteContainer"
       /\ r.path = Msg.path
       /\ r.src = "cm"
    /\ StepTrace

PrepCreateIfLogged ==
    /\ IsEvent("PrepCreate")
    /\ PrepCreate
    /\ ValidatePrep
    /\ StepTrace

PrepDeleteIfLogged ==
    /\ IsEvent("PrepDelete")
    /\ PrepDelete
    /\ ValidatePrep
    /\ StepTrace

PrepDeleteContainerIfLogged ==
    /\ IsEvent("PrepDeleteContainer")
    /\ PrepDeleteContainer
    /\ ValidatePrep
    /\ StepTrace

PrepReadIfLogged ==
    /\ IsEvent("PrepRead")
    /\ PrepRead
    /\ ValidatePrep
    /\ StepTrace

FinalApplyIfLogged ==
    /\ IsEvent("FinalApply")
    /\ pipe /= <<>>
    /\ Head(pipe).req.op = Msg.op
    /\ Head(pipe).req.path = Msg.path
    /\ Head(pipe).req.src = Msg.src
    /\ ApplyErr(Head(pipe)) = Msg.err           \* rc.err / reply code FRP computed
    /\ FinalApply
    /\ Msg.src = "cm" \/ creply' = Msg.err      \* reply sent to the client
    /\ TreeMatches
    /\ StepTrace

TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ pipe /= <<>>
    /\ Head(pipe).req.op = Msg.op
    /\ Head(pipe).req.path = Msg.path
    /\ TargetCheck
    /\ creply' = Msg.err                        \* "NONODE" only from FRP:674
    /\ targetFired' = (targetFired \/ Msg.err = "NONODE")
    /\ TreeMatches
    /\ StepTrace

FinalExistsIfLogged ==
    /\ IsEvent("FinalExists")
    /\ pipe /= <<>>
    /\ Head(pipe).req.op = Msg.op
    /\ Head(pipe).req.path = Msg.path
    /\ FinalExists
    /\ creply' = Msg.err
    /\ TreeMatches
    /\ StepTrace

\* Step marker only: the event carries no state (instrumentation-spec.md).
MgrStartIfLogged ==
    /\ IsEvent("MgrStart")
    /\ MgrStart
    /\ StepTrace

MgrScanIfLogged ==
    /\ IsEvent("MgrScan")
    /\ MgrScan
    /\ cand' = SeqToSet(Msg.cands)              \* getCandidates' return value
    /\ StepTrace

\* Step marker only: MgrDone's guard (posted = cand) already requires that a
\* MgrPost event was replayed for every candidate of the MgrScan event.
MgrDoneIfLogged ==
    /\ IsEvent("MgrDone")
    /\ MgrDone
    /\ StepTrace

-----------------------------------------------------------------------------
(***************************************************************************)
(* Silent actions (no server-side trace event).  The workload client's     *)
(* receipt of a reply and the return of checked.await happen on the test   *)
(* thread; they are implied by that thread's next event, so each is        *)
(* enabled only when the next event belongs to the client thread.  Both   *)
(* are deterministic and fire at most once per client step.               *)
(***************************************************************************)
SilentClientRecv ==
    /\ l <= Len(TraceLog)
    /\ logline.event.name \in {"ClientSend", "MgrStart"}
    /\ ClientRecv
    /\ UNCHANGED traceVars

SilentClientAwaitChecked ==
    /\ l <= Len(TraceLog)
    /\ logline.event.name = "ClientSend"
    /\ ClientAwaitChecked
    /\ UNCHANGED traceVars

-----------------------------------------------------------------------------
TraceNext ==
    \/ ClientSendIfLogged
    \/ RtForwardIfLogged
    \/ MgrPostIfLogged
    \/ PrepCreateIfLogged
    \/ PrepDeleteIfLogged
    \/ PrepDeleteContainerIfLogged
    \/ PrepReadIfLogged
    \/ FinalApplyIfLogged
    \/ TargetCheckIfLogged
    \/ FinalExistsIfLogged
    \/ MgrStartIfLogged
    \/ MgrScanIfLogged
    \/ MgrDoneIfLogged
    \/ SilentClientRecv
    \/ SilentClientAwaitChecked

TraceSpec == TraceInit /\ [][TraceNext]_<<l, vars>> /\ WF_<<l, vars>>(TraceNext)

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [
        l        |-> l,
        len      |-> Len(TraceLog),
        event    |-> IF l <= Len(TraceLog) THEN logline.event.name ELSE "DONE",
        tMsg     |-> IF l <= Len(TraceLog) THEN logline.event.msg ELSE "DONE",
        tState   |-> IF l <= Len(TraceLog) THEN logline.event.state ELSE "DONE",
        tree     |-> tree,
        pview    |-> pview,
        zxid     |-> zxid,
        rtQ      |-> rtQ,
        prepQ    |-> prepQ,
        pipe     |-> pipe,
        creply   |-> creply,
        cpc      |-> cpc,
        cwait    |-> cwait,
        mgr      |-> mgr,
        cand     |-> cand,
        posted   |-> posted,
        targetFired |-> targetFired
    ]

=============================================================================
