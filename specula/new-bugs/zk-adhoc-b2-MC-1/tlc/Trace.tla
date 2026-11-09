-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for zk-adhoc-b2 (Category A: one linear NDJSON trace).  *)
(*                                                                         *)
(* Replays a trace of the workload LeaderElectionSupportTest#testNodes3     *)
(* (or a variant in the same module) against base.tla. Every base action   *)
(* has exactly one trace event (instrumentation-spec.md section 2); there  *)
(* are no silent actions. Each wrapper matches the event, calls the base   *)
(* action unchanged, validates the captured fields, and advances `l`.      *)
(*                                                                         *)
(* Event envelope (one NDJSON object per line):                            *)
(*   {"tag":"trace","seq":N,"event":{"name":E,"thread":"W"|"ET"|"SRV",     *)
(*     "p":P,"session":S, ...event fields...}}                             *)
(* P = the LES instance's id = its worker thread's name; S = "0x"+hex      *)
(* session id. Constants Participants/Sessions/SessionOf come from the     *)
(* trace (Trace.cfg overrides).                                            *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

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

VARIABLE l      \* cursor: next trace line to match (1-indexed)

logline == TraceLog[l]
te == logline.event   \* the current trace event

ToSet(sq) == {sq[i] : i \in DOMAIN sq}

-----------------------------------------------------------------------------
(* Constants derived from the trace *)

\* A participant = a worker thread that sent its create (WStart).
CreateLines == TLCEval({k \in 1..Len(TraceLog) :
                          /\ TraceLog[k].event.name = "Send"
                          /\ TraceLog[k].event.thread = "W"
                          /\ TraceLog[k].event.op = "create"})

TraceParticipants == TLCEval({TraceLog[k].event.p : k \in CreateLines})

TraceSessions == TLCEval({TraceLog[k].event.session : k \in 1..Len(TraceLog)})

TraceSessionOf == TLCEval(
    [p \in TraceParticipants |->
        TraceLog[CHOOSE k \in CreateLines : TraceLog[k].event.p = p].event.session])

ASSUME TraceParticipants /= {}

-----------------------------------------------------------------------------
(* Event predicates and helpers *)

IsEv(name) ==
    /\ l <= Len(TraceLog)
    /\ te.name = name

IsSend(kind, op) ==
    /\ IsEv("Send")
    /\ te.thread = kind
    /\ te.op = op

\* The model thread an event belongs to.
EvThread == IF te.thread = "W" THEN W(te.p) ELSE ET(te.session)

StepTrace == l' = l + 1

-----------------------------------------------------------------------------
(* Post-state validation *)

\* Send events (ClientCnxn.queuePacket, CC:1674): the request just appended to
\* the handle's FIFO is the logged one, from the logged thread; the recipe
\* state read under the trace lock at enqueue time equals the model's.
ValidateSend ==
    LET s == te.session IN
    /\ Len(reqQ'[s]) > 0
    /\ reqQ'[s][Len(reqQ'[s])].op = te.op
    /\ reqQ'[s][Len(reqQ'[s])].id = te.id
    /\ reqQ'[s][Len(reqQ'[s])].t = EvThread
    /\ reqQ'[s][Len(reqQ'[s])].p = te.p
    /\ lstate'[te.p] = te.state

\* Srv events (FRP.processRequest entry, before applyRequest, FRP:158): the
\* request at the head of the session's FIFO is the logged one and the root's
\* children before the step equal the model's `offers`.
ValidateSrvPre ==
    LET s == te.session IN
    /\ reqQ[s] /= <<>>
    /\ Head(reqQ[s]).op = te.op
    /\ Head(reqQ[s]).id = te.id
    /\ offers = ToSet(te.offers)

\* Recipe (LES) events: the instance state right after the step.
ValidateState == lstate'[te.p] = te.state

-----------------------------------------------------------------------------
(* Action wrappers: client sends *)

WStartIfLogged ==
    /\ IsSend("W", "create")
    /\ WStart(te.p)
    /\ ValidateSend
    /\ pc'[W(te.p)] = "w_create"
    /\ StepTrace

WDetStartIfLogged ==
    /\ IsSend("W", "getChildren")
    /\ WDetStart(te.p)
    /\ ValidateSend
    /\ pc'[W(te.p)] = "det_children"
    /\ StepTrace

