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
        alive = ((n1 :> TRUE @@ n2 :> TRUE))
        /\
        session = ((n1 :> TRUE @@ n2 :> TRUE))
        /\
        targetFired = (TRUE)
        /\
        loopNow = ((n1 :> 0 @@ n2 :> 0))
        /\
        everHeld = ((n1 :> {1} @@ n2 :> {}))
        /\
        rollNow = ((n1 :> 0 @@ n2 :> 0))
        /\
        faults = ([tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0])
        /\
        cpPC = ((n1 :> "idle" @@ n2 :> "idle"))
        /\
        cpNow = ((n1 :> 0 @@ n2 :> 0))
        /\
        wLeader = ((n1 :> TRUE @@ n2 :> FALSE))
        /\
        wChild = ((n1 :> TRUE @@ n2 :> TRUE))
        /\
        gtime = (0)
        /\
        isMaster = ((n1 :> TRUE @@ n2 :> FALSE))
        /\
        epc = ((n1 :> "master" @@ n2 :> "started"))
        /\
        tokens = ({[keyId |-> 1, sec |-> n1, exp |-> 2, issuer |-> n1]})
        /\
        lpc = ((n1 :> "rollPublish" @@ n2 :> "none"))
        /\
        listening = ((n1 :> TRUE @@ n2 :> TRUE))
        /\
        evq = ((n1 :> <<>> @@ n2 :> <<>>))
        /\
        stopped = ((n1 :> FALSE @@ n2 :> FALSE))
        /\
        lastKeyUpdate = ((n1 :> -2 @@ n2 :> -2))
        /\
        leaderExists = ((n1 :> TRUE @@ n2 :> FALSE))
        /\
        allKeys = ((n1 :> <<[sec |-> n1, id |-> 1, exp |-> 99]>> @@ n2 :> <<>>))
        /\
        published = ({})
        /\
        wData = ((n1 :> {} @@ n2 :> {}))
        /\
        zkLeader = (n1)
        /\
        rollPrev = ((n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]))
        /\
        startList = ((n1 :> {} @@ n2 :> {}))
        /\
        currentKey = ((n1 :> [sec |-> n1, id |-> 1, exp |-> 99] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]))
        /\
        idSeq = ((n1 :> 1 @@ n2 :> 0))
        /\
        zkKeys = (<<>>)
        /\
        minted = ({<<1, n1>>})
        /\
        startFailed = ((n1 :> FALSE @@ n2 :> FALSE))
        /\
        startPC = ((n1 :> "done" @@ n2 :> "done"))
        /\
        skew = ((n1 :> 0 @@ n2 :> 0))
    )
----

