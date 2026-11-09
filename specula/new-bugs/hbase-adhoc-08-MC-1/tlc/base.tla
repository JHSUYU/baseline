-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* Ad hoc coordination target hbase-adhoc-08 (Apache HBase, pinned tree    *)
(* 1790942bb2).                                                            *)
(*                                                                         *)
(* Target check:                                                           *)
(*   ClusterSchemaServiceImpl.getNamespace(String), CSSI:109-113           *)
(*     NamespaceDescriptor nsd = getTableNamespaceManager().get(name);     *)
(*     if (nsd == null) throw new NamespaceNotFoundException(name);  // :111*)
(*   phi_T(m, n) == n \notin cache[m]   (TNM:185-187, ConcurrentHashMap    *)
(*   without null values, TNM:65)                                          *)
(*                                                                         *)
(* Category A (distributed): the guard reads the active master's in-memory *)
(* projection (TNM.cache) of the ns rows of hbase:meta.  Faults: active    *)
(* master crash/stop with procedure-store replay, RegionServer crash.      *)
(*                                                                         *)
(* Every TargetCheck_* action (and the CTP/DNP steps that embed a lookup)  *)
(* evaluates the guard exactly as the call site does and sets              *)
(* targetFired when CSSI:111 throws, even where a caller later catches the *)
(* exception (NSM:143-146, AM:945-949, AM:2619-2636, QOC:136-137).         *)
(*                                                                         *)
(* Source abbreviations.  Unless prefixed, paths are under                 *)
(* hbase-server/src/main/java/org/apache/hadoop/hbase/.                    *)
(*   CSSI  master/ClusterSchemaServiceImpl.java                            *)
(*   TNM   master/TableNamespaceManager.java                               *)
(*   HM    master/HMaster.java                                             *)
(*   MRS   master/MasterRpcServices.java                                   *)
(*   NSM   namespace/NamespaceStateManager.java                            *)
(*   NA    namespace/NamespaceAuditor.java                                 *)
(*   MQM   quotas/MasterQuotaManager.java                                  *)
(*   MQO   quotas/MasterQuotasObserver.java                                *)
(*   QOC   quotas/QuotaObserverChore.java                                  *)
(*   DNP   master/procedure/DeleteNamespaceProcedure.java                  *)
(*   CNP   master/procedure/CreateNamespaceProcedure.java                  *)
(*   CTP   master/procedure/CreateTableProcedure.java                      *)
(*   DTP   master/procedure/DeleteTableProcedure.java                      *)
(*   ASMNP master/procedure/AbstractStateMachineNamespaceProcedure.java    *)
(*   MPU   master/procedure/MasterProcedureUtil.java                       *)
(*   PSW   master/procedure/ProcedureSyncWait.java                         *)
(*   SCP   master/procedure/ServerCrashProcedure.java                      *)
(*   AM    master/assignment/AssignmentManager.java                        *)
(*   TRSP  master/assignment/TransitRegionStateProcedure.java              *)
(*   RGU   rsgroup/RSGroupUtil.java                                        *)
(*   RGLB  rsgroup/RSGroupBasedLoadBalancer.java                           *)
(*   RGIM  rsgroup/RSGroupInfoManagerImpl.java                             *)
(*   DRGM  rsgroup/DisabledRSGroupInfoManager.java                         *)
(*   PE    hbase-procedure/.../procedure2/ProcedureExecutor.java           *)
(*   Proc  hbase-procedure/.../procedure2/Procedure.java                   *)
(*   SMP   hbase-procedure/.../procedure2/StateMachineProcedure.java       *)
(*   TNA   hbase-server/src/test/.../namespace/TestNamespaceAuditor.java   *)
(*                                                                         *)
(* Scenarios (modeling-brief.md section 2):                                *)
(*   S1 DNP overlaps quota-subsystem initialization after failover         *)
(*      (a) NSM:224 snapshot -> DNP removes nsp -> NSM:227 lookup          *)
(*      (b) DNP:261 NPE before HM:1624 -> delete reported failed -> read   *)
(*   S2 schema service published (HM:1610) before its cache is loaded,     *)
(*      read by ungated threads through RGU:117 (rsgroup enabled)          *)
(*   S3 a namespace SPACE quota row outlives the namespace; the            *)
(*      QuotaObserverChore resolves it (QOC:490)                           *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Masters,           \* HMaster instances (TNA:112 numMasters(2))
    RS,                \* RegionServers
    None,              \* null marker
    NSP,               \* workload namespace "TestNamespaceAuditor_np2" (TNA:140)
    DEFAULT_NS,        \* "default"
    HBASE_NS,          \* "hbase"
    UserRegions,       \* regions of the workload's first table (TNA:150-159), namespace NSP; {} drops them
    MetaInitHost,      \* RegionServer hosting hbase:meta at Init
    QuotaEnabled,      \* hbase.quota.enabled (TNA:109); MQM:96-99, HM:1336, HM:4658-4664
    RSGroupEnabled,    \* hbase.balancer.rsgroup.enabled (RGU:49-55); S2 workload variant
    SpaceQuotaNs,      \* S3 workload variant: namespaces given a SPACE quota right after they are created
    RsGroupRpcClient,  \* S2 workload variant: an extra admin client calling getRSGroupInfoOfTable
    RpcTableNs,        \* namespaces of the existing tables that client queries (meta -> HBASE_NS)
    CreateTableRounds, \* createTable calls of the workload (TNA:159, 162, 170, 177)
    CtRejected         \* rounds rejected by the namespace quota (TNA:162 regions, TNA:177 tables)

\* Row-key / name order of the three namespaces.  Meta rows are read in byte
\* order (TNM:109-117); getNamespaces() sorts by name (CSSI:118-120,
\* hbase-common NamespaceDescriptor.java:72-79).  "TestNamespaceAuditor_np2" <
\* "default" < "hbase" because 'T' (0x54) < 'd' (0x64) < 'h' (0x68).
NsSeq == <<NSP, DEFAULT_NS, HBASE_NS>>
NS    == {NSP, DEFAULT_NS, HBASE_NS}

MetaRegion == "meta"
Regions    == {MetaRegion} \cup UserRegions
RegionNs(r) == IF r = MetaRegion THEN HBASE_NS ELSE NSP

ASSUME /\ Cardinality(NS) = 3
       /\ MetaInitHost \in RS
       /\ MetaRegion \notin UserRegions
       /\ None \notin Masters \cup RS
       /\ SpaceQuotaNs \subseteq {NSP}
       /\ RpcTableNs \subseteq NS
       /\ CreateTableRounds \in Nat
       /\ CtRejected \subseteq 1..CreateTableRounds
       /\ QuotaEnabled \in BOOLEAN /\ RSGroupEnabled \in BOOLEAN /\ RsGroupRpcClient \in BOOLEAN

(***************************************************************************)
(* Variables                                                               *)
(***************************************************************************)
VARIABLES
    \* --- per master, volatile (lost when the master dies) ---
    phase,        \* HMaster activation milestone (HM:979-1380), "Down" after a crash or abort
    cache,        \* keys of TNM.cache of the master's ClusterSchemaServiceImpl (TNM:65); phi_T operand
    nsmSnap,      \* S1: NamespaceStateManager.initialize snapshot (NSM:224)
    nsmIdx,       \* S1: next index of the NSM:225 loop
    assignQ,      \* S2: AssignmentManager.pendingAssignQueue (AM:2444-2460)
    choreSnap,    \* S3: SPACE-quota namespaces read by the running QuotaObserverChore scan (QOC:478-486)
    \* --- durable state ---
    metaNs,       \* rows of the ns family of hbase:meta (TNM:201-219); source of the cache
    dnp,          \* DeleteNamespaceProcedure state persisted in the procedure store
    cnp,          \* CreateNamespaceProcedure state persisted in the procedure store
    ctp,          \* CreateTableProcedure (current workload round) persisted state
    spaceQuotaNs, \* S3: namespaces with a SPACE quota row in hbase:quota
    rsAlive,      \* S2: RegionServer liveness
    regionState,  \* S2: "Absent" | "Open" | "Rit" (region in transition: TRSP/SCP pending)
    regionHost,   \* S2: RegionServer hosting an open region
    \* --- volatile progress inside one procedure step on the active master ---
    dnpSub,       \* DELETE_FROM_NS_TABLE split: meta Delete (TNM:214-216) then cache.remove (TNM:218)
    cnpSub,       \* INSERT_INTO_NS_TABLE split: meta Put (TNM:197) then cache.put (TNM:198)
    ctpSub,       \* CTP PRE_OPERATION split: prepareCreate (CTP:316) then preCreate (CTP:334-338)
    \* --- workload client and its in-flight deleteNamespace RPC ---
    clientPc,     \* TNA:138-185 then @AfterEach cleanup TNA:123-136
    ctRound,      \* createTable round
    rpcHandler,   \* deleteNamespace RPC handler (HM:3678-3706): master and latch status
    \* --- target ---
    targetFired   \* CSSI:111 has thrown

masterVars == <<phase, cache, nsmSnap, nsmIdx, assignQ, choreSnap>>
procVars   == <<dnp, dnpSub, cnp, cnpSub, ctp, ctpSub>>
envVars    == <<metaNs, spaceQuotaNs, rsAlive, regionState, regionHost>>
clientVars == <<clientPc, ctRound, rpcHandler>>
vars       == <<masterVars, procVars, envVars, clientVars, targetFired>>

Phases == {"Backup", "Workers", "MetaLoaded", "Loading", "Loaded",
           "Initialized", "QuotaInit", "Running", "Down"}
DnpStates == {"None", "Prepare", "DelNsTable", "DelDirs", "RemoveQuota", "Success", "Failed"}
CnpStates == {"None", "Prepare", "CreateDir", "Insert", "SetQuota", "Success", "Failed"}
CtpStates == {"None", "Prepare", "Assign", "WaitChildren", "Success", "Rejected"}
ClientPcs == {"Boot", "CreateNs", "CreateNsWait", "SetSpaceQuota", "GetNs", "CreateTable",
              "CreateTableWait", "DeleteTables", "DelSend", "DelInRpc", "DelWait",
              "DelRejected", "ReadAfterFail", "Done"}
NoHandler == [m |-> None, st |-> "None"]

(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
Alive(m)    == phase[m] /= "Down"
IsActive(m) == phase[m] \notin {"Backup", "Down"}
NoActiveMaster == \A x \in Masters : ~IsActive(x)

\* HM:1148 startServiceThreads -> procedure workers (HM:1732), serviceStarted (HM:1817)
WorkersStarted(m) == phase[m] \in {"Workers", "MetaLoaded", "Loading", "Loaded",
                                   "Initialized", "QuotaInit", "Running"}
\* HM:1194 wakeMetaLoadedEvent
MetaLoadedEv(m) == phase[m] \in {"MetaLoaded", "Loading", "Loaded",
                                 "Initialized", "QuotaInit", "Running"}
\* HM:1610 clusterSchemaService assigned: getClusterSchema() /= null (HM:3589)
SchemaPublished(m) == phase[m] \in {"Loading", "Loaded", "Initialized", "QuotaInit", "Running"}
\* HM:1300 setInitialized(true); checkInitialized (HM:3424-3433) passes
Initialized(m) == phase[m] \in {"Initialized", "QuotaInit", "Running"}
\* HM:1624 quotaManager published; getMasterQuotaManager() (HM:3327-3329) /= null
QuotaManagerPublished(m) == phase[m] = "Running"
\* Initialized-gated procedures (ASMNP:73-76, CTP:266-276, Proc:1021-1024) run on the
\* active master only after HM:1300.
ProcRunnable(m) == Initialized(m)

MetaOnline == regionState[MetaRegion] = "Open"
AliveRS    == {x \in RS : rsAlive[x]}

SortedNs(S) == SelectSeq(NsSeq, LAMBDA n : n \in S)
\* TNM:111-116: the scanner returns the next meta row after the last one loaded.
\* Meta's ns family has no writer while the cache loads (every writer is an
\* initialized-gated procedure), so the next row is the least row not yet cached.
NextRow(m) == Head(SortedNs(metaNs \ cache[m]))

\* Regions created by the CTP of round k (only the first table is tracked)
CtpRegions(k) == IF k = 1 THEN UserRegions ELSE {}

(***************************************************************************)
(* Init: the cluster after InitMetaProcedure (HM:1109-1128, 1150-1155),    *)
(* before any master has loaded its cache.  meta holds default and hbase  *)
(* (brief 3.2: InitMeta is not modeled).                                   *)
(***************************************************************************)
Init ==
    /\ phase        = [m \in Masters |-> "Backup"]
    /\ cache        = [m \in Masters |-> {}]
    /\ nsmSnap      = [m \in Masters |-> <<>>]
    /\ nsmIdx       = [m \in Masters |-> 1]
    /\ assignQ      = [m \in Masters |-> {}]
    /\ choreSnap    = [m \in Masters |-> <<>>]
    /\ metaNs       = {DEFAULT_NS, HBASE_NS}
    /\ dnp          = "None"
    /\ cnp          = "None"
    /\ ctp          = "None"
    /\ spaceQuotaNs = {}
    /\ rsAlive      = [x \in RS |-> TRUE]
    /\ regionState  = [r \in Regions |-> IF r = MetaRegion THEN "Open" ELSE "Absent"]
    /\ regionHost   = [r \in Regions |-> IF r = MetaRegion THEN MetaInitHost ELSE None]
    /\ dnpSub       = "Idle"
    /\ cnpSub       = "Idle"
    /\ ctpSub       = "Idle"
    /\ clientPc     = "Boot"
    /\ ctRound      = 1
    /\ rpcHandler   = NoHandler
    /\ targetFired  = FALSE

(***************************************************************************)
(* Master activation: HMaster.run -> finishActiveMasterInitialization      *)
(***************************************************************************)

\* HM:2597-2615, HM:979-1148.  The backup wins the active-master znode
\* (HM:2614) once no master is active, then runs initialization up to
\* startServiceThreads (HM:1148):
\*   HM:1044-1046 createProcedureExecutor loads persisted procedures (dnp, cnp,
\*                ctp, the TRSPs/SCPs behind regionState = "Rit");
\*   HM:1049-1058 AM.start (assign thread, AM:313-321), setupRIT;
\*   HM:1066-1071 SCPs scheduled for dead servers;
\*   HM:1148 -> HM:1732 procedure workers start, HM:1817 serviceStarted.
\* Nothing between these points reads the cache (clusterSchemaService is
\* still null, HM:350), so they form one step.
BecomeActive(m) ==
    /\ phase[m] = "Backup"
    /\ NoActiveMaster
    /\ phase' = [phase EXCEPT ![m] = "Workers"]
    /\ UNCHANGED <<cache, nsmSnap, nsmIdx, assignQ, choreSnap, procVars, envVars,
                   clientVars, targetFired>>

\* HM:1172-1194: waitForMetaOnline (HM:1179) blocks until meta is online, then
\* joinCluster / processOfflineRegions / wakeMetaLoadedEvent (HM:1189-1194).
WaitForMetaOnline(m) ==
    /\ phase[m] = "Workers"
    /\ MetaOnline                                            \* HM:1179
    /\ phase' = [phase EXCEPT ![m] = "MetaLoaded"]           \* HM:1194
    /\ UNCHANGED <<cache, nsmSnap, nsmIdx, assignQ, choreSnap, procVars, envVars,
                   clientVars, targetFired>>

\* HM:1257-1262 -> initClusterSchemaService HM:1609-1611.
\*   HM:1257 waitForNamespaceOnline: true on a 3.x meta (migration only).
\*   HM:1610 the field clusterSchemaService (HM:350) is assigned: from here
\*           getClusterSchema() /= null although the cache is empty (S2).
\*   HM:1611 startAsync -> CSSI:58-61 doStart: notifyStarted() (CSSI:60) is
\*           called BEFORE tableNamespaceManager.start() (CSSI:61).
\*   TNM:173-175 start: tryMigrateNamespaceTable finds the ns family in meta
\*           and sets migrationDone (TNM:79-85); loadFromMeta follows (LoadRow).
InitClusterSchemaService(m) ==
    /\ phase[m] = "MetaLoaded"
    /\ phase' = [phase EXCEPT ![m] = "Loading"]
    /\ cache' = [cache EXCEPT ![m] = {}]                     \* new TNM, empty map (TNM:65)
    /\ UNCHANGED <<nsmSnap, nsmIdx, assignQ, choreSnap, procVars, envVars,
                   clientVars, targetFired>>

\* TNM:108-117 loadFromMeta, one scanner row per step.
LoadRow(m) ==
    /\ phase[m] = "Loading"
    /\ MetaOnline                                            \* TNM:109-110 scan of hbase:meta
    /\ metaNs \ cache[m] /= {}                               \* TNM:112-115 result /= null
    /\ cache' = [cache EXCEPT ![m] = @ \cup {NextRow(m)}]    \* TNM:116 -> TNM:100-105 cache.put
    /\ UNCHANGED <<phase, nsmSnap, nsmIdx, assignQ, choreSnap, procVars, envVars,
                   clientVars, targetFired>>

\* TNM:113-114 result == null -> break; TNM.start and CSSI:61 return;
\* HM:1612-1618 awaitRunning returns normally.
LoadDone(m) ==
    /\ phase[m] = "Loading"
    /\ MetaOnline
    /\ metaNs \subseteq cache[m]                             \* no row left: scanner.next() == null
    /\ phase' = [phase EXCEPT ![m] = "Loaded"]
    /\ UNCHANGED <<cache, nsmSnap, nsmIdx, assignQ, choreSnap, procVars, envVars,
                   clientVars, targetFired>>

\* Effect of a master process dying (crash, stop, abort).  All volatile state
\* of the master is lost, including the in-step progress of procedures, which
\* only the active master executes.  An RPC handler living on m dies with it
\* (rpcHandler keeps its record; the client sees the dead master).
MasterDies(m) ==
    /\ phase'     = [phase EXCEPT ![m] = "Down"]
    /\ cache'     = [cache EXCEPT ![m] = {}]
    /\ nsmSnap'   = [nsmSnap EXCEPT ![m] = <<>>]
    /\ nsmIdx'    = [nsmIdx EXCEPT ![m] = 1]
    /\ assignQ'   = [assignQ EXCEPT ![m] = {}]
    /\ choreSnap' = [choreSnap EXCEPT ![m] = <<>>]
    /\ dnpSub' = "Idle"
    /\ cnpSub' = "Idle"
    /\ ctpSub' = "Idle"

\* S2: the meta scan fails while meta is offline: TNM:109-112 IOException ->
\* CSSI:62-63 notifyFailed -> HM:1613-1615 awaitRunning throws
\* IllegalStateException -> HM:1263-1272 rethrown (not the HBase 1->2 upgrade
\* case) -> HM:2617-2630 abort.
LoadFail(m) ==
    /\ phase[m] = "Loading"
    /\ ~MetaOnline
    /\ MasterDies(m)
    /\ UNCHANGED <<metaNs, spaceQuotaNs, rsAlive, regionState, regionHost,
                   dnp, cnp, ctp, clientVars, targetFired>>

\* HM:1275-1300: preMasterInitialization hook, observers registered, then
\* HM:1300 setInitialized(true).  Opens checkInitialized (HM:3424-3433) and
\* every initialized-gated procedure (ASMNP:73-76; Proc:1021-1024 checks the
\* gate before any lock shortcut).
GateInitialized(m) ==
    /\ phase[m] = "Loaded"
    /\ phase' = [phase EXCEPT ![m] = "Initialized"]          \* HM:1300
    /\ UNCHANGED <<cache, nsmSnap, nsmIdx, assignQ, choreSnap, procVars, envVars,
                   clientVars, targetFired>>

\* S1: HM:1333-1335 -> initQuotaManager HM:1621-1623 -> MQM.start (MQM:95-116)
\* -> NA.start (NA:48-49) -> NSM.start (NSM:59-61) -> NSM.initialize:
\* NSM:224 snapshots getNamespaces() = CSSI:116-120 (checkIsRunning passes;
\* list of the cache sorted by name).
QuotaSnapshot(m) ==
    /\ phase[m] = "Initialized"
    /\ IF QuotaEnabled
         THEN \* MQM:102-115 quota table ensured, NamespaceAuditor started
              /\ phase'   = [phase EXCEPT ![m] = "QuotaInit"]
              /\ nsmSnap' = [nsmSnap EXCEPT ![m] = SortedNs(cache[m])]   \* NSM:224
              /\ nsmIdx'  = [nsmIdx EXCEPT ![m] = 1]                     \* NSM:225
         ELSE \* MQM:96-99 quota disabled: start() returns; HM:1624 publishes;
              \* HM:1336 skips the quota chores
              /\ phase' = [phase EXCEPT ![m] = "Running"]
              /\ UNCHANGED <<nsmSnap, nsmIdx>>
    /\ UNCHANGED <<cache, assignQ, choreSnap, procVars, envVars, clientVars, targetFired>>

\* S1(a) TARGET SITE.  NSM:225-227 loop body for the snapshot entry n:
\*   NSM:226 addNamespace(n) (nsStateCache, not modeled);
\*   NSM:227 listTableNamesByNamespace(n) -> HM:3758-3760 (checkInitialized
\*   passes) -> listTableNames HM:3847-3853 -> getTableDescriptors
\*   HM:3868-3876 -> CSSI:109-111.
\* Nothing in NSM:223-239 takes a lock or catches the exception; it escapes
\* NA:48-51 and MQM:114-116 to HM:2617-2630, which aborts the master.
TargetCheck_NsmInit(m) ==
    /\ phase[m] = "QuotaInit"
    /\ nsmIdx[m] <= Len(nsmSnap[m])
    /\ LET n == nsmSnap[m][nsmIdx[m]] IN
         IF n \notin cache[m]                                \* CSSI:110-111 nsd == null
           THEN /\ targetFired' = TRUE                       \* CSSI:111 throw NamespaceNotFoundException
                /\ UNCHANGED nsmIdx
           ELSE /\ targetFired' = targetFired
                \* NSM:228-235 per-table meta scans (abstracted)
                /\ nsmIdx' = [nsmIdx EXCEPT ![m] = @ + 1]
    /\ UNCHANGED <<phase, cache, nsmSnap, assignQ, choreSnap, procVars, envVars, clientVars>>

\* S1: NSM:237-238 initialized = true -> NA:50 -> MQM:116 initialized = true
\* -> HM:1624 this.quotaManager = quotaManager (volatile, HM:469) -> HM:1336-1347
\* quota chores scheduled (QuotaObserverChore when quota is enabled).
QuotaPublish(m) ==
    /\ phase[m] = "QuotaInit"
    /\ nsmIdx[m] > Len(nsmSnap[m])
    /\ phase' = [phase EXCEPT ![m] = "Running"]
    /\ UNCHANGED <<cache, nsmSnap, nsmIdx, assignQ, choreSnap, procVars, envVars,
                   clientVars, targetFired>>

\* FAULT (S1, S2, S3): the active master stops or crashes at any milestone
\* (TNA:541-545 killActiveMaster = HMaster.stop; process crash).  Durable
\* state (meta, procedure store, quota table) survives; the backup takes over.
MasterCrash(m) ==
    /\ IsActive(m)
    /\ MasterDies(m)
    /\ UNCHANGED <<metaNs, spaceQuotaNs, rsAlive, regionState, regionHost,
                   dnp, cnp, ctp, clientVars, targetFired>>

(***************************************************************************)
(* DeleteNamespaceProcedure (S1, S3).  One procedure step per action; the  *)
(* next state is persisted after the step (PE:1893-1912), so a crash inside*)
(* a step re-runs it on the next master.  Runs on the active master after  *)
(* HM:1300 (ProcRunnable) holding the namespace exclusive lock             *)
(* (ASMNP:79-84).                                                          *)
(***************************************************************************)

\* DNP:70-78 DELETE_NAMESPACE_PREPARE -> prepareDelete DNP:188-216.
DnpPrepare(m) ==
    /\ dnp = "Prepare"
    /\ ProcRunnable(m)
    /\ IF NSP \in cache[m]                                   \* DNP:189 doesNamespaceExist = cache.containsKey (TNM:181-183)
         THEN \* DNP:193-197 not a reserved namespace.
              \* DNP:199-201 listTableDescriptorsByNamespace(nsp) -> HM:3764-3766
              \* (checkInitialized) -> HM:3827-3833 -> HM:3868-3876 getNamespace(nsp)
              \* -> CSSI:110-111.  TARGET SITE whose guard is FALSE here: DNP:189 saw
              \* nsp in the same cache within this step, the DNP holds the namespace
              \* exclusive lock, and the only remover (TNM:218) is this procedure's
              \* next step.
              \* DNP:206-215 tableCount == 0 (the cleanup deleted the tables first,
              \* TNA:125-128); nsDescriptor kept for rollback.
              /\ dnp' = "DelNsTable"                         \* DNP:77, persisted
              \* DNP:72 releaseSyncLatch(): the handler blocked at HM:3696 resumes
              /\ rpcHandler' = IF rpcHandler.m = m /\ rpcHandler.st = "Latch"
                                 THEN [rpcHandler EXCEPT !.st = "Released"]
                                 ELSE rpcHandler
              /\ UNCHANGED clientPc
         ELSE \* DNP:190-191 setFailure(NamespaceNotFoundException) thrown by DNP
              \* itself (a legitimate answer, not CSSI:111); DNP:73-75 NO_MORE_STATE.
              /\ dnp' = "Failed"
              \* DNP:72 latch released with the failure: HM:3696 throws, the post
              \* hook is skipped (HM:3697), the RPC returns the exception.
              /\ IF rpcHandler.m = m /\ rpcHandler.st = "Latch"
                   THEN /\ rpcHandler' = NoHandler
                        /\ clientPc' = "DelRejected"
                   ELSE UNCHANGED <<rpcHandler, clientPc>>
    /\ UNCHANGED <<masterVars, dnpSub, cnp, cnpSub, ctp, ctpSub, envVars, ctRound, targetFired>>

\* DNP:79-80 DELETE_NAMESPACE_DELETE_FROM_NS_TABLE -> DNP:223-225 ->
\* TNM:212-217: checkMigrationDone (TNM:213, migrationDone on 3.x), then the
\* whole-row meta Delete (TNM:214-216).  Writers go meta first, then cache.
DnpMetaDelete(m) ==
    /\ dnp = "DelNsTable"
    /\ dnpSub = "Idle"
    /\ ProcRunnable(m)
    /\ MetaOnline                                            \* else IOException -> DNP:97-104 retry
    /\ metaNs' = metaNs \ {NSP}                              \* TNM:214-216 (idempotent on a re-run)
    /\ dnpSub' = "MetaDeleted"
    /\ UNCHANGED <<masterVars, dnp, cnp, cnpSub, ctp, ctpSub, spaceQuotaNs, rsAlive,
                   regionState, regionHost, clientVars, targetFired>>

\* TNM:218 cache.remove(nsp) -- the only cache remover -- then DNP:81
\* setNextState(DELETE_DIRECTORIES), persisted (PE:1893-1912).
DnpCacheRemove(m) ==
    /\ dnp = "DelNsTable"
    /\ dnpSub = "MetaDeleted"
    /\ ProcRunnable(m)
    /\ cache' = [cache EXCEPT ![m] = @ \ {NSP}]              \* TNM:218
    /\ dnp' = "DelDirs"                                      \* DNP:81
    /\ dnpSub' = "Idle"
    /\ UNCHANGED <<phase, nsmSnap, nsmIdx, assignQ, choreSnap, cnp, cnpSub, ctp, ctpSub,
                   envVars, clientVars, targetFired>>

\* DNP:87-90 DELETE_NAMESPACE_DELETE_DIRECTORIES -> DNP:233-252 (rmdir).
DnpDeleteDirectories(m) ==
    /\ dnp = "DelDirs"
    /\ ProcRunnable(m)
    /\ dnp' = "RemoveQuota"                                  \* DNP:89
    /\ UNCHANGED <<masterVars, dnpSub, cnp, cnpSub, ctp, ctpSub, envVars, clientVars, targetFired>>

\* S1(b): DNP:91-93 DELETE_NAMESPACE_REMOVE_NAMESPACE_QUOTA -> DNP:259-262
\* env.getMasterServices().getMasterQuotaManager().removeNamespaceQuota(ns),
\* with no null check.
DnpRemoveQuota(m) ==
    /\ dnp = "RemoveQuota"
    /\ ProcRunnable(m)
    /\ IF QuotaManagerPublished(m)                           \* HM:3327-3329 /= null after HM:1624
         THEN dnp' = "Success"   \* MQM:386-390; DNP:93 NO_MORE_STATE -> SUCCESS (PE:1871-1874)
         ELSE dnp' = "Failed"    \* DNP:261 NullPointerException escapes DNP:97 (catches IOException
                                 \* only) -> PE:1844-1849 "CODE-BUG" setFailure -> rollback
                                 \* PE:1677-1717; every DNP:108-121 rollbackState throws UOE, caught at
                                 \* PE:1760-1763 -> ROLLEDBACK.  Nothing is undone: meta row and cache
                                 \* entry are already gone.
    /\ UNCHANGED <<masterVars, dnpSub, cnp, cnpSub, ctp, ctpSub, envVars, clientVars, targetFired>>

(***************************************************************************)
(* CreateNamespaceProcedure (workload anchor: creates nsp in meta and in   *)
(* the cache).  Same execution rules as the DNP.                           *)
(***************************************************************************)

\* CNP:62-70 PREPARE -> prepareCreate CNP:184-193.
CnpPrepare(m) ==
    /\ cnp = "Prepare"
    /\ ProcRunnable(m)
    /\ cnp' = IF NSP \in cache[m]                            \* CNP:185 doesNamespaceExist
                THEN "Failed"                                \* CNP:186-188 NamespaceExistException
                ELSE "CreateDir"                             \* CNP:190-191 checks; CNP:64 latch; CNP:69
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnpSub, ctp, ctpSub, envVars, clientVars, targetFired>>

\* CNP:71-74 CREATE_DIRECTORY (mkdirs).
CnpCreateDirectory(m) ==
    /\ cnp = "CreateDir"
    /\ ProcRunnable(m)
    /\ cnp' = "Insert"                                       \* CNP:73
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnpSub, ctp, ctpSub, envVars, clientVars, targetFired>>

\* CNP:75-76 INSERT_INTO_NS_TABLE -> ASMNP:95-98 -> TNM:195-197:
\* checkMigrationDone, then insertNamespaceToMeta (TNM:201-209).
CnpMetaPut(m) ==
    /\ cnp = "Insert"
    /\ cnpSub = "Idle"
    /\ ProcRunnable(m)
    /\ MetaOnline                                            \* else IOException -> CNP:89-95 retry
    /\ metaNs' = metaNs \cup {NSP}                           \* TNM:197, TNM:208
    /\ cnpSub' = "MetaPut"
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnp, ctp, ctpSub, spaceQuotaNs, rsAlive,
                   regionState, regionHost, clientVars, targetFired>>

\* TNM:198 cache.put, then CNP:77 setNextState(SET_NAMESPACE_QUOTA), persisted.
CnpCachePut(m) ==
    /\ cnp = "Insert"
    /\ cnpSub = "MetaPut"
    /\ ProcRunnable(m)
    /\ cache' = [cache EXCEPT ![m] = @ \cup {NSP}]           \* TNM:198
    /\ cnp' = "SetQuota"                                     \* CNP:77
    /\ cnpSub' = "Idle"
    /\ UNCHANGED <<phase, nsmSnap, nsmIdx, assignQ, choreSnap, dnp, dnpSub, ctp, ctpSub,
                   envVars, clientVars, targetFired>>

\* CNP:83-85 SET_NAMESPACE_QUOTA -> CNP:200-205: if isInitialized() then
\* getMasterQuotaManager().setNamespaceQuota(ns), with no null check (T-3).
CnpSetNamespaceQuota(m) ==
    /\ cnp = "SetQuota"
    /\ ProcRunnable(m)                                       \* CNP:202 isInitialized() is TRUE
    /\ cnp' = IF QuotaManagerPublished(m)
                THEN "Success"                               \* CNP:203, CNP:85 NO_MORE_STATE
                ELSE "Failed"                                \* CNP:203 NPE -> PE:1844-1849; no-op rollback
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnpSub, ctp, ctpSub, envVars, clientVars, targetFired>>

(***************************************************************************)
(* CreateTableProcedure (workload anchor: target sites CTP:316 and NSM:155)*)
(***************************************************************************)

\* CTP:93-96 CREATE_TABLE_PRE_OPERATION -> prepareCreate CTP:278-332, then the latch
\* release (CTP:96).  A user table waits for "initialized" (CTP:266-276).
CtpPrepare(m) ==
    /\ ctp = "Prepare"
    /\ ctpSub = "Idle"
    /\ ProcRunnable(m)
    \* CTP:280-305 table absent, has a CF, replicas ok, no encoded-name collision.
    \* CTP:307-314 user table; the descriptor names no rsgroup, so checkGroupExists
    \* returns null (MPU:225-237) and the namespace is consulted:
    /\ IF NSP \notin cache[m]                                \* CTP:315-316 getNamespace(nsp) -> CSSI:110-111
         THEN /\ targetFired' = TRUE                         \* CSSI:111
              /\ UNCHANGED ctpSub
         ELSE /\ targetFired' = targetFired
              /\ ctpSub' = "PrepDone"                        \* CTP:317-322; CTP:96 latch; CTP:103 preCreate begins
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnp, cnpSub, ctp, envVars, clientVars>>

\* CTP:103 preCreate -> CTP:334-338: ProcedureSyncWait.getMasterQuotaManager
\* (PSW:261-270) waits until the quota manager is published, then
\* MQM.checkNamespaceTableAndRegionQuota -> NA:61-67 -> NSM:149-155 ->
\* getNamespaceDescriptor NSM:140-142 -> CSSI:110-111 (caught NSM:143-146).
CtpPreCreate(m) ==
    /\ ctp = "Prepare"
    /\ ctpSub = "PrepDone"
    /\ ProcRunnable(m)
    /\ QuotaManagerPublished(m)                              \* PSW:263-268
    /\ IF QuotaEnabled /\ NSP \notin cache[m]                \* NSM:155 -> NSM:142 -> CSSI:110-111
         THEN /\ targetFired' = TRUE                         \* CSSI:111 (then caught at NSM:143)
              /\ UNCHANGED <<ctp, ctpSub>>
         ELSE /\ targetFired' = targetFired
              \* NSM:156-175 quota outcome is taken as given (brief 3.2): the
              \* rounds in CtRejected throw QuotaExceededException; PRE_OPERATION supports
              \* rollback (CTP:145-147 setFailure).
              /\ ctp' = IF QuotaEnabled /\ ctRound \in CtRejected THEN "Rejected" ELSE "Assign"
              /\ ctpSub' = "Idle"
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnp, cnpSub, envVars, clientVars>>

\* CTP:106-131 WRITE_FS_LAYOUT, ADD_TO_META (needs meta), ASSIGN_REGIONS:
\* CTP:128-129 -> AM:926-949 createRoundRobinAssignProcedures -> balancer
\* roundRobinAssignment RGLB:181-185 -> generateGroupAssignments RGLB:227-238 ->
\* RGU:77-123.  With rsgroup enabled RGU:117 looks the namespace up (S2 site);
\* AM:945-949 catches a failure and falls back.  Child TRSPs are created for the
\* table's regions.
CtpAssignRegions(m) ==
    /\ ctp = "Assign"
    /\ ProcRunnable(m)
    /\ MetaOnline                                            \* CTP:122-123 addTableToMeta
    /\ IF RSGroupEnabled /\ NSP \notin cache[m]              \* RGU:117 -> CSSI:110-111
         THEN /\ targetFired' = TRUE
              /\ UNCHANGED <<ctp, regionState>>
         ELSE /\ targetFired' = targetFired
              /\ regionState' = [r \in Regions |->
                                   IF r \in CtpRegions(ctRound) THEN "Rit" ELSE regionState[r]]
              /\ ctp' = "WaitChildren"                       \* CTP:130
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnp, cnpSub, ctpSub, metaNs, spaceQuotaNs,
                   rsAlive, regionHost, clientVars>>

\* CTP:132-141 UPDATE_DESC_CACHE, POST_OPERATION after the child TRSPs finished.
CtpFinish(m) ==
    /\ ctp = "WaitChildren"
    /\ ProcRunnable(m)
    /\ \A r \in CtpRegions(ctRound) : regionState[r] = "Open"
    /\ ctp' = "Success"                                      \* CTP:141 NO_MORE_STATE
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnp, cnpSub, ctpSub, envVars, clientVars, targetFired>>

(***************************************************************************)
(* Workload client: TestNamespaceAuditor#testTableOperations (TNA:138-185) *)
(* and its @AfterEach cleanup (TNA:123-136).  The client is sequential and *)
(* sends master RPCs to the active master; a master that is not            *)
(* initialized answers PleaseHoldException and the client retries later.  *)
(***************************************************************************)

\* TNA:102-116 startMiniCluster then waitForQuotaInitialize (TNA:526-538).
ClientStart ==
    /\ clientPc = "Boot"
    /\ \E m \in Masters : QuotaManagerPublished(m)
    /\ clientPc' = "CreateNs"
    /\ UNCHANGED <<masterVars, procVars, envVars, ctRound, rpcHandler, targetFired>>

\* TNA:144 createNamespace -> HM:3601-3628 -> CSSI:86-91 -> CSSI:78-83.
\* The CNP is stored with its nonce before the procId is returned.  The RPC's
\* latch wait (HM:3614-3619) and a resend without a nonce (T-4) are not
\* modeled: neither writes the cache.
ClientCreateNamespace(m) ==
    /\ clientPc = "CreateNs"
    /\ Initialized(m)                                        \* HM:3603 checkInitialized
    /\ cnp' = "Prepare"
    /\ clientPc' = "CreateNsWait"
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnpSub, ctp, ctpSub, envVars, ctRound,
                   rpcHandler, targetFired>>

\* The client polls getProcedureResult MRS:1381-1396 (checkInitialized MRS:1385).
\* A failed create (T-3) fails the test method; JUnit then runs the cleanup.
ClientCreateNsResult(m) ==
    /\ clientPc = "CreateNsWait"
    /\ Initialized(m)
    /\ cnp \in {"Success", "Failed"}
    /\ clientPc' = IF cnp = "Success"
                     THEN IF NSP \in SpaceQuotaNs THEN "SetSpaceQuota" ELSE "GetNs"
                     ELSE "DeleteTables"
    /\ UNCHANGED <<masterVars, procVars, envVars, ctRound, rpcHandler, targetFired>>

\* S3 workload variant: Admin.setQuota(QuotaSettingsFactory.limitNamespaceSpace
\* (nsp, ...)) -> MRS:1903-1907 -> MQM.setQuota writes the SPACE row.
ClientSetSpaceQuota(m) ==
    /\ clientPc = "SetSpaceQuota"
    /\ QuotaManagerPublished(m)                              \* MRS:1905-1906
    /\ spaceQuotaNs' = spaceQuotaNs \cup {NSP}
    /\ clientPc' = "GetNs"
    /\ UNCHANGED <<masterVars, procVars, metaNs, rsAlive, regionState, regionHost, ctRound,
                   rpcHandler, targetFired>>

\* TARGET SITE (workload TNA:145; S1(b) follow-up read): getNamespaceDescriptor
\* -> MRS:1132-1138 -> HM:3713-3716 -> CSSI:109-111.
TargetCheck_ClientGet(m) ==
    /\ clientPc \in {"GetNs", "ReadAfterFail"}
    /\ Initialized(m)                                        \* HM:3714 checkInitialized
    \* HM:3715 cpHost.preGetNamespaceDescriptor
    /\ IF NSP \notin cache[m]                                \* HM:3716 -> CSSI:110-111
         THEN /\ targetFired' = TRUE                         \* CSSI:111
              /\ UNCHANGED clientPc
         ELSE /\ targetFired' = targetFired
              /\ clientPc' = IF clientPc = "ReadAfterFail" THEN "Done"
                             ELSE IF CreateTableRounds > 0 THEN "CreateTable"
                             ELSE "DeleteTables"
    /\ UNCHANGED <<masterVars, procVars, envVars, ctRound, rpcHandler>>

\* TARGET SITE (workload TNA:159/162/170/177): createTable -> HM:2510-2518.
TargetCheck_ClientCreateTable(m) ==
    /\ clientPc = "CreateTable"
    /\ Initialized(m)                                        \* HM:2512 checkInitialized
    \* HM:2513-2516 preCreateTableRegionsInfos returns the descriptor
    /\ IF NSP \notin cache[m]                                \* HM:2517-2518 getNamespace(nsp) -> CSSI:110-111
         THEN /\ targetFired' = TRUE                         \* CSSI:111
              /\ UNCHANGED <<ctp, clientPc>>
         ELSE /\ targetFired' = targetFired
              /\ ctp' = "Prepare"                            \* HM:2520-2548 CTP submitted with a nonce
              /\ clientPc' = "CreateTableWait"
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnp, cnpSub, ctpSub, envVars, ctRound, rpcHandler>>

\* The client polls the CTP result (MRS:1381-1396); TNA:159-184 expect the
\* rounds in CtRejected to fail with an IOException.
ClientCreateTableResult(m) ==
    /\ clientPc = "CreateTableWait"
    /\ Initialized(m)
    /\ ctp \in {"Success", "Rejected"}
    /\ ctp' = "None"                                         \* the next round submits a new CTP
    /\ IF ctRound < CreateTableRounds
         THEN /\ ctRound' = ctRound + 1
              /\ clientPc' = "CreateTable"
         ELSE /\ UNCHANGED ctRound
              /\ clientPc' = "DeleteTables"
    /\ UNCHANGED <<masterVars, dnp, dnpSub, cnp, cnpSub, ctpSub, envVars, rpcHandler, targetFired>>

\* TNA:125-128 disable + delete every table.  DeleteTableProcedure waits for
\* the quota manager (DTP:448-452 -> PSW:261-270) and for regions in
\* transition (DTP:109).  Then TNA:129-131 listNamespaceDescriptors
\* (HM:3725-3736 -> CSSI:116-120, the cache) and deleteNamespace if listed.
\* After a failed createNamespace (T-3) no table exists: the TNA:125 loop runs
\* zero times, so no DTP waits and only checkInitialized gates the listing.
ClientDeleteTables(m) ==
    /\ clientPc = "DeleteTables"
    /\ IF cnp = "Failed" \/ CreateTableRounds = 0
         THEN Initialized(m)
         ELSE QuotaManagerPublished(m)
    /\ MetaOnline
    /\ \A r \in UserRegions : regionState[r] /= "Rit"
    /\ regionState' = [r \in Regions |-> IF r \in UserRegions THEN "Absent" ELSE regionState[r]]
    /\ regionHost'  = [r \in Regions |-> IF r \in UserRegions THEN None ELSE regionHost[r]]
    /\ clientPc' = IF NSP \in cache[m] THEN "DelSend" ELSE "Done"
    /\ UNCHANGED <<masterVars, procVars, metaNs, spaceQuotaNs, rsAlive, ctRound,
                   rpcHandler, targetFired>>

\* TNA:131 deleteNamespace -> HM:3678-3706 -> MPU:132-146.  The stock client
\* sends no nonce (RawAsyncHBaseAdmin:969, RequestConverter:1539-1543; the proto
\* default is 0, Master.proto:248-252), so the nonce key is null (PE:862-864) and
\* registerNonce returns -1 (PE:875-877) -> run(): HM:3686 preDeleteNamespace;
\* HM:3693-3695 the DNP is stored; HM:3696 latch.await().
ClientDeleteNamespace(m) ==
    /\ clientPc = "DelSend"
    /\ Initialized(m)                                        \* HM:3680 checkInitialized
    /\ dnp' = "Prepare"
    /\ rpcHandler' = [m |-> m, st |-> "Latch"]
    /\ clientPc' = "DelInRpc"
    /\ UNCHANGED <<masterVars, dnpSub, cnp, cnpSub, ctp, ctpSub, envVars, ctRound, targetFired>>

\* S3: HM:3696-3698 after DNP:72 released the latch the handler runs
\* postDeleteNamespace on the RPC thread, outside the procedure.
\* MQO:105-127 (installed when quota is enabled, HM:4658-4664): if nsp has a
\* SPACE quota, admin.setQuota(removeNamespaceSpaceLimit) -> MRS:1903-1906
\* getMasterQuotaManager().setQuota with no null check.
HookPostDeleteNamespace(m) ==
    /\ clientPc = "DelInRpc"
    /\ rpcHandler.m = m
    /\ rpcHandler.st = "Released"
    /\ Alive(m)
    /\ IF QuotaEnabled /\ NSP \in spaceQuotaNs               \* MQO:108-115
         THEN IF QuotaManagerPublished(m)
                THEN /\ spaceQuotaNs' = spaceQuotaNs \ {NSP} \* MQO:116-118 row removed
                     /\ clientPc' = "DelWait"                \* RPC returns the procId (MPU:145)
                ELSE \* MRS:1906 NPE -> the hook throws -> MPU:138-141: with a null nonce
                     \* key setFailureResultForNonce does nothing (PE:936-938) and the
                     \* exception is the RPC's answer.  The client is told the delete
                     \* failed while the DNP keeps running; the SPACE row survives.
                     /\ UNCHANGED spaceQuotaNs
                     /\ clientPc' = "ReadAfterFail"
         ELSE /\ UNCHANGED spaceQuotaNs                      \* MQO:113-114 no quota row
              /\ clientPc' = "DelWait"
    /\ rpcHandler' = NoHandler
    /\ UNCHANGED <<masterVars, procVars, metaNs, rsAlive, regionState, regionHost, ctRound,
                   targetFired>>

\* FAULT-BOUNDED (S1, S3): the handler's master died before answering; the
\* client resends to the new active master.  There is no nonce (see
\* ClientDeleteNamespace), so MPU:134 returns -1 and run() submits a SECOND DNP
\* with a new latch (HM:3693-3696).  The first DNP is not deduplicated.
ClientResendDeleteNamespace(m) ==
    /\ clientPc = "DelInRpc"
    /\ rpcHandler.m \in Masters
    /\ phase[rpcHandler.m] = "Down"
    /\ Initialized(m)                                        \* HM:3680 on the new master
    /\ dnp /= "None"                                         \* stored at HM:3694 before the crash
    /\ rpcHandler' = [m |-> m, st |-> "ResendLatch"]
    /\ UNCHANGED <<masterVars, procVars, envVars, clientPc, ctRound, targetFired>>

\* PREPARE of the second DNP (DNP:70-75).  It runs after the recovered DNP has
\* finished: that DNP keeps the namespace exclusive lock across its whole step
\* loop (ASMNP:79-89, PE:1853-1857, PE:1946; no yield, SMP:130), the lock is
\* restored on load if it was held at the crash (Proc:1013-1014, PE:599), and a
\* DNP not yet started is woken to the queue's front (ProcedureEvent:116) when
\* HM:1300 opens the gate, before HM:3680 can pass.  So DNP:189 finds nsp gone
\* and DNP:190-191 fails with the DNP's own NamespaceNotFoundException, not
\* CSSI:111.  DNP:72 releases the latch; HM:3696 throws, so the post hook
\* (HM:3698) does not run for this request either; the RPC returns the exception.
DnpResendPrepare(m) ==
    /\ rpcHandler.m = m
    /\ rpcHandler.st = "ResendLatch"
    /\ dnp \in {"Success", "Failed"}
    /\ ProcRunnable(m)
    /\ NSP \notin cache[m]                                   \* DNP:189
    /\ rpcHandler' = NoHandler
    /\ clientPc' = "DelRejected"
    /\ UNCHANGED <<masterVars, procVars, envVars, ctRound, targetFired>>

\* The client received the namespace-not-found answer (DNP:190-191) and stops:
\* TNA:129-133 rethrows.  It was told the namespace is gone, so it has no reason
\* to read it (brief 3.2).
ClientDeleteRejected ==
    /\ clientPc = "DelRejected"
    /\ clientPc' = "Done"
    /\ UNCHANGED <<masterVars, procVars, envVars, ctRound, rpcHandler, targetFired>>

\* The client polls the DNP result (MRS:1381-1396, checkInitialized MRS:1385).
\* A reported failure leads the client to read the namespace it was told
\* still exists (S1(b), modeling-brief.md section 2).
ClientDeleteNsResult(m) ==
    /\ clientPc = "DelWait"
    /\ Initialized(m)
    /\ dnp \in {"Success", "Failed"}
    /\ clientPc' = IF dnp = "Success" THEN "Done" ELSE "ReadAfterFail"
    /\ UNCHANGED <<masterVars, procVars, envVars, ctRound, rpcHandler, targetFired>>

(***************************************************************************)
(* S2: assignment through the rsgroup balancer while the cache loads      *)
(***************************************************************************)

\* FAULT (S2): a RegionServer dies.  Its SCP (SCP:142-240) re-assigns its
\* regions: meta first (SCP:168-177, 200-201), the others after meta is loaded
\* (SCP:160-164, 204-213).  At least one RegionServer stays alive.
RSCrash(x) ==
    /\ rsAlive[x]
    /\ \E y \in RS \ {x} : rsAlive[y]
    /\ rsAlive' = [rsAlive EXCEPT ![x] = FALSE]
    /\ regionState' = [r \in Regions |->
                         IF regionState[r] = "Open" /\ regionHost[r] = x THEN "Rit" ELSE regionState[r]]
    /\ regionHost'  = [r \in Regions |->
                         IF regionState[r] = "Open" /\ regionHost[r] = x THEN None ELSE regionHost[r]]
    /\ UNCHANGED <<masterVars, procVars, metaNs, spaceQuotaNs, clientVars, targetFired>>

