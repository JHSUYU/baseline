---- MODULE MC_TTrace_1794187168 ----
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
        dnRegC = (-1)
        /\
        cur = ((v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]))
        /\
        nnC = (1)
        /\
        trashEnabled = (FALSE)
        /\
        mustRollback = (FALSE)
        /\
        finTmp = ((v1 :> FALSE @@ v2 :> FALSE))
        /\
        dnPrev = ((v1 :> FALSE @@ v2 :> FALSE))
        /\
        prev = ((v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]))
        /\
        targetFired = (TRUE)
        /\
        startOpt = ("ROLLBACK")
        /\
        bpLoaded = ({})
        /\
        remTmp = ((v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]))
        /\
        issued = ({1, 2})
        /\
        nsC = (1)
        /\
        dnOk = ((v1 :> TRUE @@ v2 :> TRUE))
        /\
        dnUp = (TRUE)
        /\
        ruAfterImage = (FALSE)
        /\
        prevTmp = ((v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]))
        /\
        nnPrevC = (-1)
        /\
        trash = ((v1 :> FALSE @@ v2 :> FALSE))
        /\
        memLV = (-57)
        /\
        nnRU = ("none")
        /\
        dnLoaded = ({v1, v2})
        /\
        marker = ((v1 :> FALSE @@ v2 :> FALSE))
        /\
        bpInit = ("loading")
        /\
        visited = ({v1})
        /\
        ld = ((v1 :> [pc |-> "Fail", mode |-> "startup", c405 |-> 2, err |-> "B421"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]))
        /\
        online = ((v1 :> TRUE @@ v2 :> TRUE))
        /\
        fc = ([dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0])
        /\
        memC = (2)
    )
----

