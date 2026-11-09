-------------------------------- MODULE MC --------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hbase-adhoc-k2).                   *)
(* Counter-bounds only the fault-injection actions that introduce          *)
(* non-determinism: client attempt timeout, lost reply, master crash.      *)
(* Reactive actions (handlers, procedure steps, failover recovery, client  *)
(* reply handling) are unbounded.                                          *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxTimeouts,      \* ClientTimeout          [Scenario 1, 3]
    MaxLostReplies,   \* ReplyLost              [Scenario 1]
    MaxCrashes        \* MasterCrash            [Scenario 2]

VARIABLE faults

\* The workload's single logical request: admin.addColumnFamily(T, cf1)
\* (TestTableDescriptorModificationFromClient.java:124).  Tuples cannot be written
\* in a .cfg, hence `FamilySeq <- MCFamilySeq`.
MCFamilySeq == <<"cf1">>

faultVars == <<faults>>
mcVars == <<vars, faults>>

MCInit ==
    /\ Init
    /\ faults = [timeouts |-> 0, lost |-> 0, crashes |-> 0]

MCClientTimeout ==
    /\ faults.timeouts < MaxTimeouts
    /\ ClientTimeout
    /\ faults' = [faults EXCEPT !.timeouts = @ + 1]

MCReplyLost ==
    /\ faults.lost < MaxLostReplies
    /\ ReplyLost
    /\ faults' = [faults EXCEPT !.lost = @ + 1]

MCMasterCrash ==
    /\ faults.crashes < MaxCrashes
    /\ MasterCrash
    /\ faults' = [faults EXCEPT !.crashes = @ + 1]

MCNext ==
    \/ /\ ~targetFired
       /\ \/ /\ \/ ClientNext
                \/ HandlerNext
                \/ ProcNext
                \/ MasterNext
             /\ UNCHANGED faultVars
          \/ MCClientTimeout
          \/ MCReplyLost
          \/ MCMasterCrash
    \/ /\ Terminated
       /\ UNCHANGED faultVars

MCSpec == MCInit /\ [][MCNext]_mcVars

\* No VIEW: the fault counters stay in the state (spent budget matters).
\* No symmetry: one client, one table, and ids are allocated in order.

-----------------------------------------------------------------------------
(* Invariants *)

MCTypeOK ==
    /\ TypeOK
    /\ faults.timeouts <= MaxTimeouts
    /\ faults.lost <= MaxLostReplies
    /\ faults.crashes <= MaxCrashes

\* Temporary sanity check (adhoc tla-patterns §2): TargetCheck is enabled in some
\* reachable state.  EXPECTED TO BE VIOLATED (run only via MC_sanity_reached.cfg).
TargetReached == ~(\E a \in DOMAIN attempts : attempts[a].hpc = "Started" /\ masterUp)

\* Sanity: the fault-free workload completes (expected to be violated: it proves the
\* client can reach Finished, i.e. the model is not stuck).  Run only via
\* MC_sanity_reached.cfg.
WorkloadCompletes == client.pc # "Finished"

=============================================================================
