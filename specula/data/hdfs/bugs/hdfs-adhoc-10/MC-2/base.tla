------------------------------- MODULE base -------------------------------
(***************************************************************************)
(* hdfs-adhoc-10: can Journal.checkWriteRequest(RequestInfo) take its      *)
(* failing branch?                                                         *)
(*                                                                         *)
(*   Journal.java:517  if (reqInfo.getEpoch() != lastWriterEpoch.get())    *)
(*   Journal.java:518    throw new IOException("IPC's epoch ... is not the *)
(*                         current writer epoch ...")                      *)
(*                                                                         *)
(* Category A (distributed / message passing). One or two NameNode-side    *)
(* writers (QuorumJournalManager + AsyncLoggerSet + one IPCLoggerChannel   *)
(* per JournalNode) talk to the JournalNodes (JournalNodeRpcServer ->      *)
(* Journal) over Hadoop IPC.                                               *)
(*                                                                         *)
(* Path abbreviations used in the annotations (pinned tree 734dd8a67cd):   *)
(*   J    = hadoop-hdfs/.../hdfs/qjournal/server/Journal.java              *)
(*   JRPC = hadoop-hdfs/.../hdfs/qjournal/server/JournalNodeRpcServer.java *)
(*   JNd  = hadoop-hdfs/.../hdfs/qjournal/server/JournalNode.java          *)
(*   IPCL = hadoop-hdfs/.../hdfs/qjournal/client/IPCLoggerChannel.java     *)
(*   ALS  = hadoop-hdfs/.../hdfs/qjournal/client/AsyncLoggerSet.java       *)
(*   QJM  = hadoop-hdfs/.../hdfs/qjournal/client/QuorumJournalManager.java *)
(*   QOS  = hadoop-hdfs/.../hdfs/qjournal/client/QuorumOutputStream.java   *)
(*   QC   = hadoop-hdfs/.../hdfs/qjournal/client/QuorumCall.java           *)
(*   SRC  = hadoop-hdfs/.../hdfs/qjournal/client/                          *)
(*            SegmentRecoveryComparator.java                               *)
(*   PLF  = hadoop-hdfs/.../hdfs/util/PersistentLongFile.java              *)
(*   AFOS = hadoop-hdfs/.../hdfs/util/AtomicFileOutputStream.java          *)
(*   FJM  = hadoop-hdfs/.../hdfs/server/namenode/FileJournalManager.java   *)
(*   RI   = hadoop-hdfs/.../hdfs/qjournal/protocol/RequestInfo.java        *)
(*   IPCC = hadoop-common/.../ipc/Client.java                              *)
(*   IPCS = hadoop-common/.../ipc/Server.java                              *)
(*   QTU  = hadoop-hdfs/src/test/.../hdfs/qjournal/QJMTestUtil.java        *)
(*                                                                         *)
(* Granularity. Every Journal write-path method is synchronized (J:339,    *)
(* 393, 484, 514, 568, 629, 827, 871), so one JournalNode-side RPC is one  *)
(* atomic step on the guard's operands. A channel call is split into       *)
(* ChannelDispatch (the task starts on the channel's single-thread         *)
(* executor and stamps RequestInfo, IPCL:287-291) and a JN step that runs  *)
(* the handler and completes the client future. Loss, late execution and  *)
(* JN crash act on the request between those two steps.                   *)
(*                                                                         *)
(* Scenario map (modeling-brief.md section 2):                             *)
(*   S1 lost request ............ LoseRequest                              *)
(*   S2 JN crash/restart ........ Crash, Restart                           *)
(*   S3 failover, empty segment . WriterCrash, writer 2, files, recovery   *)
(*   S4 late execution .......... TimeoutLate, JNExecLate, DropLate        *)
(*   S5 persistence faults ...... StartPersistFail, PowerLoss              *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets, TLC

CONSTANTS
    JN,          \* JournalNodes (MiniJournalCluster: 3)
    NumWriters,  \* 1 = the workload's single writer; 2 = failover (Scenario 3)
    SegLen,      \* txns per segment, one flush each (workload: <<3, 1>>)
    W2Segs,      \* number of segments writer 2 writes after recovery
    LostOps      \* ops whose request LoseRequest may drop (Scenario 1/3)

ASSUME Cardinality(JN) >= 1
ASSUME NumWriters \in {1, 2}
ASSUME Len(SegLen) >= 1 /\ \A k \in 1..Len(SegLen) : SegLen[k] >= 1
ASSUME W2Segs \in 0..Len(SegLen)

\* HdfsServerConstants.INVALID_TXID
INVALID_TXID == -12345

\* "no segment" marker for newEpoch / recovery bookkeeping (txids start at 1)
NoSeg == 0

Writers == 1..NumWriters

\* ALS.getMajoritySize L153-155
Majority == Cardinality(JN) \div 2 + 1

Max(S) == CHOOSE x \in S : \A y \in S : y <= x

SumSeq(s) == LET F[i \in 0..Len(s)] == IF i = 0 THEN 0 ELSE F[i - 1] + s[i]
             IN F[Len(s)]

\* The workload's segments: writeSegment(1, 3) then writeSegment(4, 1), one
\* flush each (TestQuorumJournalManager L159-168, QTU:80-112). Configs
\* substitute it for SegLen (TLC config files cannot hold tuples).
WorkloadSegLen == <<3, 1>>

\* Segments a writer writes once it is active, and their sizes.
NSegs(w) == IF w = 1 THEN Len(SegLen) ELSE W2Segs
SegLenOf(k) == SegLen[k]

\* Txid space: writer 1 writes 1..Total; writer 2 starts at most at Total + 1.
Total == SumSeq(SegLen)
MaxTxId == Total + SumSeq(SubSeq(SegLen, 1, W2Segs)) + 1
TxIds == 1..MaxTxId

\* Ops on the channel's single-thread executor (IPCL:86-89). Names:
\*   gjs = getJournalState, ne = newEpoch, start = startLogSegment,
\*   journal = sendEdits/journal, finalize = finalizeLogSegment,
\*   prepare = prepareRecovery, accept = acceptRecovery.
Ops == {"gjs", "ne", "start", "journal", "finalize", "prepare", "accept"}
\* Ops whose RPC carries a RequestInfo stamped by createReqInfo (IPCL:287-291)
ReqInfoOps == {"start", "journal", "finalize", "prepare", "accept"}

\* Result codes of a JN handler: "ok", the target "L518", or the line of
\* the other throw that fired (see the handlers below).
TargetCode == "L518"

\* ---------------------------------------------------------------------------
\* Records
\* ---------------------------------------------------------------------------

\* A task queued on a channel (generic argument slots a1..a3):
\*   ne: a1 = epoch; start: a1 = txid; journal: a1 = segmentTxId,
\*   a2 = firstTxnId, a3 = numTxns; finalize: a1 = startTxId, a2 = endTxId;
\*   prepare: a1 = segmentTxId; accept: a1 = segmentTxId, a2 = endTxId.
MkOp(op, a1, a2, a3) == [op |-> op, cid |-> 0, a1 |-> a1, a2 |-> a2, a3 |-> a3]

\* "no request in flight" on a channel
NoReq == [w |-> 0, op |-> "none", cid |-> 0, a1 |-> 0, a2 |-> 0, a3 |-> 0,
          epoch |-> 0, serial |-> -1, committed |-> INVALID_TXID, st |-> "none"]

\* One logger's answer in a QuorumCall. Fields are used per op:
\*   gjs: promised; ne: lastSeg; prepare: hasSeg, segLast, segInProg, lwe,
\*   committed.
NoResp == [st |-> "none", promised |-> 0, lastSeg |-> NoSeg, hasSeg |-> FALSE,
           segLast |-> 0, segInProg |-> FALSE, lwe |-> 0,
           committed |-> INVALID_TXID]
Pending == [NoResp EXCEPT !.st = "pending"]
ErrResp == [NoResp EXCEPT !.st = "err"]

\* Edit log files on a JN, keyed by start txid. FJM.getLogFile (L499-521)
\* matches at most one file per start txid; a file moved aside (".empty",
\* FJM L626-629) no longer matches (FJM L73-74, L334) and is "none" here.
\*   inprog: edits_inprogress_<start>, last = last txid in the file
\*           (INVALID_TXID when it holds only the header)
\*   final:  edits_<start>-<last>
NoFile == [st |-> "none", last |-> 0]

\* JournalNode state for one journal.
\*   promised  lastPromisedEpoch (PersistentLongFile, J:106)
\*   lwMem     lastWriterEpoch.get() cache (J:125, PLF L45-59)
\*   lwDisk    last-writer-epoch file content; a missing file reads as 0
\*             (PLF L90-107, default 0 at J:208-209)
\*   lwPrev    on-disk value before the last rename (power loss, S5c)
\*   serial    currentEpochIpcSerial (J:117, volatile)
\*   curSeg    curSegmentTxId; INVALID_TXID <=> curSegment == null (J:90-91)
\*   nextTx    nextTxId (J:93, volatile)
\*   committed committedTxnId (BestEffortLongFile, J:133)
\*   files     edit log files (see NoFile)
JNInit == [promised |-> 0, lwMem |-> 0, lwDisk |-> 0, lwPrev |-> 0,
           serial |-> -1, curSeg |-> INVALID_TXID, nextTx |-> INVALID_TXID,
           committed |-> INVALID_TXID, files |-> [t \in TxIds |-> NoFile]]

\* ---------------------------------------------------------------------------
\* Variables
\* ---------------------------------------------------------------------------

VARIABLES
    \* JournalNode side
    jn,           \* [JN -> JN state record]
    up,           \* [JN -> BOOLEAN] JN process running              (S2, S5c)
    srvPend,      \* [JN -> set of requests] calls the client already failed
                  \* that a handler may still run (IPCS L1300-1304)   (S4)
    \* Channel side (IPCLoggerChannel per writer and JN)
    chQ,          \* [Writers -> [JN -> Seq(task)]] queued, not yet started
    inflight,     \* [Writers -> [JN -> request]] the running task's RPC
    nextSerial,   \* [Writers -> [JN -> Nat]] ipcSerial (IPCL:96)
    outOfSync,    \* [Writers -> [JN -> BOOLEAN]] (IPCL:146)
    \* Writer side (QuorumJournalManager + AsyncLoggerSet)
    wPhase,       \* "idle" | "fanout" | "wait" | "done" | "halted"
    wOp,          \* op to fan out / being awaited
    wCid,         \* id of the current QuorumCall
    wRes,         \* [Writers -> [JN -> response]] current QuorumCall results
    wEpoch,       \* epoch stamped by createReqInfo (IPCL:97, set at L184-186)
    wCommitted,   \* committedTxId stamped by createReqInfo (IPCL:98, L189-195)
    wSeg,         \* index of the segment being written; 0 while recovering
    wRec,         \* [seg, end] of the segment being recovered (S3)
    \* Target
    targetFired   \* Journal.java:518 threw

jnVars == <<jn, up, srvPend>>
chVars == <<chQ, inflight, nextSerial, outOfSync>>
wVars  == <<wPhase, wOp, wCid, wRes, wEpoch, wCommitted, wSeg, wRec>>
vars   == <<jnVars, chVars, wVars, targetFired>>

\* ===========================================================================
\* JournalNode handlers. Pure functions from the JN state and a request to
\* [st |-> new JN state, res |-> result code, resp |-> response]. Java fields
\* are mutated in place and an exception keeps every earlier mutation, so
\* each throw site returns the state reached at that point.
\* ===========================================================================

\* J:484-512 checkRequest
CheckRequest(s, req) ==
    IF req.epoch < s.promised                                    \* J:486
    THEN [st |-> s, res |-> "L486"]                              \* J:487-489 IOException
    ELSE
      LET s1 == IF req.epoch > s.promised                        \* J:490
                THEN [s EXCEPT !.promised = req.epoch,           \* J:493 -> J:371 lastPromisedEpoch.set
                               !.serial = -1]                    \* J:375 currentEpochIpcSerial = -1
                ELSE s
      IN IF ~(req.serial > s1.serial)                            \* J:497 checkSync(serial > current)
         THEN [st |-> s1, res |-> "L497"]                        \* J:497-500 JournalOutOfSyncException
         ELSE
           LET s2 == [s1 EXCEPT !.serial = req.serial]           \* J:501
           IN IF req.committed # INVALID_TXID                    \* J:503 hasCommittedTxId (RI L69-71)
              THEN IF req.committed >= s2.committed              \* J:504-505
                   THEN [st |-> [s2 EXCEPT !.committed = req.committed],  \* J:510
                         res |-> "ok"]
                   ELSE [st |-> s2, res |-> "L504"]              \* J:504-508 IllegalArgumentException
              ELSE [st |-> s2, res |-> "ok"]

\* J:221-246 scanStorageForLatestEdits: from the highest start txid down,
\* move aside every file with no transactions (J:233-238) and stop at the
\* first file that has some (J:239-240). FJM.getLogFiles sorts by start txid
\* (FJM L468-483).
ScanLatest(fs) ==
    LET nonEmpty == {t \in TxIds : fs[t].st # "none" /\ fs[t].last # INVALID_TXID}
        latest   == IF nonEmpty = {} THEN NoSeg ELSE Max(nonEmpty)
    IN [files  |-> [t \in TxIds |-> IF fs[t].st # "none" /\ t > latest
                                    THEN NoFile               \* J:238 moveAsideEmptyFile
                                    ELSE fs[t]],
        latest |-> latest]                                     \* J:240 / J:245 (null)

\* J:799-822 getSegmentInfo(t): an empty file is moved aside and reported as
\* absent (J:808-812). Finalized files carry their last txid in the name.
SegInfo(fs, t) ==
    LET f == fs[t] IN
    IF f.st = "none"                                           \* J:801-803
    THEN [files |-> fs, has |-> FALSE, last |-> 0, inprog |-> FALSE]
    ELSE IF f.last = INVALID_TXID                              \* J:805-808 scanLog; INVALID_TXID
    THEN [files |-> [fs EXCEPT ![t] = NoFile],                 \* J:811 moveAsideEmptyFile
          has |-> FALSE, last |-> 0, inprog |-> FALSE]         \* J:812 return null
    ELSE [files |-> fs, has |-> TRUE, last |-> f.last,         \* J:814-818
          inprog |-> (f.st = "inprog")]

\* JRPC:178-188 getJournalState -> J:284-287 getLastPromisedEpoch (read only)
HGetJournalState(s) ==
    [st |-> s, res |-> "ok", resp |-> [NoResp EXCEPT !.promised = s.promised]]

\* J:339-365 newEpoch (no RequestInfo; epoch is the argument)
HNewEpoch(s, e) ==
    \* J:342 checkFormatted, J:343 checkConsistentNamespace: always pass
    IF e <= s.promised                                         \* J:347
    THEN [st |-> s, res |-> "L347", resp |-> NoResp]           \* J:348-349 IOException
    ELSE LET s1 == [s EXCEPT !.promised = e,                   \* J:352 -> J:371
                             !.serial = -1,                    \* J:375
                             !.curSeg = INVALID_TXID]          \* J:353 abortCurSegment (J:378-387)
             sc == ScanLatest(s1.files)                        \* J:358
         IN [st |-> [s1 EXCEPT !.files = sc.files], res |-> "ok",
             resp |-> [NoResp EXCEPT !.lastSeg = sc.latest]]   \* J:360-362 setLastSegmentTxId

\* J:568-604 startLogSegment up to the lastWriterEpoch read at J:606.
HStartPre(s, req) ==
    \* J:570-571 assert fjm != null; checkFormatted: pass
    LET cr == CheckRequest(s, req)                             \* J:572
    IN IF cr.res # "ok" THEN [st |-> cr.st, res |-> cr.res]
       ELSE
         LET s1 == [cr.st EXCEPT !.curSeg = INVALID_TXID]      \* J:574-583 abortCurSegment if open
             f  == s1.files[req.a1]                            \* J:588 fjm.getLogFile(txid)
         IN IF f.st = "final"                                  \* J:589-590 !existing.isInProgress()
            THEN [st |-> s1, res |-> "L591"]                   \* J:591-592 IllegalStateException
            ELSE IF f.st = "inprog" /\ f.last # req.a1         \* J:598-599 scanLog; lastTxId != firstTxId
            THEN [st |-> s1, res |-> "L600"]                   \* J:600-602 IllegalStateException
            ELSE [st |-> s1, res |-> "ok"]

\* J:568-624 startLogSegment
HStart(s, req) ==
    LET pre == HStartPre(s, req)
    IN IF pre.res # "ok" THEN [st |-> pre.st, res |-> pre.res, resp |-> NoResp]
       ELSE
         LET s1 == pre.st
             s2 == IF s1.lwMem # req.epoch                     \* J:606-607
                   THEN [s1 EXCEPT !.lwMem  = req.epoch,       \* J:611 set(): PLF L61-67 cache after write
                                   !.lwPrev = s1.lwDisk,       \*   value before the rename (AFOS L81)
                                   !.lwDisk = req.epoch]       \*   AFOS L70-98 write, fsync, rename
                   ELSE s1
         IN [st |-> [s2 EXCEPT
                       \* J:618 purgePaxosDecision: paxos files not modeled
                       !.files[req.a1] = [st |-> "inprog", last |-> INVALID_TXID],  \* J:620 fjm.startLogSegment: header only (FJM L121-136)
                       !.curSeg = req.a1,                      \* J:621
                       !.nextTx = req.a1],                     \* J:623
             res |-> "ok", resp |-> NoResp]

\* J:393-473 journal, with checkWriteRequest J:514-522. This is where the
\* target check is evaluated (TargetCheck and the late path call it).
HJournal(s, req) ==
    \* J:396 checkFormatted: pass
    LET cr == CheckRequest(s, req)                             \* J:397 -> J:515
    IN IF cr.res # "ok" THEN [st |-> cr.st, res |-> cr.res, resp |-> NoResp]
       ELSE IF req.epoch # cr.st.lwMem                         \* J:517 reqInfo.getEpoch() != lastWriterEpoch.get()
       THEN [st |-> cr.st, res |-> TargetCode, resp |-> NoResp] \* J:518-520 throw IOException  <== TARGET
       ELSE
         LET s1 == cr.st IN
         \* J:399-403 numTxns == 0: never sent (QOS L90-95)
         IF s1.curSeg = INVALID_TXID                           \* J:405 checkSync(curSegment != null)
         THEN [st |-> s1, res |-> "L405", resp |-> NoResp]
         ELSE IF s1.curSeg # req.a1                            \* J:408 curSegmentTxId != segmentTxId
         THEN [st |-> [s1 EXCEPT !.curSeg = INVALID_TXID],     \* J:419 abortCurSegment
               res |-> "L408", resp |-> NoResp]                \* J:420 JournalOutOfSyncException
         ELSE IF s1.nextTx # req.a2                            \* J:423 checkSync(nextTxId == firstTxnId)
         THEN [st |-> s1, res |-> "L423", resp |-> NoResp]
         ELSE LET last == req.a2 + req.a3 - 1                  \* J:427
              IN [st |-> [s1 EXCEPT
                            !.files[req.a1] = [st |-> "inprog", last |-> last],  \* J:442-446 writeRaw, flush
                            !.nextTx = last + 1],              \* J:470-471
                  res |-> "ok", resp |-> NoResp]

\* J:629-685 finalizeLogSegment (a1 = startTxId, a2 = endTxId)
HFinalize(s, req) ==
    LET cr == CheckRequest(s, req)                             \* J:631-632
    IN IF cr.res # "ok" THEN [st |-> cr.st, res |-> cr.res, resp |-> NoResp]
       ELSE
         LET s0  == cr.st
             cur == req.a1 = s0.curSeg                         \* J:637
             s1  == IF cur THEN [s0 EXCEPT !.curSeg = INVALID_TXID]  \* J:638-643 curSegment.close()
                    ELSE s0
         IN IF cur /\ s1.nextTx # req.a2 + 1                   \* J:645
            THEN [st |-> s1, res |-> "L645", resp |-> NoResp]  \* J:645-648 JournalOutOfSyncException
            ELSE
              LET f == s1.files[req.a1] IN                     \* J:654
              IF f.st = "none"                                 \* J:655
              THEN [st |-> s1, res |-> "L656", resp |-> NoResp] \* J:656-657
              ELSE IF f.st = "inprog"                          \* J:660
              THEN IF ~cur /\ f.last # req.a2                  \* J:661-670 needsValidation: scanLog, checkSync
                   THEN [st |-> s1, res |-> "L666", resp |-> NoResp]
                   ELSE [st |-> [s1 EXCEPT !.files[req.a1] =   \* J:672 fjm.finalizeLogSegment (FJM L139-161)
                                   [st |-> "final", last |-> req.a2]],
                         res |-> "ok", resp |-> NoResp]
              ELSE IF req.a2 # f.last                          \* J:674 checkArgument(endTxId == last)
              THEN [st |-> s1, res |-> "L674", resp |-> NoResp]
              ELSE [st |-> s1, res |-> "ok", resp |-> NoResp]  \* J:684 purgePaxosDecision: not modeled

\* J:827-866 prepareRecovery (a1 = segmentTxId)
HPrepare(s, req) ==
    LET cr == CheckRequest(s, req)                             \* J:829-830
    IN IF cr.res # "ok" THEN [st |-> cr.st, res |-> cr.res, resp |-> NoResp]
       ELSE
         LET s1 == [cr.st EXCEPT !.curSeg = INVALID_TXID]      \* J:832 abortCurSegment
             \* J:837-838 no persisted paxos data: only the newest writer runs
             \* recovery and its prepare precedes its accept
             si == SegInfo(s1.files, req.a1)                   \* J:840
             s2 == [s1 EXCEPT !.files = si.files]
         IN [st |-> s2, res |-> "ok",
             resp |-> [NoResp EXCEPT !.hasSeg    = si.has,     \* J:851-854
                                     !.segLast   = si.last,
                                     !.segInProg = si.inprog,
                                     !.lwe       = s2.lwMem,   \* J:857 setLastWriterEpoch
                                     !.committed = s2.committed]]  \* J:858-860

\* J:871-986 acceptRecovery (a1 = segmentTxId, a2 = endTxId of the decision)
HAccept(s, req) ==
    LET cr == CheckRequest(s, req)                             \* J:874-875
    IN IF cr.res # "ok" THEN [st |-> cr.st, res |-> cr.res, resp |-> NoResp]
       ELSE
         LET s1 == [cr.st EXCEPT !.curSeg = INVALID_TXID]      \* J:877 abortCurSegment
             \* J:883-886 well-formed segment: the writer sends a recovered one
             si == SegInfo(s1.files, req.a1)                   \* J:906
             s2 == [s1 EXCEPT !.files = si.files]
             c  == s2.committed
         IN IF si.has /\ si.last = req.a2                      \* J:907-908 up to date
            THEN [st |-> s2, res |-> "ok", resp |-> NoResp]    \* J:950-954 skip download; J:976 persist paxos
            ELSE IF si.has /\ req.a1 <= c /\ c <= si.last /\ ~(c <= req.a2)  \* J:924-925
            THEN [st |-> s2, res |-> "L926", resp |-> NoResp]  \* J:926-933 AssertionError
            ELSE IF si.has /\ ~si.inprog                       \* J:938-940 alwaysAssert(isInProgress)
            THEN [st |-> s2, res |-> "L938", resp |-> NoResp]
            ELSE [st |-> [s2 EXCEPT !.files[req.a1] =          \* J:948 syncLog; J:979-982 replaceFile
                            [st |-> "inprog", last |-> req.a2]],
                  res |-> "ok", resp |-> NoResp]

\* Dispatch on the op of a request (used by the late-execution path).
Handler(s, req) ==
    CASE req.op = "gjs"      -> HGetJournalState(s)
      [] req.op = "ne"       -> HNewEpoch(s, req.a1)
      [] req.op = "start"    -> HStart(s, req)
      [] req.op = "journal"  -> HJournal(s, req)
      [] req.op = "finalize" -> HFinalize(s, req)
      [] req.op = "prepare"  -> HPrepare(s, req)
      [] req.op = "accept"   -> HAccept(s, req)

\* ===========================================================================
\* Client-side completion helpers
\* ===========================================================================

\* QC:78-88 future callbacks -> addResult / addException (QC:259-268): a
\* logger's answer counts only for the QuorumCall that issued it, and only
\* while the writer is still waiting on that call.
RecordResult(w, j, cid, r) ==
    wRes' = IF wPhase[w] = "wait" /\ cid = wCid[w]
            THEN [wRes EXCEPT ![w][j] = r]
            ELSE wRes

\* The channel task finishes after its RPC returned with JN result `out`.
Complete(w, j, req, out) ==
    /\ inflight' = [inflight EXCEPT ![w][j] = NoReq]
    /\ outOfSync' =
         CASE req.op = "journal" /\ out.res # "ok"
                -> [outOfSync EXCEPT ![w][j] = TRUE]           \* IPCL:363-370
           [] req.op = "start" /\ out.res = "ok"
                -> [outOfSync EXCEPT ![w][j] = FALSE]          \* IPCL:477-484
           [] OTHER -> outOfSync                                \* failed start: unchanged (IPCL:474-487)
    /\ RecordResult(w, j, req.cid,
                    IF out.res = "ok" THEN [out.resp EXCEPT !.st = "ok"]
                    ELSE ErrResp)

OkSet(w) == {j \in JN : wRes[w][j].st = "ok"}
GotQuorum(w) == Cardinality(OkSet(w)) >= Majority             \* ALS:128-132 minSuccesses = majority

\* A halted writer's queued tasks die with the NameNode process.
DropQueues(w) == chQ' = [chQ EXCEPT ![w] = [j \in JN |-> <<>>]]

\* ===========================================================================
\* Writer actions (QuorumJournalManager / AsyncLoggerSet / QuorumOutputStream)
\* ===========================================================================

\* QJM:474-478 recoverUnfinalizedSegments -> createNewUniqueEpoch QJM:227-234.
\* A later writer exists only after the previous one stopped (failover).
WriterBegin(w) ==
    /\ wPhase[w] = "idle"
    /\ \A v \in Writers : v < w => wPhase[v] \in {"halted", "done"}
    /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
    /\ wOp' = [wOp EXCEPT ![w] = MkOp("gjs", 0, 0, 0)]        \* QJM:233 loggers.getJournalState()
    /\ UNCHANGED <<jnVars, chVars, wCid, wRes, wEpoch, wCommitted, wSeg, wRec, targetFired>>

\* ALS fan-out wrappers (ALS:208-215, 225-263, 291-312): one task per logger,
\* each submitted to that logger's single-thread executor.
WriterFanOut(w) ==
    /\ wPhase[w] = "fanout"
    /\ wPhase' = [wPhase EXCEPT ![w] = "wait"]
    /\ wCid' = [wCid EXCEPT ![w] = @ + 1]
    /\ chQ' = [chQ EXCEPT ![w] = [j \in JN |->
                 Append(chQ[w][j], [wOp[w] EXCEPT !.cid = wCid[w] + 1])]]
    /\ wRes' = [wRes EXCEPT ![w] = [j \in JN |-> Pending]]
    /\ UNCHANGED <<jnVars, inflight, nextSerial, outOfSync, wOp, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* QJM:232-242 createNewUniqueEpoch: majority of getJournalState answers,
\* epoch = max promised + 1, then newEpoch(epoch) (QJM:243-245).
CreateNewUniqueEpoch_GotJournalState(w) ==
    /\ wPhase[w] = "wait" /\ wOp[w].op = "gjs"
    /\ GotQuorum(w)
    /\ LET maxP == Max({wRes[w][j].promised : j \in OkSet(w)})   \* QJM:236-239
       IN wOp' = [wOp EXCEPT ![w] = MkOp("ne", maxP + 1, 0, 0)] \* QJM:242-244
    /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
    /\ UNCHANGED <<jnVars, chVars, wCid, wRes, wEpoch, wCommitted, wSeg, wRec, targetFired>>

\* QJM:243-248 newEpoch quorum, setEpoch; then recoverUnfinalizedSegments
\* QJM:485-498 picks the most recent segment any responder reported.
CreateNewUniqueEpoch_GotNewEpoch(w) ==
    /\ wPhase[w] = "wait" /\ wOp[w].op = "ne"
    /\ GotQuorum(w)
    /\ wEpoch' = [wEpoch EXCEPT ![w] = wOp[w].a1]              \* QJM:247 -> ALS:61-68 -> IPCL:184-186 (all channels)
    /\ LET segs == {wRes[w][j].lastSeg : j \in OkSet(w)} \ {NoSeg}   \* QJM:485-491
       IN IF segs = {}
          THEN \* QJM:493-498 nothing to recover: active; first segment at txid 1
               /\ wSeg' = [wSeg EXCEPT ![w] = 1]
               /\ wOp' = [wOp EXCEPT ![w] = MkOp("start", 1, 0, 0)]   \* QTU:83 qjm.startLogSegment
               /\ UNCHANGED wRec
          ELSE \* QJM:496 recoverUnclosedSegment(mostRecentSegmentTxId)
               /\ wRec' = [wRec EXCEPT ![w] = [seg |-> Max(segs), end |-> 0]]
               /\ wOp' = [wOp EXCEPT ![w] = MkOp("prepare", Max(segs), 0, 0)]  \* QJM:317-321
               /\ UNCHANGED wSeg
    /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
    /\ UNCHANGED <<jnVars, chVars, wCid, wRes, wCommitted, targetFired>>

\* SRC:82-89 both in-progress: larger max(acceptedInEpoch, lastWriterEpoch)
\* wins, then larger endTxId (no accepted recovery exists, see HPrepare).
BestInProgress(X) ==
    CHOOSE r \in X : \A q \in X : \/ q.lwe < r.lwe
                                  \/ (q.lwe = r.lwe /\ q.segLast <= r.segLast)

\* QJM:316-394 recoverUnclosedSegment: prepare quorum, pick the best logger
\* (SRC), sanity check, then acceptRecovery.
RecoverUnclosedSegment_GotPrepare(w) ==
    /\ wPhase[w] = "wait" /\ wOp[w].op = "prepare"
    /\ GotQuorum(w)
    /\ LET R       == {wRes[w][j] : j \in OkSet(w)}
           withSeg == {r \in R : r.hasSeg}
           fin     == {r \in withSeg : ~r.segInProg}
           S       == wRec[w].seg
       IN IF withSeg = {}
          THEN \* QJM:347-371 none of the responders had a log: nothing to do.
               \* Every earlier segment is finalized, so the writer resumes at S.
               /\ wSeg' = [wSeg EXCEPT ![w] = 1]
               /\ wOp' = [wOp EXCEPT ![w] = MkOp("start", S, 0, 0)]
               /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
               /\ UNCHANGED <<chQ, wRec>>
          ELSE
            LET E   == IF fin # {} THEN (CHOOSE r \in fin : TRUE).segLast   \* SRC:67-71 finalized wins
                       ELSE BestInProgress(withSeg).segLast                 \* SRC:82-89
                bad == \/ Cardinality({r.segLast : r \in fin}) > 1          \* SRC:73-78 AssertionError
                       \/ \E r \in R : r.committed # INVALID_TXID /\ r.committed > E  \* QJM:379-390 AssertionError
            IN IF bad
               THEN /\ wPhase' = [wPhase EXCEPT ![w] = "halted"]
                    /\ DropQueues(w)
                    /\ UNCHANGED <<wOp, wSeg, wRec>>
               ELSE /\ wRec' = [wRec EXCEPT ![w].end = E]
                    /\ wOp' = [wOp EXCEPT ![w] = MkOp("accept", S, E, 0)]   \* QJM:392-396
                    /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
                    /\ UNCHANGED <<chQ, wSeg>>
    /\ UNCHANGED <<jnVars, inflight, nextSerial, outOfSync, wCid, wRes, wEpoch,
                   wCommitted, targetFired>>

\* QJM:395-403 accept quorum, then finalizeLogSegment(S, E).
RecoverUnclosedSegment_GotAccept(w) ==
    /\ wPhase[w] = "wait" /\ wOp[w].op = "accept"
    /\ GotQuorum(w)
    /\ wOp' = [wOp EXCEPT ![w] = MkOp("finalize", wRec[w].seg, wRec[w].end, 0)]
    /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
    /\ UNCHANGED <<jnVars, chVars, wCid, wRes, wEpoch, wCommitted, wSeg, wRec, targetFired>>

\* QJM:430-440 startLogSegment returns a QuorumOutputStream at a majority;
\* the workload then writes the segment's txns and flushes once
\* (QTU:89 -> QTU:105-112 -> QOS:89-113).
StartLogSegment_GotQuorum(w) ==
    /\ wPhase[w] = "wait" /\ wOp[w].op = "start"
    /\ GotQuorum(w)
    /\ LET T == wOp[w].a1 IN
       wOp' = [wOp EXCEPT ![w] = MkOp("journal", T, T, SegLenOf(wSeg[w]))]  \* QOS:110-112 sendEdits(seg, first, n)
    /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
    /\ UNCHANGED <<jnVars, chVars, wCid, wRes, wEpoch, wCommitted, wSeg, wRec, targetFired>>

\* QOS:113-118 sendEdits quorum, then setCommittedTxId on every channel;
\* the workload closes the stream and finalizes (QTU:90-92).
FlushAndSync_GotQuorum(w) ==
    /\ wPhase[w] = "wait" /\ wOp[w].op = "journal"
    /\ GotQuorum(w)
    /\ LET last == wOp[w].a2 + wOp[w].a3 - 1 IN
       /\ wCommitted' = [wCommitted EXCEPT ![w] = last]        \* QOS:118 -> ALS:75-79 -> IPCL:189-195
       /\ wOp' = [wOp EXCEPT ![w] = MkOp("finalize", wOp[w].a1, last, 0)]  \* QJM:443-446
    /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
    /\ UNCHANGED <<jnVars, chVars, wCid, wRes, wEpoch, wSeg, wRec, targetFired>>

\* QJM:443-449 finalizeLogSegment quorum. While recovering (wSeg = 0) this is
\* the recovery's finalize (QJM:402-407), after which the writer is active
\* (QJM:498) and starts at E + 1. Otherwise roll to the next segment.
FinalizeLogSegment_GotQuorum(w) ==
    /\ wPhase[w] = "wait" /\ wOp[w].op = "finalize"
    /\ GotQuorum(w)
    /\ IF wSeg[w] = 0
       THEN /\ wSeg' = [wSeg EXCEPT ![w] = 1]
            /\ wOp' = [wOp EXCEPT ![w] = MkOp("start", wRec[w].end + 1, 0, 0)]
            /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
       ELSE IF wSeg[w] < NSegs(w)
       THEN /\ wSeg' = [wSeg EXCEPT ![w] = @ + 1]
            /\ wOp' = [wOp EXCEPT ![w] = MkOp("start", wOp[w].a2 + 1, 0, 0)]  \* QTU:83 next writeSegment
            /\ wPhase' = [wPhase EXCEPT ![w] = "fanout"]
       ELSE /\ wPhase' = [wPhase EXCEPT ![w] = "done"]
            /\ UNCHANGED <<wSeg, wOp>>
    /\ UNCHANGED <<jnVars, chVars, wCid, wRes, wEpoch, wCommitted, wRec, targetFired>>

\* ALS:142-145 every logger answered and fewer than a majority succeeded:
\* QuorumException. The writer stops (FSEditLog L1437-1446 terminates).
WriterQuorumFail(w) ==
    /\ wPhase[w] = "wait"
    /\ \A j \in JN : wRes[w][j].st \in {"ok", "err"}           \* ALS:129 minResponses = all
    /\ ~GotQuorum(w)
    /\ wPhase' = [wPhase EXCEPT ![w] = "halted"]
    /\ DropQueues(w)
    /\ UNCHANGED <<jnVars, inflight, nextSerial, outOfSync, wOp, wCid, wRes,
                   wEpoch, wCommitted, wSeg, wRec, targetFired>>

\* ===========================================================================
\* Channel actions (IPCLoggerChannel)
\* ===========================================================================

\* A task starts on the single-thread executor (IPCL:86-89, FIFO). Write ops
\* past throwIfOutOfSync (IPCL:358, 492) stamp RequestInfo (IPCL:287-291:
\* epoch, ipcSerial++, committedTxId) and send the RPC. A JN that is down
\* refuses the connection, so the call fails without delivery
\* (IPCC L968-1015; the workload sets ipc.client.connect.max.retries=0).
ChannelDispatch(w, j) ==
    /\ chQ[w][j] # <<>>
    /\ inflight[w][j].op = "none"
    /\ LET t  == Head(chQ[w][j])
           ri == t.op \in ReqInfoOps
       IN /\ ~(t.op \in {"journal", "finalize"} /\ outOfSync[w][j])
          /\ inflight' = [inflight EXCEPT ![w][j] =
                [w |-> w, op |-> t.op, cid |-> t.cid,
                 a1 |-> t.a1, a2 |-> t.a2, a3 |-> t.a3,
                 epoch     |-> IF ri THEN wEpoch[w] ELSE 0,           \* IPCL:290 epoch
                 serial    |-> IF ri THEN nextSerial[w][j] ELSE -1,   \* IPCL:290 ipcSerial++
                 committed |-> IF ri THEN wCommitted[w] ELSE INVALID_TXID,  \* IPCL:290
                 st        |-> IF up[j] THEN "sent" ELSE "failed"]]
          /\ nextSerial' = IF ri THEN [nextSerial EXCEPT ![w][j] = @ + 1]
                           ELSE nextSerial
    /\ chQ' = [chQ EXCEPT ![w][j] = Tail(@)]
    /\ UNCHANGED <<jnVars, outOfSync, wVars, targetFired>>

\* IPCL:416-423 throwIfOutOfSync: journal (IPCL:358) and finalize (IPCL:492)
\* fail locally until the next successful start. The heartbeat RPC it may
\* send (IPCL:435-446) is not modeled (brief section 3.2).
ChannelFailOutOfSync(w, j) ==
    /\ chQ[w][j] # <<>>
    /\ inflight[w][j].op = "none"
    /\ Head(chQ[w][j]).op \in {"journal", "finalize"}
    /\ outOfSync[w][j]
    /\ chQ' = [chQ EXCEPT ![w][j] = Tail(@)]
    /\ RecordResult(w, j, Head(chQ[w][j]).cid, ErrResp)
    /\ UNCHANGED <<jnVars, inflight, nextSerial, outOfSync, wPhase, wOp, wCid,
                   wEpoch, wCommitted, wSeg, wRec, targetFired>>

\* The RPC threw at the client without running on the JN (lost request,
\* refused connection, timeout). IPCL:363-370 marks the channel out of sync
\* only for journal; a failed start leaves outOfSync as is (IPCL:474-487).
CallFailed(w, j) ==
    /\ inflight[w][j].st = "failed"
    /\ LET req == inflight[w][j] IN
       /\ inflight' = [inflight EXCEPT ![w][j] = NoReq]
       /\ outOfSync' = IF req.op = "journal"
                       THEN [outOfSync EXCEPT ![w][j] = TRUE]
                       ELSE outOfSync
       /\ RecordResult(w, j, req.cid, ErrResp)
    /\ UNCHANGED <<jnVars, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* ===========================================================================
\* JournalNode RPC handlers: run the handler atomically under the Journal
\* monitor and complete the client future.
\* ===========================================================================

Delivered(w, j, op) ==
    /\ up[j]
    /\ inflight[w][j].op = op
    /\ inflight[w][j].st = "sent"

\* JRPC:178-188 getJournalState
JNGetJournalState(w, j) ==
    /\ Delivered(w, j, "gjs")
    /\ LET req == inflight[w][j]
           out == HGetJournalState(jn[j])
       IN /\ jn' = [jn EXCEPT ![j] = out.st]
          /\ Complete(w, j, req, out)
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* JRPC:190-197 newEpoch -> J:339-365
JNNewEpoch(w, j) ==
    /\ Delivered(w, j, "ne")
    /\ LET req == inflight[w][j]
           out == HNewEpoch(jn[j], req.a1)
       IN /\ jn' = [jn EXCEPT ![j] = out.st]
          /\ Complete(w, j, req, out)
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* JRPC:222-227 startLogSegment -> J:568-624
JNStartLogSegment(w, j) ==
    /\ Delivered(w, j, "start")
    /\ LET req == inflight[w][j]
           out == HStart(jn[j], req)
       IN /\ jn' = [jn EXCEPT ![j] = out.st]
          /\ Complete(w, j, req, out)
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* JRPC:208-214 journal -> J:393-473, checkWriteRequest J:514-522.
\* The target: enabled whenever a journal RPC reaches the JN; the guard is
\* evaluated in HJournal exactly as at J:517.
TargetCheck(w, j) ==
    /\ Delivered(w, j, "journal")
    /\ LET req == inflight[w][j]
           out == HJournal(jn[j], req)
       IN /\ jn' = [jn EXCEPT ![j] = out.st]
          /\ targetFired' = (out.res = TargetCode)             \* J:518 throw new IOException(...)
          /\ Complete(w, j, req, out)
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec>>

\* JRPC:229-234 finalizeLogSegment -> J:629-685
JNFinalizeLogSegment(w, j) ==
    /\ Delivered(w, j, "finalize")
    /\ LET req == inflight[w][j]
           out == HFinalize(jn[j], req)
       IN /\ jn' = [jn EXCEPT ![j] = out.st]
          /\ Complete(w, j, req, out)
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* JRPC:275-279 prepareRecovery -> J:827-866 (IPCL:527-538; the extra getJournalState
\* it sends when the HTTP endpoint is unknown is read-only)
JNPrepareRecovery(w, j) ==
    /\ Delivered(w, j, "prepare")
    /\ LET req == inflight[w][j]
           out == HPrepare(jn[j], req)
       IN /\ jn' = [jn EXCEPT ![j] = out.st]
          /\ Complete(w, j, req, out)
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* JRPC:283-286 acceptRecovery -> J:871-986 (the log download always succeeds)
JNAcceptRecovery(w, j) ==
    /\ Delivered(w, j, "accept")
    /\ LET req == inflight[w][j]
           out == HAccept(jn[j], req)
       IN /\ jn' = [jn EXCEPT ![j] = out.st]
          /\ Complete(w, j, req, out)
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* ===========================================================================
\* Fault actions (bounded in MC.tla)
\* ===========================================================================

\* S1/S3: the request never reaches the JN; the client sees an IOException
\* (IPCC L1294-1304 markClosed fails pending calls; no resend, IPCC
\* L1514-1560). In-tree shape: TestQJMWithFaults#failIpcNumber, which throws
\* after createReqInfo has stamped the request.
LoseRequest(w, j) ==
    /\ inflight[w][j].st = "sent"
    /\ inflight[w][j].op \in LostOps
    /\ inflight' = [inflight EXCEPT ![w][j].st = "failed"]
    /\ UNCHANGED <<jnVars, chQ, nextSerial, outOfSync, wVars, targetFired>>

\* S4: the client's call times out (IPCC L545-571, rpc timeout 120 s) and
\* fails, but the JN still holds the call: a handler that already passed
\* the isOpen check runs it later (IPCS L1300-1304). No ordering across
\* connections (IPCS L3273-3279).
TimeoutLate(w, j) ==
    /\ inflight[w][j].st = "sent"
    /\ srvPend' = [srvPend EXCEPT ![j] = @ \cup {inflight[w][j]}]
    /\ inflight' = [inflight EXCEPT ![w][j].st = "failed"]
    /\ UNCHANGED <<jn, up, chQ, nextSerial, outOfSync, wVars, targetFired>>

\* S4: a held call finally runs (atomically, under the Journal monitor). A
\* late journal evaluates the target guard too (HJournal).
JNExecLate(j) ==
    /\ up[j]
    /\ \E r \in srvPend[j] :
         LET out == Handler(jn[j], r) IN
         /\ jn' = [jn EXCEPT ![j] = out.st]
         /\ srvPend' = [srvPend EXCEPT ![j] = @ \ {r}]
         /\ targetFired' = (r.op = "journal" /\ out.res = TargetCode)  \* J:518
    /\ UNCHANGED <<up, chVars, wVars>>

\* S4: the handler skips a call whose connection is closed (IPCS L1300-1304).
DropLate(j) ==
    /\ \E r \in srvPend[j] : srvPend' = [srvPend EXCEPT ![j] = @ \ {r}]
    /\ UNCHANGED <<jn, up, chVars, wVars, targetFired>>

\* Requests in flight to a stopped JN fail at the client.
FailInflightTo(j) ==
    inflight' = [w \in Writers |-> [k \in JN |->
                   IF k = j /\ inflight[w][k].st = "sent"
                   THEN [inflight[w][k] EXCEPT !.st = "failed"]
                   ELSE inflight[w][k]]]

\* S2: JN process stops (MiniJournalCluster stopAndJoin). Calls it held die.
Crash(j) ==
    /\ up[j]
    /\ up' = [up EXCEPT ![j] = FALSE]
    /\ FailInflightTo(j)
    /\ srvPend' = [srvPend EXCEPT ![j] = {}]
    /\ UNCHANGED <<jn, chQ, nextSerial, outOfSync, wVars, targetFired>>

\* S2: JN restarts. The Journal is re-created on the first RPC
\* (JNd:98-125 -> J:159-178): volatile fields reinitialized (J:90-93, 117),
\* epochs reloaded lazily from disk (J:166 -> J:202-213), and the
\* constructor's scan moves empty trailing files aside (J:174 -> J:221-246).
Restart(j) ==
    /\ ~up[j]
    /\ up' = [up EXCEPT ![j] = TRUE]
    /\ LET s == jn[j] IN
       jn' = [jn EXCEPT ![j] =
                [s EXCEPT !.serial = -1,                       \* J:117
                          !.curSeg = INVALID_TXID,             \* J:90-91
                          !.nextTx = INVALID_TXID,             \* J:93
                          !.lwMem  = s.lwDisk,                 \* J:208-209 reload (missing file -> 0)
                          \* lwPrev kept: a process crash does not make the
                          \* last rename durable (no directory fsync, AFOS:81)
                          !.files  = ScanLatest(s.files).files]]  \* J:174
    /\ UNCHANGED <<srvPend, chVars, wVars, targetFired>>

\* S5a/S5b: startLogSegment reaches J:611 and lastWriterEpoch.set() throws.
\* PLF L61-67 writes before updating the cache, so the cache keeps the old
\* value. On disk the old file survives (a: write/fsync/rename error), or the
\* rename fallback already deleted it (b: AFOS L84-97), which reads as 0.
StartPersistFail(w, j) ==
    /\ Delivered(w, j, "start")
    /\ LET req == inflight[w][j]
           pre == HStartPre(jn[j], req)
       IN /\ pre.res = "ok"
          /\ pre.st.lwMem # req.epoch                          \* J:607 the set() at J:611 runs
          /\ \E d \in {pre.st.lwDisk, 0} :
               jn' = [jn EXCEPT ![j] = [pre.st EXCEPT !.lwDisk = d, !.lwPrev = d]]
          /\ Complete(w, j, req, [res |-> "L611io", resp |-> NoResp])
    /\ UNCHANGED <<up, srvPend, chQ, nextSerial, wPhase, wOp, wCid, wEpoch,
                   wCommitted, wSeg, wRec, targetFired>>

\* S5c: OS crash / power loss. AFOS:81 renames without fsyncing the
\* directory, so the last rename of last-writer-epoch may be undone.
PowerLoss(j) ==
    /\ up[j]
    /\ up' = [up EXCEPT ![j] = FALSE]
    /\ \E d \in {jn[j].lwDisk, jn[j].lwPrev} :
         jn' = [jn EXCEPT ![j].lwDisk = d, ![j].lwPrev = d]
    /\ FailInflightTo(j)
    /\ srvPend' = [srvPend EXCEPT ![j] = {}]
    /\ UNCHANGED <<chQ, nextSerial, outOfSync, wVars, targetFired>>

\* S3: the writer (NameNode) dies between steps. Its queued tasks die with
\* it; RPCs already in flight may still run on the JNs.
WriterCrash(w) ==
    /\ wPhase[w] \in {"fanout", "wait"}
    /\ wPhase' = [wPhase EXCEPT ![w] = "halted"]
    /\ DropQueues(w)
    /\ UNCHANGED <<jnVars, inflight, nextSerial, outOfSync, wOp, wCid, wRes,
                   wEpoch, wCommitted, wSeg, wRec, targetFired>>

\* ===========================================================================
\* Specification
\* ===========================================================================

Init ==
    /\ jn = [j \in JN |-> JNInit]                 \* freshly formatted (MiniJournalCluster; qjm.format)
    /\ up = [j \in JN |-> TRUE]
    /\ srvPend = [j \in JN |-> {}]
    /\ chQ = [w \in Writers |-> [j \in JN |-> <<>>]]
    /\ inflight = [w \in Writers |-> [j \in JN |-> NoReq]]
    /\ nextSerial = [w \in Writers |-> [j \in JN |-> 0]]      \* IPCL:96
    /\ outOfSync = [w \in Writers |-> [j \in JN |-> FALSE]]   \* IPCL:146
    /\ wPhase = [w \in Writers |-> "idle"]
    /\ wOp = [w \in Writers |-> MkOp("none", 0, 0, 0)]
    /\ wCid = [w \in Writers |-> 0]
    /\ wRes = [w \in Writers |-> [j \in JN |-> NoResp]]
    /\ wEpoch = [w \in Writers |-> -1]                        \* IPCL:97
    /\ wCommitted = [w \in Writers |-> INVALID_TXID]          \* IPCL:98
    /\ wSeg = [w \in Writers |-> 0]
    /\ wRec = [w \in Writers |-> [seg |-> NoSeg, end |-> 0]]
    /\ targetFired = FALSE

WriterStep(w) ==
    \/ WriterBegin(w)
    \/ WriterFanOut(w)
    \/ CreateNewUniqueEpoch_GotJournalState(w)
    \/ CreateNewUniqueEpoch_GotNewEpoch(w)
    \/ RecoverUnclosedSegment_GotPrepare(w)
    \/ RecoverUnclosedSegment_GotAccept(w)
    \/ StartLogSegment_GotQuorum(w)
    \/ FlushAndSync_GotQuorum(w)
    \/ FinalizeLogSegment_GotQuorum(w)
    \/ WriterQuorumFail(w)

ChannelStep(w, j) ==
    \/ ChannelDispatch(w, j)
    \/ ChannelFailOutOfSync(w, j)
    \/ CallFailed(w, j)
    \/ JNGetJournalState(w, j)
    \/ JNNewEpoch(w, j)
    \/ JNStartLogSegment(w, j)
    \/ TargetCheck(w, j)
    \/ JNFinalizeLogSegment(w, j)
    \/ JNPrepareRecovery(w, j)
    \/ JNAcceptRecovery(w, j)

FaultStep ==
    \/ \E w \in Writers, j \in JN : LoseRequest(w, j) \/ TimeoutLate(w, j)
                                    \/ StartPersistFail(w, j)
    \/ \E w \in Writers : WriterCrash(w)
    \/ \E j \in JN : Crash(j) \/ Restart(j) \/ PowerLoss(j)
                     \/ JNExecLate(j) \/ DropLate(j)

\* Once the target has thrown, everything stops (short counterexamples).
Next ==
    /\ ~targetFired
    /\ \/ \E w \in Writers : WriterStep(w)
       \/ \E w \in Writers, j \in JN : ChannelStep(w, j)
       \/ FaultStep

Spec == Init /\ [][Next]_vars

\* ===========================================================================
\* Properties
\* ===========================================================================

\* The oracle: Journal.java:518 never throws.
TargetSafe == ~targetFired

\* Temporary sanity check (tla-patterns.md section 2): TLC must VIOLATE this,
\* proving that some state enables the target's code path.
TargetReached == ~(\E w \in Writers, j \in JN : ENABLED TargetCheck(w, j))

Codes == {"ok", TargetCode, "L347", "L405", "L408", "L423", "L486", "L497",
          "L504", "L591", "L600", "L611io", "L645", "L656", "L666", "L674",
          "L926", "L938"}

TxOrNone == TxIds \cup {INVALID_TXID}
FileStates == {NoFile}
              \cup [st : {"inprog"}, last : TxOrNone]
              \cup [st : {"final"}, last : TxIds]
Epochs == 0..(NumWriters + 1)
OpCount == 3 + 3 * Len(SegLen) + 3                     \* upper bound on calls per writer
ReqRec == [w : Writers, op : Ops, cid : 0..OpCount,
           a1 : Int, a2 : Int, a3 : Int, epoch : Epochs \cup {-1},
           serial : -1..OpCount, committed : TxOrNone,
           st : {"sent", "failed"}]

\* Structural sanity 1: domains.
TypeOK ==
    /\ targetFired \in BOOLEAN
    /\ up \in [JN -> BOOLEAN]
    /\ \A j \in JN :
         /\ jn[j].promised \in Epochs
         /\ jn[j].lwMem \in Epochs /\ jn[j].lwDisk \in Epochs /\ jn[j].lwPrev \in Epochs
         /\ jn[j].serial \in -1..OpCount
         /\ jn[j].curSeg \in TxOrNone
         /\ jn[j].nextTx \in TxOrNone \cup {MaxTxId + 1}
         /\ jn[j].committed \in TxOrNone
         /\ \A t \in TxIds : jn[j].files[t] \in FileStates
         /\ srvPend[j] \subseteq ReqRec
    /\ \A w \in Writers :
         /\ wPhase[w] \in {"idle", "fanout", "wait", "done", "halted"}
         /\ wOp[w].op \in Ops \cup {"none"}
         /\ wEpoch[w] \in Epochs \cup {-1}
         /\ wCommitted[w] \in TxOrNone
         /\ wSeg[w] \in 0..Len(SegLen)
         /\ \A j \in JN :
              /\ inflight[w][j] \in ReqRec \cup {NoReq}
              /\ nextSerial[w][j] \in 0..(OpCount + 1)
              /\ outOfSync[w][j] \in BOOLEAN
              /\ wRes[w][j].st \in {"none", "pending", "ok", "err"}
              /\ \A k \in 1..Len(chQ[w][j]) : chQ[w][j][k].op \in Ops

\* Structural sanity 2: a request carries only values its sender held.
\* RequestInfo fields are the writer's epoch, a serial the channel already
\* issued, and a committed txid not above the writer's.
ReqFromSender(r, j) ==
    r.op \in ReqInfoOps =>
        /\ r.epoch = wEpoch[r.w]
        /\ r.serial < nextSerial[r.w][j]
        /\ r.committed <= wCommitted[r.w]

MsgFromSender ==
    /\ \A w \in Writers, j \in JN :
         inflight[w][j].op # "none" =>
            /\ inflight[w][j].w = w
            /\ ReqFromSender(inflight[w][j], j)
    /\ \A j \in JN : \A r \in srvPend[j] : ReqFromSender(r, j)

=============================================================================
