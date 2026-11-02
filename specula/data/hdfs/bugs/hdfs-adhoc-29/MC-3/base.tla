-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-29: can a block-recovery task find its block pool           *)
(* unregistered at BlockRecoveryWorker.java:604?                          *)
(*                                                                         *)
(* Target (ad hoc check), BlockRecoveryWorker.getActiveNamenodeForBP:     *)
(*   BRW:602  BPOfferService bpos = datanode.getBPOfferService(bpid);      *)
(*   BRW:603  if (bpos == null) {                                          *)
(*   BRW:604    throw new IOException("No block pool offer service ...");  *)
(* phi_T: a recovery Daemon executes BRW:602 for pool p and the            *)
(*   synchronized read bpByBlockPoolId.get(p) (DN:2239-2241 -> BPM:85-87)  *)
(*   returns null. The only write producing null is BPM.remove (BPM:89-95, *)
(*   remove BY KEY), whose only caller is DN:2152, reached when the pool's *)
(*   last actor leaves (BPOS:476-491).                                     *)
(*                                                                         *)
(* Category A (distributed / message passing), with per-thread steps      *)
(* inside one DataNode: recovery Daemon vs BPServiceActor main thread vs   *)
(* CommandProcessingThread vs DataNode lifecycle vs refreshNamenodes.      *)
(*                                                                         *)
(* Source tree: /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-29/hadoop        *)
(*   @ 734dd8a67cd (pinned). Abbreviations (hadoop-hdfs src/main/java/     *)
(*   org/apache/hadoop/hdfs/server/...):                                   *)
(*   BRW  datanode/BlockRecoveryWorker.java   BPM datanode/BlockPoolManager *)
(*   BPOS datanode/BPOfferService.java        BPSA datanode/BPServiceActor  *)
(*   DN   datanode/DataNode.java              DS  datanode/DataStorage      *)
(*   BPSS datanode/BlockPoolSliceStorage.java                              *)
(*   FDI  datanode/fsdataset/impl/FsDatasetImpl.java                       *)
(*   FVI  datanode/fsdataset/impl/FsVolumeImpl.java                        *)
(*   DM   blockmanagement/DatanodeManager.java                             *)
(*   DD   blockmanagement/DatanodeDescriptor.java                          *)
(*   BUCF blockmanagement/BlockUnderConstructionFeature.java               *)
(*   PRB  blockmanagement/PendingRecoveryBlocks.java                       *)
(*   FSN  namenode/FSNamesystem.java   NNRS namenode/NameNodeRpcServer.java *)
(*                                                                         *)
(* Scope (modeling brief §3): contiguous recovery task only (the striped   *)
(* task has the same guard/operand/unmap transitions); replica states,     *)
(* lengths and GS rules are abstracted to the outcome class of            *)
(* initReplicaRecovery; one NameNode per nameservice (no HA).              *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    DN,           \* DataNodes
    NS,           \* nameservice ids a DataNode can be configured with
    NN,           \* NameNodes; one per nameservice (no HA, brief §3.2)
    Pool,         \* block pool ids
    NnOf,         \* [NS -> NN]   NN address configured for a nameservice
    PoolOf,       \* [NN -> Pool] block pool id the NN returns from versionRequest (BPSA:262)
    InitCfg,      \* nameservices configured when the DataNode starts (DN:1958-1959)
    RefreshCfg,   \* nameservices of the config given to refreshNamenodes (Scenario 3)
    RecPool,      \* block pool of the block under lease recovery
    MaxAttempts,  \* recovery attempts the NN may start for the block (bounds tasks too)
    Nil           \* null

ASSUME NnOf \in [NS -> NN]
ASSUME PoolOf \in [NN -> Pool]
ASSUME InitCfg \subseteq NS /\ InitCfg # {}
\* BPM:165-168: refreshNamenodes with no NameNode address throws before any change.
ASSUME RefreshCfg \subseteq NS /\ RefreshCfg # {}
ASSUME RecPool \in Pool /\ \E n \in NN : PoolOf[n] = RecPool
ASSUME MaxAttempts \in Nat \ {0}
ASSUME Nil \notin NS \cup NN \cup Pool \cup DN
\* Nameservices configured together name different namespaces (one BPOS per pool at start).
ASSUME \A a, b \in InitCfg : a # b => PoolOf[NnOf[a]] # PoolOf[NnOf[b]]

\* The NameNode that serves the recovering block. Only its side is modeled as an environment;
\* other NameNodes (Scenario 3 federation topology) accept everything and send no modeled command.
RecNN == CHOOSE n \in NN : PoolOf[n] = RecPool
PoolOfNs(ns) == PoolOf[NnOf[ns]]

\* Default topology helpers for configs with one NameNode and one pool.
SingleNnOf   == [ns \in NS |-> CHOOSE n \in NN : TRUE]
SinglePoolOf == [n \in NN |-> CHOOSE p \in Pool : TRUE]

Task == 1..MaxAttempts           \* task slots: one recovery Daemon per delivered command
NLocs == Cardinality(DN)         \* every DataNode holds a replica (workload: replication 2, 2 DNs)

Perms(S) == {f \in [1..Cardinality(S) -> S] :
                \A i, j \in 1..Cardinality(S) : i # j => f[i] # f[j]}

ActorPcs  == {"none", "conn", "initSt", "reg", "run", "fail", "exit", "dead"}
TaskSts   == {"none", "getId", "initRR", "loopEnd", "target", "activeNN", "commit",
              "done", "failed", "npe", "fired"}
LiveTaskSts == {"getId", "initRR", "loopEnd", "target", "activeNN", "commit"}
RROutcome == {"replica", "none", "ioErr", "rip"}
CommitOutcome == {"ok", "stale", "lost", "error"}
StopCause == {"volFail", "shutdown"}
Cmd == [type : {"register", "recover"}, rid : 0..MaxAttempts]

VARIABLES
    \* --- DataNode lifecycle (per DN) ---
    dnRun,        \* DataNode.shouldRun (DN:395)
    dnShut,       \* progress of DataNode.shutdown(): "no" | "begun" (DN:2545) | "intr" (DN:2612, 2655)
    nsCfg,        \* nameservices of the DN's current configuration (refresh target)
    shutStop,     \* nameservices whose BPOS shutDownAll will stop() (bposArray, DN:2540-2542)
    refreshStop,  \* nameservices whose BPOS refresh Step 4 will stop() (BPM:239-252)
    \* --- BlockPoolManager registry (per DN) ---
    offerSvc,     \* BPM.offerServices / bpByNameserviceId keys (BPM:49-54)
    bpMap,        \* BPM.bpByBlockPoolId (BPM:51-52): [Pool -> NS \cup {Nil}], the guard operand
    \* --- BPOfferService (per DN and nameservice) ---
    bposPool,     \* bpNSInfo / bpId (BPOS:246-265); Nil = no block pool id
    bposActive,   \* bpServiceToActive /= null (BPOS:86); the BPOS's only actor
    bposReg,      \* bpRegistration /= null (BPOS:432)
    \* --- BPServiceActor and its CommandProcessingThread (one actor per BPOS) ---
    actorPc,      \* "none" not created | "conn" handshake | "initSt" storage init | "reg"
                  \* registration | "run" offerService | "fail" init failed, no retry |
                  \* "exit" run()'s finally reached | "dead" cleaned up
    actorRun,     \* shouldServiceRun (BPSA:116)
    cmdQ,         \* CommandProcessingThread queue (BPSA:1402)
    cmdAlive,     \* CommandProcessingThread running (BPSA:1412-1422)
    \* --- FsDataset / DataStorage (per DN) ---
    dsPool,       \* FsDatasetImpl holds the pool's replica map (DN:2202 add, FDI:3326-3334 remove)
    stLoaded,     \* DataStorage.bpStorageMap holds the pool's storage (DN:2199 load, DS:1421-1423)
    rurMax,       \* highest recovery attempt that ran initReplicaRecovery on the DN's replica
    \* --- Recovery tasks (BlockRecoveryWorker Daemons, contiguous) ---
    task,         \* [Task -> task record]
    nTasks,       \* task slots used
    \* --- NameNode environment for the recovering block (RecNN) ---
    nnAttempt,    \* recovery attempts started; also the NN's current recovery id (FSN:3889-3896)
    nnTried,      \* replicas with chosenAsPrimary set (BUCF:253-287)
    nnPending,    \* block queued in the DN descriptor's recoverBlocks (DD:717-723)
    nnDone,       \* recovery committed (FSN:4111+): no further attempt
    nnKnows,      \* the NN has the DN registered (DM:1876-1878)
    nnReject,     \* the NN rejects the DN's heartbeats/registrations (operator fault)
    dnsBad,       \* the NN cannot reverse-resolve the DN's address (environment fault)
    blockLocs,    \* expected locations of the block, in order (constant after Init)
    \* --- Target ---
    targetFired   \* BRW:604 executed

dnVars    == <<dnRun, dnShut, nsCfg, shutStop, refreshStop>>
regVars   == <<offerSvc, bpMap>>
bposVars  == <<bposPool, bposActive, bposReg>>
actorVars == <<actorPc, actorRun, cmdQ, cmdAlive>>
dsVars    == <<dsPool, stLoaded, rurMax>>
taskVars  == <<task, nTasks>>
nnVars    == <<nnAttempt, nnTried, nnPending, nnDone, nnKnows, nnReject, dnsBad, blockLocs>>
vars == <<dnVars, regVars, bposVars, actorVars, dsVars, taskVars, nnVars, targetFired>>

NoTask == [st |-> "none", dn |-> Nil, pool |-> Nil, rid |-> 0, via |-> Nil,
           idx |-> 0, errs |-> 0, cands |-> 0, sync |-> 0, okReads |-> 0,
           readNs |-> Nil, intr |-> FALSE, mapped |-> FALSE]

TaskRec == [st : TaskSts, dn : DN \cup {Nil}, pool : Pool \cup {Nil}, rid : 0..MaxAttempts,
            via : NS \cup {Nil}, idx : 0..NLocs, errs : 0..NLocs, cands : 0..NLocs,
            sync : 0..NLocs, okReads : 0..NLocs, readNs : NS \cup {Nil},
            intr : BOOLEAN, mapped : BOOLEAN]

-----------------------------------------------------------------------------
(* Helpers *)

\* BPSA:953-955 shouldRun() == shouldServiceRun && dn.shouldRun()
ShouldRun(d, ns) == actorRun[d][ns] /\ dnRun[d]

\* NN-side rejection of a (re-)registration of d: DM:1195-1201 unresolved address
\* (DisallowedDatanodeException); DM:1213-1214 not in the include list.
NnRejectsReg(d, ns) == NnOf[ns] = RecNN /\ (dnsBad[d] \/ nnReject[d])

HasRegisterQueued(d, ns) == \E i \in 1..Len(cmdQ[d][ns]) : cmdQ[d][ns][i].type = "register"

\* BRW:129 for (DatanodeID id : locs): go to the next location or leave the loop.
NextLoc(r) == IF r.idx < NLocs THEN [r EXCEPT !.idx = @ + 1, !.st = "getId"]
              ELSE [r EXCEPT !.st = "loopEnd"]

\* Outcome class of FsDatasetImpl.initReplicaRecovery(rBlock) on DataNode x (FDI:3022-3047,
\* 3071-3139) for task r. Replica state/length/GS details are abstracted (brief §3.2).
ReplicaOutcome(r, x) ==
    IF ~dsPool[x][r.pool]
    THEN {"none"}                  \* FDI:3033-3036 map.get == null: replica map cleaned (FDI:3331)
    ELSE IF rurMax[x] >= r.rid
    THEN {"rip", "ioErr"}          \* FDI:3114-3120 RUR with recoveryId >= ours -> RecoveryInProgress;
                                   \* FDI:3106-3110 finalized with GS >= recoveryId -> IOException
    ELSE {"replica"}               \* FDI:3126-3138 replica -> RUR(recoveryId); BRW:136-143 syncList

\* BRW:132-135: local call when the location is this DataNode, else InterDatanodeProtocol RPC.
InitRROutcomes(t) ==
    LET r == task[t]
        x == blockLocs[r.idx]
    IN IF x = r.dn
       THEN \* local: DN:3526-3531; an interrupted Daemon can fail in stopWriter's join (FDI:3043-3044)
            ReplicaOutcome(r, x) \cup (IF r.intr THEN {"ioErr"} ELSE {})
       ELSE IF r.intr \/ dnShut[x] = "intr"
            THEN {"ioErr"}         \* interrupted Daemon (DN:2612) / peer's ipcServer stopped (DN:2655)
            ELSE ReplicaOutcome(r, x)

\* BRW:191-319 rest of syncBlock: updateReplicaUnderRecovery (BRW:287-303) and
\* commitBlockSynchronization through the proxy returned at BRW:607 (BRW:206-207, 317-319).
CommitOutcomes(t) ==
    LET r == task[t] IN
    IF r.intr \/ actorPc[r.dn][r.readNs] = "dead"
    THEN {"error"}                 \* interrupted Daemon / proxy closed by cleanUp (BPSA:651)
    ELSE {"lost"} \cup             \* returns without reaching the NN (the workload's spy)
         (IF nnDone \/ r.rid = nnAttempt
          THEN {"ok"}              \* FSN:4106 id matches (or FSN:4092-4100 already complete)
          ELSE {"stale"})          \* FSN:4106-4110 "recovery id ... does not match"

-----------------------------------------------------------------------------
(* Initial state: every DataNode has just run startDataNode (DN:1958-1959 refreshNamenodes:  *)
(* BPM:209-236 creates and starts one BPOS per configured nameservice; the actor constructor *)
(* starts its CommandProcessingThread, BPSA:159-160).                                        *)

Init ==
    /\ dnRun       = [d \in DN |-> TRUE]
    /\ dnShut      = [d \in DN |-> "no"]
    /\ nsCfg       = [d \in DN |-> InitCfg]
    /\ shutStop    = [d \in DN |-> {}]
    /\ refreshStop = [d \in DN |-> {}]
    /\ offerSvc    = [d \in DN |-> InitCfg]
    /\ bpMap       = [d \in DN |-> [p \in Pool |-> Nil]]
    /\ bposPool    = [d \in DN |-> [ns \in NS |-> Nil]]
    /\ bposActive  = [d \in DN |-> [ns \in NS |-> FALSE]]
    /\ bposReg     = [d \in DN |-> [ns \in NS |-> FALSE]]
    /\ actorPc     = [d \in DN |-> [ns \in NS |-> IF ns \in InitCfg THEN "conn" ELSE "none"]]
    /\ actorRun    = [d \in DN |-> [ns \in NS |-> ns \in InitCfg]]
    /\ cmdQ        = [d \in DN |-> [ns \in NS |-> <<>>]]
    /\ cmdAlive    = [d \in DN |-> [ns \in NS |-> ns \in InitCfg]]
    /\ dsPool      = [d \in DN |-> [p \in Pool |-> FALSE]]
    /\ stLoaded    = [d \in DN |-> [p \in Pool |-> FALSE]]
    /\ rurMax      = [d \in DN |-> 0]
    /\ task        = [t \in Task |-> NoTask]
    /\ nTasks      = 0
    /\ nnAttempt   = 0
    /\ nnTried     = {}
    /\ nnPending   = [d \in DN |-> FALSE]
    /\ nnDone      = FALSE
    /\ nnKnows     = [d \in DN |-> FALSE]
    /\ nnReject    = [d \in DN |-> FALSE]
    /\ dnsBad      = [d \in DN |-> FALSE]
    /\ blockLocs   \in Perms(DN)           \* DM:1765 uc.getExpectedStorageLocations() order
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(* BPServiceActor: handshake, storage init, registration (BPSA:899-929)       *)

\* BPSA:302-317 connectToNNAndHandshake up to BPOS.verifyAndSetNamespaceInfo (BPOS:382-401):
\* retrieveNamespaceInfo, then setNamespaceInfo; on the BPOS's first handshake initBlockPool
\* registers the pool with the BlockPoolManager (DN:2185-2195 -> BPM:65-72, the put).
ActorConnect(d, ns) ==
    /\ actorPc[d][ns] = "conn"
    /\ ShouldRun(d, ns)                                        \* BPSA:260 loop while shouldRun()
    /\ LET p     == PoolOfNs(ns)                               \* BPSA:262 versionRequest() pool id
           first == bposPool[d][ns] = Nil                      \* BPOS:394 setNamespaceInfo returned null
       IN /\ bposActive' = [bposActive EXCEPT ![d][ns] = TRUE] \* BPOS:386-390 non-HA NN is ACTIVE
          /\ bposPool'   = [bposPool EXCEPT ![d][ns] = p]      \* BPOS:258-260
          /\ IF first
             THEN \* BPOS:401 -> DN:2195 -> BPM:71 bpByBlockPoolId.put (overwrites any mapping)
                  /\ bpMap'   = [bpMap EXCEPT ![d][p] = ns]
                  /\ actorPc' = [actorPc EXCEPT ![d][ns] = "initSt"]
             ELSE \* re-handshake after a rejected registration (BPSA:913-917): no initBlockPool
                  /\ UNCHANGED bpMap
                  /\ actorPc' = [actorPc EXCEPT ![d][ns] = "reg"]
    /\ UNCHANGED <<dnVars, offerSvc, bposReg, actorRun, cmdQ, cmdAlive, dsVars, taskVars,
                   nnVars, targetFired>>

\* DN:2197-2207 rest of initBlockPool: initStorage (DN:2251-2280 -> DS:564-567) and
\* data.addBlockPool (DN:2202). Separate step: the put (DN:2195) already happened.
ActorInitStorage(d, ns) ==
    /\ actorPc[d][ns] = "initSt"
    /\ LET p == bposPool[d][ns] IN
       IF stLoaded[d][p]
       THEN \* BPSS:221-224 "attempt to load an used block storage" for every location, caught
            \* per location (DS:473-476) -> DS:566-567 IOException out of initBlockPool;
            \* BPOS:403-409 setNamespaceInfo(null) (the put is NOT undone); BPSA:910-912
            \* INIT_FAILED; BPSA:913/949-951 -> BPOS:860-867: no bpid, and the only actor is not
            \* alive (BPSA:171-177) -> BPSA:918-921 FAILED, return (ActorLoopExit: the finally)
            /\ bposPool' = [bposPool EXCEPT ![d][ns] = Nil]
            /\ actorPc'  = [actorPc EXCEPT ![d][ns] = "fail"]
            /\ UNCHANGED <<dsPool, stLoaded>>
       ELSE /\ stLoaded' = [stLoaded EXCEPT ![d][p] = TRUE]    \* DN:2199, 2263 storage loaded
            /\ dsPool'   = [dsPool EXCEPT ![d][p] = TRUE]      \* DN:2202 data.addBlockPool
            /\ actorPc'  = [actorPc EXCEPT ![d][ns] = "reg"]
            /\ UNCHANGED bposPool
    /\ UNCHANGED <<dnVars, regVars, bposActive, bposReg, actorRun, cmdQ, cmdAlive, rurMax,
                   taskVars, nnVars, targetFired>>

\* BPSA:323-324 register(nsInfo) -> BPSA:838-879; NN side NNRS:1620-1622 -> DM:1188-1216.
ActorRegister(d, ns) ==
    /\ actorPc[d][ns] = "reg"
    /\ ShouldRun(d, ns)                                        \* BPSA:845 while (shouldRun())
    /\ IF NnRejectsReg(d, ns)
       THEN \* BPSA:856-858 RemoteException rethrown -> BPSA:910-917 INIT_FAILED,
            \* shouldRetryInit() (bpid known, BPOS:861-865) -> sleep, connectToNNAndHandshake again
            /\ actorPc' = [actorPc EXCEPT ![d][ns] = "conn"]
            /\ UNCHANGED <<bposReg, nnKnows>>
       ELSE \* BPSA:848-850 registered; BPSA:871 -> BPOS:422-445 bpRegistration; BPSA:926 RUNNING
            /\ bposReg' = [bposReg EXCEPT ![d][ns] = TRUE]
            /\ nnKnows' = IF NnOf[ns] = RecNN THEN [nnKnows EXCEPT ![d] = TRUE] ELSE nnKnows
            /\ actorPc' = [actorPc EXCEPT ![d][ns] = "run"]
    /\ UNCHANGED <<dnVars, regVars, bposPool, bposActive, actorRun, cmdQ, cmdAlive, dsVars,
                   taskVars, nnAttempt, nnTried, nnPending, nnDone, nnReject, dnsBad, blockLocs,
                   targetFired>>

-----------------------------------------------------------------------------
(* BPServiceActor.offerService: one heartbeat whose reply carries a modeled outcome.          *)
(* A quiet heartbeat (nothing pending, nothing rejected) changes no modeled state: omitted.  *)

\* BPSA:686-790 one loop iteration with sendHeartBeat (BPSA:711 -> BPSA:545-549); NN side
\* NNRS:1626-1640: verifyRequest (NNRS:1777-1786), then DM:1856-1893 handleHeartbeat.
ActorHeartbeat(d, ns) ==
    /\ actorPc[d][ns] = "run"
    /\ ShouldRun(d, ns)                                        \* BPSA:686 while (shouldRun())
    /\ NnOf[ns] = RecNN                                        \* only RecNN sends modeled commands
    \* BPSA:548-549 storage reports: for a pool released from the dataset, FDI:163-185 ->
    \* FVI:420-421 -> FVI:562-567 throws IOException before the NN is contacted (BPSA:805-807)
    /\ dsPool[d][bposPool[d][ns]]
    /\ \/ \* NNRS:1781-1785 UnregisteredNodeException (registration ID changed) or DM:1871-1873
          \* DisallowedDatanodeException -> BPSA:791-798 shouldServiceRun = false; return
          /\ nnReject[d]
          /\ actorRun' = [actorRun EXCEPT ![d][ns] = FALSE]
          /\ UNCHANGED <<cmdQ, nnPending>>
       \/ \* DM:1876-1878 node not registered -> RegisterCommand.REGISTER; BPSA:745-756 enqueue.
          \* Abstraction: a REGISTER already queued makes a duplicate a no-op.
          /\ ~nnReject[d]
          /\ ~nnKnows[d]
          /\ ~HasRegisterQueued(d, ns)
          /\ cmdQ' = [cmdQ EXCEPT ![d][ns] = Append(@, [type |-> "register", rid |-> 0])]
          /\ UNCHANGED <<actorRun, nnPending>>
       \/ \* DM:1888-1893 recovery command first; DD:780-785 poll drains the queue
          /\ ~nnReject[d]
          /\ nnKnows[d]
          /\ nnPending[d]
          /\ nnPending' = [nnPending EXCEPT ![d] = FALSE]
          /\ IF nnDone
             THEN \* DM:1760-1763 block no longer under construction: IOException at the NN;
                  \* the DN logs the RemoteException and retries (BPSA:800-804)
                  UNCHANGED cmdQ
             ELSE \* DM:1815-1816 the command carries the NN's current recovery id
                  cmdQ' = [cmdQ EXCEPT ![d][ns] = Append(@, [type |-> "recover", rid |-> nnAttempt])]
          /\ UNCHANGED actorRun
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorPc, cmdAlive, dsVars, taskVars, nnAttempt,
                   nnTried, nnDone, nnKnows, nnReject, dnsBad, blockLocs, targetFired>>

-----------------------------------------------------------------------------
(* CommandProcessingThread (BPSA:1400-1525): processQueue takes one command and runs           *)
(* processCommand (BPSA:1453-1484) -> BPOS.processCommandFromActor (BPOS:671-705).             *)

\* BPSA:1428 loop check after the command; leaving the loop clears the queue (BPSA:1443-1444)
\* and work()'s finally sets shouldServiceRun = false (BPSA:1418-1421). `run` is the value of
\* shouldServiceRun once the command has run.
AfterCmd(d, ns, run) ==
    IF run /\ dnRun[d]
    THEN /\ cmdQ'     = [cmdQ EXCEPT ![d][ns] = Tail(@)]
         /\ actorRun' = [actorRun EXCEPT ![d][ns] = run]
         /\ UNCHANGED cmdAlive
    ELSE /\ cmdQ'     = [cmdQ EXCEPT ![d][ns] = <<>>]
         /\ actorRun' = [actorRun EXCEPT ![d][ns] = FALSE]
         /\ cmdAlive' = [cmdAlive EXCEPT ![d][ns] = FALSE]

\* BPOS:681-689 DNA_REGISTER -> BPSA:967-984 reRegister.
CmdRegister(d, ns) ==
    /\ cmdAlive[d][ns]
    /\ cmdQ[d][ns] # <<>>
    /\ Head(cmdQ[d][ns]).type = "register"
    /\ IF ~ShouldRun(d, ns)
       THEN \* BPSA:968 if (shouldRun()) is false: nothing is done
            /\ AfterCmd(d, ns, actorRun[d][ns])
            /\ UNCHANGED nnKnows
       ELSE IF NnRejectsReg(d, ns)
       THEN \* BPSA:980 register -> BPSA:856-858 RemoteException (DisallowedDatanodeException)
            \* -> BPSA:1461-1468 shouldServiceRun = false; return false
            /\ AfterCmd(d, ns, FALSE)
            /\ UNCHANGED nnKnows
       ELSE \* BPSA:848-850, 871: re-registered at the NN (DM:1188-1216)
            /\ nnKnows' = IF NnOf[ns] = RecNN THEN [nnKnows EXCEPT ![d] = TRUE] ELSE nnKnows
            /\ AfterCmd(d, ns, actorRun[d][ns])
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorPc, dsVars, taskVars, nnAttempt, nnTried,
                   nnPending, nnDone, nnReject, dnsBad, blockLocs, targetFired>>

\* BPOS:690-704 isActiveActor read under the BPOS read lock, then dispatch:
\* BPOS:783-787 DNA_RECOVERBLOCK -> BRW:615-641 recoverBlocks starts a Daemon running
\* RecoveryTaskContiguous.recover() (BRW:110-129); a standby actor ignores it (BPOS:837-848).
CmdRecover(d, ns) ==
    /\ cmdAlive[d][ns]
    /\ cmdQ[d][ns] # <<>>
    /\ Head(cmdQ[d][ns]).type = "recover"
    /\ LET c == Head(cmdQ[d][ns])
           p == PoolOfNs(ns)          \* DM:1784 ExtendedBlock(blockPoolId, b): the NN's pool (BRW:113)
       IN IF bposActive[d][ns] /\ nTasks < MaxAttempts
          THEN /\ nTasks' = nTasks + 1
               /\ task'   = [task EXCEPT ![nTasks + 1] =
                               [st |-> "getId", dn |-> d, pool |-> p, rid |-> c.rid, via |-> ns,
                                idx |-> 1, errs |-> 0, cands |-> 0, sync |-> 0, okReads |-> 0,
                                readNs |-> Nil, intr |-> FALSE, mapped |-> bpMap[d][p] # Nil]]
          ELSE UNCHANGED taskVars
    /\ AfterCmd(d, ns, actorRun[d][ns])
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorPc, dsVars, nnVars, targetFired>>

\* Scenario 2 fault: an unchecked exception from a command handler (e.g. DNA_INVALIDATE racing
\* a volume removal, FsDatasetAsyncDiskService.java:181-193; DNA_REGISTER after a block-token
\* setting change, DN:2115-2126) escapes processCommand, which catches only RemoteException and
\* IOException (BPSA:1461-1472): BPSA:1415-1417 FAILED, BPSA:1418-1421 shouldServiceRun = false.
CmdThreadCrash(d, ns) ==
    /\ cmdAlive[d][ns]
    /\ actorPc[d][ns] = "run"                    \* commands come from a running actor's replies
    /\ cmdAlive' = [cmdAlive EXCEPT ![d][ns] = FALSE]
    /\ actorRun' = [actorRun EXCEPT ![d][ns] = FALSE]
    /\ cmdQ'     = [cmdQ EXCEPT ![d][ns] = <<>>]   \* nobody processes the rest of the queue
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorPc, dsVars, taskVars, nnVars, targetFired>>

-----------------------------------------------------------------------------
(* Actor exit: stop(), run() ending, cleanUp (the unmap).                                     *)

\* BPSA:622-633 stop(): called by BPOS.stop (BPOS:358-362) from BPM.shutDownAll (BPM:113-121,
\* DN:2662-2668, after DN:2612/2655) or from refresh Step 4 (BPM:246-249).
ActorStop(d, ns) ==
    /\ \/ ns \in shutStop[d] /\ dnShut[d] = "intr"
       \/ ns \in refreshStop[d]
    \* BPOS:359 iterates bpServices: an actor removed by its own cleanUp (BPOS:483) is not stopped
    /\ actorPc[d][ns] \notin {"none", "dead"}
    /\ shutStop'    = [shutStop EXCEPT ![d] = @ \ {ns}]
    /\ refreshStop' = [refreshStop EXCEPT ![d] = @ \ {ns}]
    /\ actorRun'    = [actorRun EXCEPT ![d][ns] = FALSE]   \* BPSA:623
    \* BPSA:630-632 interrupt the command thread, blocked in queue.take() (BPSA:1430):
    \* BPSA:1434-1440 break, BPSA:1443-1444 clear, BPSA:1418-1421 exit
    /\ cmdAlive'    = [cmdAlive EXCEPT ![d][ns] = FALSE]
    /\ cmdQ'        = [cmdQ EXCEPT ![d][ns] = <<>>]
    /\ UNCHANGED <<dnRun, dnShut, nsCfg, regVars, bposVars, actorPc, dsVars, taskVars, nnVars,
                   targetFired>>

\* BPSA:931 run() loop / BPSA:686 offerService loop end when shouldRun() is false (BPSA:939
\* EXITED). In the init phase the loops at BPSA:260/845 end and BPSA:278/866-868 throw;
\* shouldRetryInit() is false without shouldRun() (BPSA:949-951) -> BPSA:918-921 FAILED.
\* A failed storage init ("fail", see ActorInitStorage) returns the same way.
\* Every path then reaches run()'s finally (BPSA:943-946).
ActorLoopExit(d, ns) ==
    /\ \/ actorPc[d][ns] \in {"conn", "reg", "run"} /\ ~ShouldRun(d, ns)
       \/ actorPc[d][ns] = "fail"
    /\ actorPc' = [actorPc EXCEPT ![d][ns] = "exit"]
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorRun, cmdQ, cmdAlive, dsVars, taskVars,
                   nnVars, targetFired>>

\* BPSA:943-946 finally -> BPSA:648-654 cleanUp: shouldServiceRun = false (L650), close the NN
\* proxy (L651), then BPOS:476-491 shutdownActor under the BPOS write lock:
\* bpServiceToActive = null (L479-481), bpServices.remove (L483); with one NameNode per
\* nameservice the list is now empty (L485) -> DN:2151-2172 shutdownBlockPool.
\* One atomic step (BPOS write lock + BPM monitor); the dataset/storage release (DN:2164,
\* DN:2168) follows the unmap with no modeled observer that needs the gap.
ActorCleanUp(d, ns) ==
    /\ actorPc[d][ns] = "exit"
    /\ LET p == bposPool[d][ns] IN                             \* BPM:91, DN:2153 hasBlockPoolId()
       /\ actorPc'    = [actorPc EXCEPT ![d][ns] = "dead"]
       /\ actorRun'   = [actorRun EXCEPT ![d][ns] = FALSE]
       /\ bposActive' = [bposActive EXCEPT ![d][ns] = FALSE]
       /\ offerSvc'   = [offerSvc EXCEPT ![d] = @ \ {ns}]     \* BPM:90; BPM:97-106 identity removal
       /\ IF p # Nil
          THEN /\ bpMap'    = [bpMap EXCEPT ![d][p] = Nil]     \* DN:2152 -> BPM:94 remove BY KEY
               /\ dsPool'   = [dsPool EXCEPT ![d][p] = FALSE]  \* DN:2163-2164 -> FDI:3326-3334
               /\ stLoaded' = [stLoaded EXCEPT ![d][p] = FALSE] \* DN:2167-2168 -> DS:1421-1423
          ELSE UNCHANGED <<bpMap, dsPool, stLoaded>>
    /\ UNCHANGED <<dnVars, bposPool, bposReg, cmdQ, cmdAlive, rurMax, taskVars, nnVars,
                   targetFired>>

-----------------------------------------------------------------------------
(* DataNode lifecycle (Scenario 1) and federation refresh (Scenario 3).                       *)

\* Scenario 1 fault. "volFail": DN:4065-4090 handleVolumeFailures -> DN:2720-2744 handleDiskError:
\* FDI:676-684 hasEnoughResource() is false (failed volumes > failed.volumes.tolerated, default
\* 0) -> DN:2743 shouldRun = false; shutdown() is not called. "shutdown": DataNode.shutdown()
\* (shutdownDatanode RPC DN:3848-3876; MiniDFSCluster.java:2229-2233): DN:2540-2542 bposArray,
\* DN:2544-2546 shouldRun = false (non-upgrade shutdown).
DnStop(d, cause) ==
    /\ dnShut[d] = "no"
    /\ dnRun' = [dnRun EXCEPT ![d] = FALSE]
    /\ \/ /\ cause = "volFail"
          /\ dnRun[d]
          /\ UNCHANGED <<dnShut, shutStop>>
       \/ /\ cause = "shutdown"
          /\ dnShut'   = [dnShut EXCEPT ![d] = "begun"]
          /\ shutStop' = [shutStop EXCEPT ![d] = offerSvc[d]]
    /\ UNCHANGED <<nsCfg, refreshStop, regVars, bposVars, actorVars, dsVars, taskVars, nnVars,
                   targetFired>>

\* DataNode.shutdown() continued: DN:2604-2629 threadGroup.interrupt() without waiting
\* (recovery Daemons run in datanode.threadGroup, BRW:617): their InterDatanodeProtocol and NN
\* calls fail from now on; DN:2654-2656 ipcServer.stop(): peers' calls to d fail. Merged: no
\* modeled event lies between L2612 and L2655. shutDownAll (DN:2664) then stops the actors.
DnShutdownInterrupt(d) ==
    /\ dnShut[d] = "begun"
    /\ dnShut' = [dnShut EXCEPT ![d] = "intr"]
    /\ task'   = [t \in Task |-> IF task[t].dn = d /\ task[t].st \in LiveTaskSts
                                 THEN [task[t] EXCEPT !.intr = TRUE]
                                 ELSE task[t]]
    /\ UNCHANGED <<dnRun, nsCfg, shutStop, refreshStop, regVars, bposVars, actorVars, dsVars,
                   nTasks, nnVars, targetFired>>

\* Scenario 3 fault (operator). DN:3810-3815 refreshNamenodes() -> BPM:148-173 ->
\* doRefreshNamenodes Steps 1-3 under the BPM lock (BPM:185-237); Step 4 (BPM:239-252) is the
\* later ActorStop of each removed nameservice. Step 5 (refreshNNList) is a no-op here: one NN
\* per nameservice, addresses unchanged.
RefreshStart(d) ==
    /\ dnShut[d] = "no"                                        \* the RPC server is up
    /\ nsCfg[d] # RefreshCfg
    /\ LET toAdd    == RefreshCfg \ offerSvc[d]                \* BPM:189-195
           toRemove == offerSvc[d] \ RefreshCfg                \* BPM:199-200
       IN /\ \A ns \in toAdd : actorPc[d][ns] = "none"         \* bound: a BPOS is created once per ns
          /\ offerSvc'    = [offerSvc EXCEPT ![d] = @ \cup toAdd]           \* BPM:230-233
          \* BPM:236 startAll -> BPOS:351-355 -> BPSA:599-611; new actors' command threads
          \* were started by the BPSA constructor (BPSA:159-160)
          /\ actorPc'     = [actorPc EXCEPT ![d] =
                               [ns \in NS |-> IF ns \in toAdd THEN "conn" ELSE actorPc[d][ns]]]
          /\ actorRun'    = [actorRun EXCEPT ![d] =
                               [ns \in NS |-> IF ns \in toAdd THEN TRUE ELSE actorRun[d][ns]]]
          /\ cmdAlive'    = [cmdAlive EXCEPT ![d] =
                               [ns \in NS |-> IF ns \in toAdd THEN TRUE ELSE cmdAlive[d][ns]]]
          /\ refreshStop' = [refreshStop EXCEPT ![d] = toRemove]
          /\ nsCfg'       = [nsCfg EXCEPT ![d] = RefreshCfg]
    /\ UNCHANGED <<dnRun, dnShut, shutStop, bpMap, bposVars, cmdQ, dsVars, taskVars, nnVars,
                   targetFired>>

-----------------------------------------------------------------------------
(* NameNode environment for the recovering block.                                             *)

\* FSN:3885-3896 internalReleaseLease starts an attempt when PRB:63-84 allows it (none pending,
\* or the previous one timed out: time is not modeled, so any time) -> BUCF:253-290
\* initializeBlockRecovery picks the primary -> DD:717-723 addBlockToBeRecovered.
NnIssueRecovery(primary) ==
    /\ ~nnDone
    /\ nnAttempt < MaxAttempts
    /\ nnAttempt = 0 => \A x \in DN : nnKnows[x]   \* the block was written after DNs registered
    /\ LET untried == DN \ nnTried
           reset   == untried = {}                 \* BUCF:253-266 all tried -> clear the flags
       IN /\ primary \in (IF reset THEN DN ELSE untried)      \* BUCF:267-283 (latest heartbeat)
          /\ nnTried' = (IF reset THEN {} ELSE nnTried) \cup {primary}   \* BUCF:287
    /\ nnAttempt' = nnAttempt + 1                  \* FSN:3889 nextGenerationStamp -> recovery id
    /\ nnPending' = [nnPending EXCEPT ![primary] = TRUE]       \* DD:718-723 (no duplicate entry)
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, taskVars, nnDone, nnKnows,
                   nnReject, dnsBad, blockLocs, targetFired>>

\* Scenario 2 fault (operator): the DN is dropped from the include list and refreshNodes marks
\* it disallowed (DM:1403-1411 -> heartbeat DM:1871-1874; registration DM:1213-1214), or the NN
\* is restarted with -upgrade/-format so the registration ID differs (NNRS:1777-1786).
NnReject(d) ==
    /\ ~nnReject[d]
    /\ nnReject' = [nnReject EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, taskVars, nnAttempt, nnTried,
                   nnPending, nnDone, nnKnows, dnsBad, blockLocs, targetFired>>

\* Scenario 2 fault (environment): the NN's reverse DNS lookup of d fails (DM:1195-1201 with
\* the default dfs.namenode.datanode.registration.ip-hostname-check = true).
DnsFail(d) ==
    /\ ~dnsBad[d]
    /\ dnsBad' = [dnsBad EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, taskVars, nnAttempt, nnTried,
                   nnPending, nnDone, nnKnows, nnReject, blockLocs, targetFired>>

\* Scenario 2 fault (environment): NN restart (down and up as one step). The datanode map,
\* the DN descriptors' recovery queues and the chosenAsPrimary flags are in memory; the next
\* heartbeat gets REGISTER (DM:1876-1878). Recovery ids stay monotone (FSN:3889).
NnRestart ==
    /\ nnKnows'   = [d \in DN |-> FALSE]
    /\ nnPending' = [d \in DN |-> FALSE]
    /\ nnTried'   = {}
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, taskVars, nnAttempt, nnDone,
                   nnReject, dnsBad, blockLocs, targetFired>>

-----------------------------------------------------------------------------
(* Recovery Daemon: RecoveryTaskContiguous.recover() (BRW:118-184) and syncBlock (BRW:187-320) *)

\* BRW:131 getDatanodeID(bpid) -> BRW:562-567: the first registry read of the window.
TaskGetId(t) ==
    /\ task[t].st = "getId"
    /\ LET r == task[t]
           b == bpMap[r.dn][r.pool]           \* BRW:563 -> DN:2239-2241 -> BPM:85-87 get(bpid)
       IN task' = [task EXCEPT ![t] =
             IF b = Nil
             THEN \* BRW:564-565 IOException -> caught at BRW:162-166: ++errorCount
                  NextLoc([r EXCEPT !.errs = @ + 1])
             ELSE IF ~bposReg[r.dn][b]
             THEN \* BRW:567 new DatanodeID(bpos.bpRegistration) with null -> DatanodeID.java:67-68
                  \* NullPointerException; recover()'s callers catch IOException only (BRW:630)
                  [r EXCEPT !.st = "npe"]
             ELSE [r EXCEPT !.st = "initRR"]]
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, nTasks, nnVars, targetFired>>

