-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-26: can a DataNode block-pool rollback reach the throw at    *)
(* BlockPoolSliceStorage.java:621?                                         *)
(*                                                                         *)
(*   throw new InconsistentFSStateException(bpSd.getRoot(),                *)
(*       "Cannot rollback to a newer state. ...")      BPSS:621-626        *)
(*   guard (BPSS:618-620):                                                 *)
(*     !(prevInfo.getLayoutVersion() >= DataNodeLayoutVersion.getCurrent.. *)
(*       && prevInfo.getCTime() <= nsInfo.getCTime())                      *)
(*                                                                         *)
(* Pinned tree /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-26/hadoop at      *)
(* 734dd8a67cd. Paths are relative to                                      *)
(* hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/.  *)
(*   BPSS  server/datanode/BlockPoolSliceStorage.java                      *)
(*   DS    server/datanode/DataStorage.java                                *)
(*   S/SI  server/common/Storage.java / server/common/StorageInfo.java     *)
(*   DN    server/datanode/DataNode.java                                   *)
(*   BPOS  server/datanode/BPOfferService.java                             *)
(*   BPSA  server/datanode/BPServiceActor.java                             *)
(*   SLC   server/datanode/checker/StorageLocationChecker.java             *)
(*   FDI   server/datanode/fsdataset/impl/FsDatasetImpl.java               *)
(*   FSI   server/namenode/FSImage.java                                    *)
(*   NNU   server/namenode/NNUpgradeUtil.java                              *)
(*   NNS   server/namenode/NNStorage.java                                  *)
(*   NNJ   server/namenode/NameNode.java                                   *)
(*   RPC   server/namenode/NameNodeRpcServer.java                          *)
(*                                                                         *)
(* Category A (distributed). One non-HA NameNode, DataNodes with NumVols   *)
(* volumes each (config order 1..NumVols), one block pool. The model keeps *)
(* the persistent VERSION values the guard reads (per-volume BP current,   *)
(* previous, previous.tmp; the NN's current and previous cTime) and the    *)
(* volatile DataNode state that decides which nsInfo, which startup option *)
(* and which branch each per-volume transition takes.                      *)
(*                                                                         *)
(* Not modeled (modeling-brief.md 3.2): HA, rolling upgrade, BP trash and  *)
(* RU markers, DN-level `previous` and the DS twin check (DS:939-948),     *)
(* blocks, crash windows inside a BP transition, PROVIDED storage,         *)
(* federation (one block pool, one namespace: the nsID/bpid checks at      *)
(* BPSS:392-403 always pass).                                              *)
(*                                                                         *)
(* This module has no operator procedure and no fault bounds: MC.tla adds  *)
(* the documented upgrade/rollback procedure and the Scenario counters.    *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets

CONSTANTS
    DN,         \* DataNode ids
    NumVols,    \* data dirs per DataNode (dfs.datanode.data.dir), config order
    MaxCT,      \* cTime values are 1..MaxCT: an order-preserving stand-in for ms timestamps
    FormatCT,   \* cTime stamped by the NameNode format before Init (NNS:626-630, Time.now())
    Tolerated   \* dfs.datanode.failed.volumes.tolerated (DFSConfigKeys.java:475, default 0);
                \* the -1 "limit" form (SLC:220-227) is not modeled

ASSUME NumVols \in Nat \ {0}
ASSUME MaxCT \in Nat \ {0}
ASSUME Tolerated \in Nat

(***************************************************************************)
(* Layout versions are negative, and .cfg files cannot hold negative       *)
(* integers, so they are defined here (a cfg may override with `<-`).      *)
(* DataNodeLayoutVersion.java:37-38: getCurrentLayoutVersion() is the last *)
(* non-reserved feature, BLOCKID_BASED_LAYOUT_32_by_32 = -57 (:90).        *)
(***************************************************************************)
InitSwLV == -57
\* The next DataNode layout (Scenario 4). Smaller is newer: SI:219 treats
\* lv < service LV as a "future version".
NewSwLV == InitSwLV - 1
LVSet == {InitSwLV + 1, InitSwLV, InitSwLV - 1}

Vol == 1..NumVols
CTime == 1..MaxCT
NoCT == 0                                   \* no cTime: absent VERSION / no previous / not known yet
NoVer == [lv |-> 0, ct |-> NoCT]            \* absent directory or VERSION file
Ver(lv, ct) == [lv |-> lv, ct |-> ct]
Vers == [lv : LVSet, ct : CTime]
DNStates == {"down", "handshake", "loading", "registering", "running", "reconnecting"}
StartOpts == {"REGULAR", "ROLLBACK"}        \* DN:3424-3445 accepts only these two

\* The elements of a finite set of volume indices, in config order.
InOrder(S) == [i \in 1..Cardinality(S) |->
                 CHOOSE v \in S : Cardinality({w \in S : w < v}) = i - 1]

VARIABLES
    \* ---- NameNode storage (FSImage / NNStorage) ----
    nnUp,        \* the NameNode process is up and answers DataNode RPCs
    nnCur,       \* cTime in the NN's current/VERSION = NamespaceInfo.cTime (RPC:1754-1758)
    nnPrev,      \* cTime in the NN's previous/VERSION; NoCT if no previous dir
    nnHist,      \* every cTime the NN storage has held (for VolumeCTimesFromNN only)
    \* ---- DataNode process (volatile; reset when the process stops) ----
    dnPc,        \* see DNStates
    dnOpt,       \* startup option of the running process (DN:3424-3455; read at DN:2256)
    dnNs,        \* nsInfo.cTime of the handshake (BPOS bpNSInfo: BPSA:308, BPOS:394)
    dnPending,   \* volumes whose BP load has not run yet, in config order (DS:459)
    dnCont,      \* volumes with a queued upgrade continuation (DS:471, 479-498)
    dnRegCT,     \* cTime field of the DataNode's shared BlockPoolSliceStorage object;
                 \* registrations copy it (BPOS:461-470, DN:2073-2089, S:1417-1421)
    dnSwLV,      \* DataNodeLayoutVersion.getCurrentLayoutVersion() of the DN software
    \* ---- Volume storage (persistent unless noted) ----
    volCur,      \* <vol>/current/<bpid>/current/VERSION as [lv, ct]; NoVer if absent
    volPrev,     \* <vol>/current/<bpid>/previous/VERSION
    volTmp,      \* <vol>/current/<bpid>/previous.tmp/VERSION (between BPSS:486 and :517)
    volOnline,   \* the volume's disk is usable (Scenario 2)
    volBpFault,  \* a transient I/O fault waits on the volume's BP dir (Scenario 2)
    volLoad,     \* volatile: "none" (not in DataStorage), "dn" (DN-level dir loaded,
                 \* BP load failed or not finished), "bp" (BP load completed)
    \* ---- Target ----
    targetFired  \* the throw at BPSS:621 has executed

nnVars  == <<nnUp, nnCur, nnPrev, nnHist>>
dnVars  == <<dnPc, dnOpt, dnNs, dnPending, dnCont, dnRegCT, dnSwLV>>
volVars == <<volCur, volPrev, volTmp, volOnline, volBpFault, volLoad>>
vars    == <<nnVars, dnVars, volVars, targetFired>>

SwLV(d) == dnSwLV[d]

-----------------------------------------------------------------------------
(***************************************************************************)
(* Initial state: an existing cluster, stopped. The NameNode was formatted *)
(* with cTime FormatCT; every DataNode volume was formatted by an earlier  *)
(* start against it (BPSS:167-172, 283-292: LV = software LV, cTime =      *)
(* nsInfo.cTime, no previous). A volume formatted later, inside an upgrade *)
(* epoch -- a replaced disk, or a DataNode commissioned during the bake -- *)
(* is Scenario 3 (VolReplace), so it is not free in the initial state.     *)
(***************************************************************************)
Init ==
    /\ nnUp = FALSE
    /\ nnCur = FormatCT                     \* NNS:626-630 newNamespaceInfo(..., Time.now())
    /\ nnPrev = NoCT
    /\ nnHist = {FormatCT}
    /\ dnPc = [d \in DN |-> "down"]
    /\ dnOpt = [d \in DN |-> "REGULAR"]
    /\ dnNs = [d \in DN |-> NoCT]
    /\ dnPending = [d \in DN |-> <<>>]
    /\ dnCont = [d \in DN |-> {}]
    /\ dnRegCT = [d \in DN |-> NoCT]
    /\ dnSwLV = [d \in DN |-> InitSwLV]
    /\ volCur = [d \in DN |-> [v \in Vol |-> Ver(InitSwLV, FormatCT)]]
    /\ volPrev = [d \in DN |-> [v \in Vol |-> NoVer]]
    /\ volTmp = [d \in DN |-> [v \in Vol |-> NoVer]]
    /\ volOnline = [d \in DN |-> [v \in Vol |-> TRUE]]
    /\ volBpFault = [d \in DN |-> [v \in Vol |-> FALSE]]
    /\ volLoad = [d \in DN |-> [v \in Vol |-> "none"]]
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode                                                                *)
(***************************************************************************)

\* Regular NameNode start (FSI:325-339 REGULAR: load the image). After load,
\* isUpgradeFinalized = "no storage dir has previous" (FSI:689).
NNStart ==
    /\ ~nnUp
    /\ nnCur /= NoCT                        \* storage formatted, else the start fails
    /\ nnUp' = TRUE
    /\ UNCHANGED <<nnCur, nnPrev, nnHist, dnVars, volVars, targetFired>>

\* The NameNode process stops. A running DataNode's actor keeps retrying its
\* heartbeat and re-registers when an NN answers again (BPSA:967-984).
NNStop ==
    /\ nnUp
    /\ nnUp' = FALSE
    /\ dnPc' = [d \in DN |-> IF dnPc[d] = "running" THEN "reconnecting" ELSE dnPc[d]]
    /\ UNCHANGED <<nnCur, nnPrev, nnHist, dnOpt, dnNs, dnPending, dnCont,
                   dnRegCT, dnSwLV, volVars, targetFired>>

\* `namenode -upgrade` (start-dfs.sh -upgrade passes it to the NN only,
\* src/main/bin/start-dfs.sh:68-69): FSImage.doUpgrade, FSI:455-519.
\* `ct` is the wall clock at the start; the MC layer chooses it.
NNUpgrade(ct) ==
    /\ ~nnUp
    /\ nnCur /= NoCT
    /\ nnPrev = NoCT                        \* FSI:456 -> checkUpgrade FSI:423-433:
                                            \*   "previous fs state should not exist during upgrade"
    /\ ct \in CTime
    /\ nnCur' = ct                          \* FSI:464-465 storage.cTime = now(); no check
                                            \*   that it exceeds the old cTime
    /\ nnPrev' = nnCur                      \* FSI:478-488 NNU.doPreUpgrade (NNU:116-121) moves
                                            \*   current aside; FSI:501-509 NNU.doUpgrade
                                            \*   (NNU:183-189) makes it previous
    /\ nnHist' = nnHist \cup {ct}
    /\ nnUp' = TRUE                         \* the NN keeps running after an upgrade start;
                                            \*   isUpgradeFinalized = false (FSI:512)
    /\ UNCHANGED <<dnVars, volVars, targetFired>>

\* Offline `namenode -rollback` (NNJ:1628-1649 -> FSI:521-572). The process
\* is not the running NameNode (NNJ:1635-1640 warns that none may run).
NNRollback ==
    /\ ~nnUp
    /\ nnPrev /= NoCT                       \* FSI:529-537 NNU.canRollBack (NNU:55-79);
                                            \*   FSI:550-552 "Cannot rollback. None of the
                                            \*   storage directories contain previous fs state."
    /\ nnCur' = nnPrev                      \* FSI:556-562 -> NNU.doRollBack (NNU:213-236):
    /\ nnPrev' = NoCT                       \*   current -> removed.tmp, previous -> current
    /\ UNCHANGED <<nnUp, nnHist, dnVars, volVars, targetFired>>

\* `dfsadmin -finalizeUpgrade`: FSImage.finalizeUpgrade (FSI:616-632) deletes
\* previous in every dir (NNU.doFinalize, FSI:621-624); isUpgradeFinalized = true (FSI:631).
NNFinalize ==
    /\ nnUp
    /\ nnPrev /= NoCT
    /\ nnPrev' = NoCT
    /\ UNCHANGED <<nnUp, nnCur, nnHist, dnVars, volVars, targetFired>>

\* `namenode -format` (NNS:611-632; cTime = Time.now(), NNS:626-630). Not in
\* Next: MC starts from a formatted NameNode. Trace.tla uses it to replay a
\* MiniDFSCluster that formats its NameNode.
NNFormat(ct) ==
    /\ ~nnUp
    /\ ct \in CTime
    /\ nnCur' = ct
    /\ nnPrev' = NoCT
    /\ nnHist' = nnHist \cup {ct}
    /\ UNCHANGED <<nnUp, dnVars, volVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* DataNode start, handshake and per-volume block-pool load               *)
(***************************************************************************)

\* The DataNode process is gone (stop, init failure or rejected registration):
\* every volatile field resets; on-disk state stays.
ResetDN(d) ==
    /\ dnPc' = [dnPc EXCEPT ![d] = "down"]
    /\ dnOpt' = [dnOpt EXCEPT ![d] = "REGULAR"]
    /\ dnNs' = [dnNs EXCEPT ![d] = NoCT]
    /\ dnPending' = [dnPending EXCEPT ![d] = <<>>]
    /\ dnCont' = [dnCont EXCEPT ![d] = {}]
    /\ dnRegCT' = [dnRegCT EXCEPT ![d] = NoCT]
    /\ volLoad' = [volLoad EXCEPT ![d] = [v \in Vol |-> "none"]]

\* DataNode process start (DataNode.secureMain -> createDataNode):
\*  - parseArguments: `-rollback` or `-regular`, default REGULAR, stored in the
\*    conf for the life of the process (DN:3424-3455);
\*  - makeInstance runs StorageLocationChecker.check (DN:3391-3405). It drops
\*    failed locations when at most `Tolerated` failed (SLC:228-236) and needs
\*    one good location (SLC:238-241). Otherwise the DataNode does not start,
\*    which changes nothing, so the action is disabled.
\* The surviving locations, in config order, are the process's dataDirs.
DNStart(d, opt) ==
    /\ dnPc[d] = "down"
    /\ opt \in StartOpts
    /\ LET good == {v \in Vol : volOnline[d][v]}
       IN /\ Cardinality(Vol \ good) <= Tolerated          \* SLC:229-235
          /\ good /= {}                                    \* SLC:238-241
          /\ dnPending' = [dnPending EXCEPT ![d] = InOrder(good)]
    /\ dnPc' = [dnPc EXCEPT ![d] = "handshake"]
    /\ dnOpt' = [dnOpt EXCEPT ![d] = opt]
    /\ UNCHANGED <<nnVars, dnNs, dnCont, dnRegCT, dnSwLV, volVars, targetFired>>

PendingSet(d) == {dnPending[d][i] : i \in 1..Len(dnPending[d])}

\* Handshake and storage init up to the block-pool loop:
\*  - BPSA.connectToNNAndHandshake (BPSA:302-317): versionRequest returns the
\*    NN's NamespaceInfo (BPSA:258-281, RPC:1754-1758; it retries while no NN answers);
\*  - the first actor of the block pool calls dn.initBlockPool (BPOS:394-401) ->
\*    initStorage (DN:2199, 2251-2264) -> DataStorage.recoverTransitionRead
\*    (DS:564-566) -> addStorageLocations (DS:382-397);
\*  - loadDataStorage loads the DN-level dir of each location (DS:403-448).
\*    `loaded` is the set whose DN-level load succeeded (DS:417). DN-level
\*    storage is not modeled (brief 3.2), so MC passes every location; a trace
\*    passes the observed set. A failed DN-level load is swallowed (DS:424-426)
\*    and its location is never BP-loaded; with none loaded, addStorageLocations
\*    returns empty (DS:392-394) and DNInitDone fails the init (DS:566-567);
\*  - loadBlockPoolSliceStorage creates the shared BlockPoolSliceStorage with
\*    nsInfo.cTime (DS:454 -> DS:1409-1419).
DNHandshake(d, loaded) ==
    /\ dnPc[d] = "handshake"
    /\ nnUp
    /\ loaded \subseteq PendingSet(d)
    /\ dnNs' = [dnNs EXCEPT ![d] = nnCur]
    /\ dnRegCT' = [dnRegCT EXCEPT ![d] = nnCur]
    /\ dnPending' = [dnPending EXCEPT ![d] = SelectSeq(@, LAMBDA x : x \in loaded)]
    /\ volLoad' = [volLoad EXCEPT ![d] =
                     [v \in Vol |-> IF v \in loaded THEN "dn" ELSE "none"]]
    /\ dnPc' = [dnPc EXCEPT ![d] = "loading"]
    /\ UNCHANGED <<nnVars, dnOpt, dnCont, dnSwLV, volCur, volPrev,
                   volTmp, volOnline, volBpFault, targetFired>>

