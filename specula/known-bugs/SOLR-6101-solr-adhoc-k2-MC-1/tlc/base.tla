-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* Ad hoc coordination target: CoreAdminHandler.handleCreateAction        *)
(*   solr/core/src/java/org/apache/solr/handler/admin/CoreAdminHandler.java *)
(*   L560  throw new SolrException(SERVER_ERROR,                            *)
(*           "non legacy mode coreNodeName missing " + params)              *)
(*                                                                          *)
(* Pinned tree: lucene-solr @ 6e6ca4a3a91fd2b2d8fde70b7ac110c8e8401b4f.     *)
(* All paths below are relative to solr/.  Abbreviations:                  *)
(*   CAH = core/src/java/org/apache/solr/handler/admin/CoreAdminHandler.java*)
(*   OCP = core/src/java/org/apache/solr/cloud/OverseerCollectionProcessor.java *)
(*   OV  = core/src/java/org/apache/solr/cloud/Overseer.java                *)
(*   CH  = core/src/java/org/apache/solr/handler/admin/CollectionsHandler.java *)
(*   ZSR = solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java   *)
(*   ZKC = core/src/java/org/apache/solr/cloud/ZkController.java            *)
(*                                                                          *)
(* Category A (message passing).  Actors:                                   *)
(*   - OCP task threads (one per collection-API task, OCP:225-360), which   *)
(*     send CoreAdmin CREATE requests over HTTP (sendShardRequest,          *)
(*     OCP:1998-2008, or shardHandler.submit directly);                     *)
(*   - the Overseer ClusterStateUpdater thread, which drains the FIFO       *)
(*     /overseer/queue (OV:338-386) and is the only writer of               *)
(*     /clusterprops.json (OV:388-404) and of clusterstate.json;            *)
(*   - the receiving node's CAH thread (TargetCheck), which reads           *)
(*     /clusterprops.json live from ZK (ZSR:643-654).                       *)
(*   - Collections API clients issuing CLUSTERPROP (CH:237-252).            *)
(*                                                                          *)
(* Scenario 1 (brief §2): SPLITSHARD CREATEs never carry coreNodeName.      *)
(* Scenario 2 (brief §2): createCollection / addReplica read legacyCloud    *)
(*   once in the OCP; the receiver re-reads it later.                       *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Nodes,            \* live Solr nodes (all ZooKeeper-aware SolrCloud nodes)
    Ops,              \* collection-API tasks in the OCP work queue
    OpSpec,           \* Ops -> static description of each task (see below)
    InitLegacyFalse,  \* initial /clusterprops.json legacyCloud == "false"?
    InitColls,        \* collections present in clusterstate.json at start
    InitSlices        \* <<coll, slice>> pairs present at start

(***************************************************************************)
(* OpSpec[op] shapes (static task parameters computed by the OCP code       *)
(* before the steps we model):                                             *)
(*  split:  [kind |-> "split", coll, leaderNode,                            *)
(*           leaders  |-> Seq([core, slice])  \* OCP:1316-1320 subShardNames *)
(*           replicas |-> Seq([core, slice])] \* OCP:1461-1464, j=2..repFactor*)
(*  createcollection: [kind, coll, cores |-> Seq([core, slice, node])]     *)
(*           \* OCP:2125-2131 coreName / nodeName per (slice, j)            *)
(*  addreplica: [kind, coll, slice, core, node]  \* OCP:2233-2275           *)
(***************************************************************************)

NULL == 0                       \* "coreNodeName == null"; real cnns are 1..
PropVals == {"false", "unset"}  \* CLUSTERPROP val: "false" or null (removes key, OV:394)

ZkControllerPresent(n) == TRUE  \* CAH:557: every node in the modeled cluster is SolrCloud

Kind(op) == OpSpec[op].kind
Coll(op) == OpSpec[op].coll

SplitOps == {op \in Ops : Kind(op) = "split"}
CCOps    == {op \in Ops : Kind(op) = "createcollection"}
AROps    == {op \in Ops : Kind(op) = "addreplica"}

SeqCores(s) == {s[i].core : i \in DOMAIN s}

OpCores(op) ==
    CASE Kind(op) = "split"            -> SeqCores(OpSpec[op].leaders) \cup SeqCores(OpSpec[op].replicas)
      [] Kind(op) = "createcollection" -> SeqCores(OpSpec[op].cores)
      [] Kind(op) = "addreplica"       -> {OpSpec[op].core}

AllCores == UNION {OpCores(op) : op \in Ops}

CCSlices(op) == {OpSpec[op].cores[i].slice : i \in DOMAIN OpSpec[op].cores}

Pcs == {"queued", "done", "failed",
        "sp_sendLeader", "sp_collectLeaders", "sp_waitLeaderCnn",
        "sp_sendReplica", "sp_waitReplicaCnn", "sp_collectReplicas",
        "cc_readLegacy", "cc_enqueue", "cc_waitCreated", "cc_core",
        "cc_waitReplicas", "cc_submit", "cc_responses",
        "ar_readLegacy", "ar_waitCnn", "ar_send", "ar_collect"}

FirstPc(op) ==
    CASE Kind(op) = "split"            -> "sp_sendLeader"
      [] Kind(op) = "createcollection" -> "cc_readLegacy"
      [] Kind(op) = "addreplica"       -> "ar_readLegacy"

VARIABLES
    \* ZK /clusterprops.json: legacyCloud == "false"  (Scenario 1, 2; guard operand 1)
    zkLegacyFalse,
    \* /overseer/queue, FIFO, drained by OV ClusterStateUpdater (Scenario 1, 2)
    stateQueue,
    \* clusterstate.json: collections, slices, core -> coreNodeName (Scenario 2)
    csColls, csSlices, replicaCnn, nextCnn,
    \* in-flight / answered CoreAdmin CREATE requests (guard operand 2)
    createMsgs,
    \* cores registered in each node's CoreContainer (CAH:547)
    nodeCores,
    \* OCP task-thread locals (Scenario 1, 2)
    ocpPc, ocpIdx, ocpLegacy, ocpCnn,
    \* oracle
    targetFired

zkVars    == <<zkLegacyFalse>>
csVars    == <<csColls, csSlices, replicaCnn, nextCnn>>
ocpVars   == <<ocpPc, ocpIdx, ocpLegacy, ocpCnn>>
vars      == <<zkLegacyFalse, stateQueue, csColls, csSlices, replicaCnn, nextCnn,
               createMsgs, nodeCores, ocpPc, ocpIdx, ocpLegacy, ocpCnn, targetFired>>

----------------------------------------------------------------------------
(* Helpers *)

\* OV:1276-1277  isLegacy(props) == !"false".equals(props.get("legacyCloud"))
IsLegacy == ~zkLegacyFalse

MsgsOf(op, cores) == {m \in createMsgs : m.op = op /\ m.core \in cores}

NewMsg(op, n, core, slice, cnn) ==
    [op |-> op, node |-> n, core |-> core, coll |-> Coll(op), slice |-> slice,
     cnn |-> cnn, status |-> "sent"]

\* The OCP's shardHandler has a response for m (ok or exception).
Answered(m) == m.status \in {"ok", "failed"}

Running(op) == ocpPc[op] \notin {"queued", "done", "failed"}

----------------------------------------------------------------------------
Init ==
    /\ zkLegacyFalse = InitLegacyFalse
    /\ stateQueue    = <<>>
    /\ csColls       = InitColls
    /\ csSlices      = InitSlices
    /\ replicaCnn    = [c \in AllCores |-> NULL]
    /\ nextCnn       = 1
    /\ createMsgs    = {}
    /\ nodeCores     = [n \in Nodes |-> {}]
    /\ ocpPc         = [op \in Ops |-> "queued"]
    /\ ocpIdx        = [op \in Ops |-> 1]
    /\ ocpLegacy     = [op \in Ops |-> TRUE]
    /\ ocpCnn        = [op \in Ops |-> NULL]
    /\ targetFired   = FALSE

----------------------------------------------------------------------------
(***************************************************************************)
(* Collections API client: CLUSTERPROP                                      *)
(***************************************************************************)

\* CH:237-252 handleProp: name validated against KNOWN_CLUSTER_PROPS
\* (CH:240, OCP:147); message enqueued on /overseer/queue (CH:251).
\* The handler returns without waiting for the write.
ClientSetClusterProp(v) ==
    /\ v \in PropVals
    /\ stateQueue' = Append(stateQueue, [type |-> "clusterprop", val |-> v])
    /\ UNCHANGED <<zkVars, csVars, createMsgs, nodeCores, ocpVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Overseer ClusterStateUpdater (OV:338-386 processMessage), FIFO.          *)
(***************************************************************************)

\* OV:377-378 CLUSTERPROP -> handleProp OV:388-404.
Overseer_HandleProp ==
    /\ stateQueue /= <<>>
    /\ Head(stateQueue).type = "clusterprop"
    /\ LET msg == Head(stateQueue) IN
       \* OV:392-394: val == null -> m.remove(name) else m.put(name, val)
       \* OV:397-400: setData/create /clusterprops.json
       zkLegacyFalse' = (msg.val = "false")
    /\ stateQueue' = Tail(stateQueue)
    /\ UNCHANGED <<csVars, createMsgs, nodeCores, ocpVars, targetFired>>

\* OV:365-366 CREATESHARD -> createShard OV:557-579.
Overseer_CreateShard ==
    /\ stateQueue /= <<>>
    /\ Head(stateQueue).type = "createshard"
    /\ LET msg == Head(stateQueue) IN
       \* OV:561-562: if slice == null create it (CONSTRUCTION); else log error
       csSlices' = csSlices \cup {<<msg.coll, msg.slice>>}
    /\ stateQueue' = Tail(stateQueue)
    /\ UNCHANGED <<zkVars, csColls, replicaCnn, nextCnn, createMsgs, nodeCores, ocpVars, targetFired>>

\* OV:369-370 CREATECOLLECTION -> buildCollection OV:430-...
Overseer_BuildCollection ==
    /\ stateQueue /= <<>>
    /\ Head(stateQueue).type = "createcollection"
    /\ LET msg == Head(stateQueue) IN
       IF msg.coll \in csColls
         THEN UNCHANGED <<csColls, csSlices>>              \* OV:433-436 already exists
         ELSE /\ csColls'  = csColls \cup {msg.coll}       \* OV:438-...
              /\ csSlices' = csSlices \cup {<<msg.coll, s>> : s \in msg.slices}
    /\ stateQueue' = Tail(stateQueue)
    /\ UNCHANGED <<zkVars, replicaCnn, nextCnn, createMsgs, nodeCores, ocpVars, targetFired>>

\* OV:371-372 ADDREPLICA -> createReplica OV:408-428.
Overseer_CreateReplica ==
    /\ stateQueue /= <<>>
    /\ Head(stateQueue).type = "addreplica"
    /\ LET msg == Head(stateQueue) IN
       IF <<msg.coll, msg.slice>> \notin csSlices
         THEN UNCHANGED <<replicaCnn, nextCnn>>            \* OV:414-418 invalid slice
         ELSE \* OV:420-426: coreNodeName = Assign.assignNode(...); put replica (state DOWN)
              /\ replicaCnn' = [replicaCnn EXCEPT ![msg.core] = nextCnn]
              /\ nextCnn'    = nextCnn + 1
    /\ stateQueue' = Tail(stateQueue)
    /\ UNCHANGED <<zkVars, csColls, csSlices, createMsgs, nodeCores, ocpVars, targetFired>>

\* OV:339-344 STATE: isLegacy(clusterProps) ? updateState : updateStateNew.
\* The Overseer's cached clusterProps (OV:104) is refreshed only by OV's own
\* handleProp (OV:401), and OV is the only writer, so it equals zkLegacyFalse.
Overseer_UpdateState ==
    /\ stateQueue /= <<>>
    /\ Head(stateQueue).type = "state"
    /\ LET msg == Head(stateQueue) IN
       IF zkLegacyFalse /\ <<msg.coll, msg.slice>> \notin csSlices
         THEN UNCHANGED <<replicaCnn, nextCnn>>            \* OV:604-616 updateStateNew: no such slice
         ELSE \* OV:641-651 updateState: coreNodeName from message, else the
              \* already-registered one, else Assign.assignNode
              IF replicaCnn[msg.core] /= NULL
                THEN UNCHANGED <<replicaCnn, nextCnn>>
                ELSE IF msg.cnn /= NULL
                       THEN /\ replicaCnn' = [replicaCnn EXCEPT ![msg.core] = msg.cnn]
                            /\ UNCHANGED nextCnn
                       ELSE /\ replicaCnn' = [replicaCnn EXCEPT ![msg.core] = nextCnn]
                            /\ nextCnn'    = nextCnn + 1
    /\ stateQueue' = Tail(stateQueue)
    /\ UNCHANGED <<zkVars, csColls, csSlices, createMsgs, nodeCores, ocpVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* OCP: task pickup                                                         *)