\* BRW:132-166 callInitReplicaRecovery on the current location and the outcome handling.
TaskInitRR(t, o) ==
    /\ task[t].st = "initRR"
    /\ o \in InitRROutcomes(t)
    /\ LET r == task[t]
           x == blockLocs[r.idx]
       IN /\ task' = [task EXCEPT ![t] =
                CASE o = "replica" ->   \* BRW:136-143 candidate added to syncList
                        NextLoc([r EXCEPT !.cands = @ + 1, !.sync = @ + 1, !.okReads = @ + 1])
                  [] o = "none"    ->   \* BRW:148-151 info == null: "does not have replica"
                        NextLoc([r EXCEPT !.okReads = @ + 1])
                  [] o = "ioErr"   ->   \* BRW:162-166 IOException: ++errorCount
                        NextLoc([r EXCEPT !.errs = @ + 1])
                  [] o = "rip"     ->   \* BRW:157-161 RecoveryInProgressException: return
                        [r EXCEPT !.st = "done"]]
          \* FDI:3121-3129 the replica becomes (or stays) RUR with this recovery id
          /\ rurMax' = IF o = "replica" THEN [rurMax EXCEPT ![x] = r.rid] ELSE rurMax
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsPool, stLoaded, nTasks, nnVars,
                   targetFired>>

