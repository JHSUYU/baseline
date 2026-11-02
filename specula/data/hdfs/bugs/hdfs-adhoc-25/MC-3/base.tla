-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-25: the ad hoc check at                                      *)
(*   BlockPoolSliceStorage.loadStorageDirectory, BlockPoolSliceStorage.java *)
(*   :184-185                                                               *)
(*     if (getCTime() != nsInfo.getCTime())                                 *)
(*       throw new IOException("Datanode CTime (=...) is not equal to       *)
(*                              namenode CTime (=...)");                    *)
(* reached when doTransition (BPSS:369-425) returned false.                 *)
(*                                                                          *)
(* Tree pinned at 734dd8a67cd. Path abbreviations (all under               *)
(* hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/):  *)
(*   BPSS = server/datanode/BlockPoolSliceStorage.java                      *)
(*   DS   = server/datanode/DataStorage.java                                *)
(*   DN   = server/datanode/DataNode.java                                   *)
(*   BPOS = server/datanode/BPOfferService.java                             *)
(*   BPSA = server/datanode/BPServiceActor.java                             *)
(*   FSD  = server/datanode/fsdataset/impl/FsDatasetImpl.java               *)
(*   ST   = server/common/Storage.java                                      *)
(*   SI   = server/common/StorageInfo.java                                  *)
(*   SL   = server/datanode/StorageLocation.java                            *)
(*   FSI  = server/namenode/FSImage.java                                    *)
(*   NNRPC = server/namenode/NameNodeRpcServer.java                         *)
(*                                                                          *)
(* Category A (NameNode/DataNode coordination through the RPC handshake    *)
(* and on-disk VERSION files), with Category B split windows for the      *)
(* hot-swap pool threads that share one BlockPoolSliceStorage object       *)
(* (modeling brief, Section 1).                                            *)
(*                                                                          *)
(* Scenarios (modeling brief, Section 2):                                  *)
(*   S1  PROVIDED location checked against another location's leftover     *)
(*       cTime in the startup loop.                                        *)
(*   S2  concurrent hot-swap loads race on the shared object.             *)
(*   S3  leftover state or namespace-info drift after the startup loop.   *)
(*                                                                          *)
(* Abstractions, each justified in the brief (Section 3.2) or below:      *)
(*   - cTimes are order-preserving ranks (naturals). NoCT = no value.     *)
(*   - The layout version of every block-pool VERSION is the current      *)
(*     DataNode LV: all writers store it (BPSS:287, 188, 509), and the    *)
(*     workload fixture never writes a block-pool VERSION with another LV *)
(*     (UpgradeUtilities.java:503-511 writes only federation LVs). So     *)
(*     the LV conjuncts of BPSS:404, 408 and 414 are constant.            *)
(*   - namespaceID / blockpoolID are constant per block pool; a VERSION   *)
(*     with a foreign id only comes from the test fixture (bpBad).        *)
(*   - Block files, hard links, trash, rolling-upgrade markers and        *)
(*     finalize are not modeled (they never write the shared fields).    *)
(*   - Disk IO errors inside an upgrade are not modeled.                  *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Loc,            \* storage locations, numbered in config-file order (naturals)
    ProvidedLoc,    \* the PROVIDED locations (subset of Loc); the rest are DISK
    InitConf,       \* locations in dfs.datanode.data.dir initially
    InitFormatted,  \* DISK locations that hold block-pool data (at InitCT) initially
    SwapLocs,       \* locations an operator may hot-add by reconfiguration
    NN,             \* NameNodes that serve the block pool (two = HA)
    SwapWidth,      \* max hot-swap pool threads in one reconfiguration
    InitCT,         \* NameNode cTime at format
    MaxCT           \* bound on cTime ranks (type invariant only)

ASSUME /\ Loc \subseteq Nat
       /\ ProvidedLoc \subseteq Loc
       /\ InitConf \subseteq Loc /\ SwapLocs \subseteq Loc
       /\ InitFormatted \subseteq Loc \ ProvidedLoc
       /\ NN # {}
       /\ SwapWidth \in Nat /\ InitCT \in Nat /\ MaxCT \in Nat

\* One PROVIDED location per DataNode (fault model, Phase 3). Every PROVIDED
\* directory gets the one configured storage ID (DataStorage.createStorageID,
\* DS:150-156, "Only one provided storage id is supported"), and
\* FsDatasetImpl.activateVolume rejects a duplicate storage UUID (FSD:446-453);
\* SL:122 states the same assumption. A second PROVIDED location is an
\* unsupported configuration.
ASSUME Cardinality(ProvidedLoc) <= 1

NoCT   == -1     \* no VERSION / no previous / null nsInfo
NoBpss == -2     \* bpStorageMap holds no BlockPoolSliceStorage for the block pool

DiskLoc == Loc \ ProvidedLoc

\* Load threads: 0 is the thread that runs initBlockPool -> initStorage (the
\* startup loader); 1..SwapWidth are refreshVolumes pool threads (DN:1312-1329).
ST     == 0
HsThr  == 1..SwapWidth
Thr    == {ST} \cup HsThr

Opts == {"REGULAR", "ROLLBACK"}

----------------------------------------------------------------------------
(***************************************************************************)
(* Variables                                                               *)
(***************************************************************************)

\* NameNode side (one value per NameNode of the nameservice).
VARIABLES
    nnCT,       \* cTime the NameNode reports in versionRequest (FSI:465)
    nnPrev,     \* cTime of the NameNode's previous fs state (upgrade not finalized), NoCT if none
    issued      \* every cTime a NameNode format/upgrade produced (provenance)

\* On-disk state per location (S1, S2: source of leftover cTimes; crash recovery).
\* PROVIDED locations have no block-pool directory: all NoCT.
VARIABLES
    ver,        \* block-pool current/VERSION cTime, NoCT if absent
    prev,       \* block-pool previous/VERSION cTime, NoCT if no previous dir
    ptmp,       \* block-pool previous.tmp/VERSION cTime, NoCT if absent
    dnVer,      \* DataNode-level VERSION: "none" (empty dir), "cur", "old" (pre-federation
                \* layout), "bad" (load throws: newer LV, SI:216-221; pre-federation
                \* namespaceID mismatch, DS:739-745; clusterID mismatch, DS:748-753)
    bpBad       \* block-pool VERSION ids: "ok", "badNs", "badBp" (only the test fixture writes bad ids)

\* DataNode process.
VARIABLES
    dnUp,       \* the DataNode process runs
    dnOpt,      \* its startup option (DN:2256 getStartupOption)
    confFile,   \* dfs.datanode.data.dir in the configuration file (sequence)
    dataDirs,   \* DataNode.dataDirs in memory (DN:1891, DN:1370)
    dsDirs,     \* DataStorage storage directories (DataNode-level volumes loaded)
    dataInit    \* FsDataset created (DN:2275-2279); refreshVolumes needs it (DN:3839-3845)

\* The shared BlockPoolSliceStorage object (S1-S3) and the BPOfferService.
VARIABLES
    bpssCT,     \* its cTime field (SI:50, plain long), NoBpss if no object
    bpssDirs,   \* its block-pool storage directories (by location)
    bpNS,       \* BPOfferService.bpNSInfo cTime (BPOS:236-265), NoCT if null
    bposLive,   \* the BPOfferService is registered with the BlockPoolManager
    actor       \* BPServiceActor per NameNode: "conn", "init", "run", "dead"

\* Startup loader: one thread inside initStorage, under the BPOS write lock
\* (BPOS:384) and the DataNode monitor (DN:2262-2264).
VARIABLES
    ldPhase,    \* "idle", "dn" (DS:408-431), "join" (DS:479-498 after the BP loop), "bp"
    ldOwner,    \* the NameNode whose actor runs initBlockPool
    ldNs,       \* the nsInfo cTime of this init (DN:2186)
    ldQ,        \* locations not yet visited by the current loop (sequence)
    ldDnOK,     \* DataNode-level successes in loop order (DS:416-418)
    ldDnPend,   \* DataNode-level upgrades queued as callables (DS:419-423)
    ldAnyOK,    \* some block-pool directory loaded (DS:466-469, 490)
    ldPend      \* locations with a queued block-pool upgrade callable (DS:471)

\* Block-pool load threads (BPSS.loadBpStorageDirectories / loadStorageDirectory).
VARIABLES
    pc,         \* program counter per thread
    tLoc        \* location the thread loads

\* Hot-swap reconfiguration (S2, S3).
VARIABLES
    hsActive,   \* refreshVolumes runs (it holds the DataNode monitor, DN:1290)
    hsNs,       \* the nsInfos snapshot (DN:1286-1289)
    hsDeact     \* deactivateLocations, removed after the adds (DN:1355)

\* The target.
VARIABLE targetFired

nnVars   == <<nnCT, nnPrev, issued>>
diskVars == <<ver, prev, ptmp, dnVer, bpBad>>
dnVars   == <<dnUp, dnOpt, confFile, dataDirs, dsDirs, dataInit>>
bpVars   == <<bpssCT, bpssDirs, bpNS, bposLive, actor>>
ldVars   == <<ldPhase, ldOwner, ldNs, ldQ, ldDnOK, ldDnPend, ldAnyOK, ldPend>>
thrVars  == <<pc, tLoc>>
hsVars   == <<hsActive, hsNs, hsDeact>>

vars == <<nnVars, diskVars, dnVars, bpVars, ldVars, thrVars, hsVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
MaxIssued == Max(issued)

SeqToSet(s) == {s[i] : i \in DOMAIN s}

\* Locations of S in config-file order (locations are numbered in that order;
\* TLC configs cannot hold sequences).
RECURSIVE InOrder(_)
InOrder(S) == IF S = {} THEN <<>>
              ELSE LET m == CHOOSE x \in S : \A y \in S : x <= y
                   IN <<m>> \o InOrder(S \ {m})

IsProvided(l) == l \in ProvidedLoc

\* nsInfo cTime and startup option the thread loads with.
NsOf(t)  == IF t = ST THEN ldNs ELSE hsNs
OptOf(t) == IF t = ST THEN dnOpt ELSE "HOTSWAP"     \* DS:341-342 passes HOTSWAP
\* callables: non-null at startup (DS:462-465), null for hot swap (DS:341-342).
Deferred(t) == t = ST

AnyLoc == CHOOSE x \in Loc : TRUE
AnyNN  == CHOOSE n \in NN : TRUE

\* DataStorage.getBlockPoolSliceStorage (DS:1409-1419, synchronized): returns the
\* object in bpStorageMap, or creates one with nsInfo.getCTime() (DS:1414-1415).
GetBpss(ns) == IF bpssCT = NoBpss THEN ns ELSE bpssCT

\* DataNode-level load of location l, DataStorage.loadStorageDirectory (DS:269-308)
\* with doTransition (DS:719-780), for the dnVer abstraction:
\*   "ok"     PROVIDED (DS:722-725); empty dir -> format (DS:283-287, 571-582) then
\*            regular; current LV -> regular (DS:756-759)
\*   "preFed" pre-federation LV -> doUpgradePreFederation (DS:762-770, 804-850)
\*   "fail"   "bad": IncorrectVersionException (SI:216-221), pre-federation
\*            namespaceID mismatch (DS:739-745), clusterID mismatch (DS:748-753);
\*            none of them touches the block-pool storage object
\* ROLLBACK at DataNode level (DS:726-728) only matters with a DataNode-level
\* previous dir, which exists only after a pre-federation upgrade; not modeled
\* (DS:924-932: no previous -> layout-version rewrite only).
DnOutcome(l) ==
    IF IsProvided(l) THEN "ok"
    ELSE CASE dnVer[l] \in {"none", "cur"} -> "ok"
           [] dnVer[l] = "old"             -> "preFed"
           [] OTHER                        -> "fail"

\* Block-pool directory re-formatted by doUpgradePreFederation: the old current
\* (with the block pool) is renamed to previous.tmp (DS:831), then
\* bpStorage.format(curDir, nsInfo) (DS:834-836 -> BPSS:271-275 -> BPSS:283-292)
\* writes the shared fields (cTime := nsInfo cTime, BPSS:288) and a fresh VERSION.
PreFedFormat(l, ns) ==
    /\ bpssCT' = ns
    /\ ver'  = [ver  EXCEPT ![l] = ns]
    /\ prev' = [prev EXCEPT ![l] = NoCT]
    /\ ptmp' = [ptmp EXCEPT ![l] = NoCT]

----------------------------------------------------------------------------
(***************************************************************************)
(* Thread bookkeeping                                                      *)
(*                                                                         *)
(* Goto and FinishLoad set exactly <<pc, tLoc, ldQ, ldPhase, ldAnyOK,      *)
(* ldPend, bpssDirs, dsDirs>>.                                             *)
(***************************************************************************)

Goto(t, s) ==
    /\ pc' = [pc EXCEPT ![t] = s]
    /\ UNCHANGED <<tLoc, ldQ, ldPhase, ldAnyOK, ldPend, bpssDirs, dsDirs>>

\* Thread t finished loading tLoc[t]; outcome \in {"ok", "deferred", "fail"}.
FinishLoad(t, outcome) ==
    LET l == tLoc[t] IN
    IF t = ST
    THEN \* DS:464-476. recoverTransitionRead added the directory to the shared
         \* object also when its upgrade is only queued (BPSS:257-261).
         /\ bpssDirs' = IF outcome \in {"ok", "deferred"}
                          THEN bpssDirs \cup {l} ELSE bpssDirs
         /\ ldAnyOK' = (ldAnyOK \/ outcome = "ok")                   \* DS:466-469
         /\ ldPend'  = IF outcome = "deferred"                       \* DS:470-472
                          THEN ldPend \cup {l} ELSE ldPend
         \* "fail": DS:473-476 logs the exception and the loop continues.
         /\ IF ldQ # <<>>
            THEN \* DS:459-460 next location (makeBlockPoolDir), DS:464
                 /\ pc'   = [pc EXCEPT ![ST] = "contains"]
                 /\ tLoc' = [tLoc EXCEPT ![ST] = Head(ldQ)]
                 /\ ldQ'  = Tail(ldQ)
                 /\ ldPhase' = ldPhase
            ELSE \* loop done: DS:479-498 submits and joins the callables
                 /\ pc' = [pc EXCEPT ![ST] = "idle"]
                 /\ ldPhase' = "join"
                 /\ UNCHANGED <<tLoc, ldQ>>
         /\ UNCHANGED dsDirs
    ELSE \* hot-swap pool thread, FsDatasetImpl.addVolume (FSD:515-562)
         /\ pc' = [pc EXCEPT ![t] = IF outcome = "ok" THEN "ok" ELSE "fail"]
         /\ IF outcome = "ok"
            THEN \* FSD:559 builder.build() -> DS:252-266
                 /\ bpssDirs' = bpssDirs \cup {l}
                 /\ dsDirs'   = dsDirs \cup {l}
            ELSE \* FSD:521-525, DN:1323-1324: volume not added
                 UNCHANGED <<bpssDirs, dsDirs>>
         /\ UNCHANGED <<tLoc, ldQ, ldPhase, ldAnyOK, ldPend>>

\* Variables a block-pool load step never changes.
BpFrame == UNCHANGED <<nnVars, dnVer, bpBad, dnUp, dnOpt, confFile, dataDirs,
                       dataInit, bpNS, bposLive, actor, ldOwner, ldNs, ldDnOK,
                       ldDnPend, hsVars>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Initial state: the cluster has been running at InitCT; the DataNode    *)
(* process has just started with REGULAR (DN:1884-1959) and its actors are *)
(* connecting.                                                             *)
(***************************************************************************)

Init ==
    /\ nnCT   = [n \in NN |-> InitCT]
    /\ nnPrev = [n \in NN |-> NoCT]
    /\ issued = {InitCT}
    /\ ver    = [x \in Loc |-> IF x \in InitFormatted THEN InitCT ELSE NoCT]
    /\ prev   = [x \in Loc |-> NoCT]
    /\ ptmp   = [x \in Loc |-> NoCT]
    /\ dnVer  = [x \in Loc |-> IF x \in InitFormatted THEN "cur" ELSE "none"]
    /\ bpBad  = [x \in Loc |-> "ok"]
    /\ dnUp = TRUE
    /\ dnOpt = "REGULAR"
    /\ confFile = InOrder(InitConf)
    /\ dataDirs = InOrder(InitConf)
    /\ dsDirs = {}
    /\ dataInit = FALSE
    /\ bpssCT = NoBpss                 \* DS:107-108, 111-115: fresh DataStorage, empty map
    /\ bpssDirs = {}
    /\ bpNS = NoCT
    /\ bposLive = TRUE                 \* DN:1958-1959 refreshNamenodes starts the actors
    /\ actor = [n \in NN |-> "conn"]
    /\ ldPhase = "idle" /\ ldOwner = AnyNN /\ ldNs = NoCT
    /\ ldQ = <<>> /\ ldDnOK = <<>> /\ ldDnPend = <<>>
    /\ ldAnyOK = FALSE /\ ldPend = {}
    /\ pc = [t \in Thr |-> "idle"]
    /\ tLoc = [t \in Thr |-> AnyLoc]
    /\ hsActive = FALSE /\ hsNs = NoCT /\ hsDeact = {}
    /\ targetFired = FALSE

----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode cTime lifecycle (environment: operator restarts a NameNode).  *)
(***************************************************************************)

\* NameNode -upgrade: FSImage.doUpgrade (FSI:455-465). checkUpgrade
\* (FSI:423-433, called at FSI:456) refuses while a previous fs state exists.
\* The new cTime is now() (FSI:465): later than every cTime issued before.
\* With HA (|NN| = 2) the whole nameservice moves (Phase 3, fault model): the
\* documented HA upgrade shuts down all NameNodes, upgrades one, and
\* re-bootstraps the other from it with -bootstrapStandby
\* (HDFSHighAvailabilityWithQJM.md:705-725), so two running NameNodes never
\* report different cTimes. A NameNode left serving the old cTime would be an
\* operator deviation from that procedure. With one NameNode this is the same
\* as updating n alone.
NNUpgrade(n) ==
    /\ nnPrev[n] = NoCT                                   \* FSI:428-431
    /\ MaxIssued < MaxCT                                  \* rank domain of the model, not code
    /\ LET c == MaxIssued + 1 IN                          \* FSI:465
         \* FSI:481 doPreUpgrade (current -> previous.tmp), FSI:504 doUpgrade
         \* (previous.tmp -> previous): the old state is kept as previous
         /\ nnPrev' = [m \in NN |-> nnCT[n]]
         /\ nnCT'   = [m \in NN |-> c]
         /\ issued' = issued \cup {c}
    /\ UNCHANGED <<diskVars, dnVars, bpVars, ldVars, thrVars, hsVars, targetFired>>

\* NameNode -rollback: FSImage.doRollback (FSI:521-572) needs a previous fs
\* state (FSI:529-552) and restores it, i.e. the cTime before the upgrade.
\* HA: both NameNodes are shut down, the rollback runs on the upgraded one and
\* the other is re-bootstrapped from it (HDFSHighAvailabilityWithQJM.md:733).
NNRollback(n) ==
    /\ nnPrev[n] # NoCT
    /\ nnCT'   = [m \in NN |-> nnPrev[n]]
    /\ nnPrev' = [m \in NN |-> NoCT]
    /\ UNCHANGED <<issued, diskVars, dnVars, bpVars, ldVars, thrVars, hsVars,
                   targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Environment: disk replacement and the workload's test fixture.          *)
(***************************************************************************)

\* An operator replaces the disk behind DISK location l with an empty one
\* (S1 second source: a directory formatted after a NameNode -upgrade has no
\* previous). Only while the DataNode does not use l.
DiskReplace(l) ==
    /\ l \in DiskLoc
    /\ \/ ~dnUp
       \/ /\ l \notin dsDirs /\ l \notin SeqToSet(dataDirs)
          /\ ldPhase = "idle" /\ ~hsActive
    /\ ver'   = [ver   EXCEPT ![l] = NoCT]
    /\ prev'  = [prev  EXCEPT ![l] = NoCT]
    /\ ptmp'  = [ptmp  EXCEPT ![l] = NoCT]
    /\ dnVer' = [dnVer EXCEPT ![l] = "none"]
    /\ bpBad' = [bpBad EXCEPT ![l] = "ok"]
    /\ UNCHANGED <<nnVars, dnVars, bpVars, ldVars, thrVars, hsVars, targetFired>>

\* TRACE ONLY (not in Next): the workload's fixture rewrites the VERSION files of
\* a stopped DataNode (TestDFSStartupVersions.java:267-271 ->
\* UpgradeUtilities.java:372-395 copy of the master storage, 482-512 VERSION
\* rewrite). It writes the guard's left-operand source (the block-pool VERSION
\* cTime), so it is an environment action that MC configs exclude (brief S1).
FixtureWriteVersion(l, dv, bct, bad) ==
    /\ ~dnUp
    /\ l \in DiskLoc
    /\ dnVer' = [dnVer EXCEPT ![l] = dv]
    /\ ver'   = [ver   EXCEPT ![l] = bct]
    /\ prev'  = [prev  EXCEPT ![l] = NoCT]
    /\ ptmp'  = [ptmp  EXCEPT ![l] = NoCT]
    /\ bpBad' = [bpBad EXCEPT ![l] = bad]
    /\ UNCHANGED <<nnVars, dnVars, bpVars, ldVars, thrVars, hsVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* DataNode process lifecycle                                              *)
(***************************************************************************)

\* The DataNode process stops (shutdown or crash) at any point. Memory is lost:
\* DataStorage, the shared object, the BPOfferService, load threads, queued
\* callables. Disks keep their state; a crash inside an upgrade or rollback
\* leaves previous.tmp, which ST:761-768 / ST:797-807 recover at the next start.
DNStop ==
    /\ dnUp
    /\ dnUp' = FALSE
    /\ dataDirs' = <<>>
    /\ dsDirs' = {}
    /\ dataInit' = FALSE
    /\ bpssCT' = NoBpss
    /\ bpssDirs' = {}
    /\ bpNS' = NoCT
    /\ bposLive' = FALSE
    /\ actor' = [n \in NN |-> "dead"]
    /\ ldPhase' = "idle" /\ ldNs' = NoCT
    /\ ldQ' = <<>> /\ ldDnOK' = <<>> /\ ldDnPend' = <<>>
    /\ ldAnyOK' = FALSE /\ ldPend' = {}
    /\ pc' = [t \in Thr |-> "idle"]
    /\ hsActive' = FALSE /\ hsNs' = NoCT /\ hsDeact' = {}
    /\ UNCHANGED <<nnVars, diskVars, dnOpt, confFile, tLoc, ldOwner, targetFired>>

\* A new DataNode process: DataNode.startDataNode (DN:1884-1959). dataDirs come
\* from the configuration in order (DN:3312-3334; StorageLocationChecker keeps
\* the order and PROVIDED is always healthy, SL:283-294). storage = new
\* DataStorage() (DN:1931) has an empty bpStorageMap (DS:107-108).
\* refreshNamenodes (DN:1959) starts one actor per NameNode (BPSA:900-909).
DNStartConf(opt, dirs) ==
    /\ ~dnUp
    /\ opt \in Opts
    /\ dnUp' = TRUE
    /\ dnOpt' = opt
    /\ confFile' = dirs
    /\ dataDirs' = dirs
    /\ bposLive' = TRUE
    /\ actor' = [n \in NN |-> "conn"]
    /\ UNCHANGED <<nnVars, diskVars, dsDirs, dataInit, bpssCT, bpssDirs, bpNS,
                   ldVars, thrVars, hsVars, targetFired>>

DNStart(opt) == DNStartConf(opt, confFile)

----------------------------------------------------------------------------
(***************************************************************************)
(* BPOfferService / BPServiceActor                                         *)
(***************************************************************************)

\* BPServiceActor.connectToNNAndHandshake (BPSA:302-325): retrieveNamespaceInfo
\* returns NameNode n's cTime (BPSA:308); verifyAndSetNamespaceInfo
\* (BPOS:382-415) holds the BPOS write lock (BPOS:384), i.e. waits for an
\* initBlockPool that is running.
Handshake(n) ==
    /\ dnUp /\ bposLive
    /\ actor[n] = "conn"
    /\ ldPhase = "idle"                                   \* BPOS:384
    /\ LET ns == nnCT[n] IN
       IF bpNS = NoCT
       THEN \* BPOS:394-401: no cached nsInfo -> setNamespaceInfo, then
            \* DN.initBlockPool (DN:2185-2199) -> initStorage (DN:2251-2264),
            \* which needs the DataNode monitor (DN:2262) that refreshVolumes
            \* holds for its whole run (DN:1290).
            /\ ~hsActive
            /\ bpNS' = ns
            /\ actor' = [actor EXCEPT ![n] = "init"]
            /\ ldPhase' = "dn" /\ ldOwner' = n /\ ldNs' = ns
            \* DN:2263 storage.recoverTransitionRead(this, nsInfo, dataDirs, startOpt)
            \* -> DS:564-569 -> addStorageLocations (DS:382-401) -> loadDataStorage
            /\ ldQ' = dataDirs
            /\ ldDnOK' = <<>> /\ ldDnPend' = <<>>
            /\ ldAnyOK' = FALSE /\ ldPend' = {}
       ELSE \* BPOS:245-262: cached nsInfo set -> only block pool ID, namespace ID
            \* and cluster ID are compared (BPOS:250-257); the cTime is replaced
            \* without reloading storage (BPOS:258). BPSA:324 register; BPSA:926.
            /\ bpNS' = ns
            /\ actor' = [actor EXCEPT ![n] = "run"]
            /\ UNCHANGED ldVars
    /\ UNCHANGED <<nnVars, diskVars, dnVars, bpssCT, bpssDirs, bposLive,
                   thrVars, hsVars, targetFired>>

\* Heartbeats and block reports pass NNRPC verifyRequest (NNRPC:1635, 1647,
\* 1777-1787): the registration ID is NS-nsid-cid-cTime of the DataNode's live
\* block-pool storage object (DN:2073-2089, DatanodeRegistration.java:91-92,
\* ST:1417-1421). A cTime that differs from NameNode n's raises
\* UnregisteredNodeException and the actor exits (BPSA:791-798).
ActorRejected(n) ==
    /\ dnUp /\ actor[n] = "run"
    /\ bpssCT # nnCT[n]
    /\ actor' = [actor EXCEPT ![n] = "dead"]
    \* BPSA:945 cleanUp (BPSA:648-654) -> BPOS.shutdownActor (BPOS:476-490): the
    \* last actor shuts the block pool down (DN:2151-2172). The block pool id is
    \* set, so the object leaves bpStorageMap (DS:1421-1423); threads that hold
    \* it keep using it, and no new one is created in this process (no actor
    \* is left to init, and refreshVolumes finds no BPOfferService).
    /\ bposLive' = (\E m \in NN \ {n} : actor[m] # "dead")
    /\ UNCHANGED <<nnVars, diskVars, dnVars, bpssCT, bpssDirs, bpNS, ldVars,
                   thrVars, hsVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Startup: DataStorage.addStorageLocations (DS:382-401)                   *)
