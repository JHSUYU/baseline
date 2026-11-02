--------------------------------- MODULE MC ---------------------------------
(***************************************************************************)
(* Model checking wrapper for base.tla (hdfs-adhoc-24, BPSS:421).          *)
(*                                                                         *)
(* Counter-bounded (they introduce non-determinism / faults / operator     *)
(* procedures):                                                            *)
(*   DataNodeStart, DataNodeCrash, NNDoUpgrade (normal and clock fault),   *)
(*   NNDoRollback, NNFinalizeUpgrade, NNCTimeRegress, VolumeOffline,       *)
(*   AttachEmptyVolume, RefreshVolumes (hot swap), NNStartRollingUpgrade,  *)
(*   NNFinalizeRollingUpgrade, NNCheckpoint, NNRestart.                    *)
(* Unbounded (deterministic / reactive): every loader step of              *)
(* BlockPoolSliceStorage (incl. TargetCheck), startup loop steps,          *)
(* HotSwapBuild, DataNodeStop, VolumeOnline (pairs with an offline),       *)
(* SignalRollingUpgrade, TrashBlockDelete, FinalizeUpgradeForVolume,       *)
(* FinalizeTmpDelete.                                                      *)
(***************************************************************************)
EXTENDS base, TLC

CONSTANTS
    MaxDNStarts,       \* DataNode process starts (REGULAR or ROLLBACK)
    MaxDNCrashes,      \* DataNode crashes at a step boundary (Scenario 2)
    MaxNNUpgrades,     \* NN -upgrade restarts (workload; Scenarios 2-4)
    MaxClockFaults,    \* NN -upgrade with a clock behind an earlier cTime (Scenario 4); also counts as an upgrade
    MaxNNRollbacks,    \* NN -rollback restarts (Scenarios 2, 3)
    MaxNNFinalizes,    \* dfsadmin -finalizeUpgrade (Scenario 4)
    MaxCTimeRegress,   \* NN reports a lower issued cTime (Scenario 4, directory split)
    MaxOffline,        \* volume disk goes offline (Scenarios 1, 2)
    MaxAttach,         \* empty / replaced disk attached (Scenarios 1, 2)
    MaxHotSwaps,       \* dfs.datanode.data.dir reconfigurations (Scenarios 1, 2)
    MaxRUStarts,       \* rolling upgrade starts (Scenario 3)
    MaxRUFinalizes,    \* rolling upgrade finalizes (Scenario 3)
    MaxCheckpoints,    \* NN checkpoints after the RU FINALIZE edit (Scenario 3)
    MaxNNRestarts      \* NN regular restarts (Scenario 3)

VARIABLE fc            \* fault / operation counters

mcVars == <<vars, fc>>

FC0 == [dnStart |-> 0, dnCrash |-> 0, nnUpgrade |-> 0, clock |-> 0, nnRollback |-> 0,
        nnFinalize |-> 0, regress |-> 0, offline |-> 0, attach |-> 0, hotswap |-> 0,
        ruStart |-> 0, ruFinalize |-> 0, checkpoint |-> 0, nnRestart |-> 0]

MCInit == Init /\ fc = FC0

Inc(k) == fc' = [fc EXCEPT ![k] = @ + 1]

\* ---- NameNode ----
MCNNDoUpgrade ==
    /\ fc.nnUpgrade < MaxNNUpgrades
    /\ NNDoUpgrade(MaxIssued + 1)
    /\ Inc("nnUpgrade")

MCNNDoUpgradeClockFault ==
    /\ fc.nnUpgrade < MaxNNUpgrades
    /\ fc.clock < MaxClockFaults
    /\ \E c \in 0..MaxIssued : NNDoUpgrade(c)
    /\ fc' = [fc EXCEPT !.nnUpgrade = @ + 1, !.clock = @ + 1]

MCNNDoRollback ==
    /\ fc.nnRollback < MaxNNRollbacks
    /\ NNDoRollback
    /\ Inc("nnRollback")

MCNNFinalizeUpgrade ==
    /\ fc.nnFinalize < MaxNNFinalizes
    /\ NNFinalizeUpgrade
    /\ Inc("nnFinalize")

MCNNCTimeRegress ==
    /\ fc.regress < MaxCTimeRegress
    /\ \E c \in issued : NNCTimeRegress(c)
    /\ Inc("regress")

MCNNStartRollingUpgrade ==
    /\ fc.ruStart < MaxRUStarts
    /\ NNStartRollingUpgrade
    /\ Inc("ruStart")

