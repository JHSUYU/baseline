-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hbase-adhoc-31: can RSRpcServices.throwOnWrongStartCode fire?           *)
(*                                                                         *)
(* Ad hoc coordination target (target.yaml, apache/hbase @ 1790942bb2):    *)
(*   RSRpcServices.java:1877  if (server.getServerName().getStartcode()    *)
(*                                 != serverStartCode)                     *)
(*   RSRpcServices.java:1878    throw new ServiceException(                *)
(*                                new DoNotRetryIOException(...))          *)
(*                                                                         *)
(* Category A (distributed / message passing). The HMaster names region    *)
(* servers by incarnation (host, port, startcode); the RPC layer delivers  *)
(* by address (host:port). The guard compares the startcode the master     *)
(* stamped into an Open/CloseRegionRequest with the startcode of whichever *)
(* incarnation holds the port when the request arrives.                    *)
(*                                                                         *)
(* Property: TargetSafe == ~targetFired (adhoc-coordination Shared Rule 1). *)
(*                                                                         *)
(* Scenario-driven extensions (modeling-brief.md section 2/4):             *)
(*   S1 stale dispatcher retry chain   : calls, buf, rrp, RS phases        *)
(*   S2 lower-startcode successor      : RsConstructClockBack, RecordNewM  *)
(*   S3 failover: predecessor online and dead : mPhase, MasterStartup     *)
(*   S4 hostname spelling              : ServerName.sp, FindSameAddrM      *)
(*                                                                         *)
(* Source abbreviations (all under the pinned tree):                       *)
(*  RSR  hbase-server/.../regionserver/RSRpcServices.java                  *)
(*  HRS  hbase-server/.../regionserver/HRegionServer.java                  *)
(*  HSB  hbase-server/.../HBaseServerBase.java                             *)
(*  CR   hbase-server/.../ipc/CallRunner.java                              *)
(*  NRS  hbase-server/.../ipc/NettyRpcServer.java                          *)
(*  ARH  hbase-server/.../regionserver/handler/AssignRegionHandler.java    *)
(*  URH  hbase-server/.../regionserver/handler/UnassignRegionHandler.java  *)
(*  CRH  hbase-server/.../regionserver/handler/CloseRegionHandler.java     *)
(*  RSPD hbase-server/.../master/procedure/RSProcedureDispatcher.java      *)
(*  RPD  hbase-procedure/.../procedure2/RemoteProcedureDispatcher.java     *)
(*  RRPB hbase-server/.../master/assignment/RegionRemoteProcedureBase.java *)
(*  ORP  .../master/assignment/OpenRegionProcedure.java                    *)
(*  CRP  .../master/assignment/CloseRegionProcedure.java                   *)
(*  TRSP .../master/assignment/TransitRegionStateProcedure.java            *)
(*  AM   .../master/assignment/AssignmentManager.java                      *)
(*  SCP  .../master/procedure/ServerCrashProcedure.java                    *)
(*  SM   hbase-server/.../master/ServerManager.java                        *)
(*  MRS  hbase-server/.../master/MasterRpcServices.java                    *)
(*  RST  hbase-server/.../master/RegionServerTracker.java                  *)
(*  DS   hbase-server/.../master/DeadServer.java                           *)
(*  HM   hbase-server/.../master/HMaster.java                              *)
(*  BLB  hbase-balancer/.../master/balancer/BaseLoadBalancer.java          *)
(*  SN   hbase-common/.../ServerName.java                                  *)
(*  ADR  hbase-common/.../net/Address.java                                 *)
(*  ARC  hbase-client/.../ipc/AbstractRpcClient.java                       *)
(*  FS   hbase-client/.../ipc/FailedServers.java                           *)
(*  NRC  hbase-client/.../ipc/NettyRpcConnection.java                      *)
(***************************************************************************)
EXTENDS Naturals, Integers, FiniteSets, Sequences, TLC

CONSTANTS
    NAddr,          \* number of RS host:port addresses (initial incarnation k binds address k)
    MaxInc,         \* number of RS incarnation ids (NAddr initial + restarts)
    Region,         \* user regions (hbase:meta is not modeled, brief 3.2)
    HostOf(_),      \* host of an address; BLB groups servers by lower-cased host (BLB:313-317)
    MixedCaseHost,  \* S4: the master-observed hostname has upper-case letters (SM:269-272)
    ForceRetain,    \* hbase.master.scp.force.region.retainment (workload: TRUE, Test:234)
    ScpRetain,      \* hbase.master.scp.retain.assignment (workload: TRUE, Test:307)
    FailFastLimit   \* hbase.master.rs.remote.proc.fail.fast.limit (RSPD:259-268; default 10)

ASSUME NAddr \in Nat /\ NAddr >= 1
ASSUME MaxInc \in Nat /\ MaxInc >= NAddr
ASSUME FailFastLimit \in Nat /\ FailFastLimit >= 1
ASSUME MixedCaseHost \in BOOLEAN /\ ForceRetain \in BOOLEAN /\ ScpRetain \in BOOLEAN

Addr    == 1..NAddr
Inc     == 1..MaxInc
InitInc == 1..NAddr

-----------------------------------------------------------------------------
(* ServerNames.                                                            *)
(* A ServerName is (hostname, port, startcode) (SN:86, 102-111). The model  *)
(* names it by incarnation i (address incAddr[i], startcode sc[i]) plus the *)
(* hostname spelling sp. ServerName.equals/compareTo/hashCode ignore host   *)
(* case (SN:249-291), so Java equality is "same .i". isSameAddress uses     *)
(* Address.equals, which is case-sensitive (SN:299-301; ADR:119-128), so it *)
(* is "same address and same .sp".                                         *)
(*   - ZooKeeper-derived names are lower case (SN:239-241 toString; RST:209)*)
(*   - RPC-derived names keep the master-observed spelling (SM:269-272) and *)
(*     the RS renames itself to it (HRS:1424-1427).                         *)
Lower    == "lower"
Mixed    == "Mixed"
NoSp     == "none"
Spell    == {Lower, Mixed}
DeploySp == IF MixedCaseHost THEN Mixed ELSE Lower
ZkSp     == Lower

SN(i, s) == [i |-> i, sp |-> s]
NoSN     == SN(0, NoSp)
SNs      == {SN(i, s) : i \in Inc, s \in Spell}

RsPhases    == {"none", "bound", "started", "registered", "online", "stopping", "exited"}
BoundPhases == {"bound", "started", "registered", "online", "stopping"}
MPhases     == {"down", "upgraded", "serviceStarted", "initialized", "ready"}
RStates     == {"OPEN", "OPENING", "CLOSING", "CLOSED", "ABNORMALLY_CLOSED"}
TrspStates  == {"GET_ASSIGN_CANDIDATE", "WAIT_RETAIN", "WAIT_PLAN", "OPEN",
                "CONFIRM_OPENED", "CLOSE", "CONFIRM_CLOSED"}
RrpStates   == {"DISPATCH", "REPORT_SUCCEED", "DISPATCH_FAIL", "SERVER_CRASH"}
ScpStates   == {"none", "START", "GET_REGIONS", "SPLIT_LOGS", "ASSIGN", "FINISH", "done"}
CallModes   == {"dead", "run", "sent", "resp"}
Outcomes    == {"none", "ok", "conn", "snrye", "rsse", "io", "dnr"}

NoTRSP == [type |-> "none", st |-> "none", cand |-> NoSN, fnp |-> FALSE,
           child |-> 0, parent |-> 0]
NewTrsp(ty, st, cand, fnp, parent) ==
    [type |-> ty, st |-> st, cand |-> cand, fnp |-> fnp, child |-> 0, parent |-> parent]

-----------------------------------------------------------------------------
VARIABLES
    \* ---- RegionServer incarnations (one JVM process each) ----
    incAddr,     \* incAddr[i]: address bound by incarnation i (0 = not constructed)
    sc,          \* sc[i]: startcode = wall clock at construction (HSB:124, 268)
    rsPhase,     \* rsPhase[i] \in RsPhases (brief 3.1 phase table; analysis section 5)
    holder,      \* holder[a]: incarnation bound to host:port a, 0 if none (port exclusivity)
    znode,       \* znode[i]: ephemeral RS znode exists (created HRS:1467, deleted HRS:1034-1040 or session expiry)
    rsRegions,   \* rsRegions[i]: user regions online on incarnation i (HRS onlineRegions)
    rsTasks,     \* rsTasks[i]: accepted open/close region procedures not yet executed (RSR:3939-3993)
    \* ---- HMaster volatile state ----
    mPhase,      \* master initialization phase (HM:1044-1358); "ready" = initialized and dead servers cleared
    online,      \* online[i]: spelling of i's key in SM.onlineServers, NoSp if absent
    reported,    \* reported[i]: onlineServers value has lastReportTimestamp > 0 (SM:1050-1056)
    dead,        \* dead[i]: spelling of i's DeadServer entry, NoSp if absent (DS)
    srvNode,     \* srvNode[i]: AM ServerStateNode state ("none" = absent) (AM:1995-2047)
    dNode,       \* dNode[i]: spelling of the RSPD BufferNode key for i, NoSp if absent (RPD:74-75, 154-157)
    buf,         \* buf[i]: remote procedures queued on i's BufferNode (RPD:384, 396-408)
    calls,       \* ExecuteProceduresRemoteCall / DeadRSRemoteCall instances (RSPD:224-515)
    rstView,     \* RST.regionServers: last seen znode children (RST:68, 214)
    failedSrv,   \* addresses in the master RPC client's unexpired failed-servers list (ARC:132, FS:34)
    \* ---- HMaster durable state (procedure store, hbase:meta, RS list storage) ----
    rsList,      \* MasterRegionServerList: started (SM:282) / expired (SM:710)
    scp,         \* scp[i]: ServerCrashProcedure state for incarnation i (SCP:155-297)
    scpRegs,     \* scpRegs[i]: regionsOnCrashedServer (SCP:205)
    trsp,        \* trsp[r]: the TransitRegionStateProcedure attached to region r (at most one, TRSP:110-113)
    rrp,         \* rrp[p]: Open/CloseRegionProcedure p (RRPB); a function on 1..nextPid-1
    nextPid,     \* next procedure id for a remote region procedure
    rstate,      \* rstate[r]: RegionStateNode state (AM:2165-2184)
    loc,         \* loc[r]: RegionStateNode.regionLocation (TRSP:295, 384)
    lastHost,    \* lastHost[r]: RegionStateNode.lastHost (AM:2299, 2330)
    \* ---- target ----
    targetFired  \* the failing branch of RSR:1877 executed (RSR:1878)