\* Branch of BPSS.doTransition after its read at L388, for the volume whose
\* current/VERSION is `cur` there (nsInfo.cTime = dnNs[d]).
Outcome388(d, cur) ==
    IF cur.lv < SwLV(d) THEN "readFail"     \* L388 readProperties -> BPSS:343 ->
                                            \*   SI:216-222 IncorrectVersionException
    ELSE IF cur.lv = SwLV(d) /\ cur.ct = dnNs[d] THEN "regular"     \* L404-406
    ELSE IF cur.lv > SwLV(d) \/ cur.ct < dnNs[d] THEN "upgrade"     \* L414-417
    ELSE "refuse"                                                    \* L419-424
    \* L389 checkVersionUpgradable passes for every modeled LV (S:91 = -16,
    \* S:1146-1161); L392-403 pass (one namespace, one block pool).

\* The BP load of volume v takes the doRollback branch:
\*  - BPSS.loadStorageDirectory (BPSS:149-181) finds the BP dir NORMAL
\*    (S:717-731: current/VERSION exists, no temp dir);
\*  - doTransition sees ROLLBACK with previous present (BPSS:375).
\* PROVIDED storage (BPSS:372-374) and BP trash (the checkState at
\* BPSS:376-378) are not modeled.
TargetEnabled(d, v) ==
    /\ dnPc[d] = "loading"
    /\ dnPending[d] /= <<>>
    /\ Head(dnPending[d]) = v
    /\ ~volBpFault[d][v]
    /\ volCur[d][v] /= NoVer
    /\ dnOpt[d] = "ROLLBACK"                \* BPSS:375 startOpt == ROLLBACK
    /\ volPrev[d][v] /= NoVer               \* BPSS:375 sd.getPreviousDir().exists()

