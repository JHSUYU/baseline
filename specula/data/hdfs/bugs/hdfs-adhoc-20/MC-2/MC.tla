-------------------------------- MODULE MC --------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-20, BPOfferService:615). *)
(*                                                                         *)
(* Counter-bounded (fault injection / scenario drivers), one counter each: *)
(*   Crash            MaxCrash          S1, S2                             *)
(*   StopNameNode     MaxCleanRestart   S4 (clean stop; restart follows)   *)
(*   ToActive,        MaxFailover       S2, S3, S4 (each HA transition     *)
(*   ToStandby                          counts once)                       *)
(*   Depose           MaxDepose         S3                                 *)
(*   Refresh          MaxRefresh        S2, S3, S4                         *)
(*   ActorDie         MaxActorDeath     S2, S3, S4                         *)
(*   Partition        MaxPartition      S2, S3, S4                         *)
(*   DNRestart        MaxDNRestart      workload (OOB upgrade restart)     *)
(*   ClientEdit       MaxTxid           workload size: written[n] < MaxTxid *)
(*                                                                         *)
(* Unbounded (reactive / consequences of earlier steps):                   *)
(*   SyncEdits, TerminateOnJournalFailure, StopRpcServer, Restart, Heal,   *)
(*   VersionRequest, HandshakeApply, HeartbeatHandle, HeartbeatRpcFail,    *)
(*   TargetCheck.                                                          *)
(*                                                                         *)
(* No VIEW: the counters stay in the fingerprint, so a state first reached *)
(* with more faults used never hides the same state with budget left.      *)
(***************************************************************************)
EXTENDS base, TLC

\* ============================================================================
\* BOUNDS
\* ============================================================================

CONSTANT MaxTxid          \* ClientEdit only while written[n] < MaxTxid
CONSTANT MaxCrash
CONSTANT MaxCleanRestart
CONSTANT MaxFailover
CONSTANT MaxDepose
CONSTANT MaxRefresh
CONSTANT MaxActorDeath
CONSTANT MaxPartition
CONSTANT MaxDNRestart

ASSUME /\ MaxTxid \in Nat
       /\ {MaxCrash, MaxCleanRestart, MaxFailover, MaxDepose, MaxRefresh,
           MaxActorDeath, MaxPartition, MaxDNRestart} \subseteq Nat

\* ============================================================================
\* FAULT COUNTERS
\* ============================================================================

VARIABLE faults

mcVars == <<vars, faults>>

NoFaults == [crash     |-> 0,
             cleanStop |-> 0,
             failover  |-> 0,
             depose    |-> 0,
             refresh   |-> 0,
             death     |-> 0,
             partition |-> 0,
             dnRestart |-> 0]

\* Checked and incremented on the same transition.
Bump(k) == faults' = [faults EXCEPT ![k] = @ + 1]

\* ============================================================================
\* COUNTER-BOUNDED WRAPPERS
\* ============================================================================

\* Workload size bound, not a fault: no counter, guard on the NN's txid.
MCClientEdit(n) ==
    /\ written[n] < MaxTxid
    /\ ClientEdit(n)
    /\ UNCHANGED faults

MCCrash(n) ==
    /\ faults.crash < MaxCrash
    /\ Crash(n)
    /\ Bump("crash")

MCStopNameNode(n) ==
    /\ faults.cleanStop < MaxCleanRestart
    /\ StopNameNode(n)
    /\ Bump("cleanStop")

MCToActive(n) ==
    /\ faults.failover < MaxFailover
    /\ ToActive(n)
    /\ Bump("failover")

MCToStandby(n) ==
    /\ faults.failover < MaxFailover
    /\ ToStandby(n)
    /\ Bump("failover")

MCDepose(n, m) ==
    /\ faults.depose < MaxDepose
    /\ Depose(n, m)
    /\ Bump("depose")

MCPartition(n) ==
    /\ faults.partition < MaxPartition
    /\ Partition(n)
    /\ Bump("partition")

MCActorDie(a) ==
    /\ faults.death < MaxActorDeath
    /\ ActorDie(a)
    /\ Bump("death")

MCRefresh ==
    /\ faults.refresh < MaxRefresh
    /\ Refresh
    /\ Bump("refresh")

MCDNRestart ==
    /\ faults.dnRestart < MaxDNRestart
    /\ DNRestart
    /\ Bump("dnRestart")

\* ============================================================================
\* SPEC
\* ============================================================================

MCInit ==
    /\ Init
    /\ faults = NoFaults

MCNext ==
    /\ ~targetFired
    /\ \/ \E n \in NN :
            \/ MCClientEdit(n)
            \/ SyncEdits(n)                  /\ UNCHANGED faults
            \/ TerminateOnJournalFailure(n)  /\ UNCHANGED faults
            \/ MCCrash(n)
            \/ MCStopNameNode(n)
            \/ StopRpcServer(n)              /\ UNCHANGED faults
            \/ Restart(n)                    /\ UNCHANGED faults
            \/ MCToActive(n)
            \/ MCToStandby(n)
            \/ MCPartition(n)
            \/ Heal(n)                       /\ UNCHANGED faults
       \/ \E n, m \in NN : MCDepose(n, m)
       \/ \E a \in NN :
            \/ VersionRequest(a)             /\ UNCHANGED faults
            \/ HandshakeApply(a)             /\ UNCHANGED faults
            \/ HeartbeatHandle(a)            /\ UNCHANGED faults
            \/ HeartbeatRpcFail(a)           /\ UNCHANGED faults
            \/ TargetCheck(a)                /\ UNCHANGED faults
            \/ MCActorDie(a)
       \/ MCRefresh
       \/ MCDNRestart

MCSpec == MCInit /\ [][MCNext]_mcVars

\* ============================================================================
\* SYMMETRY
\* ============================================================================

\* The NameNodes are interchangeable: Init picks the first active
\* nondeterministically and no action names a particular NN.  Only used in
\* the HA configs (two NNs); harmless with one NN.
Symmetry == Permutations(NN)

=============================================================================
