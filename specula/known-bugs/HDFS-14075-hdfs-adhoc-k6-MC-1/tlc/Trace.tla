------------------------------- MODULE Trace -------------------------------
(*
 * Trace validation for hdfs-adhoc-k6 (Category A: single linear NDJSON trace).
 *
 * One NameNode process; every event is emitted under a process-wide trace lock
 * at the point listed in instrumentation-spec.md, so the file order is a valid
 * linearization of the base spec's steps.
 *
 * Line format (one JSON object per line):
 *   {"tag":"trace",
 *    "event":{"name":"<Action>", "actor":"rpc|roller|admin"   (roll/segment steps),
 *             "admitted":true|false                             (RollAcquire),
 *             "ok":true|false                                   (StartSegment),
 *             "journal":"j1"                                    (JournalFault/Repair),
 *             "state":{"elState":"IN_SEGMENT", "streamOpen":true,
 *                      "jStream":{"j1":"active"}, "pendingEdits":0,
 *                      "safeMode":false, "haState":"Active",
 *                      "stopPhase":"running"}}}
 * "state" is the post-action snapshot.
 *)
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

ASSUME Len(TraceLog) > 0

\* Journal ids come from the trace (the jStream keys, in JournalSet order).
TraceJournal == TLCEval(DOMAIN TraceLog[1].event.state.jStream)

\* ============================================================================
\* TRACE CURSOR
\* ============================================================================

VARIABLE l

logline == TraceLog[l]
ev      == logline.event

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ ev.name = name

IsActorEvent(name, a) ==
    /\ IsEvent(name)
    /\ ev.actor = a

\* ============================================================================
\* POST-STATE VALIDATION
\* ============================================================================

\* Every field the harness captures in "state" is checked after every event.
ValidatePostState ==
    LET s == ev.state IN
    /\ elState'      = s.elState
    /\ streamOpen'   = s.streamOpen
    /\ pendingEdits' = s.pendingEdits
    /\ safeMode'     = s.safeMode
    /\ haState'      = s.haState
    /\ stopPhase'    = s.stopPhase
    /\ \A j \in Journal : jStream'[j] = s.jStream[j]

\* ============================================================================
\* ACTION WRAPPERS
\* ============================================================================

Step(A) ==
    /\ A
    /\ ValidatePostState
    /\ l' = l + 1

TraceRpcRollArrive ==
    /\ IsActorEvent("RpcRollArrive", "rpc")
    /\ Step(RpcRollArrive)

TraceRollerCheck ==
    /\ IsActorEvent("RollerCheck", "roller")
    /\ Step(RollerCheck)

\* "admitted" tells which branch of FSNamesystem.java:4735-4736 was taken.
TraceRollAcquire ==
    \E a \in RollActor :
        /\ IsActorEvent("RollAcquire", a)
        /\ Step(RollAcquire(a))
        /\ (lockHolder' = a) = ev.admitted

TraceTargetCheck ==
    \E a \in Actor :
        /\ IsActorEvent("TargetCheck", a)
        /\ Step(TargetCheck(a))

TraceEndSegmentSync ==
    \E a \in Actor :
        /\ IsActorEvent("EndSegmentSync", a)
        /\ Step(EndSegmentSync(a))

TraceEndSegmentFinalize ==
    \E a \in Actor :
        /\ IsActorEvent("EndSegmentFinalize", a)
        /\ Step(EndSegmentFinalize(a))

\* "ok" tells whether journalSet.startLogSegment succeeded (FSEditLog.java:1383-1390).
TraceStartSegment ==
    \E a \in Actor :
        /\ IsActorEvent("StartSegment", a)
        /\ Step(StartSegment(a))
        /\ (elState' = "IN_SEGMENT") = ev.ok

TraceClientEdit ==
    /\ IsEvent("ClientEdit")
    /\ Step(ClientEdit)

TraceSyncThreadRun ==
    /\ IsEvent("SyncThreadRun")
    /\ Step(SyncThreadRun)

\* Fault events are emitted by the harness at injection time (none in the
\* unmodified workload).
TraceJournalFault ==
    \E j \in Journal :
        /\ IsEvent("JournalFault")
        /\ ev.journal = j
        /\ Step(JournalFault(j))
        /\ jDisk'[j] = "failed"

TraceJournalRepair ==
    \E j \in Journal :
        /\ IsEvent("JournalRepair")
        /\ ev.journal = j
        /\ Step(JournalRepair(j))
        /\ jDisk'[j] = "ok"

TraceEnterSafeMode ==
    /\ IsEvent("EnterSafeMode")
    /\ Step(EnterSafeMode)

TraceLeaveSafeMode ==
    /\ IsEvent("LeaveSafeMode")
    /\ Step(LeaveSafeMode)

TraceSaveNamespaceBegin ==
    /\ IsActorEvent("SaveNamespaceBegin", "admin")
    /\ Step(SaveNamespaceBegin)

TraceStopExitState ==
    /\ IsEvent("StopExitState")
    /\ Step(StopExitState)

TraceStopRpc ==
    /\ IsEvent("StopRpc")
    /\ Step(StopRpc)

TraceFsnClose ==
    /\ IsEvent("FsnClose")
    /\ Step(FsnClose)

TraceTransitionToStandby ==
    /\ IsEvent("TransitionToStandby")
    /\ Step(TransitionToStandby)

\* ============================================================================
\* SPEC
\* ============================================================================

\* The trace starts after cluster.waitActive(): base Init describes that state.
\* The first event's pre-state is not recorded; TraceInit is base Init.
TraceInit ==
    /\ Init
    /\ l = 1

\* No silent actions: every base action has its own trace event.
TraceNext ==
    /\ l <= Len(TraceLog)
    /\ ~targetFired
    /\ ~halted
    /\ \/ TraceRpcRollArrive
       \/ TraceRollerCheck
       \/ TraceRollAcquire
       \/ TraceTargetCheck
       \/ TraceEndSegmentSync
       \/ TraceEndSegmentFinalize
       \/ TraceStartSegment
       \/ TraceClientEdit
       \/ TraceSyncThreadRun
       \/ TraceJournalFault
       \/ TraceJournalRepair
       \/ TraceEnterSafeMode
       \/ TraceLeaveSafeMode
       \/ TraceSaveNamespaceBegin
       \/ TraceStopExitState
       \/ TraceStopRpc
       \/ TraceFsnClose
       \/ TraceTransitionToStandby

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceMatched == <>(l > Len(TraceLog))

TraceView == <<vars, l>>

=============================================================================
