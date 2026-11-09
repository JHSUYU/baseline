------------------------------- MODULE base -------------------------------
(***************************************************************************)
(* hbase-adhoc-11 -- ad hoc coordination target                            *)
(*   AssignmentManager.preTransitCheck(RegionStateNode, State[])           *)
(*   AssignmentManager.java:769                                            *)
(*     if (!regionNode.isInState(expectedStates))                          *)
(*       throw new DoNotRetryRegionException(UNEXPECTED_STATE_REGION ...)  *)
(*                                                                         *)
(* Pinned tree: /bulk/specula-adhoc/hbase/cases/hbase-adhoc-11/hbase      *)
(*              @ 1790942bb2d46f41f1b4aed94db85e6f5bd18a1a                 *)
(*                                                                         *)
(* Category A (distributed / message passing): the HMaster opens and      *)
(* closes regions on RegionServers by remote procedures; RSs answer with   *)
(* reportRegionStateTransition.  The check itself is master-local.         *)
(*                                                                         *)
(* Path abbreviations used in every annotation (all under                  *)
(* hbase-server/src/main/java/org/apache/hadoop/hbase/ unless noted):      *)
(*   AM   master/assignment/AssignmentManager.java                         *)
(*   RSN  master/assignment/RegionStateNode.java                           *)
(*   TRSP master/assignment/TransitRegionStateProcedure.java               *)
(*   RRPB master/assignment/RegionRemoteProcedureBase.java                 *)
(*   ORP  master/assignment/OpenRegionProcedure.java                       *)
(*   CRP  master/assignment/CloseRegionProcedure.java                      *)
(*   STRP master/assignment/SplitTableRegionProcedure.java                 *)
(*   AMU  master/assignment/AssignmentManagerUtil.java                     *)
(*   RS_  master/assignment/RegionStates.java                              *)
(*   RSS  master/assignment/RegionStateStore.java                          *)
(*   TRP  master/procedure/TruncateRegionProcedure.java                    *)
(*   SCP  master/procedure/ServerCrashProcedure.java                       *)
(*   DTP  master/procedure/DisableTableProcedure.java                      *)
(*   ACTRP master/procedure/AbstractCloseTableRegionsProcedure.java        *)
(*   HM   master/HMaster.java                                              *)
(*   MRS  master/MasterRpcServices.java                                    *)
(*   RSG  rsgroup/RSGroupInfoManagerImpl.java                              *)
(*   ARH  regionserver/handler/AssignRegionHandler.java                    *)
(*   URH  regionserver/handler/UnassignRegionHandler.java                  *)
(*   SMP  hbase-procedure/.../procedure2/StateMachineProcedure.java        *)
(*   PE   hbase-procedure/.../procedure2/ProcedureExecutor.java            *)
(*   RDP  hbase-procedure/.../procedure2/RemoteProcedureDispatcher.java    *)
(*                                                                         *)
(* Scenarios (modeling-brief.md section 2):                                *)
(*   S1 split puts the region in SPLITTING with no TRSP; leaks L1 (abort   *)
(*      off-by-one) and L2 (CLOSED parent rolled back to OPEN)             *)
(*   S2 truncate's forced detach leaves a TRSP running unattached          *)
(*   S3 internal callers select regions by SSN membership / location       *)
(*                                                                         *)
(* Production semantics: Java `assert` is disabled in production          *)
(* (bin/hbase has no -ea), so RSN.setProcedure / unsetProcedure ownership *)
(* asserts (RSN:214, RSN:221) are NOT enforced here.                       *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Regions,                 \* regions of the workload table
    Servers,                 \* RegionServer ServerNames
    NoServer,                \* null ServerName
    MaxPid,                  \* bound on procedure ids handed out by the PE (model bound)
    OperatorWaitsForSplit,   \* environment flag, brief section 5 (S1 hunt)
    MaxRsgRetry              \* hbase.rsgroup.move.max.retry (RSG:139-142), scaled down

ASSUME NoServer \notin Servers
ASSUME MaxPid \in Nat /\ MaxRsgRetry \in Nat
ASSUME OperatorWaitsForSplit \in BOOLEAN

NoProc     == 0           \* RSN.procedure == null / TRSP.remoteProc == null
OrphanProc == -1          \* a TRSP attached to the RSN but never submitted (see SplitCloseParentRegion)
Pids       == 1..MaxPid   \* PE.nextProcId()

(***************************************************************************)
(* Region states reachable in this model (RegionState.State).              *)
(* MERGING/MERGING_NEW/SPLITTING_NEW/FAILED_OPEN are not reachable in the *)
(* modeled scope (brief 3.2: merge optional; daughters excluded; FAILED_OPEN*)
(* needs non-default hbase.assignment.maximum.attempts, AM:152-153).       *)
(***************************************************************************)
RegionStates == {"OFFLINE", "OPENING", "OPEN", "CLOSING", "CLOSED",
                 "SPLITTING", "SPLIT", "ABNORMALLY_CLOSED"}

\* AM:2181 STATES_EXPECTED_ON_ASSIGN, AM:2184 STATES_EXPECTED_ON_UNASSIGN_OR_MOVE
ExpectedOnAssign         == {"CLOSED", "OFFLINE"}
ExpectedOnUnassignOrMove == {"OPEN"}
ExpectedStates(op) == IF op = "assign" THEN ExpectedOnAssign ELSE ExpectedOnUnassignOrMove

Ops     == {"assign", "unassign", "move"}
Callers == {"operator", "balancer", "decom", "rsg"}

\* TRSP:149-167 setInitialAndLastState
TrspTypes == {"ASSIGN", "UNASSIGN", "MOVE"}
TrspPcs   == {"NONE", "GET_ASSIGN_CANDIDATE", "OPEN", "CONFIRM_OPENED",
              "CLOSE", "CONFIRM_CLOSED", "DONE"}
InitialPc(t) == IF t = "ASSIGN" THEN "GET_ASSIGN_CANDIDATE" ELSE "CLOSE"
LastPc(t)    == IF t = "UNASSIGN" THEN "CONFIRM_CLOSED" ELSE "CONFIRM_OPENED"

\* RegionRemoteProcedureBaseState
RrpbStates == {"NONE", "DISPATCH", "REPORT_SUCCEED", "DISPATCH_FAIL", "SERVER_CRASH", "DONE"}

(***************************************************************************)
(* SplitTableRegionState.  CREATE_DAUGHTER_REGIONS stands for the three   *)
(* file-system/hook steps CREATE_DAUGHTER_REGIONS, WRITE_MAX_SEQUENCE_ID_  *)
(* FILE and PRE_OPERATION_BEFORE_META (STRP:318-330): their rollbacks      *)
(* (STRP:382-387) never touch the RegionStateNode, and every abort landing *)
(* in any of them still rolls back through CHECK_CLOSED_REGIONS.           *)
(* PRE_OPERATION_AFTER_META stands for PRE_OPERATION_AFTER_META,           *)
(* OPEN_CHILD_REGIONS and POST_OPERATION (STRP:335-345; daughters are not  *)
(* modeled, brief 3.2).                                                    *)
(***************************************************************************)
SplitStates == {"PREPARE", "PRE_OPERATION", "CLOSE_PARENT_REGION", "CHECK_CLOSED_REGIONS",
                "CREATE_DAUGHTER_REGIONS", "UPDATE_META", "PRE_OPERATION_AFTER_META", "EOF"}

\* STRP:418-431 isRollbackSupported
SplitRollbackSupported(s) == s \notin {"UPDATE_META", "PRE_OPERATION_AFTER_META", "EOF"}

MsgTypes == {"OPEN_REQ", "CLOSE_REQ", "REPORT"}
Codes    == {"OPENED", "CLOSED", "NONE"}

DummyRegion == CHOOSE r \in Regions : TRUE

NoTrsp    == [pc |-> "NONE", region |-> DummyRegion, type |-> "ASSIGN", force |-> FALSE,
              cand |-> NoServer, child |-> NoProc, waitAssign |-> FALSE, parent |-> NoProc]
NoRrpb    == [st |-> "NONE", region |-> DummyRegion, kind |-> "OPEN", target |-> NoServer,
              sent |-> FALSE, parent |-> NoProc]
NoSplit   == [st |-> "none", pid |-> NoProc, region |-> DummyRegion, stack |-> <<>>,
              execs |-> 0, aborted |-> FALSE, child |-> NoProc]
NoTrunc   == [st |-> "none", pid |-> NoProc, region |-> DummyRegion, child |-> NoProc]
NoScp     == [st |-> "none", pid |-> NoProc, todo |-> {}, children |-> {}]
NoDisable == [st |-> "none", pid |-> NoProc, children |-> {}]
NoPlan    == [st |-> "none", region |-> DummyRegion, src |-> NoServer, dest |-> NoServer]
NoDecom   == [st |-> "none", server |-> NoServer, todo |-> <<>>, dests |-> {}]
NoRsg     == [st |-> "none", server |-> NoServer, todo |-> <<>>, failed |-> {},
              retry |-> 0, waiting |-> {}]
IdleOp    == [kind |-> "idle", pid |-> NoProc]

VARIABLES
    \* ---- master in-memory RegionStateNode (RSN:81-105) ----
    rsnState,         \* RSN.state            (RSN:97)
    rsnLoc,           \* RSN.regionLocation   (RSN:88)
    rsnProc,          \* RSN.procedure        (RSN:87): NoProc | OrphanProc | pid
    lastHost,         \* RSN.lastHost         (RSN:92)
    activeTrspCount,  \* RSN.activeTransitProcedureCount (RSN:73, 216, 222)
    \* ---- ServerStateNode / ServerManager ----
    serverState,      \* SSN.state (ServerStateNode:40); "GONE" = RS_.removeServer (RS_:686-688)
    ssn,              \* SSN.regions (ServerStateNode:36)
    draining,         \* ServerManager drain list (HM:4158)
    \* ---- persisted state: hbase:meta + table state ----
    metaState,        \* info:state column              (RSS:220-223)
    metaLoc,          \* info:sn / info:server columns  (RSS:196-219): last non-null location (sticky)
    metaSplitParent,  \* RegionInfo offline+split written at the split PONR (RSS:376-377)
    tableState,       \* TableStateManager: ENABLED | DISABLING | DISABLED
    \* ---- RegionServer side ----
    rsOnline,         \* RS process alive
    rsRegions,        \* regions online on the RS (HRegionServer.onlineRegions)
    \* ---- network: master -> RS open/close requests, RS -> master reports ----
    msgs,
    \* ---- procedures ----
    trsp,             \* [Pids -> TRSP record]
    rrpb,             \* [Pids -> RegionRemoteProcedureBase record]
    nextPid,          \* PE procId allocator
    schedLock,        \* MasterProcedureScheduler region exclusive lock owner (pid | NoProc)
    split,            \* the SplitTableRegionProcedure (at most one at a time)
    trunc,            \* the TruncateRegionProcedure (at most one at a time)
    scp,              \* [Servers -> ServerCrashProcedure record]
    disable,          \* the DisableTableProcedure + CloseTableRegionsProcedure
    \* ---- callers that reach preTransitCheck ----
    opWait,           \* the operator's single outstanding request (brief section 1)
    balPlan,          \* a balancer RegionPlan computed but not yet executed
    decom,            \* HM.decommissionRegionServers offload loop
    rsg,              \* RSGroup moveRegionsBetweenGroups loop
    \* ---- oracle ----
    targetFired       \* TRUE once AM:769 throws for an in-model request

rsnVars     == <<rsnState, rsnLoc, rsnProc, lastHost, activeTrspCount>>
serverVars  == <<serverState, ssn, draining>>
metaVars    == <<metaState, metaLoc, metaSplitParent, tableState>>
rsVars      == <<rsOnline, rsRegions>>
procVars    == <<trsp, rrpb, nextPid, schedLock>>
cplxVars    == <<split, trunc, scp, disable>>
callerVars  == <<opWait, balPlan, decom, rsg>>
vars == <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, callerVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
Last(s)  == s[Len(s)]
Front(s) == SubSeq(s, 1, Len(s) - 1)

RECURSIVE SetToSeq(_)
SetToSeq(S) == IF S = {} THEN <<>>
               ELSE LET x == CHOOSE x \in S : TRUE IN <<x>> \o SetToSeq(S \ {x})

\* all orderings of a (small) set; used for loops whose iteration order is unspecified
Orderings(S) == {f \in [1..Cardinality(S) -> S] :
                    \A i, j \in 1..Cardinality(S) : i # j => f[i] # f[j]}

Req(kind, s, r, c)  == [type |-> IF kind = "OPEN" THEN "OPEN_REQ" ELSE "CLOSE_REQ",
                        srv |-> s, region |-> r, pid |-> c, code |-> "NONE"]
Report(s, r, code, c) == [type |-> "REPORT", srv |-> s, region |-> r, pid |-> c, code |-> code]

NewTrsp(r, t, force, cand, parent) ==
    [pc |-> InitialPc(t), region |-> r, type |-> t, force |-> force, cand |-> cand,
     child |-> NoProc, waitAssign |-> FALSE, parent |-> parent]
NewRrpb(r, kind, target, parent) ==
    [st |-> "DISPATCH", region |-> r, kind |-> kind, target |-> target, sent |-> FALSE,
     parent |-> parent]

\* createDestinationServersList: online (not expired) and not draining
AssignableServers == {s \in Servers : serverState[s] = "ONLINE" /\ s \notin draining}

\* RSS.generateUpdateRegionLocationPut (RSS:180-226): the state column is always written;
\* the location columns are written only for a non-null location (RSS:196-219), so a row
\* written with a null location keeps its previous sn/server cells.
MetaWrite(r, st, loc) ==
    /\ metaState' = [metaState EXCEPT ![r] = st]
    /\ metaLoc'   = [metaLoc EXCEPT ![r] = IF loc = NoServer THEN @ ELSE loc]

SplitActive == split.st \in {"ready", "inStep", "waitChild", "rollback"}

\* SMP:274-276 getCurrentState
SplitCurrentState == IF split.stack = <<>> THEN "PREPARE" ELSE Last(split.stack)

\* The operator's synchronous Admin call has returned (brief section 1: at most one
\* outstanding request).  move/assign/unassign wait for the TRSP (HM:2490-2497,
\* AM:829, AM:869); truncate/disable wait for their procedure; decommission returns
\* after its loop (HM:4163-4176); RSGroup moveServers after waitForRegionMovement.
OperatorIdle ==
    CASE opWait.kind = "idle"    -> TRUE
      [] opWait.kind = "trsp"    -> trsp[opWait.pid].pc = "DONE"
      [] opWait.kind = "trunc"   -> trunc.st = "done"
      [] opWait.kind = "disable" -> disable.st = "done"
      [] opWait.kind = "decom"   -> decom.st = "done"
      [] opWait.kind = "rsg"     -> rsg.st = "done"

(***************************************************************************)
(* Well-formed operator request (brief section 1).  A request is a         *)
(* designed rejection only if it is invalid for a stable state the caller  *)
(* can see in hbase:meta.  Designed rejections are never generated in MC   *)
(* (Case B); the trace spec accepts them through OperatorRejectedRequest.  *)
(***************************************************************************)
DesignedRejection(op, r) ==
    \/ metaSplitParent[r]
    \/ op = "assign" /\ metaState[r] = "OPEN"
    \/ op # "assign" /\ metaState[r] \in {"CLOSED", "OFFLINE"}

WellFormed(op, r) ==
    /\ ~DesignedRejection(op, r)
    /\ OperatorWaitsForSplit => ~SplitActive

-----------------------------------------------------------------------------
(***************************************************************************)
(* MasterProcedureScheduler region lock.  Region procedures (TRSP, split, *)
(* truncate) hold it for their whole life (holdLock=true,                  *)
(* AbstractStateMachineRegionProcedure:82-84).  A child has lock access   *)
(* when its parent holds the lock (LockAndQueue.hasLockAccess, 70-90).     *)
(* RRPBs take no scheduler lock (no acquireLock override).  Acquisition   *)
(* happens at a procedure's first execution; the order among waiting     *)
(* procedures is nondeterministic (brief 2, S1 L2).                        *)
(***************************************************************************)
ParentHasLock(p) == trsp[p].parent # NoProc /\ schedLock[trsp[p].region] = trsp[p].parent
TrspCanLock(p)   == LET r == trsp[p].region IN
                       \/ schedLock[r] = p
                       \/ schedLock[r] = NoProc
                       \/ ParentHasLock(p)
TrspLockAfter(p) == LET r == trsp[p].region IN
                       [schedLock EXCEPT ![r] = IF ParentHasLock(p) THEN @ ELSE p]
TrspLockReleased(p) == LET r == trsp[p].region IN
                       [schedLock EXCEPT ![r] = IF @ = p THEN NoProc ELSE @]

\* a TRSP step can run: suspended neither on its RRPB child nor on the assign event
TrspRunnable(p) ==
    /\ trsp[p].pc \notin {"NONE", "DONE"}
    /\ trsp[p].child = NoProc
    /\ ~trsp[p].waitAssign
    /\ TrspCanLock(p)

-----------------------------------------------------------------------------
(***************************************************************************)
(* TARGET: AM.preTransitCheck (AM:762-774), guards in code order, under    *)
(* the RSN lock held by every caller (AM:787/861/881).                     *)
(***************************************************************************)
CheckOutcome(r, op) ==
    IF rsnProc[r] # NoProc                         \* AM:764-766 HBaseIOException (retriable)
      THEN "IN_TRANSITION"
    ELSE IF rsnState[r] \notin ExpectedStates(op)  \* AM:768-769 RSN.isInState (RSN:155-160) -- TARGET
      THEN "UNEXPECTED_STATE"
    ELSE IF tableState \in {"DISABLED", "DISABLING"} \* AM:771-772, AM:563-566
      THEN "TABLE_DISABLED"
    ELSE "PASS"

\* TRSP factory used on the PASS continuation
\*   assign   AM:800-801 TRSP.assign(env, ri, null)            (TRSP:730-739)
\*   unassign AM:864-865 TRSP.unassign(env, ri)                (TRSP:741-744)
\*   move     AM:885-886 TRSP.move(env, ri, target): forceNewPlan = (target == null) (TRSP:757-761)
TrspTypeOf(op) == CASE op = "assign" -> "ASSIGN" [] op = "unassign" -> "UNASSIGN" [] op = "move" -> "MOVE"

RsgDests == {s \in Servers : s # rsg.server /\ serverState[s] = "ONLINE"}

\* "the code path that reaches the check", per caller
CallerAt(c, r, op, d) ==
    CASE c = "operator" ->
            \* MRS.assignRegion (MRS:730-760) -> AM.assign (AM:827-835) -> createAssignProcedure (AM:784-807, override=false)
            \* MRS.unassignRegion (MRS:1847-1880) -> AM.unassign (AM:855-871)
            \* MRS.moveRegion (MRS:1598-1619) -> HM.move (HM:2414-2507) -> AM.createMoveRegionProcedure (AM:873-891)
            /\ OperatorIdle
            /\ WellFormed(op, r)
            /\ IF op = "move"
                 THEN /\ d \in Servers
                      /\ serverState[d] = "ONLINE"
                      /\ d # rsnLoc[r]            \* HM:2463-2467 same-server move is skipped before the check
                 ELSE d = NoServer
      [] c = "balancer" ->
            \* HM.executeRegionPlansWithThrottling (HM:2242-2258) -> AM.balance (AM:904-913) -> moveAsync (AM:898-902)
            /\ balPlan.st = "planned"
            /\ balPlan.region = r /\ op = "move" /\ d = balPlan.dest
            /\ rsnLoc[r] = balPlan.src           \* AM:905-911 only the location is re-checked (getRegionAssignments, RS_:504-510)
      [] c = "decom" ->
            \* HM.decommissionRegionServers offload loop (HM:4165-4175) -> moveAsync
            /\ decom.st = "running"
            /\ decom.todo # <<>> /\ Head(decom.todo) = r
            /\ op = "move" /\ d \in decom.dests   \* HM:4168 randomAssignment over destServers
      [] c = "rsg" ->
            \* RSG.moveRegionsBetweenGroups (RSG:1022-1046) -> moveAsync
            /\ rsg.st = "running"
            /\ rsg.todo # <<>> /\ Head(rsg.todo) = r
            /\ op = "move" /\ d \in RsgDests      \* RSG:1029-1034

CallerAfter(c, r, out, p) ==
    CASE c = "operator" ->
            \* a failing check returns the exception to the client; a pass waits for the TRSP
            /\ opWait' = IF out = "PASS" THEN [kind |-> "trsp", pid |-> p] ELSE IdleOp
            /\ UNCHANGED <<balPlan, decom, rsg>>
      [] c = "balancer" ->
            \* HM:2249-2252 HBaseIOException is caught, WARN, plan skipped
            /\ balPlan' = NoPlan
            /\ UNCHANGED <<opWait, decom, rsg>>
      [] c = "decom" ->
            \* HM:4167-4174 no try/catch: any exception aborts the remaining offload
            /\ decom' = IF out = "PASS"
                          THEN [decom EXCEPT !.todo = Tail(decom.todo),
                                             !.st = IF Len(decom.todo) = 1 THEN "done" ELSE "running"]
                          ELSE [decom EXCEPT !.todo = <<>>, !.st = "done"]
            /\ UNCHANGED <<opWait, balPlan, rsg>>
      [] c = "rsg" ->
            \* RSG:1036-1044 per-region catch: failedRegions, retried later
            /\ rsg' = [rsg EXCEPT !.todo = Tail(rsg.todo),
                                  !.failed = IF out = "PASS" THEN rsg.failed ELSE rsg.failed \cup {r},
                                  !.waiting = IF out = "PASS" THEN rsg.waiting \cup {p} ELSE rsg.waiting]
            /\ UNCHANGED <<opWait, balPlan, decom>>

(***************************************************************************)
(* TargetCheck: the code path reaching AM:769 for caller c, evaluating the *)
(* guard exactly as the code does, and the normal continuation on PASS:   *)
(* setProcedure (RSN:213-218) of a new TRSP, submitted to the PE.          *)
(***************************************************************************)
TargetCheck(c, r, op, d) ==
    /\ CallerAt(c, r, op, d)
    /\ LET out == CheckOutcome(r, op)
           p   == nextPid
       IN
       /\ (out = "PASS" => nextPid \in Pids)
       /\ targetFired' = (out = "UNEXPECTED_STATE")     \* AM:769 throw new DoNotRetryRegionException
       /\ IF out = "PASS"
            THEN \* AM:884 regionNode.checkOnline() (RSN:318-335) for move: state is OPEN here and the
                 \* in-memory RegionInfo split/offline flags are never set (AM:2380-2387), so it passes.
                 /\ trsp' = [trsp EXCEPT ![p] = NewTrsp(r, TrspTypeOf(op), op = "move" /\ d = NoServer,
                                                        d, NoProc)]
                 /\ rsnProc' = [rsnProc EXCEPT ![r] = p]
                 /\ activeTrspCount' = activeTrspCount + 1
                 /\ nextPid' = nextPid + 1
            ELSE UNCHANGED <<trsp, rsnProc, activeTrspCount, nextPid>>
       /\ CallerAfter(c, r, out, p)
    /\ UNCHANGED <<rsnState, rsnLoc, lastHost, serverVars, metaVars, rsVars, msgs,
                   rrpb, schedLock, cplxVars>>

(***************************************************************************)
(* Trace-only: an operator request that is a designed rejection (brief     *)
(* 3.1 OperatorRejectedRequest; the workload's two moves at                *)
(* TestRegionMove.java:107 and :120).  preTransitCheck takes a failing     *)
(* branch; nothing changes; targetFired is NOT set.  Not in Next.          *)
(***************************************************************************)
OperatorRejectedRequest(r, op, d) ==
    /\ OperatorIdle
    /\ DesignedRejection(op, r)
    /\ CheckOutcome(r, op) # "PASS"
    /\ IF op = "move" THEN d \in Servers /\ d # rsnLoc[r] ELSE d = NoServer
    /\ opWait' = IdleOp
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars,
                   balPlan, decom, rsg, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* TransitRegionStateProcedure (TRSP).  One action per executeFromState    *)
(* case (TRSP:482-531).  No step checks that the TRSP is still the one     *)
(* attached to the RSN (TRSP:448-531): a detached TRSP keeps running.      *)
(***************************************************************************)

\* GET_ASSIGN_CANDIDATE: TRSP:488-506 -> queueAssign (TRSP:246-278)
TrspGetAssignCandidate(p) ==
    LET t == trsp[p]
        r == t.region
    IN
    /\ t.pc = "GET_ASSIGN_CANDIDATE"
    /\ TrspRunnable(p)
    \* TRSP:491-504 replica sanity check: default replica only -> skipped
    /\ rsnLoc' = [rsnLoc EXCEPT ![r] =
                    IF t.force THEN NoServer                          \* TRSP:249-251
                    ELSE IF t.cand # NoServer THEN t.cand             \* TRSP:253-255
                    ELSE IF lastHost[r] # NoServer THEN lastHost[r]   \* TRSP:256-261
                    ELSE @]
    \* TRSP:262-269 isForceRegionRetainment() is false by default -> skipped
    \* TRSP:273-277 AM.queueAssign; setNextState(OPEN); suspend on the region's ProcedureEvent
    /\ trsp' = [trsp EXCEPT ![p].pc = "OPEN", ![p].waitAssign = TRUE]
    /\ schedLock' = TrspLockAfter(p)
    /\ UNCHANGED <<rsnState, rsnProc, lastHost, activeTrspCount, serverVars, metaVars, rsVars,
                   msgs, rrpb, nextPid, cplxVars, callerVars, targetFired>>

