------------------------------- MODULE base -------------------------------
(***************************************************************************)
(* HBase token-authentication master-key distribution, anchored at one     *)
(* ad hoc check (hbase-adhoc-k1):                                          *)
(*                                                                         *)
(*   AuthenticationTokenSecretManager.retrievePassword  ATSM:138-153       *)
(*     :145  masterKey = allKeys.get(identifier.getKeyId())                *)
(*     :146  if (masterKey == null)                                        *)
(*     :147    throw new InvalidToken("Unknown master key for token ...")  *)
(*                                                                         *)
(* Category A (distributed): every server keeps a replica `allKeys` of the *)
(* key set; one elected key master writes it to ZooKeeper; the other       *)
(* servers learn it through asynchronous one-shot ZK watches.  Inside one  *)
(* JVM three threads race (RPC handler, LeaderElector, ZK event thread),   *)
(* so the non-atomic windows the brief names are split (Category B layer). *)
(*                                                                         *)
(* Path prefixes (tree pinned at 92aa67fd15):                              *)
(*   ATSM = hbase-server/.../security/token/AuthenticationTokenSecretManager.java *)
(*   ZKSW = hbase-server/.../security/token/ZKSecretWatcher.java           *)
(*   ZKLM = hbase-client/.../zookeeper/ZKLeaderManager.java                *)
(*   ZKU  = hbase-client/.../zookeeper/ZKUtil.java                         *)
(*   ZKW  = hbase-client/.../zookeeper/ZooKeeperWatcher.java               *)
(*   RPCS = hbase-server/.../ipc/RpcServer.java                            *)
(*                                                                         *)
(* Time is discrete: one tick = KeyInterval-th of hbase.auth.key.update.   *)
(* interval.  Clock(n) = gtime + skew[n] stands for                        *)
(* EnvironmentEdgeManager.currentTime() on node n.                         *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Node,           \* servers (each runs an RpcServer + ATSM)
    None,           \* "no node" (model value)
    KeyInterval,    \* hbase.auth.key.update.interval, in ticks (RPCS:2190-2191)
    TokenLifetime,  \* hbase.auth.token.max.lifetime, in ticks (RPCS:2192-2193)
    MaxSkew,        \* bound of per-node clock skew (S2; ServerManager.java:216,389)
    Inf             \* stands for Long.MAX_VALUE (ATSM:252); larger than any clock

ASSUME /\ KeyInterval \in Nat \ {0}
       /\ TokenLifetime \in Nat \ {0}
       /\ MaxSkew \in Nat
       /\ Inf \in Nat
       /\ None \notin Node

(***************************************************************************)
(* Variables                                                               *)
(***************************************************************************)
VARIABLES
    \* --- clocks (S1, S2) ---
    gtime,          \* global time
    skew,           \* [Node -> -MaxSkew..MaxSkew], fixed per behavior (S2)
    \* --- process life cycle (S4, S5) ---
    alive,          \* process is running
    session,        \* ZK session valid (ephemeral znodes survive while TRUE)
    listening,      \* RpcServer listener started, accepts DIGEST (RPCS:2174)
    startPC,        \* step inside ZKSecretWatcher.start (ZKSW:57-67), S5
    startList,      \* children list read at ZKSW:63 / ZKU:749 before per-child getData
    \* --- guard operands and their writers (ATSM:66-77) ---
    allKeys,        \* [Node -> (KeyId -> Key)]  ATSM:73
    currentKey,     \* [Node -> Key \cup {NoKey}] ATSM:75 (not volatile)
    idSeq,          \* ATSM:77
    lastKeyUpdate,  \* ATSM:66
    \* --- leader election (ATSM:271-335, ZKLM) ---
    isMaster,       \* LeaderElector.isMaster ATSM:274
    epc,            \* elector thread PC: none/started/waiting/claimed/master
    leaderExists,   \* ZKLM.leaderExists flag
    stopped,        \* LeaderElector.stopped ATSM:272 (stop() also interrupts)
    \* --- leader loop / rollCurrentKey split (S1, S4, S6) ---
    lpc,            \* leader-loop PC
    loopNow,        \* `now` read at ATSM:316 (also used for :225)
    rollNow,        \* `now` read at ATSM:249
    rollPrev,       \* `prev` at ATSM:250
    \* --- token issuance split (S1) and the token pool ---
    cpPC,           \* createPassword PC per node (one RPC handler slot)
    cpNow,          \* `now` read at ATSM:128
    tokens,         \* tokens handed to clients
    \* --- ZooKeeper (linearizable store) ---
    zkKeys,         \* /hbase/tokenauth/keys/<id> -> Key
    zkLeader,       \* owner of ephemeral /hbase/tokenauth/keymaster, or None
    \* --- one-shot watches and per-client FIFO event queues (S3-S6) ---
    wChild,         \* children watch on keys parent armed (ZKU:453)
    wData,          \* key ids with a data watch armed (ZKU:671 via ZKU:754)
    wLeader,        \* watch on the leader znode armed (ZKU:362 / ZKU:671)
    evq,            \* ZK events not yet processed by the node's event thread
    \* --- the target ---
    targetFired,
    \* --- ghost (history) variables, used only by invariants / hunt filters ---
    published,      \* <<id, sec>> ever written to ZK
    everHeld,       \* per incarnation: key ids that were ever in allKeys[n]
    startFailed,    \* per incarnation: ATSM.start() swallowed a KeeperException
    minted          \* <<id, sec>> ever created by rollCurrentKey

clockVars == <<gtime, skew>>
lifeVars  == <<alive, session, listening, startPC, startList>>
keyVars   == <<allKeys, currentKey, idSeq, lastKeyUpdate>>
electVars == <<isMaster, epc, leaderExists, stopped>>
loopVars  == <<lpc, loopNow, rollNow, rollPrev>>
issueVars == <<cpPC, cpNow, tokens>>
zkVars    == <<zkKeys, zkLeader>>
watchVars == <<wChild, wData, wLeader, evq>>
ghostVars == <<published, everHeld, startFailed, minted>>

vars == <<clockVars, lifeVars, keyVars, electVars, loopVars, issueVars,
          zkVars, watchVars, targetFired, ghostVars>>

(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
\* AuthenticationKey (AuthenticationKey.java): id, expiration, secret.
\* The secret is abstracted to the node that generated it (ATSM:253).
NoKey == [id |-> 0, exp |-> 0, sec |-> None]
EmptyMap == [i \in {} |-> NoKey]

Put(f, k, v) == [x \in (DOMAIN f) \cup {k} |-> IF x = k THEN v ELSE f[x]]
Remove(f, S) == [x \in (DOMAIN f) \ S |-> f[x]]
Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y

Clock(n) == gtime + skew[n]          \* EnvironmentEdgeManager.currentTime()

\* lastKeyUpdate starts at 0 ms, i.e. far in the past: the first loop rolls.
Epoch0 == -(KeyInterval + MaxSkew + 1)

Ev(t, i) == [type |-> t, id |-> i]

\* Process is running and its ZK client can still receive events.
Live(m) == alive[m] /\ session[m]

\* The ATSM monitor is held by the leader thread inside the synchronized
\* removeExpiredKeys (ATSM:219) and rollCurrentKey (ATSM:243).  addKey and
\* removeKey (ATSM:171, :194) are synchronized too, so the ZK event thread
\* blocks on key events while it is held.
LockHeld(n) == lpc[n] \in {"removing", "rollInstall", "rollPublish", "rollUpdatePrev"}

RollDue(n, now) == lastKeyUpdate[n] + KeyInterval < now        \* ATSM:321

(***************************************************************************)
(* ZooKeeper writes and the watch events they fire.                        *)
(* ZK delivers each client's events in zxid order (one event thread,       *)
(* ZKW:538-582).  Watches are one-shot: firing clears them; handlers       *)
(* re-arm them when they re-read ZK.                                       *)
(***************************************************************************)
\* create of a key znode: NodeChildrenChanged to children watchers.
ZkCreate(k) ==
    LET W == {m \in Node : Live(m) /\ wChild[m]} IN
    /\ zkKeys' = Put(zkKeys, k.id, k)
    /\ evq'    = [m \in Node |-> IF m \in W THEN Append(evq[m], Ev("Children", 0)) ELSE evq[m]]
    /\ wChild' = [m \in Node |-> IF m \in W THEN FALSE ELSE wChild[m]]
    /\ UNCHANGED wData

\* setData of a key znode: NodeDataChanged to data watchers.
ZkSetData(k) ==
    LET W == {m \in Node : Live(m) /\ k.id \in wData[m]} IN
    /\ zkKeys' = Put(zkKeys, k.id, k)
    /\ evq'    = [m \in Node |-> IF m \in W THEN Append(evq[m], Ev("Data", k.id)) ELSE evq[m]]
    /\ wData'  = [m \in Node |-> IF m \in W THEN wData[m] \ {k.id} ELSE wData[m]]
    /\ UNCHANGED wChild

\* ZKUtil.createSetData ZKU:833-841: create if absent, else setData.
ZkCreateSetData(k) ==
    IF k.id \in DOMAIN zkKeys THEN ZkSetData(k) ELSE ZkCreate(k)

\* delete of a key znode: NodeDeleted to data watchers, then
\* NodeChildrenChanged to children watchers.
ZkDelete(i) ==
    LET WD == {m \in Node : Live(m) /\ i \in wData[m]}
        WC == {m \in Node : Live(m) /\ wChild[m]}
    IN
    /\ zkKeys' = Remove(zkKeys, {i})
    /\ evq' = [m \in Node |->
                 LET q1 == IF m \in WD THEN Append(evq[m], Ev("Deleted", i)) ELSE evq[m]
                 IN IF m \in WC THEN Append(q1, Ev("Children", 0)) ELSE q1]
    /\ wData'  = [m \in Node |-> IF m \in WD THEN wData[m] \ {i} ELSE wData[m]]
    /\ wChild' = [m \in Node |-> IF m \in WC THEN FALSE ELSE wChild[m]]

\* create / delete of the leader znode: NodeCreated / NodeDeleted to the
\* leader-znode watchers (other than `ex`).  Both reach handleLeaderChange.
ZkSetLeader(v, ex) ==
    LET W == {m \in Node \ ex : Live(m) /\ wLeader[m]} IN
    /\ zkLeader' = v
    /\ evq'    = [m \in Node |-> IF m \in W THEN Append(evq[m], Ev("Leader", 0)) ELSE evq[m]]
    /\ wLeader' = [m \in Node |-> IF m \in W THEN FALSE ELSE wLeader[m]]

(***************************************************************************)
(* addKey for a set S of znode ids read from ZK (ATSM:171-192), applied    *)
(* once per key in refreshNodes (ZKSW:138-157) or nodeDataChanged          *)
(* (ZKSW:108).  Uses zkKeys at handling time (handlers re-read ZK).        *)
(***************************************************************************)
AddKeys(n, S) ==
    IF isMaster[n] \/ S = {}
    THEN UNCHANGED <<allKeys, currentKey, idSeq, everHeld>>      \* ATSM:173-178
    ELSE LET mx == Max(S) IN
         /\ allKeys' = [allKeys EXCEPT ![n] =                    \* ATSM:184
                          [i \in (DOMAIN allKeys[n]) \cup S |->
                              IF i \in S THEN zkKeys[i] ELSE allKeys[n][i]]]
         /\ currentKey' = [currentKey EXCEPT ![n] =              \* ATSM:185-187
                          IF currentKey[n] = NoKey \/ mx > currentKey[n].id
                          THEN zkKeys[mx] ELSE currentKey[n]]
         /\ idSeq' = [idSeq EXCEPT ![n] =                        \* ATSM:189-191
                          IF mx > idSeq[n] THEN mx ELSE idSeq[n]]
         /\ everHeld' = [everHeld EXCEPT ![n] = @ \cup S]

