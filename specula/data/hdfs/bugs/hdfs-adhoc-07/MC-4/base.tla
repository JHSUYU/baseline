--------------------------------- MODULE base ---------------------------------
(***************************************************************************)
(* hdfs-adhoc-07: HDFS Quorum Journal Manager (QJM) and the ad hoc check    *)
(* in Journal.acceptRecovery (pinned tree 734dd8a67cd).                     *)
(*                                                                          *)
(*   Journal.java:924  if (txnRange(currentSegment).contains(committedTxnId.get()) &&   *)
(*   Journal.java:925      !txnRange(segment).contains(committedTxnId.get())) {         *)
(*   Journal.java:926    throw new AssertionError("Cannot replace segment ... would     *)
(*                         discard already-committed txn ...")                         *)
(*                                                                          *)
(* Category A (distributed, message passing): NW writers (one QJM instance  *)
(* each, i.e. one NameNode incarnation) talk to the JournalNodes in JN over  *)
(* Hadoop IPC.                                                              *)
(*                                                                          *)
(* Granularity (modeling brief 3.1):                                        *)
(*  - Every Journal RPC handler is `synchronized`, so one JN handler run is  *)
(*    one atomic action.  The acceptRecovery handler is split by code path: *)
(*    TargetCheck is the path that reaches line 924; JNAcceptRecovery is    *)
(*    every other path; JNAcceptRecoveryCrash is the 976/977 crash window.  *)
(*  - Each writer->JN channel (IPCLoggerChannel) is a FIFO queue of tasks    *)
(*    run by one executor thread.  ChDispatch / ChHeartbeat / ChOutOfSync    *)
(*    are that thread picking up the head task; the RequestInfo (epoch,     *)
(*    committedTxId) is bound there (createReqInfo, IPCLoggerChannel:287).  *)
(*  - The writer's receipt of a reply is merged into the JN action (the     *)
(*    reply is recorded in wr[w].resp at once).  The writer's quorum steps  *)
(*    may use ANY subset of >= majority recorded successes, which is how a  *)
(*    reply that is still on the wire when waitForWriteQuorum returns is    *)
(*    represented (QuorumCall.getResults copies only what has arrived).     *)
(*  - The writer program follows QuorumJournalManager call order; each      *)
(*    quorum wait is one action (QuorumCall.waitFor).  Purge is fire-and-   *)
(*    forget and may be issued while another call is outstanding.          *)
(*                                                                          *)
(* Abbreviations for source files (all under hadoop-hdfs-project/           *)
(* hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/):                      *)
(*   J    qjournal/server/Journal.java                                      *)
(*   JRS  qjournal/server/JournalNodeRpcServer.java                         *)
(*   GJES qjournal/server/GetJournalEditServlet.java                        *)
(*   JNS  qjournal/server/JNStorage.java                                    *)
(*   QJM  qjournal/client/QuorumJournalManager.java                         *)
(*   ILC  qjournal/client/IPCLoggerChannel.java                             *)
(*   ALS  qjournal/client/AsyncLoggerSet.java                               *)
(*   QC   qjournal/client/QuorumCall.java                                   *)
(*   QOS  qjournal/client/QuorumOutputStream.java                           *)
(*   SRC  qjournal/client/SegmentRecoveryComparator.java                    *)
(*   FJM  server/namenode/FileJournalManager.java                           *)
(*   ELFOS server/namenode/EditLogFileOutputStream.java                     *)
(*                                                                          *)
(* Extensions and the brief Scenario that motivates each (brief sec. 4):    *)
(*   targetFired, TargetCheck, otherFired       oracle (all Scenarios)      *)
(*   ch[w][j].q/.inf + Bind at ChDispatch       dispatch-time RequestInfo   *)
(*                                              (Scenarios 1, 2)            *)
(*   jn[j].fc, .cs, .nx reset by JNCrash        restart-volatile state (1)  *)
(*   WPurgeLogsOlderThan, JNPurgeLogsOlderThan  acceptor forgetting (1)     *)
(*   jn[j].lwe, ch[w][j].oos/.hb, ChHeartbeat,  journal-wide writer epoch,  *)
(*   ChOutOfSync, Rank/Best                     re-incarnation (2)          *)
(*   ch[w][j].zb, RpcLate, req.ov               IPC late execution (2)      *)
(*   jn[j].tmp, JNAcceptRecoveryCrash,          split accept, roll-forward  *)
(*   roll-forward in JNPrepareRecovery          (3)                         *)
(*                                                                          *)
(* Encoding: txid 0 stands for HdfsServerConstants.INVALID_TXID (-12345).   *)
(* Real txids are >= 1, so no txnRange contains either value, and a          *)
(* RequestInfo with committedTxId = INVALID carries no committedTxId        *)
(* (RequestInfo.java:69-70, QJournalProtocolTranslatorPB.java:189-190).     *)
(***************************************************************************)
EXTENDS Integers, FiniteSets, Sequences, TLC

CONSTANTS
    JN,              \* the JournalNodes
    NW,              \* number of writer (QJM) instances; writer w is QJM number w
    MaxTxId,         \* largest txid a writer may write
    AssertsEnabled,  \* -ea in the JN and writer JVMs (surefire default: TRUE)
    ConnectRetry,    \* ipc.client.connect.max.retries > 0: a call dispatched to a
                     \* down JN may be delivered after it restarts (Client.java:1675)
    NoJN             \* model value: "no JournalNode"

ASSUME NW \in Nat /\ NW >= 1
ASSUME MaxTxId \in Nat /\ MaxTxId >= 1
ASSUME AssertsEnabled \in BOOLEAN /\ ConnectRetry \in BOOLEAN
ASSUME NoJN \notin JN

W    == 1..NW
Seg  == 1..MaxTxId                 \* possible segment start txids
Txn0 == 0..MaxTxId                 \* txids plus 0 = INVALID_TXID
Ep   == 0..NW                      \* epochs (0 = none); epoch(w_k) <= k
Majority == Cardinality(JN) \div 2 + 1          \* ALS.getMajoritySize 153-155

MaxOf(S) == CHOOSE x \in S : \A y \in S : y <= x

VARIABLES
    jn,           \* [JN -> JN record]: persistent + volatile JournalNode state
    ch,           \* [W -> [JN -> channel record]]: IPCLoggerChannel per (writer, JN)
    wr,           \* [W -> writer record]: QuorumJournalManager / NameNode writer
    targetFired,  \* TRUE once Journal.java:926 has thrown
    otherFired    \* history: other (competing) checks that failed; never read by actions

vars == <<jn, ch, wr, targetFired, otherFired>>

(***************************************************************************)
(* Requests and tasks.  One record shape for all of them (TLC-friendly).    *)
(*   op   the IPCLoggerChannel task (the writer's call)                     *)
(*   rop  the RPC actually sent: op, or "hb" when throwIfOutOfSync sent a   *)
(*        heartbeat instead (ILC 416-446)                                   *)
(*   s    gjs/ne: 0; prep/acc/fin: segment start S; start: txid; jrnl:      *)
(*        segmentTxId; purge: minTxIdToKeep                                 *)
(*   f    jrnl: firstTxnId                                                  *)
(*   e    jrnl: last txid of the batch; fin: endTxId; acc: segment.end      *)
(*   ip   acc: segment.isInProgress                                         *)
(*   src  acc: the JN whose HTTP server is the sync source (QJM 392)        *)
(*   x    ne: the proposed epoch (QJM 243-245)                              *)
(*   ep, c  RequestInfo epoch and committedTxId, bound at dispatch          *)
(*   ov   late call only: a later call of the same channel has already      *)
(*        passed J.checkRequest, so its IPC serial is higher (J 497-501)    *)
(***************************************************************************)
Ops == {"gjs", "ne", "prep", "acc", "fin", "start", "jrnl", "purge"}

Mk(op, s, f, e, ip, src, x) ==
    [op |-> op, rop |-> op, s |-> s, f |-> f, e |-> e, ip |-> ip, src |-> src,
     x |-> x, ep |-> 0, c |-> 0, ov |-> FALSE]

NoReq                    == Mk("none", 0, 0, 0, FALSE, NoJN, 0)
GjsTask                  == Mk("gjs", 0, 0, 0, FALSE, NoJN, 0)     \* ILC 326-332
NeTask(e)                == Mk("ne", 0, 0, 0, FALSE, NoJN, e)     \* ILC 335-339
PrepTask(S)              == Mk("prep", S, 0, 0, FALSE, NoJN, 0)   \* ILC 527-538
AccTask(S, E, ip, src)   == Mk("acc", S, 0, E, ip, src, 0)        \* ILC 541-546
FinTask(S, E)            == Mk("fin", S, 0, E, FALSE, NoJN, 0)    \* ILC 490-496
StartTask(t)             == Mk("start", t, 0, 0, FALSE, NoJN, 0)  \* ILC 474-487
JrnlTask(sg, fst, lst)   == Mk("jrnl", sg, fst, lst, FALSE, NoJN, 0) \* ILC 342-414
PurgeTask(m)             == Mk("purge", m, 0, 0, FALSE, NoJN, 0)  \* ILC 499-504

\* Identity of a writer call: replies to an earlier call of the same writer
\* go to that call's QuorumCall object, not to the current one.
SameCall(a, b) == a.op = b.op /\ a.s = b.s /\ a.f = b.f /\ a.x = b.x

(***************************************************************************)
(* Replies as recorded by the writer's QuorumCall.                          *)
(*   k    "none" | "ok" | "err" (exception) | "aerr" (AssertionError)       *)
(*   pe   gjs: lastPromisedEpoch (JRS 178-188)                              *)
(*   ls   ne: lastSegmentTxId, 0 = absent (J 360-362)                       *)
(*   has, end, ip, ae, lwe, c   prep: segmentState, acceptedInEpoch,        *)
(*        lastWriterEpoch, lastCommittedTxId (J 849-860)                    *)
(***************************************************************************)
NoResp   == [k |-> "none", pe |-> 0, ls |-> 0, has |-> FALSE, end |-> 0,
             ip |-> FALSE, ae |-> 0, lwe |-> 0, c |-> 0]
OkResp   == [NoResp EXCEPT !.k = "ok"]
ErrResp  == [NoResp EXCEPT !.k = "err"]
AErrResp == [NoResp EXCEPT !.k = "aerr"]
NoResps  == [j \in JN |-> NoResp]

(***************************************************************************)
(* JournalNode record.                                                      *)
(*   up     JN process running                                              *)
(*   pr     lastPromisedEpoch   (PersistentLongFile, J 106, 206-207)        *)
(*   lwe    lastWriterEpoch     (PersistentLongFile, J 125, 208-209)        *)
(*   c      committedTxnId      (BestEffortLongFile, J 133, 210-212)        *)
(*   files  strictly-named segment files by start txid: end = highest txid  *)
(*          in the file (0 = header only), ip = in-progress.  Files moved   *)
(*          aside (.empty/.stale) are invisible to every strict matcher    *)
(*          (FJM 313-366) and are simply absent here.                       *)
(*   paxos  paxos/<S> records: accepted epoch and segment (J 1073-1123)     *)
(*   tmp    edits_inprogress_S.epoch=E download files (JNS 120-124)         *)
(*   cs     curSegmentTxId, 0 = no open segment (J 90-91)        volatile   *)
(*   nx     nextTxId (J 93); only read while cs # 0, so it is kept at 0     *)
(*          whenever cs = 0 (canonical form, no behavior lost)   volatile   *)
(*   fc     FJM.currentInProgress start, 0 = null (FJM 79)       volatile   *)
(***************************************************************************)
NoFile == [ex |-> FALSE, end |-> 0, ip |-> FALSE]
NoPax  == [ex |-> FALSE, ep |-> 0, end |-> 0, ip |-> FALSE]

JNInit == [up |-> TRUE, pr |-> 0, lwe |-> 0, c |-> 0,
           files |-> [s \in Seg |-> NoFile], paxos |-> [s \in Seg |-> NoPax],
           tmp |-> {}, cs |-> 0, nx |-> 0, fc |-> 0]

(***************************************************************************)
(* Channel record (IPCLoggerChannel of writer w towards JN j).              *)
(*   q    tasks submitted to singleThreadExecutor, not yet started (ILC 89) *)
(*   inf  the call the executor thread is blocked on (sent, or connecting)  *)
(*   zb   a call the writer already saw fail but which the JN may still     *)
(*        execute later (IPC late execution, analysis-report F5)            *)
(*   oos  outOfSync (ILC 146)                                               *)
(*   hb   lastHeartbeatStopwatch is running (ILC 151, 443)                  *)
(***************************************************************************)
ChInit == [q |-> <<>>, inf |-> NoReq, zb |-> NoReq, oos |-> FALSE, hb |-> FALSE]

(***************************************************************************)
(* Writer record.                                                           *)
(*   pc     program counter (see WaitPC / ActivePC)                         *)
(*   ep     this writer's epoch (computed at QJM 242, used after setEpoch)  *)
(*   c      committedTxId held by its channels (ILC 98, 189-195)            *)
(*   call   the call whose quorum the writer is waiting for                 *)
(*   resp   replies recorded for that call                                  *)
(*   S      segment under recovery (QJM 484-495)                            *)
(*   dec    recovery decision: segment end/inProgress and the sync source  *)
(*   seg    start txid of the open output stream, 0 = none (QOS 43)         *)
(*   last   NameNode's last written txid (FSEditLog.getLastWrittenTxId)     *)
(*   opened TRUE after the first startLogSegment (FSEditLog.openForWrite)   *)
(***************************************************************************)
NoDec  == [end |-> 0, ip |-> FALSE, src |-> NoJN]
WInit  == [pc |-> "init", ep |-> 0, c |-> 0, call |-> NoReq, resp |-> NoResps,
           S |-> 0, dec |-> NoDec, seg |-> 0, last |-> 0, opened |-> FALSE]
WDead  == [WInit EXCEPT !.pc = "dead"]   \* canonical: a dead writer reads nothing

WaitPC   == {"gjs", "ne", "prep", "acc", "rfin", "start", "send", "fin"}
ActivePC == {"act", "start", "send", "fin"}     \* isActiveWriter (QJM 498)
PCs      == {"init", "dead", "act"} \cup WaitPC

OtherKinds == {"client386", "cmp76", "a845", "a898", "a938", "dupSeg"}

(***************************************************************************)
(* Initial state: three formatted, empty JournalNodes (the workload's       *)
(* qjm.format() has run, TestQuorumJournalManager.java:127); no writer has  *)
(* started.                                                                 *)
(***************************************************************************)
Init ==
    /\ jn = [j \in JN |-> JNInit]
    /\ ch = [w \in W |-> [j \in JN |-> ChInit]]
    /\ wr = [w \in W |-> WInit]
    /\ targetFired = FALSE
    /\ otherFired = {}

-----------------------------------------------------------------------------
(***************************************************************************)
(* Storage helpers                                                          *)
(***************************************************************************)

NonEmpty(f) == f.ex /\ ~(f.ip /\ f.end = 0)

\* J.getSegmentInfo (J 799-822): the strictly named file at S (FJM.getLogFile
\* 499-521); an in-progress file is scanned (805-806); a file with no txns
\* is moved aside to .empty and null is returned (808-812).
SegInfo(files, S) ==
    LET f == files[S] IN
    IF ~f.ex THEN [has |-> FALSE, end |-> 0, ip |-> FALSE, files |-> files]
    ELSE IF f.ip /\ f.end = 0
         THEN [has |-> FALSE, end |-> 0, ip |-> FALSE,
               files |-> [files EXCEPT ![S] = NoFile]]
         ELSE [has |-> TRUE, end |-> f.end, ip |-> f.ip, files |-> files]

\* J.scanStorageForLatestEdits (J 221-246): walk the strictly named files
\* from the highest start down; move aside each one without txns (233-238);
\* return the first non-empty one.  Finalized files always have txns.
ScanLatest(files) ==
    LET nes    == {s \in Seg : NonEmpty(files[s])}
        latest == IF nes = {} THEN 0 ELSE MaxOf(nes)
    IN [latest |-> latest,
        files  |-> [s \in Seg |-> IF s > latest THEN NoFile ELSE files[s]]]

(***************************************************************************)
(* J.checkRequest (J 484-512) applied to JN record s and request r.         *)
(*   ok    all checks passed                                                *)
(*   epok  the epoch check passed and the IPC serial was raised (J 501),    *)
(*         which makes an older late call of the same channel fail later   *)
(*   st    the JN record after the checks (effects are never rolled back)   *)
(***************************************************************************)
CheckReq(s, r) ==
    IF r.ep < s.pr
    THEN [ok |-> FALSE, epok |-> FALSE, st |-> s]                 \* 486-489 IOException
    ELSE LET s1 == IF r.ep > s.pr THEN [s EXCEPT !.pr = r.ep]     \* 490-494 new promise,
                   ELSE s                                         \*   serial reset (375)
         IN IF r.ov /\ r.ep = s.pr
            THEN [ok |-> FALSE, epok |-> FALSE, st |-> s1]        \* 497-500 serial not higher
            ELSE IF r.c # 0 /\ r.c < s1.c
                 THEN [ok |-> FALSE, epok |-> TRUE, st |-> s1]    \* 503-508 IllegalArgument
                 ELSE [ok |-> TRUE, epok |-> TRUE,
                       st |-> IF r.c # 0 THEN [s1 EXCEPT !.c = r.c]   \* 510
                              ELSE s1]

-----------------------------------------------------------------------------
(***************************************************************************)
(* Writer-side bookkeeping                                                  *)
(***************************************************************************)

\* A reply reaches the QuorumCall of the call it belongs to (QC 78-88).
Record(wv, j, r, resp) ==
    IF /\ wv.pc \in WaitPC
       /\ SameCall(wv.call, r)
       /\ wv.resp[j].k = "none"
    THEN [wv EXCEPT !.resp[j] = resp]
    ELSE wv

\* Channel-side effects when the executor thread finishes call r.
Outcome(cv, r, ok) ==
    [cv EXCEPT !.inf = NoReq,
               !.oos = IF r.rop = "jrnl" /\ ~ok THEN TRUE        \* ILC 363-370
                       ELSE IF r.rop = "start" /\ ok THEN FALSE   \* ILC 477-484
                       ELSE @]

Overtake(cv, epok) ==
    IF epok /\ cv.zb # NoReq THEN [cv EXCEPT !.zb.ov = TRUE] ELSE cv

\* ALS fan-out (ALS 208-314): the same task is submitted to every channel.
Fanout(w, t) ==
    ch' = [ch EXCEPT ![w] = [j \in JN |-> [ch[w][j] EXCEPT !.q = Append(@, t)]]]

ClearQueues(w) == [ch EXCEPT ![w] = [j \in JN |-> [ch[w][j] EXCEPT !.q = <<>>]]]

Await(wv, pc, t) == [wv EXCEPT !.pc = pc, !.call = t, !.resp = NoResps]

Succ(w)      == {j \in JN : wr[w].resp[j].k = "ok"}
Responded(w) == {j \in JN : wr[w].resp[j].k # "none"}
\* Results seen when waitForWriteQuorum returns (QC 165-177, 299-301; ALS
\* 124-147): the successes that had arrived, at least a majority of them.
Results(w)   == {R \in SUBSET Succ(w) : Cardinality(R) >= Majority}

ReqAt(w, j, src) == IF src = "in" THEN ch[w][j].inf ELSE ch[w][j].zb

(***************************************************************************)
(* Completing a JN handler run.                                             *)
(*   j, w, src  the JN, the channel's writer, "in" (the in-flight call) or  *)
(*              "zb" (a late call)                                          *)
(*   lose       the reply is lost: the JN executed, the writer sees an      *)
(*              IOException (connection reset, analysis-report 2)           *)
(*   s2, resp   JN record after the handler, and its reply                  *)
(*   epok       see CheckReq                                                *)
(*   of         competing checks that failed in this run                    *)
(* targetFired is set by the caller.                                        *)
(***************************************************************************)
Complete(j, w, src, lose, s2, resp, epok, of) ==
    LET r    == ReqAt(w, j, src)
        hb   == r.rop = "hb"   \* the task still throws after its heartbeat (ILC 421)
        ok   == resp.k = "ok" /\ ~lose /\ ~hb
        seen == IF lose \/ hb THEN ErrResp ELSE resp
    IN
    /\ jn' = [jn EXCEPT ![j] = s2]
    /\ otherFired' = otherFired \cup of
    /\ IF src = "in"
       THEN /\ ch' = [ch EXCEPT ![w][j] = Overtake(Outcome(@, r, ok), epok)]
            /\ wr' = [wr EXCEPT ![w] = Record(@, j, r, seen)]
       ELSE /\ ch' = [ch EXCEPT ![w][j].zb = NoReq]   \* nobody waits for a late call
            /\ UNCHANGED wr

\* JN j's IPC handler takes request r of channel (w,j).
Runnable(j, w, src, lose, rop) ==
    /\ jn[j].up
    /\ ReqAt(w, j, src).rop = rop
    /\ (src = "zb" => ~lose)

-----------------------------------------------------------------------------
(***************************************************************************)
(* JournalNode handlers (one atomic action each: J methods are synchronized)*)
(***************************************************************************)

\* JRS.getJournalState 178-188 -> J.getLastPromisedEpoch 284-287 (no checkRequest).
JNGetJournalState(j, w, src, lose) ==
    /\ Runnable(j, w, src, lose, "gjs")
    /\ Complete(j, w, src, lose, jn[j], [OkResp EXCEPT !.pe = jn[j].pr], FALSE, {})
    /\ UNCHANGED targetFired

\* J.newEpoch 339-365 (no checkRequest; the epoch is the call argument).
JNNewEpoch(j, w, src, lose) ==
    LET r == ReqAt(w, j, src)
        s == jn[j]
    IN
    /\ Runnable(j, w, src, lose, "ne")
    /\ IF r.x <= s.pr
       THEN Complete(j, w, src, lose, s, ErrResp, FALSE, {})       \* 347-350
       ELSE LET s1 == [s EXCEPT !.pr = r.x,                        \* 352 (serial reset 375)
                                !.cs = 0, !.nx = 0]                \* 353 abortCurSegment 378-387
                sc == ScanLatest(s1.files)                         \* 358
            IN Complete(j, w, src, lose, [s1 EXCEPT !.files = sc.files],
                        [OkResp EXCEPT !.ls = sc.latest],          \* 360-362
                        FALSE, {})
    /\ UNCHANGED targetFired

\* J.heartbeat 475-477: checkRequest only.
JNHeartbeat(j, w, src, lose) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)
    IN
    /\ Runnable(j, w, src, lose, "hb")
    /\ Complete(j, w, src, lose, cr.st, IF cr.ok THEN OkResp ELSE ErrResp, cr.epok, {})
    /\ UNCHANGED targetFired

\* J.journal 393-473.
JNJournal(j, w, src, lose) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)                                   \* 397 -> 515
        s1 == cr.st
        cs == s1.cs
    IN
    /\ Runnable(j, w, src, lose, "jrnl")
    /\ IF ~cr.ok
       THEN Complete(j, w, src, lose, s1, ErrResp, cr.epok, {})
       ELSE IF r.ep # s1.lwe                                       \* 517-521 not the writer epoch
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       ELSE IF cs = 0                                              \* 405-406 no segment open
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       ELSE IF cs # r.s                                            \* 408-421 abort, out of sync
       THEN Complete(j, w, src, lose, [s1 EXCEPT !.cs = 0, !.nx = 0], ErrResp, TRUE, {})
       ELSE IF s1.nx # r.f                                         \* 423-425
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       \* 427-471: append to the open stream.  If a purge removed or renamed
       \* that file (FJM 206-210), the bytes go to an invisible file.
       \* (numTxns = 0 at 401-403 is never sent by QOS.)
       ELSE Complete(j, w, src, lose,
                     [s1 EXCEPT !.files[cs] = IF @.ex THEN [@ EXCEPT !.end = r.e] ELSE @,
                                !.nx = r.e + 1],                   \* 442-446, 471
                     OkResp, TRUE, {})
    /\ UNCHANGED targetFired

\* J.startLogSegment 568-624.
JNStartLogSegment(j, w, src, lose) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)                                   \* 572
        t  == r.s
        s1 == [cr.st EXCEPT !.cs = 0, !.nx = 0]                    \* 574-583 abortCurSegment
        ex == s1.files[t]                                          \* 588 fjm.getLogFile(txid)
    IN
    /\ Runnable(j, w, src, lose, "start")
    /\ IF ~cr.ok
       THEN Complete(j, w, src, lose, cr.st, ErrResp, cr.epok, {})
       ELSE IF ex.ex /\ ~ex.ip                                     \* 590-593 finalized: ISE
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       ELSE IF ex.ex /\ ex.end # t                                 \* 598-603 not exactly 1 txn
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})       \*   (header-only too): ISE
       ELSE Complete(j, w, src, lose,
                     [s1 EXCEPT !.lwe = r.ep,                      \* 606-612
                                !.paxos[t] = NoPax,                \* 618 purgePaxosDecision
                                !.fc = t,                          \* FJM 124
                                !.files[t] = [ex |-> TRUE, end |-> 0, ip |-> TRUE],
                                                                   \* FJM 125-127, ELFOS 123-130 truncate
                                !.cs = t, !.nx = t],               \* 620-623
                     OkResp, TRUE, {})
    /\ UNCHANGED targetFired

\* J.finalizeLogSegment 629-685.
JNFinalizeLogSegment(j, w, src, lose) ==
    LET r     == ReqAt(w, j, src)
        cr    == CheckReq(jn[j], r)                                \* 632
        s0    == cr.st
        S     == r.s
        E     == r.e
        atCur == S = s0.cs                                         \* 637
        s1    == IF atCur THEN [s0 EXCEPT !.cs = 0, !.nx = 0] ELSE s0   \* 638-643 close
        f     == s1.files[S]                                       \* 654
    IN
    /\ Runnable(j, w, src, lose, "fin")
    /\ IF ~cr.ok
       THEN Complete(j, w, src, lose, s0, ErrResp, cr.epok, {})
       ELSE IF atCur /\ s0.nx # E + 1                              \* 645-648
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       ELSE IF ~f.ex                                               \* 655-658
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       ELSE IF f.ip /\ ~atCur /\ f.end # E                         \* 661-671 validation scan
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       ELSE IF ~f.ip /\ E # f.end                                  \* 673-678 re-finalize: IAE
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {})
       ELSE Complete(j, w, src, lose,
                     [s1 EXCEPT !.files[S] = [ex |-> TRUE, end |-> E, ip |-> FALSE],
                                                                   \* 672 -> FJM 139-157
                                !.fc = IF f.ip /\ @ = S THEN 0 ELSE @,  \* FJM 158-160
                                !.paxos[S] = NoPax],               \* 684 purgePaxosDecision
                     OkResp, TRUE, {})
    /\ UNCHANGED targetFired

\* J.purgeLogsOlderThan 690-696 -> JNS.purgeDataOlderThan 174-179
\*   -> FJM.purgeLogsOlderThan 199-214, isStaleInProgressLog 216-224;
\*   -> JNS.purgeMatching 188-210 on the paxos dir.
JNPurgeLogsOlderThan(j, w, src, lose) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)                                   \* 693
        s1 == cr.st
        m  == r.s
        Purged(sg, f) ==
            IF ~f.ex THEN f
            ELSE IF ~f.ip /\ f.end < m THEN NoFile                 \* 206-208 finalized, last < min
            ELSE IF f.ip /\ sg < m THEN NoFile                     \* 206-208 in-progress (last INVALID)
            ELSE IF f.ip /\ sg # s1.fc THEN NoFile                 \* 209-210, 216-224 -> .stale
            ELSE f
    IN
    /\ Runnable(j, w, src, lose, "purge")
    /\ IF ~cr.ok
       THEN Complete(j, w, src, lose, s1, ErrResp, cr.epok, {})
       ELSE Complete(j, w, src, lose,
                     [s1 EXCEPT !.files = [sg \in Seg |-> Purged(sg, s1.files[sg])],
                                !.paxos = [sg \in Seg |-> IF sg < m THEN NoPax
                                                          ELSE s1.paxos[sg]],  \* JNS 177-178
                                !.tmp   = {t \in s1.tmp : t.s >= m}],
                                \* tmp names match EDITS_INPROGRESS_STALE_REGEX when
                                \* forPurging (FJM 347-362) and are deleted when start < min
                     OkResp, TRUE, {})
    /\ UNCHANGED targetFired

\* J.prepareRecovery 827-866.
JNPrepareRecovery(j, w, src, lose) ==
    LET r    == ReqAt(w, j, src)
        cr   == CheckReq(jn[j], r)                                 \* 830
        S    == r.s
        s1   == [cr.st EXCEPT !.cs = 0, !.nx = 0]                  \* 832 abortCurSegment
        prev == s1.paxos[S]                                        \* 837
        \* 838 completeHalfDoneAcceptRecovery 1051-1068: roll the download of
        \* the accepted epoch forward if it is still at its temporary path.
        rfT  == {t \in s1.tmp : prev.ex /\ t.s = S /\ t.ep = prev.ep}
        rf   == rfT # {}
        dup  == rf /\ s1.files[S].ex /\ ~s1.files[S].ip            \* would leave 2 files at S
        s2   == IF rf
                THEN [s1 EXCEPT !.files[S] = [ex |-> TRUE,
                                              end |-> (CHOOSE t \in rfT : TRUE).end,
                                              ip |-> TRUE],        \* 1063-1066 replaceFile
                                !.tmp = @ \ rfT]
                ELSE s1
        si   == SegInfo(s2.files, S)                               \* 840
        s3   == [s2 EXCEPT !.files = si.files]
        hasFin == si.has /\ ~si.ip                                 \* 841
        PrepResp(has, end, ip, ae) ==                              \* 849-860
            [OkResp EXCEPT !.has = has, !.end = end, !.ip = ip, !.ae = ae,
                           !.lwe = s3.lwe, !.c = s3.c]
    IN
    /\ Runnable(j, w, src, lose, "prep")
    /\ IF ~cr.ok
       THEN Complete(j, w, src, lose, cr.st, ErrResp, cr.epok, {})
       ELSE IF dup                       \* getLogFile would throw ISE (FJM 516-519)
       THEN Complete(j, w, src, lose, s1, ErrResp, TRUE, {"dupSeg"})
       ELSE IF prev.ex /\ ~hasFin                                  \* 843
       THEN IF AssertsEnabled /\ ~si.has                           \* 845 on null segInfo: NPE
            THEN Complete(j, w, src, lose, s3, ErrResp, TRUE, {})
            ELSE IF AssertsEnabled /\ prev.end # si.end            \* 845 assert (-ea only)
            THEN Complete(j, w, src, lose, s3, AErrResp, TRUE, {"a845"})
            ELSE Complete(j, w, src, lose, s3,                     \* 849-850 accepted state
                          PrepResp(TRUE, prev.end, prev.ip, prev.ep), TRUE, {})
       ELSE IF si.has                                              \* 852-854 disk state
       THEN Complete(j, w, src, lose, s3, PrepResp(TRUE, si.end, si.ip, 0), TRUE, {})
       ELSE Complete(j, w, src, lose, s3, PrepResp(FALSE, 0, FALSE, 0), TRUE, {})
    /\ UNCHANGED targetFired

(***************************************************************************)
(* J.acceptRecovery 871-986, split by code path.                            *)
(***************************************************************************)

\* Lines 877-908 after a successful checkRequest (875) on JN record s.
\*   path  "badseg" 883-886 | "a898" 897-902 | "sync" 909-915 (no current
\*         segment) | "skip" 950-954 (same end) | "guard" 916- (reaches 924)
\*   st    JN record so far;  cur  currentSegment (906)
AcceptPre(s, r) ==
    LET S  == r.s
        s1 == [s EXCEPT !.cs = 0, !.nx = 0]                        \* 877 abortCurSegment
        si == SegInfo(s1.files, S)                                 \* 906
        s2 == [s1 EXCEPT !.files = si.files]
    IN IF ~(r.e > 0 /\ r.e >= S)                                   \* 883-886 IAE
       THEN [path |-> "badseg", st |-> s1, cur |-> si]
       ELSE IF s1.paxos[S].ex /\ s1.paxos[S].ep > r.ep             \* 888, 897-902
       THEN [path |-> "a898", st |-> s1, cur |-> si]
       ELSE [path |-> IF ~si.has THEN "sync"                       \* 907-915
                      ELSE IF si.end = r.e THEN "skip"             \* 950-954
                      ELSE "guard",                                \* 916
             st |-> s2, cur |-> si]

\* The failing branch of the target, exactly as written at 924-925:
\* txnRange(cur).contains(C) && !txnRange(segment).contains(C), where
\* txnRange(seg) = Range.between(start, end) inclusive (988-992) and C is
\* committedTxnId after checkRequest.  cur.start = segment.start = S (815).
TargetGuard(ap, r) ==
    LET S == r.s
        C == ap.st.c
    IN /\ S <= C /\ C <= ap.cur.end
       /\ ~(S <= C /\ C <= r.e)

\* syncLog 1001-1034: download the source JN's *current* strictly named file
\* at S over HTTP (GJES 213-227, inProgressOk; only the byte count is checked).
\* -1: the download fails (source down, or no file: 404).
DownloadEnd(j, s, r) ==
    LET S   == r.s
        sf  == IF r.src = j THEN s.files[S] ELSE jn[r.src].files[S]
        sup == r.src = j \/ jn[r.src].up
    IN IF sup /\ sf.ex THEN sf.end ELSE -1

NewPax(r) == [ex |-> TRUE, ep |-> r.ep, end |-> r.e, ip |-> r.ip]  \* 889-892

\* Every path of acceptRecovery except the one that reaches line 924.
JNAcceptRecovery(j, w, src, lose) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)                                   \* 875
        S  == r.s
        ap == AcceptPre(cr.st, r)
        dl == DownloadEnd(j, ap.st, r)
    IN
    /\ Runnable(j, w, src, lose, "acc")
    /\ ~(cr.ok /\ ap.path = "guard")
    /\ IF ~cr.ok
       THEN Complete(j, w, src, lose, cr.st, ErrResp, cr.epok, {})
       ELSE IF ap.path = "badseg"
       THEN Complete(j, w, src, lose, ap.st, ErrResp, TRUE, {})
       ELSE IF ap.path = "a898"
       THEN Complete(j, w, src, lose, ap.st, AErrResp, TRUE, {"a898"})
       ELSE IF ap.path = "skip"
       THEN Complete(j, w, src, lose,
                     [ap.st EXCEPT !.paxos[S] = NewPax(r)],        \* 976 persistPaxosData
                     OkResp, TRUE, {})
       ELSE IF dl < 0                                              \* "sync": 948 fails
       THEN Complete(j, w, src, lose, ap.st, ErrResp, TRUE, {})
       ELSE Complete(j, w, src, lose,
                     [ap.st EXCEPT !.paxos[S] = NewPax(r),         \* 976
                                   !.files[S] = [ex |-> TRUE, end |-> dl, ip |-> TRUE]],
                                                                   \* 979-982 replaceFile
                     OkResp, TRUE, {})
    /\ UNCHANGED targetFired

\* The code path that reaches the ad hoc check: acceptRecovery with a current
\* segment whose end differs from the decision (907-908, else-branch 916).
TargetCheck(j, w, src) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)                                   \* 875
        S  == r.s
        ap == AcceptPre(cr.st, r)
        dl == DownloadEnd(j, ap.st, r)
    IN
    /\ Runnable(j, w, src, FALSE, "acc")
    /\ cr.ok
    /\ ap.path = "guard"
    /\ IF TargetGuard(ap, r)                                       \* 924-925
       THEN /\ targetFired' = TRUE                                 \* 926 throw AssertionError
            /\ Complete(j, w, src, FALSE, ap.st, AErrResp, TRUE, {})
       ELSE /\ UNCHANGED targetFired
            /\ IF ~ap.cur.ip                                       \* 938-940 alwaysAssert
               THEN Complete(j, w, src, FALSE, ap.st, AErrResp, TRUE, {"a938"})
               ELSE IF dl < 0                                      \* 948 download fails
               THEN Complete(j, w, src, FALSE, ap.st, ErrResp, TRUE, {})
               ELSE Complete(j, w, src, FALSE,
                             [ap.st EXCEPT !.paxos[S] = NewPax(r), \* 976
                                           !.files[S] = [ex |-> TRUE, end |-> dl, ip |-> TRUE]],
                                                                   \* 979-982
                             OkResp, TRUE, {})

-----------------------------------------------------------------------------
(***************************************************************************)
(* JN process crash and restart                                             *)
(***************************************************************************)

\* Connections to j reset: every call in flight to j fails at its writer
\* (no IPC call-level retry once bytes were sent, analysis-report 2), and
\* calls queued in the JN's IPC server are discarded (Server.stop).
ChAfterCrash(j) ==
    [w \in W |-> [k \in JN |->
        IF k # j THEN ch[w][k]
        ELSE IF ch[w][k].inf = NoReq THEN [ch[w][k] EXCEPT !.zb = NoReq]
        ELSE [Outcome(ch[w][k], ch[w][k].inf, FALSE) EXCEPT !.zb = NoReq]]]

WrAfterCrash(j) ==
    [w \in W |-> IF ch[w][j].inf = NoReq THEN wr[w]
                 ELSE Record(wr[w], j, ch[w][j].inf, ErrResp)]

\* Volatile state is lost: curSegment / nextTxId / currentEpochIpcSerial and
\* FJM.currentInProgress live in the Journal and FJM objects (J 90-93, 117;
\* FJM 79); a restart builds new ones (J 159-178; JournalNode 98-125).
JNCrash(j) ==
    /\ jn[j].up
    /\ jn' = [jn EXCEPT ![j].up = FALSE, ![j].cs = 0, ![j].nx = 0, ![j].fc = 0]
    /\ ch' = ChAfterCrash(j)
    /\ wr' = WrAfterCrash(j)
    /\ UNCHANGED <<targetFired, otherFired>>

\* Restart with the same storage (MiniJournalCluster.restartJournalNode).
\* Epochs and committedTxnId are re-read from disk (J 202-213).  The Journal
\* constructor's scan moves aside trailing files without txns (J 174-177);
\* it runs on the first RPC, which is equivalent because nothing else touches
\* the directory before that.  With connect retries off (the workload sets
\* ipc.client.connect.max.retries = 0, TestQuorumJournalManager.java:110-112)
\* every call dispatched while j was down has already failed.
JNRestart(j) ==
    /\ ~jn[j].up
    /\ ConnectRetry \/ \A w \in W : ch[w][j].inf = NoReq
    /\ jn' = [jn EXCEPT ![j].up = TRUE, ![j].files = ScanLatest(@).files]
    /\ UNCHANGED <<ch, wr, targetFired, otherFired>>

\* A crash inside acceptRecovery after persistPaxosData (976) and before the
\* rename (979-982), i.e. at JournalFaultInjector.afterPersistPaxosData (977).
\* The download stays at its temporary path; a later prepareRecovery rolls
\* it forward (838).  (A crash before 976 leaves an orphan tmp file that no
\* paxos record names, so it is a plain JNCrash; not modeled separately.)
JNAcceptRecoveryCrash(j, w, src) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)
        S  == r.s
        ap == AcceptPre(cr.st, r)
        dl == DownloadEnd(j, ap.st, r)
        s3 == [ap.st EXCEPT !.paxos[S] = NewPax(r),
                            !.tmp = {t \in @ : ~(t.s = S /\ t.ep = r.ep)}
                                    \cup {[s |-> S, ep |-> r.ep, end |-> dl]},
                            !.up = FALSE, !.cs = 0, !.nx = 0, !.fc = 0]
    IN
    /\ Runnable(j, w, src, FALSE, "acc")
    /\ cr.ok
    /\ \/ ap.path = "sync"
       \/ ap.path = "guard" /\ ~TargetGuard(ap, r) /\ ap.cur.ip
    /\ dl >= 0
    /\ jn' = [jn EXCEPT ![j] = s3]
    /\ ch' = ChAfterCrash(j)
    /\ wr' = WrAfterCrash(j)
    /\ UNCHANGED <<targetFired, otherFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Channel (IPCLoggerChannel executor thread and the IPC client)            *)
(***************************************************************************)

Bind(t, w) == [t EXCEPT !.ep = wr[w].ep, !.c = wr[w].c]          \* createReqInfo 287-291

\* The executor runs the head task and sends its RPC (ILC 85-89, 175-176).
ChDispatch(w, j) ==
    /\ ch[w][j].inf = NoReq
    /\ ch[w][j].q # <<>>
    /\ LET t == Head(ch[w][j].q) IN
       /\ ~(t.op \in {"jrnl", "fin"} /\ ch[w][j].oos)              \* 358, 492 throwIfOutOfSync
       /\ ch' = [ch EXCEPT ![w][j].q = Tail(@), ![w][j].inf = Bind(t, w)]
    /\ UNCHANGED <<jn, wr, targetFired, otherFired>>

\* Out of sync: throwIfOutOfSync sends a heartbeat first (ILC 416-446).  The
\* first time it must (stopwatch not running, 437); later only after 1 s.
ChHeartbeat(w, j) ==
    /\ ch[w][j].inf = NoReq
    /\ ch[w][j].q # <<>>
    /\ LET t == Head(ch[w][j].q) IN
       /\ t.op \in {"jrnl", "fin"} /\ ch[w][j].oos
       /\ ch' = [ch EXCEPT ![w][j].q = Tail(@),
                           ![w][j].inf = [Bind(t, w) EXCEPT !.rop = "hb"],
                           ![w][j].hb = TRUE]                      \* 443
    /\ UNCHANGED <<jn, wr, targetFired, otherFired>>

\* Out of sync and the heartbeat interval has not elapsed: the task throws
\* JournalOutOfSyncException without any RPC (ILC 421).
ChOutOfSync(w, j) ==
    /\ ch[w][j].inf = NoReq
    /\ ch[w][j].q # <<>>
    /\ ch[w][j].hb
    /\ LET t == Head(ch[w][j].q) IN
       /\ t.op \in {"jrnl", "fin"} /\ ch[w][j].oos
       /\ ch' = [ch EXCEPT ![w][j].q = Tail(@)]
       /\ wr' = [wr EXCEPT ![w] = Record(@, j, t, ErrResp)]
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* The newest call fails before its task runs: no RPC, no serial, no
\* outOfSync change.  Production: sendEdits refused by reserveQueueSpace
\* (LoggerTooFarBehindException, ILC 345-349).  Test harness: a Mockito stub
\* futureThrows (TestQuorumJournalManagerUnit.java:130-133).
ChReject(w, j) ==
    /\ ch[w][j].q # <<>>
    /\ LET q == ch[w][j].q
           t == q[Len(q)]
       IN /\ ch' = [ch EXCEPT ![w][j].q = SubSeq(q, 1, Len(q) - 1)]
          /\ wr' = [wr EXCEPT ![w] = Record(@, j, t, ErrResp)]
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* Common effect of a call that fails at the writer without having run.
CallFails(w, j) ==
    LET r == ch[w][j].inf IN
    /\ ch' = [ch EXCEPT ![w][j] = Outcome(@, r, FALSE)]
    /\ wr' = [wr EXCEPT ![w] = Record(@, j, r, ErrResp)]

\* Network loss: the call never reaches the JN; the writer gets an IOException.
RpcDrop(w, j) ==
    /\ ch[w][j].inf # NoReq
    /\ jn[j].up
    /\ CallFails(w, j)
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* The JN is down: connection refused once connect retries are exhausted.
RpcConnectFail(w, j) ==
    /\ ch[w][j].inf # NoReq
    /\ ~jn[j].up
    /\ CallFails(w, j)
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* IPC late execution (analysis-report 2, F5): the writer sees a failure
\* (timeout / connection reset) but the call is still queued at the JN's
\* IPC server and may run later, after later calls of other channels.
RpcLate(w, j) ==
    /\ ch[w][j].inf # NoReq
    /\ jn[j].up
    /\ ch[w][j].zb = NoReq
    /\ LET r == ch[w][j].inf IN
       /\ ch' = [ch EXCEPT ![w][j] = [Outcome(@, r, FALSE) EXCEPT !.zb = r]]
       /\ wr' = [wr EXCEPT ![w] = Record(@, j, r, ErrResp)]
    /\ UNCHANGED <<jn, targetFired, otherFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Writer (QuorumJournalManager, as driven by FSEditLog or a test)          *)
(***************************************************************************)

\* QJM.recoverUnfinalizedSegments 473-478 -> createNewUniqueEpoch 227-235:
\* getJournalState to every JN (ALS 208-215).
WRecoverUnfinalizedSegments(w) ==
    /\ wr[w].pc = "init"
    /\ wr' = [wr EXCEPT ![w] = Await(@, "gjs", GjsTask)]
    /\ Fanout(w, GjsTask)
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* QJM 232-245: epoch = max lastPromisedEpoch of the quorum + 1; newEpoch to all.
WCreateNewUniqueEpoch(w, R) ==
    /\ wr[w].pc = "gjs"
    /\ R \in Results(w)
    /\ LET e == MaxOf({wr[w].resp[j].pe : j \in R}) + 1            \* 237-242
           t == NeTask(e)
       IN /\ wr' = [wr EXCEPT ![w] = [Await(@, "ne", t) EXCEPT !.ep = e]]
          /\ Fanout(w, t)                                          \* 243-245, ALS 225-234
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* QJM 243-247 newEpoch quorum, setEpoch (247); 485-491 mostRecentSegmentTxId;
\* then recoverUnclosedSegment (496 -> 311-321) sends prepareRecovery to all,
\* or nothing to recover on a fresh system (493-498).
WRecoverPrepare(w, R) ==
    /\ wr[w].pc = "ne"
    /\ R \in Results(w)
    /\ LET segs == {wr[w].resp[j].ls : j \in R} \ {0}
       IN IF segs = {}
          THEN /\ wr' = [wr EXCEPT ![w] = [Await(@, "act", NoReq) EXCEPT !.last = 0]]
               /\ UNCHANGED ch
          ELSE LET S == MaxOf(segs) IN
               /\ wr' = [wr EXCEPT ![w] = [Await(@, "prep", PrepTask(S)) EXCEPT !.S = S]]
               /\ Fanout(w, PrepTask(S))                           \* ALS 291-302
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* SegmentRecoveryComparator 39-90 as a rank; Collections.max (QJM 335-336).
\* Having a segment beats not (49-57); finalized beats in-progress (69-71);
\* finalized ones are equal (73-79); in-progress by (max(acceptedInEpoch,
\* lastWriterEpoch), endTxId) (82-89).
Rank(r) ==
    IF ~r.has THEN <<0, 0, 0>>
    ELSE IF ~r.ip THEN <<2, 0, 0>>
    ELSE <<1, MaxOf({r.ae, r.lwe}), r.end>>
LexLT(a, b) ==
    \/ a[1] < b[1]
    \/ a[1] = b[1] /\ a[2] < b[2]
    \/ a[1] = b[1] /\ a[2] = b[2] /\ a[3] < b[3]
\* Ties are broken by HashMap iteration order: any maximal element.
Best(rs, R) == {b \in R : \A k \in R : ~LexLT(Rank(rs[b]), Rank(rs[k]))}
\* Collections.max compares two finalized responses of different lengths
\* sooner or later, and the comparator throws (SRC 73-78).
CmpThrows(rs, R) ==
    \E a, b \in R : /\ rs[a].has /\ ~rs[a].ip /\ rs[b].has /\ ~rs[b].ip
                    /\ rs[a].end # rs[b].end

\* QJM.recoverUnclosedSegment 316-397: decide from the prepare quorum,
\* client-side sanity check, then acceptRecovery to all loggers.
WRecoverDecide(w, R) ==
    /\ wr[w].pc = "prep"
    /\ R \in Results(w)
    /\ LET rs == wr[w].resp
           S  == wr[w].S
       IN
       IF CmpThrows(rs, R)                                         \* SRC 76 AssertionError
       THEN /\ wr' = [wr EXCEPT ![w] = WDead]
            /\ ch' = ClearQueues(w)
            /\ otherFired' = otherFired \cup {"cmp76"}
       ELSE IF \A j \in R : ~rs[j].has                             \* 347-372 nothing to recover
       THEN /\ wr' = [wr EXCEPT ![w] = [Await(@, "act", NoReq) EXCEPT !.last = S - 1, !.S = 0]]
            /\ UNCHANGED <<ch, otherFired>>
       ELSE \E b \in Best(rs, R) :
              IF \E k \in R : rs[k].c > rs[b].end                  \* 379-390 client check
              THEN /\ wr' = [wr EXCEPT ![w] = WDead]
                   /\ ch' = ClearQueues(w)
                   /\ otherFired' = otherFired \cup {"client386"}
              ELSE LET t == AccTask(S, rs[b].end, rs[b].ip, b) IN  \* 374, 392-394
                   /\ wr' = [wr EXCEPT ![w] = [Await(@, "acc", t) EXCEPT
                                !.dec = [end |-> rs[b].end, ip |-> rs[b].ip, src |-> b]]]
                   /\ Fanout(w, t)                                 \* ALS 304-314
                   /\ UNCHANGED otherFired
    /\ UNCHANGED <<jn, targetFired>>