_init ==
    /\ rollNow = _TETrace[1].rollNow
    /\ skew = _TETrace[1].skew
    /\ allKeys = _TETrace[1].allKeys
    /\ isMaster = _TETrace[1].isMaster
    /\ startPC = _TETrace[1].startPC
    /\ wChild = _TETrace[1].wChild
    /\ targetFired = _TETrace[1].targetFired
    /\ minted = _TETrace[1].minted
    /\ lastKeyUpdate = _TETrace[1].lastKeyUpdate
    /\ listening = _TETrace[1].listening
    /\ cpPC = _TETrace[1].cpPC
    /\ alive = _TETrace[1].alive
    /\ stopped = _TETrace[1].stopped
    /\ startFailed = _TETrace[1].startFailed
    /\ everHeld = _TETrace[1].everHeld
    /\ evq = _TETrace[1].evq
    /\ lpc = _TETrace[1].lpc
    /\ faults = _TETrace[1].faults
    /\ gtime = _TETrace[1].gtime
    /\ cpNow = _TETrace[1].cpNow
    /\ idSeq = _TETrace[1].idSeq
    /\ epc = _TETrace[1].epc
    /\ published = _TETrace[1].published
    /\ session = _TETrace[1].session
    /\ leaderExists = _TETrace[1].leaderExists
    /\ startList = _TETrace[1].startList
    /\ tokens = _TETrace[1].tokens
    /\ wData = _TETrace[1].wData
    /\ currentKey = _TETrace[1].currentKey
    /\ loopNow = _TETrace[1].loopNow
    /\ wLeader = _TETrace[1].wLeader
    /\ zkLeader = _TETrace[1].zkLeader
    /\ zkKeys = _TETrace[1].zkKeys
    /\ rollPrev = _TETrace[1].rollPrev
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ rollNow  = _TETrace[i].rollNow
        /\ rollNow' = _TETrace[j].rollNow
        /\ skew  = _TETrace[i].skew
        /\ skew' = _TETrace[j].skew
        /\ allKeys  = _TETrace[i].allKeys
        /\ allKeys' = _TETrace[j].allKeys
        /\ isMaster  = _TETrace[i].isMaster
        /\ isMaster' = _TETrace[j].isMaster
        /\ startPC  = _TETrace[i].startPC
        /\ startPC' = _TETrace[j].startPC
        /\ wChild  = _TETrace[i].wChild
        /\ wChild' = _TETrace[j].wChild
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ minted  = _TETrace[i].minted
        /\ minted' = _TETrace[j].minted
        /\ lastKeyUpdate  = _TETrace[i].lastKeyUpdate
        /\ lastKeyUpdate' = _TETrace[j].lastKeyUpdate
        /\ listening  = _TETrace[i].listening
        /\ listening' = _TETrace[j].listening
        /\ cpPC  = _TETrace[i].cpPC
        /\ cpPC' = _TETrace[j].cpPC
        /\ alive  = _TETrace[i].alive
        /\ alive' = _TETrace[j].alive
        /\ stopped  = _TETrace[i].stopped
        /\ stopped' = _TETrace[j].stopped
        /\ startFailed  = _TETrace[i].startFailed
        /\ startFailed' = _TETrace[j].startFailed
        /\ everHeld  = _TETrace[i].everHeld
        /\ everHeld' = _TETrace[j].everHeld
        /\ evq  = _TETrace[i].evq
        /\ evq' = _TETrace[j].evq
        /\ lpc  = _TETrace[i].lpc
        /\ lpc' = _TETrace[j].lpc
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ gtime  = _TETrace[i].gtime
        /\ gtime' = _TETrace[j].gtime
        /\ cpNow  = _TETrace[i].cpNow
        /\ cpNow' = _TETrace[j].cpNow
        /\ idSeq  = _TETrace[i].idSeq
        /\ idSeq' = _TETrace[j].idSeq
        /\ epc  = _TETrace[i].epc
        /\ epc' = _TETrace[j].epc
        /\ published  = _TETrace[i].published
        /\ published' = _TETrace[j].published
        /\ session  = _TETrace[i].session
        /\ session' = _TETrace[j].session
        /\ leaderExists  = _TETrace[i].leaderExists
        /\ leaderExists' = _TETrace[j].leaderExists
        /\ startList  = _TETrace[i].startList
        /\ startList' = _TETrace[j].startList
        /\ tokens  = _TETrace[i].tokens
        /\ tokens' = _TETrace[j].tokens
        /\ wData  = _TETrace[i].wData
        /\ wData' = _TETrace[j].wData
        /\ currentKey  = _TETrace[i].currentKey
        /\ currentKey' = _TETrace[j].currentKey
        /\ loopNow  = _TETrace[i].loopNow
        /\ loopNow' = _TETrace[j].loopNow
        /\ wLeader  = _TETrace[i].wLeader
        /\ wLeader' = _TETrace[j].wLeader
        /\ zkLeader  = _TETrace[i].zkLeader
        /\ zkLeader' = _TETrace[j].zkLeader
        /\ zkKeys  = _TETrace[i].zkKeys
        /\ zkKeys' = _TETrace[j].zkKeys
        /\ rollPrev  = _TETrace[i].rollPrev
        /\ rollPrev' = _TETrace[j].rollPrev

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
        rollNow |-> rollNow
        ,skew |-> skew
        ,allKeys |-> allKeys
        ,isMaster |-> isMaster
        ,startPC |-> startPC
        ,wChild |-> wChild
        ,targetFired |-> targetFired
        ,minted |-> minted
        ,lastKeyUpdate |-> lastKeyUpdate
        ,listening |-> listening
        ,cpPC |-> cpPC
        ,alive |-> alive
        ,stopped |-> stopped
        ,startFailed |-> startFailed
        ,everHeld |-> everHeld
        ,evq |-> evq
        ,lpc |-> lpc
        ,faults |-> faults
        ,gtime |-> gtime
        ,cpNow |-> cpNow
        ,idSeq |-> idSeq
        ,epc |-> epc
        ,published |-> published
        ,session |-> session
        ,leaderExists |-> leaderExists
        ,startList |-> startList
        ,tokens |-> tokens
        ,wData |-> wData
        ,currentKey |-> currentKey
        ,loopNow |-> loopNow
        ,wLeader |-> wLeader
        ,zkLeader |-> zkLeader
        ,zkKeys |-> zkKeys
        ,rollPrev |-> rollPrev
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_rollNowUnchanged |-> rollNow = rollNow'
        
        \* Format the `rollNow` variable as Json value.
        \* ,_rollNowJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(rollNow)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_rollNowModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].rollNow # _TETrace[s-1].rollNow
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
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> FALSE @@ n2 :> FALSE),wChild |-> (n1 :> FALSE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> FALSE @@ n2 :> FALSE),epc |-> (n1 :> "none" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "none" @@ n2 :> "none"),listening |-> (n1 :> FALSE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> FALSE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> None,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "createParents" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> FALSE @@ n2 :> FALSE),wChild |-> (n1 :> FALSE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> FALSE @@ n2 :> FALSE),epc |-> (n1 :> "none" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "none" @@ n2 :> "none"),listening |-> (n1 :> FALSE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> FALSE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> None,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "watchExists" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> FALSE @@ n2 :> FALSE),wChild |-> (n1 :> FALSE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> FALSE @@ n2 :> FALSE),epc |-> (n1 :> "none" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "none" @@ n2 :> "none"),listening |-> (n1 :> FALSE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> FALSE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> None,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "listChildren" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> FALSE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> FALSE @@ n2 :> FALSE),epc |-> (n1 :> "none" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "none" @@ n2 :> "none"),listening |-> (n1 :> FALSE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> FALSE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> None,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "readChildren" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> FALSE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> FALSE @@ n2 :> FALSE),epc |-> (n1 :> "started" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "none" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> FALSE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> None,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> FALSE @@ n2 :> FALSE),epc |-> (n1 :> "claimed" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "none" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "loop" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "removing" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 0, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "rollStart" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "clockRead" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "rollStart" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "createParents"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "clockRead" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "rollStart" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "watchExists"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "clockRead" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> FALSE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "rollStart" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "listChildren"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "clockRead" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> TRUE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "rollStart" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "readChildren"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "clockRead" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> TRUE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "rollInstall" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 0 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "readChildren"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {1} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "clockRead" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> TRUE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {},lpc |-> (n1 :> "rollPublish" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<[sec |-> n1, id |-> 1, exp |-> 99]>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> n1, id |-> 1, exp |-> 99] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 1 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {<<1, n1>>},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "readChildren"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {1} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> TRUE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "none"),tokens |-> {[keyId |-> 1, sec |-> n1, exp |-> 2, issuer |-> n1]},lpc |-> (n1 :> "rollPublish" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> FALSE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<[sec |-> n1, id |-> 1, exp |-> 99]>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> n1, id |-> 1, exp |-> 99] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 1 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {<<1, n1>>},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "readChildren"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> FALSE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {1} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> TRUE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "started"),tokens |-> {[keyId |-> 1, sec |-> n1, exp |-> 2, issuer |-> n1]},lpc |-> (n1 :> "rollPublish" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> TRUE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<[sec |-> n1, id |-> 1, exp |-> 99]>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> n1, id |-> 1, exp |-> 99] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 1 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {<<1, n1>>},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "done"),skew |-> (n1 :> 0 @@ n2 :> 0)]),
    ([alive |-> (n1 :> TRUE @@ n2 :> TRUE),session |-> (n1 :> TRUE @@ n2 :> TRUE),targetFired |-> TRUE,loopNow |-> (n1 :> 0 @@ n2 :> 0),everHeld |-> (n1 :> {1} @@ n2 :> {}),rollNow |-> (n1 :> 0 @@ n2 :> 0),faults |-> [tokens |-> 1, crash |-> 0, expire |-> 0, zkFail |-> 0, stop |-> 0, restart |-> 0],cpPC |-> (n1 :> "idle" @@ n2 :> "idle"),cpNow |-> (n1 :> 0 @@ n2 :> 0),wLeader |-> (n1 :> TRUE @@ n2 :> FALSE),wChild |-> (n1 :> TRUE @@ n2 :> TRUE),gtime |-> 0,isMaster |-> (n1 :> TRUE @@ n2 :> FALSE),epc |-> (n1 :> "master" @@ n2 :> "started"),tokens |-> {[keyId |-> 1, sec |-> n1, exp |-> 2, issuer |-> n1]},lpc |-> (n1 :> "rollPublish" @@ n2 :> "none"),listening |-> (n1 :> TRUE @@ n2 :> TRUE),evq |-> (n1 :> <<>> @@ n2 :> <<>>),stopped |-> (n1 :> FALSE @@ n2 :> FALSE),lastKeyUpdate |-> (n1 :> -2 @@ n2 :> -2),leaderExists |-> (n1 :> TRUE @@ n2 :> FALSE),allKeys |-> (n1 :> <<[sec |-> n1, id |-> 1, exp |-> 99]>> @@ n2 :> <<>>),published |-> {},wData |-> (n1 :> {} @@ n2 :> {}),zkLeader |-> n1,rollPrev |-> (n1 :> [sec |-> None, id |-> 0, exp |-> 0] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),startList |-> (n1 :> {} @@ n2 :> {}),currentKey |-> (n1 :> [sec |-> n1, id |-> 1, exp |-> 99] @@ n2 :> [sec |-> None, id |-> 0, exp |-> 0]),idSeq |-> (n1 :> 1 @@ n2 :> 0),zkKeys |-> <<>>,minted |-> {<<1, n1>>},startFailed |-> (n1 :> FALSE @@ n2 :> FALSE),startPC |-> (n1 :> "done" @@ n2 :> "done"),skew |-> (n1 :> 0 @@ n2 :> 0)])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS n1, n2

=============================================================================

---- CONFIG MC_TTrace_1794187161 ----
CONSTANTS
    n1 = n1
    n2 = n2
    None = None
    Node = { n1 , n2 }
    KeyInterval = 1
    TokenLifetime = 2
    MaxSkew = 0
    Inf = 99
    MaxTime = 2
    MaxTokens = 1
    MaxCrash = 0
    MaxExpire = 0
    MaxZkFail = 0
    MaxStop = 0
    MaxRestart = 0
    QuiescentTick = TRUE
    TargetFilter = "S3"
    n1 = n1
    n2 = n2
    None = None

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