-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-26 (Category A: one NDJSON file, one    *)
(* cursor `l`). Event names, fields and code locations are defined in      *)
(* instrumentation-spec.md; this module must stay in step with it.         *)
(*                                                                         *)
(* Line format (after preprocessing, instrumentation-spec.md section 1):   *)
(*   {"tag":"trace","ts":"<ns>","event":{"name":..,"nid":..,               *)
(*                                       "state":{..},"msg":{..}}}         *)
(* Every cTime is an integer rank (1 = oldest cTime of the trace, 0 =      *)
(* none); every VERSION is {"lv":<int>,"ct":<rank>}, {"lv":0,"ct":0} when  *)
(* the file or directory is absent.                                        *)
(*                                                                         *)
(* The first event is "Init": the storage state when the traced segment    *)
(* starts, with every node down. "Setup" events are test-fixture writes    *)
(* (UpgradeUtilities helpers in the workload test): they replace the       *)
(* on-disk state of nodes that are down, and must agree with nodes that    *)
(* are up. Every other event is one base-spec action.                      *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

\* Trace file: ../traces/<name>.ndjson by default; JSON=<path> selects another.
JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                 /\ x.tag = "trace"
                                 /\ "event" \in DOMAIN x))

\* Checks on the first event are ASSUMEs, so a bad Init stops TLC instead of
\* leaving zero initial states (which TLC would report as "No error").
ASSUME Len(TraceLog) > 0
InitEv == TraceLog[1].event
ASSUME InitEv.name = "Init"
ASSUME InitEv.state.nn.up = FALSE
ASSUME Len(InitEv.state.dns) > 0
ASSUME InitEv.state.maxCT \in Nat \ {0}

\* Model constants taken from the trace (Trace.cfg substitutes them).
TraceDN        == {InitEv.state.dns[i].nid : i \in DOMAIN InitEv.state.dns}
TraceNumVols   == Len(InitEv.state.dns[1].vols)
TraceMaxCT     == InitEv.state.maxCT
TraceTolerated == InitEv.state.dns[1].tolerated
TraceSwLV      == InitEv.state.dns[1].swLV

ASSUME \A i \in DOMAIN InitEv.state.dns :
          /\ Len(InitEv.state.dns[i].vols) = TraceNumVols
          /\ InitEv.state.dns[i].swLV = TraceSwLV
          /\ InitEv.state.dns[i].tolerated = TraceTolerated

DnIdx(d) == CHOOSE i \in DOMAIN InitEv.state.dns : InitEv.state.dns[i].nid = d
AsVer(j) == [lv |-> j.lv, ct |-> j.ct]
ToSet(s) == {s[i] : i \in DOMAIN s}

-----------------------------------------------------------------------------
VARIABLE l          \* index of the next trace event to match

traceVars == <<vars, l>>

\* The Init event is the initial state; matching starts at event 2.
TraceInit ==
    /\ l = 2
    /\ nnUp = FALSE
    /\ nnCur = InitEv.state.nn.cur
    /\ nnPrev = InitEv.state.nn.prev
    /\ nnHist = {InitEv.state.nn.cur, InitEv.state.nn.prev} \ {NoCT}
    /\ dnPc = [d \in DN |-> "down"]
    /\ dnOpt = [d \in DN |-> "REGULAR"]
    /\ dnNs = [d \in DN |-> NoCT]
    /\ dnPending = [d \in DN |-> <<>>]
    /\ dnCont = [d \in DN |-> {}]
    /\ dnRegCT = [d \in DN |-> NoCT]
    /\ dnSwLV = [d \in DN |-> InitEv.state.dns[DnIdx(d)].swLV]
    /\ volCur = [d \in DN |-> [v \in Vol |->
                   AsVer(InitEv.state.dns[DnIdx(d)].vols[v].cur)]]
    /\ volPrev = [d \in DN |-> [v \in Vol |->
                   AsVer(InitEv.state.dns[DnIdx(d)].vols[v].prev)]]
    /\ volTmp = [d \in DN |-> [v \in Vol |-> NoVer]]
    /\ volOnline = [d \in DN |-> [v \in Vol |->
                     InitEv.state.dns[DnIdx(d)].vols[v].online]]
    /\ volBpFault = [d \in DN |-> [v \in Vol |-> FALSE]]
    /\ volLoad = [d \in DN |-> [v \in Vol |-> "none"]]
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(* Event access *)

Ev == TraceLog[l].event

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ TraceLog[l].event.name = name

\* A DataNode event from a DataNode the model knows.
IsDNEvent(name) ==
    /\ IsEvent(name)
    /\ Ev.nid \in DN

Advance == l' = l + 1

-----------------------------------------------------------------------------
(* Post-state checks (instrumentation-spec.md section 2 lists the fields) *)

\* NameNode storage after the step.
NNMatches ==
    /\ nnCur' = Ev.state.cur
    /\ nnPrev' = Ev.state.prev

