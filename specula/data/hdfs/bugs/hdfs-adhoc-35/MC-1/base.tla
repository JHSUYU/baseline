------------------------------- MODULE base -------------------------------
(***************************************************************************)
(* hdfs-adhoc-35: the DataNode cluster-ID check                            *)
(*                                                                         *)
(*   DataStorage.doTransition, DataStorage.java:748-753                    *)
(*     if (federationSupported                                             *)
(*         && !getClusterID().equals(nsInfo.getClusterID()))               *)
(*       throw new IOException("Incompatible clusterIDs in " ...);  (750)  *)
(*   (the stack frame of the throw reports line 752, see the brief §1)     *)
(*                                                                         *)
(* Pinned tree: /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-35/hadoop        *)
(*   at 734dd8a67cd.  Paths below hadoop-hdfs-project/hadoop-hdfs/src/main/ *)
(*   java/org/apache/hadoop/hdfs/server/:                                   *)
(*     DS   datanode/DataStorage.java                                       *)
(*     SI   common/StorageInfo.java                                         *)
(*     ST   common/Storage.java                                             *)
(*     DN   datanode/DataNode.java                                          *)
(*     FSD  datanode/fsdataset/impl/FsDatasetImpl.java                      *)
(*     BPOS datanode/BPOfferService.java, BPSA datanode/BPServiceActor.java *)
(*                                                                         *)
(* Category A (one DataNode talking to its NameNode), with Category-B      *)
(* granularity inside the DataNode: the guard re-reads two plain fields of *)
(* the DataNode's single DataStorage object (SI:47-50, DN:1931) that every *)
(* directory load rewrites, so every read and every write of those fields  *)
(* is its own step (brief §1 "Granularity note").                          *)
(*                                                                         *)
(* Loader threads (brief §1 "Concurrency model"):                          *)
(*   main  - the block-pool init thread: BPSA handshake -> DN.initStorage  *)
(*           (DN monitor, DN:2262) -> DS.addStorageLocations (DS monitor,  *)
(*           DS:382) -> loadDataStorage loop (DS:408-431), one directory   *)
(*           at a time.                                                    *)
(*   task  - the startup doUpgrade callable of a pre-federation directory  *)
(*           (DS:842-848), run on the DS:387 executor with no monitor,     *)
(*           overlapping the main loop's later directories (Scenario 2).   *)
(*   hs    - one hot-swap worker per new location (DN:1312-1329) ->        *)
(*           FSD.addVolume -> DS.prepareVolume (not synchronized, DS:324)  *)
(*           (Scenario 1).                                                 *)
(* main and hs exclude each other through the DN monitor (DN:2262 vs       *)
(* DN:1290); here: hs workers exist only while dn = "up", main only while  *)
(* dn = "init".                                                            *)
(*                                                                         *)
(* Abstractions (each argued in the comments at the relevant action):      *)
(*   - layout versions are the classes of DataNodeLayoutVersion.supports(  *)
(*     FEDERATION, lv) (brief §1): PRE = -16..-34,-41,-44 (FED false),     *)
(*     OLD = the other FED layouts above -57, CUR = -57, FUT = below -57   *)
(*     (rejected at SI:219-221), L0 = the constructor's 0 (SI:57).         *)
(*   - cluster IDs: "" (SI:57), "C" (this cluster), "X" (foreign; diag and *)
(*     trace fixture only).  "NONE" = no clusterID key in the VERSION file *)
(*     (a genuine 0.20/1.x directory).                                     *)
(*   - namespace IDs: "0" (SI:57), "N" (the NameNode's), "X" (other);      *)
(*     "NONE" = no namespaceID key.                                        *)
(*   - datanodeUuid: 0 = no key / null (DS:104), 1 = the identity every    *)
(*     initial file with a key carries, >= 2 = generated at DN:2062.  Only *)
(*     equality matters (DS:662-672), so a generated value is the smallest *)
(*     one no file holds (FreshUuid).                                      *)
(*   - cTime, storage IDs, storage type: not modeled (brief §3.2).         *)
(*   - BlockPoolSliceStorage: own StorageInfo (BPSS:119), never touches    *)
(*     the DataStorage fields; modeled as an opaque per-location ok/fail.  *)
(*   - crash windows inside directory transitions: the on-disk state of a  *)
(*     location changes only at the step that writes its VERSION file.     *)
(*   - sequentially consistent memory (brief §3.2).                        *)
(***************************************************************************)
EXTENDS Integers, FiniteSets, TLC

CONSTANTS
    Loc,          \* storage locations (strings); one StorageDirectory per location
    ProvLocs,     \* the PROVIDED location (at most one in-model: DS:150-156, FSD:446-453)
    \* initial DN-level VERSION of each DISK location (a location may be in several
    \* classes; Init then chooses one).  PROVIDED locations have no VERSION file
    \* (ST:376-387, ST:491-496).
    InitNone,     \* empty directory: NOT_FORMATTED (ST:704-709, ST:727-738)
    InitPre,      \* genuine 0.20/1.x directory: PRE layout, no clusterID key, nsid N, no uuid
    InitPreCid,   \* PRE layout written by a post-federation writer (workload fixture form, T-UU:482-498)
    InitOld,      \* federation-era older layout (OLD), cid C, no nsid key
    InitCur,      \* current layout (-57), cid C, no nsid key, has datanodeUuid
    InitForeign,  \* diag only (out of model): current layout carrying a foreign cid "X"
    StartDirs,    \* dfs.datanode.data.dir at the first DataNode start
    SwapCands,    \* locations an operator may hot-add (dfs.datanode.data.dir reconfiguration)
    StartOpts,    \* DataNode startup options used: subset of {"REGULAR", "ROLLBACK"}
    NnCid,        \* cluster ID the NameNode reports ("C"; "X" only in a diag cfg)
    HsNsChoices,  \* {NnCid}, or {NnCid, "NULL"} for a federated DN whose nsInfos.get(0) is null (DN:1286-1289)
    VolTolerated, \* dfs.datanode.failed.volumes.tolerated (-1 or >= 0)
    RetryInit,    \* TRUE: another actor re-runs initBlockPool after a failed or interrupted init (BPSA:910-917)
    HotSwapWidth  \* most new locations in one reconfiguration (model bound)

NoLoc  == "-"
\* no VERSION file (an empty directory) / no previous directory.  A record, so that
\* TLC can compare it with VERSION records; its layout class "NOF" is never read.
NoRec  == [lv |-> "NOF", cid |-> "NONE", nsid |-> "NONE", uuid |-> 0]
NnNsid == "N"                \* the NameNode's namespaceID (one cluster)
MainId == <<"main", NoLoc>>
HsId(l)   == <<"hs", l>>
TaskId(l) == <<"task", l>>
LdIds  == {MainId} \cup {HsId(l) : l \in Loc} \cup {TaskId(l) : l \in Loc}

\* DataNodeLayoutVersion.supports(FEDERATION, lv) (LayoutVersion.java:308-312; brief §1 table)
FED(lv) == lv \in {"OLD", "CUR"}

LvVals   == {"PRE", "OLD", "CUR", "FUT"}       \* on-disk layout classes
SLvVals  == {"L0", "PRE", "OLD", "CUR"}        \* values the shared field can hold
CidVals  == {"", "C", "X"}
NsidVals == {"0", "N", "X"}
\* datanodeUuid identities: at most 2 per location are on disk (current + previous), so
\* this range always holds one that no file carries (FreshUuid).
UuidVals == 0..(2 * Cardinality(Loc) + 2)
RecSet   == [lv : LvVals, cid : CidVals \cup {"NONE"}, nsid : NsidVals \cup {"NONE"}, uuid : UuidVals]
DiskVals == {NoRec} \cup RecSet

PreRec     == [lv |-> "PRE", cid |-> "NONE", nsid |-> "N",    uuid |-> 0]
PreCidRec  == [lv |-> "PRE", cid |-> "C",    nsid |-> "N",    uuid |-> 1]
OldRec     == [lv |-> "OLD", cid |-> "C",    nsid |-> "NONE", uuid |-> 0]
CurRec     == [lv |-> "CUR", cid |-> "C",    nsid |-> "NONE", uuid |-> 1]
ForeignRec == [lv |-> "CUR", cid |-> "X",    nsid |-> "NONE", uuid |-> 1]

InitRecs(l) ==
       (IF l \in InitNone    THEN {NoRec}      ELSE {})
    \cup (IF l \in InitPre     THEN {PreRec}     ELSE {})
    \cup (IF l \in InitPreCid  THEN {PreCidRec}  ELSE {})
    \cup (IF l \in InitOld     THEN {OldRec}     ELSE {})
    \cup (IF l \in InitCur     THEN {CurRec}     ELSE {})
    \cup (IF l \in InitForeign THEN {ForeignRec} ELSE {})
    \cup (IF l \in ProvLocs    THEN {NoRec}      ELSE {})

InitClasses == InitNone \cup InitPre \cup InitPreCid \cup InitOld \cup InitCur \cup InitForeign

ASSUME ProvLocs \subseteq Loc /\ Cardinality(ProvLocs) <= 1
ASSUME InitClasses \subseteq Loc \ ProvLocs
ASSUME \A l \in Loc \ ProvLocs : InitRecs(l) # {}
ASSUME StartDirs \subseteq Loc /\ StartDirs # {} /\ SwapCands \subseteq Loc
ASSUME StartOpts \subseteq {"REGULAR", "ROLLBACK"} /\ StartOpts # {}
ASSUME NnCid \in {"C", "X"} /\ NnCid \in HsNsChoices /\ HsNsChoices \subseteq {NnCid, "NULL"}
\* DN:1921-1929: tolerated must be -1 or below the number of configured volumes
ASSUME VolTolerated \in Int /\ VolTolerated >= -1 /\ VolTolerated < Cardinality(StartDirs)
ASSUME RetryInit \in BOOLEAN /\ HotSwapWidth \in Nat \ {0}

(***************************************************************************)
(* Variables                                                               *)
(***************************************************************************)
VARIABLES
    dn,           \* DataNode process: "down" | "init" (block-pool init running) | "up" | "noBP"
    startOpt,     \* startup option of the running DataNode (DN:2256)
    confDirs,     \* dfs.datanode.data.dir as the site file lists it
    loaded,       \* DataStorage.storageDirs (ST:1063 addStorageDir; DS:409/DS:327 containsStorageDir)
    sLV,          \* DataStorage.layoutVersion (SI:47)   -- guard operand source, DS:735
    sCID,         \* DataStorage.clusterID     (SI:49)   -- guard operand, DS:749
    sNSID,        \* DataStorage.namespaceID   (SI:48)   -- DS:739 sibling check
    dnUuid,       \* DataStorage.datanodeUuid (DS:104), 0 = null; DS:662-672 compares it, DN:2061-2063 generates it
    disk,         \* DN-level <loc>/current/VERSION, per location
    prev,         \* <loc>/previous/VERSION (left by a pre-federation upgrade, DS:864)
    ld,           \* loader threads, keyed by LdIds
    mainPending,  \* main loop: locations not yet visited (DS:408)
    mainJoin,     \* main loop: locations whose upgrade task is submitted, not yet joined (DS:433-445)
    mainOk,       \* main loop: successLocations (DS:406, DS:418, DS:429, DS:438)
    targetFired,  \* DS:750 executed
    fireInfo      \* diagnostic: who fired and against which values (route isolation)

lifeVars  == <<dn, startOpt, confDirs>>
fieldVars == <<sLV, sCID, sNSID, dnUuid>>
diskVars  == <<disk, prev>>
exitVars  == <<ld, loaded, mainOk, mainJoin>>
tgtVars   == <<targetFired, fireInfo>>
vars == <<dn, startOpt, confDirs, loaded, sLV, sCID, sNSID, dnUuid, disk, prev,
          ld, mainPending, mainJoin, mainOk, targetFired, fireInfo>>

PCs == {"idle",
        "loop", "join", "uuid", "fsd",                               \* main loop control
        "analyze", "fmtLV", "fmtCID", "fmtWrite",                    \* loadStorageDirectory / format
        "rbRestore", "rbLV", "rbCID", "rbNSID", "rbWrite",           \* doRollback
        "readLV", "readCID", "readNSID",                             \* readProperties
        "fed", "check", "branch", "upgBranch",                       \* doTransition
        "regLV", "regWrite",                                         \* DS:299-300
        "pfCID", "pfLV", "pfWrite",                                  \* doUpgrade (pre-federation)
        "upLV", "upWrite",                                           \* upgradeProperties (federation-era)
        "built",                                                     \* hs: DN-level load done
        "ok", "err"}                                                 \* task: future done
LdRecs == [pc : PCs, loc : Loc \cup {NoLoc}, fed : BOOLEAN,
           ns : {"C", "X", "NULL", NoLoc}, zombie : BOOLEAN]
Idle       == [pc |-> "idle", loc |-> NoLoc, fed |-> FALSE, ns |-> NoLoc, zombie |-> FALSE]
MainAtLoop == [pc |-> "loop", loc |-> NoLoc, fed |-> FALSE, ns |-> NnCid, zombie |-> FALSE]
NoFire     == [kind |-> NoLoc, loc |-> NoLoc, dsCid |-> NoLoc, nnCid |-> NoLoc,
               fileLv |-> NoLoc, fileCid |-> NoLoc]

HsBusy == \E l \in Loc : ld[HsId(l)].pc # "idle"
FileOf(w) == disk[ld[w].loc]

\* Storage.lock (ST:700, ST:906-922, ST:932-971): the per-directory file lock is held by
\* a live loader of the same location; a second loader in the same JVM gets
\* OverlappingFileLockException -> null -> IOException "Cannot lock storage".
\* PROVIDED locations are never locked (ST:663-667 returns before ST:700).
Locked(l, w) == \E v \in LdIds \ {w} : ld[v].pc # "idle" /\ ld[v].loc = l

\* Storage.writeProperties -> DataStorage.setPropertiesFromFields (DS:591-610): the
\* VERSION file is a copy of the shared fields at write time.  DS:595 always writes
\* clusterID; DS:600-603 writes datanodeUuid if set; DS:606-609 writes namespaceID
\* only for a non-federation layoutVersion.
\* Abstraction: the four field reads of one VERSION write (DS:595, 597, 606, 608) are
\* taken at one instant.  A split could pair a clusterID read before another worker's
\* writes with a layoutVersion read after them; it only adds more ways to persist a
\* (federation LV, "") pair, which Scenario 1 already reaches with the atomic write,
\* and at startup every writer of a federation LV other than the main loop itself
\* has already stored "C" (DS:860 before DS:874).
VFF == [lv |-> sLV, cid |-> sCID, nsid |-> IF FED(sLV) THEN "NONE" ELSE sNSID, uuid |-> dnUuid]

\* DN:2062 generateUuid(): a random UUID, equal to no value a VERSION file holds.
UuidsOnDisk == {disk[x].uuid : x \in Loc} \cup {prev[x].uuid : x \in Loc}
FreshUuid == CHOOSE u \in UuidVals \ {0, 1} : u \notin UuidsOnDisk

\* DS:662-672: a VERSION with a datanodeUuid key must carry the DataStorage's value, if set.
UuidMismatch(f) == f.uuid # 0 /\ dnUuid # 0 /\ dnUuid # f.uuid
\* DS:665-666: adopted if the DataStorage has none yet.
AdoptUuid(f) == IF dnUuid = 0 THEN f.uuid ELSE dnUuid

\* doTransition entry (DS:296 -> DS:726): only the main loop runs with the DataNode's
\* startup option; hot-swap workers run with HOTSWAP (DS:333-334).
TransPc(w) == IF w = MainId /\ startOpt = "ROLLBACK" THEN "rbRestore" ELSE "readLV"

(***************************************************************************)
(* Loader exits.  Each helper assigns exactly exitVars.                    *)
(***************************************************************************)
GoLd(w, p) ==
    /\ ld' = [ld EXCEPT ![w].pc = p]
    /\ UNCHANGED <<loaded, mainOk, mainJoin>>

\* IOException out of loadStorageDirectory (DS:304-307: unlock, rethrow).
\*   main: caught at DS:424-426, loop continues;  hs: FSD:522-524 -> DN:1336-1340.
FailLd(w) ==
    /\ ld' = [ld EXCEPT ![w] = IF w = MainId THEN MainAtLoop ELSE Idle]
    /\ UNCHANGED <<loaded, mainOk, mainJoin>>

\* NullPointerException (diag: hot swap with a null nsInfos.get(0)).  DS:304 catches
\* only IOException, FSD:520-525 and DN:1320-1326 likewise; the future fails and
\* DN:1345-1349 reports it.  Never the target.  (The leaked file lock is not modeled:
\* a later load of that location may then also fail, which only removes behaviors.)
NpeLd(w) ==
    /\ ld' = [ld EXCEPT ![w] = Idle]
    /\ UNCHANGED <<loaded, mainOk, mainJoin>>

\* loadStorageDirectory returned sd (DS:303).
\*   main: DS:416-418 callables empty -> addStorageDir, success.add.
\*   hs:   back in prepareVolume (DS:335) -> BPSS + FSD.addVolume (AddVolumeBuild).
OkLd(w) ==
    IF w = MainId
    THEN /\ loaded' = loaded \cup {ld[w].loc}
         /\ mainOk' = mainOk \cup {ld[w].loc}
         /\ ld' = [ld EXCEPT ![w] = MainAtLoop]
         /\ UNCHANGED mainJoin
    ELSE /\ ld' = [ld EXCEPT ![w].pc = "built"]
         /\ UNCHANGED <<loaded, mainOk, mainJoin>>

\* Main loop, pre-federation directory: DS:839-849 adds the doUpgrade callable,
\* DS:770 returns true, DS:303 returns sd, DS:416-422 submits it to the executor.
SubmitTask(w) ==
    LET l == ld[w].loc IN
    /\ Assert(ld[TaskId(l)].pc = "idle", "two upgrade tasks for one location")
    /\ ld' = [ld EXCEPT ![w] = MainAtLoop,
                        ![TaskId(l)] = [pc |-> "pfCID", loc |-> l, fed |-> FALSE,
                                        ns |-> ld[w].ns, zombie |-> FALSE]]
    /\ mainJoin' = mainJoin \cup {l}
    /\ UNCHANGED <<loaded, mainOk>>

\* End of doUpgrade (DS:864-866).
\*   task:   the future completes (DS:846); the main loop joins it at DS:437.  A zombie
\*           (its init was interrupted) has no joiner: its directory is never added.
\*   hs:     inline doUpgrade (DS:840) -> DS:770 -> DS:303.
DoUpgradeDone(w) ==
    IF w[1] = "task"
    THEN IF ld[w].zombie
         THEN /\ ld' = [ld EXCEPT ![w] = Idle]
              /\ UNCHANGED <<loaded, mainOk, mainJoin>>
         ELSE GoLd(w, "ok")
    ELSE OkLd(w)

(***************************************************************************)
(* loadStorageDirectory (DS:269-308) and its callees, one step per access  *)
(* to a shared DataStorage field.                                          *)
(***************************************************************************)

\* DS:272-274 -> Storage.StorageDirectory.analyzeStorage (ST:659-781)
AnalyzeStorage(w) ==
    /\ ld[w].pc = "analyze"
    /\ LET l == ld[w].loc IN
       IF l \in ProvLocs
         \* ST:663-667 PROVIDED is NORMAL (no lock); DS:296 -> DS:722-724
         \* createStorageID, return false ("regular start up for PROVIDED")
         THEN GoLd(w, "regLV")
       ELSE IF Locked(l, w)
         THEN FailLd(w)                       \* ST:700 lock() fails; DS:304-306
       ELSE IF disk[l] = NoRec
         \* ST:704-709 (HOTSWAP + mkdirs) or ST:727-738 (no VERSION): NOT_FORMATTED
         THEN IF ld[w].ns = "NULL"
                THEN NpeLd(w)                 \* DS:284-285 nsInfo.getNamespaceID()
                ELSE GoLd(w, "fmtLV")         \* DS:283-287 format
       \* ST:730-731 NORMAL -> DS:296 doTransition
       ELSE GoLd(w, TransPc(w))
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

\* ---- DataStorage.format (DS:571-582) ------------------------------------
\* DS:573 clearDirectory (an I/O failure there writes no field: VolumeIOFailure)
FormatLV(w) ==
    /\ ld[w].pc = "fmtLV"
    /\ sLV' = "CUR"                                     \* DS:574
    /\ GoLd(w, "fmtCID")
    /\ UNCHANGED <<lifeVars, sCID, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

FormatCID(w) ==
    /\ ld[w].pc = "fmtCID"
    /\ sCID'  = ld[w].ns                                \* DS:575 nsInfo.getClusterID()
    /\ sNSID' = NnNsid                                  \* DS:576 nsInfo.getNamespaceID()
    \* DS:577 cTime; DS:578 setDatanodeUuid(datanode.getDatanodeUuid()) = the
    \* DataStorage's own value (DN:4016-4017), unchanged; DS:580 createStorageID
    /\ GoLd(w, "fmtWrite")
    /\ UNCHANGED <<lifeVars, sLV, dnUuid, diskVars, mainPending, tgtVars>>

FormatWrite(w) ==
    /\ ld[w].pc = "fmtWrite"
    /\ disk' = [disk EXCEPT ![ld[w].loc] = VFF]         \* DS:581 writeProperties
    /\ GoLd(w, TransPc(w))                              \* DS:287 -> DS:296 doTransition
    /\ UNCHANGED <<lifeVars, fieldVars, prev, mainPending, tgtVars>>

\* ---- DataStorage.doRollback (DS:919-963), main loop with -rollback (DS:726-727)
RollbackRestore(w) ==
    /\ ld[w].pc = "rbRestore"
    /\ LET l == ld[w].loc IN
       IF prev[l] = NoRec
         \* DS:924-927: no previous dir; FED(current LV) holds -> layout-version rollback
         THEN /\ GoLd(w, "rbLV")
              /\ UNCHANGED diskVars
         \* DS:934-948: prevInfo is a separate DataStorage (no shared field access); its
         \* LV check passes for every in-model previous layout, the cTime check is
         \* assumed to pass (prev cTime <= NN cTime, the documented rollback).
         \* DS:952-961: current -> removed.tmp, previous -> current, delete removed.tmp
         \* (crash recovery ST:771-780, ST:808-817 lands on one side of this step).
         ELSE /\ disk' = [disk EXCEPT ![l] = prev[l]]
              /\ prev' = [prev EXCEPT ![l] = NoRec]
              /\ GoLd(w, "readLV")                      \* DS:962 return -> DS:729
    /\ UNCHANGED <<lifeVars, fieldVars, mainPending, tgtVars>>

RollbackReadLV(w) ==
    /\ ld[w].pc = "rbLV"
    \* DS:927 readProperties(sd, CUR) -> DS:702-703 -> DS:628-629 override
    /\ sLV' = "CUR"
    /\ GoLd(w, "rbCID")
    /\ UNCHANGED <<lifeVars, sCID, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

\* ---- DataStorage.setFieldsFromProperties (DS:623-674), shared by the normal read
\* (DS:729) and the rollback read (DS:927).  DS:633 setcTime and DS:634
\* checkStorageType do not touch modeled fields and pass for in-model files.
ReadCidStep(w, here, next) ==
    /\ ld[w].pc = here
    /\ LET f == FileOf(w) IN
       \* DS:635 setClusterId(props, layoutVersion, sd): the argument is the shared
       \* layoutVersion read now; SI:204-205 decides on it.
       IF FED(sLV)
         THEN IF f.cid = "NONE"
                THEN /\ FailLd(w)                       \* SI:206 -> SI:255-257 "clusterID missing"
                     /\ UNCHANGED sCID
              ELSE IF ~(sCID = "" \/ f.cid = "" \/ sCID = f.cid)
                THEN /\ FailLd(w)                       \* SI:207-210 "cluster Id is incompatible with others."
                     /\ UNCHANGED sCID
              \* SI:211.  SI:207's read and SI:211's write are one step: in-model the
              \* shared value is "" or the file's, so SI:207 never fails in-model and the
              \* split would only move the write.
              ELSE /\ sCID' = f.cid
                   /\ GoLd(w, next)
         ELSE /\ GoLd(w, next)                          \* SI:204: not a federation layout
              /\ UNCHANGED sCID
    /\ UNCHANGED <<lifeVars, sLV, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

ReadNsidStep(w, here, next) ==
    /\ ld[w].pc = here
    /\ LET f == FileOf(w) IN
       IF ~FED(sLV)                                     \* DS:638-639 re-reads layoutVersion
         THEN IF f.nsid = "NONE"
                THEN /\ FailLd(w)                       \* DS:640 -> SI:229 -> SI:255-257 "namespaceID missing"
                     /\ UNCHANGED <<sNSID, dnUuid>>
              ELSE IF sNSID # "0" /\ f.nsid # "0" /\ sNSID # f.nsid
                THEN /\ FailLd(w)                       \* SI:230-233 "namespaceID is incompatible with others."
                     /\ UNCHANGED <<sNSID, dnUuid>>
              ELSE /\ sNSID' = f.nsid                   \* SI:234
                   \* DS:645-659 storage ID checks pass in-model (a new sd has no ID yet)
                   /\ IF UuidMismatch(f)
                        THEN /\ FailLd(w)                 \* DS:667-671 "DatanodeUuid=.. does not match"
                             /\ UNCHANGED dnUuid          \* the fields written so far stay
                        ELSE /\ dnUuid' = AdoptUuid(f)    \* DS:662-666
                             /\ GoLd(w, next)
         ELSE /\ UNCHANGED sNSID
              /\ IF UuidMismatch(f)
                   THEN /\ FailLd(w)                      \* DS:667-671
                        /\ UNCHANGED dnUuid
                   ELSE /\ dnUuid' = AdoptUuid(f)         \* DS:645-673
                        /\ GoLd(w, next)
    /\ UNCHANGED <<lifeVars, sLV, sCID, diskVars, mainPending, tgtVars>>

RollbackReadCID(w)  == ReadCidStep(w, "rbCID", "rbNSID")
RollbackReadNSID(w) == ReadNsidStep(w, "rbNSID", "rbWrite")

RollbackWrite(w) ==
    /\ ld[w].pc = "rbWrite"
    /\ disk' = [disk EXCEPT ![ld[w].loc] = VFF]         \* DS:928 writeProperties
    /\ GoLd(w, "readLV")                                \* DS:932 return -> DS:729
    /\ UNCHANGED <<lifeVars, fieldVars, prev, mainPending, tgtVars>>

\* ---- DataStorage.doTransition (DS:719-780), regular read path ----------
ReadLV(w) ==
    /\ ld[w].pc = "readLV"
    /\ LET f == FileOf(w) IN
       /\ Assert(f # NoRec, "readLV on a location without VERSION")
       \* DS:729 readProperties -> SI:148 readPropertiesFile -> DS:703 -> DS:631
       \* setLayoutVersion (SI:216-224)
       /\ IF f.lv = "FUT"
            THEN /\ FailLd(w)                           \* SI:219-221 IncorrectVersionException
                 /\ UNCHANGED sLV
            ELSE /\ sLV' = f.lv                          \* SI:223
                 /\ GoLd(w, "readCID")
    /\ UNCHANGED <<lifeVars, sCID, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

ReadCID(w)  == ReadCidStep(w, "readCID", "readNSID")
ReadNSID(w) == ReadNsidStep(w, "readNSID", "fed")

\* DS:730 checkVersionUpgradable(layoutVersion) and DS:731-733 assert pass for every
\* value the shared field holds after this loader's own DS:631 (PRE/OLD/CUR); the
\* read that matters is DS:735-737.
TransitionFed(w) ==
    /\ ld[w].pc = "fed"
    /\ Assert(sLV # "L0", "shared layoutVersion still 0 after a VERSION read")
    /\ ld' = [ld EXCEPT ![w].fed = FED(sLV), ![w].pc = "check"]   \* DS:735-737
    /\ UNCHANGED <<loaded, mainOk, mainJoin>>
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

\* DS:739-745 (federationSupported false): reads the shared namespaceID.
NamespaceCheck(w) ==
    /\ ld[w].pc = "check"
    /\ ~ld[w].fed
    /\ IF ld[w].ns = "NULL"
         THEN NpeLd(w)                                  \* DS:740 nsInfo.getNamespaceID()
       ELSE IF sNSID # NnNsid
         THEN FailLd(w)                                 \* DS:741 "Incompatible namespaceIDs"
       ELSE GoLd(w, "branch")
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

\* THE TARGET: DS:747-753 (federationSupported true).
TargetCheck(w) ==
    /\ ld[w].pc = "check"
    /\ ld[w].fed                                        \* DS:748 federationSupported
    /\ IF ld[w].ns = "NULL"
         THEN /\ NpeLd(w)                               \* DS:749 nsInfo.getClusterID() on null: NPE, not the target
              /\ UNCHANGED tgtVars
       ELSE IF sCID # ld[w].ns                          \* DS:749 !getClusterID().equals(nsInfo.getClusterID())
         THEN /\ targetFired' = TRUE                     \* DS:750 throw new IOException("Incompatible clusterIDs ...")
              /\ fireInfo' = [kind |-> w[1], loc |-> ld[w].loc, dsCid |-> sCID,
                              nnCid |-> ld[w].ns, fileLv |-> FileOf(w).lv,
                              fileCid |-> FileOf(w).cid]
              /\ FailLd(w)                              \* DS:304-307
       ELSE /\ GoLd(w, "branch")
            /\ UNCHANGED tgtVars
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending>>

\* DS:756-758: regular start up if the shared layoutVersion is current now.
RegularBranch(w) ==
    /\ ld[w].pc = "branch"
    /\ IF sLV = "CUR"
         THEN GoLd(w, "regLV")                          \* DS:757 createStorageID, DS:758 return false
         ELSE GoLd(w, "upgBranch")
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

\* DS:762-779: re-reads the shared layoutVersion.
UpgradeBranch(w) ==
    /\ ld[w].pc = "upgBranch"
    /\ IF sLV \in {"PRE", "OLD"}                        \* DS:762 layoutVersion > CUR
         THEN IF ld[w].fed
                THEN GoLd(w, "upLV")                    \* DS:763-766 upgradeProperties
              \* DS:768 doUpgradePreFederation: DS:808-838 (renames, BPSS format; the
              \* DS:808 read of layoutVersion only feeds linkAllBlocks and a log line)
              ELSE IF w = MainId
                THEN SubmitTask(w)                      \* DS:841-849 callable (callables != null)
              ELSE GoLd(w, "pfCID")                     \* DS:839-840 inline doUpgrade (hot swap)
       ELSE FailLd(w)                                   \* DS:777-779 "BUG: The stored LV ..." (sLV turned CUR since DS:756)
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

\* DS:299 after a non-upgrade transition (regular or PROVIDED).
ServiceLV(w) ==
    /\ ld[w].pc = "regLV"
    /\ sLV' = "CUR"                                     \* DS:299 setServiceLayoutVersion
    /\ GoLd(w, "regWrite")
    /\ UNCHANGED <<lifeVars, sCID, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

WriteLoaded(w) ==
    /\ ld[w].pc = "regWrite"
    /\ IF ld[w].loc \in ProvLocs
         THEN UNCHANGED disk                            \* DS:300 -> ST:1251-1257: no VERSION file for PROVIDED
         ELSE disk' = [disk EXCEPT ![ld[w].loc] = VFF]  \* DS:300 -> ST:1258-1283
    /\ OkLd(w)                                          \* DS:303
    /\ UNCHANGED <<lifeVars, fieldVars, prev, mainPending, tgtVars>>

\* ---- DataStorage.doUpgrade (DS:852-866): startup task or inline hot swap ----
\* DS:857 linkAllBlocks touches no DataStorage field (its failure: LinkBlocksFailure).
DoUpgradeCID(w) ==
    /\ ld[w].pc = "pfCID"
    /\ sCID' = ld[w].ns                                 \* DS:860 clusterID = nsInfo.getClusterID()
    /\ GoLd(w, "pfLV")
    /\ UNCHANGED <<lifeVars, sLV, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

DoUpgradeLV(w) ==
    /\ ld[w].pc = "pfLV"
    \* DS:861 upgradeProperties: DS:870-873 read layoutVersion only for createStorageID
    \* and a log line; DS:874
    /\ sLV' = "CUR"
    /\ GoLd(w, "pfWrite")
    /\ UNCHANGED <<lifeVars, sCID, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

DoUpgradeWrite(w) ==
    /\ ld[w].pc = "pfWrite"
    /\ LET l == ld[w].loc IN
       /\ disk' = [disk EXCEPT ![l] = VFF]              \* DS:875 writeProperties
       \* DS:831 current -> previous.tmp, DS:864 previous.tmp -> previous: the old
       \* VERSION becomes previous/VERSION.  A crash before DS:875 recovers the old
       \* state (ST:802-807 RECOVER_UPGRADE), after it completes (ST:797-801).
       /\ prev' = [prev EXCEPT ![l] = disk[l]]
    /\ DoUpgradeDone(w)
    /\ UNCHANGED <<lifeVars, fieldVars, mainPending, tgtVars>>

\* ---- upgradeProperties for a federation-era layout (DS:766 -> DS:868-876) ----
UpgradePropsLV(w) ==
    /\ ld[w].pc = "upLV"
    /\ sLV' = "CUR"                                     \* DS:874
    /\ GoLd(w, "upWrite")
    /\ UNCHANGED <<lifeVars, sCID, sNSID, dnUuid, diskVars, mainPending, tgtVars>>

UpgradePropsWrite(w) ==
    /\ ld[w].pc = "upWrite"
    /\ disk' = [disk EXCEPT ![ld[w].loc] = VFF]         \* DS:875
    /\ OkLd(w)                                          \* DS:770 return true -> DS:303
    /\ UNCHANGED <<lifeVars, fieldVars, prev, mainPending, tgtVars>>

(***************************************************************************)
(* Faults                                                                  *)
(***************************************************************************)
\* Volume I/O failure before any shared field write of this load: an unusable root
\* (ST:672-698 NON_EXISTENT -> DS:279-282), mkdirs or lock I/O errors, clearDirectory
\* (DS:573), the VERSION read (DS:702).  Tolerated at startup by
\* dfs.datanode.failed.volumes.tolerated (FSD:311-343).
\* Most startup disk failures are caught earlier: DN:3391-3405 StorageLocationChecker
\* (SLC:151-245) drops the location before the DataNode exists, so the main loop never
\* visits it, and FSD:313-318 still counts it as failed.  This step covers that route
\* too: it writes no field, so both reach the same state at InitFsDataset (the location
\* is in confDirs \ loaded, the shared fields are untouched).  Only the checker's own
\* tolerance failure (SLC:220-236, no DataNode at all) is not represented; it is the
\* same outcome as InitFails for this model.
VolumeIOFailure(w) ==
    /\ ld[w].pc = "analyze"
    /\ ld[w].loc \notin ProvLocs
    /\ FailLd(w)
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

\* DS:857 linkAllBlocks fails before DS:860.
\*   task: call() throws (DS:845) -> the future fails -> DS:439-440 at the join.
\*   hs:   inline -> DS:304-307.
LinkBlocksFailure(w) ==
    /\ ld[w].pc = "pfCID"
    /\ IF w[1] = "task"
         THEN IF ld[w].zombie
                THEN /\ ld' = [ld EXCEPT ![w] = Idle]
                     /\ UNCHANGED <<loaded, mainOk, mainJoin>>
                ELSE GoLd(w, "err")
         ELSE FailLd(w)
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

(***************************************************************************)
(* The startup main loop: DS.addStorageLocations (DS:382-401) under the DN *)
(* monitor (DN:2262-2264), called from DN.initStorage (DN:2251-2280).      *)
(***************************************************************************)

\* Init failed: DS:566-567 or FSD:327-343 -> DN:2199 throws -> BPOS:404-409
\* setNamespaceInfo(null) -> BPSA:910-921 (retry only if another actor can, RetryInit).
InitFails ==
    /\ dn' = "noBP"
    /\ ld' = [ld EXCEPT ![MainId] = Idle]
    /\ mainPending' = {} /\ mainJoin' = {} /\ mainOk' = {}

\* DS:408-431 loop head (iteration order = configuration order; any order is a
\* valid configuration, so the next location is chosen freely).
LoadDataStorageNext(l) ==
    /\ ld[MainId].pc = "loop"
    /\ l \in mainPending
    /\ mainPending' = mainPending \ {l}
    /\ IF l \in loaded
         THEN /\ mainOk' = mainOk \cup {l}              \* DS:427-429 "has already been used"
              /\ UNCHANGED ld
         ELSE /\ ld' = [ld EXCEPT ![MainId].pc = "analyze", ![MainId].loc = l]   \* DS:410-415
              /\ UNCHANGED mainOk
    /\ UNCHANGED <<lifeVars, loaded, fieldVars, diskVars, mainJoin, tgtVars>>

\* DS:433: loop finished; join the submitted upgrade tasks.
LoadDataStorageEndLoop ==
    /\ ld[MainId].pc = "loop"
    /\ mainPending = {}
    /\ ld' = [ld EXCEPT ![MainId].pc = "join"]
    /\ UNCHANGED <<lifeVars, loaded, fieldVars, diskVars, mainPending, mainJoin, mainOk, tgtVars>>

\* DS:435-444 (joins are field-free; any order of finished tasks).
LoadDataStorageJoin(l) ==
    /\ ld[MainId].pc = "join"
    /\ l \in mainJoin
    /\ ld[TaskId(l)].pc \in {"ok", "err"}
    /\ mainJoin' = mainJoin \ {l}
    /\ ld' = [ld EXCEPT ![TaskId(l)] = Idle]
    /\ IF ld[TaskId(l)].pc = "ok"
         THEN /\ loaded' = loaded \cup {l}              \* DS:437 addStorageDir(t.future.get())
              /\ mainOk' = mainOk \cup {l}              \* DS:438
         ELSE UNCHANGED <<loaded, mainOk>>              \* DS:439-440 ExecutionException
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, tgtVars>>

\* DS:392-397 -> DS:450-501 loadBlockPoolSliceStorage over the success locations.
\* BPSS has its own StorageInfo (BPSS:119, DS:1409-1419): no DataStorage field.
\* F = locations whose block-pool load fails (DS:473-476).
LoadBlockPoolSliceStorage(F) ==
    /\ ld[MainId].pc = "join"
    /\ mainJoin = {}
    /\ F \subseteq mainOk
    /\ IF mainOk \ F = {}
         \* DS:392-393 / BPSS failures -> DS:566-567 "All specified directories have
         \* failed to load." (the DN-level dirs already added stay in storageDirs)
         THEN /\ InitFails
              /\ UNCHANGED <<startOpt, confDirs>>
         ELSE /\ ld' = [ld EXCEPT ![MainId].pc = "uuid"]
              /\ UNCHANGED <<lifeVars, mainPending, mainJoin, mainOk>>
    /\ UNCHANGED <<loaded, fieldVars, diskVars, tgtVars>>

\* DN:2273 -> DN:2060-2066 checkDatanodeUuid (synchronized on the DataNode, so it
\* excludes the main loop and hot swap; only zombie tasks can overlap it).
CheckDatanodeUuid ==
    /\ ld[MainId].pc = "uuid"
    /\ IF dnUuid = 0
         THEN /\ dnUuid' = FreshUuid                     \* DN:2062
              /\ sLV' = "CUR"                            \* DN:2063 writeAll -> ST:1397
              \* ST:1398-1400: every loaded directory's VERSION from the fields
              \* (PROVIDED: no file).  One step: only zombie tasks run concurrently and
              \* they never write "" (see the brief §4.3).
              /\ disk' = [l \in Loc |->
                            IF l \in loaded \ ProvLocs
                              THEN [lv |-> "CUR", cid |-> sCID, nsid |-> "NONE", uuid |-> FreshUuid]
                              ELSE disk[l]]
         ELSE UNCHANGED <<dnUuid, sLV, disk>>
    /\ ld' = [ld EXCEPT ![MainId].pc = "fsd"]
    /\ UNCHANGED <<lifeVars, loaded, sCID, sNSID, prev, mainPending, mainJoin, mainOk, tgtVars>>

\* DN:2275-2279 data == null -> FsDatasetImpl constructor (FSD:299-343): volumes that
\* are configured but not loaded at DataNode level count as failed (FSD:411-425).
InitFsDataset ==
    /\ ld[MainId].pc = "fsd"
    /\ LET failed == confDirs \ loaded
           ok == IF VolTolerated = -1
                   THEN failed # confDirs                     \* FSD:327-334
                   ELSE Cardinality(failed) <= VolTolerated   \* FSD:335-342
       IN IF ok
            THEN /\ dn' = "up"                           \* DN:2202-2211, BPSA:926 RUNNING
                 /\ ld' = [ld EXCEPT ![MainId] = Idle]
                 /\ mainPending' = {} /\ mainJoin' = {} /\ mainOk' = {}
            ELSE InitFails                               \* DiskErrorException "Too many failed volumes"
    /\ UNCHANGED <<startOpt, confDirs, loaded, fieldVars, diskVars, tgtVars>>

\* An interrupt of the block-pool thread (BPSA:622-629 stop(): DataNode shutdown,
\* refreshNamenodes removing the nameservice, refreshNNList removing this NameNode):
\* at DS:437 future.get() -> DS:441-442 InterruptedIOException; between loads the
\* remaining loads fail on their first interruptible I/O and the join throws.
\* DS:398-400 executor.shutdown() lets submitted tasks finish: they become zombies.
InitBlockPoolInterrupted ==
    /\ dn = "init"
    /\ ld[MainId].pc \in {"loop", "join"}
    /\ dn' = "noBP"
    /\ ld' = [w \in LdIds |->
                IF w = MainId THEN Idle
                ELSE IF w[1] = "task" /\ ld[w].pc \in {"ok", "err"} THEN Idle   \* never joined
                ELSE IF w[1] = "task" /\ ld[w].pc # "idle" THEN [ld[w] EXCEPT !.zombie = TRUE]
                ELSE ld[w]]
    /\ mainPending' = {} /\ mainJoin' = {} /\ mainOk' = {}
    /\ UNCHANGED <<startOpt, confDirs, loaded, fieldVars, diskVars, tgtVars>>

\* BPSA:913-917 retry by an actor that can still init (HA peer, re-added nameservice):
\* BPSA:908 -> BPOS:394 (bpNSInfo was reset at BPOS:408) -> DN:2199 -> DN:2262-2263,
\* same DataStorage object, same startup option.
InitBlockPoolRetry ==
    /\ RetryInit
    /\ dn = "noBP"
    /\ dn' = "init"
    /\ ld' = [ld EXCEPT ![MainId] = MainAtLoop]
    /\ mainPending' = confDirs
    /\ mainJoin' = {} /\ mainOk' = {}
    /\ UNCHANGED <<startOpt, confDirs, loaded, fieldVars, diskVars, tgtVars>>

(***************************************************************************)
(* DataNode lifecycle                                                      *)
(***************************************************************************)

\* DataNode start: DN:1921-1931 new DataStorage() (SI:56-58: LV 0, cid "", nsid 0);
\* BPSA:302-317 handshake -> BPOS:382-401 -> DN:2185-2199 initBlockPool ->
\* DN:2251-2264 initStorage -> DS:564-566 -> DS:382-389 -> DS:403-408.
DataNodeStart ==
    /\ dn = "down"
    /\ \E opt \in StartOpts : startOpt' = opt
    /\ dn' = "init"
    /\ sLV' = "L0" /\ sCID' = "" /\ sNSID' = "0" /\ dnUuid' = 0
    /\ loaded' = {}
    /\ ld' = [ld EXCEPT ![MainId] = MainAtLoop]
    /\ mainPending' = confDirs
    /\ mainJoin' = {} /\ mainOk' = {}
    /\ UNCHANGED <<confDirs, diskVars, tgtVars>>

\* DataNode shutdown / process exit: every loader thread dies with the process; the
\* DataStorage object is gone (its fields are reset to canonical values, which no
\* step reads while the DataNode is down).
DataNodeShutdown ==
    /\ dn # "down"
    /\ dn' = "down"
    /\ startOpt' = "REGULAR"
    /\ ld' = [w \in LdIds |-> Idle]
    /\ loaded' = {}
    /\ sLV' = "L0" /\ sCID' = "" /\ sNSID' = "0" /\ dnUuid' = 0
    /\ mainPending' = {} /\ mainJoin' = {} /\ mainOk' = {}
    /\ UNCHANGED <<confDirs, diskVars, tgtVars>>

(***************************************************************************)
(* Hot swap: DN.reconfigurePropertyImpl(dfs.datanode.data.dir) (DN:640-648)*)
(* -> DN.refreshVolumes (DN:1284-1373).                                    *)
(***************************************************************************)

\* DN:1286-1289 nsInfos from every BPOS (outside the monitor); DN:1290 DN monitor;
\* DN:1295 parseChangedVolumes: new locations = the new value minus loaded dirs
\* (DN:1169-1202); the new value keeps every loaded location (dropping the PROVIDED
\* one NPEs at DN:1196-1200; removals are not modeled).  DN:1312-1329: one worker per
\* new location; DS:327 containsStorageDir is false for each.
RefreshVolumes(S, ns) ==
    /\ dn = "up"
    /\ ~HsBusy
    /\ S # {} /\ S \subseteq SwapCands \ loaded
    /\ Cardinality(S) <= HotSwapWidth
    /\ ns \in HsNsChoices
    /\ confDirs' = confDirs \cup S
    /\ ld' = [w \in LdIds |->
                IF w[1] = "hs" /\ w[2] \in S
                  THEN [pc |-> "analyze", loc |-> w[2], fed |-> FALSE, ns |-> ns, zombie |-> FALSE]
                  ELSE ld[w]]
    /\ UNCHANGED <<dn, startOpt, loaded, fieldVars, diskVars, mainPending, mainJoin, mainOk, tgtVars>>

\* DS:335-345 BPSS loads (own StorageInfo) -> FSD:527-560: build() (DS:252-266, under
\* the DataStorage monitor) adds the directory; ok = FALSE: a BPSS/addBlockPool
\* failure (DS:341, FSD:536-554) and the volume is not added.  The reconfiguration
\* thread releases the DN monitor when every worker returned (DN:1331-1371).
AddVolumeBuild(l, ok) ==
    /\ ld[HsId(l)].pc = "built"
    /\ ld' = [ld EXCEPT ![HsId(l)] = Idle]
    /\ loaded' = IF ok THEN loaded \cup {l} ELSE loaded
    /\ UNCHANGED <<lifeVars, fieldVars, diskVars, mainPending, mainJoin, mainOk, tgtVars>>

(***************************************************************************)
(* Trace-only environment steps (not in Next): the workload fixture       *)
(* rewrites the DN-level VERSION (T-UU:482-498) and the test switches the  *)
(* data directory between its clusters.  MC never uses them.               *)
(***************************************************************************)
FixtureWriteVersion(l, rec) ==
    /\ dn = "down"
    /\ disk' = [disk EXCEPT ![l] = rec]
    /\ UNCHANGED <<lifeVars, loaded, fieldVars, prev, ld, mainPending, mainJoin, mainOk, tgtVars>>

FixtureSetDataDirs(dirs) ==
    /\ dn = "down"
    /\ confDirs' = dirs
    /\ UNCHANGED <<dn, startOpt, loaded, fieldVars, diskVars, ld, mainPending, mainJoin, mainOk, tgtVars>>

(***************************************************************************)
(* Spec                                                                    *)
(***************************************************************************)
Init ==
    /\ dn = "down"
    /\ startOpt = "REGULAR"
    /\ confDirs = StartDirs
    /\ loaded = {}
    /\ sLV = "L0" /\ sCID = "" /\ sNSID = "0" /\ dnUuid = 0
    /\ disk \in {d \in [Loc -> UNION {InitRecs(x) : x \in Loc}] : \A x \in Loc : d[x] \in InitRecs(x)}
    /\ prev = [x \in Loc |-> NoRec]
    /\ ld = [w \in LdIds |-> Idle]
    /\ mainPending = {} /\ mainJoin = {} /\ mainOk = {}
    /\ targetFired = FALSE
    /\ fireInfo = NoFire

LoaderStep(w) ==
    \/ AnalyzeStorage(w)
    \/ FormatLV(w) \/ FormatCID(w) \/ FormatWrite(w)
    \/ RollbackRestore(w) \/ RollbackReadLV(w) \/ RollbackReadCID(w)
    \/ RollbackReadNSID(w) \/ RollbackWrite(w)
    \/ ReadLV(w) \/ ReadCID(w) \/ ReadNSID(w)
    \/ TransitionFed(w) \/ NamespaceCheck(w) \/ TargetCheck(w)
    \/ RegularBranch(w) \/ UpgradeBranch(w)
    \/ ServiceLV(w) \/ WriteLoaded(w)
    \/ DoUpgradeCID(w) \/ DoUpgradeLV(w) \/ DoUpgradeWrite(w)
    \/ UpgradePropsLV(w) \/ UpgradePropsWrite(w)

Next ==
    \/ DataNodeStart
    \/ DataNodeShutdown
    \/ \E x \in Loc : LoadDataStorageNext(x)
    \/ LoadDataStorageEndLoop
    \/ \E x \in Loc : LoadDataStorageJoin(x)
    \/ \E F \in SUBSET Loc : LoadBlockPoolSliceStorage(F)
    \/ CheckDatanodeUuid
    \/ InitFsDataset
    \/ InitBlockPoolInterrupted
    \/ InitBlockPoolRetry
    \/ \E S \in SUBSET SwapCands, ns \in HsNsChoices : RefreshVolumes(S, ns)
    \/ \E x \in Loc, ok \in BOOLEAN : AddVolumeBuild(x, ok)
    \/ \E w \in LdIds : LoaderStep(w)
    \/ \E w \in LdIds : VolumeIOFailure(w)
    \/ \E w \in LdIds : LinkBlocksFailure(w)

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The ad hoc oracle: DS:750 never throws.
TargetSafe == ~targetFired

\* Structural sanity 1: every variable in its domain; loader slots well formed.
TypeOK ==
    /\ dn \in {"down", "init", "up", "noBP"}
    /\ startOpt \in {"REGULAR", "ROLLBACK"}
    /\ confDirs \subseteq Loc /\ loaded \subseteq Loc
    /\ sLV \in SLvVals /\ sCID \in CidVals /\ sNSID \in NsidVals /\ dnUuid \in UuidVals
    /\ disk \in [Loc -> DiskVals] /\ prev \in [Loc -> DiskVals]
    /\ \A x \in Loc : disk[x] # NoRec => disk[x].lv # "L0"
    /\ ld \in [LdIds -> LdRecs]
    /\ mainPending \subseteq Loc /\ mainJoin \subseteq Loc /\ mainOk \subseteq Loc
    /\ targetFired \in BOOLEAN
    \* slots: the main loop exists exactly during a block-pool init; hot-swap
    \* workers only on a running DataNode; every joinable task is a live non-zombie
    /\ (ld[MainId].pc # "idle") <=> (dn = "init")
    /\ HsBusy => dn = "up"
    /\ \A x \in mainJoin : ld[TaskId(x)].pc # "idle" /\ ~ld[TaskId(x)].zombie
    /\ \A x \in Loc : (ld[TaskId(x)].pc # "idle" /\ ~ld[TaskId(x)].zombie) => x \in mainJoin
    /\ \A x \in Loc : ld[HsId(x)].pc # "idle" => ld[HsId(x)].loc = x
    /\ \A x \in Loc : ld[TaskId(x)].pc # "idle" => ld[TaskId(x)].loc = x

\* Structural sanity 2: no cluster ID is invented.  The shared field and every
\* VERSION file hold "", a NameNode's ID, or an ID that was on disk initially; a
\* missing clusterID key only survives from an initial file.
SourceCids == {"", NnCid} \cup {r.cid : r \in (UNION {InitRecs(x) : x \in Loc}) \ {NoRec}}
NoInventedCid ==
    /\ sCID \in SourceCids
    /\ \A x \in Loc : disk[x] # NoRec => disk[x].cid \in SourceCids
    /\ \A x \in Loc : prev[x] # NoRec => prev[x].cid \in SourceCids

\* Sanity only (must be VIOLATED): some loader is about to evaluate the target guard.
TargetReached == ~(\E w \in LdIds : ld[w].pc = "check" /\ ld[w].fed)

=============================================================================
