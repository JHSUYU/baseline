------------------------------- MODULE base -------------------------------
(*
 * Ad hoc coordination target hdfs-adhoc-k6.
 *
 *   FSEditLog.endCurrentLogSegment(boolean)            FSEditLog.java:1406
 *     Preconditions.checkState(isSegmentOpen(),        FSEditLog.java:1409
 *         "Bad state: %s", state);                     -> IllegalStateException
 *   isSegmentOpen() == (state == State.IN_SEGMENT)     FSEditLog.java:363-364
 *
 * phi_T: endCurrentLogSegment is entered while elState # "IN_SEGMENT".
 * Property: TargetSafe == ~targetFired.
 *
 * Category A (brief §1). One NameNode process. Its actors are:
 *   "rpc"    - an RPC handler running FSNamesystem.rollEditLog (rollEditLog /
 *              rollEdits RPC, startCheckpoint, HA rolling upgrade: all of them
 *              take the same writeLock + checkOperation(JOURNAL) + safe-mode
 *              admission, FSNamesystem.java:4728-4745)
 *   "roller" - NameNodeEditLogRoller thread (FSNamesystem.java:4076-4115)
 *   "admin"  - an RPC handler running saveNamespace (FSNamesystem.java:4475-4501)
 *   plus the client edit handlers, the async sync thread (FSEditLogAsync.run),
 *   the NameNode.stop path and the HA transitionToStandby path.
 *
 * Paths are relative to hadoop-hdfs-project/hadoop-hdfs/src/main/java/
 * org/apache/hadoop/hdfs/server/namenode/ at commit c37cda11e9c.
 *
 * Not modeled (brief §3.2): monitor release inside close()/saveNamespace
 * check-then-act (lock-excluded), BackupNode paths, copyEditLogSegmentsToSharedDir,
 * continuing after terminate() with ExitUtil disabled (terminate == halted here),
 * edit content / txid arithmetic / metrics / overflow semaphore.
 *)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Journal,        \* journal managers in the JournalSet (FSEditLog.initJournals :276-305)
    Required,       \* required journals: dfs.namenode.edits.dir.required + shared dirs (FSNamesystem.java:1490-1495)
    MinRedundant,   \* dfs.namenode.edits.dir.minimum (FSEditLog.java:277-279)
    AsyncMode,      \* dfs.namenode.edits.asynclogging -> FSEditLogAsync
    HAEnabled,      \* HA configured (enables TransitionToStandby)
    RollerFires     \* the roller's threshold check can pass (FSNamesystem.java:4092)

ASSUME Journal # {}
ASSUME Required \subseteq Journal
ASSUME MinRedundant \in Nat
ASSUME AsyncMode \in BOOLEAN /\ HAEnabled \in BOOLEAN /\ RollerFires \in BOOLEAN