\* Volume v of DataNode d after the step equals the snapshot j
\* (on-disk current / previous / previous.tmp VERSION and load state).
VolMatches(d, v, j) ==
    /\ volCur'[d][v] = AsVer(j.cur)
    /\ volPrev'[d][v] = AsVer(j.prev)
    /\ volTmp'[d][v] = AsVer(j.tmp)
    /\ volLoad'[d][v] = j.load

\* Every volume of d, from the event's "vols" array (config order).
AllVolsMatch(d) == \A v \in Vol : VolMatches(d, v, Ev.state.vols[v])

\* On-disk state only (events where the process is gone or "load" is not
\* captured).
DiskMatches(d) ==
    \A v \in Vol :
        /\ volCur'[d][v] = AsVer(Ev.state.vols[v].cur)
        /\ volPrev'[d][v] = AsVer(Ev.state.vols[v].prev)
        /\ volTmp'[d][v] = AsVer(Ev.state.vols[v].tmp)

\* The DataNode's handshake nsInfo cTime and its shared BPSS cTime.
MemMatches(d) ==
    /\ dnNs'[d] = Ev.state.ns
    /\ dnRegCT'[d] = Ev.state.regCT

-----------------------------------------------------------------------------
(* Test fixture *)

SetupIdx(d) == CHOOSE i \in DOMAIN Ev.state.dns : Ev.state.dns[i].nid = d
SetupVol(d, v) == Ev.state.dns[SetupIdx(d)].vols[v]

\* UpgradeUtilities.create*Dirs / create*VersionFile / createEmptyDirs and
\* other fixture writes (TestDFSRollback): not a system action. It replaces
\* the storage of nodes that are down; a node that is up must already hold
\* exactly that state. The NameNode model has one storage dir, so all name
\* dirs must agree ("agree").
TraceSetup ==
    /\ IsEvent("Setup")
    /\ Ev.state.nn.agree = TRUE
    /\ \A d \in DN : \E i \in DOMAIN Ev.state.dns : Ev.state.dns[i].nid = d
    /\ IF nnUp
       THEN /\ nnCur = Ev.state.nn.cur
            /\ nnPrev = Ev.state.nn.prev
            /\ UNCHANGED <<nnCur, nnPrev, nnHist>>
       ELSE /\ nnCur' = Ev.state.nn.cur
            /\ nnPrev' = Ev.state.nn.prev
            /\ nnHist' = nnHist \cup ({Ev.state.nn.cur, Ev.state.nn.prev} \ {NoCT})
    /\ \A d \in DN :
         IF dnPc[d] = "down" THEN TRUE
         ELSE \A v \in Vol : /\ volCur[d][v] = AsVer(SetupVol(d, v).cur)
                             /\ volPrev[d][v] = AsVer(SetupVol(d, v).prev)
    /\ volCur' = [d \in DN |-> IF dnPc[d] = "down"
                                THEN [v \in Vol |-> AsVer(SetupVol(d, v).cur)]
                                ELSE volCur[d]]
    /\ volPrev' = [d \in DN |-> IF dnPc[d] = "down"
                                 THEN [v \in Vol |-> AsVer(SetupVol(d, v).prev)]
                                 ELSE volPrev[d]]
    /\ UNCHANGED <<nnUp, dnVars, volTmp, volOnline, volBpFault, volLoad, targetFired>>
    /\ Advance

-----------------------------------------------------------------------------
(* NameNode events *)

TraceNNFormat ==
    /\ IsEvent("NNFormat")
    /\ NNFormat(Ev.state.cur)
    /\ NNMatches
    /\ Advance

TraceNNStart ==
    /\ IsEvent("NNStart")
    /\ NNStart
    /\ NNMatches
    /\ Advance

TraceNNStop ==
    /\ IsEvent("NNStop")
    /\ NNStop
    /\ Advance

TraceNNUpgrade ==
    /\ IsEvent("NNUpgrade")
    /\ NNUpgrade(Ev.state.cur)
    /\ NNMatches
    /\ Advance

TraceNNRollback ==
    /\ IsEvent("NNRollback")
    /\ NNRollback
    /\ NNMatches
    /\ Advance

\* finalizeUpgrade also runs (as a no-op) on an already finalized NameNode.
TraceNNFinalize ==
    /\ IsEvent("NNFinalize")
    /\ IF nnPrev = NoCT
       THEN /\ nnUp
            /\ UNCHANGED vars
       ELSE NNFinalize
    /\ NNMatches
    /\ Advance

-----------------------------------------------------------------------------
(* DataNode events *)

TraceDNStart ==
    /\ IsDNEvent("DNStart")
    /\ DNStart(Ev.nid, Ev.msg.opt)
    /\ dnPending'[Ev.nid] = Ev.msg.dirs     \* the checker's surviving dataDirs
    /\ Advance

\* Emitted after loadDataStorage (DS:389-390), before the shared BPSS exists,
\* so only nsInfo is compared here; later events compare its cTime.
\* msg.loaded = the locations whose DN-level dir loaded.
TraceDNHandshake ==
    /\ IsDNEvent("DNHandshake")
    /\ DNHandshake(Ev.nid, ToSet(Ev.msg.loaded))
    /\ dnNs'[Ev.nid] = Ev.state.ns
    /\ AllVolsMatch(Ev.nid)
    /\ Advance

