------------------------------ MODULE base ------------------------------
(***************************************************************************)
(* Ad hoc coordination target zk-adhoc-k1 (Apache ZooKeeper @ 31794056e6). *)
(*                                                                         *)
(* Target: SessionTrackerImpl.checkSession(long, Object), the throw of     *)
(*   KeeperException.SessionMovedException at                              *)
(*   server/SessionTrackerImpl.java:246, guarded by                        *)
(*   `session.owner != owner` (L245) when session.owner is already set.    *)
(*                                                                         *)
(* Category A (distributed / message passing). One client session, one    *)
(* leader, a set of followers. Only the leader's SessionTrackerImpl keeps  *)
(* an owner (LearnerSessionTracker.java:79-85 are no-ops), so the model    *)
(* tracks one `owner` value at the leader and every path that writes it:   *)
(*   - LearnerHandler REVALIDATE      (LearnerHandler.java:395-423)        *)
(*   - leader-local reopen            (LeaderZooKeeperServer.java:165-175) *)
(*   - Prep createSession             (PrepRequestProcessor.java:352-361)  *)
(*   - claim-on-null in checkSession  (SessionTrackerImpl.java:243-244)    *)
(* and every path that reaches the check (PrepRequestProcessor.pRequest).  *)
(*                                                                         *)
(* Citations are relative to src/java/main/org/apache/zookeeper/.          *)
(*                                                                         *)
(* Owner values (Java reference identity):                                 *)
(*   Me    = ServerCnxn.me (ServerCnxn.java:39), the leader's own clients  *)
(*   f     = the LearnerHandler instance of follower f (one per learner    *)
(*           link; learner reconnection is not modelled, brief 3.2)        *)
(*   None  = null                                                          *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Leader,      \* the leader server
    Followers,   \* follower (learner) servers; also their LearnerHandler owner values
    None,        \* Java null
    Me           \* ServerCnxn.me

Server == {Leader} \cup Followers
Owners == {None, Me} \cup Followers

\* Spec request types. Opcodes are grouped by the Prep branch they take
\* (PrepRequestProcessor.java:209-397) and by where a follower sends them
\* (FollowerRequestProcessor.java:75-88).
\*   "write"         create/delete/setData/setACL      PRP L209-212, 271-274, 305-308, 327-330
\*   "read"          exists/getData/getACL/getChildren/getChildren2/setWatches   PRP L389-397
\*   "ping"          ping                               PRP L394-397
\*   "sync"          sync                               PRP L388, 396-397
\*   "createSession" createSession                      PRP L352-361
CheckTypes  == {"write", "read", "ping", "sync"}   \* the Prep branches that call checkSession
ReqTypes    == CheckTypes \cup {"createSession"}

\* Client connection states (one handle at a time, brief 3.2)
\*   "Init"     session not created yet
\*   "Creating" createSession submitted, waiting for its completion
\*   "Disc"     no live connection
\*   "Sent"     ConnectRequest (reopen) written to srv's socket, not yet read
\*   "Read"     follower srv read it and sent REVALIDATE; waiting for the reply
\*   "Conn"     connected to srv
ClientStates == {"Init", "Creating", "Disc", "Sent", "Read", "Conn"}

VARIABLES
    \* --- leader SessionTrackerImpl (S1, S2) ---
    sessionAlive,  \* sessionsById.get(sid) != null            SessionTrackerImpl.java:239-242
    owner,         \* SessionImpl.owner                        SessionTrackerImpl.java:65
    \* --- leader Prep queue (S1, S2) ---
    prepQueue,     \* PrepRequestProcessor.submittedRequests: seq of [type, owner]   PRP L100-114
    \* --- learner links (S1, S2) ---
    link,          \* [Followers -> Seq(packet)] follower->leader TCP stream, one LearnerHandler reader
    revalReplies,  \* [Followers -> Nat] REVALIDATE replies queued leader->follower (LearnerHandler L420-422)
    pendingReval,  \* [Followers -> Nat] Learner.pendingRevalidations.get(sid): attempt id, 0 = absent (Learner.java:75, 103)
    \* --- server socket inboxes (S2) ---
    inbox,         \* [Server -> SUBSET Nat] reopen ConnectRequests written but not yet read by srv's selector
    \* --- client environment (S1, S2) ---
    client,        \* [st, srv, att]
    opPending,     \* a synchronous op is outstanding (workload: every op is synchronous)
    pingPending,   \* a ping submitted at the leader is not yet processed
    \* --- provenance ghosts (OwnerProvenance) ---
    hSent,         \* followers whose LearnerHandler ever stamped / revalidated the session
    meUsed,        \* the leader ever set or stamped ServerCnxn.me
    \* --- target ---
    targetFired

trackerVars == <<sessionAlive, owner>>
linkVars    == <<link, revalReplies, pendingReval>>
clientVars  == <<inbox, client, opPending, pingPending>>
ghostVars   == <<hSent, meUsed>>
vars == <<trackerVars, prepQueue, linkVars, clientVars, ghostVars, targetFired>>

----------------------------------------------------------------------------
\* Helpers

ReqPkt(t)   == [kind |-> "REQUEST", type |-> t]       \* Leader.REQUEST, Learner.request L158-176
RevalPkt    == [kind |-> "REVALIDATE", type |-> "none"] \* Leader.REVALIDATE, Learner.validateSession L101-102
Packets     == {RevalPkt} \cup {ReqPkt(t) : t \in {"write", "sync", "createSession"}}

PrepEntry(t, o) == [type |-> t, owner |-> o]

\* NIOServerCnxn.readConnectRequest L745 factory.closeSessionWithoutWakeup(sid):
\* closes a connection on server s that already carries this session id
\* (NIOServerCnxn.java:334-350). The live client connection carries it once
\* srv read its ConnectRequest (setSessionId, L746): states "Read" and "Conn".
\* Connections the client already abandoned are taken as reaped by EOF; which
\* one is closed never changes the owner value (see brief-coverage.md).
ClosesLiveCnxn(s, a) ==
    /\ client.srv = s
    /\ client.st \in {"Read", "Conn"}
    /\ client.att # a

----------------------------------------------------------------------------
Init ==
    /\ sessionAlive = FALSE
    /\ owner = None
    /\ prepQueue = <<>>
    /\ link = [f \in Followers |-> <<>>]
    /\ revalReplies = [f \in Followers |-> 0]
    /\ pendingReval = [f \in Followers |-> 0]
    /\ inbox = [s \in Server |-> {}]
    /\ client = [st |-> "Init", srv |-> None, att |-> 0]
    /\ opPending = FALSE
    /\ pingPending = FALSE
    /\ hSent = {}
    /\ meUsed = FALSE
    /\ targetFired = FALSE

----------------------------------------------------------------------------
(***************************************************************************)
(* Client side                                                             *)
(***************************************************************************)

\* New session at server s: ClientCnxn.primeConnection with sessionId 0
\* (ClientCnxn.java:913-914) -> NIOServerCnxn.readConnectRequest new-session
\* branch (NIOServerCnxn.java:748-751) -> ZooKeeperServer.createSession
\* (ZooKeeperServer.java:496-506).
ClientCreateSession(s) ==
    /\ client.st = "Init"
    /\ IF s = Leader
       THEN \* Leader: SessionTrackerImpl.createSession adds the session now
            \* (SessionTrackerImpl.java:213-216, 218-236; owner stays null, L65),
            \* then submitRequest(cnxn, ..., createSession) builds a Request
            \* with owner null (ZooKeeperServer.java:504, 552-555) and touches
            \* it (L574) into Prep.
            /\ sessionAlive' = TRUE
            /\ prepQueue' = Append(prepQueue, PrepEntry("createSession", None))
            /\ UNCHANGED link
       ELSE \* Follower: LearnerSessionTracker.createSession only allocates the
            \* id (LearnerSessionTracker.java:75-77); FollowerRequestProcessor
            \* forwards createSession to the leader (FollowerRequestProcessor.java:84-86).
            /\ link' = [link EXCEPT ![s] = Append(@, ReqPkt("createSession"))]
            /\ UNCHANGED <<sessionAlive, prepQueue>>
    /\ client' = [st |-> "Creating", srv |-> s, att |-> 0]
    /\ UNCHANGED <<owner, revalReplies, pendingReval, inbox, opPending,
                   pingPending, ghostVars, targetFired>>

\* Client opens the existing session at server s: a new handle with the same
\* sessionId/passwd (workload), or ClientCnxn reconnect; primeConnection
\* writes a ConnectRequest carrying sessionId and passwd (ClientCnxn.java:907-950).
\* The brief (3.2) excludes moving with a request in flight: the client opens
\* only with nothing outstanding.
ClientOpen(s) ==
    /\ client.st = "Disc"
    /\ ~opPending
    /\ ~pingPending
    /\ LET a == client.att + 1 IN
       /\ client' = [st |-> "Sent", srv |-> s, att |-> a]
       /\ inbox' = [inbox EXCEPT ![s] = @ \cup {a}]
    /\ UNCHANGED <<trackerVars, prepQueue, linkVars, opPending, pingPending,
                   ghostVars, targetFired>>

\* Client gives up a pending handshake: SendThread.run while not CONNECTED,
\* to = connectTimeout - idleRecv (ClientCnxn.java:1042-1045) -> SessionTimeoutException
\* (L1046-1051) -> cleanup() closes the socket (L1159-1212). Nothing retracts
\* the ConnectRequest already in the server's socket, the follower's
\* pendingRevalidations entry, or a REVALIDATE already on the learner link.
\* Fault action (Scenario 2), bounded in MC.
ClientAbandonOpen ==
    /\ client.st \in {"Sent", "Read"}
    /\ client' = [client EXCEPT !.st = "Disc"]
    /\ UNCHANGED <<trackerVars, prepQueue, linkVars, inbox, opPending,
                   pingPending, ghostVars, targetFired>>

\* Workload: DisconnectableZooKeeper.disconnect() closes the socket without a
\* closeSession (test/test/DisconnectableZooKeeper.java). Every workload op is
\* synchronous, so nothing is outstanding.
ClientDisconnect ==
    /\ client.st = "Conn"
    /\ ~opPending
    /\ ~pingPending
    /\ client' = [client EXCEPT !.st = "Disc"]
    /\ UNCHANGED <<trackerVars, prepQueue, linkVars, inbox, opPending,
                   pingPending, ghostVars, targetFired>>

\* An op from a client connected to the leader:
\* NIOServerCnxn.readRequest builds Request(this, ...) and setOwner(ServerCnxn.me)
\* (NIOServerCnxn.java:664-666); ZooKeeperServer.submitRequest touches and
\* queues it to Prep (ZooKeeperServer.java:558-590).
\* t \in {"write", "read", "sync"}: a synchronous op; t = "ping": SendThread.sendPing
\* (ClientCnxn.java:961-965), not awaited by the workload.
ClientSubmitLeader(t) ==
    /\ client.st = "Conn"
    /\ client.srv = Leader
    /\ t \in CheckTypes
    /\ IF t = "ping"
       THEN /\ ~pingPending
            /\ pingPending' = TRUE
            /\ UNCHANGED opPending
       ELSE /\ ~opPending
            /\ opPending' = TRUE
            /\ UNCHANGED pingPending
    /\ prepQueue' = Append(prepQueue, PrepEntry(t, Me))
    /\ meUsed' = TRUE
    /\ UNCHANGED <<trackerVars, linkVars, inbox, client, hSent, targetFired>>

\* An op from a client connected to follower f that the follower forwards:
\* NIOServerCnxn.readRequest (owner is irrelevant on a follower, LearnerSessionTracker
\* L79-85) -> FollowerRequestProcessor.run ships write ops and sync to the
\* leader (FollowerRequestProcessor.java:75-87). Reads and pings on a follower
\* are served locally and never reach the leader's tracker: not modelled.
ClientSubmitFollower(f, t) ==
    /\ client.st = "Conn"
    /\ client.srv = f
    /\ f \in Followers
    /\ t \in {"write", "sync"}
    /\ ~opPending
    /\ opPending' = TRUE
    /\ link' = [link EXCEPT ![f] = Append(@, ReqPkt(t))]  \* Learner.request L158-176
    /\ UNCHANGED <<trackerVars, prepQueue, revalReplies, pendingReval, inbox,
                   client, pingPending, ghostVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Server side: session reopen                                             *)
(***************************************************************************)

\* Follower f's selector reads reopen ConnectRequest of attempt a:
\* NIOServerCnxn.readConnectRequest (NIOServerCnxn.java:701-754), reopen branch:
\*   L745 closeSessionWithoutWakeup(sid); L746 setSessionId;
\*   L747 zk.reopenSession -> ZooKeeperServer.reopenSession (ZooKeeperServer.java:529-536):
\*     checkPasswd holds (the client always sends the right passwd) ->
\*     LearnerZooKeeperServer.revalidateSession (LearnerZooKeeperServer.java:79-82) ->
\*     Learner.validateSession (Learner.java:93-111):
\*       L103 pendingRevalidations.put(sid, cnxn)   (overwrites any earlier entry)
\*       L110 writePacket(REVALIDATE)
FollowerReadConnect(f, a) ==
    /\ f \in Followers
    /\ a \in inbox[f]
    /\ inbox' = [inbox EXCEPT ![f] = @ \ {a}]
    /\ pendingReval' = [pendingReval EXCEPT ![f] = a]
    /\ link' = [link EXCEPT ![f] = Append(@, RevalPkt)]
    /\ client' =
         IF client.att = a /\ client.st = "Sent" /\ client.srv = f
         THEN [client EXCEPT !.st = "Read"]        \* this is the live attempt
         ELSE IF ClosesLiveCnxn(f, a)
              THEN [client EXCEPT !.st = "Disc"]   \* L745 closes the live cnxn
              ELSE client                          \* stale attempt; client elsewhere
    /\ UNCHANGED <<trackerVars, prepQueue, revalReplies, opPending, pingPending,
                   ghostVars, targetFired>>

\* Leader's selector reads reopen ConnectRequest of attempt a. One selector
\* step, atomic w.r.t. the tracker owner:
\*   NIOServerCnxn.readConnectRequest L745 closeSessionWithoutWakeup, L746-747 reopenSession
\*   -> ZooKeeperServer.reopenSession L531-534 (passwd ok)
\*   -> LeaderZooKeeperServer.revalidateSession (LeaderZooKeeperServer.java:165-175):
\*        L167 super.revalidateSession: touchSession (ZooKeeperServer.java:520),
\*             cnxn.finishSessionInit(rc) (L526)
\*        L171 setOwner(sid, ServerCnxn.me)  -- unconditional
LeaderReadConnect(a) ==
    /\ a \in inbox[Leader]
    /\ inbox' = [inbox EXCEPT ![Leader] = @ \ {a}]
    /\ LET rc == sessionAlive IN                  \* touchSession, SessionTrackerImpl.java:161-171
       /\ client' =
            IF client.att = a /\ client.st = "Sent" /\ client.srv = Leader
            THEN IF rc THEN [client EXCEPT !.st = "Conn"]   \* finishSessionInit(true), live attempt
                       ELSE [client EXCEPT !.st = "Disc"]   \* finishSessionInit(false) -> close
            ELSE IF ClosesLiveCnxn(Leader, a)
                 THEN [client EXCEPT !.st = "Disc"]          \* L745 closes the live cnxn
                 ELSE client
       \* setOwner throws SessionExpiredException if the session is gone
       \* (SessionTrackerImpl.java:251-254), caught at LZKS L172-174.
       /\ owner' = IF rc THEN Me ELSE owner                  \* SessionTrackerImpl.java:255
       /\ meUsed' = (meUsed \/ rc)
    /\ UNCHANGED <<sessionAlive, prepQueue, linkVars, opPending, pingPending,
                   hSent, targetFired>>

\* LearnerHandler of f reads REVALIDATE (LearnerHandler.java:395-423):
\*   L403 valid = leader.zk.touch(id, to)  (LeaderZooKeeperServer.java:87-88)
\*   L404-409 if valid: leader.zk.setOwner(id, this)  -- unconditional, no fencing
\*   L420-422 reply queued to f
LeaderRecvRevalidate(f) ==
    /\ f \in Followers
    /\ link[f] # <<>>
    /\ Head(link[f]).kind = "REVALIDATE"
    /\ link' = [link EXCEPT ![f] = Tail(@)]
    /\ LET valid == sessionAlive IN
       /\ owner' = IF valid THEN f ELSE owner
       /\ hSent' = IF valid THEN hSent \cup {f} ELSE hSent
    /\ revalReplies' = [revalReplies EXCEPT ![f] = @ + 1]
    /\ UNCHANGED <<sessionAlive, prepQueue, pendingReval, clientVars, meUsed,
                   targetFired>>

\* Follower f processes the REVALIDATE reply: Follower.processPacket L131-133
\* -> Learner.revalidate (Learner.java:322-345):
\*   L329-330 cnxn = pendingRevalidations.remove(sid)
\*   L331-334 null -> warn only
\*   L336     cnxn.finishSessionInit(valid): the client connects only if that
\*            cnxn is its live attempt (a closed one just drops the reply)
FollowerRevalidate(f) ==
    /\ f \in Followers
    /\ revalReplies[f] > 0
    /\ revalReplies' = [revalReplies EXCEPT ![f] = @ - 1]
    /\ pendingReval' = [pendingReval EXCEPT ![f] = 0]
    /\ LET a == pendingReval[f] IN
       client' =
         IF a # 0 /\ client.att = a /\ client.st = "Read" /\ client.srv = f
         THEN IF sessionAlive                         \* valid flag of the reply
              THEN [client EXCEPT !.st = "Conn"]
              ELSE [client EXCEPT !.st = "Disc"]
         ELSE client
    /\ UNCHANGED <<trackerVars, prepQueue, link, inbox, opPending, pingPending,
                   ghostVars, targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Server side: request forwarding                                         *)
(***************************************************************************)

\* LearnerHandler of f reads a forwarded REQUEST (LearnerHandler.java:424-438):
\*   L430-432 sync: new LearnerSyncRequest(this, ...) whose super(null, ...)
\*            leaves Request.owner null (LearnerSyncRequest.java:29-33,
\*            server/Request.java:79) -- no setOwner
\*   L433-436 otherwise: Request(null, ...); si.setOwner(this); submitRequest
\*   submitRequest: touch(si.cnxn) returns at once for cnxn == null
\*   (ZooKeeperServer.java:328-331, 574), then Prep (L577).
LeaderRecvRequest(f) ==
    /\ f \in Followers
    /\ link[f] # <<>>
    /\ Head(link[f]).kind = "REQUEST"
    /\ LET t == Head(link[f]).type IN
       /\ prepQueue' = Append(prepQueue,
                              IF t = "sync" THEN PrepEntry(t, None)    \* L430-432
                                            ELSE PrepEntry(t, f))      \* L434-436
       /\ hSent' = IF t = "sync" THEN hSent ELSE hSent \cup {f}
    /\ link' = [link EXCEPT ![f] = Tail(@)]
    /\ UNCHANGED <<trackerVars, revalReplies, pendingReval, clientVars, meUsed,
                   targetFired>>