(***************************************************************************)

\* DataStorage.loadDataStorage loop (DS:408-431), one location per step.
DNLevelLoad ==
    /\ dnUp /\ ldPhase = "dn" /\ ldQ # <<>>
    /\ LET l == Head(ldQ) IN
       /\ ldQ' = Tail(ldQ)
       /\ IF l \in dsDirs
          THEN \* DS:427-430: already loaded by an earlier init of this process
               /\ ldDnOK' = Append(ldDnOK, l)
               /\ UNCHANGED <<diskVars, dsDirs, bpssCT, ldDnPend>>
          ELSE CASE DnOutcome(l) = "ok" ->
                      \* DS:414-418: no callables -> addStorageDir, success
                      /\ ldDnOK' = Append(ldDnOK, l)
                      /\ dsDirs' = dsDirs \cup {l}
                      /\ dnVer' = IF IsProvided(l) THEN dnVer
                                  ELSE [dnVer EXCEPT ![l] = "cur"]   \* DS:283-287 format
                      /\ UNCHANGED <<ver, prev, ptmp, bpBad, bpssCT, ldDnPend>>
                 [] DnOutcome(l) = "preFed" ->
                      \* DS:768 -> DS:804-850; the bpss is created here if absent
                      \* (DS:835 -> DS:1409-1419); callable queued (DS:842-848, 419-423)
                      /\ PreFedFormat(l, ldNs)
                      /\ ldDnPend' = Append(ldDnPend, l)
                      /\ UNCHANGED <<dnVer, bpBad, dsDirs, ldDnOK>>
                 [] OTHER ->
                      \* "bad" VERSION: DS:424-426 logs, location dropped
                      /\ UNCHANGED <<diskVars, dsDirs, bpssCT, ldDnOK, ldDnPend>>
    /\ UNCHANGED <<nnVars, dnUp, dnOpt, confFile, dataDirs, dataInit, bpssDirs,
                   bpNS, bposLive, actor, ldPhase, ldOwner, ldNs, ldAnyOK,
                   ldPend, thrVars, hsVars, targetFired>>

