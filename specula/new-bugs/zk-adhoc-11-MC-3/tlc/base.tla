------------------------------- MODULE base -------------------------------
(***************************************************************************)
(* Ad hoc target: can QuorumPeer.loadDataBase() reach the failing branch   *)
(* "The current epoch, x, is older than the last zxid, y" at               *)
(* QuorumPeer.java:1236?                                                   *)
(*                                                                         *)
(* Implementation: Apache ZooKeeper 3.10.0-SNAPSHOT, pinned at eab16599.   *)
(* Category A (distributed / message passing).                             *)
(*                                                                         *)
(* Citations are relative to                                               *)
(* zookeeper-server/src/main/java/org/apache/zookeeper/, with these names: *)
(*   QP   server/quorum/QuorumPeer.java                                    *)
(*   LRN  server/quorum/Learner.java                                       *)
(*   FLW  server/quorum/Follower.java                                      *)
(*   FZK  server/quorum/FollowerZooKeeperServer.java                       *)
(*   LH   server/quorum/LearnerHandler.java                                *)
(*   LDR  server/quorum/Leader.java                                        *)
(*   FLE  server/quorum/FastLeaderElection.java                            *)
(*   ZKS  server/ZooKeeperServer.java                                      *)
(*   ZKD  server/ZKDatabase.java                                           *)
(*   DT   server/DataTree.java                                             *)
(*   FTSL server/persistence/FileTxnSnapLog.java                           *)
(*   AFOS common/AtomicFileOutputStream.java                               *)
(*   AFWI common/AtomicFileWritingIdiom.java                               *)
(*                                                                         *)
(* Deliberate abstractions (brief section 3):                              *)
(*  - FLE is one atomic Elect(Q) / ElectJoin(n, l), keeping the winner     *)
(*    rule (currentEpoch, zxid, sid) of FLE:717-742.                       *)
(*  - Fsync'd commit points are the durability model: a process crash      *)
(*    keeps what reached a commit point. Power loss and partial snapshots  *)
(*    are out of scope (brief 3.2).                                        *)
(*  - No observers, reconfig, admin restore or QA-only properties.         *)
(*  - The first-run default writes (QP:1225, QP:1253) and setAcceptedEpoch *)
(*    are atomic and infallible: a missing currentEpoch makes the guard    *)
(*    false (QP:1215-1225), and acceptedEpoch is not an operand of phi_T.  *)
(***************************************************************************)
EXTENDS Integers, FiniteSets, Sequences, TLC

CONSTANTS
    Server,          \* numeric sids; ties in Elect break on the sid (FLE:738-742)
    MaxEpoch,        \* largest epoch a leader may decide on
    MaxTxnPerEpoch,  \* client txns per epoch (a bound on LeadPropose)
    ForceSnapSync    \* -Dzookeeper.forceSnapshotSync (LH:258, 283-286, 846)

ASSUME /\ IsFiniteSet(Server) /\ Server \subseteq Nat
       /\ MaxEpoch \in Nat /\ MaxTxnPerEpoch \in Nat
       /\ ForceSnapSync \in BOOLEAN

(***************************************************************************)
(* Zxids. The implementation packs (epoch << 32) | counter (ZxidUtils); a  *)
(* base-1000 encoding keeps them in TLC's integer range with the same      *)
(* order. The trace harness uses the same encoding.                        *)
(***************************************************************************)
ZxidBase == 1000
ASSUME MaxTxnPerEpoch < ZxidBase

Zxid(e, c) == e * ZxidBase + c
EpochOf(z) == z \div ZxidBase       \* QP:1212 ZxidUtils.getEpochFromZxid
Low(z)     == z % ZxidBase          \* LH:792 (zxid & 0xffffffffL)

Epochs  == 0..MaxEpoch
AllZxid == {Zxid(e, c) : e \in Epochs, c \in 0..MaxTxnPerEpoch}

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y

IsQuorum(S) == 2 * Cardinality(S) > Cardinality(Server)  \* QuorumMaj

NoFile   == -1       \* the epoch file does not exist (QP:1215)
TmpNone  == -1       \* currentEpoch.tmp does not exist (QP:1231)
TmpEmpty == -2       \* currentEpoch.tmp exists but holds no value (AFOS:59)
NoPeer   == -1
NoEpoch  == -1       \* QP:2301-2302 fields before the first read

(***************************************************************************)
(* Variables                                                               *)
(***************************************************************************)
VARIABLES
    \* -- durable, per peer (survive Crash) -- Scenarios 1, 2, 3
    snapZxid,    \* name zxid of the newest valid snapshot (FileSnap.java:77-117)
    dLog,        \* zxids in the durable txn log (FileTxnLog.java:394-411)
    curFile,     \* <snapDir>/currentEpoch, or NoFile (QP:2304)
    accFile,     \* <snapDir>/acceptedEpoch, or NoFile (QP:2306)
    tmp,         \* <snapDir>/currentEpoch.tmp: TmpNone, TmpEmpty or a value
    \* -- volatile, per peer -- Scenarios 1, 2, 3
    role,        \* "Down", "Starting", "Looking", "Following", "Leading"
    running,     \* QP.running (QP:1682); FALSE once a graceful stop began (S3)
    memZxid,     \* DataTree.lastProcessedZxid (DT:1105-1107)
    memCur,      \* QP.currentEpoch (QP:2302)
    memAcc,      \* QP.acceptedEpoch (QP:2301)
    zkDbInit,    \* ZKDatabase.initialized (ZKD:291); cleared by ZKD.clear (ZKD:191)
    cLog,        \* ZKDatabase.committedLog (ZKD:322; ZKS:1887-1889)
    \* -- split currentEpoch write (AFWI -> AFOS) -- Scenarios 1, 2
    wrStep,      \* "Idle", "ToOpen", "ToFill", "ToRename"
    wrVal,       \* the epoch being written
    wrCtx,       \* whose write: "None", "Learner", "Leader", "Load"
    loadCaller,  \* for wrCtx = "Load": "start" or "elect"
    \* -- learner -- Scenarios 1, 2, 3
    syncMode,    \* QP.syncMode: "NONE", "DIFF", "SNAP", "TRUNC"; sticky (LRN:816, 924)
    lstep,       \* learner program counter, see LearnerSteps
    leaderOf,    \* the leader this peer follows, or NoPeer
    newEpoch,    \* LRN:573 newEpoch of the current sync
    writeToTxnLog, \* LRN:647 local of syncWithLeader
    pNotLogged,  \* LRN:583 packetsNotLogged (a set: it is zxid-ordered FIFO here)
    pCommitted,  \* LRN:582 packetsCommitted
    sockOpen,    \* this peer's socket to the leader (closed locally, LRN:919) (S3)
    connOpen,    \* FALSE once the far end closed; buffered bytes stay readable
    \* -- leader -- sync source of Scenarios 1, 2, 3
    lstate,      \* "Idle", "LoadData", "Discover", "AwaitEpochQuorum",
                 \* "SetEpoch", "AwaitNLAck", "Started"
    lEpoch,      \* LDR.epoch (LDR:1475)
    connecting,  \* LDR.connectingFollowers (LDR:1478)
    electing,    \* LDR.electingFollowers (LDR:1529)
    nlAcked,     \* NEWLEADER ack set (LDR:1644)
    \* -- leader-to-learner channel -- Scenarios 1, 2, 3
    q,           \* per-learner FIFO, LearnerHandler.queuedPackets
    hstep,       \* per-learner LearnerHandler stage, see HandlerSteps
    \* -- the oracle
    targetFired  \* the branch at QP:1236 was taken

diskVars  == <<snapZxid, dLog, curFile, accFile, tmp>>
memVars   == <<role, running, memZxid, memCur, memAcc, zkDbInit, cLog>>
writeVars == <<wrStep, wrVal, wrCtx, loadCaller>>
learnVars == <<syncMode, lstep, leaderOf, newEpoch, writeToTxnLog,
               pNotLogged, pCommitted, sockOpen, connOpen>>
leadVars  == <<lstate, lEpoch, connecting, electing, nlAcked>>
netVars   == <<q, hstep>>
vars == <<diskVars, memVars, writeVars, learnVars, leadVars, netVars, targetFired>>

LearnerSteps == {"Idle", "Register", "AwaitLeaderInfo", "AwaitOp", "SyncLoop",
                 "EpochWrite", "AfterNL", "PostLoop", "Broadcast", "Failed"}
HandlerSteps == {"None", "Info", "AckEpoch", "Synced", "NLQueued", "Done"}
PacketTypes  == {"DIFF", "TRUNC", "SNAP", "PROPOSAL", "COMMIT", "NEWLEADER", "UPTODATE"}

Packet(t, z) == [type |-> t, zxid |-> z]

(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
RECURSIVE ProposalPackets(_), PairPackets(_)
\* LH:1020-1024, LDR:1382-1390: a PROPOSAL per zxid, in zxid order
ProposalPackets(S) ==
    IF S = {} THEN <<>>
    ELSE <<Packet("PROPOSAL", Min(S))>> \o ProposalPackets(S \ {Min(S)})
\* LH:1023-1024: PROPOSAL + COMMIT per committed zxid, in zxid order
PairPackets(S) ==
    IF S = {} THEN <<>>
    ELSE <<Packet("PROPOSAL", Min(S)), Packet("COMMIT", Min(S))>>
         \o PairPackets(S \ {Min(S)})

\* FileSnap.java:77-117 + FTSL:326-377 + DT:1105-1107: restore loads the newest
\* snapshot, then replays every durable txn above it, with no epoch filter
DiskZxid(n) == Max({snapZxid[n]} \cup dLog[n])
\* ZKD:276-279: the playback listener adds replayed txns to the committed log
ReplayedTxns(n) == {z \in dLog[n] : z > snapZxid[n]}

FollowersOf(l) == {f \in Server : role[f] = "Following" /\ leaderOf[f] = l}

\* LDR:1394 addForwardingFollower is reached at LH:925 (syncFollower)
Forwarding(l) ==
    {f \in FollowersOf(l) : hstep[f] \in {"Synced", "NLQueued", "Done"}}

\* LDR:1329 outstandingProposals: proposed in this epoch, not yet applied
Outstanding(l) ==
    IF lstate[l] = "Started"
    THEN {z \in dLog[l] : EpochOf(z) = lEpoch[l] /\ z > memZxid[l]}
    ELSE {}

\* LDR:1471-1483: the epoch is decided once a quorum connected
EpochDecided(l) == lstate[l] \in {"AwaitEpochQuorum", "SetEpoch", "AwaitNLAck", "Started"}
\* LDR:1534 electionFinished
ElectionFinished(l) == lstate[l] \in {"SetEpoch", "AwaitNLAck", "Started"}

(***************************************************************************)
(* Sync decision, LearnerHandler.syncFollower (LH:780-937)                 *)
(***************************************************************************)
\* LH:952-1040 queueCommittedProposals(src, p, _, lastC). op = "NEEDOP" means
\* needOpPacket stayed TRUE, which falls back to a snapshot at LH:930-934.
QueueCommittedProposals(src, p, lastC) ==
    LET ge    == {z \in src : z >= p}
        first == Min(ge)
        prev  == Max({z \in src : z < p} \cup {-1})      \* LH:967-970
        pairs == {z \in src : z > p}
        isNew == Low(p) = 0                              \* LH:952
    IN  IF ge = {}
        THEN IF isNew
             THEN [op |-> "DIFF", opz |-> lastC, pairs |-> {}]   \* LH:1029-1038
             ELSE [op |-> "NEEDOP", opz |-> -1, pairs |-> {}]
        ELSE IF first = p \/ isNew                               \* LH:977, 987
             THEN [op |-> "DIFF", opz |-> lastC, pairs |-> pairs]
             ELSE IF EpochOf(first) /= EpochOf(p)                \* LH:998-1003
                  THEN [op |-> "NEEDOP", opz |-> -1, pairs |-> {}]
                  ELSE [op |-> "TRUNC", opz |-> prev, pairs |-> pairs]  \* LH:1006-1011

\* txnOk: the nondeterministic outcome of the txnlog size limit (LH:878-881;
\* ZKD:365-376, 386-420). FALSE also covers a disabled txnlog sync (ZKD:355).
SyncPlan(l, f, txnOk) ==
    LET cl    == cLog[l]
        lp    == memZxid[l]                              \* LH:804
        p     == memZxid[f]                              \* LH:552 peerLastZxid
        minC  == IF cl = {} THEN lp ELSE Min(cl)         \* LH:815-827
        maxC  == IF cl = {} THEN lp ELSE Max(cl)
        Snap  == [op |-> "SNAP", opz |-> lp, pairs |-> {}]  \* LH:568
        Fallback(r) == IF r.op = "NEEDOP" THEN Snap ELSE r  \* LH:930-934
    IN  IF ForceSnapSync THEN Snap                       \* LH:846-848
        ELSE IF lp = p                                   \* LH:849-857
             THEN [op |-> "DIFF", opz |-> p, pairs |-> {}]
        ELSE IF p > maxC /\ Low(p) /= 0                  \* LH:858-867
             THEN [op |-> "TRUNC", opz |-> maxC, pairs |-> {}]
        ELSE IF maxC >= p /\ minC <= p                   \* LH:868-873
             THEN Fallback(QueueCommittedProposals(cl, p, maxC))
        ELSE IF /\ p < minC                              \* LH:874
                /\ txnOk
                \* ZKD:395-405: the iterator is empty unless the log's first
                \* txn is at or below p, so a peer older than the log gets SNAP
                /\ dLog[l] /= {}
                /\ Min(dLog[l]) <= p
             THEN LET r1 == QueueCommittedProposals({z \in dLog[l] : z <= minC}, p, maxC)
                      queued == Max(r1.pairs \cup {p})
                  IN  IF queued < minC                   \* LH:886-893 gap: revert to SNAP
                      THEN Snap
                      ELSE Fallback([r1 EXCEPT !.pairs = @ \cup {z \in cl : z > queued}])
        ELSE Snap                                        \* LH:908-919

\* LH:920-925 currentZxid handed to startForwarding
SyncCurrentZxid(l, f, plan) ==
    IF plan.op = "SNAP" THEN memZxid[l]
    ELSE IF plan.op = "TRUNC" /\ plan.pairs = {} /\ memZxid[f] > plan.opz
         THEN plan.opz                                   \* LH:865
         ELSE Max(plan.pairs \cup {memZxid[f]})

(***************************************************************************)
(* Init: fresh, empty disks, all peers down.                               *)
(* FTSL:297-303 writes snapshot.0 at the first restore; snapZxid = 0 here  *)
(* stands for it, since no guard distinguishes the two.                    *)
(***************************************************************************)
Init ==
    /\ snapZxid = [n \in Server |-> 0]
    /\ dLog     = [n \in Server |-> {}]
    /\ curFile  = [n \in Server |-> NoFile]
    /\ accFile  = [n \in Server |-> NoFile]
    /\ tmp      = [n \in Server |-> TmpNone]
    /\ role     = [n \in Server |-> "Down"]
    /\ running  = [n \in Server |-> TRUE]
    /\ memZxid  = [n \in Server |-> 0]
    /\ memCur   = [n \in Server |-> NoEpoch]
    /\ memAcc   = [n \in Server |-> NoEpoch]
    /\ zkDbInit = [n \in Server |-> FALSE]
    /\ cLog     = [n \in Server |-> {}]
    /\ wrStep   = [n \in Server |-> "Idle"]
    /\ wrVal    = [n \in Server |-> -1]
    /\ wrCtx    = [n \in Server |-> "None"]
    /\ loadCaller = [n \in Server |-> "None"]
    /\ syncMode = [n \in Server |-> "NONE"]
    /\ lstep    = [n \in Server |-> "Idle"]
    /\ leaderOf = [n \in Server |-> NoPeer]
    /\ newEpoch = [n \in Server |-> NoEpoch]
    /\ writeToTxnLog = [n \in Server |-> FALSE]
    /\ pNotLogged = [n \in Server |-> {}]
    /\ pCommitted = [n \in Server |-> {}]
    /\ sockOpen = [n \in Server |-> TRUE]
    /\ connOpen = [n \in Server |-> TRUE]
    /\ lstate   = [n \in Server |-> "Idle"]
    /\ lEpoch   = [n \in Server |-> NoEpoch]
    /\ connecting = [n \in Server |-> {}]
    /\ electing = [n \in Server |-> {}]
    /\ nlAcked  = [n \in Server |-> {}]
    /\ q        = [n \in Server |-> <<>>]
    /\ hstep    = [n \in Server |-> "None"]
    /\ targetFired = FALSE

(***************************************************************************)
(* TargetCheck: QuorumPeer.loadDataBase (QP:1206-1265).                    *)
(*                                                                         *)
(* caller "start" is QP:1194 (failure exits the process,                   *)
(* QuorumPeerMain.java:113-116); caller "elect" is getLastLoggedZxid       *)
(* (QP:1386-1388) from FLE:938 -> FLE:865, where failure is caught at      *)
(* QP:1586-1589 and zkDb stays initialized (ZKD:291).                      *)
(***************************************************************************)
\* After the load: the caller's continuation. ok = FALSE is a load failure
\* other than the target (QP:1262-1263).
AfterLoad(n, caller, ok) ==
    role' = [role EXCEPT ![n] =
                IF caller = "start"
                THEN IF ok THEN "Looking" ELSE "Down"   \* QP:1201; QuorumPeerMain:113-116
                ELSE "Looking"]                         \* QP:1586-1589

\* QP:1241-1260 the acceptedEpoch half of the method. e = epochOfZxid.
LoadContinue(n, caller, e, c) ==
    LET a == IF accFile[n] = NoFile THEN e ELSE accFile[n]   \* QP:1241-1254
    IN  /\ memAcc'  = [memAcc EXCEPT ![n] = a]
        /\ accFile' = [accFile EXCEPT ![n] = a]              \* QP:1253
        /\ AfterLoad(n, caller, a >= c)                      \* QP:1255 not the target

TargetCheck(n, caller) ==
    LET loaded == DiskZxid(n)                   \* QP:1208, 1211
        e      == EpochOf(loaded)               \* QP:1212
        c      == IF curFile[n] = NoFile        \* QP:1214-1225
                  THEN e ELSE curFile[n]
    IN
    /\ memZxid'  = [memZxid EXCEPT ![n] = loaded]
    /\ cLog'     = [cLog EXCEPT ![n] = ReplayedTxns(n)]
    /\ zkDbInit' = [zkDbInit EXCEPT ![n] = TRUE]     \* ZKD:291, before the check
    /\ memCur'   = [memCur EXCEPT ![n] = c]          \* QP:1214 or QP:1221
    /\ UNCHANGED <<snapZxid, dLog, running, learnVars, leadVars, netVars>>
    /\ IF e > c /\ tmp[n] = TmpNone                  \* QP:1227, QP:1231 false
       THEN \* QP:1236 throw new IOException("The current epoch, ...")
            /\ targetFired' = TRUE
            /\ UNCHANGED <<curFile, accFile, tmp, role, memAcc, writeVars>>
       ELSE
       /\ targetFired' = targetFired
       /\ IF e > c /\ tmp[n] = TmpEmpty
          THEN \* QP:1232 -> QP:2294-2295 "Found null": a failure, not the target
               /\ AfterLoad(n, caller, FALSE)
               /\ UNCHANGED <<curFile, accFile, tmp, memAcc, writeVars>>
          ELSE IF e > c
          THEN \* QP:1231-1234 fallback: setCurrentEpoch(epochOfTmp), the same
               \* non-atomic write as any other. epochOfTmp is not compared to e.
               /\ wrStep' = [wrStep EXCEPT ![n] = "ToOpen"]
               /\ wrVal'  = [wrVal EXCEPT ![n] = tmp[n]]
               /\ wrCtx'  = [wrCtx EXCEPT ![n] = "Load"]
               /\ loadCaller' = [loadCaller EXCEPT ![n] = caller]
               /\ role'   = [role EXCEPT ![n] = IF caller = "start" THEN "Starting" ELSE @]
               /\ UNCHANGED <<curFile, accFile, tmp, memAcc>>
          ELSE \* QP:1227 false
               /\ curFile' = [curFile EXCEPT ![n] = c]    \* QP:1225 default on a missing file
               /\ tmp'     = [tmp EXCEPT ![n] =
                                 IF curFile[n] = NoFile THEN TmpNone ELSE @]
               /\ LoadContinue(n, caller, e, c)
               /\ UNCHANGED writeVars

\* QP:1194 QuorumPeer.start. Not a fault: a late Start is the lagging learner.
Start(n) ==
    /\ role[n] = "Down"
    /\ TargetCheck(n, "start")

\* QP:1585 -> FLE:938 -> FLE:865 -> QP:1387-1388. Scenario 2: the reload that
\* follows the SNAP-mode clear. Elect stays disabled until it ran.
ElectReload(n) ==
    /\ role[n] = "Looking"
    /\ running[n]
    /\ ~zkDbInit[n]
    /\ wrStep[n] = "Idle"
    /\ TargetCheck(n, "elect")

(***************************************************************************)
(* Epoch write: QP:2340-2344 -> QP:2316-2324 -> AFWI:57-89 -> AFOS:55-106  *)
(* One step per crash-visible disk state. Scenarios 1, 2.                  *)
(***************************************************************************)
\* AFOS:59 new FileOutputStream truncates or creates the tmp
EpochTmpOpen(n) ==
    /\ wrStep[n] = "ToOpen"
    /\ tmp' = [tmp EXCEPT ![n] = TmpEmpty]
    /\ wrStep' = [wrStep EXCEPT ![n] = "ToFill"]
    /\ UNCHANGED <<snapZxid, dLog, curFile, accFile, memVars, wrVal, wrCtx,
                   loadCaller, learnVars, leadVars, netVars>>

\* AFWI:71-72 bw.flush, AFOS:79-80 flush and fsync
EpochTmpFill(n) ==
    /\ wrStep[n] = "ToFill"
    /\ tmp' = [tmp EXCEPT ![n] = wrVal[n]]
    /\ wrStep' = [wrStep EXCEPT ![n] = "ToRename"]
    /\ UNCHANGED <<snapZxid, dLog, curFile, accFile, memVars, wrVal, wrCtx,
                   loadCaller, learnVars, leadVars, netVars>>

WriteDone(n) ==
    /\ wrStep' = [wrStep EXCEPT ![n] = "Idle"]
    /\ wrVal'  = [wrVal EXCEPT ![n] = -1]
    /\ wrCtx'  = [wrCtx EXCEPT ![n] = "None"]
    /\ loadCaller' = [loadCaller EXCEPT ![n] = "None"]

RenameCommit(n) ==                         \* AFOS:87 rename; QP:2342 memory
    /\ curFile' = [curFile EXCEPT ![n] = wrVal[n]]
    /\ tmp'     = [tmp EXCEPT ![n] = TmpNone]
    /\ memCur'  = [memCur EXCEPT ![n] = wrVal[n]]
    /\ WriteDone(n)

\* Learner: LRN:813-819 setCurrentEpoch, then syncMode NONE, then the NEWLEADER ack
EpochRenameLearner(f) ==
    /\ wrStep[f] = "ToRename"
    /\ wrCtx[f] = "Learner"
    /\ RenameCommit(f)
    /\ syncMode' = [syncMode EXCEPT ![f] = "NONE"]              \* LRN:816
    /\ lstep' = [lstep EXCEPT ![f] =
                    IF sockOpen[f] THEN "AfterNL" ELSE "Failed"] \* LRN:819 write throws
    /\ nlAcked' = IF sockOpen[f] /\ connOpen[f]                  \* LDR:1636-1644
                  THEN [nlAcked EXCEPT ![leaderOf[f]] = @ \cup {f}]
                  ELSE nlAcked
    /\ UNCHANGED <<snapZxid, dLog, accFile, role, running, memZxid, memAcc, zkDbInit,
                   cLog, leaderOf, newEpoch, writeToTxnLog, pNotLogged, pCommitted,
                   sockOpen, connOpen, lstate, lEpoch, connecting, electing, netVars>>

