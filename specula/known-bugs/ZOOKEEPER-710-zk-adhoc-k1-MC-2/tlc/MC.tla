-------------------------------- MODULE MC --------------------------------
(***************************************************************************)
(* Model checking wrapper for base (zk-adhoc-k1).                          *)
(*                                                                         *)
(* Counter-bounded (they introduce non-determinism):                       *)
(*   opens    ClientOpen                       workload reopen, bounded    *)
(*   ops      ClientSubmitLeader/Follower for write/read/ping              *)
(*   syncs    ClientSubmitLeader/Follower for sync      (Scenario 1)       *)
(*   abandons ClientAbandonOpen                         (Scenario 2 fault) *)
(* Unbounded (reactive): ClientCreateSession (once, from "Init"),          *)
(*   ClientDisconnect (bounded through opens), FollowerReadConnect,        *)
(*   LeaderReadConnect, LeaderRecvRevalidate, FollowerRevalidate,          *)
(*   LeaderRecvRequest, PrepCreateSession, TargetCheck.                    *)
(* Message delay is unbounded queue residence, not a separate fault.       *)
(***************************************************************************)
EXTENDS base

zk == INSTANCE base

CONSTANTS
    MaxOpens,     \* reopens of the session (workload moves)
    MaxOps,       \* write/read/ping ops
    MaxSyncs,     \* sync ops (Scenario 1)
    MaxAbandon    \* abandoned handshakes (Scenario 2)

VARIABLE counters

mcVars == <<vars, counters>>

MCInit ==
    /\ Init
    /\ counters = [opens |-> 0, ops |-> 0, syncs |-> 0, abandons |-> 0]

Bump(k) == counters' = [counters EXCEPT ![k] = @ + 1]

MCClientOpen(s) ==
    /\ counters.opens < MaxOpens
    /\ zk!ClientOpen(s)
    /\ Bump("opens")

MCClientAbandonOpen ==
    /\ counters.abandons < MaxAbandon
    /\ zk!ClientAbandonOpen
    /\ Bump("abandons")

OpKey(t) == IF t = "sync" THEN "syncs" ELSE "ops"
OpMax(t) == IF t = "sync" THEN MaxSyncs ELSE MaxOps

MCClientSubmitLeader(t) ==
    /\ counters[OpKey(t)] < OpMax(t)
    /\ zk!ClientSubmitLeader(t)
    /\ Bump(OpKey(t))

MCClientSubmitFollower(f, t) ==
    /\ counters[OpKey(t)] < OpMax(t)
    /\ zk!ClientSubmitFollower(f, t)
    /\ Bump(OpKey(t))

MCNext ==
    /\ ~targetFired
    /\ \/ /\ \/ \E s \in Server : ClientCreateSession(s)
             \/ ClientDisconnect
             \/ \E f \in Followers : \E a \in inbox[f] : FollowerReadConnect(f, a)
             \/ \E a \in inbox[Leader] : LeaderReadConnect(a)
             \/ \E f \in Followers : LeaderRecvRevalidate(f)
             \/ \E f \in Followers : FollowerRevalidate(f)
             \/ \E f \in Followers : LeaderRecvRequest(f)
             \/ PrepCreateSession
             \/ TargetCheck
          /\ UNCHANGED counters
       \/ \E s \in Server : MCClientOpen(s)
       \/ MCClientAbandonOpen
       \/ \E t \in CheckTypes : MCClientSubmitLeader(t)
       \/ \E f \in Followers, t \in {"write", "sync"} : MCClientSubmitFollower(f, t)

MCSpec == MCInit /\ [][MCNext]_mcVars

Symmetry == Permutations(Followers)

MCTypeOK ==
    /\ TypeOK
    /\ counters \in [{"opens", "ops", "syncs", "abandons"} -> Nat]
    /\ client.att <= MaxOpens

=============================================================================
