--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hbase-adhoc-31).                   *)
(*                                                                         *)
(* Counter-bounded (they introduce nondeterminism):                        *)
(*   client   ClientMove                 admin.move (S1-S4 trigger)         *)
(*   stop     RsStop                     graceful stop (workload Test:264)  *)
(*   crash    RsCrash                    abrupt death, znode lingers        *)
(*   restart  RsConstruct(+ClockBack)    same-port restart (Test:270-272)   *)
(*   clock    RsConstructClockBack       S2 wall clock stepped back         *)
(*   failover MasterCrash                S3/S4 master failover              *)
(*   snrye    CallSnryeTimeout           60 s of SNRYE elapsed (time)       *)
(*   giveup   TrspForceRetainGiveUp      force-retain retries ran out (time) *)
(* stop + crash <= MaxRsDown.                                              *)
(*                                                                         *)
(* Unbounded: every reactive action in base!ReactiveNext (RS startup steps, *)
(* reports, region handlers, tracker, dispatcher, delivery, TargetCheck,   *)
(* RRP/TRSP/SCP steps, master startup phases, znode deletion).             *)
(*                                                                         *)
(* MaxPid bounds the number of Open/CloseRegionProcedures created (a state  *)
(* constraint, like a term bound); FailFastLimit is scaled down from 10.    *)
(***************************************************************************)
EXTENDS base, TLC

CONSTANTS
    MaxClientOps,       \* admin.move calls
    MaxRsStop,          \* graceful RS stops
    MaxRsCrash,         \* abrupt RS deaths (znode lingers until session expiry)
    MaxRsDown,          \* total stops + crashes
    MaxRsRestart,       \* new RS incarnations (same-port restarts)
    MaxClockStepBack,   \* restarts whose startcode is below the predecessor's (S2)
    MaxMasterFailover,  \* active master crashes (S3, S4)
    MaxSnryeTimeout,    \* SNRYE wait windows that run out (RSPD:303-305)
    MaxRetainGiveUp,    \* force-retain waits that run out of retries (TRSP:227, 239-243)
    MaxPid,             \* Open/CloseRegionProcedures created
    FocusMode           \* which firing steps count in this hunt: see HuntFocus

ASSUME FocusMode \in {"none", "afterRetry", "stillOnline", "stillOnlineLateRegister", "stillOnlineNoScp"}

VARIABLE fc             \* fault / workload counters

mcVars == <<vars, fc>>

\* Quantifiers in MCNext range over constant supersets so that TLC splits MCNext into named actions.
\* A call is identified by its procedure set: each pid is in at most one call per master lifetime
\* (RrpDispatch runs once per pid; a failover clears calls).
TaskSet  == [r : Region, k : {"open", "close"}, p : 1..MaxPid]
CallKeys == SUBSET (1..MaxPid) \ {{}}

MCInit ==
    /\ Init
    /\ fc = [client |-> 0, stop |-> 0, crash |-> 0, restart |-> 0, clock |-> 0,
             failover |-> 0, snrye |-> 0, giveup |-> 0]

-----------------------------------------------------------------------------
(* Counter-bounded wrappers                                                *)

MCClientMove(r, j) ==
    /\ ~targetFired
    /\ fc.client < MaxClientOps
    /\ j \in Constructed
    /\ ClientMove(r, SN(j, DeploySp))
    /\ fc' = [fc EXCEPT !.client = @ + 1]

MCRsStop(i) ==
    /\ ~targetFired
    /\ fc.stop < MaxRsStop
    /\ fc.stop + fc.crash < MaxRsDown
    /\ RsStop(i)
    /\ fc' = [fc EXCEPT !.stop = @ + 1]

MCRsCrash(i) ==
    /\ ~targetFired
    /\ fc.crash < MaxRsCrash
    /\ fc.stop + fc.crash < MaxRsDown
    /\ RsCrash(i)
    /\ fc' = [fc EXCEPT !.crash = @ + 1]

