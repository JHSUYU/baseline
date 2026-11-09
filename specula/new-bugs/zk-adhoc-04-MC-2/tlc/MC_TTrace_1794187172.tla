---- MODULE MC_TTrace_1794187172 ----
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
        dbInit = (<<TRUE, TRUE, FALSE>>)
        /\
        accEpoch = (<<1, 1, 0>>)
        /\
        role = (<<"FOLLOWING", "LOOKING", "DOWN">>)
        /\
        pktCommitted = (<<<<>>, <<>>, <<>>>>)
        /\
        cLastZxid = (<<11>>)
        /\
        log = (<<{}, {11}, {}>>)
        /\
        targetFired = (TRUE)
        /\
        cSeenRw = (<<FALSE>>)
        /\
        leaderOf = (<<2, 0, 0>>)
        /\
        faults = ([aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1])
        /\
        utdSent = (<<{}, {}, {}>>)
        /\
        serving = (<<"RW", "RO", "NONE">>)
        /\
        lepoch = (<<1, 0, 0>>)
        /\
        syncMode = (<<"NONE", "NONE", "NONE">>)
        /\
        snapZ = (<<0, 0, -1>>)
        /\
        cState = (<<"CONNECTING">>)
        /\
        pendingTxns = (<<<<>>, <<>>, <<>>>>)
        /\
        toLog = (<<<<>>, <<>>, <<>>>>)
        /\
        commitQ = (<<<<>>, <<>>, <<>>>>)
        /\
        phase = (<<"STARTED", "NONE", "NONE">>)
        /\
        committed = ({})
        /\
        targetInfo = ([sid |-> 1, role |-> "FOLLOWING", cid |-> 1, cz |-> 11, sz |-> 0, srv |-> "RW", cls |-> "C"])
        /\
        acks = (<<{}, {}, {}>>)
        /\
        cReplies = (<<<<>>>>)
        /\
        lastCommitted = (<<0, 0, 0>>)
        /\
        nlAcks = (<<{}, {}, {}>>)
        /\
        clog = (<<{}, {11}, {}>>)
        /\
        cSess = (<<2>>)
        /\
        fwd = (<<{}, {}, {}>>)
        /\
        hzxid = (<<0, 0, 0>>)
        /\
        lpz = (<<0, 11, 0>>)
        /\
        served = ({11})
        /\
        cRwTarget = (<<0>>)
        /\
        cConn = (<<0>>)
        /\
        inbox = (<<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>)
        /\
        pktNotLogged = (<<<<>>, <<>>, <<>>>>)
        /\
        curEpoch = (<<1, 1, 0>>)
    )
----

