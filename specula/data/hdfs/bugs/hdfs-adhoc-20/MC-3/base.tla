------------------------------- MODULE base -------------------------------
(***************************************************************************)
(* hdfs-adhoc-20: can the assert at BPOfferService.java:615 fail?           *)
(*                                                                         *)
(*   BPOfferService.updateActorStatesFromHeartbeat(actor, nnHaState)       *)
(*     614   if (bpServiceToActive == actor) {                             *)
(*     615     assert txid >= lastActiveClaimTxId;     <-- the target       *)
(*     616     lastActiveClaimTxId = txid;                                 *)
(*                                                                         *)
(* Property: TargetSafe == ~targetFired (adhoc-coordination Shared Rule 1).*)
(* Tree: /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-20/hadoop @ 734dd8a67cd *)
(*                                                                         *)
(* Category A (distributed / message-passing): the guard's operands come   *)
(* from remote NameNodes (heartbeat and versionRequest RPC responses)      *)
(* across NN crash/restart, edit-log durability and HA failover.  Every    *)
(* DataNode-side write of the operands holds the BPOfferService write lock *)
(* (BPOfferService.java:105-125), so each DN step below is one atomic      *)
(* action.  Each RPC is split into an NN-side snapshot action and a DN-side *)
(* processing action, because NN state can change in between.             *)
(*                                                                         *)
(* Path legend (all under hadoop-hdfs-project/hadoop-hdfs/src/main/java/   *)
(* org/apache/hadoop/hdfs/):                                               *)
(*   BPOfferService.java, BPServiceActor.java, BlockPoolManager.java,      *)
(*   DataNode.java              -> server/datanode/                        *)
(*   FSNamesystem.java, FSImage.java, FSEditLog.java, FSEditLogAsync.java, *)
(*   JournalSet.java, FileJournalManager.java, NameNode.java,             *)
(*   NameNodeRpcServer.java     -> server/namenode/                        *)
(*   HAState.java, ActiveState.java, StandbyState.java                     *)
(*                              -> server/namenode/ha/                     *)
(*   DatanodeManager.java       -> server/blockmanagement/                 *)
(*   QuorumJournalManager.java  -> qjournal/client/                        *)
(*   Journal.java               -> qjournal/server/                        *)
(*                                                                         *)
(* Modeling Brief: ../modeling-brief.md (Scenarios S1-S4, invariants §5). *)
(***************************************************************************)
EXTENDS Integers, FiniteSets, TLC

\* ============================================================================
\* CONSTANTS
\* ============================================================================

\* NameNodes of the (single) nameservice.  The DataNode's BPOfferService owns
\* one BPServiceActor per NN address (BPOfferService.java:139-142), and with an
\* unchanged NN list at most one live actor per address exists (refreshNNList
\* only adds addresses with no actor in bpServices, BPOfferService.java:148-162).
\* So an actor is identified by its NN: actor a talks to NameNode a.
CONSTANT NN

\* HAUtil.isHAEnabled(conf, nsId) (NameNode.java:1157).  FALSE for the
\* workload's MiniDFSCluster (one NN), TRUE for the HA Scenarios S2-S4.
CONSTANT HAEnabled

\* bpServiceToActive == null (BPOfferService.java:86).
CONSTANT Null

ASSUME HAEnabled \in BOOLEAN
ASSUME Null \notin NN
\* Non-HA nameservices have exactly one NameNode (NameNode.java:1196-1198).
ASSUME ~HAEnabled => Cardinality(NN) = 1

\* ============================================================================
\* VARIABLES
\* ============================================================================

\* ---- DataNode: the BPOfferService of the block pool (all Scenarios) ----
\* Guard operands (brief §4 "DN block-pool state").
VARIABLE bpServiceToActive    \* B: actor of the NN this DN accepts as ACTIVE, or Null.   BPOfferService.java:86
VARIABLE lastActiveClaimTxId  \* L: txid of the last accepted ACTIVE claim, init -1.     BPOfferService.java:103
\* Actor lifecycle (brief §4 "Actor lifecycle"): handshake vs heartbeat paths,
\* fresh actors, actor death.
VARIABLE aPhase               \* [NN -> {"INIT","VERSIONED","RUNNING","DEAD"}]
VARIABLE nsResp               \* [NN -> {"NONE","ACTIVE","STANDBY"}]: NamespaceInfo.getState() of the
                              \*   handshake's versionRequest, received but not yet applied
VARIABLE hbResp               \* [NN -> NoResp \cup HbResp]: heartbeat response in flight
                              \*   (at most one: synchronous RPC on the actor thread, BPServiceActor.java:711)

\* ---- NameNodes (brief §4 "NN edit-log state", "NN HA state") ----
VARIABLE nnPhase   \* [NN -> {"UP","STOPPING","DOWN"}]: UP = started and serving
                   \*   (NameNode.java:1181, NameNodeRpcServer.java:2371-2376); STOPPING = inside
                   \*   NameNode.stop() after exitState, RPC server still up (NameNode.java:1237-1244)
VARIABLE haState   \* [NN -> {"ACTIVE","STANDBY"}]: haContext.getState().getServiceState()
                   \*   (FSNamesystem.java:4506, 5699-5701).  OBSERVER is not modeled (brief §3.2).
VARIABLE fenced    \* [NN -> BOOLEAN]: NN still believes it is ACTIVE but another NN took a newer
                   \*   journal epoch (deposed active, S3).  Its next journal write fails (Journal.java:484-490)
VARIABLE written   \* [NN -> Nat]: FSEditLog.txid, the last *assigned* txid (FSEditLog.java:541, 567-569)
VARIABLE applied   \* [NN -> Nat]: FSImage.lastAppliedTxId (FSImage.java:775, 1569-1571)
VARIABLE durable   \* Nat: last txid of the durable edit log: the NN's local edits dir in non-HA,
                   \*   the JournalNode quorum in HA (brief §3.1 "shared durable stands for the JN quorum")

\* ---- DN <-> NN links (brief §4 "Links", S2/S4) ----
VARIABLE link      \* [NN -> BOOLEAN]

\* ---- Target ----
VARIABLE targetFired   \* the assert at BPOfferService.java:615 failed

\* ---- History (not implementation state; only read by RespFromSender) ----
VARIABLE maxHeldTxid   \* [NN -> Nat]: highest max(applied, written) NN n ever held while serving

dnVars   == <<bpServiceToActive, lastActiveClaimTxId, aPhase, nsResp, hbResp>>
nnVars   == <<nnPhase, haState, fenced, written, applied, durable>>
vars     == <<dnVars, nnVars, link, targetFired, maxHeldTxid>>

\* ============================================================================
\* HELPERS
\* ============================================================================

Max(x, y) == IF x >= y THEN x ELSE y

HAStates == {"ACTIVE", "STANDBY"}

\* No heartbeat response in flight.
NoResp == [state |-> "NONE", txid |-> -1]

\* FSImage.getCorrectLastAppliedOrWrittenTxId() = max(lastAppliedTxId,
\* editLog.getLastWrittenTxId()) (FSImage.java:1564-1567): the txid every
\* heartbeat reports (FSNamesystem.java:4505-4507).
ReportedTxid(n) == Max(applied[n], written[n])

\* The NN answers DataNode RPCs: started (NameNode.java:1181; checkNNStartup,
\* NameNodeRpcServer.java:2371-2376) and RPC server not yet stopped
\* (NameNode.java:1244 -> 1045-1046).
Serving(n) == nnPhase[n] \in {"UP", "STOPPING"}

\* The NN that owns the open edit-log segment and the current journal epoch:
\* ACTIVE with the segment open (FSNamesystem.java:1452 / 1315-1317) and not
\* deposed.
IsWriter(n) == nnPhase[n] = "UP" /\ haState[n] = "ACTIVE" /\ ~fenced[n]

\* An NN that answers as ACTIVE and has not been deposed.  A graceful
\* promotion of another NN (ZKFC / haadmin with working fencing) cannot
\* happen while such an NN exists; overlapping ACTIVE NNs are Depose (S3).
ClaimsActiveUnfenced(n) == Serving(n) /\ haState[n] = "ACTIVE" /\ ~fenced[n]

\* bpServices is non-empty, i.e. the BPOfferService still exists
\* (BPOfferService.java:483-487: the last actor's shutdown destroys it).
HasLiveActor == \E a \in NN : aPhase[a] /= "DEAD"

\* History update: NN n now holds (applied, written) = (ap, wr).
Held(n, ap, wr) ==
    maxHeldTxid' = [maxHeldTxid EXCEPT ![n] = Max(@, Max(ap, wr))]

\* A process exit loses all volatile NN state.  The values of a DOWN NN are
\* never read; they are reset to one canonical value to keep states distinct
\* only where it matters.
GoDown(n) ==
    /\ nnPhase' = [nnPhase EXCEPT ![n] = "DOWN"]
    /\ haState' = [haState EXCEPT ![n] = "STANDBY"]
    /\ fenced'  = [fenced  EXCEPT ![n] = FALSE]
    /\ written' = [written EXCEPT ![n] = 0]
    /\ applied' = [applied EXCEPT ![n] = 0]

\* ============================================================================
\* INITIAL STATE
\* ============================================================================

\* Cluster up after format (image at txid 0) and NN start: the NN that starts
\* ACTIVE loads the image (applied = 0), setNextTxId(1) (FSImage.java:775) and
\* opens the log with START_LOG_SEGMENT at txid 1, synced
\* (FSNamesystem.java:1315-1317, FSEditLog.java:329-349, 1453-1460).
\* Non-HA: the single NN starts ACTIVE (NameNode.java:1196-1198).  HA: one NN
\* has been made ACTIVE, the others are STANDBY (NameNode.java:1206-1207); the
\* active one is chosen nondeterministically so the initial states are
\* symmetric in NN.  The DataNode has just built its BPOfferService
\* (B = null, L = -1: BPOfferService.java:86, 103) with one actor per NN in
\* its handshake (BPServiceActor.java:899-908).
Init ==
    \E n0 \in NN :
        /\ nnPhase = [n \in NN |-> "UP"]
        /\ haState = [n \in NN |-> IF n = n0 THEN "ACTIVE" ELSE "STANDBY"]
        /\ fenced  = [n \in NN |-> FALSE]
        /\ applied = [n \in NN |-> 0]
        /\ written = [n \in NN |-> IF n = n0 THEN 1 ELSE 0]
        /\ durable = 1
        /\ link    = [n \in NN |-> TRUE]
        /\ bpServiceToActive   = Null
        /\ lastActiveClaimTxId = -1
        /\ aPhase  = [a \in NN |-> "INIT"]
        /\ nsResp  = [a \in NN |-> "NONE"]
        /\ hbResp  = [a \in NN |-> NoResp]
        /\ targetFired = FALSE
        /\ maxHeldTxid = [n \in NN |-> IF n = n0 THEN 1 ELSE 0]

\* ============================================================================
\* NAMENODE ACTIONS: edit log (S1, S2, S3)
\* ============================================================================

\* --------------------------------------------------------------------------
\* ClientEdit(n): a namespace operation is logged on NN n.
\* FSEditLog.logEdit (FSEditLog.java:466-486) -> beginTransaction: txid++
\* (FSEditLog.java:538-551, :541), before any sync.  Default async mode
\* assigns the txid at enqueue, before the background thread writes it
\* (FSEditLogAsync.java:128-137; queue drained at :246-281).  So the new txid
\* is immediately visible to heartbeats (getLastWrittenTxId,
\* FSEditLog.java:567-569) while not yet durable: brief deviation 1.
\* --------------------------------------------------------------------------
ClientEdit(n) ==
    \* Writes are served only in ACTIVE state; a deposed (fenced) NN still
    \* believes it is ACTIVE and keeps assigning txids (brief §3.1 Depose; S3).
    /\ nnPhase[n] = "UP"
    /\ haState[n] = "ACTIVE"
    \* FSEditLog.java:541  txid++
    /\ written' = [written EXCEPT ![n] = @ + 1]
    /\ Held(n, applied[n], written[n] + 1)
    /\ UNCHANGED <<dnVars, nnPhase, haState, fenced, applied, durable,
                   link, targetFired>>

\* --------------------------------------------------------------------------
\* SyncEdits(n): the writer flushes its buffered edits.
\* FSEditLog.logSync (FSEditLog.java:666-779): under the FSEditLog monitor it
\* reads lastJournalledTxId, the txid of the last op written into the double
\* buffer (FSEditLog.java:694; tracked per op, JournalSet.java:467-469), swaps
\* buffers (:712), then flushes outside the monitor (:735-738).  When the
\* flush returns, every txid up to that value is durable (:763).  In async
\* mode edits still in the queue are not in the buffer, so a sync may cover
\* only a prefix of the written txids: durable' ranges over
\* durable+1..written (brief §3.1 "SyncEdits").
\* --------------------------------------------------------------------------
SyncEdits(n) ==
    /\ IsWriter(n)
    /\ durable < written[n]
    /\ \E d \in (durable + 1)..written[n] :
          durable' = d
    /\ UNCHANGED <<dnVars, nnPhase, haState, fenced, written, applied,
                   link, targetFired, maxHeldTxid>>

\* --------------------------------------------------------------------------
\* TerminateOnJournalFailure(n): a deposed NN's next journal write fails.
\* Any write, flush or segment close of a fenced NN is rejected by the
\* JournalNodes' epoch check (Journal.java:484-490).  For the required shared
\* journal this calls terminate(1) (JournalSet.java:393-408; also
\* FSEditLog.java:735-750 for a failed flush), i.e. the process exits.  This
\* covers the fenced NN's sync, its segment close in transitionToStandby /
\* NameNode.stop() (FSEditLog.java:399-410), and log rolls.  An idle deposed
\* NN may never write (brief S3 evidence), so the action is never forced.
\* --------------------------------------------------------------------------
TerminateOnJournalFailure(n) ==
    /\ Serving(n)
    /\ fenced[n]
    /\ GoDown(n)
    /\ UNCHANGED <<dnVars, durable, link, targetFired, maxHeldTxid>>

\* ============================================================================
\* NAMENODE ACTIONS: process lifecycle (S1, S2, S4)
\* ============================================================================

\* --------------------------------------------------------------------------
\* Crash(n): the NN process dies (kill -9, power loss, or terminate(1) after a
\* failed flush, FSEditLog.java:713-723, 739-749).  Volatile state is lost.
\* If n was the writer, the log end that survives is some r with
\* durable <= r <= written[n]:
\*  - non-HA: the in-progress edits file is scanned to its last complete op
\*    at restart (FileJournalManager.java:426-466); bytes already handed to
\*    write() survive a process kill (analysis-report §6.B);
\*  - HA/QJM: the next writer recovers the unclosed segment from the best
\*    JournalNode response (QuorumJournalManager.java:311-404, :335-336),
\*    which lies between the quorum-acked end and the longest JN log.
\* (r, written[n]] is lost.  The choice is made here because nothing writes
\* the log between the crash and its recovery.  A non-writer (standby,
\* fenced, or stopping with its segment already closed) loses nothing durable.
\* --------------------------------------------------------------------------
Crash(n) ==
    /\ Serving(n)
    /\ \E r \in (IF IsWriter(n) THEN durable..written[n] ELSE {durable}) :
          durable' = r
    /\ GoDown(n)
    /\ UNCHANGED <<dnVars, link, targetFired, maxHeldTxid>>

\* --------------------------------------------------------------------------
\* StopNameNode(n): first half of a clean NameNode.stop() (NameNode.java:
\* 1230-1243): state.exitState(haContext) (:1237-1239).  For the ACTIVE NN,
\* ActiveState.exitState -> stopActiveServices (ActiveState.java:68-74;
\* FSNamesystem.java:1558-1564): editLog.close() logs END_LOG_SEGMENT at
\* written+1 and syncs everything (FSEditLog.java:399-410, 1466-1494), then
\* lastAppliedTxId := lastWritten (FSImage.java:1569-1571).  The HA state
\* object is not changed and the RPC server is still up, so heartbeats keep
\* being answered (ACTIVE, written+1) until StopRpcServer.  A fenced NN's
\* close is rejected by the JNs: that is TerminateOnJournalFailure.
\* MiniDFSCluster.restartNameNode stops the NN this way (trace variant V1).
\* --------------------------------------------------------------------------
StopNameNode(n) ==
    /\ nnPhase[n] = "UP"
    /\ ~fenced[n]
    /\ nnPhase' = [nnPhase EXCEPT ![n] = "STOPPING"]
    /\ IF haState[n] = "ACTIVE"
       THEN \* FSEditLog.java:1472-1477 END_LOG_SEGMENT + logSyncAll;
            \* FSNamesystem.java:1563 updateLastAppliedTxIdFromWritten
            /\ written' = [written EXCEPT ![n] = @ + 1]
            /\ applied' = [applied EXCEPT ![n] = written[n] + 1]
            /\ durable' = written[n] + 1
            /\ Held(n, written[n] + 1, written[n] + 1)
       ELSE \* standby: no segment open, nothing written
            UNCHANGED <<written, applied, durable, maxHeldTxid>>
    /\ UNCHANGED <<dnVars, haState, fenced, link, targetFired>>

\* --------------------------------------------------------------------------
\* StopRpcServer(n): second half of NameNode.stop(): stopCommonServices ->
\* rpcServer.stop() (NameNode.java:1244, 1045-1046), started := false
\* (:1259).  From now on DN RPCs fail with an IOException at the DN.
\* --------------------------------------------------------------------------
StopRpcServer(n) ==
    /\ nnPhase[n] = "STOPPING"
    /\ GoDown(n)
    /\ UNCHANGED <<dnVars, durable, link, targetFired, maxHeldTxid>>

\* --------------------------------------------------------------------------
\* Restart(n): a new NameNode process starts and becomes visible to DNs.
\* NameNode constructor (NameNode.java:1157-1183): createHAState (:1158,
\* :1194-1209), initialize -> loadFSImage (FSNamesystem.java:1281-1327):
\* lastAppliedTxId := end of the durable log, setNextTxId(lastApplied+1)
\* (FSImage.java:775).  DN RPCs are rejected until started := true
\* (NameNode.java:1181; NameNodeRpcServer.java:2371-2376), so the NN becomes
\* visible in one step.
\*  - non-HA: ACTIVE_STATE (NameNode.java:1196-1198); openEditLogForWrite
\*    (FSNamesystem.java:1315-1317) logs START_LOG_SEGMENT at durable+1 and
\*    syncs it (FSEditLog.java:333, 347, 1453-1460).  The first heartbeat
\*    reports (ACTIVE, recovered+1).
\*  - HA: STANDBY_STATE (NameNode.java:1206-1207); no segment is opened
\*    (FSNamesystem.java:1315), txid = lastApplied.  The standby's tailing is
\*    not modeled: STANDBY reports never reach :615 (their txid is unused,
\*    analysis-report §1.2) and ToActive catches up to the durable log anyway.
\* --------------------------------------------------------------------------
Restart(n) ==
    /\ nnPhase[n] = "DOWN"
    /\ nnPhase' = [nnPhase EXCEPT ![n] = "UP"]
    /\ fenced'  = [fenced  EXCEPT ![n] = FALSE]
    /\ IF ~HAEnabled
       THEN /\ haState' = [haState EXCEPT ![n] = "ACTIVE"]
            /\ applied' = [applied EXCEPT ![n] = durable]
            /\ written' = [written EXCEPT ![n] = durable + 1]
            /\ durable' = durable + 1
            /\ Held(n, durable, durable + 1)
       ELSE /\ haState' = [haState EXCEPT ![n] = "STANDBY"]
            /\ applied' = [applied EXCEPT ![n] = durable]
            /\ written' = [written EXCEPT ![n] = durable]
            /\ UNCHANGED durable
            /\ Held(n, durable, durable)
    /\ UNCHANGED <<dnVars, link, targetFired>>

\* ============================================================================
\* NAMENODE ACTIONS: HA transitions (S2, S3, S4)
\* ============================================================================

\* --------------------------------------------------------------------------
\* ToActive(m): graceful transitionToActive (NameNode.java:2012-2027) ->
\* StandbyState.setState (StandbyState.java:56-64) -> setStateInternal under
\* the GLOBAL write lock (HAState.java:56-69; NameNode.java:2247-2256), so
\* heartbeats (BM read lock, FSNamesystem.java:4492) never see a half-done
\* transition.  ActiveState.enterState -> startActiveServices
\* (ActiveState.java:59-65; FSNamesystem.java:1412-1453): recover unclosed
\* streams and catch up the shared log (:1421-1427), nextTxId :=
\* lastApplied+1 (:1447-1450), openForWrite: START_LOG_SEGMENT synced
\* (:1452; FSEditLog.java:329-349, 1453-1460).
\* Graceful = the previous active was made standby or is down; with an
\* unfenced ACTIVE NN still serving, a promotion is the split brain Depose.
\* --------------------------------------------------------------------------
ToActive(m) ==
    /\ HAEnabled
    /\ nnPhase[m] = "UP"
    /\ haState[m] = "STANDBY"
    /\ ~\E n \in NN \ {m} : ClaimsActiveUnfenced(n)
    /\ haState' = [haState EXCEPT ![m] = "ACTIVE"]
    \* FSNamesystem.java:1427 catchupDuringFailover; :1447-1452 START at +1
    /\ applied' = [applied EXCEPT ![m] = durable]
    /\ written' = [written EXCEPT ![m] = durable + 1]
    /\ durable' = durable + 1
    /\ Held(m, durable, durable + 1)
    /\ UNCHANGED <<dnVars, nnPhase, fenced, link, targetFired>>

\* --------------------------------------------------------------------------
\* ToStandby(n): graceful transitionToStandby (NameNode.java:2029-2036) ->
\* ActiveState.setState(STANDBY) (ActiveState.java:50-56) -> setStateInternal
\* under the GLOBAL write lock (HAState.java:56-69) -> exitState ->
\* stopActiveServices (FSNamesystem.java:1558-1564): END_LOG_SEGMENT at
\* written+1, sync all (FSEditLog.java:399-410, 1466-1494), lastAppliedTxId :=
\* lastWritten.  A fenced NN's close fails: TerminateOnJournalFailure.
\* --------------------------------------------------------------------------
ToStandby(n) ==
    /\ HAEnabled
    /\ IsWriter(n)
    /\ haState' = [haState EXCEPT ![n] = "STANDBY"]
    /\ written' = [written EXCEPT ![n] = @ + 1]
    /\ applied' = [applied EXCEPT ![n] = written[n] + 1]
    /\ durable' = written[n] + 1
    /\ Held(n, written[n] + 1, written[n] + 1)
    /\ UNCHANGED <<dnVars, nnPhase, fenced, link, targetFired>>

\* --------------------------------------------------------------------------
\* Depose(n, m): split brain (S3).  m is made ACTIVE (new journal epoch,
\* recovery, catch-up, START) while n is not told -- fencing by journal epoch
\* only (shell(/bin/true)), haadmin --forceactive, or a GC pause / partition
\* of n.  n keeps haState = ACTIVE: heartbeats and versionRequest read only
\* the volatile NameNode.state (FSNamesystem.java:4505-4507, 1927-1929,
\* 5699-5701) and nothing consults ZooKeeper or the JNs when answering.
\* m's recovered end e lies in durable..written[n] (QJM recovery,
\* QuorumJournalManager.java:311-404), then START at e+1
\* (FSNamesystem.java:1412-1453).  A later ToActive on n is a no-op
\* (HAState.java:136-139): the model has no step for it.
\* --------------------------------------------------------------------------
Depose(n, m) ==
    /\ HAEnabled
    /\ n /= m
    /\ ClaimsActiveUnfenced(n)
    /\ nnPhase[m] = "UP"
    /\ haState[m] = "STANDBY"
    /\ \E e \in (IF IsWriter(n) THEN durable..written[n] ELSE {durable}) :
          /\ applied' = [applied EXCEPT ![m] = e]
          /\ written' = [written EXCEPT ![m] = e + 1]
          /\ durable' = e + 1
          /\ Held(m, e, e + 1)
    /\ fenced'  = [fenced  EXCEPT ![n] = TRUE]
    /\ haState' = [haState EXCEPT ![m] = "ACTIVE"]
    /\ UNCHANGED <<dnVars, nnPhase, link, targetFired>>

\* ============================================================================
\* NETWORK (S2, S4)
\* ============================================================================

\* DN<->NN link loss: versionRequest and heartbeat RPCs to n fail at the DN
\* with an IOException (BPServiceActor.java:265-272 retry every 5 s;
\* :805-807 sleepAfterException).  B and L are untouched (:791-807).
Partition(n) ==
    /\ link[n]
    /\ link' = [link EXCEPT ![n] = FALSE]
    /\ UNCHANGED <<dnVars, nnVars, targetFired, maxHeldTxid>>

Heal(n) ==
    /\ ~link[n]
    /\ link' = [link EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<dnVars, nnVars, targetFired, maxHeldTxid>>

\* ============================================================================
\* DATANODE ACTIONS: handshake (P2 path, S2/S3)
\* ============================================================================

\* --------------------------------------------------------------------------
\* VersionRequest(a): NN side of the handshake's first RPC.
\* BPServiceActor.run -> connectToNNAndHandshake (BPServiceActor.java:908,
\* 302-308) -> retrieveNamespaceInfo (:258-281): versionRequest RPC (:262),
\* retried every 5 s while the NN is unreachable (:265-272).  NN side:
\* NameNodeRpcServer.versionRequest (NameNodeRpcServer.java:1754-1758):
\* checkNNStartup, then FSNamesystem.getNamespaceInfo under the FS read lock
\* (FSNamesystem.java:1903-1910, 1927-1929): the HA state, and no txid.
\* --------------------------------------------------------------------------
VersionRequest(a) ==
    /\ aPhase[a] = "INIT"
    /\ Serving(a)
    /\ link[a]
    /\ nsResp' = [nsResp EXCEPT ![a] = haState[a]]
    /\ aPhase' = [aPhase EXCEPT ![a] = "VERSIONED"]
    /\ UNCHANGED <<bpServiceToActive, lastActiveClaimTxId, hbResp, nnVars,
                   link, targetFired, maxHeldTxid>>

\* --------------------------------------------------------------------------
\* HandshakeApply(a): DN side of the handshake.
\* BPServiceActor.java:317 -> BPOfferService.verifyAndSetNamespaceInfo
\* (BPOfferService.java:382-415) under the write lock (:384):
\*   386-390  if (nsInfo.getState() == ACTIVE && bpServiceToActive == null)
\*              bpServiceToActive = actor;
\* No txid comparison and lastActiveClaimTxId untouched (brief deviation 2,
\* CR-1).  Then setNamespaceInfo/initBlockPool (:392-411), state :=
\* nsInfo.getState() (BPServiceActor.java:318) and register (:324, 838-879).
\* register is collapsed into this step (brief §3.1): it never touches B or
\* L, and the actor's first heartbeat needs the NN serving anyway.  If
\* register or initBlockPool fails, run() retries the whole handshake
\* (:904-924); B keeps pointing at the actor (CR-3); a retried handshake
\* finds B /= null and changes nothing.  Then RUNNING (:926).
\* --------------------------------------------------------------------------
HandshakeApply(a) ==
    /\ aPhase[a] = "VERSIONED"
    \* BPOfferService.java:386-390
    /\ bpServiceToActive' =
          IF nsResp[a] = "ACTIVE" /\ bpServiceToActive = Null
          THEN a
          ELSE bpServiceToActive
    /\ aPhase' = [aPhase EXCEPT ![a] = "RUNNING"]
    /\ nsResp' = [nsResp EXCEPT ![a] = "NONE"]
    /\ UNCHANGED <<lastActiveClaimTxId, hbResp, nnVars, link, targetFired,
                   maxHeldTxid>>

\* ============================================================================
\* DATANODE ACTIONS: heartbeat and the target (P1/P2, all Scenarios)
\* ============================================================================

\* --------------------------------------------------------------------------
\* HeartbeatHandle(a): NN side of a heartbeat.
\* BPServiceActor.offerService (BPServiceActor.java:674-813) -> sendHeartBeat
\* (:711, 545-591; RPC at :571-581).  NN side: NameNodeRpcServer.sendHeartbeat
\* (NameNodeRpcServer.java:1626-1640: checkNNStartup :1634, verifyRequest
\* :1635) -> FSNamesystem.handleHeartbeat under the BM read lock
\* (FSNamesystem.java:4484-4517, :4492):
\*   4505-4507  new NNHAStatusHeartbeat(haContext.getState().getServiceState(),
\*                  getFSImage().getCorrectLastAppliedOrWrittenTxId())
\* A DN unknown to a restarted NN gets REGISTER back, with the HA status
\* still attached (DatanodeManager.java:1863-1878): no exception, the actor
\* survives the NN restart (brief S1 evidence).
\* --------------------------------------------------------------------------
HeartbeatHandle(a) ==
    /\ aPhase[a] = "RUNNING"
    /\ hbResp[a] = NoResp
    /\ Serving(a)
    /\ link[a]
    /\ hbResp' = [hbResp EXCEPT ![a] =
                    [state |-> haState[a], txid |-> ReportedTxid(a)]]
    /\ UNCHANGED <<bpServiceToActive, lastActiveClaimTxId, aPhase, nsResp,
                   nnVars, link, targetFired, maxHeldTxid>>

\* --------------------------------------------------------------------------
\* HeartbeatRpcFail(a): the heartbeat response never reaches the actor
\* (connection reset after the NN answered).  The actor catches the
\* IOException and sleeps (BPServiceActor.java:805-807, 815-823); B and L are
\* untouched.  Adds no (B, L) behavior: the resulting state equals one where
\* HeartbeatHandle never ran.  Needed so the actor can heartbeat again.
\* --------------------------------------------------------------------------
HeartbeatRpcFail(a) ==
    /\ hbResp[a] /= NoResp
    /\ hbResp' = [hbResp EXCEPT ![a] = NoResp]
    /\ UNCHANGED <<bpServiceToActive, lastActiveClaimTxId, aPhase, nsResp,
                   nnVars, link, targetFired, maxHeldTxid>>

\* --------------------------------------------------------------------------
\* TargetCheck(a): DN side of a heartbeat: the target method.
\* BPServiceActor.java:733-734 -> BPOfferService.updateActorStatesFromHeartbeat
\* (BPOfferService.java:576-621), entirely under the write lock (:579, :619),
\* before any command of the response is queued (BPServiceActor.java:745-756).
\* Single call site of the method (analysis-report §2.1).
\* --------------------------------------------------------------------------
TargetCheck(a) ==
    /\ hbResp[a] /= NoResp
    /\ LET txid              == hbResp[a].txid                   \* :581
           nnClaimsActive    == hbResp[a].state = "ACTIVE"       \* :583-584
           bposThinksActive  == bpServiceToActive = a            \* :585
           isMoreRecentClaim == txid > lastActiveClaimTxId       \* :586
       IN
       IF nnClaimsActive /\ ~bposThinksActive /\ ~isMoreRecentClaim
       THEN \* :588-598 split brain: a different NN already claimed ACTIVE
            \* with a higher or equal txid -> warn and return
            UNCHANGED <<bpServiceToActive, lastActiveClaimTxId, targetFired>>
       ELSE
         LET \* bpServiceToActive after :588-612
             B1 == IF nnClaimsActive /\ ~bposThinksActive
                   THEN a                      \* :599-606 takeover at higher txid
                   ELSE IF ~nnClaimsActive /\ bposThinksActive
                        THEN Null              \* :608-611 relinquish
                        ELSE bpServiceToActive \* no change
         IN
         /\ bpServiceToActive' = B1
         /\ IF B1 = a                                            \* :614
            THEN IF ~(txid >= lastActiveClaimTxId)
                 THEN \* :615 assert fails: AssertionError
                      /\ targetFired' = TRUE
                      /\ UNCHANGED lastActiveClaimTxId
                 ELSE \* :616
                      /\ lastActiveClaimTxId' = txid
                      /\ UNCHANGED targetFired
            ELSE UNCHANGED <<lastActiveClaimTxId, targetFired>>
    \* the response is consumed (BPServiceActor.java:735-740 then commands)
    /\ hbResp' = [hbResp EXCEPT ![a] = NoResp]
    /\ UNCHANGED <<aPhase, nsResp, nnVars, link, maxHeldTxid>>

\* ============================================================================
\* DATANODE ACTIONS: actor and BPOfferService lifecycle (S2, S3, S4, workload)
\* ============================================================================

\* --------------------------------------------------------------------------
\* ActorDie(a): the actor thread exits and runs cleanUp (BPServiceActor.java:
\* 940-946, 648-654) -> BPOfferService.shutdownActor (BPOfferService.java:
\* 476-491) under the write lock: if B == actor then B := null (:479-481),
\* remove from bpServices (:483), and if no actor is left the block pool is
\* shut down (:485-487 -> DataNode.java:2151-2152 -> BlockPoolManager.java:
\* 89-111).  L is kept (brief deviation 3, CR-5).  Exit causes: init failure
\* without retry (:910-922), UnregisteredNode/DisallowedDatanode/
\* IncorrectVersion RemoteException (:791-799), stop() (:622-633), an Error
\* escaping the loop (:940-942).  An in-flight response dies with the thread.
\* --------------------------------------------------------------------------
ActorDie(a) ==
    /\ aPhase[a] /= "DEAD"
    /\ bpServiceToActive' = IF bpServiceToActive = a
                            THEN Null
                            ELSE bpServiceToActive
    /\ aPhase' = [aPhase EXCEPT ![a] = "DEAD"]
    /\ nsResp' = [nsResp EXCEPT ![a] = "NONE"]
    /\ hbResp' = [hbResp EXCEPT ![a] = NoResp]
    /\ UNCHANGED <<lastActiveClaimTxId, nnVars, link, targetFired,
                   maxHeldTxid>>

\* --------------------------------------------------------------------------
\* Refresh: DataNode.refreshNamenodes(conf) (DataNode.java:3806-3808; also
\* dfsadmin -refreshNamenodes) with an unchanged NN list ->
\* BlockPoolManager.refreshNamenodes (BlockPoolManager.java:148-173) ->
\* doRefreshNamenodes (:175-292):
\*  - BPOS still exists (Step 5, :254-291) -> refreshNNList
\*    (BPOfferService.java:145-175): added = configured addresses with no
\*    actor in bpServices (:148-155), i.e. the NNs whose actor died; a new
\*    actor is created and started for each (:155-162).  B and L are kept.
\*  - BPOS was destroyed with its last actor (Step 3, :209-236): createBPOS
\*    builds a fresh BPOfferService (B = null, L = -1,
\*    BPOfferService.java:86, 103) with one actor per NN (:139-142).
\* --------------------------------------------------------------------------
Refresh ==
    /\ \E a \in NN : aPhase[a] = "DEAD"
    /\ IF HasLiveActor
       THEN /\ aPhase' = [a \in NN |-> IF aPhase[a] = "DEAD"
                                       THEN "INIT"
                                       ELSE aPhase[a]]
            /\ UNCHANGED <<bpServiceToActive, lastActiveClaimTxId>>
       ELSE /\ aPhase' = [a \in NN |-> "INIT"]
            /\ bpServiceToActive'   = Null
            /\ lastActiveClaimTxId' = -1
    /\ UNCHANGED <<nsResp, hbResp, nnVars, link, targetFired, maxHeldTxid>>

