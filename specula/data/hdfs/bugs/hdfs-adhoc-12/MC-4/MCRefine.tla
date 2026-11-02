------------------------------- MODULE MCRefine -------------------------------
(***************************************************************************)
(* Final-state refinements of TargetSafe for hunt follow-ups (hdfs-adhoc-12 *)
(* Phase 3).  Each is violated only by a TargetSafe violation of a chosen   *)
(* shape, so any counterexample also counts for its parent hunt cfg.  Run   *)
(* next to byte-identical copies of spec/base.tla and spec/MC.tla.          *)
(***************************************************************************)
EXTENDS MC

\* Scenario 4, robust shape: the target fires only after the source lost every
\* reply the cfg allows (MC_hunt_staleissuer.cfg: 3), so the source keeps its
\* retired key for a whole interval instead of racing one rotation.
TargetSafeAllLost == ~(targetFired /\ fc.lost = MaxLostResponses)

=============================================================================
