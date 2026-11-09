------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for hbase-adhoc-11 (Category A: single linear trace).  *)
(*                                                                         *)
(* Replays an NDJSON trace emitted by the instrumented HMaster and          *)
(* RegionServers (see instrumentation-spec.md) against base.tla.  Every    *)
(* event names exactly one base action; every action parameter is taken   *)
(* from the event, so the replay is deterministic and TraceMatched (under  *)
(* weak fairness) is a sound "whole trace consumed" check.                 *)
(*                                                                         *)
(* Trace line: {"tag":"trace","ts":N,"event":{"name":..,"nid":..,          *)
(*              "state":{..},"msg":{..}}}                                  *)
(*   - region ids are encoded region names; server ids are                 *)
(*     ServerName.toString(); "null" stands for a null server/region      *)
(*   - procedures are identified by "oid" (hex identityHashCode of the     *)
(*     Java object, stable for the object's life) and, once the PE has     *)
(*     assigned one, by "pid" (procId).  RS-side events and reports carry *)
(*     only the remote procedure's procId.                                 *)
(*   - "rgn" is the post-state snapshot of the affected region:            *)
(*     {name, rsnState, rsnLoc, rsnProcOid, metaState, metaLoc, ssn}       *)
(*     with meta* taken from the harness's shadow of the last hbase:meta  *)
(*     Put for that region, and ssn the servers whose ServerStateNode      *)
(*     holds the region.                                                   *)
(* The first line is an "Init" snapshot of the workload table taken when   *)
(* tracing is armed (quiescent cluster; see instrumentation-spec.md).      *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

\* ---------------------------------------------------------------------------
\* Trace loading
\* ---------------------------------------------------------------------------
JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                 /\ x.tag = "trace"
                                 /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0
ASSUME TraceLog[1].event.name = "Init"

\* ---------------------------------------------------------------------------
\* Model constants derived from the Init line (Trace.cfg: Regions <- TraceRegions,
\* Servers <- TraceServers)
\* ---------------------------------------------------------------------------
InitEv      == TraceLog[1].event
InitRegions == InitEv.state.regions
TraceRegions == TLCEval({InitRegions[i].name : i \in 1..Len(InitRegions)})
TraceServers == TLCEval({InitEv.state.servers[i] : i \in 1..Len(InitEv.state.servers)})
InitRec(r) == InitRegions[CHOOSE i \in 1..Len(InitRegions) : InitRegions[i].name = r]

Srv(x) == IF x = "null" THEN NoServer ELSE x
SetOf(seq) == {seq[i] : i \in 1..Len(seq)}

\* ---------------------------------------------------------------------------
\* Cursor and id maps
\* ---------------------------------------------------------------------------
VARIABLES
    l,        \* cursor into TraceLog
    oidMap,   \* Java object identity (oid) -> model pid
    pidMap    \* real procId of a remote procedure -> model pid (bound at RrpbDispatch)

traceVars == <<l, oidMap, pidMap>>
allVars   == <<vars, traceVars>>

Ev  == TraceLog[l].event
Msg == Ev.msg
St  == Ev.state
IsEvent(n) == l <= Len(TraceLog) /\ Ev.name = n
Advance == l' = l + 1

Mapped(o) == o \in DOMAIN oidMap
P(o) == oidMap[o]                         \* model pid of an already-mapped object
Bind(o, p) == oidMap @@ (o :> p)          \* (left-biased: an existing binding wins)

\* ---------------------------------------------------------------------------
\* Post-state validation
\* ---------------------------------------------------------------------------
\* a region's attached TRSP vs the trace's oid ("0" = none).  An attached object that the
\* trace never saw run is the never-submitted TRSP of SplitCloseParentRegion (OrphanProc).
ProcIs(p, o) ==
    IF o = "0" THEN p = NoProc
    ELSE IF o \in DOMAIN oidMap' THEN p = oidMap'[o]
    ELSE p = OrphanProc

ValidateRegion(g) ==
    LET r == g.name IN
    /\ rsnState'[r] = g.rsnState
    /\ rsnLoc'[r] = Srv(g.rsnLoc)
    /\ ProcIs(rsnProc'[r], g.rsnProcOid)
    /\ metaState'[r] = g.metaState
    /\ metaLoc'[r] = Srv(g.metaLoc)
    /\ {s \in Servers : r \in ssn'[s]} = SetOf(g.ssn)

ValidatePc(p) == trsp'[p].pc = St.pc

\* ---------------------------------------------------------------------------
\* Initial state from the Init line
\* ---------------------------------------------------------------------------
TraceInit ==
    /\ l = 2
    /\ oidMap = [o \in {} |-> NoProc]
    /\ pidMap = [x \in {} |-> NoProc]
    /\ rsnState  = [r \in Regions |-> InitRec(r).rsnState]
    /\ rsnLoc    = [r \in Regions |-> Srv(InitRec(r).rsnLoc)]
    /\ lastHost  = [r \in Regions |-> Srv(InitRec(r).lastHost)]
    /\ metaState = [r \in Regions |-> InitRec(r).metaState]
    /\ metaLoc   = [r \in Regions |-> Srv(InitRec(r).metaLoc)]
    /\ rsnProc   = [r \in Regions |-> NoProc]
    /\ activeTrspCount = 0
    /\ serverState = [s \in Servers |-> "ONLINE"]
    /\ ssn = [s \in Servers |-> {r \in Regions : s \in SetOf(InitRec(r).ssn)}]
    /\ draining = {}
    /\ metaSplitParent = [r \in Regions |-> FALSE]
    /\ tableState = InitEv.state.table
    /\ rsOnline = [s \in Servers |-> TRUE]
    \* quiescent at arming: the RS hosts exactly the OPEN regions the master places on it
    /\ rsRegions = [s \in Servers |-> {r \in Regions : InitRec(r).rsnState = "OPEN"
                                                     /\ Srv(InitRec(r).rsnLoc) = s}]
    /\ msgs = {}
    /\ trsp = [p \in Pids |-> NoTrsp]
    /\ rrpb = [p \in Pids |-> NoRrpb]
    /\ nextPid = 1
    /\ schedLock = [r \in Regions |-> NoProc]
    /\ split = NoSplit
    /\ trunc = NoTrunc
    /\ scp = [s \in Servers |-> NoScp]
    /\ disable = NoDisable
    /\ opWait = IdleOp
    /\ balPlan = NoPlan
    /\ decom = NoDecom
    /\ rsg = NoRsg
    /\ targetFired = FALSE

\* ---------------------------------------------------------------------------
\* The target check (all callers) and the trace-only designed rejection
\* ---------------------------------------------------------------------------
TargetCheckEv ==
    /\ IsEvent("TargetCheck")
    /\ LET c  == Msg.caller
           r  == Msg.region
           op == Msg.op
           d  == Srv(Msg.dest)
       IN
       /\ CheckOutcome(r, op) = Msg.outcome
       /\ IF c = "operator" /\ DesignedRejection(op, r)
            THEN /\ OperatorRejectedRequest(r, op, d)          \* brief 3.1: not a finding
                 /\ oidMap' = oidMap
            ELSE /\ TargetCheck(c, r, op, d)
                 /\ oidMap' = IF Msg.outcome = "PASS" THEN Bind(Msg.trspOid, nextPid) ELSE oidMap
       /\ ValidateRegion(St.rgn)
    /\ UNCHANGED pidMap
    /\ Advance

\* ---------------------------------------------------------------------------
\* TRSP steps
\* ---------------------------------------------------------------------------
TrspGetAssignCandidateEv ==
    /\ IsEvent("TrspGetAssignCandidate")
    /\ Mapped(Msg.oid)
    /\ TrspGetAssignCandidate(P(Msg.oid))
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ ValidatePc(P(Msg.oid))
    /\ ValidateRegion(St.rgn)
    /\ Advance

AssignQueueAcceptPlanEv ==
    /\ IsEvent("AssignQueueAcceptPlan")
    /\ \E p \in Pids :
          /\ trsp[p].region = Msg.region
          /\ trsp[p].pc = "OPEN"
          /\ trsp[p].waitAssign
          /\ AssignQueueAcceptPlan(p, Srv(Msg.server))
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ rsnLoc'[Msg.region] = Srv(Msg.server)
    /\ Advance

TrspOpenEv ==
    /\ IsEvent("TrspOpen")
    /\ Mapped(Msg.oid)
    /\ TrspOpen(P(Msg.oid))
    /\ oidMap' = IF Msg.childOid = "0" THEN oidMap ELSE Bind(Msg.childOid, nextPid)
    /\ (Msg.childOid = "0") = (trsp'[P(Msg.oid)].child = NoProc)
    /\ UNCHANGED pidMap
    /\ ValidatePc(P(Msg.oid))
    /\ ValidateRegion(St.rgn)
    /\ Advance

TrspConfirmOpenedEv ==
    /\ IsEvent("TrspConfirmOpened")
    /\ Mapped(Msg.oid)
    /\ TrspConfirmOpened(P(Msg.oid))
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ ValidatePc(P(Msg.oid))
    /\ ValidateRegion(St.rgn)
    /\ Advance

TrspCloseEv ==
    /\ IsEvent("TrspClose")
    /\ Mapped(Msg.oid)
    /\ TrspClose(P(Msg.oid))
    /\ oidMap' = IF Msg.childOid = "0" THEN oidMap ELSE Bind(Msg.childOid, nextPid)
    /\ (Msg.childOid = "0") = (trsp'[P(Msg.oid)].child = NoProc)
    /\ UNCHANGED pidMap
    /\ ValidatePc(P(Msg.oid))
    /\ ValidateRegion(St.rgn)
    /\ Advance

TrspConfirmClosedEv ==
    /\ IsEvent("TrspConfirmClosed")
    /\ Mapped(Msg.oid)
    /\ TrspConfirmClosed(P(Msg.oid))
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ ValidatePc(P(Msg.oid))
    /\ ValidateRegion(St.rgn)
    /\ Advance

\* ---------------------------------------------------------------------------
\* Remote procedures, RegionServers, reports
\* ---------------------------------------------------------------------------
RrpbDispatchEv ==
    /\ IsEvent("RrpbDispatch")
    /\ Mapped(Msg.oid)
    /\ LET c == P(Msg.oid) IN
       /\ rrpb[c].target = Srv(Msg.target)
       /\ RrpbDispatch(c)
       /\ (Msg.outcome = "SENT") = rrpb'[c].sent
       /\ pidMap' = pidMap @@ (Msg.pid :> c)
    /\ UNCHANGED oidMap
    /\ Advance

RsOpenRegionEv ==
    /\ IsEvent("RsOpenRegion")
    /\ Msg.pid \in DOMAIN pidMap
    /\ LET c == pidMap[Msg.pid] IN
       /\ RsHandleOpen(Req("OPEN", Ev.nid, Msg.region, c))
       /\ (Msg.outcome = "OPENED") = (Report(Ev.nid, Msg.region, "OPENED", c) \in msgs')
       /\ Msg.region \in rsRegions'[Ev.nid]
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

RsCloseRegionEv ==
    /\ IsEvent("RsCloseRegion")
    /\ Msg.pid \in DOMAIN pidMap
    /\ LET c == pidMap[Msg.pid] IN
       /\ RsHandleClose(Req("CLOSE", Ev.nid, Msg.region, c))
       /\ (Msg.outcome = "CLOSED") = (Report(Ev.nid, Msg.region, "CLOSED", c) \in msgs')
       /\ Msg.region \notin rsRegions'[Ev.nid]
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

RemoteCallFailedEv ==
    /\ IsEvent("RemoteCallFailed")
    /\ Msg.pid \in DOMAIN pidMap
    /\ LET c == pidMap[Msg.pid]
           m == Req(rrpb[c].kind, Srv(Msg.server), rrpb[c].region, c)
       IN \/ RemoteCallFailed(m, FALSE)
          \/ /\ rsOnline[Srv(Msg.server)]
             /\ RemoteCallFailed(m, TRUE)
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

MasterReportTransitionEv ==
    /\ IsEvent("MasterReportTransition")
    /\ Msg.pid \in DOMAIN pidMap
    /\ LET c == pidMap[Msg.pid] IN
       /\ MasterReportTransition(Report(Srv(Msg.server), Msg.region, Msg.code, c))
       /\ (Msg.outcome = "ACCEPTED") = (rrpb'[c].st = "REPORT_SUCCEED" /\ rrpb[c].st = "DISPATCH")
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ ValidateRegion(St.rgn)
    /\ Advance

RrpbReportSucceedEv ==
    /\ IsEvent("RrpbReportSucceed")
    /\ Mapped(Msg.oid)
    /\ RrpbReportSucceed(P(Msg.oid))
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ ValidateRegion(St.rgn)
    /\ Advance

RrpbDispatchFailEv ==
    /\ IsEvent("RrpbDispatchFail")
    /\ Mapped(Msg.oid)
    /\ RrpbDispatchFail(P(Msg.oid))
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

RrpbServerCrashEv ==
    /\ IsEvent("RrpbServerCrash")
    /\ Mapped(Msg.oid)
    /\ RrpbServerCrash(P(Msg.oid))
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ ValidateRegion(St.rgn)
    /\ Advance

\* ---------------------------------------------------------------------------
\* DisableTableProcedure (workload)
\* ---------------------------------------------------------------------------
OperatorDisableEv ==
    /\ IsEvent("OperatorDisable")
    /\ OperatorDisable
    /\ oidMap' = Bind(Msg.oid, nextPid)
    /\ UNCHANGED pidMap
    /\ Advance

DisableSetDisablingEv ==
    /\ IsEvent("DisableSetDisabling")
    /\ DisableSetDisabling
    /\ tableState' = St.table
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

CloseTableRegionsScheduleEv ==
    /\ IsEvent("CloseTableRegionsSchedule")
    /\ CloseTableRegionsSchedule
    /\ LET ch     == Msg.children
           chOids == {ch[i].oid : i \in 1..Len(ch)}
           RegOf(o) == ch[CHOOSE i \in 1..Len(ch) : ch[i].oid = o].region
       IN /\ {ch[i].region : i \in 1..Len(ch)} = {r \in Regions : rsnProc'[r] # rsnProc[r]}
          /\ oidMap' = oidMap @@ [o \in chOids |-> rsnProc'[RegOf(o)]]
    /\ UNCHANGED pidMap
    /\ Advance

CloseTableRegionsConfirmEv ==
    /\ IsEvent("CloseTableRegionsConfirm")
    /\ CloseTableRegionsConfirm
    /\ disable'.st = (IF Msg.outcome = "DONE" THEN "SET_DISABLED" ELSE "SCHEDULE")
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

DisableSetDisabledEv ==
    /\ IsEvent("DisableSetDisabled")
    /\ DisableSetDisabled
    /\ tableState' = St.table
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

\* ---------------------------------------------------------------------------
\* Split (S1).  Not exercised by testDisableAndMove; used by workload variants.
\* ---------------------------------------------------------------------------
SplitSubmitEv ==
    /\ IsEvent("SplitSubmit")
    /\ SplitSubmit(Msg.region)
    /\ oidMap' = Bind(Msg.oid, nextPid)
    /\ UNCHANGED pidMap
    /\ Advance

SmpExecuteEntryEv ==
    /\ IsEvent("SmpExecuteEntry")
    /\ SmpExecuteEntry
    /\ (split'.st = "rollback") = Msg.aborted
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

SplitStepEv(name, A, next) ==
    /\ IsEvent(name)
    /\ A
    /\ split'.st = St.st
    /\ (next = "" \/ SplitCurrentState' = next \/ split'.st = "rollback")
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ ValidateRegion(St.rgn)
    /\ Advance

SplitPrepareEv              == SplitStepEv("SplitPrepare", SplitPrepare, "")
SplitCheckClosedRegionsEv   == SplitStepEv("SplitCheckClosedRegions", SplitCheckClosedRegions, "")
SplitCreateDaughterRegionsEv == SplitStepEv("SplitCreateDaughterRegions", SplitCreateDaughterRegions, "")
SplitUpdateMetaEv           == SplitStepEv("SplitUpdateMeta", SplitUpdateMeta, "")
SplitAfterMetaEv            == SplitStepEv("SplitAfterMeta", SplitAfterMeta, "")

SplitPreOperationEv ==
    /\ IsEvent("SplitPreOperation")
    /\ SplitPreOperation(Msg.failed)
    /\ split'.st = St.st
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

SplitCloseParentRegionEv ==
    /\ IsEvent("SplitCloseParentRegion")
    /\ SplitCloseParentRegion
    /\ oidMap' = IF Msg.outcome = "ATTACHED" THEN Bind(Msg.childOid, nextPid) ELSE oidMap
    /\ split'.st = St.st
    /\ UNCHANGED pidMap
    /\ ValidateRegion(St.rgn)
    /\ Advance

SplitRollbackStepEv ==
    /\ IsEvent("SplitRollbackStep")
    /\ SplitRollbackStep
    /\ oidMap' = IF Msg.reopenOid = "0" THEN oidMap ELSE Bind(Msg.reopenOid, nextPid)
    /\ split'.st = St.st
    /\ UNCHANGED pidMap
    /\ ValidateRegion(St.rgn)
    /\ Advance

OperatorAbortSplitEv ==
    /\ IsEvent("OperatorAbortSplit")
    /\ OperatorAbortSplit
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

\* ---------------------------------------------------------------------------
\* Truncate (S2).  Not exercised by testDisableAndMove; used by workload variants.
\* ---------------------------------------------------------------------------
OperatorTruncateEv ==
    /\ IsEvent("OperatorTruncate")
    /\ OperatorTruncate(Msg.region)
    /\ oidMap' = Bind(Msg.oid, nextPid)
    /\ UNCHANGED pidMap
    /\ Advance

TruncPreOperationEv ==
    /\ IsEvent("TruncPreOperation")
    /\ TruncPreOperation
    /\ trunc'.st = St.st
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

TruncMakeOfflineEv ==
    /\ IsEvent("TruncMakeOffline")
    /\ TruncMakeOffline
    /\ oidMap' = Bind(Msg.childOid, nextPid)
    /\ UNCHANGED pidMap
    /\ ValidateRegion(St.rgn)
    /\ Advance

TruncRemoveEv ==
    /\ IsEvent("TruncRemove")
    /\ TruncRemove
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

TruncMakeOnlineEv ==
    /\ IsEvent("TruncMakeOnline")
    /\ TruncMakeOnline
    /\ oidMap' = Bind(Msg.childOid, nextPid)
    /\ UNCHANGED pidMap
    /\ ValidateRegion(St.rgn)
    /\ Advance

TruncPostOperationEv ==
    /\ IsEvent("TruncPostOperation")
    /\ TruncPostOperation
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

\* ---------------------------------------------------------------------------
\* Balancer, decommission, RSGroup (S2/S3 callers)
\* ---------------------------------------------------------------------------
BalancerPlanEv ==
    /\ IsEvent("BalancerPlan")
    /\ BalancerPlan(Msg.region, Srv(Msg.dest))
    /\ balPlan'.src = Srv(Msg.src)
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

BalancerSkipPlanEv ==
    /\ IsEvent("BalancerSkipPlan")
    /\ BalancerSkipPlan
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

OperatorDecommissionEv ==
    /\ IsEvent("OperatorDecommission")
    /\ OperatorDecommission(Msg.server)
    /\ decom'.todo = Msg.regions
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

DecomNoDestinationEv ==
    /\ IsEvent("DecomNoDestination")
    /\ DecomNoDestination
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

OperatorRsgMoveServersEv ==
    /\ IsEvent("OperatorRsgMoveServers")
    /\ OperatorRsgMoveServers(Msg.server)
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

RsgSelectEv ==
    /\ IsEvent("RsgSelect")
    /\ RsgSelect
    /\ rsg'.todo = Msg.regions
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

RsgNoDestinationEv ==
    /\ IsEvent("RsgNoDestination")
    /\ RsgNoDestination
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

RsgEndRoundEv ==
    /\ IsEvent("RsgEndRound")
    /\ RsgEndRound
    /\ rsg'.st = St.st
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

\* ---------------------------------------------------------------------------
\* RS crash, SCP, master failover
\* ---------------------------------------------------------------------------
RsCrashEv ==
    /\ IsEvent("RsCrash")
    /\ RsCrash(Msg.server)
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

MasterExpireServerEv ==
    /\ IsEvent("MasterExpireServer")
    /\ MasterExpireServer(Msg.server)
    /\ oidMap' = Bind(Msg.oid, nextPid)
    /\ UNCHANGED pidMap
    /\ Advance

ScpGetRegionsEv ==
    /\ IsEvent("ScpGetRegions")
    /\ ScpGetRegions(Msg.server)
    /\ scp'[Msg.server].todo = SetOf(Msg.regions)
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

ScpAssignRegionEv ==
    /\ IsEvent("ScpAssignRegion")
    /\ ScpAssignRegion(Msg.server, Msg.region)
    /\ oidMap' = IF Msg.childOid = "0" THEN oidMap ELSE Bind(Msg.childOid, nextPid)
    /\ UNCHANGED pidMap
    /\ ValidateRegion(St.rgn)
    /\ Advance

ScpFinishEv ==
    /\ IsEvent("ScpFinish")
    /\ ScpFinish(Msg.server)
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

MasterFailoverEv ==
    /\ IsEvent("MasterFailover")
    /\ MasterFailover
    /\ UNCHANGED <<oidMap, pidMap>>
    /\ Advance

\* ---------------------------------------------------------------------------
\* Next / spec / properties
\* ---------------------------------------------------------------------------
\* end of trace: stutter (keeps deadlock detection quiet; not a <TraceNext>_v step)
TraceDone == l > Len(TraceLog) /\ UNCHANGED allVars

TraceNext ==
    \/ TargetCheckEv
    \/ TrspGetAssignCandidateEv
    \/ AssignQueueAcceptPlanEv
    \/ TrspOpenEv
    \/ TrspConfirmOpenedEv
    \/ TrspCloseEv
    \/ TrspConfirmClosedEv
    \/ RrpbDispatchEv
    \/ RsOpenRegionEv
    \/ RsCloseRegionEv
    \/ RemoteCallFailedEv
    \/ MasterReportTransitionEv
    \/ RrpbReportSucceedEv
    \/ RrpbDispatchFailEv
    \/ RrpbServerCrashEv
    \/ OperatorDisableEv
    \/ DisableSetDisablingEv
    \/ CloseTableRegionsScheduleEv
    \/ CloseTableRegionsConfirmEv
    \/ DisableSetDisabledEv
    \/ SplitSubmitEv
    \/ SmpExecuteEntryEv
    \/ SplitPrepareEv
    \/ SplitPreOperationEv
    \/ SplitCloseParentRegionEv
    \/ SplitCheckClosedRegionsEv
    \/ SplitCreateDaughterRegionsEv
    \/ SplitUpdateMetaEv
    \/ SplitAfterMetaEv
    \/ SplitRollbackStepEv
    \/ OperatorAbortSplitEv
    \/ OperatorTruncateEv
    \/ TruncPreOperationEv
    \/ TruncMakeOfflineEv
    \/ TruncRemoveEv
    \/ TruncMakeOnlineEv
    \/ TruncPostOperationEv
    \/ BalancerPlanEv
    \/ BalancerSkipPlanEv
    \/ OperatorDecommissionEv
    \/ DecomNoDestinationEv
    \/ OperatorRsgMoveServersEv
    \/ RsgSelectEv
    \/ RsgNoDestinationEv
    \/ RsgEndRoundEv
    \/ RsCrashEv
    \/ MasterExpireServerEv
    \/ ScpGetRegionsEv
    \/ ScpAssignRegionEv
    \/ ScpFinishEv
    \/ MasterFailoverEv
    \/ TraceDone

TraceSpec == TraceInit /\ [][TraceNext]_allVars /\ WF_allVars(TraceNext)

\* the whole trace was consumed (Trace.cfg PROPERTIES)
TraceMatched == <>(l > Len(TraceLog))

TraceView == <<vars, l>>

TraceAlias ==
    [ cursor   |-> l,
      traceLen |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN Ev.name ELSE "DONE",
      evMsg    |-> IF l <= Len(TraceLog) THEN Msg ELSE "DONE",
      evState  |-> IF l <= Len(TraceLog) THEN St ELSE "DONE",
      rsnState |-> rsnState,
      rsnLoc   |-> rsnLoc,
      rsnProc  |-> rsnProc,
      metaState |-> metaState,
      metaLoc  |-> metaLoc,
      ssn      |-> ssn,
      trsp     |-> trsp,
      rrpb     |-> rrpb,
      msgs     |-> msgs,
      oidMap   |-> oidMap,
      pidMap   |-> pidMap,
      targetFired |-> targetFired ]
=============================================================================