TraceTargetCheck ==
    /\ IsDNEvent("TargetCheck")
    /\ TargetCheck(Ev.nid, Ev.msg.v)
    /\ TargetOutcome(Ev.nid, Ev.msg.v) = Ev.msg.outcome
    /\ MemMatches(Ev.nid)
    /\ AllVolsMatch(Ev.nid)
    /\ Advance

TraceDNLoadVolume ==
    /\ IsDNEvent("DNLoadVolume")
    /\ DNLoadVolume(Ev.nid, Ev.msg.v)
    /\ LoadOutcome(Ev.nid, Ev.msg.v) = Ev.msg.outcome
    /\ MemMatches(Ev.nid)
    /\ AllVolsMatch(Ev.nid)
    /\ Advance

\* Continuations run in parallel executor threads, so only the event's own
\* volume is compared; every continuation writes the same shared cTime.
TraceDNUpgradeContinuation ==
    /\ IsDNEvent("DNUpgradeContinuation")
    /\ DNUpgradeContinuation(Ev.nid, Ev.msg.v)
    /\ dnRegCT'[Ev.nid] = Ev.state.regCT
    /\ VolMatches(Ev.nid, Ev.msg.v, Ev.state.vol)
    /\ Advance

TraceDNInitDone ==
    /\ IsDNEvent("DNInitDone")
    /\ DNInitDone(Ev.nid)
    /\ (dnPc'[Ev.nid] = "registering") = Ev.msg.ok
    /\ DiskMatches(Ev.nid)
    /\ Advance

\* The registration the NameNode returned carries the shared BPSS cTime.
TraceDNRegister ==
    /\ IsDNEvent("DNRegister")
    /\ dnRegCT[Ev.nid] = Ev.msg.regCT
    /\ DNRegister(Ev.nid)
    /\ Advance

TraceDNReRegister ==
    /\ IsDNEvent("DNReRegister")
    /\ dnRegCT[Ev.nid] = Ev.msg.regCT
    /\ DNReRegister(Ev.nid)
    /\ Advance

TraceDNFinalize ==
    /\ IsDNEvent("DNFinalize")
    /\ DNFinalize(Ev.nid)
    /\ DiskMatches(Ev.nid)
    /\ Advance

\* DataNode.shutdown(). If the model's DataNode already ended (BP init failed
\* or registration rejected), the real process may still exist (MiniDFSCluster
\* keeps the object); its block-pool service must then be dead.
TraceDNStop ==
    /\ IsDNEvent("DNStop")
    /\ IF dnPc[Ev.nid] = "down"
       THEN /\ Ev.msg.alive = FALSE
            /\ UNCHANGED vars
       ELSE /\ Ev.msg.alive = TRUE
            /\ DNStop(Ev.nid)
    /\ DiskMatches(Ev.nid)
    /\ Advance

\* Hot-swap add of one volume (only that volume is compared: refreshVolumes
\* adds volumes in parallel threads, DN:1312-1329).
TraceHotSwapAdd ==
    /\ IsDNEvent("HotSwapAdd")
    /\ HotSwapAdd(Ev.nid, Ev.msg.v)
    /\ LoadOutcome(Ev.nid, Ev.msg.v) = Ev.msg.outcome
    /\ dnRegCT'[Ev.nid] = Ev.state.regCT
    /\ VolMatches(Ev.nid, Ev.msg.v, Ev.state.vol)
    /\ Advance

-----------------------------------------------------------------------------
\* No silent actions: every modeled step has its own event.
TraceNext ==
    \/ TraceSetup
    \/ TraceNNFormat
    \/ TraceNNStart
    \/ TraceNNStop
    \/ TraceNNUpgrade
    \/ TraceNNRollback
    \/ TraceNNFinalize
    \/ TraceDNStart
    \/ TraceDNHandshake
    \/ TraceTargetCheck
    \/ TraceDNLoadVolume
    \/ TraceDNUpgradeContinuation
    \/ TraceDNInitDone
    \/ TraceDNRegister
    \/ TraceDNReRegister
    \/ TraceDNFinalize
    \/ TraceDNStop
    \/ TraceHotSwapAdd
    \/ /\ l > Len(TraceLog)
       /\ UNCHANGED traceVars

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

\* Every event was matched.
TraceMatched == <>(l > Len(TraceLog))

\* For debugging (ALIAS TraceAlias in Trace.cfg): the event about to be matched.
TraceAlias ==
    [l |-> l,
     next |-> IF l <= Len(TraceLog) THEN TraceLog[l].event ELSE "END",
     nnUp |-> nnUp, nnCur |-> nnCur, nnPrev |-> nnPrev,
     dnPc |-> dnPc, dnOpt |-> dnOpt, dnNs |-> dnNs, dnPending |-> dnPending,
     dnCont |-> dnCont, dnRegCT |-> dnRegCT,
     volCur |-> volCur, volPrev |-> volPrev, volTmp |-> volTmp,
     volLoad |-> volLoad, targetFired |-> targetFired]

=============================================================================
