---- MODULE MC_TTrace_1794187162 ----
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
        phase = ((m1 :> "Down" @@ m2 :> "QuotaInit"))
        /\
        nsmSnap = ((m1 :> <<>> @@ m2 :> <<"TestNamespaceAuditor_np2", "default", "hbase">>))
        /\
        cache = ((m1 :> {} @@ m2 :> {"default", "hbase"}))
        /\
        choreSnap = ((m1 :> <<>> @@ m2 :> <<>>))
        /\
        cnp = ("Success")
        /\
        rsAlive = ((r1 :> TRUE))
        /\
        targetFired = (TRUE)
        /\
        ctpSub = ("Idle")
        /\
        dnp = ("DelDirs")
        /\
        cnpSub = ("Idle")
        /\
        regionHost = ([meta |-> r1])
        /\
        nsmIdx = ((m1 :> 1 @@ m2 :> 1))
        /\
        faultCounters = ([masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0])
        /\
        ctRound = (4)
        /\
        metaNs = ({"default", "hbase"})
        /\
        spaceQuotaNs = ({})
        /\
        regionState = ([meta |-> "Open"])
        /\
        rpcHandler = ([m |-> m2, st |-> "Released"])
        /\
        clientPc = ("DelInRpc")
        /\
        dnpSub = ("Idle")
        /\
        assignQ = ((m1 :> {} @@ m2 :> {}))
        /\
        ctp = ("None")
    )
----

