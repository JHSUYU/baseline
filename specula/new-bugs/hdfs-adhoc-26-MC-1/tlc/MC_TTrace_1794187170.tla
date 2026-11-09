---- MODULE MC_TTrace_1794187170 ----
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
        dnNs = ([dn0 |-> 2])
        /\
        nnCur = (2)
        /\
        dnSwLV = ([dn0 |-> -57])
        /\
        volBpFault = ([dn0 |-> <<FALSE, FALSE>>])
        /\
        volLoad = ([dn0 |-> <<"dn", "dn">>])
        /\
        nnHist = ({2, 4, 6})
        /\
        targetFired = (TRUE)
        /\
        volCur = ([dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>])
        /\
        volPrev = ([dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>])
        /\
        dnPending = ([dn0 |-> <<2>>])
        /\
        nnUp = (TRUE)
        /\
        clock = (8)
        /\
        dnRegCT = ([dn0 |-> 2])
        /\
        faults = ([upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0])
        /\
        volTmp = ([dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>])
        /\
        dnCont = ([dn0 |-> {}])
        /\
        dnOut = ([dn0 |-> FALSE])
        /\
        opPhase = ("ROLLEDBACK")
        /\
        dnPc = ([dn0 |-> "loading"])
        /\
        volOnline = ([dn0 |-> <<TRUE, TRUE>>])
        /\
        dnRolledBack = ([dn0 |-> FALSE])
        /\
        nnPrev = (0)
        /\
        dnOpt = ([dn0 |-> "ROLLBACK"])
    )
----

