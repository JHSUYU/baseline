--------------------------------- MODULE base ---------------------------------
(***************************************************************************)
(* Specula ad hoc target zk-adhoc-04: Apache ZooKeeper 3.10.0-SNAPSHOT,    *)
(* pinned tree eab16599.  Category A (distributed / message passing).      *)
(*                                                                         *)
(* All file:line references are relative to                                *)
(*   zookeeper-server/src/main/java/org/apache/zookeeper/                  *)
(* unless a path says otherwise.                                           *)
(*                                                                         *)
(* TARGET (the only hunting property):                                     *)
(*   server/ZooKeeperServer.java:1504-1516                                 *)
(*     ZooKeeperServer.processConnectRequest(ServerCnxn, ConnectRequest)   *)
(*     if (request.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid)    *)
(*       throw new CloseRequestException(.., CLIENT_ZXID_AHEAD); // :1516  *)
(*   phi_T(c, s) == cLastZxid[c] > lpz[s]   (signed long comparison)       *)
(*   TargetSafe  == ~targetFired                                           *)
(*                                                                         *)
(* The two operands:                                                       *)
(*   lpz[s]       = s's zkDb.dataTree.lastProcessedZxid (DataTree.java:845)*)
(*   cLastZxid[c] = ClientCnxn.lastZxid (ClientCnxn.java:820), sent as     *)
(*                  ConnectRequest.lastZxidSeen (ClientCnxn.java:1013)     *)
(*                                                                         *)
(* Scenarios (modeling brief section 2) and the extensions they motivate:  *)
(*   S1 txn-less epoch zxid <<e,0>> (Leader.java:1609) reaches clients,    *)
(*      never DIFF-synced learners (Learner.java:586-595):                 *)
(*      LeaderStartup/LeaderServe, LearnerHandlerSync (sync plans), RO     *)
(*      carry-over                                                         *)
(*   S2 read-only server serves logged-but-uncommitted txns (shutdown(false)*)
(*      fast-forward, ZooKeeperServer.java:928-940): log/toLog, acks,      *)
(*      FastForward, PeerStop(graceful), StartRO                           *)
(*   S3 server behind the client's view: commitQ/ApplyCommitted (async     *)
(*      apply), pktCommitted deferred past startup (Learner.java:827 vs    *)
(*      :845-847), frozen RO server, stale learner                         *)
(*   S4 untrusted empty DB served read-only at -1 (FileTxnSnapLog.java:307)*)
(*      : TrustEmptyDB, RestoreZ                                           *)
(*                                                                         *)
(* Zxids.  A zxid (epoch<<32 | counter) is encoded as epoch*ZB + counter,  *)
(* because TLC integers are 32-bit.  ZB must exceed every counter used.    *)
(* -1 is the "possibly missing data" value of FileTxnSnapLog.java:307.     *)
(*                                                                         *)
(* Abstractions (each justified at the place it is used):                  *)
(*  - leader->learner TCP stream = FIFO inbox[F]; learner->leader ACKs are *)
(*    recorded at the leader in the step that sends them;                  *)
(*  - FLE is abstracted to Elect(Q, L) / JoinLeader(s, L) with the code's  *)
(*    vote order (FastLeaderElection.java:717-743) and -1 rule (:1000-1007)*)
(*  - observers, dynamic reconfig, global sessions, throttling, auth and   *)
(*    multi-op atomicity are not modeled (brief section 3.2).              *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets, TLC

-----------------------------------------------------------------------------
(* CONSTANTS                                                               *)
-----------------------------------------------------------------------------

CONSTANT Server        \* peer ids = QuorumPeer.getMyId(); integers, because
                       \* FLE breaks vote ties by sid (FastLeaderElection.java:741-742)
CONSTANT Client        \* client handles (ZooKeeper objects); integers
CONSTANT ZB            \* zxid counter base: Z(e, c) == e * ZB + c (ZxidUtils.makeZxid)
CONSTANT RoEnabled     \* System property readonlymode.enabled (QuorumPeer.java:1532)
CONSTANT TrustEmptyDB  \* zookeeper.db.autocreate, default true (FileTxnSnapLog.java:73-75, 172-173, 263)
CONSTANT ClientCanBeRO \* ZooKeeper(.., canBeReadOnly) => ConnectRequest.readOnly (ClientCnxn.java:1013)
CONSTANT AsyncApply    \* TRUE: CommitProcessor hand-off (CommitProcessor.java:590-599) and the
                       \* apply (CommitProcessor.java:380 -> DataTree.java:1105-1106) are separate
                       \* steps, as in the code.  FALSE is a hunting knob that merges them.

ASSUME Server \subseteq (Nat \ {0}) /\ Server # {}
ASSUME Client \subseteq (Nat \ {0}) /\ Client # {}
ASSUME ZB \in Nat /\ ZB >= 2
ASSUME RoEnabled \in BOOLEAN /\ TrustEmptyDB \in BOOLEAN
ASSUME ClientCanBeRO \in BOOLEAN /\ AsyncApply \in BOOLEAN

-----------------------------------------------------------------------------
(* SENTINELS AND HELPERS                                                   *)
-----------------------------------------------------------------------------

NoServer    == 0       \* "no server": not connected / no leader
ExpiredSess == -1      \* a client session whose server instance is gone
NoSnap      == -1      \* no snapshot file in the data dir

Z(e, c)  == e * ZB + c                                  \* ZxidUtils.makeZxid
Epoch(z) == IF z < 0 THEN -1 ELSE z \div ZB             \* ZxidUtils.getEpochFromZxid
Ctr(z)   == IF z < 0 THEN -1 ELSE z % ZB                \* zxid & 0xffffffffL

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y
MaxOr(S, d) == IF S = {} THEN d ELSE Max(S)

Quorum(Q) == 2 * Cardinality(Q) > Cardinality(Server)  \* QuorumMaj.containsQuorum

SeqSet(q) == {q[i] : i \in DOMAIN q}

RECURSIVE AscSeq(_)
AscSeq(S) == IF S = {} THEN <<>> ELSE LET m == Min(S) IN <<m>> \o AscSeq(S \ {m})

Pkt(t, z) == [t |-> t, z |-> z]          \* QuorumPacket(type, zxid, ..)

RECURSIVE PropCommitPkts(_)
PropCommitPkts(zs) ==
    IF zs = <<>> THEN <<>>
    ELSE <<Pkt("PROPOSAL", Head(zs)), Pkt("COMMIT", Head(zs))>> \o PropCommitPkts(Tail(zs))

RECURSIVE PropPkts(_)
PropPkts(zs) ==
    IF zs = <<>> THEN <<>> ELSE <<Pkt("PROPOSAL", Head(zs))>> \o PropPkts(Tail(zs))

-----------------------------------------------------------------------------
(* VARIABLES                                                               *)
-----------------------------------------------------------------------------

\* --- Peer lifecycle (QuorumPeer.run, QuorumPeer.java:1522-1641) ---
VARIABLE role      \* "DOWN" | "LOOKING" | "FOLLOWING" | "LEADING"  (ServerState + stopped process)
VARIABLE phase     \* progress inside the role, see PhaseSet
VARIABLE leaderOf  \* followers: the peer they follow; NoServer otherwise
VARIABLE lepoch    \* epoch of the leader instance a peer leads / is synced to (0 = none)
VARIABLE serving   \* "NONE" | "RO" | "RW": server object attached to the cnxn factory AND running
                   \* (NIOServerCnxn.java:438-441, ServerCnxn.java:599-601); "RO" = ReadOnlyZooKeeperServer
VARIABLE dbInit    \* ZKDatabase.initialized (ZKDatabase.java:191, 291, 306)

\* --- Data tree and persistence (DataTree, ZKDatabase, FileTxnSnapLog) ---
VARIABLE lpz       \* zkDb.dataTree.lastProcessedZxid: the server operand of the target
VARIABLE clog      \* ZKDatabase.committedLog as a set of zxids (ZKDatabase.java:322-353)
VARIABLE log       \* zxids in the on-disk txn log (FileTxnLog); no commit marker exists
VARIABLE snapZ     \* zxid of the highest-zxid snapshot file (FileSnap picks it); NoSnap = none
VARIABLE curEpoch  \* QuorumPeer currentEpoch file (FLE vote epoch, FastLeaderElection.java:876-888)
VARIABLE accEpoch  \* QuorumPeer acceptedEpoch file (Leader.getEpochToPropose input)

\* --- Learner side (Learner.syncWithLeader, Follower, FollowerZooKeeperServer) ---
VARIABLE syncMode     \* QuorumPeer.syncMode: "NONE"|"DIFF"|"SNAP"|"TRUNC" (Learner.java:588,597,620,816)
VARIABLE inbox        \* leader -> learner packet stream (FIFO), records Pkt(t, z)
VARIABLE pktNotLogged \* Learner.syncWithLeader packetsNotLogged (Learner.java:583)
VARIABLE pktCommitted \* Learner.syncWithLeader packetsCommitted (Learner.java:582)
VARIABLE pendingTxns  \* FollowerZooKeeperServer.pendingTxns (FollowerZooKeeperServer.java:77)
VARIABLE toLog        \* follower SyncRequestProcessor queue: received, not yet logged+ACKed
VARIABLE commitQ      \* CommitProcessor.committedRequests: committed, not yet applied (all roles)

\* --- Leader side (Leader, LearnerHandler) ---
VARIABLE hzxid         \* ZooKeeperServer.hzxid (ZooKeeperServer.java:214)
VARIABLE fwd           \* Leader.forwardingFollowers (Leader.java:219-227)
VARIABLE nlAcks        \* NEWLEADER ack set of the leader instance (Leader.waitForNewLeaderAck)
VARIABLE utdSent       \* learners whose LearnerHandler queued UPTODATE (LearnerHandler.java:653)
VARIABLE acks          \* set of <<sid, zxid>>: Proposal.addAck (Leader.java:1099)
VARIABLE lastCommitted \* Leader.lastCommitted (Leader.java:1212, 1221, 1572)

\* --- Client (ClientCnxn) ---
VARIABLE cState     \* "CONNECTING" | "CONNECTED" | "CONNECTEDREADONLY" | "CLOSED" (ZooKeeper.States)
VARIABLE cConn      \* server of the current connection, NoServer if none
VARIABLE cLastZxid  \* ClientCnxn.lastZxid: the client operand of the target
VARIABLE cRwTarget  \* ClientCnxn.rwServerAddress (ClientCnxn.java:1177-1179, 1367)
VARIABLE cSeenRw    \* ClientCnxn.seenRwServerBefore (ClientCnxn.java:217, 1426)
VARIABLE cSess      \* server instance holding the client's local session; ExpiredSess when gone
VARIABLE cReplies   \* FIFO of reply-header zxids in flight to the client (pendingQueue order)

\* --- Target and ghosts ---
VARIABLE targetFired \* the failing branch at ZooKeeperServer.java:1516 was taken
VARIABLE targetInfo  \* diagnostic record of the hit (no invariant reads it)
VARIABLE committed   \* ghost: zxids that are part of a committed history (hit classification)
VARIABLE served      \* ghost: lpz values carried by replies the client read (ClientZxidWasServed)

peerVars   == <<role, phase, leaderOf, lepoch, serving, dbInit>>
dataVars   == <<lpz, clog, log, snapZ, curEpoch, accEpoch>>
learnVars  == <<syncMode, inbox, pktNotLogged, pktCommitted, pendingTxns, toLog, commitQ>>
leaderVars == <<hzxid, fwd, nlAcks, utdSent, acks, lastCommitted>>
clientVars == <<cState, cConn, cLastZxid, cRwTarget, cSeenRw, cSess, cReplies>>
ghostVars  == <<targetFired, targetInfo, committed, served>>

vars == <<peerVars, dataVars, learnVars, leaderVars, clientVars, ghostVars>>

RoleSet  == {"DOWN", "LOOKING", "FOLLOWING", "LEADING"}
\* LEADING:   ELECTED -> SYNC (discovery done, Leader.java:713) -> STARTED (zk.startup, RUNNING,
\*            Leader.java:1599) -> BROADCAST (lpz bumped :1609 and attached for clients :762)
\* FOLLOWING: ELECTED -> DISCOVERED (epoch accepted) -> SYNC (sync stream queued)
\*            -> SYNC2 (NEWLEADER done, Learner.java:746-821) -> STARTED (UPTODATE + zk.startup,
\*            Learner.java:743, 827) -> BROADCAST (Learner.java:837-848 done)
PhaseSet == {"NONE", "ELECTED", "DISCOVERED", "SYNC", "SYNC2", "STARTED", "BROADCAST"}
PktTypes == {"DIFF", "SNAP", "TRUNC", "PROPOSAL", "COMMIT", "NEWLEADER", "UPTODATE"}

NoInfo == [cid |-> 0, sid |-> 0, cz |-> 0, sz |-> 0, srv |-> "NONE", role |-> "NONE", cls |-> "NONE"]

-----------------------------------------------------------------------------
(* DERIVED OPERATORS                                                       *)
-----------------------------------------------------------------------------

\* FLE vote order (peerEpoch, zxid, sid): FastLeaderElection.totalOrderPredicate :738-742.
\* Vote fields: getPeerEpoch() = currentEpoch (:876-888), getInitLastLoggedZxid() =
\* QuorumPeer.getLastLoggedZxid() = lpz (QuorumPeer.java:1386-1390), sid = getMyId().
VoteGT(a, b) ==
    \/ curEpoch[a] > curEpoch[b]
    \/ /\ curEpoch[a] = curEpoch[b]
       /\ \/ lpz[a] > lpz[b]
          \/ lpz[a] = lpz[b] /\ a > b

\* StateSummary.isMoreRecentThan, checked by Leader.waitForEpochAck (Leader.java:1520-1527)
MoreRecent(f, l) ==
    \/ curEpoch[f] > curEpoch[l]
    \/ curEpoch[f] = curEpoch[l] /\ lpz[f] > lpz[l]

\* FileTxnSnapLog.restore (FileTxnSnapLog.java:252-313) as called by ZKDatabase.loadDataBase:
\*  - no snapshot (deserialize returns -1, :283) and empty log: 0 if trustEmptyDB (:297-303)
\*    else lastProcessedZxid = -1 (:304-309);
\*  - otherwise the highest-zxid snapshot (FileSnap.java:117 sets lpz to its zxid) then
\*    fastForwardFromEdits replays every logged txn above it (:312, :326-377).
\* A data dir with a txn log but no snapshot throws (:286-290); no model path creates one:
\* every peer that logs a txn has a snapshot (restore :300, Leader.java:646, Learner.java:759-761).
RestoreZ(s) ==
    IF snapZ[s] = NoSnap
    THEN IF TrustEmptyDB THEN 0 ELSE -1
    ELSE MaxOr({snapZ[s]} \cup log[s], snapZ[s])

\* snapshot written by restore for a trusted empty DB (FileTxnSnapLog.java:300, save :474-482)
RestoreSnap(s) == IF snapZ[s] = NoSnap /\ TrustEmptyDB THEN 0 ELSE snapZ[s]

\* committedLog rebuilt by the PlayBackListener during restore (ZKDatabase.java:276-280)
RestoreClog(s) == {x \in log[s] : x > snapZ[s]}

\* Zxids a leader instance has proposed in its epoch: ZooKeeperServer.getNextZxid (:694-696)
\* starting from makeZxid(epoch, 0) (Leader.java:657).
ProposedBy(l) ==
    IF role[l] = "LEADING" /\ phase[l] = "BROADCAST" THEN Z(lepoch[l], 1) .. hzxid[l] ELSE {}

\* Leader.outstandingProposals: proposed, not yet committed (commit is in order, Leader.java:978-996)
Outstanding(l) ==
    IF role[l] = "LEADING" /\ phase[l] = "BROADCAST" THEN (lastCommitted[l] + 1) .. hzxid[l] ELSE {}

\* Requests still queued in a RUNNING server's SyncRequestProcessor.  A graceful
\* ZooKeeperServer.shutdown -> shutdownComponents -> SyncRequestProcessor.shutdown appends
\* them to the txn log before it returns (requests ahead of REQUEST_OF_DEATH are processed).
\* Leader: ProposalRequestProcessor -> SyncRequestProcessor (own proposals not yet logged).
UnloggedQueued(s) ==
    IF role[s] = "LEADING" THEN ProposedBy(s) \ log[s] ELSE SeqSet(toLog[s])

Running(s) ==   \* ZooKeeperServer state RUNNING for the role's server object
    \/ role[s] = "LEADING" /\ phase[s] \in {"STARTED", "BROADCAST"}   \* Leader.java:1599
    \/ role[s] = "FOLLOWING" /\ phase[s] \in {"STARTED", "BROADCAST"}  \* Learner.java:827

\* A follower's leader instance is still there (its TCP connection is alive).
LeaderAlive(f) ==
    LET l == leaderOf[f] IN
    /\ l \in Server
    /\ role[l] = "LEADING"
    /\ phase[f] = "ELECTED" \/ lepoch[l] = lepoch[f]

\* Learners still following leader l: they keep the leader's synced set alive
\* (Leader.java:788-805 counts LearnerHandler.synced() plus the leader itself).
Supporters(l) ==
    {l} \cup {f \in Server :
                /\ role[f] = "FOLLOWING" /\ leaderOf[f] = l
                /\ phase[f] = "ELECTED" \/ lepoch[f] = lepoch[l]}

\* Leader history at establishment: everything applied in its tree (ghost only).
LeaderHistory(l) == clog[l] \cup {x \in log[l] : x <= lpz[l]}

\* Learner.syncWithLeader writeToTxnLog (Learner.java:647, 764): FALSE only before
\* NEWLEADER when snapshotNeeded, i.e. after SNAP or TRUNC (Learner.java:577-595).
WriteToTxnLog(f) == phase[f] = "SYNC2" \/ syncMode[f] = "DIFF"

\* New epoch proposed by a leader with discovery quorum Q (Leader.getEpochToPropose :1469-1502)
NewEpoch(Q) == Max({accEpoch[q] : q \in Q}) + 1

(***************************************************************************)
(* LearnerHandler.syncFollower (LearnerHandler.java:780-938) and           *)
(* queueCommittedProposals (:951-1040), reduced to what they decide:       *)
(* the op packet (DIFF/TRUNC/SNAP and its zxid), the committed proposals   *)
(* queued as PROPOSAL+COMMIT (q), and currentZxid passed to                *)
(* Leader.startForwarding (cur).  peer = the learner's ACKEPOCH zxid =     *)
(* getLastLoggedZxid() = lpz[f] (Learner.java:490, 527).                   *)
(***************************************************************************)
SyncPlans(l, f) ==
    LET peer  == lpz[f]
        lz    == lpz[l]                                     \* :804
        C     == clog[l]
        minC  == IF C = {} THEN lz ELSE Min(C)               \* :815-828
        maxC  == IF C = {} THEN lz ELSE Max(C)
        newEp == Ctr(peer) = 0                               \* :792 isPeerNewEpochZxid
        Snap  == [mode |-> "SNAP", z |-> lz, q |-> {}, cur |-> lz]  \* :563-588, zxidToSend :568
    IN
    IF lz = peer
    THEN {[mode |-> "DIFF", z |-> peer, q |-> {}, cur |-> peer]}      \* :849-857 empty diff
    ELSE IF peer > maxC /\ ~newEp
    THEN {[mode |-> "TRUNC", z |-> maxC, q |-> {}, cur |-> maxC]}     \* :858-867
    ELSE IF maxC >= peer /\ minC <= peer                              \* :868-873 committedLog
    THEN LET Above == {x \in C : x > peer}
             Below == {x \in C : x < peer}
         IN IF peer \in C \/ newEp
            THEN {[mode |-> "DIFF", z |-> maxC, q |-> Above, cur |-> MaxOr(Above, peer)]} \* :976-994
            ELSE IF Epoch(Min(Above)) # Epoch(peer)
            THEN {Snap}                                       \* :998-1004 return, then :930-935
            ELSE {[mode |-> "TRUNC", z |-> Max(Below), q |-> Above,
                   cur |-> MaxOr(Above, peer)]}              \* :1006-1011 TRUNC(prevProposalZxid)
    ELSE IF peer < minC                                       \* :874-907 txnlog + committedLog
    THEN LET Lg == {x \in log[l] : peer < x /\ x <= minC} \cup {x \in C : x > minC}
         IN IF peer \in log[l] /\ minC \in log[l]
            \* getProposalsFromTxnLog is non-empty only if the log starts exactly at peer
            \* (ZKDatabase.java:397-405) and the on-disk size is under 0.33 x snapshot size
            \* (:407-414, data-size dependent, hence both outcomes); a gap below minC
            \* reverts to SNAP (LearnerHandler.java:886-895).
            THEN {Snap, [mode |-> "DIFF", z |-> maxC, q |-> Lg, cur |-> MaxOr(Lg, peer)]}
            ELSE {Snap}
    ELSE {Snap}                                               \* :908-919 unhandled -> snapshot

-----------------------------------------------------------------------------
(* SHARED EFFECTS                                                          *)
-----------------------------------------------------------------------------

\* Closing all client connections of server s (closeAllConnections; NIOServerCnxn close).
\* The local session tracker belongs to the server object, so local sessions created
\* there die with it (LearnerSessionTracker / LocalSessionTracker are per instance).
DropClients(s) ==
    /\ cState' = [c \in Client |->
                    IF cConn[c] = s /\ cState[c] \in {"CONNECTED", "CONNECTEDREADONLY"}
                    THEN "CONNECTING" ELSE cState[c]]
    /\ cConn' = [c \in Client |-> IF cConn[c] = s THEN NoServer ELSE cConn[c]]
    /\ cSess' = [c \in Client |-> IF cSess[c] = s THEN ExpiredSess ELSE cSess[c]]
    /\ cReplies' = [c \in Client |-> IF cConn[c] = s THEN <<>> ELSE cReplies[c]]   \* lost

\* zkDb.fastForwardDataBase (ZKDatabase.java:304-308) -> FileTxnSnapLog.fastForwardFromEdits
\* (:326-377): replay every logged txn above lastProcessedZxid (:330), with NO commit check,
\* adding each to committedLog through the listener (:360, ZKDatabase.java:276-280).
FFlpz(s, lg)  == MaxOr({lpz[s]} \cup {x \in lg : x > lpz[s]}, lpz[s])
FFclog(s, lg) == clog[s] \cup {x \in lg : x > lpz[s]}

\* Learner side of losing the leader (Follower.followLeader exits, QuorumPeer.java:1618-1621):
\* Learner.shutdown (Learner.java:910-926) then updateServerState -> LOOKING.
LearnerShutdown(f) ==
    LET run  == Running(f)
        full == syncMode[f] = "SNAP"              \* :922-924 shutdown(syncMode == SNAP)
        lg   == IF run THEN log[f] \cup UnloggedQueued(f) ELSE log[f]
    IN
    /\ role'     = [role EXCEPT ![f] = "LOOKING"]
    /\ phase'    = [phase EXCEPT ![f] = "NONE"]
    /\ leaderOf' = [leaderOf EXCEPT ![f] = NoServer]
    /\ lepoch'   = [lepoch EXCEPT ![f] = 0]
    /\ serving'  = [serving EXCEPT ![f] = "NONE"]              \* :911 setZooKeeperServer(null)
    /\ DropClients(f)                                         \* :912 closeAllConnections
    /\ log' = [log EXCEPT ![f] = lg]                          \* SyncRequestProcessor drained
    /\ IF full
       THEN \* not RUNNING (syncMode is reset to NONE at NEWLEADER, before startup), so
            \* canShutdown() is false (ZooKeeperServer.java:922-925) and zkDb.clear() runs
            \* (:946-948, ZKDatabase.java:175-192): new DataTree, lpz = 0, initialized = false
            /\ lpz'    = [lpz EXCEPT ![f] = 0]
            /\ clog'   = [clog EXCEPT ![f] = {}]
            /\ dbInit' = [dbInit EXCEPT ![f] = FALSE]
       ELSE IF run
       THEN \* shutdown(false) on a RUNNING server: fast-forward (ZooKeeperServer.java:928-940)
            /\ lpz'  = [lpz EXCEPT ![f] = FFlpz(f, lg)]
            /\ clog' = [clog EXCEPT ![f] = FFclog(f, lg)]
            /\ UNCHANGED dbInit
       ELSE UNCHANGED <<lpz, clog, dbInit>>                   \* not RUNNING: nothing (:943-945)
    /\ inbox'        = [inbox EXCEPT ![f] = <<>>]
    /\ pktNotLogged' = [pktNotLogged EXCEPT ![f] = <<>>]
    /\ pktCommitted' = [pktCommitted EXCEPT ![f] = <<>>]
    /\ pendingTxns'  = [pendingTxns EXCEPT ![f] = <<>>]
    /\ toLog'        = [toLog EXCEPT ![f] = <<>>]
    /\ commitQ'      = [commitQ EXCEPT ![f] = <<>>]          \* CommitProcessor halted
    \* the leader's LearnerHandler for f exits (removeLearnerHandler)
    /\ fwd'     = [l \in Server |-> fwd[l] \ {f}]
    /\ utdSent' = [l \in Server |-> utdSent[l] \ {f}]
    \* NEWLEADER acks stay in newLeaderProposal while the leader is establishing; after
    \* quorumFormed only the per-handler ack gates UPTODATE.
    /\ nlAcks'  = [l \in Server |-> IF phase[l] \in {"STARTED", "BROADCAST"}
                                     THEN nlAcks[l] \ {f} ELSE nlAcks[l]]
    /\ UNCHANGED <<syncMode, snapZ, curEpoch, accEpoch, hzxid, acks, lastCommitted>>

\* The whole peer process goes away: QuorumUtil.shutdown -> QuorumPeer.shutdown
\* (QuorumPeer.java:1681-1715), a crash, or ServiceUtils.requestSystemExit.
\* Only the data dir survives (log, snapshots, epoch files).  graceful = the
\* server object was shut down (SyncRequestProcessor drained into the log).
ResetPeer(s, graceful) ==
    /\ role'     = [role EXCEPT ![s] = "DOWN"]
    /\ phase'    = [phase EXCEPT ![s] = "NONE"]
    /\ leaderOf' = [leaderOf EXCEPT ![s] = NoServer]
    /\ lepoch'   = [lepoch EXCEPT ![s] = 0]
    /\ serving'  = [serving EXCEPT ![s] = "NONE"]           \* :1690 shutdownServerCnxnFactory
    /\ dbInit'   = [dbInit EXCEPT ![s] = FALSE]             \* :1708-1714 zkDb.close
    /\ DropClients(s)
    /\ lpz'  = [lpz EXCEPT ![s] = 0]                         \* in-memory tree lost
    /\ clog' = [clog EXCEPT ![s] = {}]
    /\ log'  = [log EXCEPT ![s] = IF graceful /\ Running(s) THEN @ \cup UnloggedQueued(s) ELSE @]
    /\ syncMode'     = [syncMode EXCEPT ![s] = "NONE"]
    /\ inbox'        = [inbox EXCEPT ![s] = <<>>]
    /\ pktNotLogged' = [pktNotLogged EXCEPT ![s] = <<>>]
    /\ pktCommitted' = [pktCommitted EXCEPT ![s] = <<>>]
    /\ pendingTxns'  = [pendingTxns EXCEPT ![s] = <<>>]
    /\ toLog'        = [toLog EXCEPT ![s] = <<>>]
    /\ commitQ'      = [commitQ EXCEPT ![s] = <<>>]
    /\ hzxid'         = [hzxid EXCEPT ![s] = 0]
    /\ fwd'           = [l \in Server |-> IF l = s THEN {} ELSE fwd[l] \ {s}]
    /\ utdSent'       = [l \in Server |-> IF l = s THEN {} ELSE utdSent[l] \ {s}]
    /\ nlAcks'        = [l \in Server |-> IF l = s THEN {}
                                          ELSE IF phase[l] \in {"STARTED", "BROADCAST"}
                                          THEN nlAcks[l] \ {s}
                                          ELSE nlAcks[l]]
    /\ acks'          = [acks EXCEPT ![s] = {}]
    /\ lastCommitted' = [lastCommitted EXCEPT ![s] = 0]
    /\ UNCHANGED <<snapZ, curEpoch, accEpoch>>

-----------------------------------------------------------------------------
(* INITIAL STATE: QuorumUtil(1) data dirs, every peer stopped               *)
(* (src/test/java/org/apache/zookeeper/test/QuorumUtil.java:96-129: fresh   *)
(*  createTmpDir per peer, peers started later by start(id) :206-216)       *)
-----------------------------------------------------------------------------

Init ==
    /\ role     = [s \in Server |-> "DOWN"]
    /\ phase    = [s \in Server |-> "NONE"]
    /\ leaderOf = [s \in Server |-> NoServer]
    /\ lepoch   = [s \in Server |-> 0]
    /\ serving  = [s \in Server |-> "NONE"]
    /\ dbInit   = [s \in Server |-> FALSE]
    /\ lpz      = [s \in Server |-> 0]                 \* DataTree.java:845
    /\ clog     = [s \in Server |-> {}]
    /\ log      = [s \in Server |-> {}]
    /\ snapZ    = [s \in Server |-> NoSnap]
    /\ curEpoch = [s \in Server |-> 0]
    /\ accEpoch = [s \in Server |-> 0]
    /\ syncMode     = [s \in Server |-> "NONE"]
    /\ inbox        = [s \in Server |-> <<>>]
    /\ pktNotLogged = [s \in Server |-> <<>>]
    /\ pktCommitted = [s \in Server |-> <<>>]
    /\ pendingTxns  = [s \in Server |-> <<>>]
    /\ toLog        = [s \in Server |-> <<>>]
    /\ commitQ      = [s \in Server |-> <<>>]
    /\ hzxid         = [s \in Server |-> 0]
    /\ fwd           = [s \in Server |-> {}]
    /\ nlAcks        = [s \in Server |-> {}]
    /\ utdSent       = [s \in Server |-> {}]
    /\ acks          = [s \in Server |-> {}]
    /\ lastCommitted = [s \in Server |-> 0]
    /\ cState    = [c \in Client |-> "CONNECTING"]
    /\ cConn     = [c \in Client |-> NoServer]
    /\ cLastZxid = [c \in Client |-> 0]                \* ClientCnxn.java:820 (fresh handle)
    /\ cRwTarget = [c \in Client |-> NoServer]
    /\ cSeenRw   = [c \in Client |-> FALSE]            \* ZooKeeper.java:1160 (sessionId == 0)
    /\ cSess     = [c \in Client |-> NoServer]
    /\ cReplies  = [c \in Client |-> <<>>]
    /\ targetFired = FALSE
    /\ targetInfo  = NoInfo
    /\ committed   = {}
    /\ served      = {}

-----------------------------------------------------------------------------
(* PEER LIFECYCLE                                                          *)
-----------------------------------------------------------------------------

\* QuorumUtil.start(id) (QuorumUtil.java:206-216) -> QuorumPeer.start -> loadDataBase
\* (QuorumPeer.java:1206-1208) -> ZKDatabase.loadDataBase (ZKDatabase.java:288-297).
\* The peer then enters the main loop in LOOKING (QuorumPeer.java:1527-1528).
\* Epoch files are kept as they are on disk (QuorumPeer.java:1214-1254 only creates
\* missing ones from the zxid's epoch, which is 0 for a fresh trusted DB).
PeerStart(s) ==
    /\ role[s] = "DOWN"
    /\ ~(snapZ[s] = NoSnap /\ log[s] # {})          \* FileTxnSnapLog.java:286-290 would throw
    /\ role'   = [role EXCEPT ![s] = "LOOKING"]
    /\ lpz'    = [lpz EXCEPT ![s] = RestoreZ(s)]
    /\ clog'   = [clog EXCEPT ![s] = RestoreClog(s)]
    /\ snapZ'  = [snapZ EXCEPT ![s] = RestoreSnap(s)]
    /\ dbInit' = [dbInit EXCEPT ![s] = TRUE]          \* ZKDatabase.java:291
    /\ UNCHANGED <<phase, leaderOf, lepoch, serving, log, curEpoch, accEpoch>>
    /\ UNCHANGED <<learnVars, leaderVars, clientVars, ghostVars>>

\* Fault: the peer process is stopped (QuorumUtil.shutdown, QuorumUtil.java:251-271 ->
\* QuorumPeer.shutdown :1681-1715, graceful) or crashes (not graceful).
PeerStop(s, graceful) ==
    /\ role[s] # "DOWN"
    /\ ResetPeer(s, graceful)
    /\ UNCHANGED <<cLastZxid, cRwTarget, cSeenRw, ghostVars>>

\* Lazy reload while LOOKING: FLE asks QuorumPeer.getLastLoggedZxid, which calls
\* loadDataBase when the DB was cleared (QuorumPeer.java:1386-1390; FastLeaderElection.java:863-869).
ReloadDb(s) ==
    /\ role[s] = "LOOKING"
    /\ ~dbInit[s]
    /\ lpz'    = [lpz EXCEPT ![s] = RestoreZ(s)]
    /\ clog'   = [clog EXCEPT ![s] = RestoreClog(s)]
    /\ snapZ'  = [snapZ EXCEPT ![s] = RestoreSnap(s)]
    /\ dbInit' = [dbInit EXCEPT ![s] = TRUE]
    /\ UNCHANGED <<role, phase, leaderOf, lepoch, serving, log, curEpoch, accEpoch>>
    /\ UNCHANGED <<learnVars, leaderVars, clientVars, ghostVars>>

-----------------------------------------------------------------------------
(* READ-ONLY MODE (QuorumPeer.java:1532-1576, ReadOnlyZooKeeperServer)      *)
-----------------------------------------------------------------------------

\* After max(2000, tickTime) the helper thread starts the RO server if the peer is still
\* LOOKING (QuorumPeer.java:1544-1551).  ReadOnlyZooKeeperServer.startup (:73-85):
\* super.startup() -> RUNNING (ZooKeeperServer.java:810), then attach (:82).  It serves the
\* peer's own zkDb (QuorumPeer.java:1536) and never applies a txn (RO chain :65-71).
StartRO(s) ==
    /\ RoEnabled                                    \* QuorumPeer.java:1532
    /\ role[s] = "LOOKING"                           \* QuorumPeer.java:1549
    /\ serving[s] = "NONE"
    /\ serving' = [serving EXCEPT ![s] = "RO"]
    /\ UNCHANGED <<role, phase, leaderOf, lepoch, dbInit>>
    /\ UNCHANGED <<dataVars, learnVars, leaderVars, clientVars, ghostVars>>

\* The RO server keeps serving after FLE has already set FOLLOWING/LEADING
\* (FastLeaderElection.java:894-899) until lookForLeader() and checkSuspended() return
\* (QuorumPeer.java:1566-1567; a suspended peer waits in :1475-1483).  Then the finally
\* block (:1571-1576) calls roZk.shutdown() = shutdown(false) (ZooKeeperServer.java:914-916):
\* shutdownComponents detaches it and closes its connections (ReadOnlyZooKeeperServer.java:193-206),
\* then zkDb.fastForwardDataBase (ZooKeeperServer.java:928-940).
ShutdownRO(s) ==
    /\ role[s] \in {"FOLLOWING", "LEADING"}
    /\ serving[s] = "RO"
    /\ serving' = [serving EXCEPT ![s] = "NONE"]
    /\ DropClients(s)
    /\ lpz'  = [lpz EXCEPT ![s] = FFlpz(s, log[s])]
    /\ clog' = [clog EXCEPT ![s] = FFclog(s, log[s])]
    /\ UNCHANGED <<role, phase, leaderOf, lepoch, dbInit, log, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<learnVars, leaderVars, cLastZxid, cRwTarget, cSeenRw, ghostVars>>

-----------------------------------------------------------------------------
(* LEADER ELECTION (FastLeaderElection.lookForLeader)                      *)
-----------------------------------------------------------------------------

\* A quorum Q of LOOKING peers converges on the best vote in Q.  Peers whose vote zxid is
\* -1 ignore and are ignored by LOOKING notifications (FastLeaderElection.java:1000-1007).
\* setPeerState sets LEADING/FOLLOWING (:894-899) while any RO server keeps running.
Elect(Q, L) ==
    /\ Q \subseteq Server
    /\ Quorum(Q)                                         \* :1041 voteSet.hasAllQuorums()
    /\ L \in Q
    /\ \A s \in Q : role[s] = "LOOKING" /\ dbInit[s] /\ lpz[s] # -1
    /\ \A s \in Q \ {L} : VoteGT(L, s)                    \* :1012-1026 best vote wins
    /\ role'     = [s \in Server |-> IF s = L THEN "LEADING"
                                      ELSE IF s \in Q THEN "FOLLOWING" ELSE role[s]]
    /\ phase'    = [s \in Server |-> IF s \in Q THEN "ELECTED" ELSE phase[s]]
    /\ leaderOf' = [s \in Server |-> IF s \in Q \ {L} THEN L ELSE leaderOf[s]]
    /\ UNCHANGED <<lepoch, serving, dbInit>>
    /\ UNCHANGED <<dataVars, learnVars, leaderVars, clientVars, ghostVars>>

\* A peer finalizes on the quorum of votes it has SEEN (:1040-1058), and those votes can be
\* stale: a voter may have decided otherwise since, so peers of one round can decide different
\* leaders (trace ro_round_trip_split_vote: p1 follows 2 while p3 leads alone).  Here s alone
\* decides LEADING from a quorum Q of peers that were in this election (LOOKING or just decided,
\* never an established peer, whose notifications carry its FOLLOWING/LEADING vote) and whose
\* own votes s beats, so each could have voted for s.  s then waits in getEpochToPropose until
\* initLimit (Leader.java:1469-1500) and LeaderShutdown takes it back to LOOKING unless others
\* join it.  The symmetric stale decision of a follower is Elect plus the connect failure in
\* FollowerLoseLeader; the model's Elect decides L early, which only moves its report.
ElectStranded(s) ==
    /\ role[s] = "LOOKING" /\ dbInit[s] /\ lpz[s] # -1
    /\ \E Q \in SUBSET Server :
          /\ s \in Q /\ Quorum(Q)
          /\ \A v \in Q \ {s} :
                /\ role[v] = "LOOKING" \/ (role[v] # "DOWN" /\ phase[v] = "ELECTED")
                /\ dbInit[v] /\ lpz[v] # -1                \* :1000-1007
                /\ VoteGT(s, v)                            \* :738-742
    /\ role'  = [role EXCEPT ![s] = "LEADING"]
    /\ phase' = [phase EXCEPT ![s] = "ELECTED"]
    /\ UNCHANGED <<leaderOf, lepoch, serving, dbInit>>
    /\ UNCHANGED <<dataVars, learnVars, leaderVars, clientVars, ghostVars>>

\* A LOOKING peer joins an established leader on FOLLOWING/LEADING notifications from a
\* quorum (FastLeaderElection.receivedFollowingNotification :1140-1177; checkLeader needs the
\* leader itself to report LEADING).  The -1 rule applies only to LOOKING notifications.
\* A leader that has not finished discovery can also complete s's own round: recvset already
\* holds s's vote for L and L's LEADING notification of the same electionEpoch makes the quorum
\* (:1142-1151), which is the first branch of receivedFollowingNotification.
JoinLeader(s, L) ==
    /\ s # L
    /\ role[s] = "LOOKING"
    /\ dbInit[s]                                         \* lookForLeader reloads first (:863-869)
    /\ role[L] = "LEADING"
    /\ \/ Quorum({L} \cup {f \in Server \ {s} : role[f] = "FOLLOWING" /\ leaderOf[f] = L})
       \/ /\ phase[L] = "ELECTED"
          /\ lpz[s] # -1 /\ VoteGT(L, s)
          /\ Quorum({L, s} \cup {f \in Server \ {s} : role[f] = "FOLLOWING" /\ leaderOf[f] = L})
    /\ role'     = [role EXCEPT ![s] = "FOLLOWING"]
    /\ phase'    = [phase EXCEPT ![s] = "ELECTED"]
    /\ leaderOf' = [leaderOf EXCEPT ![s] = L]
    /\ UNCHANGED <<lepoch, serving, dbInit>>
    /\ UNCHANGED <<dataVars, learnVars, leaderVars, clientVars, ghostVars>>

-----------------------------------------------------------------------------
(* LEADER ESTABLISHMENT (Leader.lead, LearnerHandler.run)                  *)
-----------------------------------------------------------------------------

\* Leader.lead :643-713 with the discovery quorum Q (the learners whose FOLLOWERINFO /
\* ACKEPOCH completed getEpochToPropose and waitForEpochAck):
\*   :646 zk.loadData(): DB already initialized -> setZxid(lpz) and takeSnapshot
\*        (ZooKeeperServer.java:539-551), a snapshot named after the PRE-bump lpz;
\*   :655 epoch = max acceptedEpoch + 1 (Leader.java:1474-1483); learners accept it
\*        (Learner.java:512-514, 531-532);
\*   :657 zk.setZxid(makeZxid(epoch, 0)) -- hzxid only, lpz is untouched here;
\*   :710-711 waitForEpochAck (only lastZxid != -1 counts, :1528) then setCurrentEpoch.
LeaderDiscovery(L, Q) ==
    /\ role[L] = "LEADING" /\ phase[L] = "ELECTED" /\ serving[L] = "NONE"
    /\ L \in Q /\ Q \subseteq Server /\ Quorum(Q)
    /\ \A f \in Q \ {L} :
          /\ role[f] = "FOLLOWING" /\ leaderOf[f] = L /\ phase[f] = "ELECTED"
          /\ serving[f] = "NONE"                         \* RO finally done, in followLeader
          /\ lpz[f] # -1                                 \* Leader.java:1528
          /\ ~MoreRecent(f, L)                           \* Leader.java:1520-1527
    /\ LET e == NewEpoch(Q) IN
       /\ accEpoch' = [s \in Server |-> IF s \in Q THEN e ELSE accEpoch[s]]
       /\ curEpoch' = [curEpoch EXCEPT ![L] = e]
       /\ hzxid'    = [hzxid EXCEPT ![L] = Z(e, 0)]
       /\ lepoch'   = [s \in Server |-> IF s \in Q THEN e ELSE lepoch[s]]
    /\ snapZ'  = [snapZ EXCEPT ![L] = IF @ = NoSnap THEN lpz[L] ELSE Max({@, lpz[L]})]
    /\ phase'  = [s \in Server |-> IF s = L THEN "SYNC"
                                   ELSE IF s \in Q THEN "DISCOVERED" ELSE phase[s]]
    /\ nlAcks'  = [nlAcks EXCEPT ![L] = {L}]             \* :716 waitForNewLeaderAck(self)
    /\ fwd'     = [fwd EXCEPT ![L] = {}]
    /\ utdSent' = [utdSent EXCEPT ![L] = {}]
    /\ acks'    = [acks EXCEPT ![L] = {}]
    /\ lastCommitted' = [lastCommitted EXCEPT ![L] = 0]
    /\ UNCHANGED <<role, leaderOf, serving, dbInit, lpz, clog, log>>
    /\ UNCHANGED <<learnVars, clientVars, ghostVars>>

\* One LearnerHandler, from ACKEPOCH to queueing NEWLEADER (LearnerHandler.java:520-610):
\* syncFollower picks DIFF/TRUNC/SNAP and queues committed proposals (SyncPlans), then
\* Leader.startForwarding (:925; Leader.java:1367-1400) queues toBeApplied (= the leader's
\* commitQ) as PROPOSAL+COMMIT and outstanding proposals as PROPOSAL above currentZxid,
\* and adds the learner to forwardingFollowers; NEWLEADER(makeZxid(epoch,0)) follows (:604-605).
\* A learner that registers after discovery (phase ELECTED) gets the established epoch at once
\* (getEpochToPropose / waitForEpochAck return immediately, Leader.java:1471-1473, 1517-1519).
\* The handler runs atomically with respect to broadcasts: startForwarding and the NEWLEADER
\* queueing are adjacent, so later PROPOSAL/COMMITs reach the learner after NEWLEADER.
LearnerHandlerSync(L, F) ==
    /\ L # F
    /\ role[L] = "LEADING" /\ phase[L] \in {"SYNC", "STARTED", "BROADCAST"}
    /\ role[F] = "FOLLOWING" /\ leaderOf[F] = L /\ serving[F] = "NONE"
    /\ F \notin fwd[L]
    /\ \/ phase[F] = "DISCOVERED" /\ lepoch[F] = lepoch[L]
       \/ phase[F] = "ELECTED" /\ lepoch[L] >= accEpoch[F]  \* else Follower.java:97-103 throws
    /\ \E plan \in SyncPlans(L, F) :
          LET fwdC == {x \in SeqSet(commitQ[L]) : x > plan.cur}
              fwdP == {x \in Outstanding(L) : x > plan.cur}
              fwdPkts == IF hzxid[L] > plan.cur                       \* Leader.java:1370
                         THEN PropCommitPkts(AscSeq(fwdC)) \o PropPkts(AscSeq(fwdP))
                         ELSE <<>>
          IN inbox' = [inbox EXCEPT ![F] =
                         <<Pkt(plan.mode, plan.z)>> \o PropCommitPkts(AscSeq(plan.q))
                         \o fwdPkts \o <<Pkt("NEWLEADER", Z(lepoch[L], 0))>>]
    /\ fwd'      = [fwd EXCEPT ![L] = @ \cup {F}]                     \* Leader.java:1393-1394
    /\ phase'    = [phase EXCEPT ![F] = "SYNC"]
    /\ lepoch'   = [lepoch EXCEPT ![F] = lepoch[L]]
    /\ accEpoch' = [accEpoch EXCEPT ![F] = IF lepoch[L] > @ THEN lepoch[L] ELSE @]
    /\ UNCHANGED <<role, leaderOf, serving, dbInit, lpz, clog, log, snapZ, curEpoch>>
    /\ UNCHANGED <<syncMode, pktNotLogged, pktCommitted, pendingTxns, toLog, commitQ>>
    /\ UNCHANGED <<hzxid, nlAcks, utdSent, acks, lastCommitted, clientVars, ghostVars>>

\* Leader.java:741 startZkServer (:1570-1610), first half, once waitForNewLeaderAck saw a
\* quorum (:716):
\*   :1572 lastCommitted = zk.getZxid() (= makeZxid(epoch, 0))
\*   :1599 zk.startup() -> RUNNING.  LearnerHandlers blocked in waitForStartup
\*         (Leader.java:1402-1409) may now queue UPTODATE.  The data tree still holds the
\*         PRE-bump lastProcessedZxid and clients cannot reach the leader yet.
\* The NEWLEADER quorum makes the leader's history committed (ghost `committed`).
LeaderStartup(L) ==
    /\ role[L] = "LEADING" /\ phase[L] = "SYNC"
    /\ Quorum(nlAcks[L])
    /\ lastCommitted' = [lastCommitted EXCEPT ![L] = hzxid[L]]
    /\ phase'   = [phase EXCEPT ![L] = "STARTED"]
    /\ committed' = committed \cup LeaderHistory(L)
    /\ UNCHANGED <<role, leaderOf, lepoch, serving, dbInit, dataVars>>
    /\ UNCHANGED <<learnVars, hzxid, fwd, nlAcks, utdSent, acks, clientVars>>
    /\ UNCHANGED <<targetFired, targetInfo, served>>

\* Second half: :1609 zk.getZKDatabase().setlastProcessedZxid(zk.getZxid()) -- the txn-less
\* makeZxid(epoch, 0) -- then lead() continues to :761-762 self.setZooKeeperServer(zk):
\* from here on clients reach the leader and isro answers "rw".  Nothing a client can
\* observe happens between :1609 and :762, so they are one step.  No proposal exists
\* before this step (requests reach the leader only through attached servers); the
\* :1599 -> :1609 race of brief CR-2 is not modeled.
LeaderServe(L) ==
    /\ role[L] = "LEADING" /\ phase[L] = "STARTED"
    /\ lpz'     = [lpz EXCEPT ![L] = hzxid[L]]
    /\ serving' = [serving EXCEPT ![L] = "RW"]
    /\ phase'   = [phase EXCEPT ![L] = "BROADCAST"]
    /\ UNCHANGED <<role, leaderOf, lepoch, dbInit, clog, log, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<learnVars, leaderVars, clientVars, ghostVars>>

\* LearnerHandler.java:628-653: after this learner's NEWLEADER ack and waitForStartup
\* (Leader.java:1402-1409, zk RUNNING) the handler queues UPTODATE.
LeaderSendUptodate(L, F) ==
    /\ role[L] = "LEADING" /\ Running(L)
    /\ F \in nlAcks[L] \cap fwd[L]
    /\ F \notin utdSent[L]
    /\ inbox'   = [inbox EXCEPT ![F] = Append(@, Pkt("UPTODATE", -1))]
    /\ utdSent' = [utdSent EXCEPT ![L] = @ \cup {F}]
    /\ UNCHANGED <<peerVars, dataVars, syncMode, pktNotLogged, pktCommitted, pendingTxns>>
    /\ UNCHANGED <<toLog, commitQ, hzxid, fwd, nlAcks, acks, lastCommitted>>
    /\ UNCHANGED <<clientVars, ghostVars>>

-----------------------------------------------------------------------------
(* LEARNER SYNC (Learner.syncWithLeader, Learner.java:570-872)             *)
-----------------------------------------------------------------------------

\* Packets already in the stream can still be read after the leader instance went away
\* (TCP buffering); the learner notices only when the read fails (FollowerLoseLeader).
\* Effects on the leader (ACKs) are dropped if its instance is gone.
InSync(f) ==
    /\ role[f] = "FOLLOWING" /\ leaderOf[f] \in Server
    /\ inbox[f] # <<>>

\* :586-595 DIFF: lastProcessedZxid is NOT written; snapshotNeeded = false.
\* (LearnerHandler.java:786-787 claims the learner adopts makeZxid(epoch,0); it does not.)
LearnerRecvDiff(F) ==
    /\ InSync(F) /\ phase[F] = "SYNC"
    /\ Head(inbox[F]).t = "DIFF"
    /\ syncMode' = [syncMode EXCEPT ![F] = "DIFF"]
    /\ inbox'    = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<peerVars, dataVars, pktNotLogged, pktCommitted, pendingTxns, toLog, commitQ>>
    /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

\* :596-617 SNAP: deserializeSnapshot clears the DB (:600-601, ZKDatabase.clear), then
\* :614 setlastProcessedZxid(qp.getZxid()) = the leader's lpz when it was sent.
LearnerRecvSnap(F) ==
    /\ InSync(F) /\ phase[F] = "SYNC"
    /\ Head(inbox[F]).t = "SNAP"
    /\ syncMode' = [syncMode EXCEPT ![F] = "SNAP"]
    /\ lpz'      = [lpz EXCEPT ![F] = Head(inbox[F]).z]
    /\ clog'     = [clog EXCEPT ![F] = {}]
    /\ inbox'    = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<peerVars, log, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<pktNotLogged, pktCommitted, pendingTxns, toLog, commitQ>>
    /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

\* :618-629 TRUNC: ZKDatabase.truncateLog (ZKDatabase.java:611-623) = clear, truncate the
\* txn log above t (FileTxnSnapLog.java:513-535; snapshots are kept), reload; then
\* :628 setlastProcessedZxid(t).
LearnerRecvTrunc(F) ==
    /\ InSync(F) /\ phase[F] = "SYNC"
    /\ Head(inbox[F]).t = "TRUNC"
    /\ LET t  == Head(inbox[F]).z
           lg == {x \in log[F] : x <= t}
       IN /\ log'  = [log EXCEPT ![F] = lg]
          /\ lpz'  = [lpz EXCEPT ![F] = t]
          /\ clog' = [clog EXCEPT ![F] = {x \in lg : x > snapZ[F]}]
    /\ syncMode' = [syncMode EXCEPT ![F] = "TRUNC"]
    /\ inbox'    = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<peerVars, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<pktNotLogged, pktCommitted, pendingTxns, toLog, commitQ>>
    /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

\* :654-669 PROPOSAL during sync: packetsNotLogged.add (before or after NEWLEADER).
LearnerRecvProposal(F) ==
    /\ InSync(F) /\ phase[F] \in {"SYNC", "SYNC2"}
    /\ Head(inbox[F]).t = "PROPOSAL"
    /\ pktNotLogged' = [pktNotLogged EXCEPT ![F] = Append(@, Head(inbox[F]).z)]
    /\ inbox'        = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<peerVars, dataVars, syncMode, pktCommitted, pendingTxns, toLog, commitQ>>
    /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

\* :670-696 COMMIT during sync.
\*   !writeToTxnLog (SNAP/TRUNC before NEWLEADER): apply now if it matches the head of
\*   packetsNotLogged (:683-692, zk.processTxn -> DataTree.java:1105-1106; NOT logged), else warn.
\*   writeToTxnLog (DIFF, or any mode after NEWLEADER): packetsCommitted.add (:693-695).
LearnerRecvCommit(F) ==
    /\ InSync(F) /\ phase[F] \in {"SYNC", "SYNC2"}
    /\ Head(inbox[F]).t = "COMMIT"
    /\ pktNotLogged[F] # <<>>                         \* :672-673 dereferences peekFirst()
    /\ LET z == Head(inbox[F]).z IN
       IF ~WriteToTxnLog(F)
       THEN IF Head(pktNotLogged[F]) = z
            THEN /\ lpz'  = [lpz EXCEPT ![F] = IF z > @ THEN z ELSE @]
                 /\ clog' = [clog EXCEPT ![F] = @ \cup {z}]
                 /\ pktNotLogged' = [pktNotLogged EXCEPT ![F] = Tail(@)]
                 /\ UNCHANGED pktCommitted
            ELSE UNCHANGED <<lpz, clog, pktNotLogged, pktCommitted>>      \* :684-688
       ELSE /\ pktCommitted' = [pktCommitted EXCEPT ![F] = Append(@, z)]
            /\ UNCHANGED <<lpz, clog, pktNotLogged>>
    /\ inbox' = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<peerVars, log, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<syncMode, pendingTxns, toLog, commitQ, leaderVars, clientVars, ghostVars>>

\* :785-800 drain packetsCommitted at NEWLEADER: append + apply each commit that matches the
\* head of packetsNotLogged, warn and skip the others (:788-795).
RECURSIVE NLDrain(_, _, _, _, _)
NLDrain(pc, pnl, z, lg, cl) ==
    IF pc = <<>> THEN [pnl |-> pnl, z |-> z, lg |-> lg, cl |-> cl]
    ELSE LET x == Head(pc) IN
         IF pnl = <<>> \/ Head(pnl) # x
         THEN NLDrain(Tail(pc), pnl, z, lg, cl)
         ELSE NLDrain(Tail(pc), Tail(pnl), IF x > z THEN x ELSE z, lg \cup {x}, cl \cup {x})

\* :746-821 NEWLEADER:
\*   :759-761 snapshotNeeded (SNAP/TRUNC) -> takeSnapshot, named after the current lpz;
\*   :764 writeToTxnLog = true;
\*   :769-808 follower: append + apply committed packets (fzk.appendRequest, fzk.processTxn),
\*            then zkDb.commit();
\*   :813 setCurrentEpoch(newEpoch); :816 syncMode = NONE;
\*   :819 ACK(newLeaderZxid) -> LearnerHandler.java:617-628 -> waitForNewLeaderAck.
LearnerRecvNewLeader(F) ==
    /\ InSync(F) /\ phase[F] = "SYNC"
    /\ Head(inbox[F]).t = "NEWLEADER"
    /\ LET d == NLDrain(pktCommitted[F], pktNotLogged[F], lpz[F], log[F], clog[F]) IN
       /\ lpz'          = [lpz EXCEPT ![F] = d.z]
       /\ log'          = [log EXCEPT ![F] = d.lg]
       /\ clog'         = [clog EXCEPT ![F] = d.cl]
       /\ pktNotLogged' = [pktNotLogged EXCEPT ![F] = d.pnl]
    /\ snapZ' = [snapZ EXCEPT ![F] =
                   IF syncMode[F] \in {"SNAP", "TRUNC"}
                   THEN IF @ = NoSnap THEN lpz[F] ELSE Max({@, lpz[F]})
                   ELSE @]
    /\ pktCommitted' = [pktCommitted EXCEPT ![F] = <<>>]
    /\ curEpoch'     = [curEpoch EXCEPT ![F] = lepoch[F]]
    /\ syncMode'     = [syncMode EXCEPT ![F] = "NONE"]
    /\ nlAcks'       = IF LeaderAlive(F) THEN [nlAcks EXCEPT ![leaderOf[F]] = @ \cup {F}]
                       ELSE nlAcks
    /\ phase'        = [phase EXCEPT ![F] = "SYNC2"]
    /\ inbox'        = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<role, leaderOf, lepoch, serving, dbInit, accEpoch>>
    /\ UNCHANGED <<pendingTxns, toLog, commitQ, hzxid, fwd, utdSent, acks, lastCommitted>>
    /\ UNCHANGED <<clientVars, ghostVars>>

\* :731-745 UPTODATE: self.setZooKeeperServer(zk) (:743, attached but not yet running, so
\* connections still fail at NIOServerCnxn.java:439-441 and isro answers "null"), break;
\* then :825-835 ACK and zk.startup() (:827) -> RUNNING.  From here on the learner serves
\* clients and answers isro "rw" -- before the deferred commits below are handed off.
LearnerRecvUptodate(F) ==
    /\ InSync(F) /\ phase[F] = "SYNC2"
    /\ Head(inbox[F]).t = "UPTODATE"
    /\ serving' = [serving EXCEPT ![F] = "RW"]
    /\ phase'   = [phase EXCEPT ![F] = "STARTED"]
    /\ inbox'   = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<role, leaderOf, lepoch, dbInit, dataVars>>
    /\ UNCHANGED <<syncMode, pktNotLogged, pktCommitted, pendingTxns, toLog, commitQ>>
    /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

\* FollowerZooKeeperServer.commit (FollowerZooKeeperServer.java:99-113) over a sequence:
\* empty pendingTxns -> warn and skip (:100-103); head mismatch -> requestSystemExit
\* (:105-109); else pop and CommitProcessor.commit (:110-112, CommitProcessor.java:590-599).
RECURSIVE CommitDrain(_, _, _)
CommitDrain(pc, pend, cq) ==
    IF pc = <<>> THEN [pend |-> pend, cq |-> cq, exit |-> FALSE]
    ELSE IF pend = <<>> THEN CommitDrain(Tail(pc), pend, cq)
    ELSE IF Head(pend) # Head(pc) THEN [pend |-> pend, cq |-> cq, exit |-> TRUE]
    ELSE CommitDrain(Tail(pc), Tail(pend), Append(cq, Head(pc)))

NonEpochZxids(q) == SelectSeq(q, LAMBDA x : Ctr(x) # 0)   \* FollowerZooKeeperServer.java:80-82

\* :837-848 after startup: logRequest every packetsNotLogged entry (:840-842 ->
\* FollowerZooKeeperServer.logRequest :79-84: pendingTxns + SyncRequestProcessor), then
\* fzk.commit(zxid) for every packetsCommitted entry (:845-847).
LearnerFlushDeferred(F) ==
    /\ role[F] = "FOLLOWING" /\ phase[F] = "STARTED"
    /\ LET pend0 == pendingTxns[F] \o NonEpochZxids(pktNotLogged[F])
           d     == CommitDrain(pktCommitted[F], pend0, <<>>)
       IN IF d.exit
          THEN /\ ResetPeer(F, FALSE)                   \* ServiceUtils.requestSystemExit
               /\ UNCHANGED <<cLastZxid, cRwTarget, cSeenRw, ghostVars>>
          ELSE /\ toLog'        = [toLog EXCEPT ![F] = @ \o pktNotLogged[F]]
               /\ pendingTxns'  = [pendingTxns EXCEPT ![F] = d.pend]
               /\ pktNotLogged' = [pktNotLogged EXCEPT ![F] = <<>>]
               /\ pktCommitted' = [pktCommitted EXCEPT ![F] = <<>>]
               /\ phase'        = [phase EXCEPT ![F] = "BROADCAST"]
               /\ IF AsyncApply
                  THEN /\ commitQ' = [commitQ EXCEPT ![F] = @ \o d.cq]
                       /\ UNCHANGED <<lpz, clog>>
                  ELSE /\ lpz'  = [lpz EXCEPT ![F] = MaxOr({@} \cup SeqSet(d.cq), @)]
                       /\ clog' = [clog EXCEPT ![F] = @ \cup SeqSet(d.cq)]
                       /\ UNCHANGED commitQ
               /\ UNCHANGED <<role, leaderOf, lepoch, serving, dbInit>>
               /\ UNCHANGED <<log, snapZ, curEpoch, accEpoch, syncMode, inbox>>
               /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

-----------------------------------------------------------------------------
(* BROADCAST: proposals, acks, commits, apply                               *)
-----------------------------------------------------------------------------

\* A write accepted by the leader's pipeline: PrepRequestProcessor takes zks.getNextZxid()
\* (ZooKeeperServer.java:694-696), Leader.propose (Leader.java:1295-1335) sends PROPOSAL to
\* every forwarding follower (:1331 -> sendPacket :1195-1201).  The writer may be any client.
LeaderPropose(L) ==
    /\ role[L] = "LEADING" /\ phase[L] = "BROADCAST"
    /\ Ctr(hzxid[L]) + 1 < ZB                     \* rollover guard (Leader.java:1304-1308)
    /\ LET z == hzxid[L] + 1 IN
       /\ hzxid' = [hzxid EXCEPT ![L] = z]
       /\ inbox' = [f \in Server |-> IF f \in fwd[L]
                                      THEN Append(inbox[f], Pkt("PROPOSAL", z)) ELSE inbox[f]]
    /\ UNCHANGED <<peerVars, dataVars, syncMode, pktNotLogged, pktCommitted, pendingTxns>>
    /\ UNCHANGED <<toLog, commitQ, fwd, nlAcks, utdSent, acks, lastCommitted>>
    /\ UNCHANGED <<clientVars, ghostVars>>

\* Leader's own SyncRequestProcessor appends its proposal and AckRequestProcessor calls
\* Leader.processAck(self) (Leader.java:1054-1099).  Proposals are logged in order.
LeaderSyncAck(L) ==
    /\ role[L] = "LEADING" /\ phase[L] = "BROADCAST"
    /\ ProposedBy(L) \ log[L] # {}
    /\ LET z == Min(ProposedBy(L) \ log[L]) IN
       /\ log'  = [log EXCEPT ![L] = @ \cup {z}]
       /\ acks' = [acks EXCEPT ![L] = @ \cup {<<L, z>>}]
    /\ UNCHANGED <<peerVars, lpz, clog, snapZ, curEpoch, accEpoch, learnVars>>
    /\ UNCHANGED <<hzxid, fwd, nlAcks, utdSent, lastCommitted, clientVars, ghostVars>>

\* Leader.processAck -> tryToCommit (Leader.java:970-1043): in order (:978-980, :990),
\* with a quorum of acks (:985); commit(zxid) sends COMMIT to forwarding followers BEFORE
\* zk.commitProcessor.commit hands it to the leader's own apply (:1032-1035).
LeaderCommit(L) ==
    /\ role[L] = "LEADING" /\ phase[L] = "BROADCAST"
    /\ lastCommitted[L] < hzxid[L]
    /\ LET z == lastCommitted[L] + 1 IN
       /\ Quorum({s \in Server : <<s, z>> \in acks[L]})
       /\ lastCommitted' = [lastCommitted EXCEPT ![L] = z]                 \* :1221
       /\ inbox' = [f \in Server |-> IF f \in fwd[L]
                                      THEN Append(inbox[f], Pkt("COMMIT", z)) ELSE inbox[f]]
       /\ committed' = committed \cup {z}
       /\ IF AsyncApply
          THEN /\ commitQ' = [commitQ EXCEPT ![L] = Append(@, z)]
               /\ UNCHANGED <<lpz, clog>>
          ELSE /\ lpz'  = [lpz EXCEPT ![L] = IF z > @ THEN z ELSE @]
               /\ clog' = [clog EXCEPT ![L] = @ \cup {z}]
               /\ UNCHANGED commitQ
    /\ UNCHANGED <<peerVars, log, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<syncMode, pktNotLogged, pktCommitted, pendingTxns, toLog>>
    /\ UNCHANGED <<hzxid, fwd, nlAcks, utdSent, acks, clientVars>>
    /\ UNCHANGED <<targetFired, targetInfo, served>>

