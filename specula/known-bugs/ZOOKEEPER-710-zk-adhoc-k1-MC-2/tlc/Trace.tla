------------------------------- MODULE Trace -------------------------------
(***************************************************************************)
(* Trace validation for base (zk-adhoc-k1), Category A: one linear NDJSON  *)
(* trace. The workload's servers and client run in one JVM (QuorumBase),   *)
(* so a single synchronized logger gives a total order.                    *)
(*                                                                         *)
(* Record: {"tag":"trace", "event": {"name": ..., "nid": ..., ...}}        *)
(* Server ids and owner values are strings: "None", "Me", or a learner sid *)
(* (see instrumentation-spec.md).                                          *)
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

logline == TraceLog[l].event

----------------------------------------------------------------------------
\* Servers, taken from the trace

LeaderEvents == {"LeaderSubmit", "LeaderReadConnect", "LeaderRecvRevalidate",
                 "LeaderRecvRequest", "PrepCreateSession", "CheckSession"}

TraceLeader == TLCEval(
    LET ks == {k \in 1..Len(TraceLog) : TraceLog[k].event.name \in LeaderEvents}
    IN TraceLog[CHOOSE k \in ks : \A j \in ks : k <= j].event.nid)

TraceServers == TLCEval(
    UNION { ({TraceLog[k].event.nid} \ {"client"})
            \cup (IF "srv" \in DOMAIN TraceLog[k].event
                  THEN {TraceLog[k].event.srv} ELSE {})
            \cup (IF "f" \in DOMAIN TraceLog[k].event
                  THEN {TraceLog[k].event.f} ELSE {})
          : k \in 1..Len(TraceLog) })

TraceFollowers == TraceServers \ {TraceLeader}

\* Implementation owner string -> spec owner
TraceOwner(v) ==
    IF v = "None" THEN None ELSE IF v = "Me" THEN Me ELSE v

\* Opcode name (ZooDefs.OpCode) -> spec request type
OpType(op) ==
    CASE op \in {"create", "delete", "setData", "setACL"}                 -> "write"
      [] op \in {"exists", "getData", "getACL", "getChildren",
                 "getChildren2", "setWatches"}                             -> "read"
      [] op = "ping"                                                       -> "ping"
      [] op = "sync"                                                       -> "sync"
      [] op = "createSession"                                              -> "createSession"

----------------------------------------------------------------------------
IsEvent(name) ==
    /\ l <= Len(TraceLog)
    /\ logline.name = name

Last(s) == s[Len(s)]

\* Post-state checks for the fields each event captures (instrumentation-spec.md 2).
CheckOwner == owner' = TraceOwner(logline.owner)

----------------------------------------------------------------------------
\* Action wrappers

TraceClientCreateSession ==
    /\ IsEvent("ClientCreateSession")
    /\ ClientCreateSession(logline.nid)
    /\ client'.st = "Creating"
    /\ client'.srv = logline.nid
    /\ l' = l + 1

TraceClientOpen ==
    /\ IsEvent("ClientOpen")
    /\ ClientOpen(logline.srv)
    /\ client'.srv = logline.srv
    /\ client'.st = "Sent"
    /\ l' = l + 1

TraceClientAbandonOpen ==
    /\ IsEvent("ClientAbandonOpen")
    /\ ClientAbandonOpen
    /\ client.srv = logline.srv
    /\ client'.st = "Disc"
    /\ l' = l + 1

TraceClientDisconnect ==
    /\ IsEvent("ClientDisconnect")
    /\ ClientDisconnect
    /\ client.srv = logline.srv
    /\ client'.st = "Disc"
    /\ l' = l + 1

TraceLeaderSubmit ==
    /\ IsEvent("LeaderSubmit")
    /\ logline.nid = Leader
    /\ ClientSubmitLeader(OpType(logline.type))
    /\ Last(prepQueue') = PrepEntry(OpType(logline.type), TraceOwner(logline.reqOwner))
    /\ l' = l + 1

TraceFollowerSubmit ==
    /\ IsEvent("FollowerSubmit")
    /\ ClientSubmitFollower(logline.nid, OpType(logline.type))
    /\ Last(link'[logline.nid]) = ReqPkt(OpType(logline.type))
    /\ l' = l + 1

TraceFollowerReadConnect ==
    /\ IsEvent("FollowerReadConnect")
    /\ \E a \in inbox[logline.nid] : FollowerReadConnect(logline.nid, a)
    /\ Last(link'[logline.nid]) = RevalPkt
    /\ l' = l + 1

TraceLeaderReadConnect ==
    /\ IsEvent("LeaderReadConnect")
    /\ logline.nid = Leader
    /\ \E a \in inbox[Leader] : LeaderReadConnect(a)
    /\ sessionAlive = logline.valid
    /\ CheckOwner
    /\ (logline.valid => client'.st = "Conn")
    /\ l' = l + 1

TraceLeaderRecvRevalidate ==
    /\ IsEvent("LeaderRecvRevalidate")
    /\ logline.nid = Leader
    /\ LeaderRecvRevalidate(logline.f)
    /\ sessionAlive = logline.valid
    /\ CheckOwner
    /\ l' = l + 1

TraceFollowerRevalidate ==
    /\ IsEvent("FollowerRevalidate")
    /\ FollowerRevalidate(logline.nid)
    /\ (pendingReval[logline.nid] # 0) = logline.found
    /\ sessionAlive = logline.valid
    /\ (logline.connected => (client'.st = "Conn" /\ client'.srv = logline.nid))
    /\ l' = l + 1

TraceLeaderRecvRequest ==
    /\ IsEvent("LeaderRecvRequest")
    /\ logline.nid = Leader
    /\ LeaderRecvRequest(logline.f)
    /\ Head(link[logline.f]).type = OpType(logline.type)
    /\ Last(prepQueue') = PrepEntry(OpType(logline.type), TraceOwner(logline.reqOwner))
    /\ l' = l + 1

TracePrepCreateSession ==
    /\ IsEvent("PrepCreateSession")
    /\ logline.nid = Leader
    /\ PrepCreateSession
    /\ Head(prepQueue).owner = TraceOwner(logline.reqOwner)
    /\ CheckOwner
    /\ sessionAlive'
    /\ l' = l + 1

TraceCheckSession ==
    /\ IsEvent("CheckSession")
    /\ logline.nid = Leader
    /\ TargetCheck
    /\ Head(prepQueue).type = OpType(logline.type)
    /\ Head(prepQueue).owner = TraceOwner(logline.reqOwner)
    /\ owner = TraceOwner(logline.ownerBefore)
    /\ CheckOwner
    /\ targetFired' = (logline.result = "moved")
    /\ (logline.result = "claimed") = (owner = None /\ sessionAlive)
    /\ (logline.result = "expired") = ~sessionAlive
    /\ l' = l + 1

TraceNext ==
    \/ TraceClientCreateSession
    \/ TraceClientOpen
    \/ TraceClientAbandonOpen
    \/ TraceClientDisconnect
    \/ TraceLeaderSubmit
    \/ TraceFollowerSubmit
    \/ TraceFollowerReadConnect
    \/ TraceLeaderReadConnect
    \/ TraceLeaderRecvRevalidate
    \/ TraceFollowerRevalidate
    \/ TraceLeaderRecvRequest
    \/ TracePrepCreateSession
    \/ TraceCheckSession

TraceInit ==
    /\ Init
    /\ l = 1

TraceSpec == TraceInit /\ [][TraceNext]_<<vars, l>> /\ WF_<<vars, l>>(TraceNext)

TraceMatched == <>(l > Len(TraceLog))

TraceView == <<vars, l>>

TraceAlias ==
    [l |-> l,
     event |-> IF l <= Len(TraceLog) THEN logline ELSE "done",
     owner |-> owner, client |-> client, prepQueue |-> prepQueue,
     link |-> link, inbox |-> inbox, pendingReval |-> pendingReval,
     targetFired |-> targetFired]

=============================================================================