----------------------------------------------------------------------------
(***************************************************************************)
(* Leader PrepRequestProcessor (single thread, PRP L100-114)               *)
(***************************************************************************)

\* pRequest createSession branch (PrepRequestProcessor.java:352-361):
\*   L359 sessionTracker.addSession(sid, to)   (adds it if absent, SessionTrackerImpl.java:218-236)
\*   L360 zks.setOwner(sid, request.getOwner()) -- handler f for a follower-created
\*        session, null for a leader-created one (ZooKeeperServer.java:554)
\* The creating client's connection completes after commit (FinalRequestProcessor);
\* the data path does not touch the owner, so completion is folded into this step.
PrepCreateSession ==
    /\ prepQueue # <<>>
    /\ Head(prepQueue).type = "createSession"
    /\ prepQueue' = Tail(prepQueue)
    /\ sessionAlive' = TRUE
    /\ owner' = Head(prepQueue).owner
    /\ client' = IF client.st = "Creating"
                 THEN [client EXCEPT !.st = "Conn"]
                 ELSE client
    /\ UNCHANGED <<linkVars, inbox, opPending, pingPending, ghostVars, targetFired>>

\* The target. pRequest for every opcode that calls checkSession:
\*   create L209-212, delete L271-274, setData L305-308, setACL L327-330,
\*   sync/exists/getData/getACL/getChildren/getChildren2/ping/setWatches L388-397:
\*     zks.sessionTracker.checkSession(request.sessionId, request.getOwner())
\* SessionTrackerImpl.checkSession (SessionTrackerImpl.java:238-248):
\*   L239-242 session == null -> SessionExpiredException (not the target)
\*   L243-244 session.owner == null -> session.owner = owner (claim)
\*   L245-246 session.owner != owner -> throw SessionMovedException   <== TARGET
\* Prep catches KeeperException (PRP L400-409) and passes the request on
\* (L435); the client's op completes (with an error, or masked for a learner
\* sync, ProposalRequestProcessor.java:65-66). Completion folded in as above.
TargetCheck ==
    /\ prepQueue # <<>>
    /\ Head(prepQueue).type \in CheckTypes
    /\ LET r == Head(prepQueue) IN
       /\ prepQueue' = Tail(prepQueue)
       /\ IF ~sessionAlive
          THEN \* L240-241 SessionExpiredException
               /\ UNCHANGED <<owner, targetFired>>
          ELSE IF owner = None
          THEN \* L243-244 claim
               /\ owner' = r.owner
               /\ UNCHANGED targetFired
          ELSE IF owner # r.owner
          THEN \* L245-246 throw new KeeperException.SessionMovedException()
               /\ targetFired' = TRUE
               /\ UNCHANGED owner
          ELSE /\ UNCHANGED <<owner, targetFired>>
       /\ IF r.type = "ping"
          THEN /\ pingPending' = FALSE
               /\ UNCHANGED opPending
          ELSE /\ opPending' = FALSE
               /\ UNCHANGED pingPending
    /\ UNCHANGED <<sessionAlive, linkVars, inbox, client, ghostVars>>