rsVars     == <<incAddr, sc, rsPhase, holder, znode, rsRegions, rsTasks>>
msVars     == <<online, reported, dead, srvNode, rsList, dNode, buf, scp>>
mVars      == <<mPhase, rstView, failedSrv>>
procVars   == <<trsp, rrp, nextPid, scpRegs>>
regionVars == <<rstate, loc, lastHost>>
vars == <<rsVars, msVars, mVars, calls, procVars, regionVars, targetFired>>

-----------------------------------------------------------------------------
(* Helpers                                                                 *)

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y

Constructed == {i \in Inc : rsPhase[i] # "none"}
MaxSc == Max({sc[j] : j \in Constructed})
MinSc == Min({sc[j] : j \in Constructed})

\* Master serves RS RPCs and runs procedure workers after startServiceThreads
\* (HM:1148 -> 1732 startProcedureExecutor, 1817 serviceStarted; MRS:638, 674, 1886 checkServiceStarted)
Serving  == mPhase \in {"serviceStarted", "initialized", "ready"}
\* HMaster.isInitialized (HM:1300)
Inited   == mPhase \in {"initialized", "ready"}
\* RegionServerTracker.active (RST:158, 211)
Tracking == mPhase \in {"upgraded", "serviceStarted", "initialized", "ready"}

\* SM.isServerOnline (SM:954-956): onlineServers.containsKey, equals ignores host case
IsOnline(i) == online[i] # NoSp
\* SM.createDestinationServersList (SM:1048-1068): online and reported at least once
Dest == {i \in Inc : online[i] # NoSp /\ reported[i]}

-----------------------------------------------------------------------------
(* ServerManager membership as pure functions over a record, so that       *)
(* registration, report, tracker expiry, dispatcher fail-fast and failover *)
(* upgrade share one literal implementation of SM:401-428 and SM:662-743.  *)

MS == [on |-> online, rep |-> reported, dd |-> dead, sn |-> srvNode,
       rl |-> rsList, dn |-> dNode, bf |-> buf, scp |-> scp]

SetMS(m) ==
    /\ online' = m.on   /\ reported' = m.rep /\ dead' = m.dd /\ srvNode' = m.sn
    /\ rsList' = m.rl   /\ dNode' = m.dn     /\ buf' = m.bf  /\ scp' = m.scp

\* SM.findServerWithSameHostnamePortWithLock (SM:508-519): lowerKey((host,port,MAX)) is the
\* highest-startcode key at that host:port (compareTo ignores case, SN:249-272); it is returned
\* only if ServerName.isSameAddress(r, sn) (case-sensitive, SN:299-301). 0 = null.
FindSameAddrM(m, n) ==
    LET cands == {j \in Inc : m.on[j] # NoSp /\ incAddr[j] = incAddr[n.i]}
    IN IF cands = {} THEN 0
       ELSE LET top == CHOOSE j \in cands : \A k \in cands : sc[k] <= sc[j]
            IN IF m.on[top] = n.sp THEN top ELSE 0

\* SM.expireServer(serverName) (SM:662-720)
ExpireM(m, n) ==
    LET i == n.i IN
    IF m.dd[i] # NoSp THEN m                                   \* SM:675-678 already in DeadServer
    ELSE
      LET m1 == IF m.on[i] # NoSp                              \* SM:679 -> moveFromOnlineToDeadServers SM:726-743
                THEN [m EXCEPT !.dd[i] = n.sp,                 \*   SM:733 deadservers.putIfAbsent(sn)
                               !.on[i] = NoSp,                 \*   SM:734 onlineServers.remove(sn)
                               !.rep[i] = FALSE]
                ELSE m                                         \*   SM:736-741 not online: nothing
      IN IF m1.sn[i] # "ONLINE"                                \* SM:705 -> AM:2000-2008, 2021-2029: NO_PROC_ID
         THEN m1                                               \* SM:706-709 skip listeners
         ELSE [m1 EXCEPT !.sn[i] = "CRASHED",                  \* AM:2039
                         !.scp[i] = IF @ \in {"none", "done"}  \* AM:2041-2044 submit SCP
                                    THEN "START" ELSE @,       \*   (a second SCP for i is merged into the pending one)
                         !.rl = @ \ {i},                       \* SM:710 storage.expired
                         !.dn[i] = NoSp,                       \* SM:711-714 serverRemoved -> RSPD:177-179 -> RPD:195-203
                         !.bf[i] = {}]                         \* RPD:420-427 abortOperationsInQueue; RRPB:126-131 is a
                                                               \*   no-op since i is no longer online (procs stay DISPATCH)

RECURSIVE ExpireAllM(_, _)
ExpireAllM(m, S) ==
    IF S = {} THEN m
    ELSE LET x == CHOOSE y \in S : TRUE
         IN ExpireAllM(ExpireM(m, SN(x, ZkSp)), S \ {x})

\* SM.checkAndRecordNewServer(serverName, sl) (SM:401-428); rep = sl has lastReportTimestamp > 0
RecordNewM(m, n, rep) ==
    LET i  == n.i
        ex == FindSameAddrM(m, n)                              \* SM:404
    IN
    IF ex # 0 /\ sc[ex] > sc[i]                                \* SM:405-409 rejected, return false
    THEN [m |-> m, ok |-> FALSE]
    ELSE
      LET m1 == [m EXCEPT !.on[i]  = IF @ = NoSp THEN n.sp ELSE @,     \* SM:410 -> 527 put (an existing key keeps its spelling)
                          !.rep[i] = rep,                              \* SM:527 new ServerMetrics value
                          !.sn[i]  = IF @ = "none" THEN "ONLINE" ELSE @, \* SM:528 -> RegionStates.createServer computeIfAbsent
                          !.dn[i]  = IF @ = NoSp THEN n.sp ELSE @]     \* SM:414-418 serverAdded -> RSPD:172-174 -> RPD:154-157
          m2 == IF ex # 0 /\ sc[ex] < sc[i]                    \* SM:420-426 expire the stale same-address server
                THEN ExpireM(m1, SN(ex, m.on[ex]))
                ELSE m1
      IN [m |-> m2, ok |-> TRUE]

RECURSIVE FoldRecord(_, _)
FoldRecord(m, s) ==
    IF s = <<>> THEN m
    ELSE FoldRecord(RecordNewM(m, SN(Head(s), ZkSp), FALSE).m, Tail(s))

\* DeadServer.cleanPreviousInstance (DS:98-106): remove the first dead entry with the same address
CleanPrevM(m, n) ==
    LET same == {d \in Inc : m.dd[d] # NoSp /\ incAddr[d] = incAddr[n.i] /\ m.dd[d] = n.sp}  \* DS:124 isSameAddress
    IN IF same = {} THEN m
       ELSE [m EXCEPT !.dd[CHOOSE d \in same : TRUE] = NoSp]   \* DS:127 (HashMap iteration order: one arbitrary entry)

Perms(S) == {f \in [1..Cardinality(S) -> S] :
               \A x, y \in 1..Cardinality(S) : x # y => f[x] # f[y]}

-----------------------------------------------------------------------------
(* Master-side handling of an RS region-state report, shared by the RS     *)
(* handlers below. AM.reportRegionStateTransition (AM:1260-1303) ->         *)
(* updateRegionTransition (AM:1305-1342) -> reportTransition (AM:1344-1354) *)
(* -> TRSP.reportTransition (TRSP:544-563) -> RRPB.reportTransition         *)
(* (RRPB:209-245) -> ORP/CRP checkTransition and update. The RS waits for   *)
(* the reply, so the report is one atomic step with the RS handler.         *)
(* p = -1 for CloseRegionHandler reports (CRH:113-114 NO_PROC_ID).          *)
ReportTransition(i, r, code, p) ==
    LET t == trsp[r]
        c == t.child
    IN
    IF /\ srvNode[i] = "ONLINE"                       \* AM:1265-1270 server node exists; AM:1281 ONLINE
       /\ t # NoTRSP                                  \* AM:1347-1350 regionNode.getProcedure() != null
       /\ c # 0                                       \* TRSP:546-552 remoteProc != null
       /\ (p < 0 \/ c = p)                            \* TRSP:555-561 pid match (or -1)
       /\ rrp[c].st = "DISPATCH"                      \* RRPB:211-214 otherwise a retry, ignore
       /\ rrp[c].tgt.i = i                            \* RRPB:215-218 targetServer.equals(serverName)
       /\ (IF rrp[c].k = "open" THEN code = "OPENED" ELSE code = "CLOSED")  \* ORP:97-113, CRP:100-106
    THEN
       /\ rrp' = [rrp EXCEPT ![c].st = "REPORT_SUCCEED"]          \* RRPB:222, persistAndWake RRPB:231
       /\ IF code = "OPENED"
          THEN /\ rstate' = [rstate EXCEPT ![r] = "OPEN"]          \* ORP:116-120 -> AM:2284-2290
               /\ UNCHANGED <<loc, lastHost>>
          ELSE /\ rstate' = [rstate EXCEPT ![r] = "CLOSED"]        \* CRP:108-113 -> AM:2293-2302
               /\ loc' = [loc EXCEPT ![r] = NoSN]                  \* AM:2297
               /\ lastHost' = [lastHost EXCEPT ![r] =              \* AM:2298-2299
                                 IF loc[r] # NoSN THEN loc[r] ELSE @]
    ELSE UNCHANGED <<rrp, rstate, loc, lastHost>>                 \* ignored, or an error reply the RS logs

-----------------------------------------------------------------------------
(* RegionServer lifecycle                                                   *)

\* HBaseServerBase constructor (HSB:259-286): startcode = currentTime() (HSB:268); the RPC listener is
\* bound inside the RpcServer constructor (HSB:284 -> NRS:190); serverName (HSB:286).
\* A new incarnation's wall clock is ahead of every earlier startcode (no clock step back).
RsConstruct(a, s) ==
    /\ holder[a] = 0                                       \* NRS:190 bind succeeds only on a free port
    /\ s > MaxSc
    /\ \E i \in Inc :
         /\ rsPhase[i] = "none"
         /\ \A j \in Inc : j < i => rsPhase[j] # "none"     \* incarnation ids allocated in order
         /\ incAddr' = [incAddr EXCEPT ![i] = a]
         /\ sc'      = [sc EXCEPT ![i] = s]
         /\ rsPhase' = [rsPhase EXCEPT ![i] = "bound"]
         /\ holder'  = [holder EXCEPT ![a] = i]
    /\ UNCHANGED <<znode, rsRegions, rsTasks, msVars, mVars, calls, procVars, regionVars, targetFired>>

\* S2: same constructor, but the host clock stepped back across the restart, so the new startcode is
\* below the predecessor's at this address (HSB:268; the skew check SM:458-473 bounds the reported
\* current time only, not the startcode; hazard acknowledged at SM:420-421 and DS:91-93).
RsConstructClockBack(a, s) ==
    /\ holder[a] = 0
    /\ \E j \in Constructed : incAddr[j] = a /\ sc[j] > s   \* lower than a predecessor at this address
    /\ \A j \in Constructed : sc[j] # s                     \* equal startcodes are excluded (brief 3.2, X5)
    /\ \E i \in Inc :
         /\ rsPhase[i] = "none"
         /\ \A j \in Inc : j < i => rsPhase[j] # "none"
         /\ incAddr' = [incAddr EXCEPT ![i] = a]
         /\ sc'      = [sc EXCEPT ![i] = s]
         /\ rsPhase' = [rsPhase EXCEPT ![i] = "bound"]
         /\ holder'  = [holder EXCEPT ![a] = i]
    /\ UNCHANGED <<znode, rsRegions, rsTasks, msVars, mVars, calls, procVars, regionVars, targetFired>>

\* HRS:558 rpcServices.start -> NRS:336-337 scheduler.start(); started = true
RsStartRpc(i) ==
    /\ rsPhase[i] = "bound"
    /\ rsPhase' = [rsPhase EXCEPT ![i] = "started"]
    /\ UNCHANGED <<incAddr, sc, holder, znode, rsRegions, rsTasks, msVars, mVars, calls,
                   procVars, regionVars, targetFired>>

\* HRS.run reportForDuty loop (HRS:853-863, 2683-2731), served by MRS.regionServerStartup (MRS:670-698)
\* -> SM.regionServerStartup (SM:255-284). Atomic: one master RPC handler.
RsReportForDuty(i) ==
    /\ rsPhase[i] = "started"
    /\ Serving                                             \* MRS:674 checkServiceStarted (HM:3418-3422)
    /\ dead[i] = NoSp                                      \* SM:278 -> 484-491 exact match (never for a fresh startcode)
    /\ LET n   == SN(i, DeploySp)                          \* SM:269-272 hostname the master sees
           m1  == IF Inited THEN CleanPrevM(MS, n) ELSE MS \* SM:494-501 clean previous instance only once initialized
           res == RecordNewM(m1, n, FALSE)                 \* SM:279 (ServerMetricsBuilder.of: lastReportTimestamp = 0)
       IN SetMS([res.m EXCEPT !.rl = @ \cup {i}])          \* SM:279-283 a rejection is only logged; SM:282 storage.started
    /\ rsPhase' = [rsPhase EXCEPT ![i] = "registered"]     \* SM:283 returns success either way
    /\ UNCHANGED <<incAddr, sc, holder, znode, rsRegions, rsTasks, mVars, calls, procVars,
                   regionVars, targetFired>>

\* HRS.handleReportForDutyResponse (HRS:1417-1512): createMyEphemeralNode (HRS:1467). The master's tracker
\* and a failover upgrade can see the child from here on, while checkOpen still answers SNRYE (RSR:1487-1489).
RsCreateEphemeralNode(i) ==
    /\ rsPhase[i] = "registered"
    /\ ~znode[i]
    /\ znode' = [znode EXCEPT ![i] = TRUE]
    /\ UNCHANGED <<incAddr, sc, rsPhase, holder, rsRegions, rsTasks, msVars, mVars, calls, procVars,
                   regionVars, targetFired>>

\* HRS.handleReportForDutyResponse tail: online.set(true) (HRS:1509-1512)
RsOnline(i) ==
    /\ rsPhase[i] = "registered"
    /\ znode[i]
    /\ rsPhase' = [rsPhase EXCEPT ![i] = "online"]
    /\ UNCHANGED <<incAddr, sc, holder, znode, rsRegions, rsTasks, msVars, mVars, calls, procVars,
                   regionVars, targetFired>>

\* Periodic report (HRS:916-920 -> tryRegionServerReport HRS:1082-1110) served by MRS.regionServerReport
\* (MRS:635-667) -> SM.regionServerReport (SM:325-356). YouAreDeadException aborts the RS
\* (HRS:1099-1102 -> 925-929 abort -> stop, so checkOpen answers RegionServerAbortedException).
RsReport(i) ==
    /\ rsPhase[i] = "online"                               \* HRS:888 main loop
    /\ Serving                                             \* MRS:638
    /\ LET n == SN(i, DeploySp) IN                         \* HRS:1093 own serverName (renamed HRS:1426)
       IF dead[i] # NoSp                                   \* SM:326 -> 484-491
       THEN /\ rsPhase' = [rsPhase EXCEPT ![i] = "stopping"]
            /\ UNCHANGED msVars
       ELSE LET m1 == IF Inited THEN CleanPrevM(MS, n) ELSE MS   \* SM:494-501
            IN IF m1.on[i] # NoSp                                 \* SM:327 replace(sn, sl) succeeded
               THEN /\ SetMS([m1 EXCEPT !.rep[i] = TRUE])
                    /\ UNCHANGED rsPhase
               ELSE LET res == RecordNewM(m1, n, TRUE) IN        \* SM:334
                    IF res.ok
                    THEN /\ SetMS(res.m)
                         /\ UNCHANGED rsPhase
                    ELSE /\ SetMS(m1)                            \* SM:335-352 YouAreDeadException
                         /\ rsPhase' = [rsPhase EXCEPT ![i] = "stopping"]
    /\ UNCHANGED <<incAddr, sc, holder, znode, rsRegions, rsTasks, mVars, calls, procVars,
                   regionVars, targetFired>>

\* Graceful stop: HRegionServer.stop -> stopped = true (HRS:2250). checkOpen now throws
\* RegionServerStoppedException (RSR:1481-1482); the port and the znode are kept (HRS:966-1007).
RsStop(i) ==
    /\ rsPhase[i] = "online"
    /\ rsPhase' = [rsPhase EXCEPT ![i] = "stopping"]
    /\ UNCHANGED <<incAddr, sc, holder, znode, rsRegions, rsTasks, msVars, mVars, calls, procVars,
                   regionVars, targetFired>>

\* Abrupt process death (kill -9 / OOM kill / power loss): the OS releases the port at once; no region
\* close, no report, and the znode lives until the ZK session expires (analysis section 5; HRS:1034-1045
\* is skipped).
RsCrash(i) ==
    /\ rsPhase[i] \in BoundPhases
    /\ rsPhase'   = [rsPhase EXCEPT ![i] = "exited"]
    /\ holder'    = [holder EXCEPT ![incAddr[i]] = 0]
    /\ rsRegions' = [rsRegions EXCEPT ![i] = {}]
    /\ rsTasks'   = [rsTasks EXCEPT ![i] = {}]
    /\ UNCHANGED <<incAddr, sc, znode, msVars, mVars, calls, procVars, regionVars, targetFired>>

\* Shutdown closes user regions (HRS:966-976 -> closeUserRegions HRS:2790-2802 -> closeRegion
\* HRS:3095-3155 -> CloseRegionHandler), each reporting CLOSED with NO_PROC_ID (CRH:112-114).
\* The report loop retries until the master answers (HRS:2366-2423).
RsCloseRegionOnStop(i, r) ==
    /\ rsPhase[i] = "stopping"
    /\ r \in rsRegions[i]
    /\ Serving
    /\ rsRegions' = [rsRegions EXCEPT ![i] = @ \ {r}]
    /\ ReportTransition(i, r, "CLOSED", -1)
    /\ UNCHANGED <<incAddr, sc, rsPhase, holder, znode, rsTasks, msVars, mVars, calls, trsp,
                   nextPid, scpRegs, targetFired>>

\* Shutdown tail: waitOnAllRegionsToClose (HRS:990-993), then rpcServices.stop() releases the port
\* (HRS:1030-1032 -> NRS:358-359). The znode is deleted only afterwards (ZnodeDelete).
RsExit(i) ==
    /\ rsPhase[i] = "stopping"
    /\ rsRegions[i] = {}
    /\ rsPhase' = [rsPhase EXCEPT ![i] = "exited"]
    /\ holder'  = [holder EXCEPT ![incAddr[i]] = 0]
    /\ rsTasks' = [rsTasks EXCEPT ![i] = {}]
    /\ UNCHANGED <<incAddr, sc, znode, rsRegions, msVars, mVars, calls, procVars, regionVars, targetFired>>

\* deleteMyEphemeralNode (HRS:1034-1040) after a stop, or ZK session expiry after a crash
\* (HConstants:285 default 90 s).
ZnodeDelete(i) ==
    /\ rsPhase[i] = "exited"
    /\ znode[i]
    /\ znode' = [znode EXCEPT ![i] = FALSE]
    /\ UNCHANGED <<incAddr, sc, rsPhase, holder, rsRegions, rsTasks, msVars, mVars, calls, procVars,
                   regionVars, targetFired>>

\* AssignRegionHandler.process (ARH:98-163): already online -> return without a report (ARH:104-113);
\* else open and report OPENED (ARH:143-155 -> HRS:2271-2302 postOpenDeployTasks).
RsOpenRegion(i, t) ==
    /\ t \in rsTasks[i] /\ t.k = "open"
    /\ rsPhase[i] \in {"online", "stopping"}
    /\ Serving
    /\ rsTasks' = [rsTasks EXCEPT ![i] = @ \ {t}]
    /\ IF t.r \in rsRegions[i]
       THEN /\ UNCHANGED <<rsRegions, rrp, rstate, loc, lastHost>>
       ELSE /\ rsRegions' = [rsRegions EXCEPT ![i] = @ \cup {t.r}]
            /\ ReportTransition(i, t.r, "OPENED", t.p)
    /\ UNCHANGED <<incAddr, sc, rsPhase, holder, znode, msVars, mVars, calls, trsp, nextPid,
                   scpRegs, targetFired>>

\* UnassignRegionHandler.process (URH:92-150): region not online -> return (URH:114-120);
\* else close and report CLOSED with its closeProcId (URH:147-150).
RsCloseRegion(i, t) ==
    /\ t \in rsTasks[i] /\ t.k = "close"
    /\ rsPhase[i] \in {"online", "stopping"}
    /\ Serving
    /\ rsTasks' = [rsTasks EXCEPT ![i] = @ \ {t}]
    /\ IF t.r \notin rsRegions[i]
       THEN /\ UNCHANGED <<rsRegions, rrp, rstate, loc, lastHost>>
       ELSE /\ rsRegions' = [rsRegions EXCEPT ![i] = @ \ {t.r}]
            /\ ReportTransition(i, t.r, "CLOSED", t.p)
    /\ UNCHANGED <<incAddr, sc, rsPhase, holder, znode, msVars, mVars, calls, trsp, nextPid,
                   scpRegs, targetFired>>

-----------------------------------------------------------------------------
(* Master: ZooKeeper-driven expiry                                         *)

\* RST.nodeChildrenChanged (RST:221-228) runs refresh() on a single-thread executor (RST:73-79):
\* list children (RST:200, 207-210, names parsed lower-case), and as active master expire every
\* server whose znode disappeared (processAsActiveMaster RST:172-179). Asynchronous and may lag.
TrackerRefresh ==
    /\ Tracking
    /\ LET kids == {i \in Inc : znode[i]}
       IN /\ kids # rstView
          /\ SetMS(ExpireAllM(MS, rstView \ kids))            \* RST:176-179
          /\ rstView' = kids                                    \* RST:214
    /\ UNCHANGED <<rsVars, mPhase, failedSrv, calls, procVars, regionVars, targetFired>>

-----------------------------------------------------------------------------
(* Master: RSProcedureDispatcher                                           *)

CallAddr(c) == incAddr[c.sn.i]               \* ARC:463-464 createAddr(sn) = (hostname, port)
Recv(c)     == holder[CallAddr(c)]           \* delivery by address only (ConnectionId:26-27)

UpdCall(c, c2) == calls' = (calls \ {c}) \cup {c2}

\* RRPB.remoteCallFailed (RRPB:121-149) for every proc of a call (RSPD:510-514), given the
\* onlineServers map `on` at that moment.
RrpCallFailed(f, ps, n, on) ==
    [p \in DOMAIN f |->
       IF /\ p \in ps
          /\ on[n.i] # NoSp                                    \* RRPB:126-131 target not online: SCP will interrupt
          /\ f[p].st = "DISPATCH"                              \* RRPB:132-138 already woken: ignore
       THEN [f[p] EXCEPT !.st = "DISPATCH_FAIL"]               \* RRPB:144-145 (not persisted, RRPB:141-143)
       ELSE f[p]]

\* BufferNode.dispatch (RPD:410-418) fired by the timeout thread (RPD:338-342) after the batching delay
\* (RPD:396-402) -> RSPD.remoteDispatch (RSPD:151-159): the ONLY liveness check before the first send.
BufferFlush(i) ==
    /\ Serving
    /\ buf[i] # {}
    /\ calls' = calls \cup
         {[sn |-> SN(i, dNode[i]), procs |-> buf[i],
           mode |-> IF IsOnline(i) THEN "run" ELSE "dead",      \* RSPD:153-158
           att |-> 0, snr |-> FALSE, ops |-> {}, out |-> "none"]}
    /\ buf' = [buf EXCEPT ![i] = {}]                            \* RPD:416 operations = null (ORP/CRP are not
                                                                \*   kept in dispatchedOperations, RRPB:397-400)
    /\ UNCHANGED <<rsVars, online, reported, dead, srvNode, rsList, dNode, scp, mVars, procVars,
                   regionVars, targetFired>>

\* DeadRSRemoteCall.run (RSPD:224-235): remoteCallFailed without any RPC
DeadCallRun(c) ==
    /\ Serving
    /\ c \in calls /\ c.mode = "dead"
    /\ rrp' = RrpCallFailed(rrp, c.procs, c.sn, online)
    /\ calls' = calls \ {c}
    /\ UNCHANGED <<rsVars, msVars, mVars, trsp, nextPid, scpRegs, regionVars, targetFired>>

\* ExecuteProceduresRemoteCall.run (RSPD:466-474), on first submission or when the DelayQueue
\* re-submits it (RPD:212-214, 338-339). The request is rebuilt on every attempt: remoteCallBuild returns
\* an operation unless the proc is REPORT_SUCCEED (RRPB:92-100) - also when SERVER_CRASH, DISPATCH_FAIL
\* or already finished. Each open/close request is stamped with getServerName()'s startcode
\* (RSPD:486-497, 517-520, 600-603; ProtobufUtil:3191-3192). No liveness check here (RSPD:477-478).
CallSend(c) ==
    /\ Serving
    /\ c \in calls /\ c.mode = "run"
    /\ UpdCall(c, [c EXCEPT !.mode = "sent",
                            !.ops = {p \in c.procs : rrp[p].st # "REPORT_SUCCEED"}])
    /\ UNCHANGED <<rsVars, msVars, mVars, procVars, regionVars, targetFired>>

\* Nothing bound to host:port: connection refused, a network error (RSPD:415-421). The failed connect
\* puts the address on the client's failed-servers list (NRC:208-213 -> FS:47-53).
CallDeliverNoServer(c) ==
    /\ c \in calls /\ c.mode = "sent"
    /\ CallAddr(c) \notin failedSrv
    /\ Recv(c) = 0
    /\ UpdCall(c, [c EXCEPT !.mode = "resp", !.out = "conn"])
    /\ failedSrv' = failedSrv \cup {CallAddr(c)}
    /\ UNCHANGED <<rsVars, msVars, mPhase, rstView, procVars, regionVars, targetFired>>

\* The address is on the list: ARC:360-366 throws FailedServerException before any connection is used, whoever
\* holds the port. It is not a network error (RSPD:415-439), so it takes the plain retry path of CallFailed.
CallDeliverFailedServer(c) ==
    /\ c \in calls /\ c.mode = "sent"
    /\ CallAddr(c) \in failedSrv
    /\ UpdCall(c, [c EXCEPT !.mode = "resp", !.out = "io"])
    /\ UNCHANGED <<rsVars, msVars, mVars, procVars, regionVars, targetFired>>

\* The entry's 2 s ran out (RpcClient:34; FS:61-79). Time passing is the trigger.
FailedServerExpire(a) ==
    /\ a \in failedSrv
    /\ failedSrv' = failedSrv \ {a}
    /\ UNCHANGED <<rsVars, msVars, mPhase, rstView, calls, procVars, regionVars, targetFired>>

\* RpcServer bound but not started: CR:118-121 ServerNotRunningYetException
CallDeliverNotStarted(c) ==
    /\ c \in calls /\ c.mode = "sent"
    /\ CallAddr(c) \notin failedSrv
    /\ Recv(c) # 0 /\ rsPhase[Recv(c)] = "bound"
    /\ UpdCall(c, [c EXCEPT !.mode = "resp", !.out = "snrye"])
    /\ UNCHANGED <<rsVars, msVars, mVars, procVars, regionVars, targetFired>>

\* RSR.executeProcedures checkOpen (RSR:4017 -> 1477-1491) throws before the guard:
\* aborted/stopped -> RegionServerAborted/StoppedException (RSR:1478-1482), not online -> SNRYE (RSR:1487-1489)
CallDeliverCheckOpenFail(c) ==
    /\ c \in calls /\ c.mode = "sent"
    /\ CallAddr(c) \notin failedSrv
    /\ Recv(c) # 0 /\ rsPhase[Recv(c)] \in {"started", "registered", "stopping"}
    /\ UpdCall(c, [c EXCEPT !.mode = "resp",
                            !.out = IF rsPhase[Recv(c)] = "stopping" THEN "rsse" ELSE "snrye"])
    /\ UNCHANGED <<rsVars, msVars, mVars, procVars, regionVars, targetFired>>

\* The target. RSR.executeProcedures (RSR:4014-4037) on the incarnation holding the port: checkOpen passed
\* (RSR:4017), then throwOnWrongStartCode(request) (RSR:4018 -> 1884-1895 -> 1859-1873 -> 1875-1882).
\* The guard is evaluated for every open and close request; all carry the call's stamped startcode.
TargetCheck(c) ==
    /\ c \in calls /\ c.mode = "sent"
    /\ CallAddr(c) \notin failedSrv
    /\ Recv(c) # 0 /\ rsPhase[Recv(c)] = "online"              \* RSR:4017 checkOpen passes
    /\ LET j == Recv(c) IN
       IF c.ops # {} /\ sc[j] # sc[c.sn.i]                      \* RSR:1885-1893, RSR:1877
       THEN /\ targetFired' = TRUE                              \* RSR:1878 ServiceException(DoNotRetryIOException)
            /\ UpdCall(c, [c EXCEPT !.mode = "resp", !.out = "dnr"])
            /\ UNCHANGED rsTasks
       ELSE /\ targetFired' = targetFired
            /\ UpdCall(c, [c EXCEPT !.mode = "resp", !.out = "ok"])
            /\ rsTasks' = [rsTasks EXCEPT ![j] = @ \cup         \* RSR:4020-4028 -> 3939-3993 handlers
                             {[r |-> rrp[p].r, k |-> rrp[p].k, p |-> p] : p \in c.ops}]
    /\ UNCHANGED <<incAddr, sc, rsPhase, holder, znode, rsRegions, msVars, mVars, procVars,
                   regionVars>>

\* sendRequest returned normally (RSPD:474): the call ends
CallSucceeded(c) ==
    /\ Serving
    /\ c \in calls /\ c.mode = "resp" /\ c.out = "ok"
    /\ calls' = calls \ {c}
    /\ UNCHANGED <<rsVars, msVars, mVars, procVars, regionVars, targetFired>>

Retry(c, snr) ==                                                \* re-send later through the DelayQueue
    UpdCall(c, [c EXCEPT !.mode = "run",
                         !.att  = IF @ + 1 > FailFastLimit THEN FailFastLimit ELSE @ + 1,
                         !.snr  = snr, !.ops = {}, !.out = "none"])

\* RSPD:475-482 catch -> unwrap (RSPD:458-463) -> scheduleForRetry (RSPD:290-367); on false,
\* remoteCallFailed (RSPD:480). The decision is taken at failure time, reading online status then.
CallFailed(c) ==
    /\ Serving
    /\ c \in calls /\ c.mode = "resp" /\ c.out \notin {"none", "ok"}
    /\ IF c.out = "snrye"                                       \* RSPD:293-302: retry in 100 ms, NO online check
       THEN /\ Retry(c, TRUE)                                   \*   (remaining time > 0; see CallSnryeTimeout)
            /\ UNCHANGED <<msVars, rrp>>
       ELSE IF c.out = "dnr"                                    \* RSPD:307-311 DoNotRetryIOException: give up
       THEN /\ calls' = calls \ {c}
            /\ rrp' = RrpCallFailed(rrp, c.procs, c.sn, online)
            /\ UNCHANGED msVars
       ELSE IF c.att >= FailFastLimit - 1 /\ c.out = "conn"     \* RSPD:326-337 fail-fast: expireServer, give up
       THEN LET m == ExpireM(MS, c.sn) IN
            /\ SetMS(m)
            /\ calls' = calls \ {c}
            /\ rrp' = RrpCallFailed(rrp, c.procs, c.sn, m.on)
       ELSE IF ~IsOnline(c.sn.i)                                \* RSPD:339-343 not online: give up
       THEN /\ calls' = calls \ {c}
            /\ rrp' = RrpCallFailed(rrp, c.procs, c.sn, online)
            /\ UNCHANGED msVars
       ELSE /\ Retry(c, c.snr)                                  \* RSPD:344-366 backoff min(100*n^2, 10 s)
            /\ UNCHANGED <<msVars, rrp>>
    /\ UNCHANGED <<rsVars, mVars, trsp, nextPid, scpRegs, regionVars, targetFired>>

\* RSPD:303-305: SNRYE for longer than rsStartupWaitTime (60 s, RSPD:68-81, 450-456) since the first
\* SNRYE: give up. Time passing is the trigger (bounded in MC).
CallSnryeTimeout(c) ==
    /\ Serving
    /\ c \in calls /\ c.mode = "resp" /\ c.out = "snrye" /\ c.snr
    /\ calls' = calls \ {c}
    /\ rrp' = RrpCallFailed(rrp, c.procs, c.sn, online)
    /\ UNCHANGED <<rsVars, msVars, mVars, trsp, nextPid, scpRegs, regionVars, targetFired>>

-----------------------------------------------------------------------------
(* Master: Open/CloseRegionProcedure (RegionRemoteProcedureBase)            *)

Unattach(t, r, p) ==                                            \* RRPB:289-291 -> TRSP:592-595
    IF t[r] # NoTRSP /\ t[r].child = p THEN [t EXCEPT ![r].child = 0] ELSE t

NewRrp(r, k, tgt) ==                                            \* ORP:49-52 / CRP:54-59 -> RRPB:84-89
    /\ rrp' = rrp @@ (nextPid :> [r |-> r, k |-> k, tgt |-> tgt, st |-> "DISPATCH",
                                  fin |-> FALSE, disp |-> FALSE])
    /\ nextPid' = nextPid + 1

\* RRPB.execute REGION_REMOTE_PROCEDURE_DISPATCH (RRPB:335-350): addOperationToNode(targetServer)
RrpDispatch(p) ==
    /\ Serving
    /\ p \in DOMAIN rrp
    /\ ~rrp[p].fin /\ ~rrp[p].disp /\ rrp[p].st = "DISPATCH"
    /\ LET i == rrp[p].tgt.i IN
       IF dNode[i] = NoSp                                       \* RPD:168-173 NoServerDispatchException
       THEN /\ rrp'  = [rrp EXCEPT ![p].fin = TRUE]             \* RRPB:341-346 unattach, finish
            /\ trsp' = Unattach(trsp, rrp[p].r, p)
            /\ UNCHANGED buf
       ELSE /\ buf'  = [buf EXCEPT ![i] = @ \cup {p}]           \* RRPB:340 -> RPD:174 -> 396-408
            /\ rrp'  = [rrp EXCEPT ![p].disp = TRUE]            \* RRPB:348-350 suspend on the region event
            /\ UNCHANGED trsp
    /\ UNCHANGED <<rsVars, online, reported, dead, srvNode, rsList, dNode, scp, mVars, calls,
                   nextPid, scpRegs, regionVars, targetFired>>

\* RRPB.execute after being woken (RRPB:352-376): REPORT_SUCCEED -> persistToMeta; DISPATCH_FAIL ->
\* nothing; SERVER_CRASH -> regionClosedAbnormally (AM:2321-2341). Then unattach and finish.
RrpFinish(p) ==
    /\ Serving
    /\ p \in DOMAIN rrp
    /\ ~rrp[p].fin
    /\ rrp[p].st \in {"REPORT_SUCCEED", "DISPATCH_FAIL", "SERVER_CRASH"}
    /\ LET r == rrp[p].r IN
       /\ IF rrp[p].st = "SERVER_CRASH"
          THEN /\ rstate'   = [rstate EXCEPT ![r] = "ABNORMALLY_CLOSED"]   \* AM:2324
               /\ loc'      = [loc EXCEPT ![r] = NoSN]                     \* AM:2325
               /\ lastHost' = [lastHost EXCEPT ![r] =                      \* AM:2329-2330
                                 IF loc[r] # NoSN THEN loc[r] ELSE @]
          ELSE UNCHANGED <<rstate, loc, lastHost>>
       /\ rrp'  = [rrp EXCEPT ![p].fin = TRUE]
       /\ trsp' = Unattach(trsp, r, p)
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, nextPid, scpRegs, targetFired>>

-----------------------------------------------------------------------------
(* Master: TransitRegionStateProcedure and the AM assign thread            *)

\* TRSP.checkAndWaitForOriginalServer (TRSP:221-244): the same-address server must be a destination
RetainOnline(l) ==
    LET k == FindSameAddrM(MS, l) IN k # 0 /\ k \in Dest       \* TRSP:224-225

\* TRSP GET_ASSIGN_CANDIDATE (TRSP:488-506) -> queueAssign (TRSP:246-278). With force-retain the TRSP
\* suspends until the hinted address has a destination (TRSP:262-269, 227-237). Running out of retries is
\* TrspForceRetainGiveUp. The re-check is taken only when its outcome changed.
TrspQueueAssign(r) ==
    /\ Serving
    /\ trsp[r] # NoTRSP
    /\ trsp[r].st \in {"GET_ASSIGN_CANDIDATE", "WAIT_RETAIN"}
    /\ LET t == trsp[r]
           l == IF t.fnp THEN NoSN                              \* TRSP:249-251
                ELSE IF t.cand # NoSN THEN t.cand               \* TRSP:253-255
                ELSE IF lastHost[r] # NoSN THEN lastHost[r]     \* TRSP:256-260
                ELSE loc[r]                                     \* location left as it was
           wait == /\ ~t.fnp /\ l # NoSN /\ ForceRetain         \* TRSP:262-265
                   /\ ~RetainOnline(l)                          \* TRSP:227 suspend (WAITING_TIMEOUT)
           st2 == IF wait THEN "WAIT_RETAIN" ELSE "WAIT_PLAN"   \* TRSP:273-277 AM.queueAssign, wait for plan
       IN /\ ~(t.st = "WAIT_RETAIN" /\ st2 = "WAIT_RETAIN" /\ l = loc[r])
          /\ loc'  = [loc EXCEPT ![r] = l]
          /\ trsp' = [trsp EXCEPT ![r].st = st2]
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, rrp, nextPid, scpRegs, rstate, lastHost, targetFired>>

\* TRSP.checkAndWaitForOriginalServer when forceRetainmentRetryCounter ran out (TRSP:227 false, TRSP:239-243;
\* AM:179-182 retry limit): queueAssign goes on with the location it already set (TRSP:273-277). Time passing
\* is the trigger (bounded in MC).
TrspForceRetainGiveUp(r) ==
    /\ Serving
    /\ trsp[r] # NoTRSP /\ trsp[r].st = "WAIT_RETAIN"
    /\ loc[r] # NoSN
    /\ ~RetainOnline(loc[r])
    /\ trsp' = [trsp EXCEPT ![r].st = "WAIT_PLAN"]
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, rrp, nextPid, scpRegs, regionVars, targetFired>>

\* BaseLoadBalancer.retainAssignment (BLB:290-382) when a hint exists (AM:2544-2545, 2613-2618);
\* round robin over the destinations otherwise (AM:2627-2633). Iteration-order choices are nondeterministic.
PlanTargets(hint) ==
    IF hint = NoSN THEN Dest
    ELSE IF Cardinality(Dest) = 1 THEN Dest                                  \* BLB:302-304
    ELSE LET local == {j \in Dest : HostOf(incAddr[j]) = HostOf(incAddr[hint.i])}  \* BLB:313-317, 334
         IN IF local = {} THEN Dest                                          \* BLB:336-341 random
            ELSE IF Cardinality(local) = 1 THEN local                        \* BLB:342-346
            ELSE IF hint.i \in local THEN {hint.i}                           \* BLB:349-351 exact name
            ELSE LET samePort == {j \in local : incAddr[j] = incAddr[hint.i]}  \* BLB:353-361
                 IN IF samePort # {} THEN samePort ELSE Dest                 \* BLB:362-364, 370-382

\* AM.processAssignQueue (AM:2526-2588) over a fresh destination snapshot (AM:2554-2567, waits for one)
\* -> processAssignmentPlans (AM:2603-2639) -> acceptPlan sets the location and wakes the TRSP (AM:2641-2655).
AmAssign(r) ==
    /\ Serving
    /\ trsp[r] # NoTRSP /\ trsp[r].st = "WAIT_PLAN"
    /\ Dest # {}
    /\ \E tgt \in PlanTargets(loc[r]) :
         /\ loc'  = [loc EXCEPT ![r] = SN(tgt, online[tgt])]
         /\ trsp' = [trsp EXCEPT ![r].st = "OPEN"]
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, rrp, nextPid, scpRegs, rstate, lastHost, targetFired>>

\* TRSP OPEN (TRSP:507-509 -> openRegion TRSP:293-311): regionOpening (AM:2212-2232), then an
\* OpenRegionProcedure for the current location (TRSP:288-291).
TrspOpen(r) ==
    /\ Serving
    /\ trsp[r] # NoTRSP /\ trsp[r].st = "OPEN"
    /\ IF loc[r] = NoSN                                         \* TRSP:302-307
       THEN /\ trsp' = [trsp EXCEPT ![r].st = "GET_ASSIGN_CANDIDATE"]
            /\ UNCHANGED <<rrp, nextPid, rstate>>
       ELSE /\ rstate' = [rstate EXCEPT ![r] = "OPENING"]
            /\ NewRrp(r, "open", loc[r])
            /\ trsp' = [trsp EXCEPT ![r].st = "CONFIRM_OPENED", ![r].child = nextPid]
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, scpRegs, loc, lastHost, targetFired>>

\* TRSP CONFIRM_OPENED (TRSP:510-511 -> confirmOpened TRSP:320-374) once the child finished.
\* Assign max attempts is Integer.MAX_VALUE by default (AM:152-153): never gives up.
TrspConfirmOpened(r) ==
    /\ Serving
    /\ trsp[r] # NoTRSP /\ trsp[r].st = "CONFIRM_OPENED" /\ trsp[r].child = 0
    /\ IF rstate[r] = "OPEN"                                    \* TRSP:328-335 finish
       THEN /\ trsp' = [trsp EXCEPT ![r] = NoTRSP]
            /\ UNCHANGED loc
       ELSE /\ trsp' = [trsp EXCEPT ![r].fnp = TRUE,            \* TRSP:359-364 force a new plan
                                    ![r].st = "GET_ASSIGN_CANDIDATE"]
            /\ loc'  = [loc EXCEPT ![r] = NoSN]
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, rrp, nextPid, scpRegs, rstate, lastHost, targetFired>>

\* TRSP CLOSE (TRSP:512-514 -> closeRegion TRSP:389-407): regionClosing (AM:2265-2276), then a
\* CloseRegionProcedure for the current location (TRSP:376-387), never re-validated.
TrspClose(r) ==
    /\ Serving
    /\ trsp[r] # NoTRSP /\ trsp[r].st = "CLOSE"
    /\ IF rstate[r] \in {"OPEN", "CLOSING"}                     \* TRSP:397
       THEN /\ rstate' = [rstate EXCEPT ![r] = "CLOSING"]
            /\ NewRrp(r, "close", loc[r])
            /\ trsp' = [trsp EXCEPT ![r].st = "CONFIRM_CLOSED", ![r].child = nextPid]
            /\ UNCHANGED loc
       ELSE /\ trsp' = [trsp EXCEPT ![r].fnp = TRUE,            \* TRSP:402-405
                                    ![r].st = "GET_ASSIGN_CANDIDATE"]
            /\ loc'  = [loc EXCEPT ![r] = NoSN]
            /\ UNCHANGED <<rrp, nextPid, rstate>>
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, scpRegs, lastHost, targetFired>>

\* TRSP CONFIRM_CLOSED (TRSP:515-516 -> confirmClosed TRSP:409-446) once the child finished
TrspConfirmClosed(r) ==
    /\ Serving
    /\ trsp[r] # NoTRSP /\ trsp[r].st = "CONFIRM_CLOSED" /\ trsp[r].child = 0
    /\ \/ /\ rstate[r] = "CLOSED"                               \* TRSP:411-421
          /\ trsp' = IF trsp[r].type = "UNASSIGN"
                     THEN [trsp EXCEPT ![r] = NoTRSP]
                     ELSE [trsp EXCEPT ![r].st = "GET_ASSIGN_CANDIDATE"]
       \/ /\ rstate[r] = "CLOSING"                              \* TRSP:422-428 retry close, same location
          /\ trsp' = [trsp EXCEPT ![r].st = "CLOSE"]
       \/ /\ rstate[r] = "ABNORMALLY_CLOSED"                    \* TRSP:435-445 reopen
          /\ trsp' = [trsp EXCEPT ![r].st = "GET_ASSIGN_CANDIDATE"]
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, rrp, nextPid, scpRegs, regionVars, targetFired>>

-----------------------------------------------------------------------------
(* Master: ServerCrashProcedure (hbase:meta and WAL contents not modeled)   *)

ScpStart(i) ==                                                  \* SCP:168-178 (not carrying meta)
    /\ Serving
    /\ scp[i] = "START"
    /\ scp' = [scp EXCEPT ![i] = "GET_REGIONS"]
    /\ UNCHANGED <<rsVars, online, reported, dead, srvNode, rsList, dNode, buf, mVars, calls,
                   procVars, regionVars, targetFired>>

\* SCP GET_REGIONS (SCP:204-220): AM.getRegionsOnServer = the ServerStateNode region set (AM:501-507),
\* filled by regionOpening/regionOpened and drained by close/abnormal close (AM:2216-2228, 2288, 2300, 2331)
ScpGetRegions(i) ==
    /\ Serving
    /\ scp[i] = "GET_REGIONS"
    /\ scpRegs' = [scpRegs EXCEPT ![i] =
                     {r \in Region : loc[r].i = i /\ rstate[r] \in {"OPENING", "OPEN", "CLOSING"}}]
    /\ scp' = [scp EXCEPT ![i] = "SPLIT_LOGS"]                   \* SCP:215-219 shouldSplitWal
    /\ UNCHANGED <<rsVars, online, reported, dead, srvNode, rsList, dNode, buf, mVars, calls,
                   trsp, rrp, nextPid, regionVars, targetFired>>

