-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base (hdfs-adhoc-29). Category A: one NDJSON file *)
(* per run, events in emission order (SpeculaTrace.emit is synchronized), *)
(* replayed with a single cursor l. Every event names the base action it  *)
(* corresponds to (instrumentation-spec.md §2); each wrapper calls that    *)
(* action with the arguments the event carries, checks the fields the     *)
(* event captured against the post-state, then advances l.                *)
(*                                                                         *)
(* Workload: TestBlockRecovery2#testRecoveryTimeout. Its @BeforeEach       *)
(* DataNode (mocked NN, pool "BP-TEST", TestBlockRecovery2.java:125-182)   *)
(* is shut down by the test's first statement (L296) before the           *)
(* MiniDFSCluster starts: its events are a prefix of the file and are     *)
(* dropped (StartIdx). The workload's teardown DataNode.shutdown() is     *)
(* replayed through DnStop like any other event; MC.cfg keeps it at 0.    *)
(*                                                                         *)
(* Identities: events carry raw ids (DataNode "dn<xferPort>", the real     *)
(* block pool id, the nameservice id or "<default>"). They are mapped to   *)
(* the literal model constants of Trace.cfg (d1, d2 / ns1 / n1 / p1) by    *)
(* order of first appearance. The constants stay literal on purpose:      *)
(* overriding base constants with trace-derived operators makes TLC       *)
(* re-read the trace lazily while it evaluates base's constant defs.      *)
(*                                                                         *)
(* No silent actions: every modeled state change of the workload has an   *)
(* event (quiet heartbeats change no modeled state and are not emitted).  *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC, Naturals, FiniteSets

-----------------------------------------------------------------------------
(* Trace loading *)

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

RawLog == TLCEval(
    SelectSeq(ndJsonDeserialize(JsonFile),
              LAMBDA x : /\ "tag" \in DOMAIN x
                         /\ x.tag = "trace"
                         /\ "event" \in DOMAIN x))

HasState(e, f) == "state" \in DOMAIN e /\ f \in DOMAIN e.state

MaxOf(S) == CHOOSE x \in S : \A y \in S : y <= x
MinOf(S) == CHOOSE x \in S : \A y \in S : x <= y

\* Where the MiniDFSCluster part of the run starts: after the last "TraceStart" marker if the
\* harness writes one, else at the first event of a DataNode other than the mocked one.
MockPool == "BP-TEST"
MarkerIdx == TLCEval({k \in 1..Len(RawLog) : RawLog[k].event.name = "TraceStart"})
MockNids == TLCEval({RawLog[k].event.nid :
                        k \in {j \in 1..Len(RawLog) : /\ HasState(RawLog[j].event, "pool")
                                                      /\ RawLog[j].event.state.pool = MockPool}})
NonMockIdx == TLCEval({k \in 1..Len(RawLog) : RawLog[k].event.nid \notin MockNids})
StartIdx == TLCEval(
    IF MarkerIdx # {} THEN MaxOf(MarkerIdx) + 1
    ELSE IF NonMockIdx # {} THEN MinOf(NonMockIdx)
    ELSE Len(RawLog) + 1)

TraceLog == TLCEval(SubSeq(RawLog, StartIdx, Len(RawLog)))

ASSUME Len(TraceLog) > 0

-----------------------------------------------------------------------------
(* Raw trace ids -> model constants (by order of first appearance). *)

TrNN == "nn"                                   \* nid of NameNode-side events

FirstIdx(pred(_)) == MinOf({k \in 1..Len(TraceLog) : pred(TraceLog[k].event)})

RawDNs == TLCEval({TraceLog[k].event.nid : k \in 1..Len(TraceLog)} \ {TrNN})
DnFirst == TLCEval([n \in RawDNs |-> FirstIdx(LAMBDA e : e.nid = n)])
DnMap == TLCEval([n \in RawDNs |->
            "d" \o ToString(Cardinality({m \in RawDNs : DnFirst[m] < DnFirst[n]}) + 1)])

RawNSs == TLCEval({TraceLog[k].event.state.ns :
                      k \in {j \in 1..Len(TraceLog) : HasState(TraceLog[j].event, "ns")}})
NsFirst == TLCEval([s \in RawNSs |-> FirstIdx(LAMBDA e : "state" \in DOMAIN e
                                                         /\ "ns" \in DOMAIN e.state
                                                         /\ e.state.ns = s)])
NsMap == TLCEval([s \in RawNSs |->
            "ns" \o ToString(Cardinality({m \in RawNSs : NsFirst[m] < NsFirst[s]}) + 1)])

RawPools == TLCEval({TraceLog[k].event.state.pool :
                        k \in {j \in 1..Len(TraceLog) : /\ TraceLog[j].event.name = "ActorConnect"
                                                        /\ HasState(TraceLog[j].event, "pool")}})

\* The workload has one namespace: every raw pool id maps to RecPool.
Dn(n) == DnMap[n]
Ns(s) == NsMap[s]
Pl(p) == IF p = "none" THEN Nil ELSE RecPool
\* A captured registry value: the nameservice now mapped for the pool, or "none" (null).
MapVal(s) == IF s = "none" THEN Nil ELSE Ns(s)

ASSUME {DnMap[n] : n \in RawDNs} = DN
ASSUME {NsMap[s] : s \in RawNSs} = InitCfg /\ InitCfg = NS
ASSUME Cardinality(RawPools) = 1 /\ Pool = {RecPool}

\* Recovery attempts in issue order; the base spec numbers them 1, 2, ... (nnAttempt).
IssueEvents == TLCEval(SelectSeq(TraceLog, LAMBDA x : x.event.name = "NnIssueRecovery"))
IssueRids   == TLCEval([i \in 1..Len(IssueEvents) |-> IssueEvents[i].event.state.rid])
IsIssued(r)  == \E i \in 1..Len(IssueRids) : IssueRids[i] = r
AttemptOf(r) == CHOOSE i \in 1..Len(IssueRids) : IssueRids[i] = r

ASSUME Len(IssueRids) <= MaxAttempts

\* The block's expected-location order, as carried by the first recovery command.
RecoverEvents == TLCEval(SelectSeq(TraceLog, LAMBDA x : /\ x.event.name = "CmdRecover"
                                                        /\ "locs" \in DOMAIN x.event.state))
LocsOf(s) == [i \in 1..Len(s) |-> Dn(s[i])]
TraceLocs == TLCEval(IF Len(RecoverEvents) > 0
                     THEN LocsOf(RecoverEvents[1].event.state.locs) ELSE <<>>)

-----------------------------------------------------------------------------
(* Cursor *)

VARIABLE l

traceVars == <<vars, l>>

E  == TraceLog[l].event
St == TraceLog[l].event.state

IsEvent(n) == l <= Len(TraceLog) /\ E.name = n

\* The model task slot of the trace's (DataNode, recovery id).
IsTask(t, d, rid) == /\ IsIssued(rid)
                     /\ task[t].st # "none"
                     /\ task[t].dn = d
                     /\ task[t].rid = AttemptOf(rid)

TraceInit ==
    /\ Init
    /\ TraceLocs # <<>> => blockLocs = TraceLocs
    /\ l = 1

-----------------------------------------------------------------------------
(* Action wrappers: match the event, run the base action, validate the post-state, advance. *)

\* ActorConnect: captured pool (bpNSInfo), mapped (the BPOS mapped for it after the step),
\* first (initBlockPool was called).
TrActorConnect ==
    /\ IsEvent("ActorConnect")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ ActorConnect(d, ns)
       /\ bposPool'[d][ns] = Pl(St.pool)
       /\ bpMap'[d][Pl(St.pool)] = MapVal(St.mapped)
       /\ (actorPc'[d][ns] = "initSt") = St.first
    /\ l' = l + 1

\* ActorInitStorage: captured ok (initBlockPool returned normally).
TrActorInitStorage ==
    /\ IsEvent("ActorInitStorage")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ ActorInitStorage(d, ns)
       /\ actorPc'[d][ns] = (IF St.ok THEN "reg" ELSE "fail")
       /\ dsPool'[d][bposPool[d][ns]] = St.ok
    /\ l' = l + 1

\* ActorRegister: captured ok (registrationSucceeded ran).
TrActorRegister ==
    /\ IsEvent("ActorRegister")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ ActorRegister(d, ns)
       /\ bposReg'[d][ns] = St.ok
       /\ actorPc'[d][ns] = (IF St.ok THEN "run" ELSE "conn")
    /\ l' = l + 1

\* ActorHeartbeat: captured outcome ("reject" | "register" | "recover") and, for "recover",
\* the recovery id of the command.
TrActorHeartbeat ==
    /\ IsEvent("ActorHeartbeat")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ ActorHeartbeat(d, ns)
       /\ CASE St.outcome = "reject"   ->
                 /\ actorRun[d][ns] /\ ~actorRun'[d][ns]
            [] St.outcome = "register" ->
                 cmdQ'[d][ns] = Append(cmdQ[d][ns], [type |-> "register", rid |-> 0])
            [] St.outcome = "recover"  ->
                 /\ IsIssued(St.rid)
                 /\ cmdQ'[d][ns] = Append(cmdQ[d][ns],
                                          [type |-> "recover", rid |-> AttemptOf(St.rid)])
            [] OTHER -> FALSE
    /\ l' = l + 1

\* CmdRegister: captured outcome ("ok" | "rejected" | "skipped").
TrCmdRegister ==
    /\ IsEvent("CmdRegister")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ CmdRegister(d, ns)
       /\ CASE St.outcome = "ok"       -> ShouldRun(d, ns) /\ (NnOf[ns] = RecNN => nnKnows'[d])
            [] St.outcome = "rejected" -> ShouldRun(d, ns) /\ ~actorRun'[d][ns]
            [] St.outcome = "skipped"  -> ~ShouldRun(d, ns)
            [] OTHER -> FALSE
    /\ l' = l + 1

\* CmdRecover: captured active (isActiveActor), rid, pool and locs of the RecoveringBlock.
TrCmdRecover ==
    /\ IsEvent("CmdRecover")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ cmdQ[d][ns] # <<>>
       /\ IsIssued(St.rid)
       /\ Head(cmdQ[d][ns]) = [type |-> "recover", rid |-> AttemptOf(St.rid)]
       /\ CmdRecover(d, ns)
       /\ IF St.active
          THEN /\ nTasks' = nTasks + 1
               /\ task'[nTasks + 1].pool = Pl(St.pool)
               /\ blockLocs = LocsOf(St.locs)
          ELSE nTasks' = nTasks
    /\ l' = l + 1

TrCmdThreadCrash ==
    /\ IsEvent("CmdThreadCrash")
    /\ CmdThreadCrash(Dn(E.nid), Ns(St.ns))
    /\ l' = l + 1

TrActorStop ==
    /\ IsEvent("ActorStop")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ ActorStop(d, ns)
       /\ ~actorRun'[d][ns]
    /\ l' = l + 1

TrActorLoopExit ==
    /\ IsEvent("ActorLoopExit")
    /\ ActorLoopExit(Dn(E.nid), Ns(St.ns))
    /\ l' = l + 1

\* ActorCleanUp: captured pool (bpos.getBlockPoolId(true), "none" if null) and mapped (the
\* BPOS mapped for that pool after cleanUp, "none" if unmapped).
TrActorCleanUp ==
    /\ IsEvent("ActorCleanUp")
    /\ LET d == Dn(E.nid)  ns == Ns(St.ns) IN
       /\ ActorCleanUp(d, ns)
       /\ bposPool[d][ns] = Pl(St.pool)
       /\ St.pool # "none" => bpMap'[d][Pl(St.pool)] = MapVal(St.mapped)
       /\ ns \notin offerSvc'[d]
    /\ l' = l + 1

\* DnStop: captured cause ("volFail" | "shutdown").
TrDnStop ==
    /\ IsEvent("DnStop")
    /\ DnStop(Dn(E.nid), St.cause)
    /\ ~dnRun'[Dn(E.nid)]
    /\ l' = l + 1

TrDnShutdownInterrupt ==
    /\ IsEvent("DnShutdownInterrupt")
    /\ DnShutdownInterrupt(Dn(E.nid))
    /\ l' = l + 1

\* NnIssueRecovery: captured rid (the new recovery id) and primary (nid of the chosen DataNode).
TrNnIssueRecovery ==
    /\ IsEvent("NnIssueRecovery")
    /\ IsIssued(St.rid)
    /\ NnIssueRecovery(Dn(St.primary))
    /\ nnAttempt' = AttemptOf(St.rid)
    /\ l' = l + 1

\* Fault events of workload variants (not in the workload itself).
TrNnReject ==
    /\ IsEvent("NnReject")
    /\ NnReject(Dn(St.dn))
    /\ l' = l + 1

TrDnsFail ==
    /\ IsEvent("DnsFail")
    /\ DnsFail(Dn(St.dn))
    /\ l' = l + 1

TrNnRestart ==
    /\ IsEvent("NnRestart")
    /\ NnRestart
    /\ l' = l + 1

\* Recovery-task events: nid = the DataNode running the Daemon, rid = its recovery id.

\* TaskGetId: captured idx (1-based location index), loc (nid of the location), result
\* ("ok" | "null" | "npe").
TrTaskGetId ==
    /\ IsEvent("TaskGetId")
    /\ \E t \in Task :
          /\ IsTask(t, Dn(E.nid), St.rid)
          /\ task[t].idx = St.idx
          /\ blockLocs[St.idx] = Dn(St.loc)
          /\ TaskGetId(t)
          /\ CASE St.result = "ok"   -> task'[t].st = "initRR"
               [] St.result = "null" -> task'[t].errs = task[t].errs + 1
               [] St.result = "npe"  -> task'[t].st = "npe"
               [] OTHER -> FALSE
    /\ l' = l + 1

\* TaskInitRR: captured idx, loc, outcome ("replica" | "none" | "ioErr" | "rip").
TrTaskInitRR ==
    /\ IsEvent("TaskInitRR")
    /\ \E t \in Task :
          /\ IsTask(t, Dn(E.nid), St.rid)
          /\ task[t].idx = St.idx
          /\ blockLocs[St.idx] = Dn(St.loc)
          /\ TaskInitRR(t, St.outcome)
    /\ l' = l + 1

\* TaskLoopEnd: captured errs, cands, sync (errorCount, candidateReplicaCnt, syncList.size()
\* at BRW:169) and result ("allFailed" | "noRWR" | "sync").
TrTaskLoopEnd ==
    /\ IsEvent("TaskLoopEnd")
    /\ \E t \in Task :
          /\ IsTask(t, Dn(E.nid), St.rid)
          /\ task[t].errs = St.errs
          /\ task[t].cands = St.cands
          /\ task[t].sync = St.sync
          /\ TaskLoopEnd(t)
          /\ task'[t].st = (IF St.result = "sync" THEN "target" ELSE "failed")
    /\ l' = l + 1

\* TargetCheck: captured result ("pass" | "fire").
TrTargetCheck ==
    /\ IsEvent("TargetCheck")
    /\ \E t \in Task :
          /\ IsTask(t, Dn(E.nid), St.rid)
          /\ TargetCheck(t)
          /\ (task'[t].st = "fired") = (St.result = "fire")
    /\ l' = l + 1

\* TaskGetActiveNN: captured result ("ok" | "noActive").
TrTaskGetActiveNN ==
    /\ IsEvent("TaskGetActiveNN")
    /\ \E t \in Task :
          /\ IsTask(t, Dn(E.nid), St.rid)
          /\ TaskGetActiveNN(t)
          /\ task'[t].st = (IF St.result = "ok" THEN "commit" ELSE "failed")
    /\ l' = l + 1

\* TaskCommit: captured outcome ("ok" | "stale" | "lost" | "error").
TrTaskCommit ==
    /\ IsEvent("TaskCommit")
    /\ \E t \in Task :
          /\ IsTask(t, Dn(E.nid), St.rid)
          /\ TaskCommit(t, St.outcome)
          /\ nnDone' = (nnDone \/ St.outcome = "ok")
    /\ l' = l + 1

-----------------------------------------------------------------------------

TraceNext ==
    \/ TrActorConnect
    \/ TrActorInitStorage
    \/ TrActorRegister
    \/ TrActorHeartbeat
    \/ TrCmdRegister
    \/ TrCmdRecover
    \/ TrCmdThreadCrash
    \/ TrActorStop
    \/ TrActorLoopExit
    \/ TrActorCleanUp
    \/ TrDnStop
    \/ TrDnShutdownInterrupt
    \/ TrNnIssueRecovery
    \/ TrNnReject
    \/ TrDnsFail
    \/ TrNnRestart
    \/ TrTaskGetId
    \/ TrTaskInitRR
    \/ TrTaskLoopEnd
    \/ TrTargetCheck
    \/ TrTaskGetActiveNN
    \/ TrTaskCommit

\* WF makes TLC leave stuttering only when no event matches (without it, TraceMatched fails).
TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

\* The whole trace was consumed.
TraceMatched == <>(l > Len(TraceLog))

\* Exists-check alternative: as an INVARIANT, "violated" means some behavior consumed the
\* whole trace. Replay here is deterministic (each event fixes the action and its arguments),
\* so TraceMatched is the primary check.
TraceNotDone == l <= Len(TraceLog)

\* Debugging view: the next event and the modeled registry/task state.
TraceAlias == [l |-> l,
               next |-> IF l <= Len(TraceLog) THEN TraceLog[l].event ELSE "END",
               bpMap |-> bpMap, actorPc |-> actorPc, actorRun |-> actorRun,
               cmdQ |-> cmdQ, task |-> task, nnAttempt |-> nnAttempt,
               nnPending |-> nnPending, nnDone |-> nnDone, dnRun |-> dnRun,
               dnShut |-> dnShut, targetFired |-> targetFired]

=============================================================================
