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
        hSent = ({f1})
        /\
        owner = (f1)
        /\
        meUsed = (TRUE)
        /\
        counters = ([opens |-> 2, ops |-> 1, syncs |-> 0, abandons |-> 1])
        /\
        targetFired = (TRUE)
        /\
        revalReplies = ((f1 :> 1 @@ f2 :> 0))
        /\
        link = ((f1 :> <<>> @@ f2 :> <<>>))
        /\
        pendingReval = ((f1 :> 1 @@ f2 :> 0))
        /\
        opPending = (FALSE)
        /\
        prepQueue = (<<>>)
        /\
        pingPending = (FALSE)
        /\
        sessionAlive = (TRUE)
        /\
        client = ([att |-> 2, srv |-> L, st |-> "Conn"])
        /\
        inbox = ((L :> {} @@ f1 :> {} @@ f2 :> {}))
    )
----

_init ==
    /\ revalReplies = _TETrace[1].revalReplies
    /\ pendingReval = _TETrace[1].pendingReval
    /\ targetFired = _TETrace[1].targetFired
    /\ link = _TETrace[1].link
    /\ prepQueue = _TETrace[1].prepQueue
    /\ counters = _TETrace[1].counters
    /\ sessionAlive = _TETrace[1].sessionAlive
    /\ client = _TETrace[1].client
    /\ opPending = _TETrace[1].opPending
    /\ pingPending = _TETrace[1].pingPending
    /\ meUsed = _TETrace[1].meUsed
    /\ inbox = _TETrace[1].inbox
    /\ hSent = _TETrace[1].hSent
    /\ owner = _TETrace[1].owner
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ revalReplies  = _TETrace[i].revalReplies
        /\ revalReplies' = _TETrace[j].revalReplies
        /\ pendingReval  = _TETrace[i].pendingReval
        /\ pendingReval' = _TETrace[j].pendingReval
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ link  = _TETrace[i].link
        /\ link' = _TETrace[j].link
        /\ prepQueue  = _TETrace[i].prepQueue
        /\ prepQueue' = _TETrace[j].prepQueue
        /\ counters  = _TETrace[i].counters
        /\ counters' = _TETrace[j].counters
        /\ sessionAlive  = _TETrace[i].sessionAlive
        /\ sessionAlive' = _TETrace[j].sessionAlive
        /\ client  = _TETrace[i].client
        /\ client' = _TETrace[j].client
        /\ opPending  = _TETrace[i].opPending
        /\ opPending' = _TETrace[j].opPending
        /\ pingPending  = _TETrace[i].pingPending
        /\ pingPending' = _TETrace[j].pingPending
        /\ meUsed  = _TETrace[i].meUsed
        /\ meUsed' = _TETrace[j].meUsed
        /\ inbox  = _TETrace[i].inbox
        /\ inbox' = _TETrace[j].inbox
        /\ hSent  = _TETrace[i].hSent
        /\ hSent' = _TETrace[j].hSent
        /\ owner  = _TETrace[i].owner
        /\ owner' = _TETrace[j].owner

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
        revalReplies |-> revalReplies
        ,pendingReval |-> pendingReval
        ,targetFired |-> targetFired
        ,link |-> link
        ,prepQueue |-> prepQueue
        ,counters |-> counters
        ,sessionAlive |-> sessionAlive
        ,client |-> client
        ,opPending |-> opPending
        ,pingPending |-> pingPending
        ,meUsed |-> meUsed
        ,inbox |-> inbox
        ,hSent |-> hSent
        ,owner |-> owner
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_revalRepliesUnchanged |-> revalReplies = revalReplies'
        
        \* Format the `revalReplies` variable as Json value.
        \* ,_revalRepliesJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(revalReplies)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_revalRepliesModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].revalReplies # _TETrace[s-1].revalReplies
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
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 0, ops |-> 0, syncs |-> 0, abandons |-> 0],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 0 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> FALSE,client |-> [att |-> 0, srv |-> None, st |-> "Init"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 0, ops |-> 0, syncs |-> 0, abandons |-> 0],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 0 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<[owner |-> None, type |-> "createSession"]>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 0, srv |-> L, st |-> "Creating"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 0, ops |-> 0, syncs |-> 0, abandons |-> 0],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 0 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 0, srv |-> L, st |-> "Conn"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 0, ops |-> 0, syncs |-> 0, abandons |-> 0],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 0 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 0, srv |-> L, st |-> "Disc"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 1, ops |-> 0, syncs |-> 0, abandons |-> 0],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 0 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 1, srv |-> f1, st |-> "Sent"],inbox |-> (L :> {} @@ f1 :> {1} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 1, ops |-> 0, syncs |-> 0, abandons |-> 0],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<[kind |-> "REVALIDATE", type |-> "none"]>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 1 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 1, srv |-> f1, st |-> "Read"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 1, ops |-> 0, syncs |-> 0, abandons |-> 1],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<[kind |-> "REVALIDATE", type |-> "none"]>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 1 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 1, srv |-> f1, st |-> "Disc"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> None,meUsed |-> FALSE,counters |-> [opens |-> 2, ops |-> 0, syncs |-> 0, abandons |-> 1],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<[kind |-> "REVALIDATE", type |-> "none"]>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 1 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 2, srv |-> L, st |-> "Sent"],inbox |-> (L :> {2} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {},owner |-> Me,meUsed |-> TRUE,counters |-> [opens |-> 2, ops |-> 0, syncs |-> 0, abandons |-> 1],targetFired |-> FALSE,revalReplies |-> (f1 :> 0 @@ f2 :> 0),link |-> (f1 :> <<[kind |-> "REVALIDATE", type |-> "none"]>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 1 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 2, srv |-> L, st |-> "Conn"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {f1},owner |-> f1,meUsed |-> TRUE,counters |-> [opens |-> 2, ops |-> 0, syncs |-> 0, abandons |-> 1],targetFired |-> FALSE,revalReplies |-> (f1 :> 1 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 1 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 2, srv |-> L, st |-> "Conn"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {f1},owner |-> f1,meUsed |-> TRUE,counters |-> [opens |-> 2, ops |-> 1, syncs |-> 0, abandons |-> 1],targetFired |-> FALSE,revalReplies |-> (f1 :> 1 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 1 @@ f2 :> 0),opPending |-> TRUE,prepQueue |-> <<[owner |-> Me, type |-> "write"]>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 2, srv |-> L, st |-> "Conn"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})]),
    ([hSent |-> {f1},owner |-> f1,meUsed |-> TRUE,counters |-> [opens |-> 2, ops |-> 1, syncs |-> 0, abandons |-> 1],targetFired |-> TRUE,revalReplies |-> (f1 :> 1 @@ f2 :> 0),link |-> (f1 :> <<>> @@ f2 :> <<>>),pendingReval |-> (f1 :> 1 @@ f2 :> 0),opPending |-> FALSE,prepQueue |-> <<>>,pingPending |-> FALSE,sessionAlive |-> TRUE,client |-> [att |-> 2, srv |-> L, st |-> "Conn"],inbox |-> (L :> {} @@ f1 :> {} @@ f2 :> {})])
    >>
----


=============================================================================

---- MODULE MC_TEConstants ----
EXTENDS MC

CONSTANTS L, f1, f2

=============================================================================

---- CONFIG MC_TTrace_1794187162 ----
CONSTANTS
    Leader = L
    Followers = { f1 , f2 }
    None = None
    Me = Me
    MaxOpens = 3
    MaxOps = 3
    MaxSyncs = 0
    MaxAbandon = 1
    None = None
    Me = Me
    L = L
    f1 = f1
    f2 = f2

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