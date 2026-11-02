-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-37 (Category A: one linear NDJSON       *)
(* trace, cursor l). Event schema: instrumentation-spec.md Section 1.      *)
(*                                                                         *)
(* Every event maps to exactly one base action, with its parameters taken  *)
(* from the event, followed by a post-state check of the fields the event  *)
(* carries. There are no silent actions: the harness emits every step,     *)
(* including the test fixtures (UpgradeUtilities), which are base actions  *)
(* outside Next.                                                           *)
(*                                                                         *)
(* cTime fields hold dense, order-preserving ranks written by the trace    *)
(* post-processor (instrumentation-spec.md Section 3.2); -1 = no VERSION.  *)
(* Location ids are the index i of .../data<i>; NameNode ids are model ids *)
(* ("n1"); the constants in Trace.cfg are literals (no trace-derived       *)
(* constant overrides).                                                    *)
(*                                                                         *)
(* TargetSafe is NOT checked here: the workload's own fixture ("DataNode   *)
(* rollback with newer fsscTime in previous", TestDFSRollback L269-295)    *)
(* fires the target by design (brief Section 1, T-1). The TargetCheck      *)
(* wrapper instead checks that the guard's outcome in the model equals the *)
(* outcome the code took, from the operands the code read.                 *)
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
ASSUME TraceLog[1].event.name = "Init"

----------------------------------------------------------------------------
\* JSON -> model values

JVer(j)   == [lv |-> j.lv, ct |-> j.ct, cid |-> j.cid]
\* A NameNode VERSION: clusterID presence is irrelevant on that side.
JNnVer(j) == IF j.lv = "none" THEN NoVer ELSE [lv |-> j.lv, ct |-> j.ct, cid |-> TRUE]
JBp(j)    == [cur |-> j.cur, prev |-> j.prev]
\* Traces have one namespace: the tree's block-pool subtree is that pool's.
JTree(j)  == [ver |-> JVer(j.ver), bp |-> [s \in Ns |-> JBp(j.bp)]]
JTmp(j)   == [kind |-> j.kind, tree |-> JTree(j.tree)]

----------------------------------------------------------------------------
\* Cursor

VARIABLE l

logline == TraceLog[l]
ev  == logline.event
msg == ev.msg
st  == ev.state

IsEvent(name) == /\ l <= Len(TraceLog)
                 /\ ev.name = name

StepTrace == l' = l + 1

----------------------------------------------------------------------------
\* Initial state: the first event ("Init") lists the on-disk state of every
\* NameNode and DataNode location when tracing starts (after
\* UpgradeUtilities.initialize() for the workload; after unpacking an image
\* for a variant). Every process is down.

InitEv == TraceLog[1].event

InitNn(n) ==
    LET xs == {x \in Range(InitEv.state.nn) : x.id = n}
    IN IF xs = {} THEN [cur |-> NoVer, prev |-> NoVer]
       ELSE LET x == CHOOSE y \in xs : TRUE
            IN [cur |-> JNnVer(x.cur), prev |-> JNnVer(x.prev)]

InitDir(d) ==
    LET xs == {x \in Range(InitEv.state.dirs) : x.id = d}
    IN IF xs = {} THEN [cur |-> EmptyTree, prev |-> EmptyTree, tmp |-> NoTmp]
       ELSE LET x == CHOOSE y \in xs : TRUE
            IN [cur |-> JTree(x.cur), prev |-> JTree(x.prev), tmp |-> JTmp(x.tmp)]

TraceInit ==
    /\ l = 2
    /\ nnCur = [n \in NN |-> InitNn(n).cur]
    /\ nnPrev = [n \in NN |-> InitNn(n).prev]
    /\ nnUp = [n \in NN |-> FALSE]
    /\ clock = 0
    /\ served = [s \in Ns |-> {}]
    /\ dCur = [d \in Dir |-> InitDir(d).cur]
    /\ dPrev = [d \in Dir |-> InitDir(d).prev]
    /\ dTmp = [d \in Dir |-> InitDir(d).tmp]
    /\ dnUp = FALSE
    /\ startOpt = "REGULAR"
    /\ dnConf = <<>>
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
\* Post-state checks

\* The three DataNode-level trees of the event's location after the step.
DiskPost(d) ==
    /\ dCur'[d] = JTree(st.cur)
    /\ dPrev'[d] = JTree(st.prev)
    /\ dTmp'[d] = JTmp(st.tmp)

NnPost(n) ==
    /\ nnCur'[n] = JNnVer(st.cur)
    /\ nnPrev'[n] = JNnVer(st.prev)

\* The loader is at the event's location.
AtDir == ld.busy /\ ld.d = msg.dir

----------------------------------------------------------------------------
\* NameNode events (nid = NameNode id)

NnStartIfLogged ==
    /\ IsEvent("NnStart")
    /\ NnStart(ev.nid)
    /\ NnPost(ev.nid)
    /\ StepTrace

NnStopIfLogged ==
    /\ IsEvent("NnStop")
    /\ NnStop(ev.nid)
    /\ StepTrace

NnFormatIfLogged ==
    /\ IsEvent("NnFormat")
    /\ NnFormat(ev.nid, JNnVer(st.cur).ct)
    /\ nnCur'[ev.nid] = JNnVer(st.cur)
    /\ StepTrace

NnUpgradeIfLogged ==
    /\ IsEvent("NnUpgrade")
    /\ NnUpgrade(ev.nid, JNnVer(st.cur).ct, msg.reboot)
    /\ NnPost(ev.nid)
    /\ StepTrace

NnRollbackIfLogged ==
    /\ IsEvent("NnRollback")
    /\ CanRollBack(ev.nid) = msg.ok
    /\ NnRollback(ev.nid, msg.reboot)
    /\ NnPost(ev.nid)
    /\ StepTrace

NnFinalizeIfLogged ==
    /\ IsEvent("NnFinalize")
    /\ NnFinalize(ev.nid)
    /\ NnPost(ev.nid)
    /\ StepTrace

NnBootstrapStandbyIfLogged ==
    /\ IsEvent("NnBootstrapStandby")
    /\ NnBootstrapStandby(ev.nid, msg.from)
    /\ NnPost(ev.nid)
    /\ StepTrace

----------------------------------------------------------------------------
\* Test fixtures (UpgradeUtilities; trace only)

FixtureNnDirIfLogged ==
    /\ IsEvent("FixtureNnDir")
    /\ FixtureNnDir(ev.nid, msg.which, JNnVer(msg.ver))
    /\ StepTrace

FixtureNnClearIfLogged ==
    /\ IsEvent("FixtureNnClear")
    /\ FixtureNnClear(ev.nid)
    /\ StepTrace

FixtureDnTreeIfLogged ==
    /\ IsEvent("FixtureDnTree")
    /\ FixtureDnTree(msg.dir, msg.which, JTree(msg.tree))
    /\ StepTrace

FixtureDnVersionIfLogged ==
    /\ IsEvent("FixtureDnVersion")
    /\ FixtureDnVersion(msg.dir, msg.which, JVer(msg.ver), msg.bpct)
    /\ StepTrace

FixtureBpDirIfLogged ==
    /\ IsEvent("FixtureBpDir")
    /\ FixtureBpDir(msg.dir, msg.which, msg.ct)
    /\ StepTrace

FixtureDnClearIfLogged ==
    /\ IsEvent("FixtureDnClear")
    /\ FixtureDnClear(msg.dir)
    /\ StepTrace

----------------------------------------------------------------------------
\* DataNode process and actors

DnStartIfLogged ==
    /\ IsEvent("DnStart")
    /\ DnStart(msg.opt, msg.conf)
    /\ StepTrace

DnStopIfLogged ==
    /\ IsEvent("DnStop")
    /\ DnStop
    /\ StepTrace

HandshakeIfLogged ==
    /\ IsEvent("Handshake")
    /\ Handshake(msg.nn)
    /\ nsInfoCt'[msg.nn] = msg.ct
    /\ StepTrace

InitStartIfLogged ==
    /\ IsEvent("InitStart")
    /\ InitStart(msg.nn)
    /\ ld'.ct = msg.ct
    /\ StepTrace

HsJoinIfLogged ==
    /\ IsEvent("HsJoin")
    /\ HsJoin(msg.nn)
    /\ StepTrace

ActorRetryOrExitIfLogged ==
    /\ IsEvent("ActorRetryOrExit")
    /\ ActorRetryOrExit(msg.nn)
    /\ (aState'[msg.nn] = "conn") = msg.retry
    /\ StepTrace

----------------------------------------------------------------------------
\* DataNode-level storage load

\* outcome: "used" (already loaded) or the analyzeStorage result:
\* "fail", "normal", "format", "completeUpgrade", "recoverUpgrade",
\* "completeRollback", "recoverRollback".
DnAnalyzeIfLogged ==
    /\ IsEvent("DnAnalyze")
    /\ ld.busy /\ ld.d = 0 /\ ld.q # <<>>
    /\ Head(ld.q) = msg.dir
    /\ IF msg.outcome = "used"
       THEN msg.dir \in dsLoaded
       ELSE msg.dir \notin dsLoaded /\ AnalyzeState(msg.dir) = msg.outcome
    /\ DnAnalyze
    /\ DiskPost(msg.dir)
    /\ StepTrace

DnRollbackNoPreviousIfLogged ==
    /\ IsEvent("DnRollbackNoPrevious")
    /\ AtDir
    /\ DnRollbackNoPrevious
    /\ (ld'.pc = "read") = msg.ok
    /\ dCur'[msg.dir].ver = JVer(st.cur)
    /\ StepTrace

\* The target: both operands as the code read them, and the branch it took.
\* outcome: "readFail" (previous/VERSION rejected before the guard),
\* "fired" (throw at DS:942), "pass" (rollback continues).
TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ AtDir
    /\ dPrev[msg.dir].ver.ct = msg.prevCt
    /\ ld.ct = msg.nsCt
    /\ LET p == dPrev[msg.dir].ver IN
       CASE msg.outcome = "readFail" -> ReadFails(p)
         [] msg.outcome = "fired"    -> ~ReadFails(p) /\ TargetGuardFails(p, ld.ct)
         [] msg.outcome = "pass"     -> ~ReadFails(p) /\ ~TargetGuardFails(p, ld.ct)
         [] OTHER                    -> FALSE
    /\ TargetCheck
    /\ StepTrace

DnRollbackRenameCurrentIfLogged ==
    /\ IsEvent("DnRollbackRenameCurrent")
    /\ AtDir
    /\ DnRollbackRenameCurrent
    /\ DiskPost(msg.dir)
    /\ StepTrace

DnRollbackRenamePreviousIfLogged ==
    /\ IsEvent("DnRollbackRenamePrevious")
    /\ AtDir
    /\ DnRollbackRenamePrevious
    /\ DiskPost(msg.dir)
    /\ StepTrace

DnRollbackDeleteTmpIfLogged ==
    /\ IsEvent("DnRollbackDeleteTmp")
    /\ AtDir
    /\ DnRollbackDeleteTmp
    /\ DiskPost(msg.dir)
    /\ StepTrace

\* outcome: "regular" (loaded), "preFed" (pre-federation upgrade follows),
\* "fail".
DnReadPropertiesIfLogged ==
    /\ IsEvent("DnReadProperties")
    /\ AtDir
    /\ DnReadProperties
    /\ CASE msg.outcome = "regular" -> msg.dir \in dsLoaded'
         [] msg.outcome = "preFed"  -> ld'.pc \in {"pfDel", "pfRen"}
         [] msg.outcome = "fail"    -> ld'.d = 0 /\ msg.dir \notin dsLoaded'
         [] OTHER                   -> FALSE
    /\ dCur'[msg.dir].ver = JVer(st.cur)
    /\ StepTrace

DnPreFedDeletePreviousIfLogged ==
    /\ IsEvent("DnPreFedDeletePrevious")
    /\ AtDir
    /\ DnPreFedDeletePrevious
    /\ DiskPost(msg.dir)
    /\ StepTrace

DnPreFedRenameIfLogged ==
    /\ IsEvent("DnPreFedRename")
    /\ AtDir
    /\ DnPreFedRename
    /\ DiskPost(msg.dir)
    /\ StepTrace

CbUpgradeFieldsIfLogged ==
    /\ IsEvent("CbUpgradeFields")
    /\ CbUpgradeFields(msg.dir)
    /\ StepTrace

CbWriteVersionIfLogged ==
    /\ IsEvent("CbWriteVersion")
    /\ CbWriteVersion(msg.dir)
    /\ dCur'[msg.dir].ver = JVer(st.cur)
    /\ StepTrace

CbRenamePrevTmpIfLogged ==
    /\ IsEvent("CbRenamePrevTmp")
    /\ CbRenamePrevTmp(msg.dir)
    /\ DiskPost(msg.dir)
    /\ StepTrace

DnAddUpgradedIfLogged ==
    /\ IsEvent("DnAddUpgraded")
    /\ DnAddUpgraded(msg.dir)
    /\ StepTrace

----------------------------------------------------------------------------
\* Block-pool level, end of the load, initialization

BpLoadIfLogged ==
    /\ IsEvent("BpLoad")
    /\ BpLoad(msg.dir)
    /\ (msg.dir \in bpLoaded'[ld.ns] \ bpLoaded[ld.ns]) = msg.ok
    /\ dCur'[msg.dir].bp[ld.ns] = JBp(st.bp)
    /\ StepTrace

DnLoadDoneIfLogged ==
    /\ IsEvent("DnLoadDone")
    /\ ld.bpOk = msg.ok
    /\ DnLoadDone
    /\ StepTrace

InitFinishIfLogged ==
    /\ IsEvent("InitFinish")
    /\ InitFinish(msg.nn)
    /\ (aState'[msg.nn] = "run") = msg.ok
    /\ StepTrace

\* level: "dn" (DataNode-level previous finalized) or "bp" (block pool).
DnFinalizeDirIfLogged ==
    /\ IsEvent("DnFinalizeDir")
    /\ (dPrev[msg.dir].ver # NoVer) = (msg.level = "dn")
    /\ DnFinalizeDir(msg.nn, msg.dir)
    /\ DiskPost(msg.dir)
    /\ StepTrace

----------------------------------------------------------------------------

TraceNext ==
    \/ NnStartIfLogged
    \/ NnStopIfLogged
    \/ NnFormatIfLogged
    \/ NnUpgradeIfLogged
    \/ NnRollbackIfLogged
    \/ NnFinalizeIfLogged
    \/ NnBootstrapStandbyIfLogged
    \/ FixtureNnDirIfLogged
    \/ FixtureNnClearIfLogged
    \/ FixtureDnTreeIfLogged
    \/ FixtureDnVersionIfLogged
    \/ FixtureBpDirIfLogged
    \/ FixtureDnClearIfLogged
    \/ DnStartIfLogged
    \/ DnStopIfLogged
    \/ HandshakeIfLogged
    \/ InitStartIfLogged
    \/ HsJoinIfLogged
    \/ ActorRetryOrExitIfLogged
    \/ DnAnalyzeIfLogged
    \/ DnRollbackNoPreviousIfLogged
    \/ TargetCheckIfLogged
    \/ DnRollbackRenameCurrentIfLogged
    \/ DnRollbackRenamePreviousIfLogged
    \/ DnRollbackDeleteTmpIfLogged
    \/ DnReadPropertiesIfLogged
    \/ DnPreFedDeletePreviousIfLogged
    \/ DnPreFedRenameIfLogged
    \/ CbUpgradeFieldsIfLogged
    \/ CbWriteVersionIfLogged
    \/ CbRenamePrevTmpIfLogged
    \/ DnAddUpgradedIfLogged
    \/ BpLoadIfLogged
    \/ DnLoadDoneIfLogged
    \/ InitFinishIfLogged
    \/ DnFinalizeDirIfLogged

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
      evmsg    |-> IF l <= Len(TraceLog) THEN msg ELSE [done |-> TRUE],
      nnCur    |-> nnCur,
      nnPrev   |-> nnPrev,
      nnUp     |-> nnUp,
      dnUp     |-> dnUp,
      startOpt |-> startOpt,
      aState   |-> aState,
      nsInfoCt |-> nsInfoCt,
      ld       |-> ld,
      cb       |-> cb,
      sh       |-> sh,
      dCur     |-> dCur,
      dPrev    |-> dPrev,
      dTmp     |-> dTmp,
      dsLoaded |-> dsLoaded,
      bpLoaded |-> bpLoaded,
      target   |-> targetFired ]

=============================================================================
