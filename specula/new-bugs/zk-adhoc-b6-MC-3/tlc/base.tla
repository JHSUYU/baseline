---------------------------------- MODULE base ----------------------------------
(*
 * Ad hoc coordination model for Apache ZooKeeper @ eab16599, target check
 * ZKDatabase.addCommittedProposal(Request), ZKDatabase.java:341
 * (IllegalStateException "Committed proposal cached out of order").
 *
 * Question: can a same-epoch zxid that leaves a gap reach a server whose
 * committed log is non-empty?
 *
 * Roles (brief section 1):
 *   L  the leader; never crashes, one epoch (brief 3.2)
 *   F  a follower that also runs ObserverMaster
 *   O  an observer that syncs only through F's ObserverMaster
 * The third participant of the workload is abstract: it is why L + "A" is always
 * a quorum, so LeaderTryToCommit needs no ACK from F (Leader.java:985).
 *
 * Paths are relative to
 *   zookeeper-server/src/main/java/org/apache/zookeeper/server/
 *
 * Zxids are the low 32 bits of the real zxid. 0 is the real 0x0, the value every
 * server holds before the first txn (workload log lines 318-320, 457-458: a fresh
 * peer and master both report 0x0 and get an empty DIFF). Every positive value
 * is in the one modeled epoch.
 *
 * Deliberately not modeled (brief 3.2): leader election and epoch change, an
 * observer attached directly to the leader, zxid allocation gaps, non-quorum
 * txns, reconfig packets, byte sizes, lost fsynced snapshots, test-only settings.
 * Also abstracted, see the notes at each action: periodic snapshots (the workload
 * sets snapCount=100000), the async fsync of SyncRequestProcessor (a crash cannot
 * lose a logged txn here), and in-process reconnect of F (an exception at F is
 * modeled as a process restart).
 *)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANT
    \* @type: Int;
    MaxTxn          \* Largest zxid the leader may allocate (brief section 4).

ASSUME MaxTxn \in Nat

L == "L"
F == "F"
O == "O"
Servers  == {L, F, O}
Learners == {F, O}

\* The value of applyPending when no txn is between ApplyTree and TargetCheck.
NoZxid == -1

\* ZKDatabase.java:86 final field, test-only property, false by default. Outside
\* the fault model (brief 3.2), kept so the guard reads as the code does.
AllowDiscontinuousProposals == FALSE

\* ZxidUtils.getEpochFromZxid. One epoch: only the pre-first-txn 0x0 differs.
EpochOf(z) == IF z = 0 THEN 0 ELSE 1

\* LearnerHandler.java:792,952 (peerLastZxid & 0xffffffffL) == 0
IsPeerNewEpochZxid(z) == z = 0

\* ZKDatabase.isTxnLogSyncEnabled, ZKDatabase.java:355-363: true by default.
TxnLogSyncEnabled == TRUE

Max(a, b) == IF a >= b THEN a ELSE b

-----------------------------------------------------------------------------
(* VARIABLES *)

