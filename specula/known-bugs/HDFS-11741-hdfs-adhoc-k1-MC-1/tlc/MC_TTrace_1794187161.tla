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
        nnSerial = (15)
        /\
        targetFired = (TRUE)
        /\
        dnKeys = ((d1 :> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)))
        /\
        nnMonPC = ("idle")
        /\
        regSnap = ((d1 :> None @@ d2 :> None))
        /\
        faults = ([loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0])
        /\
        dnPC = ((d1 :> "running" @@ d2 :> "running"))
        /\
        now = (9)
        /\
        cliDEK = ((c1 :> None))
        /\
        dnMgr = ((d1 :> TRUE @@ d2 :> TRUE))
        /\
        balOn = (TRUE)
        /\
        balKeys = ((1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14))
        /\
        conns = (<<>>)
        /\
        hbDone = ((d1 :> TRUE @@ d2 :> FALSE))
        /\
        nnCur = (14)
        /\
        dnCur = ((d1 :> 14 @@ d2 :> 13))
        /\
        nnStored = ({d1, d2})
        /\
        hbResp = ((d1 :> None @@ d2 :> None))
        /\
        npeFired = (FALSE)
        /\
        balCur = (13)
        /\
        lastRoll = (9)
        /\
        nnKeys = ((12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17))
        /\
        safeMode = (FALSE)
        /\
        hbList = ({d1, d2})
        /\
        balPollAge = (1)
        /\
        needKeyUpdate = ((d1 :> FALSE @@ d2 :> TRUE))
        /\
        nnNext = (15)
        /\
        mintedKeys = ({1, 2, 11, 12, 13, 14, 15})
        /\
        balDEK = (11)
        /\
        nnInc = (1)
    )
----