\* SCP SPLIT_LOGS (SCP:221-227, ZK-coordinated in the workload, Test:82-85): only keeps the window open
ScpSplitLogs(i) ==
    /\ Serving
    /\ scp[i] = "SPLIT_LOGS"
    /\ scp' = [scp EXCEPT ![i] = "ASSIGN"]
    /\ UNCHANGED <<rsVars, online, reported, dead, srvNode, rsList, dNode, buf, mVars, calls,
                   procVars, regionVars, targetFired>>

\* SCP ASSIGN (SCP:243-269) -> assignRegions (SCP:562-640). Only here are in-flight ORP/CRP told that
\* their server crashed (TRSP.serverCrashed TRSP:566-586 -> RRPB.serverCrashed RRPB:247-268), and
\* SERVER_CRASH does not stop remoteCallBuild (RRPB:92-100).
ScpAssign(i) ==
    /\ Serving
    /\ scp[i] = "ASSIGN"
    /\ LET R == scpRegs[i]
           match(r)   == r \in R /\ loc[r].i = i                            \* SCP:540-542, 601-611
           withTr(r)  == match(r) /\ trsp[r] # NoTRSP                      \* SCP:612-618
           abn(r)     == withTr(r) /\ trsp[r].child = 0                    \* TRSP:577-584
                         /\ rstate[r] # "ABNORMALLY_CLOSED"
       IN
       /\ trsp' = [r \in Region |->
                     IF withTr(r) THEN [trsp[r] EXCEPT !.fnp = ~ScpRetain]  \* TRSP:568
                     ELSE IF match(r)                                      \* SCP:628-635 new retain TRSP
                     THEN NewTrsp("ASSIGN", "GET_ASSIGN_CANDIDATE", NoSN, ~ScpRetain, i)
                     ELSE trsp[r]]
       /\ rrp' = [p \in DOMAIN rrp |->
                    IF \E r \in Region : withTr(r) /\ trsp[r].child = p     \* TRSP:569-576
                    THEN [rrp[p] EXCEPT !.st = "SERVER_CRASH"]              \* RRPB:248-258
                    ELSE rrp[p]]
       /\ rstate'   = [r \in Region |-> IF abn(r) THEN "ABNORMALLY_CLOSED" ELSE rstate[r]]  \* AM:2321-2341
       /\ loc'      = [r \in Region |-> IF abn(r) THEN NoSN ELSE loc[r]]
       /\ lastHost' = [r \in Region |-> IF abn(r) /\ loc[r] # NoSN THEN loc[r] ELSE lastHost[r]]
    /\ scp' = [scp EXCEPT ![i] = "FINISH"]                       \* SCP:264-265 (no replication peers)
    /\ UNCHANGED <<rsVars, online, reported, dead, srvNode, rsList, dNode, buf, mVars, calls,
                   nextPid, scpRegs, targetFired>>