MCRsConstruct(a) ==
    /\ ~targetFired
    /\ fc.restart < MaxRsRestart
    /\ RsConstruct(a, MaxSc + 1)
    /\ fc' = [fc EXCEPT !.restart = @ + 1]

MCRsConstructClockBack(a) ==
    /\ ~targetFired
    /\ fc.restart < MaxRsRestart
    /\ fc.clock < MaxClockStepBack
    /\ RsConstructClockBack(a, MinSc - 1)
    /\ fc' = [fc EXCEPT !.restart = @ + 1, !.clock = @ + 1]

MCMasterCrash ==
    /\ ~targetFired
    /\ fc.failover < MaxMasterFailover
    /\ MasterCrash
    /\ fc' = [fc EXCEPT !.failover = @ + 1]

MCCallSnryeTimeout(ps) ==
    /\ ~targetFired
    /\ fc.snrye < MaxSnryeTimeout
    /\ \E c \in calls : c.procs = ps /\ CallSnryeTimeout(c)
    /\ fc' = [fc EXCEPT !.snrye = @ + 1]

MCTrspForceRetainGiveUp(r) ==
    /\ ~targetFired
    /\ fc.giveup < MaxRetainGiveUp
    /\ TrspForceRetainGiveUp(r)
    /\ fc' = [fc EXCEPT !.giveup = @ + 1]

MCFaultNext ==
    \/ \E a \in Addr : MCRsConstruct(a) \/ MCRsConstructClockBack(a)
    \/ \E i \in Inc : MCRsStop(i) \/ MCRsCrash(i)
    \/ \E r \in Region, j \in Inc : MCClientMove(r, j)
    \/ \E ps \in CallKeys : MCCallSnryeTimeout(ps)
    \/ \E r \in Region : MCTrspForceRetainGiveUp(r)
    \/ MCMasterCrash

-----------------------------------------------------------------------------
(* Hunt focus. All Scenarios end in the same firing step, and TLC stops at  *)
(* the first violation, so a hunt whose faults also allow a shorter        *)
(* mechanism only reports that one and never answers its own question.     *)
(* Each mode disables a firing step that belongs to another Scenario; no   *)
(* other behavior changes and the oracle stays TargetSafe. This has to be  *)
(* in the wrapper: TLC checks invariants on a successor before it applies  *)
(* CONSTRAINT or ACTION_CONSTRAINT, so those cannot filter a violation.    *)
(*                                                                         *)
(*   "none"             MC.cfg, S1: every firing step counts.              *)
(*   "afterRetry"       S1 variant: the call was re-sent at least once, so *)
(*                      the shortest trace is the 1a/1b bridge (seconds    *)
(*                      wide) and not the 1c first-send race.              *)
(*   "stillOnline"      S2, S3: the master still lists the target as online *)
(*                      (SM:405-409 rejected newcomer; SM:675-678 early    *)
(*                      return). A retired target is the S1 bridge         *)
(*                      (RSPD:153, 339 run before the send).               *)
(*   "stillOnlineLateRegister" S3 variant: as "stillOnline", and no RS may  *)
(*                      register before the failover, so the shortest trace *)
(*                      is the brief's route (registers with the new master *)
(*                      before `initialized`), not a stall of seconds       *)
(*                      between HRS report-for-duty and HRS:1467.           *)
(*   "stillOnlineNoScp" S4: also no SCP was ever submitted for the target, *)
(*                      as retirement never called expireServer            *)
(*                      (SM:508-519). An expired target is S3.             *)

HuntFocus(c) ==
    \/ FocusMode = "none"
    \/ ~targetFired'
    \/ FocusMode = "afterRetry" /\ c.att > 0                  \* RSPD:298, 355 numberOfAttemptsSoFar++
    \/ /\ FocusMode \in {"stillOnline", "stillOnlineLateRegister", "stillOnlineNoScp"}
       /\ IsOnline(c.sn.i)
       /\ FocusMode # "stillOnlineNoScp" \/ scp[c.sn.i] = "none"

