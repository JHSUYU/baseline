-------------------------------- MODULE MC --------------------------------
(*
 * Model checking wrapper for base (hdfs-adhoc-k6).
 * Counter-bounds every action that introduces non-determinism (workload
 * requests, journal faults, admin actions, lifecycle events). Reactive steps
 * (RollAcquire, TargetCheck, EndSegment*, StartSegment, SyncThreadRun, StopRpc,
 * FsnClose) are unbounded.
 *)
EXTENDS base, TLC

CONSTANTS
    MaxRpcRolls,        \* rollEditLog / rollEdits / startCheckpoint arrivals
    MaxRollerChecks,    \* roller threshold checks that pass
    MaxClientEdits,     \* namespace mutations (mkdirs/delete)
    MaxJournalFaults,   \* storage I/O faults
    MaxJournalRepairs,  \* faults clearing
    MaxSafeModeEnters,  \* dfsadmin -safemode enter / resource-low
    MaxSafeModeLeaves,  \* dfsadmin -safemode leave
    MaxSaveNamespace,   \* dfsadmin -saveNamespace
    MaxStops,           \* NameNode.stop
    MaxStandby          \* HA transitionToStandby

VARIABLE cnt

mcVars == <<vars, cnt>>

CntInit == [rpcRoll |-> 0, rollerCheck |-> 0, clientEdit |-> 0, jFault |-> 0,
            jRepair |-> 0, smEnter |-> 0, smLeave |-> 0, saveNs |-> 0,
            stop |-> 0, standby |-> 0]

MCInit == Init /\ cnt = CntInit

Bump(k, max) == /\ cnt[k] < max
                /\ cnt' = [cnt EXCEPT ![k] = @ + 1]

MCRpcRollArrive       == RpcRollArrive /\ Bump("rpcRoll", MaxRpcRolls)
MCRollerCheck         == RollerCheck /\ Bump("rollerCheck", MaxRollerChecks)
MCClientEdit          == ClientEdit /\ Bump("clientEdit", MaxClientEdits)
MCJournalFault(j)     == JournalFault(j) /\ Bump("jFault", MaxJournalFaults)
MCJournalRepair(j)    == JournalRepair(j) /\ Bump("jRepair", MaxJournalRepairs)
MCEnterSafeMode       == EnterSafeMode /\ Bump("smEnter", MaxSafeModeEnters)
MCLeaveSafeMode       == LeaveSafeMode /\ Bump("smLeave", MaxSafeModeLeaves)
MCSaveNamespaceBegin  == SaveNamespaceBegin /\ Bump("saveNs", MaxSaveNamespace)
MCStopExitState       == StopExitState /\ Bump("stop", MaxStops)
MCTransitionToStandby == TransitionToStandby /\ Bump("standby", MaxStandby)

MCNext ==
    /\ ~targetFired
    /\ ~halted
    /\ \/ MCRpcRollArrive
       \/ MCRollerCheck
       \/ MCClientEdit
       \/ \E j \in Journal : MCJournalFault(j)
       \/ \E j \in Journal : MCJournalRepair(j)
       \/ MCEnterSafeMode
       \/ MCLeaveSafeMode
       \/ MCSaveNamespaceBegin
       \/ MCStopExitState
       \/ MCTransitionToStandby
       \* reactive, unbounded
       \/ /\ \/ \E a \in RollActor : RollAcquire(a)
             \/ \E a \in Actor : TargetCheck(a)
             \/ \E a \in Actor : EndSegmentSync(a)
             \/ \E a \in Actor : EndSegmentFinalize(a)
             \/ \E a \in Actor : StartSegment(a)
             \/ SyncThreadRun
             \/ StopRpc
             \/ FsnClose
          /\ UNCHANGED cnt

MCSpec == MCInit /\ [][MCNext]_mcVars

\* ---------------------------------------------------------------------------
\* Hunting probes (Phase 3). Each is TargetSafe restricted to one sub-path of a
\* Scenario; TLC violating it shows that sub-path reaches FSEditLog.java:1409.
\* S1, clean finalize: the segment was finalized (editLogStream = null) and only
\* the restart failed.
ProbeS1CleanFinalize == ~(targetFired /\ ~streamOpen)
\* S1, saveNamespace's finally restart stranded the log; the only RPC roll is the
\* one that hits the check.
ProbeS1SaveNs == ~(targetFired /\ cnt["saveNs"] = 1 /\ cnt["rpcRoll"] = 1)
\* S2, the roller thread (already blocked in writeLock) hits the check.
ProbeS2Roller == ~(targetFired /\ pc["roller"] = "atCheck")

=============================================================================
