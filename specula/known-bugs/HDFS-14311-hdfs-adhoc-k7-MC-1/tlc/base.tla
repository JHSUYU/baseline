---------------------------- MODULE base ----------------------------
(***************************************************************************)
(* HDFS DataNode block-pool storage transition (ad hoc target hdfs-adhoc-k7) *)
(*                                                                         *)
(* Target: BlockPoolSliceStorage.doTransition, the IOException thrown at   *)
(*   BPSS:422 ("Datanode state: LV = .. is newer than the namespace state")*)
(*                                                                         *)
(* Category B (concurrent / runtime).  One JVM, one block pool, one shared *)
(* BlockPoolSliceStorage object whose plain fields layoutVersion / cTime   *)
(* (SI:46,49) are read and written field-by-field by:                      *)
(*   - the startup thread ("main"): DS.loadBlockPoolSliceStorage, one      *)
(*     volume at a time (DS:452-471), then the join (DS:473-485);          *)
(*   - the startup upgrade callables ("task", one per volume), run on the  *)
(*     executor (DS:463-464, BPSS:493-500, BPSS:504-520);                  *)
(*   - hot-swap threads ("hs", one per new volume), DN.refreshVolumes ->   *)
(*     FsDatasetImpl.addVolume -> DS.prepareVolume (DN:792-807,DS:324-346),*)
(*     which upgrade synchronously (callables == null, BPSS:490-491).      *)
(*                                                                         *)
(* Path abbreviations (pinned tree b0c5a8f9ae2, relative to                *)
(*   hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/ *)
(*   server/):                                                             *)
(*   BPSS = datanode/BlockPoolSliceStorage.java                            *)
(*   DS   = datanode/DataStorage.java                                      *)
(*   DN   = datanode/DataNode.java                                         *)
(*   SI   = common/StorageInfo.java                                        *)
(*   ST   = common/Storage.java                                            *)
(*                                                                         *)
(* Granularity: one action per read site and per write site of the shared *)
(* fields (brief §2 Scenario 1 "Granularity").  The JMM is modelled as     *)
(* sequentially consistent interleaving of these plain accesses.           *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    DNLV,          \* HdfsServerConstants.DATANODE_LAYOUT_VERSION (software LV)
    OLDLV,         \* an older DN layout (numerically larger, LVs are negative)
    INITLV,        \* initial value of the field: StorageInfo(NodeType) -> 0 (SI:55-56)
    OldCT,         \* pre-upgrade on-disk cTime C0
    NsCT,          \* nsInfo.getCTime(): the NN's cTime C1 (constant in the window)
    StartOrder,    \* dataDirs order seen by DS.loadBlockPoolSliceStorage (DS:452)
    HsVols,        \* volumes added by one DN.refreshVolumes call (DN:795)
    PoolSize,      \* DS.getParallelVolumeLoadThreadsNum (DS:348-358,385-387)
    InitDiskSet    \* set of admissible initial disk functions [Vols -> Disk]

StartVols == {StartOrder[i] : i \in 1..Len(StartOrder)}
Vols      == StartVols \cup HsVols

LVs == {DNLV, OLDLV, INITLV}
CTs == {OldCT, NsCT}

ASSUME /\ DNLV < OLDLV /\ OLDLV < INITLV      \* "newer" layout = smaller LV
       /\ OldCT < NsCT
       /\ StartVols \cap HsVols = {}
       /\ PoolSize >= 1

(* On-disk state of <SD>/current/<bpid> for one volume.                    *)
(*   ver     : current/VERSION exists                                      *)
(*   lv, ct  : contents of current/VERSION (meaningful only if ver)        *)
(*   prevTmp : previous.tmp exists     prev : previous exists              *)
Disk == [ver : BOOLEAN, lv : LVs, ct : CTs, prevTmp : BOOLEAN, prev : BOOLEAN]

(* Disk shapes used to build InitDiskSet.                                  *)
VersionDisk(lv, ct) == [ver |-> TRUE, lv |-> lv, ct |-> ct, prevTmp |-> FALSE, prev |-> FALSE]
\* bp dir with no current/VERSION (fresh disk; ST:711-714 NOT_FORMATTED)
FreshDisk == [ver |-> FALSE, lv |-> DNLV, ct |-> NsCT, prevTmp |-> FALSE, prev |-> FALSE]
\* Workload fixture: master copy at LV = DNLV, old cTime (UpgradeUtilities.java:372-420)
WorkloadDisk == VersionDisk(DNLV, OldCT)
\* Already current for this NN (regular startup)
CurrentDisk == VersionDisk(DNLV, NsCT)
\* The workload: every volume holds the fixture's VERSION.
WorkloadInitDisks == {[v \in Vols |-> WorkloadDisk]}
\* Workload: numDirs = 2 (TestAdhocWorkload7.java), in dfs.datanode.data.dir order.
WorkloadStartOrder == <<1, 2>>

(* Logical threads.  Uniform tuples so that TLC can compare them.          *)
MainT    == <<"main", 0>>
TaskT(v) == <<"task", v>>
HsT(v)   == <<"hs", v>>
Threads  == {MainT} \cup {TaskT(v) : v \in StartVols} \cup {HsT(v) : v \in HsVols}

(* Program counters.  Shared doTransition / loadStorageDirectory pcs are   *)
(* used by both "main" and "hs"; the doUpgrade(name, ...) pcs by both      *)
(* "task" and "hs".                                                        *)
PCs == { "analyze",                                  \* BPSS:157
         "fmtLV", "fmtCT", "fmtWpLV", "fmtWpCT",     \* BPSS:284-293
         "rpLV", "rpCT",                             \* BPSS:389 -> BPSS:342-350
         "r405", "r406", "r409", "r415", "r416",     \* BPSS:405-422
         "upgrade",                                  \* BPSS:446-501
         "regCT", "regLV", "regWpLV", "regWpCT",     \* BPSS:182-190
         "queued", "link", "uSetLV", "uSetCT",       \* BPSS:504-520
         "uWpLV", "uWpCT", "uRename",
         "wait", "idle", "join", "done" }

VARIABLES
    bpLV, bpCT,     \* SharedBpFields: this.layoutVersion / this.cTime (SI:46,49)
    disk,           \* VolumeDisk: per-volume on-disk state
    diskInit,       \* initial disk contents (history, for FieldProvenance)
    pc,             \* per-thread program counter
    curVol,         \* StartupLoop: index into StartOrder being processed by main
    loc,            \* thread-local temporaries: props snapshot / props being built
    volRes,         \* per-volume outcome: "pending" | "upgrading" | "ok" | "failed"
    targetFired     \* Target: the throw at BPSS:422 was executed

sharedVars == <<bpLV, bpCT>>
vars == <<bpLV, bpCT, disk, diskInit, pc, curVol, loc, volRes, targetFired>>

----------------------------------------------------------------------------
(* Helpers *)

VolOf(t) == IF t = MainT THEN StartOrder[curVol] ELSE t[2]

(* Thread finished its loadStorageDirectory for VolOf(t) with outcome r.   *)
(* main: next volume of the for-loop (DS:452) or the join (DS:473).        *)
(* hs  : addVolume returns (DN:800-804).                                   *)
FinishVol(t, r) ==
    /\ volRes' = [volRes EXCEPT ![VolOf(t)] = r]
    /\ IF t = MainT
         THEN IF curVol < Len(StartOrder)
                THEN /\ curVol' = curVol + 1
                     /\ pc' = [pc EXCEPT ![t] = "analyze"]
                ELSE /\ curVol' = curVol
                     /\ pc' = [pc EXCEPT ![t] = "join"]
         ELSE /\ curVol' = curVol
              /\ pc' = [pc EXCEPT ![t] = "done"]

(* Volumes with an upgrade callable running on a pool thread.              *)
RunningTasks == {v \in StartVols : pc[TaskT(v)] \in
                    {"uSetLV", "uSetCT", "uWpLV", "uWpCT", "uRename"}}

----------------------------------------------------------------------------
(* Initial state *)

Init ==
    /\ diskInit \in InitDiskSet
    /\ disk = diskInit
    \* DS:1367-1377: new BlockPoolSliceStorage(nsid, bpid, nsInfo.getCTime(), cid)
    \*   -> BPSS:114-120: super(DATA_NODE) leaves layoutVersion = 0 (SI:55-60),
    \*      this.cTime = cTime (BPSS:119)
    /\ bpLV = INITLV
    /\ bpCT = NsCT
    /\ curVol = 1
    /\ pc = [t \in Threads |->
               CASE t = MainT     -> IF Len(StartOrder) > 0 THEN "analyze" ELSE "join"
                 [] t[1] = "task" -> "idle"
                 [] OTHER         -> "wait"]
    /\ loc = [t \in Threads |-> [plv |-> DNLV, pct |-> NsCT, wlv |-> DNLV]]
    /\ volRes = [v \in Vols |-> "pending"]
    /\ targetFired = FALSE

----------------------------------------------------------------------------
(* Hot-swap start.  DN.refreshVolumes is synchronized(DataNode) (DN:765),  *)
(* as is the startup DN.initStorage block (DN:1759-1761), which only       *)
(* returns after the join (DS:473-485).  So the hot-swap threads start     *)
(* only after startup is completely done (brief §2 Scenario 2 "Exclusion").*)
(* DN:792-807: one pool thread per new location, all submitted at once.    *)
HotSwapStart(t) ==
    /\ t[1] = "hs"
    /\ pc[t] = "wait"
    /\ pc[MainT] = "done"
    /\ pc' = [pc EXCEPT ![t] = "analyze"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

(* BPSS:150-157 loadStorageDirectory -> ST:636-757 analyzeStorage.         *)
(* The bp dir was created just before (DS:453 / DS:338), so the root       *)
(* exists and hadMkdirs = FALSE (ST:650-661).                              *)
Analyze(t) ==
    /\ t[1] \in {"main", "hs"}
    /\ pc[t] = "analyze"
    /\ LET v == VolOf(t) IN
       \* Recovery states (previous.tmp etc., ST:717-756, BPSS:173-174) are
       \* out of scope (brief §3.2): no admissible initial disk has them and
       \* no thread re-analyzes a volume it is upgrading.
       /\ ~disk[v].prevTmp
       /\ IF disk[v].ver
            THEN pc' = [pc EXCEPT ![t] = "rpLV"]       \* ST:706-707 NORMAL -> BPSS:160-161
            ELSE /\ ~disk[v].prev                      \* ST:708-710 would throw
                 /\ pc' = [pc EXCEPT ![t] = "fmtLV"]   \* ST:711-714 NOT_FORMATTED -> BPSS:168-172
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

----------------------------------------------------------------------------
(* format(StorageDirectory, NamespaceInfo)  BPSS:284-293                   *)

\* BPSS:287 bpSdir.clearDirectory(); BPSS:288 this.layoutVersion = DNLV
FormatSetLV(t) ==
    /\ pc[t] = "fmtLV"
    /\ bpLV' = DNLV
    /\ disk' = [disk EXCEPT ![VolOf(t)].ver = FALSE]     \* clearDirectory
    /\ pc' = [pc EXCEPT ![t] = "fmtCT"]
    /\ UNCHANGED <<bpCT, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:289 this.cTime = nsInfo.getCTime()   (BPSS:290-291 nsid/bpid: constant)
FormatSetCT(t) ==
    /\ pc[t] = "fmtCT"
    /\ bpCT' = NsCT
    /\ pc' = [pc EXCEPT ![t] = "fmtWpLV"]
    /\ UNCHANGED <<bpLV, disk, diskInit, curVol, loc, volRes, targetFired>>

----------------------------------------------------------------------------
(* writeProperties(sd)  ST:1210-1221 -> BPSS:317-324 setPropertiesFromFields*)
(* Two separate reads of the shared fields (BPSS:320 then BPSS:323), then  *)
(* the whole props object is written to <sd>/current/VERSION (ST:1220).    *)
(* Called from BPSS:292 (format), BPSS:190 (regular), BPSS:514 (upgrade).  *)

WpLVPcs == {"fmtWpLV", "regWpLV", "uWpLV"}

\* BPSS:320 props.setProperty("layoutVersion", layoutVersion)
WritePropertiesLV(t) ==
    /\ pc[t] \in WpLVPcs
    /\ loc' = [loc EXCEPT ![t].wlv = bpLV]
    /\ pc' = [pc EXCEPT ![t] = CASE pc[t] = "fmtWpLV" -> "fmtWpCT"
                                 [] pc[t] = "regWpLV" -> "regWpCT"
                                 [] pc[t] = "uWpLV"   -> "uWpCT"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, volRes, targetFired>>

\* BPSS:323 props.setProperty("cTime", cTime); ST:1220 write VERSION file.
\* Continuation:
\*   fmtWpCT -> BPSS:292 returns -> BPSS:172 break -> BPSS:181 doTransition -> L389
\*   regWpCT -> BPSS:190 returns -> BPSS:193 return sd (volume loaded)
\*   uWpCT   -> BPSS:514 returns -> BPSS:518 rename
WritePropertiesCT(t) ==
    /\ pc[t] \in {"fmtWpCT", "regWpCT", "uWpCT"}
    /\ disk' = [disk EXCEPT ![VolOf(t)].ver = TRUE,
                            ![VolOf(t)].lv  = loc[t].wlv,
                            ![VolOf(t)].ct  = bpCT]
    /\ CASE pc[t] = "fmtWpCT" ->
               /\ pc' = [pc EXCEPT ![t] = "rpLV"]
               /\ UNCHANGED <<curVol, volRes>>
         [] pc[t] = "regWpCT" ->
               FinishVol(t, "ok")
         [] pc[t] = "uWpCT" ->
               /\ pc' = [pc EXCEPT ![t] = "uRename"]
               /\ UNCHANGED <<curVol, volRes>>
    /\ UNCHANGED <<bpLV, bpCT, diskInit, loc, targetFired>>