_init ==
    /\ lpz = _TETrace[1].lpz
    /\ syncMode = _TETrace[1].syncMode
    /\ acks = _TETrace[1].acks
    /\ pktCommitted = _TETrace[1].pktCommitted
    /\ inbox = _TETrace[1].inbox
    /\ clog = _TETrace[1].clog
    /\ toLog = _TETrace[1].toLog
    /\ cReplies = _TETrace[1].cReplies
    /\ accEpoch = _TETrace[1].accEpoch
    /\ dbInit = _TETrace[1].dbInit
    /\ targetFired = _TETrace[1].targetFired
    /\ pktNotLogged = _TETrace[1].pktNotLogged
    /\ cState = _TETrace[1].cState
    /\ lepoch = _TETrace[1].lepoch
    /\ role = _TETrace[1].role
    /\ cSeenRw = _TETrace[1].cSeenRw
    /\ faults = _TETrace[1].faults
    /\ targetInfo = _TETrace[1].targetInfo
    /\ hzxid = _TETrace[1].hzxid
    /\ cRwTarget = _TETrace[1].cRwTarget
    /\ phase = _TETrace[1].phase
    /\ lastCommitted = _TETrace[1].lastCommitted
    /\ curEpoch = _TETrace[1].curEpoch
    /\ snapZ = _TETrace[1].snapZ
    /\ serving = _TETrace[1].serving
    /\ committed = _TETrace[1].committed
    /\ fwd = _TETrace[1].fwd
    /\ commitQ = _TETrace[1].commitQ
    /\ pendingTxns = _TETrace[1].pendingTxns
    /\ cConn = _TETrace[1].cConn
    /\ cLastZxid = _TETrace[1].cLastZxid
    /\ log = _TETrace[1].log
    /\ leaderOf = _TETrace[1].leaderOf
    /\ served = _TETrace[1].served
    /\ utdSent = _TETrace[1].utdSent
    /\ nlAcks = _TETrace[1].nlAcks
    /\ cSess = _TETrace[1].cSess
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ lpz  = _TETrace[i].lpz
        /\ lpz' = _TETrace[j].lpz
        /\ syncMode  = _TETrace[i].syncMode
        /\ syncMode' = _TETrace[j].syncMode
        /\ acks  = _TETrace[i].acks
        /\ acks' = _TETrace[j].acks
        /\ pktCommitted  = _TETrace[i].pktCommitted
        /\ pktCommitted' = _TETrace[j].pktCommitted
        /\ inbox  = _TETrace[i].inbox
        /\ inbox' = _TETrace[j].inbox
        /\ clog  = _TETrace[i].clog
        /\ clog' = _TETrace[j].clog
        /\ toLog  = _TETrace[i].toLog
        /\ toLog' = _TETrace[j].toLog
        /\ cReplies  = _TETrace[i].cReplies
        /\ cReplies' = _TETrace[j].cReplies
        /\ accEpoch  = _TETrace[i].accEpoch
        /\ accEpoch' = _TETrace[j].accEpoch
        /\ dbInit  = _TETrace[i].dbInit
        /\ dbInit' = _TETrace[j].dbInit
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ pktNotLogged  = _TETrace[i].pktNotLogged
        /\ pktNotLogged' = _TETrace[j].pktNotLogged
        /\ cState  = _TETrace[i].cState
        /\ cState' = _TETrace[j].cState
        /\ lepoch  = _TETrace[i].lepoch
        /\ lepoch' = _TETrace[j].lepoch
        /\ role  = _TETrace[i].role
        /\ role' = _TETrace[j].role
        /\ cSeenRw  = _TETrace[i].cSeenRw
        /\ cSeenRw' = _TETrace[j].cSeenRw
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ targetInfo  = _TETrace[i].targetInfo
        /\ targetInfo' = _TETrace[j].targetInfo
        /\ hzxid  = _TETrace[i].hzxid
        /\ hzxid' = _TETrace[j].hzxid
        /\ cRwTarget  = _TETrace[i].cRwTarget
        /\ cRwTarget' = _TETrace[j].cRwTarget
        /\ phase  = _TETrace[i].phase
        /\ phase' = _TETrace[j].phase
        /\ lastCommitted  = _TETrace[i].lastCommitted
        /\ lastCommitted' = _TETrace[j].lastCommitted
        /\ curEpoch  = _TETrace[i].curEpoch
        /\ curEpoch' = _TETrace[j].curEpoch
        /\ snapZ  = _TETrace[i].snapZ
        /\ snapZ' = _TETrace[j].snapZ
        /\ serving  = _TETrace[i].serving
        /\ serving' = _TETrace[j].serving
        /\ committed  = _TETrace[i].committed
        /\ committed' = _TETrace[j].committed
        /\ fwd  = _TETrace[i].fwd
        /\ fwd' = _TETrace[j].fwd
        /\ commitQ  = _TETrace[i].commitQ
        /\ commitQ' = _TETrace[j].commitQ
        /\ pendingTxns  = _TETrace[i].pendingTxns
        /\ pendingTxns' = _TETrace[j].pendingTxns
        /\ cConn  = _TETrace[i].cConn
        /\ cConn' = _TETrace[j].cConn
        /\ cLastZxid  = _TETrace[i].cLastZxid
        /\ cLastZxid' = _TETrace[j].cLastZxid
        /\ log  = _TETrace[i].log
        /\ log' = _TETrace[j].log
        /\ leaderOf  = _TETrace[i].leaderOf
        /\ leaderOf' = _TETrace[j].leaderOf
        /\ served  = _TETrace[i].served
        /\ served' = _TETrace[j].served
        /\ utdSent  = _TETrace[i].utdSent
        /\ utdSent' = _TETrace[j].utdSent
        /\ nlAcks  = _TETrace[i].nlAcks
        /\ nlAcks' = _TETrace[j].nlAcks
        /\ cSess  = _TETrace[i].cSess
        /\ cSess' = _TETrace[j].cSess

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
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC

expression == 
    [
        \* To hide variables of the `MC` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        lpz |-> lpz
        ,syncMode |-> syncMode
        ,acks |-> acks
        ,pktCommitted |-> pktCommitted
        ,inbox |-> inbox
        ,clog |-> clog
        ,toLog |-> toLog
        ,cReplies |-> cReplies
        ,accEpoch |-> accEpoch
        ,dbInit |-> dbInit
        ,targetFired |-> targetFired
        ,pktNotLogged |-> pktNotLogged
        ,cState |-> cState
        ,lepoch |-> lepoch
        ,role |-> role
        ,cSeenRw |-> cSeenRw
        ,faults |-> faults
        ,targetInfo |-> targetInfo
        ,hzxid |-> hzxid
        ,cRwTarget |-> cRwTarget
        ,phase |-> phase
        ,lastCommitted |-> lastCommitted
        ,curEpoch |-> curEpoch
        ,snapZ |-> snapZ
        ,serving |-> serving
        ,committed |-> committed
        ,fwd |-> fwd
        ,commitQ |-> commitQ
        ,pendingTxns |-> pendingTxns
        ,cConn |-> cConn
        ,cLastZxid |-> cLastZxid
        ,log |-> log
        ,leaderOf |-> leaderOf
        ,served |-> served
        ,utdSent |-> utdSent
        ,nlAcks |-> nlAcks
        ,cSess |-> cSess
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_lpzUnchanged |-> lpz = lpz'
        
        \* Format the `lpz` variable as Json value.
        \* ,_lpzJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(lpz)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_lpzModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].lpz # _TETrace[s-1].lpz
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
\*trace == IODeserialize("MC_TTrace_1794187172.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC

trace == 
    <<
    ([dbInit |-> <<FALSE, FALSE, FALSE>>,accEpoch |-> <<0, 0, 0>>,role |-> <<"DOWN", "DOWN", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<0, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<0, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<-1, -1, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"NONE", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<0, 0, 0>>]),
    ([dbInit |-> <<TRUE, FALSE, FALSE>>,accEpoch |-> <<0, 0, 0>>,role |-> <<"LOOKING", "DOWN", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<0, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<0, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, -1, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"NONE", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<0, 0, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<0, 0, 0>>,role |-> <<"LOOKING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<0, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<0, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"NONE", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<0, 0, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<0, 0, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<0, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"ELECTED", "ELECTED", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<0, 0, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"DISCOVERED", "SYNC", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<0, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"SYNC", "SYNC", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 0, t |-> "DIFF"], [z |-> 10, t |-> "NEWLEADER"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<0, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"DIFF", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"SYNC", "SYNC", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 10, t |-> "NEWLEADER"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<0, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"SYNC2", "SYNC", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {1, 2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "NONE", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"SYNC2", "STARTED", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 10, 0>>,nlAcks |-> <<{}, {1, 2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {}, {}>>,serving |-> <<"NONE", "RW", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"SYNC2", "BROADCAST", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 10, 0>>,nlAcks |-> <<{}, {1, 2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 10, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {1}, {}>>,serving |-> <<"NONE", "RW", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"SYNC2", "BROADCAST", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 10, 0>>,nlAcks |-> <<{}, {1, 2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 10, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> -1, t |-> "UPTODATE"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 0],utdSent |-> <<{}, {1}, {}>>,serving |-> <<"RW", "RW", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "BROADCAST", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 10, 0>>,nlAcks |-> <<{}, {1, 2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 10, 0>>,lpz |-> <<0, 10, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LEADING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 0, stop |-> 0, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {1}, {}>>,serving |-> <<"RW", "RW", "NONE">>,lepoch |-> <<1, 1, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "BROADCAST", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 10, 0>>,nlAcks |-> <<{}, {1, 2}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {1}, {}>>,hzxid |-> <<0, 11, 0>>,lpz |-> <<0, 10, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, FALSE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "DOWN", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {11}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "NONE", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 0, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {11}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "NONE", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {11}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 11, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {11}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "RO", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {11}, {}>>,cSess |-> <<0>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 11, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {11}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "RO", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTEDREADONLY">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {11}, {}>>,cSess |-> <<2>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 11, 0>>,served |-> {},cRwTarget |-> <<0>>,cConn |-> <<2>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<0>>,log |-> <<{}, {11}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "RO", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTEDREADONLY">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<11>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {11}, {}>>,cSess |-> <<2>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 11, 0>>,served |-> {11},cRwTarget |-> <<0>>,cConn |-> <<2>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<11>>,log |-> <<{}, {11}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "RO", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTEDREADONLY">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {11}, {}>>,cSess |-> <<2>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 11, 0>>,served |-> {11},cRwTarget |-> <<0>>,cConn |-> <<2>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<11>>,log |-> <<{}, {11}, {}>>,targetFired |-> FALSE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "RO", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 0, role |-> "NONE", cid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", cls |-> "NONE"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {11}, {}>>,cSess |-> <<2>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 11, 0>>,served |-> {11},cRwTarget |-> <<1>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>]),
    ([dbInit |-> <<TRUE, TRUE, FALSE>>,accEpoch |-> <<1, 1, 0>>,role |-> <<"FOLLOWING", "LOOKING", "DOWN">>,pktCommitted |-> <<<<>>, <<>>, <<>>>>,cLastZxid |-> <<11>>,log |-> <<{}, {11}, {}>>,targetFired |-> TRUE,cSeenRw |-> <<FALSE>>,leaderOf |-> <<2, 0, 0>>,faults |-> [aband |-> 1, stop |-> 1, part |-> 0, move |-> 0, write |-> 1],utdSent |-> <<{}, {}, {}>>,serving |-> <<"RW", "RO", "NONE">>,lepoch |-> <<1, 0, 0>>,syncMode |-> <<"NONE", "NONE", "NONE">>,snapZ |-> <<0, 0, -1>>,cState |-> <<"CONNECTING">>,pendingTxns |-> <<<<>>, <<>>, <<>>>>,toLog |-> <<<<>>, <<>>, <<>>>>,commitQ |-> <<<<>>, <<>>, <<>>>>,phase |-> <<"STARTED", "NONE", "NONE">>,committed |-> {},targetInfo |-> [sid |-> 1, role |-> "FOLLOWING", cid |-> 1, cz |-> 11, sz |-> 0, srv |-> "RW", cls |-> "C"],acks |-> <<{}, {}, {}>>,cReplies |-> <<<<>>>>,lastCommitted |-> <<0, 0, 0>>,nlAcks |-> <<{}, {}, {}>>,clog |-> <<{}, {11}, {}>>,cSess |-> <<2>>,fwd |-> <<{}, {}, {}>>,hzxid |-> <<0, 0, 0>>,lpz |-> <<0, 11, 0>>,served |-> {11},cRwTarget |-> <<0>>,cConn |-> <<0>>,inbox |-> <<<<[z |-> 11, t |-> "PROPOSAL"]>>, <<>>, <<>>>>,pktNotLogged |-> <<<<>>, <<>>, <<>>>>,curEpoch |-> <<1, 1, 0>>])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187172 ----
CONSTANTS
    Server = { 1 , 2 , 3 }
    Client = { 1 }
    ZB = 10
    RoEnabled = TRUE
    TrustEmptyDB = TRUE
    ClientCanBeRO = TRUE
    AsyncApply = FALSE
    MaxStops = 1
    MaxPartitions = 0
    MaxClientMoves = 0
    MaxClientWrites = 1
    MaxAbandonedProposals = 1
    MaxEpoch = 2

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
\* Generated on Mon Nov 09 01:19:56 UTC 2026