\* Which way TargetCheck(d, v) goes (pre-state; meaningful when TargetEnabled).
TargetOutcome(d, v) ==
    LET prev == volPrev[d][v] IN
    IF prev.lv < SwLV(d) THEN "prevReadFail"                         \* BPSS:612
    ELSE IF ~(prev.lv >= SwLV(d) /\ prev.ct <= dnNs[d]) THEN "fired" \* BPSS:618-621
    ELSE Outcome388(d, prev)                \* after the swap: "regular" or "upgrade"

\* Which way DNLoadVolume(d, v) or HotSwapAdd(d, v) goes (pre-state).
LoadOutcome(d, v) ==
    IF volBpFault[d][v] THEN "bpFault"
    ELSE IF volCur[d][v] = NoVer
         THEN IF volPrev[d][v] /= NoVer THEN "inconsistent" ELSE "format"
         ELSE Outcome388(d, volCur[d][v])

\* BPSS.doTransition from L388 on, for a DataNode start (callables /= null,
\* so an upgrade continuation is queued, BPSS:491-499). `cur` and `prev` are
\* the volume's current and previous VERSIONs at L388, after a rollback swap
\* if there was one.
After388(d, v, cur, prev) ==
    LET out == Outcome388(d, cur) IN
    IF out = "readFail"
    THEN \* BPSS.setFieldsFromProperties (BPSS:341-349) calls setLayoutVersion
         \* first, which throws (SI:219-221): this.cTime is not read. The
         \* IOException is swallowed per volume (BPSS:193-195, 229-232; DS:473-476).
         /\ volCur' = [volCur EXCEPT ![d][v] = cur]
         /\ volPrev' = [volPrev EXCEPT ![d][v] = prev]
         /\ UNCHANGED <<volTmp, volLoad, dnRegCT, dnCont>>
    ELSE
      /\ dnRegCT' = [dnRegCT EXCEPT ![d] = cur.ct]  \* L388 -> BPSS:345 setcTime
                                                    \*   (SI:195-198) on the shared object
      /\ IF out = "regular"
         THEN \* L404-406 return false. BPSS:184 getCTime() == nsInfo.getCTime()
              \* holds; BPSS:188-189 rewrite VERSION with the same values;
              \* DS:466-469 success.
              /\ volCur' = [volCur EXCEPT ![d][v] = cur]
              /\ volPrev' = [volPrev EXCEPT ![d][v] = prev]
              /\ volLoad' = [volLoad EXCEPT ![d][v] = "bp"]
              /\ UNCHANGED <<volTmp, dnCont>>
         ELSE IF out = "upgrade"
         THEN \* L408-413 restore trash (not modeled); L414-416 doUpgrade
              \* (BPSS:445-501). FEDERATION is supported by every modeled LV
              \* (BPSS:450-453). The BP previous is deleted (BPSS:477-480): an
              \* un-finalized snapshot is lost. current is renamed to previous.tmp
              \* (BPSS:486). The rest is queued as a callable (BPSS:491-499) and
              \* runs after the loop (DS:471, 479-498).
              /\ volCur' = [volCur EXCEPT ![d][v] = NoVer]
              /\ volPrev' = [volPrev EXCEPT ![d][v] = NoVer]
              /\ volTmp' = [volTmp EXCEPT ![d][v] = cur]
              /\ dnCont' = [dnCont EXCEPT ![d] = @ \cup {v}]
              /\ UNCHANGED volLoad
         ELSE \* "refuse", L419-424: IOException "Datanode state: LV = .. CTime =
              \* .. is newer than the namespace state". Swallowed (DS:473-476); the
              \* volume stays DN-level loaded and in service (FDI:361-363).
              \* this.cTime keeps cur.ct.
              /\ volCur' = [volCur EXCEPT ![d][v] = cur]
              /\ volPrev' = [volPrev EXCEPT ![d][v] = prev]
              /\ UNCHANGED <<volTmp, volLoad, dnCont>>

