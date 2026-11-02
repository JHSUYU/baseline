-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-28: can a DataNode block-recovery daemon reach the failing   *)
(* branch of BlockRecoveryWorker.getDatanodeID (BRW:562-568), i.e. throw   *)
(*   IOException("No block pool offer service for bpid=" + bpid)  at L565 *)
(* because DataNode.getBPOfferService(bpid) returned null?                 *)
(*                                                                         *)
(* Category A (modeling-brief.md Section 1): DataNode threads that meet at *)
(* monitor / read-write-lock / RPC boundaries, driven by NameNode          *)
(* heartbeat traffic, NameNode rejection, refreshNamenodes and shutdown.   *)
(* One action per lock-protected step.                                     *)
(*                                                                         *)
(* One NameNode, one block pool P, one under-construction block whose      *)
(* replicas are on every DataNode (replication = |DN|, as in the workload).*)
(*                                                                         *)
(* Source citations (pinned tree @734dd8a67cd), paths relative to          *)
(* hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/   *)
(* server/:                                                                *)
(*   BRW  datanode/BlockRecoveryWorker.java                                *)
(*   BPOS datanode/BPOfferService.java                                     *)
(*   BPM  datanode/BlockPoolManager.java                                   *)
(*   BPSA datanode/BPServiceActor.java (CommandProcessingThread: 1400-1525)*)
(*   DNJ  datanode/DataNode.java                                           *)
(*   DS   datanode/DataStorage.java                                        *)
(*   BPSS datanode/BlockPoolSliceStorage.java                              *)
(*   FSD  datanode/fsdataset/impl/FsDatasetImpl.java                       *)
(*   FSV  datanode/fsdataset/impl/FsVolumeImpl.java                        *)
(*   DXS  datanode/DataXceiverServer.java                                  *)
(*   DM   blockmanagement/DatanodeManager.java                             *)
(*   DD   blockmanagement/DatanodeDescriptor.java                          *)
(*   BUC  blockmanagement/BlockUnderConstructionFeature.java               *)
(*   PRB  blockmanagement/PendingRecoveryBlocks.java                       *)
(*   FSN  namenode/FSNamesystem.java                                       *)
(*   DID  hadoop-hdfs-client .../hdfs/protocol/DatanodeID.java             *)
(*                                                                         *)
(* Scenario map (modeling-brief.md Section 2):                             *)
(*   Scenario 1 (daemon outlives its BPOS): DnStop, DnShutDownAll,         *)
(*     RefreshNodesDisallow + ActorHeartbeat rejection, the exit           *)
(*     (ActorCleanUp, ActorShutdownActor, ActorExitRemove,                 *)
(*     ActorExitRelease), the command thread's assert / read / dispatch    *)
(*     split (CptAssert, CptRead, CptDispatch), the daemon loop (RecStart, *)
(*     TargetCheck, RecRpc).                                               *)
(*   Scenario 2 (same-pool BPOS replacement): RefreshStartNew,             *)
(*     RefreshStopOld, RefreshJoinOld, the split handshake (HsAddBlockPool,*)
(*     HsInitStorage, which fails on a loaded pool or a pending interrupt) *)
(*     and the split exit (ActorExitRemove: the key-based                  *)
(*     BlockPoolManager.remove; ActorExitRelease: release by pool id).     *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    DN,                 \* DataNodes (MiniDFSCluster.numDataNodes)
    NoDn,               \* marker for an unused daemon record (not in DN)
    MaxSlot,            \* BPOfferService objects per DataNode: slot 1 = the
                        \* startup BPOS (nameservice null, DNJ:1958-1959);
                        \* slot 2 = the BPOS a refreshNamenodes creates when
                        \* it re-homes the NameNode under nameservice ns1
                        \* (Scenario 2)
    MaxAttempts,        \* NameNode recovery attempts for the block
                        \* (recovery ids 1..MaxAttempts, in GS order)
    AssertionsEnabled   \* JVM -ea (surefire default): the assert at BPOS:673

ASSUME /\ DN # {}
       /\ NoDn \notin DN
       /\ MaxSlot \in {1, 2}
       /\ MaxAttempts \in Nat \ {0}
       /\ AssertionsEnabled \in BOOLEAN

Slot   == 1..MaxSlot
NoSlot == 0
Bpos   == DN \X Slot            \* one NameNode: one actor per BPOS, so the
                                \* actor and its command thread share the id
DnOf(b)   == b[1]
SlotOf(b) == b[2]

\* One recovery daemon per delivered DNA_RECOVERBLOCK command; a command
\* carries the delivery number as its daemon id. The NameNode queues the
\* block at most once per attempt (DD:717-724, BUC:284-287), so there are at
\* most MaxAttempts deliveries.
Rec == 1..MaxAttempts

ActPcs == {"none", "conn", "hsNs", "hsAdd", "hsStorage", "reg", "loop", "hb",
           "cleanUp", "shutdownActor", "exitRemove", "exitRelease", "dead"}
CptPcs == {"none", "loop", "take", "assert", "read", "dispatch", "dead"}
RecSts == {"none", "start", "check", "rpc", "post", "active", "commit",
           "done", "npe"}

\* A queued DNA_RECOVERBLOCK batch: daemon id, recovery id, locations.
Cmd   == [rid : Rec, att : 1..MaxAttempts, nlocs : 1..Cardinality(DN)]
NoCmd == [rid |-> 0, att |-> 0, nlocs |-> 0]

\* A recovery daemon (BRW:615-641) running RecoveryTaskContiguous (BRW:103-321):
\* its DataNode, the dispatching BPOS's slot, the recovery id, the number of
\* locations, the current location, errorCount, and the BPOS that the
\* getActiveNamenodeForBP lookup (BRW:602) returned.
RecType == [st : RecSts, dn : DN \cup {NoDn}, slot : 0..MaxSlot,
            att : 0..MaxAttempts, nlocs : 0..Cardinality(DN),
            idx : 0..(Cardinality(DN) + 1), err : 0..Cardinality(DN),
            pb : 0..MaxSlot]
NoRec == [st |-> "none", dn |-> NoDn, slot |-> NoSlot, att |-> 0,
          nlocs |-> 0, idx |-> 0, err |-> 0, pb |-> NoSlot]

VARIABLES
    \* ---- DataNode process ----
    dnPc,        \* [DN -> {"run","stopping","stopped"}]: DataNode.shouldRun
                 \* (DNJ:395) is TRUE iff "run"; "stopped" = the shutdown
                 \* thread passed shutDownAll (DNJ:2662-2668)
    refreshPc,   \* [DN -> {"idle","step4","join","done"}]: the
                 \* refreshNamenodes thread (Scenario 2)
    \* ---- BlockPoolManager, one block pool P ----
    bpmByPool,   \* [DN -> 0..MaxSlot]: bpByBlockPoolId.get(P) (BPM:51-52);
                 \* NoSlot = no entry. THE TARGET GUARD'S OPERAND.
    bpmSvcs,     \* [DN -> SUBSET Slot]: offerServices (BPM:53-54); always
                 \* the same objects as bpByNameserviceId's values (BPM:49-50):
                 \* put together (BPM:232-233), removed together (BPM:90, 97-106)
    poolLoaded,  \* [DN -> BOOLEAN]: P's BlockPoolSliceStorage is in
                 \* DataStorage.bpStorageMap and P's slices are in FsDataset;
                 \* loaded together (DNJ:2199, 2202), released together
                 \* (DNJ:2164, 2168)
    \* ---- BPOfferService objects ----
    bpNs,        \* [Bpos -> BOOLEAN]: bpNSInfo / bpId set (BPOS:67, 77),
                 \* i.e. hasBlockPoolId() (BPOS:232-234)
    bpReg,       \* [Bpos -> BOOLEAN]: bpRegistration != null (BPOS:74)
    bpActive,    \* [Bpos -> BOOLEAN]: bpServiceToActive == its actor (BPOS:86)
    bpServed,    \* [Bpos -> BOOLEAN]: its actor is in bpServices (BPOS:92-93)
    \* ---- BPServiceActor main thread ----
    actPc,       \* [Bpos -> ActPcs]
    actRun,      \* [Bpos -> BOOLEAN]: shouldServiceRun (BPSA:116)
    stopped,     \* [Bpos -> BOOLEAN]: BPServiceActor.stop() ran (BPSA:622-633):
                 \* the actor thread and the command thread are interrupted
    \* ---- CommandProcessingThread ----
    cptPc,       \* [Bpos -> CptPcs]
    cptQ,        \* [Bpos -> Seq(Cmd)]: queued DNA_RECOVERBLOCK batches
                 \* (other batches are abstracted, see CptOtherBatch)
    cptCur,      \* [Bpos -> Cmd \cup {NoCmd}]: the batch being processed
    cptSnap,     \* [Bpos -> BOOLEAN]: the isActiveActor snapshot (BPOS:694)
    \* ---- recovery daemons ----
    rec,         \* [Rec -> RecType]
    \* ---- NameNode (abstract) ----
    nnRec,       \* [att : 0..MaxAttempts, done : BOOLEAN]: the block's current
                 \* recovery id (0 = no recovery yet; BUC:241) and whether it
                 \* was committed and the file closed
    nnChosen,    \* SUBSET DN: replicas chosen as primary (BUC:253-287)
    nnRecQ,      \* [DN -> BOOLEAN]: the block is in that DatanodeDescriptor's
                 \* recoverBlocks queue (DD:205, 717-724)
    nnBanned,    \* [DN -> BOOLEAN]: isDisallowed() (DM:1408-1411)
    nnDead,      \* [DN -> BOOLEAN]: setDatanodeDead zeroed lastUpdate
                 \* (DM:1747-1750, 1871-1872)
    nnReg,       \* [DN -> BOOLEAN]: registered at the NameNode
    nnDeliv,     \* 0..MaxAttempts: recovery commands handed out (daemon ids)
    \* ---- the ad hoc target ----
    targetFired  \* BRW:565 executed

dnVars   == <<dnPc, refreshPc>>
bpmVars  == <<bpmByPool, bpmSvcs, poolLoaded>>
bposVars == <<bpNs, bpReg, bpActive, bpServed>>
actVars  == <<actPc, actRun, stopped>>
cptVars  == <<cptPc, cptQ, cptCur, cptSnap>>
nnVars   == <<nnRec, nnChosen, nnRecQ, nnBanned, nnDead, nnReg, nnDeliv>>
vars == <<dnVars, bpmVars, bposVars, actVars, cptVars, rec, nnVars,
          targetFired>>

----------------------------------------------------------------------------
\* Helpers

\* BPServiceActor.shouldRun() (BPSA:953-955): shouldServiceRun && dn.shouldRun()
\* (DNJ:4020-4022). The command thread calls the same method (BPSA:1428).
ShouldRun(b) == actRun[b] /\ dnPc[DnOf(b)] = "run"

\* The BPOS write lock is held: by the handshake from verifyAndSetNamespaceInfo
\* (BPOS:384) until initBlockPool returns (BPOS:412-413), and by shutdownActor
\* from BPOS:477 until the release ends (BPOS:488-490). Readers (BPOS:692,
\* 533) wait.
WriteLocked(b) == actPc[b] \in {"hsAdd", "hsStorage", "exitRemove", "exitRelease"}

\* Locations of a recovery command (DM:1765-1809): the expected locations
\* without stale and dead nodes if more than one remains, else every alive
\* one. A node that setDatanodeDead zeroed is stale; DatanodeDescriptor
\* isAlive() stays true for every replica because heartbeat expiry
\* (minutes) is not modeled.
NLocs ==
    LET fresh == {x \in DN : ~nnDead[x]}
    IN IF Cardinality(fresh) > 1 THEN Cardinality(fresh) ELSE Cardinality(DN)

\* BUC.initializeBlockRecovery L253-287: choose the primary and queue the
\* block at it.
ChoosePrimary ==
    LET \* L253-260: have all alive replicas been chosen already? (isAlive()
        \* holds for every replica, see NLocs)
        tried == DN \subseteq nnChosen
        \* L261-266: if so, clear every chosenAsPrimary flag
        base  == IF tried THEN {} ELSE nnChosen
        \* L270-283: alive, not chosen yet, lastUpdate > 0 (a node zeroed by
        \* setDatanodeDead never wins the "lastUpdate > mostRecent" test)
        cands == {x \in DN \ base : ~nnDead[x]}
    IN IF cands = {}
       THEN \* L284: no primary, nothing is queued
            /\ nnChosen' = base
            /\ UNCHANGED nnRecQ
       ELSE \* the most recent heartbeat wins (L276-282): timing, so any
            \E p \in cands :
              /\ nnRecQ' = [nnRecQ EXCEPT ![p] = TRUE]    \* L285-286; DD:717-724
              /\ nnChosen' = base \cup {p}                 \* L287

\* The location loop of RecoveryTaskContiguous.recover (BRW:129-167): go to
\* the next location; an IOException adds to errorCount (BRW:162-166).
NextLoc(r, failed) ==
    [r EXCEPT !.err = @ + (IF failed THEN 1 ELSE 0),
              !.idx = @ + 1,
              !.st  = IF r.idx < r.nlocs THEN "check" ELSE "post"]

----------------------------------------------------------------------------
\* Initial state: both DataNodes have run BlockPoolManager.refreshNamenodes
\* at startup (DNJ:1958-1959 -> BPM:185-237 Steps 1-3): one BPOS for the null
\* nameservice, whose actor was just started (BPSA:599-611) and whose
\* command thread started in the actor constructor (BPSA:159-160). The
\* NameNode is up and out of safe mode; the file is not yet written.

Init ==
    /\ dnPc = [d \in DN |-> "run"]
    /\ refreshPc = [d \in DN |-> "idle"]
    /\ bpmByPool = [d \in DN |-> NoSlot]
    /\ bpmSvcs = [d \in DN |-> {1}]
    /\ poolLoaded = [d \in DN |-> FALSE]
    /\ bpNs = [b \in Bpos |-> FALSE]
    /\ bpReg = [b \in Bpos |-> FALSE]
    /\ bpActive = [b \in Bpos |-> FALSE]
    /\ bpServed = [b \in Bpos |-> SlotOf(b) = 1]      \* BPOS:139-142
    /\ actPc = [b \in Bpos |-> IF SlotOf(b) = 1 THEN "conn" ELSE "none"]
    /\ actRun = [b \in Bpos |-> TRUE]                 \* BPSA:116
    /\ stopped = [b \in Bpos |-> FALSE]
    /\ cptPc = [b \in Bpos |-> IF SlotOf(b) = 1 THEN "loop" ELSE "none"]
    /\ cptQ = [b \in Bpos |-> <<>>]
    /\ cptCur = [b \in Bpos |-> NoCmd]
    /\ cptSnap = [b \in Bpos |-> FALSE]
    /\ rec = [i \in Rec |-> NoRec]
    /\ nnRec = [att |-> 0, done |-> FALSE]
    /\ nnChosen = {}
    /\ nnRecQ = [d \in DN |-> FALSE]
    /\ nnBanned = [d \in DN |-> FALSE]
    /\ nnDead = [d \in DN |-> FALSE]
    /\ nnReg = [d \in DN |-> FALSE]
    /\ nnDeliv = 0
    /\ targetFired = FALSE

----------------------------------------------------------------------------
\* DataNode-wide stop (Scenario 1 trigger)

\* DataNode.shutdown sets shouldRun = false early (DNJ:2540-2546, again at
\* L2595). The same flag is cleared by handleDiskError when too few volumes
\* remain (DNJ:2738-2744) and by a fatal DataXceiverServer error
\* (DXS:277-280); those paths never run shutDownAll.
DnStop(d) ==
    /\ dnPc[d] = "run"
    /\ dnPc' = [dnPc EXCEPT ![d] = "stopping"]
    /\ UNCHANGED <<refreshPc, bpmVars, bposVars, actVars, cptVars, rec, nnVars,
                   targetFired>>

\* DataNode.shutdown, later: threadGroup.interrupt (DNJ:2604-2629: recovery
\* daemons, an in-flight RPC fails; RecRpc's "ioe"), ipcServer.stop
\* (DNJ:2654-2656: peers' RPCs to d fail; RecRpc's "ioe"), then
\* BlockPoolManager.shutDownAll (DNJ:2662-2668 -> BPM:113-121): stop() every
\* BPOS still in offerServices (the list view of BPM:81-83 is read when
\* iterated), which stops each actor (BPOS:358-362 -> BPSA:622-633), then
\* join. Nothing waits for or cancels recovery daemons.
DnShutDownAll(d) ==
    /\ dnPc[d] = "stopping"
    /\ LET S == {<<d, k>> : k \in bpmSvcs[d]}
       IN /\ actRun' = [b \in Bpos |-> IF b \in S THEN FALSE ELSE actRun[b]]
          /\ stopped' = [b \in Bpos |-> IF b \in S THEN TRUE ELSE stopped[b]]
    /\ dnPc' = [dnPc EXCEPT ![d] = "stopped"]
    /\ UNCHANGED <<refreshPc, bpmVars, bposVars, actPc, cptVars, rec, nnVars,
                   targetFired>>

----------------------------------------------------------------------------
\* NameNode-side rejection (Scenario 1 trigger)

\* DatanodeManager.refreshNodes -> refreshDatanodes (DM:1403-1411): a node no
\* longer in the include list is disallowed. Its next heartbeat is rejected
\* (DM:1870-1874) and so is any registration (DM:1211-1214).
RefreshNodesDisallow(d) ==
    /\ ~nnBanned[d]
    /\ nnBanned' = [nnBanned EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, rec, nnRec,
                   nnChosen, nnRecQ, nnDead, nnReg, nnDeliv, targetFired>>

----------------------------------------------------------------------------
\* refreshNamenodes re-homing the NameNode under nameservice ns1 (Scenario 2)

\* DataNode.refreshNamenodes(conf) (DNJ:3806-3815) -> BPM.refreshNamenodes
\* (BPM:148-173) with dfs.nameservices=ns1 and no ns1 address keys, which
\* resolves to the same NameNode (modeling-brief.md Scenario 2 evidence).
\* doRefreshNamenodes Steps 1-3 run under the BlockPoolManager monitor
\* (BPM:185-237):
\*   Step 1 (BPM:189-195): ns1 is not in bpByNameserviceId -> toAdd = {ns1};
\*   Step 2 (BPM:199-200): toRemove = keySet - {ns1}, a live view;
\*   Step 3 (BPM:210-236): createBPOS (BPM:230; BPOS:127-143, one actor whose
\*     constructor starts its command thread, BPSA:159-160);
\*     bpByNameserviceId.put and offerServices.add (BPM:232-233);
\*     startAll (BPM:236, 123-140): running actors are left alone
\*     (BPSA:600-603), the new actor's thread starts (BPSA:604-610).
\* The refresh is an operator action on a running DataNode; a refresh that
\* races DataNode.shutdown is not modeled.
RefreshStartNew(d) ==
    /\ MaxSlot >= 2
    /\ dnPc[d] = "run"
    /\ refreshPc[d] = "idle"
    /\ actPc[<<d, 2>>] = "none"
    /\ bpmSvcs' = [bpmSvcs EXCEPT ![d] = @ \cup {2}]
    /\ bpServed' = [bpServed EXCEPT ![<<d, 2>>] = TRUE]
    /\ actPc' = [actPc EXCEPT ![<<d, 2>>] = "conn"]
    /\ cptPc' = [cptPc EXCEPT ![<<d, 2>>] = "loop"]
    /\ refreshPc' = [refreshPc EXCEPT ![d] = "step4"]
    /\ UNCHANGED <<dnPc, bpmByPool, poolLoaded, bpNs, bpReg, bpActive, actRun,
                   stopped, cptQ, cptCur, cptSnap, rec, nnVars, targetFired>>

\* Step 4 (BPM:239-251), outside the monitor. toRemove is a live view of
\* bpByNameserviceId's keys (BPM:199-200): if the null BPOS already left the
\* map (its actor exited), nothing is stopped. Otherwise bpos.stop()
\* (BPM:248 -> BPOS:358-362 -> BPSA:622-633: shouldServiceRun = false,
\* interrupt the actor and its command thread) and then bpos.join()
\* (BPM:249); "they will call remove on their own" (BPM:250).
RefreshStopOld(d) ==
    /\ refreshPc[d] = "step4"
    /\ IF 1 \in bpmSvcs[d]
       THEN /\ actRun' = [actRun EXCEPT ![<<d, 1>>] = FALSE]
            /\ stopped' = [stopped EXCEPT ![<<d, 1>>] = TRUE]
            /\ refreshPc' = [refreshPc EXCEPT ![d] = "join"]
       ELSE /\ refreshPc' = [refreshPc EXCEPT ![d] = "done"]   \* L242 false; Step 5: toRefresh empty
            /\ UNCHANGED <<actRun, stopped>>
    /\ UNCHANGED <<dnPc, bpmVars, bposVars, actPc, cptVars, rec, nnVars,
                   targetFired>>

\* bpos.join() returns once the old actor thread ended (BPOS:365-369 ->
\* BPSA:636-645); Step 5 has nothing to refresh (BPM:254-291).
RefreshJoinOld(d) ==
    /\ refreshPc[d] = "join"
    /\ actPc[<<d, 1>>] = "dead"
    /\ refreshPc' = [refreshPc EXCEPT ![d] = "done"]
    /\ UNCHANGED <<dnPc, bpmVars, bposVars, actVars, cptVars, rec, nnVars,
                   targetFired>>

----------------------------------------------------------------------------
\* BPServiceActor main thread: handshake (BPSA:302-325, run L900-947)

\* BPSA:302-308 -> retrieveNamespaceInfo (BPSA:258-281).
ActorVersionRequest(b) ==
    /\ actPc[b] = "conn"
    /\ actPc' = [actPc EXCEPT ![b] =
                   IF ShouldRun(b)                 \* L260
                   THEN "hsNs"                     \* versionRequest returns (L262);
                                                   \* checkNNVersion (L276)
                   ELSE "cleanUp"]                 \* nsInfo null: IOException (L278)
                   \* -> INIT_FAILED (L912); shouldRetryInit() is false because
                   \* shouldRun() is false (L949-951) -> FAILED, return
                   \* (L919-921) -> finally cleanUp (L943-946)
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actRun, stopped, cptVars, rec,
                   nnVars, targetFired>>

\* BPSA:311-317 -> BPOfferService.verifyAndSetNamespaceInfo (BPOS:382-415),
\* under this BPOS's write lock (L384).
ActorVerifyNsInfo(b) ==
    /\ actPc[b] = "hsNs"
    \* L386-390: the NameNode reports ACTIVE (a non-HA NameNode's state,
    \* FSN:1927-1928, 5699-5700) and bpServiceToActive is null or already
    \* this actor -> bpServiceToActive = this actor
    /\ bpActive' = [bpActive EXCEPT ![b] = TRUE]
    /\ IF ~bpNs[b]
       THEN \* L394: setNamespaceInfo returns null (BPOS:246-265 sets bpNSInfo
            \* and bpId) -> dn.initBlockPool(this) (L401)
            /\ bpNs' = [bpNs EXCEPT ![b] = TRUE]
            /\ actPc' = [actPc EXCEPT ![b] = "hsAdd"]
       ELSE \* retry after a failed registration: same NameNode, the
            \* checkNSEquality calls pass (BPOS:250-257); initBlockPool is
            \* skipped; register (BPSA:324)
            /\ actPc' = [actPc EXCEPT ![b] = "reg"]
            /\ UNCHANGED bpNs
    /\ UNCHANGED <<dnVars, bpmVars, bpReg, bpServed, actRun, stopped, cptVars,
                   rec, nnVars, targetFired>>

\* DataNode.initBlockPool L2185-2195 (still under the BPOS write lock):
\* getNamespaceInfo is set (L2186-2190); setClusterId (L2192, DataNode
\* monitor) sees the same cluster; blockPoolManager.addBlockPool (L2195 ->
\* BPM:65-72, BlockPoolManager monitor).
HsAddBlockPool(b) ==
    /\ actPc[b] = "hsAdd"
    /\ IF SlotOf(b) \in bpmSvcs[DnOf(b)]
       THEN \* BPM:66-67 holds; BPM:71 put(P, bpos) replaces any entry
            /\ bpmByPool' = [bpmByPool EXCEPT ![DnOf(b)] = SlotOf(b)]
            /\ actPc' = [actPc EXCEPT ![b] = "hsStorage"]
            /\ UNCHANGED bpNs
       ELSE \* "Unknown BPOS" IllegalArgumentException (BPM:66-67): the
            \* namespace info is reset (BPOS:403-409) and the Throwable ends
            \* the actor (BPSA:940-946). Unreachable with one actor per BPOS.
            /\ bpNs' = [bpNs EXCEPT ![b] = FALSE]
            /\ actPc' = [actPc EXCEPT ![b] = "cleanUp"]
            /\ UNCHANGED bpmByPool
    /\ UNCHANGED <<dnVars, bpmSvcs, poolLoaded, bpReg, bpActive, bpServed,
                   actRun, stopped, cptVars, rec, nnVars, targetFired>>

\* DataNode.initBlockPool L2197-2211: initStorage (L2199 -> L2251-2280; the
\* storage load runs under the DataNode monitor, L2262-2264, and the
\* DataStorage monitor, DS:382) then data.addBlockPool (L2202).
\* Two ways the load fails, both ending the same way:
\*  - stopped[b]: BPSA.stop interrupted this thread (BPSA:627-629) after its
\*    version request, and nothing in the handshake since then waits
\*    interruptibly (the BPOS write lock and the monitors do not), so the
\*    interrupt is still pending. The load then reaches an interruptible
\*    FileChannel operation, which closes the channel and throws
\*    ClosedByInterruptException: the DataNode-level directory lock
\*    (common/Storage.java:700, 906-911, 943 via DS:414-415) or, on a
\*    block-pool directory (shared, so not locked: Storage.java:906-910,
\*    BPSS:153-154), the VERSION write of a regular load (BPSS:181-189 ->
\*    common/Storage.java:1263-1282, L1281);
\*  - P's storage is still loaded: containsStorageDir (BPSS:221-225).
\* Either way each directory fails (DS:424-426 or DS:473-476), "All
\* specified directories have failed to load" (DS:564-569) -> the
\* namespace info is reset (BPOS:403-409) -> INIT_FAILED (BPSA:912);
\* shouldRetryInit (BPSA:949-951; BPOS:860-867): hasBlockPoolId() is false
\* and isAlive() is false (this actor is INIT_FAILED, BPSA:171-177; one
\* NameNode) -> FAILED, return (BPSA:919-921) -> cleanUp. The
\* bpByBlockPoolId entry put at L2195 stays.
HsInitStorage(b) ==
    /\ actPc[b] = "hsStorage"
    /\ IF ~stopped[b] /\ ~poolLoaded[DnOf(b)]
       THEN \* a fresh BlockPoolSliceStorage for P (DS:1410-1418) loads every
            \* directory (DS:450-501); FsDataset adds P (L2202); disk check
            \* and scanners (L2207-2211); verifyAndSetNamespaceInfo returns
            \* (BPOS:412-414); register next (BPSA:318-324)
            /\ poolLoaded' = [poolLoaded EXCEPT ![DnOf(b)] = TRUE]
            /\ actPc' = [actPc EXCEPT ![b] = "reg"]
            /\ UNCHANGED bpNs
       ELSE /\ bpNs' = [bpNs EXCEPT ![b] = FALSE]
            /\ actPc' = [actPc EXCEPT ![b] = "cleanUp"]
            /\ UNCHANGED poolLoaded
    /\ UNCHANGED <<dnVars, bpmByPool, bpmSvcs, bpReg, bpActive, bpServed,
                   actRun, stopped, cptVars, rec, nnVars, targetFired>>

\* BPServiceActor.register (BPSA:838-879); run() continues at L926.
ActorRegister(b) ==
    LET d == DnOf(b) IN
    /\ actPc[b] = "reg"
    /\ IF ~ShouldRun(b)
       THEN \* L845 not entered: bpRegistration null -> IOException (L866-867)
            \* -> INIT_FAILED; shouldRetryInit() false -> FAILED -> cleanUp
            /\ actPc' = [actPc EXCEPT ![b] = "cleanUp"]
            /\ UNCHANGED <<bpReg, nnReg>>
       ELSE IF nnBanned[d]
       THEN \* registerDatanode: not in the include list ->
            \* DisallowedDatanodeException (DM:1211-1214), rethrown (L856-858)
            \* -> INIT_FAILED (L912); shouldRetryInit(): hasBlockPoolId() is
            \* true (BPOS:861-864) -> retry after 5 s (L913-917): the whole
            \* connectToNNAndHandshake again (L904-909)
            /\ actPc' = [actPc EXCEPT ![b] = "conn"]
            /\ UNCHANGED <<bpReg, nnReg>>
       ELSE \* registerDatanode accepts (DM:1188-1300; a re-registration of
            \* the same node keeps its recovery queue, DD:1003-1014); the
            \* actor's registration is set (L848-850);
            \* bpos.registrationSucceeded (L871 -> BPOS:422-445, L432);
            \* runningState = RUNNING (L926); offerService (L931-933)
            /\ nnReg' = [nnReg EXCEPT ![d] = TRUE]
            /\ bpReg' = [bpReg EXCEPT ![b] = TRUE]
            /\ actPc' = [actPc EXCEPT ![b] = "loop"]
    /\ UNCHANGED <<dnVars, bpmVars, bpNs, bpActive, bpServed, actRun, stopped,
                   cptVars, rec, nnRec, nnChosen, nnRecQ, nnBanned, nnDead,
                   nnDeliv, targetFired>>

----------------------------------------------------------------------------
\* BPServiceActor main thread: offerService (BPSA:674-813)

\* BPSA:686 while (shouldRun()) (and run()'s L931 once offerService returns).
ActorLoop(b) ==
    /\ actPc[b] = "loop"
    /\ actPc' = [actPc EXCEPT ![b] =
                   IF ShouldRun(b) THEN "hb"
                   ELSE "cleanUp"]      \* runningState = EXITED (L939);
                                        \* finally cleanUp (L943-946)
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actRun, stopped, cptVars, rec,
                   nnVars, targetFired>>

\* One offerService iteration (BPSA:688-811).
ActorHeartbeat(b) ==
    LET d == DnOf(b) IN
    /\ actPc[b] = "hb"
    /\ \/ \* No effect on the model:
          \*  - L694: no heartbeat due in this iteration (an IBR was pending,
          \*    L760-764);
          \*  - stopped[b]: BPSA.stop interrupted the heartbeat RPC
          \*    (BPSA:627-629) -> IOException (L805-807);
          \*  - ~poolLoaded[d]: sendHeartBeat builds storage reports
          \*    (L548-549 -> FSD:163-185 -> FSV:420-422, 562-567: "block pool
          \*    ... is not found") -> IOException (L805-807).
          \* Trace.tla checks which of these the event reports.
          /\ actPc' = [actPc EXCEPT ![b] = "loop"]
          /\ UNCHANGED <<actRun, cptQ, nnRecQ, nnDead, nnDeliv>>
       \/ \* The NameNode rejects the heartbeat: isDisallowed() ->
          \* setDatanodeDead, DisallowedDatanodeException (DM:1870-1874)
          \* -> BPSA:791-799: shouldServiceRun = false; return -> run()
          \* L931 is false -> cleanUp (L943-946)
          /\ ~stopped[b] /\ poolLoaded[d] /\ nnBanned[d]
          /\ nnDead' = [nnDead EXCEPT ![d] = TRUE]
          /\ actRun' = [actRun EXCEPT ![b] = FALSE]
          /\ actPc' = [actPc EXCEPT ![b] = "cleanUp"]
          /\ UNCHANGED <<cptQ, nnRecQ, nnDeliv>>
       \/ \* The heartbeat is accepted (DM:1879-1893).
          \* updateActorStatesFromHeartbeat (L733-734): one ACTIVE NameNode
          \* that this BPOS already treats as active, no change (BPOS:583-617).
          /\ ~stopped[b] /\ poolLoaded[d] /\ ~nnBanned[d]
          /\ IF nnRecQ[d]
             THEN \* getBlockRecoveryCommand drains the queue (DM:1752-1757;
                  \* DD:780-785)
                  /\ nnRecQ' = [nnRecQ EXCEPT ![d] = FALSE]
                  /\ IF ~nnRec.done
                     THEN \* a BlockRecoveryCommand with the block's current
                          \* recovery id (DM:1758-1825, L1815-1816) is
                          \* enqueued for the command thread (BPSA:745-756)
                          /\ nnDeliv' = nnDeliv + 1
                          /\ cptQ' = [cptQ EXCEPT ![b] = Append(@,
                                        [rid |-> nnDeliv + 1,
                                         att |-> nnRec.att,
                                         nlocs |-> NLocs])]
                     ELSE \* the block is complete: "Recovery block ... where
                          \* it is not under construction" (DM:1760-1763) ->
                          \* RemoteException, no commands (BPSA:800-804)
                          UNCHANGED <<nnDeliv, cptQ>>
             ELSE UNCHANGED <<nnRecQ, nnDeliv, cptQ>>
          \* reports and waitTillNextIBR (L760-790), loop (L811-812)
          /\ actPc' = [actPc EXCEPT ![b] = "loop"]
          /\ UNCHANGED <<actRun, nnDead>>
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, stopped, cptPc, cptCur, cptSnap,
                   rec, nnRec, nnChosen, nnBanned, nnReg, targetFired>>

----------------------------------------------------------------------------
\* BPServiceActor exit: cleanUp -> shutdownActor -> shutdownBlockPool

\* The exit is four steps because lock-free readers see each write when it
\* happens: the command thread's shouldRun() (BPSA:1428) and its assert
\* (BPOS:673) take no lock, the map readers take the BlockPoolManager
\* monitor, and the bpServiceToActive readers take the BPOS read lock.

\* cleanUp (BPSA:648-652): shouldServiceRun = false (L650); the NameNode and
\* lifeline proxies are closed (L651-652).
ActorCleanUp(b) ==
    /\ actPc[b] = "cleanUp"
    /\ actRun' = [actRun EXCEPT ![b] = FALSE]
    /\ actPc' = [actPc EXCEPT ![b] = "shutdownActor"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, stopped, cptVars, rec, nnVars,
                   targetFired>>

\* bpos.shutdownActor (BPSA:653 -> BPOS:476-485), under this BPOS's write lock
\* (L477): bpServiceToActive cleared if it was this actor (L479-481),
\* bpServices.remove (L483); bpServices is now empty (one NameNode), so
\* dn.shutdownBlockPool(this) follows (L485-487).
ActorShutdownActor(b) ==
    /\ actPc[b] = "shutdownActor"
    /\ bpActive' = [bpActive EXCEPT ![b] = FALSE]
    /\ bpServed' = [bpServed EXCEPT ![b] = FALSE]
    /\ actPc' = [actPc EXCEPT ![b] = "exitRemove"]
    /\ UNCHANGED <<dnVars, bpmVars, bpNs, bpReg, actRun, stopped, cptVars, rec,
                   nnVars, targetFired>>

\* DataNode.shutdownBlockPool L2151-2152 -> BlockPoolManager.remove
\* (BPM:89-111, BlockPoolManager monitor), still under the BPOS write lock.
ActorExitRemove(b) ==
    LET d == DnOf(b) IN
    /\ actPc[b] = "exitRemove"
    \* BPM:90 offerServices.remove; BPM:97-106 bpByNameserviceId by identity
    /\ bpmSvcs' = [bpmSvcs EXCEPT ![d] = @ \ {SlotOf(b)}]
    \* BPM:91-95: if hasBlockPoolId(), bpByBlockPoolId.remove(P), BY KEY:
    \* the entry goes whichever BPOS it maps to
    /\ bpmByPool' = IF bpNs[b] THEN [bpmByPool EXCEPT ![d] = NoSlot]
                    ELSE bpmByPool
    /\ actPc' = [actPc EXCEPT ![b] = "exitRelease"]
    /\ UNCHANGED <<dnVars, poolLoaded, bposVars, actRun, stopped, cptVars, rec,
                   nnVars, targetFired>>

\* DataNode.shutdownBlockPool L2153-2171, still under this BPOS's write lock
\* (BPOS:477-490): if hasBlockPoolId(), release P from FsDataset (L2164) and
\* from DataStorage (L2168), by pool id. Then the write lock is released
\* (BPOS:489) and the actor thread ends (BPSA:944-947).
ActorExitRelease(b) ==
    /\ actPc[b] = "exitRelease"
    /\ poolLoaded' = IF bpNs[b] THEN [poolLoaded EXCEPT ![DnOf(b)] = FALSE]
                     ELSE poolLoaded
    /\ actPc' = [actPc EXCEPT ![b] = "dead"]
    /\ UNCHANGED <<dnVars, bpmByPool, bpmSvcs, bposVars, actRun, stopped,
                   cptVars, rec, nnVars, targetFired>>

----------------------------------------------------------------------------
\* CommandProcessingThread (BPSA:1400-1525)

\* BPSA:1428 while (shouldRun()); on false the loop ends, the queue is
\* cleared (L1443-1444) and work()'s finally clears shouldServiceRun
\* (L1418-1421).
CptLoop(b) ==
    /\ cptPc[b] = "loop"
    /\ IF ShouldRun(b)
       THEN /\ cptPc' = [cptPc EXCEPT ![b] = "take"]
            /\ UNCHANGED <<cptQ, actRun>>
       ELSE /\ cptPc' = [cptPc EXCEPT ![b] = "dead"]
            /\ cptQ' = [cptQ EXCEPT ![b] = <<>>]
            /\ actRun' = [actRun EXCEPT ![b] = FALSE]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actPc, stopped, cptCur, cptSnap,
                   rec, nnVars, targetFired>>

\* BPSA:1430 queue.take() returns a DNA_RECOVERBLOCK batch. A thread parked
\* here does not re-check shouldRun() (that is L1428), so it still takes a
\* batch enqueued after the flag flipped; an interrupt makes take() throw
\* instead (CptInterrupted).
CptTake(b) ==
    /\ cptPc[b] = "take"
    /\ ~stopped[b]
    /\ cptQ[b] # <<>>
    /\ cptCur' = [cptCur EXCEPT ![b] = Head(cptQ[b])]
    /\ cptQ' = [cptQ EXCEPT ![b] = Tail(@)]
    /\ cptPc' = [cptPc EXCEPT ![b] = "assert"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptSnap, rec, nnVars,
                   targetFired>>

\* BPSA:1430-1433: take() returns a batch without DNA_RECOVERBLOCK (block
\* report or cache report replies, other heartbeat commands, BPSA:755, 776,
\* 780). The model does not track those batches; their only effect is
\* another L1428 check.
CptOtherBatch(b) ==
    /\ cptPc[b] = "take"
    /\ ~stopped[b]
    /\ cptPc' = [cptPc EXCEPT ![b] = "loop"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptQ, cptCur, cptSnap,
                   rec, nnVars, targetFired>>

\* BPSA:1430, 1434-1444: interrupted in take() (BPSA.stop, L630-632): break,
\* clear the queue; work()'s finally clears shouldServiceRun (L1418-1421).
CptInterrupted(b) ==
    /\ cptPc[b] = "take"
    /\ stopped[b]
    /\ cptPc' = [cptPc EXCEPT ![b] = "dead"]
    /\ cptQ' = [cptQ EXCEPT ![b] = <<>>]
    /\ actRun' = [actRun EXCEPT ![b] = FALSE]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actPc, stopped, cptCur, cptSnap,
                   rec, nnVars, targetFired>>

\* processCommand (BPSA:1453-1458) -> BPOfferService.processCommandFromActor
\* (BPOS:671-705) for the DNA_RECOVERBLOCK command: first the assert, outside
\* any lock (BPOS:673).
CptAssert(b) ==
    /\ cptPc[b] = "assert"
    /\ IF ~bpServed[b] /\ AssertionsEnabled
       THEN \* assert bpServices.contains(actor) fails: the AssertionError
            \* leaves processCommand (BPSA:1456-1472) and processQueue,
            \* work() catches it (L1415-1417) and its finally clears
            \* shouldServiceRun (L1418-1421); the queue is not cleared but
            \* nobody takes from it again
            /\ cptPc' = [cptPc EXCEPT ![b] = "dead"]
            /\ actRun' = [actRun EXCEPT ![b] = FALSE]
       ELSE \* passes (or -da); not null, not DNA_REGISTER (BPOS:674-689)
            /\ cptPc' = [cptPc EXCEPT ![b] = "read"]
            /\ UNCHANGED actRun
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actPc, stopped, cptQ, cptCur,
                   cptSnap, rec, nnVars, targetFired>>

\* BPOS:690-698: isActiveActor = (actor == bpServiceToActive) under the read
\* lock, which waits while the write lock is held; then the lock is
\* released.
CptRead(b) ==
    /\ cptPc[b] = "read"
    /\ ~WriteLocked(b)
    /\ cptSnap' = [cptSnap EXCEPT ![b] = bpActive[b]]
    /\ cptPc' = [cptPc EXCEPT ![b] = "dispatch"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptQ, cptCur, rec,
                   nnVars, targetFired>>

\* BPOS:700-704 with the snapshot, outside the lock.
CptDispatch(b) ==
    LET c == cptCur[b] IN
    /\ cptPc[b] = "dispatch"
    /\ IF cptSnap[b]
       THEN \* processCommandFromActive, DNA_RECOVERBLOCK (BPOS:783-787) ->
            \* BlockRecoveryWorker.recoverBlocks (BRW:615-641): a new
            \* Daemon in datanode.threadGroup is started (L617, L639)
            rec' = [rec EXCEPT ![c.rid] =
                      [st |-> "start", dn |-> DnOf(b), slot |-> SlotOf(b),
                       att |-> c.att, nlocs |-> c.nlocs, idx |-> 1, err |-> 0,
                       pb |-> NoSlot]]
       ELSE \* processCommandFromStandby ignores it (BPOS:837-848)
            UNCHANGED rec
    \* processCommand returns true (BPSA:1458, 1483); next item (L1432-1433)
    /\ cptCur' = [cptCur EXCEPT ![b] = NoCmd]
    /\ cptPc' = [cptPc EXCEPT ![b] = "loop"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptQ, cptSnap, nnVars,
                   targetFired>>

