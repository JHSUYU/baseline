-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for solr-adhoc-k2 (Category A: one linear NDJSON       *)
(* trace from the single test JVM that hosts every Jetty node and the      *)
(* embedded ZooKeeper).  Event names, fields and capture points are        *)
(* defined in instrumentation-spec.md.                                     *)
(*                                                                          *)
(* Every wrapper calls the base action unchanged, then checks the fields   *)
(* the trace captured against the post-state.                              *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

----------------------------------------------------------------------------
(* Trace loading *)

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

VARIABLE l
logline == TraceLog[l]

----------------------------------------------------------------------------
(* Constants derived from the trace (substituted in Trace.cfg) *)

Has(e, f) == f \in DOMAIN e

TraceNodes == TLCEval(
    {TraceLog[k].node : k \in {j \in 1..Len(TraceLog) : Has(TraceLog[j], "node")}})

OcpEventNames ==
    {"SplitShard_SendLeaderCreate", "SplitShard_CollectLeaderResponses",
     "SplitShard_WaitForLeaderCoreNodeName", "SplitShard_SendReplicaCreate",
     "SplitShard_WaitForReplicaCoreNodeName", "SplitShard_CollectReplicaResponses",
     "CreateCollection_ReadLegacy", "CreateCollection_EnqueueCollection",
     "CreateCollection_WaitCreated", "CreateCollection_SubmitLegacyCreate",
     "CreateCollection_EnqueueAddReplica", "CreateCollection_WaitToSeeReplicasInState",
     "CreateCollection_SubmitNonLegacyCreate", "CreateCollection_ProcessResponses",
     "AddReplica_ReadLegacy", "AddReplica_WaitToSeeReplicasInState",
     "AddReplica_SendShardRequest", "AddReplica_CollectShardResponses"}

IsOcpEvent(e) == e.event \in OcpEventNames

TraceOps == TLCEval(
    {TraceLog[k].op : k \in {j \in 1..Len(TraceLog) : IsOcpEvent(TraceLog[j])}})

EvSeq(op, names) ==
    SelectSeq(TraceLog, LAMBDA e : IsOcpEvent(e) /\ e.op = op /\ e.event \in names)

FirstEv(op) == EvSeq(op, OcpEventNames)[1]

CoreSlice(s) == [i \in 1..Len(s) |-> [core |-> s[i].core, slice |-> s[i].slice]]
CoreSliceNode(s) ==
    [i \in 1..Len(s) |-> [core |-> s[i].core, slice |-> s[i].slice, node |-> s[i].node]]

\* Static task parameters, as computed by OCP code before the modeled steps
\* (see base.tla OpSpec comment).  Each OCP event carries "kind" and "coll".
TraceOpSpec == TLCEval(
    [op \in TraceOps |->
       LET f == FirstEv(op) IN
       CASE f.kind = "split" ->
              [kind |-> "split", coll |-> f.coll,
               leaderNode |-> EvSeq(op, {"SplitShard_SendLeaderCreate"})[1].node,
               leaders  |-> CoreSlice(EvSeq(op, {"SplitShard_SendLeaderCreate"})),
               replicas |-> CoreSlice(EvSeq(op, {"SplitShard_SendReplicaCreate"}))]
         [] f.kind = "createcollection" ->
              [kind |-> "createcollection", coll |-> f.coll,
               cores |-> CoreSliceNode(EvSeq(op, {"CreateCollection_SubmitLegacyCreate",
                                                  "CreateCollection_EnqueueAddReplica"}))]
         [] f.kind = "addreplica" ->
              LET r == EvSeq(op, {"AddReplica_ReadLegacy"})[1] IN
              [kind |-> "addreplica", coll |-> f.coll, slice |-> r.slice,
               core |-> r.core, node |-> r.node]])

\* Collections that exist before the trace: every collection a split or
\* addReplica task works on that no traced createCollection creates
\* (collection1 is created by core discovery at Jetty start-up).
TraceInitColls == TLCEval(
    {TraceOpSpec[op].coll : op \in {o \in TraceOps : TraceOpSpec[o].kind /= "createcollection"}}
    \ {TraceOpSpec[op].coll : op \in {o \in TraceOps : TraceOpSpec[o].kind = "createcollection"}})

TraceInitSlices == TLCEval(
    {<<TraceOpSpec[op].coll, TraceOpSpec[op].slice>> :
        op \in {o \in TraceOps : TraceOpSpec[o].kind = "addreplica"
                                 /\ TraceOpSpec[o].coll \in TraceInitColls}})

----------------------------------------------------------------------------
(* Event predicates and helpers *)

IsEvent(name) == l <= Len(TraceLog) /\ logline.event = name
IsOpEvent(name, op) == IsEvent(name) /\ logline.op = op

\* Trace encodes coreNodeName == null as "".
CnnMatches(cnn) == (cnn = NULL) <=> (logline.cnn = "")

\* The CREATE request record the trace line refers to.
MsgFor(core, node) == {m \in createMsgs : m.core = core /\ m.node = node}

NewMsgOk(op) ==
    \E m \in createMsgs' \ createMsgs :
        /\ m.op = op /\ m.core = logline.core /\ m.node = logline.node
        /\ m.slice = logline.slice /\ CnnMatches(m.cnn)

Step == l' = l + 1

LastOf(s) == s[Len(s)]

----------------------------------------------------------------------------
(* Client / Overseer wrappers *)

ClientSetClusterPropIfLogged ==
    /\ IsEvent("ClientSetClusterProp")
    /\ ClientSetClusterProp(logline.val)
    /\ Step

HeadIs(type) == stateQueue /= <<>> /\ Head(stateQueue).type = type

Overseer_HandlePropIfLogged ==
    /\ IsEvent("Overseer_HandleProp")
    /\ HeadIs("clusterprop") /\ Head(stateQueue).val = logline.val
    /\ Overseer_HandleProp
    /\ zkLegacyFalse' = logline.legacyFalse
    /\ Step

Overseer_CreateShardIfLogged ==
    /\ IsEvent("Overseer_CreateShard")
    /\ HeadIs("createshard")
    /\ Head(stateQueue).coll = logline.coll /\ Head(stateQueue).slice = logline.slice
    /\ Overseer_CreateShard
    /\ <<logline.coll, logline.slice>> \in csSlices'
    /\ Step

Overseer_BuildCollectionIfLogged ==
    /\ IsEvent("Overseer_BuildCollection")
    /\ HeadIs("createcollection") /\ Head(stateQueue).coll = logline.coll
    /\ Overseer_BuildCollection
    /\ logline.coll \in csColls'
    /\ Step

Overseer_CreateReplicaIfLogged ==
    /\ IsEvent("Overseer_CreateReplica")
    /\ HeadIs("addreplica") /\ Head(stateQueue).core = logline.core
    /\ Overseer_CreateReplica
    /\ CnnMatches(replicaCnn'[logline.core])
    /\ Step

Overseer_UpdateStateIfLogged ==
    /\ IsEvent("Overseer_UpdateState")
    /\ logline.core \in AllCores
    /\ HeadIs("state") /\ Head(stateQueue).core = logline.core
    /\ Overseer_UpdateState
    /\ CnnMatches(replicaCnn'[logline.core])
    /\ Step

----------------------------------------------------------------------------
(* OCP wrappers *)

SplitShard_SendLeaderCreateIfLogged(op) ==
    /\ IsOpEvent("SplitShard_SendLeaderCreate", op)
    /\ SplitShard_SendLeaderCreate(op)
    /\ NewMsgOk(op)
    /\ LastOf(stateQueue') = [type |-> "createshard", coll |-> logline.coll, slice |-> logline.slice]
    /\ Step

SplitShard_CollectLeaderResponsesIfLogged(op) ==
    /\ IsOpEvent("SplitShard_CollectLeaderResponses", op)
    /\ SplitShard_CollectLeaderResponses(op)
    /\ (ocpPc'[op] /= "failed") = logline.ok
    /\ Step

SplitShard_WaitForLeaderCoreNodeNameIfLogged(op) ==
    /\ IsOpEvent("SplitShard_WaitForLeaderCoreNodeName", op)
    /\ SplitShard_WaitForLeaderCoreNodeName(op)
    /\ Step

SplitShard_SendReplicaCreateIfLogged(op) ==
    /\ IsOpEvent("SplitShard_SendReplicaCreate", op)
    /\ logline.node \in Nodes
    /\ SplitShard_SendReplicaCreate(op, logline.node)
    /\ NewMsgOk(op)
    /\ Step

SplitShard_WaitForReplicaCoreNodeNameIfLogged(op) ==
    /\ IsOpEvent("SplitShard_WaitForReplicaCoreNodeName", op)
    /\ OpSpec[op].replicas[ocpIdx[op]].core = logline.core
    /\ SplitShard_WaitForReplicaCoreNodeName(op)
    /\ (ocpPc'[op] /= "failed") = logline.ok
    /\ Step

SplitShard_CollectReplicaResponsesIfLogged(op) ==
    /\ IsOpEvent("SplitShard_CollectReplicaResponses", op)
    /\ SplitShard_CollectReplicaResponses(op)
    /\ (ocpPc'[op] = "done") = logline.ok
    /\ Step

CreateCollection_ReadLegacyIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_ReadLegacy", op)
    /\ CreateCollection_ReadLegacy(op)
    /\ ocpLegacy'[op] = logline.isLegacy
    /\ Step

CreateCollection_EnqueueCollectionIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_EnqueueCollection", op)
    /\ CreateCollection_EnqueueCollection(op)
    /\ LastOf(stateQueue').coll = logline.coll
    /\ Step

CreateCollection_WaitCreatedIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_WaitCreated", op)
    /\ CreateCollection_WaitCreated(op)
    /\ Step

CreateCollection_SubmitLegacyCreateIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_SubmitLegacyCreate", op)
    /\ CreateCollection_SubmitLegacyCreate(op)
    /\ NewMsgOk(op)
    /\ Step

CreateCollection_EnqueueAddReplicaIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_EnqueueAddReplica", op)
    /\ CreateCollection_EnqueueAddReplica(op)
    /\ LastOf(stateQueue').core = logline.core
    /\ Step

CreateCollection_WaitToSeeReplicasInStateIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_WaitToSeeReplicasInState", op)
    /\ CreateCollection_WaitToSeeReplicasInState(op)
    /\ Step

CreateCollection_SubmitNonLegacyCreateIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_SubmitNonLegacyCreate", op)
    /\ CreateCollection_SubmitNonLegacyCreate(op)
    /\ NewMsgOk(op)
    /\ Step

CreateCollection_ProcessResponsesIfLogged(op) ==
    /\ IsOpEvent("CreateCollection_ProcessResponses", op)
    /\ CreateCollection_ProcessResponses(op)
    /\ Step

AddReplica_ReadLegacyIfLogged(op) ==
    /\ IsOpEvent("AddReplica_ReadLegacy", op)
    /\ AddReplica_ReadLegacy(op)
    /\ ocpLegacy'[op] = logline.isLegacy
    /\ Step

AddReplica_WaitToSeeReplicasInStateIfLogged(op) ==
    /\ IsOpEvent("AddReplica_WaitToSeeReplicasInState", op)
    /\ AddReplica_WaitToSeeReplicasInState(op)
    /\ CnnMatches(ocpCnn'[op])
    /\ Step

AddReplica_SendShardRequestIfLogged(op) ==
    /\ IsOpEvent("AddReplica_SendShardRequest", op)
    /\ AddReplica_SendShardRequest(op)
    /\ NewMsgOk(op)
    /\ Step

AddReplica_CollectShardResponsesIfLogged(op) ==
    /\ IsOpEvent("AddReplica_CollectShardResponses", op)
    /\ AddReplica_CollectShardResponses(op)
    /\ (ocpPc'[op] = "done") = logline.ok
    /\ Step

----------------------------------------------------------------------------
(* Receiver (CAH) wrappers *)

\* outcome: "dup" (CAH:547-551), "fired" (CAH:560), "pass" (reached CAH:565)
OutcomeStatus(o) == CASE o = "dup" -> "failed" [] o = "fired" -> "failed" [] o = "pass" -> "admitted"

TargetCheckIfLogged ==
    /\ IsEvent("TargetCheck")
    /\ logline.core \in AllCores
    /\ \E m \in MsgFor(logline.core, logline.node) :
         /\ m.status = "sent"
         /\ CnnMatches(m.cnn)                       \* guard operand 2 (CAH:559)
         /\ IsLegacy = logline.isLegacy             \* guard operand 1 (CAH:558)
         /\ TargetCheck(m)
         /\ [m EXCEPT !.status = OutcomeStatus(logline.outcome)] \in createMsgs'
         /\ targetFired' = (logline.outcome = "fired")
    /\ Step

CoreAdminHandler_PreRegisterInZkIfLogged ==
    /\ IsEvent("CoreAdminHandler_PreRegisterInZk")
    /\ logline.core \in AllCores
    /\ \E m \in MsgFor(logline.core, logline.node) :
         /\ m.status = "admitted"
         /\ CoreAdminHandler_PreRegisterInZk(m)
         /\ [m EXCEPT !.status = IF logline.ok THEN "ok" ELSE "failed"] \in createMsgs'
    /\ Step

\* CREATE / registration of a core no traced OCP task sent (direct
\* CoreAdmin clients; brief §3.2 "Do Not Model").  Consumed without a state
\* change, but the guard's operand 1 must still agree with the model's ZK.
SkipExternalCore ==
    /\ l <= Len(TraceLog)
    /\ logline.event \in {"TargetCheck", "CoreAdminHandler_PreRegisterInZk", "Overseer_UpdateState"}
    /\ logline.core \notin AllCores
    /\ logline.event = "TargetCheck" => /\ IsLegacy = logline.isLegacy
                                         /\ logline.outcome /= "fired"
    /\ UNCHANGED vars
    /\ Step

----------------------------------------------------------------------------
(* Silent action: OCP task pickup has no trace event; allowed only for the
   task named by the next trace line, and only once. *)
SilentRun ==
    /\ l <= Len(TraceLog)
    /\ IsOcpEvent(logline)
    /\ OverseerCollectionProcessor_Run(logline.op)
    /\ UNCHANGED l

----------------------------------------------------------------------------
TraceInit ==
    /\ Init
    /\ l = 1

TraceNext ==
    \/ ClientSetClusterPropIfLogged
    \/ Overseer_HandlePropIfLogged
    \/ Overseer_CreateShardIfLogged
    \/ Overseer_BuildCollectionIfLogged
    \/ Overseer_CreateReplicaIfLogged
    \/ Overseer_UpdateStateIfLogged
    \/ TargetCheckIfLogged
    \/ CoreAdminHandler_PreRegisterInZkIfLogged
    \/ SkipExternalCore
    \/ \E op \in Ops :
         \/ SplitShard_SendLeaderCreateIfLogged(op)
         \/ SplitShard_CollectLeaderResponsesIfLogged(op)
         \/ SplitShard_WaitForLeaderCoreNodeNameIfLogged(op)
         \/ SplitShard_SendReplicaCreateIfLogged(op)
         \/ SplitShard_WaitForReplicaCoreNodeNameIfLogged(op)
         \/ SplitShard_CollectReplicaResponsesIfLogged(op)
         \/ CreateCollection_ReadLegacyIfLogged(op)
         \/ CreateCollection_EnqueueCollectionIfLogged(op)
         \/ CreateCollection_WaitCreatedIfLogged(op)
         \/ CreateCollection_SubmitLegacyCreateIfLogged(op)
         \/ CreateCollection_EnqueueAddReplicaIfLogged(op)
         \/ CreateCollection_WaitToSeeReplicasInStateIfLogged(op)
         \/ CreateCollection_SubmitNonLegacyCreateIfLogged(op)
         \/ CreateCollection_ProcessResponsesIfLogged(op)
         \/ AddReplica_ReadLegacyIfLogged(op)
         \/ AddReplica_WaitToSeeReplicasInStateIfLogged(op)
         \/ AddReplica_SendShardRequestIfLogged(op)
         \/ AddReplica_CollectShardResponsesIfLogged(op)
    \/ SilentRun

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l          |-> l,
      len        |-> Len(TraceLog),
      event      |-> IF l <= Len(TraceLog) THEN logline.event ELSE "DONE",
      op         |-> IF l <= Len(TraceLog) /\ Has(logline, "op") THEN logline.op ELSE "",
      core       |-> IF l <= Len(TraceLog) /\ Has(logline, "core") THEN logline.core ELSE "",
      zkLegacyFalse |-> zkLegacyFalse,
      queueHead  |-> IF stateQueue = <<>> THEN "empty" ELSE Head(stateQueue).type,
      ocpPc      |-> ocpPc,
      createMsgs |-> createMsgs,
      replicaCnn |-> replicaCnn,
      targetFired |-> targetFired ]

=============================================================================
