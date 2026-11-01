-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-09: can Journal.checkRequest throw at Journal.java:504?      *)
(*                                                                         *)
(* Target (pinned tree 734dd8a67cd):                                       *)
(*   Journal.checkRequest(RequestInfo), J:484-512,                         *)
(*     if (reqInfo.hasCommittedTxId()) {                                   *)
(*       Preconditions.checkArgument(                     <- J:504         *)
(*           reqInfo.getCommittedTxId() >= committedTxnId.get(), ...);     *)
(*       committedTxnId.set(reqInfo.getCommittedTxId());  <- J:510         *)
(*     }                                                                   *)
(*   thrown: java.lang.IllegalArgumentException (Preconditions.java:185);  *)
(*   frame Journal.checkRequest(Journal.java:504).                         *)
(*                                                                         *)
(* phi_T(j, r) == r.ct # INVALID_TXID /\ r.ct < committedTxnId(j),         *)
(* evaluated after the epoch check (J:486-494) and the IPC-serial check    *)
(* (J:497-501) passed.  TargetSafe == ~targetFired.                        *)
(*                                                                         *)
(* Category A (distributed, message passing): writer incarnations (QJM     *)
(* instances driven by an NN), 3 JournalNodes, per-(writer, JN) FIFO       *)
(* executor channels.  Every Journal RPC handler is synchronized on the    *)
(* Journal object, so each JN-side handler is one atomic step.             *)
(*                                                                         *)
(* Path legend (hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/  *)
(* hadoop/hdfs/ unless noted):                                             *)
(*   J    qjournal/server/Journal.java                                     *)
(*   JNRS qjournal/server/JournalNodeRpcServer.java                        *)
(*   IPC  qjournal/client/IPCLoggerChannel.java                            *)
(*   ALS  qjournal/client/AsyncLoggerSet.java                              *)
(*   QC   qjournal/client/QuorumCall.java                                  *)
(*   QJM  qjournal/client/QuorumJournalManager.java                        *)
(*   QOS  qjournal/client/QuorumOutputStream.java                          *)
(*   SRC  qjournal/client/SegmentRecoveryComparator.java                   *)
(*   PBS  qjournal/protocolPB/QJournalProtocolServerSideTranslatorPB.java  *)
(*   BELF util/BestEffortLongFile.java, PLF util/PersistentLongFile.java   *)
(*   FJM  server/namenode/FileJournalManager.java                          *)
(*   FSEL server/namenode/FSEditLog.java, FSN .../FSNamesystem.java        *)
(*   FSI  server/namenode/FSImage.java,  JS  .../JournalSet.java           *)
(*   ELT  server/namenode/ha/EditLogTailer.java                            *)
(*                                                                         *)
(* Scenario map (modeling-brief.md section 2):                             *)
(*   S1 failover with swallowed read failures: DoTailEdits,                *)
(*      CatchupDuringFailover and OpenForWrite (ok = FALSE branches),      *)
(*      mid-segment StartLogSegment.                                       *)
(*   S2 history rewind: RollingRollbackDiscard / DiscardH (unfenced,       *)
(*      non-durable lowering), PowerLoss over ctHist (S2a), late delivery  *)
(*      of a stopped writer's RPC (WriterCrash keep, DeliverLate) (S2b).   *)
(*   S3 recovery truncation: full newEpoch / prepare / accept / finalize,  *)
(*      comparator, heartbeats and purges to out-of-sync JNs, JN and       *)
(*      writer crashes, message loss.                                      *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets, TLC

CONSTANTS
    JN,                \* JournalNodes (model values); MiniJournalCluster has 3 (MJC:53)
    NoJN,              \* model value: "no JournalNode"
    NumWriters,        \* writer incarnations = QJM instances (one per NN active period)
    MaxTxId,           \* highest txid a writer may write
    MaxBatch,          \* most txns in one sendEdits batch (QOS:89-112)
    InProgressTailing, \* dfs.ha.tail-edits.in-progress (DFSConfigKeys:1387 default false;
                       \*   the workload sets it true, TQJM:117)
    LaunchModes        \* NN flows a writer w > 1 may take: SUBSET {"normal", "rollback"}

ASSUME /\ NumWriters \in Nat \ {0}
       /\ MaxTxId \in Nat \ {0}
       /\ MaxBatch \in Nat \ {0}
       /\ InProgressTailing \in BOOLEAN
       /\ LaunchModes \subseteq {"normal", "rollback"}
       /\ NoJN \notin JN

Writer == 1..NumWriters

INVALID_TXID == -12345                 \* HdfsServerConstants.INVALID_TXID

\* An edit log file in a JN's current/ directory (FJM.EditLogFile): first txid s, last txid e
\* (INVALID_TXID when an in-progress file holds no transaction), ip = in progress.
NoFile == [s |-> 0, e |-> 0, ip |-> FALSE]

Majority == Cardinality(JN) \div 2 + 1 \* ALS:153-155 getMajoritySize

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min2(a, b) == IF a < b THEN a ELSE b

(***************************************************************************)
(* State                                                                   *)
(*   jn[j]     one JournalNode's Journal for the workload's journal id     *)
(*   wr[w]     writer incarnation w: its NN control flow and QJM/QOS state *)
(*   ch[w][j]  IPCLoggerChannel of writer w to JN j                        *)
(***************************************************************************)
VARIABLES
    jn,          \* [JN -> JNState]
    wr,          \* [Writer -> WriterState]
    ch,          \* [Writer -> [JN -> ChanState]]
    targetFired  \* TRUE once Journal.java:504 threw

vars == <<jn, wr, ch, targetFired>>

\* JournalNode state.  prom = lastPromisedEpoch (PLF, fsynced, J:106); lwe = lastWriterEpoch
\* (PLF, J:125); sn = currentEpochIpcSerial (volatile, J:117); ct = committedTxnId as the
\* process sees it (BELF value / page cache, J:133); ctHist = the values the committed-txid
\* page has held since its content was last known to be on disk: BELF never fsyncs
\* (BELF:68-75), the OS may write the dirty page back at any moment, so after a power loss the
\* file may hold any of them; segs = edit log files; cur = curSegmentTxId (J:91,
\* INVALID_TXID iff curSegment == null); next = nextTxId (J:93); paxos = persisted accepted
\* recovery data, one [ep, seg] per segment (J:1073-1123); up = JN process running;
\* part = the JN host is cut off from the network (fault).
JNInit == [prom |-> 0, lwe |-> 0, sn |-> -1, ct |-> INVALID_TXID, ctHist |-> {INVALID_TXID},
           segs |-> {}, cur |-> INVALID_TXID, next |-> INVALID_TXID, paxos |-> {}, up |-> TRUE,
           part |-> FALSE]

\* Writer state.  ph = control-flow location; mode = "normal" (startup / failover) or
\* "rollback" (rolling-upgrade rollback, FSI:772-797); ep = epoch on the loggers (ALS:61-68,
\* IPC:184-186); prop = epoch proposed in newEpoch (QJM:242); acc = max over quorum responses
\* (QJM:236-239, 485-491); rseg = segment under recovery; prep = prepareRecovery responses;
\* log/src = logToSync and its source logger (QJM:374, 392); ct = committedTxId of every
\* channel (IPC:98, set via ALS:75-79); call = id of the QuorumCall being waited on; ok/fail =
\* loggers that answered it; seg = open segment (QOS segmentTxId); next = FSEditLog's next txid;
\* pend = last txid of the batch in flight; applied = NN lastAppliedTxId; ckpt = rollback image.
WInit == [ph |-> "idle", mode |-> "normal", ep |-> 0, prop |-> 0, acc |-> 0, rseg |-> 0,
          prep |-> {}, log |-> NoFile, src |-> NoJN, ct |-> INVALID_TXID, call |-> 0,
          ok |-> {}, fail |-> {}, seg |-> INVALID_TXID, next |-> 1, pend |-> 0, applied |-> 0,
          ckpt |-> 0]

\* Channel state.  ipc = ipcSerial (IPC:96); oos = outOfSync (IPC:146); hb = heartbeat
\* stopwatch running (IPC:151, 436-443); q = tasks queued on the single-thread executor
\* (IPC:89, FIFO); hct = the committedTxId that createReqInfo (IPC:287-291) takes for the head
\* task (see HeadCt); late = an RPC already on the wire when the writer died.
ChInit == [ipc |-> 0, oos |-> FALSE, hb |-> FALSE, q |-> <<>>, hct |-> INVALID_TXID,
           late |-> <<>>]

Init ==
    /\ jn = [j \in JN |-> JNInit]           \* formatted journals (TQJM:127 qjm.format)
    /\ wr = [w \in Writer |-> WInit]
    /\ ch = [w \in Writer |-> [j \in JN |-> ChInit]]
    /\ targetFired = FALSE

(***************************************************************************)
(* JournalNode storage helpers                                             *)
(***************************************************************************)

\* Journal.scanStorageForLatestEdits, J:221-246: take the file with the highest first txid
\* (J:227-230); if it holds no transaction (J:233) move it aside (J:238) and look again.
RECURSIVE ScanLatest(_)
ScanLatest(S) ==
    IF S = {} THEN [segs |-> S, latest |-> NoFile]                      \* J:244-245
    ELSE LET l == CHOOSE f \in S : \A g \in S : g.s <= f.s IN
         IF l.e = INVALID_TXID THEN ScanLatest(S \ {l})                 \* J:233-238
         ELSE [segs |-> S, latest |-> l]                                \* J:239-240

\* Journal.getSegmentInfo, J:799-822.
SegInfo(S, s) ==
    LET F == {f \in S : f.s = s} IN                                     \* J:801 fjm.getLogFile
    IF F = {} THEN [info |-> NoFile, segs |-> S]                        \* J:802-804
    ELSE LET f == CHOOSE x \in F : TRUE IN
         IF f.e = INVALID_TXID                                          \* J:805-808 scan: no txns
         THEN [info |-> NoFile, segs |-> S \ {f}]                       \* J:809-812 move aside
         ELSE [info |-> f, segs |-> S]                                  \* J:814-818

\* Range.between(seg.s, seg.e).contains(x), J:988-992.
InRange(x, f) == f.s <= x /\ x <= f.e

\* Highest txid stored in JN state js (what a reader can see; J:470 highestWrittenTxId).
WrittenEnd(js) ==
    LET E == {f.e : f \in js.segs} \ {INVALID_TXID} IN IF E = {} THEN 0 ELSE Max(E)

\* A JN that a client (or another JN's HTTP fetch) can talk to.
Reach(js) == js.up /\ ~js.part

\* BestEffortLongFile.set (BELF:68-75): positional write into the page cache, no force.  The
\* written value joins the candidates for the on-disk content.  (MC.tla may override HistAdd
\* when no power loss can happen, since ctHist is read only by PowerLoss.)
HistAdd(H, v) == H \cup {v}
SetCt(js, v) == [js EXCEPT !.ct = v, !.ctHist = HistAdd(js.ctHist, v)]

(***************************************************************************)
(* Journal.checkRequest (J:484-512) and the target                         *)
(***************************************************************************)

\* RPC kinds that carry a RequestInfo and therefore run checkRequest first:
\* journal (J:397->515), heartbeat (J:476), startLogSegment (J:572), finalizeLogSegment
\* (J:632), purgeLogsOlderThan (J:693), prepareRecovery (J:830), acceptRecovery (J:875).
IsRI(k) == k \in {"journal", "heartbeat", "start", "finalize", "purge", "prepare", "accept"}

EpochLow(js, r)  == r.ep < js.prom                                      \* J:486
PromAfter(js, r) == IF r.ep > js.prom THEN r.ep ELSE js.prom            \* J:490-494 -> J:371
SnBefore(js, r)  == IF r.ep > js.prom THEN -1 ELSE js.sn                \* J:375 serial reset
SerialOK(js, r)  == r.sn > SnBefore(js, r)                              \* J:497-500

\* phi_T: the failing branch of J:503-505 as the code evaluates it.  hasCommittedTxId() is
\* committedTxId != INVALID_TXID (RequestInfo.java:69-71); an absent proto field reads as
\* INVALID_TXID (PBS:286-287; the client omits it, QJournalProtocolTranslatorPB.java:189-191).
Phi_T(js, r) == r.ct # INVALID_TXID /\ r.ct < js.ct

\* The code path that reaches the target guard: a RequestInfo RPC passed J:486 and J:497 and
\* carries a committed txid (J:503).
TargetPath(js, r) == IsRI(r.k) /\ ~EpochLow(js, r) /\ SerialOK(js, r) /\ r.ct # INVALID_TXID

\* TargetCheck: J:503-511, evaluated by JN j on RPC r.  Enabled exactly when the path is taken.
TargetCheck(j, r) ==
    /\ TargetPath(jn[j], r)                     \* J:486, J:497 passed; J:503 hasCommittedTxId()
    /\ IF r.ct < jn[j].ct                       \* J:504-505: committedTxId >= committedTxnId.get() fails
         THEN targetFired' = TRUE               \* J:504 checkArgument -> IllegalArgumentException
         ELSE targetFired' = targetFired        \* J:510 committedTxnId.set(...), handler continues

(***************************************************************************)
(* JournalNode RPC handlers.  Each returns the new state of JN j (js), the *)
(* outcome seen by the caller (ok) and response data (resp).               *)
(***************************************************************************)

\* Journal.journal J:393-473 after checkWriteRequest's checkRequest (J:397, J:515).
\* r.a = segmentTxId, r.b = firstTxnId, r.c = lastTxnId (J:427).
JournalCont(js, r) ==
    IF r.ep # js.lwe                                                    \* J:517-521 IOException
    THEN [js |-> js, ok |-> FALSE, resp |-> 0]
    ELSE IF js.cur = INVALID_TXID                                       \* J:405-406 no segment open
    THEN [js |-> js, ok |-> FALSE, resp |-> 0]
    ELSE IF js.cur # r.a                                                \* J:408-421 abortCurSegment,
    THEN [js |-> [js EXCEPT !.cur = INVALID_TXID], ok |-> FALSE, resp |-> 0] \*  JournalOutOfSync
    ELSE IF js.next # r.b                                               \* J:423-425
    THEN [js |-> js, ok |-> FALSE, resp |-> 0]
    ELSE [js |-> [js EXCEPT                                             \* J:442-446 write + flush
                     !.segs = {IF f.s = js.cur /\ f.ip THEN [f EXCEPT !.e = r.c] ELSE f
                               : f \in js.segs},                        \* (a trashed file stays invisible)
                     !.next = r.c + 1],                                 \* J:471
          ok |-> TRUE, resp |-> 0]

\* Journal.startLogSegment J:568-624 after checkRequest (J:572).  r.a = txid.
StartCont(js, r) ==
    LET js1 == [js EXCEPT !.cur = INVALID_TXID]                         \* J:574-583 abortCurSegment
        ex  == {f \in js.segs : f.s = r.a}                              \* J:588 fjm.getLogFile(txid)
    IN IF \E f \in ex : ~f.ip                                           \* J:590-593 ISE: finalized
       THEN [js |-> js1, ok |-> FALSE, resp |-> 0]
       ELSE IF \E f \in ex : f.e # f.s                                  \* J:598-603 ISE: more than one
       THEN [js |-> js1, ok |-> FALSE, resp |-> 0]                      \*   txn (an empty file scans to
                                                                        \*   INVALID_TXID # first txid)
       ELSE [js |-> [js1 EXCEPT
                       !.lwe   = r.ep,                                  \* J:606-612
                       !.paxos = {p \in js.paxos : p.seg.s # r.a},      \* J:618 purgePaxosDecision
                       !.segs  = (js.segs \ ex) \cup                    \* J:620 FJM:121-128 create
                                 {[s |-> r.a, e |-> INVALID_TXID, ip |-> TRUE]},
                       !.cur   = r.a,                                   \* J:621
                       !.next  = r.a],                                  \* J:623
             ok |-> TRUE, resp |-> 0]

\* Journal.finalizeLogSegment J:629-685 after checkRequest (J:632).
\* r.a = startTxId, r.b = endTxId.
FinalizeCont(js, r) ==
    LET atCur == r.a = js.cur                                           \* J:637
        js1   == IF atCur THEN [js EXCEPT !.cur = INVALID_TXID] ELSE js  \* J:638-643 close
        elf   == {f \in js.segs : f.s = r.a}                            \* J:654
        unpax == {p \in js.paxos : p.seg.s # r.a}                       \* J:684 purgePaxosDecision
    IN IF atCur /\ js.next # r.b + 1                                    \* J:645-648
       THEN [js |-> js1, ok |-> FALSE, resp |-> 0]
       ELSE IF elf = {}                                                 \* J:655-658
       THEN [js |-> js1, ok |-> FALSE, resp |-> 0]
       ELSE LET f == CHOOSE x \in elf : TRUE IN
            IF f.ip
            THEN IF ~atCur /\ f.e # r.b                                 \* J:661-671 validation
                 THEN [js |-> js1, ok |-> FALSE, resp |-> 0]
                 ELSE [js |-> [js1 EXCEPT                               \* J:672 FJM:139-160 rename
                                 !.segs  = (js.segs \ {f}) \cup {[s |-> r.a, e |-> r.b, ip |-> FALSE]},
                                 !.paxos = unpax],
                       ok |-> TRUE, resp |-> 0]
            ELSE IF r.b # f.e                                           \* J:674-677 IAE at J:674
                 THEN [js |-> js1, ok |-> FALSE, resp |-> 0]            \*   (not the target line)
                 ELSE [js |-> [js1 EXCEPT !.paxos = unpax], ok |-> TRUE, resp |-> 0]

\* Journal.prepareRecovery J:827-866 after checkRequest (J:830).  r.a = segmentTxId.
\* completeHalfDoneAcceptRecovery (J:838, 1051-1068) is a no-op here: AcceptCont persists the
\* paxos data and renames the synced file in one step.
PrepareCont(js, r) ==
    LET prev   == {p \in js.paxos : p.seg.s = r.a}                      \* J:837
        si     == SegInfo(js.segs, r.a)                                 \* J:840
        hasFin == si.info # NoFile /\ ~si.info.ip                       \* J:841
        useAcc == prev # {} /\ ~hasFin                                  \* J:843
        p      == IF prev = {} THEN [ep |-> 0, seg |-> NoFile] ELSE CHOOSE x \in prev : TRUE
    IN [js   |-> [js EXCEPT !.cur = INVALID_TXID, !.segs = si.segs],    \* J:832, J:840
        ok   |-> TRUE,
        resp |-> [hasSeg |-> useAcc \/ si.info # NoFile,                \* J:849-854
                  seg    |-> IF useAcc THEN p.seg ELSE si.info,
                  acc    |-> IF useAcc THEN p.ep ELSE 0,                \* J:849 (proto default 0)
                  lwe    |-> js.lwe,                                    \* J:857
                  lct    |-> js.ct]]                                    \* J:858-860 (INVALID = absent)

\* Journal.acceptRecovery J:871-986 after checkRequest (J:875).
\* r.f = segment to accept (the writer's logToSync), r.src = logger whose URL is used (QJM:392);
\* srcJs = that JN's state.  J:883-886 holds for every segment the model builds.
AcceptCont(js, r, srcJs) ==
    LET seg  == r.f
        js1  == [js EXCEPT !.cur = INVALID_TXID]                        \* J:877 abortCurSegment
        old  == {p \in js.paxos : p.seg.s = seg.s}                      \* J:888
        cur  == SegInfo(js.segs, seg.s)                                 \* J:906
        sync == cur.info = NoFile \/ cur.info.e # seg.e                 \* J:907-908
        js2  == [js1 EXCEPT !.segs = cur.segs]
        srcF == {f \in srcJs.segs : f.s = seg.s}
    IN IF \E p \in old : p.ep > r.ep                                    \* J:897-902 AssertionError
       THEN [js |-> js1, ok |-> FALSE, resp |-> 0]
       ELSE IF sync /\ cur.info # NoFile                                \* J:924-934 AssertionError
               /\ InRange(js.ct, cur.info) /\ ~InRange(js.ct, seg)
       THEN [js |-> js2, ok |-> FALSE, resp |-> 0]
       ELSE IF sync /\ cur.info # NoFile /\ ~cur.info.ip                \* J:938-940 AssertionError
       THEN [js |-> js2, ok |-> FALSE, resp |-> 0]
       ELSE IF sync /\ (~Reach(srcJs) \/ srcF = {})                     \* J:948 syncLog: HTTP fetch fails
       THEN [js |-> js2, ok |-> FALSE, resp |-> 0]
       ELSE [js |-> [js2 EXCEPT
                       !.paxos = {p \in js.paxos : p.seg.s # seg.s}     \* J:975-977 persistPaxosData
                                 \cup {[ep |-> r.ep, seg |-> seg]},
                       !.segs  = IF sync                                \* J:979-982 replaceFile
                                 THEN {f \in cur.segs : f.s # seg.s} \cup
                                      {[s |-> seg.s, e |-> (CHOOSE f \in srcF : TRUE).e, ip |-> TRUE]}
                                 ELSE cur.segs],
             ok |-> TRUE, resp |-> 0]

\* JNRS:178-188 getJournalState -> Journal.getLastPromisedEpoch J:284-287 (no RequestInfo).
GetJournalStateH(js, r) == [js |-> js, ok |-> TRUE, resp |-> js.prom]

\* Journal.newEpoch J:339-365 (no RequestInfo).  r.a = proposed epoch.
NewEpochH(js, r) ==
    IF r.a <= js.prom                                                   \* J:347-350 IOException
    THEN [js |-> js, ok |-> FALSE, resp |-> 0]
    ELSE LET sc == ScanLatest(js.segs) IN                               \* J:358
         [js   |-> [js EXCEPT !.prom = r.a, !.sn = -1,                  \* J:352 -> J:371-375
                              !.cur  = INVALID_TXID,                    \* J:353 abortCurSegment
                              !.segs = sc.segs],
          ok   |-> TRUE,
          resp |-> sc.latest.s]                                         \* J:360-362 (0 = unset)

\* Journal.discardSegments J:1198-1202 -> FJM.discardEditLogSegments FJM:273-293
\* (no RequestInfo, no epoch).  r.a = startTxId.
DiscardH(js, r) ==
    IF \E f \in js.segs : f.s < r.a /\ ~f.ip /\ f.e >= r.a              \* FJM:283-285 checkState;
    THEN [js |-> js, ok |-> FALSE, resp |-> 0]                          \*   in-progress files carry
                                                                        \*   INVALID_TXID (FJM:339)
    ELSE [js |-> [SetCt(js, r.a - 1) EXCEPT                          \* J:1201 BELF.set, no fsync
                     !.segs = {f \in js.segs : f.s < r.a}],             \* FJM:280-292 -> .trash
          ok |-> TRUE, resp |-> 0]

\* JN j runs RequestInfo RPC r: checkRequest (J:484-512) then the method body.  checkRequest's
\* promise and serial updates persist when a later check throws.
HandleRI(j, r) ==
    LET js == jn[j] IN
    IF EpochLow(js, r)                                                  \* J:486-489 IOException
    THEN [js |-> js, ok |-> FALSE, resp |-> 0]
    ELSE IF ~SerialOK(js, r)                                            \* J:497-500 OutOfSync
    THEN [js |-> [js EXCEPT !.prom = PromAfter(js, r), !.sn = SnBefore(js, r)],
          ok |-> FALSE, resp |-> 0]
    ELSE LET js1 == [js EXCEPT !.prom = PromAfter(js, r), !.sn = r.sn] IN \* J:493, J:501
         IF Phi_T(js, r)                                                \* J:504 throws (TargetCheck)
         THEN [js |-> js1, ok |-> FALSE, resp |-> 0]
         ELSE LET js2 == IF r.ct # INVALID_TXID THEN SetCt(js1, r.ct) ELSE js1 IN   \* J:510
              CASE r.k = "journal"   -> JournalCont(js2, r)
                [] r.k = "heartbeat" -> [js |-> js2, ok |-> TRUE, resp |-> 0]   \* J:475-477
                [] r.k = "start"     -> StartCont(js2, r)
                [] r.k = "finalize"  -> FinalizeCont(js2, r)
                [] r.k = "purge"     -> [js |-> js2, ok |-> TRUE, resp |-> 0]   \* J:690-696
                [] r.k = "prepare"   -> PrepareCont(js2, r)
                [] r.k = "accept"    -> AcceptCont(js2, r, IF r.src = j THEN js2 ELSE jn[r.src])

HandleRPC(j, r) ==
    CASE IsRI(r.k)        -> HandleRI(j, r)
      [] r.k = "gjs"      -> GetJournalStateH(jn[j], r)
      [] r.k = "newEpoch" -> NewEpochH(jn[j], r)
      [] r.k = "discard"  -> DiscardH(jn[j], r)

\* JN j executes RPC r atomically under the Journal monitor (J:393, 484, 568, 629, 690, 827,
\* 871, 1198 are synchronized; JNRS:178-232 dispatch).
JNDeliver(j, r) ==
    /\ jn' = [jn EXCEPT ![j] = HandleRPC(j, r).js]
    /\ IF TargetPath(jn[j], r) THEN TargetCheck(j, r) ELSE targetFired' = targetFired

(***************************************************************************)
(* Writer-side channel (IPCLoggerChannel)                                  *)
(***************************************************************************)

\* A task queued on the single-thread executor (IPC:357, 475, 491, 500, 528, 542, 590, ...).
\* k: "gjs" | "newEpoch" | "prepare" | "accept" | "finalize" | "start" | "journal" | "purge" |
\* "discard"; a, b, c: integer arguments; f: segment argument (accept); src: URL source
\* (accept); call: the QuorumCall it belongs to (0 = fire-and-forget purge, QJM:466-471).
Op(k, a, b, c, f, src, call) ==
    [k |-> k, a |-> a, b |-> b, c |-> c, f |-> f, src |-> src, call |-> call]

\* The single-thread executor starts a task as soon as it heads the queue: at submit when the
\* executor is idle, else when the previous task completed (IPC:85-89, 241-250).  The task body
\* calls createReqInfo first (IPC:362, 439, 476, 493, 501, 536, 543), so the RequestInfo carries
\* the writer's committedTxId of that moment, even if the JN serves the RPC only after the
\* writer resolved more batches through other loggers.  HeadCt is that snapshot for the head of
\* queue q (INVALID_TXID when q is empty or its head sends no RequestInfo, to keep states
\* canonical).  The other RequestInfo fields cannot change in between: the epoch is fixed before
\* the first RequestInfo task (ResolveNewEpoch) and only this channel's own tasks move ipcSerial.
\* prepareRecovery may first send a raw getJournalState (IPC:529-535), but a writer's committed
\* txid is INVALID_TXID throughout recovery.
HeadCt(w, q) == IF q # <<>> /\ IsRI(Head(q).k) THEN wr[w].ct ELSE INVALID_TXID

\* The RPC the head task sends.  createReqInfo (IPC:287-291) snapshots epoch, ipcSerial++ and
\* committedTxId together under the channel lock; only RequestInfo kinds use the snapshot.
RpcOf(w, j, o) ==
    [k |-> o.k, a |-> o.a, b |-> o.b, c |-> o.c, f |-> o.f, src |-> o.src,
     ep |-> wr[w].ep, sn |-> ch[w][j].ipc, ct |-> ch[w][j].hct]

\* heartbeatIfNecessary IPC:435-446: getProxy().heartbeat(createReqInfo()) at IPC:439, at the
\* start of the head (sendEdits / finalize) task.
HbRpc(w, j) ==
    [k |-> "heartbeat", a |-> 0, b |-> 0, c |-> 0, f |-> NoFile, src |-> NoJN,
     ep |-> wr[w].ep, sn |-> ch[w][j].ipc, ct |-> ch[w][j].hct]

\* sendEdits and finalizeLogSegment tasks first call throwIfOutOfSync (IPC:358, 492, 416-423).
OosTask(w, j, o) == o.k \in {"journal", "finalize"} /\ ch[w][j].oos

\* Channel bookkeeping after the head task ends.  riSent: createReqInfo ran (serial consumed);
\* isHb: the out-of-sync prologue tried a heartbeat; okSeen: the caller got a normal reply.
ChanAfter(w, j, o, riSent, isHb, okSeen) ==
    [ch[w][j] EXCEPT
        !.q   = Tail(@),
        !.hct = HeadCt(w, Tail(ch[w][j].q)),                            \* the next task starts
        !.ipc = IF riSent THEN @ + 1 ELSE @,                            \* IPC:290 ipcSerial++
        !.hb  = IF isHb THEN TRUE ELSE @,                               \* IPC:443 restart stopwatch
        !.oos = IF o.k = "journal" /\ ~OosTask(w, j, o) /\ ~okSeen THEN TRUE  \* IPC:363-370
                ELSE IF o.k = "start" /\ okSeen THEN FALSE              \* IPC:477-484
                ELSE @]

\* waitForWriteQuorum (ALS:124-148): waitFor(all, majority, majority) returns on all responses,
\* a majority of successes, or > majority exceptions (QC:175-177); fewer successes than a
\* majority throws (ALS:142-145).
QuorumOk(w)      == Cardinality(wr[w].ok) >= Majority
AllResponded(w)  == wr[w].ok \cup wr[w].fail = JN
QuorumFailed(w)  == ~QuorumOk(w) /\ AllResponded(w)

\* The task's future completes; if it belongs to the QuorumCall being waited on, the writer
\* records it (QC:175-177 counts responses; getResults() keeps successes, QJM:233, 244, 319).
\* Replies to a call the writer already resolved are ignored (see Resolved).
WrAfter(w, j, o, okSeen, resp) ==
    IF o.call = 0 \/ o.call # wr[w].call
    THEN wr[w]
    ELSE IF ~okSeen
    THEN [wr[w] EXCEPT !.fail = @ \cup {j}]
    ELSE CASE o.k \in {"gjs", "newEpoch"} ->                            \* QJM:236-239, 485-491
                [wr[w] EXCEPT !.ok = @ \cup {j}, !.acc = IF resp > @ THEN resp ELSE @]
           [] o.k = "prepare" ->                                        \* QJM:319-321
                [wr[w] EXCEPT !.ok = @ \cup {j},
                              !.prep = @ \cup {[j |-> j, hasSeg |-> resp.hasSeg, seg |-> resp.seg,
                                                acc |-> resp.acc, lwe |-> resp.lwe,
                                                lct |-> resp.lct]}]
           [] OTHER -> [wr[w] EXCEPT !.ok = @ \cup {j}]

\* The executor runs the head task and its own RPC is served by an up JN (normal reply).
ChannelCall(w, j) ==
    /\ ch[w][j].q # <<>>
    /\ Reach(jn[j])
    /\ LET o == Head(ch[w][j].q) IN
       /\ ~OosTask(w, j, o)                                             \* IPC:358, 492 pass
       /\ LET r   == RpcOf(w, j, o)
              res == HandleRPC(j, r)
          IN /\ JNDeliver(j, r)
             /\ ch' = [ch EXCEPT ![w][j] = ChanAfter(w, j, o, IsRI(o.k), FALSE, res.ok)]
             /\ wr' = [wr EXCEPT ![w] = WrAfter(w, j, o, res.ok, res.resp)]

\* An out-of-sync sendEdits/finalize task sends a heartbeat and then fails with
\* JournalOutOfSyncException (IPC:416-423).  The heartbeat is mandatory when the stopwatch has
\* never run (IPC:437) and possible whenever more than 1 s has passed (IPC:436, 153).
ChannelHeartbeat(w, j) ==
    /\ ch[w][j].q # <<>>
    /\ Reach(jn[j])
    /\ LET o == Head(ch[w][j].q) IN
       /\ OosTask(w, j, o)
       /\ JNDeliver(j, HbRpc(w, j))                                     \* IPC:439
       /\ ch' = [ch EXCEPT ![w][j] = ChanAfter(w, j, o, TRUE, TRUE, FALSE)]
       /\ wr' = [wr EXCEPT ![w] = WrAfter(w, j, o, FALSE, 0)]           \* IPC:421

\* Out-of-sync task within the heartbeat interval: no RPC, JournalOutOfSyncException.
ChannelSkip(w, j) ==
    /\ ch[w][j].q # <<>>
    /\ LET o == Head(ch[w][j].q) IN
       /\ OosTask(w, j, o)
       /\ ch[w][j].hb                                                   \* IPC:436-437
       /\ ch' = [ch EXCEPT ![w][j] = ChanAfter(w, j, o, FALSE, FALSE, FALSE)]
       /\ wr' = [wr EXCEPT ![w] = WrAfter(w, j, o, FALSE, 0)]
       /\ UNCHANGED <<jn, targetFired>>

\* The JN process is down (connection refused) or its host is partitioned (connect / call
\* timeout): the task fails.  The serial is consumed because createReqInfo() is evaluated before
\* the proxy call (e.g. IPC:362, 476).
ChannelDown(w, j) ==
    /\ ch[w][j].q # <<>>
    /\ ~Reach(jn[j])
    /\ LET o == Head(ch[w][j].q) IN
       \E hbTry \in (IF ~OosTask(w, j, o) THEN {FALSE}
                     ELSE IF ch[w][j].hb THEN BOOLEAN ELSE {TRUE}) :
          /\ ch' = [ch EXCEPT ![w][j] =
                      ChanAfter(w, j, o, IF OosTask(w, j, o) THEN hbTry ELSE IsRI(o.k), hbTry, FALSE)]
          /\ wr' = [wr EXCEPT ![w] = WrAfter(w, j, o, FALSE, 0)]
          /\ UNCHANGED <<jn, targetFired>>

\* Fault: the head task's RPC is lost on the network.  lostReply = FALSE: the request never
\* reaches the JN; TRUE: the JN runs the handler but the reply is lost.  Either way the caller
\* sees an IOException (no RetryInvocationHandler; a written call is never re-sent).  For an
\* out-of-sync task the RPC is its heartbeat; losing that reply changes nothing (the task fails
\* anyway), so only the lost request is a separate case.
MsgLoss(w, j, lostReply) ==
    /\ ch[w][j].q # <<>>
    /\ Reach(jn[j])
    /\ LET o == Head(ch[w][j].q) IN
       IF OosTask(w, j, o)
       THEN /\ ~lostReply
            /\ ch' = [ch EXCEPT ![w][j] = ChanAfter(w, j, o, TRUE, TRUE, FALSE)]
            /\ wr' = [wr EXCEPT ![w] = WrAfter(w, j, o, FALSE, 0)]
            /\ UNCHANGED <<jn, targetFired>>
       ELSE /\ IF lostReply THEN JNDeliver(j, RpcOf(w, j, o)) ELSE UNCHANGED <<jn, targetFired>>
            /\ ch' = [ch EXCEPT ![w][j] = ChanAfter(w, j, o, IsRI(o.k), FALSE, FALSE)]
            /\ wr' = [wr EXCEPT ![w] = WrAfter(w, j, o, FALSE, 0)]

\* A dead writer's RPC that was already on the wire reaches the JN (Server.java:1300-1304 skips
\* closed connections only racily).  Nobody consumes the reply.  It needs the same JN process
\* (a JN crash resets the connection and drops it, see JNCrash) and a healed network.
DeliverLate(w, j) ==
    /\ ch[w][j].late # <<>>
    /\ Reach(jn[j])
    /\ JNDeliver(j, Head(ch[w][j].late))
    /\ ch' = [ch EXCEPT ![w][j].late = <<>>]
    /\ UNCHANGED wr

(***************************************************************************)
(* Writer control flow: QuorumJournalManager driven by the NameNode        *)
(***************************************************************************)

\* Submit task o to channel (w, j); on an idle executor it starts at once (HeadCt).
Submit(w, j, o) ==
    [ch[w][j] EXCEPT !.q   = Append(@, o),
                     !.hct = IF ch[w][j].q = <<>> THEN HeadCt(w, <<o>>) ELSE @]

\* ALS fan-out (ALS:208-314, 383-389): one task per logger for a new QuorumCall.
IssueCall(w, k, a, b, c, f, src) ==
    LET id == wr[w].call + 1 IN
    ch' = [ch EXCEPT ![w] = [j \in JN |-> Submit(w, j, Op(k, a, b, c, f, src, id))]]

NewCall(rec, ph) == [rec EXCEPT !.call = @ + 1, !.ok = {}, !.fail = {}, !.ph = ph]

\* waitFor returned and the writer moved on to phase ph without a new call: later replies to the
\* finished QuorumCall change nothing (its futures are no longer read), so the call is retired.
Resolved(rec, ph) == [rec EXCEPT !.call = @ + 1, !.ok = {}, !.fail = {}, !.ph = ph]

\* The NN dies on a failed quorum or a client-side assertion: required-journal failures call
\* terminate (JS:395-408, FSEL:1439-1447, FSEL:1671-1678); startup failures exit the NN.  Its
\* executor queues die with the process.
AbortWr(w) == [wr EXCEPT ![w].ph = "dead", ![w].ok = {}, ![w].fail = {}]
AbortCh(w) == [ch EXCEPT ![w] = [j \in JN |-> [ch[w][j] EXCEPT !.q = <<>>, !.hct = INVALID_TXID]]]
Abort(w)   == wr' = AbortWr(w) /\ ch' = AbortCh(w)

\* Rolling-upgrade rollback images: the rollback image sits just before a segment boundary
\* (rolling upgrade start rolls the edit log); FSI:772 discards from lastAppliedTxId + 1.
RollbackPoints == {f.s - 1 : f \in UNION {jn[j].segs : j \in JN}} \ {0}

\* An NN takes the writer role: QJM.recoverUnfinalizedSegments (QJM:474-499) ->
\* createNewUniqueEpoch (QJM:227-249) -> getJournalState fan-out (QJM:232-234, ALS:208-215).
\* Reached from FSN.startActiveServices (FSN:1421-1423) or FSImage.initEditLog (FSI:836-858).
Launch(w) ==
    /\ wr[w].ph = "idle"
    /\ IF w = 1 THEN TRUE ELSE wr[w - 1].ph # "idle"                    \* incarnations in id order
    /\ \E m \in (IF w = 1 THEN {"normal"} ELSE LaunchModes) :
         \E c \in (IF m = "rollback" THEN RollbackPoints ELSE {0}) :
            /\ wr' = [wr EXCEPT ![w] =
                        [NewCall(wr[w], "gjs") EXCEPT
                            !.mode = m, !.ckpt = c, !.acc = 0,
                            !.applied = IF m = "rollback" THEN c ELSE wr[w].applied]]  \* FSI:772
            /\ IssueCall(w, "gjs", 0, 0, 0, NoFile, NoJN)
    /\ UNCHANGED <<jn, targetFired>>

\* Standby tailing before failover: EditLogTailer.doTailEdits(inProgressOk) (ELT:331-344) reads
\* only durable txns (onlyDurableTxns = true).  With in-progress tailing the RPC path keeps the
\* majority-th largest count of the responders (QJM:545-582): the smaller value of some pair of
\* responders.  Without it, only finalized segments are read (FJM:241).
TailTargets ==
    LET Up == {j \in JN : Reach(jn[j])} IN
    IF InProgressTailing
    THEN UNION {{Min2(WrittenEnd(jn[a]), WrittenEnd(jn[b])) : b \in Up \ {a}} : a \in Up}
    ELSE IF Cardinality(Up) >= Majority
         THEN {f.e : f \in {g \in UNION {jn[j].segs : j \in Up} : ~g.ip}}
         ELSE {}

DoTailEdits(w) ==
    /\ wr[w].ph = "idle"
    /\ \E t \in TailTargets :
         /\ t > wr[w].applied
         /\ wr' = [wr EXCEPT ![w].applied = t]
    /\ UNCHANGED <<jn, ch, targetFired>>

\* QJM:233-245: myEpoch = max promised over the responders + 1, then newEpoch fan-out.
ResolveGetJournalState(w) ==
    /\ wr[w].ph = "gjs"
    /\ \/ /\ QuorumOk(w)
          /\ wr' = [wr EXCEPT ![w] = [NewCall(wr[w], "newEpoch") EXCEPT
                                          !.prop = wr[w].acc + 1, !.acc = 0]]   \* QJM:236-242
          /\ IssueCall(w, "newEpoch", wr[w].acc + 1, 0, 0, NoFile, NoJN)        \* QJM:243-245
       \/ /\ QuorumFailed(w)
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* QJM:244-247 setEpoch, QJM:485-497: recover the most recent segment among the responders.
ResolveNewEpoch(w) ==
    /\ wr[w].ph = "newEpoch"
    /\ \/ /\ QuorumOk(w)
          /\ IF wr[w].acc = 0                                           \* QJM:495 nothing to recover
             THEN /\ wr' = [wr EXCEPT ![w] = [Resolved(wr[w], "recovered") EXCEPT  \* QJM:247, 498
                                                 !.ep = wr[w].prop]]
                  /\ UNCHANGED ch
             ELSE /\ wr' = [wr EXCEPT ![w] = [NewCall(wr[w], "prepare") EXCEPT
                                                 !.ep = wr[w].prop, !.rseg = wr[w].acc,
                                                 !.prep = {}]]
                  /\ IssueCall(w, "prepare", wr[w].acc, 0, 0, NoFile, NoJN)       \* QJM:317-318
       \/ /\ QuorumFailed(w)
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* SegmentRecoveryComparator.compare (SRC:40-90): r1 strictly greater than r2.  Two finalized
\* responses with different lengths throw (SRC:73-78); ResolvePrepareRecovery checks that first.
SeenEpoch(r) == IF r.acc > r.lwe THEN r.acc ELSE r.lwe                  \* SRC:83-84
Greater(r1, r2) ==
    IF r1.hasSeg # r2.hasSeg THEN r1.hasSeg                             \* SRC:49-51
    ELSE IF ~r1.hasSeg THEN FALSE                                       \* SRC:53-57
    ELSE IF r1.seg.ip # r2.seg.ip THEN ~r1.seg.ip                       \* SRC:69-71
    ELSE IF ~r1.seg.ip THEN FALSE                                       \* SRC:73-80
    ELSE \/ SeenEpoch(r1) > SeenEpoch(r2)                               \* SRC:86-89
         \/ SeenEpoch(r1) = SeenEpoch(r2) /\ r1.seg.e > r2.seg.e

\* Collections.max (QJM:335-336) keeps the first maximal entry in HashMap order: any maximal one.
BestResponses(R) == {r \in R : \A r2 \in R : ~Greater(r2, r)}

\* QJM:319-396: choose the log to keep, check it, send acceptRecovery.
ResolvePrepareRecovery(w) ==
    /\ wr[w].ph = "prepare"
    /\ \/ /\ QuorumOk(w)
          /\ LET R   == wr[w].prep
                 Fin == {r \in R : r.hasSeg /\ ~r.seg.ip}
             IN IF \E r1, r2 \in Fin : r1.seg.e # r2.seg.e               \* SRC:75-78 AssertionError
                THEN Abort(w)
                ELSE IF \A r \in R : ~r.hasSeg                          \* QJM:347-371 no log anywhere
                THEN /\ wr' = [wr EXCEPT ![w] = Resolved(wr[w], "recovered")]  \* QJM:371, 498
                     /\ UNCHANGED ch
                ELSE \E best \in BestResponses(R) :
                       IF \E r \in R : r.lct # INVALID_TXID /\ r.lct > best.seg.e  \* QJM:379-390
                       THEN Abort(w)                                    \*   AssertionError
                       ELSE /\ wr' = [wr EXCEPT ![w] = [NewCall(wr[w], "accept") EXCEPT
                                                           !.log = best.seg, !.src = best.j]]
                            /\ IssueCall(w, "accept", 0, 0, 0, best.seg, best.j)   \* QJM:392-394
       \/ /\ QuorumFailed(w)
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* QJM:395-403: acceptRecovery quorum, then finalize the recovered segment.
ResolveAcceptRecovery(w) ==
    /\ wr[w].ph = "accept"
    /\ \/ /\ QuorumOk(w)
          /\ wr' = [wr EXCEPT ![w] = NewCall(wr[w], "recFinalize")]
          /\ IssueCall(w, "finalize", wr[w].log.s, wr[w].log.e, 0, NoFile, NoJN)  \* QJM:402-403
       \/ /\ QuorumFailed(w)
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* QJM:404-407, 498: recovery done; isActiveWriter.
ResolveRecoveryFinalize(w) ==
    /\ wr[w].ph = "recFinalize"
    /\ \/ /\ QuorumOk(w)
          /\ wr' = [wr EXCEPT ![w] = Resolved(wr[w], "recovered")]
          /\ UNCHANGED ch
       \/ /\ QuorumFailed(w)
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* Read quorums: a QJM read needs a majority of successful responders (QJM:612-616, 547-551).
ReadQuorums == {Q \in SUBSET {j \in JN : Reach(jn[j])} : Cardinality(Q) >= Majority}