----------------------------------------------------------------------------
\* Recovery daemon: RecoveryTaskContiguous.recover (BRW:118-184). The
\* striped task (BRW:383-444) makes the same lookup (L396) with the same
\* pool id (L376); it is not modeled separately (modeling-brief.md 3.2).
\* The loop never checks shouldRun(), interruption, or BPOS liveness.

\* BRW:619-628: logRecoverBlock, new RecoveryTaskContiguous (L110-116: bpid,
\* locs, recoveryId), recover() up to DataNodeFaultInjector.delay() (L122).
\* A command always has a location (NLocs >= 1), so the loop L129 runs.
RecStart(i) ==
    /\ rec[i].st = "start"
    /\ rec' = [rec EXCEPT ![i].st = "check"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, nnVars,
                   targetFired>>

\* THE TARGET. BRW:131 getDatanodeID(bpid) (BRW:562-568):
\*   L563 bpos = datanode.getBPOfferService(bpid) -> DNJ:2239-2241 ->
\*        BlockPoolManager.get (BPM:85-87, monitor) -> bpByBlockPoolId.get(P)
\*   L564 if (bpos == null)
\*   L565   throw new IOException("No block pool offer service for bpid=..")
\*   L567 return new DatanodeID(bpos.bpRegistration)
TargetCheck(i) ==
    LET d == rec[i].dn
        s == bpmByPool[d]
    IN
    /\ rec[i].st = "check"
    /\ IF s = NoSlot
       THEN \* L564-565: the failing branch. The IOException is caught in the
            \* location loop (L162-166): ++errorCount, next location.
            /\ targetFired' = TRUE
            /\ rec' = [rec EXCEPT ![i] = NextLoc(@, TRUE)]
       ELSE IF ~bpReg[<<d, s>>]
       THEN \* L567: new DatanodeID(null) dereferences null (DID:67-68): a
            \* NullPointerException that no handler catches (L157-166 and
            \* L630 catch IOException only); the daemon thread dies. Not the
            \* target.
            /\ rec' = [rec EXCEPT ![i].st = "npe"]
            /\ UNCHANGED targetFired
       ELSE \* L567 returns this DataNode's registration; on to L132-135
            /\ rec' = [rec EXCEPT ![i].st = "rpc"]
            /\ UNCHANGED targetFired
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, nnVars>>

