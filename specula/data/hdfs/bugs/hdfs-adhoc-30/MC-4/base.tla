-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-30: can a DataNode block-recovery daemon reach the failing   *)
(* branch of BlockRecoveryWorker.getActiveNamenodeForBP                    *)
(* (BlockRecoveryWorker.java:609, IOException "Block pool <bpid> has not   *)
(* recognized an active NN")?                                              *)
(*                                                                         *)
(* Pinned tree: /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-30/hadoop at     *)
(* 734dd8a67cd.  Paths are relative to                                     *)
(*   hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/ *)
(*   server/                                                               *)
(* and file names without a directory are in datanode/.                    *)
(*                                                                         *)
(* Category A (modeling-brief.md section 1).  One DataNode (the recovery   *)
(* primary) is modeled.  Its block-pool service (BPOS) talks to every NN   *)
(* of the nameservice through one BPServiceActor per NN.  Each actor has a *)
(* heartbeat thread and a CommandProcessingThread; each accepted           *)
(* DNA_RECOVERBLOCK command runs in its own recovery daemon.  Every access *)
(* to bpServiceToActive holds the BPOS ReentrantReadWriteLock, and         *)
(* BlockPoolManager lookups hold the BlockPoolManager monitor, so each     *)
(* locked section is one atomic action.                                    *)
(*                                                                         *)
(* phi_T (brief section 1): the daemon executes L607 on the non-null BPOS  *)
(* it obtained at L602 while that BPOS has bpServiceToActive == null.      *)
(*                                                                         *)
(* Writers of bpServiceToActive (brief / analysis D3):                     *)
(*   W1 BPOfferService.java:386-390  handshake acknowledges an ACTIVE NN   *)
(*   W2 BPOfferService.java:479-481  actor shutdown -> null                *)
(*   W3 BPOfferService.java:588-607  heartbeat ACTIVE claim (txid guard)   *)
(*   W4 BPOfferService.java:608-612  heartbeat non-ACTIVE report -> null   *)
(*   R2 BPOfferService.java:692-698  command acceptance (isActiveActor)    *)
(*   R1 BPOfferService.java:532-543  getActiveNN, read at L607             *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets, TLC

CONSTANTS
    NN,               \* NameNodes of the nameservice; one BPServiceActor per NN per BPOS
    HA,               \* TRUE: HA nameservice.  FALSE: non-HA NN, always ACTIVE
                      \* (namenode/NameNode.java:1194-1198 createHAState)
    InitActive,       \* the NN that is ACTIVE at Init, or None
    Inc,              \* BPOS incarnations for the bpid, 1..k (BlockPoolManager.doRefreshNamenodes
                      \* can create a new BPOS for the same bpid, BlockPoolManager.java:214-236)
    Rec,              \* recovery ids (one recovered block each) the NN can issue to this DN
    EnableAssertions, \* the DN JVM runs with -ea (surefire does): BPOfferService.java:615 is live
    None              \* model value: no NN / null

ASSUME HA \in BOOLEAN /\ EnableAssertions \in BOOLEAN
ASSUME None \notin NN /\ (InitActive \in NN \/ InitActive = None)
ASSUME ~HA => (InitActive \in NN /\ NN = {InitActive})
ASSUME Inc # {} /\ 1 \in Inc /\ \A b \in Inc : b \in Nat /\ b > 0
ASSUME \A r \in Rec : r \in Nat /\ r > 0

NNStates    == {"ACTIVE", "STANDBY", "DOWN"}
HAReports   == {"ACTIVE", "STANDBY"}   \* PBHelper.convert (protocolPB/PBHelper.java:793-808) lets only
                                       \* ACTIVE/STANDBY/OBSERVER reach the DN; OBSERVER acts as STANDBY (X11)
ActorStates == {"idle", "connecting", "registering", "running", "exited"}
RecPCs      == {"none", "issued", "dropped", "wait", "pre", "lookup", "getActive", "done", "fired"}
MaxInc      == CHOOSE m \in Inc : \A b \in Inc : b <= m
NoResp      == [st |-> "none", txid |-> -1, cmd |-> <<>>]
Range(s)    == {s[i] : i \in DOMAIN s}
RecsInQ(q)  == UNION {Range(q[i]) : i \in DOMAIN q}

VARIABLES
    \* ---- NameNode side (Scenario 1) ----
    nnState,             \* [NN -> NNStates]
    nnTxid,              \* [NN -> Int]: txid n reports in a heartbeat:
                         \* max(lastAppliedTxId, lastWrittenTxId) (namenode/FSImage.java:1564-1567)
    logEnd,              \* last durable txid of the shared edit log
    nnRecQ,              \* [NN -> Seq(Rec)]: n's DatanodeDescriptor.recoverBlocks queue for this DN
    \* ---- DataNode: block-pool service incarnations (Scenarios 2-4) ----
    curInc,              \* newest BPOS incarnation created so far
    bposReg,             \* 0, or the incarnation BlockPoolManager.bpByBlockPoolId maps the bpid to
    bpStopped,           \* [Inc -> BOOLEAN]: BPOfferService.stop() was called (refreshNamenodes)
    bpNSInfo,            \* [Inc -> BOOLEAN]: bpNSInfo != null (hasBlockPoolId)
    bpRegd,              \* [Inc -> BOOLEAN]: bpRegistration != null
    bpServiceToActive,   \* [Inc -> NN \cup {None}]   (BPOfferService.java:86)
    lastActiveClaimTxId, \* [Inc -> Int]              (BPOfferService.java:103)
    \* ---- BPServiceActors, one per (incarnation, NN) ----
    actorSt,             \* [Inc -> [NN -> ActorStates]]
    hsResp,              \* [Inc -> [NN -> {"none"} \cup HAReports]]: versionRequest result not yet applied
    hbResp,              \* [Inc -> [NN -> response]]: heartbeat response not yet applied
    cmdQ,                \* [Inc -> [NN -> Seq(Seq(Rec))]]: recovery commands in the CommandProcessingThread queue
    \* ---- recovery daemons ----
    rec,                 \* [Rec -> [pc, by, bp, nxt]]
    \* ---- target ----
    targetFired

nnVars    == <<nnState, nnTxid, logEnd, nnRecQ>>
bposVars  == <<curInc, bposReg, bpStopped, bpNSInfo, bpRegd, bpServiceToActive, lastActiveClaimTxId>>
actorVars == <<actorSt, hsResp, hbResp, cmdQ>>
vars      == <<nnVars, bposVars, actorVars, rec, targetFired>>

-----------------------------------------------------------------------------
(* Helpers *)

\* The actor is still a member of bpServices: created and not yet removed by shutdownActor
\* (BPOfferService.java:92-93, 483).
InBpServices(b, n) == actorSt[b][n] \in {"connecting", "registering", "running"}

\* Recoveries handed to an actor (in flight or queued) are lost when the actor goes away.
RecsHeldBy(b, n) == RecsInQ(cmdQ[b][n]) \cup Range(hbResp[b][n].cmd)

DropRecs(S) == [r \in Rec |-> IF r \in S THEN [rec[r] EXCEPT !.pc = "dropped"] ELSE rec[r]]

\* BPServiceActor.cleanUp (BPServiceActor.java:648-654) -> bpos.shutdownActor(this) (L653) ->
\* BPOfferService.shutdownActor (BPOfferService.java:476-491), one write-locked section.
\* Only the fields shutdownActor writes, plus the actor's own thread-local state.
CleanUp(b, n) ==
    LET left == {m \in NN \ {n} : InBpServices(b, m)}   \* bpServices.remove(actor) (L483)
    IN
    /\ bpServiceToActive' = [bpServiceToActive EXCEPT ![b] =
                                IF @ = n THEN None ELSE @]           \* W2: L479-481
    \* L485-487: last actor -> dn.shutdownBlockPool(this) (DataNode.java:2151-2152) ->
    \* BlockPoolManager.remove (BlockPoolManager.java:89-95): if (t.hasBlockPoolId())
    \* bpByBlockPoolId.remove(t.getBlockPoolId()) -- removes by bpid key, whatever BPOS it maps to.
    /\ bposReg' = IF left = {} /\ bpNSInfo[b] THEN 0 ELSE bposReg
    /\ actorSt' = [actorSt EXCEPT ![b][n] = "exited"]
    /\ hsResp'  = [hsResp EXCEPT ![b][n] = "none"]
    \* A response in flight is never applied by the exiting heartbeat thread.  Queued commands are
    \* never accepted: R2 (L694) is false once W2 ran and the actor can never be active again (W1/W3
    \* run only on its own thread), and processQueue clears the queue (BPServiceActor.java:1443-1444).
    /\ hbResp'  = [hbResp EXCEPT ![b][n] = NoResp]
    /\ cmdQ'    = [cmdQ EXCEPT ![b][n] = <<>>]
    /\ rec'     = DropRecs(RecsHeldBy(b, n))

\* Ends block r of a daemon; the daemon goes on with the next block of the same command
\* (BlockRecoveryWorker.java:622-633; an IOException is caught and logged at L630-631).
Finish(r, final) ==
    rec' = IF rec[r].nxt = 0
           THEN [rec EXCEPT ![r].pc = final]
           ELSE [rec EXCEPT ![r].pc = final, ![rec[r].nxt].pc = "pre"]

RECURSIVE Chain(_)
Chain(r) == IF rec[r].nxt = 0 THEN {r} ELSE {r} \cup Chain(rec[r].nxt)

-----------------------------------------------------------------------------
(* Initial state *)

Init ==
    /\ nnState = [n \in NN |-> IF n = InitActive THEN "ACTIVE" ELSE "STANDBY"]
    /\ nnTxid  = [n \in NN |-> 0]
    /\ logEnd  = 0
    /\ nnRecQ  = [n \in NN |-> <<>>]
    /\ curInc  = 1
    /\ bposReg = 0
    /\ bpStopped = [b \in Inc |-> FALSE]
    /\ bpNSInfo  = [b \in Inc |-> FALSE]
    /\ bpRegd    = [b \in Inc |-> FALSE]
    /\ bpServiceToActive   = [b \in Inc |-> None]   \* BPOfferService.java:86
    /\ lastActiveClaimTxId = [b \in Inc |-> -1]     \* BPOfferService.java:103
    \* BPOfferService constructor creates the actors (BPOfferService.java:139-142); BlockPoolManager
    \* starts them (BlockPoolManager.java:236 -> BPOfferService.start L351-355 -> BPServiceActor.start).
    /\ actorSt = [b \in Inc |-> [n \in NN |-> IF b = 1 THEN "connecting" ELSE "idle"]]
    /\ hsResp  = [b \in Inc |-> [n \in NN |-> "none"]]
    /\ hbResp  = [b \in Inc |-> [n \in NN |-> NoResp]]
    /\ cmdQ    = [b \in Inc |-> [n \in NN |-> <<>>]]
    /\ rec     = [r \in Rec |-> [pc |-> "none", by |-> None, bp |-> 0, nxt |-> 0]]
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(* NameNode actions (Scenario 1).  An HA transition runs under the FSN GLOBAL write lock *)
(* (namenode/ha/HAState.java:56-69), and a heartbeat reads commands, HA state and txid   *)
(* under one BM read-lock hold (namenode/FSNamesystem.java:4492-4516), so each           *)
(* transition is atomic with respect to heartbeat snapshots.                             *)

\* A lease recovery makes this DN the primary of a block: FSNamesystem.internalReleaseLease
\* (lease monitor, started only on the active, FSNamesystem.java:1472; stopped on demotion L1542) ->
\* BlockUnderConstructionFeature.initializeBlockRecovery (blockmanagement/BlockUnderConstructionFeature.java:238-288)
\* -> primary.addBlockToBeRecovered (L286; blockmanagement/DatanodeDescriptor.java:717-724).
\* The NN picks the primary among the block's live expected locations, so this DN must be
\* registered with n: some actor of it to n has completed registration (BPServiceActor.java:838-879).
NNIssueRecovery(n, r) ==
    /\ nnState[n] = "ACTIVE"
    /\ \E b \in Inc : actorSt[b][n] = "running"
    /\ rec[r].pc = "none"
    /\ nnRecQ' = [nnRecQ EXCEPT ![n] = Append(@, r)]
    /\ rec' = [rec EXCEPT ![r].pc = "issued", ![r].by = n]
    /\ UNCHANGED <<nnState, nnTxid, logEnd, bposVars, actorVars, targetFired>>

\* The active assigns txids to new edits before they are synced: FSEditLog.beginTransaction
\* (namenode/FSEditLog.java:538-551, txid++ at L541); heartbeats report the last written txid.
NNLogEditsTo(n, t) ==
    /\ nnState[n] = "ACTIVE"
    /\ t > nnTxid[n]
    /\ nnTxid' = [nnTxid EXCEPT ![n] = t]
    /\ UNCHANGED <<nnState, logEnd, nnRecQ, bposVars, actorVars, rec, targetFired>>

NNLogEdit(n) == NNLogEditsTo(n, nnTxid[n] + 1)

\* NNLogEditsTo followed by NNLogSync with nothing in between: edits up to t written and durable.
\* Used by the trace spec (fault-free traces lose no edits; the shared log's end is not traced).
NNLogEditsDurable(n, t) ==
    /\ nnState[n] = "ACTIVE"
    /\ t > nnTxid[n]
    /\ nnTxid' = [nnTxid EXCEPT ![n] = t]
    /\ logEnd' = t
    /\ UNCHANGED <<nnState, nnRecQ, bposVars, actorVars, rec, targetFired>>

\* logSync makes the written edits durable in the shared log.
NNLogSync(n) ==
    /\ nnState[n] = "ACTIVE"
    /\ logEnd < nnTxid[n]
    /\ logEnd' = nnTxid[n]
    /\ UNCHANGED <<nnState, nnTxid, nnRecQ, bposVars, actorVars, rec, targetFired>>

\* A standby tails durable edits (EditLogTailer).  No DN logic reads a non-ACTIVE txid
\* (BPOfferService.java:586 is used only for claims, L614-617 only for the active), so the MC
\* spec leaves this out; the trace spec uses it to follow the standby's reported txid.
NNTailEdits(n, t) ==
    /\ nnState[n] = "STANDBY"
    /\ nnTxid[n] < t /\ t <= logEnd
    /\ nnTxid' = [nnTxid EXCEPT ![n] = t]
    /\ UNCHANGED <<nnState, logEnd, nnRecQ, bposVars, actorVars, rec, targetFired>>

\* Active -> Standby: ActiveState.setState (namenode/ha/ActiveState.java:50-56) -> setStateInternal ->
\* exitState -> FSNamesystem.stopActiveServices (FSNamesystem.java:1531-1583):
\*   lease monitor stopped (L1542); editLog.close() (L1560 -> FSEditLog.java:399-409 ->
\*   endCurrentLogSegment L1466-1477 writes END_LOG_SEGMENT and syncs everything);
\*   lastApplied = last written (L1563); blockManager.clearQueues() (L1577 ->
\*   DatanodeDescriptor.clearBlockQueues L359-366, recoverBlocks.clear() L363);
\* then setState(STANDBY) and startStandbyServices (FSNamesystem.java:1590-1612).
DemoteNN(n) ==
    /\ HA
    /\ nnState[n] = "ACTIVE"
    /\ nnState' = [nnState EXCEPT ![n] = "STANDBY"]
    /\ nnTxid'  = [nnTxid EXCEPT ![n] = nnTxid[n] + 1]
    /\ logEnd'  = nnTxid[n] + 1
    /\ nnRecQ'  = [nnRecQ EXCEPT ![n] = <<>>]
    /\ rec'     = DropRecs(Range(nnRecQ[n]))
    /\ UNCHANGED <<bposVars, actorVars, targetFired>>

\* Standby -> Active.  The failover controller promotes only after the old active left ACTIVE or
\* was fenced (hadoop-common ha/FailoverController.java:168-228).  FSNamesystem.startActiveServices
\* (FSNamesystem.java:1412-1509, GLOBAL write lock L1415): catch up to the durable log end
\* (catchupDuringFailover L1427), clearQueues (L1431), nextTxId = lastApplied + 1 (L1447-1450),
\* openForWrite (L1452 -> FSEditLog.java:329-347 -> startLogSegmentAndWriteHeaderTxn L1453-1460:
\* START_LOG_SEGMENT, logSync).
PromoteNN(n) ==
    /\ HA
    /\ nnState[n] = "STANDBY"
    /\ \A m \in NN : nnState[m] # "ACTIVE"
    /\ nnState' = [nnState EXCEPT ![n] = "ACTIVE"]
    /\ nnTxid'  = [nnTxid EXCEPT ![n] = logEnd + 1]
    /\ logEnd'  = logEnd + 1
    /\ UNCHANGED <<nnRecQ, bposVars, actorVars, rec, targetFired>>

\* NN process crash.  In-memory recovery queues are lost; edits the NN assigned but did not sync
\* are lost (FSEditLog.java:538-551 assigns the txid before logSync), so logEnd keeps only synced
\* edits.  DN heartbeats to a down NN fail with IOException and do not touch the DN's view
\* (BPServiceActor.java:805-807).
NNCrash(n) ==
    /\ nnState[n] # "DOWN"
    /\ nnState' = [nnState EXCEPT ![n] = "DOWN"]
    /\ nnRecQ'  = [nnRecQ EXCEPT ![n] = <<>>]
    /\ rec'     = DropRecs(Range(nnRecQ[n]))
    /\ UNCHANGED <<nnTxid, logEnd, bposVars, actorVars, targetFired>>

\* NN restart.  HA: it comes back STANDBY, having loaded the durable log.  Non-HA: it is ACTIVE
\* (NameNode.java:1194-1198) and opens a new segment after the durable end (openForWrite).
NNRestart(n) ==
    /\ nnState[n] = "DOWN"
    /\ IF HA
       THEN /\ nnState' = [nnState EXCEPT ![n] = "STANDBY"]
            /\ nnTxid'  = [nnTxid EXCEPT ![n] = logEnd]
            /\ UNCHANGED logEnd
       ELSE /\ nnState' = [nnState EXCEPT ![n] = "ACTIVE"]
            /\ nnTxid'  = [nnTxid EXCEPT ![n] = logEnd + 1]
            /\ logEnd'  = logEnd + 1
    /\ UNCHANGED <<nnRecQ, bposVars, actorVars, rec, targetFired>>

-----------------------------------------------------------------------------
(* Actor handshake: BPServiceActor.run (BPServiceActor.java:899-947) ->                  *)
(* connectToNNAndHandshake (L302-325).                                                   *)

\* First phase: versionRequest (L262 in retrieveNamespaceInfo L258-281), answered by
\* NameNodeRpcServer.versionRequest (namenode/NameNodeRpcServer.java:1755-1758) ->
\* FSNamesystem.getNamespaceInfo (FSNamesystem.java:1903-1910, 1927-1929): the NN's HA state now.
\* The retry loop runs only while shouldRun() (L260; L953-955).
VersionRequest(b, n) ==
    /\ actorSt[b][n] = "connecting"
    /\ hsResp[b][n] = "none"
    /\ ~bpStopped[b]
    /\ nnState[n] # "DOWN"
    /\ hsResp' = [hsResp EXCEPT ![b][n] = nnState[n]]
    /\ UNCHANGED <<nnVars, bposVars, actorSt, hbResp, cmdQ, rec, targetFired>>

\* L317 bpos.verifyAndSetNamespaceInfo (BPOfferService.java:382-415), one write-locked section:
\*   W1 (L386-390): ACTIVE nsInfo and bpServiceToActive == null -> this actor.  No txid check and
\*   lastActiveClaimTxId is not touched.
\*   L394-401: the first handshake of this BPOS (setNamespaceInfo returns null) calls
\*   dn.initBlockPool(this) -> blockPoolManager.addBlockPool (DataNode.java:2195 ->
\*   BlockPoolManager.java:65-72, put by bpid at L71).
VerifyAndSetNamespaceInfo(b, n) ==
    /\ actorSt[b][n] = "connecting"
    /\ hsResp[b][n] # "none"
    /\ bpServiceToActive' = [bpServiceToActive EXCEPT ![b] =
                                IF hsResp[b][n] = "ACTIVE" /\ @ = None THEN n ELSE @]
    /\ IF ~bpNSInfo[b]
       THEN /\ bpNSInfo' = [bpNSInfo EXCEPT ![b] = TRUE]
            /\ bposReg'  = b
       ELSE UNCHANGED <<bpNSInfo, bposReg>>
    /\ actorSt' = [actorSt EXCEPT ![b][n] = "registering"]
    /\ hsResp'  = [hsResp EXCEPT ![b][n] = "none"]
    /\ UNCHANGED <<nnVars, curInc, bpStopped, bpRegd, lastActiveClaimTxId, hbResp, cmdQ, rec, targetFired>>

\* Second phase (L324): register (L838-879): registerDatanode RPC (L848, retried while shouldRun,
\* L845), then bpos.registrationSucceeded (L871 -> BPOfferService.java:422-445, bpRegistration = reg
\* at L432).  Then run() enters the offerService loop (L926-938).
Register(b, n) ==
    /\ actorSt[b][n] = "registering"
    /\ ~bpStopped[b]
    /\ nnState[n] # "DOWN"
    /\ bpRegd'  = [bpRegd EXCEPT ![b] = TRUE]
    /\ actorSt' = [actorSt EXCEPT ![b][n] = "running"]
    /\ UNCHANGED <<nnVars, curInc, bposReg, bpStopped, bpNSInfo, bpServiceToActive,
                   lastActiveClaimTxId, hsResp, hbResp, cmdQ, rec, targetFired>>

-----------------------------------------------------------------------------
(* Heartbeat (Scenarios 1, 2): the NN takes a snapshot, the DN applies it later.        *)

\* offerService (BPServiceActor.java:674-813) -> sendHeartBeat (L711 -> L545-591, synchronous RPC at
\* L571, so at most one response per actor is in flight).  NN side: FSNamesystem.handleHeartbeat
\* (FSNamesystem.java:4484-4517), one BM read-lock hold (L4492-4516):
\*   commands (L4495 -> blockmanagement/DatanodeManager.java:1856-1893): a pending recovery command
\*   is returned alone (L1888-1893); getBlockRecoveryCommand drains the whole queue
\*   (DatanodeManager.java:1752-1754 -> DatanodeDescriptor.getLeaseRecoveryCommand L780-785);
\*   HA status: haContext state + getCorrectLastAppliedOrWrittenTxId (L4505-4507).
\* Commands other than DNA_RECOVERBLOCK do not touch bpServiceToActive and are not modeled.
HBSend(b, n) ==
    /\ actorSt[b][n] = "running"
    /\ ~bpStopped[b]                       \* while (shouldRun()) (L686)
    /\ hbResp[b][n] = NoResp
    /\ nnState[n] # "DOWN"
    /\ LET cmd == IF nnState[n] = "ACTIVE" THEN nnRecQ[n] ELSE <<>>
       IN /\ hbResp' = [hbResp EXCEPT ![b][n] =
                            [st |-> nnState[n], txid |-> nnTxid[n], cmd |-> cmd]]
          /\ nnRecQ' = [nnRecQ EXCEPT ![n] = IF cmd # <<>> THEN <<>> ELSE @]
    /\ UNCHANGED <<nnState, nnTxid, logEnd, bposVars, actorSt, hsResp, cmdQ, rec, targetFired>>

\* L733-734 bpos.updateActorStatesFromHeartbeat (BPOfferService.java:576-621, one write-locked
\* section), then L745-756 the response's commands are enqueued to this actor's
\* CommandProcessingThread.  The enqueue touches only this actor's queue, so it is merged into the
\* same step.  A rejected claim returns early from updateActorStatesFromHeartbeat (L598), but the
\* commands are still enqueued.
HBRecv(b, n) ==
    /\ hbResp[b][n] # NoResp
    /\ LET resp              == hbResp[b][n]
           txid              == resp.txid                                   \* L581
           nnClaimsActive    == resp.st = "ACTIVE"                          \* L583-584
           bposThinksActive  == bpServiceToActive[b] = n                    \* L585
           isMoreRecentClaim == txid > lastActiveClaimTxId[b]               \* L586
           rejected          == nnClaimsActive /\ ~bposThinksActive /\ ~isMoreRecentClaim  \* L591-598
           newActive         ==
               IF nnClaimsActive /\ ~bposThinksActive
               THEN IF isMoreRecentClaim THEN n                             \* W3: L600-606
                    ELSE bpServiceToActive[b]                               \* split-brain reject
               ELSE IF ~nnClaimsActive /\ bposThinksActive
                    THEN None                                               \* W4: L608-612
                    ELSE bpServiceToActive[b]
           \* L614-615: if (bpServiceToActive == actor) assert txid >= lastActiveClaimTxId
           assertFails == /\ ~rejected
                          /\ newActive = n
                          /\ EnableAssertions
                          /\ txid < lastActiveClaimTxId[b]
       IN
       IF assertFails
       THEN \* The AssertionError escapes offerService's catches (L791-807) and run()'s
            \* catch (Exception) (L934); catch (Throwable) at L940, then finally cleanUp()
            \* (L943-946): W2 nulls the view (bpServiceToActive == actor here).  No enqueue.
            /\ CleanUp(b, n)
            /\ UNCHANGED <<nnVars, curInc, bpStopped, bpNSInfo, bpRegd, lastActiveClaimTxId, targetFired>>
       ELSE
            /\ bpServiceToActive' = [bpServiceToActive EXCEPT ![b] = newActive]
            /\ lastActiveClaimTxId' = [lastActiveClaimTxId EXCEPT ![b] =
                                          IF ~rejected /\ newActive = n THEN txid ELSE @]  \* L614-617
            /\ hbResp' = [hbResp EXCEPT ![b][n] = NoResp]
            /\ cmdQ' = [cmdQ EXCEPT ![b][n] = IF resp.cmd # <<>> THEN Append(@, resp.cmd) ELSE @]  \* L745-756
            /\ UNCHANGED <<nnVars, curInc, bposReg, bpStopped, bpNSInfo, bpRegd, actorSt, hsResp, rec, targetFired>>

-----------------------------------------------------------------------------
(* Command acceptance (Scenario 1).                                                      *)

\* CommandProcessingThread.processQueue (BPServiceActor.java:1427-1445, runs while shouldRun()) ->
\* processCommand (L1453-1484) -> bpos.processCommandFromActor (L1458 -> BPOfferService.java:671-705):
\*   R2 (L692-698, read lock): isActiveActor = (actor == bpServiceToActive)
\*   active:  processCommandFromActive (L700-701) -> DNA_RECOVERBLOCK (L783-787) ->
\*            BlockRecoveryWorker.recoverBlocks (BlockRecoveryWorker.java:615-641): one daemon runs the
\*            command's blocks in order (L622-633).  The daemon does not keep the issuing actor (L784).
\*   standby: processCommandFromStandby (L703 -> L837-848): DNA_RECOVERBLOCK ignored (L841-848).
\* R2 and the spawn are merged: once R2 has run, nothing the daemon later reads depends on the order.
ProcessCmd(b, n) ==
    /\ actorSt[b][n] = "running"
    /\ ~bpStopped[b]                    \* stop() interrupts the command thread (BPServiceActor.java:630-632)
    /\ cmdQ[b][n] # <<>>
    /\ LET c             == Head(cmdQ[b][n])
           isActiveActor == bpServiceToActive[b] = n
       IN
       /\ cmdQ' = [cmdQ EXCEPT ![b][n] = Tail(@)]
       /\ rec' = [r \in Rec |->
                    IF r \in Range(c)
                    THEN LET idx == CHOOSE k \in DOMAIN c : c[k] = r
                         IN IF isActiveActor
                            THEN [rec[r] EXCEPT !.pc  = IF idx = 1 THEN "pre" ELSE "wait",
                                                !.nxt = IF idx < Len(c) THEN c[idx + 1] ELSE 0]
                            ELSE [rec[r] EXCEPT !.pc = "dropped"]
                    ELSE rec[r]]
    /\ UNCHANGED <<nnVars, bposVars, actorSt, hsResp, hbResp, targetFired>>