(***************************************************************************)

\* OCP:225-360 run loop: a work-queue head is handed to the thread pool
\* only if checkExclusivity (OCP:362-376) allows it: no other task on the
\* same collection is in progress (collectionWip).
OverseerCollectionProcessor_Run(op) ==
    /\ ocpPc[op] = "queued"
    /\ ~\E o2 \in Ops \ {op} : Coll(o2) = Coll(op) /\ Running(o2)
    /\ ocpPc' = [ocpPc EXCEPT ![op] = FirstPc(op)]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores,
                   ocpIdx, ocpLegacy, ocpCnn, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* OCP.splitShard  OCP:1163-1550   (Scenario 1)                             *)
(* No read of legacyCloud and no CORE_NODE_NAME anywhere in splitShard.     *)
(***************************************************************************)

\* OCP:1316-1347, one iteration of the sub-shard loop:
\*   1326-1337 inQueue.offer(createshard, CONSTRUCTION)
\*   1339-1347 CREATE {NAME, COLLECTION, SHARD, property.*}; no coreNodeName
SplitShard_SendLeaderCreate(op) ==
    /\ ocpPc[op] = "sp_sendLeader"
    /\ LET L == OpSpec[op].leaders
           i == ocpIdx[op]
           e == L[i]
       IN /\ stateQueue' = Append(stateQueue,
                 [type |-> "createshard", coll |-> Coll(op), slice |-> e.slice])
          /\ createMsgs' = createMsgs \cup
                 {NewMsg(op, OpSpec[op].leaderNode, e.core, e.slice, NULL)}
          /\ IF i = Len(L)
               THEN /\ ocpPc'  = [ocpPc  EXCEPT ![op] = "sp_collectLeaders"]
                    /\ ocpIdx' = [ocpIdx EXCEPT ![op] = 1]
               ELSE /\ ocpIdx' = [ocpIdx EXCEPT ![op] = i + 1]
                    /\ UNCHANGED ocpPc
    /\ UNCHANGED <<zkVars, csVars, nodeCores, ocpLegacy, ocpCnn, targetFired>>

