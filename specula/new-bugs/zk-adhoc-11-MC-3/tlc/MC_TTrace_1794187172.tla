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
        role = (<<"Following", "Down", "Leading">>)
        /\
        wrVal = (<<-1, -1, -1>>)
        /\
        memZxid = (<<0, 1001, 1000>>)
        /\
        connOpen = (<<TRUE, TRUE, TRUE>>)
        /\
        targetFired = (TRUE)
        /\
        pNotLogged = (<<{}, {}, {}>>)
        /\
        electing = (<<{}, {}, {1, 2}>>)
        /\
        curFile = (<<1, 0, 1>>)
        /\
        leaderOf = (<<3, -1, -1>>)
        /\
        faults = ([crash |-> 0, write |-> 0, shutdown |-> 1, workloadStop |-> 0])
        /\
        wrCtx = (<<"None", "None", "None">>)
        /\
        cLog = (<<{}, {1001}, {}>>)
        /\
        running = (<<TRUE, TRUE, TRUE>>)
        /\
        tmp = (<<-1, -1, -1>>)
        /\
        loadCaller = (<<"None", "None", "None">>)
        /\
        syncMode = (<<"NONE", "NONE", "NONE">>)
        /\
        sockOpen = (<<TRUE, TRUE, TRUE>>)
        /\
        hstep = (<<"NLQueued", "None", "None">>)
        /\
        accFile = (<<1, 1, 1>>)
        /\
        pCommitted = (<<{}, {}, {}>>)
        /\
        lstep = (<<"AfterNL", "Idle", "Idle">>)
        /\
        newEpoch = (<<1, -1, -1>>)
        /\
        zkDbInit = (<<TRUE, TRUE, TRUE>>)
        /\
        writeToTxnLog = (<<TRUE, FALSE, FALSE>>)
        /\
        memCur = (<<1, 0, 1>>)
        /\
        snapZxid = (<<0, 0, 0>>)
        /\
        memAcc = (<<1, -1, 1>>)
        /\
        dLog = (<<{}, {1001}, {1001}>>)
        /\
        lEpoch = (<<-1, -1, 1>>)
        /\
        q = (<<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>)
        /\
        nlAcked = (<<{}, {}, {1}>>)
        /\
        lstate = (<<"Idle", "Idle", "Started">>)
        /\
        wrStep = (<<"Idle", "Idle", "Idle">>)
        /\
        connecting = (<<{}, {}, {1, 2, 3}>>)
    )
----

