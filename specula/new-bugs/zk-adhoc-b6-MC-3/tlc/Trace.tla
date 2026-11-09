--------------------------------- MODULE Trace ----------------------------------
(*
 * Trace validation for base.tla, Category A pattern: one NDJSON file, one cursor.
 * Each wrapper matches an event, runs the full base action, checks the post-state
 * against the event and advances the cursor. Field meanings and capture points are
 * in instrumentation-spec.md.
 *
 * Roles: peers run in one JVM and the test learns who is leader and which follower
 * has the ObserverMaster only after election, so events carry "p<sid>" and one
 * {"tag":"config","roles":{...}} line, anywhere in the file, maps them to L, F, O
 * and A. A is the abstract third participant: its events, and the leader handler's
 * events about it, are filtered out.
 *
 * No silent actions: every base action in the workload's path has its own event.
 *)

EXTENDS base, Json, IOUtils

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

AllLines == TLCEval(ndJsonDeserialize(JsonFile))

RoleMap == TLCEval(
    LET cfg == SelectSeq(AllLines, LAMBDA x : "tag" \in DOMAIN x /\ x.tag = "config")
    IN IF Len(cfg) > 0 THEN cfg[1].roles
       ELSE Assert(FALSE, "the trace has no config line with the role map"))

RoleOf(nid) == RoleMap[nid]

\* The leader never starts or stops in the model (brief 3.2), so its own start and
\* shutdown events have no action.
KeepEvent(e) ==
    /\ RoleOf(e.nid) \in Servers
    /\ ("msg" \in DOMAIN e /\ "learner" \in DOMAIN e.msg) => RoleOf(e.msg.learner) \in Learners
    /\ e.name \in {"LearnerStart", "PeerShutdown"} => RoleOf(e.nid) \in Learners

TraceLog == TLCEval(
    SelectSeq(AllLines, LAMBDA x :
        /\ "tag" \in DOMAIN x
        /\ x.tag = "trace"
        /\ KeepEvent(x.event)))

ASSUME Len(TraceLog) > 0

VARIABLE l      \* Position in TraceLog, 1-indexed.

Ev == TraceLog[l].event
EvNode == RoleOf(Ev.nid)
Msg == Ev.msg

IsEvent(name) == l <= Len(TraceLog) /\ Ev.name = name
IsNodeEvent(name, n) == IsEvent(name) /\ EvNode = n

\* For handler events, the learner the handler serves.
EvLearner == RoleOf(Msg.learner)

Advance == l' = l + 1

\* Post-state of the server's database, as the event captured it.
ValidateDb(n) ==
    /\ tree'[n] = Ev.state.tree
    /\ clog'[n].empty = Ev.state.clogEmpty
    /\ ~Ev.state.clogEmpty =>
        /\ clog'[n].min = Ev.state.clogMin
        /\ clog'[n].max = Ev.state.clogMax

\* The packet the learner just consumed.
ValidateHead(n) == Head(inQ[n]).zxid = Msg.zxid

