---- MODULE MCGated_TTrace_1793568009 ----
EXTENDS MCGated_TEConstants, Sequences, TLCExt, Toolbox, MCGated, Naturals, TLC

_expression ==
    LET MCGated_TEExpression == INSTANCE MCGated_TEExpression
    IN MCGated_TEExpression!expression
----

_trace ==
    LET MCGated_TETrace == INSTANCE MCGated_TETrace
    IN MCGated_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        dnQ = ((n1 :> (d1 :> <<>>)))
        /\
        targetFired = (TRUE)
        /\
        nnSafe = ((n1 :> "off"))
        /\
        dnKeys = ((d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}))
        /\
        cDek = ([key |-> <<n1, 1, 3>>, iss |-> n1, r0 |-> 2])
        /\
        nnHA = ((n1 :> "active"))
        /\
        firstPass = ((n1 :> FALSE))
        /\
        faults = ([safe |-> 0, lost |-> 1, nnrst |-> 0, dnrst |-> 0, fo |-> 0])
        /\
        brDone = ((n1 :> (d1 :> TRUE)))
        /\
        reReg = ((n1 :> (d1 :> FALSE)))
        /\
        reg = ((n1 :> (d1 :> Null)))
        /\
        haEpoch = (1)
        /\
        dnCur = ((d1 :> <<n1, 1, 1>>))
        /\
        resp = ((n1 :> (d1 :> Null)))
        /\
        sweepPending = ((n1 :> TRUE))
        /\
        dnUp = ((d1 :> TRUE))
        /\
        bpState = ((d1 :> "keyed"))
        /\
        actorState = ((n1 :> (d1 :> "active")))
        /\
        rolls = ((n1 :> 2))
        /\
        hbSet = ((n1 :> {d1}))
        /\
        actor = ((n1 :> (d1 :> "reg")))
        /\
        needKU = ((n1 :> (d1 :> FALSE)))
        /\
        nnTop = ((n1 :> 4))
        /\
        lastClaim = ((d1 :> 0))
        /\
        bpActive = ((d1 :> n1))
        /\
        nnInc = ((n1 :> 1))
    )
----

