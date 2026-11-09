------------------------------- MODULE base -------------------------------
\* Base specification for the ad hoc coordination target solr-adhoc-k3.
\*
\* Target: solr/core/src/java/org/apache/solr/handler/admin/CoreAdminHandler.java:563
\*   CoreAdminHandler.handleCreateAction(SolrQueryRequest, SolrQueryResponse)
\*   throw new SolrException(SERVER_ERROR, "non legacy mode coreNodeName missing ...")
\*   guard (:560-562):  zkController != null
\*                   /\ !Overseer.isLegacy(zkStateReader.getClusterProps())
\*                   /\ dcore.getCloudDescriptor().getCoreNodeName() == null
\*
\* Category A (distributed / message-passing).  The three guard operands live in
\*   - ZooKeeper /clusterprops.json (legacyCloud)          -> clusterProps
\*   - the parameters of the core-admin CREATE RPC         -> req[c].hasCNN
\*   - the receiving node (SolrCloud mode)                 -> ZkControllerPresent
\*
\* Pinned tree: lucene-solr @ e75b9596abd442edaf16a4ec460a7c08afec550c.
\* Paths below are relative to solr/core/src/java/org/apache/solr/ unless they
\* start with solr/.  "OCP" = cloud/OverseerCollectionProcessor.java.
\*
\* Components modeled:
\*   OCP task thread       one client issues the Workload operations in order
\*                         (the workload test is sequential); per-op actions are
\*                         split at every ZK read/write and RPC send/receive.
\*   ClusterStateUpdater   Overseer state-queue consumer (cloud/Overseer.java:205-265).
\*   Nodes                 handleCreateAction + ZkController.preRegister, per core.
\*   Admin client          Collections API CLUSTERPROP (Scenario 3 flip).
\*
\* Abstractions (see modeling-brief.md 3.2):
\*   - Index split / merge / buffering / leader election are opaque single steps.
\*   - Wait loops with timeouts are modeled as "enabled when the awaited condition
\*     holds"; timeouts that can only make the operation fail before the target
\*     are not modeled, except checkStateInZk's 3 s timeout (its own action).
\*   - The ClusterStateUpdater writes after every message (the real loop may batch
\*     several messages into one write, :240-263); batching only hides states.
\*   - Node-side ZkStateReader views are not modeled separately: every node-side
\*     wait polls for a positive condition, so lag only delays it.  The OCP's view
\*     (ocpView) IS modeled because waitForCoreNodeName (OCP:1578-1581) can NPE on
\*     a stale view (Scenario 1 masking branch).

EXTENDS Naturals, Sequences, FiniteSets, TLC

\* ============================================================================
\* CONSTANTS
\* ============================================================================

\* Sequence of client operations, issued one after another (MigrateRouteKeyTest
\* creates the target collection and then calls MIGRATE; see
\* solr/core/src/test/org/apache/solr/cloud/MigrateRouteKeyTest.java).
\* Elements: "CreateTarget", "Migrate", "CreateShard", "AddReplica".
CONSTANT Workload

\* Value of legacyCloud in /clusterprops.json when the workload starts:
\* "absent" (default, no property), "true", or "false".
CONSTANT InitLegacyCloud

\* Values a concurrent CLUSTERPROP legacyCloud=<v> may write (Scenario 3).
\* "absent" means val=null, i.e. the property is removed (cloud/Overseer.java:399).
CONSTANT FlipValues

PropValue == {"absent", "true", "false"}

\* Named workloads (cfg files cannot write tuples; use  Workload <- WL_...).
WL_Workload    == <<"CreateTarget", "Migrate">>      \* MigrateRouteKeyTest as written
WL_CreateShard == <<"CreateShard">>                  \* Scenario 2 variant
WL_ModeAware   == <<"CreateTarget", "AddReplica">>   \* Scenario 3: mode-aware senders only

ASSUME InitLegacyCloud \in PropValue
ASSUME FlipValues \subseteq PropValue
ASSUME \A i \in 1..Len(Workload) :
         Workload[i] \in {"CreateTarget", "Migrate", "CreateShard", "AddReplica"}

\* Every node in the cluster runs in SolrCloud mode, so
\* coreContainer.getZkController() != null  (CoreAdminHandler.java:560).
ZkControllerPresent == TRUE

\* ============================================================================
\* STATIC CONFIGURATION OF THE MODELED CORES
\* ============================================================================

\* New cores that some OCP operation asks a node to CREATE.
\*   tgtR1  migrate_..._targetCollection_shard1_replica1   (createCollection, test)
\*   tmpR1  split_shard2_temp_shard1_shard1_replica1        (createCollection, OCP:1855)
\*   tmpR2  split_shard2_temp_shard1_shard1_replica2        (migrateKey,  OCP:1897-1905)
\*   implR1 <implicit coll>_<new shard>_replica1            (createShard, OCP:1094-1121)
\*   addR   collection1_shard1_replica<N>                   (addReplica,  OCP:2267-2283)
Cores == {"tgtR1", "tmpR1", "tmpR2", "implR1", "addR"}

\* Cores that exist before the workload starts (collection1 has 2 shards,
\* BasicDistributedZkTest; an implicit collection exists only for Scenario 2).
PreCores == {"c1s1", "c1s2", "implA"}

Colls == {"coll1", "target", "temp", "impl"}
Shards == {"shard1", "shard2", "shardA", "shardB"}

CoreColl ==
    ("tgtR1" :> "target") @@ ("tmpR1" :> "temp") @@ ("tmpR2" :> "temp")
    @@ ("implR1" :> "impl") @@ ("addR" :> "coll1")

