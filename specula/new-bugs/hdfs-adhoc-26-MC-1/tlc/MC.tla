--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking layer for hdfs-adhoc-26.                                 *)
(*                                                                         *)
(* It adds the documented operator procedure, so that fault-free runs are  *)
(* the workload's world, and one bounded counter per Scenario of           *)
(* modeling-brief.md section 2:                                            *)
(*                                                                         *)
(*   HdfsUserGuide.md:304-328 (src/site/markdown, pinned tree):            *)
(*     - finalize an existing backup before upgrading (:309-310);          *)
(*     - stop the cluster, then run with -upgrade (:312-314);              *)
(*     - finalize after the bake (:316-320), or                            *)
(*     - stop the cluster, `hdfs namenode -rollback`, then                 *)
(*       `start-dfs.sh -rollback` (:322-328).                              *)
(*   src/main/bin/start-dfs.sh:68-72: -upgrade goes to the NameNode only,  *)
(*   -rollback to the DataNodes only.                                      *)
(*                                                                         *)
(* opPhase records where the operator is in that procedure:                *)
(*   NORMAL     - no upgrade in progress; DataNodes start REGULAR.         *)
(*   UPGRADED   - the NN runs an unfinalized upgrade (the bake); DataNodes *)
(*                start REGULAR. Ends by finalize (NORMAL) or by an        *)
(*                offline NN rollback (ROLLEDBACK).                        *)
(*   ROLLEDBACK - after the NN rollback; DataNodes start with -rollback.   *)
(*                Ends (NORMAL) once every DataNode completed a -rollback  *)
(*                start, unless a DataNode is out of service (Scenario 1). *)
(*                                                                         *)
(* Counters (each MC_hunt_*.cfg raises only its own):                      *)
(*   MaxUpgrades        operator bound on NN -upgrade starts (not a fault) *)
(*   MaxDNOutages       S1: a DataNode is out of service across a window   *)
(*   MaxVolOutages      S2: a volume is offline at a start, or its BP load *)
(*                      hits a transient fault                             *)
(*   MaxVolReplacements S3: a volume's disk is replaced by an empty one    *)
(*   MaxSwUpgrades      S4: DataNode software with a newer DN layout,      *)
(*                      installed only in NORMAL (procedure, :307-310)     *)
(*   MaxClockSkews      S5: an NN -upgrade stamps a cTime below the        *)
(*                      current one (wall clock stepped back)              *)
(***************************************************************************)
EXTENDS base, TLC

CONSTANTS
    MaxUpgrades,
    MaxDNOutages,
    MaxVolOutages,
    MaxVolReplacements,
    MaxSwUpgrades,
    MaxClockSkews

\* Normal stamps are FormatCT + 2k; a skewed stamp is odd. Every stamp fits.
ASSUME FormatCT % 2 = 0
ASSUME MaxCT >= FormatCT + 2 * MaxUpgrades + 1

VARIABLES
    opPhase,       \* "NORMAL" | "UPGRADED" | "ROLLEDBACK"
    dnRolledBack,  \* the DataNode completed a -rollback start in this ROLLEDBACK phase
    dnOut,         \* S1: the DataNode is out of service and cannot start until repaired
    clock,         \* wall clock for NN -upgrade stamps (FSI:465 now()), steps of 2
    faults         \* counters

mcVars  == <<opPhase, dnRolledBack, dnOut, clock, faults>>
allVars == <<vars, mcVars>>

MCInit ==
    /\ Init
    /\ opPhase = "NORMAL"
    /\ dnRolledBack = [d \in DN |-> FALSE]
    /\ dnOut = [d \in DN |-> FALSE]
    /\ clock = FormatCT + 2
    /\ faults = [upgrades |-> 0, dnOutages |-> 0, volOutages |-> 0,
                 volReplacements |-> 0, swUpgrades |-> 0, clockSkews |-> 0]

AllDNsDown == \A d \in DN : dnPc[d] = "down"

\* start-dfs.sh -rollback passes -rollback to DataNodes (start-dfs.sh:71-72);
\* every other DataNode start is REGULAR (DN:3425, 3451-3455).
DNStartOption == IF opPhase = "ROLLEDBACK" THEN "ROLLBACK" ELSE "REGULAR"

\* Every DataNode either completed a -rollback start or is out of service.
RollbackWindowDone == \A d \in DN : dnRolledBack[d] \/ dnOut[d]

\* S5: a wall-clock step back makes now() smaller than the current cTime.
\* Odd values are never used by unskewed stamps.
SkewStamps == {x \in 1..(nnCur - 1) : x % 2 = 1 /\ x \notin nnHist}

-----------------------------------------------------------------------------
(* Operator: NameNode *)

MCNNStart ==
    /\ ~targetFired
    /\ NNStart
    /\ UNCHANGED mcVars

\* "Stop the cluster" stops the DataNodes first (MiniDFSCluster.shutdown does
\* the same, MiniDFSCluster.java:2201-2205).
MCNNStop ==
    /\ ~targetFired
    /\ AllDNsDown
    /\ NNStop
    /\ UNCHANGED mcVars

MCNNUpgrade ==
    /\ ~targetFired
    /\ AllDNsDown                       \* HdfsUserGuide.md:312 stop the cluster
    /\ opPhase = "NORMAL"               \* :309-310 finalize first; a ROLLEDBACK window closes first
    /\ faults.upgrades < MaxUpgrades
    /\ NNUpgrade(clock)
    /\ clock' = clock + 2
    /\ opPhase' = "UPGRADED"
    /\ faults' = [faults EXCEPT !.upgrades = @ + 1]
    /\ UNCHANGED <<dnRolledBack, dnOut>>

\* S5: the same upgrade start, with the wall clock stepped back below the
\* current cTime. FSI:464-465 stamps it without comparison.
MCNNUpgradeSkewed ==
    /\ ~targetFired
    /\ AllDNsDown
    /\ opPhase = "NORMAL"
    /\ faults.upgrades < MaxUpgrades
    /\ faults.clockSkews < MaxClockSkews
    /\ \E ct \in SkewStamps :
         /\ NNUpgrade(ct)
         /\ clock' = ct + 2             \* the clock goes on from the stepped-back value
    /\ opPhase' = "UPGRADED"
    /\ faults' = [faults EXCEPT !.upgrades = @ + 1, !.clockSkews = @ + 1]
    /\ UNCHANGED <<dnRolledBack, dnOut>>

MCNNRollback ==
    /\ ~targetFired
    /\ AllDNsDown                       \* HdfsUserGuide.md:324 stop the cluster
    /\ opPhase = "UPGRADED"
    /\ NNRollback
    /\ opPhase' = "ROLLEDBACK"
    /\ dnRolledBack' = [d \in DN |-> FALSE]
    /\ UNCHANGED <<dnOut, clock, faults>>

MCNNFinalize ==
    /\ ~targetFired
    /\ opPhase = "UPGRADED"             \* HdfsUserGuide.md:316-320
    /\ NNFinalize
    /\ opPhase' = "NORMAL"
    /\ UNCHANGED <<dnRolledBack, dnOut, clock, faults>>

\* The rollback window closes: from now on DataNodes start REGULAR.
MCCloseRollback ==
    /\ ~targetFired
    /\ opPhase = "ROLLEDBACK"
    /\ RollbackWindowDone
    /\ opPhase' = "NORMAL"
    /\ UNCHANGED <<vars, dnRolledBack, dnOut, clock, faults>>

-----------------------------------------------------------------------------
(* Operator and reactive: DataNodes *)

MCDNStart(d) ==
    /\ ~targetFired
    /\ ~dnOut[d]
    /\ DNStart(d, DNStartOption)
    /\ UNCHANGED mcVars

MCDNStop(d) == ~targetFired /\ DNStop(d) /\ UNCHANGED mcVars
\* Every DN-level dir loads: DN-level storage is not modeled (brief 3.2).
MCDNHandshake(d) == ~targetFired /\ DNHandshake(d, PendingSet(d)) /\ UNCHANGED mcVars
MCTargetCheck(d, v) == ~targetFired /\ TargetCheck(d, v) /\ UNCHANGED mcVars
MCDNLoadVolume(d, v) == ~targetFired /\ DNLoadVolume(d, v) /\ UNCHANGED mcVars
MCDNUpgradeContinuation(d, v) == ~targetFired /\ DNUpgradeContinuation(d, v) /\ UNCHANGED mcVars
MCDNInitDone(d) == ~targetFired /\ DNInitDone(d) /\ UNCHANGED mcVars
MCDNReRegister(d) == ~targetFired /\ DNReRegister(d) /\ UNCHANGED mcVars
MCDNFinalize(d) == ~targetFired /\ DNFinalize(d) /\ UNCHANGED mcVars
MCHotSwapAdd(d, v) == ~targetFired /\ HotSwapAdd(d, v) /\ UNCHANGED mcVars
MCVolRestore(d, v) == ~targetFired /\ VolRestore(d, v) /\ UNCHANGED mcVars

\* A DataNode that registers after a -rollback start in the ROLLEDBACK phase
\* has completed its part of `start-dfs.sh -rollback`.
MCDNRegister(d) ==
    /\ ~targetFired
    /\ DNRegister(d)
    /\ dnRolledBack' =
         IF opPhase = "ROLLEDBACK" /\ dnOpt[d] = "ROLLBACK" /\ dnRegCT[d] = nnCur
         THEN [dnRolledBack EXCEPT ![d] = TRUE]
         ELSE dnRolledBack
    /\ UNCHANGED <<opPhase, dnOut, clock, faults>>

-----------------------------------------------------------------------------
(* Faults, one counter per Scenario *)

\* S1: the DataNode (down) goes out of service: hardware failure, or held
\* down for repair. The operator can close a rollback window without it.
MCDNOutage(d) ==
    /\ ~targetFired
    /\ faults.dnOutages < MaxDNOutages
    /\ dnPc[d] = "down"
    /\ ~dnOut[d]
    /\ dnOut' = [dnOut EXCEPT ![d] = TRUE]
    /\ faults' = [faults EXCEPT !.dnOutages = @ + 1]
    /\ UNCHANGED <<vars, opPhase, dnRolledBack, clock>>

\* S1: the DataNode is repaired; it starts later with the then-current option.
MCDNRepair(d) ==
    /\ ~targetFired
    /\ dnOut[d]
    /\ dnOut' = [dnOut EXCEPT ![d] = FALSE]
    /\ UNCHANGED <<vars, opPhase, dnRolledBack, clock, faults>>

\* S2: a volume is offline at the next DataNode start.
MCVolOutage(d, v) ==
    /\ ~targetFired
    /\ faults.volOutages < MaxVolOutages
    /\ VolOutage(d, v)
    /\ faults' = [faults EXCEPT !.volOutages = @ + 1]
    /\ UNCHANGED <<opPhase, dnRolledBack, dnOut, clock>>

\* S2 (variant): the next BP load of a volume fails transiently.
MCVolBpFault(d, v) ==
    /\ ~targetFired
    /\ faults.volOutages < MaxVolOutages
    /\ VolBpFault(d, v)
    /\ faults' = [faults EXCEPT !.volOutages = @ + 1]
    /\ UNCHANGED <<opPhase, dnRolledBack, dnOut, clock>>

\* S3: a volume's disk is replaced by an empty one.
MCVolReplace(d, v) ==
    /\ ~targetFired
    /\ faults.volReplacements < MaxVolReplacements
    /\ VolReplace(d, v)
    /\ faults' = [faults EXCEPT !.volReplacements = @ + 1]
    /\ UNCHANGED <<opPhase, dnRolledBack, dnOut, clock>>

\* S4: DataNode software with a newer DN layout version. Installing software
\* is an operator step of the documented procedure, so it happens only with no
\* backup and no rollback in progress: "Before upgrading Hadoop software,
\* finalize if there an existing backup" (HdfsUserGuide.md:307-310), and a
\* rollback distributes the earlier version (:322-324). Phase 3 Case B: a
\* software upgrade during UPGRADED reached TargetSafe only through that
\* procedure violation (changelog.md, Bug Hunting).
MCDNSoftwareUpgrade(d) ==
    /\ ~targetFired
    /\ opPhase = "NORMAL"
    /\ faults.swUpgrades < MaxSwUpgrades
    /\ DNSoftwareUpgrade(d)
    /\ faults' = [faults EXCEPT !.swUpgrades = @ + 1]
    /\ UNCHANGED <<opPhase, dnRolledBack, dnOut, clock>>

-----------------------------------------------------------------------------
\* Every MC wrapper starts with ~targetFired: once the target fired, nothing
\* else is explored (adhoc tla-patterns 1). MCNext stays a plain disjunction
\* so TLC names each step by its action.
MCNext ==
       \/ MCNNStart
       \/ MCNNStop
       \/ MCNNUpgrade
       \/ MCNNUpgradeSkewed
       \/ MCNNRollback
       \/ MCNNFinalize
       \/ MCCloseRollback
       \/ \E d \in DN :
            \/ MCDNStart(d)
            \/ MCDNHandshake(d)
            \/ MCDNInitDone(d)
            \/ MCDNRegister(d)
            \/ MCDNReRegister(d)
            \/ MCDNFinalize(d)
            \/ MCDNStop(d)
            \/ MCDNOutage(d)
            \/ MCDNRepair(d)
            \/ MCDNSoftwareUpgrade(d)
            \/ \E v \in Vol :
                 \/ MCTargetCheck(d, v)
                 \/ MCDNLoadVolume(d, v)
                 \/ MCDNUpgradeContinuation(d, v)
                 \/ MCHotSwapAdd(d, v)
                 \/ MCVolOutage(d, v)
                 \/ MCVolRestore(d, v)
                 \/ MCVolBpFault(d, v)
                 \/ MCVolReplace(d, v)

MCSpec == MCInit /\ [][MCNext]_allVars

-----------------------------------------------------------------------------
(* Properties *)

\* TargetSafe, TypeOK and VolumeCTimesFromNN come from base.

\* MC-level domains (structural).
MCTypeOK ==
    /\ TypeOK
    /\ opPhase \in {"NORMAL", "UPGRADED", "ROLLEDBACK"}
    /\ dnRolledBack \in [DN -> BOOLEAN]
    /\ dnOut \in [DN -> BOOLEAN]
    /\ clock \in 1..(MaxCT + 2)
    /\ faults.upgrades <= MaxUpgrades
    /\ faults.dnOutages <= MaxDNOutages
    /\ faults.volOutages <= MaxVolOutages
    /\ faults.volReplacements <= MaxVolReplacements
    /\ faults.swUpgrades <= MaxSwUpgrades
    /\ faults.clockSkews <= MaxClockSkews

\* Non-vacuity probe (adhoc tla-patterns 2), used only by MC_probe_reach.cfg:
\* TLC must VIOLATE it, showing that the guard at BPSS:618-620 is evaluated.
TargetReached == ~(\E d \in DN, v \in Vol : TargetGuardEvaluated(d, v))

\* Mechanism probes, one per hunt config (MC_probe_S<n>.cfg uses the bounds
\* of MC_hunt_S<n>_*.cfg). TLC must VIOLATE each: the Scenario's fault setup
\* reaches its distinctive state. They say nothing about TargetSafe.

\* S1: a rollback window closed while the DataNode was out of service; its
\* volume still holds the abandoned epoch's cTime (newer than the NameNode's).
ProbeS1 == ~(\E d \in DN, v \in Vol :
               /\ dnOut[d] /\ opPhase = "NORMAL" /\ nnPrev = NoCT
               /\ volCur[d][v].ct > nnCur)

\* S2: the DataNode completed a -rollback start and runs, while one of its
\* volumes missed that start and still holds a newer cTime.
ProbeS2 == ~(\E d \in DN, v \in Vol :
               /\ dnPc[d] = "running" /\ dnOpt[d] = "ROLLBACK"
               /\ volLoad[d][v] /= "bp" /\ volCur[d][v].ct > nnCur)

\* S3: a volume formatted inside the abandoned epoch (no previous, newer
\* cTime) survives the closed rollback window.
ProbeS3 == ~(\E d \in DN, v \in Vol :
               /\ opPhase = "NORMAL" /\ nnPrev = NoCT
               /\ volPrev[d][v] = NoVer /\ volCur[d][v].ct > nnCur)

\* S4: re-snapshot inside one epoch: previous = (old LV, c), current = (new LV, c).
ProbeS4 == ~(\E d \in DN, v \in Vol :
               /\ volPrev[d][v] /= NoVer
               /\ volPrev[d][v].ct = volCur[d][v].ct
               /\ volPrev[d][v].lv /= volCur[d][v].lv)

\* S5: the NameNode's cTime regressed through an upgrade (current < previous).
ProbeS5 == ~(nnPrev /= NoCT /\ nnCur < nnPrev)

=============================================================================