\* Follower.processPacket PROPOSAL (Follower.java:161-180): fzk.logRequest
\* (FollowerZooKeeperServer.java:79-84) adds to pendingTxns and queues to the
\* SyncRequestProcessor; logging and the ACK happen later (FollowerSyncAck).
FollowerRecvProposal(F) ==
    /\ InSync(F) /\ phase[F] = "BROADCAST"
    /\ Head(inbox[F]).t = "PROPOSAL"
    /\ LET z == Head(inbox[F]).z IN
       /\ pendingTxns' = [pendingTxns EXCEPT ![F] = IF Ctr(z) # 0 THEN Append(@, z) ELSE @]
       /\ toLog'       = [toLog EXCEPT ![F] = Append(@, z)]
    /\ inbox' = [inbox EXCEPT ![F] = Tail(@)]
    /\ UNCHANGED <<peerVars, dataVars, syncMode, pktNotLogged, pktCommitted, commitQ>>
    /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

\* SyncRequestProcessor appends + flushes, then SendAckRequestProcessor.processRequest
\* (SendAckRequestProcessor.java:40-46) writes ACK(zxid); the leader records it
\* (Leader.processAck :1099).  An ACK to a leader instance that is gone is lost.
FollowerSyncAck(F) ==
    /\ role[F] = "FOLLOWING" /\ Running(F)
    /\ toLog[F] # <<>>
    /\ LET z == Head(toLog[F]) IN
       /\ log'   = [log EXCEPT ![F] = @ \cup {z}]
       /\ toLog' = [toLog EXCEPT ![F] = Tail(@)]
       /\ acks'  = IF LeaderAlive(F)
                   THEN [acks EXCEPT ![leaderOf[F]] = @ \cup {<<F, z>>}]
                   ELSE acks
    /\ UNCHANGED <<peerVars, lpz, clog, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<syncMode, inbox, pktNotLogged, pktCommitted, pendingTxns, commitQ>>
    /\ UNCHANGED <<hzxid, fwd, nlAcks, utdSent, lastCommitted, clientVars, ghostVars>>

