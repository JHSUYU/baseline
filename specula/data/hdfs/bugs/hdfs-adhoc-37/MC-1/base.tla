-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-37: DataStorage.doRollback rollback guard (DataStorage.java  *)
(* L939-947, throw at L942, InconsistentFSStateException).                 *)
(*                                                                         *)
(* Category A (modeling brief Section 1). The guard compares a DataNode's  *)
(* DataNode-level snapshot (<SD>/previous/VERSION, read into a fresh       *)
(* DataStorage) with the NamespaceInfo cTime that the initializing         *)
(* BPServiceActor got from its NameNode by versionRequest.                 *)
(*                                                                         *)
(* Pinned tree 734dd8a67cd. Path abbreviations (all under                  *)
(* hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/): *)
(*   DS    server/datanode/DataStorage.java                                *)
(*   BPSS  server/datanode/BlockPoolSliceStorage.java                      *)
(*   ST    server/common/Storage.java                                      *)
(*   SI    server/common/StorageInfo.java                                  *)
(*   DN    server/datanode/DataNode.java                                   *)
(*   BPOS  server/datanode/BPOfferService.java                             *)
(*   BPSA  server/datanode/BPServiceActor.java                             *)
(*   FDI   server/datanode/fsdataset/impl/FsDatasetImpl.java               *)
(*   FSI   server/namenode/FSImage.java                                    *)
(*   FSN   server/namenode/FSNamesystem.java                               *)
(*   NNS   server/namenode/NNStorage.java                                  *)
(*   NNU   server/namenode/NNUpgradeUtil.java                              *)
(*   NNM   server/namenode/NameNode.java                                   *)
(*   NNRPC server/namenode/NameNodeRpcServer.java                          *)
(*   UU    (test) UpgradeUtilities.java                                    *)
(*                                                                         *)
(* Abstractions (brief Sections 3.1/3.2):                                  *)
(*  - cTimes are integers that keep the order of the real millisecond      *)
(*    values; ranks in traces. NoCT = -1 means "no VERSION file".          *)
(*  - DataNode layout versions are classes derived from supports():        *)
(*      "ancient" LV > -16 (LAST_UPGRADABLE_LAYOUT_VERSION, ST:91),        *)
(*      "legacy"  pre-federation (no FEDERATION: -16..-34, -41, -44),      *)
(*      "pinned"  the current DataNode LV (-57),                           *)
(*      "future"  LV < -57 (SI:216-221 rejects it on every read).          *)
(*    Federation-era older LVs are not produced by any modeled path.       *)
(*  - NameNode layout classes: "pinned" (current NN LV), "legacy" (an      *)
(*    older valid LV; needs -upgrade, FSI:270-285), "bad" (unreadable or   *)
(*    nonsense VERSION; fixture only).                                     *)
(*  - All name directories of one NameNode are identical copies; one       *)
(*    logical (current, previous) pair per NameNode.                       *)
(*  - The block-pool level (BPSS) is one atomic step per location; its     *)
(*    crash windows and trash are not modeled (no effect on either         *)
(*    operand of the target guard).                                        *)
(*  - Rolling upgrade is not modeled: it never writes cTime and only       *)
(*    blocks FinalizeCommand, which the model never forces anyway          *)
(*    (brief-coverage.md, Scenario 3).                                     *)
(*  - DataNode.checkDatanodeUuid -> Storage.writeAll (DN:2060-2067, 2273;  *)
(*    ST:1396-1401) is not modeled. It runs when no loaded VERSION carried *)
(*    a datanodeUuid (the first start after a legacy upgrade) and rewrites *)
(*    the current/VERSION of every loaded location as (CUR, shared cTime); *)
(*    it never touches previous/ and never writes a pre-federation LV, so  *)
(*    it can only remove snapshot-creation behaviors (it repairs a         *)
(*    race-mislabeled LV). Omitting it over-approximates the snapshots.    *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Dir,           \* DataNode storage locations, numbered in dfs.datanode.data.dir order
    Ns1NN,         \* NameNodes of namespace 1, the pre-federation namespace (HA peers if > 1)
    Ns2NN,         \* NameNodes of namespace 2, formatted in the pinned era ({} = no federation)
    ActiveNN,      \* NameNodes whose actor is bpServiceToActive (one per namespace)
    LegacyNN,      \* the NameNode of namespace 1 that holds the legacy (pre-federation) image
    DirCtA,        \* legacy cTime in <SD>/current/VERSION of location 1
    DirCtB,        \* legacy cTime in <SD>/current/VERSION of the other locations
    InitPrevDirs,  \* locations that carry a legacy-era <SD>/previous (hadoop-22-dfs-dir.tgz shape)
    InitPrevLv,    \* its layout class ("ancient" in hadoop-22-dfs-dir.tgz: LV -7)
    InitPrevCt,    \* its cTime
    InitNnCt,      \* the legacy NameNode cTime
    FirstStamp,    \* first pinned-era clock reading; above every legacy cTime
    MaxCT          \* largest cTime value (type bound)

NN == Ns1NN \cup Ns2NN
Ns == IF Ns2NN = {} THEN {1} ELSE {1, 2}
NsOf(n) == IF n \in Ns1NN THEN 1 ELSE 2
Peers(n) == {m \in NN : NsOf(m) = NsOf(n) /\ m # n}

ASSUME /\ Dir \subseteq Nat \ {0} /\ Dir # {}
       /\ Ns1NN # {} /\ Ns1NN \cap Ns2NN = {}
       /\ LegacyNN \in Ns1NN
       /\ ActiveNN \subseteq NN
       /\ InitPrevDirs \subseteq Dir
       /\ InitPrevLv \in {"ancient", "legacy"}
       /\ {DirCtA, DirCtB, InitPrevCt, InitNnCt, FirstStamp} \subseteq 0..MaxCT

----------------------------------------------------------------------------
(* Values *)

NoCT  == -1
CTv   == 0..MaxCT
CTo   == CTv \cup {NoCT}
NoNN  == "none"

DnLv == {"ancient", "legacy", "pinned", "future"}
NnLv == {"legacy", "pinned", "bad"}

\* A VERSION file: layout class, cTime, and whether it has a clusterID key.
\* Pre-federation VERSION files have none; every file the pinned code writes
\* has one (setPropertiesFromFields, DS:595).
NoVer == [lv |-> "none", ct |-> NoCT, cid |-> FALSE]
MkVer(l, c, k) == [lv |-> l, ct |-> c, cid |-> k]

\* Block-pool slice of one DataNode-level tree: <..>/<bpid>/current and
\* <..>/<bpid>/previous VERSION cTimes (the block-pool LV is always current).
NoBp == [cur |-> NoCT, prev |-> NoCT]
NoBpMap == [s \in Ns |-> NoBp]

\* A DataNode-level directory tree (<SD>/current, <SD>/previous or a temp
\* directory): its VERSION and its block-pool subtrees. A tree with neither
\* is an absent (or empty) directory.
EmptyTree == [ver |-> NoVer, bp |-> NoBpMap]
NoTmp == [kind |-> "none", tree |-> EmptyTree]

\* Fields of the shared DataStorage object that readProperties overwrites
\* and that the upgrade callable writes back (layoutVersion, cTime).
ShInit == [lv |-> "pinned", ct |-> 0]

\* The storage loader (initStorage under the DataNode monitor).
LdIdle == [busy |-> FALSE, owner |-> NoNN, ns |-> 0, ct |-> NoCT, q |-> <<>>,
           d |-> 0, pc |-> "none", tasks |-> {}, ok |-> {}, bpDone |-> {},
           bpOk |-> FALSE]

PcT == {"none", "trans", "read", "rb1", "rb2", "rb3", "pfDel", "pfRen"}
CbT == {"none", "sub", "set", "written", "done"}
AT  == {"down", "conn", "hs", "init", "stored", "initFailed", "run", "failed"}
OptT == {"REGULAR", "ROLLBACK"}

Max(a, b) == IF a >= b THEN a ELSE b
Range(f) == {f[i] : i \in DOMAIN f}

RECURSIVE SeqOfSet(_)
SeqOfSet(S) == IF S = {} THEN <<>>
               ELSE LET m == CHOOSE x \in S : \A y \in S : x <= y
                    IN <<m>> \o SeqOfSet(S \ {m})

\* dfs.datanode.data.dir in configuration order.
DirSeq == SeqOfSet(Dir)

LegacyCt(d) == IF d = 1 THEN DirCtA ELSE DirCtB

----------------------------------------------------------------------------
VARIABLES
    \* NameNode side
    nnCur,      \* [NN -> VERSION]: <name dir>/current/VERSION
    nnPrev,     \* [NN -> VERSION]: <name dir>/previous/VERSION (NoVer = none)
    nnUp,       \* [NN -> BOOLEAN]: NameNode process serving RPCs
    clock,      \* wall clock: the next normal Time.now() reading
    served,     \* [Ns -> SUBSET CTv]: cTimes ever served by versionRequest (history)
    \* DataNode disk
    dCur,       \* [Dir -> tree]: <SD>/current
    dPrev,      \* [Dir -> tree]: <SD>/previous
    dTmp,       \* [Dir -> [kind, tree]]: <SD>/previous.tmp or <SD>/removed.tmp
    \* DataNode process
    dnUp,       \* DataNode process running
    startOpt,   \* dfs.datanode.startup of the running process (DN:3447-3455)
    dnConf,     \* dfs.datanode.data.dir of the running process (a sequence)
    dsLoaded,   \* DataStorage.storageDirs (containsStorageDir, DS:409)
    bpLoaded,   \* [Ns -> SUBSET Dir]: BlockPoolSliceStorage.storageDirs per pool
    dataInit,   \* FsDataset created (DN:2275-2279)
    bposSet,    \* [Ns -> BOOLEAN]: BPOfferService.bpNSInfo # null
    aState,     \* [NN -> AT]: BPServiceActor of the NameNode
    aRetry,     \* [NN -> BOOLEAN]: runningState is INIT_FAILED (not CONNECTING)
    nsInfoCt,   \* [NN -> CTo]: cTime of the actor's last versionRequest
    regCt,      \* [Ns -> CTo]: cTime in the pool's DataNode registration
    ld,         \* the storage loader
    cb,         \* [Dir -> CbT]: DataNode-level upgrade callable of the location
    sh,         \* shared DataStorage fields [lv, ct]
    \* Oracle
    targetFired

nnVars    == <<nnCur, nnPrev, nnUp, clock, served>>
diskVars  == <<dCur, dPrev, dTmp>>
procVars  == <<dnUp, startOpt, dnConf, dsLoaded, bpLoaded, dataInit>>
actorVars == <<bposSet, aState, aRetry, nsInfoCt, regCt>>
loadVars  == <<ld, cb, sh>>
vars == <<nnVars, diskVars, procVars, actorVars, loadVars, targetFired>>

----------------------------------------------------------------------------
(* Initial state: a pre-federation (legacy) cluster that the pinned        *)
(* software is about to take over (brief Section 3.1). Every DataNode      *)
(* location holds a legacy current/; some hold a legacy-era previous/; the *)
(* legacy NameNode cannot serve until it is started with -upgrade.         *)

Init ==
    /\ nnCur = [n \in NN |-> IF n = LegacyNN THEN MkVer("legacy", InitNnCt, TRUE)
                             ELSE NoVer]
    /\ nnPrev = [n \in NN |-> NoVer]
    /\ nnUp = [n \in NN |-> FALSE]
    /\ clock = FirstStamp
    /\ served = [s \in Ns |-> {}]
    /\ dCur = [d \in Dir |-> [ver |-> MkVer("legacy", LegacyCt(d), FALSE), bp |-> NoBpMap]]
    /\ dPrev = [d \in Dir |-> IF d \in InitPrevDirs
                              THEN [ver |-> MkVer(InitPrevLv, InitPrevCt, FALSE), bp |-> NoBpMap]
                              ELSE EmptyTree]
    /\ dTmp = [d \in Dir |-> NoTmp]
    /\ dnUp = FALSE
    /\ startOpt = "REGULAR"
    /\ dnConf = DirSeq
    /\ dsLoaded = {}
    /\ bpLoaded = [s \in Ns |-> {}]
    /\ dataInit = FALSE
    /\ bposSet = [s \in Ns |-> FALSE]
    /\ aState = [n \in NN |-> "down"]
    /\ aRetry = [n \in NN |-> FALSE]
    /\ nsInfoCt = [n \in NN |-> NoCT]
    /\ regCt = [s \in Ns |-> NoCT]
    /\ ld = LdIdle
    /\ cb = [d \in Dir |-> "none"]
    /\ sh = ShInit
    /\ targetFired = FALSE

----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode cTime lifecycle (brief Sections 1 and 3.1; Scenarios 1-3).    *)
(* A stamp st is a Time.now() reading; st < clock is a clock that reads    *)
(* earlier than an earlier stamp (the CLOCK fault of Scenario 1, bounded   *)
(* in MC.tla).                                                             *)
(***************************************************************************)

\* FSImage.recoverTransitionRead refuses an older NameNode layout without
\* -upgrade/-upgradeOnly/-rollingUpgrade started (FSI:266-285).
CanServe(n) == nnCur[n].lv = "pinned"

NextClock(st) == IF st >= clock THEN st + 1 ELSE clock

\* hdfs namenode -format: NNStorage.newNamespaceInfo uses Time.now()
\* (NNS:626-629). The first NameNode of a namespace; an HA peer bootstraps.
NnFormat(n, st) ==
    /\ ~nnUp[n]
    /\ nnCur[n] = NoVer
    /\ \A m \in Peers(n) : nnCur[m] = NoVer
    /\ nnCur' = [nnCur EXCEPT ![n] = MkVer("pinned", st, TRUE)]
    /\ clock' = NextClock(st)
    /\ UNCHANGED <<nnPrev, nnUp, served>>
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

\* Regular NameNode start (no transition). Serves versionRequest with the
\* image cTime: new NamespaceInfo(getFSImage().getStorage(), ...)
\* (FSN:1903-1910, 1927-1929).
NnStart(n) ==
    /\ ~nnUp[n]
    /\ CanServe(n)                                             \* FSI:266-285
    /\ nnUp' = [nnUp EXCEPT ![n] = TRUE]
    /\ served' = [served EXCEPT ![NsOf(n)] = @ \cup {nnCur[n].ct}]
    /\ UNCHANGED <<nnCur, nnPrev, clock>>
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

NnStop(n) ==
    /\ nnUp[n]
    /\ nnUp' = [nnUp EXCEPT ![n] = FALSE]
    /\ UNCHANGED <<nnCur, nnPrev, clock, served>>
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

\* NameNode started with -upgrade: FSImage.doUpgrade (FSI:458-517).
\*  - checkUpgrade: no previous/ in any name dir (FSI:423-433, called at FSI:459);
\*  - storage.cTime = now() (FSI:464-465), the old value is only logged
\*    (FSI:466-476): nothing enforces monotonicity;
\*  - layoutVersion = service LV (FSI:467); current -> previous
\*    (NNUpgradeUtil.doPreUpgrade/doUpgrade, FSI:480-505); isUpgradeFinalized
\*    = false (FSI:512).
\* HA (documented procedure, HDFSHighAvailabilityWithQJM.md:705-733): the
\* other NameNodes are restarted with -bootstrapStandby (reboot = TRUE) and
\* copy the new image; reboot = FALSE is a peer restarted without it, which
\* starts normally: the shared-log cTime check runs only on -upgrade
\* (FSI:845-856, 857-861). Only the active NameNode is upgraded (a stale
\* peer's own -upgrade would fail that check).
NnUpgrade(n, st, reboot) ==
    /\ ~nnUp[n]
    /\ n \in ActiveNN
    /\ nnCur[n].lv \in {"legacy", "pinned"}                    \* an image to load
    /\ nnPrev[n] = NoVer                                       \* checkUpgrade (FSI:423-433)
    /\ LET new == MkVer("pinned", st, TRUE)
           boot == IF reboot THEN Peers(n) ELSE {}
       IN /\ nnPrev' = [nnPrev EXCEPT ![n] = nnCur[n]]
          /\ nnCur' = [m \in NN |-> IF m = n \/ m \in boot THEN new ELSE nnCur[m]]
          /\ nnUp' = [m \in NN |-> IF m = n \/ m \in boot THEN TRUE ELSE nnUp[m]]
          /\ served' = [served EXCEPT ![NsOf(n)] = @ \cup {st}]
    /\ clock' = NextClock(st)
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

\* hdfs namenode -rollback: standalone, the NameNode is not running
\* (NNM:1628-1649, 1879-1882) -> FSImage.doRollback (FSI:519-572).
\* NNUpgradeUtil.canRollBack accepts a previous/ only with the same layout
\* version as the running software (NNU:55-78); there is no cTime check.
\* Otherwise "Cannot rollback to storage version ..." (NNU:69-75), a
\* missing key (SI:252-257) or "None of the storage directories contain
\* previous fs state" (FSI:540-542): nothing changes.
CanRollBack(n) == nnPrev[n] # NoVer /\ nnPrev[n].lv = "pinned"

NnRollback(n, reboot) ==
    /\ ~nnUp[n]
    /\ IF CanRollBack(n)
       THEN LET old == nnPrev[n]
                boot == IF reboot THEN {m \in Peers(n) : nnCur[m] # NoVer} ELSE {}
            IN /\ nnCur' = [m \in NN |-> IF m = n \/ m \in boot THEN old ELSE nnCur[m]]
               /\ nnPrev' = [nnPrev EXCEPT ![n] = NoVer]       \* NNUpgradeUtil.doRollBack (FSI:557-562)
               /\ nnUp' = [m \in NN |-> IF m \in boot THEN TRUE ELSE nnUp[m]]
               /\ served' = IF boot = {} THEN served
                            ELSE [served EXCEPT ![NsOf(n)] = @ \cup {old.ct}]
       ELSE UNCHANGED <<nnCur, nnPrev, nnUp, served>>
    /\ UNCHANGED clock
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

\* dfsadmin -finalizeUpgrade: FSImage.finalizeUpgrade deletes previous/ and
\* sets isUpgradeFinalized (FSI:616-632).
NnFinalize(n) ==
    /\ nnUp[n]
    /\ nnPrev[n] # NoVer
    /\ nnPrev' = [nnPrev EXCEPT ![n] = NoVer]
    /\ UNCHANGED <<nnCur, nnUp, clock, served>>
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

\* -bootstrapStandby: an HA NameNode copies the image of a running peer.
\* Only current/ is replaced (Storage.clearDirectory, ST:435-450).
NnBootstrapStandby(n, m) ==
    /\ m \in Peers(n)
    /\ nnUp[m] /\ ~nnUp[n]
    /\ nnCur' = [nnCur EXCEPT ![n] = nnCur[m]]
    /\ nnUp' = [nnUp EXCEPT ![n] = TRUE]
    /\ served' = [served EXCEPT ![NsOf(n)] = @ \cup {nnCur[m].ct}]
    /\ UNCHANGED <<nnPrev, clock>>
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* DataNode process.                                                       *)
(***************************************************************************)

\* DataNode start with -regular or -rollback (DN:3434-3455). One
\* BPServiceActor per configured NameNode starts CONNECTING (BPSA:115).
DnStart(opt, conf) ==
    /\ ~dnUp
    /\ dnUp' = TRUE
    /\ startOpt' = opt
    /\ dnConf' = conf
    /\ aState' = [n \in NN |-> "conn"]
    /\ UNCHANGED <<dsLoaded, bpLoaded, dataInit>>
    /\ UNCHANGED <<bposSet, aRetry, nsInfoCt, regCt>>
    /\ UNCHANGED <<nnVars, diskVars, loadVars, targetFired>>

\* Every in-process structure is lost; the disk stays as it is.
ProcessDown ==
    /\ dnUp' = FALSE
    /\ dsLoaded' = {}
    /\ bpLoaded' = [s \in Ns |-> {}]
    /\ dataInit' = FALSE
    /\ bposSet' = [s \in Ns |-> FALSE]
    /\ aState' = [n \in NN |-> "down"]
    /\ aRetry' = [n \in NN |-> FALSE]
    /\ nsInfoCt' = [n \in NN |-> NoCT]
    /\ regCt' = [s \in Ns |-> NoCT]
    /\ ld' = LdIdle
    /\ cb' = [d \in Dir |-> "none"]
    /\ sh' = ShInit
    /\ UNCHANGED <<startOpt, dnConf>>

\* DataNode.shutdown (DN:2527-2700) between storage loads.
DnStop ==
    /\ dnUp
    /\ ~ld.busy
    /\ \A d \in Dir : cb[d] = "none"
    /\ ProcessDown
    /\ UNCHANGED <<nnVars, diskVars, targetFired>>

\* The process dies at an arbitrary step (kill, power loss) - in particular
\* between the renames of DS:823-864 and DS:957-961 (Scenario 3).
DnCrash ==
    /\ dnUp
    /\ ProcessDown
    /\ UNCHANGED <<nnVars, diskVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* BPServiceActor / BPOfferService: handshake, storage initialization and  *)
(* retry (Scenario 2).                                                     *)
(***************************************************************************)

\* BPServiceActor.isAlive (BPSA:171-177): RUNNING, or CONNECTING with a
\* live thread. runningState stays INIT_FAILED during a retry (it is set
\* only at BPSA:912, 919, 926), so a retrying actor is not alive.
Alive(m) == \/ aState[m] = "run"
            \/ aState[m] \in {"conn", "hs", "init", "stored"} /\ ~aRetry[m]

\* connectToNNAndHandshake (BPSA:302-320) -> retrieveNamespaceInfo
\* (BPSA:258-281): bpNamenode.versionRequest(), retried while the NameNode
\* does not answer. A fresh NamespaceInfo on every attempt.
Handshake(n) ==
    /\ dnUp
    /\ aState[n] = "conn"
    /\ nnUp[n] /\ CanServe(n)
    /\ nsInfoCt' = [nsInfoCt EXCEPT ![n] = nnCur[n].ct]
    /\ aState' = [aState EXCEPT ![n] = "hs"]
    /\ UNCHANGED <<bposSet, aRetry, regCt>>
    /\ UNCHANGED <<nnVars, diskVars, procVars, loadVars, targetFired>>

\* BPOfferService.verifyAndSetNamespaceInfo (BPOS:382-415) under the BPOS
\* write lock: setNamespaceInfo returns null (BPOS:393) for the first actor,
\* which runs DataNode.initBlockPool (DN:2185-2199) -> initStorage
\* (DN:2251-2264): synchronized (DataNode) recoverTransitionRead with
\* nsInfo = bpos.getNamespaceInfo() (DN:2186) and startOpt from the
\* configuration (DN:2256). One loader at a time (DN monitor, DS:382).
InitStart(n) ==
    /\ dnUp
    /\ aState[n] = "hs"
    /\ ~bposSet[NsOf(n)]                                       \* BPOS:393
    /\ ~ld.busy                                                \* DN:2262, DS:382
    /\ bposSet' = [bposSet EXCEPT ![NsOf(n)] = TRUE]           \* BPOS:258-260
    /\ aState' = [aState EXCEPT ![n] = "init"]
    /\ ld' = [LdIdle EXCEPT !.busy = TRUE, !.owner = n, !.ns = NsOf(n),
                            !.ct = nsInfoCt[n], !.q = dnConf]
    /\ UNCHANGED <<aRetry, nsInfoCt, regCt>>
    /\ UNCHANGED <<nnVars, diskVars, procVars, cb, sh, targetFired>>

\* A later actor of an initialized pool: setNamespaceInfo compares only the
\* block pool, namespace and cluster IDs, never cTime (BPOS:246-265), and
\* replaces bpNSInfo; then register (BPSA:318) and RUNNING (BPSA:926). It
\* waits for the BPOS write lock, which an initializing peer holds through
\* the whole initBlockPool (BPOS:383-414).
HsJoin(n) ==
    /\ dnUp
    /\ aState[n] = "hs"
    /\ bposSet[NsOf(n)]
    /\ \A m \in Peers(n) : aState[m] \notin {"init", "stored"}
    /\ aState' = [aState EXCEPT ![n] = "run"]
    /\ UNCHANGED <<bposSet, aRetry, nsInfoCt, regCt>>
    /\ UNCHANGED <<nnVars, diskVars, procVars, loadVars, targetFired>>

\* BPServiceActor.run after a failed connectToNNAndHandshake (BPSA:910-923):
\* retry after 5 s while shouldRetryInit (BPSA:949-951 -> BPOS:860-867:
\* hasBlockPoolId() or another actor alive, BPOS:188-195); otherwise FAILED
\* and the thread exits.
ActorRetryOrExit(n) ==
    /\ dnUp
    /\ aState[n] = "initFailed"
    /\ IF bposSet[NsOf(n)] \/ \E m \in Peers(n) : Alive(m)
       THEN aState' = [aState EXCEPT ![n] = "conn"]            \* BPSA:913-917
       ELSE aState' = [aState EXCEPT ![n] = "failed"]          \* BPSA:918-921
    /\ UNCHANGED <<bposSet, aRetry, nsInfoCt, regCt>>
    /\ UNCHANGED <<nnVars, diskVars, procVars, loadVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* DataNode-level storage load: DataStorage.addStorageLocations (DS:382)  *)