_init ==
    /\ dnQ = _TETrace[1].dnQ
    /\ rolls = _TETrace[1].rolls
    /\ nnHA = _TETrace[1].nnHA
    /\ targetFired = _TETrace[1].targetFired
    /\ nnTop = _TETrace[1].nnTop
    /\ actor = _TETrace[1].actor
    /\ dnCur = _TETrace[1].dnCur
    /\ sweepPending = _TETrace[1].sweepPending
    /\ bpActive = _TETrace[1].bpActive
    /\ resp = _TETrace[1].resp
    /\ haEpoch = _TETrace[1].haEpoch
    /\ faults = _TETrace[1].faults
    /\ needKU = _TETrace[1].needKU
    /\ reReg = _TETrace[1].reReg
    /\ reg = _TETrace[1].reg
    /\ dnUp = _TETrace[1].dnUp
    /\ nnInc = _TETrace[1].nnInc
    /\ dnKeys = _TETrace[1].dnKeys
    /\ firstPass = _TETrace[1].firstPass
    /\ nnSafe = _TETrace[1].nnSafe
    /\ cDek = _TETrace[1].cDek
    /\ actorState = _TETrace[1].actorState
    /\ bpState = _TETrace[1].bpState
    /\ hbSet = _TETrace[1].hbSet
    /\ brDone = _TETrace[1].brDone
    /\ lastClaim = _TETrace[1].lastClaim
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ dnQ  = _TETrace[i].dnQ
        /\ dnQ' = _TETrace[j].dnQ
        /\ rolls  = _TETrace[i].rolls
        /\ rolls' = _TETrace[j].rolls
        /\ nnHA  = _TETrace[i].nnHA
        /\ nnHA' = _TETrace[j].nnHA
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ nnTop  = _TETrace[i].nnTop
        /\ nnTop' = _TETrace[j].nnTop
        /\ actor  = _TETrace[i].actor
        /\ actor' = _TETrace[j].actor
        /\ dnCur  = _TETrace[i].dnCur
        /\ dnCur' = _TETrace[j].dnCur
        /\ sweepPending  = _TETrace[i].sweepPending
        /\ sweepPending' = _TETrace[j].sweepPending
        /\ bpActive  = _TETrace[i].bpActive
        /\ bpActive' = _TETrace[j].bpActive
        /\ resp  = _TETrace[i].resp
        /\ resp' = _TETrace[j].resp
        /\ haEpoch  = _TETrace[i].haEpoch
        /\ haEpoch' = _TETrace[j].haEpoch
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ needKU  = _TETrace[i].needKU
        /\ needKU' = _TETrace[j].needKU
        /\ reReg  = _TETrace[i].reReg
        /\ reReg' = _TETrace[j].reReg
        /\ reg  = _TETrace[i].reg
        /\ reg' = _TETrace[j].reg
        /\ dnUp  = _TETrace[i].dnUp
        /\ dnUp' = _TETrace[j].dnUp
        /\ nnInc  = _TETrace[i].nnInc
        /\ nnInc' = _TETrace[j].nnInc
        /\ dnKeys  = _TETrace[i].dnKeys
        /\ dnKeys' = _TETrace[j].dnKeys
        /\ firstPass  = _TETrace[i].firstPass
        /\ firstPass' = _TETrace[j].firstPass
        /\ nnSafe  = _TETrace[i].nnSafe
        /\ nnSafe' = _TETrace[j].nnSafe
        /\ cDek  = _TETrace[i].cDek
        /\ cDek' = _TETrace[j].cDek
        /\ actorState  = _TETrace[i].actorState
        /\ actorState' = _TETrace[j].actorState
        /\ bpState  = _TETrace[i].bpState
        /\ bpState' = _TETrace[j].bpState
        /\ hbSet  = _TETrace[i].hbSet
        /\ hbSet' = _TETrace[j].hbSet
        /\ brDone  = _TETrace[i].brDone
        /\ brDone' = _TETrace[j].brDone
        /\ lastClaim  = _TETrace[i].lastClaim
        /\ lastClaim' = _TETrace[j].lastClaim

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MCGated_TTrace_1793568009.json", _TETrace)