\* Follower.processPacket COMMIT (Follower.java:199-207) -> FollowerZooKeeperServer.commit
\* (:99-113) -> CommitProcessor.commit (CommitProcessor.java:590-599).
FollowerRecvCommit(F) ==
    /\ InSync(F) /\ phase[F] = "BROADCAST"
    /\ Head(inbox[F]).t = "COMMIT"
    /\ LET z == Head(inbox[F]).z IN
       IF pendingTxns[F] = <<>>
       THEN \* :100-103 "Committing .. without seeing txn": dropped
            /\ inbox' = [inbox EXCEPT ![F] = Tail(@)]
            /\ UNCHANGED <<peerVars, dataVars, syncMode, pktNotLogged, pktCommitted>>
            /\ UNCHANGED <<pendingTxns, toLog, commitQ, leaderVars, clientVars, ghostVars>>
       ELSE IF Head(pendingTxns[F]) # z
       THEN \* :105-109 requestSystemExit(UNMATCHED_TXN_COMMIT)
            /\ ResetPeer(F, FALSE)
            /\ UNCHANGED <<cLastZxid, cRwTarget, cSeenRw, ghostVars>>
       ELSE /\ pendingTxns' = [pendingTxns EXCEPT ![F] = Tail(@)]
            /\ inbox'       = [inbox EXCEPT ![F] = Tail(@)]
            /\ IF AsyncApply
               THEN /\ commitQ' = [commitQ EXCEPT ![F] = Append(@, z)]
                    /\ UNCHANGED <<lpz, clog>>
               ELSE /\ lpz'  = [lpz EXCEPT ![F] = IF z > @ THEN z ELSE @]
                    /\ clog' = [clog EXCEPT ![F] = @ \cup {z}]
                    /\ UNCHANGED commitQ
            /\ UNCHANGED <<peerVars, log, snapZ, curEpoch, accEpoch>>
            /\ UNCHANGED <<syncMode, pktNotLogged, pktCommitted, toLog>>
            /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