_init ==
    /\ ctRound = _TETrace[1].ctRound
    /\ assignQ = _TETrace[1].assignQ
    /\ spaceQuotaNs = _TETrace[1].spaceQuotaNs
    /\ targetFired = _TETrace[1].targetFired
    /\ cnpSub = _TETrace[1].cnpSub
    /\ regionHost = _TETrace[1].regionHost
    /\ choreSnap = _TETrace[1].choreSnap
    /\ phase = _TETrace[1].phase
    /\ dnpSub = _TETrace[1].dnpSub
    /\ metaNs = _TETrace[1].metaNs
    /\ nsmIdx = _TETrace[1].nsmIdx
    /\ cnp = _TETrace[1].cnp
    /\ regionState = _TETrace[1].regionState
    /\ rpcHandler = _TETrace[1].rpcHandler
    /\ cache = _TETrace[1].cache
    /\ ctpSub = _TETrace[1].ctpSub
    /\ rsAlive = _TETrace[1].rsAlive
    /\ clientPc = _TETrace[1].clientPc
    /\ faultCounters = _TETrace[1].faultCounters
    /\ ctp = _TETrace[1].ctp
    /\ dnp = _TETrace[1].dnp
    /\ nsmSnap = _TETrace[1].nsmSnap
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ ctRound  = _TETrace[i].ctRound
        /\ ctRound' = _TETrace[j].ctRound
        /\ assignQ  = _TETrace[i].assignQ
        /\ assignQ' = _TETrace[j].assignQ
        /\ spaceQuotaNs  = _TETrace[i].spaceQuotaNs
        /\ spaceQuotaNs' = _TETrace[j].spaceQuotaNs
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ cnpSub  = _TETrace[i].cnpSub
        /\ cnpSub' = _TETrace[j].cnpSub
        /\ regionHost  = _TETrace[i].regionHost
        /\ regionHost' = _TETrace[j].regionHost
        /\ choreSnap  = _TETrace[i].choreSnap
        /\ choreSnap' = _TETrace[j].choreSnap
        /\ phase  = _TETrace[i].phase
        /\ phase' = _TETrace[j].phase
        /\ dnpSub  = _TETrace[i].dnpSub
        /\ dnpSub' = _TETrace[j].dnpSub
        /\ metaNs  = _TETrace[i].metaNs
        /\ metaNs' = _TETrace[j].metaNs
        /\ nsmIdx  = _TETrace[i].nsmIdx
        /\ nsmIdx' = _TETrace[j].nsmIdx
        /\ cnp  = _TETrace[i].cnp
        /\ cnp' = _TETrace[j].cnp
        /\ regionState  = _TETrace[i].regionState
        /\ regionState' = _TETrace[j].regionState
        /\ rpcHandler  = _TETrace[i].rpcHandler
        /\ rpcHandler' = _TETrace[j].rpcHandler
        /\ cache  = _TETrace[i].cache
        /\ cache' = _TETrace[j].cache
        /\ ctpSub  = _TETrace[i].ctpSub
        /\ ctpSub' = _TETrace[j].ctpSub
        /\ rsAlive  = _TETrace[i].rsAlive
        /\ rsAlive' = _TETrace[j].rsAlive
        /\ clientPc  = _TETrace[i].clientPc
        /\ clientPc' = _TETrace[j].clientPc
        /\ faultCounters  = _TETrace[i].faultCounters
        /\ faultCounters' = _TETrace[j].faultCounters
        /\ ctp  = _TETrace[i].ctp
        /\ ctp' = _TETrace[j].ctp
        /\ dnp  = _TETrace[i].dnp
        /\ dnp' = _TETrace[j].dnp
        /\ nsmSnap  = _TETrace[i].nsmSnap
        /\ nsmSnap' = _TETrace[j].nsmSnap

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187162.json", _TETrace)

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
        ctRound |-> ctRound
        ,assignQ |-> assignQ
        ,spaceQuotaNs |-> spaceQuotaNs
        ,targetFired |-> targetFired
        ,cnpSub |-> cnpSub
        ,regionHost |-> regionHost
        ,choreSnap |-> choreSnap
        ,phase |-> phase
        ,dnpSub |-> dnpSub
        ,metaNs |-> metaNs
        ,nsmIdx |-> nsmIdx
        ,cnp |-> cnp
        ,regionState |-> regionState
        ,rpcHandler |-> rpcHandler
        ,cache |-> cache
        ,ctpSub |-> ctpSub
        ,rsAlive |-> rsAlive
        ,clientPc |-> clientPc
        ,faultCounters |-> faultCounters
        ,ctp |-> ctp
        ,dnp |-> dnp
        ,nsmSnap |-> nsmSnap
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_ctRoundUnchanged |-> ctRound = ctRound'
        
        \* Format the `ctRound` variable as Json value.
        \* ,_ctRoundJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(ctRound)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_ctRoundModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].ctRound # _TETrace[s-1].ctRound
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
\*trace == IODeserialize("MC_TTrace_1794187162.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC, MC_TEConstants

trace == 
    <<
    ([phase |-> (m1 :> "Backup" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Workers" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "MetaLoaded" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Loading" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Loading" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {"default"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Loading" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Loaded" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Initialized" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "QuotaInit" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "QuotaInit" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 2 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "QuotaInit" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "Boot",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "None",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateNs",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Prepare",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateNsWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "CreateDir",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateNsWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Insert",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateNsWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Insert",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "MetaPut",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateNsWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "SetQuota",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateNsWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateNsWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "GetNs",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTable",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "PrepDone",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Assign"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "WaitChildren"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 1,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Success"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 2,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTable",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 2,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "PrepDone",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 2,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 2,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Rejected"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 3,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTable",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 3,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "PrepDone",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 3,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 3,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Assign"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 3,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "WaitChildren"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 3,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Success"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTable",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "PrepDone",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Prepare"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "CreateTableWait",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "Rejected"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DeleteTables",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Running" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<"default", "hbase">> @@ m2 :> <<>>),cache |-> (m1 :> {"TestNamespaceAuditor_np2", "default", "hbase"} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 3 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 0, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Backup"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Workers"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "MetaLoaded"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Loading"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Loading"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Loading"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Loading"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Loaded"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Initialized"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "None",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> None, st |-> "None"],clientPc |-> "DelSend",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Initialized"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "Prepare",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> m2, st |-> "Latch"],clientPc |-> "DelInRpc",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "Initialized"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "DelNsTable",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> m2, st |-> "Released"],clientPc |-> "DelInRpc",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "QuotaInit"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<"TestNamespaceAuditor_np2", "default", "hbase">>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "DelNsTable",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"TestNamespaceAuditor_np2", "default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> m2, st |-> "Released"],clientPc |-> "DelInRpc",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "QuotaInit"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<"TestNamespaceAuditor_np2", "default", "hbase">>),cache |-> (m1 :> {} @@ m2 :> {"TestNamespaceAuditor_np2", "default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "DelNsTable",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> m2, st |-> "Released"],clientPc |-> "DelInRpc",dnpSub |-> "MetaDeleted",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "QuotaInit"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<"TestNamespaceAuditor_np2", "default", "hbase">>),cache |-> (m1 :> {} @@ m2 :> {"default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> FALSE,ctpSub |-> "Idle",dnp |-> "DelDirs",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> m2, st |-> "Released"],clientPc |-> "DelInRpc",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"]),
    ([phase |-> (m1 :> "Down" @@ m2 :> "QuotaInit"),nsmSnap |-> (m1 :> <<>> @@ m2 :> <<"TestNamespaceAuditor_np2", "default", "hbase">>),cache |-> (m1 :> {} @@ m2 :> {"default", "hbase"}),choreSnap |-> (m1 :> <<>> @@ m2 :> <<>>),cnp |-> "Success",rsAlive |-> (r1 :> TRUE),targetFired |-> TRUE,ctpSub |-> "Idle",dnp |-> "DelDirs",cnpSub |-> "Idle",regionHost |-> [meta |-> r1],nsmIdx |-> (m1 :> 1 @@ m2 :> 1),faultCounters |-> [masterCrash |-> 1, rsCrash |-> 0, clientResend |-> 0],ctRound |-> 4,metaNs |-> {"default", "hbase"},spaceQuotaNs |-> {},regionState |-> [meta |-> "Open"],rpcHandler |-> [m |-> m2, st |-> "Released"],clientPc |-> "DelInRpc",dnpSub |-> "Idle",assignQ |-> (m1 :> {} @@ m2 :> {}),ctp |-> "None"])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS m1, m2, r1

=============================================================================

---- CONFIG MC_TTrace_1794187162 ----
CONSTANTS
    Masters = { m1 , m2 }
    RS = { r1 }
    None = None
    NSP = "TestNamespaceAuditor_np2"
    DEFAULT_NS = "default"
    HBASE_NS = "hbase"
    UserRegions = { }
    MetaInitHost = r1
    QuotaEnabled = TRUE
    RSGroupEnabled = FALSE
    SpaceQuotaNs = { }
    RsGroupRpcClient = FALSE
    RpcTableNs = { }
    CreateTableRounds = 4
    CtRejected = { 2 , 4 }
    MaxMasterCrash = 1
    MaxRSCrash = 0
    MaxClientResend = 1
    m2 = m2
    m1 = m1
    None = None
    r1 = r1

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
\* Generated on Mon Nov 09 01:19:24 UTC 2026