---- MODULE MC_TTrace_1794187161 ----
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC, MC_TEConstants

_expression ==
    LET MC_TEExpression == INSTANCE MC_TEExpression
    IN MC_TEExpression!expression
----

_trace ==
    LET MC_TETrace == INSTANCE MC_TETrace
    IN MC_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        halted = (FALSE)
        /\
        rollerShouldRun = (TRUE)
        /\
        elState = ("BETWEEN_LOG_SEGMENTS")
        /\
        jStream = ((j1 :> "disabled"))
        /\
        targetFired = (TRUE)
        /\
        cnt = ([rpcRoll |-> 2, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 1, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0])
        /\
        stopPhase = ("running")
        /\
        haState = ("Active")
        /\
        streamOpen = (FALSE)
        /\
        jDisk = ((j1 :> "failed"))
        /\
        pc = ([rpc |-> "atCheck", roller |-> "idle", admin |-> "idle"])
        /\
        lockHolder = ("rpc")
        /\
        safeMode = (FALSE)
        /\
        pendingEdits = (0)
    )
----

_init ==
    /\ targetFired = _TETrace[1].targetFired
    /\ jDisk = _TETrace[1].jDisk
    /\ stopPhase = _TETrace[1].stopPhase
    /\ pc = _TETrace[1].pc
    /\ rollerShouldRun = _TETrace[1].rollerShouldRun
    /\ lockHolder = _TETrace[1].lockHolder
    /\ jStream = _TETrace[1].jStream
    /\ pendingEdits = _TETrace[1].pendingEdits
    /\ cnt = _TETrace[1].cnt
    /\ halted = _TETrace[1].halted
    /\ haState = _TETrace[1].haState
    /\ elState = _TETrace[1].elState
    /\ streamOpen = _TETrace[1].streamOpen
    /\ safeMode = _TETrace[1].safeMode
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ jDisk  = _TETrace[i].jDisk
        /\ jDisk' = _TETrace[j].jDisk
        /\ stopPhase  = _TETrace[i].stopPhase
        /\ stopPhase' = _TETrace[j].stopPhase
        /\ pc  = _TETrace[i].pc
        /\ pc' = _TETrace[j].pc
        /\ rollerShouldRun  = _TETrace[i].rollerShouldRun
        /\ rollerShouldRun' = _TETrace[j].rollerShouldRun
        /\ lockHolder  = _TETrace[i].lockHolder
        /\ lockHolder' = _TETrace[j].lockHolder
        /\ jStream  = _TETrace[i].jStream
        /\ jStream' = _TETrace[j].jStream
        /\ pendingEdits  = _TETrace[i].pendingEdits
        /\ pendingEdits' = _TETrace[j].pendingEdits
        /\ cnt  = _TETrace[i].cnt
        /\ cnt' = _TETrace[j].cnt
        /\ halted  = _TETrace[i].halted
        /\ halted' = _TETrace[j].halted
        /\ haState  = _TETrace[i].haState
        /\ haState' = _TETrace[j].haState
        /\ elState  = _TETrace[i].elState
        /\ elState' = _TETrace[j].elState
        /\ streamOpen  = _TETrace[i].streamOpen
        /\ streamOpen' = _TETrace[j].streamOpen
        /\ safeMode  = _TETrace[i].safeMode
        /\ safeMode' = _TETrace[j].safeMode

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187161.json", _TETrace)