_init ==
    /\ online = _TETrace[1].online
    /\ marker = _TETrace[1].marker
    /\ startOpt = _TETrace[1].startOpt
    /\ issued = _TETrace[1].issued
    /\ mustRollback = _TETrace[1].mustRollback
    /\ nnPrevC = _TETrace[1].nnPrevC
    /\ ruAfterImage = _TETrace[1].ruAfterImage
    /\ trash = _TETrace[1].trash
    /\ memLV = _TETrace[1].memLV
    /\ dnOk = _TETrace[1].dnOk
    /\ fc = _TETrace[1].fc
    /\ prev = _TETrace[1].prev
    /\ dnRegC = _TETrace[1].dnRegC
    /\ trashEnabled = _TETrace[1].trashEnabled
    /\ remTmp = _TETrace[1].remTmp
    /\ targetFired = _TETrace[1].targetFired
    /\ nnC = _TETrace[1].nnC
    /\ prevTmp = _TETrace[1].prevTmp
    /\ visited = _TETrace[1].visited
    /\ ld = _TETrace[1].ld
    /\ dnUp = _TETrace[1].dnUp
    /\ nsC = _TETrace[1].nsC
    /\ memC = _TETrace[1].memC
    /\ dnLoaded = _TETrace[1].dnLoaded
    /\ finTmp = _TETrace[1].finTmp
    /\ nnRU = _TETrace[1].nnRU
    /\ dnPrev = _TETrace[1].dnPrev
    /\ cur = _TETrace[1].cur
    /\ bpInit = _TETrace[1].bpInit
    /\ bpLoaded = _TETrace[1].bpLoaded
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ online  = _TETrace[i].online
        /\ online' = _TETrace[j].online
        /\ marker  = _TETrace[i].marker
        /\ marker' = _TETrace[j].marker
        /\ startOpt  = _TETrace[i].startOpt
        /\ startOpt' = _TETrace[j].startOpt
        /\ issued  = _TETrace[i].issued
        /\ issued' = _TETrace[j].issued
        /\ mustRollback  = _TETrace[i].mustRollback
        /\ mustRollback' = _TETrace[j].mustRollback
        /\ nnPrevC  = _TETrace[i].nnPrevC
        /\ nnPrevC' = _TETrace[j].nnPrevC
        /\ ruAfterImage  = _TETrace[i].ruAfterImage
        /\ ruAfterImage' = _TETrace[j].ruAfterImage
        /\ trash  = _TETrace[i].trash
        /\ trash' = _TETrace[j].trash
        /\ memLV  = _TETrace[i].memLV
        /\ memLV' = _TETrace[j].memLV
        /\ dnOk  = _TETrace[i].dnOk
        /\ dnOk' = _TETrace[j].dnOk
        /\ fc  = _TETrace[i].fc
        /\ fc' = _TETrace[j].fc
        /\ prev  = _TETrace[i].prev
        /\ prev' = _TETrace[j].prev
        /\ dnRegC  = _TETrace[i].dnRegC
        /\ dnRegC' = _TETrace[j].dnRegC
        /\ trashEnabled  = _TETrace[i].trashEnabled
        /\ trashEnabled' = _TETrace[j].trashEnabled
        /\ remTmp  = _TETrace[i].remTmp
        /\ remTmp' = _TETrace[j].remTmp
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ nnC  = _TETrace[i].nnC
        /\ nnC' = _TETrace[j].nnC
        /\ prevTmp  = _TETrace[i].prevTmp
        /\ prevTmp' = _TETrace[j].prevTmp
        /\ visited  = _TETrace[i].visited
        /\ visited' = _TETrace[j].visited
        /\ ld  = _TETrace[i].ld
        /\ ld' = _TETrace[j].ld
        /\ dnUp  = _TETrace[i].dnUp
        /\ dnUp' = _TETrace[j].dnUp
        /\ nsC  = _TETrace[i].nsC
        /\ nsC' = _TETrace[j].nsC
        /\ memC  = _TETrace[i].memC
        /\ memC' = _TETrace[j].memC
        /\ dnLoaded  = _TETrace[i].dnLoaded
        /\ dnLoaded' = _TETrace[j].dnLoaded
        /\ finTmp  = _TETrace[i].finTmp
        /\ finTmp' = _TETrace[j].finTmp
        /\ nnRU  = _TETrace[i].nnRU
        /\ nnRU' = _TETrace[j].nnRU
        /\ dnPrev  = _TETrace[i].dnPrev
        /\ dnPrev' = _TETrace[j].dnPrev
        /\ cur  = _TETrace[i].cur
        /\ cur' = _TETrace[j].cur
        /\ bpInit  = _TETrace[i].bpInit
        /\ bpInit' = _TETrace[j].bpInit
        /\ bpLoaded  = _TETrace[i].bpLoaded
        /\ bpLoaded' = _TETrace[j].bpLoaded

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187168.json", _TETrace)

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
        online |-> online
        ,marker |-> marker
        ,startOpt |-> startOpt
        ,issued |-> issued
        ,mustRollback |-> mustRollback
        ,nnPrevC |-> nnPrevC
        ,ruAfterImage |-> ruAfterImage
        ,trash |-> trash
        ,memLV |-> memLV
        ,dnOk |-> dnOk
        ,fc |-> fc
        ,prev |-> prev
        ,dnRegC |-> dnRegC
        ,trashEnabled |-> trashEnabled
        ,remTmp |-> remTmp
        ,targetFired |-> targetFired
        ,nnC |-> nnC
        ,prevTmp |-> prevTmp
        ,visited |-> visited
        ,ld |-> ld
        ,dnUp |-> dnUp
        ,nsC |-> nsC
        ,memC |-> memC
        ,dnLoaded |-> dnLoaded
        ,finTmp |-> finTmp
        ,nnRU |-> nnRU
        ,dnPrev |-> dnPrev
        ,cur |-> cur
        ,bpInit |-> bpInit
        ,bpLoaded |-> bpLoaded
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_onlineUnchanged |-> online = online'
        
        \* Format the `online` variable as Json value.
        \* ,_onlineJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(online)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_onlineModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].online # _TETrace[s-1].online
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
\*trace == IODeserialize("MC_TTrace_1794187168.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC, MC_TEConstants

trace == 
    <<
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 1, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1},nsC |-> -1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> FALSE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "none",visited |-> {},ld |-> (v1 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 0, dnCrash |-> 0, nnUpgrade |-> 0, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 0, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> -1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 1, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> -1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> FALSE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "none",visited |-> {},ld |-> (v1 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 0, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 0, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> -1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> -1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> FALSE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "none",visited |-> {},ld |-> (v1 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 0, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> -1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 2,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {},ld |-> (v1 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 2,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "Analyze", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 2,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "FormatLV", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 2,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "FormatC", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 2,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "FormatWrite", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 2,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "Dispatch", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 0, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 2,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> -1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> FALSE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> 1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "none",visited |-> {},ld |-> (v1 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 0, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> -1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> TRUE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "REGULAR",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> -1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> FALSE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "none",visited |-> {},ld |-> (v1 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 1, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> -1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {},ld |-> (v1 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "Analyze", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "Dispatch", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "RbRestoreTrash", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> 0,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "ReadPropsLV", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "ReadPropsC", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 1]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "L404", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "L405", mode |-> "startup", c405 |-> -1, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "L408", mode |-> "startup", c405 |-> 2, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "L414", mode |-> "startup", c405 |-> 2, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> FALSE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "TargetCheck", mode |-> "startup", c405 |-> 2, err |-> "none"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2]),
    ([dnRegC |-> -1,cur |-> (v1 :> [c |-> 2, ok |-> TRUE, lv |-> -57] @@ v2 :> [c |-> 1, ok |-> TRUE, lv |-> -57]),nnC |-> 1,trashEnabled |-> FALSE,mustRollback |-> FALSE,finTmp |-> (v1 :> FALSE @@ v2 :> FALSE),dnPrev |-> (v1 :> FALSE @@ v2 :> FALSE),prev |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),targetFired |-> TRUE,startOpt |-> "ROLLBACK",bpLoaded |-> {},remTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),issued |-> {1, 2},nsC |-> 1,dnOk |-> (v1 :> TRUE @@ v2 :> TRUE),dnUp |-> TRUE,ruAfterImage |-> FALSE,prevTmp |-> (v1 :> [c |-> -1, ok |-> FALSE, lv |-> 0] @@ v2 :> [c |-> -1, ok |-> FALSE, lv |-> 0]),nnPrevC |-> -1,trash |-> (v1 :> FALSE @@ v2 :> FALSE),memLV |-> -57,nnRU |-> "none",dnLoaded |-> {v1, v2},marker |-> (v1 :> FALSE @@ v2 :> FALSE),bpInit |-> "loading",visited |-> {v1},ld |-> (v1 :> [pc |-> "Fail", mode |-> "startup", c405 |-> 2, err |-> "B421"] @@ v2 :> [pc |-> "idle", mode |-> "none", c405 |-> -1, err |-> "none"]),online |-> (v1 :> TRUE @@ v2 :> TRUE),fc |-> [dnStart |-> 2, dnCrash |-> 1, nnUpgrade |-> 1, clock |-> 0, nnRollback |-> 1, nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 1, hotswap |-> 0, ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0],memC |-> 2])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS v1, v2

=============================================================================

---- CONFIG MC_TTrace_1794187168 ----
CONSTANTS
    Vol = { v1 , v2 }
    InitLVs <- MCInitLVsCur
    MaxDNStarts = 3
    MaxDNCrashes = 1
    MaxNNUpgrades = 1
    MaxClockFaults = 0
    MaxNNRollbacks = 1
    MaxNNFinalizes = 0
    MaxCTimeRegress = 0
    MaxOffline = 1
    MaxAttach = 1
    MaxHotSwaps = 1
    MaxRUStarts = 0
    MaxRUFinalizes = 0
    MaxCheckpoints = 0
    MaxNNRestarts = 0
    v1 = v1
    v2 = v2

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
\* Generated on Mon Nov 09 01:19:30 UTC 2026