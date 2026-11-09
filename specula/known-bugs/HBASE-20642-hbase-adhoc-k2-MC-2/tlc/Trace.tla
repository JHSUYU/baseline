------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hbase-adhoc-k2), Category A: one linear  *)
(* NDJSON trace, cursor `l`.  Event names and fields are defined in        *)
(* instrumentation-spec.md.  Every wrapper calls the full base action and  *)
(* validates the post-state against the fields the event captures.         *)
(*                                                                         *)
(* Identifier mapping (64-bit values are emitted as JSON strings):         *)
(*   nonce  -> ordinal of first appearance among ClientSend events         *)
(*             (base: nextNonce allocates 1, 2, ... in send order)         *)
(*   procId -> ordinal of first appearance among reserving                 *)
(*             ModifyTableRegisterNonce events (base: nextProcId 1, 2, ...)*)
(*   attempt-> server events carry the nonce; the attempt is the one whose *)
(*             nonce matches and whose handler pc enables the base action. *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

\* ---------------------------------------------------------------------------
\* Trace loading
\* ---------------------------------------------------------------------------
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

VARIABLE l
traceVars == <<l>>

logline == TraceLog[l]
ev      == logline.event

Has(e, f) == f \in DOMAIN e
ToSet(s)  == {s[i] : i \in DOMAIN s}

\* ---------------------------------------------------------------------------
\* Constants derived from the trace (referenced from Trace.cfg via <-)
\* ---------------------------------------------------------------------------
SendEvents == TLCEval(SelectSeq(TraceLog, LAMBDA x : x.event.name = "ClientSend"))

TraceNumOps == TLCEval(
    IF Len(SendEvents) = 0 THEN 1
    ELSE LET ops == {SendEvents[i].event.op : i \in 1..Len(SendEvents)}
         IN CHOOSE m \in ops : \A o \in ops : o <= m)

\* FamilySeq: the family of each logical request, from its first ClientSend.
TraceFamilySeq == TLCEval(
    [o \in 1..TraceNumOps |->
        LET i == CHOOSE k \in 1..Len(SendEvents) : SendEvents[k].event.op = o
        IN SendEvents[i].event.family])

\* InitFams: the table's families on HDFS before the first traced event.
TraceInitFams == TLCEval(ToSet(TraceLog[1].event.state.fsDesc))

\* nonce ordinal (base nextNonce order)
NonceIdx(raw) ==
    LET i == CHOOSE k \in 1..Len(SendEvents) :
                 /\ SendEvents[k].event.nonce = raw
                 /\ \A j \in 1..(k-1) : SendEvents[j].event.nonce # raw
    IN Cardinality({SendEvents[j].event.nonce : j \in 1..i})

ReserveEvents == TLCEval(SelectSeq(TraceLog, LAMBDA x :
                    /\ x.event.name = "ModifyTableRegisterNonce"
                    /\ x.event.reserved = TRUE))

\* procId ordinal (base nextProcId order)
ProcIdx(raw) ==
    LET i == CHOOSE k \in 1..Len(ReserveEvents) :
                 /\ ReserveEvents[k].event.procId = raw
                 /\ \A j \in 1..(k-1) : ReserveEvents[j].event.procId # raw
    IN Cardinality({ReserveEvents[j].event.procId : j \in 1..i})

\* MTP state names in the trace are the ModifyTableState enum names without the
\* "MODIFY_TABLE_" prefix, plus SUCCESS / WAIT_CHILDREN (instrumentation-spec §1.3).
TraceProcState(s) == s

\* ---------------------------------------------------------------------------
\* Post-state validation
\* ---------------------------------------------------------------------------
\* Master-side snapshot (every server event): fsDesc, cache, initialized.
ValidateMasterState ==
    /\ Has(ev, "state")
    /\ ToSet(ev.state.fsDesc) = fsDesc'
    /\ ev.state.cacheValid = cacheValid'
    /\ ev.state.cacheValid => ToSet(ev.state.cacheDesc) = cacheDesc'
    /\ ev.state.initialized = initialized'

\* Client-side snapshot (every client event): tries, pc.
ValidateClientState ==
    /\ Has(ev, "client")
    /\ ev.client.tries = client'.tries
    /\ ev.client.pc = client'.pc

\* Attempt selected by nonce.
AttemptsWithNonce(raw) == {a \in DOMAIN attempts : attempts[a].nonce = NonceIdx(raw)}

\* ---------------------------------------------------------------------------
\* Action wrappers: client
\* ---------------------------------------------------------------------------
TraceClientSend ==
    /\ ev.name = "ClientSend"
    /\ ClientSend
    /\ attempts'[Len(attempts')].nonce = NonceIdx(ev.nonce)
    /\ attempts'[Len(attempts')].fam = ev.family
    /\ attempts'[Len(attempts')].op = ev.op
    /\ ValidateClientState
    /\ l' = l + 1