\* DS:433-447: the DataNode-level upgrade callables are joined; each finishes
\* doUpgrade (DS:852-866; upgradeProperties DS:868-876 stores the current LV)
\* and joins the success list after the non-upgraded ones (DS:437-438).
\* Then DS:392-397: no success -> empty result (init fails, DS:566-567); else
\* loadBlockPoolSliceStorage (DS:450-501) over the success list in order.
DNLevelJoin ==
    /\ dnUp /\ ldPhase = "dn" /\ ldQ = <<>>
    /\ LET succ == ldDnOK \o ldDnPend IN
       /\ dnVer' = [x \in Loc |-> IF x \in SeqToSet(ldDnPend) THEN "cur" ELSE dnVer[x]]
       /\ dsDirs' = dsDirs \cup SeqToSet(ldDnPend)          \* DS:437
       /\ IF succ = <<>>
          THEN \* DS:392-394
               /\ ldPhase' = "join"
               /\ UNCHANGED <<bpssCT, ldQ, thrVars>>
          ELSE \* DS:454 getBlockPoolSliceStorage; DS:459-460 first location
               /\ bpssCT' = GetBpss(ldNs)
               /\ ldPhase' = "bp"
               /\ pc'   = [pc EXCEPT ![ST] = "contains"]
               /\ tLoc' = [tLoc EXCEPT ![ST] = Head(succ)]
               /\ ldQ'  = Tail(succ)
    /\ UNCHANGED <<nnVars, ver, prev, ptmp, bpBad, dnUp, dnOpt, confFile,
                   dataDirs, dataInit, bpssDirs, bpNS, bposLive, actor, ldOwner,
                   ldNs, ldDnOK, ldDnPend, ldAnyOK, ldPend, hsVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Block-pool load of one location by thread t                            *)