_init ==
    /\ nnCur = _TETrace[1].nnCur
    /\ dnPc = _TETrace[1].dnPc
    /\ dnPending = _TETrace[1].dnPending
    /\ nnHist = _TETrace[1].nnHist
    /\ targetFired = _TETrace[1].targetFired
    /\ dnRegCT = _TETrace[1].dnRegCT
    /\ dnSwLV = _TETrace[1].dnSwLV
    /\ clock = _TETrace[1].clock
    /\ nnUp = _TETrace[1].nnUp
    /\ dnOut = _TETrace[1].dnOut
    /\ volCur = _TETrace[1].volCur
    /\ volTmp = _TETrace[1].volTmp
    /\ faults = _TETrace[1].faults
    /\ dnCont = _TETrace[1].dnCont
    /\ volOnline = _TETrace[1].volOnline
    /\ volBpFault = _TETrace[1].volBpFault
    /\ opPhase = _TETrace[1].opPhase
    /\ volLoad = _TETrace[1].volLoad
    /\ volPrev = _TETrace[1].volPrev
    /\ nnPrev = _TETrace[1].nnPrev
    /\ dnNs = _TETrace[1].dnNs
    /\ dnOpt = _TETrace[1].dnOpt
    /\ dnRolledBack = _TETrace[1].dnRolledBack
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ nnCur  = _TETrace[i].nnCur
        /\ nnCur' = _TETrace[j].nnCur
        /\ dnPc  = _TETrace[i].dnPc
        /\ dnPc' = _TETrace[j].dnPc
        /\ dnPending  = _TETrace[i].dnPending
        /\ dnPending' = _TETrace[j].dnPending
        /\ nnHist  = _TETrace[i].nnHist
        /\ nnHist' = _TETrace[j].nnHist
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ dnRegCT  = _TETrace[i].dnRegCT
        /\ dnRegCT' = _TETrace[j].dnRegCT
        /\ dnSwLV  = _TETrace[i].dnSwLV
        /\ dnSwLV' = _TETrace[j].dnSwLV
        /\ clock  = _TETrace[i].clock
        /\ clock' = _TETrace[j].clock
        /\ nnUp  = _TETrace[i].nnUp
        /\ nnUp' = _TETrace[j].nnUp
        /\ dnOut  = _TETrace[i].dnOut
        /\ dnOut' = _TETrace[j].dnOut
        /\ volCur  = _TETrace[i].volCur
        /\ volCur' = _TETrace[j].volCur
        /\ volTmp  = _TETrace[i].volTmp
        /\ volTmp' = _TETrace[j].volTmp
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ dnCont  = _TETrace[i].dnCont
        /\ dnCont' = _TETrace[j].dnCont
        /\ volOnline  = _TETrace[i].volOnline
        /\ volOnline' = _TETrace[j].volOnline
        /\ volBpFault  = _TETrace[i].volBpFault
        /\ volBpFault' = _TETrace[j].volBpFault
        /\ opPhase  = _TETrace[i].opPhase
        /\ opPhase' = _TETrace[j].opPhase
        /\ volLoad  = _TETrace[i].volLoad
        /\ volLoad' = _TETrace[j].volLoad
        /\ volPrev  = _TETrace[i].volPrev
        /\ volPrev' = _TETrace[j].volPrev
        /\ nnPrev  = _TETrace[i].nnPrev
        /\ nnPrev' = _TETrace[j].nnPrev
        /\ dnNs  = _TETrace[i].dnNs
        /\ dnNs' = _TETrace[j].dnNs
        /\ dnOpt  = _TETrace[i].dnOpt
        /\ dnOpt' = _TETrace[j].dnOpt
        /\ dnRolledBack  = _TETrace[i].dnRolledBack
        /\ dnRolledBack' = _TETrace[j].dnRolledBack

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187170.json", _TETrace)

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
        nnCur |-> nnCur
        ,dnPc |-> dnPc
        ,dnPending |-> dnPending
        ,nnHist |-> nnHist
        ,targetFired |-> targetFired
        ,dnRegCT |-> dnRegCT
        ,dnSwLV |-> dnSwLV
        ,clock |-> clock
        ,nnUp |-> nnUp
        ,dnOut |-> dnOut
        ,volCur |-> volCur
        ,volTmp |-> volTmp
        ,faults |-> faults
        ,dnCont |-> dnCont
        ,volOnline |-> volOnline
        ,volBpFault |-> volBpFault
        ,opPhase |-> opPhase
        ,volLoad |-> volLoad
        ,volPrev |-> volPrev
        ,nnPrev |-> nnPrev
        ,dnNs |-> dnNs
        ,dnOpt |-> dnOpt
        ,dnRolledBack |-> dnRolledBack
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_nnCurUnchanged |-> nnCur = nnCur'
        
        \* Format the `nnCur` variable as Json value.
        \* ,_nnCurJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(nnCur)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_nnCurModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].nnCur # _TETrace[s-1].nnCur
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
\*trace == IODeserialize("MC_TTrace_1794187170.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC

trace == 
    <<
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> FALSE,clock |-> 4,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 0, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "NORMAL",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<1, 2>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "handshake"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 4],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<1, 2>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 4],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 4],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 2, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<2>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 2],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {1}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 4],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 2],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnCont |-> [dn0 |-> {1, 2}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 4],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"bp", "dn">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 0, lv |-> 0]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 4],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 2, lv |-> -57]>>],dnCont |-> [dn0 |-> {2}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 4],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"bp", "bp">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 4],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 4],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"bp", "bp">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 4],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "registering"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 6,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 4,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> FALSE,clock |-> 6,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> FALSE,clock |-> 6,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 1, dnOutages |-> 0, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "ROLLEDBACK",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> FALSE,clock |-> 6,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 1, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> TRUE],opPhase |-> "ROLLEDBACK",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> FALSE,clock |-> 6,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 1, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> TRUE],opPhase |-> "NORMAL",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> TRUE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<1, 2>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "handshake"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 6],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 2, lv |-> -57], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<1, 2>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 6],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 6],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 4, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 2, lv |-> -57]>>],dnPending |-> [dn0 |-> <<2>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 4],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {1}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 6],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 4],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnCont |-> [dn0 |-> {1, 2}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 6],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "bp">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 6],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {1}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 6],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"bp", "bp">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 6],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 6],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"bp", "bp">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 6],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "registering"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 6,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> FALSE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "UPGRADED",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 2,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> FALSE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "ROLLEDBACK",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "ROLLEDBACK",dnPc |-> [dn0 |-> "down"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "REGULAR"]]),
    ([dnNs |-> [dn0 |-> 0],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"none", "none">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<1, 2>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 0],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "ROLLEDBACK",dnPc |-> [dn0 |-> "handshake"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "ROLLBACK"]]),
    ([dnNs |-> [dn0 |-> 2],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4, 6},targetFired |-> FALSE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<1, 2>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 2],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "ROLLEDBACK",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "ROLLBACK"]]),
    ([dnNs |-> [dn0 |-> 2],nnCur |-> 2,dnSwLV |-> [dn0 |-> -57],volBpFault |-> [dn0 |-> <<FALSE, FALSE>>],volLoad |-> [dn0 |-> <<"dn", "dn">>],nnHist |-> {2, 4, 6},targetFired |-> TRUE,volCur |-> [dn0 |-> <<[ct |-> 6, lv |-> -57], [ct |-> 6, lv |-> -57]>>],volPrev |-> [dn0 |-> <<[ct |-> 4, lv |-> -57], [ct |-> 4, lv |-> -57]>>],dnPending |-> [dn0 |-> <<2>>],nnUp |-> TRUE,clock |-> 8,dnRegCT |-> [dn0 |-> 2],faults |-> [upgrades |-> 2, dnOutages |-> 1, volOutages |-> 0, volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0],volTmp |-> [dn0 |-> <<[ct |-> 0, lv |-> 0], [ct |-> 0, lv |-> 0]>>],dnCont |-> [dn0 |-> {}],dnOut |-> [dn0 |-> FALSE],opPhase |-> "ROLLEDBACK",dnPc |-> [dn0 |-> "loading"],volOnline |-> [dn0 |-> <<TRUE, TRUE>>],dnRolledBack |-> [dn0 |-> FALSE],nnPrev |-> 0,dnOpt |-> [dn0 |-> "ROLLBACK"]])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187170 ----
CONSTANTS
    DN = { "dn0" }
    NumVols = 2
    MaxCT = 9
    FormatCT = 2
    Tolerated = 0
    MaxUpgrades = 2
    MaxDNOutages = 1
    MaxVolOutages = 0
    MaxVolReplacements = 0
    MaxSwUpgrades = 0
    MaxClockSkews = 0

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
\* Generated on Mon Nov 09 01:19:31 UTC 2026