\* createCollection uses numShards=1 for both target and temp collections
\* (MigrateRouteKeyTest.createCollection NUM_SLICES=1; OCP:1847 NUM_SLICES=1),
\* so the slice is "shard1" (Overseer.getShardNames).
CoreShard ==
    ("tgtR1" :> "shard1") @@ ("tmpR1" :> "shard1") @@ ("tmpR2" :> "shard1")
    @@ ("implR1" :> "shardB") @@ ("addR" :> "shard1")

\* Which OCP code path sends the CREATE for each core (diagnostic only).
Sender ==
    ("tgtR1" :> "createCollection") @@ ("tmpR1" :> "createCollection")
    @@ ("tmpR2" :> "migrateKey") @@ ("implR1" :> "createShard")
    @@ ("addR" :> "addReplica")

\* The single core createCollection creates (repFactor=1, numShards=1).
CCCore(coll) == IF coll = "target" THEN "tgtR1" ELSE "tmpR1"

HasOp(o) == \E i \in 1..Len(Workload) : Workload[i] = o

\* cloud/Overseer.java:1282-1284
\*   isLegacy(m) == !"false".equals(m.get("legacyCloud"))
IsLegacy(v) == v # "false"

NoCore == "none"

\* ============================================================================
\* VARIABLES
\* ============================================================================

VARIABLE clusterProps   \* ZK /clusterprops.json legacyCloud value (ZkStateReader.java:643-652)
VARIABLE cupLegacy      \* ClusterStateUpdater cached isLegacy(clusterProps) (Overseer.java:104,119,342,407)
VARIABLE stateQ         \* Overseer state queue /overseer/queue (FIFO), Seq of messages
VARIABLE cs             \* clusterstate in ZK: [colls, slices, replicas, rule]
VARIABLE ocpView        \* the Overseer's ZkStateReader cached clusterstate (read by OCP)
VARIABLE ocp            \* OCP task-thread state (program counter + locals)
VARIABLE opIdx          \* index of the current Workload operation
VARIABLE req            \* per-core CREATE RPC: [st, hasCNN, cnn]
VARIABLE nodeCores      \* cores successfully created on their node
VARIABLE targetFired    \* TRUE once CoreAdminHandler.java:563 executed
VARIABLE firedCore      \* diagnostic: which core's CREATE fired the target

zkVars   == <<clusterProps, cupLegacy, stateQ, cs>>
ocpVars  == <<ocpView, ocp, opIdx>>
nodeVars == <<req, nodeCores>>
tgtVars  == <<targetFired, firedCore>>
vars     == <<zkVars, ocpVars, nodeVars, tgtVars>>

\* ============================================================================
\* HELPERS
\* ============================================================================

\* State-queue message.  All fields present so that records are comparable.
\*   op  in {"state", "createcollection", "addreplica", "createshard",
\*           "routingrule", "clusterprop"}
\*   cnn  0 = no coreNodeName
Msg(op, coll, shard, core, cnn, val) ==
    [op |-> op, coll |-> coll, shard |-> shard, core |-> core, cnn |-> cnn, val |-> val]

\* A CREATE RPC record.  st:
\*   "none"      not sent
\*   "sent"      submitted by the OCP, not yet handled by the node
\*   "prereg"    node passed :552-567, in ZkController.preRegister (:1396)
\*   "publish"   checkStateInZk passed (:1403), about to publish DOWN (:1412)
\*   "waitShard" published DOWN, in doGetShardIdAndNodeNameProcess (:1424)
\*   "ok"        core created and registered, success response
\*   "err"       error response
Req(st, h, k) == [st |-> st, hasCNN |-> h, cnn |-> k]
Done(c) == req[c].st \in {"ok", "err"}

Max(S) == CHOOSE x \in S : \A y \in S : x >= y

ReplicasOf(s, coll) == {r \in s.replicas : r.coll = coll}

\* cloud/Assign.java:51-68  assignNode: "core_node" + (max + 1)
AssignNode(s, coll) ==
    LET ns == {r.cnn : r \in ReplicasOf(s, coll)}
    IN IF ns = {} THEN 1 ELSE Max(ns) + 1

Replica(coll, shard, cnn, core, nn) ==
    [coll |-> coll, shard |-> shard, cnn |-> cnn, core |-> core, nn |-> nn]

\* --- ClusterStateUpdater operations (cloud/Overseer.java) -------------------

\* updateState  (Overseer.java:631-730)
\*   :647-656  coreNodeName = message CNN, else getAssignedCoreNodeName (by
\*             node_name + core, :867-884), else Assign.assignNode.
\*   getAssignedCoreNodeName dereferences replica node_name without a null check
\*   (:878 nodeName.equals(msgNodeName)); a replica with no node_name throws an
\*   NPE that processMessage's caller swallows, skipping the message (:248-256).
\*   (Over-approximation: we take the NPE whenever any replica of the collection
\*   lacks node_name; the real iteration may find the match first.)
\*   :697-717  the replica is (re)written with the message props, which include
\*             node_name (ZkController.java:1069-1076 NODE_NAME_PROP).
UpdateStateNPE(s, m) ==
    /\ m.cnn = 0
    /\ \E r \in ReplicasOf(s, m.coll) : ~r.nn

AssignedCnn(s, m) ==
    IF \E r \in ReplicasOf(s, m.coll) : r.nn /\ r.core = m.core
    THEN (CHOOSE r \in ReplicasOf(s, m.coll) : r.nn /\ r.core = m.core).cnn
    ELSE AssignNode(s, m.coll)

UpdateState(s, m) ==
    IF UpdateStateNPE(s, m) THEN s
    ELSE LET k == IF m.cnn # 0 THEN m.cnn ELSE AssignedCnn(s, m)
         IN [s EXCEPT !.replicas =
                 {r \in @ : ~(r.coll = m.coll /\ r.cnn = k)}
                 \cup {Replica(m.coll, m.shard, k, m.core, TRUE)}]