(* -> loadDataStorage (DS:403-448) -> loadStorageDirectory (DS:269-308)   *)
(* -> doTransition (DS:719-780), per configured location in order.        *)
(***************************************************************************)

LoaderAt(pc) == dnUp /\ ld.busy /\ ld.d # 0 /\ ld.pc = pc

\* End of one location's loadStorageDirectory with an IOException: the
\* directory is unlocked (DS:304-307) and skipped (DS:424-426).
LdFail == [ld EXCEPT !.d = 0, !.pc = "none"]

\* Current directory has content that checkEmptyCurrent rejects (ST:613-628).
CurNonEmpty(d) == \E s \in Ns : dCur[d].bp[s] # NoBp

\* Storage.analyzeStorage for a DataNode-level directory (ST:659-781) with
\* checkCurrentIsEmpty = true (DS:274). Temp directories other than
\* previous.tmp and removed.tmp do not occur in the model.
AnalyzeState(d) ==
    LET hasCur  == dCur[d].ver # NoVer                         \* ST:717-718
        hasPrev == dPrev[d].ver # NoVer                        \* ST:721
        k == dTmp[d].kind                                      \* ST:722-725
    IN CASE k = "none" ->                                      \* ST:727-739
              IF hasCur THEN "normal"                          \* ST:730-731
              ELSE IF hasPrev THEN "fail"                      \* ST:732-734
              ELSE IF CurNonEmpty(d) THEN "fail"               \* ST:735-737
              ELSE "format"                                    \* ST:738
         [] k = "prevTmp" ->                                   \* ST:761-769
              IF hasPrev THEN "fail"                           \* ST:762-765
              ELSE IF hasCur THEN "completeUpgrade" ELSE "recoverUpgrade"
         [] k = "removedTmp" ->                                \* ST:771-780
              IF hasCur = hasPrev THEN "fail"                  \* ST:772-777
              ELSE IF hasCur THEN "completeRollback" ELSE "recoverRollback"

