-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hbase-adhoc-08), Category A: one NDJSON  *)
(* trace of the whole mini cluster (all masters and the test client in one *)
(* JVM), totally ordered by the synchronized SpeculaTrace.emit.            *)
(*                                                                         *)
(* Line format (instrumentation-spec.md section 1):                        *)
(*   {"tag":"trace","ts":<nanos>,"event":{"name":..,"nid":..,              *)
(*                                        "state":{..},"msg":{..}}}        *)
(* nid: "m<i>" (HMaster in construction order), "r<i>" (RegionServer),     *)
(* "client" (the test thread), "test" (the Init line).                     *)
(*                                                                         *)
(* An optional first line {"name":"Init","nid":"test","state":{..}}        *)
(* carries the workload configuration; Trace.cfg overrides the base        *)
(* constants with the Trace* operators below, which default to the         *)
(* workload's values when the line or a field is absent.                   *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC, FiniteSets

(***************************************************************************)
(* Trace loading                                                           *)
(***************************************************************************)
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

ToSet(s) == {s[i] : i \in DOMAIN s}

(***************************************************************************)
(* Configuration from the Init line (constant overrides in Trace.cfg)      *)
(***************************************************************************)
HasInitLine == TraceLog[1].event.name = "Init"
InitState   == IF HasInitLine THEN TraceLog[1].event.state ELSE [none |-> TRUE]
CfgOr(f, d) == IF f \in DOMAIN InitState THEN InitState[f] ELSE d

TraceMasters           == TLCEval(ToSet(CfgOr("masters", <<"m1", "m2">>)))
TraceRS                == TLCEval(ToSet(CfgOr("regionServers", <<"r1">>)))
TraceQuotaEnabled      == TLCEval(CfgOr("quotaEnabled", TRUE))
TraceRSGroupEnabled    == TLCEval(CfgOr("rsgroupEnabled", FALSE))
TraceSpaceQuotaNs      == TLCEval(ToSet(CfgOr("spaceQuotaNs", <<>>)))
TraceRsGroupRpcClient  == TLCEval(CfgOr("rsgroupRpcClient", FALSE))
TraceRpcTableNs        == TLCEval(ToSet(CfgOr("rpcTableNs", <<>>)))
TraceUserRegions       == TLCEval(ToSet(CfgOr("userRegions", <<"u1">>)))
TraceCreateTableRounds == TLCEval(CfgOr("createTableRounds", 4))
TraceCtRejected        == TLCEval(ToSet(CfgOr("ctRejected", <<2, 4>>)))

\* hbase:meta's host at Init: the first reported meta host (meta does not move
\* before the first reported crash); with one RegionServer it is that server.
MetaHostReports == TLCEval(SelectSeq(TraceLog, LAMBDA x :
                       /\ "state" \in DOMAIN x.event
                       /\ "metaHost" \in DOMAIN x.event.state))
TraceMetaInitHost ==
    IF Len(MetaHostReports) > 0 THEN MetaHostReports[1].event.state.metaHost
    ELSE CHOOSE x \in TraceRS : TRUE

(***************************************************************************)
(* Cursor and event predicates                                             *)
(***************************************************************************)
VARIABLE l

logline == TraceLog[l]
ev      == logline.event

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ ev.name = name

IsMasterEvent(name) ==
    /\ IsEvent(name)
    /\ ev.nid \in Masters

StepTrace == l' = l + 1

\* Does the trace carry assignment-manager events?  If not, the assignment of
\* the workload's table region is replayed silently (see Silent actions).
TraceHasAssignEvents == TLCEval(
    \E k \in 1..Len(TraceLog) :
        TraceLog[k].event.name \in {"TrspQueueAssign", "TargetCheck_Assign"})

(***************************************************************************)
(* Post-state validation                                                   *)
(***************************************************************************)
InitializedPhases == {"Initialized", "QuotaInit", "Running"}
SchemaPhases      == {"Loading", "Loaded", "Initialized", "QuotaInit", "Running"}