\* Leader state. Leader.java:1329 lastProposed; :990 lastCommitted.
\* outstandingProposals is (lCommitted, lProposed].
\* toBeApplied is (max of L's committed log, lCommitted]: removal follows
\* addCommittedProposal (Leader.java:1157-1169), and startForwarding filters by
\* lastSeen (:1372), so the short window after the add is not observable.
VARIABLES lProposed, lCommitted

\* Connection state. S1, S2 (split sync, late ObserverMaster start).
\* phase[n], n in Learners:
\*   down        process not running
\*   connecting  database loaded, waiting for the master's syncFollower
\*   awaitOp     registered; the op packet has not been read
\*   sync        Learner.syncWithLeader read loop
\*   uptodate    F only, between syncWithLeader and Follower.java:115-116
\*   broadcast   Follower/Observer processPacket loop
\*   lostStarted O only, socket gone, server was started (must run shutdown)
\*   lostSync    O only, socket gone during sync, server not started
\* hPhase[n]: the master-side LearnerHandler for learner n:
\*   none, needSnap (LearnerHandler.java:563), syncing,
\*   newleader (NEWLEADER queued, :605), done (UPTODATE queued, :653)
\* inQ[n]: FIFO of queued packets from master to learner n (TCP plus queuedPackets).
VARIABLES phase, hPhase, inQ

\* Database, per server. All Scenarios.
\* tree[n]      DataTree.lastProcessedZxid
\* clog[n]      committedLog as [empty, min, max]. It is contiguous on every
\*              path that has not fired the target, so min..max is exact.
\* applyPending[n]  txn between ZooKeeperServer.java:1863 and :1888 (variant (c))
\* commitQ[n]   CommitProcessor.committedRequests
\* log[n]       durable txn log, in append order (L's is derived from lProposed)
\* snap[n]      lastProcessedZxid of the newest snapshot
VARIABLES tree, clog, applyPending, commitQ, log, snap

\* Learner.syncWithLeader locals, per learner. S1, S2.
\* notLogged[n] packetsNotLogged (:583); committedIds[n] packetsCommitted (:582)
\* wtl[n] writeToTxnLog (:647); snapNeeded[n] snapshotNeeded (:579)
\* lastQueued[n] (:639); snapMode[n] SyncMode.SNAP (:597, cleared :816)
\* nlAcked[n] NEWLEADER processed and acked (:819), i.e. ~isPreZAB1_0
VARIABLES notLogged, committedIds, wtl, snapNeeded, lastQueued, snapMode, nlAcked

\* FollowerZooKeeperServer.pendingTxns (:77). S1.
VARIABLE pendingTxns

\* ObserverMaster. S1, S2, S3.
\* omUp: F's om exists (Follower.java:115-116).
\* omProposed proposedPkts (:88); omCommitted committedPkts (:89);
\* omActive: O's handler is in activeObservers (:77).
VARIABLES omUp, omProposed, omCommitted, omActive

\* Oracle (adhoc-coordination Shared Rule 1).
VARIABLE targetFired

leaderVars == <<lProposed, lCommitted>>
connVars   == <<phase, hPhase, inQ>>
dbVars     == <<tree, clog, applyPending, commitQ, log, snap>>
syncVars   == <<notLogged, committedIds, wtl, snapNeeded, lastQueued, snapMode, nlAcked>>
omVars     == <<omUp, omProposed, omCommitted, omActive>>
vars == <<leaderVars, connVars, dbVars, syncVars, pendingTxns, omVars, targetFired>>

-----------------------------------------------------------------------------
(* HELPERS *)

Pkt(t, z) == [type |-> t, zxid |-> z]

EmptyClog == [empty |-> TRUE, min |-> 0, max |-> 0]   \* ZKDatabase.java:185-187

\* The failing predicate phi_T, exactly as ZKDatabase.java:326-335 evaluates it.
PhiT(c, z) ==
    /\ ~c.empty                                        \* :326
    /\ ~(z <= c.max)                                   \* :329
    /\ ~AllowDiscontinuousProposals                    \* :333
    /\ z /= c.max + 1                                  \* :334
    /\ EpochOf(z) <= EpochOf(c.max)                    \* :335

\* The normal continuation of addCommittedProposal, ZKDatabase.java:326-345.
\* commitLogCount (:346) is 500: never reached with MaxTxn this small.
ClogAdd(c, z) ==
    IF c.empty THEN [empty |-> FALSE, min |-> z, max |-> z]   \* :327-328, :344-345
    ELSE IF z <= c.max THEN c                                 \* :329-332
    ELSE [c EXCEPT !.max = z]                                 \* :344-345

\* One synchronous ZooKeeperServer.processTxn or replay step, used where the code
\* does not cross a thread boundary between the DataTree update and the check.
\* st is [tree, clog, fired]. DataTree.java:1105-1107 only raises lastProcessedZxid.
ProcessStep(st, z) ==
    [tree  |-> Max(st.tree, z),
     clog  |-> ClogAdd(st.clog, z),
     fired |-> st.fired \/ PhiT(st.clog, z)]

RECURSIVE ProcessAll(_, _)
ProcessAll(st, s) ==
    IF s = <<>> THEN st ELSE ProcessAll(ProcessStep(st, Head(s)), Tail(s))

\* FileTxnIterator skips to the first txn >= zxid, then yields all that follow.
\* FileTxnSnapLog.java:330.
RECURSIVE DropBelow(_, _)
DropBelow(s, z) ==
    IF s = <<>> \/ Head(s) >= z THEN s ELSE DropBelow(Tail(s), z)

\* ZKDatabase.loadDataBase from an empty database: FileTxnSnapLog.restore replays
\* the log past the snapshot through addCommittedProposal (ZKDatabase.java:276-279,
\* 290, FileTxnSnapLog.java:326-360).
LoadDataBase(sn, lg) ==
    ProcessAll([tree |-> sn, clog |-> EmptyClog, fired |-> FALSE], DropBelow(lg, sn + 1))

\* ZKDatabase.fastForwardDataBase (:304-308) with the database kept.
FastForward(tr, c, lg) ==
    ProcessAll([tree |-> tr, clog |-> c, fired |-> FALSE], DropBelow(lg, tr + 1))

\* The on-disk log of a server. The leader logs each proposal it makes.
LogOf(n) == IF n = L THEN [i \in 1..lProposed |-> i] ELSE log[n]

\* The server a learner syncs from.
MasterOf(n) == IF n = F THEN L ELSE F

\* A PROPOSAL + COMMIT pair per zxid of s, LearnerHandler.java:1023-1024.
RECURSIVE Pairs(_)
Pairs(s) ==
    IF s = <<>> THEN <<>>
    ELSE <<Pkt("PROPOSAL", Head(s)), Pkt("COMMIT", Head(s))>> \o Pairs(Tail(s))

Range(a, b) == [i \in 1..Max(0, b - a + 1) |-> a + i - 1]

\* queueCommittedProposals over a log iterator, LearnerHandler.java:951-1042, for
\* the path where the first entry is the peer's zxid (:977-985). The iterator is
\* cut at maxZ (:962) and repeats are skipped (:1015). Result: zxids to queue.
RECURSIVE LogQueue(_, _, _)
LogQueue(s, queued, maxZ) ==
    IF s = <<>> \/ Head(s) > maxZ THEN <<>>
    ELSE IF Head(s) <= queued THEN LogQueue(Tail(s), queued, maxZ)
    ELSE <<Head(s)>> \o LogQueue(Tail(s), Head(s), maxZ)

(*
 * LearnerHandler.syncFollower, LearnerHandler.java:780-938. The branch order is
 * the code's. src is the master, peer the learner's lastProcessedZxid (:552), and
 * useLog resolves the size limit of ZKDatabase.java:407-414, which depends on
 * byte sizes (brief 3.2: not modeled), so either outcome is allowed.
 * Result: packets queued before startForwarding, currentZxid (:794), needSnap (:795).
 *)
SyncFollower(src, peer, useLog) ==
    LET c      == clog[src]
        t      == tree[src]                                     \* :804
        maxC   == IF c.empty THEN t ELSE c.max                  \* :802, :815-828
        minC   == IF c.empty THEN t ELSE c.min                  \* :803, :815-828
        Snap   == [packets |-> <<>>, current |-> t, needSnap |-> TRUE]   \* :920-922
    IN
    IF t = peer THEN                                            \* :849
        \* Empty DIFF, :855. currentZxid stays peerLastZxid (:794).
        [packets |-> <<Pkt("DIFF", peer)>>, current |-> peer, needSnap |-> FALSE]
    ELSE IF peer > maxC /\ ~IsPeerNewEpochZxid(peer) THEN       \* :858
        [packets |-> <<Pkt("TRUNC", maxC)>>, current |-> maxC, needSnap |-> FALSE]  \* :864-865
    ELSE IF maxC >= peer /\ minC <= peer THEN                   \* :868
        \* queueCommittedProposals(clog, peer, null, max), :872, :977-985.
        \* Nothing past maxC is queued, whatever tree says (variant (c)).
        [packets |-> <<Pkt("DIFF", maxC)>> \o Pairs(Range(peer + 1, maxC)),
         current |-> maxC, needSnap |-> FALSE]
    ELSE IF peer < minC /\ TxnLogSyncEnabled THEN               \* :874
        LET fromPeer == DropBelow(LogOf(src), peer)
        IN
        \* ZKDatabase.java:399-405: the first entry must be the peer's own zxid.
        \* An empty iterator leaves needSnap true (:882).
        IF ~useLog \/ fromPeer = <<>> \/ Head(fromPeer) /= peer THEN Snap
        ELSE
            LET fromLog == LogQueue(Tail(fromPeer), peer, minC)              \* :884
                cur == IF fromLog = <<>> THEN peer ELSE fromLog[Len(fromLog)]
            IN
            IF cur < minC THEN Snap                                          \* :886-895
            ELSE
                [packets |-> <<Pkt("DIFF", maxC)>>
                             \o Pairs(fromLog \o Range(cur + 1, maxC)),      \* :899
                 current |-> Max(cur, maxC), needSnap |-> FALSE]
    ELSE Snap                                                   \* :908-919

\* Leader.startForwarding, Leader.java:1367-1400: toBeApplied pairs, then
\* outstanding proposals for a participant. F is always a participant (:1382).
LeaderStartForwarding(lastSeen) ==
    LET applied == IF clog[L].empty THEN 0 ELSE clog[L].max
        toBeApplied == Range(Max(applied, lastSeen) + 1, lCommitted)         \* :1371-1374
        outstanding == Range(Max(lCommitted, lastSeen) + 1, lProposed)       \* :1385-1388
    IN IF lProposed > lastSeen                                               \* :1370
       THEN Pairs(toBeApplied)
            \o [i \in 1..Len(outstanding) |-> Pkt("PROPOSAL", outstanding[i])]
       ELSE <<>>

\* ObserverMaster.startForwarding queue part, ObserverMaster.java:306-318.
RetainedAfter(lastSeen) ==
    LET kept == SelectSeq(omCommitted, LAMBDA z : z > lastSeen)
    IN [i \in 1..Len(kept) |-> Pkt("INFORM", kept[i])]

\* The queue of learner n gets a forwarded packet only once the master's handler
\* registered it (Leader.java:1394 addForwardingFollower, ObserverMaster.java:330).
Forward(n, q, p) == IF hPhase[n] /= "none" THEN Append(q, p) ELSE q

-----------------------------------------------------------------------------
(* DOWN AND LOST TRANSITIONS: shared by faults and by exceptions in the code *)

ResetSync(n) ==
    /\ notLogged'    = [notLogged    EXCEPT ![n] = <<>>]
    /\ committedIds' = [committedIds EXCEPT ![n] = <<>>]
    /\ wtl'          = [wtl          EXCEPT ![n] = FALSE]
    /\ snapNeeded'   = [snapNeeded   EXCEPT ![n] = TRUE]
    /\ lastQueued'   = [lastQueued   EXCEPT ![n] = 0]
    /\ nlAcked'      = [nlAcked      EXCEPT ![n] = FALSE]

\* What O's connection loss does to O's phase: Observer.java:131-137, then
\* QuorumPeer.java:1600 runs Learner.shutdown.
LostPhase(p) ==
    IF p = "broadcast" THEN "lostStarted"
    ELSE IF p \in {"awaitOp", "sync"} THEN "lostSync"
    ELSE p

(*
 * F's process ends: a crash or restart (the workload's fault), or an exception in
 * its loop. Follower.java:126-137 stops ObserverMaster, whose handlers close
 * (ObserverMaster.java:496-497), so O's connection is lost. An exception would
 * really reconnect in-process with the database kept; it is modeled as a restart
 * because the replay rebuilds the same tree. Memory is dropped; the log and the
 * snapshot stay. tree and clog are normalized here and rebuilt by LearnerStart.
 *)
FollowerDown ==
    /\ phase'  = [phase  EXCEPT ![F] = "down", ![O] = LostPhase(phase[O])]
    /\ hPhase' = [hPhase EXCEPT ![F] = "none", ![O] = "none"]
    /\ inQ'    = [inQ    EXCEPT ![F] = <<>>, ![O] = <<>>]
    /\ tree'   = [tree   EXCEPT ![F] = snap[F]]
    /\ clog'   = [clog   EXCEPT ![F] = EmptyClog]
    /\ commitQ'      = [commitQ      EXCEPT ![F] = <<>>]
    /\ applyPending' = [applyPending EXCEPT ![F] = NoZxid]
    /\ pendingTxns'  = <<>>
    /\ omUp' = FALSE
    /\ omProposed'  = <<>>
    /\ omCommitted' = <<>>
    /\ omActive' = FALSE
    /\ notLogged'    = [notLogged    EXCEPT ![F] = <<>>, ![O] = <<>>]
    /\ committedIds' = [committedIds EXCEPT ![F] = <<>>, ![O] = <<>>]
    /\ wtl'          = [wtl          EXCEPT ![F] = FALSE, ![O] = FALSE]
    /\ snapNeeded'   = [snapNeeded   EXCEPT ![F] = TRUE, ![O] = TRUE]
    /\ lastQueued'   = [lastQueued   EXCEPT ![F] = 0, ![O] = 0]
    /\ nlAcked'      = [nlAcked      EXCEPT ![F] = FALSE, ![O] = FALSE]
    /\ snapMode'     = [snapMode     EXCEPT ![F] = FALSE]

\* O's process ends. LearnerHandler at F sees the socket close and removes itself,
\* LearnerHandler.java:730-738, :1056.
ObserverDown ==
    /\ phase'  = [phase  EXCEPT ![O] = "down"]
    /\ hPhase' = [hPhase EXCEPT ![O] = "none"]
    /\ inQ'    = [inQ    EXCEPT ![O] = <<>>]
    /\ tree'   = [tree   EXCEPT ![O] = snap[O]]
    /\ clog'   = [clog   EXCEPT ![O] = EmptyClog]
    /\ commitQ'      = [commitQ      EXCEPT ![O] = <<>>]
    /\ applyPending' = [applyPending EXCEPT ![O] = NoZxid]
    /\ UNCHANGED pendingTxns
    /\ omActive' = FALSE
    /\ UNCHANGED <<omUp, omProposed, omCommitted>>
    /\ ResetSync(O)
    /\ snapMode' = [snapMode EXCEPT ![O] = FALSE]

\* An exception inside O's sync: the throw of enforceContinuousProposal
\* (Learner.java:552) caught at Observer.java:131, or the handler's disconnect
\* (ObserverMaster.java:304). The database stays as it is until ObserverShutdown.
ObserverLostInSync ==
    /\ phase'  = [phase  EXCEPT ![O] = "lostSync"]
    /\ hPhase' = [hPhase EXCEPT ![O] = "none"]
    /\ inQ'    = [inQ    EXCEPT ![O] = <<>>]
    /\ omActive' = FALSE
    /\ ResetSync(O)
    /\ UNCHANGED <<omUp, omProposed, omCommitted, pendingTxns, snapMode>>

\* An exception in the sync of learner n.
LearnerAbort(n) ==
    IF n = F
    THEN FollowerDown
    ELSE /\ ObserverLostInSync
         /\ UNCHANGED <<tree, clog, commitQ, applyPending>>

-----------------------------------------------------------------------------
(* INIT *)

\* Every server starts at 0x0 with an initial snapshot and an empty log
\* (ZKDatabase.java:294 "highest zxid is 0x0" in the workload log). L is
\* established; F and O have not started.
Init ==
    /\ lProposed = 0
    /\ lCommitted = 0
    /\ phase  = [n \in Learners |-> "down"]
    /\ hPhase = [n \in Learners |-> "none"]
    /\ inQ    = [n \in Learners |-> <<>>]
    /\ tree = [n \in Servers |-> 0]
    /\ clog = [n \in Servers |-> EmptyClog]
    /\ applyPending = [n \in Servers |-> NoZxid]
    /\ commitQ = [n \in Servers |-> <<>>]
    /\ log  = [n \in Learners |-> <<>>]
    /\ snap = [n \in Learners |-> 0]
    /\ notLogged    = [n \in Learners |-> <<>>]
    /\ committedIds = [n \in Learners |-> <<>>]
    /\ wtl          = [n \in Learners |-> FALSE]
    /\ snapNeeded   = [n \in Learners |-> TRUE]
    /\ lastQueued   = [n \in Learners |-> 0]
    /\ snapMode     = [n \in Learners |-> FALSE]
    /\ nlAcked      = [n \in Learners |-> FALSE]
    /\ pendingTxns = <<>>
    /\ omUp = FALSE
    /\ omProposed = <<>>
    /\ omCommitted = <<>>
    /\ omActive = FALSE
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(* LEADER *)

\* Leader.propose, Leader.java:1329-1331: lastProposed, outstandingProposals, send
\* to forwarding followers. Allocation is contiguous (brief 3.2, excluded E2).
ClientPropose ==
    /\ lProposed < MaxTxn
    /\ lProposed' = lProposed + 1
    /\ inQ' = [inQ EXCEPT ![F] = Forward(F, @, Pkt("PROPOSAL", lProposed + 1))]
    /\ UNCHANGED <<lCommitted, phase, hPhase, dbVars, syncVars, pendingTxns, omVars, targetFired>>

\* Leader.tryToCommit, Leader.java:970-1035. In order (:978, :990). L and the
\* abstract third participant are a quorum (:985), so the delay of the ACKs is
\* just the delay of this action, as with the workload's held ACKs.
LeaderTryToCommit ==
    /\ lCommitted < lProposed
    /\ LET z == lCommitted + 1 IN
       /\ lCommitted' = z
       /\ inQ' = [inQ EXCEPT ![F] = Forward(F, @, Pkt("COMMIT", z))]     \* :1032
       /\ commitQ' = [commitQ EXCEPT ![L] = Append(@, z)]                \* :1035
    /\ UNCHANGED <<lProposed, phase, hPhase, tree, clog, applyPending, log, snap,
                   syncVars, pendingTxns, omVars, targetFired>>

-----------------------------------------------------------------------------
(* MASTER-SIDE LEARNER HANDLER *)

\* LearnerHandler.run -> syncFollower for F at the leader, LearnerHandler.java:556.
\* The read lock (:801) blocks addCommittedProposal but not the DataTree update:
\* atomic here w.r.t. TargetCheck, and ApplyTree is its own action.
LeaderSyncFollower(useLog) ==
    /\ phase[F] = "connecting"
    /\ hPhase[F] = "none"
    /\ LET d == SyncFollower(L, tree[F], useLog) IN
       /\ inQ' = [inQ EXCEPT ![F] = d.packets \o LeaderStartForwarding(d.current)]   \* :925
       /\ hPhase' = [hPhase EXCEPT ![F] = IF d.needSnap THEN "needSnap" ELSE "syncing"]
       /\ phase' = [phase EXCEPT ![F] = "awaitOp"]
    /\ UNCHANGED <<leaderVars, dbVars, syncVars, pendingTxns, omVars, targetFired>>

(*
 * LearnerHandler.run -> syncFollower for O at F's ObserverMaster.
 * ObserverMaster.startForwarding, ObserverMaster.java:293-332:
 *   the head check at :297 runs only if committedPkts is non-empty (:295), so an
 *   empty queue always activates the observer (:330). This is the hole of S1-S3.
 *)
OmSyncObserver(useLog) ==
    /\ omUp
    /\ phase[F] = "broadcast"
    /\ phase[O] = "connecting"
    /\ hPhase[O] = "none"
    /\ LET d == SyncFollower(F, tree[O], useLog) IN
       IF omCommitted /= <<>> /\ Head(omCommitted) > d.current + 1     \* :295-297
       THEN \* learnerHandler.shutdown(); return -1, :304-305
            /\ ObserverLostInSync
            /\ UNCHANGED <<tree, clog, commitQ, applyPending>>
       ELSE \* :306-318, :330
            /\ inQ' = [inQ EXCEPT ![O] = d.packets \o RetainedAfter(d.current)]
            /\ hPhase' = [hPhase EXCEPT ![O] = IF d.needSnap THEN "needSnap" ELSE "syncing"]
            /\ phase' = [phase EXCEPT ![O] = "awaitOp"]
            /\ omActive' = TRUE
            /\ UNCHANGED <<omUp, omProposed, omCommitted, tree, clog, commitQ, applyPending,
                           syncVars, pendingTxns>>
    /\ UNCHANGED <<leaderVars, log, snap, targetFired>>

\* LearnerHandler.java:563-585: zxidToSend is read again here, after the read lock
\* was released (:568), and SNAP is written directly to the socket, ahead of
\* queuedPackets, whose sender has not started (:610).
HandlerSendSnap(n) ==
    /\ hPhase[n] = "needSnap"
    /\ inQ' = [inQ EXCEPT ![n] = <<Pkt("SNAP", tree[MasterOf(n)])>> \o @]
    /\ hPhase' = [hPhase EXCEPT ![n] = "syncing"]
    /\ UNCHANGED <<leaderVars, phase, dbVars, syncVars, pendingTxns, omVars, targetFired>>

\* LearnerHandler.java:604-610: NEWLEADER is queued and the sender thread starts.
\* Forwarded packets may land before or after it.
HandlerQueueNewLeader(n) ==
    /\ hPhase[n] = "syncing"
    /\ inQ' = [inQ EXCEPT ![n] = Append(@, Pkt("NEWLEADER", 0))]
    /\ hPhase' = [hPhase EXCEPT ![n] = "newleader"]
    /\ UNCHANGED <<leaderVars, phase, dbVars, syncVars, pendingTxns, omVars, targetFired>>

\* LearnerHandler.java:617-653: after the NEWLEADER ACK. waitForNewLeaderAck and
\* waitForStartup return at once for an established master
\* (ObserverMaster.java:192-194,212-214).
HandlerQueueUptodate(n) ==
    /\ hPhase[n] = "newleader"
    /\ nlAcked[n]
    /\ inQ' = [inQ EXCEPT ![n] = Append(@, Pkt("UPTODATE", 0))]
    /\ hPhase' = [hPhase EXCEPT ![n] = "done"]
    /\ UNCHANGED <<leaderVars, phase, dbVars, syncVars, pendingTxns, omVars, targetFired>>

-----------------------------------------------------------------------------
(* LEARNER SYNC: Learner.syncWithLeader, Learner.java:570-872 *)

\* The learner can read only after the sender thread started
\* (LearnerHandler.java:610), which follows the queueing of NEWLEADER (:605).
CanReadOp(n, t) ==
    /\ phase[n] = "awaitOp"
    /\ hPhase[n] \in {"newleader", "done"}
    /\ inQ[n] /= <<>>
    /\ Head(inQ[n]).type = t

\* Learner.java:586-595: DIFF, so no snapshot, and writeToTxnLog is true from the
\* start (:594, :647).
LearnerReadDiff(n) ==
    /\ CanReadOp(n, "DIFF")
    /\ phase' = [phase EXCEPT ![n] = "sync"]
    /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
    /\ wtl' = [wtl EXCEPT ![n] = TRUE]
    /\ snapNeeded' = [snapNeeded EXCEPT ![n] = FALSE]
    /\ UNCHANGED <<leaderVars, hPhase, dbVars, notLogged, committedIds, lastQueued,
                   snapMode, nlAcked, pendingTxns, omVars, targetFired>>

\* Learner.java:596-617: ZKDatabase.deserializeSnapshot clears the committed log
\* (ZKDatabase.java:631), and lastProcessedZxid is the SNAP packet's zxid (:614).
LearnerReadSnap(n) ==
    /\ CanReadOp(n, "SNAP")
    /\ phase' = [phase EXCEPT ![n] = "sync"]
    /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
    /\ tree' = [tree EXCEPT ![n] = Head(inQ[n]).zxid]
    /\ clog' = [clog EXCEPT ![n] = EmptyClog]
    /\ wtl' = [wtl EXCEPT ![n] = FALSE]
    /\ snapNeeded' = [snapNeeded EXCEPT ![n] = TRUE]
    /\ snapMode' = [snapMode EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<leaderVars, hPhase, applyPending, commitQ, log, snap, notLogged,
                   committedIds, lastQueued, nlAcked, pendingTxns, omVars, targetFired>>

\* Learner.java:618-628: ZKDatabase.truncateLog (ZKDatabase.java:611-623) clears the
\* database, cuts the log and reloads it through addCommittedProposal, then
\* lastProcessedZxid is forced to the TRUNC zxid (:628). FileTxnLog.java:484-487: no
\* log to cut throws, truncateLog returns false, and the process exits (:626).
LearnerReadTrunc(n) ==
    /\ CanReadOp(n, "TRUNC")
    /\ LET z == Head(inQ[n]).zxid IN
       IF log[n] = <<>>
       THEN /\ IF n = F THEN FollowerDown ELSE ObserverDown
            /\ UNCHANGED <<leaderVars, log, snap, targetFired>>
       ELSE LET cut == SelectSeq(log[n], LAMBDA x : x <= z)
                st  == LoadDataBase(snap[n], cut)
            IN /\ phase' = [phase EXCEPT ![n] = "sync"]
               /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
               /\ log' = [log EXCEPT ![n] = cut]
               /\ tree' = [tree EXCEPT ![n] = z]
               /\ clog' = [clog EXCEPT ![n] = st.clog]
               /\ targetFired' = (targetFired \/ st.fired)      \* TargetCheck on replay
               /\ wtl' = [wtl EXCEPT ![n] = FALSE]
               /\ snapNeeded' = [snapNeeded EXCEPT ![n] = TRUE]
               /\ UNCHANGED <<leaderVars, hPhase, applyPending, commitQ, snap, notLogged,
                              committedIds, lastQueued, snapMode, nlAcked, pendingTxns, omVars>>

\* Learner.java:542-561 enforceContinuousProposal: lastQueued = 0 lets the first
\* packet through (:543, the TODO at :637-639), and a same-epoch gap throws (:552).
ContinuousOk(n, z) ==
    \/ lastQueued[n] = 0                        \* :543
    \/ z = lastQueued[n] + 1                    \* :545
    \/ EpochOf(z) > EpochOf(lastQueued[n])      \* :546, :556

CanReadSync(n, t) ==
    /\ phase[n] = "sync"
    /\ inQ[n] /= <<>>
    /\ Head(inQ[n]).type = t

\* Learner.java:654-668: PROPOSAL during sync goes only to packetsNotLogged. This
\* is the S1 mechanism: it never reaches om.proposalReceived (Follower.java:195).
LearnerSyncProposal(n) ==
    /\ CanReadSync(n, "PROPOSAL")
    /\ LET z == Head(inQ[n]).zxid IN
       IF ContinuousOk(n, z)
       THEN /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
            /\ lastQueued' = [lastQueued EXCEPT ![n] = z]        \* :660
            /\ notLogged' = [notLogged EXCEPT ![n] = Append(@, z)]   \* :668
            /\ UNCHANGED <<phase, hPhase, tree, clog, commitQ, applyPending, committedIds,
                           wtl, snapNeeded, snapMode, nlAcked, pendingTxns, omVars>>
       ELSE LearnerAbort(n)                                       \* :552
    /\ UNCHANGED <<leaderVars, log, snap, targetFired>>

\* Learner.java:670-696. A COMMIT with nothing in packetsNotLogged dereferences null
\* at :673: an exception, caught at Follower.java:126 or Observer.java:131.
\* After NEWLEADER (nlAcked) this is the S2 route: the id waits in packetsCommitted.
LearnerSyncCommit(n) ==
    /\ CanReadSync(n, "COMMIT")
    /\ LET z == Head(inQ[n]).zxid
       IN
       IF notLogged[n] = <<>>
       THEN LearnerAbort(n) /\ UNCHANGED targetFired
       ELSE IF wtl[n]
       THEN /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
            /\ committedIds' = [committedIds EXCEPT ![n] = Append(@, z)]      \* :694
            /\ UNCHANGED <<phase, hPhase, tree, clog, commitQ, applyPending, notLogged, wtl,
                           snapNeeded, lastQueued, snapMode, nlAcked, pendingTxns, omVars,
                           targetFired>>
       ELSE IF Head(notLogged[n]) /= z
       THEN /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]                             \* :684-688
            /\ UNCHANGED <<phase, hPhase, tree, clog, commitQ, applyPending, notLogged,
                           committedIds, wtl, snapNeeded, lastQueued, snapMode, nlAcked,
                           pendingTxns, omVars, targetFired>>
       ELSE LET st == ProcessStep([tree |-> tree[n], clog |-> clog[n], fired |-> FALSE], z)
            IN \* :690-691 zk.processTxn, synchronous: TargetCheck on this path too
            /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
            /\ tree' = [tree EXCEPT ![n] = st.tree]
            /\ clog' = [clog EXCEPT ![n] = st.clog]
            /\ targetFired' = (targetFired \/ st.fired)
            /\ notLogged' = [notLogged EXCEPT ![n] = Tail(@)]
            /\ UNCHANGED <<phase, hPhase, commitQ, applyPending, committedIds, wtl,
                           snapNeeded, lastQueued, snapMode, nlAcked, pendingTxns, omVars>>
    /\ UNCHANGED <<leaderVars, log, snap>>

