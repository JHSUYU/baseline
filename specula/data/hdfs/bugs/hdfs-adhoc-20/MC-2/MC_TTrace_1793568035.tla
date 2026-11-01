---- MODULE MC_TTrace_1793568035 ----
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
        nnPhase = ((n1 :> "UP" @@ n2 :> "UP"))
        /\
        fenced = ((n1 :> FALSE @@ n2 :> FALSE))
        /\
        aPhase = ((n1 :> "RUNNING" @@ n2 :> "INIT"))
        /\
        nsResp = ((n1 :> "NONE" @@ n2 :> "NONE"))
        /\
        applied = ((n1 :> 1 @@ n2 :> 0))
        /\
        targetFired = (TRUE)
        /\
        link = ((n1 :> TRUE @@ n2 :> TRUE))
        /\
        hbResp = ((n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]))
        /\
        faults = ([crash |-> 1, cleanStop |-> 0, failover |-> 1, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0])
        /\
        haState = ((n1 :> "ACTIVE" @@ n2 :> "STANDBY"))
        /\
        durable = (2)
        /\
        written = ((n1 :> 2 @@ n2 :> 0))
        /\
        lastActiveClaimTxId = (3)
        /\
        bpServiceToActive = (n1)
        /\
        maxHeldTxid = ((n1 :> 3 @@ n2 :> 0))
    )
----