\* QJM 395-404: accept quorum (395-396), then finalizeLogSegment(S, end) to
\* all (402-403).
WRecoverFinalize(w) ==
    /\ wr[w].pc = "acc"
    /\ Cardinality(Succ(w)) >= Majority
    /\ LET t == FinTask(wr[w].S, wr[w].dec.end) IN
       /\ wr' = [wr EXCEPT ![w] = Await(@, "rfin", t)]
       /\ Fanout(w, t)
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* QJM 404-407, 498: finalize quorum; the writer is active.  The NameNode then
\* has applied every txid up to the recovered end.
WRecoveryDone(w) ==
    /\ wr[w].pc = "rfin"
    /\ Cardinality(Succ(w)) >= Majority
    /\ wr' = [wr EXCEPT ![w] = [Await(@, "act", NoReq) EXCEPT
                 !.last = wr[w].dec.end, !.S = 0, !.dec = NoDec]]
    /\ UNCHANGED <<ch, jn, targetFired, otherFired>>

\* QJM.startLogSegment 430-439 at last+1 (FSEditLog: getLastWrittenTxId()+1).
WStartLogSegment(w) ==
    /\ wr[w].pc = "act"
    /\ wr[w].seg = 0
    /\ wr[w].last + 1 <= MaxTxId
    /\ LET t == StartTask(wr[w].last + 1) IN
       /\ wr' = [wr EXCEPT ![w] = [Await(@, "start", t) EXCEPT !.opened = TRUE]]
       /\ Fanout(w, t)                                             \* ALS 236-243
    /\ UNCHANGED <<jn, targetFired, otherFired>>