(***************************************************************************)
(* Per-node reset: a fresh process (Restart) or a dead one (Die).          *)
(***************************************************************************)
ResetNode(n, isAlive, spc) ==
    /\ alive'        = [alive        EXCEPT ![n] = isAlive]
    /\ listening'    = [listening    EXCEPT ![n] = FALSE]
    /\ startPC'      = [startPC      EXCEPT ![n] = spc]
    /\ startList'    = [startList    EXCEPT ![n] = {}]
    /\ allKeys'      = [allKeys      EXCEPT ![n] = EmptyMap]
    /\ currentKey'   = [currentKey   EXCEPT ![n] = NoKey]
    /\ idSeq'        = [idSeq        EXCEPT ![n] = 0]
    /\ lastKeyUpdate' = [lastKeyUpdate EXCEPT ![n] = Epoch0]
    /\ isMaster'     = [isMaster     EXCEPT ![n] = FALSE]
    /\ epc'          = [epc          EXCEPT ![n] = "none"]
    /\ leaderExists' = [leaderExists EXCEPT ![n] = FALSE]
    /\ stopped'      = [stopped      EXCEPT ![n] = FALSE]
    /\ lpc'          = [lpc          EXCEPT ![n] = "none"]
    /\ loopNow'      = [loopNow      EXCEPT ![n] = 0]
    /\ rollNow'      = [rollNow      EXCEPT ![n] = 0]
    /\ rollPrev'     = [rollPrev     EXCEPT ![n] = NoKey]
    /\ cpPC'         = [cpPC         EXCEPT ![n] = "idle"]
    /\ cpNow'        = [cpNow        EXCEPT ![n] = 0]
    /\ wChild'       = [wChild       EXCEPT ![n] = FALSE]
    /\ wData'        = [wData        EXCEPT ![n] = {}]
    /\ wLeader'      = [wLeader      EXCEPT ![n] = FALSE]
    /\ evq'          = [evq          EXCEPT ![n] = <<>>]
    /\ everHeld'     = [everHeld     EXCEPT ![n] = {}]
    /\ startFailed'  = [startFailed  EXCEPT ![n] = FALSE]