\* CommitProcessor.run processes the committed write (CommitProcessor.java:375-380) ->
\* FinalRequestProcessor.applyRequest (FinalRequestProcessor.java:111-112) ->
\* ZooKeeperServer.processTxn -> DataTree.processTxn: lastProcessedZxid = max (DataTree.java:
\* 1105-1106) and committedLog add (ZooKeeperServer.java:1886-1889).  Same on every role.
ApplyCommitted(s) ==
    /\ role[s] \in {"LEADING", "FOLLOWING"} /\ Running(s)
    /\ commitQ[s] # <<>>
    /\ LET z == Head(commitQ[s]) IN
       /\ lpz'     = [lpz EXCEPT ![s] = IF z > @ THEN z ELSE @]
       /\ clog'    = [clog EXCEPT ![s] = @ \cup {z}]
       /\ commitQ' = [commitQ EXCEPT ![s] = Tail(@)]
    /\ UNCHANGED <<peerVars, log, snapZ, curEpoch, accEpoch>>
    /\ UNCHANGED <<syncMode, inbox, pktNotLogged, pktCommitted, pendingTxns, toLog>>
    /\ UNCHANGED <<leaderVars, clientVars, ghostVars>>

-----------------------------------------------------------------------------
(* LOSING THE LEADER / THE QUORUM                                          *)
-----------------------------------------------------------------------------