(***************************************************************************)
(* TargetCheck: BPSS.doTransition L375-379 -> doRollback L603-645.         *)
(* One iteration of the BP loop (DS:459-477) for the volume at its head,   *)
(* when that volume takes the ROLLBACK + previous branch.                  *)
(***************************************************************************)
TargetCheck(d, v) ==
    /\ TargetEnabled(d, v)
    /\ dnPending' = [dnPending EXCEPT ![d] = Tail(@)]
    /\ LET prev == volPrev[d][v]
           N    == dnNs[d]
       IN
       \* L605-609: previous exists, so no early return.
       \* L611-612: read previous/VERSION into a fresh BlockPoolSliceStorage of type
       \* DATA_NODE (BPSS:126-127): setLayoutVersion throws IncorrectVersionException
       \* if lv < DataNodeLayoutVersion.getCurrentLayoutVersion() (SI:216-222,
       \* SI:241-245). That makes the LV disjunct of the guard unreachable.
       IF prev.lv < SwLV(d)
       THEN \* IncorrectVersionException at L612: a different site, not the target.
            \* Swallowed per volume (BPSS:193-195, 229-232; DS:473-476).
            UNCHANGED <<volCur, volPrev, volTmp, volLoad, dnRegCT, dnCont, targetFired>>
       ELSE IF ~(prev.lv >= SwLV(d) /\ prev.ct <= N)          \* L618-620, as written
       THEN \* THE TARGET: L621 throw new InconsistentFSStateException(...)
            \* (its stack frame reports :626, evidence/bpss-doRollback-javap.txt).
            \* It is an IOException: swallowed per volume (DS:473-476), the volume
            \* stays DN-level loaded, the shared object's fields are untouched.
            /\ targetFired' = TRUE
            /\ UNCHANGED <<volCur, volPrev, volTmp, volLoad, dnRegCT, dnCont>>
       ELSE \* L629-643: current -> removed.tmp (L637), previous -> current (L640),
            \* delete removed.tmp (L643). doTransition resumes at L388 with the
            \* old previous as current (CR-7: if prev.ct < N it re-upgrades at once).
            /\ After388(d, v, prev, NoVer)
            /\ UNCHANGED targetFired
    /\ UNCHANGED <<nnVars, dnPc, dnOpt, dnNs, dnSwLV, volOnline, volBpFault>>

