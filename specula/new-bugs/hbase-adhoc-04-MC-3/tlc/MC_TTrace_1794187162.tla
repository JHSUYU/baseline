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
        proc = ([F |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> TRUE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]])
        /\
        tState = ("DISABLED")
        /\
        obsCur = ("OBS")
        /\
        targetFired = (TRUE)
        /\
        run = (2)
        /\
        dcall = ("none")
        /\
        faults = ([noEffect |-> 0, lateEffect |-> 0, crash |-> 1])
        /\
        xlock = ("none")
        /\
        fcall = ("submitted")
        /\
        master = ("ACTIVE")
        /\
        lockWait = (<<>>)
        /\
        obsMem = ("OBS")
        /\
        firedSite = ("F")
        /\
        testPc = ("FlushWait")
        /\
        wk = ((w1 :> [p |-> "F", pc |-> "running"] @@ w2 :> [p |-> "none", pc |-> "idle"]))
        /\
        quotaRow = ("OBS")
        /\
        eclient = ("none")
        /\
        slock = ({"F"})
        /\
        ecall = ("none")
        /\
        rq = (<<>>)
    )
----

_init ==
    /\ proc = _TETrace[1].proc
    /\ firedSite = _TETrace[1].firedSite
    /\ eclient = _TETrace[1].eclient
    /\ dcall = _TETrace[1].dcall
    /\ targetFired = _TETrace[1].targetFired
    /\ xlock = _TETrace[1].xlock
    /\ faults = _TETrace[1].faults
    /\ tState = _TETrace[1].tState
    /\ ecall = _TETrace[1].ecall
    /\ testPc = _TETrace[1].testPc
    /\ rq = _TETrace[1].rq
    /\ fcall = _TETrace[1].fcall
    /\ quotaRow = _TETrace[1].quotaRow
    /\ obsMem = _TETrace[1].obsMem
    /\ run = _TETrace[1].run
    /\ slock = _TETrace[1].slock
    /\ master = _TETrace[1].master
    /\ wk = _TETrace[1].wk
    /\ lockWait = _TETrace[1].lockWait
    /\ obsCur = _TETrace[1].obsCur
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ proc  = _TETrace[i].proc
        /\ proc' = _TETrace[j].proc
        /\ firedSite  = _TETrace[i].firedSite
        /\ firedSite' = _TETrace[j].firedSite
        /\ eclient  = _TETrace[i].eclient
        /\ eclient' = _TETrace[j].eclient
        /\ dcall  = _TETrace[i].dcall
        /\ dcall' = _TETrace[j].dcall
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ xlock  = _TETrace[i].xlock
        /\ xlock' = _TETrace[j].xlock
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ tState  = _TETrace[i].tState
        /\ tState' = _TETrace[j].tState
        /\ ecall  = _TETrace[i].ecall
        /\ ecall' = _TETrace[j].ecall
        /\ testPc  = _TETrace[i].testPc
        /\ testPc' = _TETrace[j].testPc
        /\ rq  = _TETrace[i].rq
        /\ rq' = _TETrace[j].rq
        /\ fcall  = _TETrace[i].fcall
        /\ fcall' = _TETrace[j].fcall
        /\ quotaRow  = _TETrace[i].quotaRow
        /\ quotaRow' = _TETrace[j].quotaRow
        /\ obsMem  = _TETrace[i].obsMem
        /\ obsMem' = _TETrace[j].obsMem
        /\ run  = _TETrace[i].run
        /\ run' = _TETrace[j].run
        /\ slock  = _TETrace[i].slock
        /\ slock' = _TETrace[j].slock
        /\ master  = _TETrace[i].master
        /\ master' = _TETrace[j].master
        /\ wk  = _TETrace[i].wk
        /\ wk' = _TETrace[j].wk
        /\ lockWait  = _TETrace[i].lockWait
        /\ lockWait' = _TETrace[j].lockWait
        /\ obsCur  = _TETrace[i].obsCur
        /\ obsCur' = _TETrace[j].obsCur

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
        proc |-> proc
        ,firedSite |-> firedSite
        ,eclient |-> eclient
        ,dcall |-> dcall
        ,targetFired |-> targetFired
        ,xlock |-> xlock
        ,faults |-> faults
        ,tState |-> tState
        ,ecall |-> ecall
        ,testPc |-> testPc
        ,rq |-> rq
        ,fcall |-> fcall
        ,quotaRow |-> quotaRow
        ,obsMem |-> obsMem
        ,run |-> run
        ,slock |-> slock
        ,master |-> master
        ,wk |-> wk
        ,lockWait |-> lockWait
        ,obsCur |-> obsCur
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_procUnchanged |-> proc = proc'
        
        \* Format the `proc` variable as Json value.
        \* ,_procJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(proc)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_procModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].proc # _TETrace[s-1].proc
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
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "ENABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "Disable",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "ENABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "queued",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "ENABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "ctorOk",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "ENABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<"D">>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "ENABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "D", pc |-> "polled"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> TRUE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "ENABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "D",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "D", pc |-> "running"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "WAITING", step |-> "ADD_REPLICATION_BARRIER", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLING",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "RUNNABLE", step |-> "ADD_REPLICATION_BARRIER", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLING",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<"D">>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "RUNNABLE", step |-> "ADD_REPLICATION_BARRIER", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLING",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "D", pc |-> "polled"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "RUNNABLE", step |-> "ADD_REPLICATION_BARRIER", locked |-> TRUE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLING",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "D",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "D", pc |-> "running"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "submitted",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "DisableWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "NONE",firedSite |-> "none",testPc |-> "ObsSetup",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "NONE",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "VIOL",firedSite |-> "none",testPc |-> "ObsCompare",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "VIOL",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 0],xlock |-> "none",fcall |-> "none",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "VIOL",firedSite |-> "none",testPc |-> "ObsPut",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "VIOL",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "VIOL",firedSite |-> "none",testPc |-> "ObsPut",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "ABSENT",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "VIOL",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "VIOL",firedSite |-> "none",testPc |-> "ObsMemUpdate",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "VIOL",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "ObsEnable",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "VIOL",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "ObsEnableWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "awaitSubmit",slock |-> {},ecall |-> "queued",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "VIOL",targetFired |-> FALSE,run |-> 0,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "ObsRunEnd",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "VIOL",targetFired |-> FALSE,run |-> 1,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "ObsCompare",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 1,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "ObsRunEnd",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "none",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "Flush",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "queued",master |-> "DOWN",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "FlushWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "queued",master |-> "INIT",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "FlushWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "queued",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "FlushWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "submitted",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "FlushWait",wk |-> (w1 :> [p |-> "none", pc |-> "idle"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<"F">>]),
    ([proc |-> [F |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> FALSE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "submitted",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "FlushWait",wk |-> (w1 :> [p |-> "F", pc |-> "polled"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> TRUE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> FALSE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "submitted",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "none",testPc |-> "FlushWait",wk |-> (w1 :> [p |-> "F", pc |-> "running"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {"F"},ecall |-> "none",rq |-> <<>>]),
    ([proc |-> [F |-> [st |-> "RUNNABLE", step |-> "PREPARE", locked |-> TRUE], D |-> [st |-> "SUCCESS", step |-> "DONE", locked |-> FALSE], E |-> [st |-> "NONE", step |-> "PREPARE", locked |-> FALSE]],tState |-> "DISABLED",obsCur |-> "OBS",targetFired |-> TRUE,run |-> 2,dcall |-> "none",faults |-> [noEffect |-> 0, lateEffect |-> 0, crash |-> 1],xlock |-> "none",fcall |-> "submitted",master |-> "ACTIVE",lockWait |-> <<>>,obsMem |-> "OBS",firedSite |-> "F",testPc |-> "FlushWait",wk |-> (w1 :> [p |-> "F", pc |-> "running"] @@ w2 :> [p |-> "none", pc |-> "idle"]),quotaRow |-> "OBS",eclient |-> "none",slock |-> {"F"},ecall |-> "none",rq |-> <<>>])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS w1, w2

=============================================================================

---- CONFIG MC_TTrace_1794187162 ----
CONSTANTS
    Workers = { w1 , w2 }
    MaxObsRpcFailNoEffect = 0
    MaxObsRpcFailLateEffect = 0
    MaxMasterCrash = 1
    w1 = w1
    w2 = w2

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