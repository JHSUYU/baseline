--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base (hdfs-adhoc-29, target BRW:604).       *)
(*                                                                         *)
(* - Fault-injection actions are counter-bounded (record fc). Reactive    *)
(*   steps (handshakes, heartbeats that deliver what the NN queued,       *)
(*   command processing, actor exit/cleanUp, recovery-task steps, NN      *)
(*   recovery issue bounded by MaxAttempts in base) are not.              *)
(* - Every MC disjunct is a named wrapper and MCNext is a plain           *)
(*   disjunction, so counterexample steps carry action names; the stop    *)
(*   rule after the target fires is the CONSTRAINT StopAfterTarget (TLC   *)
(*   still checks invariants on the first state where targetFired holds). *)
(* - Topologies (override NnOf / PoolOf from the cfg):                     *)
(*     NnOfOne/PoolOfOne  one NN n1, pool p1 (MC.cfg, S1, S2, S3 rename)   *)
(*     NnOfFed/PoolOfFed  ns1 -> n1 (p1), ns2 -> n2 (p2) (S3 federation)   *)
(* - No VIEW: merging states that differ only in fault budgets would drop *)
(*   successors that need the remaining budget.                           *)
(***************************************************************************)
EXTENDS base, TLC

CONSTANTS
    MaxDnStop,       \* Scenario 1: DataNode stops (volume failure DN:2743 / shutdown DN:2545)
    MaxNnReject,     \* Scenario 2: operator rejection (include list DM:1871-1874 / NN -upgrade NNRS:1777-1786)
    MaxCmdCrash,     \* Scenario 2: command thread dies on an unchecked exception (BPSA:1412-1422)
    MaxNnRestart,    \* Scenario 2 environment variant: NameNode restart (-> DNA_REGISTER, DM:1876-1878)
    MaxDnsFail,      \* Scenario 2 environment variant: NN reverse DNS fails (DM:1195-1201)
    MaxRefresh,      \* Scenario 3: refreshNamenodes (DN:3810-3815)
    MaxLostCommits   \* workload fixture: first commitBlockSynchronization dropped
                     \* (TestBlockRecovery2.java:314-319); not a Scenario fault

ASSUME \A c \in {MaxDnStop, MaxNnReject, MaxCmdCrash, MaxNnRestart, MaxDnsFail, MaxRefresh,
                 MaxLostCommits} : c \in Nat

\* Named model values used by the topologies (assign each as a model value in the cfg).
CONSTANTS ns1, ns2, n1, n2, p1, p2

VARIABLE fc            \* fault counters

mcVars == <<vars, fc>>

FcZero == [dnStop |-> 0, reject |-> 0, cmdCrash |-> 0, nnRestart |-> 0, dnsFail |-> 0,
           refresh |-> 0, lost |-> 0]

\* --- Topologies -------------------------------------------------------------
NnOfOne   == [ns \in NS |-> n1]                               \* ns1 (and ns2 = rename of ns1) -> n1
PoolOfOne == [n \in NN |-> p1]
NnOfFed   == [ns \in NS |-> IF ns = ns1 THEN n1 ELSE n2]      \* federated DN: two namespaces
PoolOfFed == [n \in NN |-> IF n = n1 THEN p1 ELSE p2]

MCInit == Init /\ fc = FcZero

-----------------------------------------------------------------------------
(* Fault-injection wrappers (counted).                                                        *)

MCDnStop(d, c) ==
    /\ fc.dnStop < MaxDnStop
    /\ DnStop(d, c)
    /\ fc' = [fc EXCEPT !.dnStop = @ + 1]

MCNnReject(d) ==
    /\ fc.reject < MaxNnReject
    /\ NnReject(d)
    /\ fc' = [fc EXCEPT !.reject = @ + 1]

MCCmdThreadCrash(d, ns) ==
    /\ fc.cmdCrash < MaxCmdCrash
    /\ CmdThreadCrash(d, ns)
    /\ fc' = [fc EXCEPT !.cmdCrash = @ + 1]

MCNnRestart ==
    /\ fc.nnRestart < MaxNnRestart
    /\ NnRestart
    /\ fc' = [fc EXCEPT !.nnRestart = @ + 1]

MCDnsFail(d) ==
    /\ fc.dnsFail < MaxDnsFail
    /\ DnsFail(d)
    /\ fc' = [fc EXCEPT !.dnsFail = @ + 1]