\* Learner.java:697-730, INFORM during O's sync (F never gets INFORM from L).
\* Before NEWLEADER after a SNAP or TRUNC it applies at once (:722-724).
LearnerSyncInform(n) ==
    /\ CanReadSync(n, "INFORM")
    /\ LET z == Head(inQ[n]).zxid IN
       IF ~ContinuousOk(n, z)
       THEN LearnerAbort(n) /\ UNCHANGED targetFired                   \* :720, :552
       ELSE IF wtl[n]
       THEN /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
            /\ lastQueued' = [lastQueued EXCEPT ![n] = z]              \* :720
            /\ notLogged' = [notLogged EXCEPT ![n] = Append(@, z)]     \* :726
            /\ committedIds' = [committedIds EXCEPT ![n] = Append(@, z)]   \* :727
            /\ UNCHANGED <<phase, hPhase, tree, clog, commitQ, applyPending, wtl, snapNeeded,
                           snapMode, nlAcked, pendingTxns, omVars, targetFired>>
       ELSE LET st == ProcessStep([tree |-> tree[n], clog |-> clog[n], fired |-> FALSE], z)
            IN \* :724 zk.processTxn
            /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
            /\ lastQueued' = [lastQueued EXCEPT ![n] = z]
            /\ tree' = [tree EXCEPT ![n] = st.tree]
            /\ clog' = [clog EXCEPT ![n] = st.clog]
            /\ targetFired' = (targetFired \/ st.fired)
            /\ UNCHANGED <<phase, hPhase, commitQ, applyPending, notLogged, committedIds, wtl,
                           snapNeeded, snapMode, nlAcked, pendingTxns, omVars>>
    /\ UNCHANGED <<leaderVars, log, snap>>

