-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-11: one ad hoc coordination check                            *)
(*   BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])         *)
(*   key = allKeys.get(keyId); if (key == null)            BTSM:557-558     *)
(*     throw new InvalidEncryptionKeyException(... currentKey.getKeyId())   *)
(*                                                         BTSM:559-561     *)
(*                                                                         *)
(* Category A (distributed / message passing). The guard's operand is a     *)
(* DataNode worker's copy of a NameNode's block keys (allKeys, BTSM:81).    *)
(* It changes only when a registration reply (export at DM:1209) or a       *)
(* heartbeat KeyUpdateCommand (BM:1671-1677) is applied on the DN           *)
(* (BPOS:436-440, 788-795, 828-836). The probe, the id of a                 *)
(* DataEncryptionKey, travels NN -> client -> DN, or DN -> DN.              *)
(* The only hunting property is TargetSafe == ~targetFired.                 *)
(*                                                                         *)
(* Source: Apache Hadoop at 734dd8a67cd. Paths:                             *)
(*   hdfs/   = hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/    *)
(*             hadoop/hdfs/                                                 *)
(*   client/ = hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/    *)
(*             apache/hadoop/hdfs/                                          *)
(* Abbreviations (under hdfs/ unless marked client/):                       *)
(*   BTSM  security/token/block/BlockTokenSecretManager.java                *)
(*   BPTSM security/token/block/BlockPoolTokenSecretManager.java            *)
(*   HM    server/blockmanagement/HeartbeatManager.java                     *)
(*   DM    server/blockmanagement/DatanodeManager.java                      *)
(*   DD    server/blockmanagement/DatanodeDescriptor.java                   *)
(*   BM    server/blockmanagement/BlockManager.java                         *)
(*   BMSM  server/blockmanagement/BlockManagerSafeMode.java                 *)
(*   FSN   server/namenode/FSNamesystem.java                                *)
(*   NNRPC server/namenode/NameNodeRpcServer.java                           *)
(*   NN    server/namenode/NameNode.java                                    *)
(*   BPOS  server/datanode/BPOfferService.java                              *)
(*   BPSA  server/datanode/BPServiceActor.java                              *)
(*   DN    server/datanode/DataNode.java                                    *)
(*   DXC   server/datanode/DataXceiver.java                                 *)
(*   SDTS  protocol/datatransfer/sasl/SaslDataTransferServer.java           *)
(*   DFSC  client/DFSClient.java                                            *)
(*   DFSIS client/DFSInputStream.java                                       *)
(*   SDTC  client/protocol/datatransfer/sasl/SaslDataTransferClient.java    *)
(*                                                                         *)
(* Abstractions (modeling-brief.md section 3.2):                            *)
(*  - A key id is <<nn, incarnation, serial>>. Each NN process draws a      *)
(*    fresh random serial in its own range (BTSM:143-154, 190-197;          *)
(*    BM:743-761), so different NNs and incarnations never share an id      *)
(*    (collisions, about 2^-31, are ignored). Within one incarnation        *)
(*    allKeys holds serials 1..top, currentKey = top-1, nextKey = top.      *)
(*  - Key expiry and removal (BTSM:210-219, 234, 266) are not modeled. With *)
(*    synchronized clocks no node drops a key that an unexpired DEK names.  *)
(*  - Time: one interval roll (RollKeys) stands for one keyUpdateInterval   *)
(*    (600 min default). RollRealism encodes what every live DN does in     *)
(*    that time (3 s heartbeats, 120 s RPC timeout).                        *)
(*  - IPC is modeled as delivered or lost (LoseResponse). SASL/DIGEST-MD5   *)
(*    and cipher negotiation do not affect the guard.                       *)
(*  - Every DN holds a replica of the workload's block, and a client's      *)
(*    cached block locations include every DN (they survive NN restarts).   *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    NNs,               \* NameNodes of the one block pool: {n1}; {n1, n2} for HA (Scenario 5)
    DNs,               \* DataNodes
    FirstActive,       \* the NN that starts ACTIVE (non-HA NN is ACTIVE: NN:1194-1198)
    LateDNs,           \* DNs that start after the NNs (Scenario 3: late join)
    SplitRegistration, \* Scenario 3: DM.registerDatanode's export (DM:1209) and its join
                       \*   (DM:1300 / DM:1332-1337) are separate steps
    DekFromStandby,    \* Scenario 5: a standby or observer may answer getDataEncryptionKey
    DnTransferOn,      \* Scenario 4: DN->DN transfers that use a DN-originated DEK
    StartSafeModes,    \* safe-mode states an NN process can start in (BMSM:172-188):
                       \*   "off" for a 1-block image (the workload), "startup" for 2+ blocks
    Null

ASSUME FirstActive \in NNs
ASSUME LateDNs \subseteq DNs
ASSUME SplitRegistration \in BOOLEAN /\ DekFromStandby \in BOOLEAN
       /\ DnTransferOn \in BOOLEAN
ASSUME StartSafeModes \subseteq {"startup", "off"} /\ StartSafeModes # {}

VARIABLES
    \* -- NameNode n: master BlockTokenSecretManager (BM:546, 702-762) and its Monitor
    nnInc,         \* [NNs -> Nat] process incarnation; a restart builds a new master BTSM
    nnTop,         \* [NNs -> Nat] serial of nextKey; currentKey = top-1; allKeys = 1..top
    firstPass,     \* [NNs -> BOOLEAN] HeartbeatManager.Monitor has not run its first pass yet
    sweepPending,  \* [NNs -> BOOLEAN] Monitor rolled (HM:552) but has not swept yet (HM:553-557)
    rolls,         \* [NNs -> Nat] interval rolls by n over all incarnations: the model's clock
    \* -- NameNode n: control state
    nnSafe,        \* [NNs -> {"off","startup","manual"}] FSN.isInSafeMode (FSN:5269-5277)
    nnHA,          \* [NNs -> {"active","standby"}] HA service state
    haEpoch,       \* Nat; grows at each failover. Stands for the txid that orders ACTIVE claims
                   \*   in heartbeat replies (FSN:4505-4507; BPOS:581-586)
    \* -- NameNode n: DatanodeDescriptors
    hbSet,         \* [NNs -> SUBSET DNs] HeartbeatManager.datanodes (HM:65). datanodeMap is the
                   \*   same set here: dead-node expiry (HM:441-535) is not modeled
    needKU,        \* [NNs -> [DNs -> BOOLEAN]] DatanodeDescriptor.needKeyUpdate (DD:185, 280-286)
    brDone,        \* [NNs -> [DNs -> BOOLEAN]] n processed d's full block report since d registered
    \* -- RPCs in flight
    reg,           \* [NNs -> [DNs -> Null \cup RegT]] registerDatanode of d at n in progress
    resp,          \* [NNs -> [DNs -> Null \cup RespT]] heartbeat reply built by n, not yet received
    \* -- DataNode d: block-pool worker BlockTokenSecretManager (DN:2141-2144)
    bpState,       \* [DNs -> {"none","keyed"}] BlockPoolTokenSecretManager.map has the pool
    dnKeys,        \* [DNs -> SUBSET KeyT] worker allKeys (BTSM:81): the guard's operand
    dnCur,         \* [DNs -> KeyT \cup {Null}] worker currentKey (BTSM:79)
    \* -- DataNode d: BPOfferService and its BPServiceActors (one per NN)
    dnUp,          \* [DNs -> BOOLEAN] DataNode process running (xceiver server up, DN:3211)
    bpActive,      \* [DNs -> NNs \cup {Null}] BPOfferService.bpServiceToActive (BPOS:86)
    lastClaim,     \* [DNs -> Nat] BPOfferService.lastActiveClaimTxId (BPOS:103), haEpoch units
    actor,         \* [NNs -> [DNs -> {"conn","reg"}]] BPServiceActor registering
                   \*   (BPSA:302-325, 838-879) or in offerService (BPSA:674-813)
    actorState,    \* [NNs -> [DNs -> {"none","active","standby"}]] BPServiceActor.state
    reReg,         \* [NNs -> [DNs -> BOOLEAN]] command thread is inside reRegister (BPSA:967-984)
    dnQ,           \* [NNs -> [DNs -> Seq(CmdT)]] CommandProcessingThread queue (BPSA:1400-1525)
    \* -- client
    cDek,          \* DFSClient.encryptionKey (DFSC:239): Null or [key, iss, r0]
    \* -- target
    targetFired

nnKeyVars == <<nnInc, nnTop, firstPass, sweepPending, rolls>>
nnCtlVars == <<nnSafe, nnHA, haEpoch>>
nnDnVars  == <<hbSet, needKU, brDone>>
netVars   == <<reg, resp>>
dnKeyVars == <<bpState, dnKeys, dnCur>>
dnActVars == <<dnUp, bpActive, lastClaim, actor, actorState, reReg, dnQ>>
cliVars   == <<cDek>>
vars == <<nnKeyVars, nnCtlVars, nnDnVars, netVars, dnKeyVars, dnActVars,
          cliVars, targetFired>>

-----------------------------------------------------------------------------
(* Types and helpers *)

KeyT  == NNs \X Nat \X Nat                       \* <<nn, incarnation, serial>>
ExpT  == [nn : NNs, inc : Nat, top : Nat]        \* ExportedBlockKeys <<currentKey, allKeys>>
CmdT  == [kind : {"key"}, exp : ExpT] \cup [kind : {"reg"}, exp : {Null}]
RespT == [cmd : {"key"}, exp : ExpT, ha : {"active", "standby"}, ep : Nat]
         \cup [cmd : {"none", "reg"}, exp : {Null}, ha : {"active", "standby"}, ep : Nat]
RegT  == [ph : {"exported", "replied"}, exp : ExpT]
DekT  == [key : KeyT, iss : NNs, r0 : Nat]

Key(n, i, s) == <<n, i, s>>

\* BTSM.exportKeys (BTSM:201-208): ExportedBlockKeys(currentKey, allKeys.values())
Exp(n) == [nn |-> n, inc |-> nnInc[n], top |-> nnTop[n]]
ExpKeys(e) == {Key(e.nn, e.inc, s) : s \in 1..e.top}
ExpCur(e) == Key(e.nn, e.inc, e.top - 1)

\* The NN's currentKey (BTSM:79), named by every DEK it issues (BTSM:536-540)
NNCur(n) == Key(n, nnInc[n], nnTop[n] - 1)

\* RPC handlers of n run only after the Monitor's first pass: the Monitor
\* thread starts in startCommonServices (FSN:1374 -> BM:814 -> HM:116-118) at
\* NN:1009, before rpcServer.start() at NN:1019, and its loop body runs
\* before its first sleep (HM:544-564).
RpcUp(n) == ~firstPass[n]

RespHasKey(r) == IF r = Null THEN FALSE ELSE r.cmd = "key"
HasKeyCmd(q) == \E i \in 1..Len(q) : q[i].kind = "key"
HeadIs(q, k) == IF q = <<>> THEN FALSE ELSE Head(q).kind = k

\* DFSClient.newDataEncryptionKey refetches when expiryDate < now (DFSC:1858-1859).
\* expiryDate = issue time + tokenLifetime (BTSM:540-542); tokenLifetime =
\* keyUpdateInterval = 600 min by default. A DEK issued after the issuer's k-th
\* interval roll is valid until its (k+1)-th roll and has expired by its
\* (k+2)-th roll. In between it may have expired (ClientDropDek).
DekExpired == IF cDek = Null THEN FALSE ELSE rolls[cDek.iss] >= cDek.r0 + 2
DekUsable  == IF cDek = Null THEN FALSE ELSE ~DekExpired

-----------------------------------------------------------------------------
(* Initial state: the workload's second cluster. The NN restarts on an image *)
(* that already holds the test file, with encryption and block tokens on    *)
(* (TestEncryptedTransfer.java:93-99, 131-153). Whether it starts in        *)
(* startup safe mode depends on the image: BMSM.activate (BMSM:172-188)      *)
(* leaves safe mode at once when blockThreshold = (long)(blockTotal *        *)
(* 0.999) (BMSM:290-295; DFSConfigKeys:232) is 0, which the workload's       *)
(* 1-block image gives; an image with 2 or more blocks stays in             *)
(* PENDING_THRESHOLD until block reports arrive. StartSafeModes says which  *)
(* starts a configuration allows.                                           *)

Init ==
    /\ nnInc = [n \in NNs |-> 1]
    /\ nnTop = [n \in NNs |-> 2]     \* generateKeys: currentKey = serial+1, nextKey = serial+2 (BTSM:190-197)
    /\ firstPass = [n \in NNs |-> TRUE]
    /\ sweepPending = [n \in NNs |-> FALSE]
    /\ rolls = [n \in NNs |-> 0]
    /\ nnSafe \in [NNs -> StartSafeModes]   \* BMSM:172-188: thresholds met at activation or not
    /\ nnHA = [n \in NNs |-> IF n = FirstActive THEN "active" ELSE "standby"]
    /\ haEpoch = 1
    /\ hbSet = [n \in NNs |-> {}]
    /\ needKU = [n \in NNs |-> [d \in DNs |-> FALSE]]
    /\ brDone = [n \in NNs |-> [d \in DNs |-> FALSE]]
    /\ reg = [n \in NNs |-> [d \in DNs |-> Null]]
    /\ resp = [n \in NNs |-> [d \in DNs |-> Null]]
    /\ bpState = [d \in DNs |-> "none"]
    /\ dnKeys = [d \in DNs |-> {}]
    /\ dnCur = [d \in DNs |-> Null]
    /\ dnUp = [d \in DNs |-> d \notin LateDNs]
    /\ bpActive = [d \in DNs |-> Null]
    /\ lastClaim = [d \in DNs |-> 0]
    /\ actor = [n \in NNs |-> [d \in DNs |-> "conn"]]
    /\ actorState = [n \in NNs |-> [d \in DNs |-> "none"]]
    /\ reReg = [n \in NNs |-> [d \in DNs |-> FALSE]]
    /\ dnQ = [n \in NNs |-> [d \in DNs |-> <<>>]]
    /\ cDek = Null
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(* DN worker key intake: BTSM.addKeys(exportedKeys, updateCurrentKey),       *)
(* BTSM:228-244, under the worker monitor. removeExpiredKeys() (BTSM:234) is *)
(* not modeled (see the header).                                            *)

AddKeys(d, e, updateCurrentKey) ==
    \* BTSM:235-237: if (updateCurrentKey || currentKey == null) currentKey = exported currentKey
    /\ dnCur' = [dnCur EXCEPT ![d] = IF updateCurrentKey \/ @ = Null THEN ExpCur(e) ELSE @]
    \* BTSM:238-243: put every received key
    /\ dnKeys' = [dnKeys EXCEPT ![d] = @ \cup ExpKeys(e)]

-----------------------------------------------------------------------------
(* The target. The DN-side lookup of a DEK's key id:                         *)
(* SDTS.getEncryptionKeyFromUserName (SDTS:282-293) ->                       *)
(* BPTSM.retrieveDataEncryptionKey (BPTSM:171-174) -> get(bpid)              *)
(* (BPTSM:53-60) -> BTSM.retrieveDataEncryptionKey (BTSM:553-565). The       *)
(* lookup and the throw run under the worker monitor (BTSM:556), which       *)
(* addKeys also holds, so this is one atomic step. Callers (ClientConnect,   *)
(* DnTransfer) model the code path that reaches it.                          *)

TargetCheck(d, id) ==
    IF bpState[d] = "none"
      \* BPTSM:54-58: no worker for the pool -> IllegalArgumentException (not the target)
      THEN UNCHANGED vars
    ELSE IF id \notin dnKeys[d]
      \* BTSM:557-558: key = allKeys.get(keyId); key == null
      THEN IF dnCur[d] # Null
             \* BTSM:559-561: message built with currentKey.getKeyId(), then
             \* throw InvalidEncryptionKeyException  -- the target
             THEN /\ targetFired' = TRUE
                  /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, netVars,
                                 dnKeyVars, dnActVars, cliVars>>
             \* BTSM:561: currentKey == null -> NullPointerException (not the target)
             ELSE UNCHANGED vars
      \* BTSM:564: createPassword(nonce, key) -> the handshake proceeds
      ELSE UNCHANGED vars

\* The same decision as data, for trace validation and probes.
LookupOutcome(d, id) ==
    IF bpState[d] = "none" THEN "no_pool"
    ELSE IF id \notin dnKeys[d]
           THEN IF dnCur[d] # Null THEN "invalid_key" ELSE "npe"
           ELSE "ok"

-----------------------------------------------------------------------------
(* NameNode: key rolls (HeartbeatManager.Monitor.run, HM:543-574)           *)

\* First iteration of the Monitor loop. lastBlockKeyUpdate is still 0
\* (HM:540), so shouldUpdateBlockKey(now - 0) (HM:552; BM:808-810) calls
\* updateKeys(now) (BTSM:250-255), which rolls iff the host's monotonic
\* uptime exceeds keyUpdateInterval: either outcome. RPC is not up yet
\* (RpcUp), so hbSet[n] is empty and the sweep (HM:553-557) flags nobody.
MonitorFirstPass(n) ==
    /\ firstPass[n]
    /\ \E roll \in BOOLEAN :
         \* BTSM:260-281: currentKey := nextKey, new nextKey
         nnTop' = [nnTop EXCEPT ![n] = IF roll THEN @ + 1 ELSE @]
    /\ firstPass' = [firstPass EXCEPT ![n] = FALSE]
    /\ UNCHANGED <<nnInc, sweepPending, rolls, nnCtlVars, nnDnVars, netVars,
                   dnKeyVars, dnActVars, cliVars, targetFired>>

\* Later iterations: roll once keyUpdateInterval has elapsed since the last
\* roll (HM:552; BM:808-810; BTSM:250-255). updateKeys() (BTSM:260-281):
\* the retiring currentKey stays in allKeys (BTSM:268-270), currentKey :=
\* nextKey (BTSM:272-274), and a fresh nextKey is generated (BTSM:276-279).
\* Neither the roll nor the sweep checks safe mode or HA state.
RollRealism(n) ==
    \* A full interval (600 min) has passed since the previous roll. Every DN
    \* that is up and in n's offerService loop has, in that time:
    /\ \A d \in DNs :
         IF dnUp[d] /\ actor[n][d] = "reg"
           THEN \* re-registered with this incarnation (REGISTER on its next heartbeat, DM:1864-1878)
                /\ d \in hbSet[n]
                \* sent its first block report (scheduled at registration, BPSA:873-878)
                /\ brDone[n][d]
                \* received or lost any reply carrying a push (RPC timeout 120 s)
                /\ ~RespHasKey(resp[n][d])
                \* applied any queued push (command thread, BPSA:1427-1445)
                /\ ~HasKeyCmd(dnQ[n][d])
                \* consumed the last sweep's flag, unless safe mode suppresses pushes (DM:1882-1886)
                /\ IF nnSafe[n] = "off" THEN ~needKU[n][d] ELSE TRUE
           ELSE TRUE
    \* A registration RPC lasts milliseconds: at most one roll falls inside one.
    /\ \A d \in DNs : IF reg[n][d] = Null THEN TRUE ELSE reg[n][d].exp.top = nnTop[n]

RollKeys(n) ==
    /\ RpcUp(n)
    /\ ~sweepPending[n]
    /\ RollRealism(n)
    /\ nnTop' = [nnTop EXCEPT ![n] = @ + 1]
    /\ rolls' = [rolls EXCEPT ![n] = @ + 1]
    /\ sweepPending' = [sweepPending EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<nnInc, firstPass, nnCtlVars, nnDnVars, netVars, dnKeyVars,
                   dnActVars, cliVars, targetFired>>

\* HM:553-557: synchronized (HeartbeatManager.this) {
\*   for (d : datanodes) d.setNeedKeyUpdate(true); }  then HM:558.
SweepNeedKeyUpdate(n) ==
    /\ sweepPending[n]
    /\ needKU' = [needKU EXCEPT ![n] =
                    [d \in DNs |-> IF d \in hbSet[n] THEN TRUE ELSE @[d]]]
    /\ sweepPending' = [sweepPending EXCEPT ![n] = FALSE]
    /\ UNCHANGED <<nnInc, nnTop, firstPass, rolls, nnCtlVars, hbSet, brDone,
                   netVars, dnKeyVars, dnActVars, cliVars, targetFired>>

-----------------------------------------------------------------------------
(* Heartbeats: build (NN), deliver or lose, apply (DN command thread)       *)

\* BPSA.offerService -> sendHeartBeat (BPSA:694-711, 545-591) ->
\* NNRPC.sendHeartbeat (NNRPC:1626-1640) -> FSN.handleHeartbeat
\* (FSN:4484-4517, BM read lock) -> DM.handleHeartbeat (DM:1856-2006).
\* Send and NN handling are one step: the actor thread is blocked in the RPC.
NNHandleHeartbeat(n, d) ==
    /\ RpcUp(n)
    /\ dnUp[d]
    /\ actor[n][d] = "reg"                \* offerService runs after register (BPSA:302-325)
    /\ resp[n][d] = Null                  \* one outstanding heartbeat per actor
    /\ LET ha == nnHA[n]                  \* NNHAStatusHeartbeat (FSN:4505-4507)
       IN
       IF d \notin hbSet[n]
         \* DM:1864-1878: unknown node (getDatanode == null) or not alive
         \* (!isRegistered, DD:1134-1136) -> RegisterCommand.REGISTER
         THEN /\ resp' = [resp EXCEPT ![n][d] =
                            [cmd |-> "reg", exp |-> Null, ha |-> ha, ep |-> haEpoch]]
              /\ UNCHANGED needKU
       ELSE IF nnSafe[n] # "off"
         \* DM:1882-1886: in safe mode return no commands; needKeyUpdate stays set
         THEN /\ resp' = [resp EXCEPT ![n][d] =
                            [cmd |-> "none", exp |-> Null, ha |-> ha, ep |-> haEpoch]]
              /\ UNCHANGED needKU
       ELSE IF needKU[n][d]
         \* DM:1971 -> BM.addKeyUpdateCommand (BM:1671-1677): push
         \* KeyUpdateCommand(exportKeys()) and clear the flag when the reply is built
         THEN /\ resp' = [resp EXCEPT ![n][d] =
                            [cmd |-> "key", exp |-> Exp(n), ha |-> ha, ep |-> haEpoch]]
              /\ needKU' = [needKU EXCEPT ![n][d] = FALSE]
         ELSE /\ resp' = [resp EXCEPT ![n][d] =
                            [cmd |-> "none", exp |-> Null, ha |-> ha, ep |-> haEpoch]]
              /\ UNCHANGED needKU
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, hbSet, brDone, reg, dnKeyVars,
                   dnActVars, cliVars, targetFired>>