\* Leader: LDR:711, before any epoch-E data exists (LDR:741, 1609)
EpochRenameLeader(l) ==
    /\ wrStep[l] = "ToRename"
    /\ wrCtx[l] = "Leader"
    /\ RenameCommit(l)
    /\ lstate' = [lstate EXCEPT ![l] = "AwaitNLAck"]
    /\ UNCHANGED <<snapZxid, dLog, accFile, role, running, memZxid, memAcc, zkDbInit,
                   cLog, learnVars, lEpoch, connecting, electing, nlAcked, netVars>>

\* Load: QP:1234 then the acceptedEpoch half
EpochRenameLoad(n) ==
    /\ wrStep[n] = "ToRename"
    /\ wrCtx[n] = "Load"
    /\ curFile' = [curFile EXCEPT ![n] = wrVal[n]]
    /\ tmp'     = [tmp EXCEPT ![n] = TmpNone]
    /\ memCur'  = [memCur EXCEPT ![n] = wrVal[n]]
    /\ WriteDone(n)
    /\ LoadContinue(n, loadCaller[n], EpochOf(memZxid[n]), wrVal[n])
    /\ UNCHANGED <<snapZxid, dLog, running, memZxid, zkDbInit, cLog,
                   learnVars, leadVars, netVars>>