\* BRW:132-166: initReplicaRecovery at the location (local call or
\* InterDatanodeProtocol proxy with dnConf.socketTimeout, L132-135, 583-591).
\*   "ok"  : a reply (L136-156), next location
\*   "ioe" : any IOException - peer down or slow, this DataNode's shutdown
\*           interrupt or ipcServer.stop, a local replica error -
\*           ++errorCount, next location (L162-166)
\*   "rip" : RecoveryInProgressException: the replica is already under
\*           recovery with a recovery id >= this one (FSD:3112-3120) -> return
\*           (L157-161); the command has one block (L622-633). Possible only
\*           while another daemon of an equal or newer attempt exists.
RecRpc(i) ==
    /\ rec[i].st = "rpc"
    /\ \/ rec' = [rec EXCEPT ![i] = NextLoc(@, FALSE)]
       \/ rec' = [rec EXCEPT ![i] = NextLoc(@, TRUE)]
       \/ /\ \E j \in Rec \ {i} : rec[j].st # "none" /\ rec[j].att >= rec[i].att
          /\ rec' = [rec EXCEPT ![i].st = "done"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, nnVars,
                   targetFired>>

\* After the loop: BRW:169-183, then syncBlock (L187-189) ->
\* getActiveNamenodeForBP (BRW:600-613), whose two reads take different
\* locks. Every failure here is an IOException caught at L630-632.
\*   - errorCount == locs.length: "All datanodes failed" (L169-172)
\*   - L602-605: getBPOfferService(bpid) == null (BlockPoolManager monitor):
\*     the same message as the target but at L604, NOT the target line
RecPost(i) ==
    LET s == bpmByPool[rec[i].dn] IN
    /\ rec[i].st = "post"
    /\ rec' = IF rec[i].err = rec[i].nlocs
              THEN [rec EXCEPT ![i].st = "done"]
              ELSE [rec EXCEPT ![i].st = IF s = NoSlot THEN "done" ELSE "active",
                               ![i].pb = s]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, nnVars,
                   targetFired>>