\* TRSP REGION_STATE_TRANSITION_GET_ASSIGN_CANDIDATE (TRSP:480-505) -> queueAssign
\* TRSP:246-273 -> AM:2444-2460 pendingAssignQueue.add.  TRSPs (and SCP) are not
\* initialized-gated; they run once workers start (HM:1148).
\* TRSP:207-219 waitInitialized: meta does not wait (TRSP:212-213); other
\* regions wait for meta loaded (HM:1194) and meta assigned (TRSP:217-218).
TrspQueueAssign(m, r) ==
    /\ IsActive(m)
    /\ WorkersStarted(m)
    /\ regionState[r] = "Rit"
    /\ r \notin assignQ[m]
    /\ r = MetaRegion \/ (MetaLoadedEv(m) /\ MetaOnline)
    /\ assignQ' = [assignQ EXCEPT ![m] = @ \cup {r}]
    /\ UNCHANGED <<phase, cache, nsmSnap, nsmIdx, choreSnap, procVars, envVars, clientVars,
                   targetFired>>

\* S2 TARGET SITE.  Assign thread (started by AM.start at HM:1050, AM:313-321):
\* processAssignQueue AM:2526-2588 takes the whole pending queue
\* (AM:2512-2516) as one batch; processAssignmentPlans AM:2603-2639 ->
\* retainAssignment / roundRobinAssignment (RGLB:181-216) ->
\* generateGroupAssignments RGLB:227-238 -> RGU:77-123 for every region:
\*   RGU:79-96   descriptor present, no table group, no legacy mapping (RGIM:890-892);
\*   RGU:98-105  rsgroup disabled: DRGM:123-126 returns "default" -> return before
\*               RGU:117; enabled without mapping script: RGIM:218-221/1324-1326 null;
\*   RGU:107-116 getClusterSchema() == null (before HM:1610): default group;
\*   RGU:117     clusterSchema.getNamespace(ns) -> CSSI:110-111.
\* A failure is wrapped (RGLB:269-270), logged and the batch re-queued
\* (AM:2619-2621, AM:2634-2636).
TargetCheck_Assign(m) ==
    /\ IsActive(m)
    /\ assignQ[m] /= {}
    /\ AliveRS /= {}                                         \* AM:2554-2567
    /\ IF RSGroupEnabled /\ SchemaPublished(m)
          /\ \E r \in assignQ[m] : RegionNs(r) \notin cache[m]
         THEN /\ targetFired' = TRUE                         \* CSSI:111
              /\ UNCHANGED <<assignQ, regionState, regionHost>>
         ELSE \E x \in AliveRS :
                /\ targetFired' = targetFired
                \* AM:2641-2668 acceptPlan; the TRSP then opens the region
                \* (TRSP:507-511 OPEN, CONFIRM_OPENED), collapsed into this step.
                /\ regionState' = [r \in Regions |->
                                     IF r \in assignQ[m] THEN "Open" ELSE regionState[r]]
                /\ regionHost'  = [r \in Regions |->
                                     IF r \in assignQ[m] THEN x ELSE regionHost[r]]
                /\ assignQ' = [assignQ EXCEPT ![m] = {}]
    /\ UNCHANGED <<phase, cache, nsmSnap, nsmIdx, choreSnap, procVars, metaNs, spaceQuotaNs,
                   rsAlive, clientVars>>