\* --------------------------------------------------------------------------
\* DNRestart: the workload's OOB upgrade restart (dfsadmin -shutdownDatanode
\* <dn> upgrade; MiniDFSCluster.restartDataNode(0, true)): the old DataNode
\* and its actors are gone, a new DataNode builds a new BPOfferService
\* (BlockPoolManager.java:209-236; BPOfferService.java:127-143) with B = null,
\* L = -1 (:86, :103) and one actor per NN in its handshake.
\* --------------------------------------------------------------------------
DNRestart ==
    /\ bpServiceToActive'   = Null
    /\ lastActiveClaimTxId' = -1
    /\ aPhase' = [a \in NN |-> "INIT"]
    /\ nsResp' = [a \in NN |-> "NONE"]
    /\ hbResp' = [a \in NN |-> NoResp]
    /\ UNCHANGED <<nnVars, link, targetFired, maxHeldTxid>>

\* ============================================================================
\* NEXT-STATE RELATION
\* ============================================================================

\* Once the assert has failed every other action stops (tla-patterns §1), so
\* counterexamples end at the failing TargetCheck.
Next ==
    /\ ~targetFired
    /\ \/ \E n \in NN :
            \/ ClientEdit(n)
            \/ SyncEdits(n)
            \/ TerminateOnJournalFailure(n)
            \/ Crash(n)
            \/ StopNameNode(n)
            \/ StopRpcServer(n)
            \/ Restart(n)
            \/ ToActive(n)
            \/ ToStandby(n)
            \/ Partition(n)
            \/ Heal(n)
       \/ \E n, m \in NN : Depose(n, m)
       \/ \E a \in NN :
            \/ VersionRequest(a)
            \/ HandshakeApply(a)
            \/ HeartbeatHandle(a)
            \/ HeartbeatRpcFail(a)
            \/ TargetCheck(a)
            \/ ActorDie(a)
       \/ Refresh
       \/ DNRestart

