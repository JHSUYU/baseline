---------------------------------- MODULE MC ----------------------------------
(***************************************************************************)
(* Model-checking wrapper for zk-adhoc-b3.                                 *)
(*                                                                         *)
(* The workload is finite (seven client calls, one ContainerManager scan,  *)
(* at most one candidate), so no reactive action needs a bound.  The only  *)
(* source of extra non-determinism is the timing of the manager's post:    *)
(*   - on time: after the client has received c6's reply, as in the        *)
(*     workload (POST_DELAY_MS = 3000 ms, TestAdhocWorkloadB3.java:49,102);*)
(*   - early:  before that, i.e. a scan-to-post delay shorter than the     *)
(*     client's replace-and-read. Bounded by MaxEarlyPost (Scenario 1).    *)
(*                                                                         *)
(* No symmetry (P, C and the root play different roles) and no state      *)
(* constraint (every queue holds at most one client and one CM request).  *)
(***************************************************************************)
EXTENDS base, TLC

CONSTANT MaxEarlyPost   \* posts allowed before the client has read P back

ASSUME MaxEarlyPost \in Nat

VARIABLE faults         \* [early |-> number of early posts so far]

faultVars == <<faults>>
mcVars    == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [early |-> 0]

\* Scenario 1 timing perturbation: guard, base action, counter increment.
MCMgrPostEarly(p) ==
    /\ faults.early < MaxEarlyPost
    /\ MgrPostEarly(p)
    /\ faults' = [faults EXCEPT !.early = @ + 1]

MCNext ==
    \/ /\ ~targetFired
       /\ \/ SystemNext                           \* reactive steps: not bounded
          \/ \E p \in Paths : MgrPostOnTime(p)    \* the workload's own timing
       /\ UNCHANGED faultVars
    \/ /\ ~targetFired
       /\ \E p \in Paths : MCMgrPostEarly(p)
    \/ /\ Terminated
       /\ UNCHANGED faultVars

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
\* Invariants checked by the MC configs come from base.tla:
\*   TargetSafe              - the oracle (FRP:674 never throws)
\*   TypeOK                  - structural sanity 1
\*   PrepViewMatchesPipeline - structural sanity 2

\* Sanity check of adhoc tla-patterns section 2: a model that never enables
\* TargetCheck proves nothing.  Checked as an invariant by
\* MC_sanity_reach.cfg, where it MUST be violated (c6 is served).
TargetReached == ~ENABLED TargetCheck

=============================================================================