WStartLogSegmentDone(w) ==
    /\ wr[w].pc = "start"
    /\ Cardinality(Succ(w)) >= Majority                            \* QJM 436-437
    /\ wr' = [wr EXCEPT ![w] = [Await(@, "act", NoReq) EXCEPT !.seg = wr[w].call.s]]
    /\ UNCHANGED <<ch, jn, targetFired, otherFired>>

\* QuorumOutputStream.flushAndSync 89-112: one batch of n txns.
WSendEdits(w, n) ==
    /\ wr[w].pc = "act"
    /\ wr[w].seg # 0
    /\ n >= 1 /\ wr[w].last + n <= MaxTxId
    /\ LET t == JrnlTask(wr[w].seg, wr[w].last + 1, wr[w].last + n) IN
       /\ wr' = [wr EXCEPT ![w] = Await(@, "send", t)]
       /\ Fanout(w, t)                                             \* ALS 254-263
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* QOS 113-118: write quorum, then setCommittedTxId on every channel.
WSendEditsDone(w) ==
    /\ wr[w].pc = "send"
    /\ Cardinality(Succ(w)) >= Majority
    /\ wr' = [wr EXCEPT ![w] = [Await(@, "act", NoReq) EXCEPT
                 !.c = wr[w].call.e, !.last = wr[w].call.e]]       \* ALS 75-79, ILC 189-195
    /\ UNCHANGED <<ch, jn, targetFired, otherFired>>

