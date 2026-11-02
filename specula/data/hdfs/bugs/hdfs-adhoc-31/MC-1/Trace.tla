-------------------------------- MODULE Trace --------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hdfs-adhoc-31), Category A.              *)
(*                                                                         *)
(* The harness writes one NDJSON stream for the whole MiniDFSCluster.      *)
(* Every event carries the DataNode instance label "dn"; DataNodes share   *)
(* no state this model tracks (each has its own BlockPoolManager), so      *)
(* each DataNode's projection is validated on its own (IOEnv.DN selects    *)
(* it; default: the DataNode of the first event, i.e. dn0).                *)
(*                                                                         *)
(* Every base action has exactly one event name (instrumentation-spec.md); *)
(* there are no silent actions.  Each wrapper matches the event, runs the  *)
(* base action with the event's parameters, checks every captured field    *)
(* against the model state, and advances l.                                *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, TLC

-----------------------------------------------------------------------------
(* Trace loading *)

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

AllEvents == TLCEval(
    SelectSeq(ndJsonDeserialize(JsonFile),
              LAMBDA x : /\ "tag" \in DOMAIN x
                         /\ x.tag = "specula"
                         /\ "event" \in DOMAIN x
                         /\ "dn" \in DOMAIN x))

ASSUME Len(AllEvents) > 0

TraceDN == IF "DN" \in DOMAIN IOEnv THEN IOEnv.DN ELSE AllEvents[1].dn

TraceLog == TLCEval(SelectSeq(AllEvents, LAMBDA x : x.dn = TraceDN))

ASSUME Len(TraceLog) > 0

\* Constant bindings (Trace.cfg): the workload's values, overridable per run
\* for the brief's variants (scanner disabled / real; no header corruption).
TraceBpos ==
    IF \E k \in 1..Len(TraceLog) : TraceLog[k].event = "RefreshStart"
    THEN {"O", "N"} ELSE {"O"}
TraceScanner == IF "SCANNER" \in DOMAIN IOEnv THEN IOEnv.SCANNER ELSE "mock"
\* The scenario's test applies the header fixture (TestDiskError L258-263) to
\* this DataNode's replica.  Every trace starts with a clean replica
\* (Trace.cfg: HeaderCorrupt = FALSE); TFixtureCorruptHeader corrupts it.
TraceHeaderFixture ==
    IF "HEADER_CORRUPT" \in DOMAIN IOEnv THEN IOEnv.HEADER_CORRUPT = "true" ELSE TRUE

-----------------------------------------------------------------------------
(* Cursor and event helpers *)

VARIABLE l
traceVars == <<vars, l>>

logline == TraceLog[l]
IsEvent(name) == l <= Len(TraceLog) /\ logline.event = name
Step == l' = l + 1

ToSet(s) == {s[k] : k \in DOMAIN s}

\* Queue entry of a batch named by the harness (CPTake.batch).
BatchVal(e) ==
    CASE e.batch = "xfer"  -> e.blocks
      [] e.batch = "ec"    -> EcCmd
      [] e.batch = "other" -> OtherCmd
      [] e.batch = "empty" -> EmptyBatch

\* The guard operand as observed by a BlockPoolManager.get event:
\* found = (get(P) != null), stored = the BPOS label it returned.
MapMatches(e) ==
    /\ (bpMap # NoBpos) = e.found
    /\ e.found => bpMap = e.stored

\* Outcome of a BlockSender construction on P's replica (BS L261, L342).
SendOutcome ==
    IF ~dsHasPool THEN "notFound" ELSE IF metaCorrupt THEN "corrupt" ELSE "ok"

\* Deterministic slot choice: reporters of one kind at one position are
\* interchangeable, so the lowest such slot is taken.
LAt(kind, p) == {i \in LSlot : lrep[i].k = kind /\ lrep[i].pc = p}
PickL(kind, p) == CHOOSE i \in LAt(kind, p) : \A j \in LAt(kind, p) : i <= j
RAt(p) == {i \in RSlot : rrep[i] = p}
PickR(p) == CHOOSE i \in RAt(p) : \A j \in RAt(p) : i <= j

-----------------------------------------------------------------------------
(* Initial state: the DataNode as constructed (base Init) *)

TraceInit ==
    /\ Init
    /\ l = 1

-----------------------------------------------------------------------------
(* Actor events *)

TActorHandshakePut ==
    /\ IsEvent("ActorHandshakePut")
    /\ ActorHandshakePut(logline.bpos)
    /\ bpMap' = logline.stored
    /\ Step

TActorInitStorage ==
    /\ IsEvent("ActorInitStorage")
    /\ ActorInitStorage(logline.bpos)
    /\ (actorPc'[logline.bpos] = "hsDataset") = logline.ok
    /\ hasBp'[logline.bpos] = logline.ok
    /\ Step

TActorAddDataset ==
    /\ IsEvent("ActorAddDataset")
    /\ ActorAddDataset(logline.bpos)
    /\ dsHasPool'
    /\ Step

TActorRegister ==
    /\ IsEvent("ActorRegister")
    /\ ActorRegister(logline.bpos)
    /\ bpReg'[logline.bpos] = logline.ok
    /\ Step

TActorIterStart ==
    /\ IsEvent("ActorIterStart")
    /\ ActorIterStart(logline.bpos)
    /\ Step

TActorIterEnd ==
    /\ IsEvent("ActorIterEnd")
    /\ ActorIterEnd(logline.bpos)
    /\ Step

TActorHeartbeatTransfer ==
    /\ IsEvent("ActorHeartbeatTransfer")
    /\ ActorHeartbeatTransfer(logline.bpos, logline.blocks)
    /\ Step

TActorHeartbeatEC ==
    /\ IsEvent("ActorHeartbeatEC")
    /\ ActorHeartbeatEC(logline.bpos)
    /\ Step

TActorEnqueueOther ==
    /\ IsEvent("ActorEnqueueOther")
    /\ ActorEnqueueOther(logline.bpos, IF logline.batch = "empty" THEN EmptyBatch ELSE OtherCmd)
    /\ Step

TActorHeartbeatRejected ==
    /\ IsEvent("ActorHeartbeatRejected")
    /\ ActorHeartbeatRejected(logline.bpos)
    /\ Step

TActorLoopExit ==
    /\ IsEvent("ActorLoopExit")
    /\ ActorLoopExit(logline.bpos)
    /\ Step

TActorCleanUp ==
    /\ IsEvent("ActorCleanUp")
    /\ ActorCleanUp(logline.bpos)
    /\ Step

TShutdownActor ==
    /\ IsEvent("ShutdownActor")
    /\ ShutdownActor(logline.bpos)
    /\ Step

TUnpubMapRemove ==
    /\ IsEvent("UnpubMapRemove")
    /\ hasBp[logline.bpos] = logline.removedKey          \* BPM L91 t.hasBlockPoolId()
    /\ UnpubMapRemove(logline.bpos)
    /\ (bpMap' # NoBpos) = logline.mapped                \* containsKey(P) after BPM L94
    /\ offerSvcs' = ToSet(logline.offer)                 \* offerServices after BPM L90
    /\ Step

TUnpubGate ==
    /\ IsEvent("UnpubGate")
    /\ HasAnyRegisteredScanner = logline.hasScanners     \* DN L2159 result
    /\ UnpubGate(logline.bpos)
    /\ Step

TUnpubDataset ==
    /\ IsEvent("UnpubDataset")
    /\ UnpubDataset(logline.bpos)
    /\ Step

TUnpubStorage ==
    /\ IsEvent("UnpubStorage")
    /\ UnpubStorage(logline.bpos)
    /\ Step

\* BPSA.stop L623, by the shutdown (BPM.shutDownAll) or by refresh step 4.
TActorStop ==
    /\ IsEvent("ActorStop")
    /\ \/ /\ logline.by = "shutdown"
          /\ ShutdownStopActor(logline.bpos)
       \/ /\ logline.by = "refresh"
          /\ logline.bpos = OldB
          /\ inSvc[OldB] /\ ~stopped[OldB]
          /\ RefreshStopOld
    /\ stopped'[logline.bpos]
    /\ Step

-----------------------------------------------------------------------------
(* Command processor events *)

TCPCheck ==
    /\ IsEvent("CPCheck")
    /\ CPCheck(logline.bpos)
    /\ (cpc'[logline.bpos] = "take") = logline.ok
    /\ Step

TCPTake ==
    /\ IsEvent("CPTake")
    /\ cmdQ[logline.bpos] # <<>>
    /\ Head(cmdQ[logline.bpos]) = BatchVal(logline)
    /\ CPTake(logline.bpos)
    /\ Step

TCPTakeInterrupted ==
    /\ IsEvent("CPTakeInterrupted")
    /\ CPTakeInterrupted(logline.bpos)
    /\ Step

TCPAssert ==
    /\ IsEvent("CPAssert")
    /\ inSvc[logline.bpos] = logline.member              \* bpServices.contains(actor)
    /\ CPAssert(logline.bpos)
    /\ Step

TCPReadActive ==
    /\ IsEvent("CPReadActive")
    /\ active[logline.bpos] = logline.isActive           \* actor == bpServiceToActive
    /\ CPReadActive(logline.bpos)
    /\ Step

TCPSubmitEC ==
    /\ IsEvent("CPSubmitEC")
    /\ ecOpen = logline.submitted
    /\ CPSubmitEC(logline.bpos)
    /\ Step

-----------------------------------------------------------------------------
(* transferBlock events; caller = "O" / "N" (command processor) or "test" *)

TTestTransferStart ==
    /\ IsEvent("TestTransferStart")
    /\ TestTransferStart
    /\ Step

TTargetCheckE1 ==
    /\ IsEvent("TargetCheckE1")
    /\ MapMatches(logline)
    /\ TargetCheckE1(logline.caller)
    /\ Step

TTBRegCheck ==
    /\ IsEvent("TBRegCheck")
    /\ logline.ok = (bpMap # NoBpos /\ bpReg[bpMap])
    /\ TBRegCheck(logline.caller)
    /\ Step

TTBCheckBlock ==
    /\ IsEvent("TBCheckBlock")
    /\ logline.ok = dsHasPool
    /\ TBCheckBlock(logline.caller)
    /\ Step

TTBCtor ==
    /\ IsEvent("TBCtor")
    /\ logline.found = (bpMap # NoBpos)
    /\ TBCtor(logline.caller)
    /\ Step

TTBExecute ==
    /\ IsEvent("TBExecute")
    /\ logline.accepted = xferOpen
    /\ TBExecute(logline.caller)
    /\ Step

-----------------------------------------------------------------------------
(* Local reporter events (E2) *)

TXferSend ==
    /\ IsEvent("XferSend")
    /\ LAt("xf", "xf_send") # {}
    /\ logline.outcome = SendOutcome
    /\ XferSend(PickL("xf", "xf_send"))
    /\ Step

TClientReadStart ==
    /\ IsEvent("ClientReadStart")
    /\ ClientReadStart
    /\ Step

TReadReg ==
    /\ IsEvent("ReadReg")
    /\ LAt("rd", "rd_reg") # {}
    /\ logline.ok = (bpMap # NoBpos /\ bpReg[bpMap])
    /\ ReadReg(PickL("rd", "rd_reg"))
    /\ Step

TReadSend ==
    /\ IsEvent("ReadSend")
    /\ LAt("rd", "rd_send") # {}
    /\ logline.outcome = SendOutcome
    /\ ReadSend(PickL("rd", "rd_send"))
    /\ Step

THandleBadBlock ==
    /\ IsEvent("HandleBadBlock")
    /\ LAt(logline.kind, "hbb") # {}
    /\ logline.outcome = IF ScannerEnabled
                         THEN IF dsHasPool THEN "suspect" ELSE "noVolume"
                         ELSE "report"
    /\ HandleBadBlock(PickL(logline.kind, "hbb"))
    /\ Step

TVSScanSuspect ==
    /\ IsEvent("VSScanSuspect")
    /\ VSScanSuspect
    /\ Step

TVSScanPeriodic ==
    /\ IsEvent("VSScanPeriodic")
    /\ VSScanPeriodic
    /\ Step

TVSScanBlock ==
    /\ IsEvent("VSScanBlock")
    /\ LAt("vs", "vs_send") # {}
    /\ logline.outcome = SendOutcome
    /\ VSScanBlock(PickL("vs", "vs_send"))
    /\ Step

TVSContains ==
    /\ IsEvent("VSContains")
    /\ LAt("vs", "vs_contains") # {}
    /\ logline.found = dsHasPool
    /\ VSContains(PickL("vs", "vs_contains"))
    /\ Step

TDirScanStart ==
    /\ IsEvent("DirScanStart")
    /\ DirScanStart
    /\ Step

TDirScanCheckAndUpdate ==
    /\ IsEvent("DirScanCheckAndUpdate")
    /\ LAt("ds", "ds_locked") # {}
    /\ logline.outcome = IF dsHasPool THEN "flagged" ELSE "absent"
    /\ DirScanCheckAndUpdate(PickL("ds", "ds_locked"))
    /\ Step

TGetVolume ==
    /\ IsEvent("GetVolume")
    /\ LAt(logline.kind, "getvol") # {}
    /\ logline.found = dsHasPool
    /\ GetVolume(PickL(logline.kind, "getvol"))
    /\ Step

TTargetCheckE2 ==
    /\ IsEvent("TargetCheckE2")
    /\ LAt(logline.kind, "e2") # {}
    /\ MapMatches(logline)
    /\ TargetCheckE2(PickL(logline.kind, "e2"))
    /\ Step

-----------------------------------------------------------------------------
(* Remote reporter events (E3) *)

TRecvStart ==
    /\ IsEvent("RecvStart")
    /\ RecvStart
    /\ Step

TRecvCreate ==
    /\ IsEvent("RecvCreate")
    /\ RAt("rc_create") # {}
    /\ logline.ok = dsHasPool
    /\ RecvCreate(PickR("rc_create"))
    /\ Step

TRecvCorruptPacket ==
    /\ IsEvent("RecvCorruptPacket")
    /\ RAt("rc_active") # {}
    /\ RecvCorruptPacket(PickR("rc_active"))
    /\ Step

TRecvEnd ==
    /\ IsEvent("RecvEnd")
    /\ RAt("rc_active") # {}
    /\ RecvEnd(PickR("rc_active"))
    /\ Step

TECCorruptRound ==
    /\ IsEvent("ECCorruptRound")
    /\ RAt("ec_task") # {}
    /\ ECCorruptRound(PickR("ec_task"))
    /\ Step

TECTaskEnd ==
    /\ IsEvent("ECTaskEnd")
    /\ RAt("ec_task") # {}
    /\ ECTaskEnd(PickR("ec_task"))
    /\ Step

TTargetCheckE3 ==
    /\ IsEvent("TargetCheckE3")
    /\ LET p == IF logline.kind = "rc" THEN "rc_report" ELSE "ec_report" IN
         /\ RAt(p) # {}
         /\ MapMatches(logline)
         /\ TargetCheckE3(PickR(p))
    /\ Step

-----------------------------------------------------------------------------
(* DataNode-level events *)

TDNShutdownBegin ==
    /\ IsEvent("DNShutdownBegin") /\ DNShutdownBegin /\ Step
TShutdownXceiverServer ==
    /\ IsEvent("ShutdownXceiverServer") /\ ShutdownXceiverServer /\ Step
TShutdownScannersBegin ==
    /\ IsEvent("ShutdownScannersBegin") /\ ShutdownScannersBegin /\ Step
TShutdownScannersEnd ==
    /\ IsEvent("ShutdownScannersEnd") /\ ShutdownScannersEnd /\ Step
TShutdownXferService ==
    /\ IsEvent("ShutdownXferService") /\ ShutdownXferService /\ Step
TShutdownInterruptXceivers ==
    /\ IsEvent("ShutdownInterruptXceivers") /\ ShutdownInterruptXceivers /\ Step
TShutdownEC ==
    /\ IsEvent("ShutdownEC") /\ ShutdownEC /\ Step
TShutdownStopAllDone ==
    /\ IsEvent("ShutdownStopAllDone") /\ ShutdownStopAllDone /\ Step
TDiskFail ==
    /\ IsEvent("DiskFail") /\ DiskFail /\ Step
TRefreshStart ==
    /\ IsEvent("RefreshStart")
    /\ RefreshStart(logline.newBpos)
    /\ offerSvcs' = ToSet(logline.offer)
    /\ Step

-----------------------------------------------------------------------------
(* Untraced fixture step                                                   *)

\* The test thread's header write (base FixtureCorruptHeader) emits no event:
\* the workload test runs as written.  It is taken only when the scenario
\* applies the fixture and the next event is a BlockSender construction
\* that saw a corrupt header, which the clean header cannot explain.
TFixtureCorruptHeader ==
    /\ TraceHeaderFixture
    /\ l <= Len(TraceLog)
    /\ logline.event \in {"XferSend", "ReadSend", "VSScanBlock"}
    /\ logline.outcome = "corrupt"
    /\ FixtureCorruptHeader
    /\ UNCHANGED l

-----------------------------------------------------------------------------
(* Trace behavior *)

TraceNext ==
    \/ TActorHandshakePut \/ TActorInitStorage \/ TActorAddDataset \/ TActorRegister
    \/ TActorIterStart \/ TActorIterEnd \/ TActorHeartbeatTransfer \/ TActorHeartbeatEC
    \/ TActorEnqueueOther \/ TActorHeartbeatRejected \/ TActorLoopExit
    \/ TActorCleanUp \/ TShutdownActor \/ TUnpubMapRemove \/ TUnpubGate
    \/ TUnpubDataset \/ TUnpubStorage \/ TActorStop
    \/ TCPCheck \/ TCPTake \/ TCPTakeInterrupted \/ TCPAssert \/ TCPReadActive
    \/ TCPSubmitEC
    \/ TTestTransferStart \/ TTargetCheckE1 \/ TTBRegCheck \/ TTBCheckBlock
    \/ TTBCtor \/ TTBExecute
    \/ TXferSend \/ TClientReadStart \/ TReadReg \/ TReadSend \/ THandleBadBlock
    \/ TVSScanSuspect \/ TVSScanPeriodic \/ TVSScanBlock \/ TVSContains
    \/ TDirScanStart \/ TDirScanCheckAndUpdate \/ TGetVolume \/ TTargetCheckE2
    \/ TRecvStart \/ TRecvCreate \/ TRecvCorruptPacket \/ TRecvEnd
    \/ TECCorruptRound \/ TECTaskEnd \/ TTargetCheckE3
    \/ TDNShutdownBegin \/ TShutdownXceiverServer \/ TShutdownScannersBegin
    \/ TShutdownScannersEnd \/ TShutdownXferService \/ TShutdownInterruptXceivers
    \/ TShutdownEC \/ TShutdownStopAllDone \/ TDiskFail \/ TRefreshStart
    \/ TFixtureCorruptHeader

\* WF makes TraceMatched meaningful (without it TLC may stutter forever).
TraceSpec == TraceInit /\ [][TraceNext]_traceVars /\ WF_traceVars(TraceNext)

\* Every event consumed.  The wrappers are deterministic (one enabled
\* wrapper per event, deterministic slot choice; the fixture step and the
\* event's own wrapper are never enabled together), so this for-all property
\* is not weakened by dead branches.
TraceMatched == <>(l > Len(TraceLog))

\* Exists-style alternative: as an INVARIANT, a violation means some behavior
\* consumed the whole trace (success).
TraceNotDone == l <= Len(TraceLog)

TraceAlias ==
    [ l          |-> l,
      len        |-> Len(TraceLog),
      event      |-> IF l <= Len(TraceLog) THEN logline.event ELSE "DONE",
      line       |-> IF l <= Len(TraceLog) THEN logline ELSE [done |-> TRUE],
      bpMap      |-> bpMap,
      offerSvcs  |-> offerSvcs,
      dsHasPool  |-> dsHasPool,
      storHasPool |-> storHasPool,
      metaCorrupt |-> metaCorrupt,
      dnShouldRun |-> dnShouldRun,
      shPc       |-> shPc,
      actorPc    |-> actorPc,
      svcRun     |-> svcRun,
      stopped    |-> stopped,
      inSvc      |-> inSvc,
      active     |-> active,
      cmdQ       |-> cmdQ,
      cpc        |-> cpc,
      cpBlk      |-> cpBlk,
      lrep       |-> lrep,
      rrep       |-> rrep,
      targetFired |-> targetFired ]

=============================================================================