----------------------------------------------------------------------------
(* doTransition  BPSS:370-426.  StartupOption is REGULAR (startup) or      *)
(* HOTSWAP: the ROLLBACK branches BPSS:376-388 are not taken; storage is   *)
(* not PROVIDED (BPSS:373-375).                                            *)

\* BPSS:389 readProperties(sd) -> SI:132-135 (one file read into props)
\*   -> BPSS:344 setLayoutVersion -> SI:203-208 layoutVersion = lv.
\* SI:204-207 rejects lv < DNLV before assigning; the LV domain has none.
ReadPropertiesLV(t) ==
    /\ pc[t] = "rpLV"
    /\ LET d == disk[VolOf(t)] IN
       /\ d.ver
       /\ bpLV' = d.lv
       /\ loc' = [loc EXCEPT ![t].plv = d.lv, ![t].pct = d.ct]
    /\ pc' = [pc EXCEPT ![t] = "rpCT"]
    /\ UNCHANGED <<bpCT, disk, diskInit, curVol, volRes, targetFired>>

\* BPSS:346 setcTime -> SI:182 cTime = props cTime  (BPSS:345 nsid and
\* BPSS:348-349 bpid are constant and pass).  BPSS:390-404 checks pass for
\* the modelled LVs / ids and do not write the fields.
ReadPropertiesCT(t) ==
    /\ pc[t] = "rpCT"
    /\ bpCT' = loc[t].pct
    /\ pc' = [pc EXCEPT ![t] = "r405"]
    /\ UNCHANGED <<bpLV, disk, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:405 read this.layoutVersion == DNLV ? (&& short-circuits)