\* Process death (crash, abort, exit).  Its ZK session survives until
\* SessionClose / session timeout.
Die(n) ==
    /\ ResetNode(n, FALSE, "dead")
    /\ UNCHANGED <<clockVars, session, tokens, zkVars, targetFired, published, minted>>

(***************************************************************************)
(* Initial state.  InitWith(L): nodes in L start their RpcServer;          *)
(* the others are absent (used by Trace.tla).  The keys parent znode is    *)
(* assumed to exist (ZKSW:60 then always hits NodeExists, ZKU:1205; the    *)
(* :62 FALSE branch is only reachable before any node finished :60, when   *)
(* there are no keys).                                                     *)
(***************************************************************************)
InitWith(L, sk) ==
    /\ gtime = 0
    /\ skew = sk
    /\ alive = [n \in Node |-> n \in L]
    /\ session = [n \in Node |-> n \in L]
    /\ listening = [n \in Node |-> FALSE]
    /\ startPC = [n \in Node |-> IF n \in L THEN "createParents" ELSE "dead"]
    /\ startList = [n \in Node |-> {}]
    /\ allKeys = [n \in Node |-> EmptyMap]
    /\ currentKey = [n \in Node |-> NoKey]
    /\ idSeq = [n \in Node |-> 0]
    /\ lastKeyUpdate = [n \in Node |-> Epoch0]
    /\ isMaster = [n \in Node |-> FALSE]
    /\ epc = [n \in Node |-> "none"]
    /\ leaderExists = [n \in Node |-> FALSE]
    /\ stopped = [n \in Node |-> FALSE]
    /\ lpc = [n \in Node |-> "none"]
    /\ loopNow = [n \in Node |-> 0]
    /\ rollNow = [n \in Node |-> 0]
    /\ rollPrev = [n \in Node |-> NoKey]
    /\ cpPC = [n \in Node |-> "idle"]
    /\ cpNow = [n \in Node |-> 0]
    /\ tokens = {}
    /\ zkKeys = EmptyMap
    /\ zkLeader = None
    /\ wChild = [n \in Node |-> FALSE]
    /\ wData = [n \in Node |-> {}]
    /\ wLeader = [n \in Node |-> FALSE]
    /\ evq = [n \in Node |-> <<>>]
    /\ targetFired = FALSE
    /\ published = {}
    /\ everHeld = [n \in Node |-> {}]
    /\ startFailed = [n \in Node |-> FALSE]
    /\ minted = {}

Init == \E sk \in [Node -> -MaxSkew..MaxSkew] : InitWith(Node, sk)

(***************************************************************************)
(* Time                                                                    *)
(***************************************************************************)
Tick ==
    /\ gtime' = gtime + 1
    /\ UNCHANGED <<skew, lifeVars, keyVars, electVars, loopVars, issueVars,
                   zkVars, watchVars, targetFired, ghostVars>>