\* Every other iteration of the BP loop (DS:459-477): BPSS.recoverTransitionRead
\* (BPSS:251-263) -> loadBpStorageDirectories (BPSS:215-235) ->
\* loadStorageDirectory (BPSS:149-197) for the volume at the head of the loop.
DNLoadVolume(d, v) ==
    /\ dnPc[d] = "loading"
    /\ dnPending[d] /= <<>>
    /\ Head(dnPending[d]) = v
    /\ ~TargetEnabled(d, v)
    /\ dnPending' = [dnPending EXCEPT ![d] = Tail(@)]
    /\ LET out == LoadOutcome(d, v) IN
       IF out = "bpFault"
       THEN \* Transient fault on <vol>/current/<bpid> (Scenario 2): analyzeStorage
            \* returns NON_EXISTENT (S:687-694) -> IOException at BPSS:161-166.
            \* Swallowed (DS:473-476); the DN-level dir stays loaded (DS:417).
            /\ volBpFault' = [volBpFault EXCEPT ![d][v] = FALSE]
            /\ UNCHANGED <<volCur, volPrev, volTmp, volLoad, dnRegCT, dnCont>>
       ELSE IF out = "inconsistent"
       THEN \* previous without current/VERSION: S:732-734 InconsistentFSStateException
            \* "version file in current directory is missing"; swallowed.
            UNCHANGED <<volCur, volPrev, volTmp, volLoad, dnRegCT, dnCont, volBpFault>>
       ELSE IF out = "format"
       THEN \* No VERSION, no previous: NOT_FORMATTED (S:735-738) -> format
            \* (BPSS:167-172, 283-292): clearDirectory, LV := software LV (BPSS:287),
            \* cTime := nsInfo.cTime on the shared object (BPSS:288), write VERSION
            \* (BPSS:291). There is no previous, so doTransition takes L380-387
            \* (ROLLBACK) or neither branch, reads it back at L388, and starts
            \* regularly (L404-406).
            /\ volCur' = [volCur EXCEPT ![d][v] = Ver(SwLV(d), dnNs[d])]
            /\ dnRegCT' = [dnRegCT EXCEPT ![d] = dnNs[d]]
            /\ volLoad' = [volLoad EXCEPT ![d][v] = "bp"]
            /\ UNCHANGED <<volPrev, volTmp, dnCont, volBpFault>>
       ELSE \* NORMAL. doTransition: ROLLBACK without previous restores trash
            \* (L380-387, not modeled); REGULAR takes neither branch. Then L388.
            /\ After388(d, v, volCur[d][v], volPrev[d][v])
            /\ UNCHANGED volBpFault
    /\ UNCHANGED <<nnVars, dnPc, dnOpt, dnNs, dnSwLV, volOnline, targetFired>>