\* BRW:607-611: bpos.getActiveNN() (BPOS:532-543, read lock) on the BPOS the
\* lookup returned; null -> "has not recognized an active NN". Otherwise the
\* replica sync (L191-316, abstracted) and the commit.
RecActive(i) ==
    LET pb == <<rec[i].dn, rec[i].pb>> IN
    /\ rec[i].st = "active"
    /\ ~WriteLocked(pb)
    /\ rec' = [rec EXCEPT ![i].st = IF bpActive[pb] THEN "commit" ELSE "done"]
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, nnVars,
                   targetFired>>

\* nn.commitBlockSynchronization (BRW:206-207 or 317-319) ->
\* FSNamesystem.commitBlockSynchronization (FSN:4032-4107...). Either the
\* call never reaches the NameNode (an RPC failure; also the workload's spy,
\* which drops the first call, TestBlockRecovery2.java:314-319), or the
\* NameNode handles it: a closed file returns silently (FSN:4092-4099), a
\* stale recovery id is rejected (FSN:4106-4107), else the block is
\* committed and the file closed. The daemon then ends (BRW:634-636).
RecCommit(i) ==
    /\ rec[i].st = "commit"
    /\ rec' = [rec EXCEPT ![i].st = "done"]
    /\ \/ UNCHANGED nnRec
       \/ nnRec' = IF ~nnRec.done /\ rec[i].att = nnRec.att
                   THEN [nnRec EXCEPT !.done = TRUE]
                   ELSE nnRec
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, nnChosen,
                   nnRecQ, nnBanned, nnDead, nnReg, nnDeliv, targetFired>>