_init ==
    /\ nnPhase = _TETrace[1].nnPhase
    /\ hbResp = _TETrace[1].hbResp
    /\ durable = _TETrace[1].durable
    /\ targetFired = _TETrace[1].targetFired
    /\ fenced = _TETrace[1].fenced
    /\ link = _TETrace[1].link
    /\ bpServiceToActive = _TETrace[1].bpServiceToActive
    /\ written = _TETrace[1].written
    /\ nsResp = _TETrace[1].nsResp
    /\ applied = _TETrace[1].applied
    /\ faults = _TETrace[1].faults
    /\ maxHeldTxid = _TETrace[1].maxHeldTxid
    /\ lastActiveClaimTxId = _TETrace[1].lastActiveClaimTxId
    /\ haState = _TETrace[1].haState
    /\ aPhase = _TETrace[1].aPhase
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ nnPhase  = _TETrace[i].nnPhase
        /\ nnPhase' = _TETrace[j].nnPhase
        /\ hbResp  = _TETrace[i].hbResp
        /\ hbResp' = _TETrace[j].hbResp
        /\ durable  = _TETrace[i].durable
        /\ durable' = _TETrace[j].durable
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ fenced  = _TETrace[i].fenced
        /\ fenced' = _TETrace[j].fenced
        /\ link  = _TETrace[i].link
        /\ link' = _TETrace[j].link
        /\ bpServiceToActive  = _TETrace[i].bpServiceToActive
        /\ bpServiceToActive' = _TETrace[j].bpServiceToActive
        /\ written  = _TETrace[i].written
        /\ written' = _TETrace[j].written
        /\ nsResp  = _TETrace[i].nsResp
        /\ nsResp' = _TETrace[j].nsResp
        /\ applied  = _TETrace[i].applied
        /\ applied' = _TETrace[j].applied
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ maxHeldTxid  = _TETrace[i].maxHeldTxid
        /\ maxHeldTxid' = _TETrace[j].maxHeldTxid
        /\ lastActiveClaimTxId  = _TETrace[i].lastActiveClaimTxId
        /\ lastActiveClaimTxId' = _TETrace[j].lastActiveClaimTxId
        /\ haState  = _TETrace[i].haState
        /\ haState' = _TETrace[j].haState
        /\ aPhase  = _TETrace[i].aPhase
        /\ aPhase' = _TETrace[j].aPhase

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1793568035.json", _TETrace)

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
        nnPhase |-> nnPhase
        ,hbResp |-> hbResp
        ,durable |-> durable
        ,targetFired |-> targetFired
        ,fenced |-> fenced
        ,link |-> link
        ,bpServiceToActive |-> bpServiceToActive
        ,written |-> written
        ,nsResp |-> nsResp
        ,applied |-> applied
        ,faults |-> faults
        ,maxHeldTxid |-> maxHeldTxid
        ,lastActiveClaimTxId |-> lastActiveClaimTxId
        ,haState |-> haState
        ,aPhase |-> aPhase
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_nnPhaseUnchanged |-> nnPhase = nnPhase'
        
        \* Format the `nnPhase` variable as Json value.
        \* ,_nnPhaseJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(nnPhase)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_nnPhaseModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].nnPhase # _TETrace[s-1].nnPhase
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
\*trace == IODeserialize("MC_TTrace_1793568035.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC, MC_TEConstants

trace == 
    <<
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "INIT" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 0 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 0, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 1 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> Null,maxHeldTxid |-> (n1 :> 1 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "INIT" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 0 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 0, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 2 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> Null,maxHeldTxid |-> (n1 :> 2 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "INIT" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 0 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 0, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 3 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> Null,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "VERSIONED" @@ n2 :> "INIT"),nsResp |-> (n1 :> "ACTIVE" @@ n2 :> "NONE"),applied |-> (n1 :> 0 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 0, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 3 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> Null,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 0 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 0, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 3 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 0 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "ACTIVE", txid |-> 3] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 0, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 3 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "DOWN" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 0 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "ACTIVE", txid |-> 3] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 1, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "STANDBY" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 0 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 1 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "ACTIVE", txid |-> 3] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 1, cleanStop |-> 0, failover |-> 0, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "STANDBY" @@ n2 :> "STANDBY"),durable |-> 1,written |-> (n1 :> 1 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 1 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "ACTIVE", txid |-> 3] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 1, cleanStop |-> 0, failover |-> 1, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 2,written |-> (n1 :> 2 @@ n2 :> 0),lastActiveClaimTxId |-> -1,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 1 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 1, cleanStop |-> 0, failover |-> 1, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 2,written |-> (n1 :> 2 @@ n2 :> 0),lastActiveClaimTxId |-> 3,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 1 @@ n2 :> 0),targetFired |-> FALSE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "ACTIVE", txid |-> 2] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 1, cleanStop |-> 0, failover |-> 1, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 2,written |-> (n1 :> 2 @@ n2 :> 0),lastActiveClaimTxId |-> 3,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)]),
    ([nnPhase |-> (n1 :> "UP" @@ n2 :> "UP"),fenced |-> (n1 :> FALSE @@ n2 :> FALSE),aPhase |-> (n1 :> "RUNNING" @@ n2 :> "INIT"),nsResp |-> (n1 :> "NONE" @@ n2 :> "NONE"),applied |-> (n1 :> 1 @@ n2 :> 0),targetFired |-> TRUE,link |-> (n1 :> TRUE @@ n2 :> TRUE),hbResp |-> (n1 :> [state |-> "NONE", txid |-> -1] @@ n2 :> [state |-> "NONE", txid |-> -1]),faults |-> [crash |-> 1, cleanStop |-> 0, failover |-> 1, depose |-> 0, refresh |-> 0, death |-> 0, partition |-> 0, dnRestart |-> 0],haState |-> (n1 :> "ACTIVE" @@ n2 :> "STANDBY"),durable |-> 2,written |-> (n1 :> 2 @@ n2 :> 0),lastActiveClaimTxId |-> 3,bpServiceToActive |-> n1,maxHeldTxid |-> (n1 :> 3 @@ n2 :> 0)])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS n1, n2

=============================================================================

---- CONFIG MC_TTrace_1793568035 ----
CONSTANTS
    NN = { n1 , n2 }
    HAEnabled = TRUE
    Null = Null
    MaxTxid = 7
    MaxCrash = 1
    MaxFailover = 2
    MaxRefresh = 1
    MaxActorDeath = 1
    MaxPartition = 1
    MaxDepose = 0
    MaxCleanRestart = 0
    MaxDNRestart = 0
    n1 = n1
    n2 = n2
    Null = Null

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
\* Generated on Sun Nov 01 21:20:38 UTC 2026