\* OCP:1350-1351 collectShardResponses(abortOnError=true,
\*   "SPLITSHARD failed to create subshard leaders") -> OCP:1614-1632
SplitShard_CollectLeaderResponses(op) ==
    /\ ocpPc[op] = "sp_collectLeaders"
    /\ LET ms == MsgsOf(op, SeqCores(OpSpec[op].leaders)) IN
       /\ \A m \in ms : Answered(m)
       /\ ocpPc' = [ocpPc EXCEPT ![op] =
                      IF \E m \in ms : m.status = "failed"
                        THEN "failed"                       \* OCP:1623-1628 throw
                        ELSE "sp_waitLeaderCnn"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores,
                   ocpIdx, ocpLegacy, ocpCnn, targetFired>>

\* OCP:1355-1359 waitForCoreNodeName(collection, nodeName, subShardName)
\* (OCP:1585-1612) for every sub-shard leader.  The WaitForState requests
\* (OCP:1360-1374), index split, and buffering (OCP:1376-1430) do not touch
\* the guard's operands and are not modeled (brief §3.2).
SplitShard_WaitForLeaderCoreNodeName(op) ==
    /\ ocpPc[op] = "sp_waitLeaderCnn"
    /\ \A c \in SeqCores(OpSpec[op].leaders) : replicaCnn[c] /= NULL
    /\ ocpPc'  = [ocpPc EXCEPT ![op] =
                    IF Len(OpSpec[op].replicas) = 0 THEN "sp_collectReplicas"  \* repFactor = 1 (OCP:1433)
                    ELSE "sp_sendReplica"]
    /\ ocpIdx' = [ocpIdx EXCEPT ![op] = 1]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores,
                   ocpLegacy, ocpCnn, targetFired>>