----------------------------------------------------------------------------
\* NameNode lease recovery (abstract)

\* The lease monitor finds the file's lease expired (the workload sets the
\* lease period to 100 ms, TestBlockRecovery.java:1027) ->
\* FSNamesystem.internalReleaseLease: addBlockRecoveryAttempt returns true
\* for a first attempt (FSN:3888; PRB:63-72), a new recovery id
\* (FSN:3889-3890), initializeBlockRecovery (FSN:3896 -> BUC:238-291).
\* The block was written to every DataNode (replication = |DN|), so every
\* DataNode had registered.
NNStartRecovery ==
    /\ nnRec.att = 0
    /\ \A x \in DN : nnReg[x]
    /\ nnRec' = [nnRec EXCEPT !.att = 1]
    /\ ChoosePrimary
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, rec, nnBanned,
                   nnDead, nnReg, nnDeliv, targetFired>>

\* The lease monitor again, once the previous attempt timed out
\* (PRB:73-76; the workload sets 15 s, TestBlockRecovery.java:1005): a newer
\* recovery id and a new primary. Timing is not modeled: the timeout may
\* expire at any point before the commit.
NNRetryRecovery ==
    /\ nnRec.att >= 1
    /\ nnRec.att < MaxAttempts
    /\ ~nnRec.done
    /\ nnRec' = [nnRec EXCEPT !.att = @ + 1]
    /\ ChoosePrimary
    /\ UNCHANGED <<dnVars, bpmVars, bposVars, actVars, cptVars, rec, nnBanned,
                   nnDead, nnReg, nnDeliv, targetFired>>