\* BPSA:711-756 after sendHeartBeat returns.
DNReceiveResponse(n, d) ==
    /\ dnUp[d]
    /\ resp[n][d] # Null
    /\ LET r == resp[n][d]
           claims == r.ha = "active"                 \* BPOS:583-584
           thinks == bpActive[d] = n                 \* BPOS:585
           recent == r.ep > lastClaim[d]             \* BPOS:586
           act == IF claims /\ ~thinks
                    THEN IF recent THEN n ELSE bpActive[d]  \* BPOS:588-607 (stale claim: :591-598)
                  ELSE IF ~claims /\ thinks
                    THEN Null                               \* BPOS:608-612
                  ELSE bpActive[d]
       IN
       \* BPOS.updateActorStatesFromHeartbeat (BPOS:576-621), called at BPSA:733-734
       /\ bpActive' = [bpActive EXCEPT ![d] = act]
       /\ lastClaim' = [lastClaim EXCEPT ![d] = IF act = n THEN r.ep ELSE @]   \* BPOS:614-617
       \* BPSA:735-740: state = HA state from the reply
       /\ actorState' = [actorState EXCEPT ![n][d] = r.ha]
       \* BPSA:745-756: a KeyUpdateCommand goes to the queue head
       \* (enqueueFirst, BPSA:748-751, 1499-1508); REGISTER to the tail
       \* (enqueue, BPSA:755, 1519-1524)
       /\ dnQ' = [dnQ EXCEPT ![n][d] =
                    CASE r.cmd = "key" -> <<[kind |-> "key", exp |-> r.exp]>> \o @
                      [] r.cmd = "reg" -> Append(@, [kind |-> "reg", exp |-> Null])
                      [] OTHER         -> @]
       /\ resp' = [resp EXCEPT ![n][d] = Null]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, reg, dnKeyVars, dnUp, actor,
                   reReg, cliVars, targetFired>>