\* updateStateNew  (Overseer.java:610-627): requires the slice to exist.
UpdateStateNew(s, m) ==
    IF <<m.coll, m.shard>> \notin s.slices THEN s     \* :619-622 "No such slice exists"
    ELSE UpdateState(s, m)                             \* :625

\* buildCollection  (Overseer.java:436-453): adds the collection and its
\* slices (numShards=1 -> "shard1"), no replicas.
BuildCollection(s, m) ==
    IF m.coll \in s.colls THEN s                       \* :439-442 already exists
    ELSE [s EXCEPT !.colls = @ \cup {m.coll},
                   !.slices = @ \cup {<<m.coll, "shard1">>}]

\* createReplica  (Overseer.java:414-434): pre-registers a replica WITHOUT
\* node_name (only core, base_url, state: :427-431).
CreateReplica(s, m) ==
    IF <<m.coll, m.shard>> \notin s.slices THEN s     \* :419-423 Invalid Collection/Slice
    ELSE [s EXCEPT !.replicas = @ \cup
            {Replica(m.coll, m.shard, AssignNode(s, m.coll), m.core, FALSE)}]  \* :426-432

\* createShard (state side)  (Overseer.java:563-580): empty slice.
CreateShardState(s, m) ==
    [s EXCEPT !.slices = @ \cup {<<m.coll, m.shard>>}]

\* addRoutingRule  (Overseer.java:482-...)
AddRoutingRule(s, m) == [s EXCEPT !.rule = TRUE]

\* --- OCP helpers -------------------------------------------------------------

\* Abort the current OCP operation: an exception propagates to
\* processMessage's catch (OCP:575-583), which records it in the results.
Abort == ocp' = [ocp EXCEPT !.pc = "end", !.result = "error"]

\* OCP waitForCoreNodeName  (OCP:1567-1594) over the OCP's cached view.
\*   :1578  nodeName = replica.getStr(node_name)   (may be null)
\*   :1581  nodeName.equals(msgNodeName)           -> NPE if null
\* Outcome "npe" if some replica of the collection lacks node_name (the
\* iteration visits it before or instead of the match), "found" if the core is
\* visible with node_name, otherwise "wait" (sleep 1 s and retry, :1586-1590).
WFCNN(coll, core) ==
    IF \E r \in ReplicasOf(ocpView, coll) : ~r.nn THEN "npe"
    ELSE IF \E r \in ReplicasOf(ocpView, coll) : r.core = core /\ r.nn THEN "found"
    ELSE "wait"

\* ============================================================================
\* INITIAL STATE
\* ============================================================================

InitColls  == {"coll1"} \cup (IF HasOp("CreateShard") THEN {"impl"} ELSE {})
InitSlices == {<<"coll1", "shard1">>, <<"coll1", "shard2">>}
              \cup (IF HasOp("CreateShard") THEN {<<"impl", "shardA">>} ELSE {})
InitReplicas ==
    {Replica("coll1", "shard1", 1, "c1s1", TRUE), Replica("coll1", "shard2", 2, "c1s2", TRUE)}
    \cup (IF HasOp("CreateShard") THEN {Replica("impl", "shardA", 1, "implA", TRUE)} ELSE {})

InitCS == [colls |-> InitColls, slices |-> InitSlices,
           replicas |-> InitReplicas, rule |-> FALSE]

InitOcp == [pc |-> "idle", snap |-> TRUE, coll |-> "none", ret |-> "end",
            cnn |-> 0, result |-> "none"]

Init ==
    /\ clusterProps = InitLegacyCloud
    /\ cupLegacy    = IsLegacy(InitLegacyCloud)
    /\ stateQ       = <<>>
    /\ cs           = InitCS
    /\ ocpView      = InitCS
    /\ ocp          = InitOcp
    /\ opIdx        = 1
    /\ req          = [c \in Cores |-> Req("none", FALSE, 0)]
    /\ nodeCores    = {}
    /\ targetFired  = FALSE
    /\ firedCore    = NoCore

\* ============================================================================
\* ADMIN CLIENT: CLUSTERPROP  (Scenario 3)
\* ============================================================================

\* CollectionsHandler.handleProp  (handler/admin/CollectionsHandler.java:238-252)
\*   :240-243  name must be in KNOWN_CLUSTER_PROPS (OCP:147: legacyCloud, urlScheme)
\*   :245-251  enqueue {operation: clusterprop, name, val} on the STATE queue
\*             (not the OCP work queue, so OCP per-collection exclusivity,
\*             OCP:362-380, does not order it with collection operations).
CollectionsHandlerHandleProp(v) ==
    /\ stateQ' = Append(stateQ, Msg("clusterprop", "none", "none", NoCore, 0, v))
    /\ UNCHANGED <<clusterProps, cupLegacy, cs, ocpVars, nodeVars, tgtVars>>

\* ============================================================================
\* OVERSEER: ClusterStateUpdater  (cloud/Overseer.java:205-265, 339-412)
\* ============================================================================