(* BPSS.loadBpStorageDirectories (BPSS:215-235) ->                         *)
(* BPSS.loadStorageDirectory (BPSS:149-197) -> doTransition (BPSS:369-425) *)
(*                                                                         *)
(* Steps are split at every access to the shared object's fields: the     *)
(* cTime writes at BPSS:288, 345 (via 388) and 512, the reads at BPSS:405, *)
(* 415 and 184, and the serializations at BPSS:291, 189 and 513            *)
(* (setPropertiesFromFields BPSS:317-323). Hot-swap threads take no lock   *)
(* on this path (brief S2; the block-pool directory is "shared", so        *)
(* locking is disabled, BPSS:153-154 and ST:906-910).                      *)
(***************************************************************************)

\* BPSS:221-225: a location whose block-pool directory the object already holds
\* is refused (SL:114-128: same PROVIDED location, or same local directory).
BpContains(t) ==
    /\ pc[t] = "contains"
    /\ IF tLoc[t] \in bpssDirs
       THEN FinishLoad(t, "fail")           \* BPSS:222-224, rethrown BPSS:229-232
       ELSE Goto(t, "analyze")              \* BPSS:226 -> BPSS:153-154
    /\ UNCHANGED <<bpssCT, ver, prev, ptmp, targetFired>>
    /\ BpFrame

\* BPSS:156-175: sd.analyzeStorage (ST:659-781), then format or recovery.
BpAnalyze(t) ==
    /\ pc[t] = "analyze"
    /\ LET l == tLoc[t] IN
       IF IsProvided(l)
       THEN \* ST:663-667: PROVIDED storage is always NORMAL (BPSS:159-160)
            /\ Goto(t, "trans")
            /\ UNCHANGED <<bpssCT, ver, prev, ptmp>>
       ELSE \* DISK. makeBlockPoolDir (SL:257-281) created the root first (DS:460,
            \* DS:338), so ST:673-685 does not apply and HOTSWAP does not short-cut
            \* to NOT_FORMATTED (ST:704-710, hadMkdirs false). BPSS:738-741 makes
            \* ST:712-714 a no-op. Temp dirs other than previous.tmp never exist here.
            CASE ptmp[l] = NoCT /\ ver[l] # NoCT ->
                   \* ST:727-731 NORMAL (BPSS:159-160)
                   /\ Goto(t, "trans")
                   /\ UNCHANGED <<bpssCT, ver, prev, ptmp>>
              [] ptmp[l] = NoCT /\ ver[l] = NoCT /\ prev[l] # NoCT ->
                   \* ST:732-734 "version file in current directory is missing"
                   /\ FinishLoad(t, "fail")
                   /\ UNCHANGED <<bpssCT, ver, prev, ptmp>>
              [] ptmp[l] = NoCT /\ ver[l] = NoCT /\ prev[l] = NoCT ->
                   \* ST:735-738 NOT_FORMATTED -> BPSS:167-171 format(sd, nsInfo):
                   \* BPSS:286 clearDirectory; BPSS:287-290 set the SHARED fields,
                   \* cTime := nsInfo cTime (BPSS:288). VERSION is written next step.
                   /\ bpssCT' = NsOf(t)
                   /\ Goto(t, "fmtWrite")
                   /\ UNCHANGED <<ver, prev, ptmp>>
              [] ptmp[l] # NoCT /\ prev[l] # NoCT ->
                   \* ST:761-765 previous and previous.tmp together
                   /\ FinishLoad(t, "fail")
                   /\ UNCHANGED <<bpssCT, ver, prev, ptmp>>
              [] ptmp[l] # NoCT /\ prev[l] = NoCT /\ ver[l] # NoCT ->
                   \* ST:766-767 COMPLETE_UPGRADE -> BPSS:173-174 -> ST:797-801
                   \* rename previous.tmp -> previous
                   /\ prev' = [prev EXCEPT ![l] = ptmp[l]]
                   /\ ptmp' = [ptmp EXCEPT ![l] = NoCT]
                   /\ Goto(t, "trans")
                   /\ UNCHANGED <<bpssCT, ver>>
              [] ptmp[l] # NoCT /\ prev[l] = NoCT /\ ver[l] = NoCT ->
                   \* ST:768 RECOVER_UPGRADE -> ST:802-807 delete current,
                   \* rename previous.tmp -> current
                   /\ ver'  = [ver  EXCEPT ![l] = ptmp[l]]
                   /\ ptmp' = [ptmp EXCEPT ![l] = NoCT]
                   /\ Goto(t, "trans")
                   /\ UNCHANGED <<bpssCT, prev>>
    /\ UNCHANGED targetFired
    /\ BpFrame

\* BPSS:291 writeProperties(bpSdir): serializes the SHARED fields as they are now
\* (BPSS:317-323); another thread's write since BPSS:288 lands in this VERSION.
BpFormatWrite(t) ==
    /\ pc[t] = "fmtWrite"
    /\ ver' = [ver EXCEPT ![tLoc[t]] = bpssCT]
    /\ Goto(t, "trans")
    /\ UNCHANGED <<bpssCT, prev, ptmp, targetFired>>
    /\ BpFrame

\* doTransition, BPSS:372-387 (before readProperties).
BpTransition(t) ==
    /\ pc[t] = "trans"
    /\ LET l == tLoc[t] IN
       CASE IsProvided(l) ->
              \* BPSS:372-373 "regular startup for PROVIDED": return false with no
              \* VERSION read -> BPSS:181 -> the check at BPSS:184
              /\ Goto(t, "check")
              /\ UNCHANGED <<ver, prev>>
         [] OptOf(t) = "ROLLBACK" /\ prev[l] # NoCT ->
              \* BPSS:375-379 -> doRollback (BPSS:603-645). The previous VERSION is
              \* read into a separate object (BPSS:611-612): shared fields untouched.
              IF prev[l] <= NsOf(t)                       \* BPSS:618-620
              THEN \* BPSS:637-643 current -> removed.tmp, previous -> current,
                   \* delete removed.tmp (a crash in between is recovered by
                   \* ST:808-817 to one of the two end states)
                   /\ ver'  = [ver  EXCEPT ![l] = prev[l]]
                   /\ prev' = [prev EXCEPT ![l] = NoCT]
                   /\ Goto(t, "readProps")
              ELSE \* BPSS:621-627 InconsistentFSStateException
                   /\ FinishLoad(t, "fail")
                   /\ UNCHANGED <<ver, prev>>
         [] OTHER ->
              \* BPSS:380-387 (ROLLBACK without previous: trash restore only), or
              \* no rollback
              /\ Goto(t, "readProps")
              /\ UNCHANGED <<ver, prev>>
    /\ UNCHANGED <<bpssCT, ptmp, targetFired>>
    /\ BpFrame

\* BPSS:388 readProperties(sd) -> SI:147-150 -> setFieldsFromProperties
\* (BPSS:341-349): setcTime (BPSS:345 -> SI:195-198) writes the SHARED cTime.
BpReadProps(t) ==
    /\ pc[t] = "readProps"
    /\ LET l == tLoc[t] IN
       CASE bpBad[l] = "badNs" ->
              \* BPSS:344 -> SI:227-233 throws before setcTime
              /\ FinishLoad(t, "fail")
              /\ UNCHANGED bpssCT
         [] bpBad[l] = "badBp" ->
              \* BPSS:345 setcTime, then BPSS:347-348 -> BPSS:333-336 throws
              /\ bpssCT' = ver[l]
              /\ FinishLoad(t, "fail")
         [] OTHER ->
              \* BPSS:343-348; BPSS:389 and BPSS:392-403 pass
              /\ bpssCT' = ver[l]
              /\ Goto(t, "decide1")
    /\ UNCHANGED <<ver, prev, ptmp, targetFired>>
    /\ BpFrame

\* BPSS:404-406: first read of the shared cTime (R1).
BpDecideRegular(t) ==
    /\ pc[t] = "decide1"
    /\ IF bpssCT = NsOf(t)                     \* BPSS:404-405
       THEN Goto(t, "check")                   \* BPSS:406 return false -> BPSS:181
       ELSE Goto(t, "decide2")                 \* BPSS:408-413: LV not older, no trash restore
    /\ UNCHANGED <<bpssCT, ver, prev, ptmp, targetFired>>
    /\ BpFrame

\* BPSS:414-424: second read of the shared cTime (R2).
BpDecideUpgrade(t) ==
    /\ pc[t] = "decide2"
    /\ LET l == tLoc[t] IN
       IF bpssCT < NsOf(t)                     \* BPSS:414-415
       THEN \* BPSS:416 doUpgrade (BPSS:445-501): FEDERATION supported and root
            \* non-null (BPSS:450-457); BPSS:477-480 delete previous; BPSS:486
            \* rename current -> previous.tmp (its VERSION is the on-disk one)
            /\ ptmp' = [ptmp EXCEPT ![l] = ver[l]]
            /\ ver'  = [ver  EXCEPT ![l] = NoCT]
            /\ prev' = [prev EXCEPT ![l] = NoCT]
            /\ IF Deferred(t)
               THEN \* BPSS:491-499 queue the callable; BPSS:417 return true
                    FinishLoad(t, "deferred")
               ELSE \* BPSS:489-490 inner doUpgrade runs now
                    Goto(t, "upSet")
       ELSE \* BPSS:419-424 "Datanode state ... is newer than the namespace state"
            /\ FinishLoad(t, "fail")
            /\ UNCHANGED <<ver, prev, ptmp>>
    /\ UNCHANGED <<bpssCT, targetFired>>
    /\ BpFrame

\* Inner doUpgrade, synchronous (hot swap): BPSS:508 linkAllBlocks (new current,
\* no VERSION yet, no shared field touched); BPSS:509 LV; BPSS:512 SHARED cTime.
BpUpgradeSet(t) ==
    /\ pc[t] = "upSet"
    /\ bpssCT' = NsOf(t)
    /\ Goto(t, "upWrite")
    /\ UNCHANGED <<ver, prev, ptmp, targetFired>>
    /\ BpFrame

\* BPSS:513 writeProperties(bpSd) serializes the SHARED fields; BPSS:517 rename
\* previous.tmp -> previous (a crash in between is completed by ST:797-801).
\* doTransition returns true (BPSS:416-417): no check at BPSS:184.
BpUpgradeWrite(t) ==
    /\ pc[t] = "upWrite"
    /\ LET l == tLoc[t] IN
       /\ ver'  = [ver  EXCEPT ![l] = bpssCT]
       /\ prev' = [prev EXCEPT ![l] = ptmp[l]]
       /\ ptmp' = [ptmp EXCEPT ![l] = NoCT]
    /\ FinishLoad(t, "ok")
    /\ UNCHANGED <<bpssCT, targetFired>>
    /\ BpFrame

\* THE TARGET. BPSS:181-187: doTransition returned false (PROVIDED at
\* BPSS:372-373, or regular at BPSS:404-406). BPSS:184 reads the SHARED cTime
\* again and compares it with the nsInfo the thread loads with.
TargetCheck(t) ==
    /\ pc[t] = "check"
    /\ IF bpssCT # NsOf(t)                                    \* BPSS:184
       THEN \* BPSS:185-186 throw new IOException("Datanode CTime (=...) is not
            \* equal to namenode CTime (=...)"); BPSS:193-196, BPSS:229-232
            /\ targetFired' = TRUE
            /\ FinishLoad(t, "fail")
       ELSE /\ targetFired' = targetFired
            /\ Goto(t, "writeVer")
    /\ UNCHANGED <<bpssCT, ver, prev, ptmp>>
    /\ BpFrame

\* BPSS:188 setServiceLayoutVersion; BPSS:189 writeProperties(sd) serializes the
\* SHARED fields into this location's VERSION. PROVIDED: getVersionFile() is null
\* (ST:491-494), so writeProperties returns at ST:1254-1257.
BpWriteVersion(t) ==
    /\ pc[t] = "writeVer"
    /\ LET l == tLoc[t] IN
       ver' = IF IsProvided(l) THEN ver ELSE [ver EXCEPT ![l] = bpssCT]
    /\ FinishLoad(t, "ok")                                    \* BPSS:192
    /\ UNCHANGED <<bpssCT, prev, ptmp, targetFired>>
    /\ BpFrame

----------------------------------------------------------------------------
(***************************************************************************)
(* Startup: after the block-pool loop                                      *)
(***************************************************************************)

\* DS:479-498: the queued block-pool upgrade callables run on the executor and
\* are joined. Each runs BPSS:495 -> inner doUpgrade (BPSS:503-519): link,
\* LV and cTime := nsInfo cTime (BPSS:509, 512), VERSION (BPSS:513), rename
\* previous.tmp -> previous (BPSS:517). All callables of one init write the same
\* nsInfo cTime and nothing else touches the object meanwhile (the loader waits
\* in future.get(), DS:490; refreshVolumes is excluded by the DataNode monitor),
\* so one step per callable is exact for the shared fields.
RunDeferredUpgrade(l) ==
    /\ dnUp /\ ldPhase = "join" /\ l \in ldPend
    /\ bpssCT' = ldNs
    /\ ver'  = [ver  EXCEPT ![l] = ldNs]
    /\ prev' = [prev EXCEPT ![l] = ptmp[l]]
    /\ ptmp' = [ptmp EXCEPT ![l] = NoCT]
    /\ ldPend' = ldPend \ {l}
    /\ ldAnyOK' = TRUE                                        \* DS:490
    /\ UNCHANGED <<nnVars, dnVer, bpBad, dnVars, bpssDirs, bpNS, bposLive, actor,
                   ldPhase, ldOwner, ldNs, ldQ, ldDnOK, ldDnPend, thrVars,
                   hsVars, targetFired>>

\* End of initStorage: DS:566-567 throws "All specified directories have failed
\* to load." when no block-pool directory loaded; verifyAndSetNamespaceInfo
\* (BPOS:394-411) and BPServiceActor.run (BPSA:904-926) react.
InitFinish ==
    /\ dnUp /\ ldPhase = "join" /\ ldPend = {}
    /\ IF ldAnyOK
       THEN \* DN:2275-2279 the dataset exists after the first successful init;
            \* BPSA:324 register; BPSA:926 RUNNING
            /\ dataInit' = TRUE
            /\ actor' = [actor EXCEPT ![ldOwner] = "run"]
            /\ UNCHANGED <<bpNS, bposLive>>
       ELSE \* BPOS:404-409 setNamespaceInfo(null). BPSA:910-922: retry iff
            \* shouldRetryInit (BPSA:949-951, BPOS:860-867): the block pool id was
            \* just reset (BPOS:258-260), so only if another actor is RUNNING or
            \* CONNECTING (BPSA:171-177).
            /\ bpNS' = NoCT
            /\ IF \E m \in NN \ {ldOwner} : actor[m] \in {"conn", "run"}
               THEN /\ actor' = [actor EXCEPT ![ldOwner] = "conn"]   \* BPSA:913-917
                    /\ UNCHANGED bposLive
               ELSE \* BPSA:918-921 exit; cleanUp -> BPOS:476-490 ->
                    \* DN:2151-2172 with no block pool id: the object stays in
                    \* bpStorageMap (DN:2153, DN:2167-2169 skipped)
                    /\ actor' = [actor EXCEPT ![ldOwner] = "dead"]
                    /\ bposLive' = FALSE
            /\ UNCHANGED dataInit
    /\ ldPhase' = "idle"
    /\ UNCHANGED <<nnVars, diskVars, dnUp, dnOpt, confFile, dataDirs, dsDirs,
                   bpssCT, bpssDirs, ldOwner, ldNs, ldQ, ldDnOK, ldDnPend,
                   ldAnyOK, ldPend, thrVars, hsVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Hot swap: DataNode.reconfigurePropertyImpl(dfs.datanode.data.dir)       *)
(* (DN:640-648) -> refreshVolumes (DN:1284-1373)                           *)
(***************************************************************************)

\* The operator writes newConf into the configuration and triggers
\* reconfiguration. nsInfos is snapshotted before the DataNode monitor is taken
\* (DN:1286-1289); the monitor excludes initStorage (DN:2262) and other
\* refreshes. checkStorageState (DN:1316, DN:3839-3845) needs the dataset.
\* parseChangedVolumes (DN:1152-1236): newLocations = configured locations with
\* no DataStorage directory; deactivateLocations = DataStorage directories no
\* longer configured. One pool thread per new location (DN:1312-1329).
\* Removing a PROVIDED volume, or any volume while a PROVIDED block-pool
\* directory is loaded, ends in a NullPointerException in
\* BlockPoolSliceStorage.remove (BPSS:302-309, brief CR-2): not modeled.
ReconfigureConf(newConf) ==
    /\ dnUp /\ bposLive /\ dataInit /\ bpNS # NoCT
    /\ ldPhase = "idle" /\ ~hsActive
    /\ LET newLocs == SelectSeq(newConf, LAMBDA x : x \notin dsDirs)
           deact   == dsDirs \ SeqToSet(newConf)
       IN /\ Len(newLocs) <= SwapWidth
          /\ deact \cap ProvidedLoc = {}
          /\ deact # {} => bpssDirs \cap ProvidedLoc = {}
          \* DN:1303-1307 "Attempt to remove all volumes"
          /\ Len(dataDirs) + Len(newLocs) - Cardinality(deact) > 0
          /\ newLocs # <<>> \/ deact # {}
          /\ confFile' = newConf
          /\ hsActive' = TRUE
          /\ hsNs' = bpNS
          /\ hsDeact' = deact
          /\ pc'   = [t \in Thr |-> IF t \in 1..Len(newLocs) THEN "dnl" ELSE pc[t]]
          /\ tLoc' = [t \in Thr |-> IF t \in 1..Len(newLocs) THEN newLocs[t] ELSE tLoc[t]]
    /\ UNCHANGED <<nnVars, diskVars, dnUp, dnOpt, dataDirs, dsDirs, dataInit,
                   bpVars, ldVars, targetFired>>

\* The new dfs.datanode.data.dir value: the configured locations minus rm plus
\* add. The operator writes the whole value; every configuration of the model
\* lists its locations in location-number order (the convention of InitConf),
\* so a cfg fixes the order by how it numbers its locations.
ReconfNewConf(rm, add) == InOrder((SeqToSet(confFile) \ rm) \cup add)

\* The operator's choice: drop some configured DISK locations and add some
\* hot-swap candidates.
Reconfigure(rm, add) ==
    /\ rm \subseteq SeqToSet(confFile) \cap DiskLoc
    /\ add \subseteq SwapLocs \ SeqToSet(confFile)
    /\ rm # {} \/ add # {}
    /\ ReconfigureConf(ReconfNewConf(rm, add))

\* Pool thread t: FsDatasetImpl.addVolume (FSD:515-525) -> DataStorage.prepareVolume
\* (DS:324-346): DS:327-331 refuses a location in use; DS:333-334 DataNode-level
\* load with HOTSWAP and callables = null; DS:338 makeBlockPoolDir; DS:340
\* getBlockPoolSliceStorage returns the shared object; DS:341-342 BP load.
HsDnLevel(t) ==
    /\ t \in HsThr /\ pc[t] = "dnl"
    /\ LET l == tLoc[t] IN
       IF l \in dsDirs \/ DnOutcome(l) = "fail"
       THEN \* DS:328-330, or a "bad" VERSION -> FSD:521-525
            /\ FinishLoad(t, "fail")
            /\ UNCHANGED <<diskVars, bpssCT>>
       ELSE /\ Goto(t, "contains")
            /\ IF DnOutcome(l) = "preFed"
               THEN \* DS:839-840 (callables null): synchronous pre-federation
                    \* upgrade, block pool re-formatted with nsInfo (DS:834-836).
                    \* Only a fixture-written VERSION is "old", so this path is
                    \* trace-only; BPSS:288 and BPSS:291 are one step here.
                    /\ PreFedFormat(l, hsNs)
                    /\ dnVer' = [dnVer EXCEPT ![l] = "cur"]
                    /\ UNCHANGED bpBad
               ELSE \* DS:283-287 format of an empty directory (ST:673-685,
                    \* ST:704-710), or regular
                    /\ dnVer' = IF IsProvided(l) THEN dnVer
                                ELSE [dnVer EXCEPT ![l] = "cur"]
                    /\ bpssCT' = GetBpss(hsNs)                \* DS:340
                    /\ UNCHANGED <<ver, prev, ptmp, bpBad>>
    /\ UNCHANGED <<nnVars, dnUp, dnOpt, confFile, dataDirs, dataInit, bpNS,
                   bposLive, actor, ldOwner, ldNs, ldDnOK, ldDnPend, hsVars,
                   targetFired>>

\* DN:1331-1351 join the pool; DN:1355 removeVolumes(deactivateLocations):
\* DataStorage.removeVolumes removes the block-pool directories first
\* (DS:524-531) and then the volume (DS:533); DN:1364-1371 dataDirs := the
\* configured locations that are effective (unchanged or added).
HotSwapFinish ==
    /\ dnUp /\ hsActive
    /\ \A t \in HsThr : pc[t] \in {"idle", "ok", "fail"}
    /\ dsDirs'   = dsDirs \ hsDeact
    /\ bpssDirs' = bpssDirs \ hsDeact
    /\ dataDirs' = SelectSeq(confFile, LAMBDA x : x \in dsDirs \ hsDeact)
    /\ pc' = [t \in Thr |-> IF t \in HsThr THEN "idle" ELSE pc[t]]
    /\ hsActive' = FALSE
    /\ hsDeact' = {}
    /\ UNCHANGED <<nnVars, diskVars, dnUp, dnOpt, confFile, dataInit, bpssCT,
                   bpNS, bposLive, actor, ldVars, tLoc, hsNs, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Next                                                                    *)
