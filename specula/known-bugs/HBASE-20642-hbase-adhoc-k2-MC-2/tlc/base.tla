------------------------------- MODULE base -------------------------------
(***************************************************************************)
(* Ad hoc coordination target: hbase-adhoc-k2                              *)
(*                                                                         *)
(*   HMaster.addColumn(TableName, ColumnFamilyDescriptor, long, long)      *)
(*   hbase-server/src/main/java/org/apache/hadoop/hbase/master/            *)
(*     HMaster.java:2253-2257                                              *)
(*                                                                         *)
(*     TableDescriptor old = getTableDescriptors().get(tableName);         *)
(*     if (old.hasColumnFamily(column.getName())) {                        *)
(*       throw new InvalidFamilyOperationException(...);    // L2255       *)
(*                                                                         *)
(* Question: can ONE logical addColumn of an absent family, issued by one  *)
(* client, reach the failing branch through the system's own retry /       *)
(* timeout / failover behaviour?  TargetSafe == ~targetFired.              *)
(*                                                                         *)
(* Category A (client <-> master RPC, master crash/failover, descriptor    *)
(* persisted on HDFS).  All citations are against the pinned tree          *)
(* 6e53c90757.  Abbreviations:                                             *)
(*   HM   hbase-server/.../master/HMaster.java                             *)
(*   MRS  hbase-server/.../master/MasterRpcServices.java                   *)
(*   MPU  hbase-server/.../master/procedure/MasterProcedureUtil.java       *)
(*   MTP  hbase-server/.../master/procedure/ModifyTableProcedure.java      *)
(*   ASTP hbase-server/.../master/procedure/                               *)
(*          AbstractStateMachineTableProcedure.java                       *)
(*   PPL  hbase-server/.../master/procedure/ProcedurePrepareLatch.java     *)
(*   PE   hbase-procedure/.../procedure2/ProcedureExecutor.java            *)
(*   SMP  hbase-procedure/.../procedure2/StateMachineProcedure.java        *)
(*   FSTD hbase-server/.../util/FSTableDescriptors.java                    *)
(*   CR   hbase-server/.../ipc/CallRunner.java                             *)
(*   ADM  hbase-client/.../client/HBaseAdmin.java                          *)
(*   RAA  hbase-client/.../client/RawAsyncHBaseAdmin.java                  *)
(*   RRC  hbase-client/.../client/RpcRetryingCallerImpl.java               *)
(*   MC   hbase-client/.../client/MasterCallable.java                      *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    InitFams,                 \* families of the table when addColumn is called (workload: {"cf0"})
    FamilySeq,                \* the client's logical addColumn requests, in order (workload: <<"cf1">>)
    MaxAttempts,              \* client maxAttempts (RRC:146 `tries >= maxAttempts - 1`)
    SameNonceOnRetry,         \* FALSE: HBaseAdmin, nonce built inside rpcCall() (ADM:1026-1027)
                              \* TRUE : RawAsyncHBaseAdmin, request built once (RAA:690-694)  [Scenario 3]
    TableEnabled,             \* MTP:124 isTableEnabled; workload disables the table first -> FALSE
    PreloadTableDescriptors   \* HM:853-856 warm-up of the descriptor cache on master init

ASSUME InitFams # {} /\ Len(FamilySeq) >= 1
ASSUME \A i \in 1..Len(FamilySeq) : FamilySeq[i] \notin InitFams
ASSUME \A i, j \in 1..Len(FamilySeq) : i # j => FamilySeq[i] # FamilySeq[j]
   \* Fault model (brief §1, §3.2): one logical add per family, only when the family is
   \* absent.  A genuinely second, distinct add (testAddSameColumnFamilyTwice) is excluded.
ASSUME MaxAttempts \in Nat \ {0}
ASSUME SameNonceOnRetry \in BOOLEAN /\ TableEnabled \in BOOLEAN
ASSUME PreloadTableDescriptors \in BOOLEAN

AllFams   == InitFams \cup {FamilySeq[i] : i \in 1..Len(FamilySeq)}
MaxSends  == MaxAttempts * Len(FamilySeq)
AttemptIds == 1..MaxSends
\* Every attempt reserves at most one procId (PE:735-739) and draws at most one nonce
\* (ADM:1026-1027), so these id spaces are finite.
ProcIds   == 1..MaxSends
Nonces    == 1..MaxSends
NoProc    == 0
NoNonce   == 0

\* ModifyTableProcedure states (MTP:94-140).  UD_FS_WRITTEN / UD_CACHE_WRITTEN are the
\* in-memory sub-steps of MODIFY_TABLE_UPDATE_TABLE_DESCRIPTOR (FSTD:590 then FSTD:593-595,
\* then the state persist PE:1551); they are never stored.  WAIT_CHILDREN is the parent
\* waiting on REOPEN child procedures (PE:1597-1600).
StoredStates == {"None", "PREPARE", "PRE_OPERATION", "UPDATE_TABLE_DESCRIPTOR",
                 "REMOVE_REPLICA_COLUMN", "DELETE_FS_LAYOUT", "POST_OPERATION",
                 "REOPEN_ALL_REGIONS", "WAIT_CHILDREN", "SUCCESS"}
RunStates    == StoredStates \cup {"UD_FS_WRITTEN", "UD_CACHE_WRITTEN"}

\* Per-attempt RPC handler program counter.
\*  Queued    : call in the master RPC call queue (CR:95)
\*  Started   : passed CR:103 and HM:2250 checkInitialized; about to execute HM:2253
\*  Checked   : passed the target guard, holding `old`
\*  NonceWait : registerNonce found the nonce reserved, spinning (PE:744-750)
\*  Run       : nonce reserved for this attempt, NonceProcedureRunnable.run() (HM:2443-2463)
\*  Awaiting  : blocked in latch.await() (HM:2458)
\*  Done      : handler returned (reply carries the result)
\*  Dropped   : call dropped by CR:103-106 (deadline passed)
\*  Gone      : handler lost with its master (crash)
LiveHpc  == {"Queued", "Started", "Checked", "NonceWait", "Run", "Awaiting"}
HpcSet   == LiveHpc \cup {"Done", "Dropped", "Gone"}
ReplySet == {"none", "ok", "retry", "lost"}
ClientPcs == {"Ready", "Waiting", "OpDone", "Finished", "Failed"}

VARIABLES
    \* ---- descriptor state (FSTableDescriptors) ----
    fsDesc,        \* families in the tableinfo file on HDFS (durable)            FSTD:590
    cacheDesc,     \* families in the active master's FSTD cache (volatile)       FSTD:233-236, 593-595
    cacheValid,    \* cache holds an entry for the table                          FSTD:232, 251-253
    \* ---- active master ----
    masterUp,      \* an active master is serving                                  [Scenario 2]
    initialized,   \* HMaster.isInitialized()                                      HM:1009, HM:2842
    epoch,         \* incarnation of the active master                             [Scenario 2]
    \* ---- RPC attempts (client request + its server handler) ----
    attempts,      \* Seq of attempt records                                        [Scenario 1, 3]
    \* ---- procedure-v2 executor ----
    procRun,       \* in-memory state of each ModifyTableProcedure                  PE:procedures
    procStored,    \* last state persisted in the procedure WAL (durable)           PE:885, PE:1640-1672
    procMeta,      \* immutable/serialized proc data: newDesc, nonce, deleteCF (durable once stored)
    procLatch,     \* attempt whose CompatibilityLatch this proc holds (volatile)   HM:2456-2457
    procedures,    \* PE.procedures (submitted, unfinished)                          PE:891
    completed,     \* PE.completed                                                    PE:1704
    nonceMap,      \* PE.nonceKeysToProcIdsMap (volatile, rebuilt on load)          PE:735-739, PE:393
    nextProcId,    \* PE.nextProcId() counter
    nextNonce,     \* client nonce generator (abstract ordinal of rdm.nextLong())
    \* ---- client ----
    client,        \* the one Admin's retry loop                                     RRC:100-170
    \* ---- target ----
    targetFired,   \* HM:2255 throw executed
    \* ---- ghost ----
    fsWriters      \* procs that executed the FS descriptor write (DescOnlyFromProc)

descVars    == <<fsDesc, cacheDesc, cacheValid>>
masterVars  == <<masterUp, initialized, epoch>>
procVars    == <<procRun, procStored, procMeta, procLatch, procedures, completed,
                 nonceMap, nextProcId>>
vars == <<descVars, masterVars, attempts, procVars, nextNonce, client, targetFired, fsWriters>>

-----------------------------------------------------------------------------
(* Helpers *)

\* FSTableDescriptors.get(tableName) as seen by the active master (FSTD:217-255):
\* usecache is TRUE on the master (HM:851 setCacheOn); a cache hit returns the cached
\* descriptor (FSTD:232-236); a miss reads the tableinfo file (FSTD:240) and caches it
\* (FSTD:251-253).
DescView == IF cacheValid THEN cacheDesc ELSE fsDesc

\* Side effect of a get() on the cache (FSTD:251-253).
GetPopulatesCache ==
    /\ cacheValid' = TRUE
    /\ cacheDesc'  = DescView

SetA(a, f, v) == [attempts EXCEPT ![a] = [@ EXCEPT ![f] = v]]

\* RRC:110-150 after a retriable failure of the current attempt:
\* `if (tries >= maxAttempts - 1) throw new RetriesExhaustedException` (RRC:146-148),
\* tries is 0-based there; client.tries counts attempts already sent.
RetryOrFail(c) ==
    IF c.tries >= MaxAttempts
    THEN [c EXCEPT !.pc = "Failed"]
    ELSE [c EXCEPT !.pc = "Ready"]

ProcAlive(p) == masterUp /\ initialized /\ p \in procedures

-----------------------------------------------------------------------------
(* Initial state: table exists with InitFams and is disabled (workload             *)
(* TestTableDescriptorModificationFromClient.java:113-118); master initialized.     *)

Init ==
    /\ fsDesc      = InitFams
    /\ cacheDesc   = InitFams
    /\ cacheValid  = TRUE
    /\ masterUp    = TRUE
    /\ initialized = TRUE
    /\ epoch       = 1
    /\ attempts    = << >>
    /\ procRun     = [p \in ProcIds |-> "None"]
    /\ procStored  = [p \in ProcIds |-> "None"]
    /\ procMeta    = [p \in ProcIds |-> [newDesc |-> {}, nonce |-> NoNonce, deleteCF |-> FALSE]]
    /\ procLatch   = [p \in ProcIds |-> 0]
    /\ procedures  = {}
    /\ completed   = {}
    /\ nonceMap    = [n \in Nonces |-> NoProc]
    /\ nextProcId  = 1
    /\ nextNonce   = 1
    /\ client      = [pc |-> "Ready", op |-> 1, tries |-> 0, nonce |-> NoNonce,
                      cur |-> 0, resultProc |-> NoProc]
    /\ targetFired = FALSE
    /\ fsWriters   = {}

-----------------------------------------------------------------------------
(***************************************************************************)
(* CLIENT: HBaseAdmin.addColumnFamily -> addColumnFamilyAsync ->           *)
(*         executeCallable -> RpcRetryingCallerImpl.callWithRetries        *)
(***************************************************************************)

\* One attempt of callWithRetries (RRC:101-107): MasterCallable.prepare resolves the
\* active master (MC:56-58) and call() issues rpcCall() with a per-attempt timeout
\* (MC:93-97).  rpcCall builds the AddColumnRequest (ADM:1021-1028).
ClientSend ==
    /\ client.pc = "Ready"
    /\ masterUp                                   \* MC:57 connection.getMaster()
    /\ LET fresh == ~(SameNonceOnRetry /\ client.tries > 0)
           \* ADM:1026-1027: ng.newNonce() inside rpcCall(), fresh every attempt.
           \* RAA:690-694: request (and nonce) built once per logical call.
           n     == IF fresh THEN nextNonce ELSE client.nonce
       IN /\ nextNonce' = IF fresh THEN nextNonce + 1 ELSE nextNonce
          /\ attempts' = Append(attempts,
                 [op |-> client.op, fam |-> FamilySeq[client.op], nonce |-> n,
                  epoch |-> epoch, hpc |-> "Queued", old |-> {}, procId |-> NoProc,
                  reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE])
          /\ client' = [client EXCEPT !.pc = "Waiting", !.tries = @ + 1, !.nonce = n,
                                      !.cur = Len(attempts) + 1]
    /\ UNCHANGED <<descVars, masterVars, procVars, targetFired, fsWriters>>

\* A reply carrying the procId arrives (MRS:525-529 -> ADM:1029-1030).
ClientReceiveOk ==
    /\ client.pc = "Waiting"
    /\ attempts[client.cur].reply = "ok"
    /\ client' = [client EXCEPT !.pc = "OpDone", !.resultProc = attempts[client.cur].procId]
    /\ UNCHANGED <<descVars, masterVars, attempts, procVars, nextNonce, targetFired, fsWriters>>

\* A retriable failure arrives: PleaseHoldException from checkInitialized (HM:2843,
\* HBaseIOException, not DoNotRetry), or the connection to a crashed master is reset.
\* RRC:110-150 retries it.
ClientReceiveRetriable ==
    /\ client.pc = "Waiting"
    /\ LET at == attempts[client.cur] IN
          \/ at.reply = "retry"
          \/ at.hpc = "Gone" /\ at.reply = "none"
    /\ client' = RetryOrFail(client)
    /\ UNCHANGED <<descVars, masterVars, attempts, procVars, nextNonce, targetFired, fsWriters>>

\* FAULT: the per-attempt rpc timeout (MC:93-97) expires before any reply.
\* CallTimeoutException extends HBaseIOException (ipc/CallTimeoutException.java:28):
\* retriable (RRC:110-150).  The server handler is NOT cancelled (CR:95-106 only drops
\* calls that have not started); `abandoned` lets a still-queued call be dropped.
ClientTimeout ==
    /\ client.pc = "Waiting"
    /\ attempts[client.cur].reply = "none"
    /\ attempts[client.cur].hpc # "Gone"
    /\ attempts' = SetA(client.cur, "abandoned", TRUE)
    /\ client' = RetryOrFail(client)
    /\ UNCHANGED <<descVars, masterVars, procVars, nextNonce, targetFired, fsWriters>>

\* FAULT: the reply was produced by the handler but lost (connection closed).
\* The client sees a retriable connection error (RRC:110-150).
ReplyLost ==
    /\ client.pc = "Waiting"
    /\ attempts[client.cur].reply = "ok"
    /\ attempts' = SetA(client.cur, "reply", "lost")
    /\ client' = RetryOrFail(client)
    /\ UNCHANGED <<descVars, masterVars, procVars, nextNonce, targetFired, fsWriters>>

\* ADM:1013 get(future, ...): the ProcedureFuture waits until the master reports the
\* procedure finished (getProcedureResult reads PE.completed), then the next logical op.
ClientAwaitProcedure ==
    /\ client.pc = "OpDone"
    /\ masterUp
    /\ client.resultProc \in completed
    /\ client' = IF client.op < Len(FamilySeq)
                 THEN [client EXCEPT !.pc = "Ready", !.op = @ + 1, !.tries = 0,
                                     !.nonce = NoNonce, !.cur = 0, !.resultProc = NoProc]
                 ELSE [client EXCEPT !.pc = "Finished"]
    /\ UNCHANGED <<descVars, masterVars, attempts, procVars, nextNonce, targetFired, fsWriters>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* MASTER RPC HANDLER: MasterRpcServices.addColumn -> HMaster.addColumn     *)
(***************************************************************************)

\* CallRunner.run (CR:95-106) then MRS:518 -> HM:2250 checkInitialized (HM:2838-2846).
HandlerStart(a) ==
    /\ attempts[a].hpc = "Queued"
    /\ masterUp
    /\ \/ \* CR:103-106: start time past the deadline -> "Dropping timed out call".
          \* Only possible once the client gave up on the attempt.
          /\ attempts[a].abandoned
          /\ attempts' = SetA(a, "hpc", "Dropped")
       \/ \* HM:2842-2843: !isInitialized() -> PleaseHoldException -> MRS:530-532.
          /\ ~initialized
          /\ attempts' = [attempts EXCEPT ![a] = [@ EXCEPT !.hpc = "Done", !.reply = "retry"]]
       \/ \* HM:2250-2251: initialized; checkTableExists passes (table exists throughout).
          /\ initialized
          /\ attempts' = SetA(a, "hpc", "Started")
    /\ UNCHANGED <<descVars, masterVars, procVars, nextNonce, client, targetFired, fsWriters>>

\* THE TARGET.  HM:2253-2257.
TargetCheck(a) ==
    /\ attempts[a].hpc = "Started"
    /\ masterUp
    /\ LET old == DescView                               \* HM:2253 getTableDescriptors().get
       IN IF attempts[a].fam \in old                     \* HM:2254 old.hasColumnFamily(...)
          THEN /\ targetFired' = TRUE                    \* HM:2255 throw InvalidFamilyOperationException
               /\ GetPopulatesCache                      \* FSTD:251-253 (the get already ran)
               /\ UNCHANGED <<fsDesc, masterVars, attempts, procVars, nextNonce, client, fsWriters>>
          ELSE /\ targetFired' = targetFired
               /\ GetPopulatesCache                      \* FSTD:251-253
               /\ attempts' = [attempts EXCEPT ![a] = [@ EXCEPT !.hpc = "Checked", !.old = old]]
               /\ UNCHANGED <<fsDesc, masterVars, procVars, nextNonce, client, fsWriters>>

\* HM:2259-2261 build newDesc = old + family, HM:2261 modifyTable:
\*   HM:2438 checkInitialized (initialized is monotone within an epoch -> passes),
\*   HM:2439 sanityCheckTableDescriptor (passes for a valid family),
\*   HM:2441 -> MPU:126-128 procExec.registerNonce(nonceKey)  (PE:728-751).
ModifyTableRegisterNonce(a) ==
    /\ attempts[a].hpc = "Checked"
    /\ masterUp
    /\ LET n == attempts[a].nonce IN
       IF nonceMap[n] = NoProc
       THEN \* PE:735-739: reserve a new procId for this nonce; return -1
            /\ nonceMap'   = [nonceMap EXCEPT ![n] = nextProcId]
            /\ nextProcId' = nextProcId + 1
            /\ attempts'   = [attempts EXCEPT ![a] = [@ EXCEPT !.hpc = "Run", !.procId = nextProcId]]
       ELSE \* PE:742-750: nonce already reserved -> spin until submitted
            /\ attempts'   = [attempts EXCEPT ![a] = [@ EXCEPT !.hpc = "NonceWait",
                                                               !.procId = nonceMap[n]]]
            /\ UNCHANGED <<nonceMap, nextProcId>>
    /\ UNCHANGED <<descVars, masterVars, procRun, procStored, procMeta, procLatch,
                   procedures, completed, nextNonce, client, targetFired, fsWriters>>

