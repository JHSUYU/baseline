------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for base.tla (hbase-adhoc-k1), Category A: one linear  *)
(* NDJSON trace, cursor l.  Event names equal base action names (see       *)
(* instrumentation-spec.md).  Every event carries the post-action snapshot *)
(* of its node:                                                            *)
(*   state.tick    abstract time  floor((now_ms - t0_ms) / TickMs)         *)
(*   state.keys    sorted key ids in allKeys                               *)
(*   state.cur     currentKey id (0 = null)                                *)
(*   state.idSeq   idSeq                                                   *)
(*   state.master  LeaderElector.isMaster                                  *)
(*   state.lku     lastKeyUpdate in ticks (-1 = never, i.e. 0 ms)          *)
(*   state.stopped LeaderElector.stopped                                   *)
(* plus event-specific msg fields.                                         *)
(***************************************************************************)
EXTENDS base, Json, IOUtils, Sequences, TLC

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

VARIABLE l
traceVars == <<l>>

logline == TraceLog[l]
ev == logline.event
st == ev.state
msg == ev.msg

\* Nodes that appear in the trace; the others in Node stay absent.
TraceNodes == TLCEval({TraceLog[k].event.nid : k \in 1..Len(TraceLog)})
ASSUME TraceNodes \subseteq Node

SetOf(s) == {s[i] : i \in DOMAIN s}
Lku(x) == IF x < 0 THEN Epoch0 ELSE x

(***************************************************************************)
(* Event matching and post-state validation                                *)
(***************************************************************************)
IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ ev.name = name
    /\ gtime = st.tick                   \* time must already be at the event's tick

\* Strong validation: every field of the node snapshot.
ValidateNode(n) ==
    /\ DOMAIN allKeys'[n] = SetOf(st.keys)
    /\ currentKey'[n].id = st.cur
    /\ idSeq'[n] = st.idSeq
    /\ isMaster'[n] = st.master
    /\ lastKeyUpdate'[n] = Lku(st.lku)
    /\ stopped'[n] = st.stopped

Step(name, A(_)) ==
    /\ IsEvent(name)
    /\ LET n == ev.nid IN
       /\ A(n)
       /\ ValidateNode(n)
    /\ l' = l + 1

TraceStartCreateParents == Step("StartCreateParents", StartCreateParents)
TraceStartWatchExists   == Step("StartWatchExists", StartWatchExists)

TraceStartListChildren ==
    /\ Step("StartListChildren", StartListChildren)
    /\ startList'[ev.nid] = SetOf(msg.children)

TraceStartReadChildren == Step("StartReadChildren", StartReadChildren)
TraceStartZkFail       == Step("StartZkFail", StartZkFail)

\* One waitToBecomeLeader iteration; msg.claimed tells which branch.
TraceElectorAttempt ==
    /\ IsEvent("ElectorAttempt")
    /\ LET n == ev.nid IN
       /\ IF msg.claimed THEN ElectorAttemptClaim(n) ELSE ElectorAttemptWait(n)
       /\ ValidateNode(n)
    /\ l' = l + 1

TraceBecomeMaster == Step("BecomeMaster", BecomeMaster)