\* Scenario 2 (fault). The heartbeat RPC fails after DM.handleHeartbeat built
\* the reply and cleared needKeyUpdate (BM:1674-1676): reply lost or IPC
\* timeout (Client.java:1294-1295), FSN.requestBlockReportLeaseId throwing
\* after the commands were built (FSN:4499-4502), or handleRollingUpgradeStatus
\* throwing before the enqueue (BPSA:742-744). The DN only logs it
\* (BPSA:805-807); nothing re-arms the flag before the next sweep.
LoseResponse(n, d) ==
    /\ resp[n][d] # Null
    /\ resp' = [resp EXCEPT ![n][d] = Null]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, reg, dnKeyVars, dnActVars,
                   cliVars, targetFired>>

\* CommandProcessingThread.processQueue takes the head (BPSA:1427-1431) ->
\* processCommand (BPSA:1453-1484) -> BPOS.processCommandFromActor
\* (BPOS:671-705): isActiveActor = (actor == bpServiceToActive) is read when
\* the command is processed (BPOS:692-698). DNA_ACCESSKEYUPDATE:
\* addKeys(..., true) from the active (BPOS:788-795), addKeys(..., false)
\* from a standby (BPOS:828-836).
DNProcessKeyCommand(n, d) ==
    /\ dnUp[d]
    /\ ~reReg[n][d]                       \* the command thread is not inside reRegister
    /\ HeadIs(dnQ[n][d], "key")
    /\ AddKeys(d, Head(dnQ[n][d]).exp, bpActive[d] = n)
    /\ dnQ' = [dnQ EXCEPT ![n][d] = Tail(@)]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, netVars, bpState, dnUp,
                   bpActive, lastClaim, actor, actorState, reReg, cliVars,
                   targetFired>>