\* PE:744-751 loop exit: the reserved proc is in procedures or completed, or the nonce
\* was removed; registerNonce returns oldProcId >= 0, MPU:129 returns it, MRS:528-529
\* replies with the procId.  (isRunning() is TRUE while the master is up.)
NonceWaitDone(a) ==
    /\ attempts[a].hpc = "NonceWait"
    /\ masterUp
    /\ LET pid == attempts[a].procId IN
          \/ pid \in procedures
          \/ pid \in completed
          \/ nonceMap[attempts[a].nonce] = NoProc
    /\ attempts' = [attempts EXCEPT ![a] = [@ EXCEPT !.hpc = "Done", !.reply = "ok"]]
    /\ UNCHANGED <<descVars, masterVars, procVars, nextNonce, client, targetFired, fsWriters>>

\* MPU:130 runnable.run() = HM:2443-2463:
\*   HM:2445 getTableDescriptors().get (value only passed to coprocessors),
\*   HM:2446-2447 preModifyTable (coprocessor; no-op in the fault model),
\*   HM:2456 createBlockingLatch -> CompatibilityLatch (PPL:62-64),
\*   HM:2457 submitProcedure(new ModifyTableProcedure(env, newDesc, latch)) ->
\*     MPU:102-105 -> PE:866-893: currentProcId = nonceKeysToProcIdsMap.get(nonceKey)
\*     (PE:875-878), store.insert (PE:885), pushProcedure (PE:891).
SubmitModifyTableProcedure(a) ==
    /\ attempts[a].hpc = "Run"
    /\ masterUp
    /\ LET p   == attempts[a].procId
           nd  == attempts[a].old \cup {attempts[a].fam}       \* HM:2259-2260
       IN /\ nonceMap[attempts[a].nonce] = p                   \* PE:876-878 Preconditions
          /\ procRun'    = [procRun    EXCEPT ![p] = "PREPARE"]
          /\ procStored' = [procStored EXCEPT ![p] = "PREPARE"] \* PE:885 store.insert
          /\ procMeta'   = [procMeta   EXCEPT ![p] = [newDesc |-> nd,
                                                      nonce   |-> attempts[a].nonce,
                                                      deleteCF |-> FALSE]]
          /\ procLatch'  = [procLatch  EXCEPT ![p] = a]
          /\ procedures' = procedures \cup {p}                 \* PE:891 pushProcedure
    /\ attempts' = SetA(a, "hpc", "Awaiting")                  \* HM:2458 latch.await()
    /\ UNCHANGED <<descVars, masterVars, completed, nonceMap, nextProcId, nextNonce,
                   client, targetFired, fsWriters>>