-----------------------------------------------------------------------------
(* Recovery daemon: RecoveryTaskContiguous.recover -> syncBlock -> getActiveNamenodeForBP. *)
(* Striped blocks reach the same method at L495 after a longer pre-commit phase.           *)

\* recover() pre-commit phase (BlockRecoveryWorker.java:118-184): DataNodeFaultInjector.delay()
\* (L122), then for each replica getDatanodeID(bpid) (L131 -> L562-568, a BlockPoolManager lookup by
\* bpid) and initReplicaRecovery (L135).  A null BPOS throws IOException (L564-565), a replica
\* error (L162-166); when every replica errors, "All datanodes failed" (L169-172), caught at L630-631.
\* A registered BPOS whose bpRegistration is still null makes new DatanodeID(null) (L567) throw a
\* NullPointerException, which no catch handles: the daemon thread ends (L621-636).
\* Otherwise the replicas answered and recover() calls syncBlock (L183).
RecoverPre(r) ==
    /\ rec[r].pc = "pre"
    /\ IF bposReg = 0
       THEN Finish(r, "done")
       ELSE IF ~bpRegd[bposReg]
            THEN rec' = [x \in Rec |-> IF x \in Chain(r) THEN [rec[x] EXCEPT !.pc = "done"] ELSE rec[x]]
            ELSE rec' = [rec EXCEPT ![r].pc = "lookup"]
    /\ UNCHANGED <<nnVars, bposVars, actorVars, targetFired>>