\* OCP:1450-1486, one (i, j) iteration of the replica loop:
\*   1440-1453 nodeList = live nodes minus the parent leader's node, shuffled
\*   1466-1486 CREATE {NAME, COLLECTION, SHARD, [async], property.*}; no coreNodeName
SplitShard_SendReplicaCreate(op, n) ==
    /\ ocpPc[op] = "sp_sendReplica"
    /\ n \in Nodes \ {OpSpec[op].leaderNode}
    /\ LET e == OpSpec[op].replicas[ocpIdx[op]] IN
       createMsgs' = createMsgs \cup {NewMsg(op, n, e.core, e.slice, NULL)}
    /\ ocpPc' = [ocpPc EXCEPT ![op] = "sp_waitReplicaCnn"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, nodeCores, ocpIdx, ocpLegacy, ocpCnn, targetFired>>

\* OCP:1488 waitForCoreNodeName(collection, subShardNodeName, shardName),
\* OCP:1585-1612: polls clusterstate; throws "Could not find coreNodeName"
\* after its retries if the core never registers.
SplitShard_WaitForReplicaCoreNodeName(op) ==
    /\ ocpPc[op] = "sp_waitReplicaCnn"
    /\ LET k == ocpIdx[op]
           e == OpSpec[op].replicas[k]
       IN \/ /\ replicaCnn[e.core] /= NULL                 \* OCP:1599-1600 found
             /\ IF k = Len(OpSpec[op].replicas)
                  THEN /\ ocpPc' = [ocpPc EXCEPT ![op] = "sp_collectReplicas"]
                       /\ UNCHANGED ocpIdx
                  ELSE /\ ocpPc'  = [ocpPc  EXCEPT ![op] = "sp_sendReplica"]
                       /\ ocpIdx' = [ocpIdx EXCEPT ![op] = k + 1]
          \/ /\ replicaCnn[e.core] = NULL                  \* OCP:1611 retries exhausted
             /\ \E m \in MsgsOf(op, {e.core}) : m.status = "failed"
             /\ ocpPc' = [ocpPc EXCEPT ![op] = "failed"]
             /\ UNCHANGED ocpIdx
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores, ocpLegacy, ocpCnn, targetFired>>