\* One iteration of the main loop for the head message.
\*   :217      head = stateUpdateQueue.peek(true)
\*   :234-235  reader.updateClusterState(true); clusterState = reader.getClusterState()
\*             -- forced refresh of the Overseer's reader, which the OCP shares
\*   :240-241  processMessage(clusterState, message, operation)
\*   :258-260  workQueue.offer(head); stateUpdateQueue.poll()
\*   :263      updateZkStates(clusterState)
ClusterStateUpdaterStep ==
    /\ stateQ # <<>>
    /\ LET m == Head(stateQ) IN
       /\ stateQ' = Tail(stateQ)
       /\ ocpView' = cs                                          \* :234
       /\ CASE m.op = "state" ->                                 \* :341-346
                 /\ cs' = IF cupLegacy THEN UpdateState(cs, m)   \* :342-343
                          ELSE UpdateStateNew(cs, m)             \* :344-345
                 /\ UNCHANGED <<clusterProps, cupLegacy>>
            [] m.op = "createshard" ->                           \* :367-368
                 /\ cs' = CreateShardState(cs, m)
                 /\ UNCHANGED <<clusterProps, cupLegacy>>
            [] m.op = "createcollection" ->                      \* :371-372
                 /\ cs' = BuildCollection(cs, m)
                 /\ UNCHANGED <<clusterProps, cupLegacy>>
            [] m.op = "addreplica" ->                            \* :373-374
                 /\ cs' = CreateReplica(cs, m)
                 /\ UNCHANGED <<clusterProps, cupLegacy>>
            [] m.op = "routingrule" ->                           \* :375-376
                 /\ cs' = AddRoutingRule(cs, m)
                 /\ UNCHANGED <<clusterProps, cupLegacy>>
            [] m.op = "clusterprop" ->                           \* :379-380 handleProp
                 \* :395-412  read-modify-write of /clusterprops.json, then
                 \*           refresh the cached clusterProps (:407)
                 /\ clusterProps' = m.val                        \* :399-405
                 /\ cupLegacy' = IsLegacy(m.val)                 \* :407
                 /\ UNCHANGED cs
    /\ UNCHANGED <<ocp, opIdx, nodeVars, tgtVars>>

\* ZK watch on /clusterstate.json fires on the Overseer node and its
\* ZkStateReader picks up the latest clusterstate
\* (solr/solrj/.../common/cloud/ZkStateReader.java createClusterStateWatchersAndUpdate).
OverseerWatchRefresh ==
    /\ ocpView # cs
    /\ ocpView' = cs
    /\ UNCHANGED <<zkVars, ocp, opIdx, nodeVars, tgtVars>>

\* ============================================================================
\* OCP: task dispatch
\* ============================================================================

\* OverseerCollectionProcessor.run / processMessage dispatch (OCP:534-585).
\* The client issues the next Workload operation only after the previous one
\* returned (the test calls are synchronous).
OcpStartTask ==
    /\ ocp.pc = "idle"
    /\ opIdx <= Len(Workload)
    /\ LET o == Workload[opIdx] IN
       ocp' = CASE o = "CreateTarget" ->                         \* OCP:538-539
                     [InitOcp EXCEPT !.pc = "cc_read", !.coll = "target", !.ret = "end"]
                [] o = "Migrate"      -> [InitOcp EXCEPT !.pc = "mg_start"]   \* OCP:559-560
                [] o = "CreateShard"  -> [InitOcp EXCEPT !.pc = "cs_offer"]   \* OCP:553-554
                [] o = "AddReplica"   -> [InitOcp EXCEPT !.pc = "ar_read"]    \* OCP:563-564
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* Operation returned (success or exception recorded in results, OCP:575-583).
OcpTaskEnd ==
    /\ ocp.pc = "end"
    /\ ocp' = [ocp EXCEPT !.pc = "idle"]
    /\ opIdx' = opIdx + 1
    /\ UNCHANGED <<zkVars, ocpView, nodeVars, tgtVars>>

\* ============================================================================
\* OCP: createCollection  (OCP:2027-2209)   -- Scenario 3, and Scenario 1 path
\* ============================================================================

\* :2029-2031  clusterState.hasCollection(name) on the snapshot passed in
\*             (merged here: the snapshot is the OCP's cached view)
\* :2037-2109  argument validation (all pass for the modeled messages)
\* :2111       boolean isLegacyCloud = Overseer.isLegacy(zkStateReader.getClusterProps())
\*             -- fresh ZK read; the decision is cached in the task for the rest
\*                of the operation (Scenario 3 TOCTOU snapshot).
CCReadLegacy ==
    /\ ocp.pc = "cc_read"
    /\ IF ocp.coll \in ocpView.colls
       THEN Abort                                                \* :2030 already exists
       ELSE ocp' = [ocp EXCEPT !.snap = IsLegacy(clusterProps), !.pc = "cc_offer"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :2113  createConfNode (writes /collections/<name> configName; the config set
\*        exists, so the isLegacyCloud-dependent error branch :2373-2377 is not taken)
\* :2115  Overseer.getInQueue(...).offer(message)  -- createcollection
CCCreateConfNodeAndOffer ==
    /\ ocp.pc = "cc_offer"
    /\ stateQ' = Append(stateQ, Msg("createcollection", ocp.coll, "shard1", NoCore, 0, "none"))
    /\ ocp' = [ocp EXCEPT !.pc = "cc_waitCreated"]
    /\ UNCHANGED <<clusterProps, cupLegacy, cs, ocpView, opIdx, nodeVars, tgtVars>>

\* :2117-2126  poll zkStateReader.getClusterState() until the collection exists
\*             (30 s timeout -> SERVER_ERROR, not modeled)
CCWaitCreated ==
    /\ ocp.pc = "cc_waitCreated"
    /\ ocp.coll \in ocpView.colls
    /\ ocp' = [ocp EXCEPT !.pc = "cc_prepare"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* Loop body for the single (slice, replica) pair  :2133-2183