EpochRename(n) ==
    \/ EpochRenameLearner(n)
    \/ EpochRenameLeader(n)
    \/ EpochRenameLoad(n)

(***************************************************************************)
(* LDR.shutdown (LDR:861-892) and the end of lead() (QP:1630-1637).        *)
(* zk.shutdown() there is shutdown(false): ZKS:922-948 fast-forwards only  *)
(* a zk that was running (ZKS:218, 903-905).                               *)
(***************************************************************************)
LeaderStepDown(l) ==
    LET F == FollowersOf(l)
        started == lstate[l] = "Started"
    IN
    /\ role'    = [role EXCEPT ![l] = "Looking"]                \* QP:1637
    /\ memZxid' = [memZxid EXCEPT ![l] =
                     IF started THEN Max({@} \cup dLog[l]) ELSE @]  \* ZKS:928-941
    /\ cLog'    = [cLog EXCEPT ![l] =
                     IF started THEN @ \cup {z \in dLog[l] : z > memZxid[l]} ELSE @]
    /\ lstate'  = [lstate EXCEPT ![l] = "Idle"]
    /\ lEpoch'  = [lEpoch EXCEPT ![l] = NoEpoch]
    /\ connecting' = [connecting EXCEPT ![l] = {}]
    /\ electing'   = [electing EXCEPT ![l] = {}]
    /\ nlAcked'    = [nlAcked EXCEPT ![l] = {}]
    \* LDR:885-888 f.shutdown closes each learner socket; a learner reads what
    \* was already buffered, then fails (FLW:126-132)
    /\ connOpen' = [f \in Server |-> IF f \in F THEN FALSE ELSE connOpen[f]]
    /\ hstep'    = [f \in Server |-> IF f \in F THEN "None" ELSE hstep[f]]