\* OCP:1503-1505 collectShardResponses(abortOnError=true,
\*   "SPLITSHARD failed to create subshard replicas ..."). The commit and
\* updateshardstate steps (OCP:1507-1543) are not modeled.
SplitShard_CollectReplicaResponses(op) ==
    /\ ocpPc[op] = "sp_collectReplicas"
    /\ LET ms == MsgsOf(op, SeqCores(OpSpec[op].replicas)) IN
       /\ \A m \in ms : Answered(m)
       /\ ocpPc' = [ocpPc EXCEPT ![op] =
                      IF \E m \in ms : m.status = "failed" THEN "failed" ELSE "done"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores,
                   ocpIdx, ocpLegacy, ocpCnn, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* OCP.createCollection  OCP:2019-2201   (Scenario 2)                       *)
(***************************************************************************)

\* OCP:2103 isLegacyCloud = Overseer.isLegacy(zkStateReader.getClusterProps())
\* -- the single read of legacyCloud for the whole task (live ZK, ZSR:643-654).
CreateCollection_ReadLegacy(op) ==
    /\ ocpPc[op] = "cc_readLegacy"
    /\ ocpLegacy' = [ocpLegacy EXCEPT ![op] = IsLegacy]
    /\ ocpPc'     = [ocpPc EXCEPT ![op] = "cc_enqueue"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores, ocpIdx, ocpCnn, targetFired>>

\* OCP:2105-2107 createConfNode; inQueue.offer(create collection message)
CreateCollection_EnqueueCollection(op) ==
    /\ ocpPc[op] = "cc_enqueue"
    /\ stateQueue' = Append(stateQueue,
           [type |-> "createcollection", coll |-> Coll(op), slices |-> CCSlices(op)])
    /\ ocpPc' = [ocpPc EXCEPT ![op] = "cc_waitCreated"]
    /\ UNCHANGED <<zkVars, csVars, createMsgs, nodeCores, ocpIdx, ocpLegacy, ocpCnn, targetFired>>

\* OCP:2109-2118 poll until the collection appears in clusterstate.
\* (The 30 s timeout branch, OCP:2117-2118, throws before any CREATE and is
\* not modeled.)
CreateCollection_WaitCreated(op) ==
    /\ ocpPc[op] = "cc_waitCreated"
    /\ Coll(op) \in csColls
    /\ ocpPc'  = [ocpPc  EXCEPT ![op] = "cc_core"]
    /\ ocpIdx' = [ocpIdx EXCEPT ![op] = 1]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores, ocpLegacy, ocpCnn, targetFired>>

CCNextAfterCore(op, i) ==
    IF i = Len(OpSpec[op].cores)
      THEN /\ ocpPc'  = [ocpPc EXCEPT ![op] =
                           IF ocpLegacy[op] THEN "cc_responses"     \* OCP:2179 skip
                           ELSE "cc_waitReplicas"]                   \* OCP:2179-2181
           /\ ocpIdx' = [ocpIdx EXCEPT ![op] = 1]
      ELSE /\ ocpIdx' = [ocpIdx EXCEPT ![op] = i + 1]
           /\ UNCHANGED ocpPc

\* OCP:2125-2176, one core iteration, legacy branch (isLegacyCloud = true):
\*   2151-2163 params {NAME, COLL_CONF, COLLECTION, SHARD, numShards, property.*}
\*   2171-2172 shardHandler.submit(sreq) immediately; no coreNodeName.
CreateCollection_SubmitLegacyCreate(op) ==
    /\ ocpPc[op] = "cc_core"
    /\ ocpLegacy[op]
    /\ LET i == ocpIdx[op]
           e == OpSpec[op].cores[i]
       IN /\ createMsgs' = createMsgs \cup {NewMsg(op, e.node, e.core, e.slice, NULL)}
          /\ CCNextAfterCore(op, i)
    /\ UNCHANGED <<zkVars, stateQueue, csVars, nodeCores, ocpLegacy, ocpCnn, targetFired>>

\* OCP:2125-2176, one core iteration, non-legacy branch:
\*   2138-2149 inQueue.offer(ADDREPLICA, state DOWN)  ("in the new mode,
\*             create the replica in clusterstate prior to creating the core")
\*   2173-2175 coresToCreate.put(coreName, sreq)  -- not sent yet
CreateCollection_EnqueueAddReplica(op) ==
    /\ ocpPc[op] = "cc_core"
    /\ ~ocpLegacy[op]
    /\ LET i == ocpIdx[op]
           e == OpSpec[op].cores[i]
       IN /\ stateQueue' = Append(stateQueue,
                 [type |-> "addreplica", coll |-> Coll(op), slice |-> e.slice, core |-> e.core])
          /\ CCNextAfterCore(op, i)
    /\ UNCHANGED <<zkVars, csVars, createMsgs, nodeCores, ocpLegacy, ocpCnn, targetFired>>

\* OCP:2181 waitToSeeReplicasInState(collectionName, coresToCreate.keySet())
\* OCP:2203-2230 (30 s timeout throws before any send; not modeled).
CreateCollection_WaitToSeeReplicasInState(op) ==
    /\ ocpPc[op] = "cc_waitReplicas"
    /\ \A c \in SeqCores(OpSpec[op].cores) : replicaCnn[c] /= NULL
    /\ ocpPc'  = [ocpPc  EXCEPT ![op] = "cc_submit"]
    /\ ocpIdx' = [ocpIdx EXCEPT ![op] = 1]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores, ocpLegacy, ocpCnn, targetFired>>