\*   :2147-2157  if(!isLegacyCloud) offer ADDREPLICA {collection, shard, core,
\*               state=down, base_url}  (pre-registration)
\*   :2160-2176  CREATE params: action, name, collection.configName,
\*               collection, shard, numShards (+ async, property.*) -- no coreNodeName
\*   :2178-2182  if(isLegacyCloud) shardHandler.submit(...) NOW  (no coreNodeName)
\*               else coresToCreate.put(coreName, sreq)
CCPrepareCore ==
    /\ ocp.pc = "cc_prepare"
    /\ LET c == CCCore(ocp.coll) IN
       IF ~ocp.snap
       THEN /\ stateQ' = Append(stateQ,
                   Msg("addreplica", ocp.coll, "shard1", c, 0, "none"))   \* :2148-2156
            /\ ocp' = [ocp EXCEPT !.pc = "cc_waitReplicas"]
            /\ UNCHANGED req
       ELSE /\ req' = [req EXCEPT ![c] = Req("sent", FALSE, 0)]           \* :2179-2180
            /\ ocp' = [ocp EXCEPT !.pc = "cc_responses"]
            /\ UNCHANGED stateQ
    /\ UNCHANGED <<clusterProps, cupLegacy, cs, ocpView, opIdx, nodeCores, tgtVars>>

\* Non-legacy branch  :2187-2195
\*   :2189  waitToSeeReplicasInState(collection, coresToCreate.keySet())
\*          (OCP:2211-2237, polls the cached view for a replica with that core)
\*   :2190-2192  sreq.params.set(coreNodeName, replica.getName())
\*   :2193  shardHandler.submit(...)
CCWaitReplicasAndSubmit ==
    /\ ocp.pc = "cc_waitReplicas"
    /\ LET c == CCCore(ocp.coll) IN
       /\ \E r \in ReplicasOf(ocpView, ocp.coll) : r.core = c
       /\ LET r == CHOOSE r \in ReplicasOf(ocpView, ocp.coll) : r.core = c IN
          req' = [req EXCEPT ![c] = Req("sent", TRUE, r.cnn)]
    /\ ocp' = [ocp EXCEPT !.pc = "cc_responses"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeCores, tgtVars>>

\* :2197  processResponses(results, shardHandler) -- waits for every response,
\*        records failures, does NOT throw (OCP:2339-2347).  Then returns to caller.
CCProcessResponses ==
    /\ ocp.pc = "cc_responses"
    /\ Done(CCCore(ocp.coll))
    /\ ocp' = [ocp EXCEPT !.pc = ocp.ret,
                          !.result = IF req[CCCore(ocp.coll)].st = "ok" THEN "ok" ELSE "error"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* ============================================================================
\* OCP: addReplica  (OCP:2240-2337)   -- Scenario 3
\* ============================================================================

\* :2241-2283  collection / slice / live-node checks on the passed snapshot;
\*             coreName assigned as <coll>_<shard>_replica<N> (:2267-2283)
\* :2286       if(!Overseer.isLegacy(zkStateReader.getClusterProps()))  -- fresh read
\*   :2287-2294  offer ADDREPLICA (pre-registration)
ARReadLegacy ==
    /\ ocp.pc = "ar_read"
    /\ IF <<"coll1", "shard1">> \notin ocpView.slices
       THEN /\ Abort                                             \* :2248-2254
            /\ UNCHANGED stateQ
       ELSE IF ~IsLegacy(clusterProps)                           \* :2286
            THEN /\ stateQ' = Append(stateQ,
                        Msg("addreplica", "coll1", "shard1", "addR", 0, "none"))  \* :2287-2294
                 /\ ocp' = [ocp EXCEPT !.pc = "ar_waitReplica"]
            ELSE /\ ocp' = [ocp EXCEPT !.pc = "ar_send", !.cnn = 0]
                 /\ UNCHANGED stateQ
    /\ UNCHANGED <<clusterProps, cupLegacy, cs, ocpView, opIdx, nodeVars, tgtVars>>

\* :2295  params.set(coreNodeName, waitToSeeReplicasInState(...).get(coreName).getName())
ARWaitReplica ==
    /\ ocp.pc = "ar_waitReplica"
    /\ \E r \in ReplicasOf(ocpView, "coll1") : r.core = "addR"
    /\ LET r == CHOOSE r \in ReplicasOf(ocpView, "coll1") : r.core = "addR" IN
       ocp' = [ocp EXCEPT !.pc = "ar_send", !.cnn = r.cnn]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :2299-2329  readConfigName, CREATE params (name, conf, collection, shard, ...)
\* :2330-2331  setupAsyncRequest; sendShardRequest(node, params, shardHandler)
ARSend ==
    /\ ocp.pc = "ar_send"
    /\ req' = [req EXCEPT !["addR"] = Req("sent", ocp.cnn # 0, ocp.cnn)]
    /\ ocp' = [ocp EXCEPT !.pc = "ar_collect"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeCores, tgtVars>>

\* :2333-2334  collectShardResponses(results, abortOnError=true, ...) (OCP:1621-1639)
ARCollect ==
    /\ ocp.pc = "ar_collect"
    /\ Done("addR")
    /\ IF req["addR"].st = "err" THEN Abort                      \* :1631-1636 throw
       ELSE ocp' = [ocp EXCEPT !.pc = "end", !.result = "ok"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* ============================================================================
\* OCP: createShard  (OCP:1062-1130)   -- Scenario 2
\* ============================================================================

\* :1064-1077  parameter checks, node selection
\* :1079       Overseer.getInQueue(...).offer(message)   -- createshard (state side)
CSOfferSlice ==
    /\ ocp.pc = "cs_offer"
    /\ stateQ' = Append(stateQ, Msg("createshard", "impl", "shardB", NoCore, 0, "none"))
    /\ ocp' = [ocp EXCEPT !.pc = "cs_waitSlice"]
    /\ UNCHANGED <<clusterProps, cupLegacy, cs, ocpView, opIdx, nodeVars, tgtVars>>