(***************************************************************************)
(* Start-up: RpcServer.start (RPCS:2164-2177) -> ATSM.start (ATSM:103-112) *)
(*   -> ZKSecretWatcher.start (ZKSW:57-67) -> leaderElector.start (:108)   *)
(*   -> listener.start (RPCS:2174).                                        *)
(* Split at each ZK call so a ZK failure can hit any of them (S5).         *)
(***************************************************************************)
StartStepUnchanged ==
    UNCHANGED <<clockVars, alive, session, listening, keyVars, electVars, loopVars,
                issueVars, zkVars, targetFired, ghostVars>>

\* ZKSW:58 registerListener; ZKSW:60 createWithParents(keysParent) -> NodeExists.
StartCreateParents(n) ==
    /\ Live(n) /\ startPC[n] = "createParents"
    /\ startPC' = [startPC EXCEPT ![n] = "watchExists"]
    /\ UNCHANGED <<startList, watchVars>>
    /\ StartStepUnchanged

\* ZKSW:62 watchAndCheckExists(keysParent) -> TRUE (exists-watch on the parent;
\* the parent never changes, so that watch never fires).
StartWatchExists(n) ==
    /\ Live(n) /\ startPC[n] = "watchExists"
    /\ startPC' = [startPC EXCEPT ![n] = "listChildren"]
    /\ UNCHANGED <<startList, watchVars>>
    /\ StartStepUnchanged

\* ZKSW:63-64 -> ZKU:748-749 -> ZKU:453 getChildren(keysParent, watch).
StartListChildren(n) ==
    /\ Live(n) /\ startPC[n] = "listChildren"
    /\ wChild' = [wChild EXCEPT ![n] = TRUE]
    /\ startList' = [startList EXCEPT ![n] = DOMAIN zkKeys]
    /\ startPC' = [startPC EXCEPT ![n] = "readChildren"]
    /\ UNCHANGED <<wData, wLeader, evq>>
    /\ StartStepUnchanged

\* ZKU:752-757 per-child getDataAndWatch (NoNode -> null, skipped at
\* ZKSW:144-146), then ZKSW:65 refreshNodes -> addKey each (ZKSW:150),
\* then ATSM:108 leaderElector.start() and RPCS:2174 listener.start().
StartReadChildren(n) ==
    /\ Live(n) /\ startPC[n] = "readChildren"
    /\ LET S == startList[n] \cap DOMAIN zkKeys IN
       /\ wData' = [wData EXCEPT ![n] = @ \cup S]
       /\ AddKeys(n, S)
    /\ startPC' = [startPC EXCEPT ![n] = "done"]
    /\ epc' = [epc EXCEPT ![n] = "started"]
    /\ listening' = [listening EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<clockVars, alive, session, startList, lastKeyUpdate,
                   isMaster, leaderExists, stopped, loopVars, issueVars, zkVars,
                   wChild, wLeader, evq, targetFired, published, startFailed, minted>>

\* FAULT (S5): a ZK call in ZKSW.start throws KeeperException after the
\* RecoverableZooKeeper retries (RZK:273-283).  ATSM:109-111 logs and
\* swallows it: refreshNodes did not run, the LeaderElector is never
\* started (:108 skipped), yet RpcServer.start goes on to listener.start()
\* (RPCS:2169-2174).  Watches already armed stay armed.
StartZkFail(n) ==
    /\ Live(n)
    /\ startPC[n] \in {"createParents", "watchExists", "listChildren", "readChildren"}
    /\ startPC' = [startPC EXCEPT ![n] = "done"]
    /\ listening' = [listening EXCEPT ![n] = TRUE]
    /\ startFailed' = [startFailed EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<clockVars, alive, session, startList, keyVars, electVars,
                   loopVars, issueVars, zkVars, watchVars, targetFired,
                   published, everHeld, minted>>

(***************************************************************************)
(* Leader election: LeaderElector.run ATSM:310-313 -> ZKLeaderManager.     *)
(***************************************************************************)
\* ZKLM:59-70 start() (registerListener), then one iteration of
\* waitToBecomeLeader ZKLM:107-131.  Enabled at thread start or after
\* handleLeaderChange woke the waiter (ZKLM:139-147).
ElectorAttemptClaim(n) ==
    /\ Live(n) /\ ~stopped[n]                                    \* ZKLM:108
    /\ \/ epc[n] = "started"
       \/ epc[n] = "waiting" /\ ~leaderExists[n]                 \* ZKLM:140
    /\ zkLeader = None
    \* ZKLM:110 createEphemeralNodeAndWatch succeeds (ZKU:969-970): watchers of
    \* the leader znode get NodeCreated; ZKU:977 then re-arms our own watch.
    /\ LET W == {m \in Node : Live(m) /\ wLeader[m]} IN
       /\ zkLeader' = n
       /\ evq' = [m \in Node |-> IF m \in W THEN Append(evq[m], Ev("Leader", 0)) ELSE evq[m]]
       /\ wLeader' = [m \in Node |-> IF m = n THEN TRUE
                                     ELSE IF m \in W THEN FALSE ELSE wLeader[m]]
    /\ leaderExists' = [leaderExists EXCEPT ![n] = TRUE]         \* ZKLM:112
    /\ epc' = [epc EXCEPT ![n] = "claimed"]                      \* ZKLM:117 return
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, isMaster, stopped, loopVars,
                   issueVars, zkKeys, wChild, wData, targetFired, ghostVars>>