\* OCP:2182-2186 for each coresToCreate entry:
\*   sreq.params.set(CORE_NODE_NAME, replicas.get(core).getName()); submit
CreateCollection_SubmitNonLegacyCreate(op) ==
    /\ ocpPc[op] = "cc_submit"
    /\ LET i == ocpIdx[op]
           e == OpSpec[op].cores[i]
       IN /\ createMsgs' = createMsgs \cup
                 {NewMsg(op, e.node, e.core, e.slice, replicaCnn[e.core])}
          /\ IF i = Len(OpSpec[op].cores)
               THEN /\ ocpPc'  = [ocpPc  EXCEPT ![op] = "cc_responses"]
                    /\ ocpIdx' = [ocpIdx EXCEPT ![op] = 1]
               ELSE /\ ocpIdx' = [ocpIdx EXCEPT ![op] = i + 1]
                    /\ UNCHANGED ocpPc
    /\ UNCHANGED <<zkVars, stateQueue, csVars, nodeCores, ocpLegacy, ocpCnn, targetFired>>

\* OCP:2190 processResponses(results, shardHandler) -- waits for all
\* responses, records failures, does not abort.
CreateCollection_ProcessResponses(op) ==
    /\ ocpPc[op] = "cc_responses"
    /\ \A m \in MsgsOf(op, SeqCores(OpSpec[op].cores)) : Answered(m)
    /\ ocpPc' = [ocpPc EXCEPT ![op] = "done"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores,
                   ocpIdx, ocpLegacy, ocpCnn, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* OCP.addReplica  OCP:2232-2329   (Scenario 2)                             *)
(***************************************************************************)

\* OCP:2278 if(!Overseer.isLegacy(zkStateReader.getClusterProps())) -- the
\* single read of legacyCloud for this task.
\*   non-legacy: 2279-2286 inQueue.offer(ADDREPLICA, state DOWN), then wait (2287)
\*   legacy:     skip to the send; params carry no coreNodeName
\* The read and the ADDREPLICA offer are one step: the only state between
\* them is the queue position of ADDREPLICA, which TargetCheck never reads.
AddReplica_ReadLegacy(op) ==
    /\ ocpPc[op] = "ar_readLegacy"
    /\ ocpLegacy' = [ocpLegacy EXCEPT ![op] = IsLegacy]
    /\ IF IsLegacy
         THEN /\ ocpPc' = [ocpPc EXCEPT ![op] = "ar_send"]
              /\ UNCHANGED stateQueue
         ELSE /\ stateQueue' = Append(stateQueue,
                    [type |-> "addreplica", coll |-> Coll(op),
                     slice |-> OpSpec[op].slice, core |-> OpSpec[op].core])
              /\ ocpPc' = [ocpPc EXCEPT ![op] = "ar_waitCnn"]
    /\ UNCHANGED <<zkVars, csVars, createMsgs, nodeCores, ocpIdx, ocpCnn, targetFired>>

\* OCP:2287 params.set(CORE_NODE_NAME,
\*   waitToSeeReplicasInState(collection, [coreName]).get(coreName).getName())
AddReplica_WaitToSeeReplicasInState(op) ==
    /\ ocpPc[op] = "ar_waitCnn"
    /\ replicaCnn[OpSpec[op].core] /= NULL
    /\ ocpCnn' = [ocpCnn EXCEPT ![op] = replicaCnn[OpSpec[op].core]]
    /\ ocpPc'  = [ocpPc EXCEPT ![op] = "ar_send"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores, ocpIdx, ocpLegacy, targetFired>>

\* OCP:2291-2318 params {ACTION=CREATE, NAME, COLL_CONF, COLLECTION, SHARD,
\* [dataDir, instanceDir], property.*} + the cnn set at 2287 (if any);
\* sendShardRequest(node, params) OCP:2318.
AddReplica_SendShardRequest(op) ==
    /\ ocpPc[op] = "ar_send"
    /\ createMsgs' = createMsgs \cup
           {NewMsg(op, OpSpec[op].node, OpSpec[op].core, OpSpec[op].slice, ocpCnn[op])}
    /\ ocpPc' = [ocpPc EXCEPT ![op] = "ar_collect"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, nodeCores, ocpIdx, ocpLegacy, ocpCnn, targetFired>>

\* OCP:2320-2321 collectShardResponses(abortOnError=true, "ADDREPLICA failed ...")
AddReplica_CollectShardResponses(op) ==
    /\ ocpPc[op] = "ar_collect"
    /\ LET ms == MsgsOf(op, {OpSpec[op].core}) IN
       /\ \A m \in ms : Answered(m)
       /\ ocpPc' = [ocpPc EXCEPT ![op] =
                      IF \E m \in ms : m.status = "failed" THEN "failed" ELSE "done"]
    /\ UNCHANGED <<zkVars, stateQueue, csVars, createMsgs, nodeCores,
                   ocpIdx, ocpLegacy, ocpCnn, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* TARGET: receiving node handles CoreAdmin CREATE                          *)
