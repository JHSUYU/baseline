---- MODULE MCGuided_TTrace_1794187168 ----
EXTENDS Sequences, MCGuided_TEConstants, TLCExt, Toolbox, MCGuided, Naturals, TLC

_expression ==
    LET MCGuided_TEExpression == INSTANCE MCGuided_TEExpression
    IN MCGuided_TEExpression!expression
----

_trace ==
    LET MCGuided_TETrace == INSTANCE MCGuided_TETrace
    IN MCGuided_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        astate = ((d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")))
        /\
        role = ((n1 :> "active"))
        /\
        targetFired = (TRUE)
        /\
        dnKeys = ((d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}))
        /\
        nextOp = (2)
        /\
        act = ((d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")))
        /\
        known = ((n1 :> {d1, d2, d3}))
        /\
        reg = ((n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])))
        /\
        mc = ([rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0])
        /\
        cliDek = (2)
        /\
        regCurFromStandby = ((d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE))
        /\
        term = (1)
        /\
        xferQ = ((n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)))
        /\
        markPending = ((n1 :> FALSE))
        /\
        live = ((n1 :> {d1, d2, d3}))
        /\
        nnCur = ((n1 :> 2))
        /\
        dnCur = ((d1 :> 1 @@ d2 :> 1 @@ d3 :> 1))
        /\
        fireInfo = ([kid |-> 2, sk |-> 1, k |-> "write", rsr |-> d1, dn |-> d2])
        /\
        actTerm = ((n1 :> 1))
        /\
        keyOwner = (<<n1, n1, n1>>)
        /\
        nnKeys = ((n1 :> {1, 2, 3}))
        /\
        needKU = ((n1 :> {d1, d2, d3}))
        /\
        ops = ({[ph |-> "check", pipe |-> <<d1, d2>>, pos |-> 2, k |-> "write", tok |-> [kid |-> 2, sk |-> 1, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> 1]})
        /\
        lastClaim = ((d1 :> 1 @@ d2 :> 1 @@ d3 :> 1))
        /\
        bpActive = ((d1 :> n1 @@ d2 :> n1 @@ d3 :> n1))
        /\
        nnEp = ((n1 :> 1))
        /\
        cmdQ = ((d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)))
        /\
        hb = ((n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])))
        /\
        nnNext = ((n1 :> 3))
        /\
        nnInc = ((n1 :> 1))
    )
----

_init ==
    /\ nnEp = _TETrace[1].nnEp
    /\ nnCur = _TETrace[1].nnCur
    /\ mc = _TETrace[1].mc
    /\ actTerm = _TETrace[1].actTerm
    /\ targetFired = _TETrace[1].targetFired
    /\ nnNext = _TETrace[1].nnNext
    /\ dnCur = _TETrace[1].dnCur
    /\ cliDek = _TETrace[1].cliDek
    /\ bpActive = _TETrace[1].bpActive
    /\ astate = _TETrace[1].astate
    /\ cmdQ = _TETrace[1].cmdQ
    /\ markPending = _TETrace[1].markPending
    /\ needKU = _TETrace[1].needKU
    /\ reg = _TETrace[1].reg
    /\ fireInfo = _TETrace[1].fireInfo
    /\ nnInc = _TETrace[1].nnInc
    /\ dnKeys = _TETrace[1].dnKeys
    /\ xferQ = _TETrace[1].xferQ
    /\ regCurFromStandby = _TETrace[1].regCurFromStandby
    /\ hb = _TETrace[1].hb
    /\ act = _TETrace[1].act
    /\ known = _TETrace[1].known
    /\ term = _TETrace[1].term
    /\ role = _TETrace[1].role
    /\ live = _TETrace[1].live
    /\ nextOp = _TETrace[1].nextOp
    /\ ops = _TETrace[1].ops
    /\ keyOwner = _TETrace[1].keyOwner
    /\ nnKeys = _TETrace[1].nnKeys
    /\ lastClaim = _TETrace[1].lastClaim
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ nnEp  = _TETrace[i].nnEp
        /\ nnEp' = _TETrace[j].nnEp
        /\ nnCur  = _TETrace[i].nnCur
        /\ nnCur' = _TETrace[j].nnCur
        /\ mc  = _TETrace[i].mc
        /\ mc' = _TETrace[j].mc
        /\ actTerm  = _TETrace[i].actTerm
        /\ actTerm' = _TETrace[j].actTerm
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ nnNext  = _TETrace[i].nnNext
        /\ nnNext' = _TETrace[j].nnNext
        /\ dnCur  = _TETrace[i].dnCur
        /\ dnCur' = _TETrace[j].dnCur
        /\ cliDek  = _TETrace[i].cliDek
        /\ cliDek' = _TETrace[j].cliDek
        /\ bpActive  = _TETrace[i].bpActive
        /\ bpActive' = _TETrace[j].bpActive
        /\ astate  = _TETrace[i].astate
        /\ astate' = _TETrace[j].astate
        /\ cmdQ  = _TETrace[i].cmdQ
        /\ cmdQ' = _TETrace[j].cmdQ
        /\ markPending  = _TETrace[i].markPending
        /\ markPending' = _TETrace[j].markPending
        /\ needKU  = _TETrace[i].needKU
        /\ needKU' = _TETrace[j].needKU
        /\ reg  = _TETrace[i].reg
        /\ reg' = _TETrace[j].reg
        /\ fireInfo  = _TETrace[i].fireInfo
        /\ fireInfo' = _TETrace[j].fireInfo
        /\ nnInc  = _TETrace[i].nnInc
        /\ nnInc' = _TETrace[j].nnInc
        /\ dnKeys  = _TETrace[i].dnKeys
        /\ dnKeys' = _TETrace[j].dnKeys
        /\ xferQ  = _TETrace[i].xferQ
        /\ xferQ' = _TETrace[j].xferQ
        /\ regCurFromStandby  = _TETrace[i].regCurFromStandby
        /\ regCurFromStandby' = _TETrace[j].regCurFromStandby
        /\ hb  = _TETrace[i].hb
        /\ hb' = _TETrace[j].hb
        /\ act  = _TETrace[i].act
        /\ act' = _TETrace[j].act
        /\ known  = _TETrace[i].known
        /\ known' = _TETrace[j].known
        /\ term  = _TETrace[i].term
        /\ term' = _TETrace[j].term
        /\ role  = _TETrace[i].role
        /\ role' = _TETrace[j].role
        /\ live  = _TETrace[i].live
        /\ live' = _TETrace[j].live
        /\ nextOp  = _TETrace[i].nextOp
        /\ nextOp' = _TETrace[j].nextOp
        /\ ops  = _TETrace[i].ops
        /\ ops' = _TETrace[j].ops
        /\ keyOwner  = _TETrace[i].keyOwner
        /\ keyOwner' = _TETrace[j].keyOwner
        /\ nnKeys  = _TETrace[i].nnKeys
        /\ nnKeys' = _TETrace[j].nnKeys
        /\ lastClaim  = _TETrace[i].lastClaim
        /\ lastClaim' = _TETrace[j].lastClaim

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MCGuided_TTrace_1794187168.json", _TETrace)

