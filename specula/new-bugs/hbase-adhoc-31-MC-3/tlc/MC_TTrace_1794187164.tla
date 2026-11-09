---- MODULE MC_TTrace_1794187164 ----
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
        srvNode = (<<"ONLINE", "ONLINE", "ONLINE">>)
        /\
        loc = ((r1 :> [i |-> 1, sp |-> "lower"]))
        /\
        targetFired = (TRUE)
        /\
        dead = (<<"lower", "none", "none">>)
        /\
        rstate = ((r1 :> "CLOSING"))
        /\
        nextPid = (2)
        /\
        sc = (<<1, 2, 3>>)
        /\
        znode = (<<TRUE, TRUE, TRUE>>)
        /\
        mPhase = ("serviceStarted")
        /\
        rstView = ({1, 2})
        /\
        reported = (<<FALSE, FALSE, FALSE>>)
        /\
        incAddr = (<<1, 2, 1>>)
        /\
        rsTasks = (<<{}, {}, {}>>)
        /\
        dNode = (<<"lower", "lower", "lower">>)
        /\
        scp = (<<"START", "none", "none">>)
        /\
        rsPhase = (<<"exited", "online", "online">>)
        /\
        lastHost = ((r1 :> [i |-> 0, sp |-> "none"]))
        /\
        holder = (<<3, 2>>)
        /\
        rsRegions = (<<{}, {}, {}>>)
        /\
        trsp = ((r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]))
        /\
        rrp = (<<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>)
        /\
        buf = (<<{}, {}, {}>>)
        /\
        scpRegs = (<<{}, {}, {}>>)
        /\
        calls = ({[procs |-> {1}, att |-> 0, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "resp", snr |-> FALSE, ops |-> {1}, out |-> "dnr"]})
        /\
        failedSrv = ({})
        /\
        online = (<<"lower", "lower", "lower">>)
        /\
        fc = ([client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0])
        /\
        rsList = ({2, 3})
    )
----