\* FSN:1427 catchupDuringFailover (ELT:297-328): doTailEdits(false) (ELT:317, HDFS-16689) reads
\* finalized segments from a read quorum (QJM:609-656) until nothing is new; then FSN:1447-1450
\* nextTxId = lastAppliedTxId + 1.  ok = FALSE: the QJM read throws and JournalSet swallows it
\* (JS:276-282), so catch-up loads nothing (ELT:324).
CatchupDuringFailover(w, ok) ==
    /\ wr[w].ph = "recovered"
    /\ wr[w].mode = "normal"
    /\ IF ok
       THEN \E Q \in ReadQuorums :
              LET E == {f.e : f \in {g \in UNION {jn[j].segs : j \in Q} : ~g.ip}}
                  a == Max(E \cup {wr[w].applied})
              IN wr' = [wr EXCEPT ![w].applied = a, ![w].next = a + 1, ![w].ph = "caughtUp"]
       ELSE wr' = [wr EXCEPT ![w].next = wr[w].applied + 1, ![w].ph = "caughtUp"]
    /\ UNCHANGED <<jn, ch, targetFired>>

\* Rolling-upgrade rollback (FSI:772, 780-783): FSEL.discardSegments (FSEL:1737-1742) ->
\* QJM.discardSegments (QJM:772-773, ALS:383-389), after recovery in initEditLog (FSI:836-858).
RollingRollbackDiscard(w) ==
    /\ wr[w].ph = "recovered"
    /\ wr[w].mode = "rollback"
    /\ wr' = [wr EXCEPT ![w] = NewCall(wr[w], "discard")]
    /\ IssueCall(w, "discard", wr[w].ckpt + 1, 0, 0, NoFile, NoJN)
    /\ UNCHANGED <<jn, targetFired>>