\* The loader visits the next configured location (DS:408-431):
\*  - already loaded: "has already been used" -> success (DS:427-430);
\*  - else loadStorageDirectory: analyzeStorage (DS:274), then format
\*    (DS:283-287) or the recovery of an interrupted transition (DS:288-289,
\*    Storage.doRecover ST:789-840).
DnAnalyze ==
    /\ dnUp /\ ld.busy /\ ld.d = 0 /\ ld.q # <<>>
    /\ LET d == Head(ld.q)
           st == AnalyzeState(d)
           go == [ld EXCEPT !.q = Tail(ld.q), !.d = d, !.pc = "trans"]
       IN IF d \in dsLoaded
          THEN /\ ld' = [ld EXCEPT !.q = Tail(ld.q), !.ok = @ \cup {d}]
               /\ UNCHANGED <<diskVars, sh>>
          ELSE CASE st = "fail" ->                             \* InconsistentFSStateException
                      /\ ld' = [ld EXCEPT !.q = Tail(ld.q)]
                      /\ UNCHANGED <<diskVars, sh>>
                 [] st = "normal" ->
                      /\ ld' = go
                      /\ UNCHANGED <<diskVars, sh>>
                 [] st = "format" ->
                      \* DataStorage.format (DS:571-582): clearDirectory, LV = CUR,
                      \* cTime = 0 (DS:577), writeProperties.
                      /\ dCur' = [dCur EXCEPT ![d] = [ver |-> MkVer("pinned", 0, TRUE),
                                                      bp |-> NoBpMap]]
                      /\ sh' = [lv |-> "pinned", ct |-> 0]
                      /\ ld' = go
                      /\ UNCHANGED <<dPrev, dTmp>>
                 [] st = "completeUpgrade" ->                  \* ST:797-801: previous.tmp -> previous
                      /\ dPrev' = [dPrev EXCEPT ![d] = dTmp[d].tree]
                      /\ dTmp' = [dTmp EXCEPT ![d] = NoTmp]
                      /\ ld' = go
                      /\ UNCHANGED <<dCur, sh>>
                 [] st = "recoverUpgrade" ->                   \* ST:802-807: delete current, previous.tmp -> current
                      /\ dCur' = [dCur EXCEPT ![d] = dTmp[d].tree]
                      /\ dTmp' = [dTmp EXCEPT ![d] = NoTmp]
                      /\ ld' = go
                      /\ UNCHANGED <<dPrev, sh>>
                 [] st = "completeRollback" ->                 \* ST:808-812: delete removed.tmp
                      /\ dTmp' = [dTmp EXCEPT ![d] = NoTmp]
                      /\ ld' = go
                      /\ UNCHANGED <<dCur, dPrev, sh>>
                 [] st = "recoverRollback" ->                  \* ST:813-817: removed.tmp -> current
                      /\ dCur' = [dCur EXCEPT ![d] = dTmp[d].tree]
                      /\ dTmp' = [dTmp EXCEPT ![d] = NoTmp]
                      /\ ld' = go
                      /\ UNCHANGED <<dPrev, sh>>
    /\ UNCHANGED <<nnVars, procVars, actorVars, cb, targetFired>>

