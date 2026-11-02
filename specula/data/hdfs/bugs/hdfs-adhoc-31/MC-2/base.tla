-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-31: can DataNode.getBPOSForBlock reach its failing branch?   *)
(*                                                                         *)
(*   DataNode.java:1833-1842 (pinned tree 734dd8a67cd)                     *)
(*     1836  BPOfferService bpos = blockPoolManager.get(block.getBPId());  *)
(*     1837  if (bpos == null) {                                          *)
(*     1838    throw new IOException("cannot locate OfferService thread    *)
(*     1839        for bp=" + block.getBlockPoolId());   (frame line 1839) *)
(*                                                                         *)
(* phi_T: at the synchronized read BlockPoolManager.get (BPM L85-87),      *)
(* bpByBlockPoolId has no key for the block's pool.  Values are never      *)
(* null (BPM L71), so the model keeps one pool P and bpMap = the BPOS      *)
(* stored under P, or NoBpos when the key is absent.                       *)
(*                                                                         *)
(* Category A (modeling brief sec. 1): one DataNode, the NameNode as an    *)
(* environment (heartbeat responses, rejections, admin operations), and    *)
(* per-thread program counters for the DataNode's threads.  Actions are    *)
(* split at lock releases and lock-free reads (brief sec. 3.1).            *)
(*                                                                         *)
(* Entries into L1836 (brief sec. 1):                                      *)
(*   E1 transferBlock DN L2838  (command processor; workload test thread)  *)
(*   E2 reportBadBlocks(block, volume) DN L1797  (DataTransfer, readBlock, *)
(*      VolumeScanner via handleBadBlock; DirectoryScanner checkAndUpdate) *)
(*   E3 reportRemoteBadBlock DN L1810  (BlockReceiver; EC read rounds)     *)
(*                                                                         *)
(* Paths are relative to hadoop-hdfs-project/hadoop-hdfs/src/main/java/    *)
(* org/apache/hadoop/hdfs/server/datanode/.  Abbreviations:                *)
(*   DN DataNode.java, BPOS BPOfferService.java, BPSA BPServiceActor.java, *)
(*   BPM BlockPoolManager.java, FSD fsdataset/impl/FsDatasetImpl.java,     *)
(*   FSV fsdataset/impl/FsVolumeImpl.java, DX DataXceiver.java,            *)
(*   BR BlockReceiver.java, BS BlockSender.java, VS VolumeScanner.java,    *)
(*   BSc BlockScanner.java, DSc DirectoryScanner.java, DS DataStorage.java,*)
(*   BPSS BlockPoolSliceStorage.java, ECW erasurecode/ErasureCodingWorker, *)
(*   SR erasurecode/StripedReader.java, BMH hadoop-hdfs-client .../        *)
(*   BlockMetadataHeader.java.                                             *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Bpos,               \* BPOfferService objects for pool P: {"O"}, or {"O","N"} for Scenario 4
    CmdBpos,            \* BPOS whose NameNode heartbeats may carry commands (environment choice)
    MaxBlocks,          \* max blocks in one DNA_TRANSFER BlockCommand (brief S1: default 2)
    Scanner,            \* "mock" (workload TestDiskError L247-249) | "real" | "disabled"
    HeaderCorrupt,      \* the local replica's meta header is corrupt at Init (fixture
                        \* TestDiskError L258-263; see FixtureCorruptHeader)
    AssertionsEnabled,  \* JVM -ea (surefire default; brief sec. 1)
    TestCallerEnabled,  \* workload test thread calls transferBlock (TestDiskError L279)
    LocalSlots,         \* slots for local bad-block reporter threads
    RemoteSlots         \* slots for remote-corruption reporter threads

OldB       == "O"                    \* BPOS created at DN startup (nameservice key null)
NewBs      == Bpos \ {OldB}          \* BPOS created by refreshNamenodes (Scenario 4)
NoBpos     == "none"
TestCaller == "test"
Callers    == Bpos \cup {TestCaller} \* threads that run transferBlock (DN L2835)
\* Command-queue entries (one batch = one entry, BPSA L1486-1523):
\*   k \in 1..MaxBlocks  a DNA_TRANSFER BlockCommand of k blocks of P
EcCmd      == 0                      \* a DNA_ERASURE_CODING_RECONSTRUCTION
OtherCmd   == -1                     \* a batch of commands this model does not track
                                     \* (DNA_FINALIZE after a block report, ...)
EmptyBatch == -2                     \* a batch with no command (BPSA L776, L1510-1517)
CmdVals    == -2..MaxBlocks
LSlot      == 1..LocalSlots
RSlot      == 1..RemoteSlots

ASSUME /\ OldB \in Bpos
       /\ CmdBpos \subseteq Bpos
       /\ MaxBlocks \in Nat \ {0}
       /\ Scanner \in {"mock", "real", "disabled"}
       /\ HeaderCorrupt \in BOOLEAN
       /\ AssertionsEnabled \in BOOLEAN
       /\ TestCallerEnabled \in BOOLEAN
       /\ LocalSlots \in Nat /\ RemoteSlots \in Nat

ActorPcs  == {"new", "hs", "hsStorage", "hsDataset", "reg", "run", "iter",
              "cleanup", "shutActor", "unpubRemove", "unpubGate",
              "unpubDataset", "unpubStorage", "exited"}
CallerPcs == {"idle", "check", "take", "assert", "readActive", "ecSubmit",
              "e1", "reg", "ckblk", "ctor", "exec", "exited", "done"}
LRepPcs   == {"none", "xf_send", "rd_reg", "rd_send", "hbb", "vs_send",
              "vs_contains", "ds_locked", "getvol", "e2"}
RRepPcs   == {"none", "rc_create", "rc_active", "rc_report", "ec_task", "ec_report"}
ShPcs     == {"none", "killXceiver", "scanners", "scannersJoin", "xfer",
              "interrupt", "ec", "stopAll", "done"}

VARIABLES
    \* ---- guard operand: BlockPoolManager (BPM L49-54) ----
    bpMap,          \* bpByBlockPoolId.get(P): a BPOS or NoBpos (BPM L51)
    offerSvcs,      \* offerServices, a CopyOnWriteArrayList (BPM L53-54)
    \* ---- dataset and storage of pool P (brief S2, S4) ----
    dsHasPool,      \* FsDataset holds P: volumeMap + volumes (DN L2202 add, FSD L3331-3332 release)
    storHasPool,    \* DataStorage holds P's loaded BlockPoolSliceStorage (DS L1409-1423, BPSS L221)
    metaCorrupt,    \* P's replica has a corrupt meta header on disk (read by BS L342 -> BMH L189-192)
    \* ---- DataNode-wide state ----
    dnShouldRun,    \* DataNode.shouldRun (DN L2545, L2743)
    shPc,           \* DataNode.shutdown() thread position (T1, DN L2527-2700)
    xferOpen,       \* xferService accepts tasks (closed at DN L2601)
    xcAccept,       \* xceiver servers accept connections (killed at DN L2551-2568)
    xcIntr,         \* "dataXceiverServer" thread group interrupted (DN L2612)
    ecOpen,         \* EC reconstruction pool accepts tasks (DN L2659 -> ECW L167-170)
    refreshPc,      \* refreshNamenodes caller (T5 / Scenario 4, BPM L148-252)
    scanPhase,      \* "run" | "stopping" (removeAllVolumeScanners holds the BSc monitor) | "cleared"
    vsPoolEnabled,  \* VolumeScanners have a block iterator for P (DN L2209 enable, L2160 disable)
    vsSuspect,      \* a VolumeScanner holds P's suspect block (DN L4122 -> VS L705-722)
    dirScanUp,      \* the DirectoryScanner exists (DN L2210 initDirectoryScanner, L1611-1630)
    \* ---- per BPOS b (one NameNode per nameservice: one actor per BPOS) ----
    actorPc,        \* BPServiceActor thread position
    svcRun,         \* BPSA.shouldServiceRun (BPSA L116)
    stopped,        \* BPSA.stop() was called: actor and command thread interrupted (BPSA L622-633)
    hasBp,          \* BPOS.bpId != null (BPOS L77, L258-260)
    bpReg,          \* BPOS.bpRegistration != null (BPOS L74, L432)
    inSvc,          \* actor \in BPOS.bpServices (BPOS L92-93, L483)
    active,         \* BPOS.bpServiceToActive == actor (BPOS L86)
    cmdQ,           \* command processor queue: Seq of CmdVals, one entry per batch
    \* ---- command processor threads and the workload test thread ----
    cpc,            \* [Callers -> CallerPcs]
    cpBlk,          \* current batch (CmdVals); for a DNA_TRANSFER, blocks still to run incl. the current
    \* ---- worker threads ----
    lrep,           \* local bad-block reporters (E2): [k |-> kind, pc |-> position]
    rrep,           \* remote-corruption reporters (E3)
    \* ---- target ----
    targetFired,    \* the failing branch DN L1837-1838 executed
    targetEntry     \* "none" | "E1" | "E2" | "E3": entry of the first failing check (diagnostic)

regVars    == <<bpMap, offerSvcs>>
dataVars   == <<dsHasPool, storHasPool, metaCorrupt>>
dnVars     == <<dnShouldRun, shPc, xferOpen, xcAccept, xcIntr, ecOpen, refreshPc>>
scanVars   == <<scanPhase, vsPoolEnabled, vsSuspect, dirScanUp>>
actorVars  == <<actorPc, svcRun, stopped, hasBp, bpReg, inSvc, active, cmdQ>>
cpVars     == <<cpc, cpBlk>>
workVars   == <<lrep, rrep>>
targetVars == <<targetFired, targetEntry>>
vars == <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, workVars, targetVars>>

-----------------------------------------------------------------------------
(* Helpers *)

\* BPSA L953-955 shouldRun() == shouldServiceRun && dn.shouldRun()
ShouldRun(b) == svcRun[b] /\ dnShouldRun

\* The actor holds the BPOS write lock: verifyAndSetNamespaceInfo (BPOS L384-414)
\* and shutdownActor (BPOS L477-490).  CPReadActive takes the read lock (BPOS L692).
WLockHeld(b) == actorPc[b] \in {"hsStorage", "hsDataset", "unpubRemove",
                                "unpubGate", "unpubDataset", "unpubStorage"}

\* BlockScanner.isEnabled() (BSc L214-216); the workload mock stubs it TRUE
\* (TestDiskError L247-249).
ScannerEnabled == Scanner \in {"mock", "real"}

\* BSc L221 hasAnyRegisteredScanner(): an unstubbed Mockito mock returns FALSE;
\* "disabled" never adds scanners (BSc addVolumeScanner); L302 clears them.
HasAnyRegisteredScanner == Scanner = "real" /\ scanPhase # "cleared"

\* BSc L294-303 removeAllVolumeScanners is synchronized and joins the
\* VolumeScanners while holding the monitor.  A Mockito mock has no such body.
BsMonitorHeld == Scanner # "mock" /\ scanPhase = "stopping"

\* Local reporter kinds: "xf" DataTransfer task, "rd" readBlock xceiver,
\* "vs" VolumeScanner thread, "ds" DirectoryScanner reconcile thread.
NoRep == [k |-> "none", pc |-> "none"]
FreeL == {i \in LSlot : lrep[i].pc = "none"}
FreeR == {i \in RSlot : rrep[i] = "none"}
\* Lowest free slot (deterministic allocation); exhausting the slots is a model error.
StartL(kind, p) ==
    /\ Assert(FreeL # {}, "local reporter slots exhausted: raise LocalSlots")
    /\ lrep' = [lrep EXCEPT ![CHOOSE i \in FreeL : \A j \in FreeL : i <= j] =
                   [k |-> kind, pc |-> p]]
\* Move local reporter i to position p, or end it.
LTo(i, p) == lrep' = [lrep EXCEPT ![i] = IF p = "none" THEN NoRep ELSE [@ EXCEPT !.pc = p]]
\* One VolumeScanner thread per volume and one DirectoryScanner thread scan
\* one block at a time (VS run loop -> scanBlock; DSc reconcile L474-494).
VSBusy == \E i \in LSlot : lrep[i].k = "vs"
DSBusy == \E i \in LSlot : lrep[i].k = "ds"
StartR(p) ==
    /\ Assert(FreeR # {}, "remote reporter slots exhausted: raise RemoteSlots")
    /\ rrep' = [rrep EXCEPT ![CHOOSE i \in FreeR : \A j \in FreeR : i <= j] = p]

\* transferBlocks loop (DN L2902-2909) after block i returned or threw an
\* IOException (caught at L2906-2908).  The test thread instead returns to
\* the test (TestDiskError L279).
AfterBlock(c) ==
    IF c = TestCaller
    THEN /\ cpc' = [cpc EXCEPT ![c] = "done"]
         /\ cpBlk' = [cpBlk EXCEPT ![c] = 0]
    ELSE IF cpBlk[c] > 1
         THEN /\ cpc' = [cpc EXCEPT ![c] = "e1"]
              /\ cpBlk' = [cpBlk EXCEPT ![c] = @ - 1]
         ELSE \* BPOS L818 return true; BPSA L1432-1433; loop back to L1428
              /\ cpc' = [cpc EXCEPT ![c] = "check"]
              /\ cpBlk' = [cpBlk EXCEPT ![c] = 0]

\* A RuntimeException or Error escapes transferBlocks (catches IOException
\* only, DN L2906), processCommand (catches RemoteException/IOException,
\* BPSA L1461-1472) and processQueue (catches InterruptedException, L1434):
\* work() L1415-1417 logs it, finally L1418-1421 shouldServiceRun = false.
CallerDies(c) ==
    /\ cpc' = [cpc EXCEPT ![c] = IF c = TestCaller THEN "done" ELSE "exited"]
    /\ cpBlk' = [cpBlk EXCEPT ![c] = 0]
    /\ svcRun' = IF c = TestCaller THEN svcRun ELSE [svcRun EXCEPT ![c] = FALSE]

\* The failing branch.  The IOException itself is handled by each caller.
Fire(entry) ==
    /\ targetFired' = TRUE
    /\ targetEntry' = IF targetFired THEN targetEntry ELSE entry

-----------------------------------------------------------------------------
(* Initial state: DN started, BPOS O's actor about to handshake            *)

Init ==
    /\ bpMap = NoBpos
    /\ offerSvcs = {OldB}                       \* BPM L232-233 at DN startup
    /\ dsHasPool = FALSE
    /\ storHasPool = FALSE
    /\ metaCorrupt = HeaderCorrupt
    /\ dnShouldRun = TRUE
    /\ shPc = "none"
    /\ xferOpen = TRUE
    /\ xcAccept = TRUE
    /\ xcIntr = FALSE
    /\ ecOpen = TRUE
    /\ refreshPc = "idle"
    /\ scanPhase = "run"
    /\ vsPoolEnabled = FALSE
    /\ vsSuspect = FALSE
    /\ dirScanUp = FALSE
    \* BPM L236 startAll -> BPOS.start L351-355 -> BPSA.start L599-611
    /\ actorPc = [b \in Bpos |-> IF b = OldB THEN "hs" ELSE "new"]
    /\ svcRun = [b \in Bpos |-> TRUE]
    /\ stopped = [b \in Bpos |-> FALSE]
    /\ hasBp = [b \in Bpos |-> FALSE]
    /\ bpReg = [b \in Bpos |-> FALSE]
    /\ inSvc = [b \in Bpos |-> b = OldB]        \* BPOS ctor L139-142
    /\ active = [b \in Bpos |-> FALSE]
    /\ cmdQ = [b \in Bpos |-> <<>>]
    \* BPSA ctor L159-160 starts the command processor
    /\ cpc = [c \in Callers |-> IF c = OldB THEN "check" ELSE "idle"]
    /\ cpBlk = [c \in Callers |-> 0]
    /\ lrep = [i \in LSlot |-> NoRep]
    /\ rrep = [i \in RSlot |-> "none"]
    /\ targetFired = FALSE
    /\ targetEntry = "none"

-----------------------------------------------------------------------------
(* Actor handshake: BPSA.run L900-930 -> connectToNNAndHandshake L302-325  *)

\* [S4 step N1] BPSA L304-308 connect + versionRequest; L317 ->
\* BPOS.verifyAndSetNamespaceInfo L382-401 -> DN.initBlockPool L2185-2195.
ActorHandshakePut(b) ==
    /\ actorPc[b] = "hs"
    \* BPOS L384 writeLock; L386-390 the single NN reports ACTIVE and
    \* bpServiceToActive == null -> bpServiceToActive = actor
    /\ active' = [active EXCEPT ![b] = TRUE]
    \* BPOS L394 setNamespaceInfo(nsInfo) returns null on the first handshake
    \* (one actor per BPOS); L258-260 bpId = P
    /\ hasBp' = [hasBp EXCEPT ![b] = TRUE]
    \* DN L2192 setClusterId; DN L2195 blockPoolManager.addBlockPool(bpos):
    \* BPM L66-67 bpos is in offerServices (b leaves it only in its own
    \* UnpubMapRemove); BPM L71 put(P, bpos) overwrites any entry
    /\ bpMap' = b
    /\ actorPc' = [actorPc EXCEPT ![b] = "hsStorage"]
    /\ UNCHANGED <<offerSvcs, dataVars, dnVars, scanVars, svcRun, stopped, bpReg,
                   inSvc, cmdQ, cpVars, workVars, targetVars>>

\* [S4 step N2] DN L2199 initStorage -> L2262-2264 synchronized (this)
\* storage.recoverTransitionRead -> DS L564-567 -> DS L382 addStorageLocations
\* (synchronized) -> L450-464 -> DS L1409-1419 reuses P's BPSS if present ->
\* BPSS L215-225 loadBpStorageDirectories.
ActorInitStorage(b) ==
    /\ actorPc[b] = "hsStorage"
    /\ IF ~storHasPool
         THEN /\ storHasPool' = TRUE
              /\ actorPc' = [actorPc EXCEPT ![b] = "hsDataset"]
              /\ UNCHANGED hasBp
         ELSE \* BPSS L221-225 "attempt to load an used block storage" for every
              \* location -> DS L566-567 "All specified directories have failed
              \* to load." -> BPOS L403-409 setNamespaceInfo(null): bpId = null;
              \* the map entry put at DN L2195 stays (brief CR-2).  BPOS L412-414
              \* unlock; BPSA L910-921 INIT_FAILED, shouldRetryInit() is FALSE
              \* (BPSA L949-951, BPOS L860-867: no bpId, the only actor is
              \* INIT_FAILED) -> FAILED, return -> finally L943-945 cleanUp()
              /\ hasBp' = [hasBp EXCEPT ![b] = FALSE]
              /\ actorPc' = [actorPc EXCEPT ![b] = "cleanup"]
              /\ UNCHANGED storHasPool
    /\ UNCHANGED <<regVars, dsHasPool, metaCorrupt, dnVars, scanVars, svcRun, stopped, bpReg,
                   inSvc, active, cmdQ, cpVars, workVars, targetVars>>

\* [S4 step N3] DN L2201-2211.
ActorAddDataset(b) ==
    /\ actorPc[b] = "hsDataset"
    /\ dsHasPool' = TRUE                        \* DN L2202 data.addBlockPool(P)
    \* DN L2209 blockScanner.enableBlockPoolId -> BSc L310-315 (mock: stub;
    \* "disabled": no VolumeScanners; after L302 the scanner map is empty)
    /\ vsPoolEnabled' = (HasAnyRegisteredScanner \/ vsPoolEnabled)
    /\ dirScanUp' = TRUE                        \* DN L2210 initDirectoryScanner (once per DN)
    \* BPOS L412-414 writeUnlock; BPSA L318-324 -> register(nsInfo)
    /\ actorPc' = [actorPc EXCEPT ![b] = "reg"]
    /\ UNCHANGED <<regVars, storHasPool, metaCorrupt, dnVars, scanPhase, vsSuspect, svcRun,
                   stopped, hasBp, bpReg, inSvc, active, cmdQ, cpVars, workVars,
                   targetVars>>

\* BPSA L838-879 register(nsInfo).
ActorRegister(b) ==
    /\ actorPc[b] = "reg"
    /\ IF ShouldRun(b)
         THEN \* L845-851 registerDatanode RPC; L871 bpos.registrationSucceeded:
              \* BPOS L424-434 writeLock, bpRegistration = reg (L432)
              /\ bpReg' = [bpReg EXCEPT ![b] = TRUE]
              \* BPSA L926 RUNNING; L931-933 while (shouldRun()) offerService()
              /\ actorPc' = [actorPc EXCEPT ![b] = "run"]
         ELSE \* L845 loop ends; L866-867 IOException("DN shut down before block
              \* pool registered") -> L910-921: shouldRun() is FALSE, no retry ->
              \* FAILED, return -> finally L943-945 cleanUp()
              /\ actorPc' = [actorPc EXCEPT ![b] = "cleanup"]
              /\ UNCHANGED bpReg
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, svcRun, stopped, hasBp,
                   inSvc, active, cmdQ, cpVars, workVars, targetVars>>

-----------------------------------------------------------------------------
(* offerService loop: BPSA L674-813.  "run" = at the loop head L686 or   *)
(* waiting in L790; "iter" = inside one iteration (L687-L811), where no    *)
(* shouldRun() check runs: a response that arrives after DN L2545 still    *)
(* enqueues its commands.                                                  *)

\* L686 while (shouldRun()) holds: one iteration starts.
ActorIterStart(b) ==
    /\ actorPc[b] = "run"
    /\ ShouldRun(b)
    /\ actorPc' = [actorPc EXCEPT ![b] = "iter"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, svcRun, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, cpVars, workVars, targetVars>>

\* End of the iteration: L790 waitTillNextIBR returned (or an IOException /
\* non-fatal RemoteException was handled at L800-807); L811
\* processQueueMessages; back to L686.  An interrupt from BPSA.stop (L628)
\* only cuts the wait or the RPC short.
ActorIterEnd(b) ==
    /\ actorPc[b] = "iter"
    /\ actorPc' = [actorPc EXCEPT ![b] = "run"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, svcRun, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, cpVars, workVars, targetVars>>

\* Environment: the heartbeat (L694-711) returns a DNA_TRANSFER of k blocks of P
\* (DatanodeManager L1904-1950).  The heartbeat needs P in every volume:
\* sendHeartBeat L547-548 getStorageReports(P) -> FSV L562-567 "block pool
\* ... is not found" otherwise.  L733-734 updateActorStatesFromHeartbeat keeps
\* the single ACTIVE NN active; L745-756 enqueue (LinkedBlockingDeque.put is
\* not interruptible).
ActorHeartbeatTransfer(b, k) ==
    /\ actorPc[b] = "iter"
    /\ b \in CmdBpos
    /\ dsHasPool
    /\ k \in 1..MaxBlocks
    /\ cmdQ' = [cmdQ EXCEPT ![b] = Append(@, k)]     \* BPSA L755 -> L1519-1523
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, svcRun, stopped,
                   hasBp, bpReg, inSvc, active, cpVars, workVars, targetVars>>

\* Environment: the heartbeat returns a DNA_ERASURE_CODING_RECONSTRUCTION
\* (Scenario 3, BPOS L809-814).  One modeled command per batch (brief X7).
ActorHeartbeatEC(b) ==
    /\ actorPc[b] = "iter"
    /\ b \in CmdBpos
    /\ dsHasPool
    /\ cmdQ' = [cmdQ EXCEPT ![b] = Append(@, EcCmd)]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, svcRun, stopped,
                   hasBp, bpReg, inSvc, active, cpVars, workVars, targetVars>>

\* Environment: a batch this model does not track: heartbeat commands other
\* than the two above (L755), the full block report's result (L772-776,
\* enqueued even when empty, L1510-1517) or a cache-report command (L779-780).
\* It still passes the per-command guards of BPOS L673 / L692-698.
ActorEnqueueOther(b, e) ==
    /\ actorPc[b] = "iter"
    /\ e \in {OtherCmd, EmptyBatch}
    /\ cmdQ' = [cmdQ EXCEPT ![b] = Append(@, e)]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, svcRun, stopped,
                   hasBp, bpReg, inSvc, active, cpVars, workVars, targetVars>>

\* Fault T3: the heartbeat RPC throws RemoteException Unregistered /
\* Disallowed / IncorrectVersion (BPSA L791-798): shouldServiceRun = false,
\* return; run() L931 loop ends; L939; finally L943-945 cleanUp().
ActorHeartbeatRejected(b) ==
    /\ actorPc[b] = "iter"
    /\ dsHasPool                                     \* the heartbeat was sent (L547-548)
    /\ svcRun' = [svcRun EXCEPT ![b] = FALSE]
    /\ actorPc' = [actorPc EXCEPT ![b] = "cleanup"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, stopped, hasBp, bpReg,
                   inSvc, active, cmdQ, cpVars, workVars, targetVars>>

\* BPSA L686 / L931 loop condition fails (T1 DN L2545, T2 DN L2743, a stop,
\* or the command processor's finally L1420); L939 EXITED; L943-945 cleanUp().
ActorLoopExit(b) ==
    /\ actorPc[b] = "run"
    /\ ~ShouldRun(b)
    /\ actorPc' = [actorPc EXCEPT ![b] = "cleanup"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, svcRun, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, cpVars, workVars, targetVars>>

-----------------------------------------------------------------------------
(* Actor exit = the unpublish: BPSA.cleanUp L648-654 -> BPOS.shutdownActor *)
(* L476-491 -> DN.shutdownBlockPool L2151-2172, all inside the BPOS write  *)
(* lock.  Split at every write a lock-free or differently-locked reader    *)
(* can see (brief sec. 3.1).                                               *)

ActorCleanUp(b) ==
    /\ actorPc[b] = "cleanup"
    /\ svcRun' = [svcRun EXCEPT ![b] = FALSE]        \* BPSA L650 (read lock-free at L1428)
    \* L651-652 close the NN proxies; L653 bpos.shutdownActor(this)
    /\ actorPc' = [actorPc EXCEPT ![b] = "shutActor"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, stopped, hasBp, bpReg,
                   inSvc, active, cmdQ, cpVars, workVars, targetVars>>

ShutdownActor(b) ==
    /\ actorPc[b] = "shutActor"
    \* BPOS L477 writeLock (CPReadActive is one atomic step, so never holds it)
    /\ active' = [active EXCEPT ![b] = FALSE]        \* L479-481
    /\ inSvc' = [inSvc EXCEPT ![b] = FALSE]          \* L483 (read lock-free by the L673 assert)
    \* L485 bpServices.isEmpty(): one actor per BPOS -> L486 dn.shutdownBlockPool(this)
    /\ actorPc' = [actorPc EXCEPT ![b] = "unpubRemove"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, svcRun, stopped, hasBp,
                   bpReg, cmdQ, cpVars, workVars, targetVars>>

\* DN L2152 blockPoolManager.remove(bpos): BPM L89-111 (synchronized).
UnpubMapRemove(b) ==
    /\ actorPc[b] = "unpubRemove"
    /\ offerSvcs' = offerSvcs \ {b}                  \* BPM L90
    \* BPM L91-95: remove BY KEY when t.hasBlockPoolId(), with no check that the
    \* stored value is t (brief CR-1, Scenario 4).  L97-110 bpByNameserviceId
    \* is removed by identity (not modeled).
    /\ bpMap' = IF hasBp[b] THEN NoBpos ELSE bpMap
    \* DN L2153 if (bpos.hasBlockPoolId()): otherwise nothing else; BPOS L488-490
    \* unlock; cleanUp returns and the actor thread ends
    /\ actorPc' = [actorPc EXCEPT ![b] = IF hasBp[b] THEN "unpubGate" ELSE "exited"]
    /\ UNCHANGED <<dataVars, dnVars, scanVars, svcRun, stopped, hasBp, bpReg,
                   inSvc, active, cmdQ, cpVars, workVars, targetVars>>

\* DN L2159-2161: hasAnyRegisteredScanner() is synchronized on BlockScanner
\* (BSc L221), so it waits while removeAllVolumeScanners joins the scanners
\* (BSc L294-303): the window stretch of Scenario 2.
UnpubGate(b) ==
    /\ actorPc[b] = "unpubGate"
    /\ ~BsMonitorHeld
    \* L2160 disableBlockPoolId -> BSc L322-327 -> VS L764-781 drops P's iterator
    /\ vsPoolEnabled' = IF HasAnyRegisteredScanner THEN FALSE ELSE vsPoolEnabled
    /\ actorPc' = [actorPc EXCEPT ![b] = "unpubDataset"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanPhase, vsSuspect, dirScanUp, svcRun,
                   stopped, hasBp, bpReg, inSvc, active, cmdQ, cpVars, workVars,
                   targetVars>>

\* DN L2163-2165 data.shutdownBlockPool(P): FSD L3326-3334 under the BP write
\* lock; L3331 volumeMap.cleanUpBlockPool, L3332 volumes.removeBlockPool.
UnpubDataset(b) ==
    /\ actorPc[b] = "unpubDataset"
    /\ dsHasPool' = FALSE
    /\ actorPc' = [actorPc EXCEPT ![b] = "unpubStorage"]
    /\ UNCHANGED <<regVars, storHasPool, metaCorrupt, dnVars, scanVars, svcRun, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, cpVars, workVars, targetVars>>

\* DN L2167-2169 storage.removeBlockPoolStorage(P): DS L1421-1423 (synchronized).
UnpubStorage(b) ==
    /\ actorPc[b] = "unpubStorage"
    /\ storHasPool' = FALSE
    \* BPOS L488-490 writeUnlock; cleanUp returns; BPSA.run returns
    /\ actorPc' = [actorPc EXCEPT ![b] = "exited"]
    /\ UNCHANGED <<regVars, dsHasPool, metaCorrupt, dnVars, scanVars, svcRun, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, cpVars, workVars, targetVars>>

\* BPSA.stop L622-633: shouldServiceRun = false; interrupt the actor thread
\* (L627-629) and the command processor (L630-632).  Called from
\* BPOS.stop L358-362 for each actor still in bpServices, by
\* BPM.shutDownAll (DN L2664, BPM L113-116) or refresh step 4 (BPM L246-249).
StopEffect(b) ==
    /\ svcRun' = [svcRun EXCEPT ![b] = FALSE]
    /\ stopped' = [stopped EXCEPT ![b] = TRUE]

-----------------------------------------------------------------------------
(* Command processor: BPSA.CommandProcessingThread L1400-1525             *)

CPCheck(b) ==
    /\ cpc[b] = "check"
    /\ IF ShouldRun(b)                                \* L1428
         THEN /\ cpc' = [cpc EXCEPT ![b] = "take"]
              /\ UNCHANGED <<svcRun, cmdQ>>
         ELSE \* L1443-1444 queue.clear(); work() finally L1418-1421
              /\ cmdQ' = [cmdQ EXCEPT ![b] = <<>>]
              /\ svcRun' = [svcRun EXCEPT ![b] = FALSE]
              /\ cpc' = [cpc EXCEPT ![b] = "exited"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, stopped, hasBp,
                   bpReg, inSvc, active, cpBlk, workVars, targetVars>>

\* L1430 queue.take() (blocks while empty); L1431 action.run() ->
\* processCommand L1453-1458 for the batch's one command.
CPTake(b) ==
    /\ cpc[b] = "take"
    /\ ~stopped[b]
    /\ cmdQ[b] # <<>>
    /\ cmdQ' = [cmdQ EXCEPT ![b] = Tail(@)]
    /\ IF Head(cmdQ[b]) = EmptyBatch
         THEN \* L1456 loops over no command; L1483 return true; L1432-1433, L1428
              /\ cpBlk' = [cpBlk EXCEPT ![b] = 0]
              /\ cpc' = [cpc EXCEPT ![b] = "check"]
         ELSE /\ cpBlk' = [cpBlk EXCEPT ![b] = Head(cmdQ[b])]
              /\ cpc' = [cpc EXCEPT ![b] = "assert"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, svcRun, stopped,
                   hasBp, bpReg, inSvc, active, workVars, targetVars>>

\* An interrupt (BPSA.stop L630-632) makes take() throw (L1434); L1436-1440
\* re-interrupt then Thread.interrupted() -> break; L1443-1444; L1418-1421.
CPTakeInterrupted(b) ==
    /\ cpc[b] = "take"
    /\ stopped[b]
    /\ cmdQ' = [cmdQ EXCEPT ![b] = <<>>]
    /\ svcRun' = [svcRun EXCEPT ![b] = FALSE]
    /\ cpc' = [cpc EXCEPT ![b] = "exited"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, stopped, hasBp,
                   bpReg, inSvc, active, cpBlk, workVars, targetVars>>

\* BPOS L673 assert bpServices.contains(actor): a lock-free read of the COW
\* list.  With -ea an AssertionError kills the processor (BPSA L1415-1421).
CPAssert(b) ==
    /\ cpc[b] = "assert"
    /\ IF AssertionsEnabled /\ ~inSvc[b]
         THEN CallerDies(b)
         ELSE /\ cpc' = [cpc EXCEPT ![b] = "readActive"]
              /\ UNCHANGED <<cpBlk, svcRun>>
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, workVars, targetVars>>

\* BPOS L690-698 isActiveActor under the read lock; dispatch outside it (L700-704).
CPReadActive(b) ==
    /\ cpc[b] = "readActive"
    /\ ~WLockHeld(b)                                  \* L692 readLock()
    /\ IF active[b]
         THEN \* L700-701 processCommandFromActive: DNA_TRANSFER L738-743,
              \* EC L809-814; another command has no modeled effect (L744-817)
              IF cpBlk[b] = OtherCmd
              THEN /\ cpc' = [cpc EXCEPT ![b] = "check"]
                   /\ cpBlk' = [cpBlk EXCEPT ![b] = 0]
              ELSE /\ cpc' = [cpc EXCEPT ![b] = IF cpBlk[b] = EcCmd THEN "ecSubmit" ELSE "e1"]
                   /\ UNCHANGED cpBlk
         ELSE \* L702-703 processCommandFromStandby: DNA_TRANSFER and EC are
              \* ignored (L837-848), others have no modeled effect; L853 return
              \* true; BPSA L1432-1433, L1428
              /\ cpc' = [cpc EXCEPT ![b] = "check"]
              /\ cpBlk' = [cpBlk EXCEPT ![b] = 0]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, workVars, targetVars>>

\* BPOS L809-814 -> ECW.processErasureCodingTasks L121-156: submit the
\* reconstruction task (unbounded queue, ECW L109-111); after DN L2659 the
\* submit is rejected and ECW L151-154 catches and logs it.
CPSubmitEC(b) ==
    /\ cpc[b] = "ecSubmit"
    /\ IF ecOpen THEN StartR("ec_task") ELSE UNCHANGED rrep
    /\ cpc' = [cpc EXCEPT ![b] = "check"]             \* BPOS L818; BPSA L1432-1433
    /\ cpBlk' = [cpBlk EXCEPT ![b] = 0]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, lrep, targetVars>>

-----------------------------------------------------------------------------
(* transferBlock DN L2835-2897, run by a command processor (DNA_TRANSFER,  *)
(* BPOS L738-743 -> DN L2899-2910) or by the workload's test thread.       *)

\* Workload W6 (TestDiskError L279): the test thread calls transferBlock
\* directly, without the command path's guards.  No production caller does
\* this (brief X15): TestCallerEnabled is FALSE in every MC configuration.
TestTransferStart ==
    /\ TestCallerEnabled
    /\ cpc[TestCaller] = "idle"
    /\ cpc' = [cpc EXCEPT ![TestCaller] = "e1"]
    /\ cpBlk' = [cpBlk EXCEPT ![TestCaller] = 1]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, workVars, targetVars>>

\* TARGET, entry E1: DN L2838 getBPOSForBlock -> L1835-1838.
TargetCheckE1(c) ==
    /\ cpc[c] = "e1"
    /\ IF bpMap = NoBpos                              \* L1836 BPM.get (BPM L85-87); L1837
         THEN /\ Fire("E1")                           \* L1838 throw new IOException(..)
              /\ AfterBlock(c)                        \* caught at DN L2906-2908
         ELSE /\ cpc' = [cpc EXCEPT ![c] = "reg"]     \* L1841 return bpos
              /\ UNCHANGED <<cpBlk, targetVars>>
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, workVars>>

\* DN L2839 getDNRegistrationForBP -> L2342 noRegistration() hook; L2343 BPM.get;
\* L2344-2345 IOException("cannot find BPOfferService for bpid=") - a sibling check.
TBRegCheck(c) ==
    /\ cpc[c] = "reg"
    /\ IF bpMap = NoBpos \/ ~bpReg[bpMap]
         THEN AfterBlock(c)
         ELSE /\ cpc' = [cpc EXCEPT ![c] = "ckblk"]
              /\ UNCHANGED cpBlk
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, workVars, targetVars>>

\* DN L2846-2882 data.checkBlock(block, numBytes, FINALIZED): a volumeMap
\* lookup.  The workload's corruption is in the meta file only, so the
\* block-file checks pass.
TBCheckBlock(c) ==
    /\ cpc[c] = "ckblk"
    /\ IF ~dsHasPool
         THEN AfterBlock(c)      \* L2848-2849 ReplicaNotFoundException; L2863-2867 return
         ELSE /\ cpc' = [cpc EXCEPT ![c] = "ctor"]
              /\ UNCHANGED cpBlk
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, workVars, targetVars>>

\* DN L2884-2893 -> DataTransfer ctor L3023-3048: L3038 BPM.get, L3039
\* bpos.bpRegistration with no null check (brief TV-1).
TBCtor(c) ==
    /\ cpc[c] = "ctor"
    /\ IF bpMap = NoBpos
         THEN CallerDies(c)                           \* NullPointerException
         ELSE /\ cpc' = [cpc EXCEPT ![c] = "exec"]
              /\ UNCHANGED <<cpBlk, svcRun>>
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, workVars, targetVars>>

\* DN L2895 xferService.execute(dataTransferTask).
TBExecute(c) ==
    /\ cpc[c] = "exec"
    /\ IF xferOpen
         THEN /\ StartL("xf", "xf_send")              \* DataTransfer.run on an xfer thread
              /\ AfterBlock(c)
              /\ UNCHANGED svcRun
         ELSE \* after DN L2601: RejectedExecutionException (AbortPolicy)
              /\ CallerDies(c)
              /\ UNCHANGED lrep
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, stopped, hasBp,
                   bpReg, inSvc, active, cmdQ, rrep, targetVars>>

-----------------------------------------------------------------------------
(* Local bad-block reporters (Scenario 2, entry E2)                        *)

\* DataTransfer.run DN L3054-3092: connect, SASL, new BlockSender (L3092):
\* BS L261 / L504-509 replica lookup, then BS L342 -> BMH L189-192 header.
XferSend(i) ==
    /\ lrep[i].pc = "xf_send"
    /\ LTo(i, IF ~dsHasPool THEN "none"   \* ReplicaNotFoundException -> L3131-3132
                                          \* handleBadBlock: not a bad block (L4110-4114)
              ELSE IF metaCorrupt
                   THEN "hbb"             \* CorruptMetaHeaderException -> L3131-3132
                                          \* handleBadBlock(b, ie, false)
                   ELSE "none")           \* L3099-3130 transfer completes
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* Environment: a client read of P's replica (DataXceiver.readBlock).  The
\* xceiver server must accept it (DN L2551-2568), and DX L594-597 checkAccess ->
\* checkAndWaitForBP DX L1401-1434 needs a mapped, registered BPOS
\* (DN L2340-2348); otherwise it waits and fails "Not ready to serve the
\* block pool" (DX L1433), a sibling check.
ClientReadStart ==
    /\ xcAccept
    /\ bpMap # NoBpos
    /\ bpReg[bpMap]
    /\ StartL("rd", "rd_reg")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* DX L599-600 getDNRegistrationForBP again, before the try at L606: a
\* failure propagates without handleBadBlock.
ReadReg(i) ==
    /\ lrep[i].pc = "rd_reg"
    /\ LTo(i, IF bpMap = NoBpos \/ ~bpReg[bpMap] THEN "none" ELSE "rd_send")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* DX L606-615 new BlockSender; an IOException is rethrown (L612-615) and
\* reaches DX L655-669 handleBadBlock(block, ioe, false).
ReadSend(i) ==
    /\ lrep[i].pc = "rd_send"
    /\ LTo(i, IF ~dsHasPool THEN "none"         \* ReplicaNotFoundException: not bad
              ELSE IF metaCorrupt THEN "hbb"    \* CorruptMetaHeaderException
              ELSE "none")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* DN L4108-4130 handleBadBlock(block, e, fromScanner = false) with a
\* CorruptMetaHeaderException (isBadBlock, L4110-4111).
HandleBadBlock(i) ==
    /\ lrep[i].pc = "hbb"
    /\ IF ScannerEnabled                              \* L4116 blockScanner.isEnabled()
         THEN \* L4117 data.getVolume(block) (FSD L191-198): null -> L4118-4120 return;
              \* else L4122 markSuspectBlock (BSc L357-374, synchronized; a mock
              \* records the call) -> VS L705-722 queues the block
              /\ (Scanner = "real" /\ dsHasPool) => ~BsMonitorHeld
              /\ LTo(i, "none")
              /\ vsSuspect' = IF dsHasPool /\ Scanner = "real" /\ scanPhase = "run"
                              THEN TRUE ELSE vsSuspect
         ELSE /\ LTo(i, "getvol")                      \* L4123-4125 reportBadBlocks(block)
              /\ UNCHANGED vsSuspect
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanPhase, vsPoolEnabled, dirScanUp,
                   actorVars, cpVars, rrep, targetVars>>

\* A VolumeScanner scans P's suspect block (VS run loop; queued at L705-722).
VSScanSuspect ==
    /\ Scanner = "real"
    /\ scanPhase = "run"                              \* VS L697-702 stopping ends the loop
    /\ ~VSBusy
    /\ vsSuspect
    /\ vsSuspect' = FALSE
    /\ StartL("vs", "vs_send")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanPhase, vsPoolEnabled, dirScanUp,
                   actorVars, cpVars, rrep, targetVars>>

\* Environment: a periodic VolumeScanner pass reaches P's replica (P's block
\* iterator exists from DN L2209 until L2160).
VSScanPeriodic ==
    /\ Scanner = "real"
    /\ scanPhase = "run"
    /\ vsPoolEnabled
    /\ ~VSBusy
    /\ StartL("vs", "vs_send")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* VS scanBlock L417-458: L423 getStoredBlock and L444 new BlockSender both
\* look the replica up in the volumeMap.  A release before either one ends
\* the scan without a report (L425-439 return -1 / L452-453 handle -> L280
\* contains FALSE), so
\* the two lookups are one step here.  An interrupt from VS.shutdown stops
\* sendBlock quietly (handle(block, null)); the header check runs in the
\* BlockSender constructor before any interruptible read.
VSScanBlock(i) ==
    /\ lrep[i].pc = "vs_send"
    /\ LTo(i, IF ~dsHasPool THEN "none"
              ELSE IF metaCorrupt THEN "vs_contains"     \* L452-453 handle(block, e)
              ELSE "none")                               \* L449 handle(block, null)
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* VS ScanResultHandler.handle L273-299.
VSContains(i) ==
    /\ lrep[i].pc = "vs_contains"
    \* L280 dataset.contains(block) (FSD L2652-2659, BP read lock): FALSE ->
    \* L280-284 return.  Else L288-293 (not FileNotFoundException) and
    \* L297-298 handleBadBlock(block, e, true): fromScanner -> DN L4123-4125
    \* reportBadBlocks(block)
    /\ LTo(i, IF dsHasPool THEN "getvol" ELSE "none")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* Environment: DirectoryScanner.reconcile (DSc L474-494) found a diff for P's
\* replica that checkAndUpdate flags (an on-disk length that differs from the
\* in-memory length, or a non-regular block/meta file, FSD L2964-2983).
\* DN L1604 shutdownDirectoryScanner stops later runs.
DirScanStart ==
    /\ dirScanUp
    /\ scanPhase = "run"
    /\ ~DSBusy
    /\ StartL("ds", "ds_locked")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* FSD checkAndUpdate L2765-2984 under the DIR write lock, which takes the BP
\* read lock first (DataSetLockManager L203-206).
DirScanCheckAndUpdate(i) ==
    /\ lrep[i].pc = "ds_locked"
    \* L2786 memBlockInfo = volumeMap.get(bpid, blockId).  Absent: the on-disk
    \* replica is re-added (FSD L2860-2869, brief TV-3, not modeled), no report.
    \* Present and flagged: L2964-2983 corruptBlock; L2990-2996 report OUTSIDE
    \* the lock with no getVolume pre-check -> DN L1795-1797
    /\ LTo(i, IF dsHasPool THEN "e2" ELSE "none")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* DN L1778-1784 reportBadBlocks(block): L1779 getFSDataset().getVolume(block)
\* (FSD L191-198, BP read lock).
GetVolume(i) ==
    /\ lrep[i].pc = "getvol"
    /\ LTo(i, IF dsHasPool THEN "e2"     \* L1784 reportBadBlocks(block, volume)
              ELSE "none")               \* L1780-1783 "Cannot find FsVolumeSpi"
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep, targetVars>>

\* TARGET, entry E2: DN L1797 getBPOSForBlock -> L1835-1838.  The IOException
\* is caught at DN L4126-4127 (handleBadBlock) or FSD L2997-3000.
TargetCheckE2(i) ==
    /\ lrep[i].pc = "e2"
    /\ IF bpMap = NoBpos
         THEN Fire("E2")
         ELSE UNCHANGED targetVars       \* L1798-1799 bpos.reportBadBlocks (BPOS L292-299)
    /\ LTo(i, "none")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, rrep>>

-----------------------------------------------------------------------------
(* Remote-corruption reporters (Scenario 3, entry E3)                      *)

\* Environment: a peer DN writes a replica of P to this DN (DNA_TRANSFER or
\* EC writer; clientname "" -> isDatanode, DX L702).  DX L731 checkAccess ->
\* checkAndWaitForBP (DX L1401-1434).
RecvStart ==
    /\ xcAccept
    /\ bpMap # NoBpos
    /\ bpReg[bpMap]
    /\ StartR("rc_create")
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, lrep, targetVars>>

\* DX L777 getBlockReceiver -> BR L215-217 createTemporary: needs P in the
\* dataset's volumes (FSV L562-567), else the op fails.
RecvCreate(i) ==
    /\ rrep[i] = "rc_create"
    /\ rrep' = [rrep EXCEPT ![i] = IF dsHasPool THEN "rc_active" ELSE "none"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, lrep, targetVars>>

\* Environment: the next packet's data does not match its CRC.  BR
\* receivePacket -> verifyChunks L494-498 ChecksumException (shouldVerifyChecksum
\* is TRUE for isDatanode, BR L544-546).  After DN L2612 the thread is
\* interrupted and the next packet read fails, so no new packet arrives.
RecvCorruptPacket(i) ==
    /\ rrep[i] = "rc_active"
    /\ ~xcIntr
    /\ rrep' = [rrep EXCEPT ![i] = "rc_report"]       \* BR L507 srcDataNode != null && isDatanode
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, lrep, targetVars>>

\* The receiver ends without a report: clean packets up to finalizeBlock
\* (BR L1038 -> FSD L2002-2010; fails if P was released), a socket error, or
\* the interrupt from DN L2612.
RecvEnd(i) ==
    /\ rrep[i] = "rc_active"
    /\ rrep' = [rrep EXCEPT ![i] = "none"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, lrep, targetVars>>

\* Environment: a read round of the reconstruction meets a corrupt source:
\* StripedBlockReader L176-180 ChecksumException -> corruptedBlocks; SR
\* readMinimumSources L267-275 reports them in a finally.  No pool check on
\* the EC path (brief S3).
ECCorruptRound(i) ==
    /\ rrep[i] = "ec_task"
    /\ rrep' = [rrep EXCEPT ![i] = "ec_report"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, lrep, targetVars>>

\* The reconstruction finishes with clean rounds only (reportCorruptedBlocks
\* loops over an empty map, DN L1818-1825: brief X12).
ECTaskEnd(i) ==
    /\ rrep[i] = "ec_task"
    /\ rrep' = [rrep EXCEPT ![i] = "none"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, lrep, targetVars>>

\* TARGET, entry E3: BR L511 / SR L273 -> DN L1814-1822 -> L1808-1810
\* getBPOSForBlock -> L1835-1838.  Caught at BR L510-515 (then BR L518-519
\* ends the receiver) or by StripedBlockReconstructor L69-71 (task aborted).
TargetCheckE3(i) ==
    /\ rrep[i] \in {"rc_report", "ec_report"}
    /\ IF bpMap = NoBpos
         THEN Fire("E3")
         ELSE UNCHANGED targetVars       \* L1811 bpos.reportRemoteBadBlock (BPOS L517-526)
    /\ rrep' = [rrep EXCEPT ![i] = "none"]
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorVars, cpVars, lrep>>

-----------------------------------------------------------------------------
(* Unpublish triggers that run outside the actor                           *)

\* Fault T1: DataNode.shutdown() L2527-2546 (admin shutdownDatanode DN
\* L3848-3876, MiniDFSCluster teardown): shouldRun = false first (L2544-2546).
DNShutdownBegin ==
    /\ shPc = "none"
    /\ dnShouldRun' = FALSE
    /\ shPc' = "killXceiver"
    /\ UNCHANGED <<regVars, dataVars, xferOpen, xcAccept, xcIntr, ecOpen, refreshPc,
                   scanVars, actorVars, cpVars, workVars, targetVars>>

\* DN L2551-2568 kill + interrupt both xceiver servers: no new xceiver ops.
ShutdownXceiverServer ==
    /\ shPc = "killXceiver"
    /\ xcAccept' = FALSE
    /\ shPc' = "scanners"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, xferOpen, xcIntr, ecOpen, refreshPc,
                   scanVars, actorVars, cpVars, workVars, targetVars>>

\* DN L2571 -> L1603-1606: L1604 shutdownDirectoryScanner; L1605
\* removeAllVolumeScanners (BSc L294-297 synchronized: VS.shutdown each,
\* VS L697-702 stopping + interrupt), then the joins below.
ShutdownScannersBegin ==
    /\ shPc = "scanners"
    /\ scanPhase' = "stopping"
    /\ shPc' = "scannersJoin"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, xferOpen, xcAccept, xcIntr, ecOpen,
                   refreshPc, vsPoolEnabled, vsSuspect, dirScanUp, actorVars, cpVars,
                   workVars, targetVars>>

\* BSc L298-302 joinUninterruptibly each scanner with a timeout, clear the
\* map, release the monitor.  A scanner that outlives the timeout keeps
\* running, so in-flight scans are not forced to finish first.
ShutdownScannersEnd ==
    /\ shPc = "scannersJoin"
    /\ scanPhase' = "cleared"
    /\ shPc' = "xfer"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, xferOpen, xcAccept, xcIntr, ecOpen,
                   refreshPc, vsPoolEnabled, vsSuspect, dirScanUp, actorVars, cpVars,
                   workVars, targetVars>>

\* DN L2583-2601: checkers, L2595 shouldRun = false (again), L2598, then
\* L2601 HadoopExecutors.shutdown(xferService): later execute() is rejected;
\* running DataTransfer tasks continue (awaitTermination, then shutdownNow;
\* an interrupt can only end a task before its report).
ShutdownXferService ==
    /\ shPc = "xfer"
    /\ xferOpen' = FALSE
    /\ shPc' = "interrupt"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, xcAccept, xcIntr, ecOpen, refreshPc,
                   scanVars, actorVars, cpVars, workVars, targetVars>>

\* DN L2603-2629: not for upgrade -> L2612 threadGroup.interrupt() at once,
\* without waiting.  The group is "dataXceiverServer" (DN L1682): xceivers
\* only, not the command processor (BPSA L1405) or EC pool threads.
ShutdownInterruptXceivers ==
    /\ shPc = "interrupt"
    /\ xcIntr' = TRUE
    /\ shPc' = "ec"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, xferOpen, xcAccept, ecOpen, refreshPc,
                   scanVars, actorVars, cpVars, workVars, targetVars>>

\* DN L2630-2660: join the xceiver servers, L2655 ipcServer.stop, L2659
\* ecWorker.shutDown (ECW L167-170: plain shutdown(); queued tasks still run).
ShutdownEC ==
    /\ shPc = "ec"
    /\ ecOpen' = FALSE
    /\ shPc' = "stopAll"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, xferOpen, xcAccept, xcIntr, refreshPc,
                   scanVars, actorVars, cpVars, workVars, targetVars>>

\* DN L2664 -> BPM L113-116 shutDownAll: bposArray is a live view of the COW
\* offerServices (DN L2540-2542, BPM L81-83), so a BPOS whose last actor
\* already exited is skipped; BPOS.stop L358-362 reaches only actors still in
\* bpServices (brief TV-2).
ShutdownStopActor(b) ==
    /\ shPc = "stopAll"
    /\ b \in offerSvcs
    /\ inSvc[b]
    /\ ~stopped[b]
    /\ StopEffect(b)
    /\ UNCHANGED <<regVars, dataVars, dnVars, scanVars, actorPc, hasBp, bpReg, inSvc,
                   active, cmdQ, cpVars, workVars, targetVars>>

\* End of the stop loop (BPM L117).  The joins (BPM L118-120) and the rest of
\* shutdown (DN L2670-2699: unlockAll, data.shutdown(), which keeps the
\* volumeMap) write nothing this model reads.
ShutdownStopAllDone ==
    /\ shPc = "stopAll"
    /\ \A b \in offerSvcs : inSvc[b] => stopped[b]
    /\ shPc' = "done"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, xferOpen, xcAccept, xcIntr, ecOpen,
                   refreshPc, scanVars, actorVars, cpVars, workVars, targetVars>>

\* Fault T2: a volume failure beyond the tolerated count (DN L2706-2717 ->
\* handleVolumeFailures -> handleDiskError L2720-2744): shouldRun = false at
\* L2743 and shutdown() is never called.  The reported replica is assumed to
\* sit on a healthy volume (brief sec. 3.1: no other side effect).
DiskFail ==
    /\ dnShouldRun
    /\ dnShouldRun' = FALSE
    /\ UNCHANGED <<regVars, dataVars, shPc, xferOpen, xcAccept, xcIntr, ecOpen, refreshPc,
                   scanVars, actorVars, cpVars, workVars, targetVars>>

\* Fault T5 / Scenario 4: dfsadmin -refreshNamenodes after adding
\* dfs.nameservices=ns1 for the same NN (Federation.md L158-177; without it the
\* key is null, DFSUtilClient L402-407).  BPM L185-237 under the BPM monitor:
\* toAdd = {ns1}, toRemove = {null}; createBPOS(ns1) (BPOS ctor L127-143 ->
\* BPSA ctor L159-160 starts the new command processor); L232-233 register it;
\* L236 startAll starts the new actor (the old one is alive: BPSA L600-603).
RefreshStart(n) ==
    /\ refreshPc = "idle"
    /\ n \in NewBs
    /\ actorPc[n] = "new"
    /\ offerSvcs' = offerSvcs \cup {n}
    /\ inSvc' = [inSvc EXCEPT ![n] = TRUE]
    /\ actorPc' = [actorPc EXCEPT ![n] = "hs"]
    /\ cpc' = [cpc EXCEPT ![n] = "check"]
    /\ refreshPc' = "stopOld"
    /\ UNCHANGED <<bpMap, dataVars, dnShouldRun, shPc, xferOpen, xcAccept, xcIntr, ecOpen,
                   scanVars, svcRun, stopped, hasBp, bpReg, active, cmdQ, cpBlk,
                   workVars, targetVars>>

\* Step 4, outside the BPM monitor (BPM L239-252): the old BPOS's stop()
\* (BPOS L358-362 -> BPSA L622-633), then join.  "They will call remove on
\* their own" (L250): the old actor's exit runs UnpubMapRemove by key.
RefreshStopOld ==
    /\ refreshPc = "stopOld"
    /\ IF inSvc[OldB] /\ ~stopped[OldB]
         THEN StopEffect(OldB)
         ELSE UNCHANGED <<svcRun, stopped>>          \* stop() finds no actor
    /\ refreshPc' = "done"
    /\ UNCHANGED <<regVars, dataVars, dnShouldRun, shPc, xferOpen, xcAccept, xcIntr,
                   ecOpen, scanVars, actorPc, hasBp, bpReg, inSvc, active, cmdQ,
                   cpVars, workVars, targetVars>>

-----------------------------------------------------------------------------
(* Workload fixture                                                        *)

\* TestDiskError L258-263: the test overwrites the replica's meta header
\* (type and bytesPerChecksum = 0).  It does so after L257
\* DFSTestUtil.getFirstBlock, which reads one byte of the replica
\* (DFSTestUtil L847-851: a real readBlock with a clean header).  Not part of
\* Next: Trace.tla replays it, and the MC configurations start from its
\* result (HeaderCorrupt = TRUE), which keeps every report it enables.
FixtureCorruptHeader ==
    /\ ~metaCorrupt
    /\ metaCorrupt' = TRUE
    /\ UNCHANGED <<regVars, dsHasPool, storHasPool, dnVars, scanVars, actorVars,
                   cpVars, workVars, targetVars>>

-----------------------------------------------------------------------------
(* The target and the system                                               *)

TargetCheck ==
    \/ \E c \in Callers : TargetCheckE1(c)
    \/ \E i \in LSlot : TargetCheckE2(i)
    \/ \E i \in RSlot : TargetCheckE3(i)

\* A state in which some thread is about to evaluate DN L1836.
TargetCheckEnabled ==
    \/ \E c \in Callers : cpc[c] = "e1"
    \/ \E i \in LSlot : lrep[i].pc = "e2"
    \/ \E i \in RSlot : rrep[i] \in {"rc_report", "ec_report"}

ActorNext(b) ==
    \/ ActorHandshakePut(b) \/ ActorInitStorage(b) \/ ActorAddDataset(b)
    \/ ActorRegister(b) \/ ActorIterStart(b) \/ ActorIterEnd(b)
    \/ \E k \in 1..MaxBlocks : ActorHeartbeatTransfer(b, k)
    \/ ActorHeartbeatEC(b) \/ (\E e \in {OtherCmd, EmptyBatch} : ActorEnqueueOther(b, e))
    \/ ActorHeartbeatRejected(b) \/ ActorLoopExit(b)
    \/ ActorCleanUp(b) \/ ShutdownActor(b) \/ UnpubMapRemove(b) \/ UnpubGate(b)
    \/ UnpubDataset(b) \/ UnpubStorage(b)

CPNext(b) ==
    \/ CPCheck(b) \/ CPTake(b) \/ CPTakeInterrupted(b) \/ CPAssert(b)
    \/ CPReadActive(b) \/ CPSubmitEC(b)

TBNext(c) ==
    \/ TargetCheckE1(c) \/ TBRegCheck(c) \/ TBCheckBlock(c) \/ TBCtor(c)
    \/ TBExecute(c)

LocalNext(i) ==
    \/ XferSend(i) \/ ReadReg(i) \/ ReadSend(i) \/ HandleBadBlock(i)
    \/ VSScanBlock(i) \/ VSContains(i) \/ DirScanCheckAndUpdate(i)
    \/ GetVolume(i) \/ TargetCheckE2(i)

RemoteNext(i) ==
    \/ RecvCreate(i) \/ RecvCorruptPacket(i) \/ RecvEnd(i)
    \/ ECCorruptRound(i) \/ ECTaskEnd(i) \/ TargetCheckE3(i)

DNNext ==
    \/ DNShutdownBegin \/ ShutdownXceiverServer \/ ShutdownScannersBegin
    \/ ShutdownScannersEnd \/ ShutdownXferService \/ ShutdownInterruptXceivers
    \/ ShutdownEC \/ (\E b \in Bpos : ShutdownStopActor(b)) \/ ShutdownStopAllDone
    \/ DiskFail \/ (\E n \in NewBs : RefreshStart(n)) \/ RefreshStopOld

EnvNext ==
    \/ TestTransferStart \/ ClientReadStart \/ VSScanSuspect \/ VSScanPeriodic
    \/ DirScanStart \/ RecvStart

Next ==
    \/ \E b \in Bpos : ActorNext(b) \/ CPNext(b)
    \/ \E c \in Callers : TBNext(c)
    \/ \E i \in LSlot : LocalNext(i)
    \/ \E i \in RSlot : RemoteNext(i)
    \/ DNNext
    \/ EnvNext

Spec == Init /\ [][Next]_vars

\* State constraint for base.cfg only: keeps one reporter slot free (so the
\* unbounded environment never trips the StartL/StartR overflow Assert) and
\* the command queue short.  MC.tla bounds the environment with counters.
BaseConstraint ==
    /\ FreeL # {}
    /\ FreeR # {}
    /\ \A b \in Bpos : Len(cmdQ[b]) <= 1

-----------------------------------------------------------------------------
(* Properties                                                              *)

\* The ad hoc target property: the check never fails.
TargetSafe == ~targetFired

TypeOK ==
    /\ bpMap \in Bpos \cup {NoBpos}
    /\ offerSvcs \subseteq Bpos
    /\ dsHasPool \in BOOLEAN /\ storHasPool \in BOOLEAN /\ metaCorrupt \in BOOLEAN
    /\ dnShouldRun \in BOOLEAN
    /\ shPc \in ShPcs
    /\ xferOpen \in BOOLEAN /\ xcAccept \in BOOLEAN /\ xcIntr \in BOOLEAN
    /\ ecOpen \in BOOLEAN
    /\ refreshPc \in {"idle", "stopOld", "done"}
    /\ scanPhase \in {"run", "stopping", "cleared"}
    /\ vsPoolEnabled \in BOOLEAN /\ vsSuspect \in BOOLEAN /\ dirScanUp \in BOOLEAN
    /\ actorPc \in [Bpos -> ActorPcs]
    /\ svcRun \in [Bpos -> BOOLEAN] /\ stopped \in [Bpos -> BOOLEAN]
    /\ hasBp \in [Bpos -> BOOLEAN] /\ bpReg \in [Bpos -> BOOLEAN]
    /\ inSvc \in [Bpos -> BOOLEAN] /\ active \in [Bpos -> BOOLEAN]
    /\ \A b \in Bpos : cmdQ[b] \in Seq(CmdVals)
    /\ cpc \in [Callers -> CallerPcs]
    /\ cpBlk \in [Callers -> CmdVals]
    /\ lrep \in [LSlot -> [k : {"none", "xf", "rd", "vs", "ds"}, pc : LRepPcs]]
    /\ \A i \in LSlot : (lrep[i].k = "none") <=> (lrep[i].pc = "none")
    /\ rrep \in [RSlot -> RRepPcs]
    /\ targetFired \in BOOLEAN
    /\ targetEntry \in {"none", "E1", "E2", "E3"}

\* Structural sanity (brief sec. 5, TransferFromRunningActor): commands are
\* enqueued only by an actor's heartbeat inside offerService (BPSA L745-756),
\* which runs only after register() succeeded (BPSA L324, L871 -> BPOS L432;
\* bpRegistration is never reset), so a queued or in-process command implies
\* its BPOS registered.  The pool is always P and the heartbeat needed P in
\* the dataset (BPSA L547-548).
TransferFromRegisteredActor ==
    \A b \in Bpos :
        (cmdQ[b] # <<>> \/ cpc[b] \in {"assert", "readActive", "ecSubmit", "e1",
                                       "reg", "ckblk", "ctor", "exec"})
            => bpReg[b]

=============================================================================
