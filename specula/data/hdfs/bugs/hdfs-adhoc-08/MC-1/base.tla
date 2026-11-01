-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-08: the stale-epoch fence in Journal.checkRequest.           *)
(*                                                                         *)
(* Target: Journal.java:486-489 (throw at 487, frame line 489)             *)
(*     if (reqInfo.getEpoch() < lastPromisedEpoch.get()) throw IOException *)
(* Property: TargetSafe == ~targetFired.                                   *)
(*                                                                         *)
(* Category A (distributed, message passing, crash faults). One NameNode-  *)
(* side writer at a time (a QuorumJournalManager instance, "writer") talks *)
(* to the JournalNodes (JN) over Hadoop IPC. One journal id.               *)
(*                                                                         *)
(* Source tree pinned at 734dd8a67cd. Paths are relative to                *)
(*   hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/ *)
(*   J    = qjournal/server/Journal.java                                   *)
(*   JNRS = qjournal/server/JournalNodeRpcServer.java                      *)
(*   JNd  = qjournal/server/JournalNode.java                               *)
(*   QJM  = qjournal/client/QuorumJournalManager.java                      *)
(*   ALS  = qjournal/client/AsyncLoggerSet.java                            *)
(*   ILC  = qjournal/client/IPCLoggerChannel.java                          *)
(*   QC   = qjournal/client/QuorumCall.java                                *)
(*   QOS  = qjournal/client/QuorumOutputStream.java                        *)
(*   PLF  = util/PersistentLongFile.java                                   *)
(*   NNU  = server/namenode/NNUpgradeUtil.java                             *)
(*                                                                         *)
(* Scope (modeling-brief.md §3):                                           *)
(*  - JN promise as PersistentLongFile: cached value + on-disk value, lazy *)
(*    load (PLF:53-67). Scenario 2 needs the cache/disk split.             *)
(*  - Epoch acquisition as coded: 1 + max over the getJournalState replies *)
(*    present when the majority wait returns; newEpoch majority; setEpoch  *)
(*    on ALL loggers (QJM:227-248, ALS:61-68). Scenarios 1 and 2.          *)
(*  - Every RPC carrying RequestInfo reaches the JN through TargetCheck    *)
(*    (one action, kind label), which evaluates J:486 exactly.             *)
(*  - Per (writer, JN) FIFO single-thread executor with one blocking RPC   *)
(*    in flight (ILC:85-89); quorum waits return at a majority (QC:165-177)*)
(*    and leave the minority's requests queued.                            *)
(*  - Not modeled (brief §3.2): edit bytes, txids, segment files (only a   *)
(*    "has a segment" bit), committedTxId, the IPC serial check            *)
(*    (J:497-501), the lastWriterEpoch check (J:517-521), read RPCs,       *)
(*    heartbeat/purge sends (see TargetCheck comment), JournalNodeSyncer.  *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets, TLC

CONSTANTS
    JN,          \* JournalNodes of the quorum (workload: MiniJournalCluster with 3)
    MaxWriters,  \* number of sequential writer instances (one QJM per NN activation)
    ReqRounds,   \* write rounds (startLogSegment, journal, finalizeLogSegment) per writer
    NoOverlap,   \* hunt scope (brief §3.1.3): a writer starts only after every earlier
                 \* writer has stopped. FALSE re-admits the designed paths D1/D3.
    DropOnStop   \* hunt scope (brief §3.1.3): a stopped writer's undelivered requests
                 \* and replies are discarded. FALSE re-admits the designed path D2.

ASSUME /\ IsFiniteSet(JN) /\ JN # {}
       /\ MaxWriters \in Nat /\ MaxWriters >= 1
       /\ ReqRounds \in Nat
       /\ NoOverlap \in BOOLEAN
       /\ DropOnStop \in BOOLEAN

Writer == 1..MaxWriters

\* ILC:97 `epoch = -1`; ALS:54 INVALID_EPOCH = -1.
NoEpoch == -1
\* PLF:46 `loaded = false`: the cached value has not been read from disk yet.
NotLoaded == -1
\* No `previous/` directory (NNU:216-218 rollback is a no-op without it).
NoPrev == [promise |-> -1, seg |-> FALSE]
\* No reply in flight on the (writer, JN) channel. Real rounds start at 1.
NoReply == [rnd |-> 0, kind |-> "none", ok |-> FALSE, val |-> -1]

\* RPC kinds. GJS = getJournalState, NE = newEpoch (neither carries RequestInfo).
\* RequestInfo kinds (brief §1, report §2.4): PR = prepareRecovery,
\* AR = acceptRecovery, FIN = finalizeLogSegment, SLS = startLogSegment,
\* J = journal (sendEdits).
Kinds   == {"GJS", "NE", "PR", "AR", "FIN", "SLS", "J"}
RIKinds == {"PR", "AR", "FIN", "SLS", "J"}

\* Writer states.
\*  idle    : QJM not yet activated
\*  gjs     : waiting for the getJournalState quorum   (QJM:232-234)
\*  ne      : waiting for the newEpoch quorum          (QJM:243-245)
\*  pr      : waiting for the prepareRecovery quorum   (QJM:317-321)
\*  ar      : waiting for the acceptRecovery quorum    (QJM:394-396)
\*  rfin    : waiting for the recovery finalize quorum (QJM:402-407)
\*  ready   : isActiveWriter = true, no call outstanding (QJM:498)
\*  sls     : waiting for the startLogSegment quorum   (QJM:434-437)
\*  j       : waiting for the sendEdits quorum         (QOS:110-113)
\*  fin     : waiting for the finalizeLogSegment quorum (QJM:445-448)
\*  stopped : crashed, timed out, terminated (JournalSet.java:394-408) or closed
WStates    == {"idle", "gjs", "ne", "pr", "ar", "rfin", "ready",
               "sls", "j", "fin", "stopped"}
WaitStates == {"gjs", "ne", "pr", "ar", "rfin", "sls", "j", "fin"}

VARIABLES
    \* ---- JournalNode state (one Journal object per JN; JNd:80, 98-125) ----
    cache,       \* lastPromisedEpoch PLF cached value, or NotLoaded (PLF:45-46)
    disk,        \* current/last-promised-epoch on disk (PLF:61-67, 76-88)
    prev,        \* previous/ snapshot after an upgrade: [promise, seg], or NoPrev
    hasSeg,      \* JN holds an edit segment with transactions (NE/PR reply field)
    \* ---- writer (QJM instance) state ----
    wst,         \* writer state, see WStates
    wRnd,        \* number of fan-outs issued (identifies the current QuorumCall)
    wResp,       \* current QuorumCall outcome per JN: "none" | "ok" | "err"
    wVal,        \* current QuorumCall success payload per JN (GJS: promise; NE/PR: seg bit)
    wCand,       \* myEpoch chosen in createNewUniqueEpoch (QJM:242), or NoEpoch
    wEpoch,      \* epoch established on every channel by setEpoch (ALS:61-68, ILC:183-186)
    wSeg,        \* write rounds started (bounded by ReqRounds)
    \* ---- network: per (writer, JN) single-thread executor queue ----
    chan,        \* chan[w][j]: FIFO of requests; the head is the one in flight (ILC:85-89)
    rep,         \* rep[w][j]: reply in flight back to the client, or NoReply
    \* ---- target ----
    targetFired  \* J:487-489 throw executed

jnVars  == <<cache, disk, prev, hasSeg>>
wVars   == <<wst, wRnd, wResp, wVal, wCand, wEpoch, wSeg>>
netVars == <<chan, rep>>
vars    == <<cache, disk, prev, hasSeg, wst, wRnd, wResp, wVal, wCand, wEpoch,
             wSeg, chan, rep, targetFired>>

-----------------------------------------------------------------------------
(* Helpers *)

Max(S) == CHOOSE x \in S : \A y \in S : x >= y

\* PersistentLongFile.get() (PLF:53-59): read the file on the first access only.
\* Every caller below also writes the loaded value back into `cache`.
EffPromise(j) == IF cache[j] = NotLoaded THEN disk[j] ELSE cache[j]

\* ALS:153-155 getMajoritySize = size / 2 + 1.
Majority == Cardinality(JN) \div 2 + 1

NumOk(w)   == Cardinality({j \in JN : wResp[w][j] = "ok"})
NumErr(w)  == Cardinality({j \in JN : wResp[w][j] = "err"})
NumResp(w) == NumOk(w) + NumErr(w)

\* ALS:124-148 waitForWriteQuorum = QC.waitFor(N, majority, majority).
\* QC:176 returns once `majority` successes are in; ALS:142 then passes and
\* ALS:147 returns the success snapshot (QC:299-301).
QuorumOk(w) == NumOk(w) >= Majority
\* QC:175 (all responded) or QC:177 (exceptions > majority) returns with fewer
\* than `majority` successes; ALS:142-145 throws QuorumException.
QuorumFailed(w) ==
    /\ \/ NumResp(w) >= Cardinality(JN)
       \/ NumErr(w) > Majority
    /\ NumOk(w) < Majority

Live(w) == wst[w] \notin {"idle", "stopped"}

\* ALS fan-out (ALS:208-215, 225-234, 236-252, 254-263, 291-314): one task is
\* submitted to every logger's single-thread executor and one QuorumCall is
\* created (QC:71-91). The new call starts with no responses.
SendToAll(w, kind, e) ==
    /\ chan' = [chan EXCEPT ![w] =
                  [j \in JN |-> Append(chan[w][j],
                                       [kind |-> kind, rnd |-> wRnd[w] + 1,
                                        epoch |-> e])]]
    /\ wRnd'  = [wRnd  EXCEPT ![w] = @ + 1]
    /\ wResp' = [wResp EXCEPT ![w] = [j \in JN |-> "none"]]
    /\ wVal'  = [wVal  EXCEPT ![w] = [j \in JN |-> -1]]

\* The finished QuorumCall is no longer consulted (canonical "no call" state).
ClearCall(w) ==
    /\ wResp' = [wResp EXCEPT ![w] = [j \in JN |-> "none"]]
    /\ wVal'  = [wVal  EXCEPT ![w] = [j \in JN |-> -1]]

\* A writer stops: NN crash, quorum timeout (ALS:137-139), QuorumException
\* followed by terminate (JournalSet.java:394-408), or QJM.close (QJM:501-505).
\* DropOnStop: its undelivered requests and replies are discarded. Without it,
\* ILC.close only calls executor.shutdown() (ILC:197-210), so queued tasks still run.
StopWriter(w) ==
    /\ wst'  = [wst  EXCEPT ![w] = "stopped"]
    /\ wRnd' = [wRnd EXCEPT ![w] = 0]
    /\ wSeg' = [wSeg EXCEPT ![w] = 0]
    /\ ClearCall(w)
    /\ IF DropOnStop
         THEN /\ chan' = [chan EXCEPT ![w] = [j \in JN |-> <<>>]]
              /\ rep'  = [rep  EXCEPT ![w] = [j \in JN |-> NoReply]]
         ELSE UNCHANGED <<chan, rep>>

\* The request at the head of chan[w][j] is in flight once the previous reply
\* has reached the client: the executor thread blocks on one RPC at a time.
HeadInFlight(w, j) == /\ rep[w][j] = NoReply
                      /\ chan[w][j] # <<>>

-----------------------------------------------------------------------------
(* Writer (NameNode / QJM) actions *)

\* QJM.recoverUnfinalizedSegments (QJM:474-478) -> createNewUniqueEpoch
\* (QJM:227-234) -> loggers.getJournalState() fan-out (ALS:208-215).
\* Every NN activation builds a new QJM (FSEditLog.java:288-310,
\* FSNamesystem.java:1421-1423), so a writer index is one QJM instance.
WriterStart(w) ==
    /\ wst[w] = "idle"
    \* Brief §3.1.3: NoOverlap = writers never overlap (excludes D1/D3).
    /\ \A v \in Writer : v < w =>
          IF NoOverlap THEN wst[v] = "stopped" ELSE wst[v] # "idle"
    /\ wst' = [wst EXCEPT ![w] = "gjs"]
    \* ILC:325-332: getJournalState carries no RequestInfo (epoch field unused).
    /\ SendToAll(w, "GJS", NoEpoch)
    /\ UNCHANGED <<jnVars, rep, wCand, wEpoch, wSeg, targetFired>>

\* QJM:232-245. The getJournalState wait returned with a majority of successes
\* (ALS:124-147, QC:176). myEpoch = 1 + max over the successful replies present
\* in the snapshot (QJM:236-242; QC:299-301). Slow or failed JNs are ignored even
\* if they hold the highest promise. Then loggers.newEpoch(nsInfo, myEpoch)
\* fan-out (QJM:243-244; ALS:225-234; ILC:334-339).
ChooseEpoch(w) ==
    /\ wst[w] = "gjs"
    /\ QuorumOk(w)
    /\ LET okJ         == {j \in JN : wResp[w][j] = "ok"}
           maxPromised == Max({wVal[w][j] : j \in okJ})      \* QJM:236-239
           myEpoch     == maxPromised + 1                     \* QJM:242
       IN /\ wCand' = [wCand EXCEPT ![w] = myEpoch]
          /\ wst'   = [wst   EXCEPT ![w] = "ne"]
          /\ SendToAll(w, "NE", myEpoch)
    /\ UNCHANGED <<jnVars, rep, wEpoch, wSeg, targetFired>>

\* QJM:243-247 then QJM:478-498. The newEpoch wait returned with a majority of
\* successes. loggers.setEpoch(myEpoch) sets the epoch of ALL loggers, including
\* JNs that rejected with "Proposed epoch X <= last promise Y" (ALS:61-68,
\* ILC:183-186): nothing marks or retries them (CR-3).
\* QJM:485-491: recovery is needed iff a successful newEpoch reply reported a
\* segment (lastSegmentTxId, J:358-362). Then recoverUnclosedSegment ->
\* prepareRecovery fan-out (QJM:496, 317-318; ALS:291-302); else
\* isActiveWriter = true (QJM:498).
Establish(w) ==
    /\ wst[w] = "ne"
    /\ QuorumOk(w)
    /\ wEpoch' = [wEpoch EXCEPT ![w] = wCand[w]]              \* QJM:247
    /\ LET needRec == \E j \in JN : wResp[w][j] = "ok" /\ wVal[w][j] = 1
       IN IF needRec                                          \* QJM:495
            THEN /\ wst' = [wst EXCEPT ![w] = "pr"]
                 \* ILC:536 createReqInfo reads the channel epoch set at QJM:247.
                 /\ SendToAll(w, "PR", wCand[w])
            ELSE /\ wst' = [wst EXCEPT ![w] = "ready"]        \* QJM:498
                 /\ ClearCall(w)
                 /\ UNCHANGED <<chan, wRnd>>
    /\ UNCHANGED <<jnVars, rep, wCand, wSeg, targetFired>>

\* QJM:319-346, 374-396. The prepareRecovery wait returned with a majority; the
\* best response has a segment (or an accepted value): acceptRecovery fan-out
\* (QJM:394; ALS:304-314; ILC:541-546).
AcceptRecovery(w) ==
    /\ wst[w] = "pr"
    /\ QuorumOk(w)
    /\ \E j \in JN : wResp[w][j] = "ok" /\ wVal[w][j] = 1    \* QJM:341-346
    /\ wst' = [wst EXCEPT ![w] = "ar"]
    /\ SendToAll(w, "AR", wEpoch[w])
    /\ UNCHANGED <<jnVars, rep, wCand, wEpoch, wSeg, targetFired>>

\* QJM:347-371. No prepareRecovery response has a log to recover: return,
\* then isActiveWriter = true (QJM:498).
RecoveryNoLog(w) ==
    /\ wst[w] = "pr"
    /\ QuorumOk(w)
    /\ ~\E j \in JN : wResp[w][j] = "ok" /\ wVal[w][j] = 1
    /\ wst' = [wst EXCEPT ![w] = "ready"]
    /\ ClearCall(w)
    /\ UNCHANGED <<jnVars, netVars, wRnd, wCand, wEpoch, wSeg, targetFired>>

\* QJM:395-403. acceptRecovery quorum reached: finalizeLogSegment fan-out
\* (ALS:245-252; ILC:490-496).
RecoveryFinalize(w) ==
    /\ wst[w] = "ar"
    /\ QuorumOk(w)
    /\ wst' = [wst EXCEPT ![w] = "rfin"]
    /\ SendToAll(w, "FIN", wEpoch[w])
    /\ UNCHANGED <<jnVars, rep, wCand, wEpoch, wSeg, targetFired>>

\* QJM:404-408 recovery finalize quorum reached; QJM:498 isActiveWriter = true.
RecoveryDone(w) ==
    /\ wst[w] = "rfin"
    /\ QuorumOk(w)
    /\ wst' = [wst EXCEPT ![w] = "ready"]
    /\ ClearCall(w)
    /\ UNCHANGED <<jnVars, netVars, wRnd, wCand, wEpoch, wSeg, targetFired>>

\* QJM:429-437: startLogSegment (precondition isActiveWriter, QJM:432-433)
\* fan-out (ALS:236-243). ILC:473-487 sends it to every logger, with no
\* out-of-sync check, so a JN that rejected newEpoch receives it too.
StartLogSegment(w) ==
    /\ wst[w] = "ready"
    /\ wSeg[w] < ReqRounds
    /\ wst'  = [wst  EXCEPT ![w] = "sls"]
    /\ wSeg' = [wSeg EXCEPT ![w] = @ + 1]
    /\ SendToAll(w, "SLS", wEpoch[w])
    /\ UNCHANGED <<jnVars, rep, wCand, wEpoch, targetFired>>

\* QJM:436-439 startLogSegment quorum reached; a QuorumOutputStream is created
\* and its flush sends the batch: loggers.sendEdits fan-out (QOS:89-112;
\* ALS:254-263; ILC:342-414).
SendEdits(w) ==
    /\ wst[w] = "sls"
    /\ QuorumOk(w)
    /\ wst' = [wst EXCEPT ![w] = "j"]
    /\ SendToAll(w, "J", wEpoch[w])
    /\ UNCHANGED <<jnVars, rep, wCand, wEpoch, wSeg, targetFired>>

\* QOS:113-118 sendEdits quorum reached; the stream is closed and
\* QJM.finalizeLogSegment fans out (QJM:442-446; ALS:245-252; ILC:490-496).
FinalizeLogSegment(w) ==
    /\ wst[w] = "j"
    /\ QuorumOk(w)
    /\ wst' = [wst EXCEPT ![w] = "fin"]
    /\ SendToAll(w, "FIN", wEpoch[w])
    /\ UNCHANGED <<jnVars, rep, wCand, wEpoch, wSeg, targetFired>>

\* QJM:447-448 finalizeLogSegment quorum reached; the writer is idle-active.
SegmentFinalized(w) ==
    /\ wst[w] = "fin"
    /\ QuorumOk(w)
    /\ wst' = [wst EXCEPT ![w] = "ready"]
    /\ ClearCall(w)
    /\ UNCHANGED <<jnVars, netVars, wRnd, wCand, wEpoch, wSeg, targetFired>>

\* ALS:142-145: the wait returned (QC:175 all responded, or QC:177) with fewer
\* than a majority of successes -> QuorumException. A failed epoch acquisition
\* or a failed write on the shared journal terminates the NN
\* (JournalSet.java:394-408), so the writer stops. Reactive, not a fault.
QuorumFail(w) ==
    /\ wst[w] \in WaitStates
    /\ QuorumFailed(w)
    /\ StopWriter(w)
    /\ UNCHANGED <<jnVars, wCand, wEpoch, targetFired>>

\* Fault: NN crash, quorum timeout (ALS:137-139 -> terminate), or close
\* (QJM:501-505, ALS:101-105). Any live state.
WriterStop(w) ==
    /\ Live(w)
    /\ StopWriter(w)
    /\ UNCHANGED <<jnVars, wCand, wEpoch, targetFired>>

-----------------------------------------------------------------------------
(* JournalNode RPC handlers. Each Journal RPC method is synchronized, so one  *)
(* RPC is atomic per journal (report §1).                                    *)

\* JNRS:178-188 getJournalState -> Journal.getLastPromisedEpoch (J:284-287):
\* checkFormatted (always formatted here), lastPromisedEpoch.get() (PLF:53-59,
\* loads the cache lazily). The reply carries the cached value.
HandleGetJournalState(j, w) ==
    /\ HeadInFlight(w, j)
    /\ Head(chan[w][j]).kind = "GJS"
    /\ LET m == Head(chan[w][j])
           p == EffPromise(j)
       IN /\ cache' = [cache EXCEPT ![j] = p]
          /\ rep'   = [rep EXCEPT ![w][j] =
                         [rnd |-> m.rnd, kind |-> m.kind, ok |-> TRUE, val |-> p]]
          /\ chan'  = [chan EXCEPT ![w][j] = Tail(@)]
    /\ UNCHANGED <<disk, prev, hasSeg, wVars, targetFired>>

