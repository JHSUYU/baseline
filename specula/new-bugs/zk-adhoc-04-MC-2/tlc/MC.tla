---------------------------------- MODULE MC ----------------------------------
\* Model-checking wrapper for zk-adhoc-04 (base.tla).
\*
\* Only actions that introduce non-determinism are bounded (mc-spec-pattern.md,
\* "Which Actions to Bound"):
\*   PeerStop            stop  <= MaxStops        crash / QuorumUtil.shutdown
\*   PartitionFollower   part  <= MaxPartitions   network partition follower|leader
\*   ClientMove          move  <= MaxClientMoves  connection loss / updateServerList
\*   LeaderPropose       write <= MaxClientWrites client writes
\*   a leader instance leaves BROADCAST with outstanding proposals
\*                       aband <= MaxAbandonedProposals (S2 mechanism)
\*   LeaderDiscovery     new epoch <= MaxEpoch
\* Reactive steps (elections, sync, commit, apply, RO start/stop, client connect,
\* replies, RO seek, restart of a stopped peer) are unbounded.
\*
\* No symmetry: FLE breaks vote ties by sid (FastLeaderElection.java:741), so
\* permuting Server is not sound.
EXTENDS base

CONSTANT MaxStops, MaxPartitions, MaxClientMoves, MaxClientWrites,
         MaxAbandonedProposals, MaxEpoch

ASSUME /\ MaxStops \in Nat /\ MaxPartitions \in Nat /\ MaxClientMoves \in Nat
       /\ MaxClientWrites \in Nat /\ MaxAbandonedProposals \in Nat /\ MaxEpoch \in Nat
ASSUME MaxClientWrites < ZB - 1        \* counters stay below the zxid base

VARIABLE faults

mc_vars == <<vars, faults>>

-----------------------------------------------------------------------------
(* Counter-bounded wrappers                                                *)
-----------------------------------------------------------------------------

\* A leader instance that leaves BROADCAST while proposals are outstanding abandons them
\* (Leader.outstandingProposals is dropped with the instance).
Abandons(s) == Outstanding(s) # {}
AbandonOK(s) == Abandons(s) => faults.aband < MaxAbandonedProposals
AbandonInc(s) == IF Abandons(s) THEN 1 ELSE 0

MCPeerStop(s, g) ==
    /\ faults.stop < MaxStops
    /\ AbandonOK(s)
    /\ PeerStop(s, g)
    /\ faults' = [faults EXCEPT !.stop = @ + 1, !.aband = @ + AbandonInc(s)]

MCLeaderShutdown(L) ==
    /\ AbandonOK(L)
    /\ LeaderShutdown(L)
    /\ faults' = [faults EXCEPT !.aband = @ + AbandonInc(L)]

MCPartitionFollower(F) ==
    /\ faults.part < MaxPartitions
    /\ PartitionFollower(F)
    /\ faults' = [faults EXCEPT !.part = @ + 1]

MCClientMove(c) ==
    /\ faults.move < MaxClientMoves
    /\ ClientMove(c)
    /\ faults' = [faults EXCEPT !.move = @ + 1]

MCLeaderPropose(L) ==
    /\ faults.write < MaxClientWrites
    /\ LeaderPropose(L)
    /\ faults' = [faults EXCEPT !.write = @ + 1]

\* One reply in flight per client: pipelined replies carry no zxid values that a single
\* in-flight reply taken at the same moments cannot carry.
MCServerReply(c) ==
    /\ cReplies[c] = <<>>
    /\ ServerReply(c)

MCLeaderDiscovery(L, Q) ==
    /\ Q \subseteq Server /\ Q # {}
    /\ NewEpoch(Q) <= MaxEpoch
    /\ LeaderDiscovery(L, Q)
    /\ UNCHANGED faults

-----------------------------------------------------------------------------
(* Init / Next                                                             *)
-----------------------------------------------------------------------------

MCInit ==
    /\ Init
    /\ faults = [stop |-> 0, part |-> 0, move |-> 0, write |-> 0, aband |-> 0]

\* Unbounded (reactive / recovery / client-API) steps leave the counters alone.
\* Every disjunct carries ~targetFired: once the target fired the run stops
\* (tla-patterns section 1).  One disjunct per action so TLC reports coverage per action.
Live == ~targetFired
Same == UNCHANGED faults

