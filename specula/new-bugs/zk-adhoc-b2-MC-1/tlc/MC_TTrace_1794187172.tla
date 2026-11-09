---- MODULE MC_TTrace_1794187172 ----
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
        offers = ({1, 2})
        /\
        etP = ((s1 :> NoP))
        /\
        owner = ((0 :> s1 @@ 1 :> s1 @@ 2 :> s1))
        /\
        creator = ((0 :> p1 @@ 1 :> p2 @@ 2 :> p3))
        /\
        etQ = ((s1 :> <<[id |-> 0, ws |-> {p2}]>>))
        /\
        toRead = (([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {1, 2} @@ [kind |-> "ET", id |-> s1] :> {}))
        /\
        alive = ((s1 :> TRUE))
        /\
        rcv = (([kind |-> "W", id |-> p1] :> [id |-> 0, op |-> "delete", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> 0, op |-> "getData", err |-> "NONODE", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]))
        /\
        reqQ = ((s1 :> <<>>))
        /\
        targetFired = (TRUE)
        /\
        lateStarts = ({p3})
        /\
        expiries = (0)
        /\
        ownId = ((p1 :> 0 @@ p2 :> 1 @@ p3 :> 2))
        /\
        pc = (([kind |-> "W", id |-> p1] :> "w_delete" @@ [kind |-> "W", id |-> p2] :> "sleep" @@ [kind |-> "W", id |-> p3] :> "det_data" @@ [kind |-> "ET", id |-> s1] :> "et_idle"))
        /\
        lstate = ((p1 :> "STOP" @@ p2 :> "READY" @@ p3 :> "DETERMINE"))
        /\
        srvW = ((0 :> {} @@ 1 :> {} @@ 2 :> {}))
        /\
        removedBy = ((0 :> "delete" @@ 1 :> "none" @@ 2 :> "none"))
        /\
        cliW = ((s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})))
        /\
        stopSkew = (0)
        /\
        firedBy = ("peerStop")
        /\
        nextSeq = (3)
        /\
        listing = (([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {0, 1, 2} @@ [kind |-> "ET", id |-> s1] :> {}))
    )
----

