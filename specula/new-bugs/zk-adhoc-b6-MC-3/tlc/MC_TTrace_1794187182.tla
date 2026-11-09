---- MODULE MC_TTrace_1794187182 ----
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
        omCommitted = (<<3>>)
        /\
        log = ([F |-> <<1, 2, 3>>, O |-> <<1>>])
        /\
        targetFired = (TRUE)
        /\
        omProposed = (<<>>)
        /\
        faults = ([fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1])
        /\
        inQ = ([F |-> <<>>, O |-> <<[type |-> "NEWLEADER", zxid |-> 0]>>])
        /\
        snapNeeded = ([F |-> TRUE, O |-> TRUE])
        /\
        lastQueued = ([F |-> 0, O |-> 3])
        /\
        pendingTxns = (<<>>)
        /\
        applyPending = ([F |-> 1, L |-> -1, O |-> -1])
        /\
        commitQ = ([F |-> <<2, 3>>, L |-> <<1, 2, 3>>, O |-> <<>>])
        /\
        phase = ([F |-> "broadcast", O |-> "sync"])
        /\
        hPhase = ([F |-> "done", O |-> "newleader"])
        /\
        snapMode = ([F |-> FALSE, O |-> FALSE])
        /\
        tree = ([F |-> 1, L |-> 0, O |-> 3])
        /\
        notLogged = ([F |-> <<>>, O |-> <<>>])
        /\
        omUp = (TRUE)
        /\
        wtl = ([F |-> FALSE, O |-> FALSE])
        /\
        clog = ([F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> FALSE, min |-> 1, max |-> 3]])
        /\
        nlAcked = ([F |-> FALSE, O |-> FALSE])
        /\
        lProposed = (3)
        /\
        omActive = (TRUE)
        /\
        lCommitted = (3)
        /\
        snap = ([F |-> 0, O |-> 0])
        /\
        committedIds = ([F |-> <<>>, O |-> <<>>])
    )
----

