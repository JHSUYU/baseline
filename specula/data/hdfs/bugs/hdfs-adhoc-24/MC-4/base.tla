-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-24: can an execution reach the failing branch of the ad hoc  *)
(* check at BlockPoolSliceStorage.java:421 (BlockPoolSliceStorage.        *)
(* doTransition, throws java.io.IOException "Datanode state: LV = .. CTime *)
(* = .. is newer than the namespace state ..")?                            *)
(*                                                                         *)
(* Category A (NameNode <-> DataNode agreement on the namespace cTime,     *)
(* across restart / upgrade / rollback / finalize), with per-thread        *)
(* program counters for the DataNode volume loaders (Scenario 1).          *)
(*                                                                         *)
(* Source tree pinned at 734dd8a67cd. File abbreviations used in the       *)
(* annotations (all under hadoop-hdfs-project/hadoop-hdfs/src/main/java/   *)
(* org/apache/hadoop/hdfs/server/):                                         *)
(*   BPSS  = datanode/BlockPoolSliceStorage.java                           *)
(*   DS    = datanode/DataStorage.java                                     *)
(*   ST    = common/Storage.java                                           *)
(*   SI    = common/StorageInfo.java                                       *)
(*   DNLV  = datanode/DataNodeLayoutVersion.java                           *)
(*   DN    = datanode/DataNode.java                                        *)
(*   BPOS  = datanode/BPOfferService.java                                  *)
(*   BPSA  = datanode/BPServiceActor.java                                  *)
(*   FSD   = datanode/fsdataset/impl/FsDatasetImpl.java                    *)
(*   SL    = datanode/StorageLocation.java                                 *)
(*   FSI   = namenode/FSImage.java                                         *)
(*   FSN   = namenode/FSNamesystem.java                                    *)
(*   FSEL  = namenode/FSEditLogLoader.java                                 *)
(*   NNRPC = namenode/NameNodeRpcServer.java                               *)
(*   NNS   = namenode/NNStorage.java                                       *)
(*                                                                         *)
(* Target predicate (modeling-brief.md section 1), LV@k / C@k = value of   *)
(* the SHARED field this.layoutVersion / this.cTime read at line k,        *)
(* n = nsInfo.getCTime(), cur = DataNodeLayoutVersion.getCurrentLayout-   *)
(* Version():                                                              *)
(*   phi_T == ~(LV@404 = cur /\ C@405 = n) /\ ~(LV@414 > cur \/ C@415 < n)  *)
(* The loader thread reaches pc "L414" only if the L404/L405 return was    *)
(* not taken; CheckUpgradeLV evaluates LV@414 and TargetCheck evaluates    *)
(* C@415 and takes the throw at L421.                                       *)
(***************************************************************************)
EXTENDS Naturals, Integers, FiniteSets, TLC

CONSTANTS
    Vol,        \* block-pool slices of one DataNode: one <vol>/current/<bpid> per volume
    InitLVs     \* layout versions the volumes may hold in the initial state (CurLV and/or OldLV)

(***************************************************************************)
(* Constants taken from the code                                           *)
(***************************************************************************)
CurLV   == -57  \* DNLV:37-38, 55-57 current DN layout = last feature, DNLV:90 BLOCKID_BASED_LAYOUT_32_by_32(-57)
OldLV   == -56  \* DNLV:87 BLOCKID_BASED_LAYOUT(-56): an older layout (> CurLV) that supports FEDERATION
InitLV  == 0    \* BPSS:113-115 super(NodeType.DATA_NODE) -> SI:56-58 layoutVersion = 0 until first written
NoC     == -1   \* "no cTime": no previous / no nsInfo / DN down
FormatC == 1    \* NNS:626-630 newNamespaceInfo(): cTime = Time.now() at format (first issued cTime)

LVs == {CurLV, OldLV}

\* Content of a VERSION file (BPSS:316-323 layoutVersion, namespaceID, blockpoolID, cTime).
\* namespaceID / blockpoolID / clusterID are constant (single namespace, single block pool).
Ver(l, c) == [ok |-> TRUE, lv |-> l, c |-> c]
NoVer     == [ok |-> FALSE, lv |-> 0, c |-> NoC]

\* Loader thread record. One loader per volume at a time (startup loader visits volumes one by one;
\* hot swap starts one task per new volume), so the thread is identified by its volume.
IdleLd == [pc |-> "idle", mode |-> "none", c405 |-> NoC, err |-> "none"]

Pcs == {"idle", "Analyze", "FormatLV", "FormatC", "FormatWrite", "Dispatch",
        "RbRenameCur", "RbRenamePrev", "RbDeleteTmp", "RbRestoreTrash",
        "ReadPropsLV", "ReadPropsC", "L404", "L405", "L408", "L409", "L414", "TargetCheck",
        "UpDelDnPrev", "UpDelPrev", "UpRenameCur", "CallableWait", "LinkBlocks",
        "UpSetLV", "UpSetC", "UpWrite", "UpRenameTmp",
        "PostCheckC", "PostSetLV", "PostWrite", "Commit", "Fail"}
Modes == {"none", "startup", "hotswap", "callable"}
Errs  == {"none", "S733", "S744", "S755", "S763", "S773", "B376", "B621", "B388", "B421", "B185"}

VARIABLES
    \* ---- NameNode (abstract: atomic restarts and admin commands) ----
    nnC,           \* cTime returned by versionRequest (FSI:464-465 upgrade, FSI:800-804 loaded dir, NNS:626-630 format)
    nnPrevC,       \* cTime of the NN `previous` state, NoC when finalized (FSI:423-433, 464, 521-568, 616-632)
    nnRU,          \* rollingUpgradeInfo: "none" | "inprogress" | "finalized" (FSN:7727-7729, 7800-7836)
    ruAfterImage,  \* an NN restart re-creates the RU info: START (and FINALIZE, if logged) follow the newest
                   \* regular fsimage, or the image records the in-progress RU (FSEL:892-913;
                   \* FSImageFormatProtobuf.java:513-517, 982-983)
    issued,        \* every cTime the NN (or the initial storage) ever held; used by CTimeProvenance
    \* ---- environment / operator procedure ----
    online,        \* online[v]: the disk of volume v is accessible
    mustRollback,  \* the NN was rolled back; the next DN start must be -rollback (start-dfs.sh:71-72)
    \* ---- per-volume persistent block-pool state, root <vol>/current/<bpid> (BPSS:153-154, ST:345-358) ----
    cur,           \* current/VERSION, NoVer if absent (ST:491-496, 717-718)
    prev,          \* previous/ with its VERSION (ST:503-521, 721; BPSS:605-612)
    prevTmp,       \* previous.tmp/ = the old current during an upgrade (ST:533-538, 722; BPSS:481-486, 517)
    remTmp,        \* removed.tmp/ = the rolled-away current during a rollback (ST:550-555, 723; BPSS:632-643)
    finTmp,        \* finalized.tmp/ exists (ST:566-571, 724; BPSS:669-688)
    marker,        \* RollingUpgradeInProgress marker file in the BP root (BPSS:82, 863-909)
    trash,         \* trash/ exists in the BP root (BPSS:70, 743-745)
    dnPrev,        \* DN-level <vol>/previous exists (BPSS:464-471; DS:1020-1024) -- trace fixtures only
    dnOk,          \* the DN-level storage of v loads (DS:408-431) -- FALSE only via trace fixtures
    \* ---- DataNode process (volatile) ----
    dnUp,          \* DataNode process running
    startOpt,      \* startup option of this process (DN:3451-3455): "REGULAR" | "ROLLBACK"
    nsC,           \* cTime of the handshake NamespaceInfo (BPSA:302-317, BPOS:246-265, 394-401); also used by hot swap (DN:1286-1289)
    memLV,         \* SHARED BlockPoolSliceStorage.layoutVersion (SI:47, public, not volatile, no lock)
    memC,          \* SHARED BlockPoolSliceStorage.cTime (SI:50); one BPSS per bpid (DS:107-108, 1409-1419)
    bpInit,        \* block pool init phase: "none" | "loading" | "callables" | "done" | "failed"
    dnLoaded,      \* volumes in DataStorage.storageDirs (DN level; DS:417, 437; DS:264)
    bpLoaded,      \* volumes in BlockPoolSliceStorage.storageDirs (BPSS:259-261; DS:261)
    visited,       \* volumes the startup loader already visited (DS:459)
    ld,            \* ld[v]: loader thread working on volume v
    dnRegC,        \* cTime in the DN registration (DN:2073-2088 live BPSS; BPSA:838-851); heartbeats need = nnC
    trashEnabled,  \* bpid in DataStorage.trashEnabledBpids (DS:96, 173-190), in memory
    \* ---- target ----
    targetFired    \* the failing branch at BPSS:421 was taken

nnVars   == <<nnC, nnPrevC, nnRU, ruAfterImage, issued>>
envVars  == <<online, mustRollback>>
volDisk  == <<cur, prev, prevTmp, remTmp, finTmp, marker, trash, dnPrev, dnOk>>
shared   == <<memLV, memC>>
dnCtl    == <<dnUp, startOpt, nsC, bpInit, dnLoaded, bpLoaded, visited, dnRegC, trashEnabled>>
vars     == <<nnVars, envVars, volDisk, shared, dnCtl, ld, targetFired>>

MaxIssued == CHOOSE m \in issued : \A x \in issued : x <= m

(***************************************************************************)
(* Initial state: a formatted cluster (NN cTime FormatC, finalized), the   *)
(* DataNode down, every volume formatted with the NN cTime, at a layout    *)
(* from InitLVs (OldLV = the slice was written by older DN software).      *)
(***************************************************************************)
Init ==
    /\ nnC = FormatC
    /\ nnPrevC = NoC
    /\ nnRU = "none"
    /\ ruAfterImage = FALSE
    /\ issued = {FormatC}
    /\ online = [v \in Vol |-> TRUE]
    /\ mustRollback = FALSE
    /\ cur \in [Vol -> {Ver(l, FormatC) : l \in InitLVs}]
    /\ prev = [v \in Vol |-> NoVer]
    /\ prevTmp = [v \in Vol |-> NoVer]
    /\ remTmp = [v \in Vol |-> NoVer]
    /\ finTmp = [v \in Vol |-> FALSE]
    /\ marker = [v \in Vol |-> FALSE]
    /\ trash = [v \in Vol |-> FALSE]
    /\ dnPrev = [v \in Vol |-> FALSE]
    /\ dnOk = [v \in Vol |-> TRUE]
    /\ dnUp = FALSE
    /\ startOpt = "REGULAR"
    /\ nsC = NoC
    /\ memLV = InitLV
    /\ memC = NoC
    /\ bpInit = "none"
    /\ dnLoaded = {}
    /\ bpLoaded = {}
    /\ visited = {}
    /\ ld = [v \in Vol |-> IdleLd]
    /\ dnRegC = NoC
    /\ trashEnabled = FALSE
    /\ targetFired = FALSE

(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
\* Effective startup option seen by doTransition for the loader of v:
\* hot swap passes HOTSWAP (DS:333-334, 341-342); startup passes the process option (DN:2256, 2263).
Opt(v) == IF ld[v].mode = "hotswap" THEN "HOTSWAP" ELSE startOpt

\* A loader step that only moves the program counter.
Goto(v, p) ==
    /\ ld' = [ld EXCEPT ![v].pc = p]
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnCtl, targetFired>>

\* A loader step that fails with an exception thrown at site e (caught by LoadStorageDirectoryFail).
FailWith(v, e) == ld' = [ld EXCEPT ![v].pc = "Fail", ![v].err = e]

IsEmpty(v) ==
    /\ ~cur[v].ok /\ ~prev[v].ok /\ ~prevTmp[v].ok /\ ~remTmp[v].ok
    /\ ~finTmp[v] /\ ~marker[v] /\ ~trash[v] /\ ~dnPrev[v]

(***************************************************************************)
(* NameNode (Scenarios 2-4). Each NN restart is one atomic step; the DN   *)
(* only observes (cTime, previous, RU status, finalized).                  *)
(***************************************************************************)

\* FSI.doUpgrade L455-519: NN restarted with -upgrade. c is the new cTime (L465 storage.cTime = now()).
\* Next passes c = MaxIssued + 1 (wall clock ahead of every earlier cTime); a clock behind an
\* earlier-issued cTime is the fault of Scenario 4 (c <= MaxIssued).
NNDoUpgrade(c) ==
    /\ ~dnUp                                   \* documented procedure: the cluster is stopped first
    /\ nnPrevC = NoC                           \* L456 checkUpgrade -> L423-433: no `previous` in any dir
    /\ LET ru == IF ruAfterImage THEN nnRU ELSE "none" IN   \* L461 loadFSImage replays the edits after the newest image (FSEL:892-913)
         /\ ru /= "inprogress"                 \* L462 checkRollingUpgrade -> FSN:7792-7798 (finalized RU info passes)
         /\ nnRU' = ru                         \* the in-memory RU info lives as long as the NN process (FSN:7800-7836)
    /\ nnPrevC' = nnC                          \* L464 oldCTime; L501-509 NNUpgradeUtil.doUpgrade keeps it in previous/
    /\ nnC' = c                                \* L465 storage.cTime = now()  (no comparison with oldCTime)
    /\ issued' = issued \cup {c}
    /\ ruAfterImage' = FALSE                   \* L495 saveFSImageInAllDirs: the new image follows every edit
    /\ UNCHANGED <<envVars, volDisk, shared, dnCtl, ld, targetFired>>

\* FSI.doRollback L521-568: NN restarted with -rollback.
\* Abstraction: the RU info after a rollback is not tracked (set to "none"); the DN load that Scenario 3
\* needs happens at the DN -rollback start, before any heartbeat.
NNDoRollback ==
    /\ ~dnUp                                   \* documented procedure: the cluster is stopped first
    /\ nnPrevC /= NoC                          \* L550-552 some dir has a previous state
    /\ nnC' = nnPrevC                          \* L556-562 NNUpgradeUtil.doRollBack: previous -> current (pre-upgrade cTime)
    /\ nnPrevC' = NoC
    /\ nnRU' = "none"
    /\ ruAfterImage' = FALSE
    /\ mustRollback' = TRUE                    \* no NN->DN rollback command; DNs start with -rollback (start-dfs.sh:71-72)
    /\ UNCHANGED <<issued, online, volDisk, shared, dnCtl, ld, targetFired>>

\* FSI.finalizeUpgrade L616-632 (dfsadmin -finalizeUpgrade): deletes previous/, isUpgradeFinalized = true.
NNFinalizeUpgrade ==
    /\ nnPrevC /= NoC
    /\ nnPrevC' = NoC                          \* L621-624 NNUpgradeUtil.doFinalize; L631
    /\ UNCHANGED <<nnC, nnRU, ruAfterImage, issued, envVars, volDisk, shared, dnCtl, ld, targetFired>>

\* Scenario 4 (directory split), abstract fault: the per-directory VERSION writes of FSI:501-509 are
\* not atomic across directories and the reported cTime comes from the directory whose image is
\* loaded (FSI:800-804); a crash in that loop plus loss of the upgraded directory lowers nnC.
NNCTimeRegress(c) ==
    /\ c \in issued
    /\ c < nnC
    /\ nnC' = c
    /\ UNCHANGED <<nnPrevC, nnRU, ruAfterImage, issued, envVars, volDisk, shared, dnCtl, ld, targetFired>>

\* FSN.startRollingUpgrade L7609-7639 (Scenario 3).
NNStartRollingUpgrade ==
    /\ nnRU /= "inprogress"                    \* L7616-7618
    /\ nnPrevC = NoC                           \* checkUpgrade: non-HA L7621 -> L7657-7666; HA L7624 -> L7645-7648
    /\ nnRU' = "inprogress"                    \* setRollingUpgradeInfo: non-HA L7673, HA L7649
    /\ ruAfterImage' = TRUE                    \* non-HA L7668 saves the rollback image (RU not yet set, so not
                                               \* recorded in it) before L7627 logs START: a restart replays START
    /\ UNCHANGED <<nnC, nnPrevC, issued, envVars, volDisk, shared, dnCtl, ld, targetFired>>

\* FSN.finalizeRollingUpgrade L7800-7831 (Scenario 3).
NNFinalizeRollingUpgrade ==
    /\ nnRU = "inprogress"                     \* L7807-7809
    /\ nnRU' = "finalized"                     \* L7812 -> L7833-7835 rollingUpgradeInfo.finalize(); stays non-null
    \* L7819-7820 the (pre-START) rollback image becomes the newest regular image: ruAfterImage unchanged
    /\ UNCHANGED <<nnC, nnPrevC, ruAfterImage, issued, envVars, volDisk, shared, dnCtl, ld, targetFired>>

\* A checkpoint (saveNamespace / standby or secondary checkpoint) after the RU FINALIZE edit
\* (Scenario 3). A finalized RU is not saved in an fsimage (FSImageFormatProtobuf.java:982-983 saves
\* the start time only while isRollingUpgrade()), so afterwards a restart no longer re-creates it.
\* A checkpoint while the RU is in progress changes nothing here: the image records the in-progress
\* RU (FSImageFormatProtobuf.java:513-517) and a later FINALIZE edit is replayed on top of it.
NNCheckpoint ==
    /\ nnRU = "finalized"
    /\ ruAfterImage
    /\ ruAfterImage' = FALSE
    /\ UNCHANGED <<nnC, nnPrevC, nnRU, issued, envVars, volDisk, shared, dnCtl, ld, targetFired>>

\* NN restarted without -upgrade / -rollback (Scenario 3): loads the newest image and replays the
\* edits after it (FSEL:892-913); cTime and previous are unchanged. Only restarts that change the
\* abstract state are steps: a finalized RU whose edits precede the newest image is not re-created.
NNRestart ==
    /\ nnRU /= "none"
    /\ ~ruAfterImage
    /\ nnRU' = "none"
    /\ UNCHANGED <<nnC, nnPrevC, ruAfterImage, issued, envVars, volDisk, shared, dnCtl, ld, targetFired>>

(***************************************************************************)
(* DataNode process start / stop / crash                                   *)
(***************************************************************************)

\* DataNode start with option opt, handshake, DN-level storage load and BPSS creation:
\*  DN:3451-3455 startup option (per process); BPSA:302-317 versionRequest -> BPOS.verifyAndSetNamespaceInfo
\*  L382-401 -> DN.initBlockPool L2185-2199 -> initStorage L2251-2264 (DN monitor) -> DS.recoverTransitionRead
\*  L564-566 -> addStorageLocations L382-397 -> loadDataStorage L403-448 (DN level, offline volumes fail) ->
\*  loadBlockPoolSliceStorage L453-454 -> getBlockPoolSliceStorage L1409-1419 (new BPSS with cTime = nsInfo.cTime).
DataNodeStart(opt) ==
    /\ ~dnUp
    /\ IF opt = "ROLLBACK" THEN mustRollback ELSE ~mustRollback   \* procedure; excludes AR X9
    /\ dnUp' = TRUE
    /\ startOpt' = opt
    /\ nsC' = nnC                              \* BPSA:262 versionRequest
    /\ mustRollback' = FALSE                   \* the operator did start the DN with -rollback
    /\ LET L == {v \in Vol : online[v] /\ dnOk[v]} IN
         /\ dnLoaded' = L                      \* DS:408-431 DN-level load per location; failures are skipped
         /\ memC' = IF L = {} THEN NoC ELSE nnC   \* DS:392-394 no BPSS if nothing loaded; else DS:1414-1415 cTime = nsInfo.cTime
    /\ memLV' = InitLV                         \* BPSS:113-115
    /\ bpInit' = "loading"
    /\ bpLoaded' = {}
    /\ visited' = {}
    /\ ld' = [v \in Vol |-> IdleLd]
    /\ dnRegC' = NoC
    /\ trashEnabled' = FALSE                   \* DS:111-115 fresh trashEnabledBpids
    /\ UNCHANGED <<nnVars, online, volDisk, targetFired>>

\* Volatile DataNode state is lost.
DNReset ==
    /\ dnUp' = FALSE
    /\ startOpt' = "REGULAR"
    /\ nsC' = NoC
    /\ memLV' = InitLV
    /\ memC' = NoC
    /\ bpInit' = "none"
    /\ dnLoaded' = {}
    /\ bpLoaded' = {}
    /\ visited' = {}
    /\ ld' = [v \in Vol |-> IdleLd]
    /\ dnRegC' = NoC
    /\ trashEnabled' = FALSE

\* Clean shutdown (operator stop / MiniDFSCluster.shutdown) when no storage operation is in flight.
DataNodeStop ==
    /\ dnUp
    /\ bpInit \in {"done", "failed"}
    /\ \A v \in Vol : ld[v].pc = "idle"
    /\ DNReset
    /\ UNCHANGED <<nnVars, envVars, volDisk, targetFired>>

\* DataNode crash at any persistent-step boundary (fault). Disk state, including the transient
\* previous.tmp / removed.tmp / finalized.tmp directories, survives.
DataNodeCrash ==
    /\ dnUp
    /\ DNReset
    /\ UNCHANGED <<nnVars, envVars, volDisk, targetFired>>

(***************************************************************************)
(* Startup block-pool loader: DS.loadBlockPoolSliceStorage L450-501.      *)
(* The BPServiceActor thread loads the DN-level volumes one at a time      *)
(* (DS:459-477, under the DN monitor DN:2262-2264 and DS:382              *)
(* `synchronized`); upgrades are deferred to callables (BPSS:491-500) that *)
(* run after the loop (DS:479-498).                                        *)
(***************************************************************************)
LoadBlockPoolSliceStorageNext(v) ==
    /\ dnUp
    /\ bpInit = "loading"
    /\ v \in dnLoaded \ visited                 \* DS:459 for (dataDir : dataDirs)
    /\ \A w \in Vol : ld[w].pc \in {"idle", "CallableWait"}   \* sequential loop
    /\ visited' = visited \cup {v}
    \* DS:460 makeBlockPoolDir creates <vol>/current/<bpid> (SL:257-281);
    \* DS:464 -> BPSS.recoverTransitionRead L251-262 -> loadBpStorageDirectories L215-235;
    \* BPSS:221 containsStorageDir: v is not in the BPSS at a fresh start (no BP re-init is modeled)
    /\ ld' = [ld EXCEPT ![v] = [pc |-> "Analyze", mode |-> "startup", c405 |-> NoC, err |-> "none"]]
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnUp, startOpt, nsC, bpInit, dnLoaded, bpLoaded,
                   dnRegC, trashEnabled, targetFired>>

\* DS:479-484 after the loop the deferred upgrade callables are submitted (they run in parallel).
SubmitUpgradeCallables ==
    /\ dnUp
    /\ bpInit = "loading"
    /\ dnLoaded \subseteq visited
    /\ \A w \in Vol : ld[w].pc \in {"idle", "CallableWait"}
    /\ bpInit' = "callables"
    /\ ld' = [w \in Vol |-> IF ld[w].pc = "CallableWait"
                              THEN [ld[w] EXCEPT !.pc = "LinkBlocks", !.mode = "callable"]
                              ELSE ld[w]]
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnUp, startOpt, nsC, dnLoaded, bpLoaded, visited,
                   dnRegC, trashEnabled, targetFired>>

\* DS:486-500 all futures joined; DS:566-568 recoverTransitionRead fails if nothing loaded
\* ("All specified directories have failed to load."): BPOS:403-409 resets the nsInfo and the single
\* actor exits (BPSA:910-921). Otherwise BPSA:324 register -> DN.createBPRegistration L2073-2088
\* uses the live BPSS StorageInfo (its cTime).
BlockPoolInitDone ==
    /\ dnUp
    /\ bpInit = "callables"
    /\ \A w \in Vol : ld[w].pc = "idle"
    /\ IF bpLoaded = {}
         THEN /\ bpInit' = "failed"
              /\ dnRegC' = NoC
         ELSE /\ bpInit' = "done"
              /\ dnRegC' = memC
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnUp, startOpt, nsC, dnLoaded, bpLoaded, visited,
                   ld, trashEnabled, targetFired>>

(***************************************************************************)
(* Hot swap (Scenario 1): DN.refreshVolumes L1284-1373 under the DN        *)
(* monitor (L1290). parseChangedVolumes L1152-1236: every configured       *)
(* location not loaded at DN level is new (L1171-1192, 1204-1220).         *)
(* L1312-1329: one data.addVolume(location, nsInfos) task per new volume,  *)
(* run concurrently on a thread pool. FSD.addVolume L514-525 takes no lock *)
(* before DS.prepareVolume L324-346 (not synchronized): DN-level load with *)
(* HOTSWAP (L333-334), makeBlockPoolDir (L338), then                       *)
(* loadBpStorageDirectories(nsInfo, loc, HOTSWAP, callables = null)        *)
(* (L341-342) on the SHARED BlockPoolSliceStorage (L340).                  *)
(***************************************************************************)
RefreshVolumes(S) ==
    /\ dnUp
    /\ bpInit = "done"                         \* DN:1286-1289 nsInfos from the initialized block pool
    /\ \A w \in Vol : ld[w].pc = "idle"         \* one reconfiguration at a time (DN monitor)
    /\ S /= {}
    /\ S \subseteq {v \in Vol : online[v] /\ dnOk[v] /\ v \notin dnLoaded}
    /\ ld' = [w \in Vol |-> IF w \in S
                              THEN [pc |-> "Analyze", mode |-> "hotswap", c405 |-> NoC, err |-> "none"]
                              ELSE ld[w]]
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnCtl, targetFired>>

\* FSD.addVolume L527-560 (addBlockPool / getVolumeMap, not modeled) then builder.build()
\* (DS:252-266): BP-level and DN-level storage dirs are added.
HotSwapBuild(v) ==
    /\ ld[v].pc = "Commit"
    /\ bpLoaded' = bpLoaded \cup {v}
    /\ dnLoaded' = dnLoaded \cup {v}
    /\ ld' = [ld EXCEPT ![v] = IdleLd]
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnUp, startOpt, nsC, bpInit, visited, dnRegC,
                   trashEnabled, targetFired>>

(***************************************************************************)
(* BPSS.loadStorageDirectory L149-197, step 1: analyzeStorage + recovery.   *)
(***************************************************************************)
\* ST.StorageDirectory.analyzeStorage L659-781 on the BP root. L663-667 PROVIDED: not modeled.
\* L673-698 the root exists (pre-created by makeBlockPoolDir, DS:338 / DS:460) and is writable
\* (offline volumes are never loaded). L700 lock(): BP dirs are shared, no lock (ST:906-910, BPSS:153-154).
\* L704-710 HOTSWAP returns NOT_FORMATTED only if the root had to be created (hadMkdirs): never here.
\* L712-714 checkOldLayoutStorage: BPSS.isPreUpgradableLayout is false (BPSS:738-741).
AnalyzeState(v) ==
    LET hasCurrent      == cur[v].ok           \* L717-718 current/VERSION exists
        hasPrevious     == prev[v].ok          \* L721
        hasPreviousTmp  == prevTmp[v].ok       \* L722
        hasRemovedTmp   == remTmp[v].ok        \* L723
        hasFinalizedTmp == finTmp[v]           \* L724 (lastcheckpoint.tmp, L725, never exists at BP level)
        nTmp == (IF hasPreviousTmp THEN 1 ELSE 0) + (IF hasRemovedTmp THEN 1 ELSE 0)
                  + (IF hasFinalizedTmp THEN 1 ELSE 0)
    IN  IF nTmp = 0 THEN                                         \* L727-739 no temp dirs
            IF hasCurrent THEN "NORMAL"                          \* L730-731
            ELSE IF hasPrevious THEN "S733"                      \* L732-734 "version file in current directory is missing."
            ELSE "NOT_FORMATTED"                                 \* L735-738 (checkEmptyCurrent L613-628: current absent or empty)
        ELSE IF nTmp > 1 THEN "S744"                             \* L741-745 "too many temporary directories."
        ELSE IF hasFinalizedTmp THEN
            IF hasPrevious THEN "S755" ELSE "COMPLETE_FINALIZE"  \* L753-759
        ELSE IF hasPreviousTmp THEN
            IF hasPrevious THEN "S763"                           \* L761-765
            ELSE IF hasCurrent THEN "COMPLETE_UPGRADE"           \* L766-767
            ELSE "RECOVER_UPGRADE"                               \* L768
        ELSE IF hasCurrent = hasPrevious THEN "S773"             \* L771-777 exactly one of current/previous with removed.tmp
        ELSE IF hasCurrent THEN "COMPLETE_ROLLBACK"              \* L778-779
        ELSE "RECOVER_ROLLBACK"                                  \* L780

AnalyzeErrs == {"S733", "S744", "S755", "S763", "S773"}

\* BPSS:156-175 switch on the state; ST.doRecover L789-840 is applied in the same step (it only
\* renames/deletes temp directories; a crash inside it leads to the same recovery state again).
AnalyzeStorage(v) ==
    /\ ld[v].pc = "Analyze"
    /\ LET st == AnalyzeState(v) IN
       CASE st = "NORMAL" ->                                     \* BPSS:159-160
              /\ ld' = [ld EXCEPT ![v].pc = "Dispatch"]
              /\ UNCHANGED volDisk
         [] st = "NOT_FORMATTED" ->                              \* BPSS:167-171 format(sd, nsInfo)
              \* BPSS:286 bpSdir.clearDirectory(): current/ recreated empty (ST:435-460)
              /\ ld' = [ld EXCEPT ![v].pc = "FormatLV"]
              /\ UNCHANGED volDisk
         [] st = "COMPLETE_UPGRADE" ->                           \* ST:797-801 rename previous.tmp -> previous
              /\ prev' = [prev EXCEPT ![v] = prevTmp[v]]
              /\ prevTmp' = [prevTmp EXCEPT ![v] = NoVer]
              /\ ld' = [ld EXCEPT ![v].pc = "Dispatch"]
              /\ UNCHANGED <<cur, remTmp, finTmp, marker, trash, dnPrev, dnOk>>
         [] st = "RECOVER_UPGRADE" ->                            \* ST:802-807 deleteAsync(current); rename previous.tmp -> current
              /\ cur' = [cur EXCEPT ![v] = prevTmp[v]]
              /\ prevTmp' = [prevTmp EXCEPT ![v] = NoVer]
              /\ ld' = [ld EXCEPT ![v].pc = "Dispatch"]
              /\ UNCHANGED <<prev, remTmp, finTmp, marker, trash, dnPrev, dnOk>>
         [] st = "COMPLETE_ROLLBACK" ->                          \* ST:808-812 deleteDir(removed.tmp)
              /\ remTmp' = [remTmp EXCEPT ![v] = NoVer]
              /\ ld' = [ld EXCEPT ![v].pc = "Dispatch"]
              /\ UNCHANGED <<cur, prev, prevTmp, finTmp, marker, trash, dnPrev, dnOk>>
         [] st = "RECOVER_ROLLBACK" ->                           \* ST:813-817 rename removed.tmp -> current (rollback undone)
              /\ cur' = [cur EXCEPT ![v] = remTmp[v]]
              /\ remTmp' = [remTmp EXCEPT ![v] = NoVer]
              /\ ld' = [ld EXCEPT ![v].pc = "Dispatch"]
              /\ UNCHANGED <<prev, prevTmp, finTmp, marker, trash, dnPrev, dnOk>>
         [] st = "COMPLETE_FINALIZE" ->                          \* ST:818-822 deleteAsync(finalized.tmp)
              /\ finTmp' = [finTmp EXCEPT ![v] = FALSE]
              /\ ld' = [ld EXCEPT ![v].pc = "Dispatch"]
              /\ UNCHANGED <<cur, prev, prevTmp, remTmp, marker, trash, dnPrev, dnOk>>
         [] OTHER ->                                             \* InconsistentFSStateException from analyzeStorage
              /\ FailWith(v, st)
              /\ UNCHANGED volDisk
    /\ UNCHANGED <<nnVars, envVars, shared, dnCtl, targetFired>>

(***************************************************************************)
(* BPSS.format L283-292 (NOT_FORMATTED). Writes the SHARED fields, then    *)
(* writes the shared fields (whatever they hold by then) into this         *)
(* volume's VERSION.                                                       *)
(***************************************************************************)
FormatSetLV(v) ==                              \* L287 this.layoutVersion = getCurrentLayoutVersion()
    /\ ld[v].pc = "FormatLV"
    /\ memLV' = CurLV
    /\ ld' = [ld EXCEPT ![v].pc = "FormatC"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, memC, dnCtl, targetFired>>

FormatSetCTime(v) ==                           \* L288 this.cTime = nsInfo.getCTime()
    /\ ld[v].pc = "FormatC"
    /\ memC' = nsC
    /\ ld' = [ld EXCEPT ![v].pc = "FormatWrite"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, memLV, dnCtl, targetFired>>

FormatWriteVersion(v) ==                       \* L289-290 namespaceID/blockpoolID (constant); L291 writeProperties(bpSdir)
    /\ ld[v].pc = "FormatWrite"
    /\ cur' = [cur EXCEPT ![v] = Ver(memLV, memC)]   \* BPSS:316-323 setPropertiesFromFields reads the shared fields
    /\ ld' = [ld EXCEPT ![v].pc = "Dispatch"]
    /\ UNCHANGED <<nnVars, envVars, prev, prevTmp, remTmp, finTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

(***************************************************************************)
(* BPSS.doTransition L369-425                                              *)
(***************************************************************************)
\* L372-374 PROVIDED storage: not modeled. L375-387 rollback dispatch (reads only this volume's disk).
DoTransitionDispatch(v) ==
    /\ ld[v].pc = "Dispatch"
    /\ IF Opt(v) = "ROLLBACK" /\ prev[v].ok                      \* L375
         THEN IF trash[v]                                        \* L376-378 Preconditions.checkState(!trash)
                THEN FailWith(v, "B376")                         \* IllegalStateException
                ELSE ld' = [ld EXCEPT ![v].pc = "RbRenameCur"]   \* L379 doRollback(sd, nsInfo)
       ELSE IF Opt(v) = "ROLLBACK"                               \* L380-381 ROLLBACK && !previous
         THEN ld' = [ld EXCEPT ![v].pc = "RbRestoreTrash"]
       ELSE ld' = [ld EXCEPT ![v].pc = "ReadPropsLV"]            \* L388
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnCtl, targetFired>>

\* BPSS.doRollback L603-645, split at the three renames/deletes (crash windows).
DoRollbackRenameCurrent(v) ==
    /\ ld[v].pc = "RbRenameCur"
    \* L605-609 prevDir exists (checked at L375); L611-612 read previous/VERSION into a throw-away BPSS
    /\ IF ~(prev[v].lv >= CurLV /\ prev[v].c <= nsC)            \* L618-620
         THEN /\ FailWith(v, "B621")                             \* L621-626 "Cannot rollback to a newer state."
              /\ UNCHANGED <<cur, remTmp>>
         ELSE /\ remTmp' = [remTmp EXCEPT ![v] = cur[v]]         \* L632-637 rename(current, removed.tmp)
              /\ cur' = [cur EXCEPT ![v] = NoVer]
              /\ ld' = [ld EXCEPT ![v].pc = "RbRenamePrev"]
    /\ UNCHANGED <<nnVars, envVars, prev, prevTmp, finTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

DoRollbackRenamePrevious(v) ==                 \* L639-640 rename(previous, current)
    /\ ld[v].pc = "RbRenamePrev"
    /\ cur' = [cur EXCEPT ![v] = prev[v]]
    /\ prev' = [prev EXCEPT ![v] = NoVer]
    /\ ld' = [ld EXCEPT ![v].pc = "RbDeleteTmp"]
    /\ UNCHANGED <<nnVars, envVars, prevTmp, remTmp, finTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

DoRollbackDeleteTmp(v) ==                      \* L642-643 deleteDir(removed.tmp)
    /\ ld[v].pc = "RbDeleteTmp"
    /\ remTmp' = [remTmp EXCEPT ![v] = NoVer]
    /\ ld' = [ld EXCEPT ![v].pc = "ReadPropsLV"]
    /\ UNCHANGED <<nnVars, envVars, cur, prev, prevTmp, finTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

RestoreTrashForRollback(v) ==                  \* L382-386 restoreBlockFilesFromTrash (BPSS:550-589 fullyDelete(trash)); cTime unchanged
    /\ ld[v].pc = "RbRestoreTrash"
    /\ trash' = [trash EXCEPT ![v] = FALSE]
    /\ ld' = [ld EXCEPT ![v].pc = "ReadPropsLV"]
    /\ UNCHANGED <<nnVars, envVars, cur, prev, prevTmp, remTmp, finTmp, marker, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

\* L388 readProperties(sd): SI:147-150 reads current/VERSION, then BPSS.setFieldsFromProperties L341-349
\* writes the SHARED fields one after the other.
ReadPropertiesLV(v) ==
    /\ ld[v].pc = "ReadPropsLV"
    /\ IF ~cur[v].ok
         THEN /\ FailWith(v, "B388")                             \* SI:252-259 property missing (VERSION absent)
              /\ UNCHANGED memLV
         ELSE /\ memLV' = cur[v].lv                              \* BPSS:343 -> SI:216-223 (L219 future-LV check passes: lv >= CurLV)
              /\ ld' = [ld EXCEPT ![v].pc = "ReadPropsC"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, memC, dnCtl, targetFired>>

ReadPropertiesCTime(v) ==
    /\ ld[v].pc = "ReadPropsC"
    /\ memC' = cur[v].c                        \* BPSS:345 -> SI:195-198 (same VERSION read; no other thread writes this volume)
    \* BPSS:344 setNamespaceID / BPSS:347-348 setBlockPoolID: single namespace and bpid.
    \* L389 checkVersionUpgradable(this.layoutVersion) (ST:1146-1163) and the L390 assert pass for every
    \* value any thread writes to memLV (CurLV, OldLV); L392-403 namespaceID / blockpoolID match.
    /\ ld' = [ld EXCEPT ![v].pc = "L404"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, memLV, dnCtl, targetFired>>

CheckRegularLV(v) ==                           \* L404 this.layoutVersion == getCurrentLayoutVersion()
    /\ ld[v].pc = "L404"
    /\ Goto(v, IF memLV = CurLV THEN "L405" ELSE "L408")

CheckRegularCTime(v) ==                        \* L405 && this.cTime == nsInfo.getCTime()
    /\ ld[v].pc = "L405"
    /\ IF memC = nsC
         THEN ld' = [ld EXCEPT ![v].pc = "PostCheckC"]            \* L406 return false (regular startup) -> BPSS:181-184
         ELSE ld' = [ld EXCEPT ![v].pc = "L408", ![v].c405 = memC]
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnCtl, targetFired>>

CheckLayoutForTrash(v) ==                      \* L408 this.layoutVersion > getCurrentLayoutVersion()
    /\ ld[v].pc = "L408"
    /\ Goto(v, IF memLV > CurLV THEN "L409" ELSE "L414")

RestoreTrashBeforeLayoutUpgrade(v) ==          \* L409-412 restoreBlockFilesFromTrash (file I/O window between the guard reads)
    /\ ld[v].pc = "L409"
    /\ trash' = [trash EXCEPT ![v] = FALSE]
    /\ ld' = [ld EXCEPT ![v].pc = "L414"]
    /\ UNCHANGED <<nnVars, envVars, cur, prev, prevTmp, remTmp, finTmp, marker, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

CheckUpgradeLV(v) ==                           \* L414 this.layoutVersion > getCurrentLayoutVersion() (first operand)
    /\ ld[v].pc = "L414"
    /\ Goto(v, IF memLV > CurLV THEN "UpDelDnPrev" ELSE "TargetCheck")   \* L416 doUpgrade via short-circuit

\* Value of this.cTime used at L415: a fresh read of the shared field, or (when L405 was evaluated)
\* the L405 value reused by the JIT -- both are legal under the JMM (no synchronization in between).
C415(v) == {memC} \cup (IF ld[v].c405 = NoC THEN {} ELSE {ld[v].c405})

\* THE TARGET. BPSS.doTransition L414-L424 (second operand at L415, throw at L421).
TargetCheck(v) ==
    /\ ld[v].pc = "TargetCheck"
    /\ \E c \in C415(v) :
         IF c < nsC                                              \* L415 || this.cTime < nsInfo.getCTime()
           THEN /\ ld' = [ld EXCEPT ![v].pc = "UpDelDnPrev"]     \* L416-417 doUpgrade(...); return true
                /\ targetFired' = targetFired
           ELSE /\ targetFired' = TRUE                           \* L419-424 throw new IOException("Datanode state: LV = "
                /\ FailWith(v, "B421")                           \*   + ... + " is newer than the namespace state: ...")
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnCtl>>

(***************************************************************************)
(* BPSS.doUpgrade L445-501 and doUpgrade(String, ...) L503-519             *)
(***************************************************************************)
DoUpgradeDeleteDnPrevious(v) ==
    /\ ld[v].pc = "UpDelDnPrev"
    \* L450-453 supports(FEDERATION, this.layoutVersion): true for CurLV / OldLV; L455-457 PROVIDED: n/a;
    \* L458 oldLV only selects the block-file layout conversion (block files are not modeled)
    /\ dnPrev' = [dnPrev EXCEPT ![v] = FALSE]  \* L464-471 delete <SD>/previous if it exists
    \* L475 cleanupDetachDir: no detach dir for layouts with APPEND_RBW_DIR
    /\ ld' = [ld EXCEPT ![v].pc = "UpDelPrev"]
    /\ UNCHANGED <<nnVars, envVars, cur, prev, prevTmp, remTmp, finTmp, marker, trash, dnOk,
                   shared, dnCtl, targetFired>>

DoUpgradeDeletePrevious(v) ==                  \* L477-480 delete <SD>/current/<bpid>/previous before upgrading
    /\ ld[v].pc = "UpDelPrev"
    /\ prev' = [prev EXCEPT ![v] = NoVer]
    /\ ld' = [ld EXCEPT ![v].pc = "UpRenameCur"]
    /\ UNCHANGED <<nnVars, envVars, cur, prevTmp, remTmp, finTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

DoUpgradeRenameCurrent(v) ==                   \* L481-486 rename(current, previous.tmp)
    /\ ld[v].pc = "UpRenameCur"
    /\ prevTmp' = [prevTmp EXCEPT ![v] = cur[v]]
    /\ cur' = [cur EXCEPT ![v] = NoVer]
    /\ IF ld[v].mode = "hotswap"
         THEN /\ ld' = [ld EXCEPT ![v].pc = "LinkBlocks"]       \* L489-490 callables == null: upgrade inline
              /\ UNCHANGED bpLoaded
         ELSE /\ ld' = [ld EXCEPT ![v].pc = "CallableWait"]     \* L491-500 deferred; L417 return true;
              /\ bpLoaded' = bpLoaded \cup {v}                   \* BPSS:192, 228, 259-261 sd added to the BPSS
    /\ UNCHANGED <<nnVars, envVars, prev, remTmp, finTmp, marker, trash, dnPrev, dnOk, shared,
                   dnUp, startOpt, nsC, bpInit, dnLoaded, visited, dnRegC, trashEnabled, targetFired>>

LinkAllBlocks(v) ==                            \* L508 linkAllBlocks(previous.tmp -> current): new current/ without VERSION
    /\ ld[v].pc = "LinkBlocks"
    /\ Goto(v, "UpSetLV")

DoUpgradeSetLV(v) ==                           \* L509 this.layoutVersion = getCurrentLayoutVersion()
    /\ ld[v].pc = "UpSetLV"
    /\ memLV' = CurLV
    /\ ld' = [ld EXCEPT ![v].pc = "UpSetC"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, memC, dnCtl, targetFired>>

DoUpgradeSetCTime(v) ==                        \* L510-511 assert namespaceID; L512 this.cTime = nsInfo.getCTime()
    /\ ld[v].pc = "UpSetC"
    /\ memC' = nsC
    /\ ld' = [ld EXCEPT ![v].pc = "UpWrite"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, memLV, dnCtl, targetFired>>

DoUpgradeWriteVersion(v) ==                    \* L513 writeProperties(bpSd): the SHARED fields
    /\ ld[v].pc = "UpWrite"
    /\ cur' = [cur EXCEPT ![v] = Ver(memLV, memC)]
    /\ ld' = [ld EXCEPT ![v].pc = "UpRenameTmp"]
    /\ UNCHANGED <<nnVars, envVars, prev, prevTmp, remTmp, finTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

DoUpgradeRenameTmp(v) ==                       \* L515-518 rename(previous.tmp, previous)
    /\ ld[v].pc = "UpRenameTmp"
    /\ prev' = [prev EXCEPT ![v] = prevTmp[v]]
    /\ prevTmp' = [prevTmp EXCEPT ![v] = NoVer]
    /\ ld' = IF ld[v].mode = "hotswap"
               THEN [ld EXCEPT ![v].pc = "Commit"]               \* L417 return true -> BPSS:192 -> DS:343 -> FSD:527-560
               ELSE [ld EXCEPT ![v] = IdleLd]                     \* callable done: DS:488-490 success.add(future.get())
    /\ UNCHANGED <<nnVars, envVars, cur, remTmp, finTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, targetFired>>

(***************************************************************************)
(* BPSS.loadStorageDirectory L181-196 after doTransition returned false    *)
(***************************************************************************)
CheckCTimeAfterLoad(v) ==                      \* L184-187
    /\ ld[v].pc = "PostCheckC"
    /\ IF memC /= nsC
         THEN FailWith(v, "B185")                                \* IOException "Datanode CTime (=..) is not equal to namenode CTime"
         ELSE ld' = [ld EXCEPT ![v].pc = "PostSetLV"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnCtl, targetFired>>

SetServiceLayoutVersion(v) ==                  \* L188 setServiceLayoutVersion(getServiceLayoutVersion()) (SI:237-245)
    /\ ld[v].pc = "PostSetLV"
    /\ memLV' = CurLV
    /\ ld' = [ld EXCEPT ![v].pc = "PostWrite"]
    /\ UNCHANGED <<nnVars, envVars, volDisk, memC, dnCtl, targetFired>>

WritePropertiesAfterLoad(v) ==                 \* L189 writeProperties(sd): the SHARED fields; L192 return sd
    /\ ld[v].pc = "PostWrite"
    /\ cur' = [cur EXCEPT ![v] = Ver(memLV, memC)]
    /\ IF ld[v].mode = "hotswap"
         THEN /\ ld' = [ld EXCEPT ![v].pc = "Commit"]
              /\ UNCHANGED bpLoaded
         ELSE /\ ld' = [ld EXCEPT ![v] = IdleLd]
              /\ bpLoaded' = bpLoaded \cup {v}                   \* BPSS:259-261 addStorageDir; DS:466-469
    /\ UNCHANGED <<nnVars, envVars, prev, prevTmp, remTmp, finTmp, marker, trash, dnPrev, dnOk, shared,
                   dnUp, startOpt, nsC, bpInit, dnLoaded, visited, dnRegC, trashEnabled, targetFired>>

\* BPSS:193-195 catch (IOException): sd.unlock(); rethrow -> BPSS:229-232 -> startup: DS:473-476 (volume
\* skipped); hot swap: DS:341 -> FSD:520-525 -> DN:1335-1340 "FAILED TO ADD". The IllegalStateException
\* of L376 is not an IOException: at startup it escapes DS:473 and aborts the whole block-pool init
\* (DS:382-400 -> DN.initBlockPool -> BPOS:403-409).
LoadStorageDirectoryFail(v) ==
    /\ ld[v].pc = "Fail"
    /\ IF ld[v].err = "B376" /\ ld[v].mode = "startup"
         THEN /\ ld' = [w \in Vol |-> IdleLd]
              /\ bpInit' = "failed"
         ELSE /\ ld' = [ld EXCEPT ![v] = IdleLd]
              /\ UNCHANGED bpInit
    /\ UNCHANGED <<nnVars, envVars, volDisk, shared, dnUp, startOpt, nsC, dnLoaded, bpLoaded, visited,
                   dnRegC, trashEnabled, targetFired>>

(***************************************************************************)
(* Heartbeat-driven DataNode work (needs a registration whose cTime        *)
(* matches the NN: NNRPC:1777-1787 verifyRequest, ST:1417-1421; on a       *)
(* mismatch the actor exits, BPSA:791-799).                                *)
(***************************************************************************)

\* Scenario 3. BPSA:735-744 (ACTIVE NN) -> handleRollingUpgradeStatus L656-667 ->
\* BPOS.signalRollingUpgrade L554-567, over the DN-level storage dirs (DS:192-198). Per volume.
SignalRollingUpgrade(v) ==
    /\ dnUp
    /\ bpInit = "done"
    /\ dnRegC = nnC
    /\ v \in dnLoaded
    /\ nnRU /= "none"                                            \* BPOS:556-558 status == null -> return
    /\ IF nnRU = "inprogress"
         THEN \* BPOS:560-562 enableTrash (DS:173-178) + setRollingUpgradeMarkers (BPSS:863-881)
              /\ ~marker[v] \/ ~trashEnabled
              /\ trashEnabled' = TRUE
              /\ marker' = [marker EXCEPT ![v] = TRUE]          \* BPSS:869-873 createNewFile
              /\ UNCHANGED <<trash, prev, finTmp>>
         ELSE \* BPOS:563-565 clearTrash (DS:180-186 -> BPSS:810-839) + clearRollingUpgradeMarkers (BPSS:889-909)
              /\ marker[v] \/ trashEnabled
              /\ trash' = IF trashEnabled                        \* DS:181 only if trash is enabled in this process
                            THEN [w \in Vol |-> IF w \in bpLoaded /\ ~prev[w].ok THEN FALSE ELSE trash[w]]
                            ELSE trash                           \* BPSS:812-821 dirs with previous are skipped (prod, no -ea)
              /\ trashEnabled' = FALSE                           \* DS:183
              /\ IF marker[v]                                    \* BPSS:898 marker exists
                   THEN /\ IF prev[v].ok                         \* BPSS:900 doFinalize -> L651-670
                             THEN /\ prev' = [prev EXCEPT ![v] = NoVer]       \* L670 rename(previous, finalized.tmp)
                                  /\ finTmp' = [finTmp EXCEPT ![v] = TRUE]
                             ELSE UNCHANGED <<prev, finTmp>>                \* L659-661 already finalized
                        /\ marker' = [marker EXCEPT ![v] = FALSE]           \* BPSS:901-903
                   ELSE UNCHANGED <<prev, finTmp, marker>>
    /\ UNCHANGED <<nnVars, envVars, cur, prevTmp, remTmp, dnPrev, dnOk, shared, dnUp, startOpt, nsC,
                   bpInit, dnLoaded, bpLoaded, visited, dnRegC, ld, targetFired>>

\* Scenario 3: during an RU deleted replicas go to trash (DS:209-214 -> BPSS:768-788), only where no
\* previous exists (BPSS:747-757 isTrashAllowed).
TrashBlockDelete(v) ==
    /\ dnUp
    /\ trashEnabled
    /\ v \in bpLoaded
    /\ ~prev[v].ok
    /\ ~trash[v]
    /\ trash' = [trash EXCEPT ![v] = TRUE]
    /\ UNCHANGED <<nnVars, envVars, cur, prev, prevTmp, remTmp, finTmp, marker, dnPrev, dnOk,
                   shared, dnCtl, ld, targetFired>>

\* DNA_FINALIZE: NNRPC:1682-1687 (upgrade finalized, no RU in progress, active) in the block-report
\* response -> BPOS:774-781 -> DN.finalizeUpgradeForPool L3660-3662 -> DS.finalizeUpgrade L1016-1031,
\* over the DN-level storage dirs (including volumes whose BP load failed). Per volume.
FinalizeUpgradeForVolume(v) ==
    /\ dnUp
    /\ bpInit = "done"
    /\ dnRegC = nnC
    /\ nnPrevC = NoC                                             \* NNRPC:1682 isUpgradeFinalized
    /\ nnRU /= "inprogress"                                      \* NNRPC:1683 !isRollingUpgrade
    /\ v \in dnLoaded
    /\ dnPrev[v] \/ prev[v].ok
    /\ IF dnPrev[v]                                              \* DS:1021-1024 DN-level previous: DS.doFinalize L974-1008
         THEN /\ dnPrev' = [dnPrev EXCEPT ![v] = FALSE]
              /\ UNCHANGED <<prev, finTmp>>
         ELSE /\ prev' = [prev EXCEPT ![v] = NoVer]              \* DS:1026-1028 -> BPSS.doFinalize L651-670
              /\ finTmp' = [finTmp EXCEPT ![v] = TRUE]           \* L668-670 rename(previous, finalized.tmp)
              /\ UNCHANGED dnPrev
    /\ UNCHANGED <<nnVars, envVars, cur, prevTmp, remTmp, marker, trash, dnOk, shared, dnCtl, ld, targetFired>>

\* BPSS:672-688 (and DS:992-1007) the finalize daemon deletes finalized.tmp.
FinalizeTmpDelete(v) ==
    /\ dnUp
    /\ finTmp[v]
    /\ finTmp' = [finTmp EXCEPT ![v] = FALSE]
    /\ UNCHANGED <<nnVars, envVars, cur, prev, prevTmp, remTmp, marker, trash, dnPrev, dnOk,
                   shared, dnCtl, ld, targetFired>>

(***************************************************************************)
(* Volume availability (fault model: a disk offline and back, an empty     *)
(* or replaced disk).                                                      *)
(***************************************************************************)
\* A disk fails or is unplugged. A loaded volume is removed by the DN's volume-failure handling
\* (DN.handleVolumeFailures L4065 -> DS.removeVolumes L510-547: BP level first, then DN level).
VolumeOffline(v) ==
    /\ online[v]
    /\ ld[v].pc = "idle"
    /\ online' = [online EXCEPT ![v] = FALSE]
    /\ dnLoaded' = dnLoaded \ {v}
    /\ bpLoaded' = bpLoaded \ {v}
    /\ UNCHANGED <<nnVars, mustRollback, volDisk, shared, dnUp, startOpt, nsC, bpInit, visited, ld,
                   dnRegC, trashEnabled, targetFired>>

\* The disk comes back with its content (not re-added until a restart or a hot swap).
VolumeOnline(v) ==
    /\ ~online[v]
    /\ online' = [online EXCEPT ![v] = TRUE]
    /\ UNCHANGED <<nnVars, mustRollback, volDisk, shared, dnCtl, ld, targetFired>>

\* A new or replaced, empty disk at a configured location that the DN is not using.
AttachEmptyVolume(v) ==
    /\ v \notin dnLoaded
    /\ ld[v].pc = "idle"
    /\ ~online[v] \/ ~IsEmpty(v)
    /\ online' = [online EXCEPT ![v] = TRUE]
    /\ cur' = [cur EXCEPT ![v] = NoVer]
    /\ prev' = [prev EXCEPT ![v] = NoVer]
    /\ prevTmp' = [prevTmp EXCEPT ![v] = NoVer]
    /\ remTmp' = [remTmp EXCEPT ![v] = NoVer]
    /\ finTmp' = [finTmp EXCEPT ![v] = FALSE]
    /\ marker' = [marker EXCEPT ![v] = FALSE]
    /\ trash' = [trash EXCEPT ![v] = FALSE]
    /\ dnPrev' = [dnPrev EXCEPT ![v] = FALSE]
    /\ UNCHANGED <<nnVars, mustRollback, dnOk, shared, dnCtl, ld, targetFired>>

(***************************************************************************)
(* Next                                                                    *)
(***************************************************************************)
LoaderStep(v) ==
    \/ AnalyzeStorage(v)
    \/ FormatSetLV(v) \/ FormatSetCTime(v) \/ FormatWriteVersion(v)
    \/ DoTransitionDispatch(v)
    \/ DoRollbackRenameCurrent(v) \/ DoRollbackRenamePrevious(v) \/ DoRollbackDeleteTmp(v)
    \/ RestoreTrashForRollback(v)
    \/ ReadPropertiesLV(v) \/ ReadPropertiesCTime(v)
    \/ CheckRegularLV(v) \/ CheckRegularCTime(v)
    \/ CheckLayoutForTrash(v) \/ RestoreTrashBeforeLayoutUpgrade(v)
    \/ CheckUpgradeLV(v) \/ TargetCheck(v)
    \/ DoUpgradeDeleteDnPrevious(v) \/ DoUpgradeDeletePrevious(v) \/ DoUpgradeRenameCurrent(v)
    \/ LinkAllBlocks(v) \/ DoUpgradeSetLV(v) \/ DoUpgradeSetCTime(v)
    \/ DoUpgradeWriteVersion(v) \/ DoUpgradeRenameTmp(v)
    \/ CheckCTimeAfterLoad(v) \/ SetServiceLayoutVersion(v) \/ WritePropertiesAfterLoad(v)
    \/ LoadStorageDirectoryFail(v)
    \/ HotSwapBuild(v)

\* The individual actions do not test targetFired: Trace.tla replays the workload past the L421
\* throw (the exception is caught and the DataNode continues). For model checking, "once the
\* target fired, everything stops" (adhoc tla-patterns.md section 1) is the state constraint
\* StopAfterTarget below: TLC still checks every invariant on the state where targetFired becomes
\* TRUE but explores no successor of it. Keeping Next a plain disjunction lets TLC label each step
\* of a counterexample with its action name.
Next ==
    \/ NNDoUpgrade(MaxIssued + 1)
    \/ \E c \in 0..MaxIssued : NNDoUpgrade(c)                   \* Scenario 4 clock fault
    \/ NNDoRollback
    \/ NNFinalizeUpgrade
    \/ \E c \in issued : NNCTimeRegress(c)                       \* Scenario 4 directory split
    \/ NNStartRollingUpgrade \/ NNFinalizeRollingUpgrade \/ NNCheckpoint \/ NNRestart
    \/ \E o \in {"REGULAR", "ROLLBACK"} : DataNodeStart(o)
    \/ DataNodeStop \/ DataNodeCrash
    \/ SubmitUpgradeCallables \/ BlockPoolInitDone
    \/ \E S \in SUBSET Vol : RefreshVolumes(S)
    \/ \E v \in Vol :
         \/ LoadBlockPoolSliceStorageNext(v)
         \/ LoaderStep(v)
         \/ SignalRollingUpgrade(v) \/ TrashBlockDelete(v)
         \/ FinalizeUpgradeForVolume(v) \/ FinalizeTmpDelete(v)
         \/ VolumeOffline(v) \/ VolumeOnline(v) \/ AttachEmptyVolume(v)

Spec == Init /\ [][Next]_vars

\* State constraint used by every model-checking config: stop after the target fired.
StopAfterTarget == ~targetFired

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)
\* The ad hoc check never fails (adhoc-coordination Shared Rule 1).
TargetSafe == ~targetFired

VerSet == {NoVer} \cup [ok : {TRUE}, lv : LVs, c : Nat]
LdSet  == [pc : Pcs, mode : Modes, c405 : Nat \cup {NoC}, err : Errs]

\* Structural sanity 1: variable domains.
TypeOK ==
    /\ nnC \in Nat
    /\ nnPrevC \in Nat \cup {NoC}
    /\ nnRU \in {"none", "inprogress", "finalized"}
    /\ ruAfterImage \in BOOLEAN
    /\ issued \subseteq Nat
    /\ online \in [Vol -> BOOLEAN]
    /\ mustRollback \in BOOLEAN
    /\ cur \in [Vol -> VerSet]
    /\ prev \in [Vol -> VerSet]
    /\ prevTmp \in [Vol -> VerSet]
    /\ remTmp \in [Vol -> VerSet]
    /\ finTmp \in [Vol -> BOOLEAN]
    /\ marker \in [Vol -> BOOLEAN]
    /\ trash \in [Vol -> BOOLEAN]
    /\ dnPrev \in [Vol -> BOOLEAN]
    /\ dnOk \in [Vol -> BOOLEAN]
    /\ dnUp \in BOOLEAN
    /\ startOpt \in {"REGULAR", "ROLLBACK"}
    /\ nsC \in Nat \cup {NoC}
    /\ memLV \in LVs \cup {InitLV}
    /\ memC \in Nat \cup {NoC}
    /\ bpInit \in {"none", "loading", "callables", "done", "failed"}
    /\ dnLoaded \subseteq Vol
    /\ bpLoaded \subseteq Vol
    /\ visited \subseteq Vol
    /\ ld \in [Vol -> LdSet]
    /\ dnRegC \in Nat \cup {NoC}
    /\ trashEnabled \in BOOLEAN
    /\ targetFired \in BOOLEAN

\* Structural sanity 2: a loader, a VERSION file or a registration holds only cTimes that some
\* VERSION file or nsInfo held (no value is invented).
CTimeProvenance ==
    /\ \A v \in Vol :
         /\ cur[v].ok => cur[v].c \in issued
         /\ prev[v].ok => prev[v].c \in issued
         /\ prevTmp[v].ok => prevTmp[v].c \in issued
         /\ remTmp[v].ok => remTmp[v].c \in issued
         /\ ld[v].c405 /= NoC => ld[v].c405 \in issued
    /\ nnPrevC /= NoC => nnPrevC \in issued
    /\ nnC \in issued
    /\ memC /= NoC => memC \in issued
    /\ nsC /= NoC => nsC \in issued
    /\ dnRegC /= NoC => dnRegC \in issued

\* Temporary sanity check (adhoc tla-patterns.md section 2): MUST be violated by MC_sanity_reach.cfg,
\* i.e. some loader reaches the code path of the check (pc after the L414 read).
TargetReached == ~(\E v \in Vol : ld[v].pc = "TargetCheck")

\* For base.cfg only: the base spec issues ever-larger cTimes and has no fault bounds.
BaseConstraint == MaxIssued <= 2
BaseInitLVs == {CurLV, OldLV}

=============================================================================