\* QJM.finalizeLogSegment 443-448 (log roll or close).
WFinalizeLogSegment(w) ==
    /\ wr[w].pc = "act"
    /\ wr[w].seg # 0
    /\ wr[w].last >= wr[w].seg
    /\ LET t == FinTask(wr[w].seg, wr[w].last) IN
       /\ wr' = [wr EXCEPT ![w] = Await(@, "fin", t)]
       /\ Fanout(w, t)                                             \* ALS 245-252
    /\ UNCHANGED <<jn, targetFired, otherFired>>

WFinalizeLogSegmentDone(w) ==
    /\ wr[w].pc = "fin"
    /\ Cardinality(Succ(w)) >= Majority
    /\ wr' = [wr EXCEPT ![w] = [Await(@, "act", NoReq) EXCEPT !.seg = 0]]
    /\ UNCHANGED <<ch, jn, targetFired, otherFired>>

\* QJM.purgeLogsOlderThan 466-471 -> ALS 107-111: fire and forget; may be
\* issued while another call of the same writer is outstanding.
WPurgeLogsOlderThan(w, m) ==
    /\ wr[w].pc \in ActivePC
    /\ m \in Seg
    /\ Fanout(w, PurgeTask(m))
    /\ UNCHANGED <<wr, jn, targetFired, otherFired>>