MCRefreshStart(d) ==
    /\ fc.refresh < MaxRefresh
    /\ RefreshStart(d)
    /\ fc' = [fc EXCEPT !.refresh = @ + 1]

\* Only the "lost" outcome (the call returns without reaching the NN) is a counted fault;
\* the other outcomes follow from the state (CommitOutcomes in base).
MCTaskCommit(t, o) ==
    /\ TaskCommit(t, o)
    /\ IF o = "lost"
       THEN /\ fc.lost < MaxLostCommits
            /\ fc' = [fc EXCEPT !.lost = @ + 1]
       ELSE UNCHANGED fc

-----------------------------------------------------------------------------
(* Reactive wrappers (unbounded).                                                             *)

MCActorConnect(d, ns)      == ActorConnect(d, ns)      /\ UNCHANGED fc
MCActorInitStorage(d, ns)  == ActorInitStorage(d, ns)  /\ UNCHANGED fc
MCActorRegister(d, ns)     == ActorRegister(d, ns)     /\ UNCHANGED fc
MCActorHeartbeat(d, ns)    == ActorHeartbeat(d, ns)    /\ UNCHANGED fc
MCCmdRegister(d, ns)       == CmdRegister(d, ns)       /\ UNCHANGED fc
MCCmdRecover(d, ns)        == CmdRecover(d, ns)        /\ UNCHANGED fc
MCActorStop(d, ns)         == ActorStop(d, ns)         /\ UNCHANGED fc
MCActorLoopExit(d, ns)     == ActorLoopExit(d, ns)     /\ UNCHANGED fc
MCActorCleanUp(d, ns)      == ActorCleanUp(d, ns)      /\ UNCHANGED fc
MCDnShutdownInterrupt(d)   == DnShutdownInterrupt(d)   /\ UNCHANGED fc
MCNnIssueRecovery(d)       == NnIssueRecovery(d)       /\ UNCHANGED fc
MCTaskGetId(t)             == TaskGetId(t)             /\ UNCHANGED fc
MCTaskInitRR(t, o)         == TaskInitRR(t, o)         /\ UNCHANGED fc
MCTaskLoopEnd(t)           == TaskLoopEnd(t)           /\ UNCHANGED fc
MCTargetCheck(t)           == TargetCheck(t)           /\ UNCHANGED fc
MCTaskGetActiveNN(t)       == TaskGetActiveNN(t)       /\ UNCHANGED fc

-----------------------------------------------------------------------------

MCNext ==
    \/ \E d \in DN, ns \in NS :
          \/ MCActorConnect(d, ns)
          \/ MCActorInitStorage(d, ns)
          \/ MCActorRegister(d, ns)
          \/ MCActorHeartbeat(d, ns)
          \/ MCCmdRegister(d, ns)
          \/ MCCmdRecover(d, ns)
          \/ MCCmdThreadCrash(d, ns)
          \/ MCActorStop(d, ns)
          \/ MCActorLoopExit(d, ns)
          \/ MCActorCleanUp(d, ns)
    \/ \E d \in DN :
          \/ \E c \in StopCause : MCDnStop(d, c)
          \/ MCDnShutdownInterrupt(d)
          \/ MCRefreshStart(d)
          \/ MCNnIssueRecovery(d)
          \/ MCNnReject(d)
          \/ MCDnsFail(d)
    \/ MCNnRestart
    \/ \E t \in Task :
          \/ MCTaskGetId(t)
          \/ \E o \in RROutcome : MCTaskInitRR(t, o)
          \/ MCTaskLoopEnd(t)
          \/ MCTargetCheck(t)
          \/ MCTaskGetActiveNN(t)
          \/ \E o \in CommitOutcome : MCTaskCommit(t, o)

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(* Symmetry, sanity probe, counter typing.                                                    *)

\* DataNodes are interchangeable: Init picks blockLocs among all permutations and every action
\* is generic in the DataNode.
Symmetry == Permutations(DN)

\* Sanity probe (adhoc tla-patterns §2): violated iff a reachable state has TargetCheck enabled.
TargetReached == ~(\E t \in Task : task[t].st = "target")

FcOK == fc \in [{"dnStop", "reject", "cmdCrash", "nnRestart", "dnsFail", "refresh", "lost"}
                -> Nat]

=============================================================================
