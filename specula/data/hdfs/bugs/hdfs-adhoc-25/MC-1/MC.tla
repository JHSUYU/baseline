--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model checking wrapper for hdfs-adhoc-25 (BPSS:184-185 CTime check).    *)
(*                                                                         *)
(* Bounded (they introduce nondeterminism; operator / environment / fault):*)
(*   NameNode -upgrade and -rollback, DataNode restart (stop at any point  *)
(*   = crash or shutdown, then start with REGULAR or ROLLBACK), disk       *)
(*   replacement, reconfiguration that hot-adds volumes, reconfiguration   *)
(*   that detaches volumes.                                                *)
(* Not bounded (reactive code paths): handshakes, actor rejection, the     *)
(* startup loader, block-pool load steps, deferred upgrade callables,      *)
(* init completion, hot-swap pool threads and their join.                  *)
(*                                                                         *)
(* Every step has a named wrapper so TLC labels counterexample steps, and  *)
(* the stop-after-target rule is a CONSTRAINT, not a Next conjunct.        *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxNNUpgrade,   \* NameNode -upgrade restarts (all NameNodes together)
    MaxNNRollback,  \* NameNode -rollback restarts
    MaxDNRestart,   \* DataNode stop + start
    MaxFreshDisk,   \* disk replacements
    MaxHotSwap,     \* reconfigurations that start pool threads (hot adds)
    MaxDetach       \* volumes detached by reconfiguration

ASSUME /\ MaxNNUpgrade \in Nat /\ MaxNNRollback \in Nat /\ MaxDNRestart \in Nat
       /\ MaxFreshDisk \in Nat /\ MaxHotSwap \in Nat /\ MaxDetach \in Nat
       /\ InitCT + MaxNNUpgrade <= MaxCT

VARIABLE fc     \* fault counters

mc_vars == <<vars, fc>>

----------------------------------------------------------------------------
\* Bounded wrappers.

MCNNUpgrade(n) ==
    /\ fc.nnUp < MaxNNUpgrade
    /\ NNUpgrade(n)
    /\ fc' = [fc EXCEPT !.nnUp = @ + 1]

MCNNRollback(n) ==
    /\ fc.nnRb < MaxNNRollback
    /\ NNRollback(n)
    /\ fc' = [fc EXCEPT !.nnRb = @ + 1]

MCDiskReplace(l) ==
    /\ fc.fresh < MaxFreshDisk
    /\ DiskReplace(l)
    /\ fc' = [fc EXCEPT !.fresh = @ + 1]

\* A stop is only useful if a start may follow; the start pays the budget.
MCDNStop ==
    /\ fc.restart < MaxDNRestart
    /\ DNStop
    /\ UNCHANGED fc

MCDNStart(o) ==
    /\ DNStart(o)
    /\ fc' = [fc EXCEPT !.restart = @ + 1]

\* A reconfiguration counts as a hot swap if it starts pool threads, and
\* each detached volume counts against MaxDetach.
MCReconfigure(rm, add) ==
    /\ LET newConf == ReconfNewConf(rm, add)
           newLocs == SelectSeq(newConf, LAMBDA x : x \notin dsDirs)
           hs      == fc.hotswap + (IF newLocs # <<>> THEN 1 ELSE 0)
           det     == fc.detach + Cardinality(rm)
       IN /\ hs <= MaxHotSwap
          /\ det <= MaxDetach
          /\ Reconfigure(rm, add)
          /\ fc' = [fc EXCEPT !.hotswap = hs, !.detach = det]

----------------------------------------------------------------------------
\* Reactive steps (unbounded), named so counterexamples keep their labels.

MCHandshake(n)         == Handshake(n)         /\ UNCHANGED fc
MCActorRejected(n)     == ActorRejected(n)     /\ UNCHANGED fc
MCDNLevelLoad          == DNLevelLoad          /\ UNCHANGED fc
MCDNLevelJoin          == DNLevelJoin          /\ UNCHANGED fc
MCBpContains(t)        == BpContains(t)        /\ UNCHANGED fc
MCBpAnalyze(t)         == BpAnalyze(t)         /\ UNCHANGED fc
MCBpFormatWrite(t)     == BpFormatWrite(t)     /\ UNCHANGED fc
MCBpTransition(t)      == BpTransition(t)      /\ UNCHANGED fc
MCBpReadProps(t)       == BpReadProps(t)       /\ UNCHANGED fc
MCBpDecideRegular(t)   == BpDecideRegular(t)   /\ UNCHANGED fc
MCBpDecideUpgrade(t)   == BpDecideUpgrade(t)   /\ UNCHANGED fc
MCBpUpgradeSet(t)      == BpUpgradeSet(t)      /\ UNCHANGED fc
MCBpUpgradeWrite(t)    == BpUpgradeWrite(t)    /\ UNCHANGED fc
MCTargetCheck(t)       == TargetCheck(t)       /\ UNCHANGED fc
MCBpWriteVersion(t)    == BpWriteVersion(t)    /\ UNCHANGED fc
MCRunDeferredUpgrade(l)== RunDeferredUpgrade(l)/\ UNCHANGED fc
MCInitFinish           == InitFinish           /\ UNCHANGED fc
MCHsDnLevel(t)         == HsDnLevel(t)         /\ UNCHANGED fc
MCHotSwapFinish        == HotSwapFinish        /\ UNCHANGED fc

----------------------------------------------------------------------------

MCInit ==
    /\ Init
    /\ fc = [nnUp |-> 0, nnRb |-> 0, restart |-> 0, fresh |-> 0,
             hotswap |-> 0, detach |-> 0]

\* The test fixture (FixtureWriteVersion) is not part of the MC model.
MCNext ==
    \/ \E n \in NN : MCNNUpgrade(n)
    \/ \E n \in NN : MCNNRollback(n)
    \/ \E l \in Loc : MCDiskReplace(l)
    \/ MCDNStop
    \/ \E o \in Opts : MCDNStart(o)
    \/ \E n \in NN : MCHandshake(n)
    \/ \E n \in NN : MCActorRejected(n)
    \/ MCDNLevelLoad
    \/ MCDNLevelJoin
    \/ \E t \in Thr : MCBpContains(t)
    \/ \E t \in Thr : MCBpAnalyze(t)
    \/ \E t \in Thr : MCBpFormatWrite(t)
    \/ \E t \in Thr : MCBpTransition(t)
    \/ \E t \in Thr : MCBpReadProps(t)
    \/ \E t \in Thr : MCBpDecideRegular(t)
    \/ \E t \in Thr : MCBpDecideUpgrade(t)
    \/ \E t \in Thr : MCBpUpgradeSet(t)
    \/ \E t \in Thr : MCBpUpgradeWrite(t)
    \/ \E t \in Thr : MCTargetCheck(t)
    \/ \E t \in Thr : MCBpWriteVersion(t)
    \/ \E l \in Loc : MCRunDeferredUpgrade(l)
    \/ MCInitFinish
    \/ \E rm \in SUBSET DiskLoc, add \in SUBSET SwapLocs : MCReconfigure(rm, add)
    \/ \E t \in HsThr : MCHsDnLevel(t)
    \/ MCHotSwapFinish

MCSpec == MCInit /\ [][MCNext]_mc_vars

----------------------------------------------------------------------------
\* Stop exploring once the target fired (TLC still checks the invariants of
\* the first state that violates the constraint).
StopAfterTarget == ~targetFired

\* Sanity (tla-patterns Section 2): expected to be VIOLATED, which shows that
\* some explored state enables TargetCheck.
TargetReached == ~(\E t \in Thr : pc[t] = "check")

\* Counters stay within their bounds (structural).
CountersOK ==
    /\ fc.nnUp <= MaxNNUpgrade /\ fc.nnRb <= MaxNNRollback
    /\ fc.restart <= MaxDNRestart /\ fc.fresh <= MaxFreshDisk
    /\ fc.hotswap <= MaxHotSwap /\ fc.detach <= MaxDetach

=============================================================================