\* AM.processAssignQueue -> acceptPlan (AM:2641-2668): the assignment thread sets the
\* location WITHOUT the RSN lock (AM:2655) and wakes the event (AM:2668).  The
\* retain/round-robin balancer choice (AM:2603-2633) is abstracted to any destination.
AssignQueueAcceptPlan(p, s) ==
    LET r == trsp[p].region IN
    /\ trsp[p].pc = "OPEN"
    /\ trsp[p].waitAssign
    /\ s \in AssignableServers
    /\ rsnLoc' = [rsnLoc EXCEPT ![r] = s]
    /\ trsp' = [trsp EXCEPT ![p].waitAssign = FALSE]
    /\ UNCHANGED <<rsnState, rsnProc, lastHost, activeTrspCount, serverVars, metaVars, rsVars,
                   msgs, rrpb, nextPid, schedLock, cplxVars, callerVars, targetFired>>

\* OPEN: TRSP:293-311
TrspOpen(p) ==
    LET t   == trsp[p]
        r   == t.region
        loc == rsnLoc[r]
        c   == nextPid
    IN
    /\ t.pc = "OPEN"
    /\ TrspRunnable(p)
    /\ schedLock' = TrspLockAfter(p)
    /\ IF loc = NoServer
         THEN \* TRSP:302-306 no location: back to GET_ASSIGN_CANDIDATE, throw -> backoff (TRSP:520-529)
              /\ trsp' = [trsp EXCEPT ![p].pc = "GET_ASSIGN_CANDIDATE"]
              /\ UNCHANGED <<rsnState, ssn, metaState, metaLoc, rrpb, nextPid>>
         ELSE \* AM.regionOpening (AM:2212-2232): transitStateAndUpdate(OPENING) with NO expected
              \* states (AM:2191-2209), persisted; then addRegion to the SSN (AM:2217-2228)
              /\ c \in Pids
              /\ rsnState' = [rsnState EXCEPT ![r] = "OPENING"]
              /\ MetaWrite(r, "OPENING", loc)
              /\ ssn' = IF serverState[loc] # "GONE" THEN [ssn EXCEPT ![loc] = @ \cup {r}] ELSE ssn
              \* openRegionAfterUpdatingMeta (TRSP:288-291): child OpenRegionProcedure, RRPB:84-89 attachRemoteProc
              /\ rrpb' = [rrpb EXCEPT ![c] = NewRrpb(r, "OPEN", loc, p)]
              /\ trsp' = [trsp EXCEPT ![p].pc = "CONFIRM_OPENED", ![p].child = c]
              /\ nextPid' = nextPid + 1
    /\ UNCHANGED <<rsnLoc, rsnProc, lastHost, activeTrspCount, serverState, draining,
                   metaSplitParent, tableState, rsVars, msgs, cplxVars, callerVars, targetFired>>

