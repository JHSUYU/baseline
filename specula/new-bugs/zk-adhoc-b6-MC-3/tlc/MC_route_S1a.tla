------------------------------- MODULE MC_route_S1a -------------------------------
(*
 * Route check for Scenario 1, not a hunt config. It narrows MC_hunt_S1 to the
 * workload-shaped route of brief S1 variant (a), to give Phase 4 a counterexample
 * that needs no stall of F's CommitProcessor:
 *   - O registers only while F has no commit waiting to be applied, so variants
 *     (b) and (c) and S2's window cannot be used;
 *   - no TRUNC is sent, so the TRUNC routes cannot be used;
 *   - the target fires only live on O's commit processor (ZooKeeperServer.java:1888).
 * It only removes behaviors of MCSpec, so any violation is also one of MC_hunt_S1.
 *)
EXTENDS MC

RouteRegisterWhenFIdle ==
    (hPhase[O] = "none" /\ hPhase'[O] /= "none")
        => (commitQ[F] = <<>> /\ applyPending[F] = NoZxid)

RouteFiresLiveOnObserver ==
    (~targetFired /\ targetFired') => applyPending[O] /= NoZxid

RouteNoTrunc ==
    \A n \in Learners : \A i \in DOMAIN inQ[n] : inQ[n][i].type /= "TRUNC"

================================================================================