\* QJM:775-787: waitFor(all, all, 0) returns at the first exception, which is rethrown (no catch
\* in FSEL:1737-1742, so NN startup fails).  On success FSI:775 setNextTxId(ckpt + 1).
ResolveDiscardSegments(w) ==
    /\ wr[w].ph = "discard"
    /\ \/ /\ wr[w].ok = JN
          /\ wr' = [wr EXCEPT ![w] = [Resolved(wr[w], "caughtUp") EXCEPT
                                          !.next = wr[w].ckpt + 1]]
          /\ UNCHANGED ch
       \/ /\ wr[w].fail # {}
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* Start a segment at txid next: FSEL.startLogSegment (FSEL:1413-1438) -> QJM.startLogSegment
\* (QJM:430-435, ALS:236-243).
StartSegment(w) ==
    /\ wr' = [wr EXCEPT ![w] = NewCall(wr[w], "start")]
    /\ IssueCall(w, "start", wr[w].next, 0, 0, NoFile, NoJN)

\* FSEL:329-347 openForWrite (FSN:1452 after failover; FSN:1315-1317 non-HA startup).  The safety
\* check (FSEL:333-345) reads at segmentTxId = next with inProgressOk (journalSet.selectInputStreams,
\* QJM:512-533).  ok = TRUE: a read quorum Q answers; a stream exists iff some responder holds a
\* txid >= next -> IllegalStateException, the NN does not become the writer.  ok = FALSE: the read
\* fails and is swallowed (JS:276-282), so the check passes vacuously.
OpenForWrite(w, ok) ==
    /\ wr[w].ph = "caughtUp"
    /\ wr[w].next <= MaxTxId
    /\ IF ok
       THEN \E Q \in ReadQuorums :
              IF \E j \in Q : WrittenEnd(jn[j]) >= wr[w].next           \* FSEL:338-345
              THEN Abort(w)
              ELSE StartSegment(w)                                      \* FSEL:347
       ELSE StartSegment(w)
    /\ UNCHANGED <<jn, targetFired>>