MCNNFinalizeRollingUpgrade ==
    /\ fc.ruFinalize < MaxRUFinalizes
    /\ NNFinalizeRollingUpgrade
    /\ Inc("ruFinalize")

MCNNCheckpoint ==
    /\ fc.checkpoint < MaxCheckpoints
    /\ NNCheckpoint
    /\ Inc("checkpoint")

MCNNRestart ==
    /\ fc.nnRestart < MaxNNRestarts
    /\ NNRestart
    /\ Inc("nnRestart")

\* ---- DataNode process ----
MCDataNodeStart ==
    /\ fc.dnStart < MaxDNStarts
    /\ \E o \in {"REGULAR", "ROLLBACK"} : DataNodeStart(o)
    /\ Inc("dnStart")

MCDataNodeCrash ==
    /\ fc.dnCrash < MaxDNCrashes
    /\ DataNodeCrash
    /\ Inc("dnCrash")

MCRefreshVolumes ==
    /\ fc.hotswap < MaxHotSwaps
    /\ \E S \in SUBSET Vol : RefreshVolumes(S)
    /\ Inc("hotswap")

\* ---- volumes ----
MCVolumeOffline(v) ==
    /\ fc.offline < MaxOffline
    /\ VolumeOffline(v)
    /\ Inc("offline")

MCAttachEmptyVolume(v) ==
    /\ fc.attach < MaxAttach
    /\ AttachEmptyVolume(v)
    /\ Inc("attach")

\* ---- unbounded (reactive / deterministic): one named wrapper each, so that TLC labels every
\* counterexample step with the base action it took ----
MCDataNodeStop              == DataNodeStop /\ UNCHANGED fc
MCSubmitUpgradeCallables    == SubmitUpgradeCallables /\ UNCHANGED fc
MCBlockPoolInitDone         == BlockPoolInitDone /\ UNCHANGED fc
MCLoadBlockPoolSliceStorageNext(v) == LoadBlockPoolSliceStorageNext(v) /\ UNCHANGED fc
MCAnalyzeStorage(v)         == AnalyzeStorage(v) /\ UNCHANGED fc
MCFormatSetLV(v)            == FormatSetLV(v) /\ UNCHANGED fc
MCFormatSetCTime(v)         == FormatSetCTime(v) /\ UNCHANGED fc
MCFormatWriteVersion(v)     == FormatWriteVersion(v) /\ UNCHANGED fc
MCDoTransitionDispatch(v)   == DoTransitionDispatch(v) /\ UNCHANGED fc
MCDoRollbackRenameCurrent(v)  == DoRollbackRenameCurrent(v) /\ UNCHANGED fc
MCDoRollbackRenamePrevious(v) == DoRollbackRenamePrevious(v) /\ UNCHANGED fc
MCDoRollbackDeleteTmp(v)    == DoRollbackDeleteTmp(v) /\ UNCHANGED fc
MCRestoreTrashForRollback(v) == RestoreTrashForRollback(v) /\ UNCHANGED fc
MCReadPropertiesLV(v)       == ReadPropertiesLV(v) /\ UNCHANGED fc
MCReadPropertiesCTime(v)    == ReadPropertiesCTime(v) /\ UNCHANGED fc
MCCheckRegularLV(v)         == CheckRegularLV(v) /\ UNCHANGED fc
MCCheckRegularCTime(v)      == CheckRegularCTime(v) /\ UNCHANGED fc
MCCheckLayoutForTrash(v)    == CheckLayoutForTrash(v) /\ UNCHANGED fc
MCRestoreTrashBeforeLayoutUpgrade(v) == RestoreTrashBeforeLayoutUpgrade(v) /\ UNCHANGED fc
MCCheckUpgradeLV(v)         == CheckUpgradeLV(v) /\ UNCHANGED fc
MCTargetCheck(v)            == TargetCheck(v) /\ UNCHANGED fc
MCDoUpgradeDeleteDnPrevious(v) == DoUpgradeDeleteDnPrevious(v) /\ UNCHANGED fc
MCDoUpgradeDeletePrevious(v) == DoUpgradeDeletePrevious(v) /\ UNCHANGED fc
MCDoUpgradeRenameCurrent(v) == DoUpgradeRenameCurrent(v) /\ UNCHANGED fc
MCLinkAllBlocks(v)          == LinkAllBlocks(v) /\ UNCHANGED fc
MCDoUpgradeSetLV(v)         == DoUpgradeSetLV(v) /\ UNCHANGED fc
MCDoUpgradeSetCTime(v)      == DoUpgradeSetCTime(v) /\ UNCHANGED fc
MCDoUpgradeWriteVersion(v)  == DoUpgradeWriteVersion(v) /\ UNCHANGED fc
MCDoUpgradeRenameTmp(v)     == DoUpgradeRenameTmp(v) /\ UNCHANGED fc
MCCheckCTimeAfterLoad(v)    == CheckCTimeAfterLoad(v) /\ UNCHANGED fc
MCSetServiceLayoutVersion(v) == SetServiceLayoutVersion(v) /\ UNCHANGED fc
MCWritePropertiesAfterLoad(v) == WritePropertiesAfterLoad(v) /\ UNCHANGED fc
MCLoadStorageDirectoryFail(v) == LoadStorageDirectoryFail(v) /\ UNCHANGED fc
MCHotSwapBuild(v)           == HotSwapBuild(v) /\ UNCHANGED fc
MCSignalRollingUpgrade(v)   == SignalRollingUpgrade(v) /\ UNCHANGED fc
MCTrashBlockDelete(v)       == TrashBlockDelete(v) /\ UNCHANGED fc
MCFinalizeUpgradeForVolume(v) == FinalizeUpgradeForVolume(v) /\ UNCHANGED fc
MCFinalizeTmpDelete(v)      == FinalizeTmpDelete(v) /\ UNCHANGED fc
MCVolumeOnline(v)           == VolumeOnline(v) /\ UNCHANGED fc