ElectorAttemptWait(n) ==
    /\ Live(n) /\ ~stopped[n]                                    \* ZKLM:108
    /\ \/ epc[n] = "started"
       \/ epc[n] = "waiting" /\ ~leaderExists[n]                 \* ZKLM:140
    /\ zkLeader # None
    \* ZKLM:121 getDataAndWatch(leaderZNode) arms a watch; the id is another
    \* server's (a restarted process has a new ServerName start code, so the
    \* "our ID" branch ZKLM:122-127 is not reachable), so ZKLM:129-130 sets
    \* leaderExists and the thread waits (ZKLM:139-147).
    /\ wLeader' = [wLeader EXCEPT ![n] = TRUE]
    /\ leaderExists' = [leaderExists EXCEPT ![n] = TRUE]         \* ZKLM:130
    /\ epc' = [epc EXCEPT ![n] = "waiting"]
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, isMaster, stopped, loopVars,
                   issueVars, zkVars, wChild, wData, evq, targetFired, ghostVars>>

\* ATSM:313 isMaster = true (also when stop() raced in, ATSM:305 vs :313),
\* then the leader loop starts (ATSM:315).
BecomeMaster(n) ==
    /\ alive[n] /\ epc[n] = "claimed"
    /\ isMaster' = [isMaster EXCEPT ![n] = TRUE]
    /\ epc' = [epc EXCEPT ![n] = "master"]
    /\ lpc' = [lpc EXCEPT ![n] = "loop"]
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, leaderExists, stopped, loopNow,
                   rollNow, rollPrev, issueVars, zkVars, watchVars, targetFired, ghostVars>>

(***************************************************************************)
(* Leader loop ATSM:315-333                                                *)
(***************************************************************************)
\* ATSM:315 while(!stopped); :316 now; :319 removeExpiredKeys() entry with
\* its isMaster check :220-223 (non-master skips straight to :321).
LeaderLoopTop(n) ==
    /\ alive[n] /\ lpc[n] = "loop"
    /\ IF stopped[n]
       THEN /\ lpc' = [lpc EXCEPT ![n] = "exited"]               \* ATSM:315 exit
            /\ UNCHANGED loopNow
       ELSE LET now == Clock(n) IN                               \* ATSM:316
            /\ loopNow' = [loopNow EXCEPT ![n] = now]
            /\ lpc' = [lpc EXCEPT ![n] =
                         IF isMaster[n] THEN "removing"          \* ATSM:219 lock
                         ELSE IF RollDue(n, now) THEN "rollStart" \* :220-222 skip, :321
                         ELSE "loop"]                            \* :327 sleep
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, electVars, rollNow, rollPrev,
                   issueVars, zkVars, watchVars, targetFired, ghostVars>>

\* removeExpiredKeys loop ATSM:225-236, one key per step (each key is a
\* separate ZK delete that other nodes can observe).  `now` (:225) is taken
\* equal to loopNow (:316): both are read back to back in the same tick.
\* No ZK call is made when nothing expired, so an expired-session master's
\* loop goes on to the roll check (:321).  With an expired session the
\* delete at :234 throws; ZKSW:169-173 calls abort (which returns) and the
\* loop continues removing locally; Abort(n) is enabled meanwhile.
LeaderRemoveExpired(n) ==
    /\ alive[n] /\ lpc[n] = "removing"
    /\ LET E == {i \in DOMAIN allKeys[n] : allKeys[n][i].exp < loopNow[n]} IN  \* :229
       IF E = {}
       THEN \* loop done, lock released; ATSM:321 roll check
            /\ lpc' = [lpc EXCEPT ![n] =
                         IF RollDue(n, loopNow[n]) THEN "rollStart" ELSE "loop"]
            /\ UNCHANGED <<allKeys, zkVars, watchVars>>
       ELSE LET i == Min(E) IN
            /\ allKeys' = [allKeys EXCEPT ![n] = Remove(@, {i})]   \* ATSM:233
            /\ IF session[n] /\ i \in DOMAIN zkKeys
               THEN /\ ZkDelete(i)                     \* :234 -> ZKSW:163-166
                    /\ UNCHANGED <<zkLeader, wLeader>>
               ELSE UNCHANGED <<zkVars, watchVars>>    \* NoNode logged ZKSW:167-168
            /\ UNCHANGED lpc
    /\ UNCHANGED <<clockVars, lifeVars, currentKey, idSeq, lastKeyUpdate,
                   electVars, loopNow, rollNow, rollPrev, issueVars,
                   targetFired, ghostVars>>

(***************************************************************************)
(* rollCurrentKey ATSM:243-265 (synchronized), split at the windows the    *)
(* brief names: clock read / install / publish / update prev.              *)
(***************************************************************************)
\* ATSM:244-247 isMaster check; ATSM:249 now.
RollReadClock(n) ==
    /\ alive[n] /\ lpc[n] = "rollStart"
    /\ IF ~isMaster[n]
       THEN /\ lpc' = [lpc EXCEPT ![n] = "loop"]                 \* :245-246
            /\ UNCHANGED rollNow
       ELSE /\ rollNow' = [rollNow EXCEPT ![n] = Clock(n)]       \* :249
            /\ lpc' = [lpc EXCEPT ![n] = "rollInstall"]
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, electVars, loopNow, rollPrev,
                   issueVars, zkVars, watchVars, targetFired, ghostVars>>