_init ==
    /\ nnNext = _TETrace[1].nnNext
    /\ hbDone = _TETrace[1].hbDone
    /\ nnMonPC = _TETrace[1].nnMonPC
    /\ nnInc = _TETrace[1].nnInc
    /\ dnKeys = _TETrace[1].dnKeys
    /\ dnMgr = _TETrace[1].dnMgr
    /\ npeFired = _TETrace[1].npeFired
    /\ balDEK = _TETrace[1].balDEK
    /\ dnPC = _TETrace[1].dnPC
    /\ dnCur = _TETrace[1].dnCur
    /\ balKeys = _TETrace[1].balKeys
    /\ needKeyUpdate = _TETrace[1].needKeyUpdate
    /\ targetFired = _TETrace[1].targetFired
    /\ nnStored = _TETrace[1].nnStored
    /\ safeMode = _TETrace[1].safeMode
    /\ nnSerial = _TETrace[1].nnSerial
    /\ faults = _TETrace[1].faults
    /\ mintedKeys = _TETrace[1].mintedKeys
    /\ now = _TETrace[1].now
    /\ hbList = _TETrace[1].hbList
    /\ hbResp = _TETrace[1].hbResp
    /\ nnKeys = _TETrace[1].nnKeys
    /\ conns = _TETrace[1].conns
    /\ balPollAge = _TETrace[1].balPollAge
    /\ cliDEK = _TETrace[1].cliDEK
    /\ lastRoll = _TETrace[1].lastRoll
    /\ regSnap = _TETrace[1].regSnap
    /\ nnCur = _TETrace[1].nnCur
    /\ balCur = _TETrace[1].balCur
    /\ balOn = _TETrace[1].balOn
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ nnNext  = _TETrace[i].nnNext
        /\ nnNext' = _TETrace[j].nnNext
        /\ hbDone  = _TETrace[i].hbDone
        /\ hbDone' = _TETrace[j].hbDone
        /\ nnMonPC  = _TETrace[i].nnMonPC
        /\ nnMonPC' = _TETrace[j].nnMonPC
        /\ nnInc  = _TETrace[i].nnInc
        /\ nnInc' = _TETrace[j].nnInc
        /\ dnKeys  = _TETrace[i].dnKeys
        /\ dnKeys' = _TETrace[j].dnKeys
        /\ dnMgr  = _TETrace[i].dnMgr
        /\ dnMgr' = _TETrace[j].dnMgr
        /\ npeFired  = _TETrace[i].npeFired
        /\ npeFired' = _TETrace[j].npeFired
        /\ balDEK  = _TETrace[i].balDEK
        /\ balDEK' = _TETrace[j].balDEK
        /\ dnPC  = _TETrace[i].dnPC
        /\ dnPC' = _TETrace[j].dnPC
        /\ dnCur  = _TETrace[i].dnCur
        /\ dnCur' = _TETrace[j].dnCur
        /\ balKeys  = _TETrace[i].balKeys
        /\ balKeys' = _TETrace[j].balKeys
        /\ needKeyUpdate  = _TETrace[i].needKeyUpdate
        /\ needKeyUpdate' = _TETrace[j].needKeyUpdate
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ nnStored  = _TETrace[i].nnStored
        /\ nnStored' = _TETrace[j].nnStored
        /\ safeMode  = _TETrace[i].safeMode
        /\ safeMode' = _TETrace[j].safeMode
        /\ nnSerial  = _TETrace[i].nnSerial
        /\ nnSerial' = _TETrace[j].nnSerial
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ mintedKeys  = _TETrace[i].mintedKeys
        /\ mintedKeys' = _TETrace[j].mintedKeys
        /\ now  = _TETrace[i].now
        /\ now' = _TETrace[j].now
        /\ hbList  = _TETrace[i].hbList
        /\ hbList' = _TETrace[j].hbList
        /\ hbResp  = _TETrace[i].hbResp
        /\ hbResp' = _TETrace[j].hbResp
        /\ nnKeys  = _TETrace[i].nnKeys
        /\ nnKeys' = _TETrace[j].nnKeys
        /\ conns  = _TETrace[i].conns
        /\ conns' = _TETrace[j].conns
        /\ balPollAge  = _TETrace[i].balPollAge
        /\ balPollAge' = _TETrace[j].balPollAge
        /\ cliDEK  = _TETrace[i].cliDEK
        /\ cliDEK' = _TETrace[j].cliDEK
        /\ lastRoll  = _TETrace[i].lastRoll
        /\ lastRoll' = _TETrace[j].lastRoll
        /\ regSnap  = _TETrace[i].regSnap
        /\ regSnap' = _TETrace[j].regSnap
        /\ nnCur  = _TETrace[i].nnCur
        /\ nnCur' = _TETrace[j].nnCur
        /\ balCur  = _TETrace[i].balCur
        /\ balCur' = _TETrace[j].balCur
        /\ balOn  = _TETrace[i].balOn
        /\ balOn' = _TETrace[j].balOn

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
        nnNext |-> nnNext
        ,hbDone |-> hbDone
        ,nnMonPC |-> nnMonPC
        ,nnInc |-> nnInc
        ,dnKeys |-> dnKeys
        ,dnMgr |-> dnMgr
        ,npeFired |-> npeFired
        ,balDEK |-> balDEK
        ,dnPC |-> dnPC
        ,dnCur |-> dnCur
        ,balKeys |-> balKeys
        ,needKeyUpdate |-> needKeyUpdate
        ,targetFired |-> targetFired
        ,nnStored |-> nnStored
        ,safeMode |-> safeMode
        ,nnSerial |-> nnSerial
        ,faults |-> faults
        ,mintedKeys |-> mintedKeys
        ,now |-> now
        ,hbList |-> hbList
        ,hbResp |-> hbResp
        ,nnKeys |-> nnKeys
        ,conns |-> conns
        ,balPollAge |-> balPollAge
        ,cliDEK |-> cliDEK
        ,lastRoll |-> lastRoll
        ,regSnap |-> regSnap
        ,nnCur |-> nnCur
        ,balCur |-> balCur
        ,balOn |-> balOn
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_nnNextUnchanged |-> nnNext = nnNext'
        
        \* Format the `nnNext` variable as Json value.
        \* ,_nnNextJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(nnNext)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_nnNextModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].nnNext # _TETrace[s-1].nnNext
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
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> <<>> @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "unreg" @@ d2 :> "unreg"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> FALSE @@ d2 :> FALSE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> None @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> <<>> @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)] @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "regSnap" @@ d2 :> "unreg"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> FALSE @@ d2 :> FALSE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> None @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> <<>> @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)] @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "regResp" @@ d2 :> "unreg"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> FALSE @@ d2 :> FALSE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> None @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> <<>> @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)] @@ d2 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)]),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "regResp" @@ d2 :> "regSnap"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> FALSE @@ d2 :> FALSE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> None @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> <<>> @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)] @@ d2 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)]),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "regAddKeys" @@ d2 :> "regSnap"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> FALSE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> None @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)]),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "regSnap"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> FALSE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)]),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "regResp"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> FALSE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> <<>>),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> [cur |-> 11, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)]),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "regAddKeys"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> None),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 0,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 1,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 1,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 1,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 1,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 1,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 2,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 2,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 2,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 2,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 2,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> FALSE,balKeys |-> <<>>,conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> None,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 12,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 11,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 0,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 12,mintedKeys |-> {1, 2, 11, 12},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "marking",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> TRUE @@ d2 :> TRUE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 11 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "KEYS", exp |-> [cur |-> 12, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)]] @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 11),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "KEYS", exp |-> [cur |-> 12, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)]]),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 3,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> None,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> ([dst |-> d1, src |-> "bal", keyId |-> 11] :> 1),hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> ([dst |-> d1, src |-> "bal", keyId |-> 11] :> 1),hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 6 @@ 12 :> 8),conns |-> ([dst |-> d1, src |-> "bal", keyId |-> 11] :> 1),hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 11,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> ([dst |-> d1, src |-> "bal", keyId |-> 11] :> 1),hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 4,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 5,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 5,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 5,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 5,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 5,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 5,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 13,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 12,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 3,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 13,mintedKeys |-> {1, 2, 11, 12, 13},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "marking",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> TRUE @@ d2 :> TRUE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 12 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "KEYS", exp |-> [cur |-> 13, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)]] @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 12,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 9 @@ 13 :> 11)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 12),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "KEYS", exp |-> [cur |-> 13, keys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)]]),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 6,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 7,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 7,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 7,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 7,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 7,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 7,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 8,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 8,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "NONE", exp |-> None] @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 8,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 8,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 8,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> [kind |-> "NONE", exp |-> None]),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 8,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> TRUE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 0,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 14,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 9,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 13,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 6,nnKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 14,mintedKeys |-> {1, 2, 11, 12, 13, 14},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 15,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "marking",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 9,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 14,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 9,nnKeys |-> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> FALSE),nnNext |-> 15,mintedKeys |-> {1, 2, 11, 12, 13, 14, 15},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 15,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 9,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 14,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 9,nnKeys |-> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> TRUE @@ d2 :> TRUE),nnNext |-> 15,mintedKeys |-> {1, 2, 11, 12, 13, 14, 15},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 15,targetFired |-> FALSE,dnKeys |-> (d1 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 9,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> FALSE @@ d2 :> FALSE),nnCur |-> 14,dnCur |-> (d1 :> 13 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> [kind |-> "KEYS", exp |-> [cur |-> 14, keys |-> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17)]] @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 9,nnKeys |-> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 15,mintedKeys |-> {1, 2, 11, 12, 13, 14, 15},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 15,targetFired |-> FALSE,dnKeys |-> (d1 :> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 9,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 14,dnCur |-> (d1 :> 14 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 9,nnKeys |-> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 15,mintedKeys |-> {1, 2, 11, 12, 13, 14, 15},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 15,targetFired |-> FALSE,dnKeys |-> (d1 :> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 9,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> ([dst |-> d1, src |-> "bal", keyId |-> 11] :> 1),hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 14,dnCur |-> (d1 :> 14 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 9,nnKeys |-> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 15,mintedKeys |-> {1, 2, 11, 12, 13, 14, 15},balDEK |-> 11,nnInc |-> 1]),
    ([nnSerial |-> 15,targetFired |-> TRUE,dnKeys |-> (d1 :> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17) @@ d2 :> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14)),nnMonPC |-> "idle",regSnap |-> (d1 :> None @@ d2 :> None),faults |-> [loss |-> 0, dead |-> 0, safeMode |-> 0, nnRestart |-> 0, dnRestart |-> 0],dnPC |-> (d1 :> "running" @@ d2 :> "running"),now |-> 9,cliDEK |-> (c1 :> None),dnMgr |-> (d1 :> TRUE @@ d2 :> TRUE),balOn |-> TRUE,balKeys |-> (1 :> 6 @@ 2 :> 8 @@ 11 :> 7 @@ 12 :> 10 @@ 13 :> 12 @@ 14 :> 14),conns |-> <<>>,hbDone |-> (d1 :> TRUE @@ d2 :> FALSE),nnCur |-> 14,dnCur |-> (d1 :> 14 @@ d2 :> 13),nnStored |-> {d1, d2},hbResp |-> (d1 :> None @@ d2 :> None),npeFired |-> FALSE,balCur |-> 13,lastRoll |-> 9,nnKeys |-> (12 :> 10 @@ 13 :> 13 @@ 14 :> 15 @@ 15 :> 17),safeMode |-> FALSE,hbList |-> {d1, d2},balPollAge |-> 1,needKeyUpdate |-> (d1 :> FALSE @@ d2 :> TRUE),nnNext |-> 15,mintedKeys |-> {1, 2, 11, 12, 13, 14, 15},balDEK |-> 11,nnInc |-> 1])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS d1, d2, c1

=============================================================================

---- CONFIG MC_TTrace_1794187161 ----
CONSTANTS
    d1 = d1
    d2 = d2
    DNs = { d1 , d2 }
    c1 = c1
    Clients = { c1 }
    None = None
    I = 2
    L = 2
    KeyIdBase = 10
    InitLastRoll = { 0 }
    BalPollPeriod = 1
    MaxTime = 10
    MaxInFlight = 1
    BalancerEnabled = TRUE
    ClientEnabled = FALSE
    DNTransferEnabled = TRUE
    LossLimit = 0
    DeadLimit = 0
    SafeModeLimit = 0
    NNRestartLimit = 0
    DNRestartLimit = 0
    d2 = d2
    c1 = c1
    d1 = d1
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
\* Generated on Mon Nov 09 01:19:23 UTC 2026