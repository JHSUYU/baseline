------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-20, BPOfferService.java:615).  *)
(*                                                                         *)
(* Category A: one NDJSON trace per test run, events in emission order     *)
(* (SpeculaTrace.emit is synchronized).  Every wrapper calls the base      *)
(* action and validates the fields the emitting thread can read:           *)
(*   NN events  -> haState, written, applied, durable of that NN           *)
(*   DN events  -> bpServiceToActive (B), lastActiveClaimTxId (L)          *)
(* plus the RPC payloads (heartbeat (state, txid); versionRequest state).  *)
(* The mapping to code is in instrumentation-spec.md.                     *)
(*                                                                         *)
(* Anchor: TestClientProtocolForPipelineRecovery#testPipelineRecoveryOnOOB *)
(* (non-HA, 1 NN, 1 DN) and its variants V1 (+ clean NN restart) and V2    *)
(* (more append/hflush rounds), brief §7.                                  *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

\* ============================================================================
\* TRACE LOADING
\* ============================================================================

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

\* The first line is the Init event emitted when the first NameNode of the
\* test JVM finishes starting (instrumentation-spec.md §2.1).
InitEvent == TraceLog[1].event

ASSUME InitEvent.name = "Init"
ASSUME InitEvent.nid \in NN

\* ============================================================================
\* TRACE CURSOR
\* ============================================================================

VARIABLE l       \* position of the next unconsumed event in TraceLog

traceVars == <<l>>

logline == TraceLog[l]

\* ============================================================================
\* MAPPINGS AND PREDICATES
\* ============================================================================

\* Trace value of bpServiceToActive: the actor's NN id, or "null".
TraceActor(s) == IF s = "null" THEN Null ELSE s

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ logline.event.name = name

\* NN events: nid = the NameNode.  DN events: nid = the NN of the actor.
IsNodeEvent(name, n) ==
    /\ IsEvent(name)
    /\ logline.event.nid = n

StepTrace == l' = l + 1

\* ============================================================================
\* BOOTSTRAP STATE
\* ============================================================================

\* The workload's MiniDFSCluster formats the NN and starts it before any
\* DataNode (MiniDFSCluster: NameNodes first, then DataNodes).  The Init line
\* carries the started NN's state (normally applied 0, written = durable = 1:
\* START_LOG_SEGMENT after format, FSEditLog.java:1453-1460).  The DataNode
\* has not started yet; its first BPOfferService is the NewBPOS event, which
\* maps to DNRestart and leaves this initial DN state unchanged.
TraceInit ==
    /\ l = 2
    /\ nnPhase = [n \in NN |-> IF n = InitEvent.nid THEN "UP" ELSE "DOWN"]
    /\ haState = [n \in NN |-> IF n = InitEvent.nid
                               THEN InitEvent.state.haState
                               ELSE "STANDBY"]
    /\ fenced  = [n \in NN |-> FALSE]
    /\ written = [n \in NN |-> IF n = InitEvent.nid
                               THEN InitEvent.state.written ELSE 0]
    /\ applied = [n \in NN |-> IF n = InitEvent.nid
                               THEN InitEvent.state.applied ELSE 0]
    /\ durable = InitEvent.state.durable
    /\ link    = [n \in NN |-> TRUE]
    /\ bpServiceToActive   = Null
    /\ lastActiveClaimTxId = -1
    /\ aPhase  = [a \in NN |-> "INIT"]
    /\ nsResp  = [a \in NN |-> "NONE"]
    /\ hbResp  = [a \in NN |-> NoResp]
    /\ targetFired = FALSE
    /\ maxHeldTxid = [n \in NN |-> Max(applied[n], written[n])]

\* ============================================================================
\* POST-STATE VALIDATION
\* ============================================================================

\* NN events: the emitting NameNode's own fields (instrumentation-spec §1.2).
ValidateNN(n) ==
    LET s == logline.event.state IN
    /\ haState'[n] = s.haState
    /\ written'[n] = s.written
    /\ applied'[n] = s.applied
    /\ durable'    = s.durable

\* After StopRpcServer the process' in-memory values are gone in the model
\* (canonical reset); only the durable log end is still meaningful.
ValidateNNDown(n) ==
    /\ nnPhase'[n] = "DOWN"
    /\ durable' = logline.event.state.durable

\* DN events: the BPOfferService fields (read under the BPOS lock).  NN fields
\* are not readable consistently from a DN thread: weak validation by
\* necessity, not convenience.
ValidateDN ==
    LET s == logline.event.state IN
    /\ bpServiceToActive'   = TraceActor(s.B)
    /\ lastActiveClaimTxId' = s.L

\* ============================================================================
\* ACTION WRAPPERS: NameNode events
\* ============================================================================

ClientEditIfLogged ==
    \E n \in NN :
        /\ IsNodeEvent("ClientEdit", n)
        /\ ClientEdit(n)
        /\ ValidateNN(n)
        /\ StepTrace

\* A SyncEdits event reports the new durable end (shadow of lastJournalledTxId
\* after a successful flush, instrumentation-spec §1.2).  The harness emits it
\* only when that end advances; the second branch tolerates a flush that made
\* nothing new durable.
SyncEditsIfLogged ==
    \E n \in NN :
        /\ IsNodeEvent("SyncEdits", n)
        /\ \/ SyncEdits(n)
           \/ /\ Serving(n)
              /\ logline.event.state.durable = durable
              /\ UNCHANGED vars
        /\ ValidateNN(n)
        /\ StepTrace

\* Second branch: the request was sent by an actor that has since died (DN
\* shutdown interrupted its RPC, ActorDie already logged); the NN still
\* answers but the response is never delivered.  Only allowed when the
\* actor is not RUNNING; the NN-side snapshot is still validated.
HeartbeatHandleIfLogged ==
    \E a \in NN :
        /\ IsNodeEvent("HeartbeatHandle", a)
        /\ \/ /\ HeartbeatHandle(a)
              /\ hbResp'[a].state = logline.event.msg.state
              /\ hbResp'[a].txid  = logline.event.msg.txid
           \/ /\ aPhase[a] /= "RUNNING"
              /\ Serving(a)
              /\ haState[a]      = logline.event.msg.state
              /\ ReportedTxid(a) = logline.event.msg.txid
              /\ UNCHANGED vars
        /\ ValidateNN(a)
        /\ StepTrace

StopNameNodeIfLogged ==
    \E n \in NN :
        /\ IsNodeEvent("StopNameNode", n)
        /\ StopNameNode(n)
        /\ ValidateNN(n)
        /\ StepTrace

StopRpcServerIfLogged ==
    \E n \in NN :
        /\ IsNodeEvent("StopRpcServer", n)
        /\ StopRpcServer(n)
        /\ ValidateNNDown(n)
        /\ StepTrace

RestartIfLogged ==
    \E n \in NN :
        /\ IsNodeEvent("Restart", n)
        /\ Restart(n)
        /\ ValidateNN(n)
        /\ StepTrace

\* ============================================================================
\* ACTION WRAPPERS: DataNode events
\* ============================================================================

\* New BPOfferService: the DataNode's first start and the workload's OOB
\* upgrade restart (MiniDFSCluster.restartDataNode).
NewBPOSIfLogged ==
    /\ IsEvent("NewBPOS")
    /\ DNRestart
    /\ ValidateDN
    /\ StepTrace

VersionRequestIfLogged ==
    \E a \in NN :
        /\ IsNodeEvent("VersionRequest", a)
        /\ VersionRequest(a)
        /\ nsResp'[a] = logline.event.msg.state
        /\ ValidateDN
        /\ StepTrace

HandshakeApplyIfLogged ==
    \E a \in NN :
        /\ IsNodeEvent("HandshakeApply", a)
        /\ HandshakeApply(a)
        /\ ValidateDN
        /\ StepTrace

\* The target.  The event carries the response the actor processed and
\* whether the assert at :615 failed.
TargetCheckIfLogged ==
    \E a \in NN :
        /\ IsNodeEvent("TargetCheck", a)
        /\ hbResp[a].state = logline.event.msg.state
        /\ hbResp[a].txid  = logline.event.msg.txid
        /\ TargetCheck(a)
        /\ targetFired' = logline.event.msg.fired
        /\ ValidateDN
        /\ StepTrace

\* The heartbeat RPC threw at the DN.  If the NN had answered (HeartbeatHandle
\* logged), the response is dropped; if the call failed before reaching the
\* NN (NN down, not started), nothing changes.
HeartbeatRpcFailIfLogged ==
    \E a \in NN :
        /\ IsNodeEvent("HeartbeatRpcFail", a)
        /\ \/ HeartbeatRpcFail(a)
           \/ /\ hbResp[a] = NoResp
              /\ UNCHANGED vars
        /\ ValidateDN
        /\ StepTrace

ActorDieIfLogged ==
    \E a \in NN :
        /\ IsNodeEvent("ActorDie", a)
        /\ ActorDie(a)
        /\ ValidateDN
        /\ StepTrace

\* ============================================================================
\* NEXT AND SPEC
\* ============================================================================

\* No silent actions: every model step the workload performs has an event.
\* Faults (Crash, Depose, ToActive/ToStandby, Partition, Refresh) do not occur
\* in the workload or its variants and have no wrapper.
TraceNext ==
    \/ ClientEditIfLogged
    \/ SyncEditsIfLogged
    \/ HeartbeatHandleIfLogged
    \/ StopNameNodeIfLogged
    \/ StopRpcServerIfLogged
    \/ RestartIfLogged
    \/ NewBPOSIfLogged
    \/ VersionRequestIfLogged
    \/ HandshakeApplyIfLogged
    \/ TargetCheckIfLogged
    \/ HeartbeatRpcFailIfLogged
    \/ ActorDieIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l        |-> l,
      len      |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN logline.event.name ELSE "DONE",
      nid      |-> IF l <= Len(TraceLog) THEN logline.event.nid ELSE "DONE",
      tState   |-> IF l <= Len(TraceLog) THEN logline.event.state ELSE "DONE",
      tMsg     |-> IF l <= Len(TraceLog) /\ "msg" \in DOMAIN logline.event
                   THEN logline.event.msg ELSE "DONE",
      B        |-> bpServiceToActive,
      L        |-> lastActiveClaimTxId,
      aPhase   |-> aPhase,
      hbResp   |-> hbResp,
      nnPhase  |-> nnPhase,
      haState  |-> haState,
      written  |-> written,
      applied  |-> applied,
      durable  |-> durable,
      fired    |-> targetFired ]

=============================================================================