\* Replica-level failures that end the block before syncBlock: RecoveryInProgressException
\* (L157-161, return), all replicas failed (L169-172), no replica in RWR or better (L176-181).
RecoverPreFail(r) ==
    /\ rec[r].pc = "pre"
    /\ Finish(r, "done")
    /\ UNCHANGED <<nnVars, bposVars, actorVars, targetFired>>

\* syncBlock (L187-189) -> getActiveNamenodeForBP: L602 datanode.getBPOfferService(bpid)
\* (DataNode.java:2239-2241 -> BlockPoolManager.get, synchronized, BlockPoolManager.java:85-87).
\* L603-604: null -> IOException "No block pool offer service" (a different check), caught at L630-631.
RecoverLookup(r) ==
    /\ rec[r].pc = "lookup"
    /\ IF bposReg = 0
       THEN Finish(r, "done")
       ELSE rec' = [rec EXCEPT ![r].pc = "getActive", ![r].bp = bposReg]
    /\ UNCHANGED <<nnVars, bposVars, actorVars, targetFired>>

\* The target.  L607: activeNN = bpos.getActiveNN() on the BPOS obtained at L602
\* (BPOfferService.java:532-543, read lock): bpServiceToActive.bpNamenode, or null when
\* bpServiceToActive == null.  bpNamenode is set before an actor can become active
\* (BPServiceActor.java:304) and never nulled (cleanUp closes it, L651), so the result is null
\* exactly when bpServiceToActive is null (brief X1).
\* L608-610: if (activeNN == null) throw new IOException("Block pool ... has not recognized an
\* active NN") -- the throw maps to line 609 (javap).
\* Else L612 returns the proxy and syncBlock commits (L317-319); the commit's outcome is not modeled.
TargetCheck(r) ==
    /\ rec[r].pc = "getActive"
    /\ IF bpServiceToActive[rec[r].bp] = None
       THEN /\ targetFired' = TRUE
            /\ Finish(r, "fired")
       ELSE /\ UNCHANGED targetFired
            /\ Finish(r, "done")
    /\ UNCHANGED <<nnVars, bposVars, actorVars>>

-----------------------------------------------------------------------------
(* Actor exit (Scenarios 2, 3).                                                          *)

\* An actor thread ends and runs cleanUp (BPServiceActor.java:943-946).  Routes (analysis A1-A3),
\* all ending in the same cleanUp: a fatal RemoteException on heartbeat/IBR/block or cache report
\* (L791-798), or from re-registration in the command thread (L1461-1469), CommandProcessingThread
\* death (L1412-1421), an Error in the heartbeat thread (L940-946), or a DataNode-wide stop
\* (DataNode.java:2545, 2595, 2743; actors see shouldRun() false at their next loop check).
\* Only a running actor is exposed: these routes are in the offerService/command loops.
ActorExit(b, n) ==
    /\ actorSt[b][n] = "running"
    /\ CleanUp(b, n)
    /\ UNCHANGED <<nnVars, curInc, bpStopped, bpNSInfo, bpRegd, lastActiveClaimTxId, targetFired>>

-----------------------------------------------------------------------------
(* Operator refreshNamenodes for the same bpid (Scenario 4).                             *)

\* BlockPoolManager.doRefreshNamenodes (BlockPoolManager.java:175-292) for a nameservice that is
\* renamed, or removed and re-added: Step 3 creates a new BPOS with one actor per NN and starts it
\* (L214-236).  It starts with bpServiceToActive == null and lastActiveClaimTxId == -1
\* (BPOfferService.java:86, 103) and is registered by bpid on its first handshake.
RefreshAdd ==
    /\ curInc < MaxInc
    /\ curInc' = curInc + 1
    /\ actorSt' = [actorSt EXCEPT ![curInc + 1] = [n \in NN |-> "connecting"]]
    /\ UNCHANGED <<nnVars, bposReg, bpStopped, bpNSInfo, bpRegd, bpServiceToActive,
                   lastActiveClaimTxId, hsResp, hbResp, cmdQ, rec, targetFired>>

\* Step 4 (L242-252): the old BPOS is stopped (BPOfferService.stop L358-362 -> BPServiceActor.stop
\* BPServiceActor.java:622-633: shouldServiceRun = false, interrupts) and joined.  Renaming runs Step 3
\* before Step 4 in one call; remove-then-re-add runs Step 4 in an earlier call, which returns only
\* after the old actors exited (join).  A stop is allowed for an older incarnation, or for the newest
\* one while a re-add is still possible.
RefreshRemove(b) ==
    /\ b <= curInc
    /\ ~bpStopped[b]
    /\ b < curInc \/ curInc < MaxInc
    /\ \E n \in NN : InBpServices(b, n)
    /\ bpStopped' = [bpStopped EXCEPT ![b] = TRUE]
    /\ UNCHANGED <<nnVars, curInc, bposReg, bpNSInfo, bpRegd, bpServiceToActive,
                   lastActiveClaimTxId, actorVars, rec, targetFired>>

\* A stopped actor leaves its loops (shouldRun() false: L260, L686, L845, L931; init failure L913-921)
\* and runs cleanUp (L943-946).
ActorStopExit(b, n) ==
    /\ bpStopped[b]
    /\ InBpServices(b, n)
    /\ CleanUp(b, n)
    /\ UNCHANGED <<nnVars, curInc, bpStopped, bpNSInfo, bpRegd, lastActiveClaimTxId, targetFired>>

-----------------------------------------------------------------------------
(* Next-state relation.  Once the target fired, everything stops (adhoc tla-patterns 1).  *)

Next ==
    /\ ~targetFired
    /\ \/ \E n \in NN, r \in Rec : NNIssueRecovery(n, r)
       \/ \E n \in NN : NNLogEdit(n) \/ NNLogSync(n)
       \/ \E n \in NN : DemoteNN(n) \/ PromoteNN(n) \/ NNCrash(n) \/ NNRestart(n)
       \/ \E b \in Inc, n \in NN :
            \/ VersionRequest(b, n) \/ VerifyAndSetNamespaceInfo(b, n) \/ Register(b, n)
            \/ HBSend(b, n) \/ HBRecv(b, n) \/ ProcessCmd(b, n)
            \/ ActorExit(b, n) \/ ActorStopExit(b, n)
       \/ \E r \in Rec : RecoverPre(r) \/ RecoverPreFail(r) \/ RecoverLookup(r) \/ TargetCheck(r)
       \/ RefreshAdd
       \/ \E b \in Inc : RefreshRemove(b)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Invariants *)

