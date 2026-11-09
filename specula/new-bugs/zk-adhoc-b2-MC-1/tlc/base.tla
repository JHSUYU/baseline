-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* zk-adhoc-b2 -- Apache ZooKeeper @ 1312ae0187 (standalone server, Java   *)
(* client, zookeeper-recipes-election LeaderElectionSupport).              *)
(*                                                                         *)
(* Ad hoc target (adhoc-coordination skill):                               *)
(*   FinalRequestProcessor.handleGetDataRequest, FRP:669-680               *)
(*     DataNode n = zks.getZKDatabase().getNode(path);   // FRP:672        *)
(*     if (n == null) {                                  // FRP:673        *)
(*         throw new KeeperException.NoNodeException();  // FRP:674 TARGET*)
(*   phi_T: the SyncThread executes FRP:672-673 for a getData request      *)
(*   (FRP:398-403) whose path is not a key of DataTree.nodes               *)
(*   (getNode = nodes.get, DT:215-217 -> NHM:62-64).                       *)
(*   TargetSafe == ~targetFired.                                           *)
(*                                                                         *)
(* Workload: LeaderElectionSupportTest#testNodes3 -- three LES instances,  *)
(* one worker thread each, all on ONE shared ZooKeeper handle/session      *)
(* (LEST:52-58, 79-94, 229-267); each runs start(); sleep(3000); stop().   *)
(*                                                                         *)
(* Category A (distributed / message-passing): the guard operand (path)    *)
(* comes from an earlier server reply (getChildren, LES:199) and the       *)
(* failure depends on how requests of several client threads/sessions are  *)
(* ordered at a server that serializes them (modeling-brief.md section 1). *)
(*                                                                         *)
(* Path abbreviations (relative to the pinned source tree):                *)
(*  FRP  zookeeper-server/.../server/FinalRequestProcessor.java            *)
(*  PRP  .../server/PrepRequestProcessor.java                              *)
(*  SRP  .../server/SyncRequestProcessor.java                              *)
(*  ZKS  .../server/ZooKeeperServer.java                                   *)
(*  DT   .../server/DataTree.java       NHM .../server/NodeHashMapImpl.java*)
(*  DN   .../server/DataNode.java                                          *)
(*  STI  .../server/SessionTrackerImpl.java                                *)
(*  NSC  .../server/NIOServerCnxn.java  WM  .../server/watch/WatchManager  *)
(*  ZK   zookeeper-server/.../ZooKeeper.java   CC .../ClientCnxn.java      *)
(*  ZKWM .../ZKWatchManager.java                                           *)
(*  LES  zookeeper-recipes/zookeeper-recipes-election/.../leader/          *)
(*       LeaderElectionSupport.java                                        *)
(*  LO   .../leader/LeaderOffer.java                                       *)
(*  LEST .../leader/LeaderElectionSupportTest.java (workload)              *)
(*                                                                         *)
(* Modeling decisions (modeling-brief.md section 3):                       *)
(*  M1 Server: one atomic step per request = the FRP step on the single    *)
(*     SyncThread (SRP:181-246; PRP:134-160, 769). Requests of one         *)
(*     connection keep their send order; connections interleave (O1/O2).   *)
(*     Throttler/Prep/Sync are order-preserving single-threaded stages and *)
(*     are collapsed into that step.                                       *)
(*  M2 Client channel: reqQ[s] is the handle's outgoingQueue + wire +      *)
(*     server pipeline, FIFO (CC:1665-1676). Server->client delivery (the  *)
(*     SendThread, CC:889-968) is FIFO and only (a) wakes the blocked      *)
(*     caller (CC:773-777), (b) registers an exists watch on its reply     *)
(*     (CC:746-750, ZK:315-325), (c) materializes one-shot watchers and    *)
(*     queues them for the EventThread (CC:910-919, 516-531). All three    *)
(*     are applied at the server step that produced the message: because  *)
(*     delivery is FIFO and none of (a)-(c) is observed before the woken   *)
(*     thread or the EventThread acts, this preserves every ordering of    *)
(*     thread steps and server steps. The woken thread's continuation is   *)
(*     a SEPARATE step (rcv[t] holds the delivered reply), so threads of   *)
(*     one handle may continue in any order after their replies arrive.    *)
(*  M3 Threads: a worker W(p) per participant and one EventThread ET(s)    *)
(*     per handle. Each sync call: send (thread) / FRP step (server) /     *)
(*     continuation (thread). The EventThread's steps are split at every   *)
(*     instance-monitor step (LES:184-186 called at LES:329, 193, 232,     *)
(*     265) and at its unsynchronized reads/writes of `state` that race    *)
(*     with stop() (LES:148): those are the interleaving points of S2.     *)
(*     The worker holds the monitor for all of start() and stop()          *)
(*     (LES:119, 147), so its re-entrant getLeaderOffer() calls and its    *)
(*     state writes inside start() are not observable and are merged.     *)
(*  M4 The offer tree: `offers` = keys of DataTree.nodes under the         *)
(*     election root (the guard operand); the root itself exists for the   *)
(*     whole workload (created in LEST:54-58, deleted in LEST:64 only      *)
(*     after the workers end).                                             *)
(*                                                                         *)
(* Scenarios (brief section 2): S1 peer withdrawal inside a listing window;*)
(* S2 self-withdrawal racing the own watcher-triggered re-determination;   *)
(* S3 peer session termination inside a listing window. The timing rules   *)
(* T1/T2 and the fault bound are applied in MC.tla; this module has every  *)
(* interleaving the code allows.                                           *)
(***************************************************************************)
EXTENDS Naturals, Integers, FiniteSets, Sequences, TLC

CONSTANTS
    Participants,   \* LES instances; one worker thread each (LEST:245-267)
    Sessions,       \* ZooKeeper handles = client sessions (one connection,
                    \* one SendThread, one EventThread each; CC:880-975, 507-582)
    SessionOf,      \* [Participants -> Sessions]: the handle each instance
                    \* uses (LES:424-426; LEST:232 -- all share one in testNodes3)
    NoP,            \* sentinel: no participant
    NoSession       \* sentinel: no ephemeral owner

ASSUME SessionOf \in [Participants -> Sessions]
ASSUME NoP \notin Participants /\ NoSession \notin Sessions

NoId == -1
\* Each instance calls start() once (LEST:253) and start() creates exactly one
\* offer (LES:136, 174-176): ids are the sequential suffixes 0..N-1 handed out
\* from the root's cversion (PRP:665-667, 681, 703).
Ids == 0..(Cardinality(Participants) - 1)

LesStates == {"START", "OFFER", "DETERMINE", "ELECTED", "READY", "FAILED", "STOP"} \* LES:461-469

W(p)  == [kind |-> "W",  id |-> p]
ET(s) == [kind |-> "ET", id |-> s]
Workers      == {W(p) : p \in Participants}
EventThreads == {ET(s) : s \in Sessions}
Threads      == Workers \cup EventThreads

\* Program counters.
\*  idle          before start() (LEST:251-253)
\*  w_create      start(): blocked in zooKeeper.create (LES:174)
\*  det_children  determineElectionStatus(): blocked in getChildren (LES:199)
\*  det_data      toLeaderOffers(): blocked in getData (LES:310)
\*  det_exists    becomeReady(): blocked in exists (LES:239)
\*  sleep         start() returned; Thread.sleep (LEST:254)
\*  w_stop        stop(): holds the monitor, wrote STOP (LES:147-148)
\*  w_delete      stop(): blocked in delete (LES:155)
\*  done          stop() returned (LEST:255-257)
\*  dead          the thread's session was closed/expired (fault S3)
\*  et_idle       EventThread waiting for an event (CC:562)
\*  et_state      process(): passed LES:329, before the read at LES:330
\*  et_det        process(): LES:330 true, before LES:190 (also the LES:256 re-entry)
\*  et_det_wait   LES:190 written, before getLeaderOffer() at LES:193
\*  et_det_mon    passed LES:193, before the getChildren send at LES:199
\*  et_leader_wait becomeLeader: LES:262 written, before getLeaderOffer() at LES:265
\*  et_ready_mon  becomeReady: passed getLeaderOffer() at LES:232, before LES:239
WorkerPCs == {"idle", "w_create", "det_children", "det_data", "det_exists",
              "sleep", "w_stop", "w_delete", "done", "dead"}
ETPCs     == {"et_idle", "et_state", "et_det", "et_det_wait", "et_det_mon",
              "det_children", "det_data", "et_leader_wait", "et_ready_mon",
              "det_exists", "dead"}

Ops == {"create", "getChildren", "getData", "exists", "delete"}
Req(op, t, p, x)      == [op |-> op, t |-> t, p |-> p, id |-> x]
Rep(op, err, x, kids) == [op |-> op, err |-> err, id |-> x, kids |-> kids]
NoReply == Rep("none", "none", NoId, {})

-----------------------------------------------------------------------------
(* Server state (standalone ZooKeeperServer; the SyncThread running FRP is  *)
(* the only DataTree writer and the only evaluator of FRP:672).             *)
VARIABLES
    offers,    \* SUBSET Ids: offer znodes in DataTree.nodes (guard operand; DT:105, 215-217)
    owner,     \* [Ids -> Sessions \cup {NoSession}]: ephemeralOwner (PRP:697-698; DT:490-495)
    nextSeq,   \* the root's cversion = next sequential suffix (PRP:665-667, 681, 703)
    srvW,      \* [Ids -> SUBSET Sessions]: server data watches set by exists (DT:708-711;
               \* WatchManager is keyed by path and connection, WM:140-176)
    alive      \* [Sessions -> BOOLEAN]: session not closing/closed (STI:308-325)

(* Session channels (M2). *)
VARIABLES
    reqQ,      \* [Sessions -> Seq(request)]: FIFO per handle (CC:1665-1676; O1/O2)
    rcv        \* [Threads -> reply]: reply delivered to the blocked caller (CC:934-968, 773-777)

(* Client watch table and EventThread (Scenarios S1-ii, S2, S3). *)
VARIABLES
    cliW,      \* [Sessions -> [Ids -> SUBSET Participants]]: ZKWatchManager dataWatches,
               \* one watcher object per LES instance (LES:239 passes `this`; ZK:315-325)
    etQ,       \* [Sessions -> Seq([id, ws])]: EventThread waitingEvents, one
               \* (watchers, NodeDeleted) pair per notification (CC:516-531)
    etP        \* [Sessions -> Participants \cup {NoP}]: instance whose process() runs (CC:589-591)

(* Recipe (LeaderElectionSupport) state and threads. *)
VARIABLES
    lstate,    \* [Participants -> LesStates]: LES.state (LES:95, 103; non-volatile)
    ownId,     \* [Participants -> Ids \cup {NoId}]: LES.leaderOffer's id (LES:99, 177, 197)
    pc,        \* [Threads -> program counter]
    listing,   \* [Threads -> SUBSET Ids]: children returned by getChildren (LES:199)
    toRead     \* [Threads -> SUBSET Ids]: listed children whose getData is not sent yet (LES:309)

(* Target and attribution history (brief section 3.1). *)
VARIABLES
    targetFired, \* FRP:673-674 failing branch taken
    firedBy,     \* who removed the missing id: "peerStop" | "selfStop" | "expiry"
    creator,     \* [Ids -> Participants \cup {NoP}]: whose create made the id (history)
    removedBy    \* [Ids -> {"none","delete","expire"}]: how the id left `offers` (history)

serverVars == <<offers, owner, nextSeq, srvW, alive>>
chanVars   == <<reqQ, rcv>>
watchVars  == <<cliW, etQ, etP>>
recipeVars == <<lstate, ownId, pc, listing, toRead>>
targetVars == <<targetFired, firedBy, creator, removedBy>>
vars == <<serverVars, chanVars, watchVars, recipeVars, targetVars>>

-----------------------------------------------------------------------------
(* Helpers *)

\* Instance on whose behalf thread t runs recipe code: the worker's own
\* instance, or the instance whose process() the EventThread is running.
PartOf(t) == IF t.kind = "W" THEN t.id ELSE etP[t.id]
\* Handle (session) thread t uses.
SessOf(t) == IF t.kind = "W" THEN SessionOf[t.id] ELSE t.id

\* The instance monitor is held by the worker for the whole of start() and
\* stop() (synchronized methods, LES:119, 147). The EventThread takes it only
\* inside getLeaderOffer() (LES:184-186), modeled as one atomic step.
HoldsMonitor(p) ==
    pc[W(p)] \in {"w_create", "det_children", "det_data", "det_exists",
                  "w_stop", "w_delete"}

MaxOf(S) == CHOOSE x \in S : \A y \in S : y <= x
MinOf(S) == CHOOSE x \in S : \A y \in S : x <= y

\* Thread t enqueues a sync request on its handle (CC:1553-1581 queuePacket +
\* wait; CC:1665-1676 FIFO append under the outgoingQueue lock).
Send(t, op, x) ==
    reqQ' = [reqQ EXCEPT ![SessOf(t)] = Append(@, Req(op, t, PartOf(t), x))]

Got(t, op) == rcv[t].op = op

\* The recipe call running on t returned:
\*  worker: determineElectionStatus returns into start() (LES:137), start()
\*          returns (LES:141) and releases the monitor (LES:119); sleep (LEST:254)
\*  EventThread: process() returns (LES:326-341); next watcher/event (CC:589-595)
FinishCall(t) ==
    /\ pc' = [pc EXCEPT ![t] = IF t.kind = "W" THEN "sleep" ELSE "et_idle"]
    /\ etP' = IF t.kind = "ET" THEN [etP EXCEPT ![t.id] = NoP] ELSE etP
    /\ listing' = [listing EXCEPT ![t] = {}]
    /\ toRead' = [toRead EXCEPT ![t] = {}]

\* NodeDeleted notifications produced by deleting the ids in `ord` (in this
\* order), as received by handle s2: one pair per id that s2 watched on the
\* server (DT:623 -> WM:140-193 -> NSC:709-737), with the client watchers
\* materialized and removed (one-shot) on arrival (CC:910-919, 516-531;
\* ZKWM:415-431). Pairs with no client watcher are no-ops and are omitted.
DeletedEvents(s2, ord) ==
    LET evs == [i \in 1..Len(ord) |->
                  [id |-> ord[i],
                   ws |-> IF s2 \in srvW[ord[i]] THEN cliW[s2][ord[i]] ELSE {}]]
    IN SelectSeq(evs, LAMBDA e : e.ws /= {})

\* All orders of a finite set (closeSession deletes a session's ephemerals in
\* the iteration order of its path list, DT:1157-1162: unspecified).
PermSeqs(S) ==
    {f \in [1..Cardinality(S) -> S] :
        \A i, j \in 1..Cardinality(S) : i /= j => f[i] /= f[j]}

-----------------------------------------------------------------------------
Init ==
    /\ offers = {}
    /\ owner = [x \in Ids |-> NoSession]
    /\ nextSeq = 0                             \* fresh root (LEST:54-58): cversion 0
    /\ srvW = [x \in Ids |-> {}]
    /\ alive = [s \in Sessions |-> TRUE]       \* handles created before the workers (LEST:52; CB createClient)
    /\ reqQ = [s \in Sessions |-> <<>>]
    /\ rcv = [t \in Threads |-> NoReply]
    /\ cliW = [s \in Sessions |-> [x \in Ids |-> {}]]
    /\ etQ = [s \in Sessions |-> <<>>]
    /\ etP = [s \in Sessions |-> NoP]
    /\ lstate = [p \in Participants |-> "STOP"]  \* LES:102-105 constructor
    /\ ownId = [p \in Participants |-> NoId]     \* LES:99 leaderOffer == null
    /\ pc = [t \in Threads |-> IF t.kind = "W" THEN "idle" ELSE "et_idle"]
    /\ listing = [t \in Threads |-> {}]
    /\ toRead = [t \in Threads |-> {}]
    /\ targetFired = FALSE
    /\ firedBy = "none"
    /\ creator = [x \in Ids |-> NoP]
    /\ removedBy = [x \in Ids |-> "none"]

-----------------------------------------------------------------------------
(***************************************************************************)
(* Worker thread W(p): start()                                             *)
(***************************************************************************)

\* LEST:251-253 -> LES:119-136 start() -> LES:165-176 makeOffer()
WStart(p) ==
    LET t == W(p) IN
    /\ pc[t] = "idle"
    \* LES:119 synchronized start(): the worker takes the monitor (HoldsMonitor)
    \* LES:120 state = START; LES:125-133 zooKeeper/hostName set (LEST:229-237)
    \* LES:136 -> LES:166 state = OFFER (overwrites START; not observable: monitor held)
    /\ lstate' = [lstate EXCEPT ![p] = "OFFER"]
    \* LES:171-176 synchronized(this) (re-entrant); zooKeeper.create(root + "/n_",
    \* hostname, OPEN_ACL_UNSAFE, EPHEMERAL_SEQUENTIAL) -> ZK:1424-1444
    /\ Send(t, "create", NoId)
    /\ pc' = [pc EXCEPT ![t] = "w_create"]
    /\ UNCHANGED <<serverVars, rcv, watchVars, ownId, listing, toRead, targetVars>>

\* Worker: determineElectionStatus() up to the getChildren send, entered
\*  (a) from start(): create returned (ZK:1445-1448), LES:174-177 leaderOffer
\*      = path, LES:137 determineElectionStatus();
\*  (b) from becomeReady(): exists returned null (ZK:1957-1960), LES:241,
\*      248-256 determineElectionStatus().
\* Inside start() the worker holds the monitor: LES:190 and the re-entrant
\* getLeaderOffer() at LES:193 are not observable before the send.
WDetStart(p) ==
    LET t == W(p) IN
    /\ \/ /\ pc[t] = "w_create"
          /\ Got(t, "create")
          /\ rcv[t].err = "OK"                            \* ZK:1445-1447 no throw
          /\ ownId' = [ownId EXCEPT ![p] = rcv[t].id]     \* LES:174-177
       \/ /\ pc[t] = "det_exists"
          /\ Got(t, "exists")
          /\ rcv[t].err = "NONODE"                        \* ZK:1957-1960 -> LES:241, 248-256
          /\ UNCHANGED ownId
    /\ lstate' = [lstate EXCEPT ![p] = "DETERMINE"]       \* LES:190
    \* LES:193-197 own id from the own path; LES:199 getChildren(root, false)
    \* -> ZK:2481-2482 -> ZK:2435-2457 (no watch)
    /\ Send(t, "getChildren", NoId)
    /\ rcv' = [rcv EXCEPT ![t] = NoReply]
    /\ pc' = [pc EXCEPT ![t] = "det_children"]
    /\ listing' = [listing EXCEPT ![t] = {}]
    /\ toRead' = [toRead EXCEPT ![t] = {}]
    /\ UNCHANGED <<serverVars, watchVars, targetVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Determination steps shared by the worker and the EventThread            *)
(* (determineElectionStatus LES:188-225, toLeaderOffers LES:300-324,       *)
(*  becomeLeader LES:261-268, becomeReady LES:227-259)                     *)
(***************************************************************************)

\* LES:300-315 toLeaderOffers: one getData(root + "/" + offer, false, null)
\* per listed child, in the iteration order of the returned list -- the
\* DataNode children HashSet (DN:104, 137; DT:734): unspecified, so the next
\* child is chosen nondeterministically. Consumes the getChildren reply (first
\* child) or the previous getData OK reply (ZK:2060-2067 no throw).
SendGetData(t, x) ==
    /\ \/ /\ pc[t] = "det_children"
          /\ Got(t, "getChildren")
          /\ x \in rcv[t].kids                                       \* LES:309
          /\ listing' = [listing EXCEPT ![t] = rcv[t].kids]          \* LES:199 result
          /\ toRead' = [toRead EXCEPT ![t] = rcv[t].kids \ {x}]
       \/ /\ pc[t] = "det_data"
          /\ Got(t, "getData")
          /\ rcv[t].err = "OK"                                       \* ZK:2061: no throw
          /\ x \in toRead[t]                                         \* LES:309 next child
          /\ toRead' = [toRead EXCEPT ![t] = toRead[t] \ {x}]
          /\ UNCHANGED listing
    /\ Send(t, "getData", x)                                         \* LES:310 -> ZK:2089-2090, 2043-2060
    /\ rcv' = [rcv EXCEPT ![t] = NoReply]
    /\ pc' = [pc EXCEPT ![t] = "det_data"]
    /\ UNCHANGED <<serverVars, watchVars, lstate, ownId, targetVars>>

\* Every listed child was read (or none was listed): LES:321 sort by id
\* (LO:80-88 ascending), LES:207-224 find the own id.
DetDecide(t) ==
    LET p    == PartOf(t)
        L    == IF pc[t] = "det_children" THEN rcv[t].kids ELSE listing[t]
        me   == ownId[p]
        prev == MaxOf({y \in L : y < me})
    IN
    /\ \/ /\ pc[t] = "det_children"
          /\ Got(t, "getChildren")
          /\ rcv[t].kids = {}                             \* LES:309 loop body never runs
       \/ /\ pc[t] = "det_data"
          /\ Got(t, "getData")
          /\ rcv[t].err = "OK"                            \* ZK:2061: no throw
          /\ toRead[t] = {}                               \* LES:309 loop done
    /\ rcv' = [rcv EXCEPT ![t] = NoReply]
    /\ CASE me \notin L ->
              \* LES:207-224: no listed offer has the own id; the loop ends and
              \* determineElectionStatus() returns without a decision
              /\ FinishCall(t)
              /\ UNCHANGED <<lstate, reqQ>>
         [] me = MinOf(L) ->
              \* LES:215-216 -> becomeLeader(): LES:262 state = ELECTED
              /\ lstate' = [lstate EXCEPT ![p] = "ELECTED"]
              /\ IF t.kind = "W"
                 THEN FinishCall(t)                       \* LES:265 re-entrant; start() returns
                 ELSE /\ pc' = [pc EXCEPT ![t] = "et_leader_wait"]  \* LES:265 still ahead
                      /\ UNCHANGED <<etP, listing, toRead>>
              /\ UNCHANGED reqQ
         [] OTHER ->
              \* LES:217-218 -> becomeReady(leaderOffers.get(i - 1)): the
              \* predecessor is the largest listed id below the own id
              IF t.kind = "W"
              THEN \* LES:230-233 getLeaderOffer() re-entrant;
                   \* LES:239 exists(prev, this) -> ZK:1939-1956
                   /\ Send(t, "exists", prev)
                   /\ pc' = [pc EXCEPT ![t] = "det_exists"]
                   /\ listing' = [listing EXCEPT ![t] = {}]
                   /\ UNCHANGED <<lstate, etP, toRead>>
              ELSE \* LES:230-233: getLeaderOffer() (a log argument) takes the monitor
                   /\ ~HoldsMonitor(p)
                   /\ pc' = [pc EXCEPT ![t] = "et_ready_mon"]
                   /\ UNCHANGED <<lstate, reqQ, etP, listing, toRead>>
    /\ UNCHANGED <<serverVars, cliW, etQ, ownId, targetVars>>

\* LES:239-247: exists returned a Stat -> READY. The client watch was
\* registered by the SendThread before the caller woke (CC:748-749;
\* ZK:322-325 -> dataWatches); see SrvExists.
RecvExistsOK(t) ==
    /\ pc[t] = "det_exists"
    /\ Got(t, "exists")
    /\ rcv[t].err = "OK"                                  \* LES:241 stat != null
    /\ lstate' = [lstate EXCEPT ![PartOf(t)] = "READY"]   \* LES:246
    /\ rcv' = [rcv EXCEPT ![t] = NoReply]
    /\ FinishCall(t)
    /\ UNCHANGED <<serverVars, reqQ, cliW, etQ, ownId, targetVars>>

\* getData replied NONODE (only produced by TargetCheck's failing branch):
\* ZK:2061-2062 throws NoNodeException; caught by start() (LES:138-139) or
\* process() (LES:336-337) -> becomeFailed(): LES:273 state = FAILED.
\* With the `~targetFired` gate of Next this step is not explored; it is kept
\* so that the continuation after the target is specified.
RecvDataNoNode(t) ==
    /\ pc[t] = "det_data"
    /\ Got(t, "getData")
    /\ rcv[t].err = "NONODE"
    /\ lstate' = [lstate EXCEPT ![PartOf(t)] = "FAILED"]  \* LES:270-275
    /\ rcv' = [rcv EXCEPT ![t] = NoReply]
    /\ FinishCall(t)
    /\ UNCHANGED <<serverVars, reqQ, cliW, etQ, ownId, targetVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* EventThread ET(s): watcher callbacks (S1-ii, S2, S3)                    *)
(***************************************************************************)

\* CC:558-566 take the next (watchers, event) pair; CC:584-595 call
\* watcher.process(event) for each materialized watcher, serially, in HashSet
\* order (nondeterministic p).
\* LES:326-329 process(): NodeDeleted (LES:328; the only event type the
\* recipe's exists watch delivers here); getLeaderOffer() is synchronized
\* (LES:184-186): blocked while the worker is in start()/stop(); then the event
\* path is compared with the own offer path (LES:329).
ETCheckOffer(s, p) ==
    LET t  == ET(s)
        ev == Head(etQ[s])
    IN
    /\ pc[t] = "et_idle"
    /\ etQ[s] /= <<>>
    /\ p \in ev.ws
    /\ ~HoldsMonitor(p)                                   \* LES:329 monitor
    /\ etQ' = [etQ EXCEPT ![s] =
                 IF ev.ws = {p} THEN Tail(etQ[s])
                 ELSE <<[ev EXCEPT !.ws = ev.ws \ {p}]>> \o Tail(etQ[s])]
    /\ IF ev.id /= ownId[p]                               \* LES:329 !path.equals(own path)
       THEN /\ pc' = [pc EXCEPT ![t] = "et_state"]
            /\ etP' = [etP EXCEPT ![s] = p]
       ELSE UNCHANGED <<pc, etP>>                         \* LES:329 false: process() returns
    /\ UNCHANGED <<serverVars, chanVars, cliW, lstate, ownId, listing, toRead, targetVars>>

\* LES:330 state != State.STOP: an unsynchronized read after the monitor step
\* of LES:329 -- stop() may have written STOP (LES:148) in between.
ETCheckState(s) ==
    LET t == ET(s)
        p == etP[s]
    IN
    /\ pc[t] = "et_state"
    /\ IF lstate[p] /= "STOP"                             \* LES:330
       THEN /\ pc' = [pc EXCEPT ![t] = "et_det"]          \* LES:331-335 determineElectionStatus()
            /\ UNCHANGED <<etP, listing, toRead>>
       ELSE FinishCall(t)                                 \* LES:330 false: process() returns
    /\ UNCHANGED <<serverVars, chanVars, cliW, etQ, lstate, ownId, targetVars>>

\* EventThread enters determineElectionStatus() -- from process() (LES:335) or
\* from becomeReady() when exists returned null (ZK:1957-1960; LES:241,
\* 248-256): LES:190 state = DETERMINE, an unsynchronized write that can
\* overwrite stop()'s STOP (LES:148).
ETDetBegin(s) ==
    LET t == ET(s)
        p == etP[s]
    IN
    /\ \/ pc[t] = "et_det"
       \/ /\ pc[t] = "det_exists"
          /\ Got(t, "exists")
          /\ rcv[t].err = "NONODE"                        \* LES:241, 248-256
    /\ lstate' = [lstate EXCEPT ![p] = "DETERMINE"]       \* LES:190
    /\ rcv' = [rcv EXCEPT ![t] = NoReply]
    /\ pc' = [pc EXCEPT ![t] = "et_det_wait"]
    /\ listing' = [listing EXCEPT ![t] = {}]
    /\ toRead' = [toRead EXCEPT ![t] = {}]
    /\ UNCHANGED <<serverVars, reqQ, watchVars, ownId, targetVars>>

\* LES:193 getLeaderOffer(): monitor step (waits while stop() runs).
ETDetMonitor(s) ==
    LET t == ET(s) IN
    /\ pc[t] = "et_det_wait"
    /\ ~HoldsMonitor(etP[s])                              \* LES:184-186, 193
    /\ pc' = [pc EXCEPT ![t] = "et_det_mon"]
    /\ UNCHANGED <<serverVars, chanVars, watchVars, lstate, ownId, listing, toRead, targetVars>>

\* LES:195-199: own id from the own path; getChildren(root, false).
ETDetSendChildren(s) ==
    LET t == ET(s) IN
    /\ pc[t] = "et_det_mon"
    /\ Send(t, "getChildren", NoId)                       \* LES:199 -> ZK:2481-2482 -> ZK:2435-2457
    /\ pc' = [pc EXCEPT ![t] = "det_children"]
    /\ UNCHANGED <<serverVars, rcv, watchVars, lstate, ownId, listing, toRead, targetVars>>

\* becomeLeader() on the EventThread: LES:265 getLeaderOffer() (log argument)
\* takes the monitor after the ELECTED write of LES:262 (DetDecide).
ETLeaderMonitor(s) ==
    LET t == ET(s) IN
    /\ pc[t] = "et_leader_wait"
    /\ ~HoldsMonitor(etP[s])                              \* LES:184-186, 265
    /\ FinishCall(t)                                      \* LES:267-268; process() returns
    /\ UNCHANGED <<serverVars, chanVars, cliW, etQ, lstate, ownId, targetVars>>

\* becomeReady() on the EventThread: LES:239 exists(prev, this) after the
\* monitor step of LES:232 (DetDecide). prev recomputed from the kept listing.
ETSendExists(s) ==
    LET t  == ET(s)
        me == ownId[etP[s]]
    IN
    /\ pc[t] = "et_ready_mon"
    /\ Send(t, "exists", MaxOf({y \in listing[t] : y < me}))   \* LES:218, 239
    /\ pc' = [pc EXCEPT ![t] = "det_exists"]
    /\ listing' = [listing EXCEPT ![t] = {}]
    /\ toRead' = [toRead EXCEPT ![t] = {}]
    /\ UNCHANGED <<serverVars, rcv, watchVars, lstate, ownId, targetVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Worker thread W(p): stop()                                              *)
(***************************************************************************)

\* LEST:254-255 sleep returned -> LES:147 synchronized stop() (the monitor is
\* free: the EventThread holds it only inside getLeaderOffer()) -> LES:148
\* state = STOP -- visible to the EventThread's unsynchronized read at LES:330
\* before the delete is sent.
WStopBegin(p) ==
    LET t == W(p) IN
    /\ pc[t] = "sleep"
    /\ lstate' = [lstate EXCEPT ![p] = "STOP"]            \* LES:148
    /\ pc' = [pc EXCEPT ![t] = "w_stop"]
    /\ UNCHANGED <<serverVars, chanVars, watchVars, ownId, listing, toRead, targetVars>>

\* LES:149-155: if (leaderOffer != null) zooKeeper.delete(path, -1).
WStopSendDelete(p) ==
    LET t == W(p) IN
    /\ pc[t] = "w_stop"
    /\ IF ownId[p] /= NoId                                \* LES:153
       THEN /\ Send(t, "delete", ownId[p])                \* LES:155 -> ZK:1683-1705
            /\ pc' = [pc EXCEPT ![t] = "w_delete"]
       ELSE /\ pc' = [pc EXCEPT ![t] = "done"]            \* LES:162-163; LEST:257
            /\ UNCHANGED reqQ
    /\ UNCHANGED <<serverVars, rcv, watchVars, lstate, ownId, listing, toRead, targetVars>>

\* LES:155-163: delete returned (LES:156) or threw (LES:157-158 becomeFailed,
\* LES:273); stop() returns and releases the monitor; LEST:257.
WStopDone(p) ==
    LET t == W(p) IN
    /\ pc[t] = "w_delete"
    /\ Got(t, "delete")
    /\ IF rcv[t].err = "OK"                               \* ZK:1706: no throw
       THEN UNCHANGED lstate
       ELSE lstate' = [lstate EXCEPT ![p] = "FAILED"]     \* LES:157-158 -> LES:270-275
    /\ rcv' = [rcv EXCEPT ![t] = NoReply]
    /\ pc' = [pc EXCEPT ![t] = "done"]
    /\ UNCHANGED <<serverVars, reqQ, watchVars, ownId, listing, toRead, targetVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Server: one FRP step per request, head of a live session's FIFO          *)
(* (FRP:147-214 on the SyncThread; per-connection order O1/O2).             *)
(* Reads pass Prep's checkSession (PRP:892-909) and carry no exception      *)
(* (FRP:194-200) only while the session is alive; throttling is off         *)
(* (FRP:158-160, 208-210; RT:84, ZKS:200-202).                              *)
(***************************************************************************)

SrvHead(s, op) ==
    /\ alive[s]
    /\ reqQ[s] /= <<>>
    /\ Head(reqQ[s]).op = op

\* create(root/n_, EPHEMERAL_SEQUENTIAL):
\*  PRP:636-715 -- validateCreateRequest/checkGlobalSession (PRP:658, 968-974);
\*  suffix = parent cversion (PRP:665-667); newCversion = cversion + 1
\*  (PRP:681, 703); ephemeralOwner = sessionId (PRP:697-698).
\*  FRP:111-112 applyRequest -> ZKS:1849-1863 -> DT:433-499 createNode:
\*  addChild (DT:480), nodes.put (DT:483), ephemerals (DT:490-495). The
\*  NodeCreated/NodeChildrenChanged triggers (DT:520-522) find no watch: the
\*  sequential path is fresh and the recipe never watches the root.
\*  Reply: FRP:303-309, 615-621 -> ZK:1444-1448.
SrvCreate(s) ==
    LET r  == Head(reqQ[s])
        id == nextSeq
    IN
    /\ SrvHead(s, "create")
    /\ id \in Ids
    /\ reqQ' = [reqQ EXCEPT ![s] = Tail(@)]
    /\ offers' = offers \cup {id}
    /\ owner' = [owner EXCEPT ![id] = s]
    /\ nextSeq' = nextSeq + 1
    /\ creator' = [creator EXCEPT ![id] = r.p]
    /\ rcv' = [rcv EXCEPT ![r.t] = Rep("create", "OK", id, {})]
    /\ UNCHANGED <<srvW, alive, watchVars, recipeVars, targetFired, firedBy, removedBy>>

\* getChildren(root, false): FRP:488-496 -> FRP:656-667 handleGetChildrenRequest:
\*  the root exists (M4), so FRP:659-662 does not throw; DT:724-748 returns a
\*  snapshot of the children; getWatch() == false (LES:199): no child watch.
SrvGetChildren(s) ==
    LET r == Head(reqQ[s]) IN
    /\ SrvHead(s, "getChildren")
    /\ reqQ' = [reqQ EXCEPT ![s] = Tail(@)]
    /\ rcv' = [rcv EXCEPT ![r.t] = Rep("getChildren", "OK", NoId, offers)]
    /\ UNCHANGED <<serverVars, watchVars, recipeVars, targetVars>>

\* Who removed the id a failing getData asked for (attribution only).
FiredByOf(r) ==
    IF removedBy[r.id] = "expire" THEN "expiry"
    ELSE IF creator[r.id] = r.p THEN "selfStop" ELSE "peerStop"

\* TARGET. getData(root/x, false, null): FRP:398-403 -> FRP:669-680
\* handleGetDataRequest:
\*   FRP:671 path = getDataRequest.getPath()
\*   FRP:672 n = zks.getZKDatabase().getNode(path)  (DT:215-217 -> NHM:62-64)
\*   FRP:673 if (n == null) FRP:674 throw new NoNodeException()
\*           -> FRP:604-605 err = NONODE -> FRP:615-621 reply
\*   else FRP:676-679 checkACL (OPEN_ACL_UNSAFE), DT:691-706 getData
\*        (watch == false, LES:310), reply.
TargetCheck(s) ==
    LET r == Head(reqQ[s]) IN
    /\ SrvHead(s, "getData")
    /\ reqQ' = [reqQ EXCEPT ![s] = Tail(@)]
    /\ IF r.id \notin offers                              \* FRP:672-673 n == null
       THEN /\ targetFired' = TRUE                        \* FRP:674 throw NoNodeException
            /\ firedBy' = FiredByOf(r)
            /\ rcv' = [rcv EXCEPT ![r.t] = Rep("getData", "NONODE", r.id, {})]  \* FRP:604-605, 615-621
       ELSE /\ UNCHANGED <<targetFired, firedBy>>
            /\ rcv' = [rcv EXCEPT ![r.t] = Rep("getData", "OK", r.id, {})]      \* FRP:676-679, 615-621
    /\ UNCHANGED <<serverVars, watchVars, recipeVars, creator, removedBy>>

\* exists(prev, watcher): FRP:375-396 -> DT:708-722 statNode(path, cnxn):
\*  the data watch is added before the existence check (DT:709-711); a missing
\*  node throws NoNode (DT:712-715 -> FRP:604-605) and ZK:1957-1960 returns null.
\*  Client side, ExistsWatchRegistration registers on the reply (CC:746-750;
\*  OK -> dataWatches, ZK:322-325). A watch registered on a missing path
\*  (DT:709-711; ZK:322-330 existWatches) could only fire on a re-create of the
\*  same sequential name, which never happens (cversion is monotonic,
\*  PRP:681, 703): not modeled (brief section 3.2).
SrvExists(s) ==
    LET r == Head(reqQ[s]) IN
    /\ SrvHead(s, "exists")
    /\ reqQ' = [reqQ EXCEPT ![s] = Tail(@)]
    /\ IF r.id \in offers                                 \* DT:712 n != null
       THEN /\ srvW' = [srvW EXCEPT ![r.id] = @ \cup {s}]                 \* DT:709-711; WM keyed by cnxn
            /\ cliW' = [cliW EXCEPT ![s][r.id] = @ \cup {r.p}]           \* CC:748-749; ZK:287-297, 322-325
            /\ rcv' = [rcv EXCEPT ![r.t] = Rep("exists", "OK", r.id, {})]   \* FRP:393-394, 615-621
       ELSE /\ UNCHANGED <<srvW, cliW>>
            /\ rcv' = [rcv EXCEPT ![r.t] = Rep("exists", "NONODE", r.id, {})] \* DT:713-714 -> FRP:604-605
    /\ UNCHANGED <<offers, owner, nextSeq, alive, etQ, etP, recipeVars, targetVars>>

\* delete(path, -1): PRP:352-376 -- checkSession (PRP:353); getRecordForPath
\*  throws NoNode for a missing node (PRP:359 -> PRP:914-927 error txn ->
\*  FRP:178-191); version -1 matches (PRP:360).
\*  FRP:111-112 -> DT:926-931 -> DT:534-627 deleteNode: removeChild (DT:548),
\*  nodes.remove (DT:563); dataWatches.triggerWatch(path, NodeDeleted)
\*  (DT:623) -> WM:140-193 removes the one-shot watches and NSC:709-737 queues
\*  the notification on each watching connection before this request's reply
\*  (FRP:615-621) [O4]. Reply: FRP:321-327.
SrvDelete(s) ==
    LET r == Head(reqQ[s])
        x == r.id
    IN
    /\ SrvHead(s, "delete")
    /\ reqQ' = [reqQ EXCEPT ![s] = Tail(@)]
    /\ IF x \in offers                                    \* PRP:359
       THEN /\ offers' = offers \ {x}                     \* DT:548, 563
            /\ removedBy' = [removedBy EXCEPT ![x] = "delete"]
            /\ etQ' = [s2 \in Sessions |-> etQ[s2] \o DeletedEvents(s2, <<x>>)]  \* DT:623; CC:910-919, 516-531
            /\ cliW' = [s2 \in Sessions |->
                          IF s2 \in srvW[x] THEN [cliW[s2] EXCEPT ![x] = {}]
                          ELSE cliW[s2]]                  \* ZKWM:415-431 one-shot
            /\ srvW' = [srvW EXCEPT ![x] = {}]            \* WM:159-167 one-shot
            /\ rcv' = [rcv EXCEPT ![r.t] = Rep("delete", "OK", x, {})]
       ELSE /\ rcv' = [rcv EXCEPT ![r.t] = Rep("delete", "NONODE", x, {})]
            /\ UNCHANGED <<offers, removedBy, etQ, cliW, srvW>>
    /\ UNCHANGED <<owner, nextSeq, alive, etP, recipeVars, targetFired, firedBy, creator>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Fault (Scenario S3): session expiry / close of handle s.                 *)
(* STI:158-171 (setSessionClosing, expire) -> ZKS:728-735 -> ZKS:702-705     *)
(* closeSession request with cnxn == null -> PRP:570-612 (the session's      *)
(* ephemerals; setSessionClosing) -> FRP:111-127 applyRequest + close of the  *)
(* connection -> ZKS:1893-1906 removeSession; DT:948-957 -> DT:1120-1182     *)
(* killSession/deleteNodes -> deleteNode per path (DT:534-627, watches as in  *)
(* SrvDelete), all in ONE FRP step. The closed connection's watches are      *)
(* removed (NSC:607-615 -> ZKS:332-333 -> DT:1482-1485).                     *)
(* Later requests of s never reach FRP:672: dropped by touch (STI:187-190 ->  *)
(* ZKS:753-763, 1262, 1276-1279) or rejected by checkSession (STI:316-318 ->  *)
(* PRP:908 -> FRP:194-200) [O7]; requests already past Prep run before the    *)
(* closeSession (O2) -- covered by interleaving SrvXxx(s) before this step.  *)
(* The handle's threads are dead for the rest of the run: their calls fail   *)
(* client-side and the recipe ignores session events (LES:328); nothing they *)
(* do afterwards reaches the server.                                         *)
(***************************************************************************)
ExpireSession(s) ==
    LET dels == {x \in offers : owner[x] = s} IN
    /\ alive[s]
    /\ alive' = [alive EXCEPT ![s] = FALSE]
    /\ offers' = offers \ dels                            \* DT:1130-1182
    /\ removedBy' = [x \in Ids |-> IF x \in dels THEN "expire" ELSE removedBy[x]]
    /\ \E ord \in PermSeqs(dels) :                        \* DT:1157-1162 path order unspecified
          etQ' = [s2 \in Sessions |->
                    IF s2 = s THEN <<>> ELSE etQ[s2] \o DeletedEvents(s2, ord)]
    /\ cliW' = [s2 \in Sessions |->
                  IF s2 = s THEN [x \in Ids |-> {}]
                  ELSE [x \in Ids |->
                          IF x \in dels /\ s2 \in srvW[x] THEN {} ELSE cliW[s2][x]]]
    /\ srvW' = [x \in Ids |-> IF x \in dels THEN {} ELSE srvW[x] \ {s}]  \* WM one-shot; DT:1482-1485
    /\ reqQ' = [reqQ EXCEPT ![s] = <<>>]                  \* O7
    /\ rcv' = [t \in Threads |-> IF SessOf(t) = s THEN NoReply ELSE rcv[t]]
    /\ pc' = [t \in Threads |-> IF SessOf(t) = s THEN "dead" ELSE pc[t]]
    /\ etP' = [etP EXCEPT ![s] = NoP]
    /\ listing' = [t \in Threads |-> IF SessOf(t) = s THEN {} ELSE listing[t]]
    /\ toRead' = [t \in Threads |-> IF SessOf(t) = s THEN {} ELSE toRead[t]]
    /\ UNCHANGED <<owner, nextSeq, lstate, ownId, targetFired, firedBy, creator>>

-----------------------------------------------------------------------------
(* The run is over: every worker returned from stop() (or died with its     *)
(* session), nothing is in flight, every live EventThread is idle.          *)
Quiescent ==
    /\ \A p \in Participants : pc[W(p)] \in {"done", "dead"}
    /\ \A s \in Sessions : reqQ[s] = <<>>
    /\ \A s \in Sessions : pc[ET(s)] \in {"et_idle", "dead"}
    /\ \A s \in Sessions : etQ[s] = <<>>

\* Deterministic / reactive steps (the MC layer passes them through).
ReactiveNext ==
    \/ \E p \in Participants :
          \/ WStart(p)
          \/ WDetStart(p)
          \/ WStopSendDelete(p)
          \/ WStopDone(p)
    \/ \E t \in Threads :
          \/ \E x \in Ids : SendGetData(t, x)
          \/ DetDecide(t)
          \/ RecvExistsOK(t)
          \/ RecvDataNoNode(t)
    \/ \E s \in Sessions :
          \/ ETCheckState(s)
          \/ ETDetBegin(s)
          \/ ETDetMonitor(s)
          \/ ETDetSendChildren(s)
          \/ ETLeaderMonitor(s)
          \/ ETSendExists(s)
          \/ SrvCreate(s)
          \/ SrvGetChildren(s)
          \/ TargetCheck(s)
          \/ SrvExists(s)
          \/ SrvDelete(s)

\* Once the target fired every other action stops (adhoc tla-patterns 1);
\* the terminal stutter keeps deadlock checking meaningful.
Next ==
    \/ /\ ~targetFired
       /\ \/ ReactiveNext
          \/ \E p \in Participants : WStopBegin(p)
          \/ \E s \in Sessions, p \in Participants : ETCheckOffer(s, p)
          \/ \E s \in Sessions : ExpireSession(s)
    \/ /\ targetFired \/ Quiescent
       /\ UNCHANGED vars

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties (brief section 5)                                            *)
(***************************************************************************)

\* The ad hoc check never fails.
TargetSafe == ~targetFired

\* Structural sanity 1: every id carried by a listing, a request, a reply, an
\* event or a watch was handed out by the server (a message carries only
\* values its sender held).
ListingFromServer ==
    LET Created == 0..(nextSeq - 1) IN
    /\ \A t \in Threads :
          /\ listing[t] \cup toRead[t] \subseteq Created
          /\ rcv[t].kids \subseteq Created
          /\ rcv[t].id /= NoId => rcv[t].id \in Created
    /\ \A s \in Sessions :
          /\ \A i \in 1..Len(reqQ[s]) : reqQ[s][i].id /= NoId => reqQ[s][i].id \in Created
          /\ \A i \in 1..Len(etQ[s]) : etQ[s][i].id \in Created
    /\ \A x \in Ids :
          (srvW[x] /= {} \/ \E s \in Sessions : cliW[s][x] /= {}) => x \in Created
    /\ \A p \in Participants : ownId[p] /= NoId => ownId[p] \in Created

\* Structural sanity 2: closeSession removes all of a session's ephemerals in
\* one step (DT:948-957), so no live offer belongs to a dead session.
NoDeadOwnerOffer ==
    \A x \in offers : owner[x] \in Sessions /\ alive[owner[x]]

TypeOK ==
    /\ offers \subseteq Ids
    /\ owner \in [Ids -> Sessions \cup {NoSession}]
    /\ nextSeq \in 0..Cardinality(Participants)
    /\ srvW \in [Ids -> SUBSET Sessions]
    /\ alive \in [Sessions -> BOOLEAN]
    /\ \A s \in Sessions : \A i \in 1..Len(reqQ[s]) :
          reqQ[s][i] \in [op : Ops, t : Threads, p : Participants, id : Ids \cup {NoId}]
    /\ \A t \in Threads :
          rcv[t] \in [op : Ops \cup {"none"}, err : {"none", "OK", "NONODE"},
                      id : Ids \cup {NoId}, kids : SUBSET Ids]
    /\ cliW \in [Sessions -> [Ids -> SUBSET Participants]]
    /\ \A s \in Sessions : \A i \in 1..Len(etQ[s]) :
          etQ[s][i] \in [id : Ids, ws : SUBSET Participants]
    /\ etP \in [Sessions -> Participants \cup {NoP}]
    /\ lstate \in [Participants -> LesStates]
    /\ ownId \in [Participants -> Ids \cup {NoId}]
    /\ \A t \in Threads : pc[t] \in (IF t.kind = "W" THEN WorkerPCs ELSE ETPCs)
    /\ listing \in [Threads -> SUBSET Ids]
    /\ toRead \in [Threads -> SUBSET Ids]
    /\ targetFired \in BOOLEAN
    /\ firedBy \in {"none", "peerStop", "selfStop", "expiry"}
    /\ creator \in [Ids -> Participants \cup {NoP}]
    /\ removedBy \in [Ids -> {"none", "delete", "expire"}]

\* Sanity probe (adhoc tla-patterns 2): TLC must VIOLATE this, i.e. a state
\* where TargetCheck is enabled is reachable.
TargetCheckEnabled(s) ==
    /\ alive[s]
    /\ reqQ[s] /= <<>>
    /\ Head(reqQ[s]).op = "getData"
TargetReached == ~(\E s \in Sessions : TargetCheckEnabled(s))

\* Sanity probe: the workload can run to completion (TLC must VIOLATE this).
NotQuiescent == ~Quiescent

=============================================================================
