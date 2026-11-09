--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hbase-adhoc-08).                   *)
(*                                                                         *)
(* Counter-bounded (they introduce non-determinism):                       *)
(*   MasterCrash                  -- MaxMasterCrash   (S1, S2, S3)         *)
(*   RSCrash                      -- MaxRSCrash       (S2)                 *)
(*   ClientResendDeleteNamespace  -- MaxClientResend  (S1, S3)             *)
(* Unbounded (react to existing state): master activation milestones,      *)
(* procedure steps, client steps, AM assignment, the quota chore, and all  *)
(* TargetCheck_* actions.                                                  *)
(*                                                                         *)
(* Workload toggles (QuotaEnabled, RSGroupEnabled, SpaceQuotaNs,           *)
(* RsGroupRpcClient, UserRegions, CreateTableRounds) are base constants    *)
(* set per config.                                                         *)
(***************************************************************************)
EXTENDS base, TLC

CONSTANTS
    MaxMasterCrash,    \* active-master crash/stop events
    MaxRSCrash,        \* RegionServer crash events
    MaxClientResend    \* deleteNamespace resends after the handler's master died

VARIABLE faultCounters

faultVars == <<faultCounters>>
mc_vars   == <<vars, faultVars>>

(***************************************************************************)
(* Counter-bounded wrappers                                                *)
(***************************************************************************)
MCMasterCrash(m) ==
    /\ ~targetFired
    /\ faultCounters.masterCrash < MaxMasterCrash
    /\ MasterCrash(m)
    /\ faultCounters' = [faultCounters EXCEPT !.masterCrash = @ + 1]

MCRSCrash(x) ==
    /\ ~targetFired
    /\ faultCounters.rsCrash < MaxRSCrash
    /\ RSCrash(x)
    /\ faultCounters' = [faultCounters EXCEPT !.rsCrash = @ + 1]

MCClientResendDeleteNamespace(m) ==
    /\ ~targetFired
    /\ faultCounters.clientResend < MaxClientResend
    /\ ClientResendDeleteNamespace(m)
    /\ faultCounters' = [faultCounters EXCEPT !.clientResend = @ + 1]

