-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hbase-adhoc-04: one ad hoc coordination check.                           *)
(*                                                                          *)
(* Target: AbstractStateMachineTableProcedure.preflightChecks(env, enabled) *)
(*   throws TableNotEnabledException at                                     *)
(*   AbstractStateMachineTableProcedure.java:163 when                       *)
(*     enabled && !ts.isEnabledOrEnabling()                (L161-162)       *)
(*     ts = master.getTableStateManager().getTableState(tn) (L158-160)      *)
(* Property: TargetSafe == ~targetFired.                                    *)
(*                                                                          *)
(* Workload: TestAdhocWorkload04#run (hbase-server). The guard is reached   *)
(*   at two sites, both with enabled = TRUE:                                *)
(*     Site D: DisableTableProcedure's constructor, in the disable RPC      *)
(*             handler, with no table lock (test L74);                      *)
(*     Site F: FlushTableProcedure FLUSH_TABLE_PREPARE, under the table     *)
(*             shared lock (test L97).                                      *)
(*                                                                          *)
(* Source: Apache HBase pinned at 1790942bb2. File names are class files    *)
(*   under hbase-server/src/main/java/org/apache/hadoop/hbase/,             *)
(*   hbase-procedure/src/main/java/org/apache/hadoop/hbase/procedure2/ and  *)
(*   hbase-client/src/main/java/org/apache/hadoop/hbase/. "test Lnn" is     *)
(*   hbase-server/src/test/java/org/apache/hadoop/hbase/quotas/             *)
(*   TestAdhocWorkload04.java.                                              *)
(*                                                                          *)
(* Category A (brief §1). Actors: the test thread with two clients (the    *)
(*   default Admin, and the quota observer whose connection makes one       *)
(*   attempt per call); the master (RPC handlers, procedure executor with   *)
(*   the MasterProcedureScheduler table lock, TableStateManager); hbase:quota*)
(*   on the RegionServer. Faults (brief §7): an observer RPC that fails     *)
(*   without effect (S1), an observer enable that fails but takes effect    *)
(*   (S2), and a master crash with failover (S3).                           *)
(*                                                                          *)
(* Scope (brief §3.2): children of D/E/F (region close/assign/flush) are    *)
(*   not modeled -- they neither write T's state nor call preflightChecks;  *)
(*   the namespace lock, the run-queue bookkeeping and the table enqueue    *)
(*   gate are not modeled, with the reasons given where they apply.         *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANT Workers        \* ProcedureExecutor worker threads (brief §4: 2 in MC)

-----------------------------------------------------------------------------
(* Value sets                                                               *)
-----------------------------------------------------------------------------

\* TableState.State: ENABLED, DISABLED, DISABLING, ENABLING (TableState.java:37-41)
TableStates == {"ENABLED", "DISABLED", "DISABLING", "ENABLING"}

\* The root procedures on table T that the workload creates. At most one of each
\* exists in any execution (argued at TestDisableTable, ObsEnableTable, TestFlushTable).
\*   "D" DisableTableProcedure (test L74)
\*   "E" EnableTableProcedure  (observer, QuotaObserverChore.java:333)
\*   "F" FlushTableProcedure   (test L97)
ProcIds == {"D", "E", "F"}
NoProc  == "none"

\* Procedure status. "NONE" = not in the procedure store. RUNNABLE/WAITING/SUCCESS/
\* FAILED are ProcedureState values; FAILED covers the rolled-back end state.
ProcStatus == {"NONE", "RUNNABLE", "WAITING", "SUCCESS", "FAILED"}

\* The next state-machine state to execute, at lock-hold boundaries only. It is
\* persisted after every executed step (ProcedureExecutor.java:1893-1912).
\*   D: PREPARE -(hold 1)-> ADD_REPLICATION_BARRIER -(hold 2)-> DONE
\*   E: PREPARE -(hold 1)-> SET_ENABLED             -(hold 2)-> DONE
\*   F: PREPARE -(same hold)-> FLUSH_REGIONS -> EOF -(final execution)-> DONE
ProcSteps == {"PREPARE", "ADD_REPLICATION_BARRIER", "SET_ENABLED",
              "FLUSH_REGIONS", "EOF", "DONE"}

\* DISABLE and ENABLE take the table exclusive lock (TableQueue.java:50-58);
\* FLUSH takes the shared lock (TableQueue.java:62-64).
NeedsXLock(p) == p \in {"D", "E"}

TestPcs == {"Disable", "DisableWait", "ObsSetup", "ObsCompare", "ObsPut",
            "ObsMemUpdate", "ObsEnable", "ObsEnableWait", "ObsRunEnd",
            "Flush", "FlushWait", "Done"}

\* Observer snapshots of T: "VIOL" = (DISABLE violation, 2048, 1024) seeded at
\* test L85-86; "OBS" = observance (notInViolation, 2048, 4096) test L87-88;
\* "NONE" = no map entry, read as NO_QUOTA (QuotaObserverChore.java:538-545).
Snapshots == {"NONE", "VIOL", "OBS"}

\* hbase:quota u:p row of T. Only ObsPut writes it, with "OBS". "VIOL_DISABLE"
\* is the value the enable quota gate rejects (HMaster.java:2850-2858); nothing in
\* this workload writes it.
QuotaRows == {"ABSENT", "OBS", "VIOL_DISABLE"}

MasterStates == {"ACTIVE", "DOWN", "INIT"}

\* Server side of the test's disable call:
\*   queued    -- request waiting for (or being retried against) an active master
\*   ctorOk    -- handler passed the DisableTableProcedure constructor, not submitted
\*   submitted -- D is in the procedure store; the client waits for its result
DCalls == {"none", "queued", "ctorOk", "submitted"}
\* Server side of the observer's enable call:
\*   queued    -- request sent, not dequeued by a handler
\*   running   -- handler dequeued it, passed checkInitialized and the nonce
\*   submitted -- E is in the procedure store; the handler has returned
ECalls == {"none", "queued", "running", "submitted"}
\* Client side of the observer's enable call:
\*   awaitSubmit -- waiting for the submit RPC's response (one attempt)
\*   broken      -- the master died while that RPC was outstanding
\*   awaitResult -- has E's procId, polling getProcedureResult
EClients == {"none", "awaitSubmit", "broken", "awaitResult"}
FCalls == {"none", "queued", "submitted"}

ProcRec      == [st : ProcStatus, step : ProcSteps, locked : BOOLEAN]
NoProcRec    == [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]
NewProcRec   == [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> FALSE]
\* wk[w].pc: "idle" = in the poll loop; "polled" = holds a procedure whose lock it
\* has not taken yet (between ProcedureExecutor.java:2181 and :1500);
\* "running" = inside execProcedure with the lock held.
WorkerStates == [pc : {"idle", "polled", "running"}, p : ProcIds \cup {NoProc}]
Idle         == [pc |-> "idle", p |-> NoProc]

-----------------------------------------------------------------------------
(* Variables                                                                *)
-----------------------------------------------------------------------------

VARIABLES
    \* --- guard operand (brief §3.1): TableStateManager's write-through cache
    \*     over T's hbase:meta row (TableStateManager.java:67-75, :134-182) ---
    tState,
    \* --- the target ---
    targetFired,   \* the throw at AbstractStateMachineTableProcedure.java:163 ran
    firedSite,     \* "D" or "F": which caller took it
    \* --- test thread (TestAdhocWorkload04.run) and the observer it drives (S1) ---
    testPc,        \* position in run()
    run,           \* loop counter of test L89
    obsMem,        \* the observer's in-memory snapshot of T (QuotaObserverChore.java:88)
    obsCur,        \* currentSnapshot argument of the running updateTableQuota call
    quotaRow,      \* hbase:quota u:p row of T
    \* --- client calls (S1, S2, S3) ---
    dcall, ecall, eclient, fcall,
    \* --- procedures (S2, S3) ---
    proc,          \* [ProcIds -> ProcRec]; `locked` is the persisted Procedure.locked
    \* --- MasterProcedureScheduler state for table T (S2) ---
    rq,            \* T's TableQueue: runnable procedures in queue order
    lockWait,      \* procedures parked on T's table lock (LockAndQueue queue)
    xlock,         \* exclusive lock owner, or NoProc
    slock,         \* shared lock holders
    wk,            \* [Workers -> WorkerStates]
    \* --- master process (S3) ---
    master

targetVars == <<targetFired, firedSite>>
testVars   == <<testPc, run, obsMem, obsCur, quotaRow>>
callVars   == <<dcall, ecall, eclient, fcall>>
schedVars  == <<rq, lockWait, xlock, slock, wk>>
vars == <<tState, targetVars, testVars, callVars, proc, schedVars, master>>

-----------------------------------------------------------------------------
(* Helpers                                                                  *)
-----------------------------------------------------------------------------

Exists(p)   == proc[p].st /= "NONE"
Finished(p) == proc[p].st \in {"SUCCESS", "FAILED"}

\* LockAndQueue.hasLockAccess (LockAndQueue.java:70-95). D, E and F are root
\* procedures, so only the owner test at L74-77 applies.
HasLockAccess(p) == xlock = p

\* MasterProcedureScheduler.isLockReady (MasterProcedureScheduler.java:231-241)
IsLockReady(p) ==
    \/ HasLockAccess(p)                            \* L234-236
    \/ /\ NeedsXLock(p)                            \* L237, L240: xlock needs !s.isLocked()
       /\ xlock = NoProc
       /\ slock = {}
    \/ /\ ~NeedsXLock(p)                           \* L240: shared needs !s.hasExclusiveLock()
       /\ xlock = NoProc

\* LockAndQueue.wakeWaitingProcedures (LockAndQueue.java:172-179): every parked
\* procedure goes to the FRONT of T's queue, the first-parked one first
\* (scheduler.addFront(descendingIterator), AbstractProcedureScheduler.java:93-104).
WakeAll ==
    /\ rq' = lockWait \o rq
    /\ lockWait' = <<>>

\* AbstractStateMachineTableProcedure.releaseLock (:101-104) ->
\* MasterProcedureScheduler.wakeTableExclusiveLock (:698-716).
ReleaseXLock ==
    /\ xlock' = NoProc                             \* LockAndQueue.java:148
    /\ IF slock = {}                               \* releaseExclusiveLock returns
         THEN WakeAll                              \*   sharedLock == 0 (L157); L704-706
         ELSE UNCHANGED <<rq, lockWait>>

\* FlushTableProcedure.releaseLock (FlushTableProcedure.java:83-86) ->
\* MasterProcedureScheduler.wakeTableSharedLock (:756-774).
ReleaseSLock(p) ==
    /\ slock' = slock \ {p}                        \* LockAndQueue.java:128
    /\ IF slock \ {p} = {} /\ xlock = NoProc       \* --sharedLock == 0 && !hasExclusiveLock()
         THEN WakeAll                              \* L762-766
         ELSE UNCHANGED <<rq, lockWait>>

\* A lock that the next master restores at load (Procedure.restoreLock,
\* Procedure.java:991-1016): held when the old master died (persisted at
\* Procedure.java:1042, cleared at :1059), procedure not finished, not WAITING
\* (L1008-1012).
Restorable(p) == proc[p].st = "RUNNABLE" /\ proc[p].locked

\* Procedure.wasExecuted (Procedure.java:904): set once a step was executed.
Executed(p) == proc[p].step /= "PREPARE"

\* procIds are reserved by registerNonce when a handler starts
\* (ProcedureExecutor.java:874-888). D's handler runs before the observer exists, and
\* an enable handler normally starts before the test sends the flush. So D < E < F.
\* Exception: an enable that failed at the client with late effect (S2) can start its
\* handler after F was submitted, so F < E, and only a later crash (S3) would show that
\* order, at load. The model keeps E before F there. That needs both faults, and each
\* MC_hunt_*.cfg sets one counter, so no hunt reaches it (base.cfg does, with no TargetSafe).
ProcIdOrder == <<"D", "E", "F">>

\* ProcedureExecutor.pushProceduresAfterLoad (ProcedureExecutor.java:496-527):
\* executed procedures first, then by procId (L506-520), each added at the back.
LoadOrder ==
    SelectSeq(ProcIdOrder, LAMBDA p : proc[p].st = "RUNNABLE" /\ Executed(p))
    \o SelectSeq(ProcIdOrder, LAMBDA p : proc[p].st = "RUNNABLE" /\ ~Executed(p))

-----------------------------------------------------------------------------
(* The target                                                               *)
(* AbstractStateMachineTableProcedure.preflightChecks(env, enabled = TRUE)  *)
(* (AbstractStateMachineTableProcedure.java:142-176):                       *)
(*   L144-150 isClusterUp / isStopping / isStopped: pass on an active       *)
(*            master (they throw HBaseIOException, not the target).         *)
(*   L151-154 enabled != null.                                              *)
(*   L157     checkTableModifiable (L122-127): T's descriptor exists.       *)
(*   L158-160 ts = getTableState(tn) = tState (TableStateManager.java:      *)
(*            134-147: cache entry, else the meta row).                     *)
(*   L161-163 if (enabled) if (!ts.isEnabledOrEnabling()) throw.            *)
(*            isEnabledOrEnabling = state in {ENABLED, ENABLING}            *)
(*            (TableState.java:107-110).                                    *)
-----------------------------------------------------------------------------

PreflightFails == tState \notin {"ENABLED", "ENABLING"}      \* phi_T

-----------------------------------------------------------------------------
(* Disable phase (test L74)                                                 *)
-----------------------------------------------------------------------------

\* test L74 admin.disableTable(table) -> Admin.java:396-398 ->
\* RawAsyncHBaseAdmin.disableTable (RawAsyncHBaseAdmin.java:815-820; the request,
\* and so its nonce, is built once and reused by every retry) -> procedureCall
\* (:565-576). The default Admin retries the submit RPC; dcall stays "queued" until
\* an active master handles it. Only this call creates D, so at most one D exists.
TestDisableTable ==
    /\ testPc = "Disable"
    /\ testPc' = "DisableWait"
    /\ dcall' = "queued"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow,
                   ecall, eclient, fcall, proc, schedVars, master>>

\* HMaster.disableTable (HMaster.java:2890-2923) for a retried request whose nonce
\* is known: L2892 checkInitialized (:3424-3433); MasterProcedureUtil.submitProcedure
\* (MasterProcedureUtil.java:132-135) -> registerNonce (ProcedureExecutor.java:874-904)
\* returns D's procId. The nonce was registered when D was submitted (L1134) and is
\* restored with D at load (L573-575). run(), and so the constructor, is skipped.
HMasterDisableTableDedup ==
    /\ dcall = "queued"
    /\ master = "ACTIVE"
    /\ Exists("D")
    /\ dcall' = "submitted"
    /\ UNCHANGED <<tState, targetVars, testVars, ecall, eclient, fcall,
                   proc, schedVars, master>>

\* Site D path. HMaster.disableTable with a fresh nonce: L2892 checkInitialized;
\* L2894-2897 registerNonce -> -1; L2898 preDisableTable (no coprocessor in the test);
\* L2910 blocking latch; L2911 new DisableTableProcedure(...) ->
\* DisableTableProcedure.java:73-80, L78 preflightChecks(env, true).
\* No table lock is held: D is not submitted yet.
SiteDPath ==
    /\ dcall = "queued"
    /\ master = "ACTIVE"
    /\ ~Exists("D")

\* TargetCheck at Site D.
DisableTableProcedureCtor ==
    /\ SiteDPath
    /\ IF PreflightFails
         THEN \* L163 throw new TableNotEnabledException(tn). run() throws;
              \* MasterProcedureUtil.java:138-141 records the failure for the nonce and
              \* rethrows; the test's disable fails.
              /\ targetFired' = TRUE
              /\ firedSite' = "D"
              /\ UNCHANGED dcall
         ELSE \* the constructor returns (DisableTableProcedure.java:79-80)
              /\ UNCHANGED targetVars
              /\ dcall' = "ctorOk"
    /\ UNCHANGED <<tState, testVars, ecall, eclient, fcall, proc, schedVars, master>>

\* HMaster.java:2911-2912 submitProcedure(D) -> MasterProcedureUtil.java:110-114 ->
\* ProcedureExecutor.submitProcedure (:1119-1143): L1134-1135 nonce and reserved
\* procId; L1138 store.insert (D is durable from here); L1142 pushProcedure -> L1197
\* scheduler.addBack(D) -> MasterProcedureScheduler.enqueue (:145-160): D is exclusive
\* and is the only enqueued exclusive procedure of T, so the waiting gate admits it
\* (TableProcedureWaitingQueue.java:66-71) -> doAdd (:178-199) appends it to T's queue.
\* The handler then blocks on the latch (HMaster.java:2913) until D's PREPARE
\* releases it (DisableTableProcedure.java:260). Retries and result polling end the
\* same way (the client waits for D), so that wait is not a separate state.
HMasterDisableSubmit ==
    /\ dcall = "ctorOk"
    /\ master = "ACTIVE"
    /\ proc' = [proc EXCEPT !["D"] = NewProcRec]
    /\ rq' = Append(rq, "D")
    /\ dcall' = "submitted"
    /\ UNCHANGED <<tState, targetVars, testVars, ecall, eclient, fcall,
                   lockWait, xlock, slock, wk, master>>

\* The client polls getProcedureResult (RawAsyncHBaseAdmin.java:3118-3169;
\* MasterRpcServices.java:1381-1414, which needs an initialized master at L1385)
\* until D is FINISHED, then Admin.disableTable returns or throws.
TestDisableDone ==
    /\ testPc = "DisableWait"
    /\ dcall = "submitted"
    /\ master = "ACTIVE"
    /\ Finished("D")
    /\ dcall' = "none"
    /\ testPc' = IF proc["D"].st = "SUCCESS"
                   THEN "ObsSetup"     \* test continues at L76
                   ELSE "Done"         \* D failed in PREPARE (TableNotEnabledException
                                       \* from DisableTableProcedure.java:254, not the
                                       \* target): the test fails at L74
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow,
                   ecall, eclient, fcall, proc, schedVars, master>>

-----------------------------------------------------------------------------
(* Observer runs (test L76-95), Scenario 1                                  *)
-----------------------------------------------------------------------------

\* test L76-86: an observer connection with hbase.client.retries.number = 0 (L77), a
\* QuotaObserverChore that is never scheduled (L82-84), and its in-memory snapshot of
\* T seeded with a DISABLE violation (L85-86 -> QuotaObserverChore.setTableQuotaSnapshot,
\* QuotaObserverChore.java:550-552). Nothing is written to hbase:quota.
ObsSetup ==
    /\ testPc = "ObsSetup"
    /\ obsMem' = "VIOL"
    /\ run' = 0
    /\ testPc' = "ObsCompare"
    /\ UNCHANGED <<tState, targetVars, obsCur, quotaRow, callVars, proc,
                   schedVars, master>>

\* test L91 observer.updateTableQuota(table, observer.getTableQuotaSnapshot(table),
\* observance): currentSnapshot is the chore's map entry (QuotaObserverChore.java:538-545).
\* L322 if (!currentSnapshot.equals(targetSnapshot)): equality covers status, usage
\* and limit (SpaceQuotaSnapshot.java:168-174), so only "OBS" equals the target.
ObsCompare ==
    /\ testPc = "ObsCompare"
    /\ obsCur' = obsMem
    /\ testPc' = IF obsMem /= "OBS"
                   THEN "ObsPut"        \* L323
                   ELSE "ObsRunEnd"     \* L352-360: nothing to do
    /\ UNCHANGED <<tState, targetVars, run, obsMem, quotaRow, callVars, proc,
                   schedVars, master>>

\* L323 snapshotNotifier.transitionTable(table, target) ->
\* TableSpaceQuotaSnapshotNotifier.java:39-47: one Table.put of u:p on hbase:quota,
\* served by the RegionServer, one attempt (ConnectionUtils.java:141-143).
ObsPut ==
    /\ testPc = "ObsPut"
    /\ quotaRow' = "OBS"
    /\ testPc' = "ObsMemUpdate"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, callVars, proc,
                   schedVars, master>>

\* L325 tableSnapshotStore.setCurrentState(table, target)
\* (TableQuotaSnapshotStore.java:162-165 -> QuotaObserverChore.java:550-552): the map
\* entry that the next run reads at test L91 now equals the target.
\* L328-334: currPolicy comes from the currentSnapshot ARGUMENT (obsCur); the target is
\* not in violation (L330), so the enable runs iff isDisableSpaceViolationPolicy(
\* currPolicy, null) (L332, L370-374), i.e. obsCur = "VIOL". A not-in-violation
\* snapshot has no policy (SpaceQuotaSnapshot.java:47, :86-88).
ObsMemUpdate ==
    /\ testPc = "ObsMemUpdate"
    /\ obsMem' = "OBS"
    /\ testPc' = IF obsCur = "VIOL" THEN "ObsEnable" ELSE "ObsRunEnd"
    /\ UNCHANGED <<tState, targetVars, run, obsCur, quotaRow, callVars, proc,
                   schedVars, master>>

\* L333 QuotaUtil.enableTableIfNotEnabled (QuotaUtil.java:636-643) -> L639
\* Admin.enableTable (Admin.java:359-361) -> RawAsyncHBaseAdmin.enableTable
\* (RawAsyncHBaseAdmin.java:807-812, fresh nonce) -> procedureCall (:565-576). The
\* submit RPC gets one attempt: maxAttempts = retries = 0 (AsyncAdminBuilderBase.java:46),
\* tries starts at 1 (AsyncRpcRetryingCaller.java:60), the first error ends the call
\* (L171-174, L185-188).
\* At most one enable request exists: it follows ObsMemUpdate, after which the map
\* equals the target and every later run stops at L322.
ObsEnableTable ==
    /\ testPc = "ObsEnable"
    /\ ecall = "none"
    /\ ecall' = "queued"
    /\ eclient' = "awaitSubmit"
    /\ testPc' = "ObsEnableWait"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, fcall,
                   proc, schedVars, master>>

\* A handler dequeues the enable call: CallRunner.run (CallRunner.java:90-105: client
\* still connected, deadline not passed); HMaster.enableTable (HMaster.java:2828-2835):
\* L2830 checkInitialized passes; L2832-2835 registerNonce -> -1 (fresh nonce), and
\* NonceProcedureRunnable.run() starts.
HMasterEnableTableStart ==
    /\ ecall = "queued"
    /\ master = "ACTIVE"
    /\ ecall' = "running"
    /\ UNCHANGED <<tState, targetVars, testVars, dcall, eclient, fcall, proc,
                   schedVars, master>>

\* The rest of run() (HMaster.java:2836-2879):
\*   L2836 preEnableTable (no coprocessor in the test);
\*   L2842-2865 space-quota gate: the quota manager is initialized (test L59-60), T is
\*     not a system table, L2848-2849 Gets u:p from hbase:quota on the MASTER's
\*     connection, L2850-2858 AccessDeniedException iff u:p is a DISABLE violation;
\*   L2874 createLatch() is the no-op latch for current clients
\*     (ProcedurePrepareLatch.java:42-56, :72-76);
\*   L2875-2876 submitProcedure(E) -> ProcedureExecutor.submitProcedure (:1119-1143):
\*     store.insert at L1138, pushProcedure -> addBack (L1197). D finished before the
\*     observer started, so the enqueue gate admits E (TableProcedureWaitingQueue.java:
\*     88-97 via MasterProcedureScheduler.completionCleanup :362-385) and doAdd
\*     appends E to T's queue;
\*   L2877 await() returns at once: the RPC returns E's procId without waiting for E.
\* The Get makes this the slow part of the handler (brief S2).
HMasterEnableTableSubmit ==
    /\ ecall = "running"
    /\ master = "ACTIVE"
    /\ IF quotaRow = "VIOL_DISABLE"
         THEN \* L2856 AccessDeniedException (a DoNotRetryIOException); nothing is
              \* submitted. Unreachable here: only ObsPut writes u:p, with "OBS".
              /\ ecall' = "none"
              /\ IF eclient = "awaitSubmit"
                   THEN /\ eclient' = "none"
                        /\ testPc' = "ObsRunEnd"
                   ELSE UNCHANGED <<eclient, testPc>>
              /\ UNCHANGED <<proc, rq>>
         ELSE /\ ~Exists("E")
              /\ proc' = [proc EXCEPT !["E"] = NewProcRec]
              /\ rq' = Append(rq, "E")
              /\ ecall' = "submitted"
              /\ UNCHANGED <<eclient, testPc>>
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, fcall,
                   lockWait, xlock, slock, wk, master>>

\* The enable request meets no active master: the connection fails (DOWN), or
\* checkInitialized throws PleaseHoldException / ServerNotRunningYetException while
\* the next master initializes (HMaster.java:2830, :3424-3433). One attempt, so the
\* call fails; QuotaUtil.java:640 swallows only TableNotDisabledException and
\* TableNotFoundException.
HMasterEnableTableNotInitialized ==
    /\ ecall = "queued"
    /\ master /= "ACTIVE"
    /\ eclient = "awaitSubmit"
    /\ ecall' = "none"
    /\ eclient' = "none"
    /\ testPc' = "ObsRunEnd"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, fcall,
                   proc, schedVars, master>>

\* The submit RPC's response (MasterRpcServices.java:911-920) reaches the client:
\* RawAsyncHBaseAdmin.waitProcedureResult (:3118-3129) starts polling
\* getProcedureResult (:3131-3169). Retriable poll errors are re-polled with no count
\* limit (L3141-3150), so from here on a master restart does not fail the call.
ObsEnableTableReply ==
    /\ ecall = "submitted"
    /\ eclient = "awaitSubmit"
    /\ eclient' = "awaitResult"
    /\ UNCHANGED <<tState, targetVars, testVars, dcall, ecall, fcall, proc,
                   schedVars, master>>

\* getProcedureResult sees E FINISHED (MasterRpcServices.java:1393-1403). A FAILED E
\* completes the future with its exception (RawAsyncHBaseAdmin.java:3158-3160). E can
\* fail only in PREPARE with TableNotDisabledException (EnableTableProcedure.java:
\* 265-268), which QuotaUtil.java:640 swallows. Either way updateTableQuota returns.
ObsEnableTableResult ==
    /\ eclient = "awaitResult"
    /\ master = "ACTIVE"
    /\ Finished("E")
    /\ eclient' = "none"
    /\ testPc' = "ObsRunEnd"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, ecall,
                   fcall, proc, schedVars, master>>

\* The master died with the submit RPC outstanding (MasterCrash): the client sees the
\* connection close; one attempt, so the call fails and is not swallowed.
ObsEnableTableConnLost ==
    /\ eclient = "broken"
    /\ eclient' = "none"
    /\ testPc' = "ObsRunEnd"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, ecall,
                   fcall, proc, schedVars, master>>

\* test L89-95: updateTableQuota returned, or threw an IOException that L92-94 catches
\* and logs ("the next run retries"). The loop moves on.
ObsRunEnd ==
    /\ testPc = "ObsRunEnd"
    /\ run' = run + 1
    /\ testPc' = IF run + 1 < 2 THEN "ObsCompare" ELSE "Flush"
    /\ UNCHANGED <<tState, targetVars, obsMem, obsCur, quotaRow, callVars, proc,
                   schedVars, master>>

-----------------------------------------------------------------------------
(* Flush (test L97)                                                         *)
-----------------------------------------------------------------------------

\* test L97 admin.flush(table) -> RawAsyncHBaseAdmin.flush(TableName) (:1030-1032) ->
\* flush(table, emptyList) (:1042-1078; one request and nonce for every retry) ->
\* procedureCall. Only this call creates F, so at most one F exists.
TestFlushTable ==
    /\ testPc = "Flush"
    /\ fcall' = "queued"
    /\ testPc' = "FlushWait"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, ecall,
                   eclient, proc, schedVars, master>>

\* HMaster.flushTable (HMaster.java:4672-4699) for a retried request whose nonce is
\* known (MasterProcedureUtil.java:134-135): returns F's procId.
HMasterFlushTableDedup ==
    /\ fcall = "queued"
    /\ master = "ACTIVE"
    /\ Exists("F")
    /\ fcall' = "submitted"
    /\ UNCHANGED <<tState, targetVars, testVars, dcall, ecall, eclient, proc,
                   schedVars, master>>

\* HMaster.flushTable with a fresh nonce: L4674 checkInitialized; L4676-4681
\* FlushTableProcedureV2 is enabled by default (MasterFlushTableProcedureManager.java:
\* 66-68); L4687 preTableFlush; L4689-4690 submitProcedure(new FlushTableProcedure(..))
\* -- the constructor checks nothing (FlushTableProcedure.java:63-68) --
\* -> ProcedureExecutor.submitProcedure (store.insert L1138, addBack L1197). FLUSH is
\* not exclusive, so the enqueue gate is skipped (MasterProcedureScheduler.java:150)
\* and F is appended to T's queue.
HMasterFlushTable ==
    /\ fcall = "queued"
    /\ master = "ACTIVE"
    /\ ~Exists("F")
    /\ proc' = [proc EXCEPT !["F"] = NewProcRec]
    /\ rq' = Append(rq, "F")
    /\ fcall' = "submitted"
    /\ UNCHANGED <<tState, targetVars, testVars, dcall, ecall, eclient,
                   lockWait, xlock, slock, wk, master>>

\* The client polls F's result; Admin.flush returns when F is FINISHED. A failed F
\* (TableNotEnabledException, passed through at RawAsyncHBaseAdmin.java:1059-1063)
\* only follows the target, after which nothing runs.
TestFlushDone ==
    /\ testPc = "FlushWait"
    /\ fcall = "submitted"
    /\ master = "ACTIVE"
    /\ Finished("F")
    /\ fcall' = "none"
    /\ testPc' = "Done"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, ecall,
                   eclient, proc, schedVars, master>>

-----------------------------------------------------------------------------
(* Procedure workers and the table lock, Scenario 2                         *)
-----------------------------------------------------------------------------

\* ProcedureExecutor.WorkerThread.run (ProcedureExecutor.java:2179-2186): L2181
\* scheduler.poll -> AbstractProcedureScheduler.poll (:153-186) ->
\* MasterProcedureScheduler.dequeue (:209-229) -> doPoll(tableRunQueue) (:243-265):
\* the first procedure of T's queue that isLockReady is returned (L250-258); the
\* ones before it that were not ready are re-added at the back (L260).
\* The lock is NOT taken here; the same worker takes it later
\* (ProcedureExecutor.java:1500). This is the poll/acquire window of brief S2.
\* Run-queue membership (L254-256, L263, :685-686, :710, :763) is not modeled: every
\* lock release re-adds T's queue (L710, L763) and doAdd adds it whenever the new
\* procedure could run (:187-198), so with only D, E and F on T a poll succeeds exactly
\* when some queued procedure is lock-ready.
\* Workers poll only on the active master: a procedure polled while the master
\* initializes is suspended in doAcquireLock -> waitInitialized (Procedure.java:
\* 1022-1023) and re-added at the front when it initializes, which leaves T's queue
\* in the same order (F cannot be submitted before initialization).
PEWorkerPoll(w) ==
    /\ master = "ACTIVE"
    /\ wk[w].pc = "idle"
    /\ \E i \in 1..Len(rq) :
         /\ IsLockReady(rq[i])
         /\ \A j \in 1..(i - 1) : ~IsLockReady(rq[j])
         /\ rq' = SubSeq(rq, i + 1, Len(rq)) \o SubSeq(rq, 1, i - 1)
         /\ wk' = [wk EXCEPT ![w] = [pc |-> "polled", p |-> rq[i]]]
    /\ UNCHANGED <<tState, targetVars, testVars, callVars, proc, lockWait, xlock,
                   slock, master>>

\* ProcedureExecutor.executeProcedure (:1437-1531) -> L1500 acquireLock (:1533-1541)
\* -> Procedure.doAcquireLock (Procedure.java:1021-1045):
\*   L1022 waitInitialized: the master is active.
\*   L1025-1032 a lock restored at load is taken without calling acquireLock.
\*   L1034 acquireLock(env):
\*     D, E: AbstractStateMachineTableProcedure.acquireLock (:93-99) ->
\*       waitTableExclusiveLock (MasterProcedureScheduler.java:668-691): L674 namespace
\*       shared lock (no namespace-exclusive procedure runs, not modeled); L679
\*       tryExclusiveLock (LockAndQueue.java:131-137) fails if any lock is held by
\*       another procedure -> L680-681 waitProcedure parks it at the tail of the lock's
\*       queue (AbstractProcedureScheduler.java:268-270): LOCK_EVENT_WAIT
\*       (ProcedureExecutor.java:1509-1512), the worker goes back to polling.
\*     F: FlushTableProcedure.acquireLock (FlushTableProcedure.java:70-81) ->
\*       waitTableSharedLock (:725-749) -> trySharedLock (LockAndQueue.java:112-121):
\*       fails only while another procedure holds the exclusive lock. There is no
\*       writer preference: a polled-but-unlocked D or E does not stop F.
\*   L1035-1043 on success: locked = true, persisted before execution.
PEWorkerAcquireLock(w) ==
    LET p == wk[w].p IN
    /\ master = "ACTIVE"
    /\ wk[w].pc = "polled"
    /\ IF xlock = p \/ p \in slock
         THEN \* restored at load (Procedure.java:1025-1032)
              /\ wk' = [wk EXCEPT ![w].pc = "running"]
              /\ UNCHANGED <<proc, lockWait, xlock, slock>>
         ELSE IF NeedsXLock(p)
           THEN IF xlock = NoProc /\ slock = {}
                  THEN /\ xlock' = p                                 \* LockAndQueue.java:135
                       /\ proc' = [proc EXCEPT ![p].locked = TRUE]   \* Procedure.java:1036-1042
                       /\ wk' = [wk EXCEPT ![w].pc = "running"]
                       /\ UNCHANGED <<lockWait, slock>>
                  ELSE /\ lockWait' = Append(lockWait, p)            \* MasterProcedureScheduler.java:680-681
                       /\ wk' = [wk EXCEPT ![w] = Idle]
                       /\ UNCHANGED <<proc, xlock, slock>>
           ELSE IF xlock = NoProc
                  THEN /\ slock' = slock \cup {p}                    \* LockAndQueue.java:119
                       /\ proc' = [proc EXCEPT ![p].locked = TRUE]
                       /\ wk' = [wk EXCEPT ![w].pc = "running"]
                       /\ UNCHANGED <<lockWait, xlock>>
                  ELSE /\ lockWait' = Append(lockWait, p)            \* MasterProcedureScheduler.java:740-742
                       /\ wk' = [wk EXCEPT ![w] = Idle]
                       /\ UNCHANGED <<proc, xlock, slock>>
    /\ UNCHANGED <<tState, targetVars, testVars, callVars, rq, master>>

\* End of an execProcedure call for an exclusive procedure p: holdLock is false
\* (Procedure.java:318-320), so ProcedureExecutor.java:1946 releases the lock ->
\* Procedure.doReleaseLock (Procedure.java:1050-1062: locked = false, persisted, then
\* releaseLock).
EndXHold(w, p, rec) ==
    /\ proc' = [proc EXCEPT ![p] = rec]
    /\ ReleaseXLock
    /\ wk' = [wk EXCEPT ![w] = Idle]

\* D, first lock hold. One execProcedure call (ProcedureExecutor.java:1806-1953): each
\* state returns HAS_MORE_STATE, StateMachineProcedure.execute returns `this`
\* (StateMachineProcedure.java:198) and the loop re-executes (ProcedureExecutor.java:
\* 1851-1858); yields are off (StateMachineProcedure.java:130-132, :266-268). The hold
\* ends when MARK_REGIONS_OFFLINE returns a child.
DisableTableHold1(w) ==
    /\ master = "ACTIVE"
    /\ wk[w] = [pc |-> "running", p |-> "D"]
    /\ proc["D"].st = "RUNNABLE"
    /\ proc["D"].step = "PREPARE"
    /\ IF tState /= "ENABLED"
         THEN \* DISABLE_TABLE_PREPARE (DisableTableProcedure.java:88-95) ->
              \* prepareDisable (:231-263): L250-252 not ENABLED -> L254
              \* setFailure(TableNotEnabledException) -- NOT the target line -- L260 latch
              \* released, NO_MORE_STATE (L92-93); rolled back in PREPARE (L155-157).
              /\ EndXHold(w, "D", [st |-> "FAILED", step |-> "DONE", locked |-> FALSE])
              /\ UNCHANGED tState
         ELSE \* L260 latch released; PRE_OPERATION (L96-99, no coprocessor);
              \* SET_DISABLING_TABLE_STATE (L100-103 -> setTableStateToDisabling
              \* :279-285 -> TableStateManager.setTableState :67-75, meta Put then cache
              \* :149-169); MARK_REGIONS_OFFLINE (L104-107) adds a
              \* CloseTableRegionsProcedure child; the children are submitted
              \* (ProcedureExecutor.java:1939-1941) and the lock released (L1946).
              /\ tState' = "DISABLING"
              /\ EndXHold(w, "D", [st |-> "WAITING", step |-> "ADD_REPLICATION_BARRIER",
                                   locked |-> FALSE])
    /\ UNCHANGED <<targetVars, testVars, callVars, slock, master>>

\* D, second lock hold, after its children: ADD_REPLICATION_BARRIER (L108-126; T has no
\* global replication scope), SET_DISABLED_TABLE_STATE (L127-130 ->
\* setTableStateToDisabled :291-297), POST_OPERATION (L131-133) -> NO_MORE_STATE ->
\* SUCCESS (ProcedureExecutor.java:1871-1874); lock released.
DisableTableHold2(w) ==
    /\ master = "ACTIVE"
    /\ wk[w] = [pc |-> "running", p |-> "D"]
    /\ proc["D"].st = "RUNNABLE"
    /\ proc["D"].step = "ADD_REPLICATION_BARRIER"
    /\ tState' = "DISABLED"
    /\ EndXHold(w, "D", [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE])
    /\ UNCHANGED <<targetVars, testVars, callVars, slock, master>>

\* E, first lock hold (brief S2: kept atomic). Same loop as D's first hold.
EnableTableHold1(w) ==
    /\ master = "ACTIVE"
    /\ wk[w] = [pc |-> "running", p |-> "E"]
    /\ proc["E"].st = "RUNNABLE"
    /\ proc["E"].step = "PREPARE"
    /\ IF tState /= "DISABLED"
         THEN \* ENABLE_TABLE_PREPARE (EnableTableProcedure.java:77-84) ->
              \* prepareEnable (:247-276): L263-265 not DISABLED -> L267
              \* setFailure(TableNotDisabledException), NO_MORE_STATE (L81-82); rolled
              \* back in PREPARE (L170-172).
              /\ EndXHold(w, "E", [st |-> "FAILED", step |-> "DONE", locked |-> FALSE])
              /\ UNCHANGED tState
         ELSE \* PRE_OPERATION (L85-88, no coprocessor); SET_ENABLING_TABLE_STATE
              \* (L89-92 -> setTableStateToEnabling :293-299); MARK_REGIONS_ONLINE
              \* (L93-140) adds the assign children (L138); children submitted, lock
              \* released. From here the guard at L161-162 accepts the table.
              /\ tState' = "ENABLING"
              /\ EndXHold(w, "E", [st |-> "WAITING", step |-> "SET_ENABLED",
                                   locked |-> FALSE])
    /\ UNCHANGED <<targetVars, testVars, callVars, slock, master>>

\* E, second lock hold, after its children: SET_ENABLED_TABLE_STATE (L141-144 ->
\* setTableStateToEnabled :305-311), POST_OPERATION (L145-147) -> SUCCESS.
EnableTableHold2(w) ==
    /\ master = "ACTIVE"
    /\ wk[w] = [pc |-> "running", p |-> "E"]
    /\ proc["E"].st = "RUNNABLE"
    /\ proc["E"].step = "SET_ENABLED"
    /\ tState' = "ENABLED"
    /\ EndXHold(w, "E", [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE])
    /\ UNCHANGED <<targetVars, testVars, callVars, slock, master>>

\* Site F path. FlushTableProcedure.executeFromState (FlushTableProcedure.java:88-115),
\* FLUSH_TABLE_PREPARE (L95-98), under the table shared lock: L96
\* preflightChecks(env, true) -> override L117-138 -> L119 super.preflightChecks.
\* flush(table) sends no column families (MasterRpcServices.java:3713-3716), so the
\* override returns at L120-122 right after the super call.
SiteFPath(w) ==
    /\ master = "ACTIVE"
    /\ wk[w] = [pc |-> "running", p |-> "F"]
    /\ proc["F"].st = "RUNNABLE"
    /\ proc["F"].step = "PREPARE"

\* TargetCheck at Site F.
FlushTablePrepare(w) ==
    /\ SiteFPath(w)
    /\ IF PreflightFails
         THEN \* L163 throw new TableNotEnabledException(tn) -> caught at L105-109: a
              \* DoNotRetryIOException -> setFailure("master-flush-table", e); the client
              \* receives it (RawAsyncHBaseAdmin.java:3158-3160, :1059-1063).
              /\ targetFired' = TRUE
              /\ firedSite' = "F"
              /\ UNCHANGED proc
         ELSE \* L97 setNextState(FLUSH_TABLE_FLUSH_REGIONS), L98 HAS_MORE_STATE: the
              \* same execProcedure loop continues (ProcedureExecutor.java:1851-1858)
              \* and the worker keeps the lock.
              /\ UNCHANGED targetVars
              /\ proc' = [proc EXCEPT !["F"].step = "FLUSH_REGIONS"]
    /\ UNCHANGED <<tState, testVars, callVars, schedVars, master>>

\* FLUSH_TABLE_FLUSH_REGIONS (L99-101): FlushRegionProcedure children, NO_MORE_STATE.
\* The loop exits, the children are submitted, the shared lock is released
\* (ProcedureExecutor.java:1946). F waits for its children.
FlushTableFlushRegions(w) ==
    /\ master = "ACTIVE"
    /\ wk[w] = [pc |-> "running", p |-> "F"]
    /\ proc["F"].st = "RUNNABLE"
    /\ proc["F"].step = "FLUSH_REGIONS"
    /\ proc' = [proc EXCEPT !["F"] = [st |-> "WAITING", step |-> "EOF", locked |-> FALSE]]
    /\ ReleaseSLock("F")
    /\ wk' = [wk EXCEPT ![w] = Idle]
    /\ UNCHANGED <<tState, targetVars, testVars, callVars, xlock, master>>

\* F after its children: StateMachineProcedure.execute finds no more state
\* (StateMachineProcedure.java:167-169) -> SUCCESS (ProcedureExecutor.java:1871-1874);
\* shared lock released.
FlushTableFinish(w) ==
    /\ master = "ACTIVE"
    /\ wk[w] = [pc |-> "running", p |-> "F"]
    /\ proc["F"].st = "RUNNABLE"
    /\ proc["F"].step = "EOF"
    /\ proc' = [proc EXCEPT !["F"] = [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE]]
    /\ ReleaseSLock("F")
    /\ wk' = [wk EXCEPT ![w] = Idle]
    /\ UNCHANGED <<tState, targetVars, testVars, callVars, xlock, master>>

\* The children of p finish (not modeled; brief §3.2). The last one makes the parent
\* runnable and puts it at the FRONT of T's queue (ProcedureExecutor.countDownChildren
\* :2008-2026, L2017-2021); for D and E the enqueue gate re-admits the enqueued
\* procedure (TableProcedureWaitingQueue.java:72-75).
ProcChildrenDone(p) ==
    /\ master = "ACTIVE"
    /\ proc[p].st = "WAITING"
    /\ proc' = [proc EXCEPT ![p].st = "RUNNABLE"]
    /\ rq' = <<p>> \o rq
    /\ UNCHANGED <<tState, targetVars, testVars, callVars, lockWait, xlock, slock,
                   wk, master>>

-----------------------------------------------------------------------------
(* Master failover, Scenario 3                                              *)
-----------------------------------------------------------------------------

\* The next active master starts: HMaster.java:1044 createProcedureExecutor ->
\* ProcedureExecutor.init (:621-692) -> load -> loadProcedures (:530-576): finished
\* procedures go to `completed` (L543-545), the others to `procedures`, and every
\* nonce is restored (L573-575) -- in the model a nonce is known iff its procedure
\* exists. restoreLocks (L599) re-takes the lock of each Restorable procedure;
\* pushProceduresAfterLoad (L605) queues the runnable ones in LoadOrder.
\* HMaster.java:1073 creates a TableStateManager with an empty cache; its first read
\* goes to T's meta row (TableStateManager.java:171-182), which holds tState.
MasterStartup ==
    /\ master = "DOWN"
    /\ master' = "INIT"
    /\ xlock' = IF Restorable("D") THEN "D"
                ELSE IF Restorable("E") THEN "E"
                ELSE NoProc
    /\ slock' = IF Restorable("F") THEN {"F"} ELSE {}
    /\ rq' = LoadOrder
    /\ UNCHANGED <<tState, targetVars, testVars, callVars, proc, lockWait, wk>>

\* HMaster.java:1148 startServiceThreads -> :1732 startProcedureExecutor (workers);
\* :1817 serviceStarted; :1300 setInitialized(true). checkInitialized now passes,
\* and procedures waiting in doAcquireLock -> waitInitialized resume.
MasterFinishInit ==
    /\ master = "INIT"
    /\ master' = "ACTIVE"
    /\ UNCHANGED <<tState, targetVars, testVars, callVars, proc, schedVars>>

-----------------------------------------------------------------------------
(* Faults. Unbounded here; MC.tla bounds each with a counter.               *)
-----------------------------------------------------------------------------

\* S1 (also its control case): the Put at L323 fails. The IOException leaves
\* updateTableQuota before L325, so the map keeps the old snapshot and the next run
\* redoes the transition. The Put may have been applied on the RegionServer before
\* the client saw the error.
ObsPutFail ==
    /\ testPc = "ObsPut"
    /\ quotaRow' \in {quotaRow, "OBS"}
    /\ testPc' = "ObsRunEnd"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, callVars, proc,
                   schedVars, master>>

\* S1: the enable call fails WITHOUT effect. Either the request is dropped before
\* dispatch (CallRunner.java:92-105: client gone, or deadline passed at dequeue), or
\* the handler throws before submitting E (the preEnableTable hook, HMaster.java:2836;
\* the hbase:quota Get, :2848-2849). No E exists; the client's one attempt fails and
\* QuotaUtil.java:640 does not swallow it. A failure of E in PREPARE/PRE_OPERATION
\* (EnableTableProcedure.java:151-153, :181-190) ends in the same state.
ObsEnableTableFailNoEffect ==
    /\ ecall \in {"queued", "running"}
    /\ eclient = "awaitSubmit"
    /\ master = "ACTIVE"
    /\ ecall' = "none"
    /\ eclient' = "none"
    /\ testPc' = "ObsRunEnd"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, fcall,
                   proc, schedVars, master>>

\* S2: the enable call reports failure but takes effect. The client's rpc timeout
\* expires while a handler is past dequeue (the server checks the deadline only at
\* dequeue, CallRunner.java:98-105, and never cancels a running handler), or before
\* dequeue but ahead of the server-side deadline, which counts from the server's
\* receive time; or the response is lost after E was stored
\* (ProcedureExecutor.java:1138). The server goes on: a "queued" or "running" request
\* can still submit E later (late submission).
ObsEnableTableFailLateEffect ==
    /\ ecall \in {"queued", "running", "submitted"}
    /\ eclient = "awaitSubmit"
    /\ eclient' = "none"
    /\ testPc' = "ObsRunEnd"
    /\ UNCHANGED <<tState, targetVars, run, obsMem, obsCur, quotaRow, dcall, ecall,
                   fcall, proc, schedVars, master>>

\* S3: the active (or initializing) master process dies. Lost: RPC handler threads,
\* the scheduler's queues and lock table, worker state. Kept: the procedure store
\* (insert ProcedureExecutor.java:1138, every executed step :1893-1912, the `locked`
\* flag Procedure.java:1042/:1059) and T's meta row (written before the cache,
\* TableStateManager.java:161-162). The test JVM survives, observer included
\* (QuotaObserverChore.java:88, :117 is a test-JVM object here).
MasterCrash ==
    /\ master /= "DOWN"
    /\ master' = "DOWN"
    /\ wk' = [w \in Workers |-> Idle]
    /\ rq' = <<>>
    /\ lockWait' = <<>>
    /\ xlock' = NoProc
    /\ slock' = {}
    \* the enable handler dies with its request; a submitted E is durable
    /\ ecall' = IF ecall \in {"queued", "running"} THEN "none" ELSE ecall
    \* the observer's outstanding submit RPC sees the connection close; a client that
    \* already polls E's result keeps polling (ObsEnableTableReply)
    /\ eclient' = IF eclient = "awaitSubmit" THEN "broken" ELSE eclient
    \* The default Admin re-sends a disable/flush with the same nonce to the next
    \* master. A request still inside the handler goes back to "queued"; for a
    \* submitted one the client either re-sends it (deduplicated by the restored
    \* nonce) or keeps polling the result. Both end with the client waiting for the
    \* same procedure.
    /\ dcall' \in CASE dcall = "ctorOk"    -> {"queued"}
                    [] dcall = "submitted" -> {"submitted", "queued"}
                    [] OTHER               -> {dcall}
    /\ fcall' \in IF fcall = "submitted" THEN {"submitted", "queued"} ELSE {fcall}
    /\ UNCHANGED <<tState, targetVars, testVars, proc>>

-----------------------------------------------------------------------------
(* Specification                                                            *)
-----------------------------------------------------------------------------

Init ==
    \* test L72 createTable returned: CreateTableProcedure wrote ENABLED
    \* (CreateTableProcedure.java:422-427) and the client waited for it.
    /\ tState = "ENABLED"
    /\ targetFired = FALSE
    /\ firedSite = "none"
    /\ testPc = "Disable"                 \* test L74 next
    /\ run = 0
    /\ obsMem = "NONE"
    /\ obsCur = "NONE"
    /\ quotaRow = "ABSENT"                \* no space quota row for T yet
    /\ dcall = "none"
    /\ ecall = "none"
    /\ eclient = "none"
    /\ fcall = "none"
    /\ proc = [p \in ProcIds |-> NoProcRec]
    /\ rq = <<>>
    /\ lockWait = <<>>
    /\ xlock = NoProc
    /\ slock = {}
    /\ wk = [w \in Workers |-> Idle]
    /\ master = "ACTIVE"

\* The adhoc pattern's TargetCheck: the two code paths that evaluate the guard.
TargetCheck == DisableTableProcedureCtor \/ \E w \in Workers : FlushTablePrepare(w)

WorkerNext(w) ==
    \/ PEWorkerPoll(w)
    \/ PEWorkerAcquireLock(w)
    \/ DisableTableHold1(w)
    \/ DisableTableHold2(w)
    \/ EnableTableHold1(w)
    \/ EnableTableHold2(w)
    \/ FlushTablePrepare(w)
    \/ FlushTableFlushRegions(w)
    \/ FlushTableFinish(w)

\* Everything except the faults.
SystemNext ==
    \/ TestDisableTable
    \/ HMasterDisableTableDedup
    \/ DisableTableProcedureCtor
    \/ HMasterDisableSubmit
    \/ TestDisableDone
    \/ ObsSetup
    \/ ObsCompare
    \/ ObsPut
    \/ ObsMemUpdate
    \/ ObsEnableTable
    \/ HMasterEnableTableStart
    \/ HMasterEnableTableSubmit
    \/ HMasterEnableTableNotInitialized
    \/ ObsEnableTableReply
    \/ ObsEnableTableResult
    \/ ObsEnableTableConnLost
    \/ ObsRunEnd
    \/ TestFlushTable
    \/ HMasterFlushTableDedup
    \/ HMasterFlushTable
    \/ TestFlushDone
    \/ \E w \in Workers : WorkerNext(w)
    \/ \E p \in ProcIds : ProcChildrenDone(p)
    \/ MasterStartup
    \/ MasterFinishInit

FaultNext ==
    \/ ObsPutFail
    \/ ObsEnableTableFailNoEffect
    \/ ObsEnableTableFailLateEffect
    \/ MasterCrash

\* The run is over (test finished or the target fired): stutter, so that TLC's
\* deadlock check still reports a model that gets stuck anywhere else.
Quiescent ==
    /\ testPc = "Done" \/ targetFired
    /\ UNCHANGED vars

\* Once the target fires, nothing else runs (adhoc tla-patterns §1).
Next ==
    \/ /\ ~targetFired
       /\ SystemNext \/ FaultNext
    \/ Quiescent

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Invariants (brief §5)                                                    *)
-----------------------------------------------------------------------------

\* The property: the guard at AbstractStateMachineTableProcedure.java:161-163 never
\* fails, at Site D or at Site F.
TargetSafe == ~targetFired

IsSeqOf(s, S)  == s \in [1..Len(s) -> S]
Distinct(s)    == \A i, j \in 1..Len(s) : i /= j => s[i] /= s[j]

TypeOK ==
    /\ tState \in TableStates
    /\ targetFired \in BOOLEAN
    /\ firedSite \in {"none", "D", "F"}
    /\ testPc \in TestPcs
    /\ run \in 0..2
    /\ obsMem \in Snapshots
    /\ obsCur \in Snapshots
    /\ quotaRow \in QuotaRows
    /\ dcall \in DCalls
    /\ ecall \in ECalls
    /\ eclient \in EClients
    /\ fcall \in FCalls
    /\ proc \in [ProcIds -> ProcRec]
    /\ IsSeqOf(rq, ProcIds) /\ Distinct(rq)
    /\ IsSeqOf(lockWait, ProcIds) /\ Distinct(lockWait)
    /\ xlock \in ProcIds \cup {NoProc}
    /\ slock \subseteq ProcIds
    /\ wk \in [Workers -> WorkerStates]
    /\ master \in MasterStates

\* A transitional table state is owned by an unfinished procedure that has passed
\* the step writing it: ENABLING by E after SET_ENABLING_TABLE_STATE, DISABLING by D
\* after SET_DISABLING_TABLE_STATE.
TransitionalStateOwned ==
    /\ tState = "ENABLING" =>
         /\ proc["E"].st \in {"RUNNABLE", "WAITING"}
         /\ proc["E"].step = "SET_ENABLED"
    /\ tState = "DISABLING" =>
         /\ proc["D"].st \in {"RUNNABLE", "WAITING"}
         /\ proc["D"].step = "ADD_REPLICATION_BARRIER"

-----------------------------------------------------------------------------
(* Sanity checks (adhoc tla-patterns §2). With every fault counter at 0,    *)
(* TLC must VIOLATE each of these: it shows that the model takes the path  *)
(* to the check at that site. They are not safety properties.             *)
-----------------------------------------------------------------------------

TargetReachedD == ~(~targetFired /\ SiteDPath)
TargetReachedF == ~(~targetFired /\ \E w \in Workers : SiteFPath(w))

\* Spec-development check, not a brief §5 invariant: while a master is up, a
\* RUNNABLE procedure is in exactly one place (T's queue, the lock's wait queue, or
\* one worker) and any other procedure is in none. While it is DOWN the scheduler
\* is empty until MasterStartup reloads the store.
Places(p) ==
    Cardinality({i \in 1..Len(rq) : rq[i] = p})
    + Cardinality({i \in 1..Len(lockWait) : lockWait[i] = p})
    + Cardinality({w \in Workers : wk[w].p = p})
SchedulerPlacementOK ==
    \A p \in ProcIds :
        IF proc[p].st = "RUNNABLE" /\ master /= "DOWN"
          THEN Places(p) = 1
          ELSE Places(p) = 0

=============================================================================