\* S2 TARGET SITE (workload variant with an extra admin client):
\* getRSGroupInfoOfTable MRS:3132-3160 has no checkInitialized; MRS:3143-3146
\* table present -> MRS:3147-3149 RGU:77-123 as above.  Before HM:1610 RGU:107-116
\* returns the default group, so the call is modeled from HM:1148 on.
TargetCheck_RsGroupRpc(m) ==
    /\ RsGroupRpcClient
    /\ RSGroupEnabled                                        \* else RGU:98-105 returns first
    /\ clientPc /= "Boot"                                    \* the variant's client starts with the workload
    /\ IsActive(m)
    /\ WorkersStarted(m)
    /\ \E n \in RpcTableNs :
         IF SchemaPublished(m) /\ n \notin cache[m]          \* RGU:107-117 -> CSSI:110-111
           THEN targetFired' = TRUE                          \* CSSI:111
           ELSE targetFired' = targetFired                   \* the RPC returns a group
    /\ UNCHANGED <<masterVars, procVars, envVars, clientVars>>

(***************************************************************************)
(* S3: QuotaObserverChore (HM:1336-1347; QOC:59, 62 every minute)         *)
(***************************************************************************)

\* QOC:125-141 chore -> _chore -> fetchAllTablesWithQuotasDefined QOC:475-486:
\* the scanner over hbase:quota yields the SPACE settings; namespace rows are
\* looked up one at a time (TargetCheck_Chore).
QuotaObserverChoreScan(m) ==
    /\ QuotaEnabled
    /\ QuotaManagerPublished(m)                              \* scheduled at HM:1342
    /\ choreSnap[m] = <<>>
    /\ spaceQuotaNs /= {}                                    \* QOC:483-487 SPACE namespace rows
    /\ choreSnap' = [choreSnap EXCEPT ![m] = SortedNs(spaceQuotaNs)]
    /\ UNCHANGED <<phase, cache, nsmSnap, nsmIdx, assignQ, procVars, envVars, clientVars,
                   targetFired>>