\* The follower's connection to its leader breaks because the leader instance is gone
\* (stopped, shut down, re-elected): readPacket throws in followLeader (Follower.java:122-132),
\* or connectToLeader / the epoch check fails before sync (Follower.java:86-103).
\* The follower must already be inside followLeader (its RO server is shut down).
FollowerLoseLeader(F) ==
    /\ role[F] = "FOLLOWING"
    /\ serving[F] # "RO"
    /\ \/ ~LeaderAlive(F)
       \/ /\ phase[F] = "ELECTED"                     \* Follower.java:97-103 epoch below accepted
          /\ leaderOf[F] \in Server
          /\ phase[leaderOf[F]] \in {"SYNC", "STARTED", "BROADCAST"}
          /\ lepoch[leaderOf[F]] < accEpoch[F]
       \/ /\ phase[F] = "ELECTED"                     \* Learner.java:413-450 connect refused 5 times:
          /\ leaderOf[F] \in Server                   \* no fault, the chosen leader is not listening yet
          /\ phase[leaderOf[F]] = "ELECTED"
    /\ LearnerShutdown(F)
    /\ UNCHANGED <<cLastZxid, cRwTarget, cSeenRw, ghostVars>>

\* Fault: network partition between a follower and its leader; the follower's read
\* times out (Learner.java:815 setSoTimeout, Follower.java:122-132) and it shuts down.
PartitionFollower(F) ==
    /\ role[F] = "FOLLOWING"
    /\ serving[F] # "RO"
    /\ LeaderAlive(F)
    /\ LearnerShutdown(F)
    /\ UNCHANGED <<cLastZxid, cRwTarget, cSeenRw, ghostVars>>