\* BRW:169-183 after the loop.
TaskLoopEnd(t) ==
    /\ task[t].st = "loopEnd"
    /\ LET r == task[t] IN
       task' = [task EXCEPT ![t].st =
                  IF r.errs = NLocs THEN "failed"                \* BRW:169-172 all datanodes failed
                  ELSE IF r.cands > 0 /\ r.sync = 0 THEN "failed" \* BRW:176-181 none RWR or better
                  ELSE "target"]                                  \* BRW:183 syncBlock -> BRW:188-189
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, nTasks, nnVars, targetFired>>

\* THE TARGET. BRW:189 getActiveNamenodeForBP(block.getBlockPoolId()) -> BRW:600-605.
TargetCheck(t) ==
    /\ task[t].st = "target"
    /\ LET r == task[t]
           b == bpMap[r.dn][r.pool]           \* BRW:602 datanode.getBPOfferService(bpid) (BPM:85-87)
       IN IF b = Nil                          \* BRW:603 if (bpos == null)
          THEN /\ targetFired' = TRUE         \* BRW:604 throw new IOException("No block pool offer service ...")
               /\ task' = [task EXCEPT ![t].st = "fired"]
          ELSE /\ targetFired' = targetFired
               /\ task' = [task EXCEPT ![t].st = "activeNN", ![t].readNs = b]
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, nTasks, nnVars>>