\* S3 TARGET SITE.  QOC:487-490 conn.getAdmin().listTableNamesByNamespace(ns)
\* -> MRS:1491-1496 -> HM:3757-3760 (checkInitialized) -> HM:3847-3853 ->
\* HM:3868-3876 -> CSSI:110-111.  Caught only at QOC:136-137: the run is
\* abandoned and retried next period.
TargetCheck_Chore(m) ==
    /\ QuotaManagerPublished(m)
    /\ choreSnap[m] /= <<>>
    /\ LET n == Head(choreSnap[m]) IN
         IF n \notin cache[m]                                \* CSSI:110-111
           THEN /\ targetFired' = TRUE                       \* CSSI:111
                /\ UNCHANGED choreSnap
           ELSE /\ targetFired' = targetFired
                /\ choreSnap' = [choreSnap EXCEPT ![m] = Tail(@)]   \* QOC:491-497
    /\ UNCHANGED <<phase, cache, nsmSnap, nsmIdx, assignQ, procVars, envVars, clientVars>>

(***************************************************************************)
(* Next-state relation                                                     *)
(***************************************************************************)
MasterStep(m) ==
    \/ BecomeActive(m)
    \/ WaitForMetaOnline(m)
    \/ InitClusterSchemaService(m)
    \/ LoadRow(m)
    \/ LoadDone(m)
    \/ LoadFail(m)
    \/ GateInitialized(m)
    \/ QuotaSnapshot(m)
    \/ TargetCheck_NsmInit(m)
    \/ QuotaPublish(m)

