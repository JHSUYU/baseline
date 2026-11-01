-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-11). Category A: one linear   *)
(* NDJSON trace, cursor l. Each wrapper matches one event, calls the base   *)
(* action, checks the post-state against the fields the event carries       *)
(* (instrumentation-spec.md section 2), and advances l.                     *)
(*                                                                         *)
(* Event envelope (adhoc java-harness.md SpeculaTrace):                     *)
(*   {"tag":"trace","ts":"<nanos>","event":{"name":..,"nid":..,             *)
(*    "state":{..},"msg":{..}}}                                             *)
(* nid is the emitting node: "nn<i>" for NameNode i, "dn<i>" for DataNode i.*)
(* Key ids are the implementation's int serials. MK maps them to model ids  *)
(* <<nn, incarnation, serial>>: an incarnation's first currentKey is        *)
(* serial0 + 1 (BTSM:190-192), and its NNStart event records it.            *)
(* A null key id is written as -1, a null node id as "null".                *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC, FiniteSets, Integers

-----------------------------------------------------------------------------
(* Trace loading                                                            *)

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

\* Lines tagged "trace" only; anything else the harness writes is ignored.
TraceLog == TLCEval(
    SelectSeq(ndJsonDeserialize(JsonFile),
              LAMBDA x : "tag" \in DOMAIN x /\ x.tag = "trace"))

ASSUME Len(TraceLog) > 0

Ev(i) == TraceLog[i].event

NNEvents == {"NNStart", "MonitorFirstPass", "RollKeys", "Sweep", "NNRegister",
             "NNRegExport", "NNRegJoin", "NNHeartbeat", "BlockReport", "GetDek",
             "SafeModeEnter", "SafeModeLeave", "Failover"}
DNEvents == {"DNRegistered", "DNHeartbeatResponse", "DNHeartbeatFailed",
             "DNTakeRegister", "DNKeyUpdate", "Lookup", "DNStart"}

\* Every event is known, and its node ids are configured NNs/DNs.
ASSUME \A i \in 1..Len(TraceLog) :
         \/ Ev(i).name = "Init"
         \/ Ev(i).name \in NNEvents /\ Ev(i).nid \in NNs
         \/ Ev(i).name \in DNEvents /\ Ev(i).nid \in DNs

\* Key-serial bases of the NN incarnations in this trace.
Bases == TLCEval(
    {[nn |-> Ev(i).nid, inc |-> Ev(i).msg.inc, base |-> Ev(i).state.cur - 1] :
        i \in {j \in 1..Len(TraceLog) : Ev(j).name = "NNStart"}})

\* Keys per incarnation in one trace stay far below this.
MaxSerialSpan == 100000

MK(id) ==
    LET B == {b \in Bases : b.base < id /\ id <= b.base + MaxSerialSpan}
    IN IF B = {} THEN <<"unmapped", 0, id>>
       ELSE LET b == CHOOSE x \in B : TRUE IN Key(b.nn, b.inc, id - b.base)

KeyOrNull(id) == IF id = -1 THEN Null ELSE MK(id)
KeySet(s) == {MK(s[i]) : i \in DOMAIN s}
NodeOrNull(x) == IF x = "null" THEN Null ELSE x
NodeSet(s) == {s[i] : i \in DOMAIN s}

-----------------------------------------------------------------------------
(* Cursor                                                                   *)

VARIABLE l

traceVars == <<vars, l>>

E == TraceLog[l].event

IsEvent(nm) == l <= Len(TraceLog) /\ E.name = nm

Step == l' = l + 1

-----------------------------------------------------------------------------
(* Post-state checks (the fields each event carries)                        *)

\* NN master keys after the event: state.cur, state.next.
NNKeysOK(n, st) ==
    /\ Key(n, nnInc'[n], nnTop'[n] - 1) = MK(st.cur)
    /\ Key(n, nnInc'[n], nnTop'[n]) = MK(st.next)

\* An export (ExportedBlockKeys) carried by a message: msg.cur, msg.keys.
ExpOK(e, m) ==
    /\ ExpCur(e) = MK(m.cur)
    /\ ExpKeys(e) = KeySet(m.keys)

\* DN worker after the event: state.cur (-1 = null), state.keys.
DNKeysOK(d, st) ==
    /\ dnCur'[d] = KeyOrNull(st.cur)
    /\ dnKeys'[d] = KeySet(st.keys)

-----------------------------------------------------------------------------
(* Action wrappers: one event each                                          *)

\* The harness's node-id mapping line (adhoc java-harness.md).
TInit ==
    /\ IsEvent("Init")
    /\ UNCHANGED vars
    /\ Step

\* BM:546 -> BTSM constructor -> generateKeys (BTSM:140-158, 174-198).
\* Incarnation 1 is Init; a later one is NNRestart.
TNNStart ==
    /\ IsEvent("NNStart")
    /\ LET n == E.nid IN
       /\ IF E.msg.inc = 1
            THEN /\ nnInc[n] = 1
                 /\ firstPass[n]
                 /\ UNCHANGED vars
            ELSE /\ E.msg.inc = nnInc[n] + 1
                 /\ NNRestart(n)
       /\ NNKeysOK(n, E.state)
    /\ Step

\* HM:543-559, the first loop iteration of this Monitor. The model assumes the
\* pass runs before RPC starts (base.tla RpcUp), so its sweep flags nobody;
\* msg.flagged checks that assumption.
TMonitorFirstPass ==
    /\ IsEvent("MonitorFirstPass")
    /\ LET n == E.nid IN
       /\ MonitorFirstPass(n)
       /\ (nnTop'[n] = nnTop[n] + 1) = E.msg.rolled
       /\ NodeSet(E.msg.flagged) = {}
       /\ NNKeysOK(n, E.state)
    /\ Step

\* HM:552 shouldUpdateBlockKey returned true on a later iteration.
TRollKeys ==
    /\ IsEvent("RollKeys")
    /\ LET n == E.nid IN
       /\ RollKeys(n)
       /\ NNKeysOK(n, E.state)
    /\ Step

\* HM:553-557 after the synchronized sweep.
TSweep ==
    /\ IsEvent("Sweep")
    /\ LET n == E.nid IN
       /\ SweepNeedKeyUpdate(n)
       /\ hbSet[n] = NodeSet(E.msg.flagged)
    /\ Step

\* DM.registerDatanode returned (DM:1311 or after DM:1341): export and join.
TNNRegister ==
    /\ IsEvent("NNRegister")
    /\ ~SplitRegistration
    /\ LET n == E.nid
           d == E.msg.dn
       IN /\ NNRegisterDatanode(n, d)
          /\ ExpOK(reg'[n][d].exp, E.msg)
    /\ Step

\* Split registration (Scenario 3 variants): export at DM:1209 ...
TNNRegExport ==
    /\ IsEvent("NNRegExport")
    /\ SplitRegistration
    /\ LET n == E.nid
           d == E.msg.dn
       IN /\ NNRegisterDatanode(n, d)
          /\ ExpOK(reg'[n][d].exp, E.msg)
    /\ Step

\* ... and the join (DM:1300 / DM:1332-1337).
TNNRegJoin ==
    /\ IsEvent("NNRegJoin")
    /\ NNRegJoin(E.nid, E.msg.dn)
    /\ Step

\* BPOS.registrationSucceeded after addKeys (BPOS:436-440).
TDNRegistered ==
    /\ IsEvent("DNRegistered")
    /\ LET d == E.nid
           n == E.msg.nn
       IN /\ (actorState[n][d] \in {"none", "active"}) = E.msg.upd
          /\ DNRegistrationSucceeded(n, d)
          /\ DNKeysOK(d, E.state)
    /\ Step

\* DM.handleHeartbeat returned (FSN:4495-4498): the commands built, the flag after.
TNNHeartbeat ==
    /\ IsEvent("NNHeartbeat")
    /\ LET n == E.nid
           d == E.msg.dn
       IN /\ nnSafe[n] = E.state.safe
          /\ NNHandleHeartbeat(n, d)
          /\ resp'[n][d].cmd = E.msg.cmd
          /\ IF E.msg.cmd = "key" THEN ExpOK(resp'[n][d].exp, E.msg) ELSE TRUE
          /\ needKU'[n][d] = E.state.flag
    /\ Step

\* BPSA:733-756 after the reply's commands were queued.
TDNHeartbeatResponse ==
    /\ IsEvent("DNHeartbeatResponse")
    /\ LET d == E.nid
           n == E.msg.nn
       IN /\ resp[n][d] # Null
          /\ resp[n][d].cmd = E.msg.cmd
          /\ resp[n][d].ha = E.msg.ha
          /\ DNReceiveResponse(n, d)
          /\ bpActive'[d] = NodeOrNull(E.state.active)
    /\ Step

\* BPSA:791-807: the heartbeat RPC failed. If the NN built a reply (an
\* NNHeartbeat event came first), the reply is lost; otherwise the call never
\* reached DM.handleHeartbeat's normal return and nothing changed.
TDNHeartbeatFailed ==
    /\ IsEvent("DNHeartbeatFailed")
    /\ IF resp[E.msg.nn][E.nid] # Null
         THEN LoseResponse(E.msg.nn, E.nid)
         ELSE UNCHANGED vars
    /\ Step

\* BPOS:681-688: the command thread took DNA_REGISTER.
TDNTakeRegister ==
    /\ IsEvent("DNTakeRegister")
    /\ DNTakeRegisterCommand(E.msg.nn, E.nid)
    /\ Step

\* BPOS:788-795 / 828-836 after addKeys.
TDNKeyUpdate ==
    /\ IsEvent("DNKeyUpdate")
    /\ LET d == E.nid
           n == E.msg.nn
       IN /\ (bpActive[d] = n) = E.msg.active
          /\ DNProcessKeyCommand(n, d)
          /\ DNKeysOK(d, E.state)
    /\ Step

\* NNRPC.blockReport processed (NNRPC:1643-1690).
TBlockReport ==
    /\ IsEvent("BlockReport")
    /\ LET n == E.nid IN
       /\ DNBlockReport(n, E.msg.dn)
       /\ nnSafe'[n] = E.state.safe
    /\ Step

\* NNRPC.getDataEncryptionKey (NNRPC:1939-1943).
TGetDek ==
    /\ IsEvent("GetDek")
    /\ ClientGetDek(E.nid)
    /\ cDek'.key = MK(E.msg.keyId)
    /\ Step

\* BPTSM.retrieveDataEncryptionKey (BPTSM:171-174), around the target call.
\* The DEK came from the client cache or from a peer DN's worker; the key id
\* decides which.
TLookup ==
    /\ IsEvent("Lookup")
    /\ LET d == E.nid
           id == MK(E.msg.keyId)
       IN /\ LookupOutcome(d, id) = E.msg.outcome
          /\ (id \in dnKeys[d]) = E.state.hasKey
          /\ dnCur[d] = KeyOrNull(E.state.cur)
          /\ \/ /\ DekUsable
                /\ cDek.key = id
                /\ ClientConnect(d)
             \/ \E s \in DNs :
                  /\ dnCur[s] = id
                  /\ DnTransfer(s, d)
    /\ Step

TSafeModeEnter ==
    /\ IsEvent("SafeModeEnter")
    /\ EnterSafeMode(E.nid)
    /\ Step

TSafeModeLeave ==
    /\ IsEvent("SafeModeLeave")
    /\ LeaveSafeMode(E.nid)
    /\ Step

\* FSN.startActiveServices on the new active (nid), after
\* markAllDatanodesStaleAndSetKeyUpdateIfNeed.
TFailover ==
    /\ IsEvent("Failover")
    /\ Failover(E.msg.from, E.nid)
    /\ Step

\* A DataNode process started. The first start of a DN that is up in Init is
\* a no-op; a late DN starts; any other start is a restart.
TDNStart ==
    /\ IsEvent("DNStart")
    /\ LET d == E.nid IN
       IF ~dnUp[d] THEN DNStart(d)
       ELSE IF bpState[d] = "none" /\ \A n \in NNs : actor[n][d] = "conn"
              THEN UNCHANGED vars
              ELSE DNRestart(d)
    /\ Step

-----------------------------------------------------------------------------
(* Silent action                                                            *)

\* A new DEK is fetched while the client still holds a usable one: the cached
\* DEK was dropped first (new DFSClient or expiry, base.tla ClientDropDek).
\* Fires only right before a GetDek event.
TSilentDropDek ==
    /\ IsEvent("GetDek")
    /\ DekUsable
    /\ ClientDropDek
    /\ UNCHANGED l

-----------------------------------------------------------------------------

TraceInit ==
    /\ Init
    /\ l = 1

TraceNext ==
    \/ TInit
    \/ TNNStart
    \/ TMonitorFirstPass
    \/ TRollKeys
    \/ TSweep
    \/ TNNRegister
    \/ TNNRegExport
    \/ TNNRegJoin
    \/ TDNRegistered
    \/ TNNHeartbeat
    \/ TDNHeartbeatResponse
    \/ TDNHeartbeatFailed
    \/ TDNTakeRegister
    \/ TDNKeyUpdate
    \/ TBlockReport
    \/ TGetDek
    \/ TLookup
    \/ TSafeModeEnter
    \/ TSafeModeLeave
    \/ TFailover
    \/ TDNStart
    \/ TSilentDropDek

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

\* Every event was matched.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [l |-> l, len |-> Len(TraceLog),
     next |-> IF l <= Len(TraceLog) THEN TraceLog[l] ELSE "done",
     nnTop |-> nnTop, nnInc |-> nnInc, nnSafe |-> nnSafe, hbSet |-> hbSet,
     needKU |-> needKU, resp |-> resp, reg |-> reg, dnKeys |-> dnKeys,
     dnCur |-> dnCur, dnQ |-> dnQ, cDek |-> cDek, targetFired |-> targetFired]

=============================================================================
