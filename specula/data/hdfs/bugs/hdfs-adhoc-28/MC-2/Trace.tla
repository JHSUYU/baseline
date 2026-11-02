-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-28 (Category A: one linear NDJSON       *)
(* trace, cursor l).                                                       *)
(*                                                                         *)
(* The workload (TestBlockRecovery2#testRecoveryTimeout ->                 *)
(* TestBlockRecovery.testRecoveryWithDatanodeDelayed) runs one NameNode    *)
(* and two DataNodes in one JVM. Events come from many threads (actors,    *)
(* command threads, recovery daemons, NameNode handlers, the test thread); *)
(* the harness writes each event while holding one global trace lock,      *)
(* inside the critical section of the step it reports                      *)
(* (instrumentation-spec.md, Section 3.1), so the file order is a valid    *)
(* linearization of the modeled steps.                                     *)
(*                                                                         *)
(* Every event maps to exactly one base action with its parameters taken   *)
(* from the event (DataNode name, BPOS slot, daemon id); there are no      *)
(* silent actions. Each wrapper calls the base action unchanged and then   *)
(* checks the fields the event carries.                                    *)
(*                                                                         *)
(* Field conventions (instrumentation-spec.md, Section 1):                 *)
(*   dn    "dn0", "dn1", ...: MiniDFSCluster DataNode index                *)
(*   slot  1 = the DataNode's startup BPOS, 2 = one a refresh created      *)
(*   rid   daemon id = delivery number of the recovery command (1, 2, ..)  *)
(*   att   rank of the recovery id (new generation stamp) among the        *)
(*         NameNode's recovery ids in this trace (1 = first)               *)
(*   entry bpByBlockPoolId.get(P) as a slot number, 0 = no entry           *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC, FiniteSets, Naturals

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

SetMax(S) == CHOOSE x \in S : \A y \in S : y <= x

EvIdx(f) == {k \in 1..Len(TraceLog) : f \in DOMAIN TraceLog[k].event}

\* Overrides for the base constants (Trace.cfg).
TraceDN == TLCEval({TraceLog[k].event.dn : k \in EvIdx("dn")})
TraceMaxSlot == TLCEval(SetMax({1} \cup {TraceLog[k].event.slot : k \in EvIdx("slot")}))
TraceMaxAttempts ==
    TLCEval(SetMax({1} \cup {TraceLog[k].event.att : k \in EvIdx("att")}))

----------------------------------------------------------------------------
\* Cursor

VARIABLE l

logline == TraceLog[l]
ev == logline.event

IsEvent(name) == /\ l <= Len(TraceLog)
                 /\ ev.name = name

StepTrace == l' = l + 1

\* The BPOS (= actor = command thread) an event names.
EvB == <<ev.dn, ev.slot>>

ToSet(s) == {s[k] : k \in DOMAIN s}

----------------------------------------------------------------------------
\* Initial state: the trace starts at the MiniDFSCluster build, after both
\* DataNodes ran their startup refreshNamenodes (DNJ:1958-1959): base Init.

TraceInit ==
    /\ Init
    /\ l = 1

----------------------------------------------------------------------------
\* DataNode-wide and operator events

DnStopIfLogged ==
    /\ IsEvent("DnStop")
    /\ DnStop(ev.dn)
    /\ StepTrace

\* slots: the BPOS slots whose stop() shutDownAll called.
DnShutDownAllIfLogged ==
    /\ IsEvent("DnShutDownAll")
    /\ {k \in Slot : k \in bpmSvcs[ev.dn]} = ToSet(ev.slots)
    /\ DnShutDownAll(ev.dn)
    /\ StepTrace

RefreshNodesDisallowIfLogged ==
    /\ IsEvent("RefreshNodesDisallow")
    /\ RefreshNodesDisallow(ev.dn)
    /\ StepTrace

RefreshStartNewIfLogged ==
    /\ IsEvent("RefreshStartNew")
    /\ ev.slot = 2
    /\ RefreshStartNew(ev.dn)
    /\ StepTrace

\* stopped: Step 4 found the null nameservice and called stop().
RefreshStopOldIfLogged ==
    /\ IsEvent("RefreshStopOld")
    /\ RefreshStopOld(ev.dn)
    /\ (refreshPc'[ev.dn] = "join") = ev.stopped
    /\ StepTrace

RefreshJoinOldIfLogged ==
    /\ IsEvent("RefreshJoinOld")
    /\ RefreshJoinOld(ev.dn)
    /\ StepTrace

----------------------------------------------------------------------------
\* Actor handshake events

ActorVersionRequestIfLogged ==
    /\ IsEvent("ActorVersionRequest")
    /\ ActorVersionRequest(EvB)
    /\ (actPc'[EvB] = "hsNs") = ev.ok
    /\ StepTrace

\* init: setNamespaceInfo returned null, so initBlockPool runs;
\* active: bpServiceToActive is this actor after L386-390.
ActorVerifyNsInfoIfLogged ==
    /\ IsEvent("ActorVerifyNsInfo")
    /\ ActorVerifyNsInfo(EvB)
    /\ (actPc'[EvB] = "hsAdd") = ev.init
    /\ bpActive'[EvB] = ev.active
    /\ StepTrace

\* entry: the map entry right after addBlockPool.
HsAddBlockPoolIfLogged ==
    /\ IsEvent("HsAddBlockPool")
    /\ HsAddBlockPool(EvB)
    /\ bpmByPool'[ev.dn] = ev.entry
    /\ StepTrace

\* ok: initStorage and data.addBlockPool succeeded; cause (when not ok):
\* "interrupted" (ClosedByInterruptException) or "loaded" (BPSS:221-225).
HsInitStorageIfLogged ==
    /\ IsEvent("HsInitStorage")
    /\ HsInitStorage(EvB)
    /\ (actPc'[EvB] = "reg") = ev.ok
    /\ ev.ok => poolLoaded'[ev.dn]
    /\ ~ev.ok => CASE ev.cause = "interrupted" -> stopped[EvB]
                   [] ev.cause = "loaded"      -> poolLoaded[ev.dn]
                   [] OTHER                    -> FALSE
    /\ StepTrace

\* outcome: "ok" | "rejected" (RemoteException, retry) | "shutdown"
ActorRegisterIfLogged ==
    /\ IsEvent("ActorRegister")
    /\ ActorRegister(EvB)
    /\ actPc'[EvB] = CASE ev.outcome = "ok"       -> "loop"
                       [] ev.outcome = "rejected" -> "conn"
                       [] OTHER                   -> "cleanUp"
    /\ (ev.outcome = "ok") = bpReg'[EvB]
    /\ StepTrace

----------------------------------------------------------------------------
\* Actor offerService and exit events

\* run: the value of shouldRun() at L686.
ActorLoopIfLogged ==
    /\ IsEvent("ActorLoop")
    /\ ActorLoop(EvB)
    /\ (actPc'[EvB] = "hb") = ev.run
    /\ StepTrace

\* outcome: "skip" (no heartbeat due), "failed" (IOException, e.g. an
\* interrupted RPC), "noPool" (storage reports failed), "rejected"
\* (DisallowedDatanodeException), "ok" (a response; cmd present iff it
\* carried a BlockRecoveryCommand).
ActorHeartbeatIfLogged ==
    /\ IsEvent("ActorHeartbeat")
    /\ ActorHeartbeat(EvB)
    /\ CASE ev.outcome \in {"skip", "failed"} ->
              /\ actPc'[EvB] = "loop"
              /\ UNCHANGED <<cptQ, nnRecQ, nnDeliv>>
         [] ev.outcome = "noPool" ->
              /\ ~poolLoaded[ev.dn]
              /\ actPc'[EvB] = "loop"
              /\ UNCHANGED <<cptQ, nnRecQ, nnDeliv>>
         [] ev.outcome = "rejected" ->
              /\ nnBanned[ev.dn]
              /\ actPc'[EvB] = "cleanUp"
         [] ev.outcome = "ok" ->
              /\ ~stopped[EvB] /\ poolLoaded[ev.dn] /\ ~nnBanned[ev.dn]
              /\ actPc'[EvB] = "loop"
              /\ nnRecQ'[ev.dn] = FALSE
              /\ IF "cmd" \in DOMAIN ev
                 THEN /\ Len(cptQ'[EvB]) = Len(cptQ[EvB]) + 1
                      /\ cptQ'[EvB][Len(cptQ'[EvB])] =
                           [rid |-> ev.cmd.rid, att |-> ev.cmd.att,
                            nlocs |-> ev.cmd.nlocs]
                 ELSE cptQ'[EvB] = cptQ[EvB]
         [] OTHER -> FALSE
    /\ StepTrace

ActorCleanUpIfLogged ==
    /\ IsEvent("ActorCleanUp")
    /\ ActorCleanUp(EvB)
    /\ StepTrace

\* wasActive: bpServiceToActive was this actor (BPOS:479).
ActorShutdownActorIfLogged ==
    /\ IsEvent("ActorShutdownActor")
    /\ bpActive[EvB] = ev.wasActive
    /\ ActorShutdownActor(EvB)
    /\ StepTrace

\* entry: the map entry right after BlockPoolManager.remove.
ActorExitRemoveIfLogged ==
    /\ IsEvent("ActorExitRemove")
    /\ ActorExitRemove(EvB)
    /\ bpmByPool'[ev.dn] = ev.entry
    /\ StepTrace

\* released: hasBlockPoolId() at DNJ:2153 (the pool was released).
ActorExitReleaseIfLogged ==
    /\ IsEvent("ActorExitRelease")
    /\ bpNs[EvB] = ev.released
    /\ ActorExitRelease(EvB)
    /\ StepTrace

----------------------------------------------------------------------------
\* Command-processing-thread events

\* run: the value of shouldRun() at BPSA:1428.
CptLoopIfLogged ==
    /\ IsEvent("CptLoop")
    /\ CptLoop(EvB)
    /\ (cptPc'[EvB] = "take") = ev.run
    /\ StepTrace

CptTakeIfLogged ==
    /\ IsEvent("CptTake")
    /\ CptTake(EvB)
    /\ cptCur'[EvB].rid = ev.rid
    /\ StepTrace

CptOtherBatchIfLogged ==
    /\ IsEvent("CptOtherBatch")
    /\ CptOtherBatch(EvB)
    /\ StepTrace

CptInterruptedIfLogged ==
    /\ IsEvent("CptInterrupted")
    /\ CptInterrupted(EvB)
    /\ StepTrace

\* served: bpServices.contains(actor), the BPOS:673 assert's operand.
CptAssertIfLogged ==
    /\ IsEvent("CptAssert")
    /\ cptCur[EvB].rid = ev.rid
    /\ bpServed[EvB] = ev.served
    /\ CptAssert(EvB)
    /\ StepTrace

\* active: isActiveActor (BPOS:694).
CptReadIfLogged ==
    /\ IsEvent("CptRead")
    /\ cptCur[EvB].rid = ev.rid
    /\ CptRead(EvB)
    /\ cptSnap'[EvB] = ev.active
    /\ StepTrace

\* started: recoverBlocks started a daemon (active path).
CptDispatchIfLogged ==
    /\ IsEvent("CptDispatch")
    /\ cptCur[EvB].rid = ev.rid
    /\ CptDispatch(EvB)
    /\ (rec'[ev.rid].st = "start") = ev.started
    /\ StepTrace

----------------------------------------------------------------------------
\* Recovery-daemon events (rid = daemon id)

RecStartIfLogged ==
    /\ IsEvent("RecStart")
    /\ ev.rid \in Rec
    /\ rec[ev.rid].dn = ev.dn
    /\ RecStart(ev.rid)
    /\ StepTrace

\* The target: idx = location index (1-based), entry = the value
\* getBPOfferService returned (slot, 0 = null), outcome = "ok" | "npe" |
\* "fired".
TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ ev.rid \in Rec
    /\ rec[ev.rid].dn = ev.dn
    /\ rec[ev.rid].idx = ev.idx
    /\ bpmByPool[ev.dn] = ev.entry
    /\ TargetCheck(ev.rid)
    /\ CASE ev.outcome = "ok"    -> rec'[ev.rid].st = "rpc"
         [] ev.outcome = "npe"   -> rec'[ev.rid].st = "npe"
         [] ev.outcome = "fired" -> targetFired'
         [] OTHER                -> FALSE
    /\ StepTrace

\* outcome: "ok" | "ioe" | "rip"
RecRpcIfLogged ==
    /\ IsEvent("RecRpc")
    /\ ev.rid \in Rec
    /\ rec[ev.rid].dn = ev.dn
    /\ RecRpc(ev.rid)
    /\ CASE ev.outcome = "ok"  -> /\ rec'[ev.rid].st # "done"
                                  /\ rec'[ev.rid].err = rec[ev.rid].err
         [] ev.outcome = "ioe" -> /\ rec'[ev.rid].st # "done"
                                  /\ rec'[ev.rid].err = rec[ev.rid].err + 1
         [] ev.outcome = "rip" -> rec'[ev.rid].st = "done"
         [] OTHER              -> FALSE
    /\ StepTrace

\* outcome: "allFailed" (L169-172) | "noBpos" (the L604 throw) | "found"
\* (entry = the slot getBPOfferService returned at L602).
RecPostIfLogged ==
    /\ IsEvent("RecPost")
    /\ ev.rid \in Rec
    /\ rec[ev.rid].dn = ev.dn
    /\ RecPost(ev.rid)
    /\ CASE ev.outcome = "allFailed" -> rec[ev.rid].err = rec[ev.rid].nlocs
         [] ev.outcome = "noBpos"    -> /\ rec[ev.rid].err < rec[ev.rid].nlocs
                                        /\ bpmByPool[ev.dn] = NoSlot
         [] ev.outcome = "found"     -> /\ rec'[ev.rid].st = "active"
                                        /\ rec'[ev.rid].pb = ev.entry
         [] OTHER                    -> FALSE
    /\ StepTrace

\* outcome: "noActive" (L608-610) | "commit"
RecActiveIfLogged ==
    /\ IsEvent("RecActive")
    /\ ev.rid \in Rec
    /\ rec[ev.rid].dn = ev.dn
    /\ RecActive(ev.rid)
    /\ rec'[ev.rid].st = IF ev.outcome = "commit" THEN "commit" ELSE "done"
    /\ ev.outcome \in {"commit", "noActive"}
    /\ StepTrace

\* outcome: "accepted" (the NameNode committed the block), "rejected" (the
\* NameNode returned an error or ignored a closed file), "lost" (the call
\* never reached the NameNode).
RecCommitIfLogged ==
    /\ IsEvent("RecCommit")
    /\ ev.rid \in Rec
    /\ rec[ev.rid].dn = ev.dn
    /\ RecCommit(ev.rid)
    /\ CASE ev.outcome = "accepted" -> /\ ~nnRec.done
                                       /\ nnRec'.done
         [] ev.outcome = "rejected" -> /\ nnRec' = nnRec
                                       /\ nnRec.done \/ rec[ev.rid].att # nnRec.att
         [] ev.outcome = "lost"     -> nnRec' = nnRec
         [] OTHER                   -> FALSE
    /\ StepTrace

----------------------------------------------------------------------------
\* NameNode events (BUC.initializeBlockRecovery). primary: the DataNode the
\* block was queued at, absent when none was chosen.

NNPrimaryPost ==
    IF "primary" \in DOMAIN ev
    THEN /\ nnRecQ'[ev.primary]
         /\ ev.primary \in nnChosen'
    ELSE nnRecQ' = nnRecQ

NNStartRecoveryIfLogged ==
    /\ IsEvent("NNStartRecovery")
    /\ NNStartRecovery
    /\ nnRec'.att = ev.att
    /\ NNPrimaryPost
    /\ StepTrace

NNRetryRecoveryIfLogged ==
    /\ IsEvent("NNRetryRecovery")
    /\ NNRetryRecovery
    /\ nnRec'.att = ev.att
    /\ NNPrimaryPost
    /\ StepTrace

----------------------------------------------------------------------------

TraceNext ==
    \/ DnStopIfLogged
    \/ DnShutDownAllIfLogged
    \/ RefreshNodesDisallowIfLogged
    \/ RefreshStartNewIfLogged
    \/ RefreshStopOldIfLogged
    \/ RefreshJoinOldIfLogged
    \/ ActorVersionRequestIfLogged
    \/ ActorVerifyNsInfoIfLogged
    \/ HsAddBlockPoolIfLogged
    \/ HsInitStorageIfLogged
    \/ ActorRegisterIfLogged
    \/ ActorLoopIfLogged
    \/ ActorHeartbeatIfLogged
    \/ ActorCleanUpIfLogged
    \/ ActorShutdownActorIfLogged
    \/ ActorExitRemoveIfLogged
    \/ ActorExitReleaseIfLogged
    \/ CptLoopIfLogged
    \/ CptTakeIfLogged
    \/ CptOtherBatchIfLogged
    \/ CptInterruptedIfLogged
    \/ CptAssertIfLogged
    \/ CptReadIfLogged
    \/ CptDispatchIfLogged
    \/ RecStartIfLogged
    \/ TargetCheckIfLogged
    \/ RecRpcIfLogged
    \/ RecPostIfLogged
    \/ RecActiveIfLogged
    \/ RecCommitIfLogged
    \/ NNStartRecoveryIfLogged
    \/ NNRetryRecoveryIfLogged

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

\* The whole trace was consumed (needs the WF in TraceSpec).
TraceMatched == <>(l > Len(TraceLog))

\* Exists-check alternative: as an INVARIANT, a violation means some behavior
\* consumed the whole trace (= success). Useful while debugging a trace.
TraceNotDone == l <= Len(TraceLog)

TraceAlias ==
    [ l          |-> l,
      len        |-> Len(TraceLog),
      event      |-> IF l <= Len(TraceLog) THEN ev.name ELSE "DONE",
      evfields   |-> IF l <= Len(TraceLog) THEN ev ELSE [done |-> TRUE],
      dnPc       |-> dnPc,
      bpmByPool  |-> bpmByPool,
      bpmSvcs    |-> bpmSvcs,
      poolLoaded |-> poolLoaded,
      actPc      |-> actPc,
      actRun     |-> actRun,
      stopped    |-> stopped,
      bpActive   |-> bpActive,
      bpServed   |-> bpServed,
      bpReg      |-> bpReg,
      cptPc      |-> cptPc,
      cptQ       |-> cptQ,
      cptCur     |-> cptCur,
      rec        |-> rec,
      nnRec      |-> nnRec,
      nnChosen   |-> nnChosen,
      nnRecQ     |-> nnRecQ,
      nnDeliv    |-> nnDeliv,
      refreshPc  |-> refreshPc,
      target     |-> targetFired ]

=============================================================================
