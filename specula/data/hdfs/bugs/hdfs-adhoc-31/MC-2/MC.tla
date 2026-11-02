--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-31).                    *)
(*                                                                         *)
(* Bounded: actions that introduce nondeterminism, i.e. the unpublish      *)
(* triggers (faults T1, T2, T3, T5) and the environment's work (NameNode   *)
(* commands, client reads, scanner passes, peer writes, corrupt data).     *)
(* Not bounded: every reactive step of a DataNode thread.                  *)
(*                                                                         *)
(* Each MC disjunct is a named wrapper so TLC labels counterexample steps  *)
(* with the action name; the stop-after-target rule is a CONSTRAINT        *)
(* (StopAfterTarget), not a conjunct of MCNext.                            *)
(*                                                                         *)
(* No SYMMETRY: the BPOS objects play distinct roles ("O" old, "N" new) and *)
(* reporter slots are allocated deterministically (lowest free slot).      *)
(* No VIEW: dropping the counters from the view would merge states with    *)
(* different remaining fault budgets, and the hunts are small (< 100k      *)
(* distinct states each).                                                  *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxShutdown,    \* T1 DataNode.shutdown() (DN L2527)
    MaxDiskFail,    \* T2 handleDiskError -> shouldRun = false (DN L2743)
    MaxNNReject,    \* T3 heartbeat RemoteException (BPSA L791-798)
    MaxRefresh,     \* T5 refreshNamenodes re-home (BPM L148-252)
    MaxXferCmd,     \* NameNode DNA_TRANSFER commands (BPSA L745-756)
    MaxEcCmd,       \* NameNode EC reconstruction commands (BPOS L809-814)
    MaxClientRead,  \* client readBlock ops on P's replica (DX L594)
    MaxVScan,       \* periodic VolumeScanner passes over P's replica
    MaxDirScan,     \* DirectoryScanner reconciles that flag P's replica (FSD L2964-2983)
    MaxRecv,        \* peer DataNode writes of a replica of P to this DN (DX L681)
    MaxCorruptPkt,  \* corrupt packets / corrupt EC source rounds (BR L497, SR L267-275)
    MaxOtherCmd     \* untracked command batches (block-report results, ...); 0 in every hunt

VARIABLE fc

mcVars == <<vars, fc>>

FcFields == {"shutdown", "diskFail", "nnReject", "refresh", "xferCmd", "ecCmd",
             "clientRead", "vscan", "dirScan", "recv", "corruptPkt", "otherCmd"}

MCInit ==
    /\ Init
    /\ fc = [f \in FcFields |-> 0]

Bump(f) == fc' = [fc EXCEPT ![f] = @ + 1]

-----------------------------------------------------------------------------
(* Bounded: fault injection (unpublish triggers)                           *)

MCDNShutdownBegin ==
    /\ fc["shutdown"] < MaxShutdown /\ DNShutdownBegin /\ Bump("shutdown")
MCDiskFail ==
    /\ fc["diskFail"] < MaxDiskFail /\ DiskFail /\ Bump("diskFail")
MCActorHeartbeatRejected(b) ==
    /\ fc["nnReject"] < MaxNNReject /\ ActorHeartbeatRejected(b) /\ Bump("nnReject")
MCRefreshStart(n) ==
    /\ fc["refresh"] < MaxRefresh /\ RefreshStart(n) /\ Bump("refresh")

(* Bounded: environment work                                               *)

MCActorHeartbeatTransfer(b, k) ==
    /\ fc["xferCmd"] < MaxXferCmd /\ ActorHeartbeatTransfer(b, k) /\ Bump("xferCmd")
MCActorHeartbeatEC(b) ==
    /\ fc["ecCmd"] < MaxEcCmd /\ ActorHeartbeatEC(b) /\ Bump("ecCmd")
MCActorEnqueueOther(b, e) ==
    /\ fc["otherCmd"] < MaxOtherCmd /\ ActorEnqueueOther(b, e) /\ Bump("otherCmd")
MCClientReadStart ==
    /\ fc["clientRead"] < MaxClientRead /\ ClientReadStart /\ Bump("clientRead")
MCVSScanPeriodic ==
    /\ fc["vscan"] < MaxVScan /\ VSScanPeriodic /\ Bump("vscan")
MCDirScanStart ==
    /\ fc["dirScan"] < MaxDirScan /\ DirScanStart /\ Bump("dirScan")
MCRecvStart ==
    /\ fc["recv"] < MaxRecv /\ RecvStart /\ Bump("recv")
MCRecvCorruptPacket(i) ==
    /\ fc["corruptPkt"] < MaxCorruptPkt /\ RecvCorruptPacket(i) /\ Bump("corruptPkt")
MCECCorruptRound(i) ==
    /\ fc["corruptPkt"] < MaxCorruptPkt /\ ECCorruptRound(i) /\ Bump("corruptPkt")

-----------------------------------------------------------------------------
(* Unbounded reactive steps (named wrappers, counters unchanged)           *)

MCActorHandshakePut(b)     == ActorHandshakePut(b) /\ UNCHANGED fc
MCActorInitStorage(b)      == ActorInitStorage(b) /\ UNCHANGED fc
MCActorAddDataset(b)       == ActorAddDataset(b) /\ UNCHANGED fc
MCActorRegister(b)         == ActorRegister(b) /\ UNCHANGED fc
MCActorIterStart(b)        == ActorIterStart(b) /\ UNCHANGED fc
MCActorIterEnd(b)          == ActorIterEnd(b) /\ UNCHANGED fc
MCActorLoopExit(b)         == ActorLoopExit(b) /\ UNCHANGED fc
MCActorCleanUp(b)          == ActorCleanUp(b) /\ UNCHANGED fc
MCShutdownActor(b)         == ShutdownActor(b) /\ UNCHANGED fc
MCUnpubMapRemove(b)        == UnpubMapRemove(b) /\ UNCHANGED fc
MCUnpubGate(b)             == UnpubGate(b) /\ UNCHANGED fc
MCUnpubDataset(b)          == UnpubDataset(b) /\ UNCHANGED fc
MCUnpubStorage(b)          == UnpubStorage(b) /\ UNCHANGED fc
MCCPCheck(b)               == CPCheck(b) /\ UNCHANGED fc
MCCPTake(b)                == CPTake(b) /\ UNCHANGED fc
MCCPTakeInterrupted(b)     == CPTakeInterrupted(b) /\ UNCHANGED fc
MCCPAssert(b)              == CPAssert(b) /\ UNCHANGED fc
MCCPReadActive(b)          == CPReadActive(b) /\ UNCHANGED fc
MCCPSubmitEC(b)            == CPSubmitEC(b) /\ UNCHANGED fc
MCTestTransferStart        == TestTransferStart /\ UNCHANGED fc
MCTargetCheckE1(c)         == TargetCheckE1(c) /\ UNCHANGED fc
MCTBRegCheck(c)            == TBRegCheck(c) /\ UNCHANGED fc
MCTBCheckBlock(c)          == TBCheckBlock(c) /\ UNCHANGED fc
MCTBCtor(c)                == TBCtor(c) /\ UNCHANGED fc
MCTBExecute(c)             == TBExecute(c) /\ UNCHANGED fc
MCXferSend(i)              == XferSend(i) /\ UNCHANGED fc
MCReadReg(i)               == ReadReg(i) /\ UNCHANGED fc
MCReadSend(i)              == ReadSend(i) /\ UNCHANGED fc
MCHandleBadBlock(i)        == HandleBadBlock(i) /\ UNCHANGED fc
MCVSScanSuspect            == VSScanSuspect /\ UNCHANGED fc
MCVSScanBlock(i)           == VSScanBlock(i) /\ UNCHANGED fc
MCVSContains(i)            == VSContains(i) /\ UNCHANGED fc
MCDirScanCheckAndUpdate(i) == DirScanCheckAndUpdate(i) /\ UNCHANGED fc
MCGetVolume(i)             == GetVolume(i) /\ UNCHANGED fc
MCTargetCheckE2(i)         == TargetCheckE2(i) /\ UNCHANGED fc
MCRecvCreate(i)            == RecvCreate(i) /\ UNCHANGED fc
MCRecvEnd(i)               == RecvEnd(i) /\ UNCHANGED fc
MCECTaskEnd(i)             == ECTaskEnd(i) /\ UNCHANGED fc
MCTargetCheckE3(i)         == TargetCheckE3(i) /\ UNCHANGED fc
MCShutdownXceiverServer    == ShutdownXceiverServer /\ UNCHANGED fc
MCShutdownScannersBegin    == ShutdownScannersBegin /\ UNCHANGED fc
MCShutdownScannersEnd      == ShutdownScannersEnd /\ UNCHANGED fc
MCShutdownXferService      == ShutdownXferService /\ UNCHANGED fc
MCShutdownInterruptXceivers == ShutdownInterruptXceivers /\ UNCHANGED fc
MCShutdownEC               == ShutdownEC /\ UNCHANGED fc
MCShutdownStopActor(b)     == ShutdownStopActor(b) /\ UNCHANGED fc
MCShutdownStopAllDone      == ShutdownStopAllDone /\ UNCHANGED fc
MCRefreshStopOld           == RefreshStopOld /\ UNCHANGED fc

MCNext ==
    \* actors (BPSA.run / offerService / cleanUp)
    \/ \E b \in Bpos : MCActorHandshakePut(b)
    \/ \E b \in Bpos : MCActorInitStorage(b)
    \/ \E b \in Bpos : MCActorAddDataset(b)
    \/ \E b \in Bpos : MCActorRegister(b)
    \/ \E b \in Bpos : MCActorIterStart(b)
    \/ \E b \in Bpos : MCActorIterEnd(b)
    \/ \E b \in Bpos : \E k \in 1..MaxBlocks : MCActorHeartbeatTransfer(b, k)
    \/ \E b \in Bpos : MCActorHeartbeatEC(b)
    \/ \E b \in Bpos : \E e \in {OtherCmd, EmptyBatch} : MCActorEnqueueOther(b, e)
    \/ \E b \in Bpos : MCActorHeartbeatRejected(b)
    \/ \E b \in Bpos : MCActorLoopExit(b)
    \/ \E b \in Bpos : MCActorCleanUp(b)
    \/ \E b \in Bpos : MCShutdownActor(b)
    \/ \E b \in Bpos : MCUnpubMapRemove(b)
    \/ \E b \in Bpos : MCUnpubGate(b)
    \/ \E b \in Bpos : MCUnpubDataset(b)
    \/ \E b \in Bpos : MCUnpubStorage(b)
    \* command processors
    \/ \E b \in Bpos : MCCPCheck(b)
    \/ \E b \in Bpos : MCCPTake(b)
    \/ \E b \in Bpos : MCCPTakeInterrupted(b)
    \/ \E b \in Bpos : MCCPAssert(b)
    \/ \E b \in Bpos : MCCPReadActive(b)
    \/ \E b \in Bpos : MCCPSubmitEC(b)
    \* transferBlock (E1)
    \/ MCTestTransferStart
    \/ \E c \in Callers : MCTargetCheckE1(c)
    \/ \E c \in Callers : MCTBRegCheck(c)
    \/ \E c \in Callers : MCTBCheckBlock(c)
    \/ \E c \in Callers : MCTBCtor(c)
    \/ \E c \in Callers : MCTBExecute(c)
    \* local reporters (E2)
    \/ \E i \in LSlot : MCXferSend(i)
    \/ MCClientReadStart
    \/ \E i \in LSlot : MCReadReg(i)
    \/ \E i \in LSlot : MCReadSend(i)
    \/ \E i \in LSlot : MCHandleBadBlock(i)
    \/ MCVSScanSuspect
    \/ MCVSScanPeriodic
    \/ \E i \in LSlot : MCVSScanBlock(i)
    \/ \E i \in LSlot : MCVSContains(i)
    \/ MCDirScanStart
    \/ \E i \in LSlot : MCDirScanCheckAndUpdate(i)
    \/ \E i \in LSlot : MCGetVolume(i)
    \/ \E i \in LSlot : MCTargetCheckE2(i)
    \* remote reporters (E3)
    \/ MCRecvStart
    \/ \E i \in RSlot : MCRecvCreate(i)
    \/ \E i \in RSlot : MCRecvCorruptPacket(i)
    \/ \E i \in RSlot : MCRecvEnd(i)
    \/ \E i \in RSlot : MCECCorruptRound(i)
    \/ \E i \in RSlot : MCECTaskEnd(i)
    \/ \E i \in RSlot : MCTargetCheckE3(i)
    \* unpublish triggers and the shutdown sequence
    \/ MCDNShutdownBegin
    \/ MCShutdownXceiverServer
    \/ MCShutdownScannersBegin
    \/ MCShutdownScannersEnd
    \/ MCShutdownXferService
    \/ MCShutdownInterruptXceivers
    \/ MCShutdownEC
    \/ \E b \in Bpos : MCShutdownStopActor(b)
    \/ MCShutdownStopAllDone
    \/ MCDiskFail
    \/ \E n \in NewBs : MCRefreshStart(n)
    \/ MCRefreshStopOld

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(* Pruning, invariants and sanity probes                                   *)

\* Stop exploring once the target fired (tla-patterns sec. 1).  TLC still
\* checks invariants on the state that violates the constraint.
StopAfterTarget == ~targetFired

MCTypeOK ==
    /\ TypeOK
    /\ fc \in [FcFields -> Nat]
    /\ fc["shutdown"] <= MaxShutdown /\ fc["diskFail"] <= MaxDiskFail
    /\ fc["nnReject"] <= MaxNNReject /\ fc["refresh"] <= MaxRefresh
    /\ fc["xferCmd"] <= MaxXferCmd /\ fc["ecCmd"] <= MaxEcCmd
    /\ fc["clientRead"] <= MaxClientRead /\ fc["vscan"] <= MaxVScan
    /\ fc["dirScan"] <= MaxDirScan /\ fc["recv"] <= MaxRecv
    /\ fc["corruptPkt"] <= MaxCorruptPkt /\ fc["otherCmd"] <= MaxOtherCmd

\* Sanity probes (tla-patterns sec. 2).  Each must be VIOLATED in a run that
\* enables the matching workers; they are never part of a hunt.
TargetReached   == ~TargetCheckEnabled
TargetReachedE1 == ~(\E c \in Callers : cpc[c] = "e1")
TargetReachedE2 == ~(\E i \in LSlot : lrep[i].pc = "e2")
TargetReachedE3 == ~(\E i \in RSlot : rrep[i] \in {"rc_report", "ec_report"})

\* Route-isolation diagnostics for Phase 3 (not hunting targets): a
\* violation names the entry that failed first.  Use one at a time, with
\* TargetSafe removed, to look past a shorter route through another entry.
NoFireE1 == ~(targetFired /\ targetEntry = "E1")
NoFireE2 == ~(targetFired /\ targetEntry = "E2")
NoFireE3 == ~(targetFired /\ targetEntry = "E3")

=============================================================================
