------------------------------- MODULE MC -------------------------------
(***************************************************************************)
(* Model-checking wrapper for base (hdfs-adhoc-k7).                        *)
(*                                                                         *)
(* The adversary in this Category B target is the scheduler, not a lost   *)
(* message.  The base spec allows every interleaving of the field-granular *)
(* accesses.  The MC layer bounds the one non-deterministic ingredient     *)
(* that the passing workload does not exhibit:                             *)
(*                                                                         *)
(*   interference = a write by thread t that CHANGES bpLV or bpCT while    *)
(*                  some other thread u is "busy", i.e. has loaded the     *)
(*                  fields for its own volume and will still read them.    *)
(*                                                                         *)
(* With MaxInterference = 0 every explored schedule is one where no thread *)
(* ever observes a value changed under it by another thread: this is the   *)
(* passing workload's behaviour (sanity, adhoc tla-patterns §2).  Writes   *)
(* of the value already held (e.g. two callables both storing DNLV) are    *)
(* not interference and stay unbounded.                                    *)
(*                                                                         *)
(* Scenario 2's fault knob, MissedUpgradeVols, bounds how many hot-swapped *)
(* volumes start behind (DNLV, nsCTime), e.g. after a disk failure during  *)
(* the startup upgrade (DS:467-470).                                       *)
(***************************************************************************)
EXTENDS base

CONSTANTS
    MaxInterference,    \* scheduler knob (Scenarios 1 and 2)
    MissedUpgradeVols,  \* Scenario 2 fault knob
    StartDiskChoices,   \* admissible VERSION states of startup volumes
    HsDiskChoices       \* admissible states of hot-swapped volumes

VARIABLE interference
mcVars == <<vars, interference>>

----------------------------------------------------------------------------
(* Startup volume orders (cfg files cannot write sequences) *)
StartOrder1 == <<1>>
StartOrder2 == <<1, 2>>
StartOrder3 == <<1, 2, 3>>

----------------------------------------------------------------------------
(* Initial disk sets *)

\* Startup volume variants (brief §6.1 MC-1): the workload's cTime-only
\* upgrade, the layout upgrade (path c, with old or current cTime), and a
\* volume that is already current.
WorkloadStartDisks == {WorkloadDisk}
AllStartDisks == {WorkloadDisk, VersionDisk(OLDLV, OldCT),
                  VersionDisk(OLDLV, NsCT), CurrentDisk}
\* Scenario 1 hunt variants (one disk shape per run): a DN software upgrade
\* with a newer DN layout and an unchanged NN cTime (path c).
LayoutOnlyStartDisks == {VersionDisk(OLDLV, NsCT)}

\* Hot-swap volume variants (brief §2 Scenario 2 "Evidence"): fresh disk,
\* current disk, or a disk that missed the upgrade.
NoHsDisks       == {FreshDisk}
BenignHsDisks   == {FreshDisk, CurrentDisk}
AllHsDisks      == {FreshDisk, CurrentDisk, WorkloadDisk,
                    VersionDisk(OLDLV, OldCT), VersionDisk(OLDLV, NsCT)}

IsMissed(d) == d.ver /\ (d.lv > DNLV \/ d.ct < NsCT)

MCInitDiskSet ==
    { d \in [Vols -> StartDiskChoices \cup HsDiskChoices] :
        /\ \A v \in StartVols : d[v] \in StartDiskChoices
        /\ \A v \in HsVols    : d[v] \in HsDiskChoices
        /\ Cardinality({v \in HsVols : IsMissed(d[v])}) <= MissedUpgradeVols }

----------------------------------------------------------------------------
(* Interference accounting *)

\* Thread u has loaded the fields for its volume and still reads them:
\* the doTransition window, the regular path, doUpgrade's LV reads,
\* format's write-back, and the upgrade's write-back.
BusyPcs == { "fmtCT", "fmtWpLV", "fmtWpCT",
             "rpCT", "r405", "r406", "r409", "r415", "r416", "upgrade",
             "regCT", "regLV", "regWpLV", "regWpCT",
             "uSetCT", "uWpLV", "uWpCT" }

Busy(u) == pc[u] \in BusyPcs

Interferes(t) ==
    /\ (bpLV' /= bpLV \/ bpCT' /= bpCT)
    /\ \E u \in Threads \ {t} : Busy(u)

MCThreadStep(t) ==
    /\ ThreadStep(t)
    /\ IF Interferes(t)
         THEN /\ interference < MaxInterference
              /\ interference' = interference + 1
         ELSE interference' = interference

MCInit ==
    /\ Init
    /\ interference = 0

MCNext ==
    /\ ~targetFired
    /\ \E t \in Threads : MCThreadStep(t)

MCSpec == MCInit /\ [][MCNext]_mcVars

----------------------------------------------------------------------------
(* Structural invariants *)

MCTypeOK ==
    /\ TypeOK
    /\ interference \in 0..MaxInterference

\* Pool bound (DS:387): never more running callables than pool threads.
PoolBound == Cardinality(RunningTasks) <= PoolSize

\* Exclusion (DN:765, DN:1759): hot-swap threads only run after startup.
HotSwapAfterStartup ==
    \A v \in HsVols : pc[HsT(v)] /= "wait" => pc[MainT] = "done"

=============================================================================
