-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-12 (Category A: one NDJSON trace, one   *)
(* cursor `l`).  Replays TestAdhocWorkload12 (and its variants) against    *)
(* base.tla.  The event schema, hook points and field meanings are in      *)
(* instrumentation-spec.md; every wrapper below consumes exactly one event *)
(* of the matching name, calls the base action, and checks the post-state  *)
(* fields the event carries.                                               *)
(*                                                                         *)
(* Event envelope (one NDJSON line):                                       *)
(*   {"tag":"trace","ts":"<nanos>","event":{"name":N,"nid":ID,             *)
(*     "state":{"tick":T,...},"msg":{...}}}                                *)
(* nid is "nn" for NameNode events and the DataNode's DatanodeUuid for     *)
(* DataNode events; NN events about a DN name it in msg.dn.  tick is       *)
(* floor((Time.now() - T0) / tokenLifetimeMs), T0 = the wall clock read    *)
(* when the master BTSM is constructed, before generateKeys (BTSM:140-157).*)
(* Key maps are arrays of [keyId, expiryTick] pairs.                       *)
(*                                                                         *)
(* Completion: TraceSpec has weak fairness on TraceNext and Trace.cfg      *)
(* checks PROPERTIES TraceMatched, so a branch that cannot finish the      *)
(* trace is a failure, even if another branch finishes it.  Every choice   *)
(* the base spec leaves open is therefore fixed by the event that needs it:*)
(* the heartbeat channel by msg.ch (carried through the RPC's caller       *)
(* context, instrumentation-spec.md), the Monitor's starting point by      *)
(* NNInit's uptimeTicks, safe-mode kind by msg.kind, token slots by the    *)
(* lowest free index.  No wrapper looks ahead in the trace.                *)
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

Ev(k) == TraceLog[k].event

ASSUME Len(TraceLog) > 0
ASSUME Ev(1).name = "NNInit"

VARIABLE l      \* cursor: next trace line to match (1-indexed)

traceVars == <<l>>

Msg == Ev(l).msg
St  == Ev(l).state
Nid == Ev(l).nid

\* ============================================================================
\* VALUES DERIVED FROM THE TRACE (bound in Trace.cfg with <-)
\* ============================================================================

TraceDN == TLCEval({Ev(k).nid : k \in {j \in 1..Len(TraceLog) : Ev(j).nid # "nn"}})

\* Key update interval in ticks of one token lifetime (BTSM:206 exports both).
TraceI == Ev(1).msg.intervalMs \div Ev(1).msg.lifetimeMs

ASSUME Ev(1).msg.lifetimeMs > 0 /\ Ev(1).msg.intervalMs % Ev(1).msg.lifetimeMs = 0

\* The master's random serial before generateKeys (BTSM:154, 190).
TraceSerialStart == Ev(1).state.cur - 1

TraceMaxTime == TLCEval(
    LET ts == {Ev(k).state.tick : k \in 1..Len(TraceLog)}
    IN CHOOSE m \in ts : \A x \in ts : x <= m)

\* Slots: every master mint, every test-thread transfer and every NN-scheduled
\* transfer opens one.
IsSlotEvent(k) ==
    \/ Ev(k).name = "Mint" /\ Ev(k).msg.master
    \/ Ev(k).name = "TransferQueued" /\ Ev(k).msg.ctx = "test"
    \/ Ev(k).name = "ScheduleTransfer"

TraceXferIds == TLCEval(
    LET n == Cardinality({k \in 1..Len(TraceLog) : IsSlotEvent(k)})
    IN 1..(IF n = 0 THEN 1 ELSE n))

\* ============================================================================
\* HELPERS
\* ============================================================================

Range(s) == {s[j] : j \in DOMAIN s}

\* [[id, exp], ...] -> (id :> exp) @@ ...
KeysOf(s) == [k \in {p[1] : p \in Range(s)} |-> (CHOOSE p \in Range(s) : p[1] = k)[2]]

ExportOf(e) == [cur |-> e.cur, keys |-> KeysOf(e.keys)]

TypesOf(r) == [j \in 1..Len(r) |-> r[j].type]

IsEvent(n) == l <= Len(TraceLog) /\ Ev(l).name = n

\* Every event is matched at the tick it carries; TraceAdvanceTime moves the clock.
AtTick == St.tick = now

Adv == l' = l + 1

\* Lowest free token slot (the base actions pick any free slot; the trace pins
\* the choice so no symmetric branch is left open).
FreeSlot == CHOOSE i \in XferIds : xf[i].st = "none" /\ \A j \in XferIds : xf[j].st = "none" => i <= j

ReplyAfter(d, c) == IF c = "actor" THEN hbResp'[d] ELSE th'.cmds
StageAfter(d, c) == IF c = "actor" THEN hbStage'[d] ELSE th'.st

\* NNInit must match generateKeys (BTSM:190-197) at tick 0.  TraceInit checks
\* the same; as ASSUMEs a bad first event stops TLC with an error instead of
\* leaving no initial state, which TLC reports as "No error has been found".
ASSUME Ev(1).state.tick = 0
ASSUME Ev(1).state.next = Ev(1).state.cur + 1
ASSUME Ev(1).state.serial = Ev(1).state.next
ASSUME KeysOf(Ev(1).state.keys) = (Ev(1).state.cur :> 2 * I + L) @@ (Ev(1).state.next :> 3 * I + L)

\* ============================================================================
\* TRACE INIT: cold start.  The master BTSM was just constructed (event 1);
\* no DN has registered yet; every DN's actor is about to call
\* registerDatanode (BPSA:838-848).
\* ============================================================================

\* F13: Monitor.lastBlockKeyUpdate starts at 0 (HBM:540) on the monotonic clock
\* (Time.monotonicNow(), HBM:547), whose origin is the machine's boot.  NNInit's
\* uptimeTicks is floor(uptime / L) at T0, so monotonic time 0 lies in tick
\* -(uptimeTicks + 1) relative to T0 (uptime is not a whole number of ticks).
\* With RotationEnabled / RotationDue (base.tla) the first Monitor rotation is
\* then possible from tick I - uptimeTicks - 1 and due one tick later, the two
\* ticks in which the first poll past uptime > I can fall; with uptime > I + 1
\* ticks it is due at tick 0.
TraceInit ==
    LET e0 == Ev(1)
        k1 == e0.state.cur
        k2 == e0.state.next
    IN
    \* NNInit validates generateKeys (BTSM:190-197) at tick 0.
    /\ e0.state.tick = 0
    /\ k2 = k1 + 1
    /\ e0.state.serial = k2
    /\ KeysOf(e0.state.keys) = (k1 :> 2 * I + L) @@ (k2 :> 3 * I + L)
    /\ l = 2
    /\ now = 0
    /\ lastRot = -(e0.msg.uptimeTicks) - 1
    /\ rotPending = FALSE
    /\ nnEpoch = 0
    /\ nnSerial = k2
    /\ nnCur = k1
    /\ nnNext = k2
    /\ nnKeys = KeysOf(e0.state.keys)
    /\ safeMode = "off"                  \* BMSM:86 status OFF until activate (BMSM:172-188)
    /\ inHM = [d \in DN |-> FALSE]
    /\ needKeyUpdate = [d \in DN |-> FALSE]
    /\ choosable = [d \in DN |-> FALSE]
    /\ dnBpReg = [d \in DN |-> FALSE]
    /\ dnTokEn = [d \in DN |-> FALSE]
    /\ dnBTSM = [d \in DN |-> FALSE]
    /\ dnCur = [d \in DN |-> NoKey]
    /\ dnKeys = [d \in DN |-> EmptyKeys]
    /\ cmdQ = [d \in DN |-> <<>>]
    /\ stalled = [d \in DN |-> FALSE]
    /\ regStage = [d \in DN |-> "rpc"]
    /\ regExport = [d \in DN |-> NoExport]
    /\ hbStage = [d \in DN |-> "idle"]
    /\ hbResp = [d \in DN |-> <<>>]
    /\ th = ThIdle
    /\ xf = [i \in XferIds |-> NoXfer]
    /\ targetFired = FALSE

\* ============================================================================
\* ACTION WRAPPERS (one trace event each)
\* ============================================================================

\* ---- NameNode: Monitor and test rotations, marking ------------------------

\* Rotate: master updateKeys() (BTSM:260-281); msg.src = "monitor" (HBM:552) or
\* "test" (WL:99).  Post-state: the master's key state.
TRotate ==
    /\ IsEvent("Rotate") /\ AtTick
    /\ IF Msg.src = "monitor" THEN Rotate ELSE TestRotate
    /\ nnCur' = St.cur
    /\ nnNext' = St.next
    /\ nnSerial' = St.serial
    /\ nnKeys' = KeysOf(St.keys)
    /\ Adv

\* Mark: HBM:553-557.  msg.dns = the nodes marked = HeartbeatManager.datanodes.
TMark ==
    /\ IsEvent("Mark") /\ AtTick
    /\ {d \in DN : inHM[d]} = Range(Msg.dns)
    /\ Mark
    /\ \A d \in Range(Msg.dns) : needKeyUpdate'[d]
    /\ Adv

\* TestMark: WL:106 setNeedKeyUpdate(true) on the test thread.
TTestMark ==
    /\ IsEvent("TestMark") /\ AtTick
    /\ TestMark(Msg.dn)
    /\ needKeyUpdate'[Msg.dn]
    /\ Adv

\* ---- NameNode: heartbeat handler -------------------------------------------

\* HandleHeartbeat: DM.handleHeartbeat up to BM:1675 (or its early return).
\* msg.ch: "actor" (the BPServiceActor's own heartbeat) or "test" (WL:157);
\* msg.kind: "register" (DM:1867/1877) | "safemode" (DM:1885) | "normal";
\* msg.haskuc / msg.kuc: the exported keys (BM:1675); msg.nxfer: transfers in
\* the DNA_TRANSFER command (DM:1948-1951).
THandleHeartbeat ==
    /\ IsEvent("HandleHeartbeat") /\ AtTick
    /\ LET d == Msg.dn
           c == Msg.ch
       IN /\ Msg.kind = (IF ~inHM[d] THEN "register"
                         ELSE IF InSafeMode THEN "safemode" ELSE "normal")
          /\ HandleHeartbeat(d, c)
          /\ Len(SelectSeq(ReplyAfter(d, c), IsKuc)) = (IF Msg.haskuc THEN 1 ELSE 0)
          /\ Msg.haskuc => \E k \in 1..Len(ReplyAfter(d, c)) :
                              /\ IsKuc(ReplyAfter(d, c)[k])
                              /\ ReplyAfter(d, c)[k].ex = ExportOf(Msg.kuc)
          /\ StageAfter(d, c) = (IF Msg.haskuc THEN "exported" ELSE "inflight")
          /\ Cardinality(RespIds(ReplyAfter(d, c))) = Msg.nxfer
    /\ Adv

\* HbClear: BM:1676, on the same NN handler thread as its HandleHeartbeat
\* (msg.ch as there).
THbClear ==
    /\ IsEvent("HbClear") /\ AtTick
    /\ LET d == Msg.dn
           c == Msg.ch
       IN /\ HbClear(d, c)
          /\ ~needKeyUpdate'[d]
    /\ Adv

\* ---- DataNode: heartbeat replies --------------------------------------------

\* DeliverResp: BPSA:745-756 on the actor thread.  msg.cmds: the modeled command
\* types of the reply in the NN's array order ("XFER", "KUC", "REG").
TDeliverResp ==
    /\ IsEvent("DeliverResp") /\ AtTick
    /\ hbStage[Nid] = "inflight"
    /\ TypesOf(hbResp[Nid]) = Msg.cmds
    /\ DeliverResp(Nid)
    /\ Adv

\* HbRespLost: the actor's offerService caught an IOException for this
\* heartbeat (BPSA:805-807).  A non-empty reply in flight is lost; an empty one
\* changes nothing (DeliverResp of it enqueues nothing); if the NN never handled
\* the request, nothing is in flight.
THbRespLost ==
    /\ IsEvent("HbRespLost") /\ AtTick
    /\ IF hbStage[Nid] = "inflight" /\ hbResp[Nid] # <<>>
       THEN LoseResp(Nid)
       ELSE IF hbStage[Nid] = "inflight"
       THEN DeliverResp(Nid)
       ELSE UNCHANGED vars
    /\ Adv

\* TestRecvResp: WL:157 sendHeartBeat returned on the test thread (BPSA:583-590).
TTestRecvResp ==
    /\ IsEvent("TestRecvResp") /\ AtTick
    /\ th.st = "inflight" /\ th.dn = Nid
    /\ TypesOf(th.cmds) = Msg.cmds
    /\ TestRecvResp
    /\ Adv

\* ---- DataNode: worker addKeys (BTSM:228-244) ----------------------------------

\* msg.ctx: "kuc" (CPT, BPOS:788-795), "reg" (BPOS:436-440), "test" (WL:161 ->
\* BPOS:788-795 on the test thread); msg.excur: the export's currentKey;
\* msg.upd: updateCurrentKey.  Post-state: the worker's currentKey and allKeys.
TAddKeys ==
    /\ IsEvent("AddKeys") /\ AtTick
    /\ Msg.upd = TRUE
    /\ LET d == Nid IN
       /\ IF Msg.ctx = "kuc"
          THEN /\ cmdQ[d] # <<>>
               /\ IsKuc(Head(cmdQ[d]))
               /\ Head(cmdQ[d]).ex.cur = Msg.excur
               /\ ProcessCommand(d)
          ELSE IF Msg.ctx = "reg"
          THEN /\ regStage[d] = "btsm"
               /\ regExport[d].cur = Msg.excur
               /\ DnAddRegKeys(d)
          ELSE /\ Msg.ctx = "test"
               /\ th.st = "proc" /\ th.dn = d
               /\ th.cmds # <<>>
               /\ IsKuc(Head(th.cmds))
               /\ Head(th.cmds).ex.cur = Msg.excur
               /\ TestProcessCmd
       /\ dnCur'[d] = St.cur
       /\ dnKeys'[d] = KeysOf(St.keys)
    /\ Adv

\* ---- Registration -------------------------------------------------------------

\* RegExport: DM:1209.  msg.ex: the exported keys.
TRegExport ==
    /\ IsEvent("RegExport") /\ AtTick
    /\ RegExport(Msg.dn)
    /\ regExport'[Msg.dn] = ExportOf(Msg.ex)
    /\ Adv

\* RegInsert: DM:1300-1301 (known descriptor) or DM:1337-1338 (new descriptor).
\* msg.wasAlive: the descriptor was already in the heartbeat list.
TRegInsert ==
    /\ IsEvent("RegInsert") /\ AtTick
    /\ Msg.wasAlive = inHM[Msg.dn]
    /\ RegInsert(Msg.dn)
    /\ inHM'[Msg.dn]
    /\ Adv

\* PublishReg: BPOS:432.
TPublishReg ==
    /\ IsEvent("PublishReg") /\ AtTick
    /\ DnPublishReg(Nid)
    /\ dnBpReg'[Nid]
    /\ Adv

\* CreateBTSM: DN:2144 (first registration of a DN process only).
TCreateBTSM ==
    /\ IsEvent("CreateBTSM") /\ AtTick
    /\ DnCreateBTSM(Nid)
    /\ dnBTSM'[Nid] /\ dnTokEn'[Nid]
    /\ Adv

\* ReRegister: the CPT runs a DNA_REGISTER command (BPOS:681-689 -> BPSA:967).
TReRegister ==
    /\ IsEvent("ReRegister") /\ AtTick
    /\ cmdQ[Nid] # <<>>
    /\ Head(cmdQ[Nid]).type = "REG"
    /\ ProcessCommand(Nid)
    /\ regStage'[Nid] = "rpc"
    /\ Adv

\* ---- Transfers and tokens -----------------------------------------------------------

\* ScheduleTransfer: DD:685 addBlockToBeReplicated (msg.src, msg.dst).
TScheduleTransfer ==
    /\ IsEvent("ScheduleTransfer") /\ AtTick
    /\ xf[FreeSlot].st = "none"
    /\ ScheduleTransfer(Msg.src, Msg.dst)
    /\ xf'[FreeSlot].st = "nn"
    /\ xf'[FreeSlot].dst = Msg.dst
    /\ Adv

\* TransferQueued: DN:2891-2895 at the source (nid); msg.dst the target;
\* msg.ctx "cpt" (DNA_TRANSFER via the CPT) or "test" (WL:129).
TTransferQueued ==
    /\ IsEvent("TransferQueued") /\ AtTick
    /\ LET s == Nid
           t == Msg.dst
       IN IF Msg.ctx = "test"
          THEN /\ xf[FreeSlot].st = "none"
               /\ TestTransfer(s, t)
               /\ xf'[FreeSlot].st = "task"
               /\ xf'[FreeSlot].dst = t
          ELSE /\ cmdQ[s] # <<>>
               /\ Head(cmdQ[s]).type = "XFER"
               /\ \E i \in Head(cmdQ[s]).ids : xf[i].dst = t
               /\ ProcessCommand(s)
    /\ Adv

\* Mint: createPassword (BTSM:482-496).  msg.master: NN-minted (client token)
\* or DN-minted (DataTransfer, DN:3074, nid = source, msg.dst = target);
\* msg.keyId, msg.expTick: the token's identifier fields.
TMint ==
    /\ IsEvent("Mint") /\ AtTick
    /\ IF Msg.master
       THEN /\ xf[FreeSlot].st = "none"
            /\ ClientOp
            /\ xf'[FreeSlot].st = "minted"
            /\ xf'[FreeSlot].key = Msg.keyId
            /\ xf'[FreeSlot].exp = Msg.expTick
       ELSE LET cand == {i \in XferIds : xf[i].st = "task" /\ xf[i].src = Nid /\ xf[i].dst = Msg.dst}
            IN /\ cand # {}
               /\ LET i == CHOOSE i \in cand : \A j \in cand : i <= j
                  IN /\ Mint(i)
                     /\ xf'[i].st = "minted"
                     /\ xf'[i].key = Msg.keyId
                     /\ xf'[i].exp = Msg.expTick
    /\ Adv

\* CheckToken: retrievePassword at the verifier (nid).  msg.keyId, msg.expTick:
\* the identifier; msg.expired: BTSM:509-511 threw; msg.found: the lookup at
\* BTSM:514-516 returned a key (found = false is the target, BTSM:517-520).
TCheckToken ==
    /\ IsEvent("CheckToken") /\ AtTick
    /\ LET v == Nid
           cand == {i \in XferIds : TokenAt(v, i) /\ xf[i].key = Msg.keyId /\ xf[i].exp = Msg.expTick}
       IN /\ cand # {}
          /\ LET i == CHOOSE i \in cand : \A j \in cand : i <= j
             IN /\ TargetCheck(v, i)
                /\ IF Msg.expired
                   THEN /\ IsExpired(xf[i].exp)
                        /\ ~targetFired'
                   ELSE /\ ~IsExpired(xf[i].exp)
                        /\ targetFired' = ~Msg.found
    /\ Adv

\* ---- Safe mode --------------------------------------------------------------

\* SafeModeOn: FSN:5299 (msg.kind "manual") or BMSM:183 ("startup", at NN start).
TSafeModeOn ==
    /\ IsEvent("SafeModeOn") /\ AtTick
    /\ Msg.kind \in {"manual", "startup"}
    /\ EnterSafeModeKind(Msg.kind)
    /\ Adv

\* SafeModeOff: BMSM:408 / FSN:5320.
TSafeModeOff ==
    /\ IsEvent("SafeModeOff") /\ AtTick
    /\ LeaveSafeMode
    /\ Adv

\* ============================================================================
\* SILENT ACTION: the clock.  Enabled only when the next event carries a later
\* tick, so it fires exactly (next tick - now) times between two events.
\* ============================================================================

TraceAdvanceTime ==
    /\ l <= Len(TraceLog)
    /\ St.tick > now
    /\ AdvanceTime
    /\ UNCHANGED l

\* ============================================================================
\* SPEC AND PROPERTIES
\* ============================================================================

TraceNext ==
    \/ TraceAdvanceTime
    \/ TRotate
    \/ TMark
    \/ TTestMark
    \/ THandleHeartbeat
    \/ THbClear
    \/ TDeliverResp
    \/ THbRespLost
    \/ TTestRecvResp
    \/ TAddKeys
    \/ TRegExport
    \/ TRegInsert
    \/ TPublishReg
    \/ TCreateBTSM
    \/ TReRegister
    \/ TScheduleTransfer
    \/ TTransferQueued
    \/ TMint
    \/ TCheckToken
    \/ TSafeModeOn
    \/ TSafeModeOff

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [l           |-> l,
     event       |-> IF l <= Len(TraceLog) THEN Ev(l).name ELSE "<done>",
     eventNid    |-> IF l <= Len(TraceLog) THEN Ev(l).nid ELSE "",
     now         |-> now,
     nnCur       |-> nnCur,
     nnKeys      |-> nnKeys,
     needKeyUpdate |-> needKeyUpdate,
     inHM        |-> inHM,
     dnCur       |-> dnCur,
     dnKeys      |-> dnKeys,
     regStage    |-> regStage,
     hbStage     |-> hbStage,
     hbResp      |-> hbResp,
     cmdQ        |-> cmdQ,
     th          |-> th,
     xf          |-> xf,
     targetFired |-> targetFired]

=============================================================================