\* The queued callable (BPSS:494-497 -> doUpgrade(name, ...) BPSS:503-519),
\* run on the executor after the loop (DS:479-498): link blocks (L508),
\* LV := software LV (L509), cTime := nsInfo.cTime on the shared object (L512),
\* write current/VERSION (L513), previous.tmp -> previous (L517). DS:490 then
\* counts the volume as loaded. Continuations run in parallel; all write the
\* same cTime.
DNUpgradeContinuation(d, v) ==
    /\ dnPc[d] = "loading"
    /\ dnPending[d] = <<>>
    /\ v \in dnCont[d]
    /\ volCur' = [volCur EXCEPT ![d][v] = Ver(SwLV(d), dnNs[d])]
    /\ volPrev' = [volPrev EXCEPT ![d][v] = volTmp[d][v]]
    /\ volTmp' = [volTmp EXCEPT ![d][v] = NoVer]
    /\ dnRegCT' = [dnRegCT EXCEPT ![d] = dnNs[d]]
    /\ volLoad' = [volLoad EXCEPT ![d][v] = "bp"]
    /\ dnCont' = [dnCont EXCEPT ![d] = @ \ {v}]
    /\ UNCHANGED <<nnVars, dnPc, dnOpt, dnNs, dnPending, dnSwLV, volOnline,
                   volBpFault, targetFired>>

\* End of DataStorage.recoverTransitionRead (DS:564-569). It throws "All
\* specified directories have failed to load." when no BP dir loaded. Then
\* initBlockPool fails, BPOS resets nsInfo (BPOS:404-409), the single actor
\* goes FAILED (BPSA:910-921 with BPOS:860-867), and the DataNode exits once
\* no block-pool service is left (DN:3361-3377, 3494-3515).
DNInitDone(d) ==
    /\ dnPc[d] = "loading"
    /\ dnPending[d] = <<>>
    /\ dnCont[d] = {}
    /\ IF \E v \in Vol : volLoad[d][v] = "bp"
       THEN /\ dnPc' = [dnPc EXCEPT ![d] = "registering"]
            /\ UNCHANGED <<dnOpt, dnNs, dnPending, dnCont, dnRegCT, volLoad>>
       ELSE ResetDN(d)
    /\ UNCHANGED <<nnVars, dnSwLV, volCur, volPrev, volTmp, volOnline, volBpFault,
                   targetFired>>

\* Registration and first heartbeat:
\*  - BPSA.register (BPSA:324, 838-879) sends a registration built from the
\*    live shared BlockPoolSliceStorage (BPSA:841 -> BPOS:461-470 -> DN:2073-2089);
\*  - registerDatanode compares cTime only when software versions differ
\*    (RPC:1616-1623, 1903-1930); the NN returns a copy, so later RPCs carry
\*    this cTime (BPSA:848-850);
\*  - the first heartbeat runs verifyRequest (RPC:1634-1635, 1777-1787): the
\*    registration ID "NS-<nsid>-<cid>-<cTime>" (S:1417-1421) must equal the NN's.
\*    On a mismatch UnregisteredNodeException stops the actor (BPSA:791-798)
\*    and the DataNode exits (DN:3361-3377).
DNRegister(d) ==
    /\ dnPc[d] = "registering"
    /\ nnUp
    /\ IF dnRegCT[d] = nnCur
       THEN /\ dnPc' = [dnPc EXCEPT ![d] = "running"]
            /\ UNCHANGED <<dnOpt, dnNs, dnPending, dnCont, dnRegCT, volLoad>>
       ELSE ResetDN(d)
    /\ UNCHANGED <<nnVars, dnSwLV, volCur, volPrev, volTmp, volOnline, volBpFault,
                   targetFired>>

\* After the NameNode comes back, BPSA.reRegister (BPSA:967-984) fetches
\* nsInfo again and registers from the live shared object (BPSA:980 -> 841);
\* it never re-runs storage transitions, and bpNSInfo (dnNs) is unchanged.
DNReRegister(d) ==
    /\ dnPc[d] = "reconnecting"
    /\ nnUp
    /\ IF dnRegCT[d] = nnCur
       THEN /\ dnPc' = [dnPc EXCEPT ![d] = "running"]
            /\ UNCHANGED <<dnOpt, dnNs, dnPending, dnCont, dnRegCT, volLoad>>
       ELSE ResetDN(d)
    /\ UNCHANGED <<nnVars, dnSwLV, volCur, volPrev, volTmp, volOnline, volBpFault,
                   targetFired>>