\* the TRSP finishes: unsetProcedure (RSN:220-224; ownership assert RSN:221 is off in production,
\* so the RSN is cleared whichever TRSP is attached) and the PE releases the region lock.
TrspFinishVars(p) ==
    LET r == trsp[p].region IN
    /\ rsnProc' = [rsnProc EXCEPT ![r] = NoProc]
    /\ activeTrspCount' = activeTrspCount - 1
    /\ trsp' = [trsp EXCEPT ![p].pc = "DONE"]
    /\ schedLock' = TrspLockReleased(p)

\* CONFIRM_OPENED: TRSP:320-374
TrspConfirmOpened(p) ==
    LET t == trsp[p]
        r == t.region
    IN
    /\ t.pc = "CONFIRM_OPENED"
    /\ TrspRunnable(p)
    /\ IF rsnState[r] = "OPEN"
         THEN IF LastPc(t.type) = "CONFIRM_OPENED"
                THEN \* TRSP:330-335 last state: unsetProcedure, NO_MORE_STATE
                     /\ TrspFinishVars(p)
                     /\ UNCHANGED <<rsnLoc, ssn>>
                ELSE \* TRSP:336-342 not the last state: close it again
                     /\ trsp' = [trsp EXCEPT ![p].pc = "CLOSE"]
                     /\ schedLock' = TrspLockAfter(p)
                     /\ UNCHANGED <<rsnLoc, rsnProc, activeTrspCount, ssn>>
         ELSE \* TRSP:345-373 failed open.  maxAttempts = Integer.MAX_VALUE by default (AM:152-153),
              \* so never give up: regionFailedOpen(giveUp=false) (AM:2240-2245) removes the region from
              \* the SSN; forceNewPlan; location null; GET_ASSIGN_CANDIDATE.
              /\ ssn' = IF rsnLoc[r] # NoServer THEN [ssn EXCEPT ![rsnLoc[r]] = @ \ {r}] ELSE ssn
              /\ rsnLoc' = [rsnLoc EXCEPT ![r] = NoServer]
              /\ trsp' = [trsp EXCEPT ![p].force = TRUE, ![p].pc = "GET_ASSIGN_CANDIDATE"]
              /\ schedLock' = TrspLockAfter(p)
              /\ UNCHANGED <<rsnProc, activeTrspCount>>
    /\ UNCHANGED <<rsnState, lastHost, serverState, draining, metaVars, rsVars, msgs, rrpb,
                   nextPid, cplxVars, callerVars, targetFired>>

\* CLOSE: TRSP:389-407
TrspClose(p) ==
    LET t   == trsp[p]
        r   == t.region
        loc == rsnLoc[r]
        c   == nextPid
    IN
    /\ t.pc = "CLOSE"
    /\ TrspRunnable(p)
    /\ schedLock' = TrspLockAfter(p)
    /\ IF rsnState[r] \in {"OPEN", "CLOSING", "SPLITTING"}     \* TRSP:397 (MERGING not modeled)
         THEN \* AM.regionClosing (AM:2265-2276): transitStateAndUpdate(CLOSING,
              \* STATES_EXPECTED_ON_CLOSING={OPEN,CLOSING,SPLITTING,MERGING} AM:2169-2173), persisted
              /\ c \in Pids
              /\ rsnState' = [rsnState EXCEPT ![r] = "CLOSING"]
              /\ MetaWrite(r, "CLOSING", loc)
              \* closeRegionAfterUpdatingMeta (TRSP:376-387): CloseRegionProcedure to regionNode.getRegionLocation()
              /\ rrpb' = [rrpb EXCEPT ![c] = NewRrpb(r, "CLOSE", loc, p)]
              /\ trsp' = [trsp EXCEPT ![p].pc = "CONFIRM_CLOSED", ![p].child = c]
              /\ nextPid' = nextPid + 1
              /\ UNCHANGED rsnLoc
         ELSE \* TRSP:402-406 not closable: forceNewPlan, location null, GET_ASSIGN_CANDIDATE
              /\ trsp' = [trsp EXCEPT ![p].force = TRUE, ![p].pc = "GET_ASSIGN_CANDIDATE"]
              /\ rsnLoc' = [rsnLoc EXCEPT ![r] = NoServer]
              /\ UNCHANGED <<rsnState, metaState, metaLoc, rrpb, nextPid>>
    /\ UNCHANGED <<rsnProc, lastHost, activeTrspCount, serverVars, metaSplitParent, tableState,
                   rsVars, msgs, cplxVars, callerVars, targetFired>>

\* CONFIRM_CLOSED: TRSP:409-446
TrspConfirmClosed(p) ==
    LET t == trsp[p]
        r == t.region
    IN
    /\ t.pc = "CONFIRM_CLOSED"
    /\ TrspRunnable(p)
    /\ IF rsnState[r] = "CLOSED" /\ LastPc(t.type) = "CONFIRM_CLOSED"
         THEN TrspFinishVars(p)                                   \* TRSP:411-417
         ELSE /\ trsp' = [trsp EXCEPT ![p].pc =
                            IF rsnState[r] = "CLOSED" THEN "GET_ASSIGN_CANDIDATE"   \* TRSP:418-420 move/reopen
                            ELSE IF rsnState[r] = "CLOSING" THEN "CLOSE"            \* TRSP:422-428 retry with backoff
                            ELSE "GET_ASSIGN_CANDIDATE"]                            \* TRSP:429-445 ABNORMALLY_CLOSED (assert :435), default replica
              /\ schedLock' = TrspLockAfter(p)
              /\ UNCHANGED <<rsnProc, activeTrspCount>>
    /\ UNCHANGED <<rsnState, rsnLoc, lastHost, serverVars, metaVars, rsVars, msgs, rrpb, nextPid,
                   cplxVars, callerVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* RegionRemoteProcedureBase (OpenRegionProcedure / CloseRegionProcedure) *)
(* and the RS side.  RRPBs take only the RSN lock (RRPB:301-327).          *)
(***************************************************************************)