\* The leader loses its quorum of supporters: the tick check (Leader.java:788-840) or an
\* establishment timeout (Leader.java:715-739, 1496-1497, 1544-1545) -> Leader.shutdown
\* (Leader.java:861-892): setZooKeeperServer(null), closeAllConnections, zk.shutdown() =
\* shutdown(false) (fast-forward if RUNNING), learner handlers shut down.  The peer then
\* goes LOOKING (QuorumPeer.java:1628-1637) with the same zkDb.
LeaderShutdown(L) ==
    /\ role[L] = "LEADING"
    /\ serving[L] # "RO"
    /\ ~Quorum(Supporters(L))
    /\ LET run == Running(L)
           lg  == IF run THEN log[L] \cup UnloggedQueued(L) ELSE log[L]
       IN /\ log'  = [log EXCEPT ![L] = lg]
          /\ lpz'  = [lpz EXCEPT ![L] = IF run THEN FFlpz(L, lg) ELSE @]
          /\ clog' = [clog EXCEPT ![L] = IF run THEN FFclog(L, lg) ELSE @]
    \* A leader that timed out before discovery finished has still run Leader.java:646 zk.loadData
    \* (LeaderDiscovery records that snapshot for the others).
    /\ snapZ' = [snapZ EXCEPT ![L] = IF phase[L] = "ELECTED"
                                     THEN IF @ = NoSnap THEN lpz[L] ELSE Max({@, lpz[L]})
                                     ELSE @]
    /\ role'    = [role EXCEPT ![L] = "LOOKING"]
    /\ phase'   = [phase EXCEPT ![L] = "NONE"]
    /\ lepoch'  = [lepoch EXCEPT ![L] = 0]
    /\ serving' = [serving EXCEPT ![L] = "NONE"]
    /\ DropClients(L)
    /\ commitQ'       = [commitQ EXCEPT ![L] = <<>>]
    /\ hzxid'         = [hzxid EXCEPT ![L] = 0]
    /\ fwd'           = [fwd EXCEPT ![L] = {}]
    /\ nlAcks'        = [nlAcks EXCEPT ![L] = {}]
    /\ utdSent'       = [utdSent EXCEPT ![L] = {}]
    /\ acks'          = [acks EXCEPT ![L] = {}]
    /\ lastCommitted' = [lastCommitted EXCEPT ![L] = 0]
    /\ UNCHANGED <<leaderOf, dbInit, curEpoch, accEpoch>>
    /\ UNCHANGED <<syncMode, inbox, pktNotLogged, pktCommitted, pendingTxns, toLog>>
    /\ UNCHANGED <<cLastZxid, cRwTarget, cSeenRw, ghostVars>>

