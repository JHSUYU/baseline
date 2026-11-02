-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for hdfs-adhoc-38 (Category A: one linear NDJSON       *)
(* trace, cursor l). Event schema: instrumentation-spec.md Section 1.      *)
(*                                                                         *)
(* Every event maps to exactly one base action, with its parameters taken  *)
(* from the event, followed by a post-state check of the fields the event  *)
(* carries. There are no silent actions: every RPC that changes a modeled  *)
(* variable emits an event inside the namesystem write lock, so the file   *)
(* order is the lock order.                                                *)
(*                                                                         *)
(* The workload test itself emits only Init, StartFile, CompleteFile and   *)
(* TargetCheck. The environment wrappers exist for the harness's variants, *)
(* which may run those RPCs only where they do not write a guard operand   *)
(* (instrumentation-spec.md Section 3.6).                                  *)
(*                                                                         *)
(* TargetSafe is checked here (Trace.cfg): the workload passes and         *)
(* evaluates the guard false twice (brief Section 1, Workload). The        *)
(* TargetCheck wrapper separately compares the guard value the code read   *)
(* with the one the model evaluates.                                       *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, FiniteSets

----------------------------------------------------------------------------
\* Trace loading

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN  SelectSeq(all, LAMBDA x : /\ "tag" \in DOMAIN x
                                  /\ x.tag = "trace"
                                  /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0
ASSUME TraceLog[1].event.name = "Init"

----------------------------------------------------------------------------
\* Client mapping: raw DFSClient names -> model clients, by order of first
\* appearance. The first client in a trace is the creator (fs2's client = C1,
\* brief Section 1). Literal constants plus this mapping, so no base constant
\* is overridden with a trace-derived operator.

ClientLines == {k \in 1..Len(TraceLog) : "client" \in DOMAIN TraceLog[k].event.msg}

RawClients == {TraceLog[k].event.msg.client : k \in ClientLines}

ASSUME Cardinality(RawClients) <= 2

FirstLine(raw) ==
    CHOOSE k \in ClientLines :
        /\ TraceLog[k].event.msg.client = raw
        /\ \A j \in ClientLines : TraceLog[j].event.msg.client = raw => k <= j

ClientMap == TLCEval(
    [raw \in RawClients |->
        IF \A other \in RawClients : FirstLine(raw) <= FirstLine(other)
        THEN C1 ELSE C2])

\* "" is the wire form of "not under construction". A uc name that no client
\* event carries stays unmapped and fails the comparison with ucHolder.
ToClient(raw) ==
    IF raw = "" THEN NoClient
    ELSE IF raw \in RawClients THEN ClientMap[raw]
    ELSE raw

----------------------------------------------------------------------------
\* Cursor

VARIABLE l

logline == TraceLog[l]
ev  == logline.event
msg == ev.msg
st  == ev.state

IsEvent(eventName) ==
    /\ l <= Len(TraceLog)
    /\ ev.name = eventName

StepTrace == l' = l + 1

\* Path components -> model inode, walking the current namespace from the root.
RECURSIVE Walk(_, _)
Walk(cur, comps) ==
    IF comps = <<>> THEN cur
    ELSE IF cur = NoINode THEN NoINode
    ELSE Walk(ChildOf(cur, Head(comps)), Tail(comps))

ResolveINode(comps) == Walk(Root, comps)

\* The parent directory of a path, and its last component.
ResolveParent(comps) == Walk(Root, SubSeq(comps, 1, Len(comps) - 1))
LastComp(comps)      == comps[Len(comps)]

----------------------------------------------------------------------------
\* Post-state validation: the fields every event captures, read inside the
\* write lock after the action (instrumentation-spec.md Section 1.2). own and
\* eff are the guard's operand 2 and its parts, uc the lease side, path F's
\* place in the namespace. Before F exists own = eff = -1, uc = "", path = [].

ValidatePostState ==
    /\ IF created'
       THEN /\ st.own = fileOwn'
            /\ st.eff = EffFile'
       ELSE /\ st.own = -1
            /\ st.eff = -1
    /\ ToClient(st.uc) = ucHolder'
    /\ st.path = PathOf(F)'

----------------------------------------------------------------------------
\* Initial state. The first event (Init) is the NameNode's view just before
\* the workload's create: the constant LAZY_PERSIST id, the default policy, and
\* an empty root without a policy. The cursor starts on the event after it.
\*
\* These are ASSUMEs on purpose. As conjuncts of TraceInit, a mismatch would leave
\* TLC with zero initial states, and TLC reports that as "No error has been found"
\* even with TraceMatched in PROPERTIES.

ASSUME TraceLog[1].event.msg.lp = LpPolicyId
ASSUME TraceLog[1].event.msg.defaultPolicy = DefaultPolicy
ASSUME TraceLog[1].event.msg.rootPolicy = UNSPECIFIED
ASSUME TraceLog[1].event.msg.rootChildren = <<>>
ASSUME TraceLog[1].event.state.own = -1
ASSUME TraceLog[1].event.state.eff = -1
ASSUME TraceLog[1].event.state.uc = ""
ASSUME TraceLog[1].event.state.path = <<>>

TraceInit ==
    /\ Init
    /\ l = 2

----------------------------------------------------------------------------
\* Workload wrappers

TraceStartFile ==
    /\ IsEvent("StartFile")
    /\ msg.src = <<WorkloadDirName, WorkloadFileName>>
    /\ msg.lazyFlag = CreateLazyFlag
    /\ msg.policyId = CreatePolicyId
    /\ StartFile(ToClient(msg.client))
    /\ ValidatePostState
    /\ StepTrace

TraceCompleteFile ==
    /\ IsEvent("CompleteFile")
    /\ CompleteFile(ToClient(msg.client))
    /\ ValidatePostState
    /\ StepTrace

\* The guard: lp and guard are what the code read at FSDirAppendOp.java:121.
\* Both are compared with the model's pre-state, then the action decides the
\* outcome from the same guard.
TraceTargetCheck ==
    /\ IsEvent("TargetCheck")
    /\ msg.lp = LpPolicyId
    /\ msg.guard = GuardFails
    /\ TargetCheck(ToClient(msg.client))
    /\ msg.outcome = outcome'[ToClient(msg.client)]
    /\ ValidatePostState
    /\ StepTrace

TraceAppendPathRejected ==
    /\ IsEvent("AppendPathRejected")
    /\ AppendPathRejected(ToClient(msg.client))
    /\ msg.outcome = outcome'[ToClient(msg.client)]
    /\ ValidatePostState
    /\ StepTrace

----------------------------------------------------------------------------
\* Environment wrappers (variants only)

TraceSetDirStoragePolicy ==
    /\ IsEvent("SetDirStoragePolicy")
    /\ SetDirStoragePolicy(ResolveINode(msg.src), msg.policy)
    /\ msg.dirLocal = dirPolicy'[ResolveINode(msg.src)]
    /\ ValidatePostState
    /\ StepTrace

TraceUnsetDirStoragePolicy ==
    /\ IsEvent("UnsetDirStoragePolicy")
    /\ UnsetDirStoragePolicy(ResolveINode(msg.src))
    /\ msg.dirLocal = dirPolicy'[ResolveINode(msg.src)]
    /\ ValidatePostState
    /\ StepTrace

TraceSetFileStoragePolicy ==
    /\ IsEvent("SetFileStoragePolicy")
    /\ ResolveINode(msg.src) = F
    /\ SetFileStoragePolicy(msg.policy)
    /\ ValidatePostState
    /\ StepTrace

TraceMkdirs ==
    /\ IsEvent("Mkdirs")
    /\ Mkdirs(ResolveParent(msg.src), LastComp(msg.src))
    /\ PathOf(L)' = msg.src
    /\ ValidatePostState
    /\ StepTrace

\* The source is bound with \E: a prime over PathOf(ResolveINode(msg.src)) would
\* re-resolve the source path, and read the cursor, in the next state.
TraceRenameOld ==
    /\ IsEvent("RenameOld")
    /\ \E x \in INode :
          /\ x = ResolveINode(msg.src)
          /\ RenameOld(x, ResolveParent(msg.dst), LastComp(msg.dst))
          /\ PathOf(x)' = msg.dst
    /\ ValidatePostState
    /\ StepTrace

TraceRename2 ==
    /\ IsEvent("Rename2")
    /\ \E x \in INode :
          /\ x = ResolveINode(msg.src)
          /\ Rename2(x, ResolveParent(msg.dst), LastComp(msg.dst), msg.overwrite)
          /\ PathOf(x)' = msg.dst
    /\ ValidatePostState
    /\ StepTrace

----------------------------------------------------------------------------
TraceNext ==
    \/ TraceStartFile
    \/ TraceCompleteFile
    \/ TraceTargetCheck
    \/ TraceAppendPathRejected
    \/ TraceSetDirStoragePolicy
    \/ TraceUnsetDirStoragePolicy
    \/ TraceSetFileStoragePolicy
    \/ TraceMkdirs
    \/ TraceRenameOld
    \/ TraceRename2

TraceVars == <<vars, l>>

\* The weak fairness makes TLC take a step whenever one is enabled. Without it
\* TraceMatched is always violated by stuttering.
TraceSpec == TraceInit /\ [][TraceNext]_TraceVars /\ WF_TraceVars(TraceNext)

TraceMatched == <>(l > Len(TraceLog))

TraceView == TraceVars

TraceAlias ==
    [l |-> l,
     event |-> IF l <= Len(TraceLog) THEN ev.name ELSE "END",
     pc |-> pc,
     parent |-> parent,
     name |-> name,
     dirPolicy |-> dirPolicy,
     fileOwn |-> fileOwn,
     eff |-> EffFile,
     ucHolder |-> ucHolder,
     outcome |-> outcome,
     targetFired |-> targetFired]

=============================================================================