\* The command thread takes a REGISTER (BPSA:1430) -> BPOS:681-688 ->
\* actor.reRegister() (BPSA:967-984), which blocks the thread until
\* registration succeeds (BPSA:845-864 retries on IOException).
DNTakeRegisterCommand(n, d) ==
    /\ dnUp[d]
    /\ ~reReg[n][d]
    /\ HeadIs(dnQ[n][d], "reg")
    /\ dnQ' = [dnQ EXCEPT ![n][d] = Tail(@)]
    /\ reReg' = [reReg EXCEPT ![n][d] = TRUE]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, netVars, dnKeyVars, dnUp,
                   bpActive, lastClaim, actor, actorState, cliVars, targetFired>>

\* Full block report after a heartbeat granted a lease (BPSA:706-723,
\* 766-776) -> NNRPC.blockReport (NNRPC:1643-1690) -> BM.processReport ->
\* BMSM.incrementSafeBlockCount (BMSM:446-468) -> checkSafeMode
\* (BMSM:206-231). Thresholds met and extension 0 (MiniDFSCluster) -> leave
\* startup safe mode. The lease handshake is not modeled.
DNBlockReport(n, d) ==
    /\ RpcUp(n)
    /\ dnUp[d]
    /\ actor[n][d] = "reg"
    /\ d \in hbSet[n]                     \* else NNRPC:1672-1676 answers REGISTER
    /\ ~brDone[n][d]
    /\ brDone' = [brDone EXCEPT ![n][d] = TRUE]
    /\ nnSafe' = [nnSafe EXCEPT ![n] = IF @ = "startup" THEN "off" ELSE @]
    /\ UNCHANGED <<nnKeyVars, nnHA, haEpoch, hbSet, needKU, netVars, dnKeyVars,
                   dnActVars, cliVars, targetFired>>