\* Master snapshot taken after the action on master m (instrumentation-spec.md
\* 1.2): HMaster.isInitialized(), getClusterSchema() /= null,
\* getMasterQuotaManager() /= null, and the keys of TNM.cache.
ValidateMaster(m) ==
    LET s == ev.state IN
    /\ (phase'[m] \in InitializedPhases) = s.initialized
    /\ (phase'[m] \in SchemaPhases)      = s.schemaPub
    /\ (phase'[m] = "Running")           = s.quotaPub
    /\ cache'[m] = ToSet(s.cache)

\* A namespace lookup reported by a target site: the looked-up name and
\* whether CSSI:110 returned a descriptor (the pre-state cache of master m).
ValidateLookup(m, n) ==
    /\ ev.msg.ns = n
    /\ ev.msg.found = (n \in cache[m])

ValidateDnp == dnp' = ev.state.dnp
ValidateCnp == cnp' = ev.state.cnp
ValidateCtp == ctp' = ev.state.ctp

(***************************************************************************)
(* Action wrappers                                                         *)
(***************************************************************************)

\* Optional first line: workload configuration and meta's ns rows at Init.
InitIfLogged ==
    /\ IsEvent("Init")
    /\ l = 1
    /\ metaNs = ToSet(ev.state.metaNs)
    /\ UNCHANGED vars
    /\ StepTrace

\* --- master activation ---
BecomeActiveIfLogged ==
    /\ IsMasterEvent("BecomeActive")
    /\ BecomeActive(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

WaitForMetaOnlineIfLogged ==
    /\ IsMasterEvent("WaitForMetaOnline")
    /\ WaitForMetaOnline(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

InitClusterSchemaServiceIfLogged ==
    /\ IsMasterEvent("InitClusterSchemaService")
    /\ InitClusterSchemaService(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

LoadRowIfLogged ==
    /\ IsMasterEvent("LoadRow")
    /\ ev.msg.ns = NextRow(ev.nid)
    /\ LoadRow(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

LoadDoneIfLogged ==
    /\ IsMasterEvent("LoadDone")
    /\ LoadDone(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

\* The master aborts; no post-state can be captured (weak validation).
LoadFailIfLogged ==
    /\ IsMasterEvent("LoadFail")
    /\ LoadFail(ev.nid)
    /\ StepTrace

GateInitializedIfLogged ==
    /\ IsMasterEvent("GateInitialized")
    /\ GateInitialized(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

QuotaSnapshotIfLogged ==
    /\ IsMasterEvent("QuotaSnapshot")
    /\ QuotaSnapshot(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ nsmSnap'[ev.nid] = ev.state.nsmSnap
    /\ StepTrace

TargetCheck_NsmInitIfLogged ==
    /\ IsMasterEvent("TargetCheck_NsmInit")
    /\ LET m == ev.nid IN
       /\ nsmIdx[m] <= Len(nsmSnap[m])
       /\ ValidateLookup(m, nsmSnap[m][nsmIdx[m]])
       /\ TargetCheck_NsmInit(m)
       /\ ValidateMaster(m)
    /\ StepTrace

QuotaPublishIfLogged ==
    /\ IsMasterEvent("QuotaPublish")
    /\ QuotaPublish(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

\* Emitted by the test right before it stops/kills the active master; the
\* master is gone afterwards (weak validation).
MasterCrashIfLogged ==
    /\ IsMasterEvent("MasterCrash")
    /\ MasterCrash(ev.nid)
    /\ StepTrace

\* --- DeleteNamespaceProcedure ---
DnpPrepareIfLogged ==
    /\ IsMasterEvent("DnpPrepare")
    /\ LET m == ev.nid IN
       /\ ValidateLookup(m, NSP)                     \* DNP:201 -> CSSI:110
       /\ DnpPrepare(m)
       /\ ValidateDnp
       /\ ValidateMaster(m)
    /\ StepTrace

DnpMetaDeleteIfLogged ==
    /\ IsMasterEvent("DnpMetaDelete")
    /\ DnpMetaDelete(ev.nid)
    /\ ValidateDnp
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

DnpCacheRemoveIfLogged ==
    /\ IsMasterEvent("DnpCacheRemove")
    /\ DnpCacheRemove(ev.nid)
    /\ ValidateDnp
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

DnpDeleteDirectoriesIfLogged ==
    /\ IsMasterEvent("DnpDeleteDirectories")
    /\ DnpDeleteDirectories(ev.nid)
    /\ ValidateDnp
    /\ StepTrace

DnpRemoveQuotaIfLogged ==
    /\ IsMasterEvent("DnpRemoveQuota")
    /\ DnpRemoveQuota(ev.nid)
    /\ ValidateDnp
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

\* PREPARE of the second DNP after a resend (DNP:190-191); the recovered DNP's
\* state stays as it ended.
DnpResendPrepareIfLogged ==
    /\ IsMasterEvent("DnpPrepare")
    /\ ev.state.dnp = "Failed"
    /\ ValidateLookup(ev.nid, NSP)                   \* DNP:189
    /\ DnpResendPrepare(ev.nid)
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

\* --- CreateNamespaceProcedure ---
CnpPrepareIfLogged ==
    /\ IsMasterEvent("CnpPrepare")
    /\ CnpPrepare(ev.nid)
    /\ ValidateCnp
    /\ StepTrace

CnpCreateDirectoryIfLogged ==
    /\ IsMasterEvent("CnpCreateDirectory")
    /\ CnpCreateDirectory(ev.nid)
    /\ ValidateCnp
    /\ StepTrace

CnpMetaPutIfLogged ==
    /\ IsMasterEvent("CnpMetaPut")
    /\ CnpMetaPut(ev.nid)
    /\ ValidateCnp
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

CnpCachePutIfLogged ==
    /\ IsMasterEvent("CnpCachePut")
    /\ CnpCachePut(ev.nid)
    /\ ValidateCnp
    /\ ValidateMaster(ev.nid)
    /\ StepTrace

CnpSetNamespaceQuotaIfLogged ==
    /\ IsMasterEvent("CnpSetNamespaceQuota")
    /\ CnpSetNamespaceQuota(ev.nid)
    /\ ValidateCnp
    /\ StepTrace

\* --- CreateTableProcedure ---
CtpPrepareIfLogged ==
    /\ IsMasterEvent("CtpPrepare")
    /\ ValidateLookup(ev.nid, NSP)                   \* CTP:316 -> CSSI:110
    /\ CtpPrepare(ev.nid)
    /\ ValidateCtp
    /\ StepTrace

CtpPreCreateIfLogged ==
    /\ IsMasterEvent("CtpPreCreate")
    /\ ValidateLookup(ev.nid, NSP)                   \* NSM:155 -> NSM:142 -> CSSI:110
    /\ CtpPreCreate(ev.nid)
    /\ ValidateCtp
    /\ StepTrace

CtpAssignRegionsIfLogged ==
    /\ IsMasterEvent("CtpAssignRegions")
    /\ CtpAssignRegions(ev.nid)
    /\ ValidateCtp
    /\ StepTrace

CtpFinishIfLogged ==
    /\ IsMasterEvent("CtpFinish")
    /\ CtpFinish(ev.nid)
    /\ ValidateCtp
    /\ StepTrace

\* --- workload client ---
ClientStartIfLogged ==
    /\ IsEvent("ClientStart")
    /\ ClientStart
    /\ StepTrace

\* Emitted on the master's RPC handler at the start of run() (HM:3610).
ClientCreateNamespaceIfLogged ==
    /\ IsMasterEvent("ClientCreateNamespace")
    /\ ev.msg.ns = NSP
    /\ ClientCreateNamespace(ev.nid)
    /\ StepTrace

\* Emitted by the test after Admin.createNamespace returned or threw.
ClientCreateNsResultIfLogged ==
    /\ IsEvent("ClientCreateNsResult")
    /\ cnp = ev.msg.result
    /\ \E m \in Masters : ClientCreateNsResult(m)
    /\ StepTrace

ClientSetSpaceQuotaIfLogged ==
    /\ IsMasterEvent("ClientSetSpaceQuota")
    /\ ev.msg.ns = NSP
    /\ ClientSetSpaceQuota(ev.nid)
    /\ StepTrace

TargetCheck_ClientGetIfLogged ==
    /\ IsMasterEvent("TargetCheck_ClientGet")
    /\ ValidateLookup(ev.nid, NSP)                   \* HM:3716 -> CSSI:110
    /\ TargetCheck_ClientGet(ev.nid)
    /\ StepTrace

TargetCheck_ClientCreateTableIfLogged ==
    /\ IsMasterEvent("TargetCheck_ClientCreateTable")
    /\ ValidateLookup(ev.nid, NSP)                   \* HM:2518 -> CSSI:110
    /\ TargetCheck_ClientCreateTable(ev.nid)
    /\ StepTrace

\* Emitted by the test after each Admin.createTable returned or threw.
ClientCreateTableResultIfLogged ==
    /\ IsEvent("ClientCreateTableResult")
    /\ ctp = ev.msg.result
    /\ ctRound = ev.msg.round
    /\ \E m \in Masters : ClientCreateTableResult(m)
    /\ StepTrace

\* Emitted by the test after the cleanup's table loop and namespace listing.
ClientDeleteTablesIfLogged ==
    /\ IsEvent("ClientDeleteTables")
    /\ \E m \in Masters :
         /\ (NSP \in cache[m]) = ev.msg.nsListed
         /\ ClientDeleteTables(m)
    /\ StepTrace

\* Emitted on the master's RPC handler at the start of run() (HM:3685), for the
\* first send and for a resend alike: the client sends no nonce, so both run run().
ClientDeleteNamespaceIfLogged ==
    /\ IsMasterEvent("ClientDeleteNamespace")
    /\ ev.msg.ns = NSP
    /\ \/ ClientDeleteNamespace(ev.nid)
       \/ ClientResendDeleteNamespace(ev.nid)
    /\ StepTrace

\* Emitted on the RPC handler after postDeleteNamespace (HM:3698) returned
\* ("NoQuota" / "Removed") or threw ("Failed").
HookPostDeleteNamespaceIfLogged ==
    /\ IsMasterEvent("HookPostDeleteNamespace")
    /\ HookPostDeleteNamespace(ev.nid)
    /\ ev.msg.result = IF QuotaEnabled /\ NSP \in spaceQuotaNs
                         THEN IF QuotaManagerPublished(ev.nid) THEN "Removed" ELSE "Failed"
                         ELSE "NoQuota"
    /\ StepTrace

\* Emitted by the test after Admin.deleteNamespace returned or threw.
ClientDeleteNsResultIfLogged ==
    /\ IsEvent("ClientDeleteNsResult")
    /\ IF clientPc = "DelRejected"
         THEN /\ ev.msg.result = "Failed"
              /\ ClientDeleteRejected
         ELSE /\ dnp = ev.msg.result
              /\ \E m \in Masters : ClientDeleteNsResult(m)
    /\ StepTrace

\* --- S2: RegionServers and assignment ---
RSCrashIfLogged ==
    /\ IsEvent("RSCrash")
    /\ ev.nid \in RS
    /\ RSCrash(ev.nid)
    /\ StepTrace

TrspQueueAssignIfLogged ==
    /\ IsMasterEvent("TrspQueueAssign")
    /\ ev.msg.region \in Regions
    /\ TrspQueueAssign(ev.nid, ev.msg.region)
    /\ StepTrace

\* msg.regions: model regions of the batch; msg.checked: RGU:117 was reached;
\* msg.found: every lookup returned a descriptor.
TargetCheck_AssignIfLogged ==
    /\ IsMasterEvent("TargetCheck_Assign")
    /\ LET m == ev.nid IN
       /\ assignQ[m] = ToSet(ev.msg.regions)
       /\ ev.msg.checked = (RSGroupEnabled /\ SchemaPublished(m))
       /\ ev.msg.found = (\A r \in assignQ[m] : RegionNs(r) \in cache[m])
       /\ TargetCheck_Assign(m)
       \* the plan was accepted (RGU:117 not reached, or every lookup succeeded)
       /\ (~ev.msg.checked \/ ev.msg.found) =>
            \A r \in ToSet(ev.msg.regions) : regionHost'[r] = ev.msg.host
    /\ StepTrace

TargetCheck_RsGroupRpcIfLogged ==
    /\ IsMasterEvent("TargetCheck_RsGroupRpc")
    /\ LET m == ev.nid IN
       /\ ev.msg.ns \in RpcTableNs
       /\ ev.msg.checked = SchemaPublished(m)
       /\ ev.msg.found = (ev.msg.ns \in cache[m])
       /\ TargetCheck_RsGroupRpc(m)
    /\ StepTrace

\* --- S3: QuotaObserverChore ---
QuotaObserverChoreScanIfLogged ==
    /\ IsMasterEvent("QuotaObserverChoreScan")
    /\ QuotaObserverChoreScan(ev.nid)
    /\ choreSnap'[ev.nid] = ev.state.choreSnap
    /\ StepTrace

TargetCheck_ChoreIfLogged ==
    /\ IsMasterEvent("TargetCheck_Chore")
    /\ choreSnap[ev.nid] /= <<>>
    /\ ValidateLookup(ev.nid, Head(choreSnap[ev.nid]))
    /\ TargetCheck_Chore(ev.nid)
    /\ StepTrace

(***************************************************************************)
(* Silent actions                                                          *)
(*                                                                         *)
(* When the trace has no assignment events (the AM was not instrumented),  *)
(* the workload table's region u1 is queued and planned silently.  Both    *)
(* steps fire only while the next event is the one that waits for that     *)
(* assignment (CtpFinish waits for the child TRSP; the cleanup's           *)
(* DisableTable waits for regions in transition, DTP:109), only for user   *)
(* regions, and only on the master that runs the procedure.                *)
(***************************************************************************)
SilentTrspQueueAssign ==
    /\ ~TraceHasAssignEvents
    /\ l <= Len(TraceLog)
    /\ ev.name \in {"CtpFinish", "ClientDeleteTables"}
    /\ \E m \in Masters, r \in UserRegions :
         /\ Initialized(m)
         /\ TrspQueueAssign(m, r)
    /\ UNCHANGED l

SilentTargetCheckAssign ==
    /\ ~TraceHasAssignEvents
    /\ l <= Len(TraceLog)
    /\ ev.name \in {"CtpFinish", "ClientDeleteTables"}
    /\ \E m \in Masters :
         /\ Initialized(m)
         /\ assignQ[m] \subseteq UserRegions
         /\ TargetCheck_Assign(m)
    /\ UNCHANGED l

(***************************************************************************)
(* Spec                                                                    *)
(***************************************************************************)
TraceInit ==
    /\ Init
    /\ l = 1

TraceNext ==
    \/ InitIfLogged
    \/ BecomeActiveIfLogged
    \/ WaitForMetaOnlineIfLogged
    \/ InitClusterSchemaServiceIfLogged
    \/ LoadRowIfLogged
    \/ LoadDoneIfLogged
    \/ LoadFailIfLogged
    \/ GateInitializedIfLogged
    \/ QuotaSnapshotIfLogged
    \/ TargetCheck_NsmInitIfLogged
    \/ QuotaPublishIfLogged
    \/ MasterCrashIfLogged
    \/ DnpPrepareIfLogged
    \/ DnpMetaDeleteIfLogged
    \/ DnpCacheRemoveIfLogged
    \/ DnpDeleteDirectoriesIfLogged
    \/ DnpRemoveQuotaIfLogged
    \/ DnpResendPrepareIfLogged
    \/ CnpPrepareIfLogged
    \/ CnpCreateDirectoryIfLogged
    \/ CnpMetaPutIfLogged
    \/ CnpCachePutIfLogged
    \/ CnpSetNamespaceQuotaIfLogged
    \/ CtpPrepareIfLogged
    \/ CtpPreCreateIfLogged
    \/ CtpAssignRegionsIfLogged
    \/ CtpFinishIfLogged
    \/ ClientStartIfLogged
    \/ ClientCreateNamespaceIfLogged
    \/ ClientCreateNsResultIfLogged
    \/ ClientSetSpaceQuotaIfLogged
    \/ TargetCheck_ClientGetIfLogged
    \/ TargetCheck_ClientCreateTableIfLogged
    \/ ClientCreateTableResultIfLogged
    \/ ClientDeleteTablesIfLogged
    \/ ClientDeleteNamespaceIfLogged
    \/ HookPostDeleteNamespaceIfLogged
    \/ ClientDeleteNsResultIfLogged
    \/ RSCrashIfLogged
    \/ TrspQueueAssignIfLogged
    \/ TargetCheck_AssignIfLogged
    \/ TargetCheck_RsGroupRpcIfLogged
    \/ QuotaObserverChoreScanIfLogged
    \/ TargetCheck_ChoreIfLogged
    \* silent (no trace line consumed)
    \/ SilentTrspQueueAssign
    \/ SilentTargetCheckAssign

TraceSpec == TraceInit /\ [][TraceNext]_<<l, vars>> /\ WF_<<l, vars>>(TraceNext)

TraceView == <<vars, l>>

TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l        |-> l,
      len      |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN ev.name ELSE "DONE",
      nid      |-> IF l <= Len(TraceLog) THEN ev.nid ELSE "DONE",
      tState   |-> IF l <= Len(TraceLog) /\ "state" \in DOMAIN ev THEN ev.state ELSE "DONE",
      tMsg     |-> IF l <= Len(TraceLog) /\ "msg" \in DOMAIN ev THEN ev.msg ELSE "DONE",
      phase    |-> phase,
      cache    |-> cache,
      metaNs   |-> metaNs,
      nsmSnap  |-> nsmSnap,
      nsmIdx   |-> nsmIdx,
      dnp      |-> dnp,
      cnp      |-> cnp,
      ctp      |-> ctp,
      clientPc |-> clientPc,
      ctRound  |-> ctRound,
      assignQ  |-> assignQ,
      regions  |-> regionState,
      fired    |-> targetFired ]

=============================================================================