DoTransitionR405(t) ==
    /\ pc[t] = "r405"
    /\ pc' = [pc EXCEPT ![t] = IF bpLV = DNLV THEN "r406" ELSE "r409"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:406 read this.cTime == nsInfo.getCTime() ?
\*   true  -> BPSS:407 return false -> BPSS:182 regular path (BPSS:185)
\*   false -> BPSS:409
DoTransitionR406(t) ==
    /\ pc[t] = "r406"
    /\ pc' = [pc EXCEPT ![t] = IF bpCT = NsCT THEN "regCT" ELSE "r409"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:409 read this.layoutVersion > DNLV ?  If so BPSS:410
\* restoreBlockFilesFromTrash (I/O on trash/, no field access, BPSS:551-590).
DoTransitionR409(t) ==
    /\ pc[t] = "r409"
    /\ pc' = [pc EXCEPT ![t] = "r415"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:415 read this.layoutVersion > DNLV ?  (|| short-circuits)
\*   true  -> BPSS:417 doUpgrade
\*   false -> BPSS:416
DoTransitionR415(t) ==
    /\ pc[t] = "r415"
    /\ pc' = [pc EXCEPT ![t] = IF bpLV > DNLV THEN "upgrade" ELSE "r416"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

\* TARGET.  BPSS:416 read this.cTime < nsInfo.getCTime() ?
\*   true  -> BPSS:417 doUpgrade; BPSS:418 return true
\*   false -> BPSS:422 throw new IOException("Datanode state: LV = ...")
TargetCheck(t) ==
    /\ pc[t] = "r416"
    /\ IF bpCT < NsCT
         THEN /\ pc' = [pc EXCEPT ![t] = "upgrade"]
              /\ targetFired' = targetFired
              /\ UNCHANGED <<curVol, volRes>>
         ELSE /\ targetFired' = TRUE                 \* BPSS:422
              \* BPSS:194-196 rethrow; DS:467-470 (startup) logs and skips the
              \* volume, DN:801-802 (hot-swap) returns the exception.
              /\ FinishVol(t, "failed")
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, loc>>