\* waitForWriteQuorum fails: every JN answered and fewer than a majority
\* succeeded (QC 175, ALS 142-145).  The NameNode terminates (FSEditLog
\* 739-749) or the QJM is abandoned.
WQuorumFail(w) ==
    /\ wr[w].pc \in WaitPC
    /\ Responded(w) = JN
    /\ Cardinality(Succ(w)) < Majority
    /\ wr' = [wr EXCEPT ![w] = WDead]
    /\ ch' = ClearQueues(w)
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* QuorumCall.checkAssertionErrors 243-257 (-ea): a JN AssertionError is
\* rethrown at the writer even when a quorum succeeded.
WQuorumAssertRethrow(w) ==
    /\ AssertsEnabled
    /\ wr[w].pc \in WaitPC
    /\ \E j \in JN : wr[w].resp[j].k = "aerr"
    /\ wr' = [wr EXCEPT ![w] = WDead]
    /\ ch' = ClearQueues(w)
    /\ UNCHANGED <<jn, targetFired, otherFired>>

\* The writer's process dies or its wait times out.  Tasks not yet started
\* are lost (they live in the NameNode JVM); calls already in flight may
\* still run at the JN.
WCrash(w) ==
    /\ wr[w].pc \notin {"init", "dead"}
    /\ wr' = [wr EXCEPT ![w] = WDead]
    /\ ch' = ClearQueues(w)
    /\ UNCHANGED <<jn, targetFired, otherFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Next-state relation                                                      *)