\* JNRS:191-197 -> Journal.newEpoch (J:339-365).
HandleNewEpoch(j, w) ==
    /\ HeadInFlight(w, j)
    /\ Head(chan[w][j]).kind = "NE"
    /\ LET m == Head(chan[w][j])
           p == EffPromise(j)          \* J:347 getLastPromisedEpoch() -> get()
       IN /\ IF m.epoch <= p           \* J:347
               THEN \* J:348-349 throw "Proposed epoch X <= last promise Y".
                    /\ cache' = [cache EXCEPT ![j] = p]
                    /\ disk'  = disk
                    /\ rep'   = [rep EXCEPT ![w][j] =
                                   [rnd |-> m.rnd, kind |-> m.kind,
                                    ok |-> FALSE, val |-> -1]]
               ELSE \* J:352 updateLastPromisedEpoch -> J:371 PLF.set: write the
                    \* file, then the cached value (PLF:61-67). J:375 serial reset
                    \* is not modeled. J:358-362 reply with lastSegmentTxId if a
                    \* segment with transactions exists.
                    /\ cache' = [cache EXCEPT ![j] = m.epoch]
                    /\ disk'  = [disk  EXCEPT ![j] = m.epoch]
                    /\ rep'   = [rep EXCEPT ![w][j] =
                                   [rnd |-> m.rnd, kind |-> m.kind, ok |-> TRUE,
                                    val |-> IF hasSeg[j] THEN 1 ELSE 0]]
          /\ chan' = [chan EXCEPT ![w][j] = Tail(@)]
    /\ UNCHANGED <<prev, hasSeg, wVars, targetFired>>