=============================================================================

 Note that you can extract this module `MCGated_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `MCGated_TEExpression.tla` file takes precedence 
  over the module `MCGated_TEExpression` below).

---- MODULE MCGated_TEExpression ----
EXTENDS MCGated_TEConstants, Sequences, TLCExt, Toolbox, MCGated, Naturals, TLC

expression == 
    [
        \* To hide variables of the `MCGated` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        dnQ |-> dnQ
        ,rolls |-> rolls
        ,nnHA |-> nnHA
        ,targetFired |-> targetFired
        ,nnTop |-> nnTop
        ,actor |-> actor
        ,dnCur |-> dnCur
        ,sweepPending |-> sweepPending
        ,bpActive |-> bpActive
        ,resp |-> resp
        ,haEpoch |-> haEpoch
        ,faults |-> faults
        ,needKU |-> needKU
        ,reReg |-> reReg
        ,reg |-> reg
        ,dnUp |-> dnUp
        ,nnInc |-> nnInc
        ,dnKeys |-> dnKeys
        ,firstPass |-> firstPass
        ,nnSafe |-> nnSafe
        ,cDek |-> cDek
        ,actorState |-> actorState
        ,bpState |-> bpState
        ,hbSet |-> hbSet
        ,brDone |-> brDone
        ,lastClaim |-> lastClaim
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_dnQUnchanged |-> dnQ = dnQ'
        
        \* Format the `dnQ` variable as Json value.
        \* ,_dnQJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(dnQ)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_dnQModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].dnQ # _TETrace[s-1].dnQ
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE MCGated_TETrace ----
\*EXTENDS MCGated_TEConstants, IOUtils, MCGated, TLC
\*
\*trace == IODeserialize("MCGated_TTrace_1793568009.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MCGated_TETrace ----
EXTENDS MCGated_TEConstants, MCGated, TLC

trace == 
    <<
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "startup"),dnKeys |-> (d1 :> {}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> TRUE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> FALSE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> Null),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "none"),actorState |-> (n1 :> (d1 :> "none")),rolls |-> (n1 :> 0),hbSet |-> (n1 :> {}),actor |-> (n1 :> (d1 :> "conn")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 2),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> Null),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "startup"),dnKeys |-> (d1 :> {}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> FALSE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> Null),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "none"),actorState |-> (n1 :> (d1 :> "none")),rolls |-> (n1 :> 0),hbSet |-> (n1 :> {}),actor |-> (n1 :> (d1 :> "conn")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 2),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> Null),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "startup"),dnKeys |-> (d1 :> {}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> FALSE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> [exp |-> [nn |-> n1, inc |-> 1, top |-> 2], ph |-> "replied"])),haEpoch |-> 1,dnCur |-> (d1 :> Null),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "none"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 0),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "conn")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 2),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "startup"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> FALSE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 0),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 2),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 0),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 2),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> TRUE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 1),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 3),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 1),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> TRUE)),nnTop |-> (n1 :> 3),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 0, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> [ha |-> "active", exp |-> [nn |-> n1, inc |-> 1, top |-> 3], cmd |-> "key", ep |-> 1])),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 1),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 3),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 1, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> FALSE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 1),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 3),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> Null,nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 1, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> TRUE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 2),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 4),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> FALSE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> [key |-> <<n1, 1, 3>>, iss |-> n1, r0 |-> 2],nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 1, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> TRUE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 2),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 4),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)]),
    ([dnQ |-> (n1 :> (d1 :> <<>>)),targetFired |-> TRUE,nnSafe |-> (n1 :> "off"),dnKeys |-> (d1 :> {<<n1, 1, 1>>, <<n1, 1, 2>>}),cDek |-> [key |-> <<n1, 1, 3>>, iss |-> n1, r0 |-> 2],nnHA |-> (n1 :> "active"),firstPass |-> (n1 :> FALSE),faults |-> [safe |-> 0, lost |-> 1, nnrst |-> 0, dnrst |-> 0, fo |-> 0],brDone |-> (n1 :> (d1 :> TRUE)),reReg |-> (n1 :> (d1 :> FALSE)),reg |-> (n1 :> (d1 :> Null)),haEpoch |-> 1,dnCur |-> (d1 :> <<n1, 1, 1>>),resp |-> (n1 :> (d1 :> Null)),sweepPending |-> (n1 :> TRUE),dnUp |-> (d1 :> TRUE),bpState |-> (d1 :> "keyed"),actorState |-> (n1 :> (d1 :> "active")),rolls |-> (n1 :> 2),hbSet |-> (n1 :> {d1}),actor |-> (n1 :> (d1 :> "reg")),needKU |-> (n1 :> (d1 :> FALSE)),nnTop |-> (n1 :> 4),lastClaim |-> (d1 :> 0),bpActive |-> (d1 :> n1),nnInc |-> (n1 :> 1)])
    >>
----


=============================================================================

---- MODULE MCGated_TEConstants ----
EXTENDS MCGated

CONSTANTS n1, d1

=============================================================================

---- CONFIG MCGated_TTrace_1793568009 ----
CONSTANTS
    NNs = { n1 }
    DNs = { d1 }
    FirstActive = n1
    LateDNs = { }
    SplitRegistration = FALSE
    DekFromStandby = FALSE
    DnTransferOn = FALSE
    StartSafeModes = { "startup" , "off" }
    Null = Null
    MaxRolls = 2
    MaxSafeModeEnter = 0
    MaxLostResp = 1
    MaxNNRestart = 0
    MaxDNRestart = 0
    MaxFailover = 0
    SafeModeRoles = { "active" }
    LossRoles = { "active" }
    DekNeedsRegisteredDNs = FALSE
    MaxQueue = 2
    n1 = n1
    Null = Null
    d1 = d1

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
\* Generated on Sun Nov 01 21:20:10 UTC 2026