Resp == [st : HAReports, txid : Int, cmd : Seq(Rec)]

TypeOK ==
    /\ nnState \in [NN -> NNStates]
    /\ nnTxid \in [NN -> Int]
    /\ logEnd \in Int
    /\ nnRecQ \in [NN -> Seq(Rec)]
    /\ curInc \in Inc
    /\ bposReg \in Inc \cup {0}
    /\ bpStopped \in [Inc -> BOOLEAN]
    /\ bpNSInfo \in [Inc -> BOOLEAN]
    /\ bpRegd \in [Inc -> BOOLEAN]
    /\ bpServiceToActive \in [Inc -> NN \cup {None}]
    /\ lastActiveClaimTxId \in [Inc -> Int]
    /\ actorSt \in [Inc -> [NN -> ActorStates]]
    /\ hsResp \in [Inc -> [NN -> {"none"} \cup HAReports]]
    /\ \A b \in Inc, n \in NN : hbResp[b][n] = NoResp \/ hbResp[b][n] \in Resp
    /\ cmdQ \in [Inc -> [NN -> Seq(Seq(Rec))]]
    /\ \A r \in Rec : /\ rec[r].pc \in RecPCs
                      /\ rec[r].by \in NN \cup {None}
                      /\ rec[r].bp \in Inc \cup {0}
                      /\ rec[r].nxt \in Rec \cup {0}
    /\ targetFired \in BOOLEAN