\* TARGET. Journal.checkRequest (J:484-512), reached by every RPC that carries
\* RequestInfo (report §2.4):
\*   SLS startLogSegment    J:568-572   (after checkFormatted J:571)
\*   J   journal            J:393-397 -> checkWriteRequest J:514-515
\*   FIN finalizeLogSegment J:629-632
\*   PR  prepareRecovery    J:827-830
\*   AR  acceptRecovery     J:871-875
\* heartbeat (J:475-476) and purgeLogsOlderThan (J:690-693) also reach it, but
\* the model never sends them. The request epoch is constant per writer (report
\* §3.1). With NoOverlap/DropOnStop, while a writer lives a JN's effective
\* promise only rises through that writer's own newEpoch/bump (to its epoch) or
\* drops through JNRestart (a loaded cache is never below the disk value).
\* So the first RequestInfo RPC a JN handles from a writer already decides J:486
\* for every later one, whatever its kind (brief-coverage.md §7.1).
\* The request epoch m.epoch is RequestInfo.getEpoch(): the channel epoch read
\* by createReqInfo (ILC:287-291), copied verbatim over the wire.
TargetCheck(j, w) ==
    /\ HeadInFlight(w, j)
    /\ Head(chan[w][j]).kind \in RIKinds
    /\ LET m == Head(chan[w][j])
           p == EffPromise(j)          \* J:486 lastPromisedEpoch.get() (cached)
       IN /\ IF m.epoch < p            \* J:486, signed long compare
               THEN \* J:487-489 throw new IOException("IPC's epoch E is less than
                    \* the last promised epoch P ..."). The caller's RPC fails.
                    /\ targetFired' = TRUE
                    /\ cache'  = [cache EXCEPT ![j] = p]
                    /\ disk'   = disk
                    /\ hasSeg' = hasSeg
                    /\ rep'    = [rep EXCEPT ![w][j] =
                                    [rnd |-> m.rnd, kind |-> m.kind,
                                     ok |-> FALSE, val |-> -1]]
               ELSE /\ targetFired' = targetFired
                    /\ IF m.epoch > p  \* J:490
                         THEN \* J:493 updateLastPromisedEpoch -> J:371 PLF.set
                              /\ cache' = [cache EXCEPT ![j] = m.epoch]
                              /\ disk'  = [disk  EXCEPT ![j] = m.epoch]
                         ELSE /\ cache' = [cache EXCEPT ![j] = p]
                              /\ disk'  = disk
                    \* Normal continuation of the caller (J:497-511 and the RPC
                    \* body). Post-guard checks are not modeled (brief §3.2).
                    \* journal writes transactions (J:442-471); acceptRecovery
                    \* syncs the recovered segment (J:906-982).
                    /\ hasSeg' = IF m.kind \in {"J", "AR"}
                                   THEN [hasSeg EXCEPT ![j] = TRUE]
                                   ELSE hasSeg
                    \* prepareRecovery reports the segment state (J:840-855).
                    /\ rep' = [rep EXCEPT ![w][j] =
                                 [rnd |-> m.rnd, kind |-> m.kind, ok |-> TRUE,
                                  val |-> IF m.kind = "PR" /\ hasSeg[j]
                                            THEN 1 ELSE 0]]
          /\ chan' = [chan EXCEPT ![w][j] = Tail(@)]
    /\ UNCHANGED <<prev, wVars>>