-----------------------------------------------------------------------------
(* Registration: NN side (export, join), then DN side (worker + addKeys)    *)

\* Started by the actor (connectToNNAndHandshake, BPSA:302-325 -> register,
\* BPSA:838-879) or by the command thread inside reRegister (BPSA:967-984).
\* NNRPC.registerDatanode (NNRPC:1617-1623) -> FSN.registerDatanode
\* (FSN:4454-4461, BM write lock) -> DM.registerDatanode (DM:1188-1361).
NNRegisterDatanode(n, d) ==
    /\ RpcUp(n)
    /\ dnUp[d]
    /\ reg[n][d] = Null
    /\ IF actor[n][d] = "conn" THEN TRUE ELSE reReg[n][d]
    \* Handshake before the first register: BPSA:308 retrieveNamespaceInfo,
    \* BPSA:317 -> BPOS.verifyAndSetNamespaceInfo (BPOS:386-390), BPSA:318
    \* state = nsInfo.getState(). reRegister does not update state (BPSA:967-984).
    /\ IF actor[n][d] = "conn"
         THEN /\ actorState' = [actorState EXCEPT ![n][d] = nnHA[n]]
              /\ bpActive' = [bpActive EXCEPT ![d] =
                                IF nnHA[n] = "active" /\ @ = Null THEN n ELSE @]
         ELSE UNCHANGED <<actorState, bpActive>>
    /\ IF SplitRegistration
         \* DM:1209 nodeReg.setExportedKeys(blockManager.getBlockKeys()) only;
         \* the join is NNRegJoin
         THEN /\ reg' = [reg EXCEPT ![n][d] = [ph |-> "exported", exp |-> Exp(n)]]
              /\ UNCHANGED <<hbSet, brDone>>
         \* DM:1209 export, then the join: known node -> heartbeatManager.register
         \* (DM:1300; HM:231-239 adds it if not alive); new node -> addDatanode
         \* (DM:1332) and heartbeatManager.addDatanode (DM:1337; HM:245-249).
         \* updateRegInfo resets block-report counts (DD:1003-1014); a new
         \* descriptor starts with needKeyUpdate = false (DD:185); a known
         \* one keeps its flag.
         ELSE /\ reg' = [reg EXCEPT ![n][d] = [ph |-> "replied", exp |-> Exp(n)]]
              /\ hbSet' = [hbSet EXCEPT ![n] = @ \cup {d}]
              /\ brDone' = [brDone EXCEPT ![n][d] = FALSE]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, needKU, resp, dnKeyVars, dnUp,
                   lastClaim, actor, reReg, dnQ, cliVars, targetFired>>