\* FinalizeCommand. A block report to an active NN whose image is finalized
\* (RPC:1682-1687; isUpgradeFinalized = no previous, FSI:631/689) gets
\* DNA_FINALIZE, handled from the active actor (BPOS:774-782) by
\* DataNode.finalizeUpgradeForPool (DN:3660-3662) -> DataStorage.finalizeUpgrade
\* (DS:1016-1031). It walks every DN-level storage dir -- including volumes
\* whose BP load failed -- and BPSS.doFinalize (BPSS:651-689) renames the BP
\* previous to finalized.tmp and deletes it. No DN-level previous exists here
\* (brief 3.2), so DS:1022-1024 never applies. Sent with every block report,
\* so it may find nothing to do.
DNFinalize(d) ==
    /\ dnPc[d] = "running"
    /\ nnUp
    /\ nnPrev = NoCT
    /\ volPrev' = [volPrev EXCEPT ![d] =
                     [v \in Vol |-> IF volLoad[d][v] /= "none" THEN NoVer
                                    ELSE volPrev[d][v]]]
    /\ UNCHANGED <<nnVars, dnVars, volCur, volTmp, volOnline, volBpFault, volLoad,
                   targetFired>>

\* DataNode process stop. Not while the block-pool loop or its continuations
\* run: crash windows inside a BP transition only rename (S:659-840), so a
\* crash there cannot change a VERSION value (brief 3.2).
DNStop(d) ==
    /\ dnPc[d] \in {"handshake", "registering", "running", "reconnecting"}
    /\ ResetDN(d)
    /\ UNCHANGED <<nnVars, dnSwLV, volCur, volPrev, volTmp, volOnline, volBpFault,
                   targetFired>>

\* Hot-swap add of a volume to a running DataNode:
\*  - DataNode.refreshVolumes (DN:1284-1373) uses the cached handshake nsInfo
\*    (DN:1286-1289) and calls FsDatasetImpl.addVolume (FDI:515-525) ->
\*    DataStorage.prepareVolume (DS:324-346) with StartupOption.HOTSWAP;
\*  - DN-level load (DS:333-334), then BPSS.loadBpStorageDirectories with
\*    callables = null (DS:341-342), so an upgrade runs inline (BPSS:489-490);
\*  - HOTSWAP never takes the ROLLBACK branches (BPSS:375, 380);
\*  - on any IOException DataStorage is not modified (DS:322) and the add fails.
HotSwapAdd(d, v) ==
    /\ dnPc[d] = "running"
    /\ volLoad[d][v] = "none"               \* DS:327-331 containsStorageDir
    /\ volOnline[d][v]
    /\ LET out == LoadOutcome(d, v)
           cur == volCur[d][v]
           N   == dnNs[d]
       IN
       IF out = "bpFault"
       THEN /\ volBpFault' = [volBpFault EXCEPT ![d][v] = FALSE]
            /\ UNCHANGED <<volCur, volPrev, volLoad, dnRegCT>>
       ELSE IF out \in {"inconsistent", "readFail"}
       THEN UNCHANGED <<volCur, volPrev, volLoad, dnRegCT, volBpFault>>
       ELSE IF out = "format"
       THEN \* BPSS:167-172, 283-292, then L388 regular
            /\ volCur' = [volCur EXCEPT ![d][v] = Ver(SwLV(d), N)]
            /\ dnRegCT' = [dnRegCT EXCEPT ![d] = N]
            /\ volLoad' = [volLoad EXCEPT ![d][v] = "bp"]
            /\ UNCHANGED <<volPrev, volBpFault>>
       ELSE IF out = "regular"
       THEN \* L388 (this.cTime := cur.ct), L404-406, BPSS:184-189
            /\ dnRegCT' = [dnRegCT EXCEPT ![d] = cur.ct]
            /\ volLoad' = [volLoad EXCEPT ![d][v] = "bp"]
            /\ UNCHANGED <<volCur, volPrev, volBpFault>>
       ELSE IF out = "upgrade"
       THEN \* L414-416 doUpgrade inline: BPSS:477-480, 486, then BPSS:503-519
            \* (previous := old current; current := (SW LV, nsInfo cTime);
            \* this.cTime := nsInfo.cTime at L512)
            /\ volPrev' = [volPrev EXCEPT ![d][v] = cur]
            /\ volCur' = [volCur EXCEPT ![d][v] = Ver(SwLV(d), N)]
            /\ dnRegCT' = [dnRegCT EXCEPT ![d] = N]
            /\ volLoad' = [volLoad EXCEPT ![d][v] = "bp"]
            /\ UNCHANGED volBpFault
       ELSE \* "refuse": L388 set this.cTime := cur.ct, then L419-424 throws
            /\ dnRegCT' = [dnRegCT EXCEPT ![d] = cur.ct]
            /\ UNCHANGED <<volCur, volPrev, volLoad, volBpFault>>
    /\ UNCHANGED <<nnVars, dnPc, dnOpt, dnNs, dnPending, dnCont, dnSwLV, volTmp,
                   volOnline, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Environment and fault actions (bounded in MC.tla)                       *)
(***************************************************************************)

\* Scenario 2: the volume's disk fails while the DataNode is down. The next
\* start drops it if tolerated (SLC:228-236) and never loads it in that process.
VolOutage(d, v) ==
    /\ dnPc[d] = "down"
    /\ volOnline[d][v]
    /\ volOnline' = [volOnline EXCEPT ![d][v] = FALSE]
    /\ UNCHANGED <<nnVars, dnVars, volCur, volPrev, volTmp, volBpFault, volLoad,
                   targetFired>>

\* The disk is usable again. It rejoins at the next DataNode start, or by
\* HotSwapAdd while the DataNode runs.
VolRestore(d, v) ==
    /\ ~volOnline[d][v]
    /\ volOnline' = [volOnline EXCEPT ![d][v] = TRUE]
    /\ UNCHANGED <<nnVars, dnVars, volCur, volPrev, volTmp, volBpFault, volLoad,
                   targetFired>>