_init ==
    /\ srvNode = _TETrace[1].srvNode
    /\ online = _TETrace[1].online
    /\ rsList = _TETrace[1].rsList
    /\ trsp = _TETrace[1].trsp
    /\ rstView = _TETrace[1].rstView
    /\ znode = _TETrace[1].znode
    /\ scp = _TETrace[1].scp
    /\ calls = _TETrace[1].calls
    /\ fc = _TETrace[1].fc
    /\ reported = _TETrace[1].reported
    /\ rsPhase = _TETrace[1].rsPhase
    /\ targetFired = _TETrace[1].targetFired
    /\ mPhase = _TETrace[1].mPhase
    /\ nextPid = _TETrace[1].nextPid
    /\ holder = _TETrace[1].holder
    /\ rrp = _TETrace[1].rrp
    /\ lastHost = _TETrace[1].lastHost
    /\ rsRegions = _TETrace[1].rsRegions
    /\ buf = _TETrace[1].buf
    /\ dead = _TETrace[1].dead
    /\ scpRegs = _TETrace[1].scpRegs
    /\ rstate = _TETrace[1].rstate
    /\ dNode = _TETrace[1].dNode
    /\ sc = _TETrace[1].sc
    /\ incAddr = _TETrace[1].incAddr
    /\ loc = _TETrace[1].loc
    /\ failedSrv = _TETrace[1].failedSrv
    /\ rsTasks = _TETrace[1].rsTasks
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ srvNode  = _TETrace[i].srvNode
        /\ srvNode' = _TETrace[j].srvNode
        /\ online  = _TETrace[i].online
        /\ online' = _TETrace[j].online
        /\ rsList  = _TETrace[i].rsList
        /\ rsList' = _TETrace[j].rsList
        /\ trsp  = _TETrace[i].trsp
        /\ trsp' = _TETrace[j].trsp
        /\ rstView  = _TETrace[i].rstView
        /\ rstView' = _TETrace[j].rstView
        /\ znode  = _TETrace[i].znode
        /\ znode' = _TETrace[j].znode
        /\ scp  = _TETrace[i].scp
        /\ scp' = _TETrace[j].scp
        /\ calls  = _TETrace[i].calls
        /\ calls' = _TETrace[j].calls
        /\ fc  = _TETrace[i].fc
        /\ fc' = _TETrace[j].fc
        /\ reported  = _TETrace[i].reported
        /\ reported' = _TETrace[j].reported
        /\ rsPhase  = _TETrace[i].rsPhase
        /\ rsPhase' = _TETrace[j].rsPhase
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ mPhase  = _TETrace[i].mPhase
        /\ mPhase' = _TETrace[j].mPhase
        /\ nextPid  = _TETrace[i].nextPid
        /\ nextPid' = _TETrace[j].nextPid
        /\ holder  = _TETrace[i].holder
        /\ holder' = _TETrace[j].holder
        /\ rrp  = _TETrace[i].rrp
        /\ rrp' = _TETrace[j].rrp
        /\ lastHost  = _TETrace[i].lastHost
        /\ lastHost' = _TETrace[j].lastHost
        /\ rsRegions  = _TETrace[i].rsRegions
        /\ rsRegions' = _TETrace[j].rsRegions
        /\ buf  = _TETrace[i].buf
        /\ buf' = _TETrace[j].buf
        /\ dead  = _TETrace[i].dead
        /\ dead' = _TETrace[j].dead
        /\ scpRegs  = _TETrace[i].scpRegs
        /\ scpRegs' = _TETrace[j].scpRegs
        /\ rstate  = _TETrace[i].rstate
        /\ rstate' = _TETrace[j].rstate
        /\ dNode  = _TETrace[i].dNode
        /\ dNode' = _TETrace[j].dNode
        /\ sc  = _TETrace[i].sc
        /\ sc' = _TETrace[j].sc
        /\ incAddr  = _TETrace[i].incAddr
        /\ incAddr' = _TETrace[j].incAddr
        /\ loc  = _TETrace[i].loc
        /\ loc' = _TETrace[j].loc
        /\ failedSrv  = _TETrace[i].failedSrv
        /\ failedSrv' = _TETrace[j].failedSrv
        /\ rsTasks  = _TETrace[i].rsTasks
        /\ rsTasks' = _TETrace[j].rsTasks

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187164.json", _TETrace)

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
        srvNode |-> srvNode
        ,online |-> online
        ,rsList |-> rsList
        ,trsp |-> trsp
        ,rstView |-> rstView
        ,znode |-> znode
        ,scp |-> scp
        ,calls |-> calls
        ,fc |-> fc
        ,reported |-> reported
        ,rsPhase |-> rsPhase
        ,targetFired |-> targetFired
        ,mPhase |-> mPhase
        ,nextPid |-> nextPid
        ,holder |-> holder
        ,rrp |-> rrp
        ,lastHost |-> lastHost
        ,rsRegions |-> rsRegions
        ,buf |-> buf
        ,dead |-> dead
        ,scpRegs |-> scpRegs
        ,rstate |-> rstate
        ,dNode |-> dNode
        ,sc |-> sc
        ,incAddr |-> incAddr
        ,loc |-> loc
        ,failedSrv |-> failedSrv
        ,rsTasks |-> rsTasks
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_srvNodeUnchanged |-> srvNode = srvNode'
        
        \* Format the `srvNode` variable as Json value.
        \* ,_srvNodeJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(srvNode)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_srvNodeModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].srvNode # _TETrace[s-1].srvNode
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
\*trace == IODeserialize("MC_TTrace_1794187164.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC, MC_TEConstants

trace == 
    <<
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "OPEN"),nextPid |-> 1,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"online", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<1, 2>>,rsRegions |-> <<{r1}, {}, {}>>,trsp |-> (r1 :> [type |-> "none", st |-> "none", cand |-> [i |-> 0, sp |-> "none"], fnp |-> FALSE, child |-> 0, parent |-> 0]),rrp |-> <<>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 0, stop |-> 0, crash |-> 0, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "OPEN"),nextPid |-> 1,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "none", st |-> "none", cand |-> [i |-> 0, sp |-> "none"], fnp |-> FALSE, child |-> 0, parent |-> 0]),rrp |-> <<>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 0, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "OPEN"),nextPid |-> 1,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CLOSE", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 0, parent |-> 0]),rrp |-> <<>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{1}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 0, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "run", snr |-> FALSE, ops |-> {}, out |-> "none"]},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 0, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "sent", snr |-> FALSE, ops |-> {1}, out |-> "none"]},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 0, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "resp", snr |-> FALSE, ops |-> {1}, out |-> "conn"]},failedSrv |-> {1},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 1, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "run", snr |-> FALSE, ops |-> {}, out |-> "none"]},failedSrv |-> {1},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 1, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "run", snr |-> FALSE, ops |-> {}, out |-> "none"]},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 1, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "sent", snr |-> FALSE, ops |-> {1}, out |-> "none"]},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<TRUE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"none", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 1, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "resp", snr |-> FALSE, ops |-> {1}, out |-> "conn"]},failedSrv |-> {1},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> 1..2]),
    ([srvNode |-> <<"CRASHED", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 0>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<FALSE, TRUE, FALSE>>,incAddr |-> <<1, 2, 0>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"none", "lower", "none">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "none">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<0, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {1},online |-> <<"none", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 0, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> {2}]),
    ([srvNode |-> <<"CRASHED", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "ready",rstView |-> 1..2,reported |-> <<FALSE, TRUE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"none", "lower", "none">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "bound">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {1},online |-> <<"none", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 0, snrye |-> 0, giveup |-> 0],rsList |-> {2}]),
    ([srvNode |-> <<"none", "none", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "down",rstView |-> {},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"none", "none", "none">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "bound">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"none", "none", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2}]),
    ([srvNode |-> <<"none", "none", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"none", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "down",rstView |-> {},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"none", "none", "none">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "started">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"none", "none", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "upgraded",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "started">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "none">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "none">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "started">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "none">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "ONLINE">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, FALSE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "lower">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "registered">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "lower">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2, 3}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "ONLINE">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, TRUE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "lower">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "registered">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "lower">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2, 3}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "ONLINE">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, TRUE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "lower">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "online">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> FALSE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "lower">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2, 3}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "ONLINE">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, TRUE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "lower">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "online">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{1}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {},failedSrv |-> {},online |-> <<"lower", "lower", "lower">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2, 3}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "ONLINE">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, TRUE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "lower">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "online">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 0, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "run", snr |-> FALSE, ops |-> {}, out |-> "none"]},failedSrv |-> {},online |-> <<"lower", "lower", "lower">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2, 3}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "ONLINE">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> FALSE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, TRUE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "lower">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "online">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 0, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "sent", snr |-> FALSE, ops |-> {1}, out |-> "none"]},failedSrv |-> {},online |-> <<"lower", "lower", "lower">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2, 3}]),
    ([srvNode |-> <<"ONLINE", "ONLINE", "ONLINE">>,loc |-> (r1 :> [i |-> 1, sp |-> "lower"]),targetFired |-> TRUE,dead |-> <<"lower", "none", "none">>,rstate |-> (r1 :> "CLOSING"),nextPid |-> 2,sc |-> <<1, 2, 3>>,znode |-> <<TRUE, TRUE, TRUE>>,mPhase |-> "serviceStarted",rstView |-> {1, 2},reported |-> <<FALSE, FALSE, FALSE>>,incAddr |-> <<1, 2, 1>>,rsTasks |-> <<{}, {}, {}>>,dNode |-> <<"lower", "lower", "lower">>,scp |-> <<"START", "none", "none">>,rsPhase |-> <<"exited", "online", "online">>,lastHost |-> (r1 :> [i |-> 0, sp |-> "none"]),holder |-> <<3, 2>>,rsRegions |-> <<{}, {}, {}>>,trsp |-> (r1 :> [type |-> "MOVE", st |-> "CONFIRM_CLOSED", cand |-> [i |-> 2, sp |-> "lower"], fnp |-> FALSE, child |-> 1, parent |-> 0]),rrp |-> <<[r |-> r1, k |-> "close", st |-> "DISPATCH", tgt |-> [i |-> 1, sp |-> "lower"], fin |-> FALSE, disp |-> TRUE]>>,buf |-> <<{}, {}, {}>>,scpRegs |-> <<{}, {}, {}>>,calls |-> {[procs |-> {1}, att |-> 0, sn |-> [i |-> 1, sp |-> "lower"], mode |-> "resp", snr |-> FALSE, ops |-> {1}, out |-> "dnr"]},failedSrv |-> {},online |-> <<"lower", "lower", "lower">>,fc |-> [client |-> 1, stop |-> 0, crash |-> 1, restart |-> 1, clock |-> 0, failover |-> 1, snrye |-> 0, giveup |-> 0],rsList |-> {2, 3}])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS r1

=============================================================================

---- CONFIG MC_TTrace_1794187164 ----
CONSTANTS
    NAddr = 2
    MaxInc = 3
    Region = { r1 }
    HostOf <- MCSameHost
    MixedCaseHost = FALSE
    ForceRetain = TRUE
    ScpRetain = TRUE
    FailFastLimit = 2
    MaxClientOps = 1
    MaxRsCrash = 1
    MaxRsDown = 1
    MaxRsRestart = 1
    MaxMasterFailover = 1
    MaxRsStop = 0
    MaxClockStepBack = 0
    MaxSnryeTimeout = 0
    MaxRetainGiveUp = 0
    MaxPid = 5
    FocusMode = "stillOnlineLateRegister"
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
\* Generated on Mon Nov 09 01:20:01 UTC 2026