-----------------------------------------------------------------------------
(* Client-side completion and request loss *)

\* The blocking RPC returns to the executor task; the future completes and the
\* QuorumCall callback records it (QC:78-88, 259-267). A reply for an older
\* QuorumCall, or for a writer that is no longer waiting, is ignored.
RecvReply(w, j) ==
    /\ rep[w][j] # NoReply
    /\ LET r == rep[w][j]
       IN IF wst[w] \in WaitStates /\ r.rnd = wRnd[w]
            THEN /\ wResp' = [wResp EXCEPT ![w][j] = IF r.ok THEN "ok" ELSE "err"]
                 /\ wVal'  = [wVal  EXCEPT ![w][j] = r.val]
            ELSE UNCHANGED <<wResp, wVal>>
    /\ rep' = [rep EXCEPT ![w][j] = NoReply]
    /\ UNCHANGED <<jnVars, chan, wst, wRnd, wCand, wEpoch, wSeg, targetFired>>

\* Fault: the RPC never reaches the JN (connection refused/reset, JN down, IPC
\* failure) and the client records an exception for it. The codebase injects
\* this with futureThrows (TestQuorumJournalManagerUnit.java:130-133), which
\* fails the future without sending anything.
LoseRequest(w, j) ==
    /\ HeadInFlight(w, j)
    /\ LET m == Head(chan[w][j])
       IN IF wst[w] \in WaitStates /\ m.rnd = wRnd[w]
            THEN wResp' = [wResp EXCEPT ![w][j] = "err"]
            ELSE UNCHANGED wResp
    /\ chan' = [chan EXCEPT ![w][j] = Tail(@)]
    /\ UNCHANGED <<jnVars, rep, wst, wRnd, wVal, wCand, wEpoch, wSeg, targetFired>>