\* The drain at NEWLEADER, Learner.java:785-800, for F only: each id matches the
\* head of packetsNotLogged or is dropped (:788-795); a match is appended to the
\* log and applied synchronously (:796-799). So these commits make no S2 window.
RECURSIVE Drain(_, _)
Drain(st, ids) ==
    IF ids = <<>> THEN st
    ELSE IF st.nl /= <<>> /\ Head(st.nl) = Head(ids)
         THEN LET p == ProcessStep([tree |-> st.tree, clog |-> st.clog, fired |-> st.fired], Head(ids))
              IN Drain([nl |-> Tail(st.nl), lg |-> Append(st.lg, Head(ids)),
                        tree |-> p.tree, clog |-> p.clog, fired |-> p.fired], Tail(ids))
         ELSE Drain(st, Tail(ids))

\* Learner.java:746-821. Snapshot if needed (:759-761), writeToTxnLog (:764), the
\* drain (:769-808, follower only), SyncMode.NONE (:816), ACK (:819).
LearnerSyncNewLeader(n) ==
    /\ CanReadSync(n, "NEWLEADER")
    /\ LET st == IF n = F /\ committedIds[n] /= <<>>
                 THEN Drain([nl |-> notLogged[n], lg |-> log[n], tree |-> tree[n],
                             clog |-> clog[n], fired |-> FALSE], committedIds[n])
                 ELSE [nl |-> notLogged[n], lg |-> log[n], tree |-> tree[n],
                       clog |-> clog[n], fired |-> FALSE]
       IN
       /\ inQ' = [inQ EXCEPT ![n] = Tail(@)]
       /\ snap' = [snap EXCEPT ![n] = IF snapNeeded[n] THEN tree[n] ELSE @]
       /\ notLogged' = [notLogged EXCEPT ![n] = st.nl]
       /\ log' = [log EXCEPT ![n] = st.lg]
       /\ tree' = [tree EXCEPT ![n] = st.tree]
       /\ clog' = [clog EXCEPT ![n] = st.clog]
       /\ targetFired' = (targetFired \/ st.fired)
       /\ committedIds' = [committedIds EXCEPT ![n] = IF n = F THEN <<>> ELSE @]
       /\ wtl' = [wtl EXCEPT ![n] = TRUE]
       /\ snapMode' = [snapMode EXCEPT ![n] = FALSE]
       /\ nlAcked' = [nlAcked EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<leaderVars, phase, hPhase, commitQ, applyPending, snapNeeded, lastQueued,
                   pendingTxns, omVars>>