----------------------------------------------------------------------------
Next ==
    /\ ~targetFired
    /\ \/ \E s \in Server : ClientCreateSession(s)
       \/ \E s \in Server : ClientOpen(s)
       \/ ClientAbandonOpen
       \/ ClientDisconnect
       \/ \E t \in CheckTypes : ClientSubmitLeader(t)
       \/ \E f \in Followers, t \in {"write", "sync"} : ClientSubmitFollower(f, t)
       \/ \E f \in Followers : \E a \in inbox[f] : FollowerReadConnect(f, a)
       \/ \E a \in inbox[Leader] : LeaderReadConnect(a)
       \/ \E f \in Followers : LeaderRecvRevalidate(f)
       \/ \E f \in Followers : FollowerRevalidate(f)
       \/ \E f \in Followers : LeaderRecvRequest(f)
       \/ PrepCreateSession
       \/ TargetCheck

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The target never fails (adhoc-coordination Shared Rule 1).
TargetSafe == ~targetFired

TypeOK ==
    /\ sessionAlive \in BOOLEAN
    /\ owner \in Owners
    /\ prepQueue \in Seq([type : ReqTypes, owner : Owners])
    /\ link \in [Followers -> Seq(Packets)]
    /\ revalReplies \in [Followers -> Nat]
    /\ pendingReval \in [Followers -> Nat]
    /\ inbox \in [Server -> SUBSET Nat]
    /\ client.st \in ClientStates
    /\ client.srv \in Server \cup {None}
    /\ client.att \in Nat
    /\ opPending \in BOOLEAN
    /\ pingPending \in BOOLEAN
    /\ hSent \subseteq Followers
    /\ meUsed \in BOOLEAN
    /\ targetFired \in BOOLEAN

\* A value reaches the owner, or a Prep entry, only from the code path that
\* holds it: f only via f's LearnerHandler (L409, L435), Me only via the
\* leader's own connections (NIOServerCnxn L665, LZKS L171).
OwnerProvenance ==
    LET Allowed == {None} \cup hSent \cup (IF meUsed THEN {Me} ELSE {})
    IN /\ owner \in Allowed
       /\ \A i \in 1..Len(prepQueue) : prepQueue[i].owner \in Allowed

\* Temporary sanity probe (tla-patterns.md 2): violated iff TargetCheck is enabled.
TargetReached ==
    ~(prepQueue # <<>> /\ Head(prepQueue).type \in CheckTypes)

\* State constraint for base.cfg only (base Spec is otherwise unbounded in
\* reopens and ops); MC.tla bounds those with counters instead.
BaseConstraint ==
    /\ client.att <= 2
    /\ Len(prepQueue) <= 2
    /\ \A f \in Followers : Len(link[f]) <= 2

=============================================================================