\* QJM:436-439: startLogSegment quorum, new QuorumOutputStream at txid.
ResolveStartLogSegment(w) ==
    /\ wr[w].ph = "start"
    /\ \/ /\ QuorumOk(w)
          /\ wr' = [wr EXCEPT ![w] = [Resolved(wr[w], "inSeg") EXCEPT !.seg = wr[w].next]]
          /\ UNCHANGED ch
       \/ /\ QuorumFailed(w)
          /\ Abort(w)                                                   \* FSEL:1439-1447 terminate
    /\ UNCHANGED <<jn, targetFired>>

\* FSEL.logSync -> QOS.flushAndSync (QOS:89-112): one batch of n txns from next.
SendEdits(w, n) ==
    /\ wr[w].ph = "inSeg"
    /\ wr[w].next + n - 1 <= MaxTxId
    /\ wr' = [wr EXCEPT ![w] = [NewCall(wr[w], "send") EXCEPT !.pend = wr[w].next + n - 1]]
    /\ IssueCall(w, "journal", wr[w].seg, wr[w].next, wr[w].next + n - 1, NoFile, NoJN)
    /\ UNCHANGED <<jn, targetFired>>

\* QOS:113-118: on a write quorum, setCommittedTxId(last txid of the batch) on every logger
\* (ALS:75-79; IPC:189-195 accepts it: it only grows).  A failed quorum terminates the NN.
ResolveSendEdits(w) ==
    /\ wr[w].ph = "send"
    /\ \/ /\ QuorumOk(w)
          /\ wr' = [wr EXCEPT ![w] = [Resolved(wr[w], "inSeg") EXCEPT
                                          !.ct = wr[w].pend, !.next = wr[w].pend + 1]]
          /\ UNCHANGED ch
       \/ /\ QuorumFailed(w)
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* FSEL.endCurrentLogSegment (FSEL:1466-1487) -> QJM.finalizeLogSegment (QJM:443-446).
FinalizeLogSegment(w) ==
    /\ wr[w].ph = "inSeg"
    /\ wr[w].next > wr[w].seg                                           \* at least one txn
    /\ wr' = [wr EXCEPT ![w] = NewCall(wr[w], "finalize")]
    /\ IssueCall(w, "finalize", wr[w].seg, wr[w].next - 1, 0, NoFile, NoJN)
    /\ UNCHANGED <<jn, targetFired>>

