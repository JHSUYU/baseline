------------------------------- MODULE Trace -------------------------------
\* Trace validation spec for solr-adhoc-k3 (Category A: single linear trace).
\*
\* Replays an NDJSON trace emitted by the instrumented MigrateRouteKeyTest
\* (all jetties run in one JVM, so one tracer writes one totally ordered file)
\* against base.tla.  Field names and trigger points: instrumentation-spec.md.
\*
\* Every wrapper:  match event -> call the base action -> validate post-state
\* fields the harness captured -> advance the cursor l.
\* One silent action: OverseerWatchRefresh (the Overseer's ZK watch firing has
\* no hook in Solr code we instrument); it is only allowed directly before an
\* OCP event that reads the cached view, and only when that event cannot be
\* consumed on the current view.

EXTENDS base, Json, IOUtils, Sequences, TLC

\* ============================================================================
\* Trace loading
\* ============================================================================

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

\* ============================================================================
\* Cursor
\* ============================================================================

VARIABLE l

traceVars == <<vars, l>>

logline == TraceLog[l]

IsEvent(e) == l <= Len(TraceLog) /\ logline.event = e
Has(f) == f \in DOMAIN logline
Step == l' = l + 1

\* Every role name the harness writes in "core" is a modeled core.
ASSUME \A k \in 1..Len(TraceLog) :
         "core" \in DOMAIN TraceLog[k] => TraceLog[k].core \in Cores \cup {NoCore}

\* ============================================================================
\* Bootstrap
\* ============================================================================

\* The workload starts after BasicDistributedZkTest set up collection1 with
\* default cluster properties.  The trace's first event may carry the
\* legacyCloud value observed at start ("initLegacyCloud"); base Init uses
\* InitLegacyCloud from Trace.cfg, which must agree.
TraceInit ==
    /\ Init
    /\ l = 1
    /\ (Has("initLegacyCloud") => clusterProps = logline.initLegacyCloud)

\* ============================================================================
\* Admin client
\* ============================================================================

\* The trace's value, not FlipValues, decides what was written.
TraceCollectionsHandlerHandleProp ==
    /\ IsEvent("CollectionsHandlerHandleProp")
    /\ CollectionsHandlerHandleProp(logline.val)
    /\ stateQ'[Len(stateQ')].val = logline.val
    /\ Step

\* ============================================================================
\* ClusterStateUpdater
\* ============================================================================

TraceClusterStateUpdaterStep ==
    /\ IsEvent("ClusterStateUpdaterStep")
    /\ stateQ # <<>>
    /\ Head(stateQ).op = logline.op
    /\ Head(stateQ).core = logline.core
    /\ Head(stateQ).coll = logline.coll
    /\ ClusterStateUpdaterStep
    \* post-state, by operation (fields per instrumentation-spec.md 2.1)
    /\ logline.op \in {"state", "addreplica"} =>
         \E r \in cs'.replicas :
            /\ r.coll = logline.coll /\ r.core = logline.core
            /\ r.cnn = logline.cnn                   \* replica name after processing
            /\ r.nn = logline.hasNodeName
    /\ logline.op = "clusterprop" =>
         /\ clusterProps' = logline.legacyCloud
         /\ cupLegacy' = logline.cupLegacy
    /\ logline.op = "createcollection" => logline.coll \in cs'.colls
    /\ logline.op = "createshard" => <<logline.coll, logline.shard>> \in cs'.slices
    /\ logline.op = "routingrule" => cs'.rule
    /\ Step

\* ============================================================================
\* OCP
\* ============================================================================

TraceOcpStartTask ==
    /\ IsEvent("OcpStartTask")
    /\ opIdx <= Len(Workload) /\ Workload[opIdx] = logline.op
    /\ OcpStartTask
    /\ Step

TraceOcpTaskEnd ==
    /\ IsEvent("OcpTaskEnd")
    /\ ocp.result = logline.result
    /\ OcpTaskEnd
    /\ Step

TraceCCReadLegacy ==
    /\ IsEvent("CCReadLegacy")
    /\ ocp.coll = logline.coll
    /\ CCReadLegacy
    /\ ocp'.pc = "cc_offer"
    /\ ocp'.snap = logline.isLegacy
    /\ Step

TraceCCCreateConfNodeAndOffer ==
    /\ IsEvent("CCCreateConfNodeAndOffer")
    /\ ocp.coll = logline.coll
    /\ CCCreateConfNodeAndOffer
    /\ Step

TraceCCWaitCreated ==
    /\ IsEvent("CCWaitCreated")
    /\ ocp.coll = logline.coll
    /\ CCWaitCreated
    /\ Step