\* :1081-1089  poll until getSlice(shard) != null (30 s timeout not modeled)
CSWaitSlice ==
    /\ ocp.pc = "cs_waitSlice"
    /\ <<"impl", "shardB">> \in ocpView.slices
    /\ ocp' = [ocp EXCEPT !.pc = "cs_send"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1094-1121  for j in 1..repFactor (repFactor=1): CREATE params name, conf,
\*             collection, shard, numShards, property.* -- never coreNodeName,
\*             never reads legacyCloud; shardHandler.submit (:1120)
CSSendCreate ==
    /\ ocp.pc = "cs_send"
    /\ req' = [req EXCEPT !["implR1"] = Req("sent", FALSE, 0)]
    /\ ocp' = [ocp EXCEPT !.pc = "cs_responses"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeCores, tgtVars>>

\* :1124  processResponses (does not throw)
CSProcessResponses ==
    /\ ocp.pc = "cs_responses"
    /\ Done("implR1")
    /\ ocp' = [ocp EXCEPT !.pc = "end",
                          !.result = IF req["implR1"].st = "ok" THEN "ok" ELSE "error"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* ============================================================================
\* OCP: migrate / migrateKey  (OCP:1706-1975)   -- Scenario 1 (workload path)
\* ============================================================================

\* migrate  :1706-1747
\*   :1712-1719  source / target collection must exist in the passed snapshot
\*   :1720-1736  compositeId routers; source slice for split.key "a/1!" is
\*               shard2 only, one target slice (one migrateKey call, :1743-1747)
MigrateStart ==
    /\ ocp.pc = "mg_start"
    /\ IF {"coll1", "target"} \subseteq ocpView.colls
       THEN ocp' = [ocp EXCEPT !.pc = "mk_buffer"]
       ELSE Abort                                                \* :1713, :1717
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* migrateKey  :1754-1801
\*   :1755-1766  temp collection exists? -> delete (it does not at start)
\*   :1771-1778  splitRange != null
\*   :1781       getLeaderRetry(target, shard1)
\*   :1788-1801  REQUESTBUFFERUPDATES to target leader; collectShardResponses
\*               (opaque: does not touch any guard operand)
MigRequestBufferUpdates ==
    /\ ocp.pc = "mk_buffer"
    /\ ocp' = [ocp EXCEPT !.pc = "mk_rule"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1803-1814  offer ADD_ROUTING_RULE on the state queue
MigOfferRoutingRule ==
    /\ ocp.pc = "mk_rule"
    /\ stateQ' = Append(stateQ, Msg("routingrule", "coll1", "shard2", NoCore, 0, "none"))
    /\ ocp' = [ocp EXCEPT !.pc = "mk_waitRule"]
    /\ UNCHANGED <<clusterProps, cupLegacy, cs, ocpView, opIdx, nodeVars, tgtVars>>

\* :1816-1833  poll the cached view until the rule is visible (60 s timeout
\*             -> "Could not add routing rule", not modeled)
MigWaitRoutingRule ==
    /\ ocp.pc = "mk_waitRule"
    /\ ocpView.rule
    /\ ocp' = [ocp EXCEPT !.pc = "mk_temp"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1838-1855  getLeaderRetry(source); readConfigName; props for temp
\*             collection (replicationFactor=1, numShards=1, createNodeSet =
\*             source leader node); createCollection(clusterState, props, results)
MigCreateTempCollection ==
    /\ ocp.pc = "mk_temp"
    /\ ocp' = [ocp EXCEPT !.pc = "cc_read", !.coll = "temp", !.ret = "mk_waitCNN1"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1857  clusterState = zkStateReader.getClusterState()
\* :1858  tempSourceSlice = ...getCollection(temp).getSlices().iterator().next()
\* :1859  getLeaderRetry(temp, shard1, 120000): a leader exists only if the temp
\*        replica1 core came up; if its CREATE failed this throws after 120 s.
\* :1861-1862  coreNodeName = waitForCoreNodeName(temp, sourceLeaderNode, replica1)
\*        (masking branch: NPE on a replica without node_name, OCP:1578-1581)
MigWaitForCoreNodeName1 ==
    /\ ocp.pc = "mk_waitCNN1"
    /\ IF req["tmpR1"].st # "ok"
       THEN Abort                                                \* :1859 getLeaderRetry timeout
       ELSE /\ WFCNN("temp", "tmpR1") # "wait"
            /\ IF WFCNN("temp", "tmpR1") = "npe"
               THEN Abort                                        \* :1581 NPE
               ELSE ocp' = [ocp EXCEPT !.pc = "mk_waitState1"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1864-1877  WaitForState(replica1 active) to the temp leader; collect (opaque)
MigWaitForState1 ==
    /\ ocp.pc = "mk_waitState1"
    /\ ocp' = [ocp EXCEPT !.pc = "mk_split"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1879-1893  SPLIT on the source leader into the temp core; collect (opaque)
MigSplit ==
    /\ ocp.pc = "mk_split"
    /\ ocp' = [ocp EXCEPT !.pc = "mk_sendCreate2"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1895-1905  CREATE replica2 of the temp collection on the target leader node:
\*   :1898  action=CREATE
\*   :1900  name=tempCollectionReplica2
\*   :1901  collection=temp
\*   :1902  shard=tempSourceSlice
\*   :1904  setupAsyncRequest (async only)
\*   :1905  sendShardRequest adds only qt (OCP:2006-2016)
\*   -- never reads legacyCloud, never pre-registers, never sets coreNodeName.
MigSendCreateReplica2 ==
    /\ ocp.pc = "mk_sendCreate2"
    /\ req' = [req EXCEPT !["tmpR2"] = Req("sent", FALSE, 0)]
    /\ ocp' = [ocp EXCEPT !.pc = "mk_collect2"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeCores, tgtVars>>

