--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model checking wrapper for hdfs-adhoc-37 (DataStorage.java L942).       *)
(*                                                                         *)
(* Operator actions (bounded): NameNode -upgrade, -rollback, DataNode      *)
(* starts. Faults (bounded, one counter per mechanism, brief Section 2):   *)
(*   Scenario 1  MaxClockSkew        a NameNode stamp from a clock that    *)
(*                                   reads earlier (value in SkewCT)       *)
(*   Scenario 2  MaxDirLoadFail      transient I/O failure of one location *)
(*               MaxSkipRebootstrap  HA peer restarted without             *)
(*                                   -bootstrapStandby                     *)
(*   Scenario 3  MaxDnCrash          DataNode crash at an arbitrary step   *)
(*               MaxRace             caller rewrites the shared DataStorage*)
(*                                   fields while an upgrade callable has  *)
(*                                   not written its VERSION yet           *)
(*                                   (RaceGate), or a callable's DS:874    *)
(*                                   lands inside the caller's read        *)
(*                                   (DnReadPropertiesRaced)               *)
(*   fixtures    MaxFixture          the workload's operand write; 0 in    *)
(*                                   every MC and hunt config              *)
(* Not bounded (reactive): handshakes, storage-load steps, callables,      *)
(* block-pool loads, init completion and retry, FinalizeCommand, NameNode  *)
(* start, finalize and bootstrap, clean DataNode stop.                     *)
(*                                                                         *)
(* Every step has a named wrapper so TLC labels counterexample steps; the  *)
(* stop-after-target rule is a CONSTRAINT (StopAfterTarget), not a Next    *)
(* conjunct (the trace spec must continue after the workload's own fire).  *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxNnUpgrade,        \* NameNode -upgrade starts
    MaxNnRollback,       \* successful NameNode -rollback runs
    MaxDnStart,          \* DataNode process starts (-regular or -rollback)
    MaxClockSkew,        \* Scenario 1: stamps from a clock behind
    SkewCT,              \* the values such a stamp may take
    MaxDirLoadFail,      \* Scenario 2: transient location load failures
    MaxSkipRebootstrap,  \* Scenario 2: HA peer not re-bootstrapped
    MaxDnCrash,          \* Scenario 3: DataNode crashes mid-step
    MaxRace,             \* Scenario 3: racy shared-field writes
    MaxFixture           \* workload fixture writes (0 = none)

ASSUME /\ {MaxNnUpgrade, MaxNnRollback, MaxDnStart, MaxClockSkew, MaxDirLoadFail,
           MaxSkipRebootstrap, MaxDnCrash, MaxRace, MaxFixture} \subseteq Nat
       /\ SkewCT \subseteq CTv
       \* every normal stamp (formats of namespace 2 and upgrades) stays in 0..MaxCT
       /\ FirstStamp + MaxNnUpgrade + Cardinality(Ns2NN) <= MaxCT + 1

VARIABLE fc     \* fault and operator counters

mc_vars == <<vars, fc>>

FcInit == [nnUpg |-> 0, nnRb |-> 0, dnStart |-> 0, skew |-> 0, ioFail |-> 0,
           noReboot |-> 0, crash |-> 0, race |-> 0, fixture |-> 0]

Inc(k) == fc' = [fc EXCEPT ![k] = @ + 1]

----------------------------------------------------------------------------
\* NameNode operator actions. A normal stamp is the current clock reading
\* (any later reading is order-equivalent); a skewed one is a value of SkewCT.

MCNnFormat(n) ==
    /\ NnFormat(n, clock)
    /\ UNCHANGED fc

MCNnFormatSkew(n, st) ==
    /\ fc.skew < MaxClockSkew
    /\ NnFormat(n, st)
    /\ Inc("skew")

MCNnStart(n) == NnStart(n) /\ UNCHANGED fc

\* A NameNode is stopped only to be upgraded or rolled back (NnUpgrade and
\* NnRollback need it down); the budget of those actions bounds the stops.
\* Only an active NameNode is upgraded (NnUpgrade); a rollback needs a
\* previous/ it can roll back to.
MCNnStop(n) ==
    /\ n \in ActiveNN
    /\ \/ fc.nnUpg < MaxNnUpgrade
       \/ fc.nnRb < MaxNnRollback /\ CanRollBack(n)
    /\ NnStop(n)
    /\ UNCHANGED fc

MCNnUpgrade(n) ==
    /\ fc.nnUpg < MaxNnUpgrade
    /\ NnUpgrade(n, clock, TRUE)
    /\ Inc("nnUpg")

MCNnUpgradeSkew(n, st) ==
    /\ fc.nnUpg < MaxNnUpgrade
    /\ fc.skew < MaxClockSkew
    /\ NnUpgrade(n, st, TRUE)
    /\ fc' = [fc EXCEPT !.nnUpg = @ + 1, !.skew = @ + 1]

MCNnUpgradeNoReboot(n) ==
    /\ Peers(n) # {}
    /\ fc.nnUpg < MaxNnUpgrade
    /\ fc.noReboot < MaxSkipRebootstrap
    /\ NnUpgrade(n, clock, FALSE)
    /\ fc' = [fc EXCEPT !.nnUpg = @ + 1, !.noReboot = @ + 1]

\* Only a rollback that succeeds is worth a budget unit (a failed one changes
\* nothing).
MCNnRollback(n) ==
    /\ CanRollBack(n)
    /\ fc.nnRb < MaxNnRollback
    /\ NnRollback(n, TRUE)
    /\ Inc("nnRb")

MCNnRollbackNoReboot(n) ==
    /\ Peers(n) # {}
    /\ CanRollBack(n)
    /\ fc.nnRb < MaxNnRollback
    /\ fc.noReboot < MaxSkipRebootstrap
    /\ NnRollback(n, FALSE)
    /\ fc' = [fc EXCEPT !.nnRb = @ + 1, !.noReboot = @ + 1]

MCNnFinalize(n) == NnFinalize(n) /\ UNCHANGED fc

MCNnBootstrapStandby(n, m) == NnBootstrapStandby(n, m) /\ UNCHANGED fc

----------------------------------------------------------------------------
\* DataNode process.

MCDnStart(o) ==
    /\ fc.dnStart < MaxDnStart
    /\ DnStart(o, DirSeq)
    /\ Inc("dnStart")

MCDnStop == DnStop /\ UNCHANGED fc

\* A crash while nothing is in flight equals a clean stop; count only the
\* crashes that interrupt a storage load or an upgrade callable.
MCDnCrash ==
    /\ fc.crash < MaxDnCrash
    /\ ld.busy \/ \E d \in Dir : cb[d] # "none"
    /\ DnCrash
    /\ Inc("crash")

----------------------------------------------------------------------------
\* The shared-field race (Scenario 3): a caller step that changes the shared
\* DataStorage fields while some upgrade callable has not yet written its
\* VERSION (DS:860-875 against DS:574-577, 628-633, 729, 299). With
\* MaxRace = 0 the caller waits for the callables' VERSION writes first.

CallableInWindow == \E d \in Dir : cb[d] \in {"sub", "set"}

RaceGate ==
    IF CallableInWindow /\ sh' # sh
    THEN /\ fc.race < MaxRace
         /\ Inc("race")
    ELSE UNCHANGED fc

MCDnAnalyze            == DnAnalyze /\ RaceGate
MCDnRollbackNoPrevious == DnRollbackNoPrevious /\ RaceGate
MCDnReadProperties     == DnReadProperties /\ RaceGate

\* A callable's DS:874 landing inside the caller's read is always a race.
MCDnReadPropertiesRaced(c, o) ==
    /\ fc.race < MaxRace
    /\ DnReadPropertiesRaced(c, o)
    /\ Inc("race")

MCDnLoadIoFail ==
    /\ fc.ioFail < MaxDirLoadFail
    /\ DnLoadIoFail
    /\ Inc("ioFail")

----------------------------------------------------------------------------
\* Reactive steps (unbounded), named so counterexamples keep their labels.

MCHandshake(n)          == Handshake(n)          /\ UNCHANGED fc
MCInitStart(n)          == InitStart(n)          /\ UNCHANGED fc
MCHsJoin(n)             == HsJoin(n)             /\ UNCHANGED fc
MCActorRetryOrExit(n)   == ActorRetryOrExit(n)   /\ UNCHANGED fc
MCTargetCheck           == TargetCheck           /\ UNCHANGED fc
MCDnRollbackRenameCurrent  == DnRollbackRenameCurrent  /\ UNCHANGED fc
MCDnRollbackRenamePrevious == DnRollbackRenamePrevious /\ UNCHANGED fc
MCDnRollbackDeleteTmp      == DnRollbackDeleteTmp      /\ UNCHANGED fc
MCDnPreFedDeletePrevious   == DnPreFedDeletePrevious   /\ UNCHANGED fc
MCDnPreFedRename           == DnPreFedRename           /\ UNCHANGED fc
MCCbUpgradeFields(d)    == CbUpgradeFields(d)    /\ UNCHANGED fc
MCCbWriteVersion(d)     == CbWriteVersion(d)     /\ UNCHANGED fc
MCCbRenamePrevTmp(d)    == CbRenamePrevTmp(d)    /\ UNCHANGED fc
MCDnAddUpgraded(d)      == DnAddUpgraded(d)      /\ UNCHANGED fc
MCBpLoad(d)             == BpLoad(d)             /\ UNCHANGED fc
MCDnLoadDone            == DnLoadDone            /\ UNCHANGED fc
MCInitFinish(n)         == InitFinish(n)         /\ UNCHANGED fc
MCDnFinalizeDir(n, d)   == DnFinalizeDir(n, d)   /\ UNCHANGED fc

----------------------------------------------------------------------------
\* The workload's operand write (TestDFSRollback L282-289: previous/VERSION
\* with a chosen cTime). Only MC_sanity_fixture.cfg enables it.
MCFixturePrevVersion(d, ct) ==
    /\ fc.fixture < MaxFixture
    /\ dPrev[d].ver # NoVer
    /\ FixtureDnVersion(d, "previous", MkVer("pinned", ct, TRUE), ct)
    /\ Inc("fixture")

----------------------------------------------------------------------------

MCInit ==
    /\ Init
    /\ fc = FcInit

MCNext ==
    \/ \E n \in NN : MCNnFormat(n)
    \/ \E n \in NN, st \in SkewCT : MCNnFormatSkew(n, st)
    \/ \E n \in NN : MCNnStart(n)
    \/ \E n \in NN : MCNnStop(n)
    \/ \E n \in NN : MCNnUpgrade(n)
    \/ \E n \in NN, st \in SkewCT : MCNnUpgradeSkew(n, st)
    \/ \E n \in NN : MCNnUpgradeNoReboot(n)
    \/ \E n \in NN : MCNnRollback(n)
    \/ \E n \in NN : MCNnRollbackNoReboot(n)
    \/ \E n \in NN : MCNnFinalize(n)
    \/ \E n, m \in NN : MCNnBootstrapStandby(n, m)
    \/ \E o \in OptT : MCDnStart(o)
    \/ MCDnStop
    \/ MCDnCrash
    \/ \E n \in NN : MCHandshake(n)
    \/ \E n \in NN : MCInitStart(n)
    \/ \E n \in NN : MCHsJoin(n)
    \/ \E n \in NN : MCActorRetryOrExit(n)
    \/ MCDnAnalyze
    \/ MCDnLoadIoFail
    \/ MCDnRollbackNoPrevious
    \/ MCTargetCheck
    \/ MCDnRollbackRenameCurrent
    \/ MCDnRollbackRenamePrevious
    \/ MCDnRollbackDeleteTmp
    \/ MCDnReadProperties
    \/ \E c \in Dir, o \in {"fail", "relabel"} : MCDnReadPropertiesRaced(c, o)
    \/ MCDnPreFedDeletePrevious
    \/ MCDnPreFedRename
    \/ \E d \in Dir : MCCbUpgradeFields(d)
    \/ \E d \in Dir : MCCbWriteVersion(d)
    \/ \E d \in Dir : MCCbRenamePrevTmp(d)
    \/ \E d \in Dir : MCDnAddUpgraded(d)
    \/ \E d \in Dir : MCBpLoad(d)
    \/ MCDnLoadDone
    \/ \E n \in NN : MCInitFinish(n)
    \/ \E n \in NN, d \in Dir : MCDnFinalizeDir(n, d)
    \/ \E d \in Dir, ct \in CTv : MCFixturePrevVersion(d, ct)

MCSpec == MCInit /\ [][MCNext]_mc_vars

----------------------------------------------------------------------------
\* Stop exploring once the target fired (TLC still checks the invariants of
\* the first state that violates the constraint).
StopAfterTarget == ~targetFired

\* Sanity (adhoc tla-patterns Section 2): expected to be VIOLATED, which
\* shows that some explored state enables TargetCheck (the loader is at the
\* rollback step of a location that has a previous/ under -rollback).
TargetReached == ~(LoaderAt("trans") /\ startOpt = "ROLLBACK" /\ dPrev[ld.d].ver # NoVer)

\* Counters stay within their bounds (structural).
CountersOK ==
    /\ fc.nnUpg <= MaxNnUpgrade /\ fc.nnRb <= MaxNnRollback
    /\ fc.dnStart <= MaxDnStart /\ fc.skew <= MaxClockSkew
    /\ fc.ioFail <= MaxDirLoadFail /\ fc.noReboot <= MaxSkipRebootstrap
    /\ fc.crash <= MaxDnCrash /\ fc.race <= MaxRace /\ fc.fixture <= MaxFixture

----------------------------------------------------------------------------
\* Diagnostics for Phase 3 (NOT hunt targets; enable only in diagnostic
\* configs). Together they imply TargetSafe: the guard fires iff
\* prev.cTime > nsInfo.cTime (SI:220 rejects the LV half).
\*  - every DataNode-level snapshot holds a DataNode-level cTime (a legacy
\*    one, or 0 from DataStorage.format, DS:577): no DataNode code writes a
\*    NameNode cTime into a DataNode-level VERSION;
\*  - every nsInfo the loader uses is a pinned-era stamp (above every
\*    legacy cTime), unless a stamp came from a skewed clock.
\* DataNode-level cTimes: the legacy VERSION files and DataStorage.format's 0.
DnLevelCTs == {DirCtA, DirCtB, 0} \cup
              (IF InitPrevDirs = {} THEN {} ELSE {InitPrevCt})
\* Every legacy-era value, including the legacy NameNode cTime.
LegacyCTs == DnLevelCTs \cup {InitNnCt}
MaxLegacyCt == CHOOSE c \in LegacyCTs : \A x \in LegacyCTs : x <= c

DiagPrevCtLegacy ==
    \A d \in Dir : dPrev[d].ver # NoVer => dPrev[d].ver.ct \in DnLevelCTs

DiagNsCtPinnedEra ==
    ld.busy => ld.ct > MaxLegacyCt

=============================================================================