\* FSEditLog.State, FSEditLog.java:147-153 (names are the enum's name())
EditLogStates == {"UNINITIALIZED", "BETWEEN_LOG_SEGMENTS", "IN_SEGMENT",
                  "OPEN_FOR_READING", "CLOSED"}

RollActor == {"rpc", "roller"}
Actor     == RollActor \cup {"admin"}
NoActor   == "none"

\* pc values of an actor that runs (part of) endCurrentLogSegment + startLogSegment
PCs == {"idle", "waitLock", "atCheck", "endSync", "endFinalize", "starting"}

VARIABLES
    \* --- the guard operand and its stream (S1, S2) ---
    elState,          \* FSEditLog.state
    streamOpen,       \* FSEditLog.editLogStream # null
    \* --- journal set with faults (S1) ---
    jDisk,            \* [Journal -> {"ok","failed"}]: storage health (environment)
    jStream,          \* [Journal -> {"active","closed","disabled"}]:
                      \*   JournalAndStream.stream # null  -> "active"
                      \*   stream = null /\ ~disabled      -> "closed"
                      \*   disabled (abort sets stream=null, JournalSet.java:349-355) -> "disabled"
    halted,           \* ExitUtil.terminate was called: the process is gone
    \* --- FSN lock + admission (S1, S2) ---
    safeMode,         \* FSNamesystem.isInSafeMode()
    haState,          \* NameNode.state: "Active" | "Standby"
    lockHolder,       \* FSN writeLock (saveNamespace's readLock+cpLock is folded in:
                      \*   only writers change modeled state, and all writers are excluded)
    pc,               \* [Actor -> PCs]
    pendingEdits,     \* client edits queued in FSEditLogAsync.editPendingQ, not yet applied
    \* --- lifecycle and roller (S2) ---
    stopPhase,        \* "running" | "exited" | "rpcStopped" | "fsnClosed"
    rollerShouldRun,  \* NameNodeEditLogRoller.shouldRun
    \* --- target ---
    targetFired

elVars    == <<elState, streamOpen>>
jVars     == <<jDisk, jStream>>
fsnVars   == <<safeMode, haState, lockHolder, pc, pendingEdits>>
lifeVars  == <<stopPhase, rollerShouldRun>>
vars      == <<elState, streamOpen, jDisk, jStream, halted, safeMode, haState,
               lockHolder, pc, pendingEdits, stopPhase, rollerShouldRun, targetFired>>

----------------------------------------------------------------------------
(* Helpers *)

\* NameNodeResourcePolicy.areResourcesAvailable, NameNodeResourcePolicy.java:41-78,
\* with JournalAndStream.isResourceAvailable == !disabled (JournalSet.java:163-165).
ResourcesAvailable(js) ==
    LET redundant == Journal \ Required
    IN  IF \E j \in Required : js[j] = "disabled" THEN FALSE          \* :66-69
        ELSE IF redundant = {} THEN Required # {}                     \* :73-76
        ELSE Cardinality({j \in redundant : js[j] # "disabled"})
                 >= MinRedundant                                      \* :77-78

\* FSEditLogAsync.run (FSEditLogAsync.java:225-257) is started by openForWrite (:100-108)
\* and stopped by close (:111-114) and restart. In this model it is alive exactly
\* while the log is open for write.
SyncThreadAlive == elState \in {"IN_SEGMENT", "BETWEEN_LOG_SEGMENTS"}

\* FSEditLog.isOpenForWrite, FSEditLog.java:343-345
IsOpenForWrite == elState \in {"IN_SEGMENT", "BETWEEN_LOG_SEGMENTS"}

\* logSync over the current JournalSetOutputStream: write (buffer only) then
\* setReadyToFlush / flushAndSync through mapJournalsAndReportErrors on every
\* active journal (FSEditLog.java:648-748, JournalSet.java:438-447,496-515).
\*  - a failure on a required journal terminates (JournalSet.java:387-400)
\*  - failed redundant journals are disabled (:401-406, :349-355)
\*  - too few left -> IOException (:408-413) -> logSync terminates
\*    (FSEditLog.java:684-697 setReadyToFlush, :708-723 flush)
SyncBad == {j \in Journal : jStream[j] = "active" /\ jDisk[j] = "failed"}
SyncJS  == [j \in Journal |-> IF j \in SyncBad THEN "disabled" ELSE jStream[j]]
SyncHalts == (SyncBad \cap Required # {}) \/ ~ResourcesAvailable(SyncJS)

DoSync ==
    /\ jStream' = SyncJS
    /\ halted'  = SyncHalts

----------------------------------------------------------------------------
(* Init: the state right after cluster.waitActive() in the workload:
 * FSNamesystem.loadFSImage -> FSImage.openEditLogForWrite (FSNamesystem.java:1122,
 * FSImage.java:626-628) -> FSEditLog.openForWrite (FSEditLog.java:317-338), safe
 * mode left, Active, every journal started. Pre-startup states (UNINITIALIZED) are
 * not modeled: rolls are rejected by checkNNStartup before startup
 * (NameNodeRpcServer.java:2240-2245). *)
Init ==
    /\ elState         = "IN_SEGMENT"
    /\ streamOpen      = TRUE
    /\ jDisk           = [j \in Journal |-> "ok"]
    /\ jStream         = [j \in Journal |-> "active"]
    /\ halted          = FALSE
    /\ safeMode        = FALSE
    /\ haState         = "Active"
    /\ lockHolder      = NoActor
    /\ pc              = [a \in Actor |-> "idle"]
    /\ pendingEdits    = 0
    /\ stopPhase       = "running"
    /\ rollerShouldRun = TRUE
    /\ targetFired     = FALSE

----------------------------------------------------------------------------
(* Roll admission *)

\* RPC rollEditLog / rollEdits: NameNodeRpcServer.java:1303-1307 / :1274-1278.
\* checkNNStartup only checks `started` (:2240-2245). The handler can only start
\* while the RPC server runs: rpcServer.stop is in stopCommonServices
\* (NameNode.java:824), after exitState (:1004). The unlocked
\* checkOperation(JOURNAL) at FSNamesystem.java:4732 rejects Standby
\* (ha/StandbyState.java:79-89); Active allows all (ha/ActiveState.java:40-42).
RpcRollArrive ==
    /\ pc["rpc"] = "idle"
    /\ stopPhase \in {"running", "exited"}
    /\ haState = "Active"                                   \* FSNamesystem.java:4732
    /\ pc' = [pc EXCEPT !["rpc"] = "waitLock"]              \* blocks in writeLock() :4733
    /\ UNCHANGED <<elVars, jVars, halted, safeMode, haState, lockHolder,
                   pendingEdits, lifeVars, targetFired>>

\* NameNodeEditLogRoller.run, FSNamesystem.java:4088-4110: the loop condition
\* fsRunning && shouldRun (:4089), then getCorrectTransactionsSinceLastLogRoll
\* (:4256-4263: 0 if standby or !isSegmentOpen()) > rollThreshold (:4092, the
\* RollerFires abstraction), then rollEditLog() (:4096) -> checkOperation (:4732).
\* None of this holds the FSN lock. The thread then blocks in writeLock(), which
\* ignores interrupts (FSNamesystemLock.java:205-210).
RollerCheck ==
    /\ pc["roller"] = "idle"
    /\ rollerShouldRun                                      \* :4089 shouldRun
    /\ stopPhase # "fsnClosed"                              \* :4089 fsRunning (FSNamesystem.close :1704)
    /\ RollerFires                                          \* :4092 numEdits > rollThreshold
    /\ haState # "Standby" /\ elState = "IN_SEGMENT"        \* :4257-4258
    /\ haState = "Active"                                   \* :4732
    /\ pc' = [pc EXCEPT !["roller"] = "waitLock"]
    /\ UNCHANGED <<elVars, jVars, halted, safeMode, haState, lockHolder,
                   pendingEdits, lifeVars, targetFired>>

\* FSNamesystem.rollEditLog, FSNamesystem.java:4733-4743: writeLock(), then
\* checkOperation(JOURNAL) (:4735) and checkNameNodeSafeMode (:4736) under the lock.
\* On either exception the finally releases the lock (:4741-4743). The edit-log
\* state is never checked here.
RollAcquire(a) ==
    /\ pc[a] = "waitLock"
    /\ lockHolder = NoActor                                 \* :4733 writeLock()
    /\ IF haState = "Active" /\ ~safeMode                   \* :4735, :4736
       THEN /\ lockHolder' = a
            /\ pc' = [pc EXCEPT ![a] = "atCheck"]           \* :4740 -> FSImage.rollEditLog
                                                            \*   (FSImage.java:1321-1322)
                                                            \*   -> FSEditLog.rollEditLog :1314-1316
       ELSE /\ lockHolder' = NoActor                        \* exception; :4741-4743 writeUnlock
            /\ pc' = [pc EXCEPT ![a] = "idle"]
    /\ UNCHANGED <<elVars, jVars, halted, safeMode, haState, pendingEdits,
                   lifeVars, targetFired>>

----------------------------------------------------------------------------
(* The target: FSEditLog.endCurrentLogSegment entry, FSEditLog.java:1406-1410.
 * Reached by FSEditLog.rollEditLog :1316 (no guard) for "rpc"/"roller", and by
 * FSImage.saveNamespace :1108-1109 (guarded by editLogWasOpen, :1106) for "admin".
 * The close() caller (:394-397) is guarded inside one atomic step below. *)
TargetCheck(a) ==
    /\ pc[a] = "atCheck"
    /\ lockHolder = a
    /\ IF elState # "IN_SEGMENT"                            \* :1409 !isSegmentOpen()
       THEN /\ targetFired' = TRUE                          \* IllegalStateException at :1409
            /\ UNCHANGED pc
       ELSE /\ targetFired' = targetFired
            /\ pc' = [pc EXCEPT ![a] = "endSync"]
    /\ UNCHANGED <<elVars, jVars, halted, safeMode, haState, lockHolder,
                   pendingEdits, lifeVars>>

\* endCurrentLogSegment :1412-1417: logEdit(OP_END_LOG_SEGMENT) then logSyncAll().
\* Async: logEdit enqueues (FSEditLogAsync.java:117-121) behind any queued client
\* edits, and logSyncAll (:137-147) waits until the sync thread drained the queue,
\* so pendingEdits must be 0 first (SyncThreadRun steps run meanwhile, the FSN lock
\* is still held). Then the sync over the journals (DoSync).
EndSegmentSync(a) ==
    /\ pc[a] = "endSync"
    /\ lockHolder = a
    /\ AsyncMode => pendingEdits = 0                        \* FSEditLogAsync.java:137-147
    /\ DoSync                                               \* FSEditLog.java:648-748
    /\ pc' = [pc EXCEPT ![a] = "endFinalize"]
    /\ UNCHANGED <<elVars, jDisk, safeMode, haState, lockHolder, pendingEdits,
                   lifeVars, targetFired>>

\* endCurrentLogSegment :1426-1433. journalSet.finalizeLogSegment
\* (JournalSet.java:217-230): for each active journal closeStream (:223) and
\* FileJournalManager.finalizeLogSegment (:224; a rename failure throws
\* IllegalStateException, FileJournalManager.java:150-155, caught as Throwable at
\* JournalSet.java:384). Failures disable the journal; a required failure
\* terminates (:387-400); too few left -> IOException (:408-413), swallowed at
\* FSEditLog.java:1429-1431 so editLogStream stays non-null. state is set to
\* BETWEEN_LOG_SEGMENTS either way (:1433).
EndSegmentFinalize(a) ==
    /\ pc[a] = "endFinalize"
    /\ lockHolder = a
    /\ LET act == {j \in Journal : jStream[j] = "active"}
           bad == {j \in act : jDisk[j] = "failed"}
           js  == [j \in Journal |-> IF j \in bad THEN "disabled"
                                     ELSE IF j \in act THEN "closed"
                                     ELSE jStream[j]]
       IN  IF bad \cap Required # {}
           THEN /\ halted' = TRUE                           \* JournalSet.java:400
                /\ jStream' = js
                /\ UNCHANGED <<elVars, pc>>
           ELSE /\ halted' = FALSE
                /\ jStream' = js
                /\ streamOpen' = IF ResourcesAvailable(js)
                                 THEN FALSE                 \* FSEditLog.java:1428
                                 ELSE streamOpen            \* :1429-1431
                /\ elState' = "BETWEEN_LOG_SEGMENTS"        \* :1433
                /\ pc' = [pc EXCEPT ![a] = "starting"]
    /\ UNCHANGED <<jDisk, safeMode, haState, lockHolder, pendingEdits,
                   lifeVars, targetFired>>

\* FSEditLog.startLogSegmentAndWriteHeaderTxn :1393-1400 -> startLogSegment
\* :1356-1391. Called by rollEditLog :1319 ("rpc"/"roller") and by the finally of
\* FSImage.saveNamespace :1123-1125 ("admin"). The FSN lock is released afterwards
\* in either case (FSNamesystem.java:4741-4743 / :4493-4496).
\*  - attemptRestoreRemovedStorage (:1380) has no effect on journals (restore off).
\*  - journalSet.startLogSegment (:1383, JournalSet.java:205-216) applies
\*    JournalAndStream.startLogSegment to EVERY journal (:91-95): checkState(stream
\*    == null) (:93), disabled = false (:94), FileJournalManager.startLogSegment
\*    (FileJournalManager.java:120-134) fails on a failed disk.
\*  - required failure -> terminate (JournalSet.java:387-400); failed redundant
\*    journals are disabled; too few -> IOException (:408-413) rethrown at
\*    FSEditLog.java:1384-1387 BEFORE state = IN_SEGMENT (:1390) and before
\*    editLogStream is assigned (:1383): the log stays BETWEEN_LOG_SEGMENTS.
\*  - on success the header op is logged and synced (:1397-1399) on the
\*    journals that just started; that sync is folded into this step (a disk
\*    failure in between can only terminate, which cannot reach the target).
StartSegment(a) ==
    /\ pc[a] = "starting"
    /\ lockHolder = a
    /\ LET bad == {j \in Journal : jDisk[j] = "failed" \/ jStream[j] = "active"}
           js  == [j \in Journal |-> IF j \in bad THEN "disabled" ELSE "active"]
       IN  IF bad \cap Required # {}
           THEN /\ halted' = TRUE                           \* JournalSet.java:400
                /\ jStream' = js
                /\ UNCHANGED <<elVars, pc, lockHolder>>
           ELSE /\ halted' = FALSE
                /\ jStream' = js
                /\ IF ResourcesAvailable(js)
                   THEN /\ elState' = "IN_SEGMENT"           \* FSEditLog.java:1390
                        /\ streamOpen' = TRUE                \* :1383
                   ELSE UNCHANGED elVars                     \* :1384-1387 IOException
                /\ lockHolder' = NoActor
                /\ pc' = [pc EXCEPT ![a] = "idle"]
    /\ UNCHANGED <<jDisk, safeMode, haState, pendingEdits, lifeVars, targetFired>>

----------------------------------------------------------------------------
(* Client edits and the async sync thread (S1: competing outcome) *)

\* A namespace mutation (mkdirs/delete in the workload): checkOperation(WRITE) and
\* the safe-mode check under writeLock, then FSEditLog.logEdit, then writeUnlock;
\* logSync runs after the unlock. No edit-log state check.
\* Async: FSEditLogAsync.logEdit (:117-121) -> enqueueEdit (:180-217): queued only.
\* Sync:  FSEditLog.logEdit (:454-474) -> doEditTransaction (:476-487): with
\*        editLogStream == null the write at :481 throws NullPointerException back to
\*        the RPC handler, and the NN survives (no sync runs); otherwise the edit is
\*        written and logSync (:648-748) syncs it.
\* In CLOSED the sync thread is stopped and the edit cannot touch modeled state, so
\* that case is not modeled.
ClientEdit ==
    /\ lockHolder = NoActor
    /\ stopPhase \in {"running", "exited"}
    /\ haState = "Active" /\ ~safeMode
    /\ IsOpenForWrite
    /\ IF AsyncMode
       THEN /\ pendingEdits' = pendingEdits + 1             \* FSEditLogAsync.java:188
            /\ UNCHANGED <<jStream, halted>>
       ELSE /\ pendingEdits' = pendingEdits
            /\ IF streamOpen
               THEN DoSync                                  \* FSEditLog.java:481, :648-748
               ELSE UNCHANGED <<jStream, halted>>           \* NPE at :481, handler error
    /\ UNCHANGED <<elVars, jDisk, safeMode, haState, lockHolder, pc, lifeVars,
                   targetFired>>

\* FSEditLogAsync.run, FSEditLogAsync.java:225-257: dequeue an edit,
\* edit.logEdit() -> doEditTransaction (:232, FSEditLog.java:476-487), then
\* logSync(getLastWrittenTxId()) (:243). With editLogStream == null the write throws
\* NullPointerException outside the inner try (:240-245), so the outer
\* catch (Throwable) calls terminate (:254-255). Runs without the FSN lock.
SyncThreadRun ==
    /\ AsyncMode
    /\ SyncThreadAlive
    /\ pendingEdits > 0
    /\ pendingEdits' = pendingEdits - 1
    /\ IF ~streamOpen
       THEN /\ halted' = TRUE                               \* NPE -> :254-255 terminate
            /\ UNCHANGED jStream
       ELSE DoSync
    /\ UNCHANGED <<elVars, jDisk, safeMode, haState, lockHolder, pc, lifeVars,
                   targetFired>>

----------------------------------------------------------------------------
(* Journal faults (S1) *)

\* A storage I/O fault on journal j's directory (any subsequent create / flush /
\* rename there fails).
JournalFault(j) ==
    /\ jDisk[j] = "ok"
    /\ jDisk' = [jDisk EXCEPT ![j] = "failed"]
    /\ UNCHANGED <<elVars, jStream, halted, fsnVars, lifeVars, targetFired>>

\* The fault clears (disk replaced / transient error gone).
JournalRepair(j) ==
    /\ jDisk[j] = "failed"
    /\ jDisk' = [jDisk EXCEPT ![j] = "ok"]
    /\ UNCHANGED <<elVars, jStream, halted, fsnVars, lifeVars, targetFired>>

----------------------------------------------------------------------------
(* Safe mode and saveNamespace (S1: interposition and second entry) *)

\* FSNamesystem.enterSafeMode, FSNamesystem.java:4655-4677 (dfsadmin -safemode
\* enter, or the resource monitor with resourcesLow). If isOpenForWrite (:4665),
\* logSyncAll (:4669) drains the async queue first.
\* (Sync mode: logSyncAll with editLogStream == null and unsynced txids would NPE;
\* that sync-mode corner is not modeled.)
EnterSafeMode ==
    /\ lockHolder = NoActor
    /\ ~safeMode
    /\ (AsyncMode /\ IsOpenForWrite) => pendingEdits = 0     \* :4668-4670
    /\ safeMode' = TRUE                                      \* :4671
    /\ UNCHANGED <<elVars, jVars, halted, haState, lockHolder, pc, pendingEdits,
                   lifeVars, targetFired>>

\* FSNamesystem.leaveSafeMode, FSNamesystem.java:4683-4697 (the branch where
\* blockManager.leaveSafeMode refuses changes nothing).
LeaveSafeMode ==
    /\ lockHolder = NoActor
    /\ safeMode
    /\ safeMode' = FALSE                                     \* :4691
    /\ UNCHANGED <<elVars, jVars, halted, haState, lockHolder, pc, pendingEdits,
                   lifeVars, targetFired>>

\* FSNamesystem.saveNamespace, FSNamesystem.java:4475-4501: cpLock + readLock
\* (:4483-4484), checkOperation(UNCHECKED), safe mode required (:4488-4491), then
\* FSImage.saveNamespace (FSImage.java:1099-1135): editLogWasOpen = isSegmentOpen()
\* (:1106); if open, endCurrentLogSegment(true) (:1108-1109), save, and in the
\* finally startLogSegmentAndWriteHeaderTxn (:1123-1125).
\* With !editLogWasOpen the method does not touch the edit log, so that branch is
\* not modeled. The save itself (saveFSImageInAllDirs) does not change modeled
\* state; its success or failure both reach the finally.
SaveNamespaceBegin ==
    /\ pc["admin"] = "idle"
    /\ lockHolder = NoActor
    /\ stopPhase \in {"running", "exited"}
    /\ safeMode                                              \* FSNamesystem.java:4488
    /\ elState = "IN_SEGMENT"                                \* FSImage.java:1106
    /\ lockHolder' = "admin"
    /\ pc' = [pc EXCEPT !["admin"] = "atCheck"]              \* FSImage.java:1108
    /\ UNCHANGED <<elVars, jVars, halted, safeMode, haState, pendingEdits,
                   lifeVars, targetFired>>

----------------------------------------------------------------------------
(* Lifecycle (S2) *)

\* The FSEditLog(Async).close effect, FSEditLog.java:387-411 + FSEditLogAsync.java:
\* 111-114: if IN_SEGMENT, waitForSyncToFinish + endCurrentLogSegment(true) (guarded
\* at :394; the sync and finalize happen under the same FSN writeLock and monitor
\* and their outcome only decides halt vs CLOSED), journalSet.close, state = CLOSED
\* (:409), stopSyncThread.
\* Requires the async queue to be drained when ending a segment (logSyncAll).
CloseEffect(final) ==
    IF elState = "CLOSED"
    THEN /\ elState' = final                                 \* :388-391 (no-op close)
         /\ UNCHANGED <<streamOpen, jStream, halted>>
    ELSE IF elState = "IN_SEGMENT"
    THEN LET act == {j \in Journal : jStream[j] = "active"}
             bad == {j \in act : jDisk[j] = "failed"}
             js  == [j \in Journal |-> IF j \in bad THEN "disabled"
                                       ELSE IF j \in act THEN "closed"
                                       ELSE jStream[j]]
         IN  /\ halted' = SyncHalts                           \* :1417 logSyncAll
             /\ jStream' = js                                 \* :1427 finalize
             /\ streamOpen' = IF ResourcesAvailable(js) THEN FALSE ELSE streamOpen
             /\ elState' = final                              \* :409
    ELSE /\ elState' = final                                 \* :409
         /\ UNCHANGED <<streamOpen, jStream, halted>>

CloseReady == (AsyncMode /\ elState = "IN_SEGMENT") => pendingEdits = 0

\* NameNode.stop, NameNode.java:996-1027: stopRequested, then state.exitState
\* (:1004). For Active: ActiveState.exitState (ha/ActiveState.java:68-74) ->
\* FSNamesystem.stopActiveServices (FSNamesystem.java:1330-1381) under writeLock:
\* roller.stop() + interrupt (:1346-1349) WITHOUT join, editLog.close() (:1355-1357).
\* For Standby: StandbyState.exitState -> stopStandbyServices (FSNamesystem.java:
\* 1429-1440) -> editLog.close() (:1438).
\* stop() never changes NameNode.state (haState): the HA state stays Active.
StopExitState ==
    /\ stopPhase = "running"
    /\ lockHolder = NoActor
    /\ CloseReady
    /\ CloseEffect("CLOSED")
    /\ rollerShouldRun' = IF haState = "Active" THEN FALSE ELSE rollerShouldRun
    /\ stopPhase' = "exited"
    /\ UNCHANGED <<jDisk, safeMode, haState, lockHolder, pc, pendingEdits,
                   targetFired>>

\* NameNode.stop finally -> stopCommonServices (NameNode.java:1010) -> rpcServer.stop
\* (:824). New RPC rolls can no longer start; handlers already past
\* checkNNStartup keep running.
StopRpc ==
    /\ stopPhase = "exited"
    /\ stopPhase' = "rpcStopped"
    /\ UNCHANGED <<elVars, jVars, halted, fsnVars, rollerShouldRun, targetFired>>

\* NameNode.java:825 namesystem.close -> FSNamesystem.close (FSNamesystem.java:
\* 1703-1718): fsRunning = false (:1704), stopActiveServices again (writeLock;
\* editLog.close is a no-op on CLOSED, FSEditLog.java:388-391).
FsnClose ==
    /\ stopPhase = "rpcStopped"
    /\ lockHolder = NoActor
    /\ CloseReady
    /\ CloseEffect("CLOSED")
    /\ rollerShouldRun' = FALSE
    /\ stopPhase' = "fsnClosed"
    /\ UNCHANGED <<jDisk, safeMode, haState, lockHolder, pc, pendingEdits,
                   targetFired>>

\* Guarded counterpart: HAState.setStateInternal (ha/HAState.java:56-68) under ONE
\* writeLock hold: ActiveState.exitState -> stopActiveServices (roller stop, close),
\* context.setState(Standby), StandbyState.enterState -> startStandbyServices ->
\* initSharedJournalsForRead (FSNamesystem.java:1386-1391, FSEditLog.java:263-274:
\* state = OPEN_FOR_READING).
TransitionToStandby ==
    /\ HAEnabled
    /\ haState = "Active"
    /\ stopPhase = "running"
    /\ lockHolder = NoActor
    /\ CloseReady
    \* close() leaves CLOSED (FSEditLog.java:409); then initSharedJournalsForRead
    \* (:263-274) sets OPEN_FOR_READING. If the close terminated, halted stops
    \* everything and the final elState is irrelevant.
    /\ CloseEffect("OPEN_FOR_READING")
    /\ haState' = "Standby"
    /\ rollerShouldRun' = FALSE
    /\ UNCHANGED <<jDisk, safeMode, lockHolder, pc, pendingEdits, stopPhase,
                   targetFired>>

----------------------------------------------------------------------------

Next ==
    /\ ~targetFired                 \* stop once the target fired (tla-patterns §1)
    /\ ~halted                      \* terminate(): the process is gone
    /\ \/ RpcRollArrive
       \/ RollerCheck
       \/ \E a \in RollActor : RollAcquire(a)
       \/ \E a \in Actor : TargetCheck(a)
       \/ \E a \in Actor : EndSegmentSync(a)
       \/ \E a \in Actor : EndSegmentFinalize(a)
       \/ \E a \in Actor : StartSegment(a)
       \/ ClientEdit
       \/ SyncThreadRun
       \/ \E j \in Journal : JournalFault(j)
       \/ \E j \in Journal : JournalRepair(j)
       \/ EnterSafeMode
       \/ LeaveSafeMode
       \/ SaveNamespaceBegin
       \/ StopExitState
       \/ StopRpc
       \/ FsnClose
       \/ TransitionToStandby

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
(* Invariants *)

TypeOK ==
    /\ elState \in EditLogStates
    /\ streamOpen \in BOOLEAN
    /\ jDisk \in [Journal -> {"ok", "failed"}]
    /\ jStream \in [Journal -> {"active", "closed", "disabled"}]
    /\ halted \in BOOLEAN
    /\ safeMode \in BOOLEAN
    /\ haState \in {"Active", "Standby"}
    /\ lockHolder \in Actor \cup {NoActor}
    /\ pc \in [Actor -> PCs]
    /\ pendingEdits \in Nat
    /\ stopPhase \in {"running", "exited", "rpcStopped", "fsnClosed"}
    /\ rollerShouldRun \in BOOLEAN
    /\ targetFired \in BOOLEAN

\* The target property.
TargetSafe == ~targetFired

\* Sanity 1 (brief §5): IN_SEGMENT is set only after the stream was assigned
\* (FSEditLog.java:1383-1390).
SegmentHasStream == elState = "IN_SEGMENT" => streamOpen

\* Sanity 2 (brief §5): a Standby NameNode never has the log open for write.
StandbyNotWriting ==
    haState = "Standby" => elState \in {"OPEN_FOR_READING", "CLOSED"}

\* Lock sanity: an actor past RollAcquire / SaveNamespaceBegin holds the FSN lock.
LockConsistent ==
    \A a \in Actor : pc[a] \in {"atCheck", "endSync", "endFinalize", "starting"}
                        <=> lockHolder = a

\* Temporary reachability probe (tla-patterns §2): TLC must VIOLATE this.
TargetReached == ~(\E a \in Actor : pc[a] = "atCheck")

=============================================================================