(***************************************************************************)
(* Reactive wrappers.  Each base action gets its own guarded wrapper so    *)
(* that TLC names the step in counterexamples; once the target has fired  *)
(* every action stops (tla-patterns.md 1).  Keep in sync with base Next.   *)
(***************************************************************************)
MCClientStart == ~targetFired /\ ClientStart /\ UNCHANGED faultVars
MCBecomeActive(m) == ~targetFired /\ BecomeActive(m) /\ UNCHANGED faultVars
MCWaitForMetaOnline(m) == ~targetFired /\ WaitForMetaOnline(m) /\ UNCHANGED faultVars
MCInitClusterSchemaService(m) == ~targetFired /\ InitClusterSchemaService(m) /\ UNCHANGED faultVars
MCLoadRow(m) == ~targetFired /\ LoadRow(m) /\ UNCHANGED faultVars
MCLoadDone(m) == ~targetFired /\ LoadDone(m) /\ UNCHANGED faultVars
MCLoadFail(m) == ~targetFired /\ LoadFail(m) /\ UNCHANGED faultVars
MCGateInitialized(m) == ~targetFired /\ GateInitialized(m) /\ UNCHANGED faultVars
MCQuotaSnapshot(m) == ~targetFired /\ QuotaSnapshot(m) /\ UNCHANGED faultVars
MCTargetCheck_NsmInit(m) == ~targetFired /\ TargetCheck_NsmInit(m) /\ UNCHANGED faultVars
MCQuotaPublish(m) == ~targetFired /\ QuotaPublish(m) /\ UNCHANGED faultVars
MCDnpPrepare(m) == ~targetFired /\ DnpPrepare(m) /\ UNCHANGED faultVars
MCDnpMetaDelete(m) == ~targetFired /\ DnpMetaDelete(m) /\ UNCHANGED faultVars
MCDnpCacheRemove(m) == ~targetFired /\ DnpCacheRemove(m) /\ UNCHANGED faultVars
MCDnpDeleteDirectories(m) == ~targetFired /\ DnpDeleteDirectories(m) /\ UNCHANGED faultVars
MCDnpRemoveQuota(m) == ~targetFired /\ DnpRemoveQuota(m) /\ UNCHANGED faultVars
MCDnpResendPrepare(m) == ~targetFired /\ DnpResendPrepare(m) /\ UNCHANGED faultVars
MCClientDeleteRejected == ~targetFired /\ ClientDeleteRejected /\ UNCHANGED faultVars
MCCnpPrepare(m) == ~targetFired /\ CnpPrepare(m) /\ UNCHANGED faultVars
MCCnpCreateDirectory(m) == ~targetFired /\ CnpCreateDirectory(m) /\ UNCHANGED faultVars
MCCnpMetaPut(m) == ~targetFired /\ CnpMetaPut(m) /\ UNCHANGED faultVars
MCCnpCachePut(m) == ~targetFired /\ CnpCachePut(m) /\ UNCHANGED faultVars
MCCnpSetNamespaceQuota(m) == ~targetFired /\ CnpSetNamespaceQuota(m) /\ UNCHANGED faultVars
MCCtpPrepare(m) == ~targetFired /\ CtpPrepare(m) /\ UNCHANGED faultVars
MCCtpPreCreate(m) == ~targetFired /\ CtpPreCreate(m) /\ UNCHANGED faultVars
MCCtpAssignRegions(m) == ~targetFired /\ CtpAssignRegions(m) /\ UNCHANGED faultVars
MCCtpFinish(m) == ~targetFired /\ CtpFinish(m) /\ UNCHANGED faultVars
MCClientCreateNamespace(m) == ~targetFired /\ ClientCreateNamespace(m) /\ UNCHANGED faultVars
MCClientCreateNsResult(m) == ~targetFired /\ ClientCreateNsResult(m) /\ UNCHANGED faultVars
MCClientSetSpaceQuota(m) == ~targetFired /\ ClientSetSpaceQuota(m) /\ UNCHANGED faultVars
MCTargetCheck_ClientGet(m) == ~targetFired /\ TargetCheck_ClientGet(m) /\ UNCHANGED faultVars
MCTargetCheck_ClientCreateTable(m) == ~targetFired /\ TargetCheck_ClientCreateTable(m) /\ UNCHANGED faultVars
MCClientCreateTableResult(m) == ~targetFired /\ ClientCreateTableResult(m) /\ UNCHANGED faultVars
MCClientDeleteTables(m) == ~targetFired /\ ClientDeleteTables(m) /\ UNCHANGED faultVars
MCClientDeleteNamespace(m) == ~targetFired /\ ClientDeleteNamespace(m) /\ UNCHANGED faultVars
MCHookPostDeleteNamespace(m) == ~targetFired /\ HookPostDeleteNamespace(m) /\ UNCHANGED faultVars
MCClientDeleteNsResult(m) == ~targetFired /\ ClientDeleteNsResult(m) /\ UNCHANGED faultVars
MCTargetCheck_Assign(m) == ~targetFired /\ TargetCheck_Assign(m) /\ UNCHANGED faultVars
MCTargetCheck_RsGroupRpc(m) == ~targetFired /\ TargetCheck_RsGroupRpc(m) /\ UNCHANGED faultVars
MCQuotaObserverChoreScan(m) == ~targetFired /\ QuotaObserverChoreScan(m) /\ UNCHANGED faultVars
MCTargetCheck_Chore(m) == ~targetFired /\ TargetCheck_Chore(m) /\ UNCHANGED faultVars
MCTrspQueueAssign(m, r) == ~targetFired /\ TrspQueueAssign(m, r) /\ UNCHANGED faultVars

(***************************************************************************)
(* Init / Next                                                             *)
(***************************************************************************)
MCInit ==
    /\ Init
    /\ faultCounters = [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0]