\* RRPB:335-351 REGION_REMOTE_PROCEDURE_DISPATCH
RrpbDispatch(c) ==
    LET b == rrpb[c]
        s == b.target
    IN
    /\ b.st = "DISPATCH"
    /\ ~b.sent
    /\ IF s = NoServer \/ serverState[s] # "ONLINE"
         THEN \* RDP:163-179 null key -> NullTargetServerDispatchException; node removed on expiry ->
              \* NoServerDispatchException; RRPB:341-346 give up: unattach and complete
              /\ rrpb' = [rrpb EXCEPT ![c].st = "DONE"]
              /\ trsp' = [trsp EXCEPT ![b.parent].child = NoProc]       \* TRSP:592-595 unattachRemoteProc
              /\ UNCHANGED msgs
         ELSE \* RRPB:340 addOperationToNode; RRPB:348-350 suspend until the report
              /\ rrpb' = [rrpb EXCEPT ![c].sent = TRUE]
              /\ msgs' = msgs \cup {Req(b.kind, s, b.region, c)}
              /\ UNCHANGED trsp
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, nextPid, schedLock, cplxVars,
                   callerVars, targetFired>>

\* RS: AssignRegionHandler.process (ARH:98-160)
RsHandleOpen(m) ==
    /\ m \in msgs
    /\ m.type = "OPEN_REQ"
    /\ rsOnline[m.srv]
    /\ IF m.region \in rsRegions[m.srv]
         THEN \* ARH:104-113 already online: no report
              /\ msgs' = msgs \ {m}
              /\ UNCHANGED rsRegions
         ELSE \* ARH:132-152 open; postOpenDeployTasks reports OPENED with openProcId (ARH:150-151)
              /\ rsRegions' = [rsRegions EXCEPT ![m.srv] = @ \cup {m.region}]
              /\ msgs' = (msgs \ {m}) \cup {Report(m.srv, m.region, "OPENED", m.pid)}
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsOnline, procVars, cplxVars, callerVars, targetFired>>

\* RS: UnassignRegionHandler.process (URH:95-158)
RsHandleClose(m) ==
    /\ m \in msgs
    /\ m.type = "CLOSE_REQ"
    /\ rsOnline[m.srv]
    /\ IF m.region \notin rsRegions[m.srv]
         THEN \* URH:114-120 not online: return without reporting
              /\ msgs' = msgs \ {m}
              /\ UNCHANGED rsRegions
         ELSE \* URH:139-153 close, remove, report CLOSED with closeProcId
              /\ rsRegions' = [rsRegions EXCEPT ![m.srv] = @ \ {m.region}]
              /\ msgs' = (msgs \ {m}) \cup {Report(m.srv, m.region, "CLOSED", m.pid)}
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsOnline, procVars, cplxVars, callerVars, targetFired>>

\* RPC to the RS failed: RSProcedureDispatcher -> RRPB.remoteCallFailed (RRPB:122-149).
\* Enabled when the RS is dead (connection fails) or, with injected = TRUE, as the
\* "RPC failure on open/close dispatch" fault (brief section 1).
RemoteCallFailed(m, injected) ==
    /\ m \in msgs
    /\ m.type \in {"OPEN_REQ", "CLOSE_REQ"}
    /\ injected \/ ~rsOnline[m.srv]
    /\ msgs' = msgs \ {m}
    /\ rrpb' = IF serverState[m.srv] # "ONLINE"        \* RRPB:126-131 server not online: SCP will interrupt us
                 THEN rrpb
               ELSE IF rrpb[m.pid].st # "DISPATCH"     \* RRPB:132-138 already woken
                 THEN rrpb
               ELSE [rrpb EXCEPT ![m.pid].st = "DISPATCH_FAIL"]   \* RRPB:144-145
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, trsp, nextPid, schedLock, cplxVars,
                   callerVars, targetFired>>

(***************************************************************************)
(* Master receives an RS report:                                           *)
(* AM.reportRegionStateTransition (AM:1260-1303) -> updateRegionTransition *)
(* (AM:1305-1342, RSN lock) -> reportTransition (AM:1344-1354) ->          *)
(* TRSP.reportTransition (TRSP:544-563) -> RRPB.reportTransition           *)
(* (RRPB:209-245).  Reports are delivered only to the ATTACHED TRSP.       *)
(***************************************************************************)
MasterReportTransition(m) ==
    LET r   == m.region
        p   == rsnProc[r]
        c   == m.pid
        loc == rsnLoc[r]
        accepted ==
            /\ serverState[m.srv] = "ONLINE"   \* AM:1265-1270 no server node / AM:1281-1297 "You are dead"
            /\ p # NoProc                       \* AM:1347-1350 -> false -> WARN "No matching procedure" (AM:1335)
            /\ p # OrphanProc                   \* never-submitted TRSP: remoteProc == null (TRSP:546-552)
            /\ trsp[p].child # NoProc           \* TRSP:546-552 no outstanding remote procedure
            /\ trsp[p].child = c                \* TRSP:555-561 pid mismatch -> ignore
            /\ rrpb[c].st = "DISPATCH"          \* RRPB:211-214 should be a retry
    IN
    /\ m \in msgs
    /\ m.type = "REPORT"
    /\ msgs' = msgs \ {m}
    /\ IF ~accepted
         THEN UNCHANGED <<rsnState, rsnLoc, lastHost, ssn, rrpb>>
         ELSE \* RRPB:215-218 targetServer == serverName (ReportFromHolder); ORP:97-113 / CRP:100-106 checkTransition
              \* RRPB:222-232 REPORT_SUCCEED, persisted to the procedure store, woken
              /\ rrpb' = [rrpb EXCEPT ![c].st = "REPORT_SUCCEED"]
              /\ IF m.code = "OPENED"
                   THEN \* ORP:116-126 -> AM.regionOpenedWithoutPersistingToMeta (AM:2284-2290):
                        \* transitionState(OPEN, {OPENING, OPEN}) (RSN:141-147); addRegionToServer (RS_:705-708)
                        IF rsnState[r] \in {"OPENING", "OPEN"}
                          THEN /\ rsnState' = [rsnState EXCEPT ![r] = "OPEN"]
                               /\ ssn' = IF loc # NoServer /\ serverState[loc] # "GONE"
                                           THEN [ssn EXCEPT ![loc] = @ \cup {r}] ELSE ssn
                               /\ UNCHANGED <<rsnLoc, lastHost>>
                          ELSE UNCHANGED <<rsnState, rsnLoc, lastHost, ssn>>  \* UnexpectedStateException -> AssertionError (RRPB:240-244)
                   ELSE \* CRP:108-113 -> AM.regionClosedWithoutPersistingToMeta (AM:2293-2302):
                        \* transitionState(CLOSED, {CLOSING, CLOSED}); location null; lastHost; removeRegionFromServer
                        IF rsnState[r] \in {"CLOSING", "CLOSED"}
                          THEN /\ rsnState' = [rsnState EXCEPT ![r] = "CLOSED"]
                               /\ rsnLoc' = [rsnLoc EXCEPT ![r] = NoServer]
                               /\ lastHost' = IF loc # NoServer THEN [lastHost EXCEPT ![r] = loc] ELSE lastHost
                               /\ ssn' = IF loc # NoServer THEN [ssn EXCEPT ![loc] = @ \ {r}] ELSE ssn
                          ELSE UNCHANGED <<rsnState, rsnLoc, lastHost, ssn>>  \* AssertionError (RRPB:240-244)
    /\ UNCHANGED <<rsnProc, activeTrspCount, serverState, draining, metaVars, rsVars, trsp,
                   nextPid, schedLock, cplxVars, callerVars, targetFired>>

\* RRPB:352-361 REPORT_SUCCEED: AM.persistToMeta (AM:2305-2317) writes the CURRENT RSN, then unattach
RrpbReportSucceed(c) ==
    LET b == rrpb[c]
        r == b.region
    IN
    /\ b.st = "REPORT_SUCCEED"
    /\ MetaWrite(r, rsnState[r], rsnLoc[r])
    /\ rrpb' = [rrpb EXCEPT ![c].st = "DONE"]
    /\ trsp' = [trsp EXCEPT ![b.parent].child = NoProc]     \* RRPB:289-291 -> TRSP:592-595
    /\ UNCHANGED <<rsnVars, serverVars, metaSplitParent, tableState, rsVars, msgs, nextPid,
                   schedLock, cplxVars, callerVars, targetFired>>

\* RRPB:362-365 DISPATCH_FAIL: region state unchanged, unattach
RrpbDispatchFail(c) ==
    LET b == rrpb[c] IN
    /\ b.st = "DISPATCH_FAIL"
    /\ rrpb' = [rrpb EXCEPT ![c].st = "DONE"]
    /\ trsp' = [trsp EXCEPT ![b.parent].child = NoProc]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, nextPid, schedLock, cplxVars,
                   callerVars, targetFired>>

\* RRPB:366-376 SERVER_CRASH: AM.regionClosedAbnormally (AM:2321-2341), then unattach
RrpbServerCrash(c) ==
    LET b   == rrpb[c]
        r   == b.region
        loc == rsnLoc[r]
    IN
    /\ b.st = "SERVER_CRASH"
    /\ rsnState' = [rsnState EXCEPT ![r] = "ABNORMALLY_CLOSED"]      \* AM:2324
    /\ rsnLoc' = [rsnLoc EXCEPT ![r] = NoServer]                      \* AM:2325
    /\ MetaWrite(r, "ABNORMALLY_CLOSED", NoServer)                    \* AM:2326
    /\ lastHost' = IF loc # NoServer THEN [lastHost EXCEPT ![r] = loc] ELSE lastHost   \* AM:2329-2332
    /\ ssn' = IF loc # NoServer THEN [ssn EXCEPT ![loc] = @ \ {r}] ELSE ssn
    /\ rrpb' = [rrpb EXCEPT ![c].st = "DONE"]
    /\ trsp' = [trsp EXCEPT ![b.parent].child = NoProc]
    /\ UNCHANGED <<rsnProc, activeTrspCount, serverState, draining, metaSplitParent, tableState,
                   rsVars, msgs, nextPid, schedLock, cplxVars, callerVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* S1: SplitTableRegionProcedure.                                          *)
(* SMP keeps a stack `states` (SMP:52-53, 291-301); each PE execution adds *)
(* one rollback step (PE:1893-1899); SMP.rollback undoes getCurrentState() *)
(* once per recorded step (SMP:204-217).  failIfAborted is read at the    *)
(* start of execute (SMP:165) and inside setNextState after the state's   *)
(* work (SMP:117-120): the two reads are split into SmpExecuteEntry and    *)
(* the per-state actions so that an abort can land between them (L1).      *)
(***************************************************************************)

\* RS-initiated split: AM.updateRegionSplitTransition (AM:1356-1408) -> createSplitProcedure
\* (AM:1193-1196) -> STRP constructor (STRP:113-157).  (The Admin split path HM:2366-2399 builds
\* the same procedure.)
SplitSubmit(r) ==
    LET loc == rsnLoc[r] IN
    /\ ~SplitActive
    /\ nextPid \in Pids
    /\ loc # NoServer
    /\ serverState[loc] = "ONLINE"            \* AM:1265-1283 report accepted only from an ONLINE server
    /\ rsOnline[loc] /\ r \in rsRegions[loc]  \* the hosting RS asks; checkSplittable asks it back (STRP:198-241)
    /\ rsnState[r] = "OPEN"                   \* AM:1393-1394 parentState.isOpened(); STRP:119 checkOnline (RSN:318-323)
    /\ ~metaSplitParent[r]                    \* RSN:324-330
    /\ tableState = "ENABLED"                 \* STRP:116 preflightChecks(env, true)
    /\ split' = [st |-> "ready", pid |-> nextPid, region |-> r, stack |-> <<>>, execs |-> 0,
                 aborted |-> FALSE, child |-> NoProc]
    /\ nextPid' = nextPid + 1
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, trsp, rrpb, schedLock, trunc,
                   scp, disable, callerVars, targetFired>>