(***************************************************************************)

WriterNext(w) ==
    \/ WRecoverUnfinalizedSegments(w)
    \/ \E R \in SUBSET JN : WCreateNewUniqueEpoch(w, R)
    \/ \E R \in SUBSET JN : WRecoverPrepare(w, R)
    \/ \E R \in SUBSET JN : WRecoverDecide(w, R)
    \/ WRecoverFinalize(w)
    \/ WRecoveryDone(w)
    \/ WStartLogSegment(w)
    \/ WStartLogSegmentDone(w)
    \/ \E n \in 1..MaxTxId : WSendEdits(w, n)
    \/ WSendEditsDone(w)
    \/ WFinalizeLogSegment(w)
    \/ WFinalizeLogSegmentDone(w)
    \/ \E m \in Seg : WPurgeLogsOlderThan(w, m)
    \/ WQuorumFail(w)
    \/ WQuorumAssertRethrow(w)
    \/ WCrash(w)

ChannelNext(w, j) ==
    \/ ChDispatch(w, j)
    \/ ChHeartbeat(w, j)
    \/ ChOutOfSync(w, j)
    \/ ChReject(w, j)
    \/ RpcDrop(w, j)
    \/ RpcConnectFail(w, j)
    \/ RpcLate(w, j)

JNHandle(j, w, src, lose) ==
    \/ JNGetJournalState(j, w, src, lose)
    \/ JNNewEpoch(j, w, src, lose)
    \/ JNHeartbeat(j, w, src, lose)
    \/ JNJournal(j, w, src, lose)
    \/ JNStartLogSegment(j, w, src, lose)
    \/ JNFinalizeLogSegment(j, w, src, lose)
    \/ JNPurgeLogsOlderThan(j, w, src, lose)
    \/ JNPrepareRecovery(j, w, src, lose)
    \/ JNAcceptRecovery(j, w, src, lose)