TraceLeaderLoopTop ==
    /\ Step("LeaderLoopTop", LeaderLoopTop)
    /\ msg.exited = (lpc'[ev.nid] = "exited")

\* msg.removed: id of the key removed in this step, 0 = loop finished.
TraceLeaderRemoveExpired ==
    /\ Step("LeaderRemoveExpired", LeaderRemoveExpired)
    /\ IF msg.removed = 0
       THEN lpc'[ev.nid] # "removing"
       ELSE /\ lpc'[ev.nid] = "removing"
            /\ msg.removed \in DOMAIN allKeys[ev.nid] \ DOMAIN allKeys'[ev.nid]
    /\ msg.rollDue = (lpc'[ev.nid] = "rollStart")

TraceRollReadClock ==
    /\ Step("RollReadClock", RollReadClock)
    /\ msg.skipped = (lpc'[ev.nid] = "loop")
    /\ ~msg.skipped => rollNow'[ev.nid] = msg.now

TraceRollInstall ==
    /\ Step("RollInstall", RollInstall)
    /\ currentKey'[ev.nid].id = msg.keyId

\* msg.interrupted: Thread.isInterrupted() after addKeyToZK returned.  Not
\* interrupted => the write happened.  Interrupted => it may or may not have.
TraceRollPublish ==
    /\ Step("RollPublish", RollPublish)
    /\ LET k == currentKey[ev.nid] IN
       ~msg.interrupted => (k.id \in DOMAIN zkKeys' /\ zkKeys'[k.id] = k)

TraceRollUpdatePrev ==
    /\ Step("RollUpdatePrev", RollUpdatePrev)
    /\ LET n == ev.nid IN
       /\ rollPrev[n].id = msg.prevId                       \* 0 = no prev
       /\ msg.prevId # 0 =>
            /\ allKeys'[n][msg.prevId].exp = msg.prevExp
            /\ ~msg.interrupted => (msg.prevId \in DOMAIN zkKeys'
                                    /\ zkKeys'[msg.prevId].exp = msg.prevExp)

\* Like TraceCrash: the model resets the node (Die), while the emitted
\* snapshot is the real pre-abort state, so the node is not validated.
TraceZkWriteFail == /\ IsEvent("ZkWriteFail") /\ ZkWriteFail(ev.nid) /\ l' = l + 1

\* msg.type in {"Children","Data","Deleted","Leader"}, msg.id (0 if none).
TraceHandleEvent ==
    /\ IsEvent("HandleEvent")
    /\ LET n == ev.nid IN
       /\ evq[n] # <<>>
       /\ Head(evq[n]) = Ev(msg.type, msg.id)
       /\ HandleEvent(n)
       /\ ValidateNode(n)
    /\ l' = l + 1

TraceIssueReadClock ==
    /\ Step("IssueReadClock", IssueReadClock)
    /\ cpNow'[ev.nid] = msg.now

\* msg.keyId = 0 when currentKey was null (NPE at ATSM:130).
TraceIssueReadKey ==
    /\ Step("IssueReadKey", IssueReadKey)
    /\ IF msg.keyId = 0
       THEN tokens' = tokens
       ELSE [issuer |-> ev.nid, keyId |-> msg.keyId, sec |-> currentKey[ev.nid].sec,
             exp |-> msg.exp] \in tokens'

\* msg.outcome in {"expired", "unknownKey", "ok"}; the token is identified
\* by (keyId, exp) from the AuthenticationTokenIdentifier.
TraceTargetCheck ==
    /\ IsEvent("TargetCheck")
    /\ LET v == ev.nid IN
       /\ \E t \in tokens :
            /\ t.keyId = msg.keyId /\ t.exp = msg.exp
            /\ TargetCheck(v, t)
            /\ CASE msg.outcome = "expired"    -> t.exp < Clock(v)
                 [] msg.outcome = "unknownKey" -> targetFired'
                 [] msg.outcome = "ok"         -> ~(t.exp < Clock(v)) /\ ~targetFired'
       /\ ValidateNode(v)
    /\ l' = l + 1

TraceNodeStop      == Step("NodeStop", NodeStop)
TraceNodeExit      == /\ IsEvent("NodeExit") /\ NodeExit(ev.nid) /\ l' = l + 1
TraceCrash         == /\ IsEvent("Crash") /\ Crash(ev.nid) /\ l' = l + 1
TraceAbort         == /\ IsEvent("Abort") /\ Abort(ev.nid) /\ l' = l + 1
TraceSessionExpire == /\ IsEvent("SessionExpire") /\ SessionExpire(ev.nid) /\ l' = l + 1
TraceSessionClose  == /\ IsEvent("SessionClose") /\ SessionClose(ev.nid) /\ l' = l + 1
TraceRestart       == Step("Restart", Restart)

(***************************************************************************)
(* Silent action: time advances only up to the next event's tick.          *)
(***************************************************************************)
TraceTick ==
    /\ l <= Len(TraceLog)
    /\ gtime < st.tick
    /\ Tick
    /\ UNCHANGED l

(***************************************************************************)
TraceInit ==
    /\ InitWith(TraceNodes, [n \in Node |-> 0])
    /\ l = 1

TraceNext ==
    \/ TraceStartCreateParents \/ TraceStartWatchExists \/ TraceStartListChildren
    \/ TraceStartReadChildren \/ TraceStartZkFail
    \/ TraceElectorAttempt \/ TraceBecomeMaster
    \/ TraceLeaderLoopTop \/ TraceLeaderRemoveExpired
    \/ TraceRollReadClock \/ TraceRollInstall \/ TraceRollPublish \/ TraceRollUpdatePrev
    \/ TraceZkWriteFail
    \/ TraceHandleEvent
    \/ TraceIssueReadClock \/ TraceIssueReadKey
    \/ TraceTargetCheck
    \/ TraceNodeStop \/ TraceNodeExit \/ TraceCrash \/ TraceAbort
    \/ TraceSessionExpire \/ TraceSessionClose \/ TraceRestart
    \/ TraceTick

TraceSpec == TraceInit /\ [][TraceNext]_<<l, vars>> /\ WF_<<l, vars>>(TraceNext)

TraceView == <<vars, l>>

TraceMatched == <>(l > Len(TraceLog))

TraceAlias ==
    [l |-> l, event |-> IF l <= Len(TraceLog) THEN ev ELSE "done",
     gtime |-> gtime, allKeys |-> allKeys, currentKey |-> currentKey,
     isMaster |-> isMaster, lpc |-> lpc, evq |-> evq, zkKeys |-> zkKeys,
     tokens |-> tokens, targetFired |-> targetFired]

=============================================================================
