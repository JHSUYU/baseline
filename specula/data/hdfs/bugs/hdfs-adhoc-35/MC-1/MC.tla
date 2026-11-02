--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model-checking wrapper for base (hdfs-adhoc-35, DataStorage.java:750).  *)
(*                                                                         *)
(* Counters bound the steps that introduce nondeterminism from outside the *)
(* DataNode's own control flow:                                            *)
(*   diskFail  - VolumeIOFailure, LinkBlocksFailure (volume I/O errors)     *)
(*   hotSwap   - RefreshVolumes (operator reconfiguration batches)         *)
(*   restart   - DataNodeShutdown (process stop; a later start is free)    *)
(*   interrupt - InitBlockPoolInterrupted (actor stopped during the init)  *)
(*   bpssFail  - block-pool slice load failures (one per failed location)  *)
(* Every other step (loader steps, main-loop control, joins, init outcome, *)
(* DataNodeStart, InitBlockPoolRetry) is reactive and unbounded.            *)
(*                                                                         *)
(* Each MCNext disjunct is a named wrapper so counterexample steps carry   *)
(* action names; the stop-after-target rule is a CONSTRAINT                *)
(* (StopAfterTarget), not a conjunct of MCNext.                            *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxDiskFail,
    MaxHotSwapBatches,
    MaxDnRestarts,
    MaxInitInterrupts,
    MaxBpssFail

VARIABLE fc

mcVars == <<vars, fc>>

FcZero == [diskFail |-> 0, hotSwap |-> 0, restart |-> 0, interrupt |-> 0, bpssFail |-> 0]

MCInit == Init /\ fc = FcZero

(***************************************************************************)
(* Fault-counted wrappers                                                  *)
(***************************************************************************)
MCVolumeIOFailure(w) ==
    /\ fc.diskFail < MaxDiskFail
    /\ VolumeIOFailure(w)
    /\ fc' = [fc EXCEPT !.diskFail = @ + 1]

MCLinkBlocksFailure(w) ==
    /\ fc.diskFail < MaxDiskFail
    /\ LinkBlocksFailure(w)
    /\ fc' = [fc EXCEPT !.diskFail = @ + 1]

MCRefreshVolumes(S, ns) ==
    /\ fc.hotSwap < MaxHotSwapBatches
    /\ RefreshVolumes(S, ns)
    /\ fc' = [fc EXCEPT !.hotSwap = @ + 1]

MCDataNodeShutdown ==
    /\ fc.restart < MaxDnRestarts
    /\ DataNodeShutdown
    /\ fc' = [fc EXCEPT !.restart = @ + 1]

MCInitBlockPoolInterrupted ==
    /\ fc.interrupt < MaxInitInterrupts
    /\ InitBlockPoolInterrupted
    /\ fc' = [fc EXCEPT !.interrupt = @ + 1]

MCLoadBlockPoolSliceStorage(F) ==
    /\ fc.bpssFail + Cardinality(F) <= MaxBpssFail
    /\ LoadBlockPoolSliceStorage(F)
    /\ fc' = [fc EXCEPT !.bpssFail = @ + Cardinality(F)]

MCAddVolumeBuild(x, ok) ==
    /\ ok \/ fc.bpssFail < MaxBpssFail
    /\ AddVolumeBuild(x, ok)
    /\ fc' = IF ok THEN fc ELSE [fc EXCEPT !.bpssFail = @ + 1]

(***************************************************************************)
(* Reactive wrappers (unbounded)                                           *)
(***************************************************************************)
MCDataNodeStart              == DataNodeStart /\ UNCHANGED fc
MCLoadDataStorageNext(x)     == LoadDataStorageNext(x) /\ UNCHANGED fc
MCLoadDataStorageEndLoop     == LoadDataStorageEndLoop /\ UNCHANGED fc
MCLoadDataStorageJoin(x)     == LoadDataStorageJoin(x) /\ UNCHANGED fc
MCCheckDatanodeUuid          == CheckDatanodeUuid /\ UNCHANGED fc
MCInitFsDataset              == InitFsDataset /\ UNCHANGED fc
MCInitBlockPoolRetry         == InitBlockPoolRetry /\ UNCHANGED fc

MCAnalyzeStorage(w)    == AnalyzeStorage(w) /\ UNCHANGED fc
MCFormatLV(w)          == FormatLV(w) /\ UNCHANGED fc
MCFormatCID(w)         == FormatCID(w) /\ UNCHANGED fc
MCFormatWrite(w)       == FormatWrite(w) /\ UNCHANGED fc
MCRollbackRestore(w)   == RollbackRestore(w) /\ UNCHANGED fc
MCRollbackReadLV(w)    == RollbackReadLV(w) /\ UNCHANGED fc
MCRollbackReadCID(w)   == RollbackReadCID(w) /\ UNCHANGED fc
MCRollbackReadNSID(w)  == RollbackReadNSID(w) /\ UNCHANGED fc
MCRollbackWrite(w)     == RollbackWrite(w) /\ UNCHANGED fc
MCReadLV(w)            == ReadLV(w) /\ UNCHANGED fc
MCReadCID(w)           == ReadCID(w) /\ UNCHANGED fc
MCReadNSID(w)          == ReadNSID(w) /\ UNCHANGED fc
MCTransitionFed(w)     == TransitionFed(w) /\ UNCHANGED fc
MCNamespaceCheck(w)    == NamespaceCheck(w) /\ UNCHANGED fc
MCTargetCheck(w)       == TargetCheck(w) /\ UNCHANGED fc
MCRegularBranch(w)     == RegularBranch(w) /\ UNCHANGED fc
MCUpgradeBranch(w)     == UpgradeBranch(w) /\ UNCHANGED fc
MCServiceLV(w)         == ServiceLV(w) /\ UNCHANGED fc
MCWriteLoaded(w)       == WriteLoaded(w) /\ UNCHANGED fc
MCDoUpgradeCID(w)      == DoUpgradeCID(w) /\ UNCHANGED fc
MCDoUpgradeLV(w)       == DoUpgradeLV(w) /\ UNCHANGED fc
MCDoUpgradeWrite(w)    == DoUpgradeWrite(w) /\ UNCHANGED fc
MCUpgradePropsLV(w)    == UpgradePropsLV(w) /\ UNCHANGED fc
MCUpgradePropsWrite(w) == UpgradePropsWrite(w) /\ UNCHANGED fc

MCNext ==
    \/ MCDataNodeStart
    \/ MCDataNodeShutdown
    \/ \E x \in Loc : MCLoadDataStorageNext(x)
    \/ MCLoadDataStorageEndLoop
    \/ \E x \in Loc : MCLoadDataStorageJoin(x)
    \/ \E F \in SUBSET Loc : MCLoadBlockPoolSliceStorage(F)
    \/ MCCheckDatanodeUuid
    \/ MCInitFsDataset
    \/ MCInitBlockPoolInterrupted
    \/ MCInitBlockPoolRetry
    \/ \E S \in SUBSET SwapCands, ns \in HsNsChoices : MCRefreshVolumes(S, ns)
    \/ \E x \in Loc, ok \in BOOLEAN : MCAddVolumeBuild(x, ok)
    \/ \E w \in LdIds : MCAnalyzeStorage(w)
    \/ \E w \in LdIds : MCFormatLV(w)
    \/ \E w \in LdIds : MCFormatCID(w)
    \/ \E w \in LdIds : MCFormatWrite(w)
    \/ \E w \in LdIds : MCRollbackRestore(w)
    \/ \E w \in LdIds : MCRollbackReadLV(w)
    \/ \E w \in LdIds : MCRollbackReadCID(w)
    \/ \E w \in LdIds : MCRollbackReadNSID(w)
    \/ \E w \in LdIds : MCRollbackWrite(w)
    \/ \E w \in LdIds : MCReadLV(w)
    \/ \E w \in LdIds : MCReadCID(w)
    \/ \E w \in LdIds : MCReadNSID(w)
    \/ \E w \in LdIds : MCTransitionFed(w)
    \/ \E w \in LdIds : MCNamespaceCheck(w)
    \/ \E w \in LdIds : MCTargetCheck(w)
    \/ \E w \in LdIds : MCRegularBranch(w)
    \/ \E w \in LdIds : MCUpgradeBranch(w)
    \/ \E w \in LdIds : MCServiceLV(w)
    \/ \E w \in LdIds : MCWriteLoaded(w)
    \/ \E w \in LdIds : MCDoUpgradeCID(w)
    \/ \E w \in LdIds : MCDoUpgradeLV(w)
    \/ \E w \in LdIds : MCDoUpgradeWrite(w)
    \/ \E w \in LdIds : MCUpgradePropsLV(w)
    \/ \E w \in LdIds : MCUpgradePropsWrite(w)
    \/ \E w \in LdIds : MCVolumeIOFailure(w)
    \/ \E w \in LdIds : MCLinkBlocksFailure(w)

MCSpec == MCInit /\ [][MCNext]_mcVars

(***************************************************************************)
(* Invariants and constraints                                              *)
(***************************************************************************)
MCTypeOK ==
    /\ TypeOK
    /\ fc \in [diskFail : 0..MaxDiskFail, hotSwap : 0..MaxHotSwapBatches,
               restart : 0..MaxDnRestarts, interrupt : 0..MaxInitInterrupts,
               bpssFail : 0..MaxBpssFail]

\* Stop exploring once the target fired (TLC still checks invariants on that state).
StopAfterTarget == ~targetFired

(***************************************************************************)
(* Diagnostics for route isolation (Phase 3).  Not hunting invariants:     *)
(* use them in MC_diag_*.cfg with TargetSafe removed.                      *)
(***************************************************************************)
\* violated iff the target fires in a load of a directory whose VERSION has a
\* federation layout (variant I-3: the victim skipped its own cid read)
NotFiredByFedFile == ~(targetFired /\ FED(fireInfo.fileLv))
\* violated iff the target fires in the startup main loop (the persisted
\* follow-on: an empty clusterID written by a hot-swap race, read after a restart)
NotFiredByMain == ~(targetFired /\ fireInfo.kind = "main")
\* violated iff the target fires while loading a VERSION whose clusterID is ""
NotFiredOnEmptyFileCid == ~(targetFired /\ fireInfo.fileCid = "")
\* the brief's §4.1 claim: in-model the target only fires on the shared field's ""
FiredOnlyOnEmptyCid == targetFired => fireInfo.dsCid = ""
\* state signatures from the brief §5 (precondition (ii); the persisted follow-on)
NoUpWithEmptyCid == ~(dn = "up" /\ sCID = "")
NoPersistedEmptyCid == \A x \in Loc : disk[x] # NoRec => disk[x].cid # ""

=============================================================================