(***************************************************************************)
(* Epoch write faults. Scenario 2.                                         *)
(***************************************************************************)
\* An IOException out of setCurrentEpoch, by owner of the write
OnWriteFailure(n) ==
    CASE wrCtx[n] = "Learner" ->       \* LRN:813 -> FLW:126
            /\ lstep' = [lstep EXCEPT ![n] = "Failed"]
            /\ UNCHANGED <<role, memZxid, cLog, leadVars, connOpen, hstep>>
      [] wrCtx[n] = "Leader" ->        \* LDR:711 -> QP:1630-1637
            /\ LeaderStepDown(n)
            /\ UNCHANGED lstep
      [] wrCtx[n] = "Load" ->          \* QP:1234 -> QP:1262-1263
            /\ AfterLoad(n, loadCaller[n], FALSE)
            /\ UNCHANGED <<memZxid, cLog, leadVars, connOpen, hstep, lstep>>

\* Failure before the rename.
\*  - Open fails (AFOS:59): nothing was opened, any stale tmp stays.
\*  - Write or flush fails (AFWI:79-87 -> AFOS:112-122) or flush, fsync or
\*    close fails inside close() (AFOS:94-103): the tmp is deleted.
EpochWriteFail(n) ==
    /\ wrStep[n] \in {"ToOpen", "ToFill", "ToRename"}
    /\ tmp' = [tmp EXCEPT ![n] = IF wrStep[n] = "ToOpen" THEN @ ELSE TmpNone]
    /\ WriteDone(n)
    /\ OnWriteFailure(n)
    /\ UNCHANGED <<snapZxid, dLog, curFile, accFile, running, memCur, memAcc, zkDbInit,
                   syncMode, leaderOf, newEpoch, writeToTxnLog, pNotLogged, pCommitted,
                   sockOpen, q>>

\* Failure of the rename itself (AFOS:86-92): the tmp survives. If delete(orig)
\* succeeded before the second rename failed, currentEpoch is missing too.
EpochRenameFail(n) ==
    /\ wrStep[n] = "ToRename"
    /\ curFile' \in {curFile, [curFile EXCEPT ![n] = NoFile]}
    /\ WriteDone(n)
    /\ OnWriteFailure(n)
    /\ UNCHANGED <<snapZxid, dLog, accFile, tmp, running, memCur, memAcc, zkDbInit,
                   syncMode, leaderOf, newEpoch, writeToTxnLog, pNotLogged, pCommitted,
                   sockOpen, q>>

(***************************************************************************)
(* Abstract election. FLE:717-742 orders votes (currentEpoch, zxid, sid);  *)
(* FLE:876 reads the vote's epoch from QP.currentEpoch.                    *)
(***************************************************************************)
Better(a, b) ==   \* FLE:738-742 totalOrderPredicate
    \/ memCur[a] > memCur[b]
    \/ /\ memCur[a] = memCur[b]
       /\ \/ memZxid[a] > memZxid[b]
          \/ memZxid[a] = memZxid[b] /\ a > b

Winner(Q) == CHOOSE w \in Q : \A o \in Q \ {w} : Better(w, o)

CanVote(n) ==
    /\ role[n] = "Looking"
    /\ running[n]
    /\ zkDbInit[n]                \* FLE:938 ran getLastLoggedZxid (ElectReload)
    /\ wrStep[n] = "Idle"

\* FLE:985, 1056: a majority of LOOKING peers agrees on the best vote among them
Elect(Q) ==
    LET w == Winner(Q) IN
    /\ IsQuorum(Q)
    /\ \A n \in Q : CanVote(n)
    /\ role'     = [n \in Server |-> IF n = w THEN "Leading"
                                     ELSE IF n \in Q THEN "Following" ELSE role[n]]
    /\ leaderOf' = [n \in Server |-> IF n \in Q \ {w} THEN w ELSE leaderOf[n]]
    /\ lstep'    = [n \in Server |-> IF n \in Q \ {w} THEN "Register" ELSE lstep[n]]
    /\ lstate'   = [lstate EXCEPT ![w] = "LoadData"]
    /\ UNCHANGED <<diskVars, running, memZxid, memCur, memAcc, zkDbInit, cLog, writeVars,
                   syncMode, newEpoch, writeToTxnLog, pNotLogged, pCommitted, sockOpen,
                   connOpen, lEpoch, connecting, electing, nlAcked, netVars>>

\* FLE:1140-1175: a late peer learns the leader from a quorum of FOLLOWING and
\* LEADING notifications, whatever its own vote. This is how the lagging learner
\* of Scenarios 1-3 joins.
ElectJoin(n, l) ==
    /\ n /= l
    /\ CanVote(n)
    /\ role[l] = "Leading"
    /\ IsQuorum({l} \cup FollowersOf(l))
    /\ role'     = [role EXCEPT ![n] = "Following"]
    /\ leaderOf' = [leaderOf EXCEPT ![n] = l]
    /\ lstep'    = [lstep EXCEPT ![n] = "Register"]
    /\ UNCHANGED <<diskVars, running, memZxid, memCur, memAcc, zkDbInit, cLog, writeVars,
                   syncMode, newEpoch, writeToTxnLog, pNotLogged, pCommitted, sockOpen,
                   connOpen, leadVars, netVars>>

(***************************************************************************)
(* Leader establishment: Leader.lead (LDR:632-741)                         *)
(***************************************************************************)
\* LDR:646 zk.loadData: zkDb is initialized, so no reload (ZKS:539-540), then a
\* clean snapshot of memory (ZKS:551). LDR:653 starts accepting learners and
\* LDR:655 proposes epoch = acceptedEpoch + 1 (LDR:1474-1475).
LeadLoadData(l) ==
    /\ role[l] = "Leading"
    /\ lstate[l] = "LoadData"
    /\ snapZxid' = [snapZxid EXCEPT ![l] = Max({@, memZxid[l]})]
    /\ lEpoch'   = [lEpoch EXCEPT ![l] = memAcc[l] + 1]
    /\ connecting' = [connecting EXCEPT ![l] = {l}]             \* LDR:1478
    /\ lstate'   = [lstate EXCEPT ![l] = "Discover"]
    /\ UNCHANGED <<dLog, curFile, accFile, tmp, memVars, writeVars, learnVars,
                   electing, nlAcked, netVars>>

\* LDR:1481-1484: a connected quorum containing the leader fixes the epoch
LeadGetEpochToPropose(l) ==
    /\ role[l] = "Leading"
    /\ lstate[l] = "Discover"
    /\ IsQuorum(connecting[l])
    /\ lEpoch[l] <= MaxEpoch        \* model bound
    /\ accFile' = [accFile EXCEPT ![l] = lEpoch[l]]             \* LDR:1483
    /\ memAcc'  = [memAcc EXCEPT ![l] = lEpoch[l]]
    /\ lstate'  = [lstate EXCEPT ![l] = "AwaitEpochQuorum"]
    /\ UNCHANGED <<snapZxid, dLog, curFile, tmp, role, running, memZxid, memCur, zkDbInit,
                   cLog, writeVars, learnVars, lEpoch, connecting, electing, nlAcked, netVars>>

\* LDR:710 -> LDR:1533-1535, then LDR:711 begins the epoch write
LeadWaitForEpochAck(l) ==
    /\ role[l] = "Leading"
    /\ lstate[l] = "AwaitEpochQuorum"
    /\ IsQuorum(electing[l] \cup {l})
    /\ lstate' = [lstate EXCEPT ![l] = "SetEpoch"]
    /\ wrStep' = [wrStep EXCEPT ![l] = "ToOpen"]
    /\ wrVal'  = [wrVal EXCEPT ![l] = lEpoch[l]]
    /\ wrCtx'  = [wrCtx EXCEPT ![l] = "Leader"]
    /\ UNCHANGED <<diskVars, memVars, loadCaller, learnVars, lEpoch, connecting,
                   electing, nlAcked, netVars>>