-----------------------------------------------------------------------------
(* CLIENT (ClientCnxn)                                                     *)
-----------------------------------------------------------------------------

\* The connected server answers one of the client's requests: a read, the automatic
\* SetWatches sent after every reconnect (ClientCnxn.java:1016-1081; its xid is rewritten
\* like any request, ClientCnxnSocketNIO.java:111-116), a write's reply, or a NOTREADONLY
\* error.  The reply header carries the server's lastProcessedZxid read at that moment:
\* FinalRequestProcessor.java:166 and :615 (ReplyHeader(cxid, lastZxid, err)), or
\* ReadOnlyRequestProcessor.java:110-114 for writes refused by a read-only server.
\* Replies reach the client in request order (ClientCnxn.java:935-952 matches pendingQueue).
ServerReply(c) ==
    /\ cState[c] \in {"CONNECTED", "CONNECTEDREADONLY"}
    /\ cReplies' = [cReplies EXCEPT ![c] = Append(@, lpz[cConn[c]])]
    /\ served' = served \cup {lpz[cConn[c]]}
    /\ UNCHANGED <<peerVars, dataVars, learnVars, leaderVars>>
    /\ UNCHANGED <<cState, cConn, cLastZxid, cRwTarget, cSeenRw, cSess>>
    /\ UNCHANGED <<targetFired, targetInfo, committed>>

\* ClientCnxn.SendThread.readResponse (ClientCnxn.java:889-965): not a ping/auth/notification
\* (:895-922); the packet is matched (:935-952) and
\*     if (replyHdr.getZxid() > 0) lastZxid = replyHdr.getZxid();        // :957-959
\* a plain overwrite, before the error check (:960), so error replies count too.
ClientRecvReply(c) ==
    /\ cState[c] \in {"CONNECTED", "CONNECTEDREADONLY"}
    /\ cReplies[c] # <<>>
    /\ LET z == Head(cReplies[c]) IN
       cLastZxid' = [cLastZxid EXCEPT ![c] = IF z > 0 THEN z ELSE @]
    /\ cReplies'  = [cReplies EXCEPT ![c] = Tail(@)]
    /\ UNCHANGED <<peerVars, dataVars, learnVars, leaderVars>>
    /\ UNCHANGED <<cState, cConn, cRwTarget, cSeenRw, cSess, ghostVars>>

\* Read-only seek: while CONNECTEDREADONLY the send loop calls pingRwServer
\* (ClientCnxn.java:1266-1277); "isro" to a host (ClientCnxn.java:1349-1371) answers "rw"
\* iff that server is attached and running and not read-only (IsroCommand.java:32-39);
\* RWServerFoundException -> cleanAndNotifyState (:1280-1299), next connect goes there.
ClientSeekRw(c, t) ==
    /\ cState[c] = "CONNECTEDREADONLY"
    /\ serving[t] = "RW"
    /\ cState'    = [cState EXCEPT ![c] = "CONNECTING"]
    /\ cConn'     = [cConn EXCEPT ![c] = NoServer]
    /\ cRwTarget' = [cRwTarget EXCEPT ![c] = t]
    /\ cReplies'  = [cReplies EXCEPT ![c] = <<>>]      \* cleanup fails pending packets
    /\ UNCHANGED <<peerVars, dataVars, learnVars, leaderVars>>
    /\ UNCHANGED <<cLastZxid, cSeenRw, cSess, ghostVars>>

\* The saved rwServerAddress cannot be reached (startConnect fails): the next attempt uses
\* hostProvider.next (ClientCnxn.java:1177-1184).
ClientRwTargetGone(c) ==
    /\ cState[c] = "CONNECTING"
    /\ cRwTarget[c] # NoServer
    /\ serving[cRwTarget[c]] = "NONE"
    /\ cRwTarget' = [cRwTarget EXCEPT ![c] = NoServer]
    /\ UNCHANGED <<peerVars, dataVars, learnVars, leaderVars>>
    /\ UNCHANGED <<cState, cConn, cLastZxid, cSeenRw, cSess, cReplies, ghostVars>>

