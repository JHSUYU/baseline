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
        nonceMap = (<<1, 0, 0>>)
        /\
        procStored = (<<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>)
        /\
        targetFired = (TRUE)
        /\
        nextNonce = (3)
        /\
        nextProcId = (2)
        /\
        epoch = (2)
        /\
        cacheDesc = ({"cf0", "cf1"})
        /\
        completed = ({})
        /\
        faults = ([timeouts |-> 0, lost |-> 0, crashes |-> 1])
        /\
        cacheValid = (TRUE)
        /\
        procMeta = (<<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>)
        /\
        masterUp = (TRUE)
        /\
        procedures = ({1})
        /\
        procLatch = (<<0, 0, 0>>)
        /\
        initialized = (TRUE)
        /\
        procRun = (<<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>)
        /\
        client = ([pc |-> "Waiting", tries |-> 2, nonce |-> 2, op |-> 1, cur |-> 2, resultProc |-> 0])
        /\
        fsWriters = ({1})
        /\
        fsDesc = ({"cf0", "cf1"})
        /\
        attempts = (<<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE], [hpc |-> "Started", epoch |-> 2, nonce |-> 2, op |-> 1, fam |-> "cf1", old |-> {}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>)
    )
----

_init ==
    /\ epoch = _TETrace[1].epoch
    /\ completed = _TETrace[1].completed
    /\ cacheValid = _TETrace[1].cacheValid
    /\ attempts = _TETrace[1].attempts
    /\ targetFired = _TETrace[1].targetFired
    /\ fsWriters = _TETrace[1].fsWriters
    /\ procStored = _TETrace[1].procStored
    /\ faults = _TETrace[1].faults
    /\ fsDesc = _TETrace[1].fsDesc
    /\ nonceMap = _TETrace[1].nonceMap
    /\ initialized = _TETrace[1].initialized
    /\ procRun = _TETrace[1].procRun
    /\ procMeta = _TETrace[1].procMeta
    /\ cacheDesc = _TETrace[1].cacheDesc
    /\ nextProcId = _TETrace[1].nextProcId
    /\ nextNonce = _TETrace[1].nextNonce
    /\ client = _TETrace[1].client
    /\ masterUp = _TETrace[1].masterUp
    /\ procedures = _TETrace[1].procedures
    /\ procLatch = _TETrace[1].procLatch
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ epoch  = _TETrace[i].epoch
        /\ epoch' = _TETrace[j].epoch
        /\ completed  = _TETrace[i].completed
        /\ completed' = _TETrace[j].completed
        /\ cacheValid  = _TETrace[i].cacheValid
        /\ cacheValid' = _TETrace[j].cacheValid
        /\ attempts  = _TETrace[i].attempts
        /\ attempts' = _TETrace[j].attempts
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ fsWriters  = _TETrace[i].fsWriters
        /\ fsWriters' = _TETrace[j].fsWriters
        /\ procStored  = _TETrace[i].procStored
        /\ procStored' = _TETrace[j].procStored
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ fsDesc  = _TETrace[i].fsDesc
        /\ fsDesc' = _TETrace[j].fsDesc
        /\ nonceMap  = _TETrace[i].nonceMap
        /\ nonceMap' = _TETrace[j].nonceMap
        /\ initialized  = _TETrace[i].initialized
        /\ initialized' = _TETrace[j].initialized
        /\ procRun  = _TETrace[i].procRun
        /\ procRun' = _TETrace[j].procRun
        /\ procMeta  = _TETrace[i].procMeta
        /\ procMeta' = _TETrace[j].procMeta
        /\ cacheDesc  = _TETrace[i].cacheDesc
        /\ cacheDesc' = _TETrace[j].cacheDesc
        /\ nextProcId  = _TETrace[i].nextProcId
        /\ nextProcId' = _TETrace[j].nextProcId
        /\ nextNonce  = _TETrace[i].nextNonce
        /\ nextNonce' = _TETrace[j].nextNonce
        /\ client  = _TETrace[i].client
        /\ client' = _TETrace[j].client
        /\ masterUp  = _TETrace[i].masterUp
        /\ masterUp' = _TETrace[j].masterUp
        /\ procedures  = _TETrace[i].procedures
        /\ procedures' = _TETrace[j].procedures
        /\ procLatch  = _TETrace[i].procLatch
        /\ procLatch' = _TETrace[j].procLatch

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
        epoch |-> epoch
        ,completed |-> completed
        ,cacheValid |-> cacheValid
        ,attempts |-> attempts
        ,targetFired |-> targetFired
        ,fsWriters |-> fsWriters
        ,procStored |-> procStored
        ,faults |-> faults
        ,fsDesc |-> fsDesc
        ,nonceMap |-> nonceMap
        ,initialized |-> initialized
        ,procRun |-> procRun
        ,procMeta |-> procMeta
        ,cacheDesc |-> cacheDesc
        ,nextProcId |-> nextProcId
        ,nextNonce |-> nextNonce
        ,client |-> client
        ,masterUp |-> masterUp
        ,procedures |-> procedures
        ,procLatch |-> procLatch
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_epochUnchanged |-> epoch = epoch'
        
        \* Format the `epoch` variable as Json value.
        \* ,_epochJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(epoch)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_epochModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].epoch # _TETrace[s-1].epoch
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
    ([nonceMap |-> <<0, 0, 0>>,procStored |-> <<"None", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 1,nextProcId |-> 1,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"None", "None", "None">>,client |-> [pc |-> "Ready", tries |-> 0, nonce |-> 0, op |-> 1, cur |-> 0, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<>>]),
    ([nonceMap |-> <<0, 0, 0>>,procStored |-> <<"None", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 1,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"None", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<[hpc |-> "Queued", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<0, 0, 0>>,procStored |-> <<"None", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 1,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"None", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<[hpc |-> "Started", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<0, 0, 0>>,procStored |-> <<"None", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 1,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"None", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<[hpc |-> "Checked", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"None", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"None", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<[hpc |-> "Run", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"PREPARE", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<1, 0, 0>>,initialized |-> TRUE,procRun |-> <<"PREPARE", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<[hpc |-> "Awaiting", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"PRE_OPERATION", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<1, 0, 0>>,initialized |-> TRUE,procRun |-> <<"PRE_OPERATION", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<[hpc |-> "Awaiting", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<1, 0, 0>>,initialized |-> TRUE,procRun |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {},fsDesc |-> {"cf0"},attempts |-> <<[hpc |-> "Awaiting", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 1,cacheDesc |-> {"cf0"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 0],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<1, 0, 0>>,initialized |-> TRUE,procRun |-> <<"UD_FS_WRITTEN", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Awaiting", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<0, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 1,cacheDesc |-> {},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 1],cacheValid |-> FALSE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> FALSE,procedures |-> {},procLatch |-> <<0, 0, 0>>,initialized |-> FALSE,procRun |-> <<"None", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<0, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 1,cacheDesc |-> {},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 1],cacheValid |-> FALSE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> FALSE,procedures |-> {},procLatch |-> <<0, 0, 0>>,initialized |-> FALSE,procRun |-> <<"None", "None", "None">>,client |-> [pc |-> "Ready", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 2,nextProcId |-> 2,epoch |-> 2,cacheDesc |-> {"cf0", "cf1"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 1],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<0, 0, 0>>,initialized |-> FALSE,procRun |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,client |-> [pc |-> "Ready", tries |-> 1, nonce |-> 1, op |-> 1, cur |-> 1, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 3,nextProcId |-> 2,epoch |-> 2,cacheDesc |-> {"cf0", "cf1"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 1],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<0, 0, 0>>,initialized |-> FALSE,procRun |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 2, nonce |-> 2, op |-> 1, cur |-> 2, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE], [hpc |-> "Queued", epoch |-> 2, nonce |-> 2, op |-> 1, fam |-> "cf1", old |-> {}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 3,nextProcId |-> 2,epoch |-> 2,cacheDesc |-> {"cf0", "cf1"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 1],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 2, nonce |-> 2, op |-> 1, cur |-> 2, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE], [hpc |-> "Queued", epoch |-> 2, nonce |-> 2, op |-> 1, fam |-> "cf1", old |-> {}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> FALSE,nextNonce |-> 3,nextProcId |-> 2,epoch |-> 2,cacheDesc |-> {"cf0", "cf1"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 1],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 2, nonce |-> 2, op |-> 1, cur |-> 2, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE], [hpc |-> "Started", epoch |-> 2, nonce |-> 2, op |-> 1, fam |-> "cf1", old |-> {}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>]),
    ([nonceMap |-> <<1, 0, 0>>,procStored |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,targetFired |-> TRUE,nextNonce |-> 3,nextProcId |-> 2,epoch |-> 2,cacheDesc |-> {"cf0", "cf1"},completed |-> {},faults |-> [timeouts |-> 0, lost |-> 0, crashes |-> 1],cacheValid |-> TRUE,procMeta |-> <<[newDesc |-> {"cf0", "cf1"}, nonce |-> 1, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE], [newDesc |-> {}, nonce |-> 0, deleteCF |-> FALSE]>>,masterUp |-> TRUE,procedures |-> {1},procLatch |-> <<0, 0, 0>>,initialized |-> TRUE,procRun |-> <<"UPDATE_TABLE_DESCRIPTOR", "None", "None">>,client |-> [pc |-> "Waiting", tries |-> 2, nonce |-> 2, op |-> 1, cur |-> 2, resultProc |-> 0],fsWriters |-> {1},fsDesc |-> {"cf0", "cf1"},attempts |-> <<[hpc |-> "Gone", epoch |-> 1, nonce |-> 1, op |-> 1, fam |-> "cf1", old |-> {"cf0"}, procId |-> 1, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE], [hpc |-> "Started", epoch |-> 2, nonce |-> 2, op |-> 1, fam |-> "cf1", old |-> {}, procId |-> 0, reply |-> "none", abandoned |-> FALSE, latchReleased |-> FALSE]>>])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187161 ----
CONSTANTS
    InitFams = { "cf0" }
    FamilySeq <- MCFamilySeq
    MaxAttempts = 3
    SameNonceOnRetry = FALSE
    TableEnabled = FALSE
    PreloadTableDescriptors = TRUE
    MaxTimeouts = 0
    MaxLostReplies = 0
    MaxCrashes = 1

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