\* LDR:716 waitForNewLeaderAck, then startZkServer (LDR:741): zk.startup
\* (LDR:1599), then lastProcessedZxid := (E, 0) (LDR:1609)
LeadStartZkServer(l) ==
    /\ role[l] = "Leading"
    /\ lstate[l] = "AwaitNLAck"
    /\ IsQuorum(nlAcked[l] \cup {l})
    /\ lstate'  = [lstate EXCEPT ![l] = "Started"]
    /\ memZxid' = [memZxid EXCEPT ![l] = Zxid(lEpoch[l], 0)]
    /\ UNCHANGED <<diskVars, role, running, memCur, memAcc, zkDbInit, cLog, writeVars,
                   learnVars, lEpoch, connecting, electing, nlAcked, netVars>>

\* LDR:1295-1331 Leader.propose: one client txn, on the leader's log and to
\* every forwarding follower. Split from LeadCommit because the code keeps them
\* apart: outstanding PROPOSALs are what LRN:841 logs without a COMMIT, and what
\* makes TRUNC reachable.
LeadPropose(l) ==
    LET e    == lEpoch[l]
        last == Max({Zxid(e, 0)} \cup {z \in dLog[l] : EpochOf(z) = e})
        z    == last + 1
        F    == Forwarding(l)
    IN
    /\ role[l] = "Leading"
    /\ lstate[l] = "Started"
    /\ running[l]
    /\ Low(last) < MaxTxnPerEpoch    \* model bound
    /\ dLog' = [dLog EXCEPT ![l] = @ \cup {z}]
    /\ q'    = [f \in Server |-> IF f \in F THEN Append(q[f], Packet("PROPOSAL", z)) ELSE q[f]]
    /\ UNCHANGED <<snapZxid, curFile, accFile, tmp, memVars, writeVars, learnVars,
                   leadVars, hstep>>

\* LDR:970-1033 tryToCommit: in order (LDR:978), on a quorum of acks (LDR:985).
\* A learner's ack follows its durable log write (SyncRequestProcessor ->
\* SendAckRequestProcessor), so the ack set is read from dLog.
LeadCommit(l) ==
    LET out == Outstanding(l)
        z   == Min(out)
        F   == Forwarding(l)
    IN
    /\ role[l] = "Leading"
    /\ running[l]
    /\ out /= {}
    /\ IsQuorum({n \in Server : z \in dLog[n]})
    /\ memZxid' = [memZxid EXCEPT ![l] = z]                     \* DT:1105-1107
    /\ cLog'    = [cLog EXCEPT ![l] = @ \cup {z}]               \* ZKS:1887-1889
    /\ q'       = [f \in Server |-> IF f \in F THEN Append(q[f], Packet("COMMIT", z)) ELSE q[f]]
    /\ UNCHANGED <<diskVars, role, running, memCur, memAcc, zkDbInit, writeVars,
                   learnVars, leadVars, hstep>>

(***************************************************************************)
(* Sync source: LearnerHandler.run (LH:520-653)                            *)
(***************************************************************************)
\* LH:556 syncFollower (incl. LH:925 startForwarding, LDR:1367-1400), and for a
\* snapshot LH:568-578. A SNAP carries lastProcessedZxid, which is >= (E, 0) once
\* the leader started (LDR:1609).
LearnerHandlerSyncFollower(l, f) ==
    /\ f \in FollowersOf(l)
    /\ hstep[f] = "AckEpoch"
    /\ ElectionFinished(l)                        \* LH:550 -> LDR:1517
    /\ \E txnOk \in BOOLEAN :
        LET plan == SyncPlan(l, f, txnOk)
            cur  == SyncCurrentZxid(l, f, plan)
        IN  q' = [q EXCEPT ![f] =
                    (<<Packet(plan.op, plan.opz)>> \o PairPackets(plan.pairs))
                    \o ProposalPackets({z \in Outstanding(l) : z > cur})]  \* LDR:1382-1390
    /\ hstep' = [hstep EXCEPT ![f] = "Synced"]
    /\ UNCHANGED <<diskVars, memVars, writeVars, learnVars, leadVars>>

\* LH:604-605 NEWLEADER is queued after the sync packets
LearnerHandlerSendNewLeader(l, f) ==
    /\ f \in FollowersOf(l)
    /\ hstep[f] = "Synced"
    /\ q' = [q EXCEPT ![f] = Append(@, Packet("NEWLEADER", Zxid(lEpoch[l], 0)))]
    /\ hstep' = [hstep EXCEPT ![f] = "NLQueued"]
    /\ UNCHANGED <<diskVars, memVars, writeVars, learnVars, leadVars>>

\* LH:628 (the ack was read), LH:646 waitForStartup, LH:653 UPTODATE
LearnerHandlerSendUpToDate(l, f) ==
    /\ f \in FollowersOf(l)
    /\ hstep[f] = "NLQueued"
    /\ f \in nlAcked[l]
    /\ lstate[l] = "Started"
    /\ q' = [q EXCEPT ![f] = Append(@, Packet("UPTODATE", -1))]
    /\ hstep' = [hstep EXCEPT ![f] = "Done"]
    /\ UNCHANGED <<diskVars, memVars, writeVars, learnVars, leadVars>>

(***************************************************************************)
(* Learner: registerWithLeader (LRN:486-540), syncWithLeader (LRN:570-872) *)
(***************************************************************************)
\* LRN:490 getLastLoggedZxid does not reload here: a participant only reaches
\* FOLLOWING through FLE:938, which initialized zkDb, and nothing clears it in
\* between. LRN:504 FOLLOWERINFO carries acceptedEpoch; LH:525 -> LDR:1474-1478.
RegisterWithLeader(f) ==
    LET l == leaderOf[f] IN
    /\ role[f] = "Following"
    /\ lstep[f] = "Register"
    /\ sockOpen[f] /\ connOpen[f]
    /\ lstate[l] /= "LoadData"                     \* LDR:653 not accepting yet
    /\ connecting' = [connecting EXCEPT ![l] = @ \cup {f}]
    /\ lEpoch' = [lEpoch EXCEPT ![l] =             \* LDR:1471-1476
                    IF lstate[l] = "Discover" /\ memAcc[f] >= @ THEN memAcc[f] + 1 ELSE @]
    /\ lstep' = [lstep EXCEPT ![f] = "AwaitLeaderInfo"]
    /\ hstep' = [hstep EXCEPT ![f] = "Info"]
    /\ UNCHANGED <<diskVars, memVars, writeVars, syncMode, leaderOf, newEpoch, writeToTxnLog,
                   pNotLogged, pCommitted, sockOpen, connOpen, lstate, electing, nlAcked, q>>

\* LRN:505-529 LEADERINFO and ACKEPOCH, with the handler's processing of the ack
\* (LH:537-550 -> LDR:1515-1530).
ReceiveLeaderInfo(f) ==
    LET l  == leaderOf[f]
        e  == lEpoch[l]
        \* LRN:512-520: an ack of -1 does not count for the new epoch
        ack == IF e > memAcc[f] THEN memCur[f] ELSE -1
        \* LDR:1521 isMoreRecentThan(leaderStateSummary), only until LDR:1517
        ahead == /\ ~ElectionFinished(l)
                 /\ ack /= -1
                 /\ \/ ack > memCur[l]
                    \/ ack = memCur[l] /\ memZxid[f] > memZxid[l]
    IN
    /\ role[f] = "Following"
    /\ lstep[f] = "AwaitLeaderInfo"
    /\ sockOpen[f] /\ connOpen[f]
    /\ EpochDecided(l)                              \* LH:525 blocks until then
    /\ IF e < memAcc[f]
       THEN \* LRN:522 "Leaders epoch, x, is less than accepted epoch"
            /\ lstep' = [lstep EXCEPT ![f] = "Failed"]
            /\ UNCHANGED <<accFile, memAcc, newEpoch, hstep, connOpen, electing>>
       ELSE
       /\ accFile' = [accFile EXCEPT ![f] = IF e > memAcc[f] THEN e ELSE @]  \* LRN:514
       /\ memAcc'  = [memAcc EXCEPT ![f] = IF e > memAcc[f] THEN e ELSE @]
       /\ newEpoch' = [newEpoch EXCEPT ![f] = e]    \* LRN:573
       /\ lstep' = [lstep EXCEPT ![f] = "AwaitOp"]
       /\ IF ahead
          THEN \* LDR:1522 IOException in the handler, which closes the socket
               /\ connOpen' = [connOpen EXCEPT ![f] = FALSE]
               /\ hstep'    = [hstep EXCEPT ![f] = "None"]
               /\ UNCHANGED electing
          ELSE /\ hstep'    = [hstep EXCEPT ![f] = "AckEpoch"]
               /\ electing' = [electing EXCEPT ![l] =
                                 IF ~ElectionFinished(l) /\ ack /= -1
                                 THEN @ \cup {f} ELSE @]                     \* LDR:1529
               /\ UNCHANGED connOpen
    /\ UNCHANGED <<snapZxid, dLog, curFile, tmp, role, running, memZxid, memCur, zkDbInit,
                   cLog, writeVars, syncMode, leaderOf, writeToTxnLog, pNotLogged,
                   pCommitted, sockOpen, lstate, lEpoch, connecting, nlAcked, q>>