\* FollowerZooKeeperServer.commit, :99-113, over the ids of Learner.java:845-847.
\* Empty pendingTxns warns and returns (:100-103). A mismatch exits the process
\* (:105-108): bad = TRUE.
RECURSIVE CommitAll(_, _)
CommitAll(st, ids) ==
    IF ids = <<>> \/ st.bad THEN st
    ELSE IF st.pending = <<>> THEN CommitAll(st, Tail(ids))
    ELSE IF Head(st.pending) /= Head(ids) THEN [st EXCEPT !.bad = TRUE]
    ELSE CommitAll([pending |-> Tail(st.pending),
                    q |-> Append(st.q, Head(ids)), bad |-> FALSE], Tail(ids))

\* Learner.java:731-745 + :825-848, F. After UPTODATE: logRequest for each of
\* packetsNotLogged (:840-842, never om.proposalReceived: om does not exist yet),
\* then fzk.commit for each of packetsCommitted (:845-847, S2's window: enqueued,
\* not applied). ObserverMaster starts in the next step, FollowerStartObserverMaster.
FollowerSyncUptodate ==
    /\ CanReadSync(F, "UPTODATE")
    /\ LET pend == pendingTxns \o notLogged[F]      \* FollowerZooKeeperServer.java:79-84
           st   == CommitAll([pending |-> pend, q |-> commitQ[F], bad |-> FALSE], committedIds[F])
       IN
       IF st.bad
       THEN FollowerDown /\ UNCHANGED log
       ELSE /\ inQ' = [inQ EXCEPT ![F] = Tail(@)]
            /\ phase' = [phase EXCEPT ![F] = "uptodate"]
            /\ log' = [log EXCEPT ![F] = @ \o notLogged[F]]
            /\ pendingTxns' = st.pending
            /\ commitQ' = [commitQ EXCEPT ![F] = st.q]
            /\ ResetSync(F)
            /\ UNCHANGED <<hPhase, tree, clog, applyPending, snapMode, omVars>>
    /\ UNCHANGED <<leaderVars, snap, targetFired>>

