------------------------------ MODULE Trace ------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-k1 (Category A: one linear NDJSON trace *)
(* per MiniDFSCluster lifetime).                                           *)
(*                                                                         *)
(* Each trace event is matched to exactly one base action; the wrapper     *)
(* calls the base action and then checks the post-state fields the event   *)
(* captured (see instrumentation-spec.md).  One silent action exists:      *)
(* TraceAdvanceTime moves the clock to the next event's timestamp.          *)
(*                                                                         *)
(* Times are milliseconds relative to the trace's epoch (SpeculaTrace.BASE),*)
(* so expiry arithmetic stays inside TLC's 32-bit integers.  Expiries are  *)
(* compared with tolerance ExpTol because the code calls Time.now()        *)
(* separately per statement (e.g. BTSM:163/166, 230/233/236/241), while    *)
(* the base action uses one `now` per step.                                *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

CONSTANT ExpTol
ASSUME ExpTol \in Nat

----
\* Trace loading
----
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
ASSUME TraceLog[1].event.name = "NNInit"

VARIABLE l
traceVars == <<l>>

ev == TraceLog[l].event

----
\* Constants derived from the trace (substituted in Trace.cfg)
----
InitEv == TraceLog[1].event
TraceI == TLCEval(InitEv.state.I)
TraceL == TLCEval(InitEv.state.L)

DNEventNames == {"DNRegistrationSucceeded", "DNRegAddKeys", "DNRecvHeartbeat",
                 "LoseHeartbeatResp", "DNTransfer", "TargetCheck"}
NNAboutDNNames == {"RegSnapshot", "RegAddToList", "NNHandleHeartbeat",
                   "NNDeclareDead"}

TraceDNs == TLCEval(
    UNION {
      LET e == TraceLog[k].event IN
        (IF e.name \in DNEventNames THEN {e.nid} ELSE {})
        \cup (IF e.name \in NNAboutDNNames THEN {e.msg.dn} ELSE {})
        \cup (IF "msg" \in DOMAIN e /\ "dst" \in DOMAIN e.msg THEN {e.msg.dst} ELSE {})
      : k \in 1..Len(TraceLog)})

TraceClients == TLCEval(
    {TraceLog[k].event.msg.src :
        k \in {j \in 1..Len(TraceLog) : TraceLog[j].event.name = "ClientConnect"}})

----
\* JSON helpers
----
ToSet(s) == {s[i] : i \in DOMAIN s}

KeyIds(lst) == {e.id : e \in ToSet(lst)}

KeysFromJson(lst) ==
    [k \in KeyIds(lst) |-> (CHOOSE e \in ToSet(lst) : e.id = k).exp]

Abs(x) == IF x < 0 THEN -x ELSE x

\* model key map f matches captured list: same ids, expiries within tolerance
SameKeys(f, lst) ==
    /\ DOMAIN f = KeyIds(lst)
    /\ \A e \in ToSet(lst) : Abs(f[e.id] - e.exp) <= ExpTol

SameExport(x, j) ==
    /\ x /= None
    /\ x.cur = j.cur
    /\ SameKeys(x.keys, j.keys)

\* DN/Balancer current key: trace sends curNull = TRUE for null
SameCur(v, st) == IF st.curNull THEN v = None ELSE v = st.cur

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ ev.name = name
    /\ ev.state.now <= now          \* the clock was advanced first

----
\* Bootstrap: the NN master manager as constructed (BTSM:110-134), captured
\* by the NNInit event; DNs, Balancer and clients as in base Init.
----
TraceInit ==
    /\ l = 2
    /\ now = InitEv.state.now
    /\ nnInc = 1
    /\ nnSerial = InitEv.state.serial
    /\ nnCur = InitEv.state.cur
    /\ nnNext = InitEv.state.next
    /\ nnKeys = KeysFromJson(InitEv.state.keys)
    /\ mintedKeys = KeyIds(InitEv.state.keys)
    \* The Monitor uses an arbitrary monotonic epoch (HBM:427,434): allow the
    \* first roll at any time; later rolls are checked against lastRoll.
    /\ lastRoll = InitEv.state.now - I - 1
    /\ nnMonPC = "idle"
    /\ hbList = {}
    /\ needKeyUpdate = [d \in DNs |-> FALSE]
    /\ safeMode = FALSE
    /\ nnStored = {}
    /\ dnPC = [d \in DNs |-> "unreg"]
    /\ dnMgr = [d \in DNs |-> FALSE]
    /\ dnKeys = [d \in DNs |-> EmptyKeys]
    /\ dnCur = [d \in DNs |-> None]
    /\ regSnap = [d \in DNs |-> None]
    /\ hbResp = [d \in DNs |-> None]
    /\ hbDone = [d \in DNs |-> FALSE]
    /\ balOn = FALSE
    /\ balKeys = EmptyKeys
    /\ balCur = None
    /\ balDEK = None
    /\ balPollAge = 0
    /\ cliDEK = [c \in Clients |-> None]
    /\ conns = EmptyBag
    /\ targetFired = FALSE
    /\ npeFired = FALSE

----
\* Silent action: advance the clock to the next event's timestamp.
\* Tightly constrained: only to exactly that value, only when it is ahead.
----
TraceAdvanceTime ==
    /\ l <= Len(TraceLog)
    /\ ev.state.now > now
    /\ AdvanceTime(ev.state.now)
    /\ UNCHANGED l

----
\* Action wrappers
----
Step == l' = l + 1

NNRollUpdateIfLogged ==
    /\ IsEvent("NNRollUpdate")
    /\ NNRollUpdate
    /\ nnCur' = ev.state.cur
    /\ nnNext' = ev.state.next
    /\ nnSerial' = ev.state.serial
    /\ SameKeys(nnKeys', ev.state.keys)
    /\ Step

NNRollMarkIfLogged ==
    /\ IsEvent("NNRollMark")
    /\ NNRollMark
    /\ hbList = ToSet(ev.state.marked)
    /\ \A d \in ToSet(ev.state.marked) : needKeyUpdate'[d]
    /\ Step

RegSnapshotIfLogged ==
    /\ IsEvent("RegSnapshot")
    /\ LET d == ev.msg.dn IN
       /\ RegSnapshot(d)
       /\ SameExport(regSnap'[d], ev.state.exp)
    /\ Step

RegAddToListIfLogged ==
    /\ IsEvent("RegAddToList")
    /\ RegAddToList(ev.msg.dn)
    /\ hbList' = ToSet(ev.state.listed)
    /\ Step

DNRegistrationSucceededIfLogged ==
    /\ IsEvent("DNRegistrationSucceeded")
    /\ LET d == ev.nid IN
       /\ (ev.state.mgrCreated = ~dnMgr[d])
       /\ DNRegistrationSucceeded(d)
       /\ dnMgr'[d]
    /\ Step

DNRegAddKeysIfLogged ==
    /\ IsEvent("DNRegAddKeys")
    /\ LET d == ev.nid IN
       /\ DNRegAddKeys(d)
       /\ SameCur(dnCur'[d], ev.state)
       /\ SameKeys(dnKeys'[d], ev.state.keys)
    /\ Step

NNHandleHeartbeatIfLogged ==
    /\ IsEvent("NNHandleHeartbeat")
    /\ LET d == ev.msg.dn IN
       /\ NNHandleHeartbeat(d)
       /\ hbResp'[d].kind = ev.msg.kind
       /\ (ev.msg.kind = "KEYS") => SameExport(hbResp'[d].exp, ev.msg.exp)
       /\ needKeyUpdate'[d] = ev.state.needKeyUpdate
    /\ Step

DNRecvHeartbeatIfLogged ==
    /\ IsEvent("DNRecvHeartbeat")
    /\ LET d == ev.nid IN
       /\ hbResp[d] /= None
       /\ hbResp[d].kind = ev.msg.kind
       /\ DNRecvHeartbeat(d)
       /\ SameCur(dnCur'[d], ev.state)
       /\ SameKeys(dnKeys'[d], ev.state.keys)
       /\ (dnPC'[d] = "unreg") = (ev.msg.kind = "REGISTER")
    /\ Step

LoseHeartbeatRespIfLogged ==
    /\ IsEvent("LoseHeartbeatResp")
    /\ LoseHeartbeatResp(ev.nid)
    /\ hbResp'[ev.nid] = None
    /\ Step

BalancerStartIfLogged ==
    /\ IsEvent("BalancerStart")
    /\ BalancerStart
    /\ balCur' = ev.state.cur
    /\ SameKeys(balKeys', ev.state.keys)
    /\ Step

BalancerPollIfLogged ==
    /\ IsEvent("BalancerPoll")
    /\ BalancerPoll
    /\ balCur' = ev.state.cur
    /\ SameKeys(balKeys', ev.state.keys)
    /\ Step

BalancerCloseIfLogged ==
    /\ IsEvent("BalancerClose")
    /\ BalancerClose
    /\ Step

BalancerConnectIfLogged ==
    /\ IsEvent("BalancerConnect")
    /\ BalancerConnect(ev.msg.dst)
    /\ balDEK' = ev.msg.keyId
    /\ BagIn(Conn("bal", ev.msg.dst, ev.msg.keyId), conns')
    /\ Step

ClientConnectIfLogged ==
    /\ IsEvent("ClientConnect")
    /\ ClientConnect(ev.msg.src, ev.msg.dst)
    /\ cliDEK'[ev.msg.src].keyId = ev.msg.keyId
    /\ Abs(cliDEK'[ev.msg.src].exp - ev.msg.exp) <= ExpTol
    /\ Step

DNTransferIfLogged ==
    /\ IsEvent("DNTransfer")
    /\ DNTransfer(ev.nid, ev.msg.dst)
    /\ dnCur[ev.nid] = ev.msg.keyId
    /\ Step

TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ LET d == ev.nid
           k == ev.msg.keyId
           r == ev.msg.result
       IN \E c \in BagToSet(conns) :
            /\ c.dst = d
            /\ c.keyId = k
            \* pre-state branch selection must agree with the observed result
            /\ CASE r = "ok"     -> dnMgr[d] /\ k \in DOMAIN dnKeys[d]
                 [] r = "nopool" -> ~dnMgr[d]
                 [] r = "npe"    -> dnMgr[d] /\ k \notin DOMAIN dnKeys[d] /\ dnCur[d] = None
                 [] r = "fired"  -> dnMgr[d] /\ k \notin DOMAIN dnKeys[d] /\ dnCur[d] /= None
                 [] OTHER        -> FALSE
            /\ TargetCheck(c)
            /\ (r = "fired") => targetFired'
            /\ (r = "npe") => npeFired'
    /\ Step

NNDeclareDeadIfLogged ==
    /\ IsEvent("NNDeclareDead")
    /\ NNDeclareDead(ev.msg.dn)
    /\ ev.msg.dn \notin hbList'
    /\ Step

EnterSafeModeIfLogged ==
    /\ IsEvent("EnterSafeMode")
    /\ EnterSafeMode
    /\ Step

LeaveSafeModeIfLogged ==
    /\ IsEvent("LeaveSafeMode")
    /\ LeaveSafeMode
    /\ Step

TraceNext ==
    \/ TraceAdvanceTime
    \/ NNRollUpdateIfLogged
    \/ NNRollMarkIfLogged
    \/ RegSnapshotIfLogged
    \/ RegAddToListIfLogged
    \/ DNRegistrationSucceededIfLogged
    \/ DNRegAddKeysIfLogged
    \/ NNHandleHeartbeatIfLogged
    \/ DNRecvHeartbeatIfLogged
    \/ LoseHeartbeatRespIfLogged
    \/ BalancerStartIfLogged
    \/ BalancerPollIfLogged
    \/ BalancerCloseIfLogged
    \/ BalancerConnectIfLogged
    \/ ClientConnectIfLogged
    \/ DNTransferIfLogged
    \/ TargetCheckIfLogged
    \/ NNDeclareDeadIfLogged
    \/ EnterSafeModeIfLogged
    \/ LeaveSafeModeIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<l, vars>> /\ WF_<<l, vars>>(TraceNext)

TraceView == <<vars, l>>

TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l       |-> l,
      len     |-> Len(TraceLog),
      event   |-> IF l <= Len(TraceLog) THEN ev.name ELSE "DONE",
      nid     |-> IF l <= Len(TraceLog) THEN ev.nid ELSE "DONE",
      evState |-> IF l <= Len(TraceLog) THEN ev.state ELSE "DONE",
      evMsg   |-> IF l <= Len(TraceLog) /\ "msg" \in DOMAIN ev THEN ev.msg ELSE "DONE",
      now     |-> now,
      nnCur   |-> nnCur,
      nnKeys  |-> nnKeys,
      hbList  |-> hbList,
      dnPC    |-> dnPC,
      dnCur   |-> dnCur,
      dnKeys  |-> dnKeys,
      hbResp  |-> hbResp,
      balCur  |-> balCur,
      balDEK  |-> balDEK,
      cliDEK  |-> cliDEK,
      conns   |-> conns ]

=============================================================================