\* ATSM:250 prev = currentKey; :251-253 new key (++idSeq, Long.MAX_VALUE);
\* :254 allKeys.put; :255 currentKey = newKey.  From here handlers sign
\* with the new key (createPassword takes no lock).
RollInstall(n) ==
    /\ alive[n] /\ lpc[n] = "rollInstall"
    /\ LET k == [id |-> idSeq[n] + 1, exp |-> Inf, sec |-> n] IN
       /\ idSeq' = [idSeq EXCEPT ![n] = k.id]                    \* :251
       /\ allKeys' = [allKeys EXCEPT ![n] = Put(@, k.id, k)]     \* :254
       /\ rollPrev' = [rollPrev EXCEPT ![n] = currentKey[n]]     \* :250
       /\ currentKey' = [currentKey EXCEPT ![n] = k]             \* :255
       /\ minted' = minted \cup {<<k.id, k.sec>>}
       /\ everHeld' = [everHeld EXCEPT ![n] = @ \cup {k.id}]
    /\ lpc' = [lpc EXCEPT ![n] = "rollPublish"]
    /\ UNCHANGED <<clockVars, lifeVars, lastKeyUpdate, electVars, loopNow, rollNow,
                   issueVars, zkVars, watchVars, targetFired, published, startFailed>>

\* ATSM:256 zkWatcher.addKeyToZK(newKey) -> ZKSW:177-182 -> ZKU:833-841.
\* Normal outcome: the znode is written (ZK fires the watches).
\* Interrupted outcome (S4/S6): LeaderElector.stop() (ATSM:307) interrupted
\* this thread; ZKU:1210-1211 / ZKU:422-425 catch InterruptedException,
\* ZKW:694-699 does nothing, and addKeyToZK returns normally.  Whether the
\* already-queued request reaches the server is not observable to the
\* caller, so both outcomes are allowed when stopped[n].
\* (currentKey[n] is the new key: addKey is blocked by the monitor.)
RollPublish(n) ==
    /\ alive[n] /\ session[n] /\ lpc[n] = "rollPublish"
    /\ LET k == currentKey[n] IN
       \/ /\ ZkCreateSetData(k)
          /\ published' = published \cup {<<k.id, k.sec>>}
       \/ /\ stopped[n]                                          \* interrupted
          /\ UNCHANGED <<zkKeys, watchVars, published>>
    /\ lpc' = [lpc EXCEPT ![n] = "rollUpdatePrev"]
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, electVars, loopNow, rollNow, rollPrev,
                   issueVars, zkLeader, wLeader, targetFired, everHeld, startFailed, minted>>

\* ATSM:257 lastKeyUpdate = now; :259-263 prev.setExpiration(now + L),
\* allKeys.put(prev), zkWatcher.updateKeyInZK(prev) -> ZKSW:194-203
\* (setData, or createSetData on NoNode).  Interrupt as in RollPublish
\* (ZKU:782-784).
RollUpdatePrev(n) ==
    /\ alive[n] /\ session[n] /\ lpc[n] = "rollUpdatePrev"
    /\ lastKeyUpdate' = [lastKeyUpdate EXCEPT ![n] = rollNow[n]]      \* :257
    /\ IF rollPrev[n] = NoKey
       THEN UNCHANGED <<allKeys, zkKeys, watchVars, published>>      \* :259
       ELSE LET p == [rollPrev[n] EXCEPT !.exp = rollNow[n] + TokenLifetime] IN  \* :261
            /\ allKeys' = [allKeys EXCEPT ![n] = Put(@, p.id, p)]   \* :262
            /\ \/ /\ IF p.id \in DOMAIN zkKeys
                     THEN ZkSetData(p)                               \* ZKSW:199
                     ELSE ZkCreate(p)                                \* ZKSW:200-202
                  /\ published' = published \cup {<<p.id, p.sec>>}
               \/ /\ stopped[n]                                      \* interrupted
                  /\ UNCHANGED <<zkKeys, watchVars, published>>
    /\ lpc' = [lpc EXCEPT ![n] = "loop"]                            \* :327 sleep
    /\ UNCHANGED <<clockVars, lifeVars, currentKey, idSeq, electVars, loopNow,
                   rollNow, rollPrev, issueVars, zkLeader, wLeader, targetFired,
                   everHeld, startFailed, minted>>

\* FAULT (S4): the ZK write in addKeyToZK / updateKeyInZK throws
\* KeeperException after retries; ZKSW:183-187 / :204-208 abort the server.
\* The key stays installed in memory (and in any token signed with it).
ZkWriteFail(n) ==
    /\ Live(n) /\ lpc[n] \in {"rollPublish", "rollUpdatePrev"}
    /\ Die(n)

