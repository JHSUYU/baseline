------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for base.tla (ad hoc target QP:1236). Category A:      *)
(* a single linear NDJSON trace, walked by the cursor l.                   *)
(*                                                                         *)
(* Anchor: CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile *)
(* run as written (adhoc Shared Rule 4). Event names and fields are in     *)
(* instrumentation-spec.md.                                                *)
(*                                                                         *)
(* Every wrapper calls the full base action, then checks the post-state    *)
(* against the fields the event captured. memZxid is checked only where    *)
(* the implementation's value is settled when the event fires: a COMMIT is *)
(* applied later by the CommitProcessor thread (FZK:99-110), so the        *)
(* broadcast events check the zxid in the message instead.                 *)
(***************************************************************************)
EXTENDS base, Json, IOUtils

(***************************************************************************)
(* Trace loading                                                           *)
(***************************************************************************)
JsonFile ==
    IF "JSON" \in DOMAIN IOEnv THEN IOEnv.JSON
    ELSE "../traces/trace.ndjson"

TraceLog == TLCEval(
    LET all == ndJsonDeserialize(JsonFile)
    IN SelectSeq(all, LAMBDA x :
        /\ "tag" \in DOMAIN x
        /\ x.tag = "trace"
        /\ "event" \in DOMAIN x))

ASSUME Len(TraceLog) > 0

VARIABLE l       \* current position in TraceLog (1-indexed)

logline == TraceLog[l]
Ev == logline.event

(***************************************************************************)
(* Identity and event predicates. Peers are "p<sid>" (adhoc java-harness). *)
(***************************************************************************)
Nid(s) == "p" \o ToString(s)
Peer(nid) == CHOOSE s \in Server : Nid(s) = nid

TraceServer == TLCEval({TraceLog[k].event.nid : k \in 1..Len(TraceLog)})
ASSUME \A nid \in TraceServer : \E s \in Server : Nid(s) = nid

IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ Ev.name = name

Advance == l' = l + 1

(***************************************************************************)
(* Post-state validation                                                   *)
(***************************************************************************)
\* Full: the node's settled volatile state
ValidatePostState(n) ==
    /\ memZxid'[n] = Ev.state.zxid
    /\ memCur'[n]  = Ev.state.curEpoch
    /\ memAcc'[n]  = Ev.state.accEpoch

\* Weak: epochs only, for events on threads where lastProcessedZxid is still
\* being moved by the CommitProcessor (see the module header)
ValidateEpochs(n) ==
    /\ memCur'[n]  = Ev.state.curEpoch
    /\ memAcc'[n]  = Ev.state.accEpoch

(***************************************************************************)
(* TargetCheck                                                             *)
(***************************************************************************)
\* msg.outcome: "ok" (normal return, QP:1260), "fallback" (about to call
\* QP:1234), "fail" (QP:1262, any failure but the target), "target" (QP:1236)
ValidateLoad(n) ==
    /\ curFile[n] = Ev.msg.diskCur                  \* pre-state, read at QP:1208
    /\ tmp[n]     = Ev.msg.diskTmp
    /\ memZxid'[n] = Ev.state.zxid
    /\ memCur'[n]  = Ev.state.curEpoch
    /\ targetFired' = (Ev.msg.outcome = "target")
    /\ Ev.msg.outcome = "fallback" => wrCtx'[n] = "Load"
    /\ Ev.msg.outcome = "ok"       => /\ wrCtx'[n] = "None"
                                      /\ role'[n] = "Looking"
                                      /\ memAcc'[n] = Ev.state.accEpoch
    /\ Ev.msg.outcome = "fail"     => wrCtx'[n] = "None"

StartIfLogged ==
    /\ IsEvent("Start")
    /\ LET n == Peer(Ev.nid) IN
       /\ Start(n)
       /\ ValidateLoad(n)
    /\ Advance

ElectReloadIfLogged ==
    /\ IsEvent("ElectReload")
    /\ LET n == Peer(Ev.nid) IN
       /\ ElectReload(n)
       /\ ValidateLoad(n)
    /\ Advance

(***************************************************************************)
(* Epoch write                                                             *)
(***************************************************************************)
EpochTmpOpenIfLogged ==
    /\ IsEvent("EpochTmpOpen")
    /\ LET n == Peer(Ev.nid) IN
       /\ EpochTmpOpen(n)
       /\ wrVal[n] = Ev.msg.epoch
       /\ tmp'[n] = TmpEmpty
    /\ UNCHANGED targetFired
    /\ Advance

EpochTmpFillIfLogged ==
    /\ IsEvent("EpochTmpFill")
    /\ LET n == Peer(Ev.nid) IN
       /\ EpochTmpFill(n)
       /\ tmp'[n] = Ev.msg.epoch
    /\ UNCHANGED targetFired
    /\ Advance

EpochRenameIfLogged ==
    /\ IsEvent("EpochRename")
    /\ LET n == Peer(Ev.nid) IN
       /\ EpochRename(n)
       /\ curFile'[n] = Ev.msg.epoch
       /\ tmp'[n] = TmpNone
       /\ memCur'[n] = Ev.msg.epoch
    /\ UNCHANGED targetFired
    /\ Advance

EpochWriteFailIfLogged ==
    /\ IsEvent("EpochWriteFail")
    /\ LET n == Peer(Ev.nid) IN
       /\ EpochWriteFail(n)
       /\ tmp'[n] = Ev.msg.diskTmp
       /\ curFile'[n] = Ev.msg.diskCur
    /\ UNCHANGED targetFired
    /\ Advance

EpochRenameFailIfLogged ==
    /\ IsEvent("EpochRenameFail")
    /\ LET n == Peer(Ev.nid) IN
       /\ EpochRenameFail(n)
       /\ tmp'[n] = Ev.msg.diskTmp
       /\ curFile'[n] = Ev.msg.diskCur
    /\ UNCHANGED targetFired
    /\ Advance

(***************************************************************************)
(* Election. The model's Elect(Q) is atomic across Q; the implementation   *)
(* decides peer by peer (FLE:985, 1056, 1149, 1169). The first event of a  *)
(* group fires Elect(Q) for some Q containing the peer and the leader;     *)
(* the group's later events find the peer already placed, or a straggler   *)
(* joins through ElectJoin. Wrong Q guesses die on later events.           *)
(***************************************************************************)
ElectIfLogged ==
    /\ IsEvent("Elect")
    /\ LET n == Peer(Ev.nid)
           w == Ev.msg.leader
       IN
       \/ \* already placed by an earlier event of this group
          /\ \/ n = w /\ role[n] = "Leading"
             \/ n /= w /\ role[n] = "Following" /\ leaderOf[n] = w
          /\ UNCHANGED vars
       \/ /\ \E Q \in SUBSET Server :
               /\ n \in Q
               /\ w \in Q
               /\ Winner(Q) = w
               /\ Elect(Q)
          /\ UNCHANGED targetFired
       \/ /\ ElectJoin(n, w)
          /\ UNCHANGED targetFired
    /\ Advance

(***************************************************************************)
(* Leader establishment                                                    *)
(***************************************************************************)
LeadLoadDataIfLogged ==
    /\ IsEvent("LeadLoadData")
    /\ LET n == Peer(Ev.nid) IN
       /\ LeadLoadData(n)
       /\ snapZxid'[n] = Ev.msg.snapZxid
       /\ ValidatePostState(n)
    /\ UNCHANGED targetFired
    /\ Advance

LeadGetEpochToProposeIfLogged ==
    /\ IsEvent("LeadGetEpochToPropose")
    /\ LET n == Peer(Ev.nid) IN
       /\ LeadGetEpochToPropose(n)
       /\ lEpoch'[n] = Ev.msg.epoch
       /\ accFile'[n] = Ev.msg.epoch
       /\ memAcc'[n] = Ev.msg.epoch
    /\ UNCHANGED targetFired
    /\ Advance

LeadWaitForEpochAckIfLogged ==
    /\ IsEvent("LeadWaitForEpochAck")
    /\ LET n == Peer(Ev.nid) IN
       /\ LeadWaitForEpochAck(n)
       /\ wrVal'[n] = Ev.msg.epoch
    /\ UNCHANGED targetFired
    /\ Advance

LeadStartZkServerIfLogged ==
    /\ IsEvent("LeadStartZkServer")
    /\ LET n == Peer(Ev.nid) IN
       /\ LeadStartZkServer(n)
       /\ ValidatePostState(n)
    /\ UNCHANGED targetFired
    /\ Advance

LeadProposeIfLogged ==
    /\ IsEvent("LeadPropose")
    /\ LET n == Peer(Ev.nid) IN
       /\ LeadPropose(n)
       /\ dLog'[n] = dLog[n] \cup {Ev.msg.zxid}
       /\ Ev.msg.zxid \notin dLog[n]
    /\ UNCHANGED targetFired
    /\ Advance

LeadCommitIfLogged ==
    /\ IsEvent("LeadCommit")
    /\ LET n == Peer(Ev.nid) IN
       /\ LeadCommit(n)
       /\ memZxid'[n] = Ev.msg.zxid
    /\ UNCHANGED targetFired
    /\ Advance

(***************************************************************************)
(* Sync source. nid is the leader; msg.to is the learner.                  *)
(***************************************************************************)
LearnerHandlerSyncFollowerIfLogged ==
    /\ IsEvent("LearnerHandlerSyncFollower")
    /\ LET n == Peer(Ev.nid)
           f == Peer(Ev.msg.to)
       IN
       /\ memZxid[f] = Ev.msg.peerZxid
       /\ LearnerHandlerSyncFollower(n, f)
       /\ Len(q'[f]) > 0
       /\ q'[f][1].type = Ev.msg.op
       /\ q'[f][1].zxid = Ev.msg.opZxid
       /\ Len(q'[f]) = 1 + Ev.msg.numQueued
    /\ UNCHANGED targetFired
    /\ Advance

LearnerHandlerSendNewLeaderIfLogged ==
    /\ IsEvent("LearnerHandlerSendNewLeader")
    /\ LET n == Peer(Ev.nid)
           f == Peer(Ev.msg.to)
       IN
       /\ LearnerHandlerSendNewLeader(n, f)
       /\ Zxid(lEpoch[n], 0) = Ev.msg.zxid
    /\ UNCHANGED targetFired
    /\ Advance

LearnerHandlerSendUpToDateIfLogged ==
    /\ IsEvent("LearnerHandlerSendUpToDate")
    /\ LearnerHandlerSendUpToDate(Peer(Ev.nid), Peer(Ev.msg.to))
    /\ UNCHANGED targetFired
    /\ Advance

(***************************************************************************)
(* Learner                                                                 *)
(***************************************************************************)
RegisterWithLeaderIfLogged ==
    /\ IsEvent("RegisterWithLeader")
    /\ LET n == Peer(Ev.nid) IN
       /\ RegisterWithLeader(n)
       /\ leaderOf[n] = Ev.msg.leader
       /\ memAcc[n] = Ev.state.accEpoch
    /\ UNCHANGED targetFired
    /\ Advance

ReceiveLeaderInfoIfLogged ==
    /\ IsEvent("ReceiveLeaderInfo")
    /\ LET n == Peer(Ev.nid) IN
       /\ ReceiveLeaderInfo(n)
       /\ lEpoch[leaderOf[n]] = Ev.msg.newEpoch
       /\ ValidatePostState(n)
    /\ UNCHANGED targetFired
    /\ Advance

ReadSyncOpIfLogged ==
    /\ IsEvent("ReadSyncOp")
    /\ LET n == Peer(Ev.nid) IN
       /\ ReadSyncOp(n)
       /\ Head(q[n]).type = Ev.msg.op
       /\ Head(q[n]).zxid = Ev.msg.opZxid
       /\ syncMode'[n] = Ev.msg.op
       /\ ValidatePostState(n)
    /\ UNCHANGED targetFired
    /\ Advance

SyncRecvProposalIfLogged ==
    /\ IsEvent("SyncRecvProposal")
    /\ LET n == Peer(Ev.nid) IN
       /\ SyncRecvProposal(n)
       /\ Head(q[n]).zxid = Ev.msg.zxid
    /\ UNCHANGED targetFired
    /\ Advance

SyncRecvCommitIfLogged ==
    /\ IsEvent("SyncRecvCommit")
    /\ LET n == Peer(Ev.nid) IN
       /\ SyncRecvCommit(n)
       /\ Head(q[n]).zxid = Ev.msg.zxid
       /\ memZxid'[n] = Ev.state.zxid         \* LRN:690 applies on this thread
    /\ UNCHANGED targetFired
    /\ Advance

NLPersistIfLogged ==
    /\ IsEvent("NLPersist")
    /\ LET n == Peer(Ev.nid) IN
       /\ NLPersist(n)
       /\ snapZxid'[n] >= Ev.msg.snapZxid     \* snapZxid is the newest by name
       /\ wrVal'[n] = Ev.msg.newEpoch
       /\ ValidatePostState(n)
    /\ UNCHANGED targetFired
    /\ Advance

ReadUpToDateIfLogged ==
    /\ IsEvent("ReadUpToDate")
    /\ ReadUpToDate(Peer(Ev.nid))
    /\ UNCHANGED targetFired
    /\ Advance

LoopExitIfLogged ==
    /\ IsEvent("LoopExit")
    /\ LoopExit(Peer(Ev.nid))
    /\ UNCHANGED targetFired
    /\ Advance

PostLoopLogIfLogged ==
    /\ IsEvent("PostLoopLog")
    /\ LET n == Peer(Ev.nid) IN
       /\ PostLoopLog(n)
       /\ Cardinality(pNotLogged[n]) = Ev.msg.numLogged
       /\ Cardinality(pCommitted[n]) = Ev.msg.numCommitted
    /\ UNCHANGED targetFired
    /\ Advance

FollowerLogProposalIfLogged ==
    /\ IsEvent("FollowerLogProposal")
    /\ LET n == Peer(Ev.nid) IN
       /\ FollowerLogProposal(n)
       /\ Head(q[n]).zxid = Ev.msg.zxid
    /\ UNCHANGED targetFired
    /\ Advance

FollowerCommitIfLogged ==
    /\ IsEvent("FollowerCommit")
    /\ LET n == Peer(Ev.nid) IN
       /\ FollowerCommit(n)
       /\ Head(q[n]).zxid = Ev.msg.zxid
    /\ UNCHANGED targetFired
    /\ Advance

LearnerAbortIfLogged ==
    /\ IsEvent("LearnerAbort")
    /\ LET n == Peer(Ev.nid) IN
       /\ LearnerAbort(n)
       /\ syncMode[n] = Ev.msg.syncMode
       /\ zkDbInit'[n] = Ev.msg.zkDbInit
       /\ ValidateEpochs(n)
    /\ UNCHANGED targetFired
    /\ Advance

(***************************************************************************)
(* Leader step-down and graceful stop                                      *)
(***************************************************************************)
\* LDR:868 is one code point for three spec actions. isShutdown makes it fire
\* once (LDR:864); a leader whose epoch write failed already stepped down in
\* EpochWriteFail, so its event is a no-op here.
LeaderStepDownIfLogged ==
    /\ IsEvent("LeaderStepDown")
    /\ LET n == Peer(Ev.nid) IN
       \/ /\ role[n] /= "Leading"
          /\ UNCHANGED vars
       \/ /\ running[n]
          /\ LeaderAbort(n)
          /\ UNCHANGED targetFired
       \/ /\ ~running[n]
          /\ ShutdownLeader(n)
          /\ UNCHANGED targetFired
    /\ Advance

ShutdownBeginIfLogged ==
    /\ IsEvent("ShutdownBegin")
    /\ ShutdownBegin(Peer(Ev.nid))
    /\ UNCHANGED targetFired
    /\ Advance

\* LRN:919 also runs from the main thread's finally (QP:1619), after a stop may
\* have ended the follow already: then this event changes nothing.
ShutdownCloseSockIfLogged ==
    /\ IsEvent("ShutdownCloseSock")
    /\ LET n == Peer(Ev.nid) IN
       \/ /\ ShutdownCloseSock(n)
          /\ UNCHANGED targetFired
       \/ /\ role[n] /= "Following" \/ ~sockOpen[n]
          /\ UNCHANGED vars
    /\ Advance

ShutdownEndIfLogged ==
    /\ IsEvent("ShutdownEnd")
    /\ ShutdownEnd(Peer(Ev.nid))
    /\ UNCHANGED targetFired
    /\ Advance

(***************************************************************************)
(* Silent action. The workload itself writes the epoch files while every   *)
(* server is down (CurrentEpochWriteFailureTest.java:83-84); the test      *)
(* source is run as written and emits no event. The next Start reports the *)
(* disk it read, so this fires only when that differs from the model, and  *)
(* only for the exact plant of lines 83-84: currentEpoch - 1 in the file,  *)
(* currentEpoch in the tmp. The test plants with all servers down, but its *)
(* restarts are concurrent and another peer may log Start first; the plant *)
(* touches only n's files, so it commutes with those Starts, and only n    *)
(* has to be down here. Trace-only: the hunts have no such action, and a   *)
(* variant may not use it (adhoc harness rules).                           *)
(***************************************************************************)
SilentTestPlantEpochFiles ==
    /\ IsEvent("Start")
    /\ LET n == Peer(Ev.nid) IN
       /\ role[n] = "Down"
       /\ tmp[n] = TmpNone
       /\ Ev.msg.diskTmp = curFile[n]
       /\ Ev.msg.diskCur = curFile[n] - 1
       /\ curFile' = [curFile EXCEPT ![n] = Ev.msg.diskCur]
       /\ tmp'     = [tmp EXCEPT ![n] = Ev.msg.diskTmp]
    /\ UNCHANGED <<snapZxid, dLog, accFile, memVars, writeVars, learnVars, leadVars,
                   netVars, targetFired, l>>

(***************************************************************************)
(* Spec                                                                    *)
(***************************************************************************)
TraceInit ==
    /\ Init
    /\ l = 1

TraceNext ==
    \/ StartIfLogged
    \/ ElectReloadIfLogged
    \/ EpochTmpOpenIfLogged
    \/ EpochTmpFillIfLogged
    \/ EpochRenameIfLogged
    \/ EpochWriteFailIfLogged
    \/ EpochRenameFailIfLogged
    \/ ElectIfLogged
    \/ LeadLoadDataIfLogged
    \/ LeadGetEpochToProposeIfLogged
    \/ LeadWaitForEpochAckIfLogged
    \/ LeadStartZkServerIfLogged
    \/ LeadProposeIfLogged
    \/ LeadCommitIfLogged
    \/ LearnerHandlerSyncFollowerIfLogged
    \/ LearnerHandlerSendNewLeaderIfLogged
    \/ LearnerHandlerSendUpToDateIfLogged
    \/ RegisterWithLeaderIfLogged
    \/ ReceiveLeaderInfoIfLogged
    \/ ReadSyncOpIfLogged
    \/ SyncRecvProposalIfLogged
    \/ SyncRecvCommitIfLogged
    \/ NLPersistIfLogged
    \/ ReadUpToDateIfLogged
    \/ LoopExitIfLogged
    \/ PostLoopLogIfLogged
    \/ FollowerLogProposalIfLogged
    \/ FollowerCommitIfLogged
    \/ LearnerAbortIfLogged
    \/ LeaderStepDownIfLogged
    \/ ShutdownBeginIfLogged
    \/ ShutdownCloseSockIfLogged
    \/ ShutdownEndIfLogged
    \/ SilentTestPlantEpochFiles

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceView == <<vars, l>>

TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [
        l        |-> l,
        len      |-> Len(TraceLog),
        event    |-> IF l <= Len(TraceLog) THEN Ev.name ELSE "DONE",
        nid      |-> IF l <= Len(TraceLog) THEN Ev.nid ELSE "DONE",
        tState   |-> IF l <= Len(TraceLog) THEN Ev.state ELSE "DONE",
        role     |-> role,
        lstep    |-> lstep,
        lstate   |-> lstate,
        memZxid  |-> memZxid,
        memCur   |-> memCur,
        memAcc   |-> memAcc,
        curFile  |-> curFile,
        tmp      |-> tmp,
        snapZxid |-> snapZxid,
        dLog     |-> dLog,
        wrStep   |-> wrStep,
        syncMode |-> syncMode,
        q        |-> q,
        hstep    |-> hstep
    ]

=============================================================================