\* LRN:581-628 the first packet, outside the while loop
ReadSyncOp(f) ==
    LET p == Head(q[f]) IN
    /\ role[f] = "Following"
    /\ lstep[f] = "AwaitOp"
    /\ sockOpen[f]
    /\ q[f] /= <<>>
    /\ p.type \in {"DIFF", "SNAP", "TRUNC"}
    /\ q' = [q EXCEPT ![f] = Tail(@)]
    /\ lstep' = [lstep EXCEPT ![f] = "SyncLoop"]
    /\ syncMode' = [syncMode EXCEPT ![f] = p.type]     \* LRN:588, 597, 620
    /\ CASE p.type = "DIFF" ->                         \* LRN:586-595
              \* LRN:589 forced snapshot needs zookeeper.snapshot.trust.empty and
              \* no snapshot (FTSL:237-239): not the case here (brief 3.2)
              /\ writeToTxnLog' = [writeToTxnLog EXCEPT ![f] = TRUE]   \* LRN:647
              /\ UNCHANGED <<dLog, memZxid, cLog>>
         [] p.type = "SNAP" ->                         \* LRN:596-616
              /\ writeToTxnLog' = [writeToTxnLog EXCEPT ![f] = FALSE]
              /\ memZxid' = [memZxid EXCEPT ![f] = p.zxid]     \* LRN:614
              /\ cLog'    = [cLog EXCEPT ![f] = {}]            \* LRN:601 -> ZKD:191
              /\ UNCHANGED dLog
         [] p.type = "TRUNC" ->                        \* LRN:618-628 -> ZKD:611-623
              \* FTSL:513-531 truncates only the log: newer snapshots stay
              /\ writeToTxnLog' = [writeToTxnLog EXCEPT ![f] = FALSE]
              /\ dLog' = [dLog EXCEPT ![f] = {z \in @ : z <= p.zxid}]
              /\ cLog' = [cLog EXCEPT ![f] =
                            {z \in dLog[f] : z <= p.zxid /\ z > snapZxid[f]}]
              /\ memZxid' = [memZxid EXCEPT ![f] = p.zxid]     \* LRN:628
    /\ UNCHANGED <<snapZxid, curFile, accFile, tmp, role, running, memCur, memAcc, zkDbInit,
                   writeVars, leaderOf, newEpoch, pNotLogged, pCommitted, sockOpen, connOpen,
                   leadVars, hstep>>

\* LRN:654-669. enforceContinuousProposal only warns on an epoch jump (LRN:546-558).
SyncRecvProposal(f) ==
    /\ role[f] = "Following"
    /\ lstep[f] \in {"SyncLoop", "AfterNL"}
    /\ running[f]                                      \* LRN:651
    /\ sockOpen[f]
    /\ q[f] /= <<>>
    /\ Head(q[f]).type = "PROPOSAL"
    /\ pNotLogged' = [pNotLogged EXCEPT ![f] = @ \cup {Head(q[f]).zxid}]   \* LRN:668
    /\ q' = [q EXCEPT ![f] = Tail(@)]
    /\ UNCHANGED <<diskVars, memVars, writeVars, syncMode, lstep, leaderOf, newEpoch,
                   writeToTxnLog, pCommitted, sockOpen, connOpen, leadVars, hstep>>

\* LRN:670-696
SyncRecvCommit(f) ==
    LET z == Head(q[f]).zxid
        nl == pNotLogged[f]
    IN
    /\ role[f] = "Following"
    /\ lstep[f] \in {"SyncLoop", "AfterNL"}
    /\ running[f]
    /\ sockOpen[f]
    /\ q[f] /= <<>>
    /\ Head(q[f]).type = "COMMIT"
    /\ q' = [q EXCEPT ![f] = Tail(@)]
    /\ IF writeToTxnLog[f]
       THEN \* LRN:693-695 remembered for NEWLEADER or for after the loop
            /\ pCommitted' = [pCommitted EXCEPT ![f] = @ \cup {z}]
            /\ UNCHANGED <<memZxid, cLog, pNotLogged, lstep>>
       ELSE IF nl = {}
       THEN \* LRN:672-673 pif.hdr on a null pif: caught at FLW:126
            /\ lstep' = [lstep EXCEPT ![f] = "Failed"]
            /\ UNCHANGED <<memZxid, cLog, pNotLogged, pCommitted>>
       ELSE IF Min(nl) = z
       THEN \* LRN:690-691 applied in memory only
            /\ memZxid' = [memZxid EXCEPT ![f] = Max({@, z})]   \* DT:1105-1107
            /\ cLog'    = [cLog EXCEPT ![f] = @ \cup {z}]       \* ZKS:1887-1889
            /\ pNotLogged' = [pNotLogged EXCEPT ![f] = @ \ {z}]
            /\ UNCHANGED <<pCommitted, lstep>>
       ELSE UNCHANGED <<memZxid, cLog, pNotLogged, pCommitted, lstep>>  \* LRN:684-688
    /\ UNCHANGED <<diskVars, role, running, memCur, memAcc, zkDbInit, writeVars, syncMode,
                   leaderOf, newEpoch, writeToTxnLog, sockOpen, connOpen, leadVars, hstep>>

\* LRN:746-808 the NEWLEADER handler up to the epoch write: the synced history
\* becomes durable BEFORE currentEpoch.tmp exists. The window of Scenarios 1, 2
\* is open from the end of this step until EpochTmpOpen.
NLPersist(f) ==
    LET snapshotNeeded == syncMode[f] \in {"SNAP", "TRUNC"}    \* LRN:579, 589-595
        toPersist == pCommitted[f] \cap pNotLogged[f]          \* LRN:785-800
    IN
    /\ role[f] = "Following"
    /\ lstep[f] = "SyncLoop"
    /\ running[f]
    /\ sockOpen[f]
    /\ q[f] /= <<>>
    /\ Head(q[f]).type = "NEWLEADER"
    /\ q' = [q EXCEPT ![f] = Tail(@)]
    \* LRN:759-761 takeSnapshot, named by memory (FTSL:478-479)
    /\ snapZxid' = [snapZxid EXCEPT ![f] =
                      IF snapshotNeeded THEN Max({@, memZxid[f]}) ELSE @]
    \* LRN:798 appendRequest, LRN:799 processTxn, LRN:804 commit (flush and fsync)
    /\ dLog'    = [dLog EXCEPT ![f] = @ \cup toPersist]
    /\ memZxid' = [memZxid EXCEPT ![f] = Max({@} \cup toPersist)]
    /\ cLog'    = [cLog EXCEPT ![f] = @ \cup toPersist]
    /\ pNotLogged' = [pNotLogged EXCEPT ![f] = @ \ toPersist]
    /\ pCommitted' = [pCommitted EXCEPT ![f] = {}]
    /\ writeToTxnLog' = [writeToTxnLog EXCEPT ![f] = TRUE]     \* LRN:764
    \* LRN:813 setCurrentEpoch begins; nothing has touched the tmp yet
    /\ wrStep' = [wrStep EXCEPT ![f] = "ToOpen"]
    /\ wrVal'  = [wrVal EXCEPT ![f] = newEpoch[f]]
    /\ wrCtx'  = [wrCtx EXCEPT ![f] = "Learner"]
    /\ lstep'  = [lstep EXCEPT ![f] = "EpochWrite"]
    /\ UNCHANGED <<curFile, accFile, tmp, role, running, memCur, memAcc, zkDbInit, loadCaller,
                   syncMode, leaderOf, newEpoch, sockOpen, connOpen, leadVars, hstep>>

\* LRN:731-745 UPTODATE breaks the loop (LRN:739-741 is unreachable: LH:600-606, 653)
ReadUpToDate(f) ==
    /\ role[f] = "Following"
    /\ lstep[f] = "AfterNL"
    /\ running[f]
    /\ sockOpen[f]
    /\ q[f] /= <<>>
    /\ Head(q[f]).type = "UPTODATE"
    /\ q' = [q EXCEPT ![f] = Tail(@)]
    /\ lstep' = [lstep EXCEPT ![f] = "PostLoop"]
    /\ UNCHANGED <<diskVars, memVars, writeVars, syncMode, leaderOf, newEpoch, writeToTxnLog,
                   pNotLogged, pCommitted, sockOpen, connOpen, leadVars, hstep>>