_init ==
    /\ offers = _TETrace[1].offers
    /\ etP = _TETrace[1].etP
    /\ etQ = _TETrace[1].etQ
    /\ firedBy = _TETrace[1].firedBy
    /\ reqQ = _TETrace[1].reqQ
    /\ lateStarts = _TETrace[1].lateStarts
    /\ toRead = _TETrace[1].toRead
    /\ targetFired = _TETrace[1].targetFired
    /\ alive = _TETrace[1].alive
    /\ cliW = _TETrace[1].cliW
    /\ removedBy = _TETrace[1].removedBy
    /\ pc = _TETrace[1].pc
    /\ listing = _TETrace[1].listing
    /\ expiries = _TETrace[1].expiries
    /\ rcv = _TETrace[1].rcv
    /\ lstate = _TETrace[1].lstate
    /\ creator = _TETrace[1].creator
    /\ ownId = _TETrace[1].ownId
    /\ nextSeq = _TETrace[1].nextSeq
    /\ srvW = _TETrace[1].srvW
    /\ stopSkew = _TETrace[1].stopSkew
    /\ owner = _TETrace[1].owner
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ offers  = _TETrace[i].offers
        /\ offers' = _TETrace[j].offers
        /\ etP  = _TETrace[i].etP
        /\ etP' = _TETrace[j].etP
        /\ etQ  = _TETrace[i].etQ
        /\ etQ' = _TETrace[j].etQ
        /\ firedBy  = _TETrace[i].firedBy
        /\ firedBy' = _TETrace[j].firedBy
        /\ reqQ  = _TETrace[i].reqQ
        /\ reqQ' = _TETrace[j].reqQ
        /\ lateStarts  = _TETrace[i].lateStarts
        /\ lateStarts' = _TETrace[j].lateStarts
        /\ toRead  = _TETrace[i].toRead
        /\ toRead' = _TETrace[j].toRead
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ alive  = _TETrace[i].alive
        /\ alive' = _TETrace[j].alive
        /\ cliW  = _TETrace[i].cliW
        /\ cliW' = _TETrace[j].cliW
        /\ removedBy  = _TETrace[i].removedBy
        /\ removedBy' = _TETrace[j].removedBy
        /\ pc  = _TETrace[i].pc
        /\ pc' = _TETrace[j].pc
        /\ listing  = _TETrace[i].listing
        /\ listing' = _TETrace[j].listing
        /\ expiries  = _TETrace[i].expiries
        /\ expiries' = _TETrace[j].expiries
        /\ rcv  = _TETrace[i].rcv
        /\ rcv' = _TETrace[j].rcv
        /\ lstate  = _TETrace[i].lstate
        /\ lstate' = _TETrace[j].lstate
        /\ creator  = _TETrace[i].creator
        /\ creator' = _TETrace[j].creator
        /\ ownId  = _TETrace[i].ownId
        /\ ownId' = _TETrace[j].ownId
        /\ nextSeq  = _TETrace[i].nextSeq
        /\ nextSeq' = _TETrace[j].nextSeq
        /\ srvW  = _TETrace[i].srvW
        /\ srvW' = _TETrace[j].srvW
        /\ stopSkew  = _TETrace[i].stopSkew
        /\ stopSkew' = _TETrace[j].stopSkew
        /\ owner  = _TETrace[i].owner
        /\ owner' = _TETrace[j].owner

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187172.json", _TETrace)

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
        offers |-> offers
        ,etP |-> etP
        ,etQ |-> etQ
        ,firedBy |-> firedBy
        ,reqQ |-> reqQ
        ,lateStarts |-> lateStarts
        ,toRead |-> toRead
        ,targetFired |-> targetFired
        ,alive |-> alive
        ,cliW |-> cliW
        ,removedBy |-> removedBy
        ,pc |-> pc
        ,listing |-> listing
        ,expiries |-> expiries
        ,rcv |-> rcv
        ,lstate |-> lstate
        ,creator |-> creator
        ,ownId |-> ownId
        ,nextSeq |-> nextSeq
        ,srvW |-> srvW
        ,stopSkew |-> stopSkew
        ,owner |-> owner
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_offersUnchanged |-> offers = offers'
        
        \* Format the `offers` variable as Json value.
        \* ,_offersJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(offers)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_offersModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].offers # _TETrace[s-1].offers
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
\*trace == IODeserialize("MC_TTrace_1794187172.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC, MC_TEConstants

trace == 
    <<
    ([offers |-> {},etP |-> (s1 :> NoP),owner |-> (0 :> NoSession @@ 1 :> NoSession @@ 2 :> NoSession),creator |-> (0 :> NoP @@ 1 :> NoP @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> -1 @@ p2 :> -1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "idle" @@ [kind |-> "W", id |-> p2] :> "idle" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "STOP" @@ p2 :> "STOP" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 0,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {},etP |-> (s1 :> NoP),owner |-> (0 :> NoSession @@ 1 :> NoSession @@ 2 :> NoSession),creator |-> (0 :> NoP @@ 1 :> NoP @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p1, id |-> -1, op |-> "create", t |-> [kind |-> "W", id |-> p1]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> -1 @@ p2 :> -1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "w_create" @@ [kind |-> "W", id |-> p2] :> "idle" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "OFFER" @@ p2 :> "STOP" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 0,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> NoSession @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> NoP @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> 0, op |-> "create", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> -1 @@ p2 :> -1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "w_create" @@ [kind |-> "W", id |-> p2] :> "idle" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "OFFER" @@ p2 :> "STOP" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 1,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> NoSession @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> NoP @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p1, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p1]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> -1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_children" @@ [kind |-> "W", id |-> p2] :> "idle" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "STOP" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 1,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> NoSession @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> NoP @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p1, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p1]], [p |-> p2, id |-> -1, op |-> "create", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> -1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_children" @@ [kind |-> "W", id |-> p2] :> "w_create" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "OFFER" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 1,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> NoSession @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> NoP @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> -1, op |-> "create", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> -1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_children" @@ [kind |-> "W", id |-> p2] :> "w_create" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "OFFER" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 1,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0}] @@ [kind |-> "W", id |-> p2] :> [id |-> 1, op |-> "create", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> -1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_children" @@ [kind |-> "W", id |-> p2] :> "w_create" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "OFFER" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 2,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_children" @@ [kind |-> "W", id |-> p2] :> "det_children" @@ [kind |-> "W", id |-> p3] :> "idle" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "STOP"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 2,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p2]], [p |-> p3, id |-> -1, op |-> "create", t |-> [kind |-> "W", id |-> p3]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_children" @@ [kind |-> "W", id |-> p2] :> "det_children" @@ [kind |-> "W", id |-> p3] :> "w_create" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "OFFER"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 2,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p2]], [p |-> p3, id |-> -1, op |-> "create", t |-> [kind |-> "W", id |-> p3]], [p |-> p1, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p1]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_data" @@ [kind |-> "W", id |-> p2] :> "det_children" @@ [kind |-> "W", id |-> p3] :> "w_create" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "OFFER"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 2,listing |-> ([kind |-> "W", id |-> p1] :> {0} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p3, id |-> -1, op |-> "create", t |-> [kind |-> "W", id |-> p3]], [p |-> p1, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p1]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_data" @@ [kind |-> "W", id |-> p2] :> "det_children" @@ [kind |-> "W", id |-> p3] :> "w_create" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "OFFER"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 2,listing |-> ([kind |-> "W", id |-> p1] :> {0} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> NoSession),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> NoP),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p3, id |-> -1, op |-> "create", t |-> [kind |-> "W", id |-> p3]], [p |-> p1, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p1]], [p |-> p2, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_data" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "w_create" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "OFFER"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 2,listing |-> ([kind |-> "W", id |-> p1] :> {0} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> 2, op |-> "create", err |-> "OK", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p1, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p1]], [p |-> p2, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> -1),pc |-> ([kind |-> "W", id |-> p1] :> "det_data" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "w_create" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "OFFER"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {0} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p1, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p1]], [p |-> p2, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p2]], [p |-> p3, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p3]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "det_data" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {0} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> 0, op |-> "getData", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p2]], [p |-> p3, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p3]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "det_data" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "DETERMINE" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {0} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p2]], [p |-> p3, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p3]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> 0, op |-> "getData", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p3, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p3]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p3, id |-> -1, op |-> "getChildren", t |-> [kind |-> "W", id |-> p3]], [p |-> p2, id |-> 1, op |-> "getData", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1, 2}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> 1, op |-> "getData", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> 1, op |-> "getData", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1, 2}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "det_data" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {0, 1} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1, 2}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p2, id |-> 0, op |-> "exists", t |-> [kind |-> "W", id |-> p2]]>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "det_exists" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> 0, op |-> "exists", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1, 2}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "det_exists" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "DETERMINE" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {s1} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {p2} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1, 2}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> FALSE,lateStarts |-> {},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "sleep" @@ [kind |-> "W", id |-> p2] :> "sleep" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "ELECTED" @@ p2 :> "READY" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {s1} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {p2} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1, 2}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> FALSE,lateStarts |-> {p3},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "w_stop" @@ [kind |-> "W", id |-> p2] :> "sleep" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "STOP" @@ p2 :> "READY" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {s1} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {p2} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "getChildren", err |-> "OK", kids |-> {0, 1, 2}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p1, id |-> 0, op |-> "delete", t |-> [kind |-> "W", id |-> p1]]>>),targetFired |-> FALSE,lateStarts |-> {p3},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "w_delete" @@ [kind |-> "W", id |-> p2] :> "sleep" @@ [kind |-> "W", id |-> p3] :> "det_children" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "STOP" @@ p2 :> "READY" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {s1} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {p2} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {0, 1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {1, 2} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p1, id |-> 0, op |-> "delete", t |-> [kind |-> "W", id |-> p1]], [p |-> p3, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p3]]>>),targetFired |-> FALSE,lateStarts |-> {p3},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "w_delete" @@ [kind |-> "W", id |-> p2] :> "sleep" @@ [kind |-> "W", id |-> p3] :> "det_data" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "STOP" @@ p2 :> "READY" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {s1} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "none" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {p2} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {0, 1, 2} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<[id |-> 0, ws |-> {p2}]>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {1, 2} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> 0, op |-> "delete", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<[p |-> p3, id |-> 0, op |-> "getData", t |-> [kind |-> "W", id |-> p3]]>>),targetFired |-> FALSE,lateStarts |-> {p3},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "w_delete" @@ [kind |-> "W", id |-> p2] :> "sleep" @@ [kind |-> "W", id |-> p3] :> "det_data" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "STOP" @@ p2 :> "READY" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "delete" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "none",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {0, 1, 2} @@ [kind |-> "ET", id |-> s1] :> {})]),
    ([offers |-> {1, 2},etP |-> (s1 :> NoP),owner |-> (0 :> s1 @@ 1 :> s1 @@ 2 :> s1),creator |-> (0 :> p1 @@ 1 :> p2 @@ 2 :> p3),etQ |-> (s1 :> <<[id |-> 0, ws |-> {p2}]>>),toRead |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {1, 2} @@ [kind |-> "ET", id |-> s1] :> {}),alive |-> (s1 :> TRUE),rcv |-> ([kind |-> "W", id |-> p1] :> [id |-> 0, op |-> "delete", err |-> "OK", kids |-> {}] @@ [kind |-> "W", id |-> p2] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}] @@ [kind |-> "W", id |-> p3] :> [id |-> 0, op |-> "getData", err |-> "NONODE", kids |-> {}] @@ [kind |-> "ET", id |-> s1] :> [id |-> -1, op |-> "none", err |-> "none", kids |-> {}]),reqQ |-> (s1 :> <<>>),targetFired |-> TRUE,lateStarts |-> {p3},expiries |-> 0,ownId |-> (p1 :> 0 @@ p2 :> 1 @@ p3 :> 2),pc |-> ([kind |-> "W", id |-> p1] :> "w_delete" @@ [kind |-> "W", id |-> p2] :> "sleep" @@ [kind |-> "W", id |-> p3] :> "det_data" @@ [kind |-> "ET", id |-> s1] :> "et_idle"),lstate |-> (p1 :> "STOP" @@ p2 :> "READY" @@ p3 :> "DETERMINE"),srvW |-> (0 :> {} @@ 1 :> {} @@ 2 :> {}),removedBy |-> (0 :> "delete" @@ 1 :> "none" @@ 2 :> "none"),cliW |-> (s1 :> (0 :> {} @@ 1 :> {} @@ 2 :> {})),stopSkew |-> 0,firedBy |-> "peerStop",nextSeq |-> 3,listing |-> ([kind |-> "W", id |-> p1] :> {} @@ [kind |-> "W", id |-> p2] :> {} @@ [kind |-> "W", id |-> p3] :> {0, 1, 2} @@ [kind |-> "ET", id |-> s1] :> {})])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS p1, p2, p3

=============================================================================

---- CONFIG MC_TTrace_1794187172 ----
CONSTANTS
    NoP = NoP
    NoSession = NoSession
    s1 = s1
    s2 = s2
    Participants = { p1 , p2 , p3 }
    Sessions = { s1 }
    SessionOf <- MCSessionOf
    SecondClient = { }
    ExpirableSessions = { }
    MaxLateStart = 1
    MaxStopSkew = 0
    MaxExpire = 0
    p2 = p2
    p3 = p3
    s2 = s2
    p1 = p1
    NoP = NoP
    NoSession = NoSession
    s1 = s1

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
\* Generated on Mon Nov 09 01:19:40 UTC 2026