\* Transient I/O failure while opening the location (Scenario 2,
\* DirLoadFail): loadStorageDirectory throws before any change, the
\* directory is unlocked and skipped (DS:304-307, 424-426) and stays as it
\* is for the next initStorage.
DnLoadIoFail ==
    /\ dnUp /\ ld.busy /\ ld.d = 0 /\ ld.q # <<>>
    /\ Head(ld.q) \notin dsLoaded
    /\ ld' = [ld EXCEPT !.q = Tail(ld.q)]
    /\ UNCHANGED <<nnVars, diskVars, procVars, actorVars, cb, sh, targetFired>>

\* A read of a VERSION file fails (other line than the target): no file
\* (readPropertiesFile creates an empty one, SI:262-280, then SI:252-257),
\* a future layout version (setLayoutVersion, SI:216-221) or, for a
\* federation layout, no clusterID (setClusterId SI:201-213 -> SI:252-257).
ReadFails(v) == \/ v.lv \in {"none", "future"}
                \/ v.lv = "pinned" /\ ~v.cid

\* LV >= DataNodeLayoutVersion.getCurrentLayoutVersion() (LV values are
\* negative; a future version is smaller).
LvAtLeastCur(lv) == lv \in {"ancient", "legacy", "pinned"}

\* doTransition with ROLLBACK (DS:726-727) -> doRollback (DS:919-932) when
\* <SD>/previous does not exist: readProperties(sd, CUR) (DS:927, DS:700-704)
\* sets the shared LV = CUR (DS:628-629) and cTime (DS:633, SI:195-198)
\* first; setClusterId (DS:635) then requires clusterID (SI:201-213), so a
\* pre-federation VERSION fails at SI:256 with those fields already written.
\* An empty VERSION fails at the cTime read (SI:252-257). On success,
\* writeProperties (DS:928) from the shared fields.
DnRollbackNoPrevious ==
    /\ LoaderAt("trans")
    /\ startOpt = "ROLLBACK"
    /\ dPrev[ld.d].ver = NoVer                                 \* DS:924
    /\ LET d == ld.d
           v == dCur[d].ver
       IN CASE v.lv = "none" ->                                \* no cTime key
                 /\ sh' = [sh EXCEPT !.lv = "pinned"]
                 /\ ld' = LdFail
                 /\ UNCHANGED dCur
            [] ~v.cid ->                                       \* SI:256 (clusterID)
                 /\ sh' = [lv |-> "pinned", ct |-> v.ct]
                 /\ ld' = LdFail
                 /\ UNCHANGED dCur
            [] OTHER ->
                 /\ sh' = [lv |-> "pinned", ct |-> v.ct]       \* DS:628-633
                 /\ dCur' = [dCur EXCEPT ![d].ver = MkVer("pinned", v.ct, TRUE)]
                 /\ ld' = [ld EXCEPT !.pc = "read"]
    /\ UNCHANGED <<dPrev, dTmp>>
    /\ UNCHANGED <<nnVars, procVars, actorVars, cb, targetFired>>

