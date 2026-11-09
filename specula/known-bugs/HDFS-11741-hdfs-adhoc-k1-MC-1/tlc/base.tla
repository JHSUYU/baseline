------------------------------ MODULE base ------------------------------
(***************************************************************************)
(* Ad hoc coordination target hdfs-adhoc-k1 (Apache Hadoop HDFS, 595e468).  *)
(*                                                                         *)
(* Target: BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])  *)
(*   security/token/block/BlockTokenSecretManager.java:476-488             *)
(*   guard  key == null, key = allKeys.get(keyId)            (479-481)     *)
(*   throw  InvalidEncryptionKeyException                    (482)         *)
(*                                                                         *)
(* Category A (distributed / message passing).  The guard's operands live  *)
(* in different processes: the NN master key manager, one worker manager   *)
(* per DN, the Balancer's worker manager and its cached DEK, and the       *)
(* DFSClient's cached DEK.  They are kept consistent only by RPCs on       *)
(* independent timers.  The model covers exactly the paths that write      *)
(* keys, deliver keys, mint DEKs, and evaluate the guard.                  *)
(*                                                                         *)
(* Path prefixes used in annotations (all in the pinned tree):             *)
(*   BTSM  = hadoop-hdfs/.../hdfs/security/token/block/                    *)
(*             BlockTokenSecretManager.java                                *)
(*   BPTSM = .../security/token/block/BlockPoolTokenSecretManager.java     *)
(*   HBM   = .../server/blockmanagement/HeartbeatManager.java              *)
(*   BM    = .../server/blockmanagement/BlockManager.java                  *)
(*   DNM   = .../server/blockmanagement/DatanodeManager.java               *)
(*   DD    = .../server/blockmanagement/DatanodeDescriptor.java            *)
(*   BPOS  = .../server/datanode/BPOfferService.java                       *)
(*   BPSA  = .../server/datanode/BPServiceActor.java                       *)
(*   DN    = .../server/datanode/DataNode.java                             *)
(*   KM    = .../server/balancer/KeyManager.java                           *)
(*   DISP  = .../server/balancer/Dispatcher.java                           *)
(*   SDTS  = .../protocol/datatransfer/sasl/SaslDataTransferServer.java    *)
(*   NNRPC = .../server/namenode/NameNodeRpcServer.java                    *)
(*   DFSC  = hadoop-hdfs-client/.../hdfs/DFSClient.java                    *)
(***************************************************************************)
EXTENDS Integers, FiniteSets, Bags, TLC

CONSTANTS
    DNs,            \* set of DataNodes (one block pool; brief 3.2)
    Clients,        \* set of DFSClient instances (each has its own DEK cache)
    I,              \* keyUpdateInterval, in model time units   (BTSM:71)
    L,              \* tokenLifetime, in model time units        (BTSM:72)
    KeyIdBase,      \* serial base of NN incarnation k is k*KeyIdBase; stands
                    \* in for the SecureRandom serial (BTSM:117) and keeps the
                    \* key ids of different incarnations disjoint
    InitLastRoll,   \* set of possible initial values of the Monitor's
                    \* lastBlockKeyUpdate relative to NN start (HBM:427,434):
                    \* the monotonic clock epoch is arbitrary, so the first
                    \* roll may come at any time <= I+1 (analysis F6)
    BalPollPeriod,  \* BlockKeyUpdater sleep, I/4 (KM:82,159), in ticks
    None            \* model value: null

ASSUME I \in Nat \ {0} /\ L \in Nat /\ KeyIdBase \in Nat /\ KeyIdBase > 2
ASSUME InitLastRoll \subseteq Int
ASSUME BalPollPeriod \in Nat \ {0}

(***************************************************************************)
(* Variables                                                               *)
(***************************************************************************)
VARIABLES
    now,            \* abstract global clock (one clock: brief 3.2 excludes skew)

    \* ---- NN master BlockTokenSecretManager + HeartbeatManager.Monitor ----
    nnInc,          \* NN incarnation (S4: keys are not persistent)
    nnSerial,       \* serialNo (BTSM:73)
    nnCur,          \* currentKey.getKeyId() (BTSM:74)
    nnNext,         \* nextKey.getKeyId()    (BTSM:75)
    nnKeys,         \* allKeys : keyId -> expiryDate (BTSM:76)
    lastRoll,       \* Monitor.lastBlockKeyUpdate (HBM:427)
    nnMonPC,        \* "idle" | "marking": between updateKeys() (HBM:439) and
                    \* the setNeedKeyUpdate loop (HBM:440-444)   [S2(b)]
    hbList,         \* HeartbeatManager.datanodes = nodes with isAlive() (HBM:212-228)
    needKeyUpdate,  \* DatanodeDescriptor.needKeyUpdate (DD:185, 273-279)
    safeMode,       \* namesystem.isInSafeMode()  (DNM:1641)       [S3]
    nnStored,       \* DNs whose NN descriptor holds storages reported by a
                    \*   heartbeat (DD:384-440 via DNM:1636).  A new descriptor
                    \*   has none (DNM:1112-1137; HBM:203 uses EMPTY_ARRAY)

    \* ---- DataNodes ----
    dnPC,           \* BPServiceActor phase: "unreg" | "regSnap" | "regResp" |
                    \*   "regAddKeys" | "running"
    dnMgr,          \* blockPoolTokenSecretManager.isBlockPoolRegistered(bp)
                    \*   (BPTSM:63-65, DN:1583-1597)
    dnKeys,         \* worker allKeys : keyId -> expiryDate
    dnCur,          \* worker currentKey id, or None (worker ctor never sets it,
                    \*   BTSM:121-134,148-149)
    regSnap,        \* exported keys captured in registerDatanode (DNM:1023),
                    \*   carried in the registration response
    hbResp,         \* in-flight heartbeat response, or None
    hbDone,         \* DN completed >= 1 heartbeat round trip in this tick

    \* ---- Balancer KeyManager ----
    balOn,          \* KeyManager constructed and updater running
    balKeys,        \* Balancer worker allKeys
    balCur,         \* Balancer worker currentKey id
    balDEK,         \* KeyManager.encryptionKey keyId, or None (KM:56,116)
    balPollAge,     \* ticks since the last getBlockKeys poll (KM:151-159)

    \* ---- DFSClient ----
    cliDEK,         \* per client: DFSClient.encryptionKey as [keyId, exp], or
                    \*   None (DFSC:1725)

    \* ---- encrypted data-transfer connections in flight ----
    conns,          \* bag of [src, dst, keyId]: the SASL username carries keyId
                    \*   (SDTS:259-268); a bag so identical concurrent
                    \*   connections stay distinct

    \* ---- history / oracle ----
    mintedKeys,     \* every keyId any NN incarnation generated
    targetFired,    \* the line-482 throw was executed
    npeFired        \* key == null but currentKey == null: NPE at line 484
                    \*   before the throw (brief 3.1 item 7) - NOT the target

nnVars   == <<nnInc, nnSerial, nnCur, nnNext, nnKeys, lastRoll, nnMonPC,
              hbList, needKeyUpdate, safeMode, nnStored>>
dnVars   == <<dnPC, dnMgr, dnKeys, dnCur, regSnap, hbResp, hbDone>>
balVars  == <<balOn, balKeys, balCur, balDEK, balPollAge>>
cliVars  == <<cliDEK>>
oracleVars == <<mintedKeys, targetFired, npeFired>>
vars == <<now, nnVars, dnVars, balVars, cliVars, conns, oracleVars>>

(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
EmptyKeys == [k \in {} |-> 0]

\* allKeys.put(k, v)
Put(f, k, v) == [x \in DOMAIN f \cup {k} |-> IF x = k THEN v ELSE f[x]]

\* removeExpiredKeys(): drop every key with expiryDate < now  (BTSM:182-191)
RemoveExpired(f) == [x \in {y \in DOMAIN f : ~(f[y] < now)} |-> f[x]]

\* exportKeys(): ExportedBlockKeys(currentKey, allKeys.values())  (BTSM:173-180)
Export == [cur |-> nnCur, keys |-> nnKeys]

\* worker addKeys(exportedKeys)  (BTSM:196-209), order kept as coded:
\*   201 removeExpiredKeys(); 202 currentKey := exported.currentKey;
\*   203-208 put every received key (overwriting the local copy).
AddKeysKeys(f, e) ==
    LET r == RemoveExpired(f) IN
    [x \in DOMAIN r \cup DOMAIN e.keys |->
        IF x \in DOMAIN e.keys THEN e.keys[x] ELSE r[x]]
AddKeysCur(e) == e.cur

\* Master construction (BTSM:110-134).  The private ctor calls
\* generateKeys() with serialNo = 0 (133), giving keys 1 and 2; the public
\* ctor then sets a random serial r (117) and calls generateKeys() again
\* (118), giving r+1 (current) and r+2 (next).  All four stay in allKeys.
\* generateKeys: current exp now+2I+L (163-164), next exp now+3I+L (166-167).
FreshNNKeys(inc) ==
    LET r == inc * KeyIdBase IN
    [cur    |-> r + 1,
     next   |-> r + 2,
     serial |-> r + 2,
     keys   |-> (1 :> now + 2*I + L) @@ (2 :> now + 3*I + L)
                @@ ((r + 1) :> now + 2*I + L) @@ ((r + 2) :> now + 3*I + L)]

\* HeartbeatManager.Monitor: shouldUpdateBlockKey(now - lastBlockKeyUpdate)
\* -> updateKeys(updateTime): updateTime > keyUpdateInterval (HBM:439,
\* BM:613-615, BTSM:215-219).  Strict >.
RollDue == now - lastRoll > I

Conn(src, dst, k) == [src |-> src, dst |-> dst, keyId |-> k]
OpenConn(c) == conns' = conns (+) SetToBag({c})
InFlight == BagCardinality(conns)

\* Connection targets are DNs the NN currently lists as live: clients get
\* them from getBlockLocations / addBlock, the Balancer from
\* getLiveDatanodeStorageReport (DISP:1094, NameNodeConnector:187), DN->DN
\* targets from NN commands or the Balancer.  Declaring a node dead removes
\* it and its replicas (DNM:696-703 removeDatanode -> removeBlocksAssociatedTo).
\* (Stale client-side location caches are not modeled.)
\* A DN is a usable target only once its descriptor holds storages: block
\* placement needs a storage with space (DD:705-730, BPPD:743-755), reads
\* need replicas from a block report, and the Balancer works from storage
\* reports.  Storages come only from heartbeat reports, which the DN sends
\* after its registration addKeys (BPSA register -> BPOS:384-386).
NNListed(d) == d \in hbList /\ d \in nnStored

(***************************************************************************)
(* Init                                                                    *)
(***************************************************************************)
Init ==
    /\ now = 0
    \* NN: BlockManager ctor builds the master manager (BM:408 -> BTSM:110-119)
    /\ nnInc = 1
    /\ LET f == FreshNNKeys(1) IN
         /\ nnSerial = f.serial
         /\ nnCur = f.cur
         /\ nnNext = f.next
         /\ nnKeys = f.keys
         /\ mintedKeys = DOMAIN f.keys
    /\ lastRoll \in InitLastRoll
    /\ nnMonPC = "idle"
    /\ hbList = {}
    /\ needKeyUpdate = [d \in DNs |-> FALSE]          \* DD:185
    /\ safeMode = FALSE
    /\ nnStored = {}
    \* DNs start unregistered, with no per-pool manager (DN:1583-1597 runs
    \* only after the first registration)
    /\ dnPC = [d \in DNs |-> "unreg"]
    /\ dnMgr = [d \in DNs |-> FALSE]
    /\ dnKeys = [d \in DNs |-> EmptyKeys]
    /\ dnCur = [d \in DNs |-> None]
    /\ regSnap = [d \in DNs |-> None]
    /\ hbResp = [d \in DNs |-> None]
    /\ hbDone = [d \in DNs |-> FALSE]
    /\ balOn = FALSE
    /\ balKeys = EmptyKeys
    /\ balCur = None
    /\ balDEK = None
    /\ balPollAge = 0
    /\ cliDEK = [c \in Clients |-> None]
    /\ conns = EmptyBag
    /\ targetFired = FALSE
    /\ npeFired = FALSE

(***************************************************************************)
(* Time                                                                    *)
(***************************************************************************)
\* Timeliness of the periodic threads, relative to one tick.  These are
\* environment assumptions, not code: a tick is a fraction of the key
\* interval, while heartbeats (3 s; 1 s in the workload), the Monitor loop
\* (5 s, HBM:451), registration RPCs and SASL handshakes are much shorter.
\*  - the Monitor rolls as soon as RollDue (its 5 s loop, HBM:430-451), and
\*    the mark loop follows updateKeys in the same iteration (HBM:439-446);
\*  - every DN finishes registration and >= 1 heartbeat round trip per tick;
\*  - a key update the NN can deliver (flag set, not in safe mode, node
\*    listed) is picked up by the DN's next heartbeat, i.e. within the tick
\*    of the roll or of leaving safe mode (heartbeat 3 s << tick);
\*  - the Balancer polls at least once every BalPollPeriod ticks (KM:159);
\*  - connections in flight are served within the tick.
Timely ==
    /\ conns = EmptyBag
    /\ nnMonPC = "idle"
    /\ ~RollDue
    /\ \A d \in DNs : dnPC[d] = "running" /\ hbResp[d] = None /\ hbDone[d]
    /\ \A d \in DNs : needKeyUpdate[d] => (safeMode \/ d \notin hbList)
    /\ balOn => balPollAge < BalPollPeriod

\* The time step itself (shared with Trace.tla, which advances the clock to
\* each event's timestamp).
AdvanceTime(t) ==
    /\ t > now
    /\ now' = t
    /\ hbDone' = [d \in DNs |-> FALSE]
    /\ balPollAge' = IF balOn THEN balPollAge + 1 ELSE balPollAge
    /\ UNCHANGED <<nnVars, dnPC, dnMgr, dnKeys, dnCur, regSnap, hbResp,
                   balOn, balKeys, balCur, balDEK, cliVars, conns, oracleVars>>

Tick == Timely /\ AdvanceTime(now + 1)

(***************************************************************************)
(* NN: HeartbeatManager.Monitor key roll  (HBM:430-451)                    *)
(* Split into updateKeys() and the mark loop: the Monitor does not hold the *)
(* namesystem lock that registerDatanode holds (FSNamesystem:3639-3645), so *)
(* registration can interleave between and around them.         [S2(b)]    *)
(***************************************************************************)
NNRollUpdate ==
    /\ nnMonPC = "idle"
    \* HBM:439 -> BM:613-615 -> BTSM:216 (updateTime > keyUpdateInterval)
    /\ RollDue
    \* BTSM:225-245 updateKeys()
    /\ LET r0  == RemoveExpired(nnKeys)                       \* 230
           \* 232-234: retiring currentKey gets final expiry now+I+L
           r1  == Put(r0, nnCur, now + I + L)
           \* 236-238: currentKey := nextKey with expiry now+2I+L
           r2  == Put(r1, nnNext, now + 2*I + L)
           \* 240-243: serialNo+1, new nextKey with expiry now+3I+L
           ns  == nnSerial + 1
           r3  == Put(r2, ns, now + 3*I + L)
       IN /\ nnKeys' = r3
          /\ nnCur' = nnNext
          /\ nnNext' = ns
          /\ nnSerial' = ns
          /\ mintedKeys' = mintedKeys \cup {ns}
    \* HBM:445 lastBlockKeyUpdate = now, the value read at HBM:434
    /\ lastRoll' = now
    /\ nnMonPC' = "marking"
    /\ UNCHANGED <<now, nnInc, hbList, needKeyUpdate, safeMode, nnStored, dnVars,
                   balVars, cliVars, conns, targetFired, npeFired>>

NNRollMark ==
    /\ nnMonPC = "marking"
    \* HBM:440-444: under synchronized(HeartbeatManager.this) mark only the
    \* nodes currently in `datanodes`
    /\ needKeyUpdate' = [d \in DNs |->
                           IF d \in hbList THEN TRUE ELSE needKeyUpdate[d]]
    /\ nnMonPC' = "idle"
    /\ UNCHANGED <<now, nnInc, nnSerial, nnCur, nnNext, nnKeys, lastRoll,
                   hbList, safeMode, nnStored, dnVars, balVars, cliVars, conns, oracleVars>>

(***************************************************************************)
(* Registration  (DNM:1002-1140, BPOS:370-391, DN:1550-1597)                *)
(* Split into: NN snapshot of the export (DNM:1023), NN adds the node to   *)
(* the heartbeat list (DNM:1098 / 1136), DN applies the response.           *)
(***************************************************************************)
RegSnapshot(d) ==
    /\ dnPC[d] = "unreg"
    \* DNM:1023 nodeReg.setExportedKeys(blockManager.getBlockKeys())
    \*   -> BM:1267-1269 -> BTSM:173-180
    /\ regSnap' = [regSnap EXCEPT ![d] = Export]
    /\ dnPC' = [dnPC EXCEPT ![d] = "regSnap"]
    /\ UNCHANGED <<now, nnVars, dnMgr, dnKeys, dnCur, hbResp, hbDone,
                   balVars, cliVars, conns, oracleVars>>

RegAddToList(d) ==
    /\ dnPC[d] = "regSnap"
    \* Known descriptor (nodeS != null, DNM:1048-1110): heartbeatManager
    \*   .register(nodeS) adds it only if !isAlive (DNM:1098, HBM:198-206).
    \* New descriptor (DNM:1112-1140): addDatanode (HBM:212-216), with
    \*   needKeyUpdate = false (DD:185); NNRestart resets the flags.
    \* Both cases leave d in `datanodes` and keep needKeyUpdate[d].
    /\ hbList' = hbList \cup {d}
    /\ dnPC' = [dnPC EXCEPT ![d] = "regResp"]
    /\ UNCHANGED <<now, nnInc, nnSerial, nnCur, nnNext, nnKeys, lastRoll,
                   nnMonPC, needKeyUpdate, safeMode, nnStored, dnMgr, dnKeys, dnCur,
                   regSnap, hbResp, hbDone, balVars, cliVars, conns, oracleVars>>

\* BPOS:370-391 registrationSucceeded -> DN:1550-1561 bpRegistrationSucceeded
\*   -> DN:1568-1598 registerBlockPoolWithSecretManager, then BPOS:384-386
\*   addKeys(reg.getExportedKeys()).
DNRegistrationSucceeded(d) ==
    /\ dnPC[d] = "regResp"
    /\ IF dnMgr[d]
       THEN \* DN:1583 pool already registered: the manager is reused
            UNCHANGED <<dnMgr, dnKeys, dnCur>>
       ELSE \* DN:1594-1597 new worker manager (allKeys empty, currentKey null)
            \* is published by addBlockPool BEFORE addKeys runs (BPOS:384-386);
            \* DataXceiver does not take the BPOfferService lock, so a
            \* connection can see it in between (analysis F5).
            /\ dnMgr' = [dnMgr EXCEPT ![d] = TRUE]
            /\ dnKeys' = [dnKeys EXCEPT ![d] = EmptyKeys]
            /\ dnCur' = [dnCur EXCEPT ![d] = None]
    /\ dnPC' = [dnPC EXCEPT ![d] = "regAddKeys"]
    /\ UNCHANGED <<now, nnVars, regSnap, hbResp, hbDone, balVars, cliVars,
                   conns, oracleVars>>

DNRegAddKeys(d) ==
    /\ dnPC[d] = "regAddKeys"
    \* BPOS:384-386 -> BPTSM:113-116 -> BTSM:196-209
    /\ dnKeys' = [dnKeys EXCEPT ![d] = AddKeysKeys(dnKeys[d], regSnap[d])]
    /\ dnCur' = [dnCur EXCEPT ![d] = AddKeysCur(regSnap[d])]
    /\ dnPC' = [dnPC EXCEPT ![d] = "running"]
    /\ regSnap' = [regSnap EXCEPT ![d] = None]
    \* registration is also treated as a heartbeat (DNM:1097, 1133)
    /\ hbDone' = [hbDone EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<now, nnVars, dnMgr, hbResp, balVars, cliVars, conns, oracleVars>>

(***************************************************************************)
(* Heartbeat  (BPSA:611-734, DNM:1613-1700, BM:1300-1307, BPOS:730-737)     *)
(* Split into NN builds the response and DN processes it; the response can *)
(* be lost in between (LoseHeartbeatResp).                                  *)
(***************************************************************************)
NNHandleHeartbeat(d) ==
    /\ dnPC[d] = "running"
    /\ hbResp[d] = None
    /\ IF d \notin hbList
       THEN \* DNM:1621-1624 unknown node / DNM:1633-1635 !isRegistered()
            \*   (isRegistered = isAlive && !forceRegistration, DD:999-1001)
            /\ hbResp' = [hbResp EXCEPT ![d] = [kind |-> "REGISTER", exp |-> None]]
            /\ UNCHANGED <<needKeyUpdate, nnStored>>
       ELSE \* DNM:1636 updateHeartbeat -> DD:384 updateHeartbeatState creates
            \*   the reported storages; this precedes the safe-mode return
            /\ nnStored' = nnStored \cup {d}
            /\ IF safeMode
               THEN \* DNM:1641-1643 safe mode: return no commands, flag stays set
                    /\ hbResp' = [hbResp EXCEPT ![d] = [kind |-> "NONE", exp |-> None]]
                    /\ UNCHANGED needKeyUpdate
               ELSE IF needKeyUpdate[d]
               THEN \* DNM:1676 -> BM:1303-1305: KeyUpdateCommand(exportKeys())
                    \*   and clear the flag while building the response
                    /\ hbResp' = [hbResp EXCEPT ![d] = [kind |-> "KEYS", exp |-> Export]]
                    /\ needKeyUpdate' = [needKeyUpdate EXCEPT ![d] = FALSE]
               ELSE /\ hbResp' = [hbResp EXCEPT ![d] = [kind |-> "NONE", exp |-> None]]
                    /\ UNCHANGED needKeyUpdate
    /\ UNCHANGED <<now, nnInc, nnSerial, nnCur, nnNext, nnKeys, lastRoll,
                   nnMonPC, hbList, safeMode, dnPC, dnMgr, dnKeys, dnCur,
                   regSnap, hbDone, balVars, cliVars, conns, oracleVars>>

DNRecvHeartbeat(d) ==
    /\ hbResp[d] /= None
    /\ LET r == hbResp[d] IN
       \* BPSA:675 processCommand -> BPOS:617-640 processCommandFromActor
       CASE r.kind = "KEYS" ->
              \* BPOS:730-737 DNA_ACCESSKEYUPDATE -> BPTSM:113-116 -> BTSM:196-209
              /\ dnKeys' = [dnKeys EXCEPT ![d] = AddKeysKeys(dnKeys[d], r.exp)]
              /\ dnCur' = [dnCur EXCEPT ![d] = AddKeysCur(r.exp)]
              /\ UNCHANGED dnPC
         [] r.kind = "REGISTER" ->
              \* DNA_REGISTER: the actor re-registers (BPOS processCommandFromActor)
              /\ dnPC' = [dnPC EXCEPT ![d] = "unreg"]
              /\ UNCHANGED <<dnKeys, dnCur>>
         [] OTHER ->
              UNCHANGED <<dnPC, dnKeys, dnCur>>
    /\ hbResp' = [hbResp EXCEPT ![d] = None]
    /\ hbDone' = [hbDone EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<now, nnVars, dnMgr, regSnap, balVars, cliVars, conns, oracleVars>>

(***************************************************************************)
(* Balancer / Mover KeyManager  (KM:58-177, DISP:334-405)                   *)
(***************************************************************************)
BalancerStart ==
    /\ ~balOn
    \* KM:63 namenode.getBlockKeys(); KM:76-79 new worker manager + addKeys
    /\ balKeys' = AddKeysKeys(EmptyKeys, Export)
    /\ balCur' = AddKeysCur(Export)
    /\ balOn' = TRUE
    /\ balDEK' = None
    /\ balPollAge' = 0
    /\ UNCHANGED <<now, nnVars, dnVars, cliVars, conns, oracleVars>>

BalancerPoll ==
    /\ balOn
    \* KM:155 addKeys(namenode.getBlockKeys()) (NNRPC getBlockKeys -> BM:1267)
    /\ balKeys' = AddKeysKeys(balKeys, Export)
    /\ balCur' = AddKeysCur(Export)
    /\ balPollAge' = 0
    /\ UNCHANGED <<now, nnVars, dnVars, balOn, balDEK, cliVars, conns, oracleVars>>

\* KM:126-136 close(): shouldRun = false, updater interrupted; the
\* NameNodeConnector (and its KeyManager) is closed when the run ends
\* (Balancer.java:721-725).  A later run builds a new KeyManager.
BalancerClose ==
    /\ balOn
    /\ balOn' = FALSE
    /\ balKeys' = EmptyKeys
    /\ balCur' = None
    /\ balDEK' = None
    /\ balPollAge' = 0
    /\ UNCHANGED <<now, nnVars, dnVars, cliVars, conns, oracleVars>>

\* DISP:358-362 PendingMove.dispatch -> saslClient.socketSend(..., km, ...)
\*   -> SaslDataTransferClient.checkTrustAndSend -> km.newDataEncryptionKey()
\* KM:113-124: mint once (if encryptionKey == null) from the worker's
\* currentKey (BTSM:455-466, keyId = currentKey id at 463); never refreshed,
\* never expiry-checked, never cleared on failure (DISP:375-392).   [S1]
BalancerConnect(d) ==
    /\ balOn
    /\ NNListed(d)
    /\ LET k == IF balDEK = None THEN balCur ELSE balDEK IN
       /\ balDEK' = k
       /\ OpenConn(Conn("bal", d, k))
    /\ UNCHANGED <<now, nnVars, dnVars, balOn, balKeys, balCur, balPollAge,
                   cliVars, oracleVars>>

(***************************************************************************)
(* DFSClient  (DFSC:1704-1735; NNRPC:1715-1718 -> BM:1309-1314)            *)
(***************************************************************************)
ClientConnect(c, d) ==
    /\ NNListed(d)
    \* DFSC:1725-1728 refetch iff no key or expiryDate < now; the NN mints
    \* from its master currentKey with expiry now+L (BTSM:455-466).  No
    \* safe-mode check on getDataEncryptionKey (NNRPC:1715-1718).
    /\ LET need == cliDEK[c] = None \/ cliDEK[c].exp < now
           k    == IF need THEN [keyId |-> nnCur, exp |-> now + L] ELSE cliDEK[c]
       IN /\ cliDEK' = [cliDEK EXCEPT ![c] = k]
          /\ OpenConn(Conn(c, d, k.keyId))
    /\ UNCHANGED <<now, nnVars, dnVars, balVars, oracleVars>>

(***************************************************************************)
(* DN -> DN transfer (replaceBlock second hop DataXceiver:1172-1175, write *)
(* pipeline mirror, replication): fresh DEK per connection from the        *)
(* sender's worker currentKey  (DN:2570-2580 -> BPTSM:136-138 -> BTSM:455-466) *)
(***************************************************************************)
DNTransfer(s, t) ==
    /\ s /= t
    /\ NNListed(t)
    /\ dnMgr[s]                 \* else BPTSM:56-58 IllegalArgumentException
    /\ dnCur[s] /= None         \* else NPE at BTSM:462 key.getKey()
    /\ OpenConn(Conn(s, t, dnCur[s]))
    /\ UNCHANGED <<now, nnVars, dnVars, balVars, cliVars, oracleVars>>

(***************************************************************************)
(* TARGET: the SASL server's password callback on DN c.dst                  *)
(* DataXceiver -> SDTS:158-182 getEncryptedStreams -> SDTS:259-271          *)
(*   getEncryptionKeyFromUserName -> BPTSM:140-143 -> BTSM:476-488.         *)
(* Atomic: the lookup runs under the worker manager's monitor (BTSM:479),  *)
(* the same monitor addKeys holds (BTSM:196).                               *)
(***************************************************************************)
TargetCheck(c) ==
    /\ BagIn(c, conns)
    /\ LET d == c.dst IN
       IF ~dnMgr[d]
       THEN \* BPTSM:55-58 get(bpid) throws IllegalArgumentException: not target
            UNCHANGED <<targetFired, npeFired, cliDEK>>
       ELSE IF c.keyId \in DOMAIN dnKeys[d]
       THEN \* BTSM:480 key found -> BTSM:487 createPassword; handshake succeeds
            UNCHANGED <<targetFired, npeFired, cliDEK>>
       ELSE IF dnCur[d] = None
       THEN \* BTSM:481 key == null, but BTSM:484 currentKey.getKeyId() throws
            \* NullPointerException while building the message: not the target
            /\ npeFired' = TRUE
            /\ UNCHANGED <<targetFired, cliDEK>>
       ELSE \* BTSM:481-484 key == null: throw InvalidEncryptionKeyException
            /\ targetFired' = TRUE
            \* SDTS:414-422 ERROR_UNKNOWN_KEY; a DFSClient clears its DEK
            \* (DFSC:1704-1709 via DFSInputStream:574-580); the Balancer does not
            /\ cliDEK' = IF c.src \in Clients
                          THEN [cliDEK EXCEPT ![c.src] = None] ELSE cliDEK
            /\ UNCHANGED npeFired
    /\ conns' = conns (-) SetToBag({c})
    /\ UNCHANGED <<now, nnVars, dnVars, balVars, mintedKeys>>

(***************************************************************************)
(* Faults and operator actions (bounded in MC.tla)                          *)
(***************************************************************************)

\* S2(a): the heartbeat response is lost after the NN cleared needKeyUpdate
\* (BM:1303-1305).  The DN sees an IOException (BPSA:726-728); nothing resends.
LoseHeartbeatResp(d) ==
    /\ hbResp[d] /= None
    /\ hbResp' = [hbResp EXCEPT ![d] = None]
    /\ hbDone' = [hbDone EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<now, nnVars, dnPC, dnMgr, dnKeys, dnCur, regSnap,
                   balVars, cliVars, conns, oracleVars>>

\* S2(b) trigger: heartbeatCheck declares d dead (HBM:436 -> removeDatanode
\* HBM:222-228: datanodes.remove, alive = false).  Abstracts a pause or
\* NN<->DN partition longer than the dead-node interval (<< I).  The DN then
\* gets REGISTER (DNM:1633-1635) and re-registers.  Runs on the Monitor thread.
NNDeclareDead(d) ==
    /\ nnMonPC = "idle"
    \* heartbeatCheck -> removeDeadDatanode holds the namesystem write lock
    \* (DNM:734-747, 698), as does registerDatanode (FSNamesystem:3639-3645)
    /\ \A x \in DNs : dnPC[x] /= "regSnap"
    /\ d \in hbList
    /\ hbList' = hbList \ {d}
    /\ UNCHANGED <<now, nnInc, nnSerial, nnCur, nnNext, nnKeys, lastRoll,
                   nnMonPC, needKeyUpdate, safeMode, nnStored, dnVars, balVars,
                   cliVars, conns, oracleVars>>

\* S3: manual (dfsadmin -safemode enter) or resource-low safe mode
\* (FSNamesystem:4317-4319).  The Monitor keeps rolling (HBM:430-446 has no
\* safe-mode check); only heartbeat delivery stops (DNM:1641-1643).
EnterSafeMode ==
    /\ ~safeMode
    /\ safeMode' = TRUE
    /\ UNCHANGED <<now, nnInc, nnSerial, nnCur, nnNext, nnKeys, lastRoll,
                   nnMonPC, hbList, needKeyUpdate, nnStored, dnVars, balVars,
                   cliVars, conns, oracleVars>>

LeaveSafeMode ==
    /\ safeMode
    /\ safeMode' = FALSE
    /\ UNCHANGED <<now, nnInc, nnSerial, nnCur, nnNext, nnKeys, lastRoll,
                   nnMonPC, hbList, needKeyUpdate, nnStored, dnVars, balVars,
                   cliVars, conns, oracleVars>>

\* S4: NN crash + restart.  New master manager with fresh keys and a new
\* random serial (BM:408 -> BTSM:110-119); keys are not persisted.  New
\* HeartbeatManager: empty `datanodes`, Monitor's lastBlockKeyUpdate = 0
\* against an arbitrary monotonic epoch (HBM:427,434).  New descriptors
\* (needKeyUpdate = false, DD:185).  A registration RPC being handled is
\* aborted (the DN retries); responses already sent may still arrive.
\* Startup safe mode is not modeled (S3 covers safe mode).
\* A SASL handshake completes within the DataXceiver socket timeout, right
\* after connect (the client sends its SASL message at once, SDTS:158-182),
\* while an NN crash + restart (image load) takes far longer: no handshake
\* begun before the crash is still pending when the new NN comes up.
NNRestart ==
    /\ conns = EmptyBag
    /\ LET inc == nnInc + 1
           f   == FreshNNKeys(inc)
       IN /\ nnInc' = inc
          /\ nnSerial' = f.serial
          /\ nnCur' = f.cur
          /\ nnNext' = f.next
          /\ nnKeys' = f.keys
          /\ mintedKeys' = mintedKeys \cup DOMAIN f.keys
    /\ lastRoll' \in {now + x : x \in InitLastRoll}
    /\ nnMonPC' = "idle"
    /\ hbList' = {}
    /\ needKeyUpdate' = [d \in DNs |-> FALSE]
    /\ safeMode' = FALSE
    \* new descriptors are built on re-registration: no storages yet
    /\ nnStored' = {}
    /\ dnPC' = [d \in DNs |-> IF dnPC[d] = "regSnap" THEN "unreg" ELSE dnPC[d]]
    /\ regSnap' = [d \in DNs |-> IF dnPC[d] = "regSnap" THEN None ELSE regSnap[d]]
    /\ UNCHANGED <<now, dnMgr, dnKeys, dnCur, hbResp, hbDone, balVars,
                   cliVars, conns, targetFired, npeFired>>

\* S4: DN crash + restart.  A new DataNode has an empty
\* BlockPoolTokenSecretManager; the pool's worker manager is created only
\* at registration (DN:1583-1597).  Connections to it are broken.  The NN
\* still holds its descriptor (alive) until heartbeatCheck.
DNRestart(d) ==
    /\ dnPC' = [dnPC EXCEPT ![d] = "unreg"]
    /\ dnMgr' = [dnMgr EXCEPT ![d] = FALSE]
    /\ dnKeys' = [dnKeys EXCEPT ![d] = EmptyKeys]
    /\ dnCur' = [dnCur EXCEPT ![d] = None]
    /\ regSnap' = [regSnap EXCEPT ![d] = None]
    /\ hbResp' = [hbResp EXCEPT ![d] = None]
    /\ conns' = [c \in {x \in DOMAIN conns : x.dst /= d} |-> conns[c]]
    /\ UNCHANGED <<now, nnVars, hbDone, balVars, cliVars, oracleVars>>

(***************************************************************************)
(* Next                                                                    *)
(***************************************************************************)
Next ==
    /\ ~targetFired       \* stop once the target fired (short counterexamples)
    /\ \/ Tick
       \/ NNRollUpdate
       \/ NNRollMark
       \/ \E d \in DNs :
            \/ RegSnapshot(d)
            \/ RegAddToList(d)
            \/ DNRegistrationSucceeded(d)
            \/ DNRegAddKeys(d)
            \/ NNHandleHeartbeat(d)
            \/ DNRecvHeartbeat(d)
            \/ BalancerConnect(d)
            \/ \E c \in Clients : ClientConnect(c, d)
            \/ LoseHeartbeatResp(d)
            \/ NNDeclareDead(d)
            \/ DNRestart(d)
       \/ \E s, t \in DNs : DNTransfer(s, t)
       \/ BalancerStart
       \/ BalancerPoll
       \/ BalancerClose
       \/ \E c \in BagToSet(conns) : TargetCheck(c)
       \/ EnterSafeMode
       \/ LeaveSafeMode
       \/ NNRestart

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The oracle: the target check never fails.
TargetSafe == ~targetFired

\* Sanity 1 (BTSM:168-169, 236-243): the NN's current and next keys exist
\* and differ.
NNKeysWellFormed ==
    /\ nnCur \in DOMAIN nnKeys
    /\ nnNext \in DOMAIN nnKeys
    /\ nnCur /= nnNext

\* Sanity 2: workers never generate keys (BTSM:148-149); every key id held or
\* presented anywhere was generated by some NN incarnation ("a message
\* carries only values its sender held").
HeldKeyIds ==
    UNION {DOMAIN dnKeys[d] : d \in DNs}
    \cup {dnCur[d] : d \in {x \in DNs : dnCur[x] /= None}}
    \cup DOMAIN balKeys
    \cup (IF balCur = None THEN {} ELSE {balCur})
    \cup (IF balDEK = None THEN {} ELSE {balDEK})
    \cup {cliDEK[c].keyId : c \in {x \in Clients : cliDEK[x] /= None}}
    \cup {c.keyId : c \in BagToSet(conns)}
KeysOriginateAtNN == HeldKeyIds \subseteq mintedKeys

\* State constraint for running base.cfg directly (MC.tla is the real
\* model-checking entry point).
BaseConstraint == now <= 1 /\ InFlight <= 1 /\ nnInc <= 1

PCs == {"unreg", "regSnap", "regResp", "regAddKeys", "running"}
TypeOK ==
    /\ now \in Int
    /\ nnMonPC \in {"idle", "marking"}
    /\ hbList \subseteq DNs
    /\ needKeyUpdate \in [DNs -> BOOLEAN]
    /\ safeMode \in BOOLEAN
    /\ nnStored \subseteq DNs
    /\ dnPC \in [DNs -> PCs]
    /\ dnMgr \in [DNs -> BOOLEAN]
    /\ hbDone \in [DNs -> BOOLEAN]
    /\ \A d \in DNs : hbResp[d] = None \/ hbResp[d].kind \in {"REGISTER", "NONE", "KEYS"}
    /\ \A d \in DNs : dnCur[d] = None \/ dnCur[d] \in DOMAIN dnKeys[d] \/ ~dnMgr[d]
    /\ balOn \in BOOLEAN
    /\ targetFired \in BOOLEAN
    /\ npeFired \in BOOLEAN

=============================================================================