=============================================================================

 Note that you can extract this module `MC_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `MC_TEExpression.tla` file takes precedence 
  over the module `MC_TEExpression` below).

---- MODULE MC_TEExpression ----
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC, MC_TEConstants

expression == 
    [
        \* To hide variables of the `MC` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        targetFired |-> targetFired
        ,jDisk |-> jDisk
        ,stopPhase |-> stopPhase
        ,pc |-> pc
        ,rollerShouldRun |-> rollerShouldRun
        ,lockHolder |-> lockHolder
        ,jStream |-> jStream
        ,pendingEdits |-> pendingEdits
        ,cnt |-> cnt
        ,halted |-> halted
        ,haState |-> haState
        ,elState |-> elState
        ,streamOpen |-> streamOpen
        ,safeMode |-> safeMode
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_targetFiredUnchanged |-> targetFired = targetFired'
        
        \* Format the `targetFired` variable as Json value.
        \* ,_targetFiredJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(targetFired)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_targetFiredModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].targetFired # _TETrace[s-1].targetFired
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE MC_TETrace ----
\*EXTENDS IOUtils, MC, TLC, MC_TEConstants
\*
\*trace == IODeserialize("MC_TTrace_1794187161.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC, MC_TEConstants

trace == 
    <<
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "IN_SEGMENT",jStream |-> (j1 :> "active"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 0, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 0, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> TRUE,jDisk |-> (j1 :> "ok"),pc |-> [rpc |-> "idle", roller |-> "idle", admin |-> "idle"],lockHolder |-> "none",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "IN_SEGMENT",jStream |-> (j1 :> "active"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 1, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 0, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> TRUE,jDisk |-> (j1 :> "ok"),pc |-> [rpc |-> "waitLock", roller |-> "idle", admin |-> "idle"],lockHolder |-> "none",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "IN_SEGMENT",jStream |-> (j1 :> "active"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 1, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 0, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> TRUE,jDisk |-> (j1 :> "ok"),pc |-> [rpc |-> "atCheck", roller |-> "idle", admin |-> "idle"],lockHolder |-> "rpc",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "IN_SEGMENT",jStream |-> (j1 :> "active"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 1, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 0, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> TRUE,jDisk |-> (j1 :> "ok"),pc |-> [rpc |-> "endSync", roller |-> "idle", admin |-> "idle"],lockHolder |-> "rpc",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "IN_SEGMENT",jStream |-> (j1 :> "active"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 1, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 0, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> TRUE,jDisk |-> (j1 :> "ok"),pc |-> [rpc |-> "endFinalize", roller |-> "idle", admin |-> "idle"],lockHolder |-> "rpc",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "BETWEEN_LOG_SEGMENTS",jStream |-> (j1 :> "closed"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 1, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 0, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> FALSE,jDisk |-> (j1 :> "ok"),pc |-> [rpc |-> "starting", roller |-> "idle", admin |-> "idle"],lockHolder |-> "rpc",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "BETWEEN_LOG_SEGMENTS",jStream |-> (j1 :> "closed"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 1, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 1, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> FALSE,jDisk |-> (j1 :> "failed"),pc |-> [rpc |-> "starting", roller |-> "idle", admin |-> "idle"],lockHolder |-> "rpc",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "BETWEEN_LOG_SEGMENTS",jStream |-> (j1 :> "disabled"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 1, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 1, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> FALSE,jDisk |-> (j1 :> "failed"),pc |-> [rpc |-> "idle", roller |-> "idle", admin |-> "idle"],lockHolder |-> "none",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "BETWEEN_LOG_SEGMENTS",jStream |-> (j1 :> "disabled"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 2, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 1, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> FALSE,jDisk |-> (j1 :> "failed"),pc |-> [rpc |-> "waitLock", roller |-> "idle", admin |-> "idle"],lockHolder |-> "none",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "BETWEEN_LOG_SEGMENTS",jStream |-> (j1 :> "disabled"),targetFired |-> FALSE,cnt |-> [rpcRoll |-> 2, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 1, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> FALSE,jDisk |-> (j1 :> "failed"),pc |-> [rpc |-> "atCheck", roller |-> "idle", admin |-> "idle"],lockHolder |-> "rpc",safeMode |-> FALSE,pendingEdits |-> 0]),
    ([halted |-> FALSE,rollerShouldRun |-> TRUE,elState |-> "BETWEEN_LOG_SEGMENTS",jStream |-> (j1 :> "disabled"),targetFired |-> TRUE,cnt |-> [rpcRoll |-> 2, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 1, jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0, stop |-> 0, standby |-> 0],stopPhase |-> "running",haState |-> "Active",streamOpen |-> FALSE,jDisk |-> (j1 :> "failed"),pc |-> [rpc |-> "atCheck", roller |-> "idle", admin |-> "idle"],lockHolder |-> "rpc",safeMode |-> FALSE,pendingEdits |-> 0])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS j1

=============================================================================

---- CONFIG MC_TTrace_1794187161 ----
CONSTANTS
    j1 = j1
    Journal = { j1 }
    Required = { }
    MinRedundant = 1
    AsyncMode = TRUE
    HAEnabled = FALSE
    RollerFires = FALSE
    MaxRpcRolls = 2
    MaxRollerChecks = 0
    MaxClientEdits = 2
    MaxJournalFaults = 1
    MaxJournalRepairs = 1
    MaxSafeModeEnters = 1
    MaxSafeModeLeaves = 1
    MaxSaveNamespace = 1
    MaxStops = 0
    MaxStandby = 0
    j1 = j1

INVARIANT
    _inv

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Mon Nov 09 01:19:22 UTC 2026