\* QJM:447-448; a failure terminates the NN (JS:395-408).
ResolveFinalizeLogSegment(w) ==
    /\ wr[w].ph = "finalize"
    /\ \/ /\ QuorumOk(w)
          /\ wr' = [wr EXCEPT ![w] = [Resolved(wr[w], "between") EXCEPT !.seg = INVALID_TXID]]
          /\ UNCHANGED ch
       \/ /\ QuorumFailed(w)
          /\ Abort(w)
    /\ UNCHANGED <<jn, targetFired>>

\* FSEL.rollEditLog (FSEL:1369-1374): the next segment starts at next.
StartLogSegment(w) ==
    /\ wr[w].ph = "between"
    /\ wr[w].next <= MaxTxId
    /\ StartSegment(w)
    /\ UNCHANGED <<jn, targetFired>>

\* QJM:466-471, ALS:107-111: purgeLogsOlderThan is fire-and-forget and not gated on outOfSync
\* (IPC:499-503).  Its storage effect (J:695) is not modeled.
PurgeLogsOlderThan(w) ==
    /\ wr[w].ph \in {"inSeg", "between"}
    /\ ch' = [ch EXCEPT ![w] = [j \in JN |-> Submit(w, j, Op("purge", 0, 0, 0, NoFile, NoJN, 0))]]
    /\ UNCHANGED <<jn, wr, targetFired>>