_init ==
    /\ phase = _TETrace[1].phase
    /\ targetFired = _TETrace[1].targetFired
    /\ hPhase = _TETrace[1].hPhase
    /\ lProposed = _TETrace[1].lProposed
    /\ snap = _TETrace[1].snap
    /\ log = _TETrace[1].log
    /\ wtl = _TETrace[1].wtl
    /\ committedIds = _TETrace[1].committedIds
    /\ tree = _TETrace[1].tree
    /\ omActive = _TETrace[1].omActive
    /\ faults = _TETrace[1].faults
    /\ nlAcked = _TETrace[1].nlAcked
    /\ lCommitted = _TETrace[1].lCommitted
    /\ pendingTxns = _TETrace[1].pendingTxns
    /\ inQ = _TETrace[1].inQ
    /\ omUp = _TETrace[1].omUp
    /\ notLogged = _TETrace[1].notLogged
    /\ snapMode = _TETrace[1].snapMode
    /\ omCommitted = _TETrace[1].omCommitted
    /\ clog = _TETrace[1].clog
    /\ commitQ = _TETrace[1].commitQ
    /\ omProposed = _TETrace[1].omProposed
    /\ applyPending = _TETrace[1].applyPending
    /\ snapNeeded = _TETrace[1].snapNeeded
    /\ lastQueued = _TETrace[1].lastQueued
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ phase  = _TETrace[i].phase
        /\ phase' = _TETrace[j].phase
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ hPhase  = _TETrace[i].hPhase
        /\ hPhase' = _TETrace[j].hPhase
        /\ lProposed  = _TETrace[i].lProposed
        /\ lProposed' = _TETrace[j].lProposed
        /\ snap  = _TETrace[i].snap
        /\ snap' = _TETrace[j].snap
        /\ log  = _TETrace[i].log
        /\ log' = _TETrace[j].log
        /\ wtl  = _TETrace[i].wtl
        /\ wtl' = _TETrace[j].wtl
        /\ committedIds  = _TETrace[i].committedIds
        /\ committedIds' = _TETrace[j].committedIds
        /\ tree  = _TETrace[i].tree
        /\ tree' = _TETrace[j].tree
        /\ omActive  = _TETrace[i].omActive
        /\ omActive' = _TETrace[j].omActive
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ nlAcked  = _TETrace[i].nlAcked
        /\ nlAcked' = _TETrace[j].nlAcked
        /\ lCommitted  = _TETrace[i].lCommitted
        /\ lCommitted' = _TETrace[j].lCommitted
        /\ pendingTxns  = _TETrace[i].pendingTxns
        /\ pendingTxns' = _TETrace[j].pendingTxns
        /\ inQ  = _TETrace[i].inQ
        /\ inQ' = _TETrace[j].inQ
        /\ omUp  = _TETrace[i].omUp
        /\ omUp' = _TETrace[j].omUp
        /\ notLogged  = _TETrace[i].notLogged
        /\ notLogged' = _TETrace[j].notLogged
        /\ snapMode  = _TETrace[i].snapMode
        /\ snapMode' = _TETrace[j].snapMode
        /\ omCommitted  = _TETrace[i].omCommitted
        /\ omCommitted' = _TETrace[j].omCommitted
        /\ clog  = _TETrace[i].clog
        /\ clog' = _TETrace[j].clog
        /\ commitQ  = _TETrace[i].commitQ
        /\ commitQ' = _TETrace[j].commitQ
        /\ omProposed  = _TETrace[i].omProposed
        /\ omProposed' = _TETrace[j].omProposed
        /\ applyPending  = _TETrace[i].applyPending
        /\ applyPending' = _TETrace[j].applyPending
        /\ snapNeeded  = _TETrace[i].snapNeeded
        /\ snapNeeded' = _TETrace[j].snapNeeded
        /\ lastQueued  = _TETrace[i].lastQueued
        /\ lastQueued' = _TETrace[j].lastQueued

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187182.json", _TETrace)

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
        phase |-> phase
        ,targetFired |-> targetFired
        ,hPhase |-> hPhase
        ,lProposed |-> lProposed
        ,snap |-> snap
        ,log |-> log
        ,wtl |-> wtl
        ,committedIds |-> committedIds
        ,tree |-> tree
        ,omActive |-> omActive
        ,faults |-> faults
        ,nlAcked |-> nlAcked
        ,lCommitted |-> lCommitted
        ,pendingTxns |-> pendingTxns
        ,inQ |-> inQ
        ,omUp |-> omUp
        ,notLogged |-> notLogged
        ,snapMode |-> snapMode
        ,omCommitted |-> omCommitted
        ,clog |-> clog
        ,commitQ |-> commitQ
        ,omProposed |-> omProposed
        ,applyPending |-> applyPending
        ,snapNeeded |-> snapNeeded
        ,lastQueued |-> lastQueued
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_phaseUnchanged |-> phase = phase'
        
        \* Format the `phase` variable as Json value.
        \* ,_phaseJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(phase)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_phaseModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].phase # _TETrace[s-1].phase
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
\*trace == IODeserialize("MC_TTrace_1794187182.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC

trace == 
    <<
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "down", O |-> "down"],hPhase |-> [F |-> "none", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 0,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "connecting", O |-> "down"],hPhase |-> [F |-> "none", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 0,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "DIFF", zxid |-> 0]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "awaitOp", O |-> "down"],hPhase |-> [F |-> "syncing", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 0,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "DIFF", zxid |-> 0], [type |-> "NEWLEADER", zxid |-> 0]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "awaitOp", O |-> "down"],hPhase |-> [F |-> "newleader", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 0,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "NEWLEADER", zxid |-> 0]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "newleader", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 0,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "newleader", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 0,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 0,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0], [type |-> "PROPOSAL", zxid |-> 1]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 1,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0], [type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 2,omActive |-> FALSE,lCommitted |-> 0,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0], [type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 2,omActive |-> FALSE,lCommitted |-> 1,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0], [type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 2,omActive |-> FALSE,lCommitted |-> 2,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0], [type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 3,omActive |-> FALSE,lCommitted |-> 2,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0], [type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 3,omActive |-> FALSE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "UPTODATE", zxid |-> 0], [type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> FALSE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "sync", O |-> "connecting"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> TRUE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> TRUE, O |-> FALSE],lProposed |-> 3,omActive |-> FALSE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "uptodate", O |-> "connecting"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> FALSE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> FALSE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "connecting"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> FALSE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "DIFF", zxid |-> 0]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "awaitOp"],hPhase |-> [F |-> "done", O |-> "syncing"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "DIFF", zxid |-> 0], [type |-> "NEWLEADER", zxid |-> 0]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "awaitOp"],hPhase |-> [F |-> "done", O |-> "newleader"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "NEWLEADER", zxid |-> 0]>>],snapNeeded |-> [F |-> TRUE, O |-> FALSE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "sync"],hPhase |-> [F |-> "done", O |-> "newleader"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> TRUE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> FALSE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "sync"],hPhase |-> [F |-> "done", O |-> "newleader"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> TRUE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> TRUE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "UPTODATE", zxid |-> 0]>>],snapNeeded |-> [F |-> TRUE, O |-> FALSE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "sync"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> TRUE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> TRUE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 1], [type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<1>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 2], [type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<1>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1, 2>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<1, 2>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 1], [type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<1, 2>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<1>>,log |-> [F |-> <<1, 2>>, O |-> <<>>],targetFired |-> FALSE,omProposed |-> <<2>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "INFORM", zxid |-> 1]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<2>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<1>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<1>>,log |-> [F |-> <<1, 2>>, O |-> <<1>>],targetFired |-> FALSE,omProposed |-> <<2>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<2>>,applyPending |-> [F |-> -1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<1>>, L |-> <<1, 2, 3>>, O |-> <<1>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 0, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<1>>,log |-> [F |-> <<1, 2>>, O |-> <<1>>],targetFired |-> FALSE,omProposed |-> <<2>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 0],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 2], [type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<2>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<>>, L |-> <<1, 2, 3>>, O |-> <<1>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1, 2>>, O |-> <<1>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<[type |-> "PROPOSAL", zxid |-> 3], [type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "INFORM", zxid |-> 2]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2>>, L |-> <<1, 2, 3>>, O |-> <<1>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1>>],targetFired |-> FALSE,omProposed |-> <<3>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "INFORM", zxid |-> 2]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<3>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2>>, L |-> <<1, 2, 3>>, O |-> <<1>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1, 2>>],targetFired |-> FALSE,omProposed |-> <<3>>,faults |-> [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<3>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2>>, L |-> <<1, 2, 3>>, O |-> <<1, 2>>],phase |-> [F |-> "broadcast", O |-> "broadcast"],hPhase |-> [F |-> "done", O |-> "done"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1, 2>>],targetFired |-> FALSE,omProposed |-> <<3>>,faults |-> [fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<3>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "down"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 0],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> TRUE, min |-> 0, max |-> 0]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> FALSE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1, 2>>],targetFired |-> FALSE,omProposed |-> <<3>>,faults |-> [fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 3]>>, O |-> <<>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<3>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "connecting"],hPhase |-> [F |-> "done", O |-> "none"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 2],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> FALSE, min |-> 1, max |-> 2]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> FALSE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1, 2>>],targetFired |-> FALSE,omProposed |-> <<3>>,faults |-> [fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<[type |-> "COMMIT", zxid |-> 3]>>, O |-> <<[type |-> "TRUNC", zxid |-> 1]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<3>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "awaitOp"],hPhase |-> [F |-> "done", O |-> "syncing"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 2],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> FALSE, min |-> 1, max |-> 2]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<3>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1, 2>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<>>, O |-> <<[type |-> "TRUNC", zxid |-> 1], [type |-> "INFORM", zxid |-> 3]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2, 3>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "awaitOp"],hPhase |-> [F |-> "done", O |-> "syncing"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 2],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> FALSE, min |-> 1, max |-> 2]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<3>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1, 2>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<>>, O |-> <<[type |-> "TRUNC", zxid |-> 1], [type |-> "INFORM", zxid |-> 3], [type |-> "NEWLEADER", zxid |-> 0]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2, 3>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "awaitOp"],hPhase |-> [F |-> "done", O |-> "newleader"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 2],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> FALSE, min |-> 1, max |-> 2]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<3>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1>>],targetFired |-> FALSE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<>>, O |-> <<[type |-> "INFORM", zxid |-> 3], [type |-> "NEWLEADER", zxid |-> 0]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 0],pendingTxns |-> <<>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2, 3>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "sync"],hPhase |-> [F |-> "done", O |-> "newleader"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 1],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> FALSE, min |-> 1, max |-> 1]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]]),
    ([omCommitted |-> <<3>>,log |-> [F |-> <<1, 2, 3>>, O |-> <<1>>],targetFired |-> TRUE,omProposed |-> <<>>,faults |-> [fRestart |-> 0, oRestart |-> 1, syncProp |-> 0, syncCommit |-> 0, evict |-> 1],inQ |-> [F |-> <<>>, O |-> <<[type |-> "NEWLEADER", zxid |-> 0]>>],snapNeeded |-> [F |-> TRUE, O |-> TRUE],lastQueued |-> [F |-> 0, O |-> 3],pendingTxns |-> <<>>,applyPending |-> [F |-> 1, L |-> -1, O |-> -1],commitQ |-> [F |-> <<2, 3>>, L |-> <<1, 2, 3>>, O |-> <<>>],phase |-> [F |-> "broadcast", O |-> "sync"],hPhase |-> [F |-> "done", O |-> "newleader"],snapMode |-> [F |-> FALSE, O |-> FALSE],tree |-> [F |-> 1, L |-> 0, O |-> 3],notLogged |-> [F |-> <<>>, O |-> <<>>],omUp |-> TRUE,wtl |-> [F |-> FALSE, O |-> FALSE],clog |-> [F |-> [empty |-> TRUE, min |-> 0, max |-> 0], L |-> [empty |-> TRUE, min |-> 0, max |-> 0], O |-> [empty |-> FALSE, min |-> 1, max |-> 3]],nlAcked |-> [F |-> FALSE, O |-> FALSE],lProposed |-> 3,omActive |-> TRUE,lCommitted |-> 3,snap |-> [F |-> 0, O |-> 0],committedIds |-> [F |-> <<>>, O |-> <<>>]])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187182 ----
CONSTANTS
    MaxTxn = 4
    MaxFollowerRestart = 0
    MaxObserverRestart = 1
    MaxSyncWindowProposals = 0
    MaxCommitDuringSync = 0
    MaxEvictingPackets = 1
    S2Only = FALSE

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
\* Generated on Mon Nov 09 01:20:00 UTC 2026