\* Scenario 2 (BP-load variant): the next BP-level load of the volume hits a
\* transient I/O fault; its DN-level dir still loads.
VolBpFault(d, v) ==
    /\ dnPc[d] = "down"
    /\ volOnline[d][v]
    /\ ~volBpFault[d][v]
    /\ volBpFault' = [volBpFault EXCEPT ![d][v] = TRUE]
    /\ UNCHANGED <<nnVars, dnVars, volCur, volPrev, volTmp, volOnline, volLoad,
                   targetFired>>

\* Scenario 3: the volume's disk is replaced by an empty one while the
\* DataNode is down. Its next load formats it at that process's nsInfo.cTime
\* (S:735-738; BPSS:167-172, 283-292; DN level DS:283-287).
VolReplace(d, v) ==
    /\ dnPc[d] = "down"
    /\ volCur[d][v] /= NoVer \/ volPrev[d][v] /= NoVer
    /\ volCur' = [volCur EXCEPT ![d][v] = NoVer]
    /\ volPrev' = [volPrev EXCEPT ![d][v] = NoVer]
    /\ volOnline' = [volOnline EXCEPT ![d][v] = TRUE]
    /\ volBpFault' = [volBpFault EXCEPT ![d][v] = FALSE]
    /\ UNCHANGED <<nnVars, dnVars, volTmp, volLoad, targetFired>>

\* Scenario 4: DataNode software with the next DN layout version
\* (DataNodeLayoutVersion.java:37-38) is installed while the DataNode is down.
DNSoftwareUpgrade(d) ==
    /\ dnPc[d] = "down"
    /\ dnSwLV[d] = InitSwLV
    /\ dnSwLV' = [dnSwLV EXCEPT ![d] = NewSwLV]
    /\ UNCHANGED <<nnVars, dnPc, dnOpt, dnNs, dnPending, dnCont, dnRegCT, volVars,
                   targetFired>>

-----------------------------------------------------------------------------
\* Unrestricted next-state relation (no operator procedure, no bounds).
\* Once the target fired, nothing else is explored (adhoc tla-patterns 1).
Next ==
    /\ ~targetFired
    /\ \/ NNStart
       \/ NNStop
       \/ NNRollback
       \/ NNFinalize
       \/ \E ct \in CTime : NNUpgrade(ct)
       \/ \E d \in DN :
            \/ \E opt \in StartOpts : DNStart(d, opt)
            \/ DNHandshake(d, PendingSet(d))
            \/ DNInitDone(d)
            \/ DNRegister(d)
            \/ DNReRegister(d)
            \/ DNFinalize(d)
            \/ DNStop(d)
            \/ DNSoftwareUpgrade(d)
            \/ \E v \in Vol :
                 \/ TargetCheck(d, v)
                 \/ DNLoadVolume(d, v)
                 \/ DNUpgradeContinuation(d, v)
                 \/ HotSwapAdd(d, v)
                 \/ VolOutage(d, v)
                 \/ VolRestore(d, v)
                 \/ VolBpFault(d, v)
                 \/ VolReplace(d, v)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The ad hoc property: the throw at BPSS:621 never executes.
TargetSafe == ~targetFired

\* Structural: variable domains.
TypeOK ==
    /\ nnUp \in BOOLEAN
    /\ nnCur \in CTime \cup {NoCT}
    /\ nnPrev \in CTime \cup {NoCT}
    /\ nnHist \subseteq CTime
    /\ dnPc \in [DN -> DNStates]
    /\ dnOpt \in [DN -> StartOpts]
    /\ dnNs \in [DN -> CTime \cup {NoCT}]
    /\ DOMAIN dnPending = DN
    /\ \A d \in DN : dnPending[d] \in Seq(Vol)
    /\ dnCont \in [DN -> SUBSET Vol]
    /\ dnRegCT \in [DN -> CTime \cup {NoCT}]
    /\ dnSwLV \in [DN -> LVSet]
    /\ volCur \in [DN -> [Vol -> Vers \cup {NoVer}]]
    /\ volPrev \in [DN -> [Vol -> Vers \cup {NoVer}]]
    /\ volTmp \in [DN -> [Vol -> Vers \cup {NoVer}]]
    /\ volOnline \in [DN -> [Vol -> BOOLEAN]]
    /\ volBpFault \in [DN -> [Vol -> BOOLEAN]]
    /\ volLoad \in [DN -> [Vol -> {"none", "dn", "bp"}]]
    /\ targetFired \in BOOLEAN

\* Structural: a DataNode only holds cTimes the NameNode served. The
\* versionRequest reply carries the NN's cTime (RPC:1754-1758); every BP
\* VERSION cTime is written from nsInfo (BPSS:288, 512) or copied by rename.
VolumeCTimesFromNN ==
    \A d \in DN :
        /\ dnNs[d] \in nnHist \cup {NoCT}
        /\ dnRegCT[d] \in nnHist \cup {NoCT}
        /\ \A v \in Vol :
             /\ volCur[d][v].ct \in nnHist \cup {NoCT}
             /\ volPrev[d][v].ct \in nnHist \cup {NoCT}
             /\ volTmp[d][v].ct \in nnHist \cup {NoCT}

\* The guard at BPSS:618-620 is evaluated: the doRollback branch is taken and
\* the read at BPSS:612 succeeds. Used by the non-vacuity probe in MC.tla.
TargetGuardEvaluated(d, v) ==
    /\ TargetEnabled(d, v)
    /\ volPrev[d][v].lv >= SwLV(d)

=============================================================================