\* Learner.java:849-867 over packetsNotLogged: a proposal whose id is not at the
\* head of packetsCommitted is skipped with a warning (:855-862). A null head
\* unboxes to an exception at :855: npe = TRUE.
RECURSIVE ObsCommitAll(_, _)
ObsCommitAll(st, nl) ==
    IF nl = <<>> \/ st.npe THEN st
    ELSE IF st.ids = <<>> THEN [st EXCEPT !.npe = TRUE]
    ELSE IF Head(nl) /= Head(st.ids) THEN ObsCommitAll(st, Tail(nl))
    ELSE ObsCommitAll([ids |-> Tail(st.ids), done |-> Append(st.done, Head(nl)), npe |-> FALSE],
                      Tail(nl))

\* Learner.java:731-745 + :849-867, O. zk.startup (:827) precedes the loop, so a
\* failure in the loop leaves a started server. ozk.commitRequest
\* (ObserverZooKeeperServer.java:75-81): log, then CommitProcessor.
ObserverSyncUptodate ==
    /\ CanReadSync(O, "UPTODATE")
    /\ LET st == ObsCommitAll([ids |-> committedIds[O], done |-> <<>>, npe |-> FALSE], notLogged[O])
       IN
       /\ inQ' = [inQ EXCEPT ![O] = IF st.npe THEN <<>> ELSE Tail(@)]
       /\ phase' = [phase EXCEPT ![O] = IF st.npe THEN "lostStarted" ELSE "broadcast"]
       /\ hPhase' = [hPhase EXCEPT ![O] = IF st.npe THEN "none" ELSE @]
       /\ omActive' = (omActive /\ ~st.npe)
       /\ log' = [log EXCEPT ![O] = @ \o st.done]
       /\ commitQ' = [commitQ EXCEPT ![O] = @ \o st.done]
       /\ ResetSync(O)
    /\ UNCHANGED <<leaderVars, tree, clog, applyPending, snap, snapMode, pendingTxns,
                   omUp, omProposed, omCommitted, targetFired>>

\* Follower.java:112-116: ObserverMaster is created and starts after the sync
\* finished, with empty proposedPkts and committedPkts (ObserverMaster.java:88-89).
FollowerStartObserverMaster ==
    /\ phase[F] = "uptodate"
    /\ phase' = [phase EXCEPT ![F] = "broadcast"]
    /\ omUp' = TRUE
    /\ omProposed' = <<>>
    /\ omCommitted' = <<>>
    /\ omActive' = FALSE
    /\ UNCHANGED <<leaderVars, hPhase, inQ, dbVars, syncVars, pendingTxns, targetFired>>

-----------------------------------------------------------------------------
(* FOLLOWER AND OBSERVER BROADCAST *)

