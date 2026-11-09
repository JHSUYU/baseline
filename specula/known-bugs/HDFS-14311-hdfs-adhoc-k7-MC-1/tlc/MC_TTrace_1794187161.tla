---- MODULE MC_TTrace_1794187161 ----
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
        loc = ((<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]))
        /\
        bpCT = (2)
        /\
        disk = (<<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>)
        /\
        pc = ((<<"main", 0>> :> "join" @@ <<"task", 1>> :> "uWpLV" @@ <<"task", 2>> :> "idle"))
        /\
        bpLV = (1)
        /\
        curVol = (2)
        /\
        targetFired = (TRUE)
        /\
        volRes = (<<"upgrading", "failed">>)
        /\
        diskInit = (<<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>)
        /\
        interference = (1)
    )
----

_init ==
    /\ bpLV = _TETrace[1].bpLV
    /\ targetFired = _TETrace[1].targetFired
    /\ loc = _TETrace[1].loc
    /\ pc = _TETrace[1].pc
    /\ disk = _TETrace[1].disk
    /\ bpCT = _TETrace[1].bpCT
    /\ volRes = _TETrace[1].volRes
    /\ curVol = _TETrace[1].curVol
    /\ diskInit = _TETrace[1].diskInit
    /\ interference = _TETrace[1].interference
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ bpLV  = _TETrace[i].bpLV
        /\ bpLV' = _TETrace[j].bpLV
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ loc  = _TETrace[i].loc
        /\ loc' = _TETrace[j].loc
        /\ pc  = _TETrace[i].pc
        /\ pc' = _TETrace[j].pc
        /\ disk  = _TETrace[i].disk
        /\ disk' = _TETrace[j].disk
        /\ bpCT  = _TETrace[i].bpCT
        /\ bpCT' = _TETrace[j].bpCT
        /\ volRes  = _TETrace[i].volRes
        /\ volRes' = _TETrace[j].volRes
        /\ curVol  = _TETrace[i].curVol
        /\ curVol' = _TETrace[j].curVol
        /\ diskInit  = _TETrace[i].diskInit
        /\ diskInit' = _TETrace[j].diskInit
        /\ interference  = _TETrace[i].interference
        /\ interference' = _TETrace[j].interference

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
EXTENDS Sequences, TLCExt, MC, Toolbox, Naturals, TLC

expression == 
    [
        \* To hide variables of the `MC` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        bpLV |-> bpLV
        ,targetFired |-> targetFired
        ,loc |-> loc
        ,pc |-> pc
        ,disk |-> disk
        ,bpCT |-> bpCT
        ,volRes |-> volRes
        ,curVol |-> curVol
        ,diskInit |-> diskInit
        ,interference |-> interference
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_bpLVUnchanged |-> bpLV = bpLV'
        
        \* Format the `bpLV` variable as Json value.
        \* ,_bpLVJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(bpLV)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_bpLVModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].bpLV # _TETrace[s-1].bpLV
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
\*trace == IODeserialize("MC_TTrace_1794187161.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC

trace == 
    <<
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 2,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "analyze" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 3,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 2,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "rpLV" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 3,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 2,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "rpCT" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r405" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r406" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r409" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r415" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r416" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "upgrade" @@ <<"task", 1>> :> "idle" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 1,targetFired |-> FALSE,volRes |-> <<"pending", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "analyze" @@ <<"task", 1>> :> "queued" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "rpLV" @@ <<"task", 1>> :> "queued" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "rpCT" @@ <<"task", 1>> :> "queued" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r405" @@ <<"task", 1>> :> "queued" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r406" @@ <<"task", 1>> :> "queued" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r409" @@ <<"task", 1>> :> "queued" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r415" @@ <<"task", 1>> :> "queued" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r415" @@ <<"task", 1>> :> "uSetLV" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 1,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r415" @@ <<"task", 1>> :> "uSetCT" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 0]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 2,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r415" @@ <<"task", 1>> :> "uWpLV" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 1]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 2,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "r416" @@ <<"task", 1>> :> "uWpLV" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> FALSE,volRes |-> <<"upgrading", "pending">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 1]),
    ([loc |-> (<<"main", 0>> :> [plv |-> 1, pct |-> 1, wlv |-> 1] @@ <<"task", 1>> :> [plv |-> 1, pct |-> 2, wlv |-> 1] @@ <<"task", 2>> :> [plv |-> 1, pct |-> 2, wlv |-> 1]),bpCT |-> 2,disk |-> <<[ver |-> FALSE, lv |-> 1, ct |-> 1, prevTmp |-> TRUE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,pc |-> (<<"main", 0>> :> "join" @@ <<"task", 1>> :> "uWpLV" @@ <<"task", 2>> :> "idle"),bpLV |-> 1,curVol |-> 2,targetFired |-> TRUE,volRes |-> <<"upgrading", "failed">>,diskInit |-> <<[ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE], [ver |-> TRUE, lv |-> 1, ct |-> 1, prevTmp |-> FALSE, prev |-> FALSE]>>,interference |-> 1])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187161 ----
CONSTANTS
    DNLV = 1
    OLDLV = 2
    INITLV = 3
    OldCT = 1
    NsCT = 2
    StartOrder <- StartOrder2
    HsVols = { }
    PoolSize = 2
    InitDiskSet <- MCInitDiskSet
    StartDiskChoices <- WorkloadStartDisks
    HsDiskChoices <- NoHsDisks
    MaxInterference = 1
    MissedUpgradeVols = 0

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