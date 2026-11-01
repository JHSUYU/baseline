-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-09 (Category A: one totally ordered     *)
(* NDJSON log).                                                            *)
(*                                                                         *)
(* The workload TestQuorumJournalManager#testSingleWriter uses spy loggers *)
(* whose single-thread executor is a DirectExecutorService                 *)
(* (SpyQJournalUtil:51-69): every channel task runs on the test thread     *)
(* inside the AsyncLoggerSet fan-out loop, JN0 -> JN1 -> JN2.  The log is  *)
(* therefore a total order and each line maps to exactly one base action   *)
(* (instrumentation-spec.md, section 2).                                   *)
(*                                                                         *)
(* Every wrapper calls the base action unchanged, then checks the logged   *)
(* post-state.  The only silent step is the NN catch-up                    *)
(* (CatchupDuringFailover), which a QJM-level test never runs; it is       *)
(* pinned to the txid of the next logged StartLogSegment.                  *)
(***************************************************************************)
EXTENDS base, Json, IOUtils

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

\* Lines tagged "trace" (instrumentation-spec.md section 1); other output is ignored.
TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                 /\ x.tag = "trace"
                                 /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0

(***************************************************************************)
(* Constants derived from the log (bound with <- in Trace.cfg)             *)
(***************************************************************************)
TraceJNs  == {"jn0", "jn1", "jn2"}    \* MiniJournalCluster node indexes 0..2 (MJC:53)
TraceNoJN == "none"

LinesOf(e) == {i \in DOMAIN TraceLog : TraceLog[i].event = e}

TraceNumWriters ==
    LET W == {TraceLog[i].w : i \in {k \in DOMAIN TraceLog : "w" \in DOMAIN TraceLog[k]}}
    IN IF W = {} THEN 1 ELSE Max(W)

TraceMaxTxId ==
    Max({1} \cup {TraceLog[i].last : i \in LinesOf("SendEdits")}
            \cup {TraceLog[i].txid : i \in LinesOf("StartLogSegment")})

TraceMaxBatch ==
    Max({1} \cup {TraceLog[i].last - TraceLog[i].first + 1 : i \in LinesOf("SendEdits")})

(***************************************************************************)
(* Cursor and helpers                                                      *)
(***************************************************************************)
VARIABLE l

traceVars == <<jn, wr, ch, targetFired, l>>

logline == TraceLog[l]

IsEvent(e) == l <= Len(TraceLog) /\ logline.event = e

Has(f) == f \in DOMAIN logline

ToSet(s) == {s[i] : i \in DOMAIN s}

AsFile(x) == [s |-> x.s, e |-> x.e, ip |-> x.ip]

(***************************************************************************)
(* Post-state validation                                                   *)
(***************************************************************************)

\* JN j after the step equals the logged snapshot (field "jn").
ValidJN(j) ==
    LET t == logline.jn IN
    /\ jn'[j].prom  = t.prom
    /\ jn'[j].lwe   = t.lwe
    /\ jn'[j].sn    = t.sn
    /\ jn'[j].ct    = t.ct
    /\ jn'[j].cur   = t.cur
    /\ jn'[j].next  = t.next
    /\ jn'[j].segs  = {AsFile(t.segs[i]) : i \in DOMAIN t.segs}
    /\ jn'[j].paxos = {[ep |-> t.paxos[i].ep, seg |-> AsFile(t.paxos[i])] : i \in DOMAIN t.paxos}

\* Channel (w, j) after the step equals the logged snapshot (field "ch").
ValidCh(w, j) ==
    LET t == logline.ch IN
    /\ ch'[w][j].ipc = t.ipc
    /\ ch'[w][j].oos = t.oos
    /\ ch'[w][j].hb  = t.hb

\* The RequestInfo the task sent equals createReqInfo's snapshot (IPC:287-291), pre-state; the
\* committed txid is the one taken when the head task started (base HeadCt).
ValidReq(w, j) ==
    LET t == logline.req IN
    /\ wr[w].ep = t.ep
    /\ ch[w][j].ipc = t.sn
    /\ ch[w][j].hct = t.ct

\* The task at the head of the channel queue is the logged call.
ValidOp(w, j) ==
    /\ ch[w][j].q # <<>>
    /\ LET o == Head(ch[w][j].q) IN
       /\ o.k = logline.kind
       /\ IF Has("a") THEN o.a = logline.a ELSE TRUE
       /\ IF Has("b") THEN o.b = logline.b ELSE TRUE
       /\ IF Has("c") THEN o.c = logline.c ELSE TRUE
       /\ IF Has("seg") THEN o.f = AsFile(logline.seg) ELSE TRUE
       /\ IF Has("src") THEN o.src = logline.src ELSE TRUE

\* Writer w resolved a QuorumCall: the loggers whose futures succeeded (pre-state).
ValidResponders(w) == IF Has("okJNs") THEN wr[w].ok = ToSet(logline.okJNs) ELSE TRUE

Outcome(w, okPh) == wr'[w].ph = IF logline.outcome = "ok" THEN okPh ELSE "dead"

(***************************************************************************)
(* Channel and JN-side events                                              *)
(***************************************************************************)

\* A channel task whose own RPC got a reply (base ChannelCall).
TChannelCall ==
    /\ IsEvent("ChannelCall")
    /\ LET w == logline.w
           j == logline.j
       IN /\ ValidOp(w, j)
          /\ IF IsRI(logline.kind) THEN ValidReq(w, j) ELSE TRUE
          /\ HandleRPC(j, RpcOf(w, j, Head(ch[w][j].q))).ok = logline.ok
          /\ ChannelCall(w, j)
          /\ ValidJN(j)
          /\ ValidCh(w, j)
    /\ l' = l + 1

\* Out-of-sync task that sent a heartbeat (base ChannelHeartbeat).
TChannelHeartbeat ==
    /\ IsEvent("ChannelHeartbeat")
    /\ LET w == logline.w
           j == logline.j
       IN /\ ValidOp(w, j)
          /\ ValidReq(w, j)
          /\ ChannelHeartbeat(w, j)
          /\ ValidJN(j)
          /\ ValidCh(w, j)
    /\ l' = l + 1

\* Out-of-sync task within the heartbeat interval (base ChannelSkip).
TChannelSkip ==
    /\ IsEvent("ChannelSkip")
    /\ LET w == logline.w
           j == logline.j
       IN /\ ValidOp(w, j)
          /\ ChannelSkip(w, j)
          /\ ValidCh(w, j)
    /\ l' = l + 1

\* Task whose RPC could not reach the JN (base ChannelDown).
TChannelDown ==
    /\ IsEvent("ChannelDown")
    /\ LET w == logline.w
           j == logline.j
       IN /\ ValidOp(w, j)
          /\ ChannelDown(w, j)
          /\ ValidCh(w, j)
    /\ l' = l + 1

\* Lost request or reply (base MsgLoss).
TMsgLoss ==
    /\ IsEvent("MsgLoss")
    /\ LET w == logline.w
           j == logline.j
       IN /\ ValidOp(w, j)
          /\ MsgLoss(w, j, logline.lostReply)
          /\ ValidJN(j)
          /\ ValidCh(w, j)
    /\ l' = l + 1

\* A crashed writer's last RPC reaches the JN (base DeliverLate).
TDeliverLate ==
    /\ IsEvent("DeliverLate")
    /\ LET w == logline.w
           j == logline.j
       IN /\ DeliverLate(w, j)
          /\ ValidJN(j)
    /\ l' = l + 1

TJNCrash ==
    /\ IsEvent("JNCrash")
    /\ JNCrash(logline.j)
    /\ l' = l + 1

TPowerLoss ==
    /\ IsEvent("PowerLoss")
    /\ PowerLoss(logline.j)
    /\ l' = l + 1

TJNRestart ==
    /\ IsEvent("JNRestart")
    /\ JNRestart(logline.j)
    /\ ValidJN(logline.j)
    /\ l' = l + 1

TPartition ==
    /\ IsEvent("Partition")
    /\ Partition(logline.j)
    /\ l' = l + 1

THeal ==
    /\ IsEvent("Heal")
    /\ Heal(logline.j)
    /\ l' = l + 1

(***************************************************************************)
(* Writer events                                                           *)
(***************************************************************************)

TLaunch ==
    /\ IsEvent("Launch")
    /\ LET w == logline.w IN
       /\ Launch(w)
       /\ wr'[w].mode = logline.mode
       /\ wr'[w].ckpt = (IF Has("ckpt") THEN logline.ckpt ELSE 0)
    /\ l' = l + 1

TDoTailEdits ==
    /\ IsEvent("DoTailEdits")
    /\ LET w == logline.w IN
       /\ DoTailEdits(w)
       /\ wr'[w].applied = logline.applied
    /\ l' = l + 1

TResolveGetJournalState ==
    /\ IsEvent("ResolveGetJournalState")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolveGetJournalState(w)
       /\ Outcome(w, "newEpoch")
       /\ IF logline.outcome = "ok" THEN wr'[w].prop = logline.epoch ELSE TRUE
    /\ l' = l + 1

TResolveNewEpoch ==
    /\ IsEvent("ResolveNewEpoch")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ IF logline.outcome = "ok" THEN wr[w].acc = logline.lastSeg ELSE TRUE
       /\ ResolveNewEpoch(w)
       /\ IF logline.outcome = "ok"
          THEN /\ wr'[w].ep = logline.epoch
               /\ wr'[w].ph = IF logline.lastSeg = 0 THEN "recovered" ELSE "prepare"
          ELSE wr'[w].ph = "dead"
    /\ l' = l + 1

TResolvePrepareRecovery ==
    /\ IsEvent("ResolvePrepareRecovery")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolvePrepareRecovery(w)
       /\ CASE logline.outcome = "accept" -> /\ wr'[w].ph = "accept"
                                             /\ wr'[w].log = AsFile(logline.seg)
                                             /\ wr'[w].src = logline.src
            [] logline.outcome = "none"   -> wr'[w].ph = "recovered"
            [] OTHER                      -> wr'[w].ph = "dead"
    /\ l' = l + 1

TResolveAcceptRecovery ==
    /\ IsEvent("ResolveAcceptRecovery")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolveAcceptRecovery(w)
       /\ Outcome(w, "recFinalize")
    /\ l' = l + 1

TResolveRecoveryFinalize ==
    /\ IsEvent("ResolveRecoveryFinalize")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolveRecoveryFinalize(w)
       /\ Outcome(w, "recovered")
    /\ l' = l + 1

TCatchupDuringFailover ==
    /\ IsEvent("CatchupDuringFailover")
    /\ LET w == logline.w IN
       /\ CatchupDuringFailover(w, logline.ok)
       /\ wr'[w].applied = logline.applied
    /\ l' = l + 1

TRollingRollbackDiscard ==
    /\ IsEvent("RollingRollbackDiscard")
    /\ LET w == logline.w IN
       /\ wr[w].ckpt + 1 = logline.start
       /\ RollingRollbackDiscard(w)
    /\ l' = l + 1

TResolveDiscardSegments ==
    /\ IsEvent("ResolveDiscardSegments")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolveDiscardSegments(w)
       /\ Outcome(w, "caughtUp")
    /\ l' = l + 1

\* QJM.startLogSegment entry: the first segment of an incarnation is opened by openForWrite
\* (base OpenForWrite), later ones by rollEditLog (base StartLogSegment).  A QJM-level test has
\* no openForWrite read; a logged "openCheck" ("ok" | "fail") pins it when present.
TStartLogSegment ==
    /\ IsEvent("StartLogSegment")
    /\ LET w == logline.w IN
       /\ wr[w].next = logline.txid
       /\ \/ \E ok \in (IF Has("openCheck") THEN {logline.openCheck = "ok"} ELSE BOOLEAN) :
                OpenForWrite(w, ok)
          \/ StartLogSegment(w)
       /\ wr'[w].ph = "start"
    /\ l' = l + 1

TResolveStartLogSegment ==
    /\ IsEvent("ResolveStartLogSegment")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolveStartLogSegment(w)
       /\ Outcome(w, "inSeg")
    /\ l' = l + 1

TSendEdits ==
    /\ IsEvent("SendEdits")
    /\ LET w == logline.w IN
       /\ wr[w].seg = logline.seg
       /\ wr[w].next = logline.first
       /\ SendEdits(w, logline.last - logline.first + 1)
    /\ l' = l + 1

TResolveSendEdits ==
    /\ IsEvent("ResolveSendEdits")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolveSendEdits(w)
       /\ Outcome(w, "inSeg")
       /\ IF logline.outcome = "ok" THEN wr'[w].ct = logline.committed ELSE TRUE
    /\ l' = l + 1

TFinalizeLogSegment ==
    /\ IsEvent("FinalizeLogSegment")
    /\ LET w == logline.w IN
       /\ wr[w].seg = logline.first
       /\ wr[w].next - 1 = logline.last
       /\ FinalizeLogSegment(w)
    /\ l' = l + 1

TResolveFinalizeLogSegment ==
    /\ IsEvent("ResolveFinalizeLogSegment")
    /\ LET w == logline.w IN
       /\ ValidResponders(w)
       /\ ResolveFinalizeLogSegment(w)
       /\ Outcome(w, "between")
    /\ l' = l + 1

TPurgeLogsOlderThan ==
    /\ IsEvent("PurgeLogsOlderThan")
    /\ PurgeLogsOlderThan(logline.w)
    /\ l' = l + 1

TCloseWriter ==
    /\ IsEvent("CloseWriter")
    /\ CloseWriter(logline.w)
    /\ l' = l + 1

TWriterCrash ==
    /\ IsEvent("WriterCrash")
    /\ WriterCrash(logline.w, ToSet(logline.keep))
    /\ l' = l + 1

(***************************************************************************)
(* Silent step                                                             *)
(***************************************************************************)

\* A QJM-level test calls qjm.startLogSegment(txid) right after recoverUnfinalizedSegments; the
\* NN would first catch up (FSN:1427) and set nextTxId = lastAppliedTxId + 1 (FSN:1447-1450).
\* Enabled only when the next logged event is that writer's StartLogSegment, and pinned to its
\* txid.
SilentCatchup ==
    /\ l <= Len(TraceLog)
    /\ logline.event = "StartLogSegment"
    /\ LET w == logline.w IN
       /\ \E ok \in BOOLEAN : CatchupDuringFailover(w, ok)
       /\ wr'[w].next = logline.txid
    /\ UNCHANGED l

(***************************************************************************)
(* Spec                                                                    *)
(***************************************************************************)
TraceInit ==
    /\ Init        \* journals already formatted (TQJM:127); the log starts at Launch
    /\ l = 1

TraceDone ==
    /\ l > Len(TraceLog)
    /\ UNCHANGED traceVars

TraceNext ==
    \/ TraceDone
    \/ TChannelCall
    \/ TChannelHeartbeat
    \/ TChannelSkip
    \/ TChannelDown
    \/ TMsgLoss
    \/ TDeliverLate
    \/ TJNCrash
    \/ TPowerLoss
    \/ TJNRestart
    \/ TPartition
    \/ THeal
    \/ TLaunch
    \/ TDoTailEdits
    \/ TResolveGetJournalState
    \/ TResolveNewEpoch
    \/ TResolvePrepareRecovery
    \/ TResolveAcceptRecovery
    \/ TResolveRecoveryFinalize
    \/ TCatchupDuringFailover
    \/ TRollingRollbackDiscard
    \/ TResolveDiscardSegments
    \/ TStartLogSegment
    \/ TResolveStartLogSegment
    \/ TSendEdits
    \/ TResolveSendEdits
    \/ TFinalizeLogSegment
    \/ TResolveFinalizeLogSegment
    \/ TPurgeLogsOlderThan
    \/ TCloseWriter
    \/ TWriterCrash
    \/ SilentCatchup

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

TraceView == traceVars

\* The whole log was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [l           |-> l,
     len         |-> Len(TraceLog),
     event       |-> IF l <= Len(TraceLog) THEN logline.event ELSE "DONE",
     jn          |-> jn,
     wr          |-> wr,
     ch          |-> ch,
     targetFired |-> targetFired]
==============================================================================