Next ==
    /\ ~targetFired                    \* stop once the target has thrown
    /\ \/ \E w \in W : WriterNext(w)
       \/ \E w \in W, j \in JN : ChannelNext(w, j)
       \/ \E j \in JN, w \in W, src \in {"in", "zb"}, lose \in BOOLEAN :
              JNHandle(j, w, src, lose)
       \/ \E j \in JN, w \in W, src \in {"in", "zb"} :
              TargetCheck(j, w, src) \/ JNAcceptRecoveryCrash(j, w, src)
       \/ \E j \in JN : JNCrash(j) \/ JNRestart(j)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                               *)
(***************************************************************************)

\* The ad hoc check never takes its failing branch (Journal.java:924-926).
TargetSafe == ~targetFired

\* Sanity (temporary): some acceptRecovery can reach line 924.  Must be
\* VIOLATED in MC.cfg, otherwise the model never exercises the check.
AcceptReachesGuard(j, w, src) ==
    LET r  == ReqAt(w, j, src)
        cr == CheckReq(jn[j], r)
    IN /\ jn[j].up
       /\ r.rop = "acc"
       /\ cr.ok
       /\ AcceptPre(cr.st, r).path = "guard"
TargetReached ==
    ~\E j \in JN, w \in W, src \in {"in", "zb"} : AcceptReachesGuard(j, w, src)