SendGetDataIfLogged ==
    /\ IsEv("Send")
    /\ te.op = "getData"
    /\ SendGetData(EvThread, te.id)
    /\ ValidateSend
    /\ PartOf(EvThread) = te.p
    /\ StepTrace

\* Worker becomeReady: DetDecide's ready branch sends exists(prev) (LES:239).
WReadySendExistsIfLogged ==
    /\ IsSend("W", "exists")
    /\ DetDecide(W(te.p))
    /\ ValidateSend
    /\ pc'[W(te.p)] = "det_exists"
    /\ StepTrace

ETDetSendChildrenIfLogged ==
    /\ IsSend("ET", "getChildren")
    /\ etP[te.session] = te.p
    /\ ETDetSendChildren(te.session)
    /\ ValidateSend
    /\ StepTrace

ETSendExistsIfLogged ==
    /\ IsSend("ET", "exists")
    /\ etP[te.session] = te.p
    /\ ETSendExists(te.session)
    /\ ValidateSend
    /\ StepTrace

WStopSendDeleteIfLogged ==
    /\ IsSend("W", "delete")
    /\ WStopSendDelete(te.p)
    /\ ValidateSend
    /\ pc'[W(te.p)] = "w_delete"
    /\ StepTrace

-----------------------------------------------------------------------------
(* Action wrappers: server (FRP) steps *)

SrvCreateIfLogged ==
    /\ IsEv("Srv") /\ te.op = "create"
    /\ LET s == te.session IN
       /\ reqQ[s] /= <<>>
       /\ Head(reqQ[s]).op = "create"
       /\ offers = ToSet(te.offers)
       /\ SrvCreate(s)
       /\ te.id = nextSeq                       \* sequential suffix from the CreateTxn path
       /\ offers' = offers \cup {te.id}
       /\ owner'[te.id] = s
    /\ StepTrace

SrvGetChildrenIfLogged ==
    /\ IsEv("Srv") /\ te.op = "getChildren"
    /\ ValidateSrvPre
    /\ SrvGetChildren(te.session)
    /\ StepTrace

TargetCheckIfLogged ==
    /\ IsEv("Srv") /\ te.op = "getData"
    /\ ValidateSrvPre
    /\ TargetCheck(te.session)
    /\ targetFired' = (te.id \notin ToSet(te.offers))   \* FRP:672-674 as logged
    /\ StepTrace

SrvExistsIfLogged ==
    /\ IsEv("Srv") /\ te.op = "exists"
    /\ ValidateSrvPre
    /\ SrvExists(te.session)
    /\ StepTrace

SrvDeleteIfLogged ==
    /\ IsEv("Srv") /\ te.op = "delete"
    /\ ValidateSrvPre
    /\ SrvDelete(te.session)
    /\ offers' = ToSet(te.offers) \ {te.id}
    /\ StepTrace

\* closeSession of a traced handle (not produced by the passing workload;
\* produced by the S3 variant): ExpireSession.
ExpireSessionIfLogged ==
    /\ IsEv("Srv") /\ te.op = "closeSession"
    /\ offers = ToSet(te.offers)
    /\ ExpireSession(te.session)
    /\ StepTrace

-----------------------------------------------------------------------------
(* Action wrappers: recipe (LES) steps *)

ETOfferIfLogged ==
    /\ IsEv("ETOffer")
    /\ etQ[te.session] /= <<>>
    /\ Head(etQ[te.session]).id = te.id          \* the NodeDeleted path
    /\ ETCheckOffer(te.session, te.p)
    /\ te.own = (te.id = ownId[te.p])            \* LES:329 comparison as logged
    /\ StepTrace

