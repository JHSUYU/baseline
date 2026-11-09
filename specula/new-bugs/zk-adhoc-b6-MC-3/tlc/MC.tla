----------------------------------- MODULE MC -----------------------------------
(*
 * Model checking wrapper for base.tla. Counters bound what introduces
 * non-determinism; reactive steps are not bounded (mc-spec-pattern).
 * Each Scenario's hunt config sets only that Scenario's counters.
 *
 * Fault counters:
 *   MaxFollowerRestart      F's process stops (workload: TestAdhocWorkloadB6.java:121)
 *   MaxObserverRestart      O's process stops (workload: TestAdhocWorkloadB6.java:120)
 *   MaxEvictingPackets      S3: a commit whose packet empties committedPkts
 * Timing counters, which bound an interleaving at its source so it cannot leave
 * a packet stuck at the head of a queue:
 *   MaxSyncWindowProposals  proposals made while F's handler has not queued UPTODATE:
 *                           they cannot reach om.proposalReceived (S1, S2)
 *   MaxCommitDuringSync     commits made between NEWLEADER and UPTODATE being queued:
 *                           they end in packetsCommitted (S2)
 *
 * The sync-window bound counts at propose time, so it is a lower bound on such
 * proposals: one F logged before it crashed can come back at resync through TRUNC
 * and startForwarding (LearnerHandler.java:858-865, Leader.java:1385-1389) without
 * being counted. A hunt config can therefore report TargetSafe with syncProp = 0.
 * Check faults in a counterexample to see which route it took.
 *)

EXTENDS base

CONSTANTS
    MaxFollowerRestart,
    MaxObserverRestart,
    MaxSyncWindowProposals,
    MaxCommitDuringSync,
    MaxEvictingPackets,
    S2Only      \* S2 focus: see OmWillKnow. FALSE in every config but MC_hunt_S2.

VARIABLE faults

faultVars == <<faults>>
mcVars == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [fRestart |-> 0, oRestart |-> 0, syncProp |-> 0,
                 syncCommit |-> 0, evict |-> 0]

\* F's handler has not queued UPTODATE (LearnerHandler.java:653), so a PROPOSAL sent
\* now is read before ObserverMaster exists (Follower.java:115, :195).
ProposeInSyncWindow == hPhase[F] /= "done"

\* NEWLEADER is queued and UPTODATE is not, so a COMMIT sent now is read between
\* them: Learner.java:693-695, then :845-847 (brief S2).
CommitInSyncWindow == hPhase[F] = "newleader"

\* The next commit's PROPOSAL is, or will be, known to ObserverMaster: it is in
\* proposedPkts, or queued behind UPTODATE. A commit for which this is false
\* with F's handler done is exactly S1's dropped commit. S2Only forbids that, so
\* MC_hunt_S2 cannot report S1's shorter route when asked about S2's.
OmWillKnow(z) ==
    \/ \E i \in DOMAIN omProposed : omProposed[i] = z
    \/ \E i \in DOMAIN inQ[F] :
        /\ inQ[F][i] = Pkt("PROPOSAL", z)
        /\ ~ \E j \in DOMAIN inQ[F] : j > i /\ inQ[F][j].type = "UPTODATE"

MCClientPropose ==
    /\ ClientPropose
    /\ IF ProposeInSyncWindow
       THEN /\ faults.syncProp < MaxSyncWindowProposals
            /\ faults' = [faults EXCEPT !.syncProp = @ + 1]
       ELSE UNCHANGED faults

MCLeaderTryToCommit ==
    /\ LeaderTryToCommit
    /\ S2Only /\ hPhase[F] = "done" => OmWillKnow(lCommitted + 1)
    /\ IF CommitInSyncWindow
       THEN /\ faults.syncCommit < MaxCommitDuringSync
            /\ faults' = [faults EXCEPT !.syncCommit = @ + 1]
       ELSE UNCHANGED faults

MCFollowerCrash ==
    /\ faults.fRestart < MaxFollowerRestart
    /\ FollowerCrash
    /\ faults' = [faults EXCEPT !.fRestart = @ + 1]

MCObserverCrash ==
    /\ faults.oRestart < MaxObserverRestart
    /\ ObserverCrash
    /\ faults' = [faults EXCEPT !.oRestart = @ + 1]

MCProposalCommittedEvicting ==
    /\ faults.evict < MaxEvictingPackets
    /\ ProposalCommittedEvicting
    /\ faults' = [faults EXCEPT !.evict = @ + 1]

MCReactive ==
    /\ ReactiveNext
    /\ UNCHANGED faults

MCNext ==
    /\ ~targetFired
    /\ \/ MCClientPropose
       \/ MCLeaderTryToCommit
       \/ MCReactive
       \/ MCProposalCommittedEvicting
       \/ MCFollowerCrash
       \/ MCObserverCrash

MCSpec == MCInit /\ [][MCNext]_mcVars

\* Every counter stays within its bound.
MCFaultsOk ==
    /\ faults.fRestart <= MaxFollowerRestart
    /\ faults.oRestart <= MaxObserverRestart
    /\ faults.syncProp <= MaxSyncWindowProposals
    /\ faults.syncCommit <= MaxCommitDuringSync
    /\ faults.evict <= MaxEvictingPackets

================================================================================