\* SCP FINISH (SCP:293-297), after every child TRSP completed: removeServer
ScpFinish(i) ==
    /\ Serving
    /\ scp[i] = "FINISH"
    /\ \A r \in Region : trsp[r] = NoTRSP \/ trsp[r].parent # i
    /\ srvNode' = [srvNode EXCEPT ![i] = "none"]
    /\ scp'     = [scp EXCEPT ![i] = "done"]
    /\ UNCHANGED <<rsVars, online, reported, dead, rsList, dNode, buf, mVars, calls, procVars,
                   regionVars, targetFired>>

-----------------------------------------------------------------------------
(* Client                                                                  *)

\* Admin.move(region, dest) -> HMaster.move (HM:2414-2480): an explicit destination is not checked for
\* liveness (HM:2445-2451; a random one comes from the destination list, HM:2436-2444)
\* -> AM.createMoveRegionProcedure (AM:873-891) -> TRSP.move (TRSP:757-761), starting at CLOSE (TRSP:159-163).
ClientMove(r, d) ==
    /\ Inited                                                   \* HM:2474 checkInitialized
    /\ trsp[r] = NoTRSP                                         \* AM:883 -> 764-767 preTransitCheck
    /\ rstate[r] = "OPEN"                                       \* AM:768-770, 884 checkOnline
    /\ d.i # loc[r].i                                           \* HM:2463-2467 same server: skip
    /\ trsp' = [trsp EXCEPT ![r] = NewTrsp("MOVE", "CLOSE", d, FALSE, 0)]
    /\ UNCHANGED <<rsVars, msVars, mVars, calls, rrp, nextPid, scpRegs, regionVars, targetFired>>