-----------------------------------------------------------------------------
(* JournalNode restart and administrative upgrade / rollback (Scenario 2) *)

\* Fault: JN process restart with its storage kept
\* (MiniJournalCluster.java:238-262). The Journal object is dropped; the next RPC
\* creates a new one (JNd:98-125) whose refreshCachedData (J:166, 202-213)
\* builds a fresh, unloaded PersistentLongFile (PLF:46). The disk value is
\* durable (PLF:61-67 writes the file before memory).
\* Requests queued for this JN are delivered to the new process: this is
\* equivalent to them having been sent after the restart (the restart and the
\* writer's fan-out commute); in-flight failures are covered by LoseRequest.
JNRestart(j) ==
    /\ cache' = [cache EXCEPT ![j] = NotLoaded]
    /\ UNCHANGED <<disk, prev, hasSeg, wVars, netVars, targetFired>>

\* Shared-log upgrade by the upgrading NN after it has established its epoch
\* and recovered (FSImage.java:838-858), before its first write:
\* doPreUpgradeOfSharedLog (FSImage.java:489-491) then doUpgradeOfSharedLog
\* (FSImage.java:497-500). QJM.doPreUpgrade / doUpgrade wait for every JN
\* (QJM:669-700), so this writer's queued requests drain first.
\* Per JN: NNU:153-172 current -> previous.tmp (edits hard-linked, NNU:126-146);
\* NNU:183-204 previous.tmp -> previous; J:1149-1166 new PersistentLongFile
\* objects, current := previous value, cache loaded with it.
\* Atomic: the doPreUpgrade-to-doUpgrade window is excluded (brief §3.2).
Upgrade(w) ==
    /\ wst[w] = "ready"
    /\ wSeg[w] = 0
    /\ \A j \in JN : prev[j] = NoPrev                         \* NNU:160-161
    /\ \A j \in JN : chan[w][j] = <<>> /\ rep[w][j] = NoReply  \* QJM:670-673, 687-690
    /\ prev'  = [j \in JN |-> [promise |-> disk[j], seg |-> hasSeg[j]]]
    /\ cache' = [j \in JN |-> disk[j]]                       \* J:1157-1166
    /\ UNCHANGED <<disk, hasSeg, wVars, netVars, targetFired>>

\* `namenode -rollback` with the NNs stopped (FSImage.java:521-565 ->
\* FSEditLog.java:1729-1735 -> QJM:754-769 waits for every JN).
\* JNd:487-491 -> Journal.doRollback (J:1189-1196) -> NNU:213-236:
\* current -> removed.tmp, previous -> current. Only refreshStorage() runs; the
\* cached lastPromisedEpoch is NOT refreshed (CR-1), unlike format (J:251-260).
Rollback ==
    /\ \E j \in JN : prev[j] # NoPrev
    /\ \A w \in Writer : ~Live(w)
    /\ disk'   = [j \in JN |-> IF prev[j] # NoPrev THEN prev[j].promise ELSE disk[j]]
    /\ hasSeg' = [j \in JN |-> IF prev[j] # NoPrev THEN prev[j].seg ELSE hasSeg[j]]
    /\ prev'   = [j \in JN |-> NoPrev]
    /\ UNCHANGED <<cache, wVars, netVars, targetFired>>

-----------------------------------------------------------------------------
(* Specification *)

\* Init = state right after QJM.format in the workload setup
\* (TestQuorumJournalManager.java:127): JNStorage.format clears current/
\* (JNStorage.java:225-231) and J:259 refreshCachedData builds an unloaded PLF
\* with default 0 (J:206-207). No writer has run yet.
Init ==
    /\ cache  = [j \in JN |-> NotLoaded]
    /\ disk   = [j \in JN |-> 0]
    /\ prev   = [j \in JN |-> NoPrev]
    /\ hasSeg = [j \in JN |-> FALSE]
    /\ wst    = [w \in Writer |-> "idle"]
    /\ wRnd   = [w \in Writer |-> 0]
    /\ wResp  = [w \in Writer |-> [j \in JN |-> "none"]]
    /\ wVal   = [w \in Writer |-> [j \in JN |-> -1]]
    /\ wCand  = [w \in Writer |-> NoEpoch]
    /\ wEpoch = [w \in Writer |-> NoEpoch]
    /\ wSeg   = [w \in Writer |-> 0]
    /\ chan   = [w \in Writer |-> [j \in JN |-> <<>>]]
    /\ rep    = [w \in Writer |-> [j \in JN |-> NoReply]]
    /\ targetFired = FALSE

WriterStep(w) ==
    \/ WriterStart(w)
    \/ ChooseEpoch(w)
    \/ Establish(w)
    \/ AcceptRecovery(w)
    \/ RecoveryNoLog(w)
    \/ RecoveryFinalize(w)
    \/ RecoveryDone(w)
    \/ StartLogSegment(w)
    \/ SendEdits(w)
    \/ FinalizeLogSegment(w)
    \/ SegmentFinalized(w)
    \/ QuorumFail(w)
    \/ WriterStop(w)
    \/ Upgrade(w)

ChannelStep(w, j) ==
    \/ HandleGetJournalState(j, w)
    \/ HandleNewEpoch(j, w)
    \/ TargetCheck(j, w)
    \/ RecvReply(w, j)
    \/ LoseRequest(w, j)

\* Once the target fired, every action stops (ad hoc tla-patterns §1).
Next ==
    /\ ~targetFired
    /\ \/ \E w \in Writer : WriterStep(w)
       \/ \E w \in Writer, j \in JN : ChannelStep(w, j)
       \/ \E j \in JN : JNRestart(j)
       \/ Rollback

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties *)