\* The target: no daemon reaches BlockRecoveryWorker.java:609.
TargetSafe == ~targetFired

\* Structural (brief section 5): the field's contract (BPOfferService.java:80-85) -- a non-null
\* bpServiceToActive refers to a member of bpServices.
ActiveActorAlive ==
    \A b \in Inc : bpServiceToActive[b] # None => InBpServices(b, bpServiceToActive[b])

\* Structural (brief section 5): an in-flight heartbeat response carries what its sender held:
\* only ACTIVE/STANDBY, a recovery command only with ACTIVE (FSNamesystem.java:4492-4516,
\* DatanodeManager.java:1884-1893, cleared on demotion FSNamesystem.java:1577), only recoveries the
\* sender itself issued, and a STANDBY txid no newer than the durable log.  Also: a non-empty NN
\* recovery queue belongs to an ACTIVE NN.
HbCarriesSenderState ==
    /\ \A b \in Inc, n \in NN :
         hbResp[b][n] # NoResp =>
           /\ hbResp[b][n].st \in HAReports
           /\ hbResp[b][n].cmd # <<>> => hbResp[b][n].st = "ACTIVE"
           /\ \A r \in Range(hbResp[b][n].cmd) : rec[r].by = n
           /\ hbResp[b][n].st = "STANDBY" => hbResp[b][n].txid <= logEnd
    /\ \A n \in NN : nnRecQ[n] # <<>> => nnState[n] = "ACTIVE"

\* Temporary reachability probe (adhoc tla-patterns 2): must be VIOLATED by MC.cfg, which shows
\* TargetCheck is enabled in some reachable state.
TargetReached == ~(\E r \in Rec : rec[r].pc = "getActive")

=============================================================================