(***************************************************************************)
(* ZK event thread: ZooKeeperWatcher.process ZKW:538-582 dispatches each   *)
(* event to every listener: ZKSecretWatcher and ZKLeaderManager.           *)
(***************************************************************************)
HandleEvent(n) ==
    /\ Live(n) /\ evq[n] # <<>>
    /\ LET e == Head(evq[n]) IN
       /\ e.type = "Leader" \/ ~LockHeld(n)       \* addKey/removeKey block on the monitor
       /\ evq' = [evq EXCEPT ![n] = Tail(@)]
       /\ CASE e.type = "Children" ->
               \* ZKSW:120-131 nodeChildrenChanged -> ZKU:746-760 (getChildren
               \* re-arms the children watch, getDataAndWatch each child) ->
               \* refreshNodes ZKSW:138-157 -> addKey each.
               /\ wChild' = [wChild EXCEPT ![n] = TRUE]
               /\ wData' = [wData EXCEPT ![n] = @ \cup DOMAIN zkKeys]
               /\ AddKeys(n, DOMAIN zkKeys)
               /\ UNCHANGED <<wLeader, leaderExists>>
            [] e.type = "Data" ->
               \* ZKSW:97-117 nodeDataChanged -> ZKU:645 getDataAndWatch;
               \* null on NoNode -> ignored (ZKSW:101-104).
               /\ IF e.id \in DOMAIN zkKeys
                  THEN /\ wData' = [wData EXCEPT ![n] = @ \cup {e.id}]
                       /\ AddKeys(n, {e.id})                         \* ZKSW:108
                  ELSE UNCHANGED <<wData, allKeys, currentKey, idSeq, everHeld>>
               /\ UNCHANGED <<wChild, wLeader, leaderExists>>
            [] e.type = "Deleted" ->
               \* ZKSW:84-93 nodeDeleted -> ATSM:194-209 removeKey
               /\ IF isMaster[n]
                  THEN UNCHANGED allKeys                            \* ATSM:196-201
                  ELSE allKeys' = [allKeys EXCEPT ![n] = Remove(@, {e.id})]  \* :207
               /\ UNCHANGED <<currentKey, idSeq, everHeld, wChild, wData, wLeader, leaderExists>>
            [] e.type = "Leader" ->
               \* ZKLM:72-84 nodeCreated/nodeDeleted -> handleLeaderChange
               \* ZKLM:86-101 (only if !candidate.isStopped()).
               /\ IF epc[n] # "none" /\ ~stopped[n]
                  THEN /\ wLeader' = [wLeader EXCEPT ![n] = TRUE]             \* ZKLM:89
                       /\ leaderExists' = [leaderExists EXCEPT ![n] = zkLeader # None]  \* :91/:94-95
                  ELSE UNCHANGED <<wLeader, leaderExists>>
               /\ UNCHANGED <<allKeys, currentKey, idSeq, everHeld, wChild, wData>>
    /\ UNCHANGED <<clockVars, lifeVars, lastKeyUpdate, isMaster, epc, stopped,
                   loopVars, issueVars, zkVars, targetFired, published,
                   startFailed, minted>>

(***************************************************************************)
(* Token issuance: TokenProvider.getAuthenticationToken (TP:127) ->        *)
(* generateToken ATSM:160-169 -> Token ctor -> createPassword ATSM:127-136 *)
(* (no lock).  Split between the clock read and the currentKey read (S1).  *)
(***************************************************************************)
IssueReadClock(n) ==
    /\ alive[n] /\ listening[n] /\ cpPC[n] = "idle"
    /\ cpNow' = [cpNow EXCEPT ![n] = Clock(n)]                       \* ATSM:128
    /\ cpPC' = [cpPC EXCEPT ![n] = "clockRead"]
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, electVars, loopVars, tokens,
                   zkVars, watchVars, targetFired, ghostVars>>

IssueReadKey(n) ==
    /\ alive[n] /\ cpPC[n] = "clockRead"
    /\ IF currentKey[n] = NoKey
       THEN UNCHANGED tokens                 \* ATSM:130 NPE: no token issued (CR5)
       ELSE tokens' = tokens \cup                                    \* :129-132
              {[issuer |-> n, keyId |-> currentKey[n].id, sec |-> currentKey[n].sec,
                exp |-> cpNow[n] + TokenLifetime]}
    /\ cpPC' = [cpPC EXCEPT ![n] = "idle"]
    /\ UNCHANGED <<clockVars, lifeVars, keyVars, electVars, loopVars, cpNow,
                   zkVars, watchVars, targetFired, ghostVars>>

(***************************************************************************)
(* THE TARGET.  SASL DIGEST handshake at validator v for token t:          *)
(* RPCS:1453 evaluateResponse -> HBaseSaslRpcServer:110 -> :84 ->          *)
(* ATSM:139 retrievePassword.  allKeys is a ConcurrentHashMap: the get at  *)
(* :145 is one atomic read, so the check is one step.                      *)
(***************************************************************************)
TargetCheck(v, t) ==
    /\ alive[v] /\ listening[v] /\ t \in tokens
    /\ LET now == Clock(v) IN                                        \* ATSM:141
       IF t.exp < now
       THEN UNCHANGED vars             \* :142-143 "Token has expired" (not the target)
       ELSE IF t.keyId \notin DOMAIN allKeys[v]                      \* :145-146
            THEN /\ targetFired' = TRUE                              \* :147 THROW
                 /\ UNCHANGED <<clockVars, lifeVars, keyVars, electVars, loopVars,
                                issueVars, zkVars, watchVars, ghostVars>>
            ELSE UNCHANGED vars        \* :151-152 password regenerated

(***************************************************************************)
(* Node stop, crash, ZK session                                            *)
(***************************************************************************)
\* Graceful stop: RpcServer.stop RPCS:2330-2338 -> ATSM.stop :114-116 ->
\* LeaderElector.stop ATSM:295-308 (not synchronized with rollCurrentKey):
\* stopped = true; if isMaster: ZKLM.stepDownAsLeader ZKLM:154-167 (delete
\* the leader znode if ours); isMaster = false; interrupt(); then the
\* listener stops (RPCS:2337-2338).
NodeStop(n) ==
    /\ alive[n] /\ startPC[n] = "done" /\ ~stopped[n]
    /\ stopped' = [stopped EXCEPT ![n] = TRUE]                       \* :300
    /\ IF isMaster[n] /\ leaderExists[n] /\ zkLeader = n /\ session[n]   \* :302, ZKLM:157-161
       THEN \* our own watch fires too; ZKLM:81 ignores it (stopped)
            /\ ZkSetLeader(None, {})                                  \* ZKLM:163
            /\ leaderExists' = [leaderExists EXCEPT ![n] = FALSE]    \* ZKLM:164
       ELSE UNCHANGED <<zkLeader, evq, wLeader, leaderExists>>
    /\ isMaster' = [isMaster EXCEPT ![n] = FALSE]                    \* :305
    /\ listening' = [listening EXCEPT ![n] = FALSE]                  \* RPCS:2337-2338
    /\ UNCHANGED <<clockVars, alive, session, startPC, startList, keyVars, epc,
                   loopVars, issueVars, zkKeys, wChild, wData, targetFired, ghostVars>>