\* Scenario 3 only (SplitRegistration). The join after the export
\* (DM:1213-1300 or DM:1314-1341); a roll and sweep can fall in between,
\* since they take only the BTSM and HeartbeatManager monitors, not the FSN
\* lock (HM:552-557; FSN:4454-4461).
NNRegJoin(n, d) ==
    /\ reg[n][d] # Null
    /\ reg[n][d].ph = "exported"
    /\ hbSet' = [hbSet EXCEPT ![n] = @ \cup {d}]
    /\ brDone' = [brDone EXCEPT ![n][d] = FALSE]
    /\ reg' = [reg EXCEPT ![n][d] = [@ EXCEPT !.ph = "replied"]]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, needKU, resp, dnKeyVars, dnActVars,
                   cliVars, targetFired>>

\* DN side after registerDatanode returns (BPSA:848-871):
\* BPOS.registrationSucceeded (BPOS:422-445) -> DN.bpRegistrationSucceeded
\* (DN:2097-2108) -> registerBlockPoolWithSecretManager creates the worker if
\* the pool is absent (DN:2130-2144) -> addKeys(export, updateCurrentKey =
\* state == null || state == ACTIVE) (BPOS:436-440). Worker creation and
\* addKeys are one step here; the window between them only yields the NPE
\* sibling (brief T-1), never the target.
DNRegistrationSucceeded(n, d) ==
    /\ dnUp[d]
    /\ reg[n][d] # Null
    /\ reg[n][d].ph = "replied"
    /\ AddKeys(d, reg[n][d].exp, actorState[n][d] \in {"none", "active"})
    /\ bpState' = [bpState EXCEPT ![d] = "keyed"]
    /\ actor' = [actor EXCEPT ![n][d] = "reg"]
    /\ reReg' = [reReg EXCEPT ![n][d] = FALSE]
    /\ reg' = [reg EXCEPT ![n][d] = Null]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, resp, dnUp, bpActive,
                   lastClaim, actorState, dnQ, cliVars, targetFired>>

-----------------------------------------------------------------------------
(* Faults and administrative events                                         *)

\* Scenario 4 (fault). NN process restart: a new master BTSM (BM:546,
\* 702-762) with a fresh random serial range (BTSM:154) and generateKeys
\* (BTSM:174-198); empty DatanodeManager/HeartbeatManager; startup safe mode
\* or not, as in Init (BMSM:172-188, 290-295); the Monitor starts over
\* (HM:540). Connections reset:
\* in-flight replies and registration RPCs at n are lost (the DN retries:
\* BPSA:845-864, 805-807). DN-side queues survive. The HA role is kept:
\* restarts are hunted only without HA (Scenario 4; a non-HA NN is ACTIVE).
NNRestart(n) ==
    /\ nnInc' = [nnInc EXCEPT ![n] = @ + 1]
    /\ nnTop' = [nnTop EXCEPT ![n] = 2]
    /\ firstPass' = [firstPass EXCEPT ![n] = TRUE]
    /\ sweepPending' = [sweepPending EXCEPT ![n] = FALSE]
    /\ \E s \in StartSafeModes : nnSafe' = [nnSafe EXCEPT ![n] = s]
    /\ hbSet' = [hbSet EXCEPT ![n] = {}]
    /\ needKU' = [needKU EXCEPT ![n] = [d \in DNs |-> FALSE]]
    /\ brDone' = [brDone EXCEPT ![n] = [d \in DNs |-> FALSE]]
    /\ reg' = [reg EXCEPT ![n] = [d \in DNs |-> Null]]
    /\ resp' = [resp EXCEPT ![n] = [d \in DNs |-> Null]]
    /\ UNCHANGED <<rolls, nnHA, haEpoch, dnKeyVars, dnActVars, cliVars,
                   targetFired>>

