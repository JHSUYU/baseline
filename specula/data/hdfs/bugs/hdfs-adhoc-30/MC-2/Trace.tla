-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-30), Category A: one          *)
(* linear NDJSON trace written by a single synchronized writer in the      *)
(* MiniDFSCluster JVM (all NameNodes and DataNodes share it).  Each event   *)
(* is emitted inside the critical section whose state change it records    *)
(* (instrumentation-spec.md), so file order is a valid linearization.      *)
(*                                                                         *)
(* The base spec models one DataNode (the recovery primary).  Events of     *)
(* other DataNodes are filtered out: the trace keeps the NN-wide events     *)
(* and the events whose "dn" is TraceDN (IOEnv.DN if set, else the primary  *)
(* of the first NNIssueRecovery, else the first DataNode seen).             *)
(*                                                                         *)
(* Every wrapper matches one event, calls the base action (never bypasses   *)
(* it), validates the post-state fields the event carries, and advances l.  *)
(* Silent steps only move NameNode txids to the value the next event        *)
(* reports; each is enabled only when that event needs it.                  *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, Naturals, Integers, FiniteSets, TLC

-----------------------------------------------------------------------------
(* Trace loading *)

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

RawLog == TLCEval(ndJsonDeserialize(JsonFile))

TraceMin(S) == CHOOSE x \in S : \A y \in S : x <= y
TraceMax(S) == CHOOSE x \in S : \A y \in S : y <= x

HasDN(e) == "dn" \in DOMAIN e

\* Events that belong to the whole nameservice, not to one DataNode.
NNWideEvents == {"DemoteNN", "PromoteNN", "NNCrash", "NNRestart"}

TraceDN == TLCEval(
    IF "DN" \in DOMAIN IOEnv THEN IOEnv.DN
    ELSE LET raw    == RawLog
             recIdx == {i \in DOMAIN raw : raw[i].event = "NNIssueRecovery"}
             dnIdx  == {i \in DOMAIN raw : HasDN(raw[i])}
         IN IF recIdx # {} THEN raw[TraceMin(recIdx)].dn
            ELSE raw[TraceMin(dnIdx)].dn)

TraceLog == TLCEval(LET raw == RawLog  dn == TraceDN IN
                SelectSeq(raw, LAMBDA e :
                    \/ e.event \in NNWideEvents
                    \/ HasDN(e) /\ e.dn = dn))

ASSUME Len(TraceLog) > 0

-----------------------------------------------------------------------------
(* Constants derived from the trace (Trace.cfg binds the base constants to these) *)
(* Every derived definition binds RawLog/TraceLog once with LET: TLC evaluates the        *)
(* cfg-bound constants before it caches RawLog/TraceLog, so each unbound reference would  *)
(* re-parse the NDJSON file (about O(n^4) line parses; harness INSTRUMENTATION.md sec. 6). *)

TraceIdxIn(tl, field) == {i \in DOMAIN tl : field \in DOMAIN tl[i]}
TraceIdx(field) == TraceIdxIn(TraceLog, field)

TraceNN == TLCEval(LET tl == TraceLog IN {tl[i].nn : i \in TraceIdxIn(tl, "nn")})

\* HA iff some NN reports STANDBY or an HA transition is traced.
TraceHA == TLCEval(LET tl == TraceLog IN
    \E i \in DOMAIN tl :
        \/ tl[i].event \in {"DemoteNN", "PromoteNN"}
        \/ "st" \in DOMAIN tl[i] /\ tl[i].st = "STANDBY")

TraceInc == TLCEval(LET tl == TraceLog IN
    1..TraceMax({1} \cup {tl[i].inc : i \in TraceIdxIn(tl, "inc")}))

TraceRec == TLCEval(LET tl == TraceLog IN
    {tl[i].rec : i \in TraceIdxIn(tl, "rec")}
    \cup UNION {Range(tl[i].recs) : i \in TraceIdxIn(tl, "recs")})

\* The NN that is ACTIVE at the start: the first NN observed as ACTIVE (VersionRequest or
\* HBSend reporting ACTIVE, or a DemoteNN) before any PromoteNN; None if a promotion comes first.
TraceInitActive == TLCEval(
    LET tl  == TraceLog
        obs == {i \in DOMAIN tl :
                  \/ tl[i].event \in {"VersionRequest", "HBSend"} /\ tl[i].st = "ACTIVE"
                  \/ tl[i].event = "DemoteNN"}
        pro == {i \in DOMAIN tl : tl[i].event = "PromoteNN"}
        ha  == TraceHA
    IN IF obs = {}
       THEN IF ha THEN None ELSE CHOOSE n \in TraceNN : TRUE
       ELSE IF pro # {} /\ TraceMin(pro) < TraceMin(obs) THEN None
       ELSE tl[TraceMin(obs)].nn)

\* Durable shared-log end at the start.  NN txids start at 0 and silent steps raise them to the
\* reported values; an HA trace that starts with no active NN starts the log at the first
\* promotion's txid - 1 (PromoteNN opens its segment at logEnd + 1).
TraceInitLogEnd == TLCEval(
    LET tl  == TraceLog
        pro == {i \in DOMAIN tl : tl[i].event = "PromoteNN"}
    IN IF TraceInitActive = None /\ pro # {} THEN tl[TraceMin(pro)].txid - 1 ELSE 0)

-----------------------------------------------------------------------------
(* Cursor *)

VARIABLE l

traceVars == <<l>>

logline == TraceLog[l]

IsEvent(name) == l <= Len(TraceLog) /\ logline.event = name

\* NN ids are strings in the trace; a null bpServiceToActive is written as "null".
ActiveStr(v) == IF v = None THEN "null" ELSE v

-----------------------------------------------------------------------------
(* Initial state: base Init, except the durable log end (TraceInitLogEnd).  Keep in sync *)
(* with base.tla Init.  The trace must start before the DataNodes start (actors connecting). *)

TraceInit ==
    /\ l = 1
    /\ nnState = [n \in NN |-> IF n = InitActive THEN "ACTIVE" ELSE "STANDBY"]
    /\ nnTxid  = [n \in NN |-> 0]
    /\ logEnd  = TraceInitLogEnd
    /\ nnRecQ  = [n \in NN |-> <<>>]
    /\ curInc  = 1
    /\ bposReg = 0
    /\ bpStopped = [b \in Inc |-> FALSE]
    /\ bpNSInfo  = [b \in Inc |-> FALSE]
    /\ bpRegd    = [b \in Inc |-> FALSE]
    /\ bpServiceToActive   = [b \in Inc |-> None]
    /\ lastActiveClaimTxId = [b \in Inc |-> -1]
    /\ actorSt = [b \in Inc |-> [n \in NN |-> IF b = 1 THEN "connecting" ELSE "idle"]]
    /\ hsResp  = [b \in Inc |-> [n \in NN |-> "none"]]
    /\ hbResp  = [b \in Inc |-> [n \in NN |-> NoResp]]
    /\ cmdQ    = [b \in Inc |-> [n \in NN |-> <<>>]]
    /\ rec     = [r \in Rec |-> [pc |-> "none", by |-> None, bp |-> 0, nxt |-> 0]]
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(* NameNode events *)

\* FSNamesystem.internalReleaseLease -> DatanodeDescriptor.addBlockToBeRecovered (L723), this DN primary.
NNIssueRecoveryLogged ==
    /\ IsEvent("NNIssueRecovery")
    /\ NNIssueRecovery(logline.nn, logline.rec)
    /\ Len(nnRecQ'[logline.nn]) = logline.qlen
    /\ l' = l + 1

\* HAState.setStateInternal ACTIVE -> STANDBY; txid = reported txid after END_LOG_SEGMENT.
DemoteNNLogged ==
    /\ IsEvent("DemoteNN")
    /\ DemoteNN(logline.nn)
    /\ nnTxid'[logline.nn] = logline.txid
    /\ l' = l + 1

\* HAState.setStateInternal STANDBY -> ACTIVE; txid = START_LOG_SEGMENT txid.
PromoteNNLogged ==
    /\ IsEvent("PromoteNN")
    /\ PromoteNN(logline.nn)
    /\ nnTxid'[logline.nn] = logline.txid
    /\ l' = l + 1

\* NN process stops serving (crash, or MiniDFSCluster shutdown/restart).  "synced" (optional) is
\* the durable txid at that moment.
NNCrashLogged ==
    /\ IsEvent("NNCrash")
    /\ NNCrash(logline.nn)
    /\ "synced" \in DOMAIN logline => logEnd = logline.synced
    /\ l' = l + 1

NNRestartLogged ==
    /\ IsEvent("NNRestart")
    /\ NNRestart(logline.nn)
    /\ nnState'[logline.nn] = logline.st
    /\ nnTxid'[logline.nn] = logline.txid
    /\ l' = l + 1

-----------------------------------------------------------------------------
(* Actor handshake *)

\* BPServiceActor.connectToNNAndHandshake L308: versionRequest returned nsInfo (state st).
VersionRequestLogged ==
    /\ IsEvent("VersionRequest")
    /\ VersionRequest(logline.inc, logline.nn)
    /\ hsResp'[logline.inc][logline.nn] = logline.st
    /\ l' = l + 1

\* BPOfferService.verifyAndSetNamespaceInfo, inside the write lock: W1 result and whether this
\* was the BPOS's first handshake (setNamespaceInfo returned null -> initBlockPool -> addBlockPool).
VerifyAndSetNamespaceInfoLogged ==
    /\ IsEvent("VerifyAndSetNamespaceInfo")
    /\ LET b == logline.inc  n == logline.nn IN
       /\ logline.registered = ~bpNSInfo[b]
       /\ VerifyAndSetNamespaceInfo(b, n)
       /\ ActiveStr(bpServiceToActive'[b]) = logline.active
       /\ logline.registered => bposReg' = b
    /\ l' = l + 1

\* BPOfferService.registrationSucceeded, inside the write lock.
RegisterLogged ==
    /\ IsEvent("Register")
    /\ Register(logline.inc, logline.nn)
    /\ bpRegd'[logline.inc]
    /\ l' = l + 1

-----------------------------------------------------------------------------
(* Heartbeat *)

\* NN side, FSNamesystem.handleHeartbeat under the BM read lock: the response snapshot.  "inc"
\* (the DN actor's BPOS incarnation) travels in the RPC CallerContext; without it the event can
\* only belong to an incarnation whose actor to this NN is running with no response in flight.
HBSendLogged ==
    /\ IsEvent("HBSend")
    /\ \E b \in Inc :
         /\ "inc" \in DOMAIN logline => b = logline.inc
         /\ HBSend(b, logline.nn)
         /\ hbResp'[b][logline.nn] = [st |-> logline.st, txid |-> logline.txid, cmd |-> logline.recs]
    /\ l' = l + 1

\* DN side, BPOfferService.updateActorStatesFromHeartbeat, inside the write lock (finally).
\* outcome: "rejected" = the early return at L598; "assertFailed" = the assert at L615 threw;
\* else "applied".  For assertFailed the event is written before cleanUp's W2, so "active" is
\* checked against the view the assert saw; the W2 itself is checked by the ActorExit event.
HBRecvLogged ==
    /\ IsEvent("HBRecv")
    /\ LET b    == logline.inc
           n    == logline.nn
           resp == hbResp[b][n]
           rej  == resp.st = "ACTIVE" /\ bpServiceToActive[b] # n
                   /\ resp.txid <= lastActiveClaimTxId[b]
       IN
       /\ resp = [st |-> logline.st, txid |-> logline.txid, cmd |-> logline.recs]
       /\ (logline.outcome = "rejected") = rej
       /\ HBRecv(b, n)
       /\ (logline.outcome = "assertFailed") = (actorSt'[b][n] = "exited")
       /\ lastActiveClaimTxId'[b] = logline.lastTxid
       /\ IF logline.outcome = "assertFailed"
          THEN ActiveStr(bpServiceToActive[b]) = logline.active
          ELSE ActiveStr(bpServiceToActive'[b]) = logline.active
    /\ l' = l + 1

-----------------------------------------------------------------------------
(* Command acceptance *)

\* BPOfferService.processCommandFromActor, inside the R2 read-lock section, BlockRecoveryCommand only.
ProcessCmdLogged ==
    /\ IsEvent("ProcessCmd")
    /\ LET b == logline.inc  n == logline.nn IN
       /\ cmdQ[b][n] # <<>>
       /\ Head(cmdQ[b][n]) = logline.recs
       /\ logline.accepted = (bpServiceToActive[b] = n)
       /\ ProcessCmd(b, n)
       /\ \A k \in DOMAIN logline.recs :
            rec'[logline.recs[k]].pc =
                IF ~logline.accepted THEN "dropped" ELSE IF k = 1 THEN "pre" ELSE "wait"
    /\ l' = l + 1

-----------------------------------------------------------------------------
(* Recovery daemon *)

\* End of RecoveryTaskContiguous.recover's pre-commit phase: "proceed" just before syncBlock (L183);
\* "abort" at L161 / L169-172 / L176-181; "died" when getDatanodeID's NullPointerException
\* (L567) ends the daemon.
RecoverPreLogged ==
    /\ IsEvent("RecoverPre")
    /\ LET r == logline.rec IN
       \/ /\ logline.outcome = "proceed"
          /\ RecoverPre(r)
          /\ rec'[r].pc = "lookup"
       \/ /\ logline.outcome = "abort"
          /\ RecoverPre(r) \/ RecoverPreFail(r)
          /\ rec'[r].pc = "done"
       \/ /\ logline.outcome = "died"
          /\ bposReg # 0 /\ ~bpRegd[bposReg]
          /\ RecoverPre(r)
    /\ l' = l + 1

\* getActiveNamenodeForBP L602: the BPOS incarnation returned by BlockPoolManager.get (0 = null).
RecoverLookupLogged ==
    /\ IsEvent("RecoverLookup")
    /\ RecoverLookup(logline.rec)
    /\ IF logline.bpos = 0
       THEN rec'[logline.rec].pc = "done"
       ELSE /\ rec'[logline.rec].pc = "getActive"
            /\ rec'[logline.rec].bp = logline.bpos
    /\ l' = l + 1

\* getActiveNamenodeForBP L607: BPOfferService.getActiveNN under the read lock; "active" is the
\* NN of bpServiceToActive, or "null" (then L609 throws).
TargetCheckLogged ==
    /\ IsEvent("TargetCheck")
    /\ LET r == logline.rec IN
       /\ rec[r].pc = "getActive"
       /\ ActiveStr(bpServiceToActive[rec[r].bp]) = logline.active
       /\ TargetCheck(r)
       /\ targetFired' = (logline.active = "null")
    /\ l' = l + 1

-----------------------------------------------------------------------------
(* Actor exit and refresh *)

\* BPOfferService.shutdownActor, inside the write lock: post view, and whether bpServices became
\* empty (then dn.shutdownBlockPool deregisters the BPOS).  An actor that already exited through
\* an assert failure (merged into HBRecv) only has its post-state checked.
ActorExitLogged ==
    /\ IsEvent("ActorExit")
    /\ LET b == logline.inc  n == logline.nn IN
       /\ logline.lastActor = ({m \in NN \ {n} : InBpServices(b, m)} = {})
       /\ \/ ActorExit(b, n)
          \/ ActorStopExit(b, n)
          \/ /\ actorSt[b][n] = "exited"
             /\ UNCHANGED vars
       /\ ActiveStr(bpServiceToActive'[b]) = logline.active
    /\ l' = l + 1

\* BlockPoolManager.doRefreshNamenodes Step 3 (new BPOS for the bpid) and Step 4 (old BPOS stop).
RefreshAddLogged ==
    /\ IsEvent("RefreshAdd")
    /\ RefreshAdd
    /\ curInc' = logline.inc
    /\ l' = l + 1

RefreshRemoveLogged ==
    /\ IsEvent("RefreshRemove")
    /\ RefreshRemove(logline.inc)
    /\ l' = l + 1

-----------------------------------------------------------------------------
(* Silent steps.  The NN's txid moves with edits nobody traces (client writes, lease          *)
(* recovery's own edits).  Each step fires only when the next event reports a txid the model    *)
(* has not reached, and it moves exactly to that value, so there is no branching.               *)

\* The txid the next event requires of NN n as the active writer, or -1.
NextActiveTxid(n) ==
    IF l > Len(TraceLog) THEN -1
    ELSE IF logline.event = "HBSend" /\ logline.nn = n /\ logline.st = "ACTIVE" THEN logline.txid
    ELSE IF logline.event = "DemoteNN" /\ logline.nn = n THEN logline.txid - 1
    ELSE IF logline.event = "NNCrash" /\ logline.nn = n /\ "synced" \in DOMAIN logline
         THEN logline.synced
    ELSE -1

\* The txid the next event requires of NN n as a standby, or -1.
NextStandbyTxid(n) ==
    IF l <= Len(TraceLog) /\ logline.event = "HBSend" /\ logline.nn = n /\ logline.st = "STANDBY"
    THEN logline.txid ELSE -1

\* The active wrote (and synced) edits up to the txid the next event reports.
SilentLogEdits ==
    /\ \E n \in NN :
         /\ nnState[n] = "ACTIVE"
         /\ NextActiveTxid(n) > nnTxid[n]
         /\ NNLogEditsDurable(n, NextActiveTxid(n))
    /\ UNCHANGED traceVars

\* A standby applies only durable edits, so the active must have synced what it reports.
SilentLogEditsForStandby ==
    /\ \E s \in NN, a \in NN :
         /\ nnState[s] = "STANDBY"
         /\ NextStandbyTxid(s) > logEnd
         /\ nnState[a] = "ACTIVE"
         /\ NNLogEditsDurable(a, NextStandbyTxid(s))
    /\ UNCHANGED traceVars

\* The standby tailed durable edits up to the txid it reports next.
SilentTail ==
    /\ \E n \in NN :
         /\ NextStandbyTxid(n) > nnTxid[n]
         /\ NNTailEdits(n, NextStandbyTxid(n))
    /\ UNCHANGED traceVars

-----------------------------------------------------------------------------

TraceNext ==
    \/ NNIssueRecoveryLogged
    \/ DemoteNNLogged
    \/ PromoteNNLogged
    \/ NNCrashLogged
    \/ NNRestartLogged
    \/ VersionRequestLogged
    \/ VerifyAndSetNamespaceInfoLogged
    \/ RegisterLogged
    \/ HBSendLogged
    \/ HBRecvLogged
    \/ ProcessCmdLogged
    \/ RecoverPreLogged
    \/ RecoverLookupLogged
    \/ TargetCheckLogged
    \/ ActorExitLogged
    \/ RefreshAddLogged
    \/ RefreshRemoveLogged
    \/ SilentLogEdits
    \/ SilentLogEditsForStandby
    \/ SilentTail

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l          |-> l,
      len        |-> Len(TraceLog),
      event      |-> IF l <= Len(TraceLog) THEN logline ELSE "DONE",
      dn         |-> TraceDN,
      nnState    |-> nnState,
      nnTxid     |-> nnTxid,
      logEnd     |-> logEnd,
      nnRecQ     |-> nnRecQ,
      bposReg    |-> bposReg,
      active     |-> bpServiceToActive,
      lastClaim  |-> lastActiveClaimTxId,
      actorSt    |-> actorSt,
      hbResp     |-> hbResp,
      cmdQ       |-> cmdQ,
      rec        |-> rec,
      fired      |-> targetFired ]

=============================================================================