SplitCanLock == schedLock[split.region] \in {NoProc, split.pid}

\* PE.execProcedure (PE:1806-1826) -> SMP.execute entry (SMP:161-174).  The split acquires the
\* region lock on its first execution (STRP:159-173, holdLock) and resumes here after its child.
SmpExecuteEntry ==
    /\ \/ split.st = "ready"
       \/ split.st = "waitChild" /\ trsp[split.child].pc = "DONE"
    /\ SplitCanLock
    /\ schedLock' = [schedLock EXCEPT ![split.region] = split.pid]
    /\ IF split.aborted
         THEN \* SMP:165 failIfAborted -> setAbortFailure; SMP:167-169 return null;
              \* PE:1893-1899 the failed execution still adds a rollback step
              split' = [split EXCEPT !.st = "rollback", !.execs = @ + 1, !.child = NoProc]
         ELSE \* SMP:171-174 first execution pushes the initial state
              split' = [split EXCEPT !.st = "inStep", !.child = NoProc,
                                     !.stack = IF @ = <<>> THEN <<"PREPARE">> ELSE @]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, trsp, rrpb, nextPid, trunc, scp,
                   disable, callerVars, targetFired>>

\* common epilogue: SMP.setNextState(next) pushes then calls failIfAborted (SMP:117-120);
\* PE adds the rollback step (PE:1893-1899); return value decides the next scheduling state.
AfterPush(next) ==
    [split EXCEPT !.stack = Append(@, next), !.execs = @ + 1,
                  !.st = IF split.aborted THEN "rollback" ELSE "ready"]

\* STRP:294-300 PREPARE -> prepareSplitRegion (STRP:511-595)
SplitPrepare ==
    LET r == split.region
        s == rsnState[r]
    IN
    /\ split.st = "inStep"
    /\ Last(split.stack) = "PREPARE"
    \* STRP:513-533 snapshot / table-modification checks, STRP:573-587 split switches: environment, assumed to pass
    /\ IF s = "SPLIT"
         THEN \* STRP:551-553 return false -> NO_MORE_STATE; SMP:189-191 push EOF (no abort check); SUCCESS
              /\ split' = [split EXCEPT !.stack = Append(@, "EOF"), !.execs = @ + 1, !.st = "done"]
              /\ schedLock' = [schedLock EXCEPT ![r] = NoProc]
              /\ UNCHANGED rsnState
         ELSE IF s \notin {"OPEN", "CLOSED"}            \* STRP:505, 561-567 EXPECTED_SPLIT_STATES
         THEN \* setFailure; return false -> push EOF; PE rolls back
              /\ split' = [split EXCEPT !.stack = Append(@, "EOF"), !.execs = @ + 1, !.st = "rollback"]
              /\ UNCHANGED <<rsnState, schedLock>>
         ELSE \* STRP:589-590 node.setState(SPLITTING): no RSN lock, no procedure check, no meta write
              /\ rsnState' = [rsnState EXCEPT ![r] = "SPLITTING"]
              /\ split' = AfterPush("PRE_OPERATION")          \* STRP:296
              /\ UNCHANGED schedLock
    /\ UNCHANGED <<rsnLoc, rsnProc, lastHost, activeTrspCount, serverVars, metaVars, rsVars, msgs,
                   trsp, rrpb, nextPid, trunc, scp, disable, callerVars, targetFired>>

\* STRP:301-304 PRE_OPERATION -> preSplitRegion (STRP:613-633).  hookFails models the
\* coprocessor preSplitRegionAction veto or QuotaExceededException (brief S1).
SplitPreOperation(hookFails) ==
    /\ split.st = "inStep"
    /\ Last(split.stack) = "PRE_OPERATION"
    /\ split' = IF hookFails
                  THEN \* IOException -> STRP:349-357 rollback supported -> setFailure (no push)
                       [split EXCEPT !.execs = @ + 1, !.st = "rollback"]
                  ELSE AfterPush("CLOSE_PARENT_REGION")          \* STRP:303
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, trunc, scp, disable,
                   callerVars, targetFired>>

\* STRP:305-313 CLOSE_PARENT_REGION -> createUnassignProcedures (STRP:958-963) ->
\* AMU.createUnassignProceduresForSplitOrMerge (AMU:92-133), under the RSN lock
SplitCloseParentRegion ==
    LET r == split.region
        c == nextPid
    IN
    /\ split.st = "inStep"
    /\ Last(split.stack) = "CLOSE_PARENT_REGION"
    /\ IF rsnProc[r] # NoProc
         THEN \* AMU:110-113 "currently in transition, give up" -> STRP:349-357 setFailure (no push)
              /\ split' = [split EXCEPT !.execs = @ + 1, !.st = "rollback"]
              /\ UNCHANGED <<rsnProc, activeTrspCount, trsp, nextPid>>
         ELSE IF split.aborted
         THEN \* AMU:114 setProcedure done; STRP:312 setNextState -> failIfAborted -> FAILED.  The children
              \* returned by SMP:193-196 are never initialized nor submitted (PE:1851-1867, 1939-1941)
              \* nor persisted (PE updateStoreOnExec): the TRSP stays attached but never runs and has
              \* no procId.
              /\ rsnProc' = [rsnProc EXCEPT ![r] = OrphanProc]
              /\ activeTrspCount' = activeTrspCount + 1
              /\ split' = [split EXCEPT !.stack = Append(@, "CHECK_CLOSED_REGIONS"), !.execs = @ + 1,
                                        !.st = "rollback"]
              /\ UNCHANGED <<trsp, nextPid>>
         ELSE \* AMU:108-115 TRSP.unassignSplitMerge (TRSP:746-750) attached; STRP:306 addChildProcedure;
              \* STRP:312 setNextState(CHECK_CLOSED_REGIONS); the split waits for the child
              /\ c \in Pids
              /\ trsp' = [trsp EXCEPT ![c] = NewTrsp(r, "UNASSIGN", FALSE, NoServer, split.pid)]
              /\ rsnProc' = [rsnProc EXCEPT ![r] = c]
              /\ activeTrspCount' = activeTrspCount + 1
              /\ nextPid' = nextPid + 1
              /\ split' = [split EXCEPT !.stack = Append(@, "CHECK_CLOSED_REGIONS"), !.execs = @ + 1,
                                        !.st = "waitChild", !.child = c]
    /\ UNCHANGED <<rsnState, rsnLoc, lastHost, serverVars, metaVars, rsVars, msgs, rrpb, schedLock,
                   trunc, scp, disable, callerVars, targetFired>>

\* STRP:314-317 CHECK_CLOSED_REGIONS -> AMU.checkClosedRegion (AMU:296-301): recovered.edits are
\* assumed absent (no WAL split in the modeled hunts)
SplitCheckClosedRegions ==
    /\ split.st = "inStep"
    /\ Last(split.stack) = "CHECK_CLOSED_REGIONS"
    /\ split' = AfterPush("CREATE_DAUGHTER_REGIONS")
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, trunc, scp, disable,
                   callerVars, targetFired>>

\* STRP:318-330 CREATE_DAUGHTER_REGIONS .. PRE_OPERATION_BEFORE_META (file system + hook; no RSN effect)
SplitCreateDaughterRegions ==
    /\ split.st = "inStep"
    /\ Last(split.stack) = "CREATE_DAUGHTER_REGIONS"
    /\ split' = AfterPush("UPDATE_META")
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, trunc, scp, disable,
                   callerVars, targetFired>>

\* STRP:331-334 UPDATE_META (point of no return) -> AM.markRegionAsSplit (AM:2365-2397)
SplitUpdateMeta ==
    LET r == split.region IN
    /\ split.st = "inStep"
    /\ Last(split.stack) = "UPDATE_META"
    /\ rsnState' = [rsnState EXCEPT ![r] = "SPLIT"]                   \* AM:2373 no RSN lock
    /\ metaSplitParent' = [metaSplitParent EXCEPT ![r] = TRUE]        \* AM:2388 -> RSS:368-400
    \* AM:2374-2377 daughters SPLITTING_NEW / CLOSED in meta: not modeled (brief 3.2)
    /\ split' = AfterPush("PRE_OPERATION_AFTER_META")
    /\ UNCHANGED <<rsnLoc, rsnProc, lastHost, activeTrspCount, serverVars, metaState, metaLoc,
                   tableState, rsVars, msgs, procVars, trunc, scp, disable, callerVars, targetFired>>

\* STRP:335-345 PRE_OPERATION_AFTER_META, OPEN_CHILD_REGIONS, POST_OPERATION -> NO_MORE_STATE
SplitAfterMeta ==
    /\ split.st = "inStep"
    /\ Last(split.stack) = "PRE_OPERATION_AFTER_META"
    /\ split' = [split EXCEPT !.stack = Append(@, "EOF"), !.execs = @ + 1, !.st = "done"]
    /\ schedLock' = [schedLock EXCEPT ![split.region] = NoProc]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, trsp, rrpb, nextPid, trunc, scp,
                   disable, callerVars, targetFired>>

(***************************************************************************)
(* One rollback step: PE.executeNormalRollback (PE:1612-1660) ->           *)
(* executeRollback (PE:1751-1768) -> SMP.rollback (SMP:204-217) ->         *)
(* STRP.rollbackState(getCurrentState()) (STRP:369-413).                   *)
(***************************************************************************)
SplitRollbackStep ==
    LET r    == split.region
        stk0 == IF split.stack # <<>> /\ Last(split.stack) = "EOF"
                  THEN Front(split.stack) ELSE split.stack        \* SMP:206-208 isEofState -> stateCount--
        cur  == IF stk0 = <<>> THEN "PREPARE" ELSE Last(stk0)     \* SMP:212, 274-276
        stk1 == IF stk0 = <<>> THEN <<>> ELSE Front(stk0)         \* SMP:214 stateCount--
        tgt  == IF rsnLoc[r] # NoServer THEN rsnLoc[r] ELSE lastHost[r]  \* getRegionServerOfRegion (RS_:528-540)
        c    == nextPid
        reopen == cur = "CHECK_CLOSED_REGIONS" /\ rsnProc[r] = NoProc
        last == split.execs = 1
    IN
    /\ split.st = "rollback"
    /\ split.execs > 0
    \* STRP:399-401 rollbackPrepareSplit (STRP:601-607): only SPLITTING -> OPEN, prior state not remembered
    /\ rsnState' = IF cur = "PREPARE" /\ rsnState[r] = "SPLITTING"
                     THEN [rsnState EXCEPT ![r] = "OPEN"] ELSE rsnState
    \* STRP:388-390 openParentRegion (STRP:649-653) -> AMU.reopenRegionsForRollback (AMU:273-280) ->
    \* createAssignProcedures(ignoreIfInTransition = true) (AMU:146-173): skip if a TRSP is attached,
    \* else attach an ASSIGN TRSP and submit it as a top-level procedure (no parent lock)
    /\ IF reopen
         THEN /\ c \in Pids
              /\ trsp' = [trsp EXCEPT ![c] = NewTrsp(r, "ASSIGN", FALSE, tgt, NoProc)]
              /\ rsnProc' = [rsnProc EXCEPT ![r] = c]
              /\ activeTrspCount' = activeTrspCount + 1
              /\ nextPid' = nextPid + 1
         ELSE UNCHANGED <<trsp, rsnProc, activeTrspCount, nextPid>>
    \* other states: PRE_OPERATION postRollBackSplitRegion hook (STRP:396-398); CLOSE_PARENT_REGION no-op
    \* (STRP:391-395); CREATE_DAUGHTER_REGIONS deleteDaughterRegions, file system (STRP:384-387);
    \* UPDATE_META and later throw UnsupportedOperationException, logged as CODE-BUG by PE:1760-1763,
    \* and the rollback continues (stateCount-- in SMP:213-215).
    /\ split' = [split EXCEPT !.stack = stk1, !.execs = @ - 1,
                              !.st = IF last THEN "done" ELSE "rollback"]
    \* PE:1704-1716 rootProcedureFinished: the region lock is released after the last step
    /\ schedLock' = IF last THEN [schedLock EXCEPT ![r] = NoProc] ELSE schedLock
    /\ UNCHANGED <<rsnLoc, lastHost, serverVars, metaVars, rsVars, msgs, rrpb, trunc, scp, disable,
                   callerVars, targetFired>>

