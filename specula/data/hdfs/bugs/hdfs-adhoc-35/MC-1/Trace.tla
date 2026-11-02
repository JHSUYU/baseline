------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for base (hdfs-adhoc-35, DataStorage.java:750).        *)
(*                                                                         *)
(* One linear NDJSON trace per test run.  Every base step is one event     *)
(* (instrumentation-spec.md); the harness serializes events with one leaf  *)
(* trace lock and reads the shared DataStorage fields inside it, so the    *)
(* file order is a linearization of the steps.  Events carry raw values:   *)
(* layout versions as ints, cluster IDs as strings, namespace IDs as ints; *)
(* this module maps them to the model's classes.                           *)
(*                                                                         *)
(* Every event is matched by exactly one wrapper that calls the base       *)
(* action with the parameters the event names and then checks the         *)
(* post-state against the event.  There are no silent steps: the replay is *)
(* deterministic, so TraceMatched (for-all under WF) is the right check.   *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

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

VARIABLE l          \* cursor into TraceLog (1-indexed)

logline == TraceLog[l]
Ev  == logline.event
Msg == logline.event.msg

(***************************************************************************)
(* Raw value mapping                                                       *)
(***************************************************************************)
\* The NameNode's cluster ID and namespace ID, as the first DataNodeStart event
\* reports them (every NameNode of the workload shares them).
FirstStart == TLCEval(CHOOSE k \in 1..Len(TraceLog) :
                        /\ TraceLog[k].event.name = "DataNodeStart"
                        /\ \A j \in 1..(k - 1) : TraceLog[j].event.name # "DataNodeStart")
NnCidRaw  == TLCEval(TraceLog[FirstStart].event.msg.nnCid)
NnNsidRaw == TLCEval(TraceLog[FirstStart].event.msg.nnNsid)

\* DataNodeLayoutVersion.supports(FEDERATION, lv) on the pinned classes (brief §1):
\* true for -35..-40, -42, -43, -45..-57; false for -16..-34, -41, -44.
PreLVs == (-34 .. -16) \cup {-41, -44}
OldLVs == (-56 .. -35) \ {-41, -44}
LvClass(v) ==
    IF v = 0 THEN "L0"
    ELSE IF v = -57 THEN "CUR"
    ELSE IF v \in OldLVs THEN "OLD"
    ELSE IF v \in PreLVs THEN "PRE"
    ELSE IF v < -57 THEN "FUT"
    ELSE "BAD"                       \* outside the modeled range: fails every check

CidOf(s)  == IF s = "" THEN "" ELSE IF s = NnCidRaw THEN "C" ELSE "X"
NsidOf(n) == IF n = 0 THEN "0" ELSE IF n = NnNsidRaw THEN "N" ELSE "X"

\* A DN-level VERSION as the harness reports it:
\*   {lv:int, hasCid:bool, cid:string, hasNsid:bool, nsid:int, hasUuid:bool}
\* The event says only whether a datanodeUuid key is present.  For a fixture write that is
\* the fixture's one constant identity (T-UU:486, base.tla's 1).  For a DataNode's own write
\* the identity comes from the model, and WroteOK compares presence; the identity itself
\* is validated through the ok flag of ReadNSID (DS:667-671).
RecOf(r) ==
    [lv   |-> LvClass(r.lv),
     cid  |-> IF r.hasCid THEN CidOf(r.cid) ELSE "NONE",
     nsid |-> IF r.hasNsid THEN NsidOf(r.nsid) ELSE "NONE",
     uuid |-> IF r.hasUuid THEN 1 ELSE 0]
HasKey(r) == [lv |-> r.lv, cid |-> r.cid, nsid |-> r.nsid, uuid |-> r.uuid # 0]

SetOf(seq) == {seq[i] : i \in DOMAIN seq}

\* loader identity: msg.kind in {"main","hs","task"}, msg.loc
EvW == IF Msg.kind = "main" THEN MainId ELSE <<Msg.kind, Msg.loc>>

(***************************************************************************)
(* Event predicates and post-state checks                                  *)
(***************************************************************************)
IsEvent(name) == l <= Len(TraceLog) /\ Ev.name = name

Advance == l' = l + 1

\* The shared DataStorage fields after the step (state = {lv, cid, nsid}).
FieldsOK ==
    /\ sLV'   = LvClass(Ev.state.lv)
    /\ sCID'  = CidOf(Ev.state.cid)
    /\ sNSID' = NsidOf(Ev.state.nsid)

\* The loader is the one the event names, at the location the event names.
AtLoc(w) == ld[w].loc = Msg.loc

\* ok = the step did not throw (intermediate steps only).
Survived(w) == ld'[w].pc \notin {"loop", "idle"}
OkOK(w) == Msg.ok = Survived(w)

\* The VERSION file the step wrote.
WroteOK == HasKey(disk'[Msg.loc]) = HasKey(RecOf(Msg.rec))

(***************************************************************************)
(* Wrappers: fixture and lifecycle                                         *)
(***************************************************************************)
FixtureSetDataDirsIfLogged ==
    /\ IsEvent("FixtureSetDataDirs")
    /\ FixtureSetDataDirs(SetOf(Msg.dirs))
    /\ Advance

FixtureWriteVersionIfLogged ==
    /\ IsEvent("FixtureWriteVersion")
    /\ Msg.loc \in Loc
    /\ FixtureWriteVersion(Msg.loc, RecOf(Msg.rec))
    /\ Advance

DataNodeStartIfLogged ==
    /\ IsEvent("DataNodeStart")
    /\ confDirs = SetOf(Msg.dirs)
    /\ CidOf(Msg.nnCid) = NnCid
    /\ NsidOf(Msg.nnNsid) = NnNsid
    /\ DataNodeStart
    /\ startOpt' = Msg.opt
    /\ FieldsOK
    /\ Advance

\* No state check: the DataStorage object is discarded (the model resets it).
DataNodeShutdownIfLogged ==
    /\ IsEvent("DataNodeShutdown")
    /\ DataNodeShutdown
    /\ Advance

(***************************************************************************)
(* Wrappers: main loop control                                             *)
(***************************************************************************)
LoadDataStorageNextIfLogged ==
    /\ IsEvent("LoadDataStorageNext")
    /\ Msg.loc \in Loc
    /\ Msg.used = (Msg.loc \in loaded)
    /\ LoadDataStorageNext(Msg.loc)
    /\ Advance

LoadDataStorageEndLoopIfLogged ==
    /\ IsEvent("LoadDataStorageEndLoop")
    /\ LoadDataStorageEndLoop
    /\ Advance

LoadDataStorageJoinIfLogged ==
    /\ IsEvent("LoadDataStorageJoin")
    /\ Msg.loc \in Loc
    /\ LoadDataStorageJoin(Msg.loc)
    /\ Msg.ok = (Msg.loc \in loaded')
    /\ Advance

LoadBlockPoolSliceStorageIfLogged ==
    /\ IsEvent("LoadBlockPoolSliceStorage")
    /\ LoadBlockPoolSliceStorage(SetOf(Msg.failed))
    /\ Msg.ok = (dn' = "init")                 \* result non-empty: init continues
    /\ Advance

CheckDatanodeUuidIfLogged ==
    /\ IsEvent("CheckDatanodeUuid")
    /\ Msg.writeAll = (dnUuid = 0)
    /\ CheckDatanodeUuid
    /\ FieldsOK
    /\ Advance

InitFsDatasetIfLogged ==
    /\ IsEvent("InitFsDataset")
    /\ InitFsDataset
    /\ Msg.up = (dn' = "up")
    /\ Advance

InitBlockPoolInterruptedIfLogged ==
    /\ IsEvent("InitBlockPoolInterrupted")
    /\ InitBlockPoolInterrupted
    /\ Advance

InitBlockPoolRetryIfLogged ==
    /\ IsEvent("InitBlockPoolRetry")
    /\ InitBlockPoolRetry
    /\ FieldsOK
    /\ Advance

(***************************************************************************)
(* Wrappers: hot swap                                                      *)
(***************************************************************************)
RefreshVolumesIfLogged ==
    /\ IsEvent("RefreshVolumes")
    /\ RefreshVolumes(SetOf(Msg.locs), IF Msg.nsNull THEN "NULL" ELSE NnCid)
    /\ Advance

AddVolumeBuildIfLogged ==
    /\ IsEvent("AddVolumeBuild")
    /\ Msg.loc \in Loc
    /\ AddVolumeBuild(Msg.loc, Msg.ok)
    /\ Advance

(***************************************************************************)
(* Wrappers: loader steps (msg.kind, msg.loc name the thread)              *)
(***************************************************************************)
AnalyzeStorageIfLogged ==
    /\ IsEvent("AnalyzeStorage")
    /\ LET w == EvW IN
       /\ w \in LdIds /\ AtLoc(w)
       /\ IF Msg.result = "FAIL"
            THEN /\ AnalyzeStorage(w) \/ VolumeIOFailure(w)
                 /\ ~Survived(w)
            ELSE /\ AnalyzeStorage(w)
                 /\ Survived(w)
                 /\ (Msg.result = "NOT_FORMATTED") = (ld'[w].pc = "fmtLV")
       /\ FieldsOK
    /\ Advance

FormatLVIfLogged ==
    /\ IsEvent("FormatLV")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ FormatLV(w) /\ FieldsOK
    /\ Advance

FormatCIDIfLogged ==
    /\ IsEvent("FormatCID")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ FormatCID(w) /\ FieldsOK
    /\ Advance

FormatWriteIfLogged ==
    /\ IsEvent("FormatWrite")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ FormatWrite(w) /\ FieldsOK /\ WroteOK
    /\ Advance

RollbackRestoreIfLogged ==
    /\ IsEvent("RollbackRestore")
    /\ LET w == EvW IN
       /\ w \in LdIds /\ AtLoc(w)
       /\ RollbackRestore(w)
       /\ Msg.restored = (ld'[w].pc = "readLV")
       /\ Msg.restored => WroteOK
       /\ FieldsOK
    /\ Advance

RollbackReadLVIfLogged ==
    /\ IsEvent("RollbackReadLV")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ RollbackReadLV(w) /\ FieldsOK
    /\ Advance

RollbackReadCIDIfLogged ==
    /\ IsEvent("RollbackReadCID")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ RollbackReadCID(w) /\ OkOK(w) /\ FieldsOK
    /\ Advance

RollbackReadNSIDIfLogged ==
    /\ IsEvent("RollbackReadNSID")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ RollbackReadNSID(w) /\ OkOK(w) /\ FieldsOK
    /\ Advance

RollbackWriteIfLogged ==
    /\ IsEvent("RollbackWrite")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ RollbackWrite(w) /\ FieldsOK /\ WroteOK
    /\ Advance

ReadLVIfLogged ==
    /\ IsEvent("ReadLV")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ ReadLV(w) /\ OkOK(w) /\ FieldsOK
    /\ Advance

ReadCIDIfLogged ==
    /\ IsEvent("ReadCID")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ ReadCID(w) /\ OkOK(w) /\ FieldsOK
    /\ Advance

ReadNSIDIfLogged ==
    /\ IsEvent("ReadNSID")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ ReadNSID(w) /\ OkOK(w) /\ FieldsOK
    /\ Advance

TransitionFedIfLogged ==
    /\ IsEvent("TransitionFed")
    /\ LET w == EvW IN
       /\ w \in LdIds /\ AtLoc(w)
       /\ TransitionFed(w)
       /\ ld'[w].fed = Msg.fed
       /\ FieldsOK
    /\ Advance

NamespaceCheckIfLogged ==
    /\ IsEvent("NamespaceCheck")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ NamespaceCheck(w) /\ OkOK(w) /\ FieldsOK
    /\ Advance

\* The target guard evaluated (fired = DS:750 thrown).
TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ LET w == EvW IN
       /\ w \in LdIds /\ AtLoc(w)
       /\ ld[w].ns = CidOf(Msg.nnCid)
       /\ TargetCheck(w)
       /\ targetFired' = Msg.fired
       /\ FieldsOK
    /\ Advance

RegularBranchIfLogged ==
    /\ IsEvent("RegularBranch")
    /\ LET w == EvW IN
       /\ w \in LdIds /\ AtLoc(w)
       /\ RegularBranch(w)
       /\ Msg.regular = (ld'[w].pc = "regLV")
       /\ FieldsOK
    /\ Advance

\* path: "props" (DS:766), "prefed" (DS:768; main: task submitted), "bug" (DS:777)
UpgradeBranchIfLogged ==
    /\ IsEvent("UpgradeBranch")
    /\ LET w == EvW IN
       /\ w \in LdIds /\ AtLoc(w)
       /\ UpgradeBranch(w)
       /\ CASE Msg.path = "props"  -> ld'[w].pc = "upLV"
            [] Msg.path = "prefed" -> IF w = MainId
                                        THEN ld'[TaskId(Msg.loc)].pc = "pfCID"
                                        ELSE ld'[w].pc = "pfCID"
            [] Msg.path = "bug"    -> ~Survived(w)
       /\ FieldsOK
    /\ Advance

ServiceLVIfLogged ==
    /\ IsEvent("ServiceLV")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ ServiceLV(w) /\ FieldsOK
    /\ Advance

\* hasRec = FALSE for a PROVIDED location (no VERSION file).
WriteLoadedIfLogged ==
    /\ IsEvent("WriteLoaded")
    /\ LET w == EvW IN
       /\ w \in LdIds /\ AtLoc(w)
       /\ WriteLoaded(w)
       /\ Msg.hasRec = (Msg.loc \notin ProvLocs)
       /\ Msg.hasRec => WroteOK
       /\ FieldsOK
    /\ Advance

DoUpgradeCIDIfLogged ==
    /\ IsEvent("DoUpgradeCID")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ DoUpgradeCID(w) /\ FieldsOK
    /\ Advance

DoUpgradeLVIfLogged ==
    /\ IsEvent("DoUpgradeLV")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ DoUpgradeLV(w) /\ FieldsOK
    /\ Advance

DoUpgradeWriteIfLogged ==
    /\ IsEvent("DoUpgradeWrite")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ DoUpgradeWrite(w) /\ FieldsOK /\ WroteOK
    /\ Advance

UpgradePropsLVIfLogged ==
    /\ IsEvent("UpgradePropsLV")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ UpgradePropsLV(w) /\ FieldsOK
    /\ Advance

UpgradePropsWriteIfLogged ==
    /\ IsEvent("UpgradePropsWrite")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ UpgradePropsWrite(w) /\ FieldsOK /\ WroteOK
    /\ Advance

LinkBlocksFailureIfLogged ==
    /\ IsEvent("LinkBlocksFailure")
    /\ LET w == EvW IN w \in LdIds /\ AtLoc(w) /\ LinkBlocksFailure(w) /\ FieldsOK
    /\ Advance

(***************************************************************************)
(* Spec                                                                    *)
(***************************************************************************)
TraceInit == Init /\ l = 1

TraceNext ==
    \/ FixtureSetDataDirsIfLogged
    \/ FixtureWriteVersionIfLogged
    \/ DataNodeStartIfLogged
    \/ DataNodeShutdownIfLogged
    \/ LoadDataStorageNextIfLogged
    \/ LoadDataStorageEndLoopIfLogged
    \/ LoadDataStorageJoinIfLogged
    \/ LoadBlockPoolSliceStorageIfLogged
    \/ CheckDatanodeUuidIfLogged
    \/ InitFsDatasetIfLogged
    \/ InitBlockPoolInterruptedIfLogged
    \/ InitBlockPoolRetryIfLogged
    \/ RefreshVolumesIfLogged
    \/ AddVolumeBuildIfLogged
    \/ AnalyzeStorageIfLogged
    \/ FormatLVIfLogged
    \/ FormatCIDIfLogged
    \/ FormatWriteIfLogged
    \/ RollbackRestoreIfLogged
    \/ RollbackReadLVIfLogged
    \/ RollbackReadCIDIfLogged
    \/ RollbackReadNSIDIfLogged
    \/ RollbackWriteIfLogged
    \/ ReadLVIfLogged
    \/ ReadCIDIfLogged
    \/ ReadNSIDIfLogged
    \/ TransitionFedIfLogged
    \/ NamespaceCheckIfLogged
    \/ TargetCheckIfLogged
    \/ RegularBranchIfLogged
    \/ UpgradeBranchIfLogged
    \/ ServiceLVIfLogged
    \/ WriteLoadedIfLogged
    \/ DoUpgradeCIDIfLogged
    \/ DoUpgradeLVIfLogged
    \/ DoUpgradeWriteIfLogged
    \/ UpgradePropsLVIfLogged
    \/ UpgradePropsWriteIfLogged
    \/ LinkBlocksFailureIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

\* Every event consumed (needs the WF conjunct of TraceSpec).
TraceMatched == <>(l > Len(TraceLog))

\* Exists-check alternative (INVARIANT; "violated" = some behavior consumed the
\* whole trace), for traces with genuinely concurrent events.
TraceNotDone == l <= Len(TraceLog)

TraceAlias ==
    [ l        |-> l,
      len      |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN Ev.name ELSE "DONE",
      emsg     |-> IF l <= Len(TraceLog) THEN Ev.msg ELSE "DONE",
      estate   |-> IF l <= Len(TraceLog) /\ "state" \in DOMAIN Ev THEN Ev.state ELSE "none",
      dn       |-> dn,
      sLV      |-> sLV,
      sCID     |-> sCID,
      sNSID    |-> sNSID,
      dnUuid   |-> dnUuid,
      disk     |-> disk,
      loaded   |-> loaded,
      ld       |-> [w \in {v \in LdIds : ld[v].pc # "idle"} |-> ld[w]],
      main     |-> <<mainPending, mainJoin, mainOk>>,
      fired    |-> targetFired ]

=============================================================================