=============================================================================

 Note that you can extract this module `MCGuided_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `MCGuided_TEExpression.tla` file takes precedence 
  over the module `MCGuided_TEExpression` below).

---- MODULE MCGuided_TEExpression ----
EXTENDS Sequences, MCGuided_TEConstants, TLCExt, Toolbox, MCGuided, Naturals, TLC

expression == 
    [
        \* To hide variables of the `MCGuided` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        nnEp |-> nnEp
        ,nnCur |-> nnCur
        ,mc |-> mc
        ,actTerm |-> actTerm
        ,targetFired |-> targetFired
        ,nnNext |-> nnNext
        ,dnCur |-> dnCur
        ,cliDek |-> cliDek
        ,bpActive |-> bpActive
        ,astate |-> astate
        ,cmdQ |-> cmdQ
        ,markPending |-> markPending
        ,needKU |-> needKU
        ,reg |-> reg
        ,fireInfo |-> fireInfo
        ,nnInc |-> nnInc
        ,dnKeys |-> dnKeys
        ,xferQ |-> xferQ
        ,regCurFromStandby |-> regCurFromStandby
        ,hb |-> hb
        ,act |-> act
        ,known |-> known
        ,term |-> term
        ,role |-> role
        ,live |-> live
        ,nextOp |-> nextOp
        ,ops |-> ops
        ,keyOwner |-> keyOwner
        ,nnKeys |-> nnKeys
        ,lastClaim |-> lastClaim
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_nnEpUnchanged |-> nnEp = nnEp'
        
        \* Format the `nnEp` variable as Json value.
        \* ,_nnEpJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(nnEp)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_nnEpModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].nnEp # _TETrace[s-1].nnEp
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE MCGuided_TETrace ----
\*EXTENDS IOUtils, MCGuided_TEConstants, MCGuided, TLC
\*
\*trace == IODeserialize("MCGuided_TTrace_1794187168.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MCGuided_TETrace ----
EXTENDS MCGuided_TEConstants, MCGuided, TLC

trace == 
    <<
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 1,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 0, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 0, r |-> 0, x |-> 0],cliDek |-> None,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 1),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1>>,nnKeys |-> (n1 :> {1, 2}),needKU |-> (n1 :> {}),ops |-> {},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 0),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 2),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 1,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 0, r |-> 0, x |-> 0],cliDek |-> None,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> TRUE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {}),ops |-> {},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 1,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 0, r |-> 0, x |-> 0],cliDek |-> None,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> None,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "connect", pipe |-> <<d1, d2>>, pos |-> 0, k |-> "write", tok |-> [kid |-> 2, sk |-> 2, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> None]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "connect", pipe |-> <<d1, d2>>, pos |-> 0, k |-> "write", tok |-> [kid |-> 2, sk |-> 2, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> None]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "sasl", pipe |-> <<d1, d2>>, pos |-> 1, k |-> "write", tok |-> [kid |-> 2, sk |-> 2, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> 2]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "check", pipe |-> <<d1, d2>>, pos |-> 1, k |-> "write", tok |-> [kid |-> 2, sk |-> 2, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> 2]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "mirror", pipe |-> <<d1, d2>>, pos |-> 1, k |-> "write", tok |-> [kid |-> 2, sk |-> 2, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> 2]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "dek", pipe |-> <<d1, d2>>, pos |-> 1, k |-> "write", tok |-> [kid |-> 2, sk |-> 2, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> 1, dek |-> 2]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "sasl", pipe |-> <<d1, d2>>, pos |-> 2, k |-> "write", tok |-> [kid |-> 2, sk |-> 1, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> 1]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> FALSE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> None, sk |-> None, k |-> None, rsr |-> None, dn |-> None],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "check", pipe |-> <<d1, d2>>, pos |-> 2, k |-> "write", tok |-> [kid |-> 2, sk |-> 1, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> 1]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)]),
    ([astate |-> (d1 :> (n1 :> "active") @@ d2 :> (n1 :> "active") @@ d3 :> (n1 :> "active")),role |-> (n1 :> "active"),targetFired |-> TRUE,dnKeys |-> (d1 :> {1, 2} @@ d2 :> {1, 2} @@ d3 :> {1, 2}),nextOp |-> 2,act |-> (d1 :> (n1 :> "run") @@ d2 :> (n1 :> "run") @@ d3 :> (n1 :> "run")),known |-> (n1 :> {d1, d2, d3}),reg |-> (n1 :> (d1 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d2 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]] @@ d3 :> [st |-> "none", ex |-> [cur |-> None, keys |-> {}]])),mc |-> [rot |-> 1, fo |-> 0, rs |-> 0, dead |-> 0, w |-> 1, r |-> 0, x |-> 0],cliDek |-> 2,regCurFromStandby |-> (d1 :> FALSE @@ d2 :> FALSE @@ d3 :> FALSE),term |-> 1,xferQ |-> (n1 :> (d1 :> <<>> @@ d2 :> <<>> @@ d3 :> <<>>)),markPending |-> (n1 :> FALSE),live |-> (n1 :> {d1, d2, d3}),nnCur |-> (n1 :> 2),dnCur |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),fireInfo |-> [kid |-> 2, sk |-> 1, k |-> "write", rsr |-> d1, dn |-> d2],actTerm |-> (n1 :> 1),keyOwner |-> <<n1, n1, n1>>,nnKeys |-> (n1 :> {1, 2, 3}),needKU |-> (n1 :> {d1, d2, d3}),ops |-> {[ph |-> "check", pipe |-> <<d1, d2>>, pos |-> 2, k |-> "write", tok |-> [kid |-> 2, sk |-> 1, iss |-> n1, inc |-> 1, ep |-> 1], src |-> "client", id |-> 1, sec |-> None, dek |-> 1]},lastClaim |-> (d1 :> 1 @@ d2 :> 1 @@ d3 :> 1),bpActive |-> (d1 :> n1 @@ d2 :> n1 @@ d3 :> n1),nnEp |-> (n1 :> 1),cmdQ |-> (d1 :> (n1 :> <<>>) @@ d2 :> (n1 :> <<>>) @@ d3 :> (n1 :> <<>>)),hb |-> (n1 :> (d1 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d2 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0] @@ d3 :> [reg |-> FALSE, st |-> "idle", ku |-> [cur |-> None, keys |-> {}], xfer |-> <<>>, ha |-> "standby", tm |-> 0])),nnNext |-> (n1 :> 3),nnInc |-> (n1 :> 1)])
    >>
----


=============================================================================

---- MODULE MCGuided_TEConstants ----
EXTENDS MCGuided

CONSTANTS n1, d1, d2, d3

=============================================================================

---- CONFIG MCGuided_TTrace_1794187168 ----
CONSTANTS
    NN = { n1 }
    DN = { d1 , d2 , d3 }
    InitActive = n1
    None = None
    OverwriteQOP = TRUE
    Repl = 2
    XferTargets = 2
    StartRegistered = TRUE
    SkipNoopHeartbeats = TRUE
    MaxRotations = 1
    MaxFailovers = 0
    MaxRestarts = 0
    MaxDeadNodes = 0
    MaxXfers = 0
    MaxWrites = 1
    MaxReads = 0
    n1 = n1
    d2 = d2
    None = None
    d1 = d1
    d3 = d3

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
\* Generated on Mon Nov 09 01:19:29 UTC 2026