(* CAH.handleRequestBody CAH:153-194 -> handleRequestInternal CAH:197-201   *)
(*   -> handleCreateAction CAH:543-608                                      *)
(***************************************************************************)
TargetCheck(m) ==
    /\ m \in createMsgs
    /\ m.status = "sent"
    \* CAH:545-546 buildCoreDescriptor (CAH:500-534): the request's
    \* coreNodeName (CAH:493) / property.coreNodeName (CAH:511-518) become the
    \* CloudDescriptor's coreNodeName (CloudDescriptor:55); m.cnn models both.
    /\ IF m.core \in nodeCores[m.node]
         THEN \* CAH:547-551 "Core with name ... already exists" (not the target)
              /\ createMsgs' = (createMsgs \ {m}) \cup {[m EXCEPT !.status = "failed"]}
              /\ UNCHANGED <<stateQueue, nodeCores, targetFired>>
       ELSE IF /\ ZkControllerPresent(m.node)                \* CAH:557
               /\ ~IsLegacy                                   \* CAH:558 live ZK read (ZSR:643-654)
               /\ m.cnn = NULL                                \* CAH:559
         THEN \* CAH:560 throw SolrException(SERVER_ERROR, "non legacy mode
              \* coreNodeName missing"); CAH:582-608 unregister + rethrow as
              \* BAD_REQUEST with the L560 exception as cause.
              /\ targetFired' = TRUE
              /\ createMsgs'  = (createMsgs \ {m}) \cup {[m EXCEPT !.status = "failed"]}
              /\ UNCHANGED <<stateQueue, nodeCores>>
         ELSE \* guard passed (or legacy): continue to CAH:565
              /\ createMsgs' = (createMsgs \ {m}) \cup {[m EXCEPT !.status = "admitted"]}
              /\ UNCHANGED <<stateQueue, nodeCores, targetFired>>
    /\ UNCHANGED <<zkVars, csVars, ocpVars>>

\* Continuation of handleCreateAction after the guard.
\* CAH:565 coreContainer.preRegisterInZk(dcore) -> ZKC:1396-1430 preRegister:
\*   ZKC:1403 checkStateInZk (ZKC:1432-1452) re-reads legacyCloud from ZK:
\*     non-legacy: ZKC:1436 `assert coreNodeName != null`, then waits up to
\*     3 s for the replica in clusterstate, else throws (ZKC:1449-1451).
\*     These are other checks, not the target.
\*   ZKC:1408-1410 setCoreNodeName if null
\*   ZKC:1411 publish(cd, DOWN) -> /overseer/queue STATE message
\* CAH:569-573 create + register the core.  The later waits inside
\* preRegister (doGetShardIdAndNodeNameProcess) and core loading do not
\* touch the guard's operands.
CoreAdminHandler_PreRegisterInZk(m) ==
    /\ m \in createMsgs
    /\ m.status = "admitted"
    /\ IF ~IsLegacy /\ (m.cnn = NULL \/ replicaCnn[m.core] = NULL)
         THEN \* ZKC:1436 assert / ZKC:1449-1451 no_such_replica -> CAH:582-608
              /\ createMsgs' = (createMsgs \ {m}) \cup {[m EXCEPT !.status = "failed"]}
              /\ UNCHANGED <<stateQueue, nodeCores>>
         ELSE /\ stateQueue' = Append(stateQueue,
                     [type |-> "state", coll |-> m.coll, slice |-> m.slice,
                      core |-> m.core, cnn |-> m.cnn])
              /\ nodeCores'  = [nodeCores EXCEPT ![m.node] = @ \cup {m.core}]
              /\ createMsgs' = (createMsgs \ {m}) \cup {[m EXCEPT !.status = "ok"]}
    /\ UNCHANGED <<zkVars, csVars, ocpVars, targetFired>>

----------------------------------------------------------------------------
(* Next-state relation *)

OcpStep ==
    \E op \in Ops :
        \/ OverseerCollectionProcessor_Run(op)
        \/ op \in SplitOps /\
             \/ SplitShard_SendLeaderCreate(op)
             \/ SplitShard_CollectLeaderResponses(op)
             \/ SplitShard_WaitForLeaderCoreNodeName(op)
             \/ \E n \in Nodes : SplitShard_SendReplicaCreate(op, n)
             \/ SplitShard_WaitForReplicaCoreNodeName(op)
             \/ SplitShard_CollectReplicaResponses(op)
        \/ op \in CCOps /\
             \/ CreateCollection_ReadLegacy(op)
             \/ CreateCollection_EnqueueCollection(op)
             \/ CreateCollection_WaitCreated(op)
             \/ CreateCollection_SubmitLegacyCreate(op)
             \/ CreateCollection_EnqueueAddReplica(op)
             \/ CreateCollection_WaitToSeeReplicasInState(op)
             \/ CreateCollection_SubmitNonLegacyCreate(op)
             \/ CreateCollection_ProcessResponses(op)
        \/ op \in AROps /\
             \/ AddReplica_ReadLegacy(op)
             \/ AddReplica_WaitToSeeReplicasInState(op)
             \/ AddReplica_SendShardRequest(op)
             \/ AddReplica_CollectShardResponses(op)

