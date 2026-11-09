--------------------------------- MODULE Trace ---------------------------------
(***************************************************************************)
(* Trace validation for zk-adhoc-04 (Category A: one linear NDJSON trace).  *)
(*                                                                         *)
(* The harness (instrumentation-spec.md) writes one line per spec action   *)
(* from every peer, LearnerHandler, NIO worker and client thread of the    *)
(* mini cluster through a synchronized SpeculaTrace.emit, so the file      *)
(* order is a total order consistent with real time.  Each wrapper below   *)
(* matches one event, calls the base action unchanged, validates the fields*)
(* the event captured, and advances the cursor l.                          *)
(*                                                                         *)
(* Envelope: {"tag":"trace","ts":..,"event":{"name":..,"nid":..,           *)
(*            "state":{..},"msg":{..}}}                                    *)
(*   nid  = "p<sid>" for peers (QuorumPeer.getMyId), "c<k>" for clients    *)
(*   zxid = {"e": epoch, "c": counter}; -1 is {"e": -1, "c": -1}           *)
(*   sids inside msg/state are plain integers                              *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

-----------------------------------------------------------------------------
(* Trace loading                                                           *)
-----------------------------------------------------------------------------

JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

\* Events that map to spec actions (the "Init" id-mapping line is skipped).
TraceEventNames ==
    { "PeerStart", "PeerStop", "ReloadDb", "StartRO", "ShutdownRO", "FLEDecided",
      "LeaderDiscovery", "LearnerHandlerSync", "LeaderStartup", "LeaderServe",
      "LeaderSendUptodate", "LeaderPropose", "LeaderSyncAck", "LeaderCommit", "LeaderShutdown",
      "LearnerRecvDiff", "LearnerRecvSnap", "LearnerRecvTrunc", "LearnerRecvProposal",
      "LearnerRecvCommit", "LearnerRecvNewLeader", "LearnerRecvUptodate", "LearnerFlushDeferred",
      "FollowerRecvProposal", "FollowerSyncAck", "FollowerRecvCommit", "ApplyCommitted",
      "LearnerShutdown", "TargetCheck", "ServerReply", "ClientRecvReply", "ClientSeekRw",
      "ClientMove" }

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x :
          /\ "tag" \in DOMAIN x
          /\ x.tag = "trace"
          /\ "event" \in DOMAIN x
          /\ x.event.name \in TraceEventNames))

ASSUME Len(TraceLog) > 0

-----------------------------------------------------------------------------
(* Cursor                                                                  *)
-----------------------------------------------------------------------------

VARIABLE l

logline == TraceLog[l]
ev      == logline.event

-----------------------------------------------------------------------------
(* Id and value mapping                                                    *)
-----------------------------------------------------------------------------

PeerOf   == [p1 |-> 1, p2 |-> 2, p3 |-> 3, p4 |-> 4, p5 |-> 5]
ClientOf == [c1 |-> 1, c2 |-> 2, c3 |-> 3]

TraceServers == TLCEval({PeerOf[TraceLog[k].event.nid] :
                           k \in {i \in 1..Len(TraceLog) : TraceLog[i].event.nid \in DOMAIN PeerOf}})
ASSUME TraceServers \subseteq Server

\* zxid object -> spec zxid (Z(e, c) = e * ZB + c); counters must stay below ZB.
TZ(j) == IF j.e < 0 THEN -1 ELSE Z(j.e, j.c)

SetOf(seq) == {seq[i] : i \in DOMAIN seq}

-----------------------------------------------------------------------------
(* Event predicates and cursor step                                        *)
-----------------------------------------------------------------------------

IsEvent(name) == l <= Len(TraceLog) /\ ev.name = name

IsPeerEvent(name, s) ==
    /\ IsEvent(name)
    /\ ev.nid \in DOMAIN PeerOf
    /\ PeerOf[ev.nid] = s

IsClientEvent(name, c) ==
    /\ IsEvent(name)
    /\ ev.nid \in DOMAIN ClientOf
    /\ ClientOf[ev.nid] = c