Spec == Init /\ [][Next]_vars

\* ============================================================================
\* INVARIANTS (brief §5)
\* ============================================================================

\* The target: the assert at BPOfferService.java:615 never fails.
TargetSafe == ~targetFired

\* Structural sanity 1: types and ranges, plus the tagged-union coherence of
\* the per-actor fields and the field contract of bpServiceToActive ("if
\* non-null, this must always refer to a member of the bpServices list",
\* BPOfferService.java:80-85).
TypeOK ==
    /\ nnPhase \in [NN -> {"UP", "STOPPING", "DOWN"}]
    /\ haState \in [NN -> HAStates]
    /\ fenced  \in [NN -> BOOLEAN]
    /\ written \in [NN -> Nat]
    /\ applied \in [NN -> Nat]
    /\ durable \in Nat
    /\ link    \in [NN -> BOOLEAN]
    /\ bpServiceToActive \in NN \cup {Null}
    /\ lastActiveClaimTxId \in Int
    /\ lastActiveClaimTxId >= -1
    /\ aPhase \in [NN -> {"INIT", "VERSIONED", "RUNNING", "DEAD"}]
    /\ nsResp \in [NN -> {"NONE"} \cup HAStates]
    /\ DOMAIN hbResp = NN
    /\ \A a \in NN :
          \/ hbResp[a] = NoResp
          \/ /\ hbResp[a].state \in HAStates
             /\ hbResp[a].txid \in Nat
    /\ targetFired \in BOOLEAN
    /\ maxHeldTxid \in [NN -> Nat]
    /\ \A a \in NN : (nsResp[a] /= "NONE") <=> (aPhase[a] = "VERSIONED")
    /\ \A a \in NN : hbResp[a] /= NoResp => aPhase[a] = "RUNNING"
    /\ bpServiceToActive /= Null => aPhase[bpServiceToActive] /= "DEAD"

\* Structural sanity 2: a heartbeat response carries only a txid its sender
\* actually held.  maxHeldTxid is a history variable updated by the NN steps
\* that change (applied, written), not by HeartbeatHandle, so the check is
\* not circular (brief §5 "RespFromSender").
RespFromSender ==
    \A a \in NN :
        hbResp[a] /= NoResp => hbResp[a].txid <= maxHeldTxid[a]

\* TEMPORARY sanity check (tla-patterns §2): TLC must VIOLATE this to show
\* the model reaches :615 in the case that can fail (ACTIVE claim from the
\* actor that already is bpServiceToActive), as the workload does.
TargetReached ==
    ~\E a \in NN :
        /\ hbResp[a] /= NoResp
        /\ hbResp[a].state = "ACTIVE"
        /\ bpServiceToActive = a

=============================================================================
