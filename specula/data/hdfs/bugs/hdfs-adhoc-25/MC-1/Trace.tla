-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-25 (Category A: one linear NDJSON       *)
(* trace, cursor l).                                                       *)
(*                                                                         *)
(* The workload (TestDFSStartupVersions#testVersions) is single-threaded   *)
(* on the block-pool path. Hot-swap variants serialize each instrumented   *)
(* step with its event (instrumentation-spec.md, Section 3), so their      *)
(* traces are linear too.                                                  *)
(*                                                                         *)
(* Every event maps to exactly one base action with its parameters taken   *)
(* from the event; there are no silent actions. NNStart in the middle of a *)
(* trace (a NameNode restarted without -upgrade) changes no model state    *)
(* and only validates the cTime.                                           *)
(*                                                                         *)
(* cTime fields hold dense, order-preserving ranks written by the trace    *)
(* post-processor (instrumentation-spec.md, Section 3.2): -1 = absent      *)
(* (NoCT), -2 = no BlockPoolSliceStorage object (NoBpss).                  *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

----------------------------------------------------------------------------
\* Trace loading

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                 /\ x.tag = "trace"
                                 /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0
ASSUME TraceLog[1].event.name = "NNStart"

----------------------------------------------------------------------------
\* Locations: the trace names locations by path (PROVIDED: by URI); the model
\* numbers them. Any numbering works for traces (DNStart and Reconfigure carry
\* explicit lists), so names are numbered in a fixed CHOOSE order.

EvLocNames(e) ==
    (IF "loc" \in DOMAIN e THEN {e.loc} ELSE {})
    \cup (IF "dirs" \in DOMAIN e THEN {e.dirs[i] : i \in DOMAIN e.dirs} ELSE {})
    \cup (IF "conf" \in DOMAIN e THEN {e.conf[i] : i \in DOMAIN e.conf} ELSE {})

TraceLocSet == TLCEval(UNION {EvLocNames(TraceLog[k].event) : k \in 1..Len(TraceLog)})

RECURSIVE SetToSeq(_)
SetToSeq(S) == IF S = {} THEN <<>>
               ELSE LET x == CHOOSE y \in S : TRUE IN <<x>> \o SetToSeq(S \ {x})

TraceLocSeq == TLCEval(SetToSeq(TraceLocSet))

LocId(name) == CHOOSE i \in DOMAIN TraceLocSeq : TraceLocSeq[i] = name
Ids(names)  == [i \in DOMAIN names |-> LocId(names[i])]

\* Overrides for the base constants (Trace.cfg).
TraceLoc == TLCEval(DOMAIN TraceLocSeq)
TraceProvided == TLCEval(
    UNION {IF TraceLog[k].event.name = "DNStart"
           THEN {LocId(TraceLog[k].event.provided[i]) :
                     i \in DOMAIN TraceLog[k].event.provided}
           ELSE {} : k \in 1..Len(TraceLog)})

----------------------------------------------------------------------------
\* Cursor

VARIABLE l

logline == TraceLog[l]
ev == logline.event

IsEvent(name) == /\ l <= Len(TraceLog)
                 /\ ev.name = name

StepTrace == l' = l + 1

\* The thread of a block-pool event loads the event's location.
ThreadAt(name) ==
    /\ IsEvent(name)
    /\ ev.tid \in Thr
    /\ tLoc[ev.tid] = LocId(ev.loc)

----------------------------------------------------------------------------
\* Initial state: the first event is the NameNode start (NNStart). The
\* DataNode is down and its storage directories are empty until a DataNode
\* start formats them or the test fixture writes them.

TraceInit ==
    /\ l = 2
    /\ nnCT   = [n \in NN |-> TraceLog[1].event.ct]
    /\ nnPrev = [n \in NN |-> NoCT]
    /\ issued = {TraceLog[1].event.ct}
    /\ ver    = [x \in Loc |-> NoCT]
    /\ prev   = [x \in Loc |-> NoCT]
    /\ ptmp   = [x \in Loc |-> NoCT]
    /\ dnVer  = [x \in Loc |-> "none"]
    /\ bpBad  = [x \in Loc |-> "ok"]
    /\ dnUp = FALSE
    /\ dnOpt = "REGULAR"
    /\ confFile = <<>>
    /\ dataDirs = <<>>
    /\ dsDirs = {}
    /\ dataInit = FALSE
    /\ bpssCT = NoBpss
    /\ bpssDirs = {}
    /\ bpNS = NoCT
    /\ bposLive = FALSE
    /\ actor = [n \in NN |-> "dead"]
    /\ ldPhase = "idle" /\ ldOwner = AnyNN /\ ldNs = NoCT
    /\ ldQ = <<>> /\ ldDnOK = <<>> /\ ldDnPend = <<>>
    /\ ldAnyOK = FALSE /\ ldPend = {}
    /\ pc = [t \in Thr |-> "idle"]
    /\ tLoc = [t \in Thr |-> AnyLoc]
    /\ hsActive = FALSE /\ hsNs = NoCT /\ hsDeact = {}
    /\ targetFired = FALSE

----------------------------------------------------------------------------
\* Post-state checks (fields required by instrumentation-spec.md).

\* On-disk state of the event's location after the step.
DiskPost(i) ==
    /\ ver'[i]  = ev.ver
    /\ prev'[i] = ev.prev
    /\ ptmp'[i] = ev.ptmp

BpssPost == bpssCT' = ev.bpss

----------------------------------------------------------------------------
\* NameNode and environment events

NNStartIfLogged ==
    /\ IsEvent("NNStart")
    /\ nnCT[ev.nn] = ev.ct            \* restart without -upgrade: same cTime
    /\ UNCHANGED vars
    /\ StepTrace

NNUpgradeIfLogged ==
    /\ IsEvent("NNUpgrade")
    /\ NNUpgrade(ev.nn)
    /\ nnCT'[ev.nn] = ev.ct
    /\ StepTrace

NNRollbackIfLogged ==
    /\ IsEvent("NNRollback")
    /\ NNRollback(ev.nn)
    /\ nnCT'[ev.nn] = ev.ct
    /\ StepTrace

DiskReplaceIfLogged ==
    /\ IsEvent("DiskReplace")
    /\ DiskReplace(LocId(ev.loc))
    /\ StepTrace

FixtureWriteVersionIfLogged ==
    /\ IsEvent("FixtureWriteVersion")
    /\ FixtureWriteVersion(LocId(ev.loc), ev.dnVer, ev.bpCt, ev.bpBad)
    /\ StepTrace

----------------------------------------------------------------------------
\* DataNode process and BPOfferService events

DNStartIfLogged ==
    /\ IsEvent("DNStart")
    /\ DNStartConf(ev.opt, Ids(ev.dirs))
    /\ StepTrace

DNStopIfLogged ==
    /\ IsEvent("DNStop")
    /\ DNStop
    /\ StepTrace

HandshakeIfLogged ==
    /\ IsEvent("Handshake")
    /\ Handshake(ev.nn)
    /\ bpNS' = ev.ns
    /\ (ldPhase' = "dn") = ev.init
    /\ StepTrace

ActorRejectedIfLogged ==
    /\ IsEvent("ActorRejected")
    /\ ActorRejected(ev.nn)
    /\ bposLive' = ev.bposLive
    /\ StepTrace

----------------------------------------------------------------------------
\* Startup loader events

DNLevelLoadIfLogged ==
    /\ IsEvent("DNLevelLoad")
    /\ ldQ # <<>> /\ Head(ldQ) = LocId(ev.loc)
    /\ (LocId(ev.loc) \in dsDirs) = (ev.outcome = "used")     \* DS:409, 427-430
    /\ DNLevelLoad
    /\ CASE ev.outcome \in {"ok", "used"} ->
              ldDnOK' = Append(ldDnOK, LocId(ev.loc))
         [] ev.outcome = "preFed" ->
              ldDnPend' = Append(ldDnPend, LocId(ev.loc))
         [] ev.outcome = "fail" ->
              /\ ldDnOK' = ldDnOK /\ ldDnPend' = ldDnPend
    /\ BpssPost
    /\ StepTrace

\* bpLocs: the success list handed to loadBlockPoolSliceStorage, in order.
DNLevelJoinIfLogged ==
    /\ IsEvent("DNLevelJoin")
    /\ DNLevelJoin
    /\ IF ev.bpLocs = <<>>
       THEN ldPhase' = "join"
       ELSE /\ ldPhase' = "bp"
            /\ <<tLoc'[ST]>> \o ldQ' = Ids(ev.bpLocs)
    /\ BpssPost
    /\ StepTrace

DeferredUpgradeIfLogged ==
    /\ IsEvent("DeferredUpgrade")
    /\ RunDeferredUpgrade(LocId(ev.loc))
    /\ BpssPost
    /\ DiskPost(LocId(ev.loc))
    /\ StepTrace

InitFinishIfLogged ==
    /\ IsEvent("InitFinish")
    /\ ldAnyOK = ev.ok
    /\ InitFinish
    /\ actor'[ldOwner] = (IF ev.ok THEN "run" ELSE IF ev.retry THEN "conn" ELSE "dead")
    /\ StepTrace

----------------------------------------------------------------------------
\* Block-pool load events (thread ev.tid; 0 = startup loader)

BpContainsIfLogged ==
    /\ ThreadAt("BpContains")
    /\ BpContains(ev.tid)
    /\ (pc'[ev.tid] = "analyze") = ev.ok
    /\ StepTrace

\* state: NORMAL, NOT_FORMATTED, COMPLETE_UPGRADE, RECOVER_UPGRADE, FAIL
BpAnalyzeIfLogged ==
    /\ ThreadAt("BpAnalyze")
    /\ BpAnalyze(ev.tid)
    /\ CASE ev.state = "NOT_FORMATTED" -> pc'[ev.tid] = "fmtWrite"
         [] ev.state = "FAIL"          -> pc'[ev.tid] \in {"contains", "idle", "fail"}
         [] OTHER                      -> pc'[ev.tid] = "trans"
    /\ BpssPost
    /\ DiskPost(LocId(ev.loc))
    /\ StepTrace

BpFormatWriteIfLogged ==
    /\ ThreadAt("BpFormatWrite")
    /\ BpFormatWrite(ev.tid)
    /\ DiskPost(LocId(ev.loc))
    /\ StepTrace

\* kind: provided, rollback, rollbackFail, none
BpTransitionIfLogged ==
    /\ ThreadAt("BpTransition")
    /\ BpTransition(ev.tid)
    /\ CASE ev.kind = "provided"     -> pc'[ev.tid] = "check"
         [] ev.kind = "rollbackFail" -> pc'[ev.tid] \in {"contains", "idle", "fail"}
         [] OTHER                    -> pc'[ev.tid] = "readProps"
    /\ DiskPost(LocId(ev.loc))
    /\ StepTrace

BpReadPropsIfLogged ==
    /\ ThreadAt("BpReadProps")
    /\ BpReadProps(ev.tid)
    /\ (pc'[ev.tid] = "decide1") = ev.ok
    /\ BpssPost
    /\ StepTrace

BpDecideRegularIfLogged ==
    /\ ThreadAt("BpDecideRegular")
    /\ BpDecideRegular(ev.tid)
    /\ (pc'[ev.tid] = "check") = ev.regular
    /\ StepTrace

BpDecideUpgradeIfLogged ==
    /\ ThreadAt("BpDecideUpgrade")
    /\ BpDecideUpgrade(ev.tid)
    /\ (ptmp'[LocId(ev.loc)] # NoCT) = ev.upgrade
    /\ DiskPost(LocId(ev.loc))
    /\ StepTrace

BpUpgradeSetIfLogged ==
    /\ ThreadAt("BpUpgradeSet")
    /\ BpUpgradeSet(ev.tid)
    /\ BpssPost
    /\ StepTrace

BpUpgradeWriteIfLogged ==
    /\ ThreadAt("BpUpgradeWrite")
    /\ BpUpgradeWrite(ev.tid)
    /\ DiskPost(LocId(ev.loc))
    /\ StepTrace

\* The target check: both operands as the code read them, and the outcome.
TargetCheckIfLogged ==
    /\ ThreadAt("TargetCheck")
    /\ bpssCT = ev.bpss
    /\ NsOf(ev.tid) = ev.ns
    /\ TargetCheck(ev.tid)
    /\ targetFired' = ev.fired
    /\ StepTrace

BpWriteVersionIfLogged ==
    /\ ThreadAt("BpWriteVersion")
    /\ BpWriteVersion(ev.tid)
    /\ DiskPost(LocId(ev.loc))
    /\ StepTrace

----------------------------------------------------------------------------
\* Hot-swap events

\* conf: the new dfs.datanode.data.dir; newLocs: parseChangedVolumes'
\* newLocations in order (thread k loads newLocs[k]); ns: the nsInfos snapshot.
ReconfigureIfLogged ==
    /\ IsEvent("Reconfigure")
    /\ ReconfigureConf(Ids(ev.conf))
    /\ hsNs' = ev.ns
    /\ \A k \in DOMAIN ev.newLocs : tLoc'[k] = LocId(ev.newLocs[k])
    /\ \A k \in HsThr : (pc'[k] = "dnl") = (k \in DOMAIN ev.newLocs)
    /\ StepTrace

HsDnLevelIfLogged ==
    /\ ThreadAt("HsDnLevel")
    /\ HsDnLevel(ev.tid)
    /\ (pc'[ev.tid] = "contains") = ev.ok
    /\ BpssPost
    /\ StepTrace

HotSwapFinishIfLogged ==
    /\ IsEvent("HotSwapFinish")
    /\ HotSwapFinish
    /\ dataDirs' = Ids(ev.dataDirs)
    /\ StepTrace

----------------------------------------------------------------------------

TraceNext ==
    \/ NNStartIfLogged
    \/ NNUpgradeIfLogged
    \/ NNRollbackIfLogged
    \/ DiskReplaceIfLogged
    \/ FixtureWriteVersionIfLogged
    \/ DNStartIfLogged
    \/ DNStopIfLogged
    \/ HandshakeIfLogged
    \/ ActorRejectedIfLogged
    \/ DNLevelLoadIfLogged
    \/ DNLevelJoinIfLogged
    \/ DeferredUpgradeIfLogged
    \/ InitFinishIfLogged
    \/ BpContainsIfLogged
    \/ BpAnalyzeIfLogged
    \/ BpFormatWriteIfLogged
    \/ BpTransitionIfLogged
    \/ BpReadPropsIfLogged
    \/ BpDecideRegularIfLogged
    \/ BpDecideUpgradeIfLogged
    \/ BpUpgradeSetIfLogged
    \/ BpUpgradeWriteIfLogged
    \/ TargetCheckIfLogged
    \/ BpWriteVersionIfLogged
    \/ ReconfigureIfLogged
    \/ HsDnLevelIfLogged
    \/ HotSwapFinishIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

\* The whole trace was consumed (needs the WF in TraceSpec).
TraceMatched == <>(l > Len(TraceLog))

\* Exists-check alternative: as an INVARIANT, a violation means some behavior
\* consumed the whole trace (= success). Useful while debugging a trace.
TraceNotDone == l <= Len(TraceLog)

TraceAlias ==
    [ l        |-> l,
      len      |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN ev.name ELSE "DONE",
      evfields |-> IF l <= Len(TraceLog) THEN ev ELSE [done |-> TRUE],
      locIds   |-> TraceLocSeq,
      nnCT     |-> nnCT,
      dnUp     |-> dnUp,
      bpssCT   |-> bpssCT,
      bpNS     |-> bpNS,
      actor    |-> actor,
      ldPhase  |-> ldPhase,
      ldQ      |-> ldQ,
      ldNs     |-> ldNs,
      pc       |-> pc,
      tLoc     |-> tLoc,
      ver      |-> ver,
      prev     |-> prev,
      ptmp     |-> ptmp,
      dnVer    |-> dnVer,
      bpBad    |-> bpBad,
      target   |-> targetFired ]

=============================================================================