MCNext ==
    \/ MCClientStart
    \/ MCClientDeleteRejected
    \/ \E m \in Masters :
         \/ MCBecomeActive(m)
         \/ MCWaitForMetaOnline(m)
         \/ MCInitClusterSchemaService(m)
         \/ MCLoadRow(m)
         \/ MCLoadDone(m)
         \/ MCLoadFail(m)
         \/ MCGateInitialized(m)
         \/ MCQuotaSnapshot(m)
         \/ MCTargetCheck_NsmInit(m)
         \/ MCQuotaPublish(m)
         \/ MCDnpPrepare(m)
         \/ MCDnpMetaDelete(m)
         \/ MCDnpCacheRemove(m)
         \/ MCDnpDeleteDirectories(m)
         \/ MCDnpRemoveQuota(m)
         \/ MCDnpResendPrepare(m)
         \/ MCCnpPrepare(m)
         \/ MCCnpCreateDirectory(m)
         \/ MCCnpMetaPut(m)
         \/ MCCnpCachePut(m)
         \/ MCCnpSetNamespaceQuota(m)
         \/ MCCtpPrepare(m)
         \/ MCCtpPreCreate(m)
         \/ MCCtpAssignRegions(m)
         \/ MCCtpFinish(m)
         \/ MCClientCreateNamespace(m)
         \/ MCClientCreateNsResult(m)
         \/ MCClientSetSpaceQuota(m)
         \/ MCTargetCheck_ClientGet(m)
         \/ MCTargetCheck_ClientCreateTable(m)
         \/ MCClientCreateTableResult(m)
         \/ MCClientDeleteTables(m)
         \/ MCClientDeleteNamespace(m)
         \/ MCHookPostDeleteNamespace(m)
         \/ MCClientDeleteNsResult(m)
         \/ MCTargetCheck_Assign(m)
         \/ MCTargetCheck_RsGroupRpc(m)
         \/ MCQuotaObserverChoreScan(m)
         \/ MCTargetCheck_Chore(m)
         \/ \E r \in Regions : MCTrspQueueAssign(m, r)
    \/ \E m \in Masters : MCMasterCrash(m)
    \/ \E x \in RS : MCRSCrash(x)
    \/ \E m \in Masters : MCClientResendDeleteNamespace(m)

MCSpec == MCInit /\ [][MCNext]_mc_vars

\* Masters are interchangeable (both start as backups).  The fault counters
\* stay in the state (no VIEW): merging states that differ only in the
\* remaining fault budget would drop behaviors.
Symmetry == Permutations(Masters)

(***************************************************************************)
(* Optional state constraints for the isolating hunt variants.  They prune *)
(* the paths of another mechanism so that a variant reports only its own;  *)
(* the main MC_hunt_S<n>.cfg files use none of them.                       *)
(***************************************************************************)
\* S1(a) path: the next NSM:227 lookup of a snapshot entry would fail.
ExcludeNsmInitRace ==
    \A m \in Masters :
        (phase[m] = "QuotaInit" /\ nsmIdx[m] <= Len(nsmSnap[m]))
            => nsmSnap[m][nsmIdx[m]] \in cache[m]

\* S1(b) path: the DNP failed (DNP:261 NPE before HM:1624).
ExcludeDnpQuotaNpe == dnp /= "Failed"

\* The createNamespace NPE (CNP:203, T-3) is not on the path: the workload's own
\* create and tables finished, and the delete is what overlaps the failover.
ExcludeCnpQuotaNpe == cnp /= "Failed"

\* A client read after a reported failure does not fail: it runs before the DNP
\* removed nsp.  Later chore lookups are unaffected.
ExcludeClientReadFail ==
    clientPc = "ReadAfterFail" => \A m \in Masters : Initialized(m) => NSP \in cache[m]

\* The deleteNamespace post hook can no longer run: it ran, its master died, or
\* the live handler serves the resend, whose DNP fails before the hook (HM:3697).
HookSettled == rpcHandler.m = None \/ phase[rpcHandler.m] = "Down" \/ rpcHandler.st = "ResendLatch"

\* S3 persistent mechanism only: a chore scan happens only after the DNP has
\* finished and the post hook (HM:3698) can no longer remove the SPACE row.
ChoreAfterDeleteSettled ==
    \A m \in Masters : choreSnap[m] /= <<>> => (dnp \in {"Success", "Failed"} /\ HookSettled)