ProcStep(m) ==
    \/ DnpPrepare(m)
    \/ DnpMetaDelete(m)
    \/ DnpCacheRemove(m)
    \/ DnpDeleteDirectories(m)
    \/ DnpRemoveQuota(m)
    \/ DnpResendPrepare(m)
    \/ CnpPrepare(m)
    \/ CnpCreateDirectory(m)
    \/ CnpMetaPut(m)
    \/ CnpCachePut(m)
    \/ CnpSetNamespaceQuota(m)
    \/ CtpPrepare(m)
    \/ CtpPreCreate(m)
    \/ CtpAssignRegions(m)
    \/ CtpFinish(m)

ClientStep(m) ==
    \/ ClientCreateNamespace(m)
    \/ ClientCreateNsResult(m)
    \/ ClientSetSpaceQuota(m)
    \/ TargetCheck_ClientGet(m)
    \/ TargetCheck_ClientCreateTable(m)
    \/ ClientCreateTableResult(m)
    \/ ClientDeleteTables(m)
    \/ ClientDeleteNamespace(m)
    \/ HookPostDeleteNamespace(m)
    \/ ClientDeleteNsResult(m)

RegionStep(m) ==
    \/ \E r \in Regions : TrspQueueAssign(m, r)
    \/ TargetCheck_Assign(m)
    \/ TargetCheck_RsGroupRpc(m)