\* Admin.abortProcedure: MRS:1417-1428 -> HM.abortProcedure (HM:3770-3783) -> PE.abort
\* (PE:1218-1226, mayInterruptIfRunning) -> STRP.abort (STRP:991-997) -> SMP.abort (SMP:223-236).
\* The flag is an AtomicBoolean written by an RPC thread at any time.  Exempt from the
\* one-outstanding-request rule and from OperatorWaitsForSplit (brief section 5).
OperatorAbortSplit ==
    /\ split.st \in {"ready", "inStep", "waitChild"}
    /\ ~split.aborted
    /\ SplitRollbackSupported(SplitCurrentState)      \* STRP:996, SMP:230-233
    /\ split' = [split EXCEPT !.aborted = TRUE]       \* SMP:234
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, trunc, scp, disable,
                   callerVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* S2: TruncateRegionProcedure.  Region procedure holding the region lock  *)
(* for its life (TRP:291-299, recovery snapshot disabled by default,       *)
(* HConstants:1545).  MAKE_OFFLINE and MAKE_ONLINE use override=force=true *)
(* and unset ANY attached TRSP (AM:1012-1018, AM:789-795).                 *)
(***************************************************************************)

\* HM.truncateRegion (HM:2699-2726) -> TruncateRegionProcedure(env, region, latch) (TRP:59-63)
OperatorTruncate(r) ==
    /\ OperatorIdle
    /\ trunc.st \in {"none", "done"}
    /\ nextPid \in Pids
    /\ ~metaSplitParent[r]
    /\ tableState = "ENABLED"                       \* preflightChecks(env, true)
    /\ trunc' = [st |-> "PRE_OPERATION", pid |-> nextPid, region |-> r, child |-> NoProc]
    /\ nextPid' = nextPid + 1
    /\ opWait' = [kind |-> "trunc", pid |-> NoProc]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, trsp, rrpb, schedLock, split, scp,
                   disable, balPlan, decom, rsg, targetFired>>

TruncCanLock == schedLock[trunc.region] \in {NoProc, trunc.pid}

\* TRP:73-90 PRE_OPERATION
TruncPreOperation ==
    LET r == trunc.region IN
    /\ trunc.st = "PRE_OPERATION"
    /\ TruncCanLock
    /\ IF rsnState[r] # "OPEN"
         THEN \* TRP:78 checkOnline -> RSN.checkOnline (RSN:318-323) DoNotRetryRegionException ->
              \* TRP:123-126 setFailure -> rollback PRE_OPERATION is a no-op (TRP:166-168)
              /\ trunc' = [trunc EXCEPT !.st = "done"]
              /\ schedLock' = [schedLock EXCEPT ![r] = NoProc]
         ELSE \* TRP:82 preTruncate hook; TRP:85-89 -> MAKE_OFFLINE
              /\ trunc' = [trunc EXCEPT !.st = "MAKE_OFFLINE"]
              /\ schedLock' = [schedLock EXCEPT ![r] = trunc.pid]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, trsp, rrpb, nextPid, split, scp,
                   disable, callerVars, targetFired>>

\* TRP:103-106 MAKE_OFFLINE -> createUnAssignProcedures (TRP:282-285) ->
\* AM.createOneUnassignProcedure(r, override=true, force=true) (AM:1006-1035)
TruncMakeOffline ==
    LET r   == trunc.region
        c   == nextPid
        old == rsnProc[r]
    IN
    /\ trunc.st = "MAKE_OFFLINE"
    /\ schedLock[r] = trunc.pid
    /\ c \in Pids
    \* AM:1012-1018 override && force: no preTransitCheck; unsetProcedure(any attached TRSP)
    \* AM:1024-1026 setProcedure(TRSP.unassign)
    /\ rsnProc' = [rsnProc EXCEPT ![r] = c]
    /\ activeTrspCount' = activeTrspCount - (IF old # NoProc THEN 1 ELSE 0) + 1
    /\ trsp' = [trsp EXCEPT ![c] = NewTrsp(r, "UNASSIGN", FALSE, NoServer, trunc.pid)]
    /\ nextPid' = nextPid + 1
    /\ trunc' = [trunc EXCEPT !.st = "REMOVE", !.child = c]     \* TRP:105 setNextState(REMOVE); wait child
    /\ UNCHANGED <<rsnState, rsnLoc, lastHost, serverVars, metaVars, rsVars, msgs, rrpb, schedLock,
                   split, scp, disable, callerVars, targetFired>>

\* TRP:107-110 REMOVE -> deleteRegionFromFileSystem (TRP:148-160, file system under the RSN lock; no
\* RSN field changes).  Runs after the MAKE_OFFLINE child has finished.
TruncRemove ==
    LET r == trunc.region IN
    /\ trunc.st = "REMOVE"
    /\ trsp[trunc.child].pc = "DONE"
    /\ schedLock[r] = trunc.pid
    /\ trunc' = [trunc EXCEPT !.st = "MAKE_ONLINE", !.child = NoProc]    \* TRP:109
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, split, scp, disable,
                   callerVars, targetFired>>

\* TRP:111-115 MAKE_ONLINE -> createAssignProcedures (TRP:287-289) ->
\* AM.createOneAssignProcedure(r, true, true) (AM:988-1000) -> createAssignProcedure(ri, null, true, true)
\* (AM:784-807)
TruncMakeOnline ==
    LET r   == trunc.region
        c   == nextPid
        old == rsnProc[r]
    IN
    /\ trunc.st = "MAKE_ONLINE"
    /\ schedLock[r] = trunc.pid
    /\ c \in Pids
    \* AM:789-795 override && force: unset any attached TRSP; AM:800-801 setProcedure(TRSP.assign)
    /\ rsnProc' = [rsnProc EXCEPT ![r] = c]
    /\ activeTrspCount' = activeTrspCount - (IF old # NoProc THEN 1 ELSE 0) + 1
    /\ trsp' = [trsp EXCEPT ![c] = NewTrsp(r, "ASSIGN", FALSE, NoServer, trunc.pid)]
    /\ nextPid' = nextPid + 1
    /\ trunc' = [trunc EXCEPT !.st = "POST_OPERATION", !.child = c]   \* TRP:114
    /\ UNCHANGED <<rsnState, rsnLoc, lastHost, serverVars, metaVars, rsVars, msgs, rrpb, schedLock,
                   split, scp, disable, callerVars, targetFired>>

\* TRP:116-119 POST_OPERATION -> NO_MORE_STATE; the region lock is released
TruncPostOperation ==
    /\ trunc.st = "POST_OPERATION"
    /\ trsp[trunc.child].pc = "DONE"
    /\ trunc' = [trunc EXCEPT !.st = "done"]
    /\ schedLock' = [schedLock EXCEPT ![trunc.region] = NoProc]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, trsp, rrpb, nextPid, split, scp,
                   disable, callerVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* S2/S3 callers: balancer, decommission, RSGroup                         *)
(***************************************************************************)

\* HM.balance (HM:2125-2210) + RS_.getAssignmentsForBalancer (RS_:548-590).  The balancer's
\* load-based choice of WHICH region moves is abstracted to any eligible region.
BalancerPlan(r, d) ==
    /\ balPlan.st = "none"
    /\ activeTrspCount = 0                                     \* HM:2142-2161 getRegionTransitScheduledCount() > 0 -> skip
    /\ \A s \in Servers : scp[s].st \in {"none", "done"}        \* HM:2163-2167 areDeadServersInProgress
    /\ tableState \notin {"DISABLED", "DISABLING"}              \* RS_:552-560
    /\ rsnState[r] \in {"OPEN", "OPENING"}                      \* RS_:565-570
    /\ rsnLoc[r] # NoServer                                     \* RS_:573-578
    /\ d \in AssignableServers /\ d # rsnLoc[r]
    /\ balPlan' = [st |-> "planned", region |-> r, src |-> rsnLoc[r], dest |-> d]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, opWait, decom,
                   rsg, targetFired>>

\* AM:905-911: location changed since the plan was made -> skip
BalancerSkipPlan ==
    /\ balPlan.st = "planned"
    /\ rsnLoc[balPlan.region] # balPlan.src
    /\ balPlan' = NoPlan
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, opWait, decom,
                   rsg, targetFired>>

\* HM.decommissionRegionServers(servers, offload=true) (HM:4145-4177)
OperatorDecommission(s) ==
    LET dests == {x \in AssignableServers : x # s}    \* HM:4164 createDestinationServersList (after drain add)
    IN
    /\ OperatorIdle
    /\ serverState[s] = "ONLINE"
    /\ s \notin draining
    /\ draining' = draining \cup {s}                  \* HM:4150-4161
    \* HM:4166 getRegionsOnServer (AM:501-507): SSN membership, no state filter
    /\ \E todo \in Orderings(ssn[s]) :
          decom' = [st |-> IF todo = <<>> THEN "done" ELSE "running", server |-> s,
                    todo |-> todo, dests |-> dests]
    /\ opWait' = [kind |-> "decom", pid |-> NoProc]
    /\ UNCHANGED <<rsnVars, serverState, ssn, metaVars, rsVars, msgs, procVars, cplxVars, balPlan,
                   rsg, targetFired>>

\* HM:4168-4171 randomAssignment returns null when there is no destination: throw, loop aborted
DecomNoDestination ==
    /\ decom.st = "running"
    /\ decom.dests = {}
    /\ decom' = [decom EXCEPT !.st = "done", !.todo = <<>>]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, opWait, balPlan,
                   rsg, targetFired>>

\* RSGroupInfoManagerImpl.moveServers -> moveServerRegionsFromGroup (RSG:984-997)
OperatorRsgMoveServers(s) ==
    /\ OperatorIdle
    /\ serverState[s] = "ONLINE"
    /\ rsg' = [st |-> "select", server |-> s, todo |-> <<>>, failed |-> {}, retry |-> 0, waiting |-> {}]
    /\ opWait' = [kind |-> "rsg", pid |-> NoProc]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, balPlan, decom,
                   targetFired>>