\* Follower.java:161-197: logRequest, then om.proposalReceived.
FollowerProcessProposal ==
    /\ phase[F] = "broadcast"
    /\ inQ[F] /= <<>>
    /\ Head(inQ[F]).type = "PROPOSAL"
    /\ LET z == Head(inQ[F]).zxid IN
       /\ inQ' = [inQ EXCEPT ![F] = Tail(@)]
       /\ pendingTxns' = Append(pendingTxns, z)                     \* :180, FZKS:81
       /\ log' = [log EXCEPT ![F] = Append(@, z)]                   \* :180, FZKS:83
       /\ omProposed' = Append(omProposed, z)                       \* :195, OM:355-357
    /\ UNCHANGED <<leaderVars, phase, hPhase, tree, clog, applyPending, commitQ, snap,
                   syncVars, omUp, omCommitted, omActive, targetFired>>

(*
 * Follower.java:199-207: fzk.commit, then om.proposalCommitted, one step (brief S1
 * granularity: only the packet loop runs them, and apply is its own action).
 * FollowerZooKeeperServer.commit :99-113; ObserverMaster.proposalCommitted :407-414.
 * removeProposedPacket :359-375: empty or a later head drops the commit silently
 * (:361-364); an earlier head throws (:365-372), caught at Follower.java:126.
 * evicting: S3. The packet is big enough that cacheCommittedPacket (:377-398) polls
 * the queue empty, itself included, and it is still sent (:413). Byte sizes are not
 * modeled (brief S3).
 *)
FollowerProcessCommitEx(evicting) ==
    /\ phase[F] = "broadcast"
    /\ inQ[F] /= <<>>
    /\ Head(inQ[F]).type = "COMMIT"
    /\ LET z == Head(inQ[F]).zxid
           known == omProposed /= <<>> /\ Head(omProposed) = z
           early == omProposed /= <<>> /\ Head(omProposed) < z
           mismatch == pendingTxns /= <<>> /\ Head(pendingTxns) /= z
       IN
       /\ evicting => known
       /\ IF mismatch \/ early
          THEN FollowerDown /\ UNCHANGED <<log>>        \* FZKS:105-108; OM:365-372
          ELSE
            /\ IF pendingTxns = <<>>                    \* FZKS:100-103
               THEN UNCHANGED <<pendingTxns, commitQ>>
               ELSE /\ pendingTxns' = Tail(pendingTxns) \* FZKS:110
                    /\ commitQ' = [commitQ EXCEPT ![F] = Append(@, z)]   \* FZKS:112
            /\ IF known
               THEN /\ omProposed' = Tail(omProposed)                    \* OM:373
                    /\ omCommitted' = IF evicting THEN <<>> ELSE Append(omCommitted, z)  \* OM:412
                    /\ inQ' = [inQ EXCEPT ![F] = Tail(@),
                                          ![O] = IF omActive THEN Append(@, Pkt("INFORM", z)) ELSE @]  \* OM:400-403
               ELSE /\ UNCHANGED <<omProposed, omCommitted>>             \* OM:361-364
                    /\ inQ' = [inQ EXCEPT ![F] = Tail(@)]
            /\ UNCHANGED <<phase, hPhase, tree, clog, applyPending, syncVars, omUp, omActive,
                           log>>
    /\ UNCHANGED <<leaderVars, snap, targetFired>>

FollowerProcessCommit == FollowerProcessCommitEx(FALSE)
ProposalCommittedEvicting == FollowerProcessCommitEx(TRUE)

\* Observer.java:202-208: INFORM becomes a Request and is committed, with no
\* continuity check on this path. ObserverZooKeeperServer.java:75-81: log, then
\* CommitProcessor.
ObserverProcessInform ==
    /\ phase[O] = "broadcast"
    /\ inQ[O] /= <<>>
    /\ Head(inQ[O]).type = "INFORM"
    /\ LET z == Head(inQ[O]).zxid IN
       /\ inQ' = [inQ EXCEPT ![O] = Tail(@)]
       /\ log' = [log EXCEPT ![O] = Append(@, z)]
       /\ commitQ' = [commitQ EXCEPT ![O] = Append(@, z)]
    /\ UNCHANGED <<leaderVars, phase, hPhase, tree, clog, applyPending, snap, syncVars,
                   pendingTxns, omVars, targetFired>>

-----------------------------------------------------------------------------
(* APPLY AND THE TARGET *)

\* A server's commit processor runs while the server is started.
CanApply(n) == IF n = L THEN TRUE ELSE phase[n] \in {"uptodate", "broadcast"}

\* ZooKeeperServer.processTxn :1863, DataTree.java:1105-1107. One write at a time
\* in CommitProcessor order. The DataTree is updated before the committed log.
ApplyTree(n) ==
    /\ CanApply(n)
    /\ applyPending[n] = NoZxid
    /\ commitQ[n] /= <<>>
    /\ LET z == Head(commitQ[n]) IN
       /\ tree' = [tree EXCEPT ![n] = Max(@, z)]
       /\ applyPending' = [applyPending EXCEPT ![n] = z]
       /\ commitQ' = [commitQ EXCEPT ![n] = Tail(@)]
    /\ UNCHANGED <<leaderVars, connVars, clog, log, snap, syncVars, pendingTxns, omVars, targetFired>>

(*
 * ZooKeeperServer.java:1888 -> ZKDatabase.addCommittedProposal(Request), :322-353.
 * The live caller of the target check. The other callers (log replay at
 * ZKDatabase.java:276-279 and the synchronous processTxn in the sync path) reach
 * the same PhiT through ProcessStep.
 *)
TargetCheck(n) ==
    /\ applyPending[n] /= NoZxid
    /\ LET z == applyPending[n] IN
       IF PhiT(clog[n], z)
       THEN /\ targetFired' = TRUE                       \* throw at ZKDatabase.java:341
            /\ UNCHANGED <<clog, applyPending>>
       ELSE /\ targetFired' = targetFired
            /\ clog' = [clog EXCEPT ![n] = ClogAdd(@, z)]
            /\ applyPending' = [applyPending EXCEPT ![n] = NoZxid]
    /\ UNCHANGED <<leaderVars, connVars, tree, commitQ, log, snap, syncVars, pendingTxns, omVars>>

TargetSafe == ~targetFired

-----------------------------------------------------------------------------
(* PROCESS LIFECYCLE *)

\* Start of a learner process: QuorumPeer loads the database, replaying the log
\* through addCommittedProposal (ZKDatabase.java:288-290). The replay is a caller of
\* the target check. FileTxnSnapLog.java:326-360.
LearnerStart(n) ==
    /\ phase[n] = "down"
    /\ LET st == LoadDataBase(snap[n], log[n]) IN
       /\ tree' = [tree EXCEPT ![n] = st.tree]
       /\ clog' = [clog EXCEPT ![n] = st.clog]
       /\ targetFired' = (targetFired \/ st.fired)
       /\ phase' = [phase EXCEPT ![n] = "connecting"]
    /\ UNCHANGED <<leaderVars, hPhase, inQ, applyPending, commitQ, log, snap, syncVars,
                   pendingTxns, omVars>>

\* The workload's fault: MainThread.shutdown of F (TestAdhocWorkloadB6.java:121).
FollowerCrash ==
    /\ phase[F] /= "down"
    /\ FollowerDown
    /\ UNCHANGED <<leaderVars, log, snap, targetFired>>