\* The oracle (ad hoc Shared Rule 1): the failing branch J:487-489 never runs.
TargetSafe == ~targetFired

Request == [kind : Kinds, rnd : Nat, epoch : Int]
Reply   == [rnd : Nat, kind : Kinds \cup {"none"}, ok : BOOLEAN, val : Int]
PrevRec == [promise : Int, seg : BOOLEAN]

\* Structural sanity 1: variable domains.
TypeOK ==
    /\ cache  \in [JN -> {NotLoaded} \cup Nat]
    /\ disk   \in [JN -> Nat]
    /\ prev   \in [JN -> PrevRec]
    /\ hasSeg \in [JN -> BOOLEAN]
    /\ wst    \in [Writer -> WStates]
    /\ wRnd   \in [Writer -> Nat]
    /\ wResp  \in [Writer -> [JN -> {"none", "ok", "err"}]]
    /\ wVal   \in [Writer -> [JN -> Int]]
    /\ wCand  \in [Writer -> {NoEpoch} \cup Nat]
    /\ wEpoch \in [Writer -> {NoEpoch} \cup Nat]
    /\ wSeg   \in [Writer -> 0..ReqRounds]
    /\ chan   \in [Writer -> [JN -> Seq(Request)]]
    /\ rep    \in [Writer -> [JN -> Reply]]
    /\ targetFired \in BOOLEAN

\* Structural sanity 2 (brief §5): a request carries only values its sender
\* held. Every RequestInfo request carries the sender's established epoch
\* (> 0, ILC:288), every newEpoch request carries the sender's myEpoch.
ReqCarriesSenderEpoch ==
    \A w \in Writer, j \in JN :
        \A i \in 1..Len(chan[w][j]) :
            LET m == chan[w][j][i] IN
            /\ m.kind \in RIKinds => (m.epoch = wEpoch[w] /\ m.epoch > 0)
            /\ m.kind = "NE" => m.epoch = wCand[w]

=============================================================================