(***************************************************************************)

BpStep(t) ==
    \/ BpContains(t)
    \/ BpAnalyze(t)
    \/ BpFormatWrite(t)
    \/ BpTransition(t)
    \/ BpReadProps(t)
    \/ BpDecideRegular(t)
    \/ BpDecideUpgrade(t)
    \/ BpUpgradeSet(t)
    \/ BpUpgradeWrite(t)
    \/ TargetCheck(t)
    \/ BpWriteVersion(t)

Next ==
    \/ \E n \in NN : NNUpgrade(n)
    \/ \E n \in NN : NNRollback(n)
    \/ \E l \in Loc : DiskReplace(l)
    \/ DNStop
    \/ \E o \in Opts : DNStart(o)
    \/ \E n \in NN : Handshake(n)
    \/ \E n \in NN : ActorRejected(n)
    \/ DNLevelLoad
    \/ DNLevelJoin
    \/ \E t \in Thr : BpStep(t)
    \/ \E l \in Loc : RunDeferredUpgrade(l)
    \/ InitFinish
    \/ \E rm \in SUBSET DiskLoc, add \in SUBSET SwapLocs : Reconfigure(rm, add)
    \/ \E t \in HsThr : HsDnLevel(t)
    \/ HotSwapFinish

Spec == Init /\ [][Next]_vars