\* :1906-1908  collectShardResponses(results, abortOnError=true, "MIGRATE failed
\*             to create replica of temporary collection ...") (OCP:1621-1639)
MigCollectCreateReplica2 ==
    /\ ocp.pc = "mk_collect2"
    /\ Done("tmpR2")
    /\ IF req["tmpR2"].st = "err"
       THEN Abort                                                \* :1631-1636 throw
       ELSE ocp' = [ocp EXCEPT !.pc = "mk_waitCNN2"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1912-1913  waitForCoreNodeName(temp, targetLeaderNode, replica2)
MigWaitForCoreNodeName2 ==
    /\ ocp.pc = "mk_waitCNN2"
    /\ WFCNN("temp", "tmpR2") # "wait"
    /\ IF WFCNN("temp", "tmpR2") = "npe"
       THEN Abort                                                \* :1581 NPE
       ELSE ocp' = [ocp EXCEPT !.pc = "mk_rest"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* :1914-1974  WaitForState(replica2), MERGEINDEXES, REQUESTAPPLYUPDATES,
\*             delete temp collection (opaque; no guard operand touched)
MigFinish ==
    /\ ocp.pc = "mk_rest"
    /\ ocp' = [ocp EXCEPT !.pc = "end", !.result = "ok"]
    /\ UNCHANGED <<zkVars, ocpView, opIdx, nodeVars, tgtVars>>

\* ============================================================================
\* NODE: CoreAdminHandler.handleCreateAction + ZkController.preRegister
\* ============================================================================

\* TARGET.  CoreAdminHandler.handleCreateAction  (CoreAdminHandler.java:546-568)
\*   :550  dcore = buildCoreDescriptor(params, coreContainer)
\*         coreNodeName comes only from params coreNodeName / property.coreNodeName
\*         (:485-532; core/CoreDescriptor.java:169-188; cloud/CloudDescriptor.java:55)
\*   :552-556  core with this name already exists -> SERVER_ERROR (not the target)
\*   :560  coreContainer.getZkController() != null
\*   :561  !Overseer.isLegacy(getZkStateReader().getClusterProps())  -- fresh ZK read
\*   :562  dcore.getCloudDescriptor().getCoreNodeName() == null
\*   :563  throw new SolrException(SERVER_ERROR, "non legacy mode coreNodeName missing")
\*         -> caught at :585, unregister, rethrown as BAD_REQUEST (:611-613):
\*            the OCP sees an error response.
\*   :568  coreContainer.preRegisterInZk(dcore)  (CoreContainer.java:879-881)
TargetCheck(c) ==
    /\ req[c].st = "sent"
    /\ IF c \in nodeCores
       THEN /\ req' = [req EXCEPT ![c].st = "err"]               \* :552-556
            /\ UNCHANGED tgtVars
       ELSE IF /\ ZkControllerPresent                            \* :560
               /\ ~IsLegacy(clusterProps)                        \* :561
               /\ ~req[c].hasCNN                                 \* :562
            THEN /\ targetFired' = TRUE                          \* :563
                 /\ firedCore' = c
                 /\ req' = [req EXCEPT ![c].st = "err"]          \* :585-613
            ELSE /\ req' = [req EXCEPT ![c].st = "prereg"]       \* :568
                 /\ UNCHANGED tgtVars
    /\ UNCHANGED <<zkVars, ocpVars, nodeCores>>

\* ZkController.preRegister  (cloud/ZkController.java:1396-1429)
\*   :1398  coreNodeName = getCoreNodeName(cd)
\*   :1403  checkStateInZk(cd)  (:1432-1453)
\*     :1433  if (!Overseer.isLegacy(zkStateReader.getClusterProps()))  -- fresh read
\*     :1436  assert coreNodeName != null           (tests run with -ea)
\*     :1440-1449  poll up to 3 s for slice.getReplica(coreNodeName) != null
\*   :1408-1409  if CNN null, set it to getCoreNodeName(cd) (generic names: stays null)
NodeCheckStateInZk(c) ==
    /\ req[c].st = "prereg"
    /\ IF IsLegacy(clusterProps)                                  \* :1433
       THEN req' = [req EXCEPT ![c].st = "publish"]
       ELSE IF ~req[c].hasCNN
            THEN req' = [req EXCEPT ![c].st = "err"]             \* :1436 AssertionError
            ELSE /\ \E r \in cs.replicas :                       \* :1448
                      r.coll = CoreColl[c] /\ r.shard = CoreShard[c] /\ r.cnn = req[c].cnn
                 /\ req' = [req EXCEPT ![c].st = "publish"]
    /\ UNCHANGED <<zkVars, ocpVars, nodeCores, tgtVars>>

\* checkStateInZk 3 s timeout  (:1440-1451): the pre-registered replica is not
\* visible yet -> SERVER_ERROR "no_such_replica in clusterstate" (bounded in MC).
NodeCheckStateInZkTimeout(c) ==
    /\ req[c].st = "prereg"
    /\ ~IsLegacy(clusterProps)
    /\ req[c].hasCNN
    /\ ~\E r \in cs.replicas :
          r.coll = CoreColl[c] /\ r.shard = CoreShard[c] /\ r.cnn = req[c].cnn
    /\ req' = [req EXCEPT ![c].st = "err"]
    /\ UNCHANGED <<zkVars, ocpVars, nodeCores, tgtVars>>

\* :1412  publish(cd, DOWN, false, true)  (ZkController.java:1020-1083)
\*        state message carries core, node_name, shard, collection and
\*        coreNodeName (the request's, or null) (:1069-1078)
NodePublishDown(c) ==
    /\ req[c].st = "publish"
    /\ stateQ' = Append(stateQ, Msg("state", CoreColl[c], CoreShard[c], c, req[c].cnn, "down"))
    /\ req' = [req EXCEPT ![c].st = "waitShard"]
    /\ UNCHANGED <<clusterProps, cupLegacy, cs, ocpVars, nodeCores, tgtVars>>

\* :1421-1428  doGetShardIdAndNodeNameProcess (:1278-1287):
\*             waitForCoreNodeName (:1289-1318, CNN null only) and
\*             waitForShardId (:1324-1333): getShardId(coll, nodeName, core)
\*             matches node_name + core (ClusterState.java:197-215).
\* CoreAdminHandler.java:571-583  locator create, coreContainer.create,
\*             register; success response.
NodeWaitForShardId(c) ==
    /\ req[c].st = "waitShard"
    /\ \E r \in cs.replicas : r.coll = CoreColl[c] /\ r.core = c /\ r.nn
    /\ req' = [req EXCEPT ![c].st = "ok"]
    /\ nodeCores' = nodeCores \cup {c}
    /\ UNCHANGED <<zkVars, ocpVars, tgtVars>>

\* ============================================================================
\* NEXT
\* ============================================================================

OcpStep ==
    \/ OcpStartTask
    \/ OcpTaskEnd
    \/ CCReadLegacy
    \/ CCCreateConfNodeAndOffer
    \/ CCWaitCreated
    \/ CCPrepareCore
    \/ CCWaitReplicasAndSubmit
    \/ CCProcessResponses
    \/ ARReadLegacy
    \/ ARWaitReplica
    \/ ARSend
    \/ ARCollect
    \/ CSOfferSlice
    \/ CSWaitSlice
    \/ CSSendCreate
    \/ CSProcessResponses
    \/ MigrateStart
    \/ MigRequestBufferUpdates
    \/ MigOfferRoutingRule
    \/ MigWaitRoutingRule
    \/ MigCreateTempCollection
    \/ MigWaitForCoreNodeName1
    \/ MigWaitForState1
    \/ MigSplit
    \/ MigSendCreateReplica2
    \/ MigCollectCreateReplica2
    \/ MigWaitForCoreNodeName2
    \/ MigFinish

NodeStep(c) ==
    \/ TargetCheck(c)
    \/ NodeCheckStateInZk(c)
    \/ NodeCheckStateInZkTimeout(c)
    \/ NodePublishDown(c)
    \/ NodeWaitForShardId(c)

\* Once the target fired, the execution stops (counterexamples stay short).
Next ==
    /\ ~targetFired
    /\ \/ OcpStep
       \/ \E c \in Cores : NodeStep(c)
       \/ ClusterStateUpdaterStep
       \/ OverseerWatchRefresh
       \/ \E v \in FlipValues : CollectionsHandlerHandleProp(v)

Spec == Init /\ [][Next]_vars

\* ============================================================================
\* INVARIANTS
\* ============================================================================

ReqSt == {"none", "sent", "prereg", "publish", "waitShard", "ok", "err"}
OcpPc == {"idle", "end",
          "cc_read", "cc_offer", "cc_waitCreated", "cc_prepare", "cc_waitReplicas", "cc_responses",
          "ar_read", "ar_waitReplica", "ar_send", "ar_collect",
          "cs_offer", "cs_waitSlice", "cs_send", "cs_responses",
          "mg_start", "mk_buffer", "mk_rule", "mk_waitRule", "mk_temp", "mk_waitCNN1",
          "mk_waitState1", "mk_split", "mk_sendCreate2", "mk_collect2", "mk_waitCNN2", "mk_rest"}

TypeOK ==
    /\ clusterProps \in PropValue
    /\ cupLegacy \in BOOLEAN
    /\ \A i \in 1..Len(stateQ) :
         stateQ[i].op \in {"state", "createcollection", "addreplica",
                           "createshard", "routingrule", "clusterprop"}
    /\ cs.colls \subseteq Colls
    /\ cs.slices \subseteq Colls \X Shards
    /\ \A r \in cs.replicas : r.core \in Cores \cup PreCores /\ r.nn \in BOOLEAN
    /\ ocp.pc \in OcpPc
    /\ opIdx \in 1..(Len(Workload) + 1)
    /\ \A c \in Cores : req[c].st \in ReqSt /\ req[c].hasCNN \in BOOLEAN
    /\ nodeCores \subseteq Cores
    /\ targetFired \in BOOLEAN
    /\ firedCore \in Cores \cup {NoCore}

\* The oracle: CoreAdminHandler.java:563 is never executed.
TargetSafe == ~targetFired

\* Sanity (brief 5): a CREATE that carries a coreNodeName names a replica the
\* OCP pre-registered for that core (OCP:2189-2193, 2295).
CNNMatchesPreRegistration ==
    \A c \in Cores :
        (req[c].st # "none" /\ req[c].hasCNN) =>
            \E r \in cs.replicas :
                r.coll = CoreColl[c] /\ r.cnn = req[c].cnn /\ r.core = c

\* Sanity (brief 5): no CREATE is in flight for a collection / slice that is
\* absent from clusterstate (OCP:2117-2126, 1081-1089, 1857-1858).
NoCreateBeforeCollectionExists ==
    \A c \in Cores :
        req[c].st # "none" => <<CoreColl[c], CoreShard[c]>> \in cs.slices

\* Temporary reachability probe (tla-patterns.md 2): the negation of
\* "TargetCheck is enabled for some core".  TLC must VIOLATE it.
TargetCheckEnabled == \E c \in Cores : req[c].st = "sent"
TargetNotReached == ~TargetCheckEnabled

\* Second probe: the whole Workload completes with success (the last operation
\* returned "ok").  TLC must VIOLATE it under MC.cfg, which shows the migrate
\* path reaches replica2's TargetCheck and gets past it.
WorkloadNotCompleted == ~(opIdx > Len(Workload) /\ ocp.result = "ok")

=============================================================================