TraceClientReceiveOk ==
    /\ ev.name = "ClientReceiveOk"
    /\ ClientReceiveOk
    /\ client'.resultProc = ProcIdx(ev.procId)
    /\ ValidateClientState
    /\ l' = l + 1

\* RRC:110-150 catch block.  The exception class tells which base action produced it.
TraceClientAttemptFailed ==
    /\ ev.name = "ClientAttemptFailed"
    /\ \/ /\ ev.exception = "CallTimeoutException"
          /\ ClientTimeout
       \/ /\ ev.exception = "PleaseHoldException"
          /\ ClientReceiveRetriable
       \/ /\ ev.exception \notin {"CallTimeoutException", "PleaseHoldException"}
          /\ \/ ReplyLost
             \/ ClientReceiveRetriable
    /\ ValidateClientState
    /\ l' = l + 1

TraceClientAwaitProcedure ==
    /\ ev.name = "ClientAwaitProcedure"
    /\ ClientAwaitProcedure
    /\ ValidateClientState
    /\ l' = l + 1

\* ---------------------------------------------------------------------------
\* Action wrappers: RPC handler
\* ---------------------------------------------------------------------------
TraceHandlerStart ==
    /\ ev.name = "HandlerStart"
    /\ \E a \in AttemptsWithNonce(ev.nonce) :
         /\ HandlerStart(a)
         /\ attempts'[a].hpc = (CASE ev.outcome = "dropped"    -> "Dropped"
                                  [] ev.outcome = "pleaseHold" -> "Done"
                                  [] ev.outcome = "started"    -> "Started")
    /\ ValidateMasterState
    /\ l' = l + 1

TraceTargetCheck ==
    /\ ev.name = "TargetCheck"
    /\ \E a \in AttemptsWithNonce(ev.nonce) :
         /\ TargetCheck(a)
         /\ targetFired' = ev.fired
         /\ ev.family = attempts[a].fam
         /\ ~ev.fired => attempts'[a].old = ToSet(ev.old)
    /\ ValidateMasterState
    /\ l' = l + 1

TraceModifyTableRegisterNonce ==
    /\ ev.name = "ModifyTableRegisterNonce"
    /\ \E a \in AttemptsWithNonce(ev.nonce) :
         /\ ModifyTableRegisterNonce(a)
         /\ attempts'[a].hpc = (IF ev.reserved THEN "Run" ELSE "NonceWait")
         /\ attempts'[a].procId = ProcIdx(ev.procId)
    /\ ValidateMasterState
    /\ l' = l + 1

TraceNonceWaitDone ==
    /\ ev.name = "NonceWaitDone"
    /\ \E a \in AttemptsWithNonce(ev.nonce) :
         /\ NonceWaitDone(a)
         /\ attempts[a].procId = ProcIdx(ev.procId)
    /\ ValidateMasterState
    /\ l' = l + 1

TraceSubmitModifyTableProcedure ==
    /\ ev.name = "SubmitModifyTableProcedure"
    /\ \E a \in AttemptsWithNonce(ev.nonce) :
         /\ SubmitModifyTableProcedure(a)
         /\ attempts[a].procId = ProcIdx(ev.procId)
         /\ procMeta'[ProcIdx(ev.procId)].newDesc = ToSet(ev.newDesc)
    /\ ValidateMasterState
    /\ l' = l + 1

TraceHandlerReply ==
    /\ ev.name = "HandlerReply"
    /\ \E a \in AttemptsWithNonce(ev.nonce) :
         /\ HandlerReply(a)
         /\ attempts[a].procId = ProcIdx(ev.procId)
    /\ ValidateMasterState
    /\ l' = l + 1