\* RSG:1019-1024 loop head: getRegions(server) (RSG:942-962) = every region whose RSN location is
\* the server, in ANY state (getRegionAssignments RS_:504-510); the RIT part (RSG:954-960) reads the
\* same RSN location field and adds nothing.  RSG:1005-1014 only online servers are owners.
RsgSelect ==
    LET sel == IF serverState[rsg.server] = "ONLINE"
                 THEN {r \in Regions : rsnLoc[r] = rsg.server} ELSE {}
    IN
    /\ rsg.st = "select"
    /\ \E todo \in Orderings(sel) :
          rsg' = [rsg EXCEPT !.st = "running", !.todo = todo, !.failed = {}, !.waiting = {}]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, opWait, balPlan,
                   decom, targetFired>>

\* RSG:1029-1034 no destination: failedRegions without reaching the check
RsgNoDestination ==
    /\ rsg.st = "running"
    /\ rsg.todo # <<>>
    /\ RsgDests = {}
    /\ rsg' = [rsg EXCEPT !.todo = Tail(rsg.todo), !.failed = rsg.failed \cup {Head(rsg.todo)}]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, opWait, balPlan,
                   decom, targetFired>>

\* RSG:1048-1074 end of a round: waitForRegionMovement, then retry or finish
RsgEndRound ==
    /\ rsg.st = "running"
    /\ rsg.todo = <<>>
    /\ \A p \in rsg.waiting : trsp[p].pc = "DONE"
    /\ rsg' = IF rsg.failed = {}
                THEN [rsg EXCEPT !.st = "done"]                              \* RSG:1049-1051
              ELSE IF rsg.retry + 1 <= MaxRsgRetry                           \* RSG:1059-1064
                THEN [rsg EXCEPT !.st = "select", !.retry = @ + 1]
              ELSE [rsg EXCEPT !.st = "done"]                                \* RSG:1067-1073 DoNotRetryIOException
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, cplxVars, opWait, balPlan,
                   decom, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* DisableTableProcedure (workload, TestRegionMove.java:116).  holdLock is *)
(* false: the table exclusive lock is taken per step, which conflicts with *)
(* the table shared lock every region procedure holds with its region lock *)
(* (LockAndQueue:131-136; TableQueue:50-80).                               *)
(***************************************************************************)
TableXLockAvailable == \A r \in Regions : schedLock[r] = NoProc

OperatorDisable ==
    /\ OperatorIdle
    /\ tableState = "ENABLED"
    /\ disable.st \in {"none", "done"}
    /\ nextPid \in Pids
    /\ disable' = [st |-> "SET_DISABLING", pid |-> nextPid, children |-> {}]
    /\ nextPid' = nextPid + 1
    /\ opWait' = [kind |-> "disable", pid |-> NoProc]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, trsp, rrpb, schedLock, split, trunc,
                   scp, balPlan, decom, rsg, targetFired>>

\* DTP:88-103 PREPARE, PRE_OPERATION, SET_DISABLING_TABLE_STATE (DTP:279-285); no RSN effect in between
DisableSetDisabling ==
    /\ disable.st = "SET_DISABLING"
    /\ TableXLockAvailable
    /\ tableState' = "DISABLING"
    /\ disable' = [disable EXCEPT !.st = "SCHEDULE"]
    /\ UNCHANGED <<rsnVars, serverVars, metaState, metaLoc, metaSplitParent, rsVars, msgs, procVars,
                   split, trunc, scp, callerVars, targetFired>>

\* DTP:104-106 -> CloseTableRegionsProcedure.schedule (ACTRP:66-87) ->
\* AM.submitUnassignProcedureForDisablingTable (AM:1140-1146) -> submitUnassignProcedure (AM:1107-1131).
\* The per-region loop is taken as one step.
CloseTableRegionsSchedule ==
    LET todo == {r \in Regions : rsnProc[r] = NoProc /\ rsnState[r] \notin {"OFFLINE", "CLOSED", "SPLIT"}}
        rit  == {r \in Regions : rsnProc[r] # NoProc}         \* AM:1115-1118 skipped, counted
        sq   == SetToSeq(todo)
        n    == Len(sq)
        PidOf(r) == nextPid + (CHOOSE i \in 1..n : sq[i] = r) - 1
    IN
    /\ disable.st = "SCHEDULE"
    /\ ~(todo = {} /\ rit # {})        \* ACTRP:72-84 nothing submitted while RITs exist: suspend, retry later
    /\ nextPid + n - 1 <= MaxPid
    \* AM:1120-1122 OFFLINE/CLOSED/SPLIT skipped; AM:1123-1124 setProcedure(TRSP.unassign) + submit as child
    /\ trsp' = [p \in Pids |-> IF p >= nextPid /\ p < nextPid + n
                                 THEN NewTrsp(sq[p - nextPid + 1], "UNASSIGN", FALSE, NoServer, disable.pid)
                                 ELSE trsp[p]]
    /\ rsnProc' = [r \in Regions |-> IF r \in todo THEN PidOf(r) ELSE rsnProc[r]]
    /\ activeTrspCount' = activeTrspCount + n
    /\ nextPid' = nextPid + n
    /\ disable' = [disable EXCEPT !.st = "CONFIRM",
                                  !.children = {p \in Pids : p >= nextPid /\ p < nextPid + n}]   \* ACTRP:85
    /\ UNCHANGED <<rsnState, rsnLoc, lastHost, serverVars, metaVars, rsVars, msgs, rrpb, schedLock,
                   split, trunc, scp, callerVars, targetFired>>

\* ACTRP:89-101 confirm -> AM.numberOfUnclosedRegions (AM:1166-1180)
CloseTableRegionsConfirm ==
    /\ disable.st = "CONFIRM"
    /\ \A p \in disable.children : trsp[p].pc = "DONE"
    /\ disable' = [disable EXCEPT !.children = {},
                     !.st = IF \E r \in Regions : rsnState[r] \notin {"OFFLINE", "CLOSED", "SPLIT"}
                              THEN "SCHEDULE" ELSE "SET_DISABLED"]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, split, trunc, scp,
                   callerVars, targetFired>>

\* DTP:108-131 ADD_REPLICATION_BARRIER, SET_DISABLED_TABLE_STATE (DTP:291-297), POST_OPERATION
DisableSetDisabled ==
    /\ disable.st = "SET_DISABLED"
    /\ TableXLockAvailable
    /\ tableState' = "DISABLED"
    /\ disable' = [disable EXCEPT !.st = "done"]
    /\ UNCHANGED <<rsnVars, serverVars, metaState, metaLoc, metaSplitParent, rsVars, msgs, procVars,
                   split, trunc, scp, callerVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Faults: RS crash + ServerCrashProcedure; master failover               *)
(***************************************************************************)

\* the RegionServer process dies: its regions are gone; requests to it fail (RemoteCallFailed)
RsCrash(s) ==
    /\ rsOnline[s]
    /\ rsOnline' = [rsOnline EXCEPT ![s] = FALSE]
    /\ rsRegions' = [rsRegions EXCEPT ![s] = {}]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, msgs, procVars, cplxVars, callerVars, targetFired>>

\* ServerManager.expireServer -> AM.submitServerCrash: SSN state CRASHED under the SSN write lock
\* (fences reportRegionStateTransition, AM:1277-1297); the dispatcher node is removed; SCP submitted
MasterExpireServer(s) ==
    /\ ~rsOnline[s]
    /\ serverState[s] = "ONLINE"
    /\ nextPid \in Pids
    /\ serverState' = [serverState EXCEPT ![s] = "CRASHED"]
    /\ scp' = [scp EXCEPT ![s] = [st |-> "GET_REGIONS", pid |-> nextPid, todo |-> {}, children |-> {}]]
    /\ nextPid' = nextPid + 1
    /\ UNCHANGED <<rsnVars, ssn, draining, metaVars, rsVars, msgs, trsp, rrpb, schedLock, split,
                   trunc, disable, callerVars, targetFired>>

\* SCP:204-218 SERVER_CRASH_GET_REGIONS -> getRegionsOnServer (SCP:309, AM:501-507)
ScpGetRegions(s) ==
    /\ scp[s].st = "GET_REGIONS"
    /\ scp' = [scp EXCEPT ![s].st = "ASSIGN", ![s].todo = ssn[s]]
    /\ UNCHANGED <<rsnVars, serverVars, metaVars, rsVars, msgs, procVars, split, trunc, disable,
                   callerVars, targetFired>>

\* SCP:243-252 SERVER_CRASH_ASSIGN -> assignRegions (SCP:562-645), one loop iteration, RSN locked
ScpAssignRegion(s, r) ==
    LET p   == rsnProc[r]
        loc == rsnLoc[r]
        c   == nextPid
        hasChild == p # NoProc /\ p # OrphanProc /\ trsp[p].child # NoProc
    IN
    /\ scp[s].st = "ASSIGN"
    /\ r \in scp[s].todo
    /\ IF loc # s
         THEN \* SCP:601-611 location no longer matches: skip
              /\ scp' = [scp EXCEPT ![s].todo = @ \ {r}]
              /\ UNCHANGED <<rsnVars, ssn, metaState, metaLoc, procVars>>
       ELSE IF p # NoProc
         THEN \* SCP:612-619 RIT -> TRSP.serverCrashed (TRSP:566-586), forceNewPlan = !retain (SCP:565-566, 88)
              /\ scp' = [scp EXCEPT ![s].todo = @ \ {r}]
              /\ trsp' = IF p # OrphanProc THEN [trsp EXCEPT ![p].force = TRUE] ELSE trsp
              /\ IF hasChild
                   THEN \* TRSP:569-576 -> RRPB.serverCrashed (RRPB:247-268): SERVER_CRASH from any other state
                        /\ rrpb' = IF rrpb[trsp[p].child].st = "SERVER_CRASH" THEN rrpb
                                   ELSE [rrpb EXCEPT ![trsp[p].child].st = "SERVER_CRASH"]
                        /\ UNCHANGED <<rsnState, rsnLoc, lastHost, ssn, metaState, metaLoc>>
                 ELSE IF rsnState[r] = "ABNORMALLY_CLOSED"
                   THEN UNCHANGED <<rrpb, rsnState, rsnLoc, lastHost, ssn, metaState, metaLoc>>  \* TRSP:578-580
                 ELSE \* TRSP:581-584 -> AM.regionClosedAbnormally (AM:2321-2341)
                      /\ rsnState' = [rsnState EXCEPT ![r] = "ABNORMALLY_CLOSED"]
                      /\ rsnLoc' = [rsnLoc EXCEPT ![r] = NoServer]
                      /\ MetaWrite(r, "ABNORMALLY_CLOSED", NoServer)
                      /\ lastHost' = [lastHost EXCEPT ![r] = loc]
                      /\ ssn' = [ssn EXCEPT ![loc] = @ \ {r}]
                      /\ UNCHANGED rrpb
              /\ UNCHANGED <<rsnProc, activeTrspCount, nextPid, schedLock>>
       ELSE IF tableState = "DISABLED"
         THEN \* SCP:620-627 skip
              /\ scp' = [scp EXCEPT ![s].todo = @ \ {r}]
              /\ UNCHANGED <<rsnVars, ssn, metaState, metaLoc, procVars>>
       ELSE \* SCP:628-635 TRSP.assign(forceNewPlan = !retain = true), setProcedure, child of the SCP
              /\ c \in Pids
              /\ trsp' = [trsp EXCEPT ![c] = NewTrsp(r, "ASSIGN", TRUE, NoServer, scp[s].pid)]
              /\ rsnProc' = [rsnProc EXCEPT ![r] = c]
              /\ activeTrspCount' = activeTrspCount + 1
              /\ nextPid' = nextPid + 1
              /\ scp' = [scp EXCEPT ![s].todo = @ \ {r}, ![s].children = @ \cup {c}]
              /\ UNCHANGED <<rsnState, rsnLoc, lastHost, ssn, metaState, metaLoc, rrpb, schedLock>>
    /\ UNCHANGED <<serverState, draining, metaSplitParent, tableState, rsVars, msgs, split, trunc,
                   disable, callerVars, targetFired>>

