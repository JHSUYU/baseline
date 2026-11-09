-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hbase-adhoc-31), Category A: one linear  *)
(* NDJSON trace from the single-JVM mini cluster of the workload test      *)
(* TestRetainAssignmentOnRestart#testForceRetainAssignment (or a variant in *)
(* the same module). Event names equal base action names; fields and code  *)
(* locations are defined in instrumentation-spec.md.                       *)
(*                                                                         *)
(* Line 1 of the trace is a "Bootstrap" snapshot taken after setupCluster   *)
(* (Test:236-259): RegionServers, user-region placement, empty DeadServer.  *)
(* ServerNames are {host, port, sc}; sc is the startcode MINUS the trace's  *)
(* epoch (TLC integers are 32-bit), so only order is preserved, which is    *)
(* all the model uses. port = 0 encodes a null ServerName.                 *)
(*                                                                         *)
(* Real procedure ids are mapped to model ids at RrpDispatch, where the     *)
(* dispatched procedure is the region TRSP's attached child (RRPB:340).     *)
(* hbase:meta procedures and reports are filtered out by the harness.      *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC, FiniteSets, Naturals

-----------------------------------------------------------------------------
(* Trace loading                                                           *)

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                 /\ x.tag = "trace"
                                 /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0

Boot == TraceLog[1].event
ASSUME Boot.name = "Bootstrap"

SetOf(s) == {s[k] : k \in DOMAIN s}

\* Constant overrides (Trace.cfg): sizes come from the trace
TraceNAddr   == Len(Boot.servers)
TraceMaxInc  == TraceNAddr + Len(SelectSeq(TraceLog, LAMBDA x : x.event.name = "RsConstruct"))
TraceRegions == {Boot.regions[k].region : k \in DOMAIN Boot.regions}
TraceHostOf(a) == "localhost"            \* mini cluster: every RS on one host, different ports

\* Initial incarnation k binds address k: Bootstrap lists servers in that order
AddrOfPort(p) == CHOOSE k \in 1..TraceNAddr : Boot.servers[k].port = p
ASSUME \A k \in DOMAIN Boot.servers : Boot.servers[k].sc > 0

-----------------------------------------------------------------------------
(* Trace cursor and trace-only bookkeeping                                 *)

VARIABLES
    l,          \* index of the next trace line to match
    pidMap      \* real procedure id -> model pid (set at RrpDispatch)

traceVars == <<l, pidMap>>

logline == TraceLog[l]
E == logline.event

IsEvent(n) == l <= Len(TraceLog) /\ E.name = n
StepTrace == l' = l + 1

\* Incarnation lookup by startcode (startcodes are unique; state-based, constructed incarnations only)
IncOfSc(s) ==
    IF \E i \in Inc : rsPhase[i] # "none" /\ sc[i] = s
    THEN CHOOSE i \in Inc : rsPhase[i] # "none" /\ sc[i] = s
    ELSE 0
SnInc(sn)     == IF sn.port = 0 THEN 0 ELSE IncOfSc(sn.sc)
IncSetOf(s)   == {SnInc(s[k]) : k \in DOMAIN s}
MP(rp)        == IF rp \in DOMAIN pidMap THEN pidMap[rp] ELSE 0
MPs(s)        == {MP(s[k]) : k \in DOMAIN s}
KnownPids(s)  == \A k \in DOMAIN s : s[k] \in DOMAIN pidMap

-----------------------------------------------------------------------------
(* Post-state validation helpers (fields captured per instrumentation-spec) *)

\* ServerManager membership after the event: onlineServers keys, the subset that reported, DeadServer
ValidateMembership ==
    /\ {i \in Inc : online'[i] # NoSp} = IncSetOf(E.online)
    /\ {i \in Inc : online'[i] # NoSp /\ reported'[i]} = IncSetOf(E.reported)
    /\ {i \in Inc : dead'[i] # NoSp} = IncSetOf(E.dead)

\* RegionStateNode after the event: state and location
ValidateRegion(r) ==
    /\ rstate'[r] = E.rstate
    /\ loc'[r].i = SnInc(E.loc)

-----------------------------------------------------------------------------
(* Bootstrap state                                                         *)

BootLoc(r)  == CHOOSE k \in DOMAIN Boot.regions : Boot.regions[k].region = r
BootInc(sn) == AddrOfPort(sn.port)   \* initial incarnation id = its address index

TraceInit ==
    /\ incAddr   = [i \in Inc |-> IF i \in InitInc THEN i ELSE 0]
    /\ sc        = [i \in Inc |-> IF i \in InitInc THEN Boot.servers[i].sc ELSE 0]
    /\ rsPhase   = [i \in Inc |-> IF i \in InitInc THEN "online" ELSE "none"]
    /\ holder    = [a \in Addr |-> a]
    /\ znode     = [i \in Inc |-> i \in InitInc]
    /\ rsRegions = [i \in Inc |-> {r \in Region : BootInc(Boot.regions[BootLoc(r)].loc) = i}]
    /\ rsTasks   = [i \in Inc |-> {}]
    /\ mPhase    = "ready"
    /\ online    = [i \in Inc |-> IF i \in InitInc THEN DeploySp ELSE NoSp]
    /\ reported  = [i \in Inc |-> i \in InitInc]
    /\ dead      = [i \in Inc |-> NoSp]
    /\ srvNode   = [i \in Inc |-> IF i \in InitInc THEN "ONLINE" ELSE "none"]
    /\ rsList    = InitInc
    /\ rstView   = InitInc
    /\ failedSrv = {}
    /\ dNode     = [i \in Inc |-> IF i \in InitInc THEN DeploySp ELSE NoSp]
    /\ buf       = [i \in Inc |-> {}]
    /\ calls     = {}
    /\ scp       = [i \in Inc |-> "none"]
    /\ scpRegs   = [i \in Inc |-> {}]
    /\ trsp      = [r \in Region |-> NoTRSP]
    /\ rrp       = <<>>
    /\ nextPid   = 1
    /\ rstate    = [r \in Region |-> "OPEN"]
    /\ loc       = [r \in Region |-> SN(BootInc(Boot.regions[BootLoc(r)].loc), DeploySp)]
    /\ lastHost  = [r \in Region |-> LET lh == Boot.regions[BootLoc(r)].lastHost IN
                                     IF lh.port = 0 THEN NoSN ELSE SN(BootInc(lh), DeploySp)]
    /\ targetFired = FALSE
    /\ l = 2
    /\ pidMap = <<>>

-----------------------------------------------------------------------------
(* Action wrappers: match the event, run the base action, validate, advance *)

\* --- RegionServer lifecycle ---

RsConstructIfLogged ==
    /\ IsEvent("RsConstruct")
    /\ RsConstruct(AddrOfPort(E.sn.port), E.sn.sc)
    /\ \E i \in Inc : rsPhase[i] = "none" /\ rsPhase'[i] = "bound" /\ sc'[i] = E.sn.sc
                      /\ holder'[AddrOfPort(E.sn.port)] = i
    /\ StepTrace /\ UNCHANGED pidMap

RsStartRpcIfLogged ==
    /\ IsEvent("RsStartRpc")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsStartRpc(i)
       /\ rsPhase'[i] = "started"
    /\ StepTrace /\ UNCHANGED pidMap

RsReportForDutyIfLogged ==
    /\ IsEvent("RsReportForDuty")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsReportForDuty(i)
       /\ rsPhase'[i] = "registered"
       /\ (online'[i] # NoSp) = E.recorded              \* SM:279 checkAndRecordNewServer result
       /\ ValidateMembership
    /\ StepTrace /\ UNCHANGED pidMap

RsCreateEphemeralNodeIfLogged ==
    /\ IsEvent("RsCreateEphemeralNode")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsCreateEphemeralNode(i)
       /\ znode'[i] /\ rsPhase'[i] = "registered"
    /\ StepTrace /\ UNCHANGED pidMap

RsOnlineIfLogged ==
    /\ IsEvent("RsOnline")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsOnline(i)
       /\ rsPhase'[i] = "online" /\ znode'[i]
    /\ StepTrace /\ UNCHANGED pidMap

\* Logged only when the report changed master state (first report, (re)record, clean, YouAreDead)
RsReportIfLogged ==
    /\ IsEvent("RsReport")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsReport(i)
       /\ (rsPhase'[i] = "stopping") = E.youAreDead
       /\ ValidateMembership
    /\ StepTrace /\ UNCHANGED pidMap

RsStopIfLogged ==
    /\ IsEvent("RsStop")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsStop(i)
       /\ rsPhase'[i] = "stopping"
    /\ StepTrace /\ UNCHANGED pidMap

RsExitIfLogged ==
    /\ IsEvent("RsExit")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsExit(i)
       /\ holder'[incAddr[i]] = 0
    /\ StepTrace /\ UNCHANGED pidMap

ZnodeDeleteIfLogged ==
    /\ IsEvent("ZnodeDelete")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ ZnodeDelete(i)
       /\ ~znode'[i]
    /\ StepTrace /\ UNCHANGED pidMap

\* --- RegionServer region handlers + master-side report (AM:1260-1303) ---

RsCloseRegionOnStopIfLogged ==
    /\ IsEvent("RsCloseRegionOnStop")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsCloseRegionOnStop(i, E.region)
       /\ E.region \notin rsRegions'[i]
       /\ ValidateRegion(E.region)
    /\ StepTrace /\ UNCHANGED pidMap

RsOpenRegionIfLogged ==
    /\ IsEvent("RsOpenRegion")
    /\ E.pid \in DOMAIN pidMap
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsOpenRegion(i, [r |-> E.region, k |-> "open", p |-> MP(E.pid)])
       /\ E.region \in rsRegions'[i]
       /\ (E.region \in rsRegions[i]) = ~E.reported     \* ARH:104-113 already online: no report
       /\ ValidateRegion(E.region)
    /\ StepTrace /\ UNCHANGED pidMap

RsCloseRegionIfLogged ==
    /\ IsEvent("RsCloseRegion")
    /\ E.pid \in DOMAIN pidMap
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ RsCloseRegion(i, [r |-> E.region, k |-> "close", p |-> MP(E.pid)])
       /\ E.region \notin rsRegions'[i]
       /\ (E.region \in rsRegions[i]) = E.reported      \* URH:114-120 not online: no report
       /\ ValidateRegion(E.region)
    /\ StepTrace /\ UNCHANGED pidMap

\* --- Master membership ---

TrackerRefreshIfLogged ==
    /\ IsEvent("TrackerRefresh")
    /\ {i \in Inc : znode[i]} = IncSetOf(E.children)   \* RST:200, 207-210 children listed
    /\ TrackerRefresh
    /\ ValidateMembership
    /\ StepTrace /\ UNCHANGED pidMap

\* --- Dispatcher ---

CallOfPids(c) == c.procs = MPs(E.pids)

BufferFlushIfLogged ==
    /\ IsEvent("BufferFlush")
    /\ KnownPids(E.pids)
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ buf[i] = MPs(E.pids)
       /\ BufferFlush(i)
       /\ \E c \in calls' : CallOfPids(c) /\ c.mode = (IF E.online THEN "run" ELSE "dead")  \* RSPD:153
    /\ StepTrace /\ UNCHANGED pidMap

DeadCallRunIfLogged ==
    /\ IsEvent("DeadCallRun")
    /\ KnownPids(E.pids)
    /\ \E c \in calls : CallOfPids(c) /\ DeadCallRun(c)
    /\ StepTrace /\ UNCHANGED pidMap

CallSendIfLogged ==
    /\ IsEvent("CallSend")
    /\ KnownPids(E.pids) /\ KnownPids(E.ops)
    /\ \E c \in calls : CallOfPids(c) /\ CallSend(c)
    /\ \E c2 \in calls' : CallOfPids(c2) /\ c2.ops = MPs(E.ops)   \* remoteCallBuild result (RRPB:92-100)
    /\ StepTrace /\ UNCHANGED pidMap

\* Master side: connection-level failure, nothing bound at host:port
CallDeliverNoServerIfLogged ==
    /\ IsEvent("CallDeliverNoServer")
    /\ KnownPids(E.pids)
    /\ \E c \in calls : CallOfPids(c) /\ CallDeliverNoServer(c)
    /\ StepTrace /\ UNCHANGED pidMap

\* RS side events identify the call by the request it carries: open/close proc ids and the stamped startcode.
\* A re-send whose procs are all REPORT_SUCCEED has no open/close request (RRPB:92-100), so no startcode to log.
SentCall(c) == /\ c.mode = "sent"
               /\ c.ops = MPs(E.ops)
               /\ c.ops = {} \/ sc[c.sn.i] = E.stamp

CallDeliverNotStartedIfLogged ==
    /\ IsEvent("CallDeliverNotStarted")
    /\ KnownPids(E.ops)
    /\ \E c \in calls : /\ SentCall(c)
                        /\ Recv(c) = SnInc(E.receiver)     \* delivery by address (ARC:463-464)
                        /\ CallDeliverNotStarted(c)
    /\ StepTrace /\ UNCHANGED pidMap

CallDeliverCheckOpenFailIfLogged ==
    /\ IsEvent("CallDeliverCheckOpenFail")
    /\ KnownPids(E.ops)
    /\ \E c \in calls : /\ SentCall(c)
                        /\ Recv(c) = SnInc(E.receiver)
                        /\ CallDeliverCheckOpenFail(c)
                        /\ \E c2 \in calls' : c2.procs = c.procs /\ c2.out = E.outcome
    /\ StepTrace /\ UNCHANGED pidMap

\* The target (RSR:4017-4018). E.fired is the outcome of RSR:1877 as the RS evaluated it.
TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ KnownPids(E.ops)
    /\ \E c \in calls : /\ SentCall(c)
                        /\ Recv(c) = SnInc(E.receiver)
                        /\ TargetCheck(c)
                        /\ \E c2 \in calls' : c2.procs = c.procs /\ (c2.out = "dnr") = E.fired
    /\ StepTrace /\ UNCHANGED pidMap

CallSucceededIfLogged ==
    /\ IsEvent("CallSucceeded")
    /\ KnownPids(E.pids)
    /\ \E c \in calls : CallOfPids(c) /\ CallSucceeded(c)
    /\ StepTrace /\ UNCHANGED pidMap

\* E.decision: "retry" (scheduleForRetry true), "giveup" (false), "failfast" (RSPD:326-337)
CallFailedIfLogged ==
    /\ IsEvent("CallFailed")
    /\ KnownPids(E.pids)
    /\ \E c \in calls : /\ CallOfPids(c)
                        /\ CallFailed(c)
                        /\ (\E c2 \in calls' : c2.procs = c.procs) = (E.decision = "retry")
                        /\ (E.decision = "failfast") => dead'[c.sn.i] # NoSp
    /\ ValidateMembership
    /\ StepTrace /\ UNCHANGED pidMap

CallSnryeTimeoutIfLogged ==
    /\ IsEvent("CallSnryeTimeout")
    /\ KnownPids(E.pids)
    /\ \E c \in calls : CallOfPids(c) /\ CallSnryeTimeout(c)
    /\ StepTrace /\ UNCHANGED pidMap

\* --- Open/CloseRegionProcedure ---

\* RRPB:335-350. The dispatched procedure is the attached child of the region's TRSP; record its real id.
RrpDispatchIfLogged ==
    /\ IsEvent("RrpDispatch")
    /\ trsp[E.region] # NoTRSP /\ trsp[E.region].child # 0
    /\ LET p == trsp[E.region].child IN
       /\ rrp[p].k = E.kind
       /\ rrp[p].tgt.i = SnInc(E.target)
       /\ RrpDispatch(p)
       /\ IF E.result = "queued" THEN p \in buf'[rrp[p].tgt.i]     \* RRPB:340
                                 ELSE rrp'[p].fin                   \* RRPB:341-346 NoServerDispatchException
       /\ pidMap' = pidMap @@ (E.pid :> p)
    /\ StepTrace

RrpFinishIfLogged ==
    /\ IsEvent("RrpFinish")
    /\ E.pid \in DOMAIN pidMap
    /\ LET p == MP(E.pid) IN
       /\ rrp[p].st = E.state
       /\ RrpFinish(p)
       /\ ValidateRegion(rrp[p].r)
    /\ StepTrace /\ UNCHANGED pidMap

\* --- TransitRegionStateProcedure / AM assign thread ---

TrspQueueAssignIfLogged ==
    /\ IsEvent("TrspQueueAssign")
    /\ TrspQueueAssign(E.region)
    /\ trsp'[E.region].st = (IF E.outcome = "wait" THEN "WAIT_RETAIN" ELSE "WAIT_PLAN")
    /\ loc'[E.region].i = SnInc(E.loc)
    /\ StepTrace /\ UNCHANGED pidMap

\* A force-retain re-check that suspends again with the same location changes no modeled state
\* (TRSP:227-237 retries every 50 ms * 2^k); base.tla omits that self-loop, so it is a trace-only stutter.
TrspQueueAssignRepeatIfLogged ==
    /\ IsEvent("TrspQueueAssign")
    /\ E.outcome = "wait"
    /\ trsp[E.region] # NoTRSP /\ trsp[E.region].st = "WAIT_RETAIN"
    /\ loc[E.region].i = SnInc(E.loc)
    /\ UNCHANGED vars
    /\ StepTrace /\ UNCHANGED pidMap

\* TRSP:227 false, TRSP:239-243: the force-retain retries ran out
TrspForceRetainGiveUpIfLogged ==
    /\ IsEvent("TrspForceRetainGiveUp")
    /\ TrspForceRetainGiveUp(E.region)
    /\ trsp'[E.region].st = "WAIT_PLAN"
    /\ loc'[E.region].i = SnInc(E.loc)
    /\ StepTrace /\ UNCHANGED pidMap

AmAssignIfLogged ==
    /\ IsEvent("AmAssign")
    /\ AmAssign(E.region)
    /\ loc'[E.region].i = SnInc(E.target)                 \* AM:2655 plan target
    /\ StepTrace /\ UNCHANGED pidMap

TrspOpenIfLogged ==
    /\ IsEvent("TrspOpen")
    /\ TrspOpen(E.region)
    /\ (trsp'[E.region].st = "CONFIRM_OPENED") = (E.outcome = "orp")
    /\ ValidateRegion(E.region)
    /\ StepTrace /\ UNCHANGED pidMap

TrspConfirmOpenedIfLogged ==
    /\ IsEvent("TrspConfirmOpened")
    /\ TrspConfirmOpened(E.region)
    /\ (trsp'[E.region] = NoTRSP) = (E.outcome = "done")
    /\ StepTrace /\ UNCHANGED pidMap

TrspCloseIfLogged ==
    /\ IsEvent("TrspClose")
    /\ TrspClose(E.region)
    /\ (trsp'[E.region].st = "CONFIRM_CLOSED") = (E.outcome = "crp")
    /\ ValidateRegion(E.region)
    /\ StepTrace /\ UNCHANGED pidMap

\* E.outcome: "done" | "reopen" | "retryClose" | "abnormal"
TrspConfirmClosedIfLogged ==
    /\ IsEvent("TrspConfirmClosed")
    /\ TrspConfirmClosed(E.region)
    /\ CASE E.outcome = "done"       -> trsp'[E.region] = NoTRSP
         [] E.outcome = "retryClose" -> trsp'[E.region].st = "CLOSE"
         [] OTHER                    -> trsp'[E.region].st = "GET_ASSIGN_CANDIDATE"
    /\ StepTrace /\ UNCHANGED pidMap

\* --- ServerCrashProcedure ---

ScpStartIfLogged ==
    /\ IsEvent("ScpStart")
    /\ LET i == SnInc(E.sn) IN i # 0 /\ ScpStart(i)
    /\ StepTrace /\ UNCHANGED pidMap

ScpGetRegionsIfLogged ==
    /\ IsEvent("ScpGetRegions")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ ScpGetRegions(i)
       /\ scpRegs'[i] = SetOf(E.regions)                  \* SCP:205 regionsOnCrashedServer (user regions)
    /\ StepTrace /\ UNCHANGED pidMap

ScpSplitLogsIfLogged ==
    /\ IsEvent("ScpSplitLogs")
    /\ LET i == SnInc(E.sn) IN i # 0 /\ ScpSplitLogs(i)
    /\ StepTrace /\ UNCHANGED pidMap

ScpAssignIfLogged ==
    /\ IsEvent("ScpAssign")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ ScpAssign(i)
       /\ {r \in Region : trsp'[r] # NoTRSP /\ trsp'[r].parent = i /\ trsp[r] = NoTRSP}
            = SetOf(E.assigned)                           \* SCP:628-635 new TRSPs
       /\ {r \in Region : trsp[r] # NoTRSP /\ loc[r].i = i /\ r \in scpRegs[i]}
            = SetOf(E.interrupted)                        \* SCP:612-618 serverCrashed
    /\ StepTrace /\ UNCHANGED pidMap

ScpFinishIfLogged ==
    /\ IsEvent("ScpFinish")
    /\ LET i == SnInc(E.sn) IN
       /\ i # 0
       /\ ScpFinish(i)
       /\ srvNode'[i] = "none"
    /\ StepTrace /\ UNCHANGED pidMap

\* --- Client (only in workload variants that call admin.move) ---

ClientMoveIfLogged ==
    /\ IsEvent("ClientMove")
    /\ LET d == SnInc(E.dest) IN
       /\ d # 0
       /\ ClientMove(E.region, SN(d, DeploySp))
    /\ StepTrace /\ UNCHANGED pidMap

-----------------------------------------------------------------------------
(* Client-side failed-servers list (ARC:360-366): no event of its own, as a  *)
(* refused call never reaches a server and the expiry is only time passing.  *)
(* Each step is forced by the next event, so the replay stays deterministic. *)

\* The next event is a delivery of c, which proves that c's address had left the list
NextEventDelivers(c) ==
    /\ l <= Len(TraceLog)
    /\ \/ E.name = "CallDeliverNoServer" /\ c.procs = MPs(E.pids)
       \/ /\ E.name \in {"TargetCheck", "CallDeliverCheckOpenFail", "CallDeliverNotStarted"}
          /\ SentCall(c) /\ Recv(c) = SnInc(E.receiver)

FailedServerExpireSilent ==
    /\ \E c \in calls : /\ c.mode = "sent" /\ CallAddr(c) \in failedSrv
                        /\ NextEventDelivers(c)
                        /\ FailedServerExpire(CallAddr(c))
    /\ UNCHANGED traceVars

\* The next event is the failure of a sent call that no server saw
CallDeliverFailedServerSilent ==
    /\ IsEvent("CallFailed")
    /\ KnownPids(E.pids)
    /\ \E c \in calls : CallOfPids(c) /\ CallDeliverFailedServer(c)
    /\ UNCHANGED traceVars

(* Otherwise there are no silent actions: every modeled step of the workload *)
(* is logged. Report events that change nothing (RsReport after the first    *)
(* one) are stutters and are not logged. RsCrash, RsConstructClockBack and   *)
(* master failover have no instrumentation (no mini-cluster utility performs *)
(* them).                                                                    *)

TraceNext ==
    \/ FailedServerExpireSilent
    \/ CallDeliverFailedServerSilent
    \/ RsConstructIfLogged
    \/ RsStartRpcIfLogged
    \/ RsReportForDutyIfLogged
    \/ RsCreateEphemeralNodeIfLogged
    \/ RsOnlineIfLogged
    \/ RsReportIfLogged
    \/ RsStopIfLogged
    \/ RsExitIfLogged
    \/ ZnodeDeleteIfLogged
    \/ RsCloseRegionOnStopIfLogged
    \/ RsOpenRegionIfLogged
    \/ RsCloseRegionIfLogged
    \/ TrackerRefreshIfLogged
    \/ BufferFlushIfLogged
    \/ DeadCallRunIfLogged
    \/ CallSendIfLogged
    \/ CallDeliverNoServerIfLogged
    \/ CallDeliverNotStartedIfLogged
    \/ CallDeliverCheckOpenFailIfLogged
    \/ TargetCheckIfLogged
    \/ CallSucceededIfLogged
    \/ CallFailedIfLogged
    \/ CallSnryeTimeoutIfLogged
    \/ RrpDispatchIfLogged
    \/ RrpFinishIfLogged
    \/ TrspQueueAssignIfLogged
    \/ TrspQueueAssignRepeatIfLogged
    \/ TrspForceRetainGiveUpIfLogged
    \/ AmAssignIfLogged
    \/ TrspOpenIfLogged
    \/ TrspConfirmOpenedIfLogged
    \/ TrspCloseIfLogged
    \/ TrspConfirmClosedIfLogged
    \/ ScpStartIfLogged
    \/ ScpGetRegionsIfLogged
    \/ ScpSplitLogsIfLogged
    \/ ScpAssignIfLogged
    \/ ScpFinishIfLogged
    \/ ClientMoveIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, traceVars>> /\ WF_<<vars, traceVars>>(TraceNext)

\* The whole trace was consumed
TraceMatched == <>(l > Len(TraceLog))

TraceView == <<vars, l>>

TraceAlias == [l |-> l, event |-> IF l <= Len(TraceLog) THEN E.name ELSE "END",
               rsPhase |-> rsPhase, holder |-> holder, online |-> online, dead |-> dead,
               trsp |-> trsp, rrp |-> rrp, calls |-> calls, scp |-> scp,
               rstate |-> rstate, loc |-> loc, targetFired |-> targetFired]

=============================================================================