\* ---------------------------------------------------------------------------
\* Action wrappers: procedure worker
\* ---------------------------------------------------------------------------
ProcStepOf(name, p) ==
    CASE name = "MTPPrepare"              -> MTPPrepare(p)
      [] name = "MTPPreOperation"         -> MTPPreOperation(p)
      [] name = "MTPUpdateDescWriteFS"    -> MTPUpdateDescWriteFS(p)
      [] name = "MTPUpdateDescWriteCache" -> MTPUpdateDescWriteCache(p)
      [] name = "MTPUpdateDescPersist"    -> MTPUpdateDescPersist(p)
      [] name = "MTPRemoveReplicaColumn"  -> MTPRemoveReplicaColumn(p)
      [] name = "MTPDeleteFsLayout"       -> MTPDeleteFsLayout(p)
      [] name = "MTPPostOperation"        -> MTPPostOperation(p)
      [] name = "MTPReopenAllRegions"     -> MTPReopenAllRegions(p)
      [] name = "MTPReopenChildrenDone"   -> MTPReopenChildrenDone(p)
      [] name = "ProcedureFinished"       -> ProcedureFinished(p)
      [] OTHER                            -> FALSE

ProcEventNames == {"MTPPrepare", "MTPPreOperation", "MTPUpdateDescWriteFS",
                   "MTPUpdateDescWriteCache", "MTPUpdateDescPersist",
                   "MTPRemoveReplicaColumn", "MTPDeleteFsLayout", "MTPPostOperation",
                   "MTPReopenAllRegions", "MTPReopenChildrenDone", "ProcedureFinished"}

TraceProcStep ==
    /\ ev.name \in ProcEventNames
    /\ LET p == ProcIdx(ev.procId) IN
       /\ ProcStepOf(ev.name, p)
       \* procState: the in-memory state after the step (instrumentation-spec §1.3)
       /\ procRun'[p] = TraceProcState(ev.procState)
       /\ procStored'[p] = TraceProcState(ev.storedState)
    /\ ValidateMasterState
    /\ l' = l + 1

\* ---------------------------------------------------------------------------
\* Action wrappers: master lifecycle (only in fault variants of the workload)
\* ---------------------------------------------------------------------------
TraceMasterCrash ==
    /\ ev.name = "MasterCrash"
    /\ MasterCrash
    /\ l' = l + 1

TraceMasterRecover ==
    /\ ev.name = "MasterRecover"
    /\ MasterRecover
    /\ ToSet(ev.state.fsDesc) = fsDesc'
    /\ ev.state.initialized = initialized'
    /\ Cardinality(procedures') = ev.loadedRunnable
    /\ l' = l + 1

TraceMasterFinishInitialization ==
    /\ ev.name = "MasterFinishInitialization"
    /\ MasterFinishInitialization
    /\ ValidateMasterState
    /\ l' = l + 1

\* ---------------------------------------------------------------------------
\* Spec
\* ---------------------------------------------------------------------------
\* Bootstrap: base Init with InitFams taken from the first event's snapshot
\* (Trace.cfg: InitFams <- TraceInitFams).  The master is initialized before the
\* workload's addColumn (the test waits for the mini cluster).
TraceInit ==
    /\ Init
    /\ l = 1

TraceNext ==
    /\ l <= Len(TraceLog)
    /\ \/ TraceClientSend
       \/ TraceClientReceiveOk
       \/ TraceClientAttemptFailed
       \/ TraceClientAwaitProcedure
       \/ TraceHandlerStart
       \/ TraceTargetCheck
       \/ TraceModifyTableRegisterNonce
       \/ TraceNonceWaitDone
       \/ TraceSubmitModifyTableProcedure
       \/ TraceHandlerReply
       \/ TraceProcStep
       \/ TraceMasterCrash
       \/ TraceMasterRecover
       \/ TraceMasterFinishInitialization
    \* No silent actions: every base action is instrumented (instrumentation-spec §2).

TraceSpec == TraceInit /\ [][TraceNext]_<<l, vars>> /\ WF_<<l, vars>>(TraceNext)

TraceView == <<vars, l>>

TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [ l |-> l,
      event |-> IF l <= Len(TraceLog) THEN ev ELSE "done",
      fsDesc |-> fsDesc, cacheDesc |-> cacheDesc, cacheValid |-> cacheValid,
      initialized |-> initialized, attempts |-> attempts, procRun |-> procRun,
      procStored |-> procStored, client |-> client, targetFired |-> targetFired ]

=============================================================================