ChoreStep(m) ==
    \/ QuotaObserverChoreScan(m)
    \/ TargetCheck_Chore(m)

\* Steps that react to existing state (not bounded in MC)
ReactiveNext ==
    \/ ClientStart
    \/ ClientDeleteRejected
    \/ \E m \in Masters :
         \/ MasterStep(m)
         \/ ProcStep(m)
         \/ ClientStep(m)
         \/ RegionStep(m)
         \/ ChoreStep(m)

\* Steps that introduce faults or retries (counter-bounded in MC)
FaultNext ==
    \/ \E m \in Masters : MasterCrash(m)
    \/ \E x \in RS : RSCrash(x)
    \/ \E m \in Masters : ClientResendDeleteNamespace(m)

\* Once the target has fired every other action stops (tla-patterns.md 1).
Next ==
    /\ ~targetFired
    /\ ReactiveNext \/ FaultNext

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The ad hoc target never fails.
TargetSafe == ~targetFired

\* Structural sanity 1: variable domains, and at most one active master.
TypeOK ==
    /\ phase \in [Masters -> Phases]
    /\ cache \in [Masters -> SUBSET NS]
    /\ \A m \in Masters : nsmSnap[m] \in Seq(NS) /\ Len(nsmSnap[m]) <= 3
    /\ nsmIdx \in [Masters -> 1..4]
    /\ assignQ \in [Masters -> SUBSET Regions]
    /\ \A m \in Masters : choreSnap[m] \in Seq(NS) /\ Len(choreSnap[m]) <= 3
    /\ metaNs \subseteq NS
    /\ dnp \in DnpStates
    /\ cnp \in CnpStates
    /\ ctp \in CtpStates
    /\ spaceQuotaNs \subseteq NS
    /\ rsAlive \in [RS -> BOOLEAN]
    /\ regionState \in [Regions -> {"Absent", "Open", "Rit"}]
    /\ regionHost \in [Regions -> RS \cup {None}]
    /\ dnpSub \in {"Idle", "MetaDeleted"}
    /\ cnpSub \in {"Idle", "MetaPut"}
    /\ ctpSub \in {"Idle", "PrepDone"}
    /\ clientPc \in ClientPcs
    /\ ctRound \in 1..(IF CreateTableRounds > 0 THEN CreateTableRounds ELSE 1)
    /\ rpcHandler \in [m : Masters \cup {None}, st : {"None", "Latch", "Released", "ResendLatch"}]
    /\ targetFired \in BOOLEAN
    /\ \A m1, m2 \in Masters : IsActive(m1) /\ IsActive(m2) => m1 = m2

\* Structural sanity 2: a cache entry only holds a namespace that meta holds,
\* except nsp between the DNP's meta Delete (TNM:214-216) and cache.remove
\* (TNM:218).  Writers go meta first (TNM:195-199, TNM:212-219).
CacheFromMeta ==
    \A m \in Masters :
        SchemaPublished(m) =>
            cache[m] \subseteq
                metaNs \cup (IF dnp = "DelNsTable" /\ dnpSub = "MetaDeleted" THEN {NSP} ELSE {})

=============================================================================