\* Clean shutdown of the writer (graceful failover or NN stop): FSEditLog.close (FSEL:399-423)
\* has already ended the segment (FSEL:406-410, modeled by FinalizeLogSegment), then closes the
\* journals: QJM.close (QJM:501-505) -> ALS.close (ALS:101-105) -> IPCLoggerChannel.close
\* (IPC:198-210).  executor.shutdown() lets queued tasks still run, so the queues are kept.
CloseWriter(w) ==
    /\ wr[w].ph = "between"
    /\ wr' = [wr EXCEPT ![w].ph = "dead"]
    /\ UNCHANGED <<jn, ch, targetFired>>

\* Fault: the NN process of writer w dies.  Queued tasks die with it; for each channel in keep,
\* the head task's RPC was already on the wire and may still reach the JN (DeliverLate).
LateCandidates(w) ==
    {j \in JN : jn[j].up /\ ch[w][j].q # <<>> /\ ~OosTask(w, j, Head(ch[w][j].q))}

WriterCrash(w, keep) ==
    /\ wr[w].ph \notin {"idle", "dead"}
    /\ keep \subseteq LateCandidates(w)
    /\ wr' = AbortWr(w)
    /\ ch' = [ch EXCEPT ![w] = [j \in JN |->
                IF j \in keep
                THEN [ch[w][j] EXCEPT !.q = <<>>, !.hct = INVALID_TXID,
                                      !.late = <<RpcOf(w, j, Head(ch[w][j].q))>>,
                                      !.ipc = IF IsRI(Head(ch[w][j].q).k) THEN @ + 1 ELSE @]
                ELSE [ch[w][j] EXCEPT !.q = <<>>, !.hct = INVALID_TXID]]]
    /\ UNCHANGED <<jn, targetFired>>