MCNext ==
    \* --- peer lifecycle / read-only mode / apply ---
    \/ \E s \in Server : Live /\ PeerStart(s) /\ Same
    \/ \E s \in Server : Live /\ ReloadDb(s) /\ Same
    \/ \E s \in Server : Live /\ StartRO(s) /\ Same
    \/ \E s \in Server : Live /\ ShutdownRO(s) /\ Same
    \/ \E s \in Server : Live /\ ApplyCommitted(s) /\ Same
    \* --- election ---
    \/ \E Q \in SUBSET Server, L \in Server : Live /\ Elect(Q, L) /\ Same
    \/ \E s \in Server : Live /\ ElectStranded(s) /\ Same
    \/ \E s, L \in Server : Live /\ JoinLeader(s, L) /\ Same
    \* --- leader ---
    \/ \E L \in Server, Q \in SUBSET Server : Live /\ MCLeaderDiscovery(L, Q)
    \/ \E L, F \in Server : Live /\ LearnerHandlerSync(L, F) /\ Same
    \/ \E L \in Server : Live /\ LeaderStartup(L) /\ Same
    \/ \E L \in Server : Live /\ LeaderServe(L) /\ Same
    \/ \E L, F \in Server : Live /\ LeaderSendUptodate(L, F) /\ Same
    \/ \E L \in Server : Live /\ MCLeaderPropose(L)
    \/ \E L \in Server : Live /\ LeaderSyncAck(L) /\ Same
    \/ \E L \in Server : Live /\ LeaderCommit(L) /\ Same
    \/ \E L \in Server : Live /\ MCLeaderShutdown(L)
    \* --- learner sync and broadcast ---
    \/ \E F \in Server : Live /\ LearnerRecvDiff(F) /\ Same
    \/ \E F \in Server : Live /\ LearnerRecvSnap(F) /\ Same
    \/ \E F \in Server : Live /\ LearnerRecvTrunc(F) /\ Same
    \/ \E F \in Server : Live /\ LearnerRecvProposal(F) /\ Same
    \/ \E F \in Server : Live /\ LearnerRecvCommit(F) /\ Same
    \/ \E F \in Server : Live /\ LearnerRecvNewLeader(F) /\ Same
    \/ \E F \in Server : Live /\ LearnerRecvUptodate(F) /\ Same
    \/ \E F \in Server : Live /\ LearnerFlushDeferred(F) /\ Same
    \/ \E F \in Server : Live /\ FollowerRecvProposal(F) /\ Same
    \/ \E F \in Server : Live /\ FollowerSyncAck(F) /\ Same
    \/ \E F \in Server : Live /\ FollowerRecvCommit(F) /\ Same
    \/ \E F \in Server : Live /\ FollowerLoseLeader(F) /\ Same
    \* --- faults ---
    \/ \E s \in Server, g \in BOOLEAN : Live /\ MCPeerStop(s, g)
    \/ \E F \in Server : Live /\ MCPartitionFollower(F)
    \/ \E c \in Client : Live /\ MCClientMove(c)
    \* --- client ---
    \/ \E c \in Client : Live /\ MCServerReply(c) /\ Same
    \/ \E c \in Client : Live /\ ClientRecvReply(c) /\ Same
    \/ \E c \in Client : Live /\ ClientRwTargetGone(c) /\ Same
    \/ \E c \in Client, s \in Server : Live /\ ClientSeekRw(c, s) /\ Same
    \* --- target ---
    \/ \E c \in Client, s \in Server : Live /\ TargetCheck(c, s) /\ Same

MCSpec == MCInit /\ [][MCNext]_mc_vars

-----------------------------------------------------------------------------
(* View                                                                    *)
-----------------------------------------------------------------------------

\* The ghost `served` only feeds the structural invariant ClientZxidWasServed and no
\* action reads it, so it is left out of the fingerprint.  The fault counters stay in the
\* view: dropping them could prune a state reached first with a larger fault budget spent,
\* which would make a bounded "no violation" result incomplete.
ModelView == <<peerVars, dataVars, learnVars, leaderVars, clientVars,
               targetFired, targetInfo, committed, faults>>

-----------------------------------------------------------------------------
(* Hunt-focusing state constraints (brief section 4, "Per-hunt constants") *)
(* Each keeps only executions in which the client's lastZxid has a given   *)
(* provenance, so a hunt cannot stop at a shorter hit of another class.    *)
(* Client reads are optional and change nothing but cLastZxid, so pruning  *)
(* on the client's value keeps every hit of the focused class reachable.   *)
-----------------------------------------------------------------------------

\* brief: the client never holds a txn-less makeZxid(e, 0) (excludes class B / S1)
NoSyntheticClientZxid ==
    \A c \in Client : cLastZxid[c] = 0 \/ Ctr(cLastZxid[c]) # 0

\* S2 focus: the client only ever holds a real txn that is not committed (class C only)
ClientOnlyUncommitted ==
    \A c \in Client : cLastZxid[c] = 0 \/ (Ctr(cLastZxid[c]) # 0 /\ cLastZxid[c] \notin committed)

\* S4 focus (MC-4 asks about lastZxidSeen = 0): the client never stores a zxid (class A only)
ClientZxidZero ==
    \A c \in Client : cLastZxid[c] = 0

\* Route focus (MC_route_*.cfg only): the shortest hit of a hunt may use a window that needs a
\* test hook or a stale peer.  Used INSTEAD of TargetSafe, this reports only a hit at a RUNNING
\* follower of a live leader, so a route config returns the plainest execution of the same class.
\* It must be an invariant: TLC also checks invariants on states a CONSTRAINT excludes.  A hit
\* anywhere else is a dead end (Live), so the search continues past it.
NoHitAtLiveFollower ==
    ~(/\ targetFired
      /\ LET s == targetInfo.sid IN
         role[s] = "FOLLOWING" /\ serving[s] = "RW" /\ LeaderAlive(s))

-----------------------------------------------------------------------------
(* Invariants used by the configs                                          *)
-----------------------------------------------------------------------------

MCTypeOK ==
    /\ TypeOK
    /\ faults \in [stop : Nat, part : Nat, move : Nat, write : Nat, aband : Nat]

\* Fault counters never exceed their bounds (wrapper sanity).
FaultBounds ==
    /\ faults.stop <= MaxStops /\ faults.part <= MaxPartitions
    /\ faults.move <= MaxClientMoves /\ faults.write <= MaxClientWrites
    /\ faults.aband <= MaxAbandonedProposals

=============================================================================
