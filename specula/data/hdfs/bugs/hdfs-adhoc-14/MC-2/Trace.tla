-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-14, BTSM:418).  Category A:   *)
(* one NDJSON file, a single cursor l.                                     *)
(*                                                                         *)
(* Line format (instrumentation-spec.md section 1):                        *)
(*   {"tag":"trace","ts":"<nanos>","event":{"name":<event>,"nid":<node>,    *)
(*    "state":{...},"msg":{...}}}                                          *)
(* NN ids "n1","n2"; DN ids "d1","d2",...; the client is "client".         *)
(* Key ids are integers; -1 means "no key"; "" means "no NameNode".        *)
(*                                                                         *)
(* Every event name is one base action (the first NNGenerateKeys of an NN  *)
(* is the Init state's; an optional "Init" line carries configuration and  *)
(* is skipped).  Each wrapper calls the base action with the event's       *)
(* parameters, validates the fields the event captured, and advances l.   *)
(* There are no silent actions.  Where an event must be matched to one of  *)
(* the in-flight operations, the oldest matching one is taken (a fixed     *)
(* choice: branches that a later event would kill break TraceMatched).     *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC, Integers, FiniteSets

\* Trace file: ../traces/<name>.ndjson, or the JSON environment variable.
JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

RawLog ==
    TLCEval(
        LET all == ndJsonDeserialize(JsonFile)
        IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                     /\ x.tag = "trace"
                                     /\ "event" \in DOMAIN x))

\* Replay starts at the first token-enabled NameNode start (its first
\* NNGenerateKeys, BTSM:174-198).  Anything before it belongs to a cluster
\* without block tokens (the workload's first, unencrypted cluster) and is not
\* part of the model.
FirstTokenIdx ==
    TLCEval(CHOOSE k \in 1..Len(RawLog) :
                /\ RawLog[k].event.name = "NNGenerateKeys"
                /\ \A j \in 1..(k - 1) : RawLog[j].event.name # "NNGenerateKeys")

TraceLog == TLCEval(SubSeq(RawLog, FirstTokenIdx, Len(RawLog)))

ASSUME Len(TraceLog) > 0

-----------------------------------------------------------------------------
(* Configuration derived from the trace (bound in Trace.cfg)               *)
-----------------------------------------------------------------------------
E(k) == TraceLog[k].event
MinSet(S) == CHOOSE x \in S : \A y \in S : x <= y
ToSet(s) == {s[j] : j \in DOMAIN s}

NNEventNames == {"NNGenerateKeys", "NNRotate", "NNMarkKeyUpdate", "NNHandleHeartbeat",
                 "NNHeartbeatClearKeyUpdate", "NNRegisterExport", "NNRegisterJoin",
                 "NNFailover", "NNScheduleReplication", "NNRemoveDeadDatanode",
                 "ClientAddBlock", "ClientGetBlockLocations", "ClientFetchDEK"}
DNEventNames == {"DNHandshake", "DNRegistrationSucceeded", "DNHandleHeartbeatResponse",
                 "DNProcessCommand", "DNTransferCreateToken", "DNSaslSendEncrypted",
                 "DNSaslReceiveEncrypted", "TargetCheck", "DNWriteBlockMirrorSecret"}

TraceNN == TLCEval({E(k).nid : k \in {j \in 1..Len(TraceLog) : E(j).name \in NNEventNames}})
TraceDN == TLCEval({E(k).nid : k \in {j \in 1..Len(TraceLog) : E(j).name \in DNEventNames}})

ASSUME TraceNN # {} /\ TraceDN # {}

FirstKeyGen(n) ==
    MinSet({k \in 1..Len(TraceLog) : E(k).name = "NNGenerateKeys" /\ E(k).nid = n})

\* BTSM:174-198 first keys of each NN (overrides base InitKeyIds).
TraceInitKeyIds ==
    TLCEval([n \in TraceNN |-> [cur  |-> E(FirstKeyGen(n)).state.cur,
                                 next |-> E(FirstKeyGen(n)).state.next]])

\* Optional "Init" line written by the harness: {"active", "overwrite", "repl",
\* "xferTargets"}.
MetaIdx == {k \in 1..Len(TraceLog) : E(k).name = "Init"}
MetaVal(f, dflt) ==
    IF MetaIdx # {} /\ f \in DOMAIN E(MinSet(MetaIdx)).state
    THEN E(MinSet(MetaIdx)).state[f]
    ELSE dflt

PipeLens == {Len(E(k).msg.pipe) : k \in {j \in 1..Len(TraceLog) : E(j).name = "ClientAddBlock"}}

TraceInitActive   == TLCEval(MetaVal("active", CHOOSE n \in TraceNN : TRUE))
TraceOverwriteQOP == TLCEval(MetaVal("overwrite", FALSE))
TraceRepl         == TLCEval(MetaVal("repl", IF PipeLens = {} THEN 1 ELSE MaxSet(PipeLens)))
TraceXferTargets  == TLCEval(MetaVal("xferTargets", 2))

-----------------------------------------------------------------------------
(* Cursor                                                                  *)
-----------------------------------------------------------------------------
VARIABLE l

traceVars == <<vars, l>>

logline == TraceLog[l]
ev  == logline.event
msg == ev.msg
st  == ev.state

\* Fresh key ids come from the trace (overrides base FreshKey): a restart's
\* first key (NNGenerateKeys.cur), or a rotation's new next key (NNRotate.next).
TraceFreshKey(n) ==
    IF logline.event.name = "NNGenerateKeys" THEN logline.event.state.cur
    ELSE logline.event.state.next

IsEvent(name) == l <= Len(TraceLog) /\ ev.name = name
Step == l' = l + 1

KeyOrNone(k) == IF k = -1 THEN None ELSE k
NNOrNone(s)  == IF s = "" THEN None ELSE s
\* access mode of the token -> operation kind
ModeKinds(m) == IF m = "WRITE" THEN {"write", "xfer"} ELSE {"read"}

\* The branch BTSM:404-421 takes for an operation in phase "check" (pre-state).
CheckOutcome(op) ==
    LET v == op.pipe[op.pos]
        t == op.tok
    IN IF TokExpired(t) THEN "expired"
       ELSE IF t.kid \notin dnKeys[v] THEN "nokey"
       ELSE IF t.sk # t.kid THEN "fired"
       ELSE "ok"

\* the oldest in-flight operation satisfying P
Oldest(P(_)) == MinSet({i \in OpIds : P(Op(i))})
Exists(P(_)) == \E i \in OpIds : P(Op(i))

-----------------------------------------------------------------------------
(* Action wrappers                                                         *)
-----------------------------------------------------------------------------
\* Optional configuration line from the harness.
TraceMeta ==
    /\ IsEvent("Init")
    /\ UNCHANGED vars
    /\ Step

\* The first key generation of an NN is the Init state's (BTSM:174-198).
TraceInitKeyGen ==
    /\ IsEvent("NNGenerateKeys")
    /\ l = FirstKeyGen(ev.nid)
    /\ nnCur[ev.nid] = st.cur
    /\ nnNext[ev.nid] = st.next
    /\ nnKeys[ev.nid] = ToSet(st.keys)
    /\ UNCHANGED vars
    /\ Step

\* A later key generation of the same NN: the process restarted.
TraceNNRestart ==
    /\ IsEvent("NNGenerateKeys")
    /\ l # FirstKeyGen(ev.nid)
    /\ NNRestart(ev.nid)
    /\ nnCur'[ev.nid] = st.cur
    /\ nnNext'[ev.nid] = st.next
    /\ nnKeys'[ev.nid] = ToSet(st.keys)
    /\ Step

TraceNNRotate ==
    /\ IsEvent("NNRotate")
    /\ NNRotate(ev.nid)
    /\ nnCur'[ev.nid] = st.cur
    /\ nnNext'[ev.nid] = st.next
    /\ nnKeys'[ev.nid] = ToSet(st.keys)
    /\ Step

TraceNNMarkKeyUpdate ==
    /\ IsEvent("NNMarkKeyUpdate")
    /\ NNMarkKeyUpdate(ev.nid)
    /\ live[ev.nid] = ToSet(msg.marked)
    /\ needKU'[ev.nid] = ToSet(st.needKU)
    /\ Step

TraceNNHandleHeartbeat ==
    /\ IsEvent("NNHandleHeartbeat")
    /\ NNHandleHeartbeat(ev.nid, msg.dn)
    /\ hb'[ev.nid][msg.dn].reg = msg.reg
    /\ (hb'[ev.nid][msg.dn].ku # NoEx) = msg.ku
    /\ IF msg.ku
       THEN /\ hb'[ev.nid][msg.dn].ku.cur = msg.kuCur
            /\ hb'[ev.nid][msg.dn].ku.keys = ToSet(msg.kuKeys)
       ELSE TRUE
    /\ hb'[ev.nid][msg.dn].xfer = msg.xfer
    /\ hb'[ev.nid][msg.dn].ha = msg.ha
    /\ Step

TraceNNHeartbeatClearKeyUpdate ==
    /\ IsEvent("NNHeartbeatClearKeyUpdate")
    /\ NNHeartbeatClearKeyUpdate(ev.nid, msg.dn)
    /\ needKU'[ev.nid] = ToSet(st.needKU)
    /\ Step

TraceNNRegisterExport ==
    /\ IsEvent("NNRegisterExport")
    /\ NNRegisterExport(ev.nid, msg.dn)
    /\ reg'[ev.nid][msg.dn].ex.cur = msg.exCur
    /\ reg'[ev.nid][msg.dn].ex.keys = ToSet(msg.exKeys)
    /\ Step

TraceNNRegisterJoin ==
    /\ IsEvent("NNRegisterJoin")
    /\ NNRegisterJoin(ev.nid, msg.dn)
    /\ live'[ev.nid] = ToSet(st.live)
    /\ Step

TraceNNFailover ==
    /\ IsEvent("NNFailover")
    /\ NNFailover(msg.from, ev.nid)
    /\ needKU'[ev.nid] = ToSet(st.needKU)
    /\ Step

TraceNNScheduleReplication ==
    /\ IsEvent("NNScheduleReplication")
    /\ NNScheduleReplication(ev.nid, msg.src, msg.targets)
    /\ Step

TraceNNRemoveDeadDatanode ==
    /\ IsEvent("NNRemoveDeadDatanode")
    /\ NNRemoveDeadDatanode(ev.nid, msg.dn)
    /\ live'[ev.nid] = ToSet(st.live)
    /\ Step

\* The new operation carries a token with the recorded key id.
NewOpHasKid(kind) ==
    \E op \in ops' : op.id = nextOp /\ op.k = kind /\ op.tok.kid = msg.kid

TraceClientAddBlock ==
    /\ IsEvent("ClientAddBlock")
    /\ ClientAddBlock(ev.nid, msg.pipe)
    /\ NewOpHasKid("write")
    /\ Step

TraceClientGetBlockLocations ==
    /\ IsEvent("ClientGetBlockLocations")
    /\ ClientGetBlockLocations(ev.nid)
    /\ NewOpHasKid("read")
    /\ Step

TraceClientFetchDEK ==
    /\ IsEvent("ClientFetchDEK")
    /\ ClientFetchDEK(ev.nid)
    /\ cliDek' = msg.kid
    /\ Step

ConnectMatch(op) ==
    /\ op.ph = "connect"
    /\ op.tok.kid = msg.kid
    /\ op.k \in ModeKinds(msg.mode)
    \* (IF, not \/: TLC splits an action-level disjunction and would evaluate
    \* op.pipe[1] on an empty pipeline)
    /\ IF op.pipe = <<>> THEN TRUE ELSE op.pipe[1] = msg.dn

TraceClientConnect ==
    /\ IsEvent("ClientConnect")
    /\ Exists(ConnectMatch)
    \* SDTC:234-235 the client's DataEncryptionKey (cached or just fetched)
    /\ cliDek = msg.dek
    /\ ClientConnect(Oldest(ConnectMatch), msg.dn)
    /\ Step

TraceDNHandshake ==
    /\ IsEvent("DNHandshake")
    /\ DNHandshake(ev.nid, msg.nn)
    /\ astate'[ev.nid][msg.nn] = msg.state
    /\ Step

TraceDNRegistrationSucceeded ==
    /\ IsEvent("DNRegistrationSucceeded")
    \* BPOS:437-438 the updateCurrentKey decision
    /\ (astate[ev.nid][msg.nn] \in {None, "active"}) = msg.updateCurrentKey
    /\ DNRegistrationSucceeded(ev.nid, msg.nn)
    /\ dnCur'[ev.nid] = st.cur
    /\ dnKeys'[ev.nid] = ToSet(st.keys)
    /\ Step

TraceDNHandleHeartbeatResponse ==
    /\ IsEvent("DNHandleHeartbeatResponse")
    /\ hb[msg.nn][ev.nid].st = "resp"
    \* the response the DN received is the one the NN built
    /\ (hb[msg.nn][ev.nid].ku # NoEx) = msg.ku
    /\ hb[msg.nn][ev.nid].reg = msg.reg
    /\ hb[msg.nn][ev.nid].xfer = msg.xfer
    /\ hb[msg.nn][ev.nid].ha = msg.ha
    /\ DNHandleHeartbeatResponse(ev.nid, msg.nn)
    /\ bpActive'[ev.nid] = NNOrNone(st.bpActive)
    /\ astate'[ev.nid][msg.nn] = st.astate
    /\ Step

TraceDNProcessCommand ==
    /\ IsEvent("DNProcessCommand")
    /\ cmdQ[ev.nid][msg.nn] # <<>>
    /\ Head(cmdQ[ev.nid][msg.nn]).t = msg.type
    \* BPOS:692-698 active or standby at processing time
    /\ (bpActive[ev.nid] = msg.nn) = msg.isActive
    /\ DNProcessCommand(ev.nid, msg.nn)
    /\ dnCur'[ev.nid] = KeyOrNone(st.cur)
    /\ dnKeys'[ev.nid] = ToSet(st.keys)
    /\ Step

XferTokMatch(op) ==
    /\ op.ph = "xferTok"
    /\ op.src = ev.nid
    /\ op.pipe = msg.targets

TraceDNTransferCreateToken ==
    /\ IsEvent("DNTransferCreateToken")
    /\ Exists(XferTokMatch)
    /\ LET i == Oldest(XferTokMatch) IN
       /\ DNTransferCreateToken(i)
       /\ \E op \in ops' : op.id = i /\ op.tok.kid = msg.kid
    /\ Step

SendMatch(op) ==
    /\ op.ph = "dek"
    /\ Sender(op) = ev.nid
    /\ op.tok.kid = msg.kid

TraceDNSaslSendEncrypted ==
    /\ IsEvent("DNSaslSendEncrypted")
    /\ Exists(SendMatch)
    /\ LET i == Oldest(SendMatch) IN
       \* DXC:823-829 secret snapshot used by updateToken (-1: no re-sign)
       /\ Op(i).sec = KeyOrNone(msg.sec)
       \* BTSM:536-538 the DEK is built from this DN's currentKey
       /\ dnCur[ev.nid] = msg.dek
       /\ DNSaslSendEncrypted(i)
    /\ Step

RecvMatch(op) ==
    /\ op.ph = "sasl"
    /\ op.pipe[op.pos] = ev.nid
    /\ op.dek = msg.dek

TraceDNSaslReceiveEncrypted ==
    /\ IsEvent("DNSaslReceiveEncrypted")
    /\ Exists(RecvMatch)
    \* BTSM:556-562 the DEK lookup outcome
    /\ (Ready(ev.nid) /\ msg.dek \in dnKeys[ev.nid]) = msg.ok
    /\ DNSaslReceiveEncrypted(Oldest(RecvMatch))
    /\ Step

CheckMatch(op) ==
    /\ op.ph = "check"
    /\ op.pipe[op.pos] = ev.nid
    /\ op.tok.kid = msg.kid
    /\ op.k \in ModeKinds(msg.mode)

TraceTargetCheck ==
    /\ IsEvent("TargetCheck")
    /\ Exists(CheckMatch)
    \* the branch of BTSM:404-421 the DN took (ok / fired = line 418 /
    \* nokey = line 518 / expired = line 365)
    /\ CheckOutcome(Op(Oldest(CheckMatch))) = msg.outcome
    /\ TargetCheck(Oldest(CheckMatch))
    /\ Step

MirrorMatch(op) ==
    /\ op.ph = "mirror"
    /\ op.pipe[op.pos] = ev.nid
    /\ op.tok.kid = msg.kid

TraceDNWriteBlockMirrorSecret ==
    /\ IsEvent("DNWriteBlockMirrorSecret")
    /\ Exists(MirrorMatch)
    /\ LET i == Oldest(MirrorMatch) IN
       /\ Op(i).pipe[Op(i).pos + 1] = msg.target
       /\ DNWriteBlockMirrorSecret(i)
       /\ \E op \in ops' : op.id = i /\ op.sec = KeyOrNone(msg.sec)
    /\ Step

-----------------------------------------------------------------------------
TraceInit ==
    /\ Init
    /\ l = 1

TraceNext ==
    \/ TraceMeta
    \/ TraceInitKeyGen
    \/ TraceNNRestart
    \/ TraceNNRotate
    \/ TraceNNMarkKeyUpdate
    \/ TraceNNHandleHeartbeat
    \/ TraceNNHeartbeatClearKeyUpdate
    \/ TraceNNRegisterExport
    \/ TraceNNRegisterJoin
    \/ TraceNNFailover
    \/ TraceNNScheduleReplication
    \/ TraceNNRemoveDeadDatanode
    \/ TraceClientAddBlock
    \/ TraceClientGetBlockLocations
    \/ TraceClientFetchDEK
    \/ TraceClientConnect
    \/ TraceDNHandshake
    \/ TraceDNRegistrationSucceeded
    \/ TraceDNHandleHeartbeatResponse
    \/ TraceDNProcessCommand
    \/ TraceDNTransferCreateToken
    \/ TraceDNSaslSendEncrypted
    \/ TraceDNSaslReceiveEncrypted
    \/ TraceTargetCheck
    \/ TraceDNWriteBlockMirrorSecret

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

\* Debugging aid (enable with ALIAS TraceAlias in a scratch cfg).
TraceAlias ==
    [l |-> l, len |-> Len(TraceLog),
     event |-> IF l <= Len(TraceLog) THEN ev.name ELSE "<done>",
     nnCur |-> nnCur, needKU |-> needKU, live |-> live, dnCur |-> dnCur,
     dnKeys |-> dnKeys, cmdQ |-> cmdQ, ops |-> ops, cliDek |-> cliDek,
     targetFired |-> targetFired]

=============================================================================