OverseerStep ==
    \/ Overseer_HandleProp
    \/ Overseer_CreateShard
    \/ Overseer_BuildCollection
    \/ Overseer_CreateReplica
    \/ Overseer_UpdateState

\* All reactive / deterministic steps (not bounded in MC).
SystemNext ==
    \/ OcpStep
    \/ OverseerStep
    \/ \E m \in createMsgs : TargetCheck(m)
    \/ \E m \in createMsgs : CoreAdminHandler_PreRegisterInZk(m)

AllQuiet ==
    /\ \A op \in Ops : ocpPc[op] \in {"done", "failed"}
    /\ stateQueue = <<>>
    /\ \A m \in createMsgs : Answered(m)

\* Stop after the target fires (keeps counterexamples short) or when every
\* task has finished; otherwise a stuck state shows up as a deadlock.
Terminating ==
    /\ targetFired \/ AllQuiet
    /\ UNCHANGED vars

Next ==
    \/ /\ ~targetFired
       /\ \/ SystemNext
          \/ \E v \in PropVals : ClientSetClusterProp(v)
    \/ Terminating

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
(* Invariants *)

StateMsgs ==
    [type : {"clusterprop"}, val : PropVals]
    \cup [type : {"createshard"}, coll : STRING, slice : STRING]
    \cup [type : {"createcollection"}, coll : STRING, slices : SUBSET STRING]
    \cup [type : {"addreplica"}, coll : STRING, slice : STRING, core : STRING]
    \cup [type : {"state"}, coll : STRING, slice : STRING, core : STRING, cnn : Nat]

TypeOK ==
    /\ zkLegacyFalse \in BOOLEAN
    /\ \A i \in DOMAIN stateQueue : stateQueue[i] \in StateMsgs
    /\ csColls \subseteq STRING
    /\ replicaCnn \in [AllCores -> Nat]
    /\ nextCnn \in Nat \ {0}
    /\ \A m \in createMsgs :
         /\ m.op \in Ops /\ m.node \in Nodes /\ m.core \in AllCores
         /\ m.cnn \in Nat /\ m.status \in {"sent", "admitted", "ok", "failed"}
    /\ nodeCores \in [Nodes -> SUBSET AllCores]
    /\ ocpPc \in [Ops -> Pcs]
    /\ ocpIdx \in [Ops -> Nat \ {0}]
    /\ ocpLegacy \in [Ops -> BOOLEAN]
    /\ ocpCnn \in [Ops -> Nat]
    /\ targetFired \in BOOLEAN

\* Target oracle: CAH:560 is never thrown.
TargetSafe == ~targetFired

\* A CREATE carries only a coreNodeName that its sender read from
\* clusterstate for that core (OCP:2184, OCP:2287).  coreNodeNames are
\* assigned once per core and never removed in this model.
CnnFromClusterState ==
    \A m \in createMsgs : m.cnn /= NULL => replicaCnn[m.core] = m.cnn

\* Temporary sanity (tla-patterns §2): must be VIOLATED with all counters 0.
TargetReached == ~(~targetFired /\ \E m \in createMsgs : m.status = "sent")

----------------------------------------------------------------------------
(* Workload-shaped default constants for base.cfg: ShardSplitTest's
   splitByUniqueKeyTest splits collection1/shard1 (2 replicas, sliceCount=2,
   shardCount=4) with no legacyCloud set.  MC.tla defines its own. *)
WorkloadNodes == {"n1", "n2"}
WorkloadOpSpec ==
    [op \in {"split"} |->
       [kind |-> "split", coll |-> "collection1", leaderNode |-> "n1",
        leaders  |-> << [core |-> "collection1_shard1_0_replica1", slice |-> "shard1_0"],
                        [core |-> "collection1_shard1_1_replica1", slice |-> "shard1_1"] >>,
        replicas |-> << [core |-> "collection1_shard1_0_replica2", slice |-> "shard1_0"],
                        [core |-> "collection1_shard1_1_replica2", slice |-> "shard1_1"] >>]]
WorkloadColls  == {"collection1"}
BaseConstraint == Len(stateQueue) <= 4   \* keeps base.cfg finite (unbounded CLUSTERPROP)
WorkloadSlices == {<<"collection1", "shard1">>}

=============================================================================