----------------------------------------------------------------------------

DnNext(d) ==
    \/ DnStop(d)
    \/ DnShutDownAll(d)
    \/ RefreshNodesDisallow(d)
    \/ RefreshStartNew(d)
    \/ RefreshStopOld(d)
    \/ RefreshJoinOld(d)

ActorNext(b) ==
    \/ ActorVersionRequest(b)
    \/ ActorVerifyNsInfo(b)
    \/ HsAddBlockPool(b)
    \/ HsInitStorage(b)
    \/ ActorRegister(b)
    \/ ActorLoop(b)
    \/ ActorHeartbeat(b)
    \/ ActorCleanUp(b)
    \/ ActorShutdownActor(b)
    \/ ActorExitRemove(b)
    \/ ActorExitRelease(b)

CptNext(b) ==
    \/ CptLoop(b)
    \/ CptTake(b)
    \/ CptOtherBatch(b)
    \/ CptInterrupted(b)
    \/ CptAssert(b)
    \/ CptRead(b)
    \/ CptDispatch(b)

RecNext(i) ==
    \/ RecStart(i)
    \/ TargetCheck(i)
    \/ RecRpc(i)
    \/ RecPost(i)
    \/ RecActive(i)
    \/ RecCommit(i)

Next ==
    \/ \E d \in DN : DnNext(d)
    \/ \E b \in Bpos : ActorNext(b)
    \/ \E b \in Bpos : CptNext(b)
    \/ \E i \in Rec : RecNext(i)
    \/ NNStartRecovery
    \/ NNRetryRecovery

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
\* Properties