(***************************************************************************)
(* JournalNode process and host faults                                     *)
(***************************************************************************)

\* RPCs left on the wire towards JN j by dead writers lose their connection when j dies.
DropLateTo(j) == [w \in Writer |-> [ch[w] EXCEPT ![j].late = <<>>]]

\* Fault: the JN process dies.  The OS page cache, and so committed-txid, survives.
JNCrash(j) ==
    /\ jn[j].up
    /\ jn' = [jn EXCEPT ![j].up = FALSE]
    /\ ch' = DropLateTo(j)
    /\ UNCHANGED <<wr, targetFired>>

\* Fault: the JN host loses power.  committed-txid reverts to whatever the OS had written back:
\* any value in ctHist (BELF:68-75 writes positionally without force); that value is now the
\* on-disk content.  Epoch files (PLF via AtomicFileOutputStream force, AFOS:74), paxos files and
\* edit logs are treated as durable (brief section 3.2).
PowerLoss(j) ==
    /\ \E v \in jn[j].ctHist :
         jn' = [jn EXCEPT ![j].up = FALSE, ![j].ct = v, ![j].ctHist = {v}]
    /\ ch' = DropLateTo(j)
    /\ UNCHANGED <<wr, targetFired>>

\* A new Journal object (J:159-178): currentEpochIpcSerial = -1 (J:117), no open segment
\* (J:90-93), committed-txid re-read lazily (J:210-212, BELF:77-98), latest empty file moved
\* aside (J:174-177 -> J:221-246).
JNRestart(j) ==
    /\ ~jn[j].up
    /\ jn' = [jn EXCEPT ![j] = [jn[j] EXCEPT !.up = TRUE, !.sn = -1, !.cur = INVALID_TXID,
                                             !.next = INVALID_TXID,
                                             !.segs = ScanLatest(jn[j].segs).segs]]
    /\ UNCHANGED <<wr, ch, targetFired>>

