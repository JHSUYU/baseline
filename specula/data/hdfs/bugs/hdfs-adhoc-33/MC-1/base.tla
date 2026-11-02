-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-33: the ad hoc check `assert bpStorage != null` in          *)
(* DataStorage.VolumeBuilder.build() (DataStorage.java:259), Apache Hadoop  *)
(* HDFS pinned at 734dd8a67cd.                                             *)
(*                                                                         *)
(* Category B (concurrent / runtime, modeling-brief.md section 1): one     *)
(* DataNode JVM.  A hot-swap `addVolume` worker reads a block pool's entry *)
(* of DataStorage.bpStorageMap at DS:340 and re-reads it in build()        *)
(* (DS:258); a block-pool shutdown on another thread can remove the entry  *)
(* in between (DN:2168).  NameNode replies and admin RPCs only trigger     *)
(* that shutdown, so they are environment actions here, not messages.     *)
(*                                                                         *)
(* Threads and their actions:                                              *)
(*  - reconfiguration caller (DN.refreshVolumes, DN:1284-1373):            *)
(*      RefreshVolumesSnapshot, RefreshVolumesReadNsInfo,                  *)
(*      RefreshVolumesSubmit, RefreshVolumesFinish;                        *)
(*  - one addVolume worker per new location w \in Vols                     *)
(*    (FsDatasetImpl.addVolume, FDI:514-562):                              *)
(*      LoadStorageDirectory, GetBlockPoolSliceStorage,                    *)
(*      AddBpStorageDirectories, AddBlockPoolAndScan, TargetCheck,         *)
(*      ActivateVolume;                                                    *)
(*  - one BPServiceActor per block pool b \in NS (non-HA: the actor is the *)
(*    BPOfferService's last actor): ActorExit; its triggers                *)
(*      OfferServiceRejected, CommandProcessorRejected (Scenario 1),       *)
(*      RefreshNamenodesRemove (Scenario 2),                               *)
(*      DNShutdown, DNStopMonitorGate, DNStopClearShouldRun (Scenario 3).  *)
(*                                                                         *)
(* Source abbreviations (under hadoop-hdfs-project/hadoop-hdfs/src/main/   *)
(* java/org/apache/hadoop/hdfs/server/):                                   *)
(*   DS   = datanode/DataStorage.java                                      *)
(*   DN   = datanode/DataNode.java                                         *)
(*   BPOS = datanode/BPOfferService.java                                   *)
(*   BPSA = datanode/BPServiceActor.java                                   *)
(*   BPM  = datanode/BlockPoolManager.java                                 *)
(*   BPSS = datanode/BlockPoolSliceStorage.java                            *)
(*   FDI  = datanode/fsdataset/impl/FsDatasetImpl.java                     *)
(*                                                                         *)
(* Atomicity (analysis-report.md section 2.3):                             *)
(*  - bpStorageMap's only mutators, getBlockPoolSliceStorage (DS:1409-1419)*)
(*    and removeBlockPoolStorage (DS:1421-1423), and build()'s whole loop  *)
(*    (DS:254-265) hold the DataStorage monitor, so each of               *)
(*    GetBlockPoolSliceStorage, TargetCheck and ActorExit is one step.     *)
(*  - ActorExit is one step: shutdownActor holds the BPOfferService write  *)
(*    lock across DN.shutdownBlockPool (BPOS:477-489), so a concurrent     *)
(*    getNamespaceInfo (BPOS:236-243, read lock) of that pool returns only *)
(*    after the removal; the removal path never takes the DataNode monitor.*)
(*  - Steps that touch only thread-local objects (the builder's            *)
(*    bpStorageDirMap, the new volume, its tempVolumeMap) are merged into  *)
(*    the neighbouring step; they commute with every other thread.         *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    NS,           \* block pools; one BPOfferService (nameservice) per pool, one actor each
    Vols,         \* new data dirs of the one hot-swap reconfiguration; one addVolume worker each
    Null,         \* a null NamespaceInfo (BPOS:236-243 before the handshake)
    DnStopModes   \* DataNode stop paths in scope: SUBSET {"direct", "gated"} (Scenario 3)

ASSUME Null \notin NS
ASSUME DnStopModes \subseteq {"direct", "gated"}

VARIABLES
    \* --- guard operand (all Scenarios) ---
    bpMap,        \* keys of DataStorage.bpStorageMap (DS:107-108)
    \* --- block-pool lifecycle (all Scenarios) ---
    bpos,         \* [NS -> [listed, hasId, svcRun, alive]]:
                  \*   listed : the BPOfferService is in BPM.offerServices (BPM:53-54)
                  \*   hasId  : hasBlockPoolId() (BPOS:232-234); never cleared by stop/shutdown
                  \*   svcRun : BPServiceActor.shouldServiceRun (BPSA:116)
                  \*   alive  : the actor thread has not run cleanUp() (BPSA:943-946)
    configured,   \* nameservices (as their pools) named in the DN's conf (Scenario 2)
    \* --- DataNode stop (Scenario 3) ---
    dnRun,        \* DataNode.shouldRun (DN:395)
    dnStop,       \* stop path started: "none", "direct" (DN:2545), "gated" (monitor passed)
    \* --- reconfiguration caller, DN.refreshVolumes (all Scenarios) ---
    rpc,          \* "idle", "reading" (DN:1286-1289), "locked" (DN:1290-1372), "done"
    snapList,     \* the CopyOnWriteArrayList snapshot iterated at DN:1287 (BPM:81-83)
    nsInfos,      \* List<NamespaceInfo> built at DN:1286-1289: Seq(NS \cup {Null})
    \* --- addVolume workers (all Scenarios) ---
    wpc,          \* worker program counter (WorkerPcs)
    wi,           \* worker's 1-based index into nsInfos (DS:337 / FDI:536 loops)
    wKeys,        \* keys of the worker's builder.bpStorageDirMap (DS:231-232)
    \* --- target ---
    targetFired   \* DS:259 failed

poolVars   == <<bpMap, bpos, configured>>
dnVars     == <<dnRun, dnStop>>
reconfVars == <<rpc, snapList, nsInfos>>
workerVars == <<wpc, wi, wKeys>>
vars == <<bpMap, bpos, configured, dnRun, dnStop, rpc, snapList, nsInfos,
          wpc, wi, wKeys, targetFired>>

(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
PoolRec   == [listed : BOOLEAN, hasId : BOOLEAN, svcRun : BOOLEAN, alive : BOOLEAN]
WorkerPcs == {"none",      \* not submitted yet
              "start",     \* submitted (DN:1318), about to run FDI.addVolume
              "get",       \* DS:338-340 next, for nsInfos[wi]
              "dirs",      \* DS:341-343 next, for nsInfos[wi]
              "scan",      \* FDI:539-540 next, for nsInfos[wi]
              "build",     \* FDI:559 builder.build() next: TargetCheck is enabled
              "activate",  \* FDI:560 activateVolume next
              "done",      \* addVolume returned
              "failed"}    \* addVolume threw

\* Every enumeration of the finite set S without repetition (a list order).
Orders(S) == {s \in [1..Cardinality(S) -> S] :
                \A i, j \in 1..Cardinality(S) : i # j => s[i] # s[j]}

\* refreshVolumes holds the DataNode monitor from DN:1290 to DN:1372.  No other
\* modeled thread holds it across steps; DNStopMonitorGate acquires it only briefly.
DnMonitorHeld == rpc = "locked"

\* BPSA.shouldRun() == shouldServiceRun && dn.shouldRun() (BPSA:953-955).
ActorShouldRun(b) == bpos[b].svcRun /\ dnRun

(***************************************************************************)
(* Initial state: after MiniDFSCluster.waitActive.  Every pool's actor     *)
(* finished its handshake: initBlockPool -> initStorage ->                 *)
(* loadBlockPoolSliceStorage put the pool's entry (DS:454), and the        *)
(* BPOfferService cached its NamespaceInfo (BPOS:258-260).                 *)
(***************************************************************************)
Init ==
    /\ bpMap = NS
    /\ bpos = [b \in NS |-> [listed |-> TRUE, hasId |-> TRUE,
                             svcRun |-> TRUE, alive |-> TRUE]]
    /\ configured = NS
    /\ dnRun = TRUE
    /\ dnStop = "none"
    /\ rpc = "idle"
    /\ snapList = <<>>
    /\ nsInfos = <<>>
    /\ wpc = [w \in Vols |-> "none"]
    /\ wi = [w \in Vols |-> 0]
    /\ wKeys = [w \in Vols |-> {}]
    /\ targetFired = FALSE

(***************************************************************************)
(* Reconfiguration caller: DN.reconfigurePropertyImpl(dfs.datanode.data.dir)*)
(* (DN:640-670) -> refreshVolumes (DN:1284-1373).  The workload's test     *)
(* thread calls it directly (TestDataNodeHotSwapVolumes:339-342).  One     *)
(* reconfiguration per behavior: a second one is serialized behind the     *)
(* DataNode monitor (DN:1290) and opens no new window.                     *)
(***************************************************************************)

\* DN:1286-1287: nsInfos = new list; the for-each creates its iterator over the
\* unmodifiable view of BPM.offerServices (BPM:81-83), a CopyOnWriteArrayList
\* (BPM:53-54): the iterator is a snapshot.  No DataNode monitor yet.  The list
\* order is the BPOfferServices' creation order; any order is possible across
\* configurations.
RefreshVolumesSnapshot ==
    /\ rpc = "idle"
    /\ \E order \in Orders({b \in NS : bpos[b].listed}) :
          snapList' = order
    /\ nsInfos' = <<>>
    /\ rpc' = "reading"
    /\ UNCHANGED <<poolVars, dnVars, workerVars, targetFired>>

\* DN:1288: nsInfos.add(bpos.getNamespaceInfo()) for the next snapshot entry.
\* BPOS:236-243 returns bpNSInfo under the BPOfferService read lock: null before
\* the handshake (BPOS:258-260), and never cleared by stop or shutdownBlockPool,
\* so an exited pool still yields its NamespaceInfo (analysis-report 4.5).
RefreshVolumesReadNsInfo ==
    /\ rpc = "reading"
    /\ Len(nsInfos) < Len(snapList)
    /\ LET b == snapList[Len(nsInfos) + 1] IN
         nsInfos' = Append(nsInfos, IF bpos[b].hasId THEN b ELSE Null)
    /\ UNCHANGED <<poolVars, dnVars, rpc, snapList, workerVars, targetFired>>

\* DN:1290 synchronized(this) (the DataNode monitor, held until DN:1372).
\* DN:1291-1300: conf.set, parseChangedVolumes: the new locations are Vols.
\* DN:1303-1306: "Attempt to remove all volumes" cannot fire: volumes are added.
\* DN:1308-1313: newLocations is non-empty; one executor thread per location.
\* DN:1316: checkStorageState: data != null once a pool initialised (DN:2275-2278).
\* DN:1317-1329: submit one Callable per location: data.addVolume(location, nsInfos).
RefreshVolumesSubmit ==
    /\ rpc = "reading"
    /\ Len(nsInfos) = Len(snapList)
    /\ ~DnMonitorHeld
    /\ rpc' = "locked"
    /\ wpc' = [w \in Vols |-> "start"]
    /\ UNCHANGED <<poolVars, dnVars, snapList, nsInfos, wi, wKeys, targetFired>>

\* DN:1331-1351: future.get() for every worker, in order; a returned IOException
\* or a thrown Throwable (ExecutionException, DN:1345-1350) marks the volume failed.
\* DN:1354-1363: removeVolumes(none); throw IOException if any volume failed.
\* DN:1364-1371: finally: shutdown the executor, rewrite the conf; DN:1372 leaves
\* the DataNode monitor.
RefreshVolumesFinish ==
    /\ rpc = "locked"
    /\ \A w \in Vols : wpc[w] \in {"done", "failed"}
    /\ rpc' = "done"
    /\ UNCHANGED <<poolVars, dnVars, snapList, nsInfos, workerVars, targetFired>>

(***************************************************************************)
(* addVolume worker w: FsDatasetImpl.addVolume (FDI:514-562), not          *)
(* synchronized.  From DS:340 to DS:254 it holds no monitor and no dataset *)
(* lock the removal path needs; only the new volume's in_use.lock file lock*)
(* (analysis-report 4.2).                                                  *)
(***************************************************************************)

\* FDI:521 -> DS.prepareVolume (DS:324-346), head:
\*   DS:327-331 containsStorageDir(location): false for a new location.
\*   DS:333-334 loadStorageDirectory(datanode, nsInfos.get(0), location, HOTSWAP)
\*     (DS:269-308): analyzeStorage locks the new dir; NOT_FORMATTED -> format
\*     (DS:283-287), whose log argument nsInfo.getNamespaceID() (DS:285) needs a
\*     non-null nsInfos.get(0).
\*   DS:335-336 new VolumeBuilder(this, sd).
\* An empty nsInfos throws IndexOutOfBoundsException and a null nsInfos.get(0) a
\* NullPointerException; neither is the IOException FDI:522 / DN:1323 catch, so
\* the worker ends through DN:1345-1350.  I/O failures of a healthy new dir are
\* outside the brief's scenarios (modeling-brief 3.2).
LoadStorageDirectory(w) ==
    /\ wpc[w] = "start"
    /\ IF Len(nsInfos) = 0
       THEN /\ wpc' = [wpc EXCEPT ![w] = "failed"]          \* DS:334 nsInfos.get(0)
            /\ UNCHANGED wi
       ELSE IF nsInfos[1] = Null
            THEN /\ wpc' = [wpc EXCEPT ![w] = "failed"]     \* DS:285 NPE
                 /\ UNCHANGED wi
            ELSE /\ wpc' = [wpc EXCEPT ![w] = "get"]        \* DS:337 loop, first nsInfo
                 /\ wi' = [wi EXCEPT ![w] = 1]
    /\ UNCHANGED <<poolVars, dnVars, reconfVars, wKeys, targetFired>>

\* DS:337-340, one iteration of the prepareVolume loop for nsInfo = nsInfos[wi]:
\*   DS:338 location.makeBlockPoolDir(nsInfo.getBlockPoolID(), ...): NPE on null.
\*   DS:340 getBlockPoolSliceStorage(nsInfo) (DS:1409-1419, synchronized on the
\*     DataStorage): DS:1412 get; DS:1413-1417 create and put if absent.
\*     This is the worker's first read of the guard operand.
GetBlockPoolSliceStorage(w) ==
    /\ wpc[w] = "get"
    /\ LET n == nsInfos[wi[w]] IN
       IF n = Null
       THEN /\ wpc' = [wpc EXCEPT ![w] = "failed"]          \* DS:338 NPE
            /\ UNCHANGED bpMap
       ELSE /\ bpMap' = bpMap \cup {n}                       \* DS:1412-1417
            /\ wpc' = [wpc EXCEPT ![w] = "dirs"]
    /\ UNCHANGED <<bpos, configured, dnVars, reconfVars, wi, wKeys, targetFired>>

\* DS:341-343, same iteration:
\*   DS:341-342 bpStorage.loadBpStorageDirectories(nsInfo, location, HOTSWAP)
\*     (BPSS:215-235): the "used block storage" check (BPSS:221-225) cannot fire
\*     for a new location; formats and locks <loc>/current/<bpid>.
\*   DS:343 builder.addBpStorageDirectories(bpid, dirs) (DS:244-247): bpid becomes
\*     a key of the builder's bpStorageDirMap.
\* Then DS:337 next iteration, or DS:345 return builder -> FDI:527-533
\* (createFsVolume, new ReplicaMap): thread-local, merged here.
AddBpStorageDirectories(w) ==
    /\ wpc[w] = "dirs"
    /\ wKeys' = [wKeys EXCEPT ![w] = @ \cup {nsInfos[wi[w]]}]
    /\ IF wi[w] < Len(nsInfos)
       THEN /\ wpc' = [wpc EXCEPT ![w] = "get"]             \* DS:337 next nsInfo
            /\ wi' = [wi EXCEPT ![w] = @ + 1]
       ELSE /\ wpc' = [wpc EXCEPT ![w] = "scan"]            \* FDI:536 loop
            /\ wi' = [wi EXCEPT ![w] = 1]
    /\ UNCHANGED <<poolVars, dnVars, reconfVars, targetFired>>

\* FDI:536-546, one iteration for nsInfos[wi]: fsVolume.addBlockPool (FDI:539)
\* and getVolumeMap into the worker's own tempVolumeMap (FDI:540; ReplicaMap with
\* NoLockManager).  The new volume is not in the dataset's volume list yet, so
\* FsDatasetImpl.shutdownBlockPool (FDI:3326-3334) never sees it: no shared state
\* of the model changes and a concurrent pool shutdown cannot make it fail.
\* After the last iteration: FDI:547 no exception; FDI:556-557 obtainReference,
\* setupAsyncLazyPersistThread: thread-local, merged here.
AddBlockPoolAndScan(w) ==
    /\ wpc[w] = "scan"
    /\ IF wi[w] < Len(nsInfos)
       THEN /\ wi' = [wi EXCEPT ![w] = @ + 1]               \* FDI:536 next nsInfo
            /\ UNCHANGED wpc
       ELSE /\ wpc' = [wpc EXCEPT ![w] = "build"]           \* FDI:559 next
            /\ wi' = [wi EXCEPT ![w] = 0]
    /\ UNCHANGED <<poolVars, dnVars, reconfVars, wKeys, targetFired>>

\* TARGET.  FDI:559 builder.build() -> DS:252-266:
\*   DS:253 assert this.sd != null: sd is loadStorageDirectory's non-null result.
\*   DS:254 synchronized (storage): the map is frozen for the whole loop.
\*   DS:255-257 for each key bpid of bpStorageDirMap,
\*   DS:258 bpStorage = this.storage.bpStorageMap.get(bpid),
\*   DS:259 assert bpStorage != null   <-- the check (assertions on in surefire).
\*   DS:260-262 bpStorage.addStorageDir(...); DS:264 storage.addStorageDir(sd).
\* The map is frozen, so iteration order decides only which key fails, not
\* whether one does.
TargetCheck(w) ==
    /\ wpc[w] = "build"
    /\ IF \E b \in wKeys[w] : b \notin bpMap                 \* DS:258-259 phi_T
       THEN /\ targetFired' = TRUE                           \* DS:259 AssertionError
            /\ wpc' = [wpc EXCEPT ![w] = "failed"]           \* -> DN:1345-1350
       ELSE /\ targetFired' = targetFired
            /\ wpc' = [wpc EXCEPT ![w] = "activate"]         \* DS:260-265
    /\ UNCHANGED <<poolVars, dnVars, reconfVars, wi, wKeys>>

\* FDI:560 activateVolume (FDI:433-476, FsDatasetImpl monitor): merges the
\* tempVolumeMap and adds the volume to the dataset; its duplicate-UUID and
\* same-mount checks (FDI:446-468) cannot fire for a fresh dir.  FDI:561 log.
ActivateVolume(w) ==
    /\ wpc[w] = "activate"
    /\ wpc' = [wpc EXCEPT ![w] = "done"]
    /\ UNCHANGED <<poolVars, dnVars, reconfVars, wi, wKeys, targetFired>>

(***************************************************************************)
(* Block-pool shutdown: the only remover of a map key.                     *)
(***************************************************************************)

\* BPSA run loop exit -> cleanUp -> shutdownActor -> DN.shutdownBlockPool:
\*   BPSA:686 / BPSA:931 the loops poll shouldRun() (BPSA:953-955) at least once
\*     per heartbeat (BPSA:790) and exit when it is false.
\*   BPSA:943-946 finally cleanUp() (BPSA:648-654): shouldServiceRun = false
\*     (BPSA:650), bpos.shutdownActor(this) (BPSA:653).
\*   BPOS:476-491 under the BPOfferService write lock: bpServices.remove(actor)
\*     (BPOS:483); this was the last actor (non-HA), so dn.shutdownBlockPool
\*     (BPOS:485-487).
\*   DN:2151-2172 (no DataNode monitor): BPM.remove (DN:2152, BPM:89-111) drops
\*     it from offerServices; if hasBlockPoolId() (DN:2153), BlockScanner (DN:2159-
\*     2161), FsDatasetImpl.shutdownBlockPool (DN:2163-2165, FDI:3326-3334) and
\*     storage.removeBlockPoolStorage(bpId) (DN:2167-2169 -> DS:1421-1423).
ActorExit(b) ==
    /\ bpos[b].alive
    /\ ~ActorShouldRun(b)                                    \* BPSA:953-955
    /\ bpos' = [bpos EXCEPT ![b].svcRun = FALSE,             \* BPSA:650
                            ![b].alive = FALSE,              \* thread ends
                            ![b].listed = FALSE]             \* DN:2152
    /\ bpMap' = IF bpos[b].hasId                             \* DN:2153
                THEN bpMap \ {b}                             \* DN:2168, DS:1422
                ELSE bpMap
    /\ UNCHANGED <<configured, dnVars, reconfVars, workerVars, targetFired>>

\* --- Scenario 1 triggers: the NameNode rejects the DataNode ---------------

\* BPSA:791-799: a heartbeat (or block / cache report) reply is a RemoteException
\* of UnregisteredNodeException, DisallowedDatanodeException or
\* IncorrectVersionException (NN: refreshNodes without this DN in the include
\* list, DatanodeManager.java:1403-1411 / 1871-1874; or a changed registration
\* ID, NameNodeRpcServer.java:1635 / 1777-1787) -> shouldServiceRun = false
\* (BPSA:797); return.  The offerService loop runs only while shouldRun().
OfferServiceRejected(b) ==
    /\ bpos[b].alive
    /\ ActorShouldRun(b)                                     \* BPSA:686
    /\ bpos' = [bpos EXCEPT ![b].svcRun = FALSE]             \* BPSA:797
    /\ UNCHANGED <<bpMap, configured, dnVars, reconfVars, workerVars, targetFired>>

\* BPSA:1453-1469 on the command-processing thread: DNA_REGISTER -> reRegister
\* (BPSA:967-984, runs only if shouldRun()) -> register -> registerDatanode
\* rejected, rethrown at BPSA:856-858 -> BPSA:1461-1468: shouldServiceRun = false.
\* The rejection comes before registrationSucceeded, so no BPOfferService lock is
\* held (no lock coupling with shutdownActor, analysis-report 4.5).
CommandProcessorRejected(b) ==
    /\ bpos[b].alive
    /\ ActorShouldRun(b)                                     \* BPSA:1428, BPSA:968
    /\ bpos' = [bpos EXCEPT ![b].svcRun = FALSE]             \* BPSA:1467
    /\ UNCHANGED <<bpMap, configured, dnVars, reconfVars, workerVars, targetFired>>

\* --- Scenario 2 trigger: refreshNamenodes drops a nameservice --------------

\* Admin RPC DN:3810-3815 or DN.refreshNamenodes(conf) (DN:3806-3808) ->
\* BPM.refreshNamenodes (BPM:148-173) -> doRefreshNamenodes (BPM:175-252):
\*   BPM:165-168 the new conf must name at least one nameservice;
\*   BPM:199-200 toRemove = bpByNameserviceId.keySet() \ new nameservices;
\*   BPM:242-251 Step 4, outside the BPM monitor and any DataNode lock:
\*     bpos.stop() (BPOS:358-362 -> BPSA:622-633: shouldServiceRun = false,
\*     interrupt), bpos.join(); the actor removes itself (ActorExit).
\* Scope: the refresh removes exactly b.  Every other configured nameservice is
\* still served (no toAdd: re-created BPOfferServices are not modeled; their
\* initBlockPool would wait for the DataNode monitor, DN:1441 / DN:2262).
RefreshNamenodesRemove(b) ==
    /\ b \in configured
    /\ bpos[b].listed                                        \* BPM:199-200
    /\ configured \ {b} # {}                                 \* BPM:165-168
    /\ \A c \in configured \ {b} : bpos[c].listed            \* scope: no toAdd
    /\ configured' = configured \ {b}
    /\ bpos' = [bpos EXCEPT ![b].svcRun = FALSE]             \* BPSA:623
    /\ UNCHANGED <<bpMap, dnVars, reconfVars, workerVars, targetFired>>

\* --- Scenario 3 triggers: the DataNode stops ------------------------------

\* "direct": DN.shutdown() (DN:2527-2700) called directly (test thread,
\* MiniDFSCluster.shutdownDataNode / shutdown).  Not for upgrade, shouldRun =
\* false at DN:2544-2546, before its first DataNode-monitor use (DN:2571 ->
\* DN:1603-1606 -> synchronized DN:1632).  The actors then exit on their own;
\* shutDownAll (DN:2662-2668) only stops and joins whatever is left.
DNShutdown ==
    /\ dnStop = "none"
    /\ "direct" \in DnStopModes
    /\ dnStop' = "direct"
    /\ dnRun' = FALSE                                        \* DN:2545
    /\ UNCHANGED <<poolVars, reconfVars, workerVars, targetFired>>

\* "gated": the stopping thread needs the DataNode monitor once before it clears
\* shouldRun; this step is its last monitor acquisition:
\*   shutdownDatanode RPC (synchronized DN:3848) -> async thread (DN:3862-3875);
\*   upgrade shutdown: DN:2571 -> shutdownDirectoryScanner (synchronized DN:1632);
\*   fatal disk error: handleVolumeFailures -> removeVolumes (DN:4084 ->
\*     synchronized DN:1405).
DNStopMonitorGate ==
    /\ dnStop = "none"
    /\ "gated" \in DnStopModes
    /\ ~DnMonitorHeld
    /\ dnStop' = "gated"
    /\ UNCHANGED <<poolVars, dnRun, reconfVars, workerVars, targetFired>>

\* Second half of a gated stop, no monitor: shouldRun = false at DN:2545 (async
\* RPC thread), DN:2595 (upgrade) or DN:2743 (handleDiskError, fatal).
DNStopClearShouldRun ==
    /\ dnStop = "gated"
    /\ dnRun
    /\ dnRun' = FALSE
    /\ UNCHANGED <<poolVars, dnStop, reconfVars, workerVars, targetFired>>

(***************************************************************************)
(* Next state                                                              *)
(***************************************************************************)
WorkerStep(w) ==
    \/ LoadStorageDirectory(w)
    \/ GetBlockPoolSliceStorage(w)
    \/ AddBpStorageDirectories(w)
    \/ AddBlockPoolAndScan(w)
    \/ TargetCheck(w)
    \/ ActivateVolume(w)

PoolStep(b) ==
    \/ OfferServiceRejected(b)
    \/ CommandProcessorRejected(b)
    \/ RefreshNamenodesRemove(b)
    \/ ActorExit(b)

\* Once the check failed every other step stops (adhoc tla-patterns 1).
Next ==
    /\ ~targetFired
    /\ \/ RefreshVolumesSnapshot
       \/ RefreshVolumesReadNsInfo
       \/ RefreshVolumesSubmit
       \/ RefreshVolumesFinish
       \/ \E w \in Vols : WorkerStep(w)
       \/ \E b \in NS : PoolStep(b)
       \/ DNShutdown
       \/ DNStopMonitorGate
       \/ DNStopClearShouldRun

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)
TypeOK ==
    /\ bpMap \subseteq NS
    /\ bpos \in [NS -> PoolRec]
    /\ configured \subseteq NS
    /\ dnRun \in BOOLEAN
    /\ dnStop \in {"none", "direct", "gated"}
    /\ rpc \in {"idle", "reading", "locked", "done"}
    /\ snapList \in Seq(NS)
    /\ nsInfos \in Seq(NS \cup {Null})
    /\ Len(nsInfos) <= Len(snapList)
    /\ wpc \in [Vols -> WorkerPcs]
    /\ wi \in [Vols -> 0..Cardinality(NS)]
    /\ wKeys \in [Vols -> SUBSET NS]
    /\ targetFired \in BOOLEAN

\* The oracle (brief section 5): build() never finds a recorded pool missing
\* from bpStorageMap.
TargetSafe == ~targetFired

\* Structural sanity (brief section 5): a pool leaves the map only when its last
\* actor has exited (DN:2168 is the only remover).
RemovalOnlyByShutdown == \A b \in NS : b \notin bpMap => ~bpos[b].alive

\* Structural sanity (brief section 5): a builder records only pools of its own
\* snapshot (DS:337-343): "a message carries only values its sender held".
BuilderKeysFromSnapshot ==
    \A w \in Vols : wKeys[w] \subseteq ({nsInfos[i] : i \in DOMAIN nsInfos} \ {Null})

=============================================================================