\* Fault or API: the connection is lost (ClientCnxn.java:1280-1299), or
\* ZooKeeper.updateServerList decides to migrate and closes the socket (ZooKeeper.java:
\* 217-231, client/HostConnectionManager.java:231-240).  The client then reconnects.
ClientMove(c) ==
    /\ cState[c] \in {"CONNECTED", "CONNECTEDREADONLY"}
    /\ cState'    = [cState EXCEPT ![c] = "CONNECTING"]
    /\ cConn'     = [cConn EXCEPT ![c] = NoServer]
    /\ cRwTarget' = [cRwTarget EXCEPT ![c] = NoServer]
    /\ cReplies'  = [cReplies EXCEPT ![c] = <<>>]
    /\ UNCHANGED <<peerVars, dataVars, learnVars, leaderVars>>
    /\ UNCHANGED <<cLastZxid, cSeenRw, cSess, ghostVars>>

-----------------------------------------------------------------------------
(* TARGET CHECK                                                            *)
-----------------------------------------------------------------------------

\* Hit classification (brief section 4), diagnostic only.
HitClass(cz, sz) ==
    IF sz = -1 THEN "A"                       \* S4: untrusted empty DB
    ELSE IF Ctr(cz) = 0 THEN "B"              \* S1: txn-less makeZxid(e, 0)
    ELSE IF cz \notin committed THEN "C"      \* S2: never-committed txn
    ELSE "D"                                  \* S3: committed, not applied at s

\* Client c's (re)connect reaches server s:
\*   ClientCnxn.startConnect / primeConnection: ConnectRequest(0, lastZxid, timeout,
\*     seenRwServerBefore ? sessionId : 0, passwd, readOnly) (ClientCnxn.java:1006-1013);
\*     the next host is rwServerAddress if set (:1177-1179), else any host.
\*   NIOServerCnxn.readConnectRequest: only a running attached server (:438-446).
\*   ZooKeeperServer.processConnectRequest (:1467-1559):
\*     :1487 throttle                                   (not modeled, brief 3.2)
\*     :1499-1503 !readOnly && read-only server        -> NOT_READ_ONLY_CLIENT, close
\*     :1504-1516 lastZxidSeen > lastProcessedZxid     -> CLIENT_ZXID_AHEAD     <== TARGET
\*     :1532-1533 sessionId == 0  -> createSession (local session, no txn: PrepRequestProcessor
\*                                   .java:883-888)
\*     :1540-1555 sessionId != 0  -> reopenSession: an unknown local session is expired and
\*                                   the client closes (ClientCnxn.java:1402-1413)
\*   ClientCnxn.onConnected (:1396-1434): CONNECTED / CONNECTEDREADONLY, seenRwServerBefore.
TargetCheck(c, s) ==
    /\ cState[c] = "CONNECTING"
    /\ cRwTarget[c] \in {NoServer, s}
    /\ serving[s] # "NONE"                                       \* NIOServerCnxn.java:439-441
    /\ cRwTarget' = [cRwTarget EXCEPT ![c] = NoServer]
    /\ IF ~ClientCanBeRO /\ serving[s] = "RO"                    \* ZooKeeperServer.java:1499
       THEN UNCHANGED <<cState, cConn, cSeenRw, cSess, targetFired, targetInfo>>
       ELSE IF cLastZxid[c] > lpz[s]                              \* ZooKeeperServer.java:1504
       THEN /\ targetFired' = TRUE                                \* ZooKeeperServer.java:1516
            /\ targetInfo'  = [cid |-> c, sid |-> s, cz |-> cLastZxid[c], sz |-> lpz[s],
                               srv |-> serving[s], role |-> role[s],
                               cls |-> HitClass(cLastZxid[c], lpz[s])]
            /\ UNCHANGED <<cState, cConn, cSeenRw, cSess>>        \* NIOServerCnxn.java:380-382
       ELSE IF cSeenRw[c] /\ cSess[c] # s                         \* reopenSession, unknown session
       THEN /\ cState' = [cState EXCEPT ![c] = "CLOSED"]
            /\ UNCHANGED <<cConn, cSeenRw, cSess, targetFired, targetInfo>>
       ELSE /\ cState'  = [cState EXCEPT ![c] = IF serving[s] = "RO"
                                                 THEN "CONNECTEDREADONLY" ELSE "CONNECTED"]
            /\ cConn'   = [cConn EXCEPT ![c] = s]
            /\ cSeenRw' = [cSeenRw EXCEPT ![c] = @ \/ serving[s] = "RW"]   \* ClientCnxn.java:1426
            /\ cSess'   = [cSess EXCEPT ![c] = s]
            /\ UNCHANGED <<targetFired, targetInfo>>
    /\ UNCHANGED <<peerVars, dataVars, learnVars, leaderVars, cLastZxid, cReplies, committed, served>>

-----------------------------------------------------------------------------
(* NEXT-STATE RELATION                                                     *)
-----------------------------------------------------------------------------

PeerNext ==
    \E s \in Server :
        \/ PeerStart(s)
        \/ \E g \in BOOLEAN : PeerStop(s, g)
        \/ ReloadDb(s)
        \/ StartRO(s)
        \/ ShutdownRO(s)

ElectionNext ==
    \/ \E Q \in SUBSET Server, L \in Server : Elect(Q, L)
    \/ \E s \in Server : ElectStranded(s)
    \/ \E s, L \in Server : JoinLeader(s, L)

LeaderNext ==
    \E L \in Server :
        \/ \E Q \in SUBSET Server : LeaderDiscovery(L, Q)
        \/ \E F \in Server : LearnerHandlerSync(L, F)
        \/ LeaderStartup(L)
        \/ LeaderServe(L)
        \/ \E F \in Server : LeaderSendUptodate(L, F)
        \/ LeaderPropose(L)
        \/ LeaderSyncAck(L)
        \/ LeaderCommit(L)
        \/ LeaderShutdown(L)

LearnerNext ==
    \E F \in Server :
        \/ LearnerRecvDiff(F)
        \/ LearnerRecvSnap(F)
        \/ LearnerRecvTrunc(F)
        \/ LearnerRecvProposal(F)
        \/ LearnerRecvCommit(F)
        \/ LearnerRecvNewLeader(F)
        \/ LearnerRecvUptodate(F)
        \/ LearnerFlushDeferred(F)
        \/ FollowerRecvProposal(F)
        \/ FollowerSyncAck(F)
        \/ FollowerRecvCommit(F)
        \/ FollowerLoseLeader(F)
        \/ PartitionFollower(F)

ApplyNext == \E s \in Server : ApplyCommitted(s)

ClientNext ==
    \E c \in Client :
        \/ ServerReply(c)
        \/ ClientRecvReply(c)
        \/ ClientRwTargetGone(c)
        \/ ClientMove(c)
        \/ \E s \in Server : ClientSeekRw(c, s)
        \/ \E s \in Server : TargetCheck(c, s)

\* Once the target fired the run is over (tla-patterns section 1).
Next ==
    /\ ~targetFired
    /\ \/ PeerNext
       \/ ElectionNext
       \/ LeaderNext
       \/ LearnerNext
       \/ ApplyNext
       \/ ClientNext

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* PROPERTIES                                                              *)
-----------------------------------------------------------------------------

\* The target check never fails (ZooKeeperServer.java:1504-1516).
TargetSafe == ~targetFired

ZxidOK(z) == z \in Int /\ z >= -1
PktOK(p)  == p.t \in PktTypes /\ p.z \in Int

TypeOK ==
    /\ role \in [Server -> RoleSet]
    /\ phase \in [Server -> PhaseSet]
    /\ leaderOf \in [Server -> Server \cup {NoServer}]
    /\ \A s \in Server : lepoch[s] \in Nat
    /\ serving \in [Server -> {"NONE", "RO", "RW"}]
    /\ dbInit \in [Server -> BOOLEAN]
    /\ \A s \in Server : ZxidOK(lpz[s])
    /\ \A s \in Server : \A x \in clog[s] \cup log[s] : x \in Nat /\ Ctr(x) # 0
    /\ \A s \in Server : snapZ[s] = NoSnap \/ snapZ[s] \in Nat
    /\ \A s \in Server : curEpoch[s] \in Nat /\ accEpoch[s] \in Nat
    /\ syncMode \in [Server -> {"NONE", "DIFF", "SNAP", "TRUNC"}]
    /\ \A s \in Server : \A i \in DOMAIN inbox[s] : PktOK(inbox[s][i])
    /\ \A s \in Server : \A x \in SeqSet(pktNotLogged[s]) \cup SeqSet(pktCommitted[s])
                                  \cup SeqSet(pendingTxns[s]) \cup SeqSet(toLog[s])
                                  \cup SeqSet(commitQ[s]) : x \in Nat
    /\ \A s \in Server : hzxid[s] \in Nat /\ lastCommitted[s] \in Nat
    /\ \A s \in Server : fwd[s] \subseteq Server /\ nlAcks[s] \subseteq Server
                         /\ utdSent[s] \subseteq Server
    /\ \A s \in Server : \A a \in acks[s] : a[1] \in Server /\ a[2] \in Nat
    /\ cState \in [Client -> {"CONNECTING", "CONNECTED", "CONNECTEDREADONLY", "CLOSED"}]
    /\ cConn \in [Client -> Server \cup {NoServer}]
    /\ \A c \in Client : cLastZxid[c] \in Nat
    /\ cRwTarget \in [Client -> Server \cup {NoServer}]
    /\ cSeenRw \in [Client -> BOOLEAN]
    /\ cSess \in [Client -> Server \cup {NoServer, ExpiredSess}]
    /\ \A c \in Client : \A i \in DOMAIN cReplies[c] : ZxidOK(cReplies[c][i])
    /\ targetFired \in BOOLEAN
    /\ committed \subseteq Nat
    /\ served \subseteq Int

\* Structural: "a message carries only values its sender held".  The client's lastZxid
\* (the ConnectRequest's lastZxidSeen) is 0 or a value some server replied with.
ClientZxidWasServed == \A c \in Client : cLastZxid[c] = 0 \/ cLastZxid[c] \in served

\* Structural: a connected client is attached to a serving server of the matching kind.
ClientConnConsistent ==
    \A c \in Client :
        /\ cState[c] = "CONNECTED" => cConn[c] \in Server /\ serving[cConn[c]] = "RW"
        /\ cState[c] = "CONNECTEDREADONLY" => cConn[c] \in Server /\ serving[cConn[c]] = "RO"
        /\ cState[c] \in {"CONNECTING", "CLOSED"} => cConn[c] = NoServer /\ cReplies[c] = <<>>

\* Temporary sanity predicates (tla-patterns section 2): TLC must VIOLATE these.
TargetReached ==
    ~\E c \in Client, s \in Server : ENABLED TargetCheck(c, s)
TargetReachedWithZxid ==
    ~\E c \in Client, s \in Server : cLastZxid[c] > 0 /\ ENABLED TargetCheck(c, s)

\* A small smoke bound for base.cfg (MC.tla carries the real bounds).
BaseStateBound ==
    /\ \A s \in Server : curEpoch[s] <= 2 /\ Ctr(hzxid[s]) <= 1

=============================================================================