\* Fault: the JN host is cut off from the network (writers and other JNs): calls time out,
\* acceptRecovery downloads from it fail.  The JN process and its state are untouched.
Partition(j) ==
    /\ ~jn[j].part
    /\ jn' = [jn EXCEPT ![j].part = TRUE]
    /\ UNCHANGED <<wr, ch, targetFired>>

Heal(j) ==
    /\ jn[j].part
    /\ jn' = [jn EXCEPT ![j].part = FALSE]
    /\ UNCHANGED <<wr, ch, targetFired>>

(***************************************************************************)
(* Next state                                                              *)
(***************************************************************************)
Next ==
    /\ ~targetFired
    /\ \/ \E w \in Writer :
            \/ Launch(w)
            \/ DoTailEdits(w)
            \/ ResolveGetJournalState(w)
            \/ ResolveNewEpoch(w)
            \/ ResolvePrepareRecovery(w)
            \/ ResolveAcceptRecovery(w)
            \/ ResolveRecoveryFinalize(w)
            \/ \E ok \in BOOLEAN : CatchupDuringFailover(w, ok)
            \/ RollingRollbackDiscard(w)
            \/ ResolveDiscardSegments(w)
            \/ \E ok \in BOOLEAN : OpenForWrite(w, ok)
            \/ ResolveStartLogSegment(w)
            \/ \E n \in 1..MaxBatch : SendEdits(w, n)
            \/ ResolveSendEdits(w)
            \/ FinalizeLogSegment(w)
            \/ ResolveFinalizeLogSegment(w)
            \/ StartLogSegment(w)
            \/ PurgeLogsOlderThan(w)
            \/ CloseWriter(w)
            \/ \E keep \in SUBSET JN : WriterCrash(w, keep)
       \/ \E w \in Writer, j \in JN :
            \/ ChannelCall(w, j)
            \/ ChannelHeartbeat(w, j)
            \/ ChannelSkip(w, j)
            \/ ChannelDown(w, j)
            \/ \E lr \in BOOLEAN : MsgLoss(w, j, lr)
            \/ DeliverLate(w, j)
       \/ \E j \in JN :
            \/ JNCrash(j)
            \/ JNRestart(j)
            \/ PowerLoss(j)
            \/ Partition(j)
            \/ Heal(j)

Spec == Init /\ [][Next]_vars

\* State constraint for base.cfg: faults are unbounded in Spec and purges are fire-and-forget, so
\* only bounded channel queues keep the base state space finite.  MC.tla bounds faults instead.
BaseQueueBound == \A w \in Writer, j \in JN : Len(ch[w][j].q) <= 2

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The oracle: Journal.java:504 never throws.
TargetSafe == ~targetFired

TxIdOrInvalid == {INVALID_TXID} \cup 0..MaxTxId
FileT == [s : 1..MaxTxId, e : {INVALID_TXID} \cup 1..MaxTxId, ip : BOOLEAN]
Phases == {"idle", "gjs", "newEpoch", "prepare", "accept", "recFinalize", "recovered",
           "discard", "caughtUp", "start", "inSeg", "send", "finalize", "between", "dead"}
OpKinds == {"gjs", "newEpoch", "prepare", "accept", "finalize", "start", "journal", "purge",
            "discard", "heartbeat"}

TypeOK ==
    /\ targetFired \in BOOLEAN
    /\ \A j \in JN :
         /\ jn[j].prom \in 0..NumWriters
         /\ jn[j].lwe \in 0..NumWriters
         /\ jn[j].sn \in Int /\ jn[j].sn >= -1
         /\ jn[j].ct \in TxIdOrInvalid
         /\ jn[j].ctHist \subseteq TxIdOrInvalid
         /\ jn[j].segs \subseteq FileT
         /\ jn[j].cur \in {INVALID_TXID} \cup 1..MaxTxId
         /\ jn[j].next \in {INVALID_TXID} \cup 1..(MaxTxId + 1)
         /\ \A p \in jn[j].paxos : p.ep \in 1..NumWriters /\ p.seg \in FileT
         /\ jn[j].up \in BOOLEAN /\ jn[j].part \in BOOLEAN
    /\ \A w \in Writer :
         /\ wr[w].ph \in Phases
         /\ wr[w].mode \in {"normal", "rollback"}
         /\ wr[w].ep \in 0..NumWriters
         /\ wr[w].ct \in {INVALID_TXID} \cup 1..MaxTxId
         /\ wr[w].ok \subseteq JN /\ wr[w].fail \subseteq JN
         /\ wr[w].ok \cap wr[w].fail = {}
         /\ wr[w].next \in 1..(MaxTxId + 1)
         /\ wr[w].applied \in 0..MaxTxId
         /\ \A j \in JN :
              /\ ch[w][j].ipc \in Nat
              /\ ch[w][j].oos \in BOOLEAN /\ ch[w][j].hb \in BOOLEAN
              /\ \A i \in 1..Len(ch[w][j].q) : ch[w][j].q[i].k \in OpKinds
              /\ ch[w][j].hct \in {INVALID_TXID} \cup 1..MaxTxId
              /\ Len(ch[w][j].late) <= 1

\* Structural: at most one edit log file per first txid on a JN (FJM.getLogFile throws
\* otherwise, FJM:517-519).
UniqueSegStarts == \A j \in JN : \A f, g \in jn[j].segs : f.s = g.s => f = g

\* Sanity, "a message carries only values its sender held": (1) an RPC still on the wire after
\* its writer died carries that writer's epoch, a serial it issued and a committed txid it held;
\* (2) a JN's committed txid (in memory or on disk) is one some writer held, or a rewind point;
\* (3) the committed txid a started task's RequestInfo carries is one its writer held, and an
\* idle channel holds no snapshot.
ReqFromSenderState ==
    /\ \A w \in Writer, j \in JN :
         \A i \in 1..Len(ch[w][j].late) :
            LET r == ch[w][j].late[i] IN
            IsRI(r.k) => /\ r.ep = wr[w].ep
                         /\ r.sn < ch[w][j].ipc
                         /\ r.ct = INVALID_TXID \/ (wr[w].ct # INVALID_TXID /\ r.ct <= wr[w].ct)
    /\ \A w \in Writer, j \in JN :
         /\ ch[w][j].q = <<>> => ch[w][j].hct = INVALID_TXID
         /\ ch[w][j].hct = INVALID_TXID \/ (wr[w].ct # INVALID_TXID /\ ch[w][j].hct <= wr[w].ct)
    /\ \A j \in JN : \A v \in {jn[j].ct} \cup jn[j].ctHist :
         \/ v = INVALID_TXID
         \/ \E w \in Writer : wr[w].ct # INVALID_TXID /\ v <= wr[w].ct
         \/ \E w \in Writer : wr[w].mode = "rollback" /\ v = wr[w].ckpt

\* Reachability probe for the sanity check: some RPC that a channel task (own RPC or
\* heartbeat) or a late delivery would hand to an up JN reaches J:503 with a committed txid.
TargetEnabled ==
    \E w \in Writer, j \in JN :
       /\ Reach(jn[j])
       /\ \/ /\ ch[w][j].q # <<>>
             /\ LET o == Head(ch[w][j].q) IN
                IF OosTask(w, j, o) THEN TargetPath(jn[j], HbRpc(w, j))
                ELSE TargetPath(jn[j], RpcOf(w, j, o))
          \/ /\ ch[w][j].late # <<>>
             /\ TargetPath(jn[j], Head(ch[w][j].late))
TargetReached == ~TargetEnabled
=============================================================================
