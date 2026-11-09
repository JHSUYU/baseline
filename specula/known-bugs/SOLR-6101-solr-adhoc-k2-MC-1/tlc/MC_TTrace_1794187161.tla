---- MODULE MC_TTrace_1794187161 ----
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC

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
        nodeCores = ([n1 |-> {}, n2 |-> {}])
        /\
        ocpPc = ([split |-> "sp_sendLeader"])
        /\
        targetFired = (TRUE)
        /\
        nextCnn = (1)
        /\
        stateQueue = (<<[coll |-> "collection1", slice |-> "shard1_0", type |-> "createshard"]>>)
        /\
        replicaCnn = ([collection1_shard1_0_replica1 |-> 0, collection1_shard1_1_replica1 |-> 0, collection1_shard1_0_replica2 |-> 0, collection1_shard1_1_replica2 |-> 0])
        /\
        ocpLegacy = ([split |-> TRUE])
        /\
        ocpIdx = ([split |-> 2])
        /\
        propChanges = (1)
        /\
        csSlices = ({<<"collection1", "shard1">>})
        /\
        ocpCnn = ([split |-> 0])
        /\
        createMsgs = ({[coll |-> "collection1", core |-> "collection1_shard1_0_replica1", slice |-> "shard1_0", node |-> "n1", op |-> "split", cnn |-> 0, status |-> "failed"]})
        /\
        csColls = ({"collection1"})
        /\
        zkLegacyFalse = (TRUE)
    )
----

_init ==
    /\ csSlices = _TETrace[1].csSlices
    /\ zkLegacyFalse = _TETrace[1].zkLegacyFalse
    /\ targetFired = _TETrace[1].targetFired
    /\ propChanges = _TETrace[1].propChanges
    /\ ocpCnn = _TETrace[1].ocpCnn
    /\ nodeCores = _TETrace[1].nodeCores
    /\ nextCnn = _TETrace[1].nextCnn
    /\ csColls = _TETrace[1].csColls
    /\ ocpPc = _TETrace[1].ocpPc
    /\ ocpIdx = _TETrace[1].ocpIdx
    /\ replicaCnn = _TETrace[1].replicaCnn
    /\ stateQueue = _TETrace[1].stateQueue
    /\ ocpLegacy = _TETrace[1].ocpLegacy
    /\ createMsgs = _TETrace[1].createMsgs
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ csSlices  = _TETrace[i].csSlices
        /\ csSlices' = _TETrace[j].csSlices
        /\ zkLegacyFalse  = _TETrace[i].zkLegacyFalse
        /\ zkLegacyFalse' = _TETrace[j].zkLegacyFalse
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ propChanges  = _TETrace[i].propChanges
        /\ propChanges' = _TETrace[j].propChanges
        /\ ocpCnn  = _TETrace[i].ocpCnn
        /\ ocpCnn' = _TETrace[j].ocpCnn
        /\ nodeCores  = _TETrace[i].nodeCores
        /\ nodeCores' = _TETrace[j].nodeCores
        /\ nextCnn  = _TETrace[i].nextCnn
        /\ nextCnn' = _TETrace[j].nextCnn
        /\ csColls  = _TETrace[i].csColls
        /\ csColls' = _TETrace[j].csColls
        /\ ocpPc  = _TETrace[i].ocpPc
        /\ ocpPc' = _TETrace[j].ocpPc
        /\ ocpIdx  = _TETrace[i].ocpIdx
        /\ ocpIdx' = _TETrace[j].ocpIdx
        /\ replicaCnn  = _TETrace[i].replicaCnn
        /\ replicaCnn' = _TETrace[j].replicaCnn
        /\ stateQueue  = _TETrace[i].stateQueue
        /\ stateQueue' = _TETrace[j].stateQueue
        /\ ocpLegacy  = _TETrace[i].ocpLegacy
        /\ ocpLegacy' = _TETrace[j].ocpLegacy
        /\ createMsgs  = _TETrace[i].createMsgs
        /\ createMsgs' = _TETrace[j].createMsgs

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
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC

expression == 
    [
        \* To hide variables of the `MC` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        csSlices |-> csSlices
        ,zkLegacyFalse |-> zkLegacyFalse
        ,targetFired |-> targetFired
        ,propChanges |-> propChanges
        ,ocpCnn |-> ocpCnn
        ,nodeCores |-> nodeCores
        ,nextCnn |-> nextCnn
        ,csColls |-> csColls
        ,ocpPc |-> ocpPc
        ,ocpIdx |-> ocpIdx
        ,replicaCnn |-> replicaCnn
        ,stateQueue |-> stateQueue
        ,ocpLegacy |-> ocpLegacy
        ,createMsgs |-> createMsgs
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_csSlicesUnchanged |-> csSlices = csSlices'
        
        \* Format the `csSlices` variable as Json value.
        \* ,_csSlicesJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(csSlices)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_csSlicesModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].csSlices # _TETrace[s-1].csSlices
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE MC_TETrace ----
\*EXTENDS IOUtils, MC, TLC
\*
\*trace == IODeserialize("MC_TTrace_1794187161.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC

trace == 
    <<
    ([nodeCores |-> [n1 |-> {}, n2 |-> {}],ocpPc |-> [split |-> "queued"],targetFired |-> FALSE,nextCnn |-> 1,stateQueue |-> <<>>,replicaCnn |-> [collection1_shard1_0_replica1 |-> 0, collection1_shard1_1_replica1 |-> 0, collection1_shard1_0_replica2 |-> 0, collection1_shard1_1_replica2 |-> 0],ocpLegacy |-> [split |-> TRUE],ocpIdx |-> [split |-> 1],propChanges |-> 0,csSlices |-> {<<"collection1", "shard1">>},ocpCnn |-> [split |-> 0],createMsgs |-> {},csColls |-> {"collection1"},zkLegacyFalse |-> FALSE]),
    ([nodeCores |-> [n1 |-> {}, n2 |-> {}],ocpPc |-> [split |-> "queued"],targetFired |-> FALSE,nextCnn |-> 1,stateQueue |-> <<[type |-> "clusterprop", val |-> "false"]>>,replicaCnn |-> [collection1_shard1_0_replica1 |-> 0, collection1_shard1_1_replica1 |-> 0, collection1_shard1_0_replica2 |-> 0, collection1_shard1_1_replica2 |-> 0],ocpLegacy |-> [split |-> TRUE],ocpIdx |-> [split |-> 1],propChanges |-> 1,csSlices |-> {<<"collection1", "shard1">>},ocpCnn |-> [split |-> 0],createMsgs |-> {},csColls |-> {"collection1"},zkLegacyFalse |-> FALSE]),
    ([nodeCores |-> [n1 |-> {}, n2 |-> {}],ocpPc |-> [split |-> "sp_sendLeader"],targetFired |-> FALSE,nextCnn |-> 1,stateQueue |-> <<[type |-> "clusterprop", val |-> "false"]>>,replicaCnn |-> [collection1_shard1_0_replica1 |-> 0, collection1_shard1_1_replica1 |-> 0, collection1_shard1_0_replica2 |-> 0, collection1_shard1_1_replica2 |-> 0],ocpLegacy |-> [split |-> TRUE],ocpIdx |-> [split |-> 1],propChanges |-> 1,csSlices |-> {<<"collection1", "shard1">>},ocpCnn |-> [split |-> 0],createMsgs |-> {},csColls |-> {"collection1"},zkLegacyFalse |-> FALSE]),
    ([nodeCores |-> [n1 |-> {}, n2 |-> {}],ocpPc |-> [split |-> "sp_sendLeader"],targetFired |-> FALSE,nextCnn |-> 1,stateQueue |-> <<>>,replicaCnn |-> [collection1_shard1_0_replica1 |-> 0, collection1_shard1_1_replica1 |-> 0, collection1_shard1_0_replica2 |-> 0, collection1_shard1_1_replica2 |-> 0],ocpLegacy |-> [split |-> TRUE],ocpIdx |-> [split |-> 1],propChanges |-> 1,csSlices |-> {<<"collection1", "shard1">>},ocpCnn |-> [split |-> 0],createMsgs |-> {},csColls |-> {"collection1"},zkLegacyFalse |-> TRUE]),
    ([nodeCores |-> [n1 |-> {}, n2 |-> {}],ocpPc |-> [split |-> "sp_sendLeader"],targetFired |-> FALSE,nextCnn |-> 1,stateQueue |-> <<[coll |-> "collection1", slice |-> "shard1_0", type |-> "createshard"]>>,replicaCnn |-> [collection1_shard1_0_replica1 |-> 0, collection1_shard1_1_replica1 |-> 0, collection1_shard1_0_replica2 |-> 0, collection1_shard1_1_replica2 |-> 0],ocpLegacy |-> [split |-> TRUE],ocpIdx |-> [split |-> 2],propChanges |-> 1,csSlices |-> {<<"collection1", "shard1">>},ocpCnn |-> [split |-> 0],createMsgs |-> {[coll |-> "collection1", core |-> "collection1_shard1_0_replica1", slice |-> "shard1_0", node |-> "n1", op |-> "split", cnn |-> 0, status |-> "sent"]},csColls |-> {"collection1"},zkLegacyFalse |-> TRUE]),
    ([nodeCores |-> [n1 |-> {}, n2 |-> {}],ocpPc |-> [split |-> "sp_sendLeader"],targetFired |-> TRUE,nextCnn |-> 1,stateQueue |-> <<[coll |-> "collection1", slice |-> "shard1_0", type |-> "createshard"]>>,replicaCnn |-> [collection1_shard1_0_replica1 |-> 0, collection1_shard1_1_replica1 |-> 0, collection1_shard1_0_replica2 |-> 0, collection1_shard1_1_replica2 |-> 0],ocpLegacy |-> [split |-> TRUE],ocpIdx |-> [split |-> 2],propChanges |-> 1,csSlices |-> {<<"collection1", "shard1">>},ocpCnn |-> [split |-> 0],createMsgs |-> {[coll |-> "collection1", core |-> "collection1_shard1_0_replica1", slice |-> "shard1_0", node |-> "n1", op |-> "split", cnn |-> 0, status |-> "failed"]},csColls |-> {"collection1"},zkLegacyFalse |-> TRUE])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187161 ----
CONSTANTS
    Nodes <- MCNodes
    Ops = { "split" }
    OpSpec <- MCOpSpec
    InitLegacyFalse = FALSE
    InitColls <- MCInitColls
    InitSlices <- MCInitSlices
    MaxPropChanges = 1
    SplitReplicas = 1

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