\* Scenario 4 (fault). DataNode process restart: a new DataNode with an empty
\* BlockPoolTokenSecretManager (DN:1942), so no worker, keys or currentKey;
\* the actors reconnect (BPSA:302-325) with state null; command queues and
\* the DN ends of RPCs are gone. The NN keeps d's descriptor and flag (no
\* dead-node expiry inside the window). A DN does not restart in the middle
\* of a split registration (Scenario 3 runs without restarts).
DNRestart(d) ==
    /\ dnUp[d]
    /\ \A n \in NNs : IF reg[n][d] = Null THEN TRUE ELSE reg[n][d].ph = "replied"
    /\ bpState' = [bpState EXCEPT ![d] = "none"]
    /\ dnKeys' = [dnKeys EXCEPT ![d] = {}]
    /\ dnCur' = [dnCur EXCEPT ![d] = Null]
    /\ bpActive' = [bpActive EXCEPT ![d] = Null]
    /\ lastClaim' = [lastClaim EXCEPT ![d] = 0]
    /\ actor' = [n \in NNs |-> [actor[n] EXCEPT ![d] = "conn"]]
    /\ actorState' = [n \in NNs |-> [actorState[n] EXCEPT ![d] = "none"]]
    /\ reReg' = [n \in NNs |-> [reReg[n] EXCEPT ![d] = FALSE]]
    /\ dnQ' = [n \in NNs |-> [dnQ[n] EXCEPT ![d] = <<>>]]
    /\ resp' = [n \in NNs |-> [resp[n] EXCEPT ![d] = Null]]
    /\ reg' = [n \in NNs |-> [reg[n] EXCEPT ![d] = Null]]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, dnUp, cliVars, targetFired>>

\* Scenario 3: a DN that starts after the NN (late join). Its state is the
\* fresh state of Init.
DNStart(d) ==
    /\ ~dnUp[d]
    /\ dnUp' = [dnUp EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, netVars, dnKeyVars,
                   bpActive, lastClaim, actor, actorState, reReg, dnQ,
                   cliVars, targetFired>>

\* Scenarios 1 and 5 (fault). Manual (dfsadmin -safemode enter,
\* FSN.setSafeMode FSN:5199-5210) or resource-low safe mode:
\* FSN.enterSafeMode (FSN:5283-5306) sets the flag (FSN:5299). It stops only
\* the delegation-token secret manager (FSN:5288, 1352-1356), not the block
\* key Monitor.
EnterSafeMode(n) ==
    /\ RpcUp(n)
    /\ nnSafe[n] = "off"
    /\ nnSafe' = [nnSafe EXCEPT ![n] = "manual"]
    /\ UNCHANGED <<nnKeyVars, nnHA, haEpoch, nnDnVars, netVars, dnKeyVars,
                   dnActVars, cliVars, targetFired>>

\* FSN.leaveSafeMode (FSN:5312-5327) clears the flag (FSN:5320).
LeaveSafeMode(n) ==
    /\ nnSafe[n] = "manual"
    /\ nnSafe' = [nnSafe EXCEPT ![n] = "off"]
    /\ UNCHANGED <<nnKeyVars, nnHA, haEpoch, nnDnVars, netVars, dnKeyVars,
                   dnActVars, cliVars, targetFired>>

\* Scenario 5 (fault). Failover n -> m. m runs FSN.startActiveServices
\* (FSN:1412-1430) -> DM.markAllDatanodesStaleAndSetKeyUpdateIfNeed
\* (DM:2092-2104): needKeyUpdate := true for every node in datanodeMap.
\* Both NNs keep their own Monitor and key stream (HM:116-118 is a common
\* service, FSN:1374); m's ACTIVE claims carry a higher txid (haEpoch).
Failover(n, m) ==
    /\ n # m
    /\ nnHA[n] = "active"
    /\ nnHA[m] = "standby"
    /\ RpcUp(m)
    /\ nnHA' = [nnHA EXCEPT ![n] = "standby", ![m] = "active"]
    /\ haEpoch' = haEpoch + 1
    /\ needKU' = [needKU EXCEPT ![m] =
                    [d \in DNs |-> IF d \in hbSet[m] THEN TRUE ELSE @[d]]]
    /\ UNCHANGED <<nnKeyVars, nnSafe, hbSet, brDone, netVars, dnKeyVars,
                   dnActVars, cliVars, targetFired>>

-----------------------------------------------------------------------------
(* Client and DN-originated DEKs; the paths that reach the target           *)

\* DFSClient.newDataEncryptionKey (DFSC:1855-1868) fetches when the cache is
\* null or expired (DFSC:1858-1859): ClientProtocol.getDataEncryptionKey ->
\* NNRPC.getDataEncryptionKey (NNRPC:1939-1943; only checkNNStartup, no
\* safe-mode or HA operation check) -> BM.generateDataEncryptionKey
\* (BM:1680-1686) -> BTSM.generateDataEncryptionKey (BTSM:532-543): keyId =
\* currentKey. The client's proxy targets the active; with DekFromStandby a
\* standby or observer may answer (stale proxy; @ReadOnly(isCoordinated)).
ClientGetDek(n) ==
    /\ RpcUp(n)
    /\ IF cDek = Null THEN TRUE ELSE DekExpired
    /\ IF nnHA[n] = "active" THEN TRUE ELSE DekFromStandby
    /\ cDek' = [key |-> NNCur(n), iss |-> n, r0 |-> rolls[n]]
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, netVars, dnKeyVars,
                   dnActVars, targetFired>>