(***************************************************************************)
(* THE TARGET. DataStorage.doRollback (DS:919-948) with <SD>/previous      *)
(* present: prevInfo = new DataStorage() (DS:934) reads previous/VERSION   *)
(* (DS:935 -> SI:155-159 -> DS:617-674), then                              *)
(*   if (!(prevInfo.LV >= CUR_LV && prevInfo.cTime <= nsInfo.cTime))       *)
(*     throw new InconsistentFSStateException(...)          (DS:939-947)   *)
(* prevInfo is local and nsInfo is the loader's NamespaceInfo, so the step *)
(* is atomic (brief Section 2, Scenario 1 granularity).                   *)
(***************************************************************************)
TargetGuardFails(p, nsCt) == ~(LvAtLeastCur(p.lv) /\ p.ct <= nsCt)

TargetCheck ==
    /\ LoaderAt("trans")
    /\ startOpt = "ROLLBACK"                                   \* DS:726
    /\ dPrev[ld.d].ver # NoVer                                 \* DS:922-924
    /\ LET p == dPrev[ld.d].ver
       IN IF ReadFails(p)
          THEN \* readPreviousVersionProperties throws first (SI:216-221,
               \* SI:252-257): another line, not the target.
               /\ ld' = LdFail
               /\ UNCHANGED targetFired
          ELSE IF TargetGuardFails(p, ld.ct)                   \* DS:939-941
               THEN /\ targetFired' = TRUE                     \* throw at DS:942
                    /\ ld' = LdFail                            \* DS:304-307, 424-426
               ELSE /\ ld' = [ld EXCEPT !.pc = "rb1"]          \* DS:949-951
                    /\ UNCHANGED targetFired
    /\ UNCHANGED <<nnVars, diskVars, procVars, actorVars, cb, sh>>

\* DS:952-957: rename current -> removed.tmp (asserts DS:953, 956).
DnRollbackRenameCurrent ==
    /\ LoaderAt("rb1")
    /\ LET d == ld.d IN
       /\ Assert(dTmp[d].kind = "none", "removed.tmp must not exist (DS:953)")
       /\ Assert(dCur[d].ver # NoVer, "current must exist (DS:956)")
       /\ dTmp' = [dTmp EXCEPT ![d] = [kind |-> "removedTmp", tree |-> dCur[d]]]
       /\ dCur' = [dCur EXCEPT ![d] = EmptyTree]
    /\ ld' = [ld EXCEPT !.pc = "rb2"]
    /\ UNCHANGED dPrev
    /\ UNCHANGED <<nnVars, procVars, actorVars, cb, sh, targetFired>>

\* DS:958-959: rename previous -> current.
DnRollbackRenamePrevious ==
    /\ LoaderAt("rb2")
    /\ LET d == ld.d IN
       /\ dCur' = [dCur EXCEPT ![d] = dPrev[d]]
       /\ dPrev' = [dPrev EXCEPT ![d] = EmptyTree]
    /\ ld' = [ld EXCEPT !.pc = "rb3"]
    /\ UNCHANGED dTmp
    /\ UNCHANGED <<nnVars, procVars, actorVars, cb, sh, targetFired>>

\* DS:960-961: delete removed.tmp; doTransition continues at DS:729.
DnRollbackDeleteTmp ==
    /\ LoaderAt("rb3")
    /\ dTmp' = [dTmp EXCEPT ![ld.d] = NoTmp]
    /\ ld' = [ld EXCEPT !.pc = "read"]
    /\ UNCHANGED <<dCur, dPrev>>
    /\ UNCHANGED <<nnVars, procVars, actorVars, cb, sh, targetFired>>

\* doTransition after the rollback step (DS:729-771): readProperties(sd)
\* into the shared DataStorage fields (DS:729 -> DS:623-674),
\* checkVersionUpgradable (DS:730, ST:1146-1163), the namespaceID check of a
\* pre-federation layout (DS:738-745: a legacy layout belongs to namespace
\* 1), the clusterID check of a federation layout (DS:747-753; one cluster
\* in the model), then
\*  - LV = CUR: regular start (DS:755-758), writeProperties after
\*    setServiceLayoutVersion (DS:296-301), addStorageDir (DS:416-418);
\*  - LV > CUR without FEDERATION: doUpgradePreFederation (DS:762-769).
DnReadProperties ==
    /\ dnUp /\ ld.busy /\ ld.d # 0
    /\ \/ ld.pc = "read"
       \/ ld.pc = "trans" /\ startOpt = "REGULAR"
    /\ LET d == ld.d
           v == dCur[d].ver
       IN CASE v.lv \in {"none", "future"} ->                 \* SI:252-257 / SI:216-221: no field written
                 /\ ld' = LdFail
                 /\ UNCHANGED <<dCur, sh, dsLoaded>>
            [] ReadFails(v) ->                                 \* no clusterID: SI:256 after SI:223, SI:197
                 /\ sh' = [lv |-> v.lv, ct |-> v.ct]
                 /\ ld' = LdFail
                 /\ UNCHANGED <<dCur, dsLoaded>>
            [] v.lv = "ancient" ->                             \* checkVersionUpgradable (DS:730)
                 /\ sh' = [lv |-> v.lv, ct |-> v.ct]
                 /\ ld' = LdFail
                 /\ UNCHANGED <<dCur, dsLoaded>>
            [] v.lv = "legacy" /\ ld.ns # 1 ->                 \* "Incompatible namespaceIDs" (DS:739-745)
                 /\ sh' = [lv |-> v.lv, ct |-> v.ct]
                 /\ ld' = LdFail
                 /\ UNCHANGED <<dCur, dsLoaded>>
            [] v.lv = "legacy" ->                              \* doUpgradePreFederation (DS:768)
                 /\ sh' = [lv |-> v.lv, ct |-> v.ct]
                 /\ ld' = [ld EXCEPT !.pc = IF dPrev[d].ver # NoVer THEN "pfDel" ELSE "pfRen"]
                 /\ UNCHANGED <<dCur, dsLoaded>>
            [] OTHER ->                                        \* LV = CUR: regular start
                 /\ sh' = [lv |-> "pinned", ct |-> v.ct]       \* DS:729, DS:299
                 /\ dCur' = [dCur EXCEPT ![d].ver = MkVer("pinned", v.ct, TRUE)]   \* DS:300
                 /\ dsLoaded' = dsLoaded \cup {d}              \* DS:416-418
                 /\ ld' = [ld EXCEPT !.d = 0, !.pc = "none", !.ok = @ \cup {d}]
    /\ UNCHANGED <<dPrev, dTmp>>
    /\ UNCHANGED <<nnVars, dnUp, startOpt, dnConf, bpLoaded, dataInit, actorVars, cb, targetFired>>

\* The same read with an upgrade callable's DS:874 (layoutVersion = CUR,
\* after its DS:860 clusterID write) landing inside it (Scenario 3 race).
\* readProperties and doTransition re-read the SHARED layoutVersion:
\* setClusterId at DS:635 (SI:204), the FEDERATION test at DS:735-737 and the
\* comparisons at DS:756/762. For a pre-federation (or ancient) VERSION:
\*  - "fail": DS:874 lands before DS:635 and setClusterId demands a clusterID
\*    (SI:256), or between DS:756 and DS:762 ("BUG: The stored LV", DS:777);
\*  - "relabel": it lands between DS:635 and DS:756, so the regular branch is
\*    taken: no pre-federation upgrade, no snapshot, an existing previous/ is
\*    NOT deleted, and the location is loaded with its VERSION rewritten as
\*    (CUR, its own cTime) (DS:299-300, 416-418).
\* The shared fields end as (CUR, the location's cTime) either way, and the
\* callable is past DS:874 (as after CbUpgradeFields). Never traced: the
\* harness's trace lock serializes DS:729 with DS:874.
DnReadPropertiesRaced(c, outcome) ==
    /\ dnUp /\ ld.busy /\ ld.d # 0
    /\ \/ ld.pc = "read"
       \/ ld.pc = "trans" /\ startOpt = "REGULAR"
    /\ cb[c] = "sub"
    /\ LET d == ld.d
           v == dCur[d].ver
       IN /\ v.lv \in {"legacy", "ancient"}
          /\ cb' = [cb EXCEPT ![c] = "set"]
          /\ sh' = [lv |-> "pinned", ct |-> v.ct]
          /\ CASE outcome = "fail" ->
                    /\ ld' = LdFail
                    /\ UNCHANGED <<dCur, dsLoaded>>
               [] outcome = "relabel" ->
                    /\ dCur' = [dCur EXCEPT ![d].ver = MkVer("pinned", v.ct, TRUE)]
                    /\ dsLoaded' = dsLoaded \cup {d}
                    /\ ld' = [ld EXCEPT !.d = 0, !.pc = "none", !.ok = @ \cup {d}]
    /\ UNCHANGED <<dPrev, dTmp>>
    /\ UNCHANGED <<nnVars, dnUp, startOpt, dnConf, bpLoaded, dataInit, actorVars, targetFired>>

\* doUpgradePreFederation (DS:804-850), step 1: delete <SD>/previous
\* (DS:822-824) - including a legacy-era snapshot.
DnPreFedDeletePrevious ==
    /\ LoaderAt("pfDel")
    /\ dPrev' = [dPrev EXCEPT ![ld.d] = EmptyTree]
    /\ ld' = [ld EXCEPT !.pc = "pfRen"]
    /\ UNCHANGED <<dCur, dTmp>>
    /\ UNCHANGED <<nnVars, procVars, actorVars, cb, sh, targetFired>>

\* doUpgradePreFederation, steps 2-3: rename current -> previous.tmp
\* (DS:830-831), format the block pool in a new current (DS:833-836;
\* BlockPoolSliceStorage.format writes nsInfo.getCTime(), BPSS:268-291), and
\* add the upgrade callable (DS:841-849), which loadDataStorage submits to
\* the executor (DS:419-422); the loop then moves to the next location.
DnPreFedRename ==
    /\ LoaderAt("pfRen")
    /\ LET d == ld.d IN
       /\ Assert(dTmp[d].kind = "none", "previous.tmp must not exist (DS:827)")
       /\ dTmp' = [dTmp EXCEPT ![d] = [kind |-> "prevTmp", tree |-> dCur[d]]]
       /\ dCur' = [dCur EXCEPT ![d] =
                     [ver |-> NoVer,
                      bp |-> [s \in Ns |-> IF s = ld.ns THEN [cur |-> ld.ct, prev |-> NoCT]
                                           ELSE NoBp]]]
       /\ cb' = [cb EXCEPT ![d] = "sub"]
       /\ ld' = [ld EXCEPT !.d = 0, !.pc = "none", !.tasks = @ \cup {d}]
    /\ UNCHANGED dPrev
    /\ UNCHANGED <<nnVars, procVars, actorVars, sh, targetFired>>

(***************************************************************************)
(* The upgrade callable (DS:842-848 -> doUpgrade DS:852-866) on an        *)
(* executor thread, concurrent with the caller's loop over the remaining   *)
(* locations. It writes the shared DataStorage fields without a lock, so   *)
(* the VERSION it writes carries whatever cTime/LV the caller last read    *)
(* (Scenario 3, shared-field race; brief Section 4).                       *)
(***************************************************************************)

\* DS:857-874: linkAllBlocks (DS:857), clusterID = nsInfo's (DS:860),
\* upgradeProperties: createStorageID (DS:870), layoutVersion = CUR (DS:874).
CbUpgradeFields(d) ==
    /\ dnUp
    /\ cb[d] = "sub"
    /\ sh' = [sh EXCEPT !.lv = "pinned"]
    /\ cb' = [cb EXCEPT ![d] = "set"]
    /\ UNCHANGED <<nnVars, diskVars, procVars, actorVars, ld, targetFired>>

\* DS:875: writeProperties(sd) from the shared fields as they are now
\* (setPropertiesFromFields, DS:591-610: always writes clusterID).
CbWriteVersion(d) ==
    /\ dnUp
    /\ cb[d] = "set"
    /\ dCur' = [dCur EXCEPT ![d].ver = MkVer(sh.lv, sh.ct, TRUE)]
    /\ cb' = [cb EXCEPT ![d] = "written"]
    /\ UNCHANGED <<dPrev, dTmp>>
    /\ UNCHANGED <<nnVars, procVars, actorVars, ld, sh, targetFired>>

\* DS:863-864: rename previous.tmp -> previous: the DataNode-level snapshot.
CbRenamePrevTmp(d) ==
    /\ dnUp
    /\ cb[d] = "written"
    /\ dPrev' = [dPrev EXCEPT ![d] = dTmp[d].tree]
    /\ dTmp' = [dTmp EXCEPT ![d] = NoTmp]
    /\ cb' = [cb EXCEPT ![d] = "done"]
    /\ UNCHANGED dCur
    /\ UNCHANGED <<nnVars, procVars, actorVars, ld, sh, targetFired>>

\* After the loop, loadDataStorage waits for each task (DS:433-445):
\* addStorageDir(future.get()) and success.
DnAddUpgraded(d) ==
    /\ dnUp /\ ld.busy /\ ld.d = 0 /\ ld.q = <<>>
    /\ d \in ld.tasks
    /\ cb[d] = "done"
    /\ dsLoaded' = dsLoaded \cup {d}
    /\ ld' = [ld EXCEPT !.tasks = @ \ {d}, !.ok = @ \cup {d}]
    /\ cb' = [cb EXCEPT ![d] = "none"]
    /\ UNCHANGED <<nnVars, diskVars, dnUp, startOpt, dnConf, bpLoaded, dataInit, actorVars, sh, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Block-pool level, one atomic step per DataNode-level success           *)
(* (loadBlockPoolSliceStorage, DS:450-501; brief Section 3.1 "abstracted").*)
(* The order of the locations does not matter: the steps touch disjoint    *)
(* state.                                                                  *)
(***************************************************************************)

DnLevelDone == ld.busy /\ ld.d = 0 /\ ld.q = <<>> /\ ld.tasks = {}

\* BlockPoolSliceStorage.loadStorageDirectory (BPSS:149-197) after
\* makeBlockPoolDir (DS:460): analyzeStorage, format if no VERSION
\* (BPSS:168-172, 283-291), doTransition (BPSS:369-425):
\*  - ROLLBACK with a block-pool previous: BPSS.doRollback guard
\*    (BPSS:618-621), then previous -> current (BPSS:623-641);
\*  - regular if cTime = nsInfo.cTime (BPSS:401-404; BPSS:184-189 passes);
\*  - upgrade if cTime < nsInfo.cTime (BPSS:410-414 -> doUpgrade
\*    BPSS:445-519: the old block-pool previous is deleted (BPSS:478-480;
\*    the DataNode-level delete at BPSS:463-471 resolves to the same
\*    block-pool previous and never touches <SD>/previous), current ->
\*    previous, cTime = nsInfo's);
\*  - otherwise "newer than the namespace state" (BPSS:417-425).
BpOutcome(b, ct) ==
    LET fmtFail == b.cur = NoCT /\ b.prev # NoCT               \* ST:732-734
        b1 == IF b.cur = NoCT THEN [cur |-> ct, prev |-> b.prev] ELSE b
        rb == startOpt = "ROLLBACK" /\ b1.prev # NoCT          \* BPSS:375-379
        b2 == IF rb THEN [cur |-> b1.prev, prev |-> NoCT] ELSE b1
    IN CASE fmtFail                  -> [ok |-> FALSE, bp |-> b]
         [] rb /\ b1.prev > ct       -> [ok |-> FALSE, bp |-> b1]   \* BPSS:621
         [] b2.cur = ct              -> [ok |-> TRUE,  bp |-> b2]
         [] b2.cur < ct              -> [ok |-> TRUE,  bp |-> [cur |-> ct, prev |-> b2.cur]]
         [] OTHER                    -> [ok |-> FALSE, bp |-> b2]   \* BPSS:421

BpLoad(d) ==
    /\ dnUp /\ DnLevelDone
    /\ d \in ld.ok \ ld.bpDone
    /\ LET s == ld.ns
           used == d \in bpLoaded[s]                           \* BPSS:221-225
           res == BpOutcome(dCur[d].bp[s], ld.ct)
           ok == ~used /\ res.ok
       IN /\ dCur' = IF used THEN dCur ELSE [dCur EXCEPT ![d].bp[s] = res.bp]
          /\ bpLoaded' = IF ok THEN [bpLoaded EXCEPT ![s] = @ \cup {d}] ELSE bpLoaded
          /\ ld' = [ld EXCEPT !.bpDone = @ \cup {d}, !.bpOk = @ \/ ok]
    /\ UNCHANGED <<dPrev, dTmp>>
    /\ UNCHANGED <<nnVars, dnUp, startOpt, dnConf, dsLoaded, dataInit, actorVars, cb, sh, targetFired>>

\* recoverTransitionRead returns and initStorage leaves synchronized
\* (DataNode) (DN:2262-2264): another pool's load may start now.
\* "All specified directories have failed to load." if no block-pool
\* success (DS:392-397, 564-568): initBlockPool fails, setNamespaceInfo(null)
\* (BPOS:402-408), runningState = INIT_FAILED (BPSA:912).
DnLoadDone ==
    /\ dnUp /\ DnLevelDone
    /\ ld.ok \subseteq ld.bpDone
    /\ LET n == ld.owner
           s == ld.ns
       IN IF ld.bpOk
          THEN /\ aState' = [aState EXCEPT ![n] = "stored"]
               /\ UNCHANGED <<bposSet, aRetry>>
          ELSE /\ bposSet' = [bposSet EXCEPT ![s] = FALSE]
               /\ aState' = [aState EXCEPT ![n] = "initFailed"]
               /\ aRetry' = [aRetry EXCEPT ![n] = TRUE]
    /\ ld' = LdIdle
    /\ UNCHANGED <<nsInfoCt, regCt>>
    /\ UNCHANGED <<nnVars, diskVars, procVars, cb, sh, targetFired>>

\* Rest of initBlockPool for an actor whose storage loaded:
\*  - the FsDataset is built once, under synchronized (DataNode)
\*    (DN:2275-2279); with the default dfs.datanode.failed.volumes.tolerated
\*    = 0 every configured location must be loaded at DataNode level at that
\*    moment (FDI:311-343, 411-428), possibly by another pool's load;
\*  - success: register and RUNNING (BPSA:318, 926); the registration
\*    carries the block-pool storage cTime = this actor's nsInfo cTime;
\*  - failure (DiskErrorException): BPOS:402-408, BPSA:912.
InitFinish(n) ==
    /\ dnUp
    /\ aState[n] = "stored"
    /\ ~ld.busy                                                \* DN:2275
    /\ LET s == NsOf(n) IN
       IF dataInit \/ Range(dnConf) \subseteq dsLoaded
       THEN /\ dataInit' = TRUE
            /\ aState' = [aState EXCEPT ![n] = "run"]
            /\ regCt' = [regCt EXCEPT ![s] = nsInfoCt[n]]
            /\ UNCHANGED <<bposSet, aRetry>>
       ELSE /\ bposSet' = [bposSet EXCEPT ![s] = FALSE]
            /\ aState' = [aState EXCEPT ![n] = "initFailed"]
            /\ aRetry' = [aRetry EXCEPT ![n] = TRUE]
            /\ UNCHANGED <<dataInit, regCt>>
    /\ UNCHANGED nsInfoCt
    /\ UNCHANGED <<nnVars, diskVars, dnUp, startOpt, dnConf, dsLoaded, bpLoaded, loadVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* FinalizeCommand (Scenario 3). NameNodeRpcServer.blockReport returns it  *)
(* when the NameNode is finalized, not in a rolling upgrade, active, with  *)
(* no stale storages (NNRPC:1682-1687); a block report needs a registration*)
(* whose cTime matches the NameNode's. Only the active actor processes it  *)
(* (BPOS:690-703, 774-781; a standby ignores it, BPOS:840).                *)
(* DataNode.finalizeUpgradeForPool (DN:3660-3662) -> DataStorage.          *)
(* finalizeUpgrade (DS:1016-1031) visits every loaded location: a          *)
(* DataNode-level previous is finalized for ANY pool (DS:1021-1024 ->      *)
(* doFinalize DS:974-1008: rename to finalized.tmp, deleted by a daemon;   *)
(* folded into one step, the temp directory holds no snapshot and          *)
(* COMPLETE_FINALIZE removes it, ST:753-759, 818-822); otherwise the       *)
(* pool's block-pool previous (DS:1025-1028 -> BPSS.doFinalize). The loop  *)
(* is one step per location (a crash may stop it between locations).     *)
(***************************************************************************)
DnFinalizeDir(n, d) ==
    /\ dnUp
    /\ aState[n] = "run"
    /\ n \in ActiveNN
    /\ nnUp[n]
    /\ nnCur[n].ct = regCt[NsOf(n)]
    /\ nnPrev[n] = NoVer                                       \* isUpgradeFinalized (FSI:512, 568, 631, 689)
    /\ d \in dsLoaded
    /\ IF dPrev[d].ver # NoVer
       THEN /\ dPrev' = [dPrev EXCEPT ![d] = EmptyTree]
            /\ UNCHANGED dCur
       ELSE /\ dCur' = [dCur EXCEPT ![d].bp[NsOf(n)].prev = NoCT]
            /\ UNCHANGED dPrev
    /\ UNCHANGED dTmp
    /\ UNCHANGED <<nnVars, procVars, actorVars, loadVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Test fixtures (UpgradeUtilities). They write guard operands directly    *)
(* and are NOT part of Next: Trace.tla replays them, MC.tla wraps them     *)
(* with MaxFixture (0 in every MC and hunt config; brief Section 3.1).     *)
(***************************************************************************)

\* createNameNodeStorageDirs (UU:344-357: a copy of the master NameNode
\* current/), createNameNodeVersionFile (UU:440-453), corruptFile
\* (UU:514-530): the VERSION of <name dir>/<which>.
FixtureNnDir(n, which, v) ==
    /\ ~nnUp[n]
    /\ IF which = "current"
       THEN /\ nnCur' = [nnCur EXCEPT ![n] = v] /\ UNCHANGED nnPrev
       ELSE /\ nnPrev' = [nnPrev EXCEPT ![n] = v] /\ UNCHANGED nnCur
    /\ UNCHANGED <<nnUp, clock, served>>
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

\* createEmptyDirs(nameNodeDirs) (UU:219-227).
FixtureNnClear(n) ==
    /\ ~nnUp[n]
    /\ nnCur' = [nnCur EXCEPT ![n] = NoVer]
    /\ nnPrev' = [nnPrev EXCEPT ![n] = NoVer]
    /\ UNCHANGED <<nnUp, clock, served>>
    /\ UNCHANGED <<diskVars, procVars, actorVars, loadVars, targetFired>>

\* createDataNodeStorageDirs(dirs, which) (UU:372-395): <SD>/<which> := a
\* copy of the master DataNode current/ tree (VERSION and block pool).
FixtureDnTree(d, which, t) ==
    /\ ~dnUp
    /\ IF which = "current"
       THEN /\ dCur' = [dCur EXCEPT ![d] = t] /\ UNCHANGED dPrev
       ELSE /\ dPrev' = [dPrev EXCEPT ![d] = t] /\ UNCHANGED dCur
    /\ UNCHANGED dTmp
    /\ UNCHANGED <<nnVars, procVars, actorVars, loadVars, targetFired>>

\* createDataNodeVersionFile(<SD>/<which>, version, bpid) (UU:482-498):
\* <SD>/<which>/VERSION := v; when the layout supports FEDERATION also the
\* block-pool VERSION <SD>/<which>/<bpid>/current/VERSION := v.ct
\* (createBlockPoolVersionFile, UU:500-512); bpct = NoCT otherwise.
FixtureDnVersion(d, which, v, bpct) ==
    /\ ~dnUp
    /\ LET upd(t) == [ver |-> v,
                      bp |-> IF bpct = NoCT THEN t.bp
                             ELSE [t.bp EXCEPT ![1] = [@ EXCEPT !.cur = bpct]]]
       IN IF which = "current"
          THEN /\ dCur' = [dCur EXCEPT ![d] = upd(dCur[d])] /\ UNCHANGED dPrev
          ELSE /\ dPrev' = [dPrev EXCEPT ![d] = upd(dPrev[d])] /\ UNCHANGED dCur
    /\ UNCHANGED dTmp
    /\ UNCHANGED <<nnVars, procVars, actorVars, loadVars, targetFired>>

\* createBlockPoolStorageDirs(dirs, which, bpid) (UU:411-426):
\* <SD>/current/<bpid>/<which> := a copy of the master block-pool current/.
FixtureBpDir(d, which, ct) ==
    /\ ~dnUp
    /\ dCur' = [dCur EXCEPT ![d].bp[1] = IF which = "current" THEN [@ EXCEPT !.cur = ct]
                                         ELSE [@ EXCEPT !.prev = ct]]
    /\ UNCHANGED <<dPrev, dTmp>>
    /\ UNCHANGED <<nnVars, procVars, actorVars, loadVars, targetFired>>

\* createEmptyDirs(dataNodeDirs) (UU:219-227).
FixtureDnClear(d) ==
    /\ ~dnUp
    /\ dCur' = [dCur EXCEPT ![d] = EmptyTree]
    /\ dPrev' = [dPrev EXCEPT ![d] = EmptyTree]
    /\ dTmp' = [dTmp EXCEPT ![d] = NoTmp]
    /\ UNCHANGED <<nnVars, procVars, actorVars, loadVars, targetFired>>

----------------------------------------------------------------------------

Next ==
    \/ \E n \in NN, st \in CTv : NnFormat(n, st)
    \/ \E n \in NN : NnStart(n)
    \/ \E n \in NN : NnStop(n)
    \/ \E n \in NN, st \in CTv, r \in BOOLEAN : NnUpgrade(n, st, r)
    \/ \E n \in NN, r \in BOOLEAN : NnRollback(n, r)
    \/ \E n \in NN : NnFinalize(n)
    \/ \E n, m \in NN : NnBootstrapStandby(n, m)
    \/ \E o \in OptT : DnStart(o, DirSeq)
    \/ DnStop
    \/ DnCrash
    \/ \E n \in NN : Handshake(n)
    \/ \E n \in NN : InitStart(n)
    \/ \E n \in NN : HsJoin(n)
    \/ \E n \in NN : ActorRetryOrExit(n)
    \/ DnAnalyze
    \/ DnLoadIoFail
    \/ DnRollbackNoPrevious
    \/ TargetCheck
    \/ DnRollbackRenameCurrent
    \/ DnRollbackRenamePrevious
    \/ DnRollbackDeleteTmp
    \/ DnReadProperties
    \/ \E c \in Dir, o \in {"fail", "relabel"} : DnReadPropertiesRaced(c, o)
    \/ DnPreFedDeletePrevious
    \/ DnPreFedRename
    \/ \E d \in Dir : CbUpgradeFields(d)
    \/ \E d \in Dir : CbWriteVersion(d)
    \/ \E d \in Dir : CbRenamePrevTmp(d)
    \/ \E d \in Dir : DnAddUpgraded(d)
    \/ \E d \in Dir : BpLoad(d)
    \/ DnLoadDone
    \/ \E n \in NN : InitFinish(n)
    \/ \E n \in NN, d \in Dir : DnFinalizeDir(n, d)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
(* Invariants (brief Section 5) *)

\* The target: DataStorage.java L942 never throws.
TargetSafe == ~targetFired

VerT(L) == [lv : L, ct : CTv, cid : BOOLEAN] \cup {NoVer}
BpT == [cur : CTo, prev : CTo]
TreeT == [ver : VerT(DnLv), bp : [Ns -> BpT]]
LdT == [busy : BOOLEAN, owner : NN \cup {NoNN}, ns : Ns \cup {0}, ct : CTo,
        q : Seq(Dir), d : Dir \cup {0}, pc : PcT, tasks : SUBSET Dir,
        ok : SUBSET Dir, bpDone : SUBSET Dir, bpOk : BOOLEAN]

TypeOK ==
    /\ nnCur \in [NN -> VerT(NnLv)]
    /\ nnPrev \in [NN -> VerT(NnLv)]
    /\ nnUp \in [NN -> BOOLEAN]
    /\ clock \in Nat
    /\ served \in [Ns -> SUBSET CTv]
    /\ dCur \in [Dir -> TreeT]
    /\ dPrev \in [Dir -> TreeT]
    /\ dTmp \in [Dir -> [kind : {"none", "prevTmp", "removedTmp"}, tree : TreeT]]
    /\ dnUp \in BOOLEAN
    /\ startOpt \in OptT
    /\ dnConf \in Seq(Dir)
    /\ dsLoaded \subseteq Dir
    /\ bpLoaded \in [Ns -> SUBSET Dir]
    /\ dataInit \in BOOLEAN
    /\ bposSet \in [Ns -> BOOLEAN]
    /\ aState \in [NN -> AT]
    /\ aRetry \in [NN -> BOOLEAN]
    /\ nsInfoCt \in [NN -> CTo]
    /\ regCt \in [Ns -> CTo]
    /\ ld \in LdT
    /\ cb \in [Dir -> CbT]
    /\ sh \in [lv : DnLv, ct : CTv]
    /\ targetFired \in BOOLEAN

\* "A message carries only values its sender held": every handshake
\* snapshot, and the loader's nsInfo, is a cTime its NameNodes served.
NsInfoSound ==
    /\ \A n \in NN : nsInfoCt[n] # NoCT => nsInfoCt[n] \in served[NsOf(n)]
    /\ ld.busy => ld.ct \in served[ld.ns]

=============================================================================
