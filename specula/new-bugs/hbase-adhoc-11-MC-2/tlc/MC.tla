-------------------------------- MODULE MC --------------------------------
(***************************************************************************)
(* Model-checking wrapper for base.tla (hbase-adhoc-11).                   *)
(*                                                                         *)
(* Counter-bounded: the actions that INTRODUCE non-determinism from the    *)
(* environment or the fault model (brief section 1):                       *)
(*   ops        operator move / unassign / assign through TargetCheck      *)
(*   disables   operator disableTable (workload)                           *)
(*   splits     RS-initiated split requests (S1, S3)                       *)
(*   aborts     operator abortProcedure on the split (S1)                  *)
(*   preOpFails split PRE_OPERATION coprocessor veto / quota (S1)          *)
(*   truncates  operator truncateRegion (S2)                               *)
(*   balPlans   balancer plans (S2, S3)                                    *)
(*   crashes    RegionServer crash (S2 variant)                            *)
(*   failovers  master failover (S3)                                       *)
(*   decoms     operator decommission with offload (S3)                    *)
(*   rsgs       operator RSGroup moveServers (S3)                          *)
(*   rpcFails   RPC failure on open/close dispatch (fault model; 0 in all  *)
(*              hunts, no Scenario uses it)                                *)
(* Not bounded: every reactive step (TRSP/RRPB/RS handlers/report         *)
(* delivery/split and truncate steps and rollback/disable steps/SCP       *)
(* steps/server expiry/balancer execution/caller loop steps).             *)
(* MaxPid bounds the total number of procedures (a model bound; reported  *)
(* with every result; PidBudgetOK tells whether a run used it all up).     *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxOps, MaxDisables, MaxSplits, MaxAborts, MaxPreOpFails, MaxTruncates,
    MaxBalancerPlans, MaxCrashes, MaxFailovers, MaxDecoms, MaxRsgMoves, MaxRpcFails

VARIABLE faults

mcVars == <<vars, faults>>

NoFaults == [ops |-> 0, disables |-> 0, splits |-> 0, aborts |-> 0, preOpFails |-> 0,
             truncates |-> 0, balPlans |-> 0, crashes |-> 0, failovers |-> 0,
             decoms |-> 0, rsgs |-> 0, rpcFails |-> 0]

Bump(k) == faults' = [faults EXCEPT ![k] = @ + 1]

MCInit == Init /\ faults = NoFaults

-----------------------------------------------------------------------------
(* Bounded wrappers *)

\* the operator's requests are bounded; internal callers are bounded by their own triggers
MCTargetCheck(c, r, op, d) ==
    IF c = "operator"
      THEN /\ faults.ops < MaxOps
           /\ TargetCheck(c, r, op, d)
           /\ Bump("ops")
      ELSE /\ TargetCheck(c, r, op, d)
           /\ UNCHANGED faults

MCOperatorDisable ==
    /\ faults.disables < MaxDisables
    /\ OperatorDisable
    /\ Bump("disables")

MCSplitSubmit(r) ==
    /\ faults.splits < MaxSplits
    /\ SplitSubmit(r)
    /\ Bump("splits")

MCOperatorAbortSplit ==
    /\ faults.aborts < MaxAborts
    /\ OperatorAbortSplit
    /\ Bump("aborts")

MCSplitPreOperationFail ==
    /\ faults.preOpFails < MaxPreOpFails
    /\ SplitPreOperation(TRUE)
    /\ Bump("preOpFails")

MCOperatorTruncate(r) ==
    /\ faults.truncates < MaxTruncates
    /\ OperatorTruncate(r)
    /\ Bump("truncates")

MCBalancerPlan(r, d) ==
    /\ faults.balPlans < MaxBalancerPlans
    /\ BalancerPlan(r, d)
    /\ Bump("balPlans")

MCRsCrash(s) ==
    /\ faults.crashes < MaxCrashes
    /\ RsCrash(s)
    /\ Bump("crashes")

MCMasterFailover ==
    /\ faults.failovers < MaxFailovers
    /\ MasterFailover
    /\ Bump("failovers")

MCOperatorDecommission(s) ==
    /\ faults.decoms < MaxDecoms
    /\ OperatorDecommission(s)
    /\ Bump("decoms")

MCOperatorRsgMoveServers(s) ==
    /\ faults.rsgs < MaxRsgMoves
    /\ OperatorRsgMoveServers(s)
    /\ Bump("rsgs")

MCRemoteCallFailedInjected(m) ==
    /\ faults.rpcFails < MaxRpcFails
    /\ RemoteCallFailed(m, TRUE)
    /\ Bump("rpcFails")

-----------------------------------------------------------------------------
(* Unbounded (reactive) actions *)
Reactive ==
    \/ \E p \in Pids : \/ TrspGetAssignCandidate(p)
                       \/ TrspOpen(p)
                       \/ TrspConfirmOpened(p)
                       \/ TrspClose(p)
                       \/ TrspConfirmClosed(p)
                       \/ RrpbDispatch(p)
                       \/ RrpbReportSucceed(p)
                       \/ RrpbDispatchFail(p)
                       \/ RrpbServerCrash(p)
    \/ \E p \in Pids, s \in Servers : AssignQueueAcceptPlan(p, s)
    \/ \E m \in msgs : \/ RsHandleOpen(m)
                       \/ RsHandleClose(m)
                       \/ MasterReportTransition(m)
                       \/ RemoteCallFailed(m, FALSE)
    \/ SmpExecuteEntry
    \/ SplitPrepare
    \/ SplitPreOperation(FALSE)
    \/ SplitCloseParentRegion
    \/ SplitCheckClosedRegions
    \/ SplitCreateDaughterRegions
    \/ SplitUpdateMeta
    \/ SplitAfterMeta
    \/ SplitRollbackStep
    \/ TruncPreOperation
    \/ TruncMakeOffline
    \/ TruncRemove
    \/ TruncMakeOnline
    \/ TruncPostOperation
    \/ BalancerSkipPlan
    \/ DecomNoDestination
    \/ RsgSelect
    \/ RsgNoDestination
    \/ RsgEndRound
    \/ DisableSetDisabling
    \/ CloseTableRegionsSchedule
    \/ CloseTableRegionsConfirm
    \/ DisableSetDisabled
    \/ \E s \in Servers : \/ MasterExpireServer(s)
                          \/ ScpGetRegions(s)
                          \/ ScpFinish(s)
                          \/ \E r \in Regions : ScpAssignRegion(s, r)

MCTargetCheckAny ==
    \E c \in Callers, r \in Regions, op \in Ops, d \in Servers \cup {NoServer} :
        MCTargetCheck(c, r, op, d)

MCNext ==
    /\ ~targetFired
    /\ \/ MCTargetCheckAny
       \/ Reactive /\ UNCHANGED faults
       \/ MCOperatorDisable
       \/ \E r \in Regions : MCSplitSubmit(r)
       \/ MCOperatorAbortSplit
       \/ MCSplitPreOperationFail
       \/ \E r \in Regions : MCOperatorTruncate(r)
       \/ \E r \in Regions, d \in Servers : MCBalancerPlan(r, d)
       \/ \E s \in Servers : MCRsCrash(s)
       \/ MCMasterFailover
       \/ \E s \in Servers : MCOperatorDecommission(s)
       \/ \E s \in Servers : MCOperatorRsgMoveServers(s)
       \/ \E m \in msgs : MCRemoteCallFailedInjected(m)

MCSpec == MCInit /\ [][MCNext]_mcVars

-----------------------------------------------------------------------------
(* Symmetry and properties *)

\* RegionServers are interchangeable; regions are not permuted (DummyRegion placeholders)
Symmetry == Permutations(Servers)

\* the oracle
MCTargetSafe == TargetSafe

\* sanity (adhoc tla-patterns 2): TEMPORARY invariant that TLC must VIOLATE in MC.cfg, showing that
\* the model reaches a state where the code path to AM:769 is taken at all
TargetReached == targetFired \/ ~(ENABLED MCTargetCheckAny)

\* sanity: the PASS branch of the check (workload's unassign at TestRegionMove.java:105 and assign at
\* :113) is taken -- TEMPORARY invariant that TLC must VIOLATE
TargetPassReached == ~(\E p \in Pids : trsp[p].pc # "NONE" /\ trsp[p].parent = NoProc)

\* diagnostic, NOT a hunting target: a step that needs a new procedure id is disabled once MaxPid ids
\* are used, so a "no violation" result only covers behaviours within that budget.  TLC reports this as
\* violated when the budget is used up.  Run it next to a hunt to tell whether MaxPid cut anything: a
\* violation means raise MaxPid, or show the budget went to an unbounded retry loop (TRSP:422-428).
PidBudgetOK == nextPid <= MaxPid

\* bounds every hunt reports
FaultBounds == faults
=============================================================================
