---- MODULE MC_TTrace_1794187180 ----
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
        zxid = (6)
        /\
        creply = ("NONODE")
        /\
        targetFired = (TRUE)
        /\
        tree = (("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]))
        /\
        faults = ([early |-> 1])
        /\
        rtQ = (<<>>)
        /\
        posted = ({"/adhoc-workload-b3"})
        /\
        cwait = (TRUE)
        /\
        pview = (("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]))
        /\
        cpc = ("c6")
        /\
        mgr = ("scanned")
        /\
        cand = ({"/adhoc-workload-b3"})
        /\
        pipe = (<<>>)
        /\
        prepQ = (<<>>)
    )
----

_init ==
    /\ posted = _TETrace[1].posted
    /\ cand = _TETrace[1].cand
    /\ mgr = _TETrace[1].mgr
    /\ targetFired = _TETrace[1].targetFired
    /\ cwait = _TETrace[1].cwait
    /\ tree = _TETrace[1].tree
    /\ faults = _TETrace[1].faults
    /\ zxid = _TETrace[1].zxid
    /\ pipe = _TETrace[1].pipe
    /\ prepQ = _TETrace[1].prepQ
    /\ rtQ = _TETrace[1].rtQ
    /\ cpc = _TETrace[1].cpc
    /\ creply = _TETrace[1].creply
    /\ pview = _TETrace[1].pview
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ posted  = _TETrace[i].posted
        /\ posted' = _TETrace[j].posted
        /\ cand  = _TETrace[i].cand
        /\ cand' = _TETrace[j].cand
        /\ mgr  = _TETrace[i].mgr
        /\ mgr' = _TETrace[j].mgr
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ cwait  = _TETrace[i].cwait
        /\ cwait' = _TETrace[j].cwait
        /\ tree  = _TETrace[i].tree
        /\ tree' = _TETrace[j].tree
        /\ faults  = _TETrace[i].faults
        /\ faults' = _TETrace[j].faults
        /\ zxid  = _TETrace[i].zxid
        /\ zxid' = _TETrace[j].zxid
        /\ pipe  = _TETrace[i].pipe
        /\ pipe' = _TETrace[j].pipe
        /\ prepQ  = _TETrace[i].prepQ
        /\ prepQ' = _TETrace[j].prepQ
        /\ rtQ  = _TETrace[i].rtQ
        /\ rtQ' = _TETrace[j].rtQ
        /\ cpc  = _TETrace[i].cpc
        /\ cpc' = _TETrace[j].cpc
        /\ creply  = _TETrace[i].creply
        /\ creply' = _TETrace[j].creply
        /\ pview  = _TETrace[i].pview
        /\ pview' = _TETrace[j].pview

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187180.json", _TETrace)

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
        posted |-> posted
        ,cand |-> cand
        ,mgr |-> mgr
        ,targetFired |-> targetFired
        ,cwait |-> cwait
        ,tree |-> tree
        ,faults |-> faults
        ,zxid |-> zxid
        ,pipe |-> pipe
        ,prepQ |-> prepQ
        ,rtQ |-> rtQ
        ,cpc |-> cpc
        ,creply |-> creply
        ,pview |-> pview
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_postedUnchanged |-> posted = posted'
        
        \* Format the `posted` variable as Json value.
        \* ,_postedJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(posted)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_postedModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].posted # _TETrace[s-1].posted
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
\*trace == IODeserialize("MC_TTrace_1794187180.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC

trace == 
    <<
    ([zxid |-> 0,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> FALSE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c1",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 0,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<[op |-> "createContainer", path |-> "/adhoc-workload-b3", src |-> "client"]>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c1",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 0,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c1",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<[op |-> "createContainer", path |-> "/adhoc-workload-b3", src |-> "client"]>>]),
    ([zxid |-> 1,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c1",mgr |-> "off",cand |-> {},pipe |-> <<[req |-> [op |-> "createContainer", path |-> "/adhoc-workload-b3", src |-> "client"], txn |-> [owner |-> "owner=Long.MIN_VALUE", path |-> "/adhoc-workload-b3", kind |-> "create", pcv |-> 0, zxid |-> 1, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<>>]),
    ([zxid |-> 1,creply |-> "OK",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c1",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 1,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> FALSE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c2",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 1,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<[op |-> "create", path |-> "/adhoc-workload-b3/child", src |-> "client"]>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c2",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 1,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c2",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<[op |-> "create", path |-> "/adhoc-workload-b3/child", src |-> "client"]>>]),
    ([zxid |-> 2,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 0, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),cpc |-> "c2",mgr |-> "off",cand |-> {},pipe |-> <<[req |-> [op |-> "create", path |-> "/adhoc-workload-b3/child", src |-> "client"], txn |-> [owner |-> "owner=0", path |-> "/adhoc-workload-b3/child", kind |-> "create", pcv |-> 1, zxid |-> 2, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<>>]),
    ([zxid |-> 2,creply |-> "OK",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),cpc |-> "c2",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 2,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> FALSE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),cpc |-> "c3",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 2,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),faults |-> [early |-> 0],rtQ |-> <<[op |-> "delete", path |-> "/adhoc-workload-b3/child", src |-> "client"]>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),cpc |-> "c3",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 2,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),cpc |-> "c3",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<[op |-> "delete", path |-> "/adhoc-workload-b3/child", src |-> "client"]>>]),
    ([zxid |-> 3,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 1, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 2]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c3",mgr |-> "off",cand |-> {},pipe |-> <<[req |-> [op |-> "delete", path |-> "/adhoc-workload-b3/child", src |-> "client"], txn |-> [owner |-> "owner=0", path |-> "/adhoc-workload-b3/child", kind |-> "delete", pcv |-> 0, zxid |-> 3, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<>>]),
    ([zxid |-> 3,creply |-> "OK",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c3",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 3,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> FALSE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "start",mgr |-> "off",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 3,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> FALSE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c4",mgr |-> "armed",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 3,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<[op |-> "delete", path |-> "/adhoc-workload-b3", src |-> "client"]>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c4",mgr |-> "armed",cand |-> {},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 3,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<[op |-> "delete", path |-> "/adhoc-workload-b3", src |-> "client"]>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c4",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 3,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c4",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<[op |-> "delete", path |-> "/adhoc-workload-b3", src |-> "client"]>>]),
    ([zxid |-> 4,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=Long.MIN_VALUE", cv |-> 1, nch |-> 0, cz |-> 1] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c4",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<[req |-> [op |-> "delete", path |-> "/adhoc-workload-b3", src |-> "client"], txn |-> [owner |-> "owner=0", path |-> "/adhoc-workload-b3", kind |-> "delete", pcv |-> 0, zxid |-> 4, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<>>]),
    ([zxid |-> 4,creply |-> "OK",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c4",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 4,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> FALSE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c5",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 4,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<[op |-> "create", path |-> "/adhoc-workload-b3", src |-> "client"]>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c5",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 4,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c5",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<[op |-> "create", path |-> "/adhoc-workload-b3", src |-> "client"]>>]),
    ([zxid |-> 5,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c5",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<[req |-> [op |-> "create", path |-> "/adhoc-workload-b3", src |-> "client"], txn |-> [owner |-> "owner=0", path |-> "/adhoc-workload-b3", kind |-> "create", pcv |-> 0, zxid |-> 5, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<>>]),
    ([zxid |-> 5,creply |-> "OK",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 0],rtQ |-> <<>>,posted |-> {},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c5",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<>>]),
    ([zxid |-> 5,creply |-> "OK",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<>>,posted |-> {"/adhoc-workload-b3"},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c5",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<[op |-> "deleteContainer", path |-> "/adhoc-workload-b3", src |-> "cm"]>>]),
    ([zxid |-> 5,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<>>,posted |-> {"/adhoc-workload-b3"},cwait |-> FALSE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c6",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<[op |-> "deleteContainer", path |-> "/adhoc-workload-b3", src |-> "cm"]>>]),
    ([zxid |-> 5,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<[op |-> "getData", path |-> "/adhoc-workload-b3", src |-> "client"]>>,posted |-> {"/adhoc-workload-b3"},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c6",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<[op |-> "deleteContainer", path |-> "/adhoc-workload-b3", src |-> "cm"]>>]),
    ([zxid |-> 5,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<>>,posted |-> {"/adhoc-workload-b3"},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c6",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<[op |-> "deleteContainer", path |-> "/adhoc-workload-b3", src |-> "cm"], [op |-> "getData", path |-> "/adhoc-workload-b3", src |-> "client"]>>]),
    ([zxid |-> 6,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<>>,posted |-> {"/adhoc-workload-b3"},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c6",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<[req |-> [op |-> "deleteContainer", path |-> "/adhoc-workload-b3", src |-> "cm"], txn |-> [owner |-> "owner=0", path |-> "/adhoc-workload-b3", kind |-> "delete", pcv |-> 0, zxid |-> 6, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<[op |-> "getData", path |-> "/adhoc-workload-b3", src |-> "client"]>>]),
    ([zxid |-> 6,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> TRUE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 5] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<>>,posted |-> {"/adhoc-workload-b3"},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c6",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<[req |-> [op |-> "deleteContainer", path |-> "/adhoc-workload-b3", src |-> "cm"], txn |-> [owner |-> "owner=0", path |-> "/adhoc-workload-b3", kind |-> "delete", pcv |-> 0, zxid |-> 6, code |-> "OK"], err |-> "OK"], [req |-> [op |-> "getData", path |-> "/adhoc-workload-b3", src |-> "client"], txn |-> [owner |-> "owner=0", path |-> "/", kind |-> "none", pcv |-> 0, zxid |-> 0, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<>>]),
    ([zxid |-> 6,creply |-> "none",targetFired |-> FALSE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<>>,posted |-> {"/adhoc-workload-b3"},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c6",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<[req |-> [op |-> "getData", path |-> "/adhoc-workload-b3", src |-> "client"], txn |-> [owner |-> "owner=0", path |-> "/", kind |-> "none", pcv |-> 0, zxid |-> 0, code |-> "OK"], err |-> "OK"]>>,prepQ |-> <<>>]),
    ([zxid |-> 6,creply |-> "NONODE",targetFired |-> TRUE,tree |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),faults |-> [early |-> 1],rtQ |-> <<>>,posted |-> {"/adhoc-workload-b3"},cwait |-> TRUE,pview |-> ("/adhoc-workload-b3" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0] @@ "/adhoc-workload-b3/child" :> [ex |-> FALSE, owner |-> "owner=0", cv |-> 0, nch |-> 0, cz |-> 0]),cpc |-> "c6",mgr |-> "scanned",cand |-> {"/adhoc-workload-b3"},pipe |-> <<>>,prepQ |-> <<>>])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187180 ----
CONSTANTS
    P = "/adhoc-workload-b3"
    C = "/adhoc-workload-b3/child"
    Root = "/"
    MaxEarlyPost = 1

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
\* Generated on Mon Nov 09 01:19:41 UTC 2026