-----------------------------------------------------------------------------
(* Master failover (S3, S4)                                                *)

\* Active master process dies: volatile state is lost; the procedure store, hbase:meta and the RS list
\* storage survive. DISPATCH_FAIL is not persisted (RRPB:141-143); a TRSP resumes from its persisted
\* state (WAIT_RETAIN re-runs GET_ASSIGN_CANDIDATE; WAIT_PLAN resumes at OPEN, TRSP:274).
MasterCrash ==
    /\ mPhase # "down"
    /\ mPhase'   = "down"
    /\ online'   = [i \in Inc |-> NoSp]
    /\ reported' = [i \in Inc |-> FALSE]
    /\ dead'     = [i \in Inc |-> NoSp]
    /\ srvNode'  = [i \in Inc |-> "none"]
    /\ dNode'    = [i \in Inc |-> NoSp]
    /\ buf'      = [i \in Inc |-> {}]
    /\ calls'    = {}
    /\ rstView'  = {}
    /\ failedSrv' = {}
    /\ rrp' = [p \in DOMAIN rrp |->
                 [rrp[p] EXCEPT !.st = IF @ = "DISPATCH_FAIL" /\ ~rrp[p].fin THEN "DISPATCH" ELSE @,
                                !.disp = FALSE]]
    /\ trsp' = [r \in Region |->
                  IF trsp[r] = NoTRSP THEN NoTRSP
                  ELSE [trsp[r] EXCEPT !.st = IF @ = "WAIT_RETAIN" THEN "GET_ASSIGN_CANDIDATE"
                                              ELSE IF @ = "WAIT_PLAN" THEN "OPEN" ELSE @]]
    /\ UNCHANGED <<rsVars, rsList, scp, nextPid, scpRegs, regionVars, targetFired>>

\* New active master, HMaster.finishActiveMasterInitialization up to the tracker upgrade:
\* procedure executor + dispatcher start (HM:1044, 1926-1929; RSPD:96-131 registers the listener while
\* onlineServers is empty), AM.setupRIT (HM:1049-1058), meta load server nodes (AM:1876-1885), then
\* RegionServerTracker.upgrade (HM:1066-1071 -> RST:128-160): createServer for possibly-live servers
\* (RST:142-143), checkAndRecordNewServer for every znode child in HashSet order (RST:145-155), then
\* findDeadServersAndProcess (RST:156-157 -> SM:444-449).
MasterStartup ==
    /\ mPhase = "down"
    /\ LET live  == rsList                                       \* HM:1070 (WAL-dir servers folded in)
           metaL == {loc[r].i : r \in {x \in Region : rstate[x] \in {"OPEN", "OPENING", "CLOSING"}
                                                      /\ loc[x] # NoSN}}
           m0    == [MS EXCEPT !.sn = [i \in Inc |-> IF i \in live \cup metaL THEN "ONLINE" ELSE "none"]]
           kids  == {i \in Inc : znode[i]}
       IN \E order \in Perms(kids) :
            LET m1 == FoldRecord(m0, order)                      \* RST:147-155
                m2 == [m1 EXCEPT !.dd = [i \in Inc |->           \* SM:446 servers with an unfinished SCP
                         IF scp[i] \notin {"none", "done"} /\ m1.dd[i] = NoSp THEN ZkSp ELSE m1.dd[i]]]
                m3 == ExpireAllM(m2, {i \in live : m2.on[i] = NoSp})   \* SM:447-448
            IN SetMS(m3)
    /\ rstView' = {i \in Inc : znode[i]}
    /\ mPhase'  = "upgraded"
    /\ UNCHANGED <<rsVars, failedSrv, calls, procVars, regionVars, targetFired>>

\* startServiceThreads (HM:1148): procedure workers (HM:1732) and serviceStarted = true (HM:1817)
MasterServiceStarted ==
    /\ mPhase = "upgraded"
    /\ mPhase' = "serviceStarted"
    /\ UNCHANGED <<rsVars, msVars, rstView, failedSrv, calls, procVars, regionVars, targetFired>>

\* setInitialized(true) (HM:1300)
MasterInitialized ==
    /\ mPhase = "serviceStarted"
    /\ mPhase' = "initialized"
    /\ UNCHANGED <<rsVars, msVars, rstView, failedSrv, calls, procVars, regionVars, targetFired>>

\* HM:1358 clearDeadServersWithSameHostNameAndPortOfOnlineServer (SM:1080-1084 -> DS:108-131): for every
\* online key, drop dead entries at the same address - including that server's own entry.
MasterClearDeadServers ==
    /\ mPhase = "initialized"
    /\ mPhase' = "ready"
    /\ dead' = [d \in Inc |->
                  IF /\ dead[d] # NoSp
                     /\ \E k \in Inc : online[k] # NoSp /\ incAddr[k] = incAddr[d] /\ online[k] = dead[d]
                  THEN NoSp ELSE dead[d]]
    /\ UNCHANGED <<rsVars, online, reported, srvNode, rsList, dNode, buf, scp, rstView, failedSrv, calls,
                   procVars, regionVars, targetFired>>

-----------------------------------------------------------------------------
(* Specification                                                           *)

Init ==
    /\ incAddr   = [i \in Inc |-> IF i \in InitInc THEN i ELSE 0]
    /\ sc        = [i \in Inc |-> IF i \in InitInc THEN i ELSE 0]
    /\ rsPhase   = [i \in Inc |-> IF i \in InitInc THEN "online" ELSE "none"]
    /\ holder    = [a \in Addr |-> a]
    /\ znode     = [i \in Inc |-> i \in InitInc]
    /\ \E place \in [Region -> InitInc] :                      \* setupCluster placement (Test:301-324)
         /\ rsRegions = [i \in Inc |-> {r \in Region : place[r] = i}]
         /\ loc       = [r \in Region |-> SN(place[r], DeploySp)]
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
    /\ lastHost  = [r \in Region |-> NoSN]
    /\ targetFired = FALSE

\* Actions that react to existing state (never bounded in MC)
ReactiveNext ==
    \/ \E i \in Inc :
         \/ RsStartRpc(i) \/ RsReportForDuty(i) \/ RsCreateEphemeralNode(i) \/ RsOnline(i) \/ RsReport(i)
         \/ RsExit(i) \/ ZnodeDelete(i)
         \/ \E r \in Region : RsCloseRegionOnStop(i, r)
         \/ \E t \in rsTasks[i] : RsOpenRegion(i, t) \/ RsCloseRegion(i, t)
         \/ BufferFlush(i)
         \/ ScpStart(i) \/ ScpGetRegions(i) \/ ScpSplitLogs(i) \/ ScpAssign(i) \/ ScpFinish(i)
    \/ TrackerRefresh
    \/ \E a \in failedSrv : FailedServerExpire(a)
    \/ \E c \in calls :
         \/ DeadCallRun(c) \/ CallSend(c)
         \/ CallDeliverNoServer(c) \/ CallDeliverFailedServer(c)
         \/ CallDeliverNotStarted(c) \/ CallDeliverCheckOpenFail(c)
         \/ TargetCheck(c)
         \/ CallSucceeded(c) \/ CallFailed(c)
    \/ \E p \in DOMAIN rrp : RrpDispatch(p) \/ RrpFinish(p)
    \/ \E r \in Region :
         \/ TrspQueueAssign(r) \/ AmAssign(r) \/ TrspOpen(r) \/ TrspConfirmOpened(r)
         \/ TrspClose(r) \/ TrspConfirmClosed(r)
    \/ MasterStartup \/ MasterServiceStarted \/ MasterInitialized \/ MasterClearDeadServers

\* Actions that introduce nondeterminism: workload steps, faults, time passing (bounded in MC)
FaultNext ==
    \/ \E a \in Addr : RsConstruct(a, MaxSc + 1) \/ RsConstructClockBack(a, MinSc - 1)
    \/ \E i \in Inc : RsStop(i) \/ RsCrash(i)
    \/ \E r \in Region, j \in Constructed : ClientMove(r, SN(j, DeploySp))
    \/ \E c \in calls : CallSnryeTimeout(c)
    \/ \E r \in Region : TrspForceRetainGiveUp(r)
    \/ MasterCrash

\* tla-patterns 1: once the target fired every action may stop
Next == ~targetFired /\ (ReactiveNext \/ FaultNext)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties                                                              *)