\* The master's handler decision, LearnerHandler.syncFollower.
ModelKind(n) ==
    IF phase'[n] = "lostSync" THEN "DISCONNECT"
    ELSE IF hPhase'[n] = "needSnap" THEN "SNAP"
    ELSE Head(inQ'[n]).type

ValidateSyncDecision(n, src, useLog) ==
    /\ Msg.peer = tree[n]
    /\ Msg.lastProcessed = tree[src]
    /\ Msg.kind = ModelKind(n)
    /\ Msg.current = SyncFollower(src, tree[n], useLog).current

-----------------------------------------------------------------------------
(* LEADER *)

TraceClientPropose ==
    /\ IsNodeEvent("ClientPropose", L)
    /\ ClientPropose
    /\ lProposed' = Msg.zxid
    /\ Advance

TraceLeaderTryToCommit ==
    /\ IsNodeEvent("LeaderTryToCommit", L)
    /\ LeaderTryToCommit
    /\ lCommitted' = Msg.zxid
    /\ Advance

-----------------------------------------------------------------------------
(* HANDLERS *)

TraceLeaderSyncFollower ==
    /\ IsNodeEvent("LeaderSyncFollower", L)
    /\ EvLearner = F
    /\ \E u \in BOOLEAN :
        /\ LeaderSyncFollower(u)
        /\ ValidateSyncDecision(F, L, u)
    /\ Advance

TraceOmSyncObserver ==
    /\ IsNodeEvent("OmSyncObserver", F)
    /\ EvLearner = O
    /\ \E u \in BOOLEAN :
        /\ OmSyncObserver(u)
        /\ ValidateSyncDecision(O, F, u)
        /\ omActive' = Msg.activated
        /\ Msg.activated => Len(RetainedAfter(Msg.current)) = Msg.retained
    /\ Advance

TraceHandlerSendSnap ==
    /\ IsEvent("HandlerSendSnap")
    /\ EvNode = MasterOf(EvLearner)
    /\ HandlerSendSnap(EvLearner)
    /\ Head(inQ'[EvLearner]).zxid = Msg.zxid
    /\ Advance

TraceHandlerQueueNewLeader ==
    /\ IsEvent("HandlerQueueNewLeader")
    /\ EvNode = MasterOf(EvLearner)
    /\ HandlerQueueNewLeader(EvLearner)
    /\ hPhase'[EvLearner] = "newleader"
    /\ Advance

TraceHandlerQueueUptodate ==
    /\ IsEvent("HandlerQueueUptodate")
    /\ EvNode = MasterOf(EvLearner)
    /\ HandlerQueueUptodate(EvLearner)
    /\ hPhase'[EvLearner] = "done"
    /\ Advance

-----------------------------------------------------------------------------
(* LEARNER SYNC. A wrapper checks phase' = "sync": the workload's sync never aborts,
   so an abort in the model is a mismatch with the implementation. *)

TraceLearnerReadDiff ==
    /\ IsEvent("LearnerReadDiff")
    /\ EvNode \in Learners
    /\ ValidateHead(EvNode)
    /\ LearnerReadDiff(EvNode)
    /\ ValidateDb(EvNode)
    /\ Advance

TraceLearnerReadSnap ==
    /\ IsEvent("LearnerReadSnap")
    /\ EvNode \in Learners
    /\ ValidateHead(EvNode)
    /\ LearnerReadSnap(EvNode)
    /\ ValidateDb(EvNode)
    /\ Advance

TraceLearnerReadTrunc ==
    /\ IsEvent("LearnerReadTrunc")
    /\ EvNode \in Learners
    /\ ValidateHead(EvNode)
    /\ LearnerReadTrunc(EvNode)
    /\ phase'[EvNode] = "sync"
    /\ ValidateDb(EvNode)
    /\ Advance

TraceLearnerSyncProposal ==
    /\ IsEvent("LearnerSyncProposal")
    /\ EvNode \in Learners
    /\ ValidateHead(EvNode)
    /\ LearnerSyncProposal(EvNode)
    /\ phase'[EvNode] = "sync"
    /\ lastQueued'[EvNode] = Msg.zxid
    /\ Len(notLogged'[EvNode]) = Msg.notLogged
    /\ Advance

TraceLearnerSyncCommit ==
    /\ IsEvent("LearnerSyncCommit")
    /\ EvNode \in Learners
    /\ ValidateHead(EvNode)
    /\ LearnerSyncCommit(EvNode)
    /\ phase'[EvNode] = "sync"
    /\ Len(notLogged'[EvNode]) = Msg.notLogged
    /\ Len(committedIds'[EvNode]) = Msg.committed
    /\ ValidateDb(EvNode)
    /\ Advance

TraceLearnerSyncInform ==
    /\ IsEvent("LearnerSyncInform")
    /\ EvNode \in Learners
    /\ ValidateHead(EvNode)
    /\ LearnerSyncInform(EvNode)
    /\ phase'[EvNode] = "sync"
    /\ lastQueued'[EvNode] = Msg.zxid
    /\ Len(notLogged'[EvNode]) = Msg.notLogged
    /\ Len(committedIds'[EvNode]) = Msg.committed
    /\ ValidateDb(EvNode)
    /\ Advance

TraceLearnerSyncNewLeader ==
    /\ IsEvent("LearnerSyncNewLeader")
    /\ EvNode \in Learners
    /\ LearnerSyncNewLeader(EvNode)
    /\ Len(notLogged'[EvNode]) = Msg.notLogged
    /\ snap'[EvNode] = Msg.snap
    /\ ValidateDb(EvNode)
    /\ Advance

TraceFollowerSyncUptodate ==
    /\ IsNodeEvent("FollowerSyncUptodate", F)
    /\ Len(notLogged[F]) = Msg.notLogged
    /\ Len(committedIds[F]) = Msg.committed
    /\ FollowerSyncUptodate
    /\ phase'[F] = "uptodate"
    /\ Advance

TraceObserverSyncUptodate ==
    /\ IsNodeEvent("ObserverSyncUptodate", O)
    /\ Len(notLogged[O]) = Msg.notLogged
    /\ Len(committedIds[O]) = Msg.committed
    /\ ObserverSyncUptodate
    /\ phase'[O] = "broadcast"
    /\ Advance

TraceFollowerStartObserverMaster ==
    /\ IsNodeEvent("FollowerStartObserverMaster", F)
    /\ FollowerStartObserverMaster
    /\ omUp'
    /\ Advance

-----------------------------------------------------------------------------
(* BROADCAST *)

TraceFollowerProcessProposal ==
    /\ IsNodeEvent("FollowerProcessProposal", F)
    /\ ValidateHead(F)
    /\ FollowerProcessProposal
    /\ Len(pendingTxns') = Msg.pending
    /\ Len(omProposed') = Msg.omProposed
    /\ Advance

\* cached is S1's question: did ObserverMaster know this commit's proposal?
TraceFollowerProcessCommit ==
    /\ IsNodeEvent("FollowerProcessCommit", F)
    /\ ValidateHead(F)
    /\ FollowerProcessCommit
    /\ phase'[F] = "broadcast"
    /\ (Len(omCommitted') > Len(omCommitted)) = Msg.cached
    /\ (Msg.cached /\ omActive) = Msg.informed
    /\ Len(pendingTxns') = Msg.pending
    /\ Advance

TraceObserverProcessInform ==
    /\ IsNodeEvent("ObserverProcessInform", O)
    /\ ValidateHead(O)
    /\ ObserverProcessInform
    /\ Advance

-----------------------------------------------------------------------------
(* APPLY AND THE TARGET *)

TraceApplyTree ==
    /\ IsEvent("ApplyTree")
    /\ ApplyTree(EvNode)
    /\ applyPending'[EvNode] = Msg.zxid
    /\ ValidateDb(EvNode)
    /\ Advance

TraceTargetCheck ==
    /\ IsEvent("TargetCheck")
    /\ applyPending[EvNode] = Msg.zxid
    /\ TargetCheck(EvNode)
    /\ targetFired' = Msg.fired
    /\ ValidateDb(EvNode)
    /\ Advance

-----------------------------------------------------------------------------
(* LIFECYCLE *)

TraceLearnerStart ==
    /\ IsEvent("LearnerStart")
    /\ EvNode \in Learners
    /\ LearnerStart(EvNode)
    /\ ValidateDb(EvNode)
    /\ Advance

\* MainThread.shutdown of a peer. It does not throw in the workload.
TracePeerShutdown ==
    /\ IsEvent("PeerShutdown")
    /\ \/ EvNode = F /\ FollowerCrash
       \/ EvNode = O /\ ObserverCrash
    /\ phase'[EvNode] = "down"
    /\ Advance

TraceObserverShutdown ==
    /\ IsNodeEvent("ObserverShutdown", O)
    /\ ObserverShutdown
    /\ ValidateDb(O)
    /\ Advance

-----------------------------------------------------------------------------

TraceInit == Init /\ l = 1

TraceNext ==
    \/ TraceClientPropose
    \/ TraceLeaderTryToCommit
    \/ TraceLeaderSyncFollower
    \/ TraceOmSyncObserver
    \/ TraceHandlerSendSnap
    \/ TraceHandlerQueueNewLeader
    \/ TraceHandlerQueueUptodate
    \/ TraceLearnerReadDiff
    \/ TraceLearnerReadSnap
    \/ TraceLearnerReadTrunc
    \/ TraceLearnerSyncProposal
    \/ TraceLearnerSyncCommit
    \/ TraceLearnerSyncInform
    \/ TraceLearnerSyncNewLeader
    \/ TraceFollowerSyncUptodate
    \/ TraceObserverSyncUptodate
    \/ TraceFollowerStartObserverMaster
    \/ TraceFollowerProcessProposal
    \/ TraceFollowerProcessCommit
    \/ TraceObserverProcessInform
    \/ TraceApplyTree
    \/ TraceTargetCheck
    \/ TraceLearnerStart
    \/ TracePeerShutdown
    \/ TraceObserverShutdown

traceAllVars == <<vars, l>>

TraceSpec == TraceInit /\ [][TraceNext]_traceAllVars /\ WF_traceAllVars(TraceNext)

\* The whole trace was consumed. Stuck at line N means event N cannot be matched.
TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [lProposed |-> lProposed, lCommitted |-> lCommitted, phase |-> phase, hPhase |-> hPhase,
     inQ |-> inQ, tree |-> tree, clog |-> clog, applyPending |-> applyPending,
     commitQ |-> commitQ, log |-> log, snap |-> snap, notLogged |-> notLogged,
     committedIds |-> committedIds, pendingTxns |-> pendingTxns, omUp |-> omUp,
     omProposed |-> omProposed, omCommitted |-> omCommitted, omActive |-> omActive,
     targetFired |-> targetFired, l |-> l,
     nextEvent |-> IF l <= Len(TraceLog) THEN TraceLog[l].event.name ELSE "END"]

================================================================================