\* BRW:607-612 bpos.getActiveNN() on the BPOS read at BRW:602 (BPOS:532-543). A different check:
\* kept so that an unmap between BRW:602 and BRW:607 is not counted as the target.
TaskGetActiveNN(t) ==
    /\ task[t].st = "activeNN"
    /\ LET r == task[t] IN
       task' = [task EXCEPT ![t].st =
                  IF bposActive[r.dn][r.readNs]
                  THEN "commit"                           \* BRW:612 return activeNN
                  ELSE "failed"]                          \* BRW:608-611 "has not recognized an active NN"
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, nTasks, nnVars, targetFired>>

\* BRW:191-319 the rest of syncBlock, folded into one step (after the target, brief §3.2).
TaskCommit(t, o) ==
    /\ task[t].st = "commit"
    /\ o \in CommitOutcomes(t)
    /\ CASE o = "ok"    -> /\ nnDone' = TRUE                          \* FSN:4111+ commit / close
                           /\ task' = [task EXCEPT ![t].st = "done"]
         [] o = "stale" -> /\ UNCHANGED nnDone                        \* FSN:4106-4110 IOException
                           /\ task' = [task EXCEPT ![t].st = "failed"]
         [] o = "lost"  -> /\ UNCHANGED nnDone                        \* NN never called
                           /\ task' = [task EXCEPT ![t].st = "done"]
         [] o = "error" -> /\ UNCHANGED nnDone                        \* IOException at the DN
                           /\ task' = [task EXCEPT ![t].st = "failed"]
    /\ UNCHANGED <<dnVars, regVars, bposVars, actorVars, dsVars, nTasks, nnAttempt, nnTried,
                   nnPending, nnKnows, nnReject, dnsBad, blockLocs, targetFired>>

