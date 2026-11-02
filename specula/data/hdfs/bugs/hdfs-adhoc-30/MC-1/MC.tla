--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hdfs-adhoc-30).                    *)
(*                                                                         *)
(* Fault-injection actions are counter-bounded; reactive actions           *)
(* (heartbeats, handshakes, command processing, daemon steps, syncs,       *)
(* restarts, exits of stopped actors) are not.  Work is bounded by the     *)
(* recovery-id set (MaxRecoveries) and operator refreshes by the BPOS      *)
(* incarnation set (MaxRefresh).                                           *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxRecoveries,    \* recoveries the NN may issue to this DN (work, not a fault)
    MaxRefresh,       \* operator refreshNamenodes creating a new BPOS for the bpid (Scenario 4)
    MaxDemote,        \* HA active -> standby transitions (Scenario 1)
    MaxPromote,       \* HA standby -> active transitions (Scenario 1)
    MaxNNCrash,       \* NameNode process crashes (Scenario 1 crash variant; Scenario 3 assert variant)
    MaxEdits,         \* edits the active assigns (unsynced until NNLogSync)
    MaxActorExit,     \* BPServiceActor exits by any A1-A3 route (Scenarios 2, 3)
    MaxReplicaFail    \* replica-level failures ending a block before syncBlock

MCRec == 1..MaxRecoveries
MCInc == 1..(MaxRefresh + 1)

VARIABLE faults

faultVars == <<faults>>
mcVars    == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [demote |-> 0, promote |-> 0, crash |-> 0, edit |-> 0,
                 exit |-> 0, replicaFail |-> 0]

Bump(f) == faults' = [faults EXCEPT ![f] = @ + 1]

-----------------------------------------------------------------------------
(* Wrappers.  Every wrapper carries ~targetFired: once the target fired, everything stops     *)
(* (adhoc tla-patterns 1).  Each MCNext disjunct is a single operator application quantified   *)
(* over constant sets, so TLC names every counterexample step after its wrapper.               *)

\* ---- bounded fault / work wrappers ----

\* Recovery ids are allocated in increasing order (no symmetric branching on the id).
MCNNIssueRecovery(n) ==
    /\ ~targetFired
    /\ \E r \in Rec :
         /\ rec[r].pc = "none"
         /\ \A s \in Rec : rec[s].pc = "none" => r <= s
         /\ NNIssueRecovery(n, r)
    /\ UNCHANGED faultVars

MCNNLogEdit(n) ==
    /\ ~targetFired
    /\ faults.edit < MaxEdits
    /\ NNLogEdit(n)
    /\ Bump("edit")

MCDemoteNN(n) ==
    /\ ~targetFired
    /\ faults.demote < MaxDemote
    /\ DemoteNN(n)
    /\ Bump("demote")

MCPromoteNN(n) ==
    /\ ~targetFired
    /\ faults.promote < MaxPromote
    /\ PromoteNN(n)
    /\ Bump("promote")

MCNNCrash(n) ==
    /\ ~targetFired
    /\ faults.crash < MaxNNCrash
    /\ NNCrash(n)
    /\ Bump("crash")

MCActorExit(b, n) ==
    /\ ~targetFired
    /\ faults.exit < MaxActorExit
    /\ ActorExit(b, n)
    /\ Bump("exit")

MCRecoverPreFail(r) ==
    /\ ~targetFired
    /\ faults.replicaFail < MaxReplicaFail
    /\ RecoverPreFail(r)
    /\ Bump("replicaFail")

\* Operator refreshNamenodes: bounded by the incarnation set (MaxRefresh), not by a counter.
MCRefreshAdd ==
    /\ ~targetFired
    /\ RefreshAdd
    /\ UNCHANGED faultVars

MCRefreshRemove(b) ==
    /\ ~targetFired
    /\ RefreshRemove(b)
    /\ UNCHANGED faultVars

\* ---- reactive wrappers (unbounded) ----

MCNNLogSync(n)                  == ~targetFired /\ NNLogSync(n) /\ UNCHANGED faultVars
MCNNRestart(n)                  == ~targetFired /\ NNRestart(n) /\ UNCHANGED faultVars
MCVersionRequest(b, n)          == ~targetFired /\ VersionRequest(b, n) /\ UNCHANGED faultVars
MCVerifyAndSetNamespaceInfo(b, n) == ~targetFired /\ VerifyAndSetNamespaceInfo(b, n) /\ UNCHANGED faultVars
MCRegister(b, n)                == ~targetFired /\ Register(b, n) /\ UNCHANGED faultVars
MCHBSend(b, n)                  == ~targetFired /\ HBSend(b, n) /\ UNCHANGED faultVars
MCHBRecv(b, n)                  == ~targetFired /\ HBRecv(b, n) /\ UNCHANGED faultVars
MCProcessCmd(b, n)              == ~targetFired /\ ProcessCmd(b, n) /\ UNCHANGED faultVars
MCActorStopExit(b, n)           == ~targetFired /\ ActorStopExit(b, n) /\ UNCHANGED faultVars
MCRecoverPre(r)                 == ~targetFired /\ RecoverPre(r) /\ UNCHANGED faultVars
MCRecoverLookup(r)              == ~targetFired /\ RecoverLookup(r) /\ UNCHANGED faultVars
MCTargetCheck(r)                == ~targetFired /\ TargetCheck(r) /\ UNCHANGED faultVars

-----------------------------------------------------------------------------

MCNext ==
    \/ \E n \in NN : MCNNIssueRecovery(n)
    \/ \E n \in NN : MCNNLogEdit(n)
    \/ \E n \in NN : MCNNLogSync(n)
    \/ \E n \in NN : MCDemoteNN(n)
    \/ \E n \in NN : MCPromoteNN(n)
    \/ \E n \in NN : MCNNCrash(n)
    \/ \E n \in NN : MCNNRestart(n)
    \/ \E b \in Inc, n \in NN : MCVersionRequest(b, n)
    \/ \E b \in Inc, n \in NN : MCVerifyAndSetNamespaceInfo(b, n)
    \/ \E b \in Inc, n \in NN : MCRegister(b, n)
    \/ \E b \in Inc, n \in NN : MCHBSend(b, n)
    \/ \E b \in Inc, n \in NN : MCHBRecv(b, n)
    \/ \E b \in Inc, n \in NN : MCProcessCmd(b, n)
    \/ \E b \in Inc, n \in NN : MCActorExit(b, n)
    \/ \E b \in Inc, n \in NN : MCActorStopExit(b, n)
    \/ \E r \in Rec : MCRecoverPre(r)
    \/ \E r \in Rec : MCRecoverPreFail(r)
    \/ \E r \in Rec : MCRecoverLookup(r)
    \/ \E r \in Rec : MCTargetCheck(r)
    \/ MCRefreshAdd
    \/ \E b \in Inc : MCRefreshRemove(b)

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(* Invariants used by the cfgs *)

MCTypeOK ==
    /\ TypeOK
    /\ faults \in [{"demote", "promote", "crash", "edit", "exit", "replicaFail"} -> Nat]

\* Scenario-isolation guide for MC_hunt_s4_replacement.cfg, used as ACTION_CONSTRAINT.  Pruning
\* only: every behavior it keeps is a behavior of MCSpec, so a violation it finds is a real
\* violation of the full model.  With no exits, the stopped old BPOS cannot null its view through W2
\* (the shorter Scenario-2-style firing a refresh stop allows), and with MaxDemote = MaxNNCrash = 0
\* no NN ever reports non-ACTIVE after being acknowledged, so a TargetSafe violation can only come
\* from a daemon whose L602 lookup returned a replacement BPOS that has not acknowledged an active NN.
S4IsolationGuide ==
    \A b \in Inc, n \in NN : actorSt[b][n] # "exited" => actorSt'[b][n] # "exited"

\* Fault-free sanity (adhoc tla-patterns 2): with every budget at 0, every recovery the NN issues
\* can be accepted and committed in the workload topology, so the workload's own path exists.
\* Used as a must-be-violated probe together with TargetReached.
WorkloadCommitted == ~(\E r \in Rec : rec[r].pc = "done" /\ rec[r].bp # 0)

=============================================================================
