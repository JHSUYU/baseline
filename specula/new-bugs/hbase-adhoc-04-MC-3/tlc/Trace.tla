-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hbase-adhoc-04 (Category A: one linear trace).      *)
(*                                                                          *)
(* The harness runs TestAdhocWorkload04#run (or a variant in the same       *)
(* module) on a single-JVM mini cluster. One synchronized logger writes     *)
(* NDJSON lines {"tag":"trace","event":{...}}; instrumentation-spec.md      *)
(* gives each event's code location, trigger point and fields. Every base   *)
(* action has exactly one event, so there are no silent actions.            *)
(*                                                                          *)
(* Each wrapper: match the event at cursor l, take the base action, check   *)
(* the post-state against the event's fields, advance l.                    *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC, FiniteSets

-----------------------------------------------------------------------------
(* Trace loading                                                            *)
-----------------------------------------------------------------------------

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                 /\ x.tag = "trace"
                                 /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0

\* Worker thread names in the trace (PEWorker-N, KeepAlivePEWorker-N).
\* Trace.cfg substitutes them for the Workers constant.
TraceWorkers == TLCEval(
    { TraceLog[k].event.w :
        k \in { k \in 1..Len(TraceLog) : "w" \in DOMAIN TraceLog[k].event } })

-----------------------------------------------------------------------------
(* Cursor                                                                   *)
-----------------------------------------------------------------------------

VARIABLE l
traceVars == <<l>>

logline == TraceLog[l].event

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ logline.name = name

StepTrace == l' = l + 1

\* Base actions run only while the target has not fired (as in base!Next).
Live == ~targetFired

-----------------------------------------------------------------------------
(* Choices resolved from the trace. TraceMatched is checked on every        *)
(* behavior, so a branch that dies early is reported even when another      *)
(* branch consumes the trace. Where the base spec leaves a choice that the   *)
(* event itself cannot show, the rest of the trace decides it. The later     *)
(* events are still matched and validated as usual.                          *)
-----------------------------------------------------------------------------

\* Position of the first MasterCrash event after position k (Len + 1 if none).
NextCrashAfter(k) ==
    LET later == { j \in (k + 1)..Len(TraceLog) : TraceLog[j].event.name = "MasterCrash" }
    IN IF later = {} THEN Len(TraceLog) + 1
       ELSE CHOOSE j \in later : \A i \in later : j <= i

\* The server went on with an enable that already failed at the client (S2):
\* a queued request is dequeued later (HEnableStart ahead), or a running handler
\* stores E later (Submit of E ahead).
LateStartAhead ==
    \E j \in (l + 1)..Len(TraceLog) : TraceLog[j].event.name = "HEnableStart"

LateSubmitAhead ==
    \E j \in (l + 1)..Len(TraceLog) :
        /\ TraceLog[j].event.name = "Submit"
        /\ TraceLog[j].event.p = "E"

\* After a crash, the default Admin re-sent the submitted disable/flush (a
\* NonceDedup for it appears before the next crash) instead of polling its result.
RetryAhead(p) ==
    \E j \in (l + 1)..(NextCrashAfter(l) - 1) :
        /\ TraceLog[j].event.name = "NonceDedup"
        /\ TraceLog[j].event.p = p

-----------------------------------------------------------------------------
(* Field mapping. The instrumentation writes the model's names directly     *)
(* (instrumentation-spec.md §1.3), so only sets need converting.            *)
-----------------------------------------------------------------------------

\* slockF: whether F holds T's shared lock (instrumentation-spec.md §1.3)
SLockOf(b) == IF b THEN {"F"} ELSE {}

\* Scheduler snapshot taken under the scheduler lock, after the action.
ValidateSched ==
    /\ rq' = logline.rq
    /\ lockWait' = logline.lockWait
    /\ xlock' = logline.xlock
    /\ slock' = SLockOf(logline.slockF)

-----------------------------------------------------------------------------
(* Test thread: disable                                                     *)
-----------------------------------------------------------------------------

\* RawAsyncHBaseAdmin.disableTable entry for T
TestDisableCallIfLogged ==
    /\ IsEvent("TestDisableCall")
    /\ Live
    /\ TestDisableTable
    /\ dcall' = "queued"
    /\ StepTrace

\* MasterProcedureUtil.submitProcedure, registerNonce returned a procId (L134-135)
NonceDedupIfLogged ==
    /\ IsEvent("NonceDedup")
    /\ Live
    /\ \/ /\ logline.p = "D"
          /\ HMasterDisableTableDedup
          /\ dcall' = "submitted"
       \/ /\ logline.p = "F"
          /\ HMasterFlushTableDedup
          /\ fcall' = "submitted"
    /\ StepTrace

\* preflightChecks between L160 and L161, called from the DisableTableProcedure
\* constructor. ts is the state read at L160; fired is the L161-162 predicate.
PreflightCheckDIfLogged ==
    /\ IsEvent("PreflightCheck")
    /\ logline.site = "D"
    /\ Live
    /\ logline.ts = tState
    /\ DisableTableProcedureCtor
    /\ targetFired' = logline.fired
    /\ StepTrace

\* ProcedureExecutor.submitProcedure after store.insert (L1138), before push (L1142)
SubmitIfLogged ==
    /\ IsEvent("Submit")
    /\ Live
    /\ \/ logline.p = "D" /\ HMasterDisableSubmit
       \/ logline.p = "E" /\ HMasterEnableTableSubmit
       \/ logline.p = "F" /\ HMasterFlushTable
    /\ proc'[logline.p] = [st |-> logline.st, step |-> logline.step,
                           locked |-> logline.locked]
    /\ StepTrace

-----------------------------------------------------------------------------
(* Test thread: observer runs                                               *)
-----------------------------------------------------------------------------

\* QuotaObserverChore.setTableQuotaSnapshot called directly (test L85-86)
ObsSetupIfLogged ==
    /\ IsEvent("ObsSetup")
    /\ Live
    /\ ObsSetup
    /\ obsMem' = logline.snapshot
    /\ StepTrace

\* QuotaObserverChore.updateTableQuota at L322
ObsCompareIfLogged ==
    /\ IsEvent("ObsCompare")
    /\ Live
    /\ run = logline.run
    /\ logline.equal = (obsMem = "OBS")
    /\ ObsCompare
    /\ obsCur' = logline.current
    /\ StepTrace

\* QuotaObserverChore.updateTableQuota around L323: ok = transitionTable returned
ObsPutIfLogged ==
    /\ IsEvent("ObsPut")
    /\ Live
    /\ \/ /\ logline.ok
          /\ ObsPut
          /\ quotaRow' = "OBS"
       \/ /\ ~logline.ok
          /\ ObsPutFail
          /\ testPc' = "ObsRunEnd"
    /\ StepTrace

\* after L325; enable = the L330 && L332 outcome
ObsMemUpdateIfLogged ==
    /\ IsEvent("ObsMemUpdate")
    /\ Live
    /\ ObsMemUpdate
    /\ obsMem' = logline.snapshot
    /\ (testPc' = "ObsEnable") = logline.enable
    /\ StepTrace

\* RawAsyncHBaseAdmin.enableTable entry for T
ObsEnableCallIfLogged ==
    /\ IsEvent("ObsEnableCall")
    /\ Live
    /\ ObsEnableTable
    /\ ecall' = "queued"
    /\ eclient' = "awaitSubmit"
    /\ StepTrace

\* HMaster.enableTable: NonceProcedureRunnable.run() entry, before L2836
HEnableStartIfLogged ==
    /\ IsEvent("HEnableStart")
    /\ Live
    /\ HMasterEnableTableStart
    /\ ecall' = "running"
    /\ StepTrace

\* RawAsyncHBaseAdmin.waitProcedureResult: the enable's procId arrived (L3121-3126)
ClientProcIdIfLogged ==
    /\ IsEvent("ClientProcId")
    /\ logline.op = "ENABLE"
    /\ Live
    /\ ObsEnableTableReply
    /\ eclient' = "awaitResult"
    /\ StepTrace

\* updateTableQuota exits, normally or by exception
ObsRunEndIfLogged ==
    /\ IsEvent("ObsRunEnd")
    /\ Live
    /\ run = logline.run
    /\ ObsRunEnd
    /\ run' = logline.run + 1
    /\ StepTrace

-----------------------------------------------------------------------------
(* Test thread: flush and client completions                                *)
-----------------------------------------------------------------------------

\* RawAsyncHBaseAdmin.flush(table, cfs) for T
TestFlushCallIfLogged ==
    /\ IsEvent("TestFlushCall")
    /\ Live
    /\ TestFlushTable
    /\ fcall' = "queued"
    /\ StepTrace

\* Exceptions that QuotaUtil.enableTableIfNotEnabled swallows (QuotaUtil.java:640)
SwallowedByQuotaUtil == {"TableNotDisabledException", "TableNotFoundException"}

\* The client future of a procedure call completed (procedureCall's consumer,
\* RawAsyncHBaseAdmin.java:574). For ENABLE an error that QuotaUtil does not
\* swallow is one of the observer's failure paths. The state picks it, except for a
\* queued or running request on an active master: the call failed without effect
\* unless the trace later shows the server going on (LateStartAhead/LateSubmitAhead).
ObsEnableErrorPath ==
    \/ /\ logline.exc = "AccessDeniedException"     \* quota gate, HMaster.java:2856
       /\ HMasterEnableTableSubmit
       /\ ecall' = "none"
    \/ /\ logline.exc /= "AccessDeniedException"
       /\ \/ ObsEnableTableConnLost                  \* eclient = "broken"
          \/ /\ ecall = "queued"
             /\ ~LateStartAhead
             /\ \/ ObsEnableTableFailNoEffect        \* master active
                \/ HMasterEnableTableNotInitialized  \* master down or initializing
          \/ /\ ecall = "queued"
             /\ LateStartAhead
             /\ ObsEnableTableFailLateEffect
          \/ /\ ecall = "running"
             /\ ~LateSubmitAhead
             /\ ObsEnableTableFailNoEffect
          \/ /\ ecall = "running"
             /\ LateSubmitAhead
             /\ ObsEnableTableFailLateEffect
          \/ /\ ecall = "submitted"
             /\ ObsEnableTableFailLateEffect

ClientDoneIfLogged ==
    /\ IsEvent("ClientDone")
    /\ Live
    /\ \/ /\ logline.op = "DISABLE"
          /\ TestDisableDone
          /\ logline.ok = (proc["D"].st = "SUCCESS")
       \/ /\ logline.op = "FLUSH"
          /\ TestFlushDone
          /\ logline.ok = (proc["F"].st = "SUCCESS")
       \/ /\ logline.op = "ENABLE"
          /\ \/ logline.ok
             \/ logline.exc \in SwallowedByQuotaUtil
          /\ ObsEnableTableResult
          /\ logline.ok = (proc["E"].st = "SUCCESS")
       \/ /\ logline.op = "ENABLE"
          /\ ~logline.ok
          /\ logline.exc \notin SwallowedByQuotaUtil
          /\ ObsEnableErrorPath
          /\ testPc' = "ObsRunEnd"
          /\ eclient' = "none"
    /\ StepTrace

-----------------------------------------------------------------------------
(* Procedure workers                                                        *)
-----------------------------------------------------------------------------

\* MasterProcedureScheduler.doPoll before `return proc` (L257), under schedLock
PollIfLogged ==
    /\ IsEvent("Poll")
    /\ Live
    /\ \E w \in Workers :
         /\ logline.w = w
         /\ PEWorkerPoll(w)
         /\ wk'[w] = [pc |-> "polled", p |-> logline.p]
         /\ rq' = logline.rq
    /\ StepTrace

\* waitTableExclusiveLock (L679-687) / waitTableQueueSharedLock (L739-745) under
\* schedLock, or Procedure.doAcquireLock L1025-1032 for a lock restored at load.
AcquireIfLogged ==
    /\ IsEvent("Acquire")
    /\ Live
    /\ \E w \in Workers :
         /\ logline.w = w
         /\ wk[w].p = logline.p
         /\ PEWorkerAcquireLock(w)
         /\ wk'[w].pc = IF logline.result = "parked" THEN "idle" ELSE "running"
         /\ (logline.result = "restored") = (xlock = logline.p \/ logline.p \in slock)
         /\ proc'[logline.p].locked = logline.locked
         /\ lockWait' = logline.lockWait
         /\ xlock' = logline.xlock
         /\ slock' = SLockOf(logline.slockF)
    /\ StepTrace

\* preflightChecks between L160 and L161, called from FLUSH_TABLE_PREPARE on worker w
PreflightCheckFIfLogged ==
    /\ IsEvent("PreflightCheck")
    /\ logline.site = "F"
    /\ Live
    /\ logline.ts = tState
    /\ \E w \in Workers :
         /\ logline.w = w
         /\ FlushTablePrepare(w)
    /\ targetFired' = logline.fired
    /\ ~logline.fired => proc'["F"].step = "FLUSH_REGIONS"
    /\ StepTrace

\* End of a lock hold: wakeTableExclusiveLock / wakeTableSharedLock, after the
\* release and the wake, under schedLock.
ExecIfLogged ==
    /\ IsEvent("Exec")
    /\ Live
    /\ \E w \in Workers :
         /\ logline.w = w
         /\ wk[w].p = logline.p
         /\ \/ /\ logline.p = "D"
               /\ (DisableTableHold1(w) \/ DisableTableHold2(w))
            \/ /\ logline.p = "E"
               /\ (EnableTableHold1(w) \/ EnableTableHold2(w))
            \/ /\ logline.p = "F"
               /\ (FlushTableFlushRegions(w) \/ FlushTableFinish(w))
         /\ wk'[w] = Idle
    /\ proc'[logline.p].st = logline.st
    /\ proc'[logline.p].step = logline.step
    /\ proc'[logline.p].locked = logline.locked
    /\ tState' = logline.tState
    /\ ValidateSched
    /\ StepTrace

\* ProcedureExecutor.countDownChildren before scheduler.addFront(parent) (L2021)
ChildrenDoneIfLogged ==
    /\ IsEvent("ChildrenDone")
    /\ Live
    /\ \E p \in ProcIds :
         /\ logline.p = p
         /\ ProcChildrenDone(p)
         /\ proc'[p].st = logline.st
    /\ StepTrace

-----------------------------------------------------------------------------
(* Master lifecycle (variants with a failover)                              *)
-----------------------------------------------------------------------------

\* Harness, just before it kills the active master. A submitted disable/flush is
\* re-sent ("queued") iff the trace shows its NonceDedup before the next crash.
MasterCrashIfLogged ==
    /\ IsEvent("MasterCrash")
    /\ Live
    /\ MasterCrash
    /\ master' = "DOWN"
    /\ dcall = "submitted" => ((dcall' = "queued") = RetryAhead("D"))
    /\ fcall = "submitted" => ((fcall' = "queued") = RetryAhead("F"))
    /\ StepTrace

\* HMaster.finishActiveMasterInitialization right after L1044 returns
MasterStartupIfLogged ==
    /\ IsEvent("MasterStartup")
    /\ Live
    /\ MasterStartup
    /\ rq' = logline.rq
    /\ xlock' = logline.xlock
    /\ slock' = SLockOf(logline.slockF)
    /\ StepTrace

\* HMaster.finishActiveMasterInitialization right after L1300
MasterInitializedIfLogged ==
    /\ IsEvent("MasterInitialized")
    /\ Live
    /\ MasterFinishInit
    /\ master' = "ACTIVE"
    /\ StepTrace

-----------------------------------------------------------------------------
(* After the target fired, base!Next only stutters (Quiescent). A trace     *)
(* that reproduces the check keeps logging (F's failure, the client's       *)
(* exception); those events are consumed without model steps. The firing   *)
(* itself was checked at its PreflightCheck event (fired = TRUE).           *)
-----------------------------------------------------------------------------

AfterFireIfLogged ==
    /\ l <= Len(TraceLog)
    /\ targetFired
    /\ UNCHANGED vars
    /\ StepTrace

-----------------------------------------------------------------------------
(* Specification                                                            *)
-----------------------------------------------------------------------------

\* The harness starts logging at the test's first disable call (L74), after
\* createTable returned: base!Init is that state.
TraceInit ==
    /\ Init
    /\ l = 1

TraceNext ==
    \/ TestDisableCallIfLogged
    \/ NonceDedupIfLogged
    \/ PreflightCheckDIfLogged
    \/ SubmitIfLogged
    \/ ObsSetupIfLogged
    \/ ObsCompareIfLogged
    \/ ObsPutIfLogged
    \/ ObsMemUpdateIfLogged
    \/ ObsEnableCallIfLogged
    \/ HEnableStartIfLogged
    \/ ClientProcIdIfLogged
    \/ ObsRunEndIfLogged
    \/ TestFlushCallIfLogged
    \/ ClientDoneIfLogged
    \/ PollIfLogged
    \/ AcquireIfLogged
    \/ PreflightCheckFIfLogged
    \/ ExecIfLogged
    \/ ChildrenDoneIfLogged
    \/ MasterCrashIfLogged
    \/ MasterStartupIfLogged
    \/ MasterInitializedIfLogged
    \/ AfterFireIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l          |-> l,
      event      |-> IF l <= Len(TraceLog) THEN logline ELSE [name |-> "END"],
      tState     |-> tState,
      testPc     |-> testPc,
      run        |-> run,
      obsMem     |-> obsMem,
      calls      |-> <<dcall, ecall, eclient, fcall>>,
      proc       |-> proc,
      rq         |-> rq,
      lockWait   |-> lockWait,
      xlock      |-> xlock,
      slock      |-> slock,
      wk         |-> wk,
      master     |-> master,
      targetFired |-> targetFired ]

=============================================================================