----------------------------------------------------------------------------
(* Regular startup  BPSS:182-190 (doTransition returned false)             *)

\* BPSS:185 read getCTime() != nsInfo.getCTime() -> BPSS:186-187 throw
\* (a different IOException, not the target).
RegularCheckCTime(t) ==
    /\ pc[t] = "regCT"
    /\ IF bpCT /= NsCT
         THEN FinishVol(t, "failed")
         ELSE /\ pc' = [pc EXCEPT ![t] = "regLV"]
              /\ UNCHANGED <<curVol, volRes>>
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, loc, targetFired>>

\* BPSS:189 setServiceLayoutVersion(getServiceLayoutVersion())
\*   -> SI:222-229 this.layoutVersion = DATANODE_LAYOUT_VERSION
RegularSetLV(t) ==
    /\ pc[t] = "regLV"
    /\ bpLV' = DNLV
    /\ pc' = [pc EXCEPT ![t] = "regWpLV"]
    /\ UNCHANGED <<bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

----------------------------------------------------------------------------
(* doUpgrade(bpSd, nsInfo, callables, conf)  BPSS:446-501                  *)
(* BPSS:451 supports(FEDERATION, layoutVersion) and BPSS:459 oldLV read    *)
(* the LV field; both DNLV and OLDLV support federation, so neither read   *)
(* changes control flow.  BPSS:470-481 deletes <SD>/previous and the bp    *)
(* previous/ dir; BPSS:487 renames current -> previous.tmp.                *)