StepTrace == l' = l + 1

-----------------------------------------------------------------------------
(* Initial state: the workload's QuorumUtil(1) starts from empty data dirs  *)
(* (QuorumUtil.java:110-129), every peer stopped, a fresh client handle.   *)
-----------------------------------------------------------------------------

TraceInit == Init /\ l = 1

-----------------------------------------------------------------------------
(* Post-state validation helpers                                           *)
-----------------------------------------------------------------------------

\* lastProcessedZxid captured after the action (state.lpz)
ValLpz(s) == lpz'[s] = TZ(ev.state.lpz)

\* the peer's role and epochs after the action
ValRole(s)   == role'[s] = ev.state.role
ValEpochs(s) == curEpoch'[s] = ev.state.curEpoch /\ accEpoch'[s] = ev.state.accEpoch

\* highest zxid in the on-disk txn log (FileTxnSnapLog.getLastLoggedZxid), -1 if empty
ValLastLogged(s) == MaxOr(log'[s], -1) = TZ(ev.state.lastLogged)

\* Shutdown paths close client connections before zk.shutdown() fast-forwards the tree, so
\* their events are emitted at entry (instrumentation-spec.md section 3.1) and carry the
\* PRE-state lastProcessedZxid.  The fast-forward result is validated by the next event of
\* the same peer that captures lpz (StartRO, ReloadDb, LearnerHandlerSync.peerLastZxid,
\* TargetCheck, ServerReply).
PreLpz(s) == lpz[s] = TZ(ev.state.lpz)

-----------------------------------------------------------------------------
(* Peer lifecycle and read-only mode                                       *)
-----------------------------------------------------------------------------

PeerStartIfLogged ==
    \E s \in Server :
        /\ IsPeerEvent("PeerStart", s)
        /\ PeerStart(s)
        /\ ValLpz(s) /\ ValEpochs(s) /\ ValLastLogged(s)
        /\ StepTrace

PeerStopIfLogged ==
    \E s \in Server :
        /\ IsPeerEvent("PeerStop", s)
        /\ PeerStop(s, ev.msg.graceful)
        /\ PreLpz(s)
        /\ StepTrace

ReloadDbIfLogged ==
    \E s \in Server :
        /\ IsPeerEvent("ReloadDb", s)
        /\ ReloadDb(s)
        /\ ValLpz(s)
        /\ StepTrace

StartROIfLogged ==
    \E s \in Server :
        /\ IsPeerEvent("StartRO", s)
        /\ StartRO(s)
        /\ ValLpz(s) /\ ValRole(s)
        /\ StepTrace

ShutdownROIfLogged ==
    \E s \in Server :
        /\ IsPeerEvent("ShutdownRO", s)
        /\ PreLpz(s)
        /\ ShutdownRO(s)
        /\ ValRole(s)
        /\ StepTrace

\* FastLeaderElection.setPeerState (:894-899).  The first peer of a round to report runs
\* Elect for some quorum containing it (TLC searches Q; later events prune wrong choices);
\* peers already decided by that Elect only validate; a LOOKING peer that decides for an
\* established leader runs JoinLeader; a peer that decides for itself on stale votes while the
\* others stay undecided runs ElectStranded.
FLEDecidedIfLogged ==
    \E s \in Server :
        /\ IsPeerEvent("FLEDecided", s)
        /\ LET L == ev.msg.leader IN
           \/ /\ role[s] = "LOOKING"
              /\ \/ \E Q \in SUBSET Server : s \in Q /\ Elect(Q, L)
                 \/ JoinLeader(s, L)
                 \/ L = s /\ ElectStranded(s)
              /\ role'[s] = ev.msg.state
              /\ role'[s] = "FOLLOWING" => leaderOf'[s] = L
              /\ StepTrace
           \/ /\ role[s] \in {"LEADING", "FOLLOWING"}
              /\ phase[s] = "ELECTED"
              /\ role[s] = ev.msg.state
              /\ role[s] = "FOLLOWING" => leaderOf[s] = L
              /\ UNCHANGED vars
              /\ StepTrace

-----------------------------------------------------------------------------
(* Leader establishment                                                    *)
-----------------------------------------------------------------------------

LeaderDiscoveryIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderDiscovery", L)
        /\ LeaderDiscovery(L, SetOf(ev.msg.quorum))
        /\ curEpoch'[L] = ev.msg.epoch
        /\ hzxid'[L] = Z(ev.msg.epoch, 0)
        /\ ValLpz(L)
        /\ StepTrace

LearnerHandlerSyncIfLogged ==
    \E L, F \in Server :
        /\ IsPeerEvent("LearnerHandlerSync", L)
        /\ F = ev.msg.peer
        /\ lpz[F] = TZ(ev.msg.peerLastZxid)
        /\ LearnerHandlerSync(L, F)
        /\ Head(inbox'[F]) = Pkt(ev.msg.mode, TZ(ev.msg.zxid))
        /\ StepTrace

LeaderStartupIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderStartup", L)
        /\ LeaderStartup(L)
        /\ lastCommitted'[L] = TZ(ev.msg.zxid)
        /\ ValLpz(L)
        /\ StepTrace

LeaderServeIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderServe", L)
        /\ LeaderServe(L)
        /\ ValLpz(L)
        /\ StepTrace

LeaderSendUptodateIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderSendUptodate", L)
        /\ LeaderSendUptodate(L, ev.msg.peer)
        /\ StepTrace

-----------------------------------------------------------------------------
(* Learner sync                                                            *)
-----------------------------------------------------------------------------

LearnerRecvDiffIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerRecvDiff", F)
        /\ Head(inbox[F]).z = TZ(ev.msg.zxid)
        /\ LearnerRecvDiff(F)
        /\ ValLpz(F)
        /\ StepTrace

LearnerRecvSnapIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerRecvSnap", F)
        /\ Head(inbox[F]).z = TZ(ev.msg.zxid)
        /\ LearnerRecvSnap(F)
        /\ ValLpz(F)
        /\ StepTrace

LearnerRecvTruncIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerRecvTrunc", F)
        /\ Head(inbox[F]).z = TZ(ev.msg.zxid)
        /\ LearnerRecvTrunc(F)
        /\ ValLpz(F) /\ ValLastLogged(F)
        /\ StepTrace

LearnerRecvProposalIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerRecvProposal", F)
        /\ Head(inbox[F]).z = TZ(ev.msg.zxid)
        /\ LearnerRecvProposal(F)
        /\ ValLpz(F)
        /\ StepTrace

LearnerRecvCommitIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerRecvCommit", F)
        /\ Head(inbox[F]).z = TZ(ev.msg.zxid)
        /\ LearnerRecvCommit(F)
        /\ ValLpz(F)
        /\ StepTrace

LearnerRecvNewLeaderIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerRecvNewLeader", F)
        /\ LearnerRecvNewLeader(F)
        /\ ValLpz(F) /\ ValEpochs(F) /\ ValLastLogged(F)
        /\ StepTrace

LearnerRecvUptodateIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerRecvUptodate", F)
        /\ LearnerRecvUptodate(F)
        /\ ValLpz(F)
        /\ StepTrace

LearnerFlushDeferredIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerFlushDeferred", F)
        /\ Len(pktNotLogged[F]) = ev.msg.logged
        /\ Len(pktCommitted[F]) = ev.msg.committed
        /\ LearnerFlushDeferred(F)
        /\ ValLpz(F)
        /\ StepTrace

-----------------------------------------------------------------------------
(* Broadcast                                                               *)
-----------------------------------------------------------------------------

LeaderProposeIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderPropose", L)
        /\ LeaderPropose(L)
        /\ hzxid'[L] = TZ(ev.msg.zxid)
        /\ StepTrace

LeaderSyncAckIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderSyncAck", L)
        /\ LeaderSyncAck(L)
        /\ TZ(ev.msg.zxid) \in log'[L] \ log[L]
        /\ StepTrace

LeaderCommitIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderCommit", L)
        /\ LeaderCommit(L)
        /\ lastCommitted'[L] = TZ(ev.msg.zxid)
        /\ StepTrace

FollowerRecvProposalIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("FollowerRecvProposal", F)
        /\ Head(inbox[F]).z = TZ(ev.msg.zxid)
        /\ FollowerRecvProposal(F)
        /\ StepTrace

FollowerSyncAckIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("FollowerSyncAck", F)
        /\ Head(toLog[F]) = TZ(ev.msg.zxid)
        /\ FollowerSyncAck(F)
        /\ StepTrace

FollowerRecvCommitIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("FollowerRecvCommit", F)
        /\ Head(inbox[F]).z = TZ(ev.msg.zxid)
        /\ FollowerRecvCommit(F)
        /\ ValLpz(F)
        /\ StepTrace

ApplyCommittedIfLogged ==
    \E s \in Server :
        /\ IsPeerEvent("ApplyCommitted", s)
        /\ Head(commitQ[s]) = TZ(ev.msg.zxid)
        /\ ApplyCommitted(s)
        /\ ValLpz(s)
        /\ StepTrace

-----------------------------------------------------------------------------
(* Losing the leader / the quorum                                          *)
-----------------------------------------------------------------------------

\* Learner.shutdown is reached both when the leader instance is gone and on a partition;
\* the trace event does not say which, TLC tries both.
LearnerShutdownIfLogged ==
    \E F \in Server :
        /\ IsPeerEvent("LearnerShutdown", F)
        /\ PreLpz(F)
        /\ FollowerLoseLeader(F) \/ PartitionFollower(F)
        /\ role'[F] = "LOOKING"
        /\ StepTrace

LeaderShutdownIfLogged ==
    \E L \in Server :
        /\ IsPeerEvent("LeaderShutdown", L)
        /\ PreLpz(L)
        /\ LeaderShutdown(L)
        /\ role'[L] = "LOOKING"
        /\ StepTrace

-----------------------------------------------------------------------------
(* Client and target                                                       *)
-----------------------------------------------------------------------------

\* Server side of processConnectRequest (ZooKeeperServer.java:1467-1516).  The pre-state
\* must agree with both operands of the guard; the outcome must agree with the branch.
\* (Whether a passed connect later expires the session is decided asynchronously and is
\* not captured here; ClientRecvReply / later TargetCheck events validate it indirectly.)
TargetCheckIfLogged ==
    \E s \in Server, c \in Client :
        /\ IsPeerEvent("TargetCheck", s)
        /\ c = ClientOf[ev.msg.client]
        /\ cLastZxid[c] = TZ(ev.msg.lastZxidSeen)
        /\ lpz[s] = TZ(ev.state.lpz)
        /\ TargetCheck(c, s)
        /\ targetFired' = (ev.msg.outcome = "CLIENT_ZXID_AHEAD")
        /\ ev.msg.outcome = "PASS" => cState'[c] \in {"CONNECTED", "CONNECTEDREADONLY", "CLOSED"}
        /\ ev.msg.outcome = "NOT_READ_ONLY_CLIENT" => cState'[c] = "CONNECTING"
        /\ StepTrace

ServerReplyIfLogged ==
    \E s \in Server, c \in Client :
        /\ IsPeerEvent("ServerReply", s)
        /\ c = ClientOf[ev.msg.client]
        /\ cConn[c] = s
        /\ ServerReply(c)
        /\ cReplies'[c][Len(cReplies'[c])] = TZ(ev.msg.zxid)
        /\ StepTrace

ClientRecvReplyIfLogged ==
    \E c \in Client :
        /\ IsClientEvent("ClientRecvReply", c)
        /\ Head(cReplies[c]) = TZ(ev.msg.zxid)
        /\ ClientRecvReply(c)
        /\ cLastZxid'[c] = TZ(ev.state.lastZxid)
        /\ StepTrace

ClientSeekRwIfLogged ==
    \E c \in Client :
        /\ IsClientEvent("ClientSeekRw", c)
        /\ ClientSeekRw(c, ev.msg.server)
        /\ StepTrace

ClientMoveIfLogged ==
    \E c \in Client :
        /\ IsClientEvent("ClientMove", c)
        /\ ClientMove(c)
        /\ StepTrace

-----------------------------------------------------------------------------
(* Silent action                                                           *)
-----------------------------------------------------------------------------

\* ClientRwTargetGone has no hook (a failed SocketChannel.connect).  It may fire only when
\* the next event is this client's TargetCheck at a server other than the saved
\* rwServerAddress, and that address is no longer serving.
SilentClientRwTargetGone ==
    /\ l <= Len(TraceLog)
    /\ ev.name = "TargetCheck"
    /\ \E c \in Client :
          /\ c = ClientOf[ev.msg.client]
          /\ cRwTarget[c] # NoServer
          /\ cRwTarget[c] # PeerOf[ev.nid]
          /\ ClientRwTargetGone(c)
          /\ UNCHANGED l

-----------------------------------------------------------------------------
(* Spec                                                                    *)
-----------------------------------------------------------------------------

TraceNext ==
    \/ PeerStartIfLogged
    \/ PeerStopIfLogged
    \/ ReloadDbIfLogged
    \/ StartROIfLogged
    \/ ShutdownROIfLogged
    \/ FLEDecidedIfLogged
    \/ LeaderDiscoveryIfLogged
    \/ LearnerHandlerSyncIfLogged
    \/ LeaderStartupIfLogged
    \/ LeaderServeIfLogged
    \/ LeaderSendUptodateIfLogged
    \/ LearnerRecvDiffIfLogged
    \/ LearnerRecvSnapIfLogged
    \/ LearnerRecvTruncIfLogged
    \/ LearnerRecvProposalIfLogged
    \/ LearnerRecvCommitIfLogged
    \/ LearnerRecvNewLeaderIfLogged
    \/ LearnerRecvUptodateIfLogged
    \/ LearnerFlushDeferredIfLogged
    \/ LeaderProposeIfLogged
    \/ LeaderSyncAckIfLogged
    \/ LeaderCommitIfLogged
    \/ FollowerRecvProposalIfLogged
    \/ FollowerSyncAckIfLogged
    \/ FollowerRecvCommitIfLogged
    \/ ApplyCommittedIfLogged
    \/ LearnerShutdownIfLogged
    \/ LeaderShutdownIfLogged
    \/ TargetCheckIfLogged
    \/ ServerReplyIfLogged
    \/ ClientRecvReplyIfLogged
    \/ ClientSeekRwIfLogged
    \/ ClientMoveIfLogged
    \/ SilentClientRwTargetGone

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceMatched == <>(l > Len(TraceLog))

TraceView == <<vars, l>>

TraceAlias ==
    [ l        |-> l,
      len      |-> Len(TraceLog),
      event    |-> IF l <= Len(TraceLog) THEN ev.name ELSE "DONE",
      nid      |-> IF l <= Len(TraceLog) THEN ev.nid ELSE "DONE",
      tstate   |-> IF l <= Len(TraceLog) /\ "state" \in DOMAIN ev THEN ev.state ELSE "-",
      tmsg     |-> IF l <= Len(TraceLog) /\ "msg" \in DOMAIN ev THEN ev.msg ELSE "-",
      role     |-> role,
      phase    |-> phase,
      serving  |-> serving,
      lpz      |-> lpz,
      log      |-> log,
      inbox    |-> inbox,
      cState   |-> cState,
      cConn    |-> cConn,
      cLastZxid |-> cLastZxid,
      cReplies |-> cReplies,
      targetFired |-> targetFired ]

=============================================================================