\* HM:2458 latch.await() returns once the procedure released the latch (PPL:105-111);
\* exception is null (no failure after UPDATE_DESC: MTP:157-167, 132-139).
\* HM:2461-2462 postModifyTable (no-op), MPU:137-138 unregisterNonceIfProcedureWasNotSubmitted
\* (proc was submitted -> nonce kept, PE:762-768), MPU:140 return procId, MRS:528-529 reply.
HandlerReply(a) ==
    /\ attempts[a].hpc = "Awaiting"
    /\ masterUp
    /\ attempts[a].latchReleased
    /\ attempts' = [attempts EXCEPT ![a] = [@ EXCEPT !.hpc = "Done", !.reply = "ok"]]
    /\ UNCHANGED <<descVars, masterVars, procVars, nextNonce, client, targetFired, fsWriters>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* PROCEDURE WORKER: ModifyTableProcedure.executeFromState (MTP:94-140)    *)
(* driven by ProcedureExecutor.execProcedure (PE:1448-1560).               *)
(* Each state step is: acquire table exclusive lock (ASTP:92-100; waits    *)
(* until the master is initialized, ASTP:93), execute, setNextState, then  *)
(* updateStoreOnExec (PE:1551 -> PE:1640-1672 store.update).  holdLock is  *)
(* false (Procedure.java:226-228), so the lock is per step; each TLA+ step *)
(* below is therefore atomic w.r.t. other procedures' steps.               *)
(***************************************************************************)

ProcAdvance(p, next) ==
    /\ procRun'    = [procRun    EXCEPT ![p] = next]
    /\ procStored' = [procStored EXCEPT ![p] = next]

\* MTP:95-98 prepareModify (MTP:239-276).
MTPPrepare(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "PREPARE"
    /\ LET unmodified == DescView                               \* MTP:252-253
       IN /\ procMeta' = [procMeta EXCEPT ![p].deleteCF =       \* MTP:262-271
                             ~(unmodified \subseteq procMeta[p].newDesc)]
          /\ GetPopulatesCache                                  \* FSTD:251-253
    /\ ProcAdvance(p, "PRE_OPERATION")                          \* MTP:97, PE:1551
    /\ UNCHANGED <<fsDesc, masterVars, attempts, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* MTP:99-102 preModify -> runCoprocessorAction PRE_OPERATION (MTP:420-422; no-op).
MTPPreOperation(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "PRE_OPERATION"
    /\ ProcAdvance(p, "UPDATE_TABLE_DESCRIPTOR")
    /\ UNCHANGED <<descVars, masterVars, attempts, procMeta, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* MTP:103-104 updateTableDescriptor -> MTP:293 add -> FSTD:324-337 -> FSTD:585-590
\* writeTableDescriptor: the new tableinfo file is durable on HDFS.     [Scenario 1, 2]
MTPUpdateDescWriteFS(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "UPDATE_TABLE_DESCRIPTOR"
    /\ fsDesc'    = procMeta[p].newDesc
    /\ procRun'   = [procRun EXCEPT ![p] = "UD_FS_WRITTEN"]
    /\ fsWriters' = fsWriters \cup {p}
    /\ UNCHANGED <<cacheDesc, cacheValid, masterVars, attempts, procStored, procMeta,
                   procLatch, procedures, completed, nonceMap, nextProcId, nextNonce,
                   client, targetFired>>

\* FSTD:593-595: `if (usecache) this.cache.put(...)` (write-through).
MTPUpdateDescWriteCache(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "UD_FS_WRITTEN"
    /\ cacheDesc'  = procMeta[p].newDesc
    /\ cacheValid' = TRUE
    /\ procRun'    = [procRun EXCEPT ![p] = "UD_CACHE_WRITTEN"]
    /\ UNCHANGED <<fsDesc, masterVars, attempts, procStored, procMeta, procLatch, procedures,
                   completed, nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* MTP:105 setNextState(REMOVE_REPLICA_COLUMN), then PE:1551 store.update.
MTPUpdateDescPersist(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "UD_CACHE_WRITTEN"
    /\ ProcAdvance(p, "REMOVE_REPLICA_COLUMN")
    /\ UNCHANGED <<descVars, masterVars, attempts, procMeta, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* MTP:107-114 updateReplicaColumnsIfNeeded (replication unchanged: no-op), branch on
\* deleteColumnFamilyInModify.
MTPRemoveReplicaColumn(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "REMOVE_REPLICA_COLUMN"
    /\ ProcAdvance(p, IF procMeta[p].deleteCF THEN "DELETE_FS_LAYOUT" ELSE "POST_OPERATION")
    /\ UNCHANGED <<descVars, masterVars, attempts, procMeta, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* MTP:115-118 deleteFromFs (abstracted; no descriptor effect).
MTPDeleteFsLayout(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "DELETE_FS_LAYOUT"
    /\ ProcAdvance(p, "POST_OPERATION")
    /\ UNCHANGED <<descVars, masterVars, attempts, procMeta, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* MTP:119-122 postModify -> postCompletedModifyTableAction (MTP:424-426; no-op stutter
\* point that only lengthens the commit->reply window).
MTPPostOperation(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "POST_OPERATION"
    /\ ProcAdvance(p, "REOPEN_ALL_REGIONS")
    /\ UNCHANGED <<descVars, masterVars, attempts, procMeta, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* MTP:123-128.  Enabled table: add REOPEN child procedures; the parent WAITs
\* (PE:1597-1600) and its store row is rewritten with children (PE:1642-1646).
\* Disabled table (workload): NO_MORE_STATE -> SMP:190 EOF -> PE:1526-1528 SUCCESS ->
\* PE:1655-1666 store.update of the finished root.
MTPReopenAllRegions(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "REOPEN_ALL_REGIONS"
    /\ ProcAdvance(p, IF TableEnabled THEN "WAIT_CHILDREN" ELSE "SUCCESS")
    /\ UNCHANGED <<descVars, masterVars, attempts, procMeta, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* Children done (PE:1620-1636 countDownChildren -> parent runnable); parent re-executes
\* with !hasMoreState (SMP:171) -> SUCCESS (PE:1526-1528) -> store.update.
MTPReopenChildrenDone(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "WAIT_CHILDREN"
    /\ ProcAdvance(p, "SUCCESS")
    /\ UNCHANGED <<descVars, masterVars, attempts, procMeta, procLatch, procedures, completed,
                   nonceMap, nextProcId, nextNonce, client, targetFired, fsWriters>>

\* PE:1263-1269 -> procedureFinished (PE:1693-1716): execCompletionCleanup ->
\* MTP:169-171 completionCleanup -> releaseSyncLatch (ASTP:115-116 -> PPL:105-111),
\* completed.put (PE:1704), procedures.remove (PE:1706).
ProcedureFinished(p) ==
    /\ ProcAlive(p)
    /\ procRun[p] = "SUCCESS"
    /\ LET a == procLatch[p] IN
       attempts' = IF a # 0 /\ attempts[a].hpc = "Awaiting"
                   THEN SetA(a, "latchReleased", TRUE)
                   ELSE attempts
    /\ completed'  = completed \cup {p}
    /\ procedures' = procedures \ {p}
    /\ UNCHANGED <<descVars, masterVars, procRun, procStored, procMeta, procLatch, nonceMap,
                   nextProcId, nextNonce, client, targetFired, fsWriters>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* MASTER CRASH / FAILOVER                                       [Scenario 2]*)
(***************************************************************************)

\* FAULT: the active master dies.  Volatile state is lost: RPC handlers and their
\* latches, the FSTD cache, PE.procedures/completed/nonceKeysToProcIdsMap.  Durable:
\* fsDesc (HDFS), procStored/procMeta (procedure WAL).  Connections to the dead master
\* are reset, so waiting clients see a retriable error (ClientReceiveRetriable).
MasterCrash ==
    /\ masterUp
    /\ masterUp'    = FALSE
    /\ initialized' = FALSE
    /\ cacheValid'  = FALSE
    /\ cacheDesc'   = {}
    /\ attempts'    = [a \in DOMAIN attempts |->
                         IF attempts[a].hpc \in LiveHpc
                         THEN [attempts[a] EXCEPT !.hpc = "Gone"]
                         ELSE attempts[a]]
    /\ procRun'     = [p \in ProcIds |-> "None"]
    /\ procLatch'   = [p \in ProcIds |-> 0]
    /\ procedures'  = {}
    /\ completed'   = {}
    /\ nonceMap'    = [n \in Nonces |-> NoProc]
    /\ UNCHANGED <<fsDesc, epoch, procStored, procMeta, nextProcId, nextNonce, client,
                   targetFired, fsWriters>>

\* A backup master becomes active and runs finishActiveMasterInitialization up to (not
\* including) setInitialized(true):
\*   HM:851 tableDescriptors.setCacheOn() (FSTD:193-196 clears the cache),
\*   HM:853-856 optional getAll() warm-up from HDFS,
\*   HM:871 createProcedureExecutor -> PE.load -> loadProcedures (PE:360-395):
\*     finished procs -> completed (PE:372-373); others -> procedures with their stored
\*     state (PE:384-385); every nonce -> nonceKeysToProcIdsMap (PE:393-394).
\* nextProcId is kept monotone (abstraction: procIds are never reused).
MasterRecover ==
    /\ ~masterUp
    /\ masterUp'    = TRUE
    /\ initialized' = FALSE
    /\ epoch'       = epoch + 1
    /\ cacheValid'  = PreloadTableDescriptors
    /\ cacheDesc'   = IF PreloadTableDescriptors THEN fsDesc ELSE {}
    /\ LET stored == {p \in ProcIds : procStored[p] # "None"} IN
       /\ completed'  = {p \in stored : procStored[p] = "SUCCESS"}
       /\ procedures' = {p \in stored : procStored[p] # "SUCCESS"}
       /\ procRun'    = [p \in ProcIds |-> procStored[p]]
       /\ nonceMap'   = [n \in Nonces |->
                           IF \E p \in stored : procMeta[p].nonce = n
                           THEN CHOOSE p \in stored : procMeta[p].nonce = n
                           ELSE NoProc]
    /\ UNCHANGED <<fsDesc, attempts, procStored, procMeta, procLatch, nextProcId, nextNonce,
                   client, targetFired, fsWriters>>

\* HM:1009 setInitialized(true): RPCs pass checkInitialized; procedures may take the
\* table lock (ASTP:93 waitInitialized).
MasterFinishInitialization ==
    /\ masterUp
    /\ ~initialized
    /\ initialized' = TRUE
    /\ UNCHANGED <<descVars, masterUp, epoch, attempts, procVars, nextNonce, client,
                   targetFired, fsWriters>>

-----------------------------------------------------------------------------

AttemptIdx == DOMAIN attempts

HandlerNext ==
    \E a \in AttemptIdx :
        \/ HandlerStart(a)
        \/ TargetCheck(a)
        \/ ModifyTableRegisterNonce(a)
        \/ NonceWaitDone(a)
        \/ SubmitModifyTableProcedure(a)
        \/ HandlerReply(a)

ProcNext ==
    \E p \in ProcIds :
        \/ MTPPrepare(p)
        \/ MTPPreOperation(p)
        \/ MTPUpdateDescWriteFS(p)
        \/ MTPUpdateDescWriteCache(p)
        \/ MTPUpdateDescPersist(p)
        \/ MTPRemoveReplicaColumn(p)
        \/ MTPDeleteFsLayout(p)
        \/ MTPPostOperation(p)
        \/ MTPReopenAllRegions(p)
        \/ MTPReopenChildrenDone(p)
        \/ ProcedureFinished(p)

ClientNext ==
    \/ ClientSend
    \/ ClientReceiveOk
    \/ ClientReceiveRetriable
    \/ ClientAwaitProcedure

FaultNext ==
    \/ ClientTimeout
    \/ ReplyLost
    \/ MasterCrash

MasterNext ==
    \/ MasterRecover
    \/ MasterFinishInitialization

\* Terminal stuttering: the target fired, or the client is finished/failed and the
\* system has nothing left to do.
Terminated ==
    /\ targetFired \/ client.pc \in {"Finished", "Failed"}
    /\ UNCHANGED vars

Next ==
    \/ /\ ~targetFired
       /\ \/ ClientNext
          \/ HandlerNext
          \/ ProcNext
          \/ FaultNext
          \/ MasterNext
    \/ Terminated

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* PROPERTIES                                                              *)
(***************************************************************************)

\* The ad hoc target: HM:2255 is never executed.
TargetSafe == ~targetFired

\* Sanity (brief §5): a requested family is on HDFS only because some
\* ModifyTableProcedure carrying it executed the FS write (MTP:293 -> FSTD:590).
DescOnlyFromProc ==
    \A f \in fsDesc \ InitFams :
        \E p \in fsWriters : f \in procMeta[p].newDesc

\* Sanity (brief §5): types, plus write-through cache (FSTD:590-595): on the active
\* master the cache equals HDFS except inside a proc's FS-write -> cache-put window;
\* and each attempt carries only values its sender held.
TypeOK ==
    /\ fsDesc \subseteq AllFams /\ cacheDesc \subseteq AllFams /\ cacheValid \in BOOLEAN
    /\ masterUp \in BOOLEAN /\ initialized \in BOOLEAN /\ epoch \in Nat \ {0}
    /\ Len(attempts) <= MaxSends
    /\ \A a \in AttemptIdx :
         /\ attempts[a].hpc \in HpcSet
         /\ attempts[a].reply \in ReplySet
         /\ attempts[a].op \in 1..Len(FamilySeq)
         /\ attempts[a].fam = FamilySeq[attempts[a].op]      \* sender held this value
         /\ attempts[a].nonce \in 1..(nextNonce - 1)         \* nonce was generated
         /\ attempts[a].epoch \in 1..epoch
         /\ attempts[a].old \subseteq AllFams
    /\ procRun \in [ProcIds -> RunStates]
    /\ procStored \in [ProcIds -> StoredStates]
    /\ procedures \subseteq ProcIds /\ completed \subseteq ProcIds
    /\ procedures \cap completed = {}
    /\ nonceMap \in [Nonces -> {NoProc} \cup ProcIds]
    /\ client.pc \in ClientPcs
    /\ targetFired \in BOOLEAN
    /\ (masterUp /\ cacheValid) =>
          \/ cacheDesc = fsDesc
          \/ \E p \in ProcIds : procRun[p] = "UD_FS_WRITTEN" /\ fsDesc = procMeta[p].newDesc

=============================================================================
