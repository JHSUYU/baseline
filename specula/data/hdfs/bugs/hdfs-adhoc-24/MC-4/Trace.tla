-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-24, BPSS:421).                *)
(*                                                                         *)
(* Category A: one linear NDJSON trace per run (instrumentation-spec.md).  *)
(* Each line: {"tag":"trace","ts":..,"event":{"name":..,"nid":..,          *)
(*             "state":{..},"msg":{}}}                                     *)
(* cTime fields are emitted as decimal strings and replaced by their dense *)
(* rank (1, 2, ...; numeric order; "-1" -> -1) by the trace preprocessor   *)
(* before TLC reads the file: TLC integers are 32-bit and the spec only   *)
(* compares cTimes with =, <, >, which ranking preserves.                  *)
(*                                                                         *)
(* Workload: TestDFSUpgrade#testUpgrade. Its storage set-up is done by     *)
(* test fixtures (UpgradeUtilities.createNameNodeStorageDirs /            *)
(* createDataNodeStorageDirs / createDataNodeVersionFile / createEmptyDirs)*)
(* that write VERSION files directly, including the guard operand          *)
(* cTime = Long.MAX_VALUE in the "newer fsscTime" step                     *)
(* (test/TestDFSUpgrade.java:304-321, test/UpgradeUtilities.java:465-512). *)
(* Those writes are outside the fault model; they enter ONLY here, as the  *)
(* environment action FixtureSnapshotEv, never in MC.tla. Because that     *)
(* fixture makes the real run execute the L421 throw, TargetSafe is NOT    *)
(* checked in Trace.cfg (it is expected to become FALSE on that step).     *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

\* ---------------------------------------------------------------------------
\* Trace loading
\* ---------------------------------------------------------------------------
JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN  SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                  /\ x.tag = "trace"
                                  /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0
ASSUME TraceLog[1].event.name = "FixtureSnapshot"

VARIABLE l                      \* cursor into TraceLog (1-indexed)

logline == TraceLog[l]
Ev == logline.event
St == logline.event.state

IsEvent(name) == l <= Len(TraceLog) /\ Ev.name = name

\* Volumes: the keys of the "vols" objects of every FixtureSnapshot (config order: v1, v2, ...).
TraceVol == TLCEval(UNION {DOMAIN TraceLog[k].event.state.vols :
                             k \in {j \in 1..Len(TraceLog) : TraceLog[j].event.name = "FixtureSnapshot"}})
TraceInitLVs == {CurLV}         \* unused by TraceInit; Init's constant needs a value

ToSet(s) == {s[i] : i \in DOMAIN s}
J2Ver(j) == IF j.ok THEN Ver(j.lv, j.c) ELSE NoVer

\* Throw site (top stack frame "SimpleClass.method:line") of each modeled exception.
\* The frame line is the line javac gives the exception's constructor call (invokespecial <init>,
\* where the stack is captured): for a multi-line `throw new X(".." + a() + .. + b())` that is
\* the line of the LAST method call in the arguments, not the `throw` line (javap -c -l of the
\* pinned build: BPSS throw L421 -> frame 424 (`nsInfo.getCTime()`), L621 -> 626, L185 -> 186;
\* the Storage/StorageInfo throws keep their own line).
ErrSite(e) ==
    CASE e = "S733" -> "Storage$StorageDirectory.analyzeStorage:733"
      [] e = "S744" -> "Storage$StorageDirectory.analyzeStorage:744"
      [] e = "S755" -> "Storage$StorageDirectory.analyzeStorage:755"
      [] e = "S763" -> "Storage$StorageDirectory.analyzeStorage:763"
      [] e = "S773" -> "Storage$StorageDirectory.analyzeStorage:773"
      [] e = "B621" -> "BlockPoolSliceStorage.doRollback:626"
      [] e = "B388" -> "StorageInfo.getProperty:256"
      [] e = "B421" -> "BlockPoolSliceStorage.doTransition:424"
      [] e = "B185" -> "BlockPoolSliceStorage.loadStorageDirectory:186"
      [] OTHER      -> "unmapped"

\* ---------------------------------------------------------------------------
\* Initial state: nothing on disk, DataNode down; the first event is a FixtureSnapshot.
\* ---------------------------------------------------------------------------
TraceInit ==
    /\ l = 1
    /\ nnC = FormatC
    /\ nnPrevC = NoC
    /\ nnRU = "none"
    /\ ruAfterImage = FALSE
    /\ issued = {FormatC}
    /\ online = [v \in Vol |-> FALSE]
    /\ mustRollback = FALSE
    /\ cur = [v \in Vol |-> NoVer]
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

\* ---------------------------------------------------------------------------
\* Environment action (trace only): the test's fixture helpers prepared the storage.
\* The event carries what the test read back from disk after the fixture call.
\* ---------------------------------------------------------------------------
NoJVer == [ok |-> FALSE, lv |-> 0, c |-> NoC]
DefaultVolSnap == [online |-> FALSE, dnOk |-> TRUE, cur |-> NoJVer, prev |-> NoJVer,
                   prevTmp |-> NoJVer, remTmp |-> NoJVer, finTmp |-> FALSE,
                   marker |-> FALSE, trash |-> FALSE, dnPrev |-> FALSE]
VS(v) == IF v \in DOMAIN St.vols THEN St.vols[v] ELSE DefaultVolSnap

SnapCTimes ==
    ({St.nn.c, St.nn.prevC}
       \cup UNION {{VS(v).cur.c, VS(v).prev.c, VS(v).prevTmp.c, VS(v).remTmp.c} : v \in Vol})
    \ {NoC}

\* nnRunning = TRUE: the NameNode is up (the DataNode fixtures of TestDFSUpgrade run after
\* createCluster()); its on-disk cTime / previous are then checked against the spec, not set.
FixtureSnapshotEv ==
    /\ IsEvent("FixtureSnapshot")
    /\ ~dnUp                                   \* fixtures run while no DataNode is running
    /\ IF St.nnRunning
         THEN /\ nnC = St.nn.c
              /\ nnPrevC = St.nn.prevC
              /\ UNCHANGED <<nnC, nnPrevC, nnRU, ruAfterImage, mustRollback>>
         ELSE /\ nnC' = St.nn.c
              /\ nnPrevC' = St.nn.prevC
              /\ nnRU' = "none"
              /\ ruAfterImage' = FALSE
              /\ mustRollback' = FALSE
    /\ issued' = issued \cup SnapCTimes
    /\ online' = [v \in Vol |-> VS(v).online]
    /\ cur' = [v \in Vol |-> J2Ver(VS(v).cur)]
    /\ prev' = [v \in Vol |-> J2Ver(VS(v).prev)]
    /\ prevTmp' = [v \in Vol |-> J2Ver(VS(v).prevTmp)]
    /\ remTmp' = [v \in Vol |-> J2Ver(VS(v).remTmp)]
    /\ finTmp' = [v \in Vol |-> VS(v).finTmp]
    /\ marker' = [v \in Vol |-> VS(v).marker]
    /\ trash' = [v \in Vol |-> VS(v).trash]
    /\ dnPrev' = [v \in Vol |-> VS(v).dnPrev]
    /\ dnOk' = [v \in Vol |-> VS(v).dnOk]
    /\ UNCHANGED <<shared, dnCtl, ld, targetFired>>
    /\ l' = l + 1

\* ---------------------------------------------------------------------------
\* NameNode events (nid "nn0")
\* ---------------------------------------------------------------------------
NNUpgradeEv ==                                 \* FSI.doUpgrade, after L518
    /\ IsEvent("NNUpgrade")
    /\ NNDoUpgrade(St.c)
    /\ nnPrevC' = St.prevC                     \* L464 oldCTime = the cTime the spec holds
    /\ l' = l + 1

NNRollbackEv ==                                \* FSI.doRollback, after L568
    /\ IsEvent("NNRollback")
    /\ NNDoRollback
    /\ nnC' = St.c
    /\ l' = l + 1

NNFinalizeEv ==                                \* FSI.finalizeUpgrade, after L631
    /\ IsEvent("NNFinalize")
    /\ NNFinalizeUpgrade
    /\ l' = l + 1

NNCTimeRegressEv ==                            \* variant only: NN restarted on an older name dir
    /\ IsEvent("NNCTimeRegress")
    /\ NNCTimeRegress(St.c)
    /\ l' = l + 1

RUStartEv ==                                   \* FSN.startRollingUpgrade, after L7627
    /\ IsEvent("RUStart")
    /\ NNStartRollingUpgrade
    /\ l' = l + 1

RUFinalizeEv ==                                \* FSN.finalizeRollingUpgrade, after L7813
    /\ IsEvent("RUFinalize")
    /\ NNFinalizeRollingUpgrade
    /\ l' = l + 1

NNCheckpointEv ==                              \* FSImage.saveNamespace / checkpoint completed
    /\ IsEvent("NNCheckpoint")
    /\ \/ NNCheckpoint
       \/ /\ ~ENABLED NNCheckpoint             \* checkpoint without effect on the abstract state
          /\ UNCHANGED vars
    /\ l' = l + 1

NNRestartEv ==                                 \* NameNode (re)started without -upgrade / -rollback
    /\ IsEvent("NNRestart")
    /\ \/ NNRestart
       \/ /\ ~ENABLED NNRestart
          /\ UNCHANGED vars
    /\ nnRU' = St.ru
    /\ l' = l + 1

\* ---------------------------------------------------------------------------
\* DataNode events (nid "dn0")
\* ---------------------------------------------------------------------------
DNStartEv ==                                   \* DS.addStorageLocations, after L389 (loadDataStorage returned)
    /\ IsEvent("DNStart")
    /\ DataNodeStart(St.opt)
    /\ nsC' = St.nsC
    /\ dnLoaded' = ToSet(St.dnLoaded)
    /\ l' = l + 1

BPLoadVolumeEv ==                              \* DS.loadBlockPoolSliceStorage, before L464
    /\ IsEvent("BPLoadVolume")
    /\ LoadBlockPoolSliceStorageNext(St.vol)
    /\ l' = l + 1

BPAnalyzeEv ==                                 \* BPSS.loadStorageDirectory, after L156
    /\ IsEvent("BPAnalyze")
    /\ AnalyzeState(St.vol) = St.sdState       \* analyzeStorage result computed from the spec's disk
    /\ AnalyzeStorage(St.vol)
    /\ l' = l + 1

\* Write events carry the VERSION content read back from disk right after the write (lv, c):
\* it must equal what the spec's shared fields held at the write.
BPFormatEv ==                                  \* BPSS.format, after L291
    /\ IsEvent("BPFormat")
    /\ FormatWriteVersion(St.vol)
    /\ cur'[St.vol] = Ver(St.lv, St.c)
    /\ l' = l + 1

BPRollbackRenameCurEv ==                       \* BPSS.doRollback, after L637
    /\ IsEvent("BPRollbackRenameCur")
    /\ DoRollbackRenameCurrent(St.vol)
    /\ remTmp'[St.vol].ok                      \* the rename branch, not the L621 throw
    /\ l' = l + 1

BPRollbackRenamePrevEv ==                      \* BPSS.doRollback, after L640
    /\ IsEvent("BPRollbackRenamePrev")
    /\ DoRollbackRenamePrevious(St.vol)
    /\ l' = l + 1

BPRollbackDoneEv ==                            \* BPSS.doRollback, after L643
    /\ IsEvent("BPRollbackDone")
    /\ DoRollbackDeleteTmp(St.vol)
    /\ l' = l + 1

BPRestoreTrashEv ==                            \* BPSS.doTransition, after L386
    /\ IsEvent("BPRestoreTrash")
    /\ RestoreTrashForRollback(St.vol)
    /\ l' = l + 1

BPReadPropsEv ==                               \* BPSS.doTransition, after L388
    /\ IsEvent("BPReadProps")
    /\ cur[St.vol] = Ver(St.lv, St.c)         \* the VERSION that readProperties loaded
    /\ ReadPropertiesCTime(St.vol)
    /\ memC' = St.c
    /\ l' = l + 1

BPUpgradeRenameCurEv ==                        \* BPSS.doUpgrade, after L486
    /\ IsEvent("BPUpgradeRenameCur")
    /\ (St.mode = "inline") = (ld[St.vol].mode = "hotswap")   \* L489 callables == null
    /\ DoUpgradeRenameCurrent(St.vol)
    /\ l' = l + 1

BPUpgradeLinkedEv ==                           \* BPSS.doUpgrade(String, ..), after L508
    /\ IsEvent("BPUpgradeLinked")
    /\ LinkAllBlocks(St.vol)
    /\ l' = l + 1

BPUpgradeWriteEv ==                            \* BPSS.doUpgrade(String, ..), after L513
    /\ IsEvent("BPUpgradeWrite")
    /\ DoUpgradeWriteVersion(St.vol)
    /\ cur'[St.vol] = Ver(St.lv, St.c)
    /\ l' = l + 1

BPUpgradeDoneEv ==                             \* BPSS.doUpgrade(String, ..), after L517
    /\ IsEvent("BPUpgradeDone")
    /\ DoUpgradeRenameTmp(St.vol)
    /\ l' = l + 1

BPLoadedEv ==                                  \* BPSS.loadStorageDirectory, after L189
    /\ IsEvent("BPLoaded")
    /\ WritePropertiesAfterLoad(St.vol)
    /\ cur'[St.vol] = Ver(St.lv, St.c)
    /\ l' = l + 1

BPLoadFailedEv ==                              \* BPSS.loadStorageDirectory catch, L193
    /\ IsEvent("BPLoadFailed")
    /\ ld[St.vol].pc = "Fail"
    /\ ErrSite(ld[St.vol].err) = St.site       \* exception class/method/line agree
    /\ LoadStorageDirectoryFail(St.vol)
    /\ l' = l + 1

BPInitDoneEv ==                                \* DS.recoverTransitionRead, at L566
    /\ IsEvent("BPInitDone")
    /\ BlockPoolInitDone
    /\ (bpInit' = "done") = St.ok
    /\ dnRegC' = St.regC
    /\ l' = l + 1

HotSwapEv ==                                   \* DN.refreshVolumes, before L1317
    /\ IsEvent("HotSwap")
    /\ RefreshVolumes(ToSet(St.vols))
    /\ l' = l + 1

HotSwapBuildEv ==                              \* FSD.addVolume, after L559
    /\ IsEvent("HotSwapBuild")
    /\ HotSwapBuild(St.vol)
    /\ l' = l + 1

DNStopEv ==                                    \* DataNode.shutdown entry
    /\ IsEvent("DNStop")
    /\ DataNodeStop \/ DataNodeCrash           \* a shutdown while storage work is in flight loses it
    /\ l' = l + 1

DNCrashEv ==                                   \* variant only: the test kills the DataNode
    /\ IsEvent("DNCrash")
    /\ DataNodeCrash
    /\ l' = l + 1

SignalRUEv ==                                  \* BPSS.setRollingUpgradeMarkers L869-878 / clearRollingUpgradeMarkers L895-906
    /\ IsEvent("SignalRU")
    /\ St.status = nnRU
    /\ \/ SignalRollingUpgrade(St.vol)
       \/ /\ ~ENABLED SignalRollingUpgrade(St.vol)   \* volume already in the requested state
          /\ UNCHANGED vars
    /\ marker'[St.vol] = St.marker
    /\ l' = l + 1

TrashCreatedEv ==                              \* variant only: a replica moved to trash
    /\ IsEvent("TrashCreated")
    /\ TrashBlockDelete(St.vol)
    /\ l' = l + 1

DNFinalizeEv ==                                \* DS.finalizeUpgrade loop, L1021-1028 (only when something is finalized)
    /\ IsEvent("DNFinalize")
    /\ FinalizeUpgradeForVolume(St.vol)
    /\ l' = l + 1

FinalizeTmpDeleteEv ==                         \* BPSS doFinalize daemon, after L677
    /\ IsEvent("FinalizeTmpDelete")
    /\ FinalizeTmpDelete(St.vol)
    /\ l' = l + 1

VolumeOfflineEv ==                             \* variant only: the test fails a disk
    /\ IsEvent("VolumeOffline")
    /\ VolumeOffline(St.vol)
    /\ l' = l + 1

VolumeOnlineEv ==                              \* variant only: the test restores a disk
    /\ IsEvent("VolumeOnline")
    /\ VolumeOnline(St.vol)
    /\ l' = l + 1

AttachEmptyVolumeEv ==                         \* variant only: the test replaces a disk with an empty one
    /\ IsEvent("AttachEmptyVolume")
    /\ AttachEmptyVolume(St.vol)
    /\ l' = l + 1

\* ---------------------------------------------------------------------------
\* Silent actions. The guard reads of doTransition (L404, L405, L408, L414, L415) live inside the
\* target method's conditions and are not instrumented (the target check is not modified); the
\* field writes that precede an instrumented write (format L287-288, doUpgrade L509/L512, L188)
\* and the pure dispatch steps are silent too. Each is enabled only at its own program counter, so
\* a single loader's silent chain is deterministic; the throw branches of AnalyzeStorage and of the
\* L618-620 rollback check are silent and are followed by a BPLoadFailed event.
\* ---------------------------------------------------------------------------
SilentPcs == {"Dispatch", "FormatLV", "FormatC", "ReadPropsLV", "L404", "L405", "L408", "L409",
              "L414", "TargetCheck", "UpDelDnPrev", "UpDelPrev", "UpSetLV", "UpSetC",
              "PostCheckC", "PostSetLV"}

SilentLoader(v) ==
    \/ /\ ld[v].pc \in SilentPcs
       /\ LoaderStep(v)
    \/ /\ ld[v].pc = "Analyze"
       /\ AnalyzeState(v) \in AnalyzeErrs
       /\ AnalyzeStorage(v)
    \/ /\ ld[v].pc = "RbRenameCur"
       /\ ~(prev[v].lv >= CurLV /\ prev[v].c <= nsC)
       /\ DoRollbackRenameCurrent(v)

SilentStep ==
    /\ l <= Len(TraceLog)
    /\ Ev.nid = "dn0"                          \* only while DataNode events are pending
    /\ \/ \E v \in Vol : SilentLoader(v)
       \/ SubmitUpgradeCallables               \* DS:479-484, after the last volume of the loop
    /\ UNCHANGED l

\* ---------------------------------------------------------------------------
\* Next / Spec
\* ---------------------------------------------------------------------------
TraceDone ==
    /\ l > Len(TraceLog)
    /\ UNCHANGED <<vars, l>>

TraceNext ==
    \/ TraceDone
    \/ FixtureSnapshotEv
    \/ NNUpgradeEv \/ NNRollbackEv \/ NNFinalizeEv \/ NNCTimeRegressEv
    \/ RUStartEv \/ RUFinalizeEv \/ NNCheckpointEv \/ NNRestartEv
    \/ DNStartEv \/ DNStopEv \/ DNCrashEv
    \/ BPLoadVolumeEv \/ BPAnalyzeEv \/ BPFormatEv
    \/ BPRollbackRenameCurEv \/ BPRollbackRenamePrevEv \/ BPRollbackDoneEv \/ BPRestoreTrashEv
    \/ BPReadPropsEv
    \/ BPUpgradeRenameCurEv \/ BPUpgradeLinkedEv \/ BPUpgradeWriteEv \/ BPUpgradeDoneEv
    \/ BPLoadedEv \/ BPLoadFailedEv \/ BPInitDoneEv
    \/ HotSwapEv \/ HotSwapBuildEv
    \/ SignalRUEv \/ TrashCreatedEv \/ DNFinalizeEv \/ FinalizeTmpDeleteEv
    \/ VolumeOfflineEv \/ VolumeOnlineEv \/ AttachEmptyVolumeEv
    \/ SilentStep

\* Weak fairness makes TraceMatched meaningful (without it a behavior may stutter forever).
TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

\* The whole trace is consumed. Under WF every behavior must reach the end, so a branch that
\* dies on a post-state check also reports a violation: single-loader traces (the workload; its
\* parallel upgrade callables write identical values) have no such branch. For a concurrent
\* hot-swap variant use the existential check instead: INVARIANT TraceNotDone (a violation means
\* some behavior consumed the entire trace).
TraceMatched == <>(l > Len(TraceLog))
TraceNotDone == l <= Len(TraceLog)

TraceView == <<vars, l>>

TraceAlias ==
    [ cursor   |-> l,
      traceLen |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN Ev.name ELSE "DONE",
      tstate   |-> IF l <= Len(TraceLog) THEN St ELSE "DONE",
      nnC      |-> nnC, nnPrevC |-> nnPrevC, nsC |-> nsC,
      memLV    |-> memLV, memC |-> memC,
      ld       |-> ld, bpInit |-> bpInit,
      cur      |-> cur, prev |-> prev, prevTmp |-> prevTmp, remTmp |-> remTmp,
      targetFired |-> targetFired ]

=============================================================================