\* Scenario 3. LRN:651 the loop condition goes false after QP:1682 while the
\* socket is still open: a normal exit, between packets, possibly before NEWLEADER.
LoopExit(f) ==
    /\ role[f] = "Following"
    /\ lstep[f] \in {"SyncLoop", "AfterNL"}
    /\ ~running[f]
    /\ sockOpen[f]
    /\ lstep' = [lstep EXCEPT ![f] = "PostLoop"]
    /\ UNCHANGED <<diskVars, memVars, writeVars, syncMode, leaderOf, newEpoch, writeToTxnLog,
                   pNotLogged, pCommitted, sockOpen, connOpen, leadVars, netVars>>

\* LRN:825-848 after the loop: the ack write (needs the socket), zk.startup, then
\* every buffered proposal goes to the log (flushed by SyncRequestProcessor, at
\* the latest by its shutdown, SyncRequestProcessor.java:254-259), and committed
\* ones are applied. There is no setCurrentEpoch here (it exists only at LRN:741,
\* 813), so after LoopExit this durably logs epoch-E txns with the old epoch.
PostLoopLog(f) ==
    LET committed == pCommitted[f] \cap pNotLogged[f] IN
    /\ role[f] = "Following"
    /\ lstep[f] = "PostLoop"
    /\ sockOpen[f]                                      \* LRN:826
    /\ dLog'    = [dLog EXCEPT ![f] = @ \cup pNotLogged[f]]   \* LRN:841
    /\ memZxid' = [memZxid EXCEPT ![f] = Max({@} \cup committed)]  \* LRN:846
    /\ cLog'    = [cLog EXCEPT ![f] = @ \cup committed]
    /\ pNotLogged' = [pNotLogged EXCEPT ![f] = {}]
    /\ pCommitted' = [pCommitted EXCEPT ![f] = {}]
    /\ lstep'   = [lstep EXCEPT ![f] = "Broadcast"]     \* LRN:827 zk is running
    /\ UNCHANGED <<snapZxid, curFile, accFile, tmp, role, running, memCur, memAcc, zkDbInit,
                   writeVars, syncMode, leaderOf, newEpoch, writeToTxnLog, sockOpen, connOpen,
                   leadVars, netVars>>

\* FLW:161-180 PROPOSAL in broadcast: FZK:79-84 logRequest; the log write is what
\* LeadCommit counts as this peer's ack
FollowerLogProposal(f) ==
    /\ role[f] = "Following"
    /\ lstep[f] = "Broadcast"
    /\ running[f]                                       \* FLW:122 this.isRunning()
    /\ sockOpen[f]
    /\ q[f] /= <<>>
    /\ Head(q[f]).type = "PROPOSAL"
    /\ dLog' = [dLog EXCEPT ![f] = @ \cup {Head(q[f]).zxid}]
    /\ q' = [q EXCEPT ![f] = Tail(@)]
    /\ UNCHANGED <<snapZxid, curFile, accFile, tmp, memVars, writeVars, learnVars,
                   leadVars, hstep>>

\* FLW:199-201 COMMIT in broadcast -> FZK:99-110 -> ZKS:1887-1889, DT:1105-1107
FollowerCommit(f) ==
    LET z == Head(q[f]).zxid IN
    /\ role[f] = "Following"
    /\ lstep[f] = "Broadcast"
    /\ running[f]
    /\ sockOpen[f]
    /\ q[f] /= <<>>
    /\ Head(q[f]).type = "COMMIT"
    /\ memZxid' = [memZxid EXCEPT ![f] = Max({@, z})]
    /\ cLog'    = [cLog EXCEPT ![f] = @ \cup {z}]
    /\ q' = [q EXCEPT ![f] = Tail(@)]
    /\ UNCHANGED <<diskVars, role, running, memCur, memAcc, zkDbInit, writeVars, learnVars,
                   leadVars, hstep>>

(***************************************************************************)
(* Leaving a role                                                          *)
(***************************************************************************)
BlockingSteps == {"Register", "AwaitLeaderInfo", "AwaitOp", "SyncLoop", "AfterNL",
                  "PostLoop", "Broadcast"}

LearnerAbortEnabled(f) ==
    \/ lstep[f] = "Failed"                                   \* an exception is pending
    \/ lstep[f] \in BlockingSteps /\ ~sockOpen[f]            \* the socket was closed locally
    \/ lstep[f] \in BlockingSteps /\ ~connOpen[f] /\ q[f] = <<>>  \* LRN:505, 581, 652 EOF
    \/ lstep[f] = "Broadcast" /\ ~running[f]                 \* FLW:122 loop ends

\* Scenario 2. FLW:126-132 catch, QP:1619 finally -> LRN:924
\* zk.shutdown(syncMode == SNAP). syncMode resets only at LRN:816, so it is sticky.
\* ZKS:922-948: fullyShutDown clears zkDb (ZKD:191) even when zk never started;
\* otherwise a running zk fast-forwards from its log (ZKS:928-941); otherwise
\* zkDb is untouched. QP:1621 returns to LOOKING.
LearnerAbort(f) ==
    LET clear   == syncMode[f] = "SNAP"
        started == lstep[f] = "Broadcast"          \* LRN:827; ZKS:218, 903-905
    IN
    /\ role[f] = "Following"
    /\ LearnerAbortEnabled(f)
    /\ role'     = [role EXCEPT ![f] = "Looking"]
    /\ memZxid'  = [memZxid EXCEPT ![f] =
                      IF clear THEN 0 ELSE IF started THEN Max({@} \cup dLog[f]) ELSE @]
    /\ cLog'     = [cLog EXCEPT ![f] =
                      IF clear THEN {}
                      ELSE IF started THEN @ \cup {z \in dLog[f] : z > memZxid[f]} ELSE @]
    /\ zkDbInit' = [zkDbInit EXCEPT ![f] = IF clear THEN FALSE ELSE @]
    /\ lstep'    = [lstep EXCEPT ![f] = "Idle"]
    /\ leaderOf' = [leaderOf EXCEPT ![f] = NoPeer]
    /\ newEpoch' = [newEpoch EXCEPT ![f] = NoEpoch]
    /\ writeToTxnLog' = [writeToTxnLog EXCEPT ![f] = FALSE]
    /\ pNotLogged' = [pNotLogged EXCEPT ![f] = {}]
    /\ pCommitted' = [pCommitted EXCEPT ![f] = {}]
    /\ sockOpen' = [sockOpen EXCEPT ![f] = TRUE]
    /\ connOpen' = [connOpen EXCEPT ![f] = TRUE]
    /\ q'        = [q EXCEPT ![f] = <<>>]
    /\ hstep'    = [hstep EXCEPT ![f] = "None"]
    /\ UNCHANGED <<diskVars, running, memCur, memAcc, writeVars, syncMode, leadVars>>

\* The leader loses its quorum: LDR:832-839 once running, and the initLimit
\* timeouts of LDR:716-718, 1491-1498, 1537-1547 and 1648-1658 while establishing. Enabled only
\* when a needed quorum can no longer form, so it is not a free timeout.
LeaderAbortEnabled(l) ==
    LET F == FollowersOf(l) IN
    \/ ~IsQuorum({l} \cup F)
    \/ /\ lstate[l] = "AwaitEpochQuorum"
       /\ ~IsQuorum(electing[l] \cup {l} \cup {f \in F : memAcc[f] < lEpoch[l]})

LeaderAbort(l) ==
    /\ role[l] = "Leading"
    /\ wrStep[l] = "Idle"
    /\ LeaderAbortEnabled(l)
    /\ LeaderStepDown(l)
    /\ UNCHANGED <<diskVars, running, memCur, memAcc, zkDbInit, writeVars, syncMode, lstep,
                   leaderOf, newEpoch, writeToTxnLog, pNotLogged, pCommitted, sockOpen, q>>

(***************************************************************************)
(* Volatile reset at process end                                           *)
(***************************************************************************)
PeerGoesDown(n) ==
    LET F == IF role[n] = "Leading" THEN FollowersOf(n) ELSE {} IN
    /\ role'     = [role EXCEPT ![n] = "Down"]
    /\ running'  = [running EXCEPT ![n] = TRUE]
    /\ memZxid'  = [memZxid EXCEPT ![n] = 0]
    /\ memCur'   = [memCur EXCEPT ![n] = NoEpoch]
    /\ memAcc'   = [memAcc EXCEPT ![n] = NoEpoch]
    /\ zkDbInit' = [zkDbInit EXCEPT ![n] = FALSE]
    /\ cLog'     = [cLog EXCEPT ![n] = {}]
    /\ WriteDone(n)
    /\ syncMode' = [syncMode EXCEPT ![n] = "NONE"]
    /\ lstep'    = [lstep EXCEPT ![n] = "Idle"]
    /\ leaderOf' = [leaderOf EXCEPT ![n] = NoPeer]
    /\ newEpoch' = [newEpoch EXCEPT ![n] = NoEpoch]
    /\ writeToTxnLog' = [writeToTxnLog EXCEPT ![n] = FALSE]
    /\ pNotLogged' = [pNotLogged EXCEPT ![n] = {}]
    /\ pCommitted' = [pCommitted EXCEPT ![n] = {}]
    /\ sockOpen' = [sockOpen EXCEPT ![n] = TRUE]
    /\ connOpen' = [f \in Server |-> IF f = n THEN TRUE
                                     ELSE IF f \in F THEN FALSE ELSE connOpen[f]]
    /\ lstate'   = [lstate EXCEPT ![n] = "Idle"]
    /\ lEpoch'   = [lEpoch EXCEPT ![n] = NoEpoch]
    /\ connecting' = [connecting EXCEPT ![n] = {}]
    /\ electing' = [electing EXCEPT ![n] = {}]
    /\ nlAcked'  = [nlAcked EXCEPT ![n] = {}]
    /\ q'        = [q EXCEPT ![n] = <<>>]
    /\ hstep'    = [f \in Server |-> IF f = n \/ f \in F THEN "None" ELSE hstep[f]]