TraceCCPrepareCore ==
    /\ IsEvent("CCPrepareCore")
    /\ CCCore(ocp.coll) = logline.core
    /\ CCPrepareCore
    /\ (req'[logline.core].st = "sent") = logline.submitted   \* legacy: submitted now
    /\ Step

TraceCCWaitReplicasAndSubmit ==
    /\ IsEvent("CCWaitReplicasAndSubmit")
    /\ CCCore(ocp.coll) = logline.core
    /\ CCWaitReplicasAndSubmit
    /\ req'[logline.core].cnn = logline.cnn
    /\ Step

TraceCCProcessResponses ==
    /\ IsEvent("CCProcessResponses")
    /\ CCCore(ocp.coll) = logline.core
    /\ CCProcessResponses
    /\ (ocp'.result = "ok") = logline.ok
    /\ Step

TraceARReadLegacy ==
    /\ IsEvent("ARReadLegacy")
    /\ ARReadLegacy
    /\ IsLegacy(clusterProps) = logline.isLegacy
    /\ Step

TraceARWaitReplica ==
    /\ IsEvent("ARWaitReplica")
    /\ ARWaitReplica
    /\ ocp'.cnn = logline.cnn
    /\ Step

TraceARSend ==
    /\ IsEvent("ARSend")
    /\ ARSend
    /\ req'["addR"].hasCNN = logline.hasCNN
    /\ Step

TraceARCollect ==
    /\ IsEvent("ARCollect")
    /\ ARCollect
    /\ (ocp'.result = "ok") = logline.ok
    /\ Step

TraceCSOfferSlice ==
    /\ IsEvent("CSOfferSlice") /\ CSOfferSlice /\ Step

TraceCSWaitSlice ==
    /\ IsEvent("CSWaitSlice") /\ CSWaitSlice /\ Step

TraceCSSendCreate ==
    /\ IsEvent("CSSendCreate")
    /\ CSSendCreate
    /\ req'["implR1"].hasCNN = logline.hasCNN
    /\ Step

TraceCSProcessResponses ==
    /\ IsEvent("CSProcessResponses")
    /\ CSProcessResponses
    /\ (ocp'.result = "ok") = logline.ok
    /\ Step

TraceMigrateStart ==
    /\ IsEvent("MigrateStart") /\ MigrateStart
    /\ ocp'.pc = "mk_buffer"
    /\ Step

TraceMigRequestBufferUpdates ==
    /\ IsEvent("MigRequestBufferUpdates") /\ MigRequestBufferUpdates /\ Step

TraceMigOfferRoutingRule ==
    /\ IsEvent("MigOfferRoutingRule") /\ MigOfferRoutingRule /\ Step

TraceMigWaitRoutingRule ==
    /\ IsEvent("MigWaitRoutingRule") /\ MigWaitRoutingRule /\ Step

TraceMigCreateTempCollection ==
    /\ IsEvent("MigCreateTempCollection") /\ MigCreateTempCollection /\ Step

\* outcome in {"found", "npe", "leaderTimeout"}
WFCNNOutcome(pcAfterFound) ==
    CASE logline.outcome = "found" ->
           /\ ocp'.pc = pcAfterFound
           /\ \E r \in ReplicasOf(ocpView, "temp") : r.core = logline.core /\ r.cnn = logline.cnn
      [] logline.outcome \in {"npe", "leaderTimeout"} ->
           ocp'.pc = "end" /\ ocp'.result = "error"

TraceMigWaitForCoreNodeName1 ==
    /\ IsEvent("MigWaitForCoreNodeName1")
    /\ logline.core = "tmpR1"
    /\ MigWaitForCoreNodeName1
    /\ WFCNNOutcome("mk_waitState1")
    /\ Step

TraceMigWaitForState1 ==
    /\ IsEvent("MigWaitForState1") /\ MigWaitForState1 /\ Step

TraceMigSplit ==
    /\ IsEvent("MigSplit") /\ MigSplit /\ Step

TraceMigSendCreateReplica2 ==
    /\ IsEvent("MigSendCreateReplica2")
    /\ MigSendCreateReplica2
    /\ req'["tmpR2"].hasCNN = logline.hasCNN
    /\ Step

TraceMigCollectCreateReplica2 ==
    /\ IsEvent("MigCollectCreateReplica2")
    /\ MigCollectCreateReplica2
    /\ (req["tmpR2"].st = "ok") = logline.ok
    /\ Step

TraceMigWaitForCoreNodeName2 ==
    /\ IsEvent("MigWaitForCoreNodeName2")
    /\ logline.core = "tmpR2"
    /\ MigWaitForCoreNodeName2
    /\ WFCNNOutcome("mk_rest")
    /\ Step

TraceMigFinish ==
    /\ IsEvent("MigFinish") /\ MigFinish /\ Step

\* ============================================================================
\* Node
\* ============================================================================

\* The target.  legacyCloud is the value the node read at :561; hasCNN is
\* whether the descriptor's coreNodeName at :562 was non-null; fired is
\* whether :563 executed.
TraceTargetCheck ==
    /\ IsEvent("TargetCheck")
    /\ TargetCheck(logline.core)
    /\ clusterProps = logline.legacyCloud
    /\ req[logline.core].hasCNN = logline.hasCNN
    /\ targetFired' = logline.fired
    /\ (logline.fired = FALSE) =>
         (req'[logline.core].st = "prereg") = ~logline.duplicate
    /\ Step

TraceNodeCheckStateInZk ==
    /\ IsEvent("NodeCheckStateInZk")
    /\ NodeCheckStateInZk(logline.core)
    /\ IsLegacy(clusterProps) = logline.isLegacy
    /\ (req'[logline.core].st = "publish") = logline.ok
    /\ Step

TraceNodeCheckStateInZkTimeout ==
    /\ IsEvent("NodeCheckStateInZkTimeout")
    /\ NodeCheckStateInZkTimeout(logline.core)
    /\ Step

TraceNodePublishDown ==
    /\ IsEvent("NodePublishDown")
    /\ NodePublishDown(logline.core)
    /\ stateQ'[Len(stateQ')].cnn = logline.cnn
    /\ Step

TraceNodeWaitForShardId ==
    /\ IsEvent("NodeWaitForShardId")
    /\ NodeWaitForShardId(logline.core)
    /\ logline.core \in nodeCores'
    /\ Step

\* ============================================================================
\* Silent action
\* ============================================================================

\* Events whose enabling condition reads the OCP's cached clusterstate.
ViewReadingEvents ==
    {"CCReadLegacy", "CCWaitCreated", "CCWaitReplicasAndSubmit", "ARReadLegacy",
     "ARWaitReplica", "CSWaitSlice", "MigrateStart", "MigWaitRoutingRule",
     "MigWaitForCoreNodeName1", "MigWaitForCoreNodeName2"}

SilentOverseerWatchRefresh ==
    /\ l <= Len(TraceLog)
    /\ logline.event \in ViewReadingEvents
    /\ OverseerWatchRefresh
    /\ UNCHANGED l

\* ============================================================================
\* Next / properties
\* ============================================================================

TraceConsume ==
    \/ TraceCollectionsHandlerHandleProp
    \/ TraceClusterStateUpdaterStep
    \/ TraceOcpStartTask
    \/ TraceOcpTaskEnd
    \/ TraceCCReadLegacy
    \/ TraceCCCreateConfNodeAndOffer
    \/ TraceCCWaitCreated
    \/ TraceCCPrepareCore
    \/ TraceCCWaitReplicasAndSubmit
    \/ TraceCCProcessResponses
    \/ TraceARReadLegacy
    \/ TraceARWaitReplica
    \/ TraceARSend
    \/ TraceARCollect
    \/ TraceCSOfferSlice
    \/ TraceCSWaitSlice
    \/ TraceCSSendCreate
    \/ TraceCSProcessResponses
    \/ TraceMigrateStart
    \/ TraceMigRequestBufferUpdates
    \/ TraceMigOfferRoutingRule
    \/ TraceMigWaitRoutingRule
    \/ TraceMigCreateTempCollection
    \/ TraceMigWaitForCoreNodeName1
    \/ TraceMigWaitForState1
    \/ TraceMigSplit
    \/ TraceMigSendCreateReplica2
    \/ TraceMigCollectCreateReplica2
    \/ TraceMigWaitForCoreNodeName2
    \/ TraceMigFinish
    \/ TraceTargetCheck
    \/ TraceNodeCheckStateInZk
    \/ TraceNodeCheckStateInZkTimeout
    \/ TraceNodePublishDown
    \/ TraceNodeWaitForShardId

\* The silent refresh fires only when no wrapper can consume the next event
\* (keeps the search deterministic: no dead branches that refreshed too early).
TraceNext ==
    \/ TraceConsume
    \/ /\ ~ENABLED TraceConsume
       /\ SilentOverseerWatchRefresh

TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

TraceView == <<vars, l>>

TraceMatched == <>(l > Len(TraceLog))

TraceAlias == [l |-> l,
               event |-> IF l <= Len(TraceLog) THEN logline.event ELSE "END",
               clusterProps |-> clusterProps, stateQ |-> stateQ, cs |-> cs,
               ocpView |-> ocpView, ocp |-> ocp, req |-> req, targetFired |-> targetFired]

=============================================================================