\* SCP:293-297 SERVER_CRASH_FINISH after its children: RS_.removeServer (RS_:686-688)
ScpFinish(s) ==
    /\ scp[s].st = "ASSIGN"
    /\ scp[s].todo = {}
    /\ \A p \in scp[s].children : trsp[p].pc = "DONE"
    /\ serverState' = [serverState EXCEPT ![s] = "GONE"]
    /\ ssn' = [ssn EXCEPT ![s] = {}]
    /\ scp' = [scp EXCEPT ![s].st = "done"]
    /\ UNCHANGED <<rsnVars, draining, metaVars, rsVars, msgs, procVars, split, trunc, disable,
                   callerVars, targetFired>>

(***************************************************************************)
(* Master failover, restricted to a quiescent cluster (no procedure,      *)
(* message or caller loop in flight; every dead RS already processed).    *)
(* The new master loads meta (AM:1843-1909) and re-attaches unfinished    *)
(* TRSPs (setupRIT AM:372-396, HM:1054-1058) -- none in a quiescent store;*)
(* in-memory-only attachments (OrphanProc) and states are lost.           *)
(***************************************************************************)
Quiescent ==
    /\ \A p \in Pids : trsp[p].pc \in {"NONE", "DONE"} /\ rrpb[p].st \in {"NONE", "DONE"}
    /\ split.st \in {"none", "done"}
    /\ trunc.st \in {"none", "done"}
    /\ disable.st \in {"none", "done"}
    /\ \A s \in Servers : scp[s].st \in {"none", "done"} /\ (rsOnline[s] \/ serverState[s] = "GONE")
    /\ msgs = {}
    /\ OperatorIdle
    /\ balPlan.st = "none"
    /\ decom.st \in {"none", "done"}
    /\ rsg.st \in {"none", "done"}

MasterFailover ==
    /\ Quiescent
    /\ rsnState' = [r \in Regions |-> metaState[r]]            \* AM:1856-1869 (null state -> OFFLINE, n/a)
    /\ rsnLoc' = [r \in Regions |-> metaLoc[r]]                \* AM:1871 location = sn column, else server
                                                               \* column (RSS:167-168, MetaTableAccessor:560-575)
    /\ lastHost' = [r \in Regions |-> metaLoc[r]]              \* AM:1870 server column (approximated by metaLoc)
    /\ rsnProc' = [r \in Regions |-> NoProc]
    /\ activeTrspCount' = 0
    \* AM:1876-1886 only OPEN/OPENING/CLOSING/SPLITTING/MERGING regions join an SSN
    /\ ssn' = [s \in Servers |-> {r \in Regions : metaState[r] \in {"OPEN", "OPENING", "CLOSING", "SPLITTING"}
                                                   /\ metaLoc[r] = s}]
    /\ schedLock' = [r \in Regions |-> NoProc]
    /\ UNCHANGED <<serverState, draining, metaVars, rsVars, msgs, trsp, rrpb, nextPid, cplxVars,
                   callerVars, targetFired>>

-----------------------------------------------------------------------------
Init ==
    /\ \E home \in [Regions -> Servers] :
          /\ rsnState  = [r \in Regions |-> "OPEN"]
          /\ rsnLoc    = home
          /\ metaState = [r \in Regions |-> "OPEN"]
          /\ metaLoc   = home
          /\ ssn       = [s \in Servers |-> {r \in Regions : home[r] = s}]
          /\ rsRegions = [s \in Servers |-> {r \in Regions : home[r] = s}]
    /\ rsnProc         = [r \in Regions |-> NoProc]
    /\ lastHost        = [r \in Regions |-> NoServer]
    /\ activeTrspCount = 0
    /\ serverState     = [s \in Servers |-> "ONLINE"]
    /\ draining        = {}
    /\ metaSplitParent = [r \in Regions |-> FALSE]
    /\ tableState      = "ENABLED"
    /\ rsOnline        = [s \in Servers |-> TRUE]
    /\ msgs            = {}
    /\ trsp            = [p \in Pids |-> NoTrsp]
    /\ rrpb            = [p \in Pids |-> NoRrpb]
    /\ nextPid         = 1
    /\ schedLock       = [r \in Regions |-> NoProc]
    /\ split           = NoSplit
    /\ trunc           = NoTrunc
    /\ scp             = [s \in Servers |-> NoScp]
    /\ disable         = NoDisable
    /\ opWait          = IdleOp
    /\ balPlan         = NoPlan
    /\ decom           = NoDecom
    /\ rsg             = NoRsg
    /\ targetFired     = FALSE

\* all actions, without the stop-at-violation guard (used by Trace.tla)
NextBody ==
    \/ \E c \in Callers, r \in Regions, op \in Ops, d \in Servers \cup {NoServer} : TargetCheck(c, r, op, d)
    \/ \E p \in Pids : \/ TrspGetAssignCandidate(p)
                       \/ TrspOpen(p)
                       \/ TrspConfirmOpened(p)
                       \/ TrspClose(p)
                       \/ TrspConfirmClosed(p)
                       \/ RrpbDispatch(p)
                       \/ RrpbReportSucceed(p)
                       \/ RrpbDispatchFail(p)
                       \/ RrpbServerCrash(p)
    \/ \E p \in Pids, s \in Servers : AssignQueueAcceptPlan(p, s)
    \/ \E m \in msgs : \/ RsHandleOpen(m)
                       \/ RsHandleClose(m)
                       \/ MasterReportTransition(m)
                       \/ RemoteCallFailed(m, FALSE)
                       \/ RemoteCallFailed(m, TRUE)
    \/ \E r \in Regions : SplitSubmit(r)
    \/ SmpExecuteEntry
    \/ SplitPrepare
    \/ SplitPreOperation(FALSE)
    \/ SplitPreOperation(TRUE)
    \/ SplitCloseParentRegion
    \/ SplitCheckClosedRegions
    \/ SplitCreateDaughterRegions
    \/ SplitUpdateMeta
    \/ SplitAfterMeta
    \/ SplitRollbackStep
    \/ OperatorAbortSplit
    \/ \E r \in Regions : OperatorTruncate(r)
    \/ TruncPreOperation
    \/ TruncMakeOffline
    \/ TruncRemove
    \/ TruncMakeOnline
    \/ TruncPostOperation
    \/ \E r \in Regions, d \in Servers : BalancerPlan(r, d)
    \/ BalancerSkipPlan
    \/ \E s \in Servers : OperatorDecommission(s)
    \/ DecomNoDestination
    \/ \E s \in Servers : OperatorRsgMoveServers(s)
    \/ RsgSelect
    \/ RsgNoDestination
    \/ RsgEndRound
    \/ OperatorDisable
    \/ DisableSetDisabling
    \/ CloseTableRegionsSchedule
    \/ CloseTableRegionsConfirm
    \/ DisableSetDisabled
    \/ \E s \in Servers : \/ RsCrash(s)
                          \/ MasterExpireServer(s)
                          \/ ScpGetRegions(s)
                          \/ ScpFinish(s)
                          \/ \E r \in Regions : ScpAssignRegion(s, r)
    \/ MasterFailover

\* once the target fires every other action stops (adhoc tla-patterns section 1)
Next == ~targetFired /\ NextBody

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* the oracle (adhoc Shared Rule 1)
TargetSafe == ~targetFired

\* phi_T (brief section 1) for a request op on region r, as evaluated at AM:768
PhiT(r, op) == rsnProc[r] = NoProc /\ rsnState[r] \notin ExpectedStates(op)

TrspRec == [pc : TrspPcs, region : Regions, type : TrspTypes, force : BOOLEAN,
            cand : Servers \cup {NoServer}, child : Pids \cup {NoProc}, waitAssign : BOOLEAN,
            parent : Pids \cup {NoProc}]
RrpbRec == [st : RrpbStates, region : Regions, kind : {"OPEN", "CLOSE"},
            target : Servers \cup {NoServer}, sent : BOOLEAN, parent : Pids \cup {NoProc}]
MsgRec  == [type : MsgTypes, srv : Servers, region : Regions, pid : Pids, code : Codes]

\* sanity invariant 1 (brief section 5)
TypeOK ==
    /\ rsnState \in [Regions -> RegionStates]
    /\ rsnLoc \in [Regions -> Servers \cup {NoServer}]
    /\ rsnProc \in [Regions -> Pids \cup {NoProc, OrphanProc}]
    /\ lastHost \in [Regions -> Servers \cup {NoServer}]
    /\ activeTrspCount \in Int
    /\ serverState \in [Servers -> {"ONLINE", "CRASHED", "GONE"}]
    /\ ssn \in [Servers -> SUBSET Regions]
    /\ draining \subseteq Servers
    /\ metaState \in [Regions -> RegionStates]
    /\ metaLoc \in [Regions -> Servers \cup {NoServer}]
    /\ metaSplitParent \in [Regions -> BOOLEAN]
    /\ tableState \in {"ENABLED", "DISABLING", "DISABLED"}
    /\ rsOnline \in [Servers -> BOOLEAN]
    /\ rsRegions \in [Servers -> SUBSET Regions]
    /\ msgs \subseteq MsgRec
    /\ trsp \in [Pids -> TrspRec]
    /\ rrpb \in [Pids -> RrpbRec]
    /\ nextPid \in 1..(MaxPid + 1)
    /\ schedLock \in [Regions -> Pids \cup {NoProc}]
    /\ split.st \in {"none", "ready", "inStep", "waitChild", "rollback", "done"}
    /\ split.stack \in Seq(SplitStates)
    /\ split.execs \in Nat
    /\ split.aborted \in BOOLEAN
    /\ trunc.st \in {"none", "PRE_OPERATION", "MAKE_OFFLINE", "REMOVE", "MAKE_ONLINE", "POST_OPERATION", "done"}
    /\ \A s \in Servers : scp[s].st \in {"none", "GET_REGIONS", "ASSIGN", "done"}
    /\ disable.st \in {"none", "SET_DISABLING", "SCHEDULE", "CONFIRM", "SET_DISABLED", "done"}
    /\ opWait.kind \in {"idle", "trsp", "trunc", "disable", "decom", "rsg"}
    /\ balPlan.st \in {"none", "planned"}
    /\ decom.st \in {"none", "running", "done"}
    /\ rsg.st \in {"none", "select", "running", "done"}
    /\ targetFired \in BOOLEAN

\* sanity invariant 2 (brief section 5): a message carries only values its sender held --
\* every request was dispatched by an RRPB for that region/server, and every OPENED/CLOSED
\* report answers such a request from the server that received it.
ReportFromHolder ==
    \A m \in msgs :
        /\ rrpb[m.pid].st # "NONE"
        /\ rrpb[m.pid].region = m.region
        /\ rrpb[m.pid].target = m.srv
        /\ m.type = "OPEN_REQ"  => rrpb[m.pid].kind = "OPEN" /\ rrpb[m.pid].sent
        /\ m.type = "CLOSE_REQ" => rrpb[m.pid].kind = "CLOSE" /\ rrpb[m.pid].sent
        /\ m.type = "REPORT"    => (m.code = "OPENED" <=> rrpb[m.pid].kind = "OPEN")
=============================================================================