_init ==
    /\ wrStep = _TETrace[1].wrStep
    /\ lstep = _TETrace[1].lstep
    /\ memAcc = _TETrace[1].memAcc
    /\ lEpoch = _TETrace[1].lEpoch
    /\ targetFired = _TETrace[1].targetFired
    /\ tmp = _TETrace[1].tmp
    /\ running = _TETrace[1].running
    /\ dLog = _TETrace[1].dLog
    /\ q = _TETrace[1].q
    /\ loadCaller = _TETrace[1].loadCaller
    /\ electing = _TETrace[1].electing
    /\ faults = _TETrace[1].faults
    /\ nlAcked = _TETrace[1].nlAcked
    /\ cLog = _TETrace[1].cLog
    /\ newEpoch = _TETrace[1].newEpoch
    /\ lstate = _TETrace[1].lstate
    /\ memZxid = _TETrace[1].memZxid
    /\ curFile = _TETrace[1].curFile
    /\ writeToTxnLog = _TETrace[1].writeToTxnLog
    /\ memCur = _TETrace[1].memCur
    /\ wrCtx = _TETrace[1].wrCtx
    /\ connOpen = _TETrace[1].connOpen
    /\ connecting = _TETrace[1].connecting
    /\ wrVal = _TETrace[1].wrVal
    /\ leaderOf = _TETrace[1].leaderOf
    /\ role = _TETrace[1].role
    /\ zkDbInit = _TETrace[1].zkDbInit
    /\ snapZxid = _TETrace[1].snapZxid
    /\ syncMode = _TETrace[1].syncMode
    /\ accFile = _TETrace[1].accFile
    /\ sockOpen = _TETrace[1].sockOpen
    /\ hstep = _TETrace[1].hstep
    /\ pCommitted = _TETrace[1].pCommitted
    /\ pNotLogged = _TETrace[1].pNotLogged
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ wrStep  = _TETrace[i].wrStep
        /\ wrStep' = _TETrace[j].wrStep
        /\ lstep  = _TETrace[i].lstep
        /\ lstep' = _TETrace[j].lstep
        /\ memAcc  = _TETrace[i].memAcc
        /\ memAcc' = _TETrace[j].memAcc
        /\ lEpoch  = _TETrace[i].lEpoch
        /\ lEpoch' = _TETrace[j].lEpoch
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ tmp  = _TETrace[i].tmp
        /\ tmp' = _TETrace[j].tmp
        /\ running  = _TETrace[i].running
        /\ running' = _TETrace[j].running
        /\ dLog  = _TETrace[i].dLog
        /\ dLog' = _TETrace[j].dLog
        /\ q  = _TETrace[i].q
        /\ q' = _TETrace[j].q
        /\ loadCaller  = _TETrace[i].loadCaller
        /\ loadCaller' = _TETrace[j].loadCaller
        /\ electing  = _TETrace[i].electing
        /\ electing' = _TETrace[j].electing
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ nlAcked  = _TETrace[i].nlAcked
        /\ nlAcked' = _TETrace[j].nlAcked
        /\ cLog  = _TETrace[i].cLog
        /\ cLog' = _TETrace[j].cLog
        /\ newEpoch  = _TETrace[i].newEpoch
        /\ newEpoch' = _TETrace[j].newEpoch
        /\ lstate  = _TETrace[i].lstate
        /\ lstate' = _TETrace[j].lstate
        /\ memZxid  = _TETrace[i].memZxid
        /\ memZxid' = _TETrace[j].memZxid
        /\ curFile  = _TETrace[i].curFile
        /\ curFile' = _TETrace[j].curFile
        /\ writeToTxnLog  = _TETrace[i].writeToTxnLog
        /\ writeToTxnLog' = _TETrace[j].writeToTxnLog
        /\ memCur  = _TETrace[i].memCur
        /\ memCur' = _TETrace[j].memCur
        /\ wrCtx  = _TETrace[i].wrCtx
        /\ wrCtx' = _TETrace[j].wrCtx
        /\ connOpen  = _TETrace[i].connOpen
        /\ connOpen' = _TETrace[j].connOpen
        /\ connecting  = _TETrace[i].connecting
        /\ connecting' = _TETrace[j].connecting
        /\ wrVal  = _TETrace[i].wrVal
        /\ wrVal' = _TETrace[j].wrVal
        /\ leaderOf  = _TETrace[i].leaderOf
        /\ leaderOf' = _TETrace[j].leaderOf
        /\ role  = _TETrace[i].role
        /\ role' = _TETrace[j].role
        /\ zkDbInit  = _TETrace[i].zkDbInit
        /\ zkDbInit' = _TETrace[j].zkDbInit
        /\ snapZxid  = _TETrace[i].snapZxid
        /\ snapZxid' = _TETrace[j].snapZxid
        /\ syncMode  = _TETrace[i].syncMode
        /\ syncMode' = _TETrace[j].syncMode
        /\ accFile  = _TETrace[i].accFile
        /\ accFile' = _TETrace[j].accFile
        /\ sockOpen  = _TETrace[i].sockOpen
        /\ sockOpen' = _TETrace[j].sockOpen
        /\ hstep  = _TETrace[i].hstep
        /\ hstep' = _TETrace[j].hstep
        /\ pCommitted  = _TETrace[i].pCommitted
        /\ pCommitted' = _TETrace[j].pCommitted
        /\ pNotLogged  = _TETrace[i].pNotLogged
        /\ pNotLogged' = _TETrace[j].pNotLogged

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
        wrStep |-> wrStep
        ,lstep |-> lstep
        ,memAcc |-> memAcc
        ,lEpoch |-> lEpoch
        ,targetFired |-> targetFired
        ,tmp |-> tmp
        ,running |-> running
        ,dLog |-> dLog
        ,q |-> q
        ,loadCaller |-> loadCaller
        ,electing |-> electing
        ,faults |-> faults
        ,nlAcked |-> nlAcked
        ,cLog |-> cLog
        ,newEpoch |-> newEpoch
        ,lstate |-> lstate
        ,memZxid |-> memZxid
        ,curFile |-> curFile
        ,writeToTxnLog |-> writeToTxnLog
        ,memCur |-> memCur
        ,wrCtx |-> wrCtx
        ,connOpen |-> connOpen
        ,connecting |-> connecting
        ,wrVal |-> wrVal
        ,leaderOf |-> leaderOf
        ,role |-> role
        ,zkDbInit |-> zkDbInit
        ,snapZxid |-> snapZxid
        ,syncMode |-> syncMode
        ,accFile |-> accFile
        ,sockOpen |-> sockOpen
        ,hstep |-> hstep
        ,pCommitted |-> pCommitted
        ,pNotLogged |-> pNotLogged
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_wrStepUnchanged |-> wrStep = wrStep'
        
        \* Format the `wrStep` variable as Json value.
        \* ,_wrStepJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(wrStep)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_wrStepModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].wrStep # _TETrace[s-1].wrStep
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
    ([role |-> <<"Down", "Down", "Down">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<-1, -1, -1>>,leaderOf |-> <<-1, -1, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"None", "None", "None">>,accFile |-> <<-1, -1, -1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"Idle", "Idle", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<FALSE, FALSE, FALSE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<-1, -1, -1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<-1, -1, -1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, -1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "Idle">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {}>>]),
    ([role |-> <<"Looking", "Down", "Down">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, -1, -1>>,leaderOf |-> <<-1, -1, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"None", "None", "None">>,accFile |-> <<0, -1, -1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"Idle", "Idle", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, FALSE, FALSE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, -1, -1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, -1, -1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, -1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "Idle">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {}>>]),
    ([role |-> <<"Looking", "Looking", "Down">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, 0, -1>>,leaderOf |-> <<-1, -1, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"None", "None", "None">>,accFile |-> <<0, 0, -1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"Idle", "Idle", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, FALSE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, -1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, 0, -1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, -1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "Idle">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {}>>]),
    ([role |-> <<"Looking", "Looking", "Looking">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<-1, -1, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"None", "None", "None">>,accFile |-> <<0, 0, 0>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"Idle", "Idle", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, 0, 0>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, -1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "Idle">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"None", "None", "None">>,accFile |-> <<0, 0, 0>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"Register", "Register", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, 0, 0>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, -1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "LoadData">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"None", "None", "None">>,accFile |-> <<0, 0, 0>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"Register", "Register", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, 0, 0>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "Discover">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"Info", "None", "None">>,accFile |-> <<0, 0, 0>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitLeaderInfo", "Register", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, 0, 0>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "Discover">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"Info", "Info", "None">>,accFile |-> <<0, 0, 0>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitLeaderInfo", "AwaitLeaderInfo", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, 0, 0>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "Discover">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"Info", "Info", "None">>,accFile |-> <<0, 0, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitLeaderInfo", "AwaitLeaderInfo", "Idle">>,newEpoch |-> <<-1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<0, 0, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitEpochQuorum">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"AckEpoch", "Info", "None">>,accFile |-> <<1, 0, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitOp", "AwaitLeaderInfo", "Idle">>,newEpoch |-> <<1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 0, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitEpochQuorum">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"AckEpoch", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitOp", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitEpochQuorum">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, 1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "Leader">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"AckEpoch", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitOp", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "SetEpoch">>,wrStep |-> <<"Idle", "Idle", "ToOpen">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, 1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "Leader">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -2>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"AckEpoch", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitOp", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "SetEpoch">>,wrStep |-> <<"Idle", "Idle", "ToFill">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, 1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 0>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "Leader">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, 1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"AckEpoch", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitOp", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 0>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "SetEpoch">>,wrStep |-> <<"Idle", "Idle", "ToRename">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"AckEpoch", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitOp", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"Synced", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AwaitOp", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<FALSE, FALSE, FALSE>>,memCur |-> <<0, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "DIFF", zxid |-> 0]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"DIFF", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"Synced", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"SyncLoop", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<0, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"DIFF", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"SyncLoop", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<0, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "NEWLEADER", zxid |-> 1000]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"Learner", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"DIFF", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"EpochWrite", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<0, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"ToOpen", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"Learner", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-2, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"DIFF", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"EpochWrite", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<0, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"ToFill", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<0, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"Learner", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"DIFF", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"EpochWrite", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<0, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"ToRename", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 0>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "AwaitNLAck">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "AckEpoch", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "Synced", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<>>, <<[type |-> "SNAP", zxid |-> 1000]>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "Synced", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "AwaitOp", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<[type |-> "SNAP", zxid |-> 1000], [type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 1000, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "SNAP", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "Synced", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "SyncLoop", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 1000, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {1001}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 0, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "SNAP", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "Synced", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "SyncLoop", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 1000, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {1001}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 1, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, FALSE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "SNAP", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "Synced", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "SyncLoop", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 1000, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {1001}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 1, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, FALSE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "SNAP", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "Synced", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "PostLoop", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Following", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 1000, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, 3, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 1, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, FALSE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "SNAP", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "Synced", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "Broadcast", "Idle">>,newEpoch |-> <<1, 1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {1001}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Looking", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, -1, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 1, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, FALSE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "SNAP", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "None", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "Idle", "Idle">>,newEpoch |-> <<1, -1, -1>>,zkDbInit |-> <<TRUE, FALSE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, 1, 1>>,dLog |-> <<{}, {1001}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Down", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 0, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> FALSE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, -1, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 1, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "None", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "Idle", "Idle">>,newEpoch |-> <<1, -1, -1>>,zkDbInit |-> <<TRUE, FALSE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, -1, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, -1, 1>>,dLog |-> <<{}, {1001}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>]),
    ([role |-> <<"Following", "Down", "Leading">>,wrVal |-> <<-1, -1, -1>>,memZxid |-> <<0, 1001, 1000>>,connOpen |-> <<TRUE, TRUE, TRUE>>,targetFired |-> TRUE,pNotLogged |-> <<{}, {}, {}>>,electing |-> <<{}, {}, {1, 2}>>,curFile |-> <<1, 0, 1>>,leaderOf |-> <<3, -1, -1>>,faults |-> [crash |-> 0, write |-> 0, shutdown |-> 1, workloadStop |-> 0],wrCtx |-> <<"None", "None", "None">>,cLog |-> <<{}, {1001}, {}>>,running |-> <<TRUE, TRUE, TRUE>>,tmp |-> <<-1, -1, -1>>,loadCaller |-> <<"None", "None", "None">>,syncMode |-> <<"NONE", "NONE", "NONE">>,sockOpen |-> <<TRUE, TRUE, TRUE>>,hstep |-> <<"NLQueued", "None", "None">>,accFile |-> <<1, 1, 1>>,pCommitted |-> <<{}, {}, {}>>,lstep |-> <<"AfterNL", "Idle", "Idle">>,newEpoch |-> <<1, -1, -1>>,zkDbInit |-> <<TRUE, TRUE, TRUE>>,writeToTxnLog |-> <<TRUE, FALSE, FALSE>>,memCur |-> <<1, 0, 1>>,snapZxid |-> <<0, 0, 0>>,memAcc |-> <<1, -1, 1>>,dLog |-> <<{}, {1001}, {1001}>>,lEpoch |-> <<-1, -1, 1>>,q |-> <<<<[type |-> "PROPOSAL", zxid |-> 1001]>>, <<>>, <<>>>>,nlAcked |-> <<{}, {}, {1}>>,lstate |-> <<"Idle", "Idle", "Started">>,wrStep |-> <<"Idle", "Idle", "Idle">>,connecting |-> <<{}, {}, {1, 2, 3}>>])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187172 ----
CONSTANTS
    Server = { 1 , 2 , 3 }
    MaxEpoch = 3
    MaxTxnPerEpoch = 2
    ForceSnapSync = FALSE
    MaxWorkloadStop = 0
    MaxCrash = 0
    MaxEpochWriteFail = 0
    MaxShutdown = 1

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
\* Generated on Mon Nov 09 01:19:43 UTC 2026