RenameCurToPrevTmp(v) ==
    disk' = [disk EXCEPT ![v].ver = FALSE, ![v].prev = FALSE, ![v].prevTmp = TRUE]

\* Startup (callables != null): BPSS:492-500 callables.add(..); BPSS:418
\* return true; then DS:462-464 executor.submit(c) for this volume.
DoUpgradeSubmit(t) ==
    /\ t = MainT
    /\ pc[t] = "upgrade"
    /\ LET v == VolOf(t) IN
       /\ RenameCurToPrevTmp(v)
       /\ volRes' = [volRes EXCEPT ![v] = "upgrading"]
       /\ IF curVol < Len(StartOrder)
            THEN /\ curVol' = curVol + 1
                 /\ pc' = [pc EXCEPT ![t] = "analyze", ![TaskT(v)] = "queued"]
            ELSE /\ curVol' = curVol
                 /\ pc' = [pc EXCEPT ![t] = "join", ![TaskT(v)] = "queued"]
    /\ UNCHANGED <<bpLV, bpCT, diskInit, loc, targetFired>>

\* Hot-swap (callables == null, DS:341-342): BPSS:490-491 synchronous
\* doUpgrade(name, ...) on the same thread.
DoUpgradeSync(t) ==
    /\ t[1] = "hs"
    /\ pc[t] = "upgrade"
    /\ RenameCurToPrevTmp(VolOf(t))
    /\ pc' = [pc EXCEPT ![t] = "link"]
    /\ UNCHANGED <<bpLV, bpCT, diskInit, curVol, loc, volRes, targetFired>>

----------------------------------------------------------------------------
(* doUpgrade(name, bpSd, nsInfo, ...)  BPSS:504-520                        *)

\* BPSS:509 linkAllBlocks(bpTmpDir, bpCurDir, oldLV, conf): creates the new
\* current/ with hard links (no shared-field access).
\* task: a pool thread picks the queued callable (DS:387 fixed pool of
\* PoolSize threads; FIFO is not required by the model).
LinkAllBlocks(t) ==
    /\ \/ /\ t[1] = "task"
          /\ pc[t] = "queued"
          /\ Cardinality(RunningTasks) < PoolSize
       \/ /\ t[1] = "hs"
          /\ pc[t] = "link"
    /\ pc' = [pc EXCEPT ![t] = "uSetLV"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:510 this.layoutVersion = DATANODE_LAYOUT_VERSION
UpgradeSetLV(t) ==
    /\ pc[t] = "uSetLV"
    /\ bpLV' = DNLV
    /\ pc' = [pc EXCEPT ![t] = "uSetCT"]
    /\ UNCHANGED <<bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:513 this.cTime = nsInfo.getCTime()   (BPSS:511 assert: nsid constant)
UpgradeSetCT(t) ==
    /\ pc[t] = "uSetCT"
    /\ bpCT' = NsCT
    /\ pc' = [pc EXCEPT ![t] = "uWpLV"]
    /\ UNCHANGED <<bpLV, disk, diskInit, curVol, loc, volRes, targetFired>>

\* BPSS:518 rename(bpTmpDir, bpPrevDir); BPSS:519-520 return.
\*   task: BPSS:498 return bpSd -> future completes (DS:477)
\*   hs  : BPSS:491 -> BPSS:418 return true -> BPSS:193 return sd -> DN:800
UpgradeRenamePrev(t) ==
    /\ pc[t] = "uRename"
    /\ disk' = [disk EXCEPT ![VolOf(t)].prevTmp = FALSE, ![VolOf(t)].prev = TRUE]
    /\ IF t[1] = "task"
         THEN /\ volRes' = [volRes EXCEPT ![VolOf(t)] = "ok"]
              /\ pc' = [pc EXCEPT ![t] = "done"]
              /\ curVol' = curVol
         ELSE FinishVol(t, "ok")
    /\ UNCHANGED <<bpLV, bpCT, diskInit, loc, targetFired>>

----------------------------------------------------------------------------
(* DS:473-485 the startup thread waits for every submitted future, then    *)
(* DS:487 returns; DN.initStorage leaves synchronized(this) (DN:1761).     *)
JoinUpgradeTasks(t) ==
    /\ t = MainT
    /\ pc[t] = "join"
    /\ \A v \in StartVols : pc[TaskT(v)] \in {"idle", "done"}
    /\ pc' = [pc EXCEPT ![t] = "done"]
    /\ UNCHANGED <<bpLV, bpCT, disk, diskInit, curVol, loc, volRes, targetFired>>

----------------------------------------------------------------------------
(* Next *)

ThreadStep(t) ==
    \/ HotSwapStart(t)
    \/ Analyze(t)
    \/ FormatSetLV(t)
    \/ FormatSetCT(t)
    \/ WritePropertiesLV(t)
    \/ WritePropertiesCT(t)
    \/ ReadPropertiesLV(t)
    \/ ReadPropertiesCT(t)
    \/ DoTransitionR405(t)
    \/ DoTransitionR406(t)
    \/ DoTransitionR409(t)
    \/ DoTransitionR415(t)
    \/ TargetCheck(t)
    \/ RegularCheckCTime(t)
    \/ RegularSetLV(t)
    \/ DoUpgradeSubmit(t)
    \/ DoUpgradeSync(t)
    \/ LinkAllBlocks(t)
    \/ UpgradeSetLV(t)
    \/ UpgradeSetCT(t)
    \/ UpgradeRenamePrev(t)
    \/ JoinUpgradeTasks(t)

\* Once the target fired, stop: keeps counterexamples short.
Next ==
    /\ ~targetFired
    /\ \E t \in Threads : ThreadStep(t)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
(* Invariants *)

\* The target check never fails (adhoc Shared Rule 1).
TargetSafe == ~targetFired

TypeOK ==
    /\ bpLV \in LVs
    /\ bpCT \in CTs
    /\ disk \in [Vols -> Disk]
    /\ diskInit \in [Vols -> Disk]
    /\ pc \in [Threads -> PCs]
    /\ curVol \in 1..(IF Len(StartOrder) = 0 THEN 1 ELSE Len(StartOrder))
    /\ loc \in [Threads -> [plv : LVs, pct : CTs, wlv : LVs]]
    /\ volRes \in [Vols -> {"pending", "upgrading", "ok", "failed"}]
    /\ targetFired \in BOOLEAN

\* The fields only hold the initial value, a value the code writes
\* (DNLV / nsInfo cTime) or a value some volume's VERSION held initially;
\* no VERSION ever holds a cTime newer than the NN's.
FieldProvenance ==
    /\ bpLV \in {INITLV, DNLV} \cup {diskInit[v].lv : v \in {w \in Vols : diskInit[w].ver}}
    /\ bpCT \in {NsCT} \cup {diskInit[v].ct : v \in {w \in Vols : diskInit[w].ver}}
    /\ \A v \in Vols : disk[v].ver => disk[v].ct <= NsCT

\* Sanity only (adhoc tla-patterns §2): must be VIOLATED in MC.cfg,
\* i.e. some state enables TargetCheck.
TargetReached == ~(\E t \in Threads : pc[t] = "r416")

=============================================================================
