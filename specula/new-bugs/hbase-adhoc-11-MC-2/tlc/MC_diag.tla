------------------------------- MODULE MC_diag ------------------------------
(***************************************************************************)
(* Phase 3 diagnostic probes.  These are NOT hunting targets: each answers *)
(* a question left open in brief-coverage.md and is expected to be         *)
(* VIOLATED, which shows the state is reachable.  Adds no actions.         *)
(***************************************************************************)
EXTENDS MC

\* Scenario 2 consequence: the detached TRSP has written CLOSING, its CLOSED report was dropped
\* (AM:1347-1350), the region is closed on the RS, and no TRSP is attached.
NotStrandedByDroppedReport ==
    ~ \E r \in Regions, p \in Pids :
        /\ trsp[p].region = r
        /\ trsp[p].pc = "CONFIRM_CLOSED"
        /\ trsp[p].child # NoProc
        /\ rrpb[trsp[p].child].st = "DISPATCH"
        /\ rrpb[trsp[p].child].sent
        /\ rsnProc[r] = NoProc
        /\ rsnState[r] = "CLOSING"
        /\ \A s \in Servers : r \notin rsRegions[s]
        /\ msgs = {}
=============================================================================