----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The oracle: BPSS:185 never throws.
TargetSafe == ~targetFired

DnVers == {"none", "cur", "old", "bad"}
PcVals == {"idle", "dnl", "contains", "analyze", "fmtWrite", "trans", "readProps",
           "decide1", "decide2", "upSet", "upWrite", "check", "writeVer",
           "ok", "fail"}

TypeOK ==
    /\ nnCT \in [NN -> 0..MaxCT]
    /\ nnPrev \in [NN -> 0..MaxCT \cup {NoCT}]
    /\ issued \subseteq 0..MaxCT
    /\ ver  \in [Loc -> 0..MaxCT \cup {NoCT}]
    /\ prev \in [Loc -> 0..MaxCT \cup {NoCT}]
    /\ ptmp \in [Loc -> 0..MaxCT \cup {NoCT}]
    /\ dnVer \in [Loc -> DnVers]
    /\ bpBad \in [Loc -> {"ok", "badNs", "badBp"}]
    /\ dnUp \in BOOLEAN /\ dnOpt \in Opts
    /\ dsDirs \subseteq Loc /\ dataInit \in BOOLEAN
    /\ bpssCT \in 0..MaxCT \cup {NoBpss}
    /\ bpssDirs \subseteq Loc
    /\ bpNS \in 0..MaxCT \cup {NoCT}
    /\ bposLive \in BOOLEAN
    /\ actor \in [NN -> {"conn", "init", "run", "dead"}]
    /\ ldPhase \in {"idle", "dn", "bp", "join"}
    /\ ldOwner \in NN
    /\ ldNs \in 0..MaxCT \cup {NoCT}
    /\ ldAnyOK \in BOOLEAN /\ ldPend \subseteq Loc
    /\ pc \in [Thr -> PcVals]
    /\ tLoc \in [Thr -> Loc]
    /\ hsActive \in BOOLEAN
    /\ hsNs \in 0..MaxCT \cup {NoCT}
    /\ hsDeact \subseteq Loc
    /\ targetFired \in BOOLEAN
    \* PROVIDED locations never get a block-pool directory
    /\ \A x \in ProvidedLoc : ver[x] = NoCT /\ prev[x] = NoCT /\ ptmp[x] = NoCT

\* Every cTime the DataNode holds (shared object, VERSION, previous,
\* previous.tmp, nsInfo) was issued by a NameNode format/upgrade: loads only
\* copy values they read (brief Section 5). Fails under the test fixture.
CTimeProvenance ==
    /\ \A x \in Loc : /\ ver[x]  \in issued \cup {NoCT}
                      /\ prev[x] \in issued \cup {NoCT}
                      /\ ptmp[x] \in issued \cup {NoCT}
    /\ bpssCT \in issued \cup {NoBpss}
    /\ bpNS \in issued \cup {NoCT}
    /\ ldNs \in issued \cup {NoCT}
    /\ hsNs \in issued \cup {NoCT}
    /\ \A n \in NN : nnCT[n] \in issued /\ nnPrev[n] \in issued \cup {NoCT}

=============================================================================