-----------------------------------------------------------------------------
(* Next-state relation: a plain disjunction so TLC labels each step with its action.          *)

Next ==
    \/ \E d \in DN, ns \in NS :
          \/ ActorConnect(d, ns)
          \/ ActorInitStorage(d, ns)
          \/ ActorRegister(d, ns)
          \/ ActorHeartbeat(d, ns)
          \/ CmdRegister(d, ns)
          \/ CmdRecover(d, ns)
          \/ CmdThreadCrash(d, ns)
          \/ ActorStop(d, ns)
          \/ ActorLoopExit(d, ns)
          \/ ActorCleanUp(d, ns)
    \/ \E d \in DN :
          \/ \E c \in StopCause : DnStop(d, c)
          \/ DnShutdownInterrupt(d)
          \/ RefreshStart(d)
          \/ NnIssueRecovery(d)
          \/ NnReject(d)
          \/ DnsFail(d)
    \/ NnRestart
    \/ \E t \in Task :
          \/ TaskGetId(t)
          \/ \E o \in RROutcome : TaskInitRR(t, o)
          \/ TaskLoopEnd(t)
          \/ TargetCheck(t)
          \/ TaskGetActiveNN(t)
          \/ \E o \in CommitOutcome : TaskCommit(t, o)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties.                                                                                *)