\* Structural 1: domains of all variables.  The last conjunct says the state
\* is representable: the model never produced two strictly named files with
\* one start txid (getLogFile would throw ISE, FJM 516-519).
ReqT  == [op: Ops \cup {"none"}, rop: Ops \cup {"hb", "none"}, s: Txn0, f: Txn0,
          e: Txn0, ip: BOOLEAN, src: JN \cup {NoJN}, x: Ep, ep: Ep, c: Txn0,
          ov: BOOLEAN]
RespT == [k: {"none", "ok", "err", "aerr"}, pe: Ep, ls: Txn0, has: BOOLEAN,
          end: Txn0, ip: BOOLEAN, ae: Ep, lwe: Ep, c: Txn0]
FileT == [ex: BOOLEAN, end: Txn0, ip: BOOLEAN]
PaxT  == [ex: BOOLEAN, ep: Ep, end: Txn0, ip: BOOLEAN]
TmpT  == [s: Seg, ep: Ep, end: Txn0]
JNT   == [up: BOOLEAN, pr: Ep, lwe: Ep, c: Txn0, files: [Seg -> FileT],
          paxos: [Seg -> PaxT], tmp: SUBSET TmpT, cs: Txn0,
          nx: 0..(MaxTxId + 1), fc: Txn0]
ChT   == [q: Seq(ReqT), inf: ReqT, zb: ReqT, oos: BOOLEAN, hb: BOOLEAN]
DecT  == [end: Txn0, ip: BOOLEAN, src: JN \cup {NoJN}]
WT    == [pc: PCs, ep: Ep, c: Txn0, call: ReqT, resp: [JN -> RespT], S: Txn0,
          dec: DecT, seg: Txn0, last: Txn0, opened: BOOLEAN]

TypeOK ==
    /\ jn \in [JN -> JNT]
    /\ ch \in [W -> [JN -> ChT]]
    /\ wr \in [W -> WT]
    /\ targetFired \in BOOLEAN
    /\ otherFired \subseteq OtherKinds
    /\ "dupSeg" \notin otherFired

\* Structural 2: a message carries only values its sender held.  A call in
\* flight (or late) of a live writer carries that writer's epoch and a
\* committedTxId no larger than the writer's (both are monotone); the
\* writer's committedTxId is one of its own acknowledged batch ends.
ReqCarriesSenderC ==
    \A w \in W :
      wr[w].pc \notin {"init", "dead"} =>
        /\ wr[w].c <= wr[w].last
        /\ \A j \in JN :
             \A r \in {ch[w][j].inf, ch[w][j].zb} :
               r # NoReq =>
                 /\ r.c <= wr[w].c
                 /\ r.op \notin {"gjs", "ne"} => r.ep = wr[w].ep
=============================================================================