\* The ad hoc oracle (adhoc-coordination Shared Rule 1).
TargetSafe == ~targetFired

TypeOK ==
    /\ dnPc \in [DN -> {"run", "stopping", "stopped"}]
    /\ refreshPc \in [DN -> {"idle", "step4", "join", "done"}]
    /\ bpmByPool \in [DN -> 0..MaxSlot]
    /\ bpmSvcs \in [DN -> SUBSET Slot]
    /\ poolLoaded \in [DN -> BOOLEAN]
    /\ bpNs \in [Bpos -> BOOLEAN]
    /\ bpReg \in [Bpos -> BOOLEAN]
    /\ bpActive \in [Bpos -> BOOLEAN]
    /\ bpServed \in [Bpos -> BOOLEAN]
    /\ actPc \in [Bpos -> ActPcs]
    /\ actRun \in [Bpos -> BOOLEAN]
    /\ stopped \in [Bpos -> BOOLEAN]
    /\ cptPc \in [Bpos -> CptPcs]
    /\ \A b \in Bpos : /\ Len(cptQ[b]) <= MaxAttempts
                       /\ \A k \in 1..Len(cptQ[b]) : cptQ[b][k] \in Cmd
    /\ cptCur \in [Bpos -> Cmd \cup {NoCmd}]
    /\ cptSnap \in [Bpos -> BOOLEAN]
    /\ rec \in [Rec -> RecType]
    /\ nnRec \in [att : 0..MaxAttempts, done : BOOLEAN]
    /\ nnChosen \subseteq DN
    /\ nnRecQ \in [DN -> BOOLEAN]
    /\ nnBanned \in [DN -> BOOLEAN]
    /\ nnDead \in [DN -> BOOLEAN]
    /\ nnReg \in [DN -> BOOLEAN]
    /\ nnDeliv \in 0..MaxAttempts
    /\ targetFired \in BOOLEAN

\* Structural (modeling-brief.md Section 5): every queued command and every
\* daemon carries pool P and a recovery id the NameNode issued (DM:1782-1784,
\* 1815-1816 build it from the NameNode's own pool id and the current
\* recovery id), and its BPOS holds pool P (the handshake checked it,
\* BPOS:250-257): commands only reach a BPOS that registered.
RecPoolFromSender ==
    /\ \A b \in Bpos :
         /\ \A k \in 1..Len(cptQ[b]) :
              /\ bpNs[b] /\ bpReg[b]
              /\ cptQ[b][k].att \in 1..nnRec.att
              /\ cptQ[b][k].rid \in 1..nnDeliv
         /\ cptCur[b] # NoCmd =>
              /\ bpNs[b] /\ bpReg[b]
              /\ cptCur[b].att \in 1..nnRec.att
    /\ \A i \in Rec : rec[i].st # "none" =>
         /\ rec[i].dn \in DN
         /\ bpNs[<<rec[i].dn, rec[i].slot>>]
         /\ bpReg[<<rec[i].dn, rec[i].slot>>]
         /\ rec[i].att \in 1..nnRec.att
         /\ i <= nnDeliv

=============================================================================