\* The ad hoc target's oracle (adhoc-coordination Shared Rule 1): BRW:604 never executes.
TargetSafe == ~targetFired

\* Once the target fired, stop exploring (used as a CONSTRAINT: TLC still checks invariants on
\* the first state where targetFired holds).
StopAfterTarget == ~targetFired

TypeOK ==
    /\ dnRun \in [DN -> BOOLEAN]
    /\ dnShut \in [DN -> {"no", "begun", "intr"}]
    /\ nsCfg \in [DN -> SUBSET NS]
    /\ shutStop \in [DN -> SUBSET NS]
    /\ refreshStop \in [DN -> SUBSET NS]
    /\ offerSvc \in [DN -> SUBSET NS]
    /\ bpMap \in [DN -> [Pool -> NS \cup {Nil}]]
    /\ bposPool \in [DN -> [NS -> Pool \cup {Nil}]]
    /\ bposActive \in [DN -> [NS -> BOOLEAN]]
    /\ bposReg \in [DN -> [NS -> BOOLEAN]]
    /\ actorPc \in [DN -> [NS -> ActorPcs]]
    /\ actorRun \in [DN -> [NS -> BOOLEAN]]
    /\ \A d \in DN, ns \in NS : /\ cmdQ[d][ns] \in Seq(Cmd)
                                /\ Len(cmdQ[d][ns]) <= MaxAttempts + 1
    /\ cmdAlive \in [DN -> [NS -> BOOLEAN]]
    /\ dsPool \in [DN -> [Pool -> BOOLEAN]]
    /\ stLoaded \in [DN -> [Pool -> BOOLEAN]]
    /\ rurMax \in [DN -> 0..MaxAttempts]
    /\ task \in [Task -> TaskRec]
    /\ nTasks \in 0..MaxAttempts
    /\ nnAttempt \in 0..MaxAttempts
    /\ nnTried \subseteq DN
    /\ nnPending \in [DN -> BOOLEAN]
    /\ nnDone \in BOOLEAN
    /\ nnKnows \in [DN -> BOOLEAN]
    /\ nnReject \in [DN -> BOOLEAN]
    /\ dnsBad \in [DN -> BOOLEAN]
    /\ blockLocs \in Perms(DN)
    /\ targetFired \in BOOLEAN

\* Structural sanity (brief §5). A message carries only what its sender held: every task comes
\* from a DNA_RECOVERBLOCK of the NN serving its pool (pool of the processing actor's BPOS,
\* recovery id already issued), and the pool was mapped on that DataNode when the active actor
\* processed the command. The mapping clause applies while the DataNode's nameservice config
\* is unchanged: after a Scenario 3 refresh, BPM:94's remove-by-key can legitimately unmap a
\* running BPOS's pool (brief CR-1).
CmdProvenance ==
    \A t \in Task : task[t].st # "none" =>
        /\ task[t].pool = PoolOfNs(task[t].via)
        /\ task[t].rid \in 1..nnAttempt
        /\ task[t].mapped \/ nsCfg[task[t].dn] # InitCfg

\* Structural sanity (brief §5): a task at (or past) TargetCheck had at least one replica
\* iteration that passed BRW:131 without an IOException (else BRW:169-172 throws first).
TargetNeedsRead ==
    \A t \in Task : task[t].st \in {"target", "activeNN", "commit", "fired"} =>
        task[t].okReads >= 1

=============================================================================