\* The stop-after-target rule is the state constraint StopAfterTarget (base.tla), set in every cfg.
MCNext ==
    \/ MCNNDoUpgrade
    \/ MCNNDoUpgradeClockFault
    \/ MCNNDoRollback
    \/ MCNNFinalizeUpgrade
    \/ MCNNCTimeRegress
    \/ MCNNStartRollingUpgrade
    \/ MCNNFinalizeRollingUpgrade
    \/ MCNNCheckpoint
    \/ MCNNRestart
    \/ MCDataNodeStart
    \/ MCDataNodeCrash
    \/ MCDataNodeStop
    \/ MCSubmitUpgradeCallables
    \/ MCBlockPoolInitDone
    \/ MCRefreshVolumes
    \/ \E v \in Vol :
         \/ MCVolumeOffline(v) \/ MCAttachEmptyVolume(v) \/ MCVolumeOnline(v)
         \/ MCLoadBlockPoolSliceStorageNext(v)
         \/ MCAnalyzeStorage(v)
         \/ MCFormatSetLV(v) \/ MCFormatSetCTime(v) \/ MCFormatWriteVersion(v)
         \/ MCDoTransitionDispatch(v)
         \/ MCDoRollbackRenameCurrent(v) \/ MCDoRollbackRenamePrevious(v) \/ MCDoRollbackDeleteTmp(v)
         \/ MCRestoreTrashForRollback(v)
         \/ MCReadPropertiesLV(v) \/ MCReadPropertiesCTime(v)
         \/ MCCheckRegularLV(v) \/ MCCheckRegularCTime(v)
         \/ MCCheckLayoutForTrash(v) \/ MCRestoreTrashBeforeLayoutUpgrade(v)
         \/ MCCheckUpgradeLV(v) \/ MCTargetCheck(v)
         \/ MCDoUpgradeDeleteDnPrevious(v) \/ MCDoUpgradeDeletePrevious(v) \/ MCDoUpgradeRenameCurrent(v)
         \/ MCLinkAllBlocks(v) \/ MCDoUpgradeSetLV(v) \/ MCDoUpgradeSetCTime(v)
         \/ MCDoUpgradeWriteVersion(v) \/ MCDoUpgradeRenameTmp(v)
         \/ MCCheckCTimeAfterLoad(v) \/ MCSetServiceLayoutVersion(v) \/ MCWritePropertiesAfterLoad(v)
         \/ MCLoadStorageDirectoryFail(v) \/ MCHotSwapBuild(v)
         \/ MCSignalRollingUpgrade(v) \/ MCTrashBlockDelete(v)
         \/ MCFinalizeUpgradeForVolume(v) \/ MCFinalizeTmpDelete(v)

MCSpec == MCInit /\ [][MCNext]_mcVars

\* Volumes are interchangeable (Init is closed under permutations of Vol).
MCSymmetry == Permutations(Vol)

\* InitLVs choices for the configs (negative integers cannot be written in a .cfg).
MCInitLVsCur == {CurLV}
MCInitLVsAll == {CurLV, OldLV}

=============================================================================