\* The stopped process exits (TokenServer.run returns / RS exits); the
\* leader thread may still have been inside rollCurrentKey until then.
NodeExit(n) ==
    /\ alive[n] /\ stopped[n]
    /\ Die(n)

\* FAULT: process crash.
Crash(n) ==
    /\ alive[n]
    /\ Die(n)

\* ZKW:631-639: Expired -> abortable.abort (also any ZK op of an expired
\* session throws and aborts).
Abort(n) ==
    /\ alive[n] /\ ~session[n]
    /\ Die(n)

\* FAULT: the ZK session of a running node expires (ZK deletes its
\* ephemeral leader znode; the node aborts later via Abort).
SessionExpire(n) ==
    /\ alive[n] /\ session[n]
    /\ session' = [session EXCEPT ![n] = FALSE]
    /\ IF zkLeader = n THEN ZkSetLeader(None, {n}) ELSE UNCHANGED <<zkLeader, evq, wLeader>>
    /\ UNCHANGED <<clockVars, alive, listening, startPC, startList, keyVars, electVars,
                   loopVars, issueVars, zkKeys, wChild, wData, targetFired, ghostVars>>

\* The session of a dead process ends (closed on exit, or timed out after
\* a crash): its ephemeral leader znode disappears.
SessionClose(n) ==
    /\ ~alive[n] /\ session[n]
    /\ session' = [session EXCEPT ![n] = FALSE]
    /\ IF zkLeader = n THEN ZkSetLeader(None, {n}) ELSE UNCHANGED <<zkLeader, evq, wLeader>>
    /\ UNCHANGED <<clockVars, alive, listening, startPC, startList, keyVars, electVars,
                   loopVars, issueVars, zkKeys, wChild, wData, targetFired, ghostVars>>

\* A dead server is started again with a new ZK session and a fresh ATSM.
Restart(n) ==
    /\ ~alive[n] /\ ~session[n]
    /\ ResetNode(n, TRUE, "createParents")
    /\ session' = [session EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<clockVars, tokens, zkVars, targetFired, published, minted>>

(***************************************************************************)
(* Next                                                                    *)
(***************************************************************************)
NodeAction(n) ==
    \/ StartCreateParents(n) \/ StartWatchExists(n)
    \/ StartListChildren(n)  \/ StartReadChildren(n) \/ StartZkFail(n)
    \/ ElectorAttemptClaim(n) \/ ElectorAttemptWait(n) \/ BecomeMaster(n)
    \/ LeaderLoopTop(n) \/ LeaderRemoveExpired(n)
    \/ RollReadClock(n) \/ RollInstall(n) \/ RollPublish(n) \/ RollUpdatePrev(n)
    \/ ZkWriteFail(n)
    \/ HandleEvent(n)
    \/ IssueReadClock(n) \/ IssueReadKey(n)
    \/ NodeStop(n) \/ NodeExit(n) \/ Crash(n) \/ Abort(n)
    \/ SessionExpire(n) \/ SessionClose(n) \/ Restart(n)

Next ==
    /\ ~targetFired          \* once the check fails, stop (short counterexamples)
    /\ \/ Tick
       \/ \E n \in Node : NodeAction(n)
       \/ \E v \in Node, t \in tokens : TargetCheck(v, t)

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)
KeyRec == [id : Nat, exp : Int, sec : Node \cup {None}]

TypeOK ==
    /\ gtime \in Nat
    /\ skew \in [Node -> -MaxSkew..MaxSkew]
    /\ alive \in [Node -> BOOLEAN] /\ session \in [Node -> BOOLEAN]
    /\ listening \in [Node -> BOOLEAN]
    /\ startPC \in [Node -> {"createParents", "watchExists", "listChildren",
                             "readChildren", "done", "dead"}]
    /\ \A n \in Node : DOMAIN allKeys[n] \subseteq Nat \ {0}
    /\ \A n \in Node : \A i \in DOMAIN allKeys[n] : allKeys[n][i] \in KeyRec
    /\ \A n \in Node : currentKey[n] \in KeyRec
    /\ idSeq \in [Node -> Nat]
    /\ isMaster \in [Node -> BOOLEAN] /\ stopped \in [Node -> BOOLEAN]
    /\ epc \in [Node -> {"none", "started", "waiting", "claimed", "master"}]
    /\ lpc \in [Node -> {"none", "loop", "removing", "rollStart", "rollInstall",
                         "rollPublish", "rollUpdatePrev", "exited"}]
    /\ cpPC \in [Node -> {"idle", "clockRead"}]
    /\ zkLeader \in Node \cup {None}
    /\ \A i \in DOMAIN zkKeys : zkKeys[i] \in KeyRec
    /\ targetFired \in BOOLEAN

\* THE PROPERTY: ATSM:146-147 never throws.
TargetSafe == ~targetFired

\* Structural: a token carries only a key its signer could have held
\* (every (keyId, secret) in a token was minted by some rollCurrentKey).
TokenFromHeldKey == \A t \in tokens : <<t.keyId, t.sec>> \in minted

\* Structural: a running master holds its own current key
\* (ATSM:254-255 install together; removeExpiredKeys never removes an
\* exp = Long.MAX_VALUE key).
MasterHoldsCurrent ==
    \A n \in Node :
        (isMaster[n] /\ alive[n] /\ currentKey[n] # NoKey)
            => currentKey[n].id \in DOMAIN allKeys[n]

=============================================================================