-----------------------------------------------------------------------------
(* Unbounded reactive actions: one named wrapper each (guard + fc kept), so *)
(* that TLC prints the action name on every counterexample step.           *)

RsStartRpc_(i)               == ~targetFired /\ RsStartRpc(i) /\ UNCHANGED fc
RsReportForDuty_(i)          == ~targetFired /\ (FocusMode # "stillOnlineLateRegister" \/ fc.failover > 0)
                                /\ RsReportForDuty(i) /\ UNCHANGED fc
RsCreateEphemeralNode_(i)    == ~targetFired /\ RsCreateEphemeralNode(i) /\ UNCHANGED fc
RsOnline_(i)                 == ~targetFired /\ RsOnline(i) /\ UNCHANGED fc
RsReport_(i)                 == ~targetFired /\ RsReport(i) /\ UNCHANGED fc
RsExit_(i)                   == ~targetFired /\ RsExit(i) /\ UNCHANGED fc
ZnodeDelete_(i)              == ~targetFired /\ ZnodeDelete(i) /\ UNCHANGED fc
RsCloseRegionOnStop_(i, r)   == ~targetFired /\ RsCloseRegionOnStop(i, r) /\ UNCHANGED fc
RsOpenRegion_(i, t)          == ~targetFired /\ RsOpenRegion(i, t) /\ UNCHANGED fc
RsCloseRegion_(i, t)         == ~targetFired /\ RsCloseRegion(i, t) /\ UNCHANGED fc
BufferFlush_(i)              == ~targetFired /\ BufferFlush(i) /\ UNCHANGED fc
ScpStart_(i)                 == ~targetFired /\ ScpStart(i) /\ UNCHANGED fc
ScpGetRegions_(i)            == ~targetFired /\ ScpGetRegions(i) /\ UNCHANGED fc
ScpSplitLogs_(i)             == ~targetFired /\ ScpSplitLogs(i) /\ UNCHANGED fc
ScpAssign_(i)                == ~targetFired /\ ScpAssign(i) /\ UNCHANGED fc
ScpFinish_(i)                == ~targetFired /\ ScpFinish(i) /\ UNCHANGED fc
TrackerRefresh_              == ~targetFired /\ TrackerRefresh /\ UNCHANGED fc
FailedServerExpire_(a)       == ~targetFired /\ FailedServerExpire(a) /\ UNCHANGED fc
DeadCallRun_(ps)             == ~targetFired /\ (\E c \in calls : c.procs = ps /\ DeadCallRun(c)) /\ UNCHANGED fc
CallSend_(ps)                == ~targetFired /\ (\E c \in calls : c.procs = ps /\ CallSend(c)) /\ UNCHANGED fc
CallDeliverNoServer_(ps)     == ~targetFired /\ (\E c \in calls : c.procs = ps /\ CallDeliverNoServer(c)) /\ UNCHANGED fc
CallDeliverFailedServer_(ps) == ~targetFired /\ (\E c \in calls : c.procs = ps /\ CallDeliverFailedServer(c)) /\ UNCHANGED fc
CallDeliverNotStarted_(ps)   == ~targetFired /\ (\E c \in calls : c.procs = ps /\ CallDeliverNotStarted(c)) /\ UNCHANGED fc
CallDeliverCheckOpenFail_(ps)== ~targetFired /\ (\E c \in calls : c.procs = ps /\ CallDeliverCheckOpenFail(c)) /\ UNCHANGED fc
TargetCheck_(ps)             == ~targetFired /\ (\E c \in calls : c.procs = ps /\ TargetCheck(c) /\ HuntFocus(c)) /\ UNCHANGED fc
CallSucceeded_(ps)           == ~targetFired /\ (\E c \in calls : c.procs = ps /\ CallSucceeded(c)) /\ UNCHANGED fc
CallFailed_(ps)              == ~targetFired /\ (\E c \in calls : c.procs = ps /\ CallFailed(c)) /\ UNCHANGED fc
RrpDispatch_(p)              == ~targetFired /\ RrpDispatch(p) /\ UNCHANGED fc
RrpFinish_(p)                == ~targetFired /\ RrpFinish(p) /\ UNCHANGED fc
TrspQueueAssign_(r)          == ~targetFired /\ TrspQueueAssign(r) /\ UNCHANGED fc
AmAssign_(r)                 == ~targetFired /\ AmAssign(r) /\ UNCHANGED fc
TrspOpen_(r)                 == ~targetFired /\ TrspOpen(r) /\ UNCHANGED fc
TrspConfirmOpened_(r)        == ~targetFired /\ TrspConfirmOpened(r) /\ UNCHANGED fc
TrspClose_(r)                == ~targetFired /\ TrspClose(r) /\ UNCHANGED fc
TrspConfirmClosed_(r)        == ~targetFired /\ TrspConfirmClosed(r) /\ UNCHANGED fc
MasterStartup_               == ~targetFired /\ MasterStartup /\ UNCHANGED fc
MasterServiceStarted_        == ~targetFired /\ MasterServiceStarted /\ UNCHANGED fc
MasterInitialized_           == ~targetFired /\ MasterInitialized /\ UNCHANGED fc
MasterClearDeadServers_      == ~targetFired /\ MasterClearDeadServers /\ UNCHANGED fc

\* Same disjuncts as base!ReactiveNext, each with fc unchanged.
MCReactiveNext ==
    \/ \E i \in Inc :
         \/ RsStartRpc_(i) \/ RsReportForDuty_(i) \/ RsCreateEphemeralNode_(i) \/ RsOnline_(i) \/ RsReport_(i)
         \/ RsExit_(i) \/ ZnodeDelete_(i)
         \/ \E r \in Region : RsCloseRegionOnStop_(i, r)
         \/ \E t \in TaskSet : RsOpenRegion_(i, t) \/ RsCloseRegion_(i, t)
         \/ BufferFlush_(i)
         \/ ScpStart_(i) \/ ScpGetRegions_(i) \/ ScpSplitLogs_(i) \/ ScpAssign_(i) \/ ScpFinish_(i)
    \/ TrackerRefresh_
    \/ \E a \in Addr : FailedServerExpire_(a)
    \/ \E ps \in CallKeys :
         \/ DeadCallRun_(ps) \/ CallSend_(ps)
         \/ CallDeliverNoServer_(ps) \/ CallDeliverFailedServer_(ps)
         \/ CallDeliverNotStarted_(ps) \/ CallDeliverCheckOpenFail_(ps)
         \/ TargetCheck_(ps)
         \/ CallSucceeded_(ps) \/ CallFailed_(ps)
    \/ \E p \in 1..MaxPid : RrpDispatch_(p) \/ RrpFinish_(p)
    \/ \E r \in Region :
         \/ TrspQueueAssign_(r) \/ AmAssign_(r) \/ TrspOpen_(r) \/ TrspConfirmOpened_(r)
         \/ TrspClose_(r) \/ TrspConfirmClosed_(r)
    \/ MasterStartup_ \/ MasterServiceStarted_ \/ MasterInitialized_ \/ MasterClearDeadServers_

\* tla-patterns 1: once the target fired every action stops. The ~targetFired guard sits inside every
\* wrapper (not on MCNext) so that TLC can split MCNext into named actions.
MCNext == MCReactiveNext \/ MCFaultNext

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(* Bounds and configuration helpers                                        *)

\* Finite number of Open/CloseRegionProcedures (TRSP retries create new ones without limit,
\* AM:152-153 Integer.MAX_VALUE attempts)
MCConstraint == nextPid <= MaxPid + 1

\* The mini cluster runs every RegionServer on one host, different ports (Test:241-244, 326-340)
MCSameHost(a) == "host"
\* Distinct hosts, for configurations that want BLB's single-local-server branch (BLB:342-346)
MCDistinctHosts(a) == a

=============================================================================
