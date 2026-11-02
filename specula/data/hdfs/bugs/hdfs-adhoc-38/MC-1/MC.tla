--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model checking wrapper for hdfs-adhoc-38 (brief Sections 1, 2, 3.1).    *)
(*                                                                         *)
(* The workload actions are reactive: never bounded. The environment       *)
(* client's RPCs introduce the non-determinism: each kind has a budget,    *)
(* checked and incremented on the same transition.                         *)
(*                                                                         *)
(* Fence (brief Section 1, "Outside the fault model"): environment actions *)
(* run only after the workload's create. Otherwise BFS returns the         *)
(* designed create-time route: an ancestor already tagged LAZY_PERSIST     *)
(* makes the create copy the policy, and the file really is lazy-persist.  *)
(*                                                                         *)
(* The stop rule is the CONSTRAINT StopAfterTarget, not a ~targetFired     *)
(* conjunct in MCNext: TLC still checks invariants on the first firing     *)
(* state, and the counterexample keeps its action names, because MCNext    *)
(* stays a plain disjunction of named wrappers.                            *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxDirPolicyOps,      \* SetDirStoragePolicy + UnsetDirStoragePolicy (Scenarios 1, 2)
    MaxFilePolicyOps,     \* SetFileStoragePolicy (Scenario 1)
    MaxRenames,           \* RenameOld + Rename2 (Scenario 2)
    MaxMkdirs,            \* Mkdirs (Scenario 2)
    TagOnlyNonAncestors   \* Scenario 2 isolation: see TagAllowed

ASSUME MaxDirPolicyOps \in Nat
ASSUME MaxFilePolicyOps \in Nat
ASSUME MaxRenames \in Nat
ASSUME MaxMkdirs \in Nat
ASSUME TagOnlyNonAncestors \in BOOLEAN

VARIABLE fc     \* Spent budgets of the environment client.

mcVars == <<vars, fc>>

MCInit ==
    /\ Init
    /\ fc = [dirPolicyOps |-> 0, filePolicyOps |-> 0, renames |-> 0, mkdirs |-> 0]

----------------------------------------------------------------------------
\* Fence and isolation. Neither is code: both are fault-model decisions from the
\* brief, so they live here and not in base.tla.

\* After the workload's create, while a guard evaluation is still ahead. The
\* steps after the last append cannot influence any guard evaluation.
EnvWindow == pc \in {"close", "append1", "append2"}

\* Scenario 2 isolation (brief Section 2): policy operations only on a directory
\* that is not, at that moment, an ancestor of F. Otherwise BFS returns the
\* Scenario 1 route. With this on, every firing needs a rename after the tag.
TagAllowed(d) == TagOnlyNonAncestors => d \notin AncestorsOf(F)

----------------------------------------------------------------------------
\* Workload: reactive, unbounded.

MCStartFile(c)          == StartFile(c)          /\ UNCHANGED fc
MCCompleteFile(c)       == CompleteFile(c)       /\ UNCHANGED fc
MCTargetCheck(c)        == TargetCheck(c)        /\ UNCHANGED fc
MCAppendPathRejected(c) == AppendPathRejected(c) /\ UNCHANGED fc
MCTerminating           == Terminating           /\ UNCHANGED fc

----------------------------------------------------------------------------
\* Environment client: fenced and budgeted.

MCSetDirStoragePolicy(d, p) ==
    /\ EnvWindow
    /\ fc.dirPolicyOps < MaxDirPolicyOps
    /\ TagAllowed(d)
    /\ SetDirStoragePolicy(d, p)
    /\ fc' = [fc EXCEPT !.dirPolicyOps = @ + 1]

MCUnsetDirStoragePolicy(d) ==
    /\ EnvWindow
    /\ fc.dirPolicyOps < MaxDirPolicyOps
    /\ TagAllowed(d)
    /\ UnsetDirStoragePolicy(d)
    /\ fc' = [fc EXCEPT !.dirPolicyOps = @ + 1]

MCSetFileStoragePolicy(p) ==
    /\ EnvWindow
    /\ fc.filePolicyOps < MaxFilePolicyOps
    /\ SetFileStoragePolicy(p)
    /\ fc' = [fc EXCEPT !.filePolicyOps = @ + 1]

MCMkdirs(dp, n) ==
    /\ EnvWindow
    /\ fc.mkdirs < MaxMkdirs
    /\ Mkdirs(dp, n)
    /\ fc' = [fc EXCEPT !.mkdirs = @ + 1]

MCRenameOld(x, dp, n) ==
    /\ EnvWindow
    /\ fc.renames < MaxRenames
    /\ RenameOld(x, dp, n)
    /\ fc' = [fc EXCEPT !.renames = @ + 1]

MCRename2(x, dp, n, o) ==
    /\ EnvWindow
    /\ fc.renames < MaxRenames
    /\ Rename2(x, dp, n, o)
    /\ fc' = [fc EXCEPT !.renames = @ + 1]

----------------------------------------------------------------------------
MCNext ==
    \/ \E c \in Client : MCStartFile(c)
    \/ \E c \in Client : MCCompleteFile(c)
    \/ \E c \in Client : MCTargetCheck(c)
    \/ \E c \in Client : MCAppendPathRejected(c)
    \/ \E d \in Dir, p \in SettablePolicy : MCSetDirStoragePolicy(d, p)
    \/ \E d \in Dir : MCUnsetDirStoragePolicy(d)
    \/ \E p \in PolicyId : MCSetFileStoragePolicy(p)
    \/ \E dp \in Dir, n \in Name : MCMkdirs(dp, n)
    \/ \E x \in INode, dp \in Dir, n \in Name : MCRenameOld(x, dp, n)
    \/ \E x \in INode, dp \in Dir, n \in Name, o \in BOOLEAN : MCRename2(x, dp, n, o)
    \/ MCTerminating

MCSpec == MCInit /\ [][MCNext]_mcVars

----------------------------------------------------------------------------
\* Stop exploring once the target fired (adhoc tla-patterns Section 1).
StopAfterTarget == ~targetFired

\* Budgets stay within their bounds. Structural, MC only.
CountersOK ==
    /\ fc.dirPolicyOps \in 0..MaxDirPolicyOps
    /\ fc.filePolicyOps \in 0..MaxFilePolicyOps
    /\ fc.renames \in 0..MaxRenames
    /\ fc.mkdirs \in 0..MaxMkdirs

\* Temporary sanity invariant (adhoc tla-patterns Section 2). TLC MUST report it
\* violated: some reachable state enables TargetCheck. Used only by
\* MC_sanity_reach.cfg.
TargetReached == ~(\E c \in Client : TargetCheckEnabled(c))

=============================================================================