\* adhoc-coordination Shared Rule 1: the target check never fails
TargetSafe == ~targetFired

\* tla-patterns 2 (temporary sanity invariant): the code path to RSR:1877 is enabled for a request with
\* at least one open/close request. TLC must VIOLATE this in the workload config.
TargetCheckEnabled ==
    \E c \in calls : /\ c.mode = "sent" /\ c.ops # {}
                     /\ CallAddr(c) \notin failedSrv
                     /\ Recv(c) # 0 /\ rsPhase[Recv(c)] = "online"
TargetReached == ~TargetCheckEnabled

TrspRec == [type : {"ASSIGN", "MOVE", "UNASSIGN"}, st : TrspStates, cand : SNs \cup {NoSN},
            fnp : BOOLEAN, child : Nat, parent : 0..MaxInc]

\* Structural: types plus port exclusivity (one incarnation per address)
TypeOK ==
    /\ incAddr \in [Inc -> 0..NAddr]
    /\ sc \in [Inc -> Int]
    /\ rsPhase \in [Inc -> RsPhases]
    /\ holder \in [Addr -> 0..MaxInc]
    /\ znode \in [Inc -> BOOLEAN]
    /\ rsRegions \in [Inc -> SUBSET Region]
    /\ \A i \in Inc : \A t \in rsTasks[i] : t.r \in Region /\ t.k \in {"open", "close"} /\ t.p \in Nat
    /\ mPhase \in MPhases
    /\ online \in [Inc -> Spell \cup {NoSp}]
    /\ reported \in [Inc -> BOOLEAN]
    /\ dead \in [Inc -> Spell \cup {NoSp}]
    /\ srvNode \in [Inc -> {"none", "ONLINE", "CRASHED"}]
    /\ dNode \in [Inc -> Spell \cup {NoSp}]
    /\ \A i \in Inc : buf[i] \subseteq DOMAIN rrp
    /\ rsList \subseteq Inc /\ rstView \subseteq Inc /\ failedSrv \subseteq Addr
    /\ scp \in [Inc -> ScpStates]
    /\ \A i \in Inc : scpRegs[i] \subseteq Region
    /\ \A r \in Region : trsp[r] = NoTRSP \/ trsp[r] \in TrspRec
    /\ DOMAIN rrp = 1..(nextPid - 1)
    /\ \A p \in DOMAIN rrp : /\ rrp[p].r \in Region /\ rrp[p].k \in {"open", "close"}
                             /\ rrp[p].tgt \in SNs /\ rrp[p].st \in RrpStates
                             /\ rrp[p].fin \in BOOLEAN /\ rrp[p].disp \in BOOLEAN
    /\ \A c \in calls : /\ c.sn \in SNs /\ c.procs \subseteq DOMAIN rrp /\ c.mode \in CallModes
                        /\ c.att \in 0..FailFastLimit /\ c.snr \in BOOLEAN
                        /\ c.ops \subseteq c.procs /\ c.out \in Outcomes
    /\ rstate \in [Region -> RStates]
    /\ \A r \in Region : loc[r] \in SNs \cup {NoSN} /\ lastHost[r] \in SNs \cup {NoSN}
    /\ targetFired \in BOOLEAN
    \* port exclusivity: a bound incarnation is the holder of its address, and the holder is bound there
    /\ \A i \in Inc : rsPhase[i] \in BoundPhases => holder[incAddr[i]] = i
    /\ \A a \in Addr : holder[a] # 0 => (rsPhase[holder[a]] \in BoundPhases /\ incAddr[holder[a]] = a)

\* Structural ("a message carries only values its sender held"): every call names a real incarnation,
\* and every procedure it carries targets exactly the ServerName the call stamps (RSPD:242, 274; RRPB:340)
RequestCarriesHeldName ==
    \A c \in calls :
        /\ c.sn.i \in Constructed
        /\ \A p \in c.procs : rrp[p].tgt.i = c.sn.i

\* For base.cfg only: keep the unbounded base Next finite, and place every RS on one host
BaseConstraint == nextPid <= 2
BaseSameHost(a) == "host"

=============================================================================