\* Scenarios 1, 3. A process crash at any step: disk stays exactly as it was,
\* including a half-written tmp.
Crash(n) ==
    /\ role[n] /= "Down"
    /\ PeerGoesDown(n)
    /\ UNCHANGED diskVars

(***************************************************************************)
(* Graceful stop, QP.shutdown (QP:1681-1714). Scenario 3: three steps, so  *)
(* the learner's main thread can interleave. The whole stop can be stuck   *)
(* behind synchronized (zk) (LRN:585-824, ZKS:922), but closeSocket         *)
(* (LRN:919) comes first, so the socket closes regardless.                 *)
(***************************************************************************)
ShutdownBegin(n) ==                 \* QP:1682 running = false, the first statement
    /\ role[n] \in {"Looking", "Following", "Leading"}
    /\ running[n]
    /\ running' = [running EXCEPT ![n] = FALSE]
    /\ UNCHANGED <<diskVars, role, memZxid, memCur, memAcc, zkDbInit, cLog, writeVars,
                   learnVars, leadVars, netVars>>

ShutdownCloseSock(f) ==             \* QP:1687-1688 -> LRN:919
    /\ role[f] = "Following"
    /\ ~running[f]
    /\ sockOpen[f]
    /\ sockOpen' = [sockOpen EXCEPT ![f] = FALSE]
    /\ UNCHANGED <<diskVars, memVars, writeVars, syncMode, lstep, leaderOf, newEpoch,
                   writeToTxnLog, pNotLogged, pCommitted, connOpen, leadVars, netVars>>

ShutdownLeader(l) ==                \* QP:1684-1686 -> LDR:861-892
    /\ role[l] = "Leading"
    /\ ~running[l]
    /\ wrStep[l] = "Idle"
    /\ LeaderStepDown(l)
    /\ UNCHANGED <<diskVars, running, memCur, memAcc, zkDbInit, writeVars, syncMode, lstep,
                   leaderOf, newEpoch, writeToTxnLog, pNotLogged, pCommitted, sockOpen, q>>

ShutdownEnd(n) ==                   \* QP:1522 the run loop has left; QP:1708-1713 zkDb.close
    /\ role[n] = "Looking"
    /\ ~running[n]
    /\ wrStep[n] = "Idle"
    /\ PeerGoesDown(n)
    /\ UNCHANGED diskVars

(***************************************************************************)
(* Next                                                                    *)
(***************************************************************************)
\* Reactive steps. None of these introduces a fault; targetFired is untouched.
ProtocolStep ==
    \/ \E n \in Server :
        \/ EpochTmpOpen(n)
        \/ EpochTmpFill(n)
        \/ EpochRename(n)
        \/ RegisterWithLeader(n)
        \/ ReceiveLeaderInfo(n)
        \/ ReadSyncOp(n)
        \/ SyncRecvProposal(n)
        \/ SyncRecvCommit(n)
        \/ NLPersist(n)
        \/ ReadUpToDate(n)
        \/ LoopExit(n)
        \/ PostLoopLog(n)
        \/ FollowerLogProposal(n)
        \/ FollowerCommit(n)
        \/ LearnerAbort(n)
        \/ LeadLoadData(n)
        \/ LeadGetEpochToPropose(n)
        \/ LeadWaitForEpochAck(n)
        \/ LeadStartZkServer(n)
        \/ LeadPropose(n)
        \/ LeadCommit(n)
        \/ LeaderAbort(n)
        \/ ShutdownCloseSock(n)
        \/ ShutdownLeader(n)
        \/ ShutdownEnd(n)
    \/ \E Q \in SUBSET Server : Q /= {} /\ Elect(Q)
    \/ \E n, l \in Server :
        \/ ElectJoin(n, l)
        \/ LearnerHandlerSyncFollower(l, n)
        \/ LearnerHandlerSendNewLeader(l, n)
        \/ LearnerHandlerSendUpToDate(l, n)

\* TargetCheck manages targetFired itself
LoadStep ==
    \E n \in Server :
        \/ Start(n)
        \/ ElectReload(n)

FaultStep ==
    \E n \in Server :
        \/ Crash(n)
        \/ EpochWriteFail(n)
        \/ EpochRenameFail(n)
        \/ ShutdownBegin(n)

\* Once the target fired, everything stops (adhoc tla-patterns.md section 1)
Next ==
    /\ ~targetFired
    /\ \/ LoadStep
       \/ (ProtocolStep \/ FaultStep) /\ UNCHANGED targetFired

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Invariants (brief section 5)                                            *)
(***************************************************************************)
TargetSafe == ~targetFired

PeerRoles == {"Down", "Starting", "Looking", "Following", "Leading"}
LeaderStates == {"Idle", "LoadData", "Discover", "AwaitEpochQuorum", "SetEpoch",
                 "AwaitNLAck", "Started"}
EpochVals == {NoEpoch} \cup 0..(MaxEpoch + 1)

TypeOK ==
    /\ snapZxid \in [Server -> AllZxid]
    /\ dLog     \in [Server -> SUBSET AllZxid]
    /\ curFile  \in [Server -> {NoFile} \cup Epochs]
    /\ accFile  \in [Server -> {NoFile} \cup Epochs]
    /\ tmp      \in [Server -> {TmpNone, TmpEmpty} \cup Epochs]
    /\ role     \in [Server -> PeerRoles]
    /\ running  \in [Server -> BOOLEAN]
    /\ memZxid  \in [Server -> AllZxid]
    /\ memCur   \in [Server -> {NoEpoch} \cup Epochs]
    /\ memAcc   \in [Server -> {NoEpoch} \cup Epochs]
    /\ zkDbInit \in [Server -> BOOLEAN]
    /\ cLog     \in [Server -> SUBSET AllZxid]
    /\ wrStep   \in [Server -> {"Idle", "ToOpen", "ToFill", "ToRename"}]
    /\ wrVal    \in [Server -> {-1} \cup Epochs]
    /\ wrCtx    \in [Server -> {"None", "Learner", "Leader", "Load"}]
    /\ loadCaller \in [Server -> {"None", "start", "elect"}]
    /\ syncMode \in [Server -> {"NONE", "DIFF", "SNAP", "TRUNC"}]
    /\ lstep    \in [Server -> LearnerSteps]
    /\ leaderOf \in [Server -> {NoPeer} \cup Server]
    /\ newEpoch \in [Server -> {NoEpoch} \cup Epochs]
    /\ writeToTxnLog \in [Server -> BOOLEAN]
    /\ pNotLogged \in [Server -> SUBSET AllZxid]
    /\ pCommitted \in [Server -> SUBSET AllZxid]
    /\ sockOpen \in [Server -> BOOLEAN]
    /\ connOpen \in [Server -> BOOLEAN]
    /\ lstate   \in [Server -> LeaderStates]
    /\ lEpoch   \in [Server -> EpochVals]
    /\ connecting \in [Server -> SUBSET Server]
    /\ electing \in [Server -> SUBSET Server]
    /\ nlAcked  \in [Server -> SUBSET Server]
    /\ q        \in [Server -> Seq([type : PacketTypes, zxid : {-1} \cup AllZxid])]
    /\ hstep    \in [Server -> HandlerSteps]
    /\ targetFired \in BOOLEAN

\* A message carries only values its sender held. Checked while the connection
\* is open: after the leader goes, its packets stay readable but its state is gone.
QueuedFromSender ==
    \A f \in Server :
        (role[f] = "Following" /\ connOpen[f] /\ leaderOf[f] /= NoPeer) =>
            LET l == leaderOf[f] IN
            /\ role[l] = "Leading"
            /\ \A i \in 1..Len(q[f]) :
                LET p == q[f][i] IN
                /\ p.type \in {"PROPOSAL", "COMMIT", "SNAP", "DIFF", "TRUNC"} =>
                       p.zxid <= Max({memZxid[l]} \cup dLog[l])
                /\ p.type = "NEWLEADER" => EpochOf(p.zxid) = lEpoch[l]

=============================================================================