(***************************************************************************)
(* Sanity predicates (tla-patterns.md 2).  Each Reach* holds in a state    *)
(* where a code path that evaluates CSSI:110-111 is enabled.  The          *)
(* TargetReached* invariants are temporary: TLC must VIOLATE each one that *)
(* the configuration can reach (fault-free workload: NsmInit, ClientGet,   *)
(* CreateTable, CtpPrepare, CtpPreCreate, DnpPrepare).                     *)
(***************************************************************************)
ReachNsmInit     == \E m \in Masters : phase[m] = "QuotaInit" /\ nsmIdx[m] <= Len(nsmSnap[m])
ReachClientGet   == \E m \in Masters : clientPc \in {"GetNs", "ReadAfterFail"} /\ Initialized(m)
ReachCreateTable == \E m \in Masters : clientPc = "CreateTable" /\ Initialized(m)
ReachCtpPrepare  == \E m \in Masters : ctp = "Prepare" /\ ctpSub = "Idle" /\ ProcRunnable(m)
ReachCtpPreCreate ==
    \E m \in Masters : /\ ctp = "Prepare" /\ ctpSub = "PrepDone"
                       /\ QuotaManagerPublished(m) /\ QuotaEnabled
ReachDnpPrepare  == \E m \in Masters : dnp = "Prepare" /\ ProcRunnable(m) /\ NSP \in cache[m]
ReachAssign ==
    \E m \in Masters : /\ IsActive(m) /\ assignQ[m] /= {} /\ AliveRS /= {}
                       /\ RSGroupEnabled /\ SchemaPublished(m)
ReachRsGroupRpc ==
    \E m \in Masters : /\ RsGroupRpcClient /\ RSGroupEnabled /\ clientPc /= "Boot"
                       /\ IsActive(m) /\ SchemaPublished(m) /\ RpcTableNs /= {}
ReachChore == \E m \in Masters : QuotaManagerPublished(m) /\ choreSnap[m] /= <<>>

ReachAnySite ==
    \/ ReachNsmInit \/ ReachClientGet \/ ReachCreateTable \/ ReachCtpPrepare
    \/ ReachCtpPreCreate \/ ReachDnpPrepare \/ ReachAssign \/ ReachRsGroupRpc \/ ReachChore

TargetReached              == ~ReachAnySite
TargetReached_NsmInit      == ~ReachNsmInit
TargetReached_ClientGet    == ~ReachClientGet
TargetReached_CreateTable  == ~ReachCreateTable
TargetReached_CtpPrepare   == ~ReachCtpPrepare
TargetReached_CtpPreCreate == ~ReachCtpPreCreate
TargetReached_DnpPrepare   == ~ReachDnpPrepare
TargetReached_Assign       == ~ReachAssign
TargetReached_RsGroupRpc   == ~ReachRsGroupRpc
TargetReached_Chore        == ~ReachChore

\* Scenario windows (temporary, used by the smoke runs).  Each one is a state a
\* Scenario needs just before its lookup, stated without the guard, so violating
\* it shows the hunt's bounds open the window; it says nothing about TargetSafe.
\* S1(a): the quota snapshot loop runs while a DNP has not yet removed nsp.
TargetReached_S1aWindow ==
    ~\E m \in Masters : /\ phase[m] = "QuotaInit" /\ nsmIdx[m] <= Len(nsmSnap[m])
                        /\ dnp \in {"Prepare", "DelNsTable"}
\* S1(b): the client was told the delete failed and is about to read nsp.
TargetReached_S1bWindow ==
    ~\E m \in Masters : clientPc = "ReadAfterFail" /\ Initialized(m)
\* S2: an ungated reader runs while the cache load is unfinished.
TargetReached_S2AssignWindow ==
    ~\E m \in Masters : ReachAssign /\ phase[m] = "Loading" /\ assignQ[m] /= {}
TargetReached_S2RpcWindow ==
    ~\E m \in Masters : ReachRsGroupRpc /\ phase[m] = "Loading"
\* S3: a SPACE row is present once the DNP has passed DELETE_FROM_NS_TABLE.
TargetReached_S3Window ==
    ~\E m \in Masters : /\ QuotaManagerPublished(m) /\ spaceQuotaNs /= {}
                        /\ dnp \in {"DelDirs", "RemoveQuota", "Success", "Failed"}

\* Sanity: the fault-free workload runs to the end of the cleanup.
WorkloadNotDone == clientPc /= "Done"

\* Sanity: every MC step is a step of the base specification (the wrappers add
\* only the counters and the stop-after-firing guard).
BaseNextRefined == [][Next]_vars

=============================================================================