\* The cached DEK is dropped: a new DFSClient (empty cache), the DEK's expiry
\* passed (DFSC:1858-1859; possible after the issuer's next interval roll),
\* or clearDataEncryptionKey (DFSC:1837-1842) after a key error
\* (DFSIS:663-669).
ClientDropDek ==
    /\ cDek # Null
    /\ cDek' = Null
    /\ UNCHANGED <<nnKeyVars, nnCtlVars, nnDnVars, netVars, dnKeyVars,
                   dnActVars, targetFired>>

\* The workload's path. A client read or checksum connection:
\* DFSIS.blockSeekTo (DFSIS:609-683) -> getBlockReader -> SASL user name
\* keyId:bpid:nonce from the cached DEK (SDTC:343-350) -> DXC.run (DXC:236-238)
\* -> SDTS.receive (SDTS:117-124, encryption on) -> getEncryptedStreams
\* (SDTS:170-194; the peer is untrusted in workload invocation [1]) -> the
\* password callback (SDTS:185-191) -> TargetCheck.
ClientConnect(d) ==
    /\ dnUp[d]
    /\ DekUsable
    /\ TargetCheck(d, cDek.key)

\* Scenario 4: a DN->DN transfer or pipeline mirror from s to d. The DEK is
\* made by s's worker from its own currentKey
\* (DN.getDataEncryptionKeyFactoryForBlock DN:3174-3184 ->
\* BPTSM.generateDataEncryptionKey BPTSM:167-169 -> BTSM:532-543), with no
\* refetch path.
DnTransfer(s, d) ==
    /\ DnTransferOn
    /\ s # d
    /\ dnUp[s]
    /\ dnUp[d]
    /\ bpState[s] = "keyed"
    /\ dnCur[s] # Null
    /\ TargetCheck(d, dnCur[s])

-----------------------------------------------------------------------------

Next ==
    /\ ~targetFired
    /\ \/ \E n \in NNs :
            \/ MonitorFirstPass(n)
            \/ RollKeys(n)
            \/ SweepNeedKeyUpdate(n)
            \/ NNRestart(n)
            \/ EnterSafeMode(n)
            \/ LeaveSafeMode(n)
            \/ ClientGetDek(n)
       \/ \E n, m \in NNs : Failover(n, m)
       \/ \E n \in NNs, d \in DNs :
            \/ NNHandleHeartbeat(n, d)
            \/ DNReceiveResponse(n, d)
            \/ LoseResponse(n, d)
            \/ DNProcessKeyCommand(n, d)
            \/ DNTakeRegisterCommand(n, d)
            \/ DNBlockReport(n, d)
            \/ NNRegisterDatanode(n, d)
            \/ NNRegJoin(n, d)
            \/ DNRegistrationSucceeded(n, d)
       \/ \E d \in DNs :
            \/ DNRestart(d)
            \/ DNStart(d)
            \/ ClientConnect(d)
       \/ \E s, d \in DNs : DnTransfer(s, d)
       \/ ClientDropDek

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties                                                                *)

\* The oracle: the target's failing branch never runs.
TargetSafe == ~targetFired

TypeOK ==
    /\ \A n \in NNs :
         /\ nnInc[n] \in Nat /\ nnInc[n] >= 1
         /\ nnTop[n] \in Nat /\ nnTop[n] >= 2
         /\ firstPass[n] \in BOOLEAN
         /\ sweepPending[n] \in BOOLEAN
         /\ rolls[n] \in Nat
         /\ nnSafe[n] \in {"off", "startup", "manual"}
         /\ nnHA[n] \in {"active", "standby"}
         /\ hbSet[n] \subseteq DNs
         /\ \A d \in DNs :
              /\ needKU[n][d] \in BOOLEAN
              /\ brDone[n][d] \in BOOLEAN
              /\ reg[n][d] = Null \/ reg[n][d] \in RegT
              /\ resp[n][d] = Null \/ resp[n][d] \in RespT
              /\ actor[n][d] \in {"conn", "reg"}
              /\ actorState[n][d] \in {"none", "active", "standby"}
              /\ reReg[n][d] \in BOOLEAN
              /\ \A i \in 1..Len(dnQ[n][d]) : dnQ[n][d][i] \in CmdT
    /\ haEpoch \in Nat
    /\ \A d \in DNs :
         /\ bpState[d] \in {"none", "keyed"}
         /\ \A k \in dnKeys[d] : k \in KeyT
         /\ dnCur[d] = Null \/ dnCur[d] \in KeyT
         /\ dnUp[d] \in BOOLEAN
         /\ bpActive[d] = Null \/ bpActive[d] \in NNs
         /\ lastClaim[d] \in Nat
    /\ cDek = Null \/ cDek \in DekT
    /\ targetFired \in BOOLEAN

\* Structural sanity: every key a DN, the client or a message holds came from
\* an NN generator, and an export holds only keys its NN held when it was
\* taken ("a message carries only values its sender held").
KeyFromNN(k) ==
    /\ k[1] \in NNs
    /\ k[2] \in 1..nnInc[k[1]]
    /\ k[3] >= 1
    /\ k[2] = nnInc[k[1]] => k[3] <= nnTop[k[1]]

ExpFromNN(e, n) ==
    /\ e.nn = n
    /\ e.inc \in 1..nnInc[n]
    /\ e.top >= 2
    /\ e.inc = nnInc[n] => e.top <= nnTop[n]

KeyProvenance ==
    /\ \A d \in DNs :
         /\ \A k \in dnKeys[d] : KeyFromNN(k)
         \* worker consistency: currentKey is one of allKeys; a pool entry
         \* exists exactly when the worker has been keyed (DN:2141-2144 and
         \* BPOS:439-440 run in one step here)
         /\ dnCur[d] # Null => dnCur[d] \in dnKeys[d]
         /\ (bpState[d] = "none") <=> (dnCur[d] = Null)
         /\ bpState[d] = "none" => dnKeys[d] = {}
    /\ cDek # Null => (KeyFromNN(cDek.key) /\ cDek.key[1] = cDek.iss)
    /\ \A n \in NNs, d \in DNs :
         /\ RespHasKey(resp[n][d]) => ExpFromNN(resp[n][d].exp, n)
         /\ reg[n][d] # Null =>
              (ExpFromNN(reg[n][d].exp, n) /\ reg[n][d].exp.inc = nnInc[n])
         /\ \A i \in 1..Len(dnQ[n][d]) :
              dnQ[n][d][i].kind = "key" => ExpFromNN(dnQ[n][d][i].exp, n)

\* tla-patterns.md section 2 probe (temporary invariant; TLC must VIOLATE it):
\* some reachable state lets the workload's path run the worker lookup
\* (BTSM:557) at a DN with a keyed worker.
TargetReached == ~(\E d \in DNs : dnUp[d] /\ DekUsable /\ bpState[d] = "keyed")

=============================================================================