ETStateIfLogged ==
    /\ IsEv("ETState")
    /\ etP[te.session] = te.p
    /\ lstate[te.p] = te.state                   \* LES:330 value read
    /\ ETCheckState(te.session)
    /\ te.pass = (pc'[ET(te.session)] = "et_det")
    /\ StepTrace

ETDetBeginIfLogged ==
    /\ IsEv("ETDetBegin")
    /\ etP[te.session] = te.p
    /\ ETDetBegin(te.session)
    /\ ValidateState
    /\ StepTrace

ETDetMonIfLogged ==
    /\ IsEv("ETDetMon")
    /\ etP[te.session] = te.p
    /\ ETDetMonitor(te.session)
    /\ StepTrace

\* DetDecide, leader branch (LES:215-216, 262), worker or EventThread.
ElectedIfLogged ==
    /\ IsEv("Elected")
    /\ PartOf(EvThread) = te.p
    /\ DetDecide(EvThread)
    /\ lstate'[te.p] = "ELECTED"
    /\ ValidateState
    /\ StepTrace

ElectedMonIfLogged ==
    /\ IsEv("ElectedMon")
    /\ etP[te.session] = te.p
    /\ ETLeaderMonitor(te.session)
    /\ StepTrace

\* DetDecide, ready branch on the EventThread: monitor step at LES:232.
ReadyMonIfLogged ==
    /\ IsEv("ReadyMon")
    /\ etP[te.session] = te.p
    /\ DetDecide(ET(te.session))
    /\ pc'[ET(te.session)] = "et_ready_mon"
    /\ StepTrace

\* DetDecide, no own entry in the listing (LES:207-224 loop ends).
DetNoMatchIfLogged ==
    /\ IsEv("DetNoMatch")
    /\ PartOf(EvThread) = te.p
    /\ DetDecide(EvThread)
    /\ pc'[EvThread] \in {"sleep", "et_idle"}
    /\ ValidateState
    /\ StepTrace

ReadyIfLogged ==
    /\ IsEv("Ready")
    /\ PartOf(EvThread) = te.p
    /\ RecvExistsOK(EvThread)
    /\ ValidateState
    /\ StepTrace

FailedIfLogged ==
    /\ IsEv("Failed")
    /\ PartOf(EvThread) = te.p
    /\ RecvDataNoNode(EvThread)
    /\ ValidateState
    /\ StepTrace

StopBeginIfLogged ==
    /\ IsEv("StopBegin")
    /\ WStopBegin(te.p)
    /\ ValidateState
    /\ StepTrace

\* stop() returned: after the delete reply (WStopDone), or directly when
\* leaderOffer == null (WStopSendDelete's no-offer branch, LES:153, 162).
StopDoneIfLogged ==
    /\ IsEv("StopDone")
    /\ \/ /\ pc[W(te.p)] = "w_delete"
          /\ WStopDone(te.p)
          /\ rcv[W(te.p)].err = te.err
       \/ /\ pc[W(te.p)] = "w_stop"
          /\ ownId[te.p] = NoId
          /\ WStopSendDelete(te.p)
    /\ pc'[W(te.p)] = "done"
    /\ ValidateState
    /\ StepTrace

-----------------------------------------------------------------------------
TraceInit ==
    /\ Init          \* fresh election root (LEST:54-58): no offers, cversion 0
    /\ l = 1

TraceNext ==
    \/ WStartIfLogged
    \/ WDetStartIfLogged
    \/ SendGetDataIfLogged
    \/ WReadySendExistsIfLogged
    \/ ETDetSendChildrenIfLogged
    \/ ETSendExistsIfLogged
    \/ WStopSendDeleteIfLogged
    \/ SrvCreateIfLogged
    \/ SrvGetChildrenIfLogged
    \/ TargetCheckIfLogged
    \/ SrvExistsIfLogged
    \/ SrvDeleteIfLogged
    \/ ExpireSessionIfLogged
    \/ ETOfferIfLogged
    \/ ETStateIfLogged
    \/ ETDetBeginIfLogged
    \/ ETDetMonIfLogged
    \/ ElectedIfLogged
    \/ ElectedMonIfLogged
    \/ ReadyMonIfLogged
    \/ DetNoMatchIfLogged
    \/ ReadyIfLogged
    \/ FailedIfLogged
    \/ StopBeginIfLogged
    \/ StopDoneIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

\* Every logged event was matched.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l        |-> l,
      len      |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN te ELSE "DONE",
      offers   |-> offers,
      nextSeq  |-> nextSeq,
      reqQ     |-> reqQ,
      rcv      |-> rcv,
      etQ      |-> etQ,
      etP      |-> etP,
      srvW     |-> srvW,
      cliW     |-> cliW,
      lstate   |-> lstate,
      ownId    |-> ownId,
      pc       |-> pc,
      listing  |-> listing,
      toRead   |-> toRead,
      targetFired |-> targetFired ]

=============================================================================