\* The workload's fault: MainThread.shutdown of O (TestAdhocWorkloadB6.java:120).
ObserverCrash ==
    /\ phase[O] /= "down"
    /\ ObserverDown
    /\ UNCHANGED <<leaderVars, log, snap, targetFired>>

(*
 * Learner.shutdown -> ZooKeeperServer.shutdown(syncMode == SNAP), Learner.java:910-926,
 * ZooKeeperServer.java:922-949, then O connects again.
 * Started server: the commit processor finishes its current request, its queue is
 * dropped, and the database fast-forwards from the log, through addCommittedProposal
 * (:936). Not started: canShutdown is false, so no fast-forward; SNAP mode clears
 * the database (:946-948) and the next getLastLoggedZxid reloads it.
 *)
ObserverShutdown ==
    /\ phase[O] \in {"lostStarted", "lostSync"}
    /\ applyPending[O] = NoZxid
    /\ LET st == IF phase[O] = "lostStarted"
                 THEN FastForward(tree[O], clog[O], log[O])
                 ELSE IF snapMode[O]
                      THEN LoadDataBase(snap[O], log[O])
                      ELSE [tree |-> tree[O], clog |-> clog[O], fired |-> FALSE]
       IN
       /\ tree' = [tree EXCEPT ![O] = st.tree]
       /\ clog' = [clog EXCEPT ![O] = st.clog]
       /\ targetFired' = (targetFired \/ st.fired)
       /\ commitQ' = [commitQ EXCEPT ![O] = <<>>]
       /\ phase' = [phase EXCEPT ![O] = "connecting"]
       /\ snapMode' = [snapMode EXCEPT ![O] = FALSE]
    /\ UNCHANGED <<leaderVars, hPhase, inQ, applyPending, log, snap, notLogged, committedIds,
                   wtl, snapNeeded, lastQueued, nlAcked, pendingTxns, omVars>>

-----------------------------------------------------------------------------
(* NEXT *)

\* Everything that happens with no fault. Bounded only by MaxTxn. The MC layer
\* splits Propose/Commit by whether they fall in F's sync window.
ReactiveNext ==
    \/ \E u \in BOOLEAN : LeaderSyncFollower(u)
    \/ \E u \in BOOLEAN : OmSyncObserver(u)
    \/ \E n \in Learners :
        \/ HandlerSendSnap(n)
        \/ HandlerQueueNewLeader(n)
        \/ HandlerQueueUptodate(n)
        \/ LearnerReadDiff(n)
        \/ LearnerReadSnap(n)
        \/ LearnerReadTrunc(n)
        \/ LearnerSyncProposal(n)
        \/ LearnerSyncCommit(n)
        \/ LearnerSyncInform(n)
        \/ LearnerSyncNewLeader(n)
        \/ LearnerStart(n)
    \/ FollowerSyncUptodate
    \/ ObserverSyncUptodate
    \/ FollowerStartObserverMaster
    \/ FollowerProcessProposal
    \/ FollowerProcessCommit
    \/ ObserverProcessInform
    \/ \E n \in Servers : ApplyTree(n) \/ TargetCheck(n)
    \/ ObserverShutdown

Next ==
    /\ ~targetFired                 \* Stop after the target fires (tla-patterns section 1).
    /\ \/ ClientPropose
       \/ LeaderTryToCommit
       \/ ReactiveNext
       \/ ProposalCommittedEvicting
       \/ FollowerCrash
       \/ ObserverCrash

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* STRUCTURAL INVARIANTS (brief section 5) *)

Zxids == 0..MaxTxn
PacketTypes == {"PROPOSAL", "COMMIT", "INFORM", "DIFF", "TRUNC", "SNAP", "NEWLEADER", "UPTODATE"}

ClogOk(c) ==
    /\ c.empty \in BOOLEAN
    /\ c.min \in Zxids
    /\ c.max \in Zxids
    /\ c.empty => (c.min = 0 /\ c.max = 0)
    /\ ~c.empty => c.min <= c.max

TypeOK ==
    /\ lProposed \in Zxids
    /\ lCommitted \in 0..lProposed
    /\ \A n \in Learners :
        /\ phase[n] \in {"down", "connecting", "awaitOp", "sync", "uptodate", "broadcast",
                         "lostStarted", "lostSync"}
        /\ hPhase[n] \in {"none", "needSnap", "syncing", "newleader", "done"}
        /\ \A i \in DOMAIN inQ[n] : inQ[n][i].type \in PacketTypes /\ inQ[n][i].zxid \in Zxids
        /\ log[n] \in Seq(Zxids)
        /\ snap[n] \in Zxids
        /\ notLogged[n] \in Seq(Zxids)
        /\ committedIds[n] \in Seq(Zxids)
        /\ wtl[n] \in BOOLEAN
        /\ snapNeeded[n] \in BOOLEAN
        /\ lastQueued[n] \in Zxids
        /\ snapMode[n] \in BOOLEAN
        /\ nlAcked[n] \in BOOLEAN
    /\ \A n \in Servers :
        /\ tree[n] \in Zxids
        /\ ClogOk(clog[n])
        /\ applyPending[n] \in Zxids \cup {NoZxid}
        /\ commitQ[n] \in Seq(Zxids)
    /\ pendingTxns \in Seq(Zxids)
    /\ omUp \in BOOLEAN
    /\ omProposed \in Seq(Zxids)
    /\ omCommitted \in Seq(Zxids)
    /\ omActive \in BOOLEAN
    /\ targetFired \in BOOLEAN

\* "A message carries only values its sender held": every packet and cached entry
\* carries a zxid the leader proposed, and a commit-like one a zxid it committed.
\* A nonzero SNAP/TRUNC/DIFF op zxid is a committed-or-proposed value of the master.
PacketsFromHistory ==
    LET Proposed == 1..lProposed
        Committed == 1..lCommitted
    IN
    /\ \A n \in Learners :
        /\ \A i \in DOMAIN inQ[n] :
            LET p == inQ[n][i] IN
            /\ p.type = "PROPOSAL" => p.zxid \in Proposed
            /\ p.type \in {"COMMIT", "INFORM"} => p.zxid \in Committed
            /\ p.type \in {"DIFF", "TRUNC", "SNAP"} => p.zxid \in 0..lProposed
        /\ \A i \in DOMAIN notLogged[n] : notLogged[n][i] \in Proposed
        /\ \A i \in DOMAIN committedIds[n] : committedIds[n][i] \in Committed
    /\ \A i \in DOMAIN omProposed : omProposed[i] \in Proposed
    /\ \A i \in DOMAIN omCommitted : omCommitted[i] \in Committed
    /\ \A i \in DOMAIN pendingTxns : pendingTxns[i] \in Proposed

\* Temporary sanity check, tla-patterns section 2: TLC must violate this, proving
\* that TargetCheck is enabled on a non-empty committed log. A model that never
\* enables TargetCheck proves nothing.
TargetReached ==
    ~ \E n \in Servers : applyPending[n] /= NoZxid /\ ~clog[n].empty

\* Same, on the observer (the role every Scenario depends on).
TargetReachedOnObserver ==
    ~ (applyPending[O] /= NoZxid /\ ~clog[O].empty)

================================================================================
