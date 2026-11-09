---- MODULE MC_TTrace_1794187171 ----
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
        dirPolicy = ([Root |-> 15, D |-> 0, L |-> 0])
        /\
        parent = ([F |-> "D", Root |-> "NoINode", D |-> "Root", L |-> "NoINode"])
        /\
        pc = ("done")
        /\
        fileOwn = (0)
        /\
        ucHolder = ("NoClient")
        /\
        createdLazy = (FALSE)
        /\
        targetFired = (TRUE)
        /\
        name = ([F |-> "foo", Root |-> "", D |-> "testAppendTwice", L |-> ""])
        /\
        fc = ([dirPolicyOps |-> 1, filePolicyOps |-> 0, renames |-> 0, mkdirs |-> 0])
        /\
        outcome = ([c1 |-> "UOE", c2 |-> "none"])
    )
----

_init ==
    /\ targetFired = _TETrace[1].targetFired
    /\ outcome = _TETrace[1].outcome
    /\ pc = _TETrace[1].pc
    /\ parent = _TETrace[1].parent
    /\ dirPolicy = _TETrace[1].dirPolicy
    /\ fc = _TETrace[1].fc
    /\ name = _TETrace[1].name
    /\ ucHolder = _TETrace[1].ucHolder
    /\ createdLazy = _TETrace[1].createdLazy
    /\ fileOwn = _TETrace[1].fileOwn
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ targetFired  = _TETrace[i].targetFired
        /\ targetFired' = _TETrace[j].targetFired
        /\ outcome  = _TETrace[i].outcome
        /\ outcome' = _TETrace[j].outcome
        /\ pc  = _TETrace[i].pc
        /\ pc' = _TETrace[j].pc
        /\ parent  = _TETrace[i].parent
        /\ parent' = _TETrace[j].parent
        /\ dirPolicy  = _TETrace[i].dirPolicy
        /\ dirPolicy' = _TETrace[j].dirPolicy
        /\ fc  = _TETrace[i].fc
        /\ fc' = _TETrace[j].fc
        /\ name  = _TETrace[i].name
        /\ name' = _TETrace[j].name
        /\ ucHolder  = _TETrace[i].ucHolder
        /\ ucHolder' = _TETrace[j].ucHolder
        /\ createdLazy  = _TETrace[i].createdLazy
        /\ createdLazy' = _TETrace[j].createdLazy
        /\ fileOwn  = _TETrace[i].fileOwn
        /\ fileOwn' = _TETrace[j].fileOwn

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MC_TTrace_1794187171.json", _TETrace)

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
        targetFired |-> targetFired
        ,outcome |-> outcome
        ,pc |-> pc
        ,parent |-> parent
        ,dirPolicy |-> dirPolicy
        ,fc |-> fc
        ,name |-> name
        ,ucHolder |-> ucHolder
        ,createdLazy |-> createdLazy
        ,fileOwn |-> fileOwn
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_targetFiredUnchanged |-> targetFired = targetFired'
        
        \* Format the `targetFired` variable as Json value.
        \* ,_targetFiredJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(targetFired)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_targetFiredModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].targetFired # _TETrace[s-1].targetFired
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
\*trace == IODeserialize("MC_TTrace_1794187171.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MC_TETrace ----
EXTENDS MC, TLC

trace == 
    <<
    ([dirPolicy |-> [Root |-> 0, D |-> 0, L |-> 0],parent |-> [F |-> "NoINode", Root |-> "NoINode", D |-> "NoINode", L |-> "NoINode"],pc |-> "create",fileOwn |-> 0,ucHolder |-> "NoClient",createdLazy |-> FALSE,targetFired |-> FALSE,name |-> [F |-> "", Root |-> "", D |-> "", L |-> ""],fc |-> [dirPolicyOps |-> 0, filePolicyOps |-> 0, renames |-> 0, mkdirs |-> 0],outcome |-> [c1 |-> "none", c2 |-> "none"]]),
    ([dirPolicy |-> [Root |-> 0, D |-> 0, L |-> 0],parent |-> [F |-> "D", Root |-> "NoINode", D |-> "Root", L |-> "NoINode"],pc |-> "close",fileOwn |-> 0,ucHolder |-> "c1",createdLazy |-> FALSE,targetFired |-> FALSE,name |-> [F |-> "foo", Root |-> "", D |-> "testAppendTwice", L |-> ""],fc |-> [dirPolicyOps |-> 0, filePolicyOps |-> 0, renames |-> 0, mkdirs |-> 0],outcome |-> [c1 |-> "none", c2 |-> "none"]]),
    ([dirPolicy |-> [Root |-> 0, D |-> 0, L |-> 0],parent |-> [F |-> "D", Root |-> "NoINode", D |-> "Root", L |-> "NoINode"],pc |-> "append1",fileOwn |-> 0,ucHolder |-> "NoClient",createdLazy |-> FALSE,targetFired |-> FALSE,name |-> [F |-> "foo", Root |-> "", D |-> "testAppendTwice", L |-> ""],fc |-> [dirPolicyOps |-> 0, filePolicyOps |-> 0, renames |-> 0, mkdirs |-> 0],outcome |-> [c1 |-> "none", c2 |-> "none"]]),
    ([dirPolicy |-> [Root |-> 15, D |-> 0, L |-> 0],parent |-> [F |-> "D", Root |-> "NoINode", D |-> "Root", L |-> "NoINode"],pc |-> "append1",fileOwn |-> 0,ucHolder |-> "NoClient",createdLazy |-> FALSE,targetFired |-> FALSE,name |-> [F |-> "foo", Root |-> "", D |-> "testAppendTwice", L |-> ""],fc |-> [dirPolicyOps |-> 1, filePolicyOps |-> 0, renames |-> 0, mkdirs |-> 0],outcome |-> [c1 |-> "none", c2 |-> "none"]]),
    ([dirPolicy |-> [Root |-> 15, D |-> 0, L |-> 0],parent |-> [F |-> "D", Root |-> "NoINode", D |-> "Root", L |-> "NoINode"],pc |-> "done",fileOwn |-> 0,ucHolder |-> "NoClient",createdLazy |-> FALSE,targetFired |-> TRUE,name |-> [F |-> "foo", Root |-> "", D |-> "testAppendTwice", L |-> ""],fc |-> [dirPolicyOps |-> 1, filePolicyOps |-> 0, renames |-> 0, mkdirs |-> 0],outcome |-> [c1 |-> "UOE", c2 |-> "none"]])
    >>
----


=============================================================================

---- CONFIG MC_TTrace_1794187171 ----
CONSTANTS
    CreateLazyFlag = FALSE
    CreatePolicyId = 0
    DefaultPolicy = 7
    MaxDirPolicyOps = 1
    MaxFilePolicyOps = 1
    MaxRenames = 0
    MaxMkdirs = 0
    TagOnlyNonAncestors = FALSE

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
\* Generated on Mon Nov 09 01:19:32 UTC 2026