-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-12.  Target: BlockTokenSecretManager.retrievePassword        *)
(* (BTSM:507-523) throws InvalidToken at BTSM:518 (stack frame :520) when  *)
(* `key = allKeys.get(identifier.getKeyId())` is null (BTSM:513-517).      *)
(*                                                                         *)
(* Category A (distributed, message passing).  The guard compares the      *)
(* issuer's currentKey (a DataNode worker BTSM, or the NameNode master     *)
(* BTSM) with the verifier DataNode's allKeys.  Nothing but NN pushes keeps *)
(* them consistent: key exports in heartbeat replies (KeyUpdateCommand)    *)
(* and in registration replies.                                            *)
(*                                                                         *)
(* Path abbreviations (all under hadoop-hdfs-project/hadoop-hdfs/src/main/ *)
(* java/org/apache/hadoop/hdfs/ unless stated), pinned at 734dd8a67cd:     *)
(*   BTSM  security/token/block/BlockTokenSecretManager.java   (target)    *)
(*   BPTSM security/token/block/BlockPoolTokenSecretManager.java           *)
(*   BM    server/blockmanagement/BlockManager.java                        *)
(*   DM    server/blockmanagement/DatanodeManager.java                     *)
(*   HBM   server/blockmanagement/HeartbeatManager.java                    *)
(*   DD    server/blockmanagement/DatanodeDescriptor.java                  *)
(*   BMSM  server/blockmanagement/BlockManagerSafeMode.java                *)
(*   RW    server/blockmanagement/ReplicationWork.java                     *)
(*   FSN   server/namenode/FSNamesystem.java                               *)
(*   BPOS  server/datanode/BPOfferService.java                             *)
(*   BPSA  server/datanode/BPServiceActor.java                             *)
(*   DN    server/datanode/DataNode.java                                   *)
(*   DXC   server/datanode/DataXceiver.java                                *)
(*   WL    src/test/java/org/apache/hadoop/hdfs/server/datanode/           *)
(*         TestAdhocWorkload12.java   (the workload test)                  *)
(*   common hadoop-common-project/hadoop-common/src/main/java/org/apache/  *)
(*         hadoop/                                                         *)
(*                                                                         *)
(* Time: `now` counts ticks of one token lifetime L (1 min in the          *)
(* workload).  Heartbeats (3 s), the Monitor loop (5 s), RPCs, DataTransfer *)
(* connect+mint and the verifier's check are all far shorter than one      *)
(* tick, so they happen between ticks; `TickRealism` (below) says what must *)
(* have happened before the clock may advance.  Key and token expiry use   *)
(* the wall clock (Timer.now / Time.now), rotation uses the monotonic      *)
(* clock (HBM:547); the workload runs in one JVM, so one `now` serves both. *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    DN,           \* DataNodes (MC: {s, t}; s = transfer source, t = verifier)
    XferIds,      \* slots for token-carrying operations (DN->DN transfers, client ops)
    I,            \* dfs.block.access.key.update.interval, in ticks (BM:721-723, 754-760)
    L,            \* dfs.block.access.token.lifetime, in ticks (BM:724-726, 754-760)
    MaxTime,      \* bound on `now`
    SerialStart,  \* random serial of the first NN incarnation (BTSM:154); 0 in MC
    KeyBase,      \* key-id stride between NN incarnations (fresh random serial per BTSM)
    MaxEpoch,     \* bound on NN incarnations (finite key space)
    Sources,      \* DNs the NN may pick as DNA_TRANSFER source
    Targets,      \* DNs the NN may pick as transfer target / a client may read from
    LossyDNs,     \* Scenario 2/4: DNs whose heartbeat replies may be lost
    StallDNs,     \* Scenario 2 variant: DNs whose command-processing thread may stall
    DeadDNs,      \* Scenario 3a: DNs that may be declared dead and then rejoin
    RestartDNs,   \* Scenario 6: DNs that may restart
    ClientOps,    \* Scenario 1 variant: NN-issued tokens (client reads) checked at DNs
    TestActions   \* workload-test-only actions (trace validation); FALSE in every MC cfg

ASSUME I \in Nat /\ L \in Nat /\ I > L /\ L >= 1
ASSUME MaxTime \in Nat /\ MaxEpoch \in Nat \ {0} /\ KeyBase \in Nat \ {0}
ASSUME Sources \subseteq DN /\ Targets \subseteq DN
ASSUME LossyDNs \subseteq DN /\ StallDNs \subseteq DN /\ DeadDNs \subseteq DN /\ RestartDNs \subseteq DN
ASSUME ClientOps \in BOOLEAN /\ TestActions \in BOOLEAN

VARIABLES
    \* ---- NameNode: master BTSM and HeartbeatManager.Monitor ----------------
    now,            \* wall clock, ticks of L
    lastRot,        \* Monitor.lastBlockKeyUpdate (HBM:540, 558)
    rotPending,     \* Monitor between the rotation (HBM:552) and the marking loop (HBM:553-558)
    nnEpoch,        \* NN incarnation (a restarted NN builds a new BTSM, BM:546)
    nnSerial,       \* master serialNo (BTSM:78, 161-167)
    nnCur,          \* master currentKey id (BTSM:79)
    nnNext,         \* master nextKey id (BTSM:80)
    nnKeys,         \* master allKeys: key id -> expiry tick (BTSM:81)
    safeMode,       \* "off" | "manual" | "startup" (FSN:5269-5277)
    \* ---- NameNode: per-DN descriptor -----------------------------------
    inHM,           \* registered and alive, i.e. in HeartbeatManager.datanodes (DD:182-184, 1134-1136)
    needKeyUpdate,  \* DD.needKeyUpdate (DD:185, 280-286)
    choosable,      \* has NORMAL storages with capacity: a transfer target (DD:816-841)
    \* ---- DataNode: worker BTSM, BPOfferService, actor, CPT ----------------
    dnBpReg,        \* BPOfferService.bpRegistration != null (BPOS:74, 432)
    dnTokEn,        \* DataNode.isBlockTokenEnabled (DN:430, 2118-2120)
    dnBTSM,         \* BPTSM holds a BTSM for the pool (BPTSM:48-64; DN:2130-2144)
    dnCur,          \* worker currentKey id, NoKey if null (BTSM:79, 235-237)
    dnKeys,         \* worker allKeys: key id -> expiry tick (BTSM:81, 228-244)
    cmdQ,           \* CommandProcessingThread queue (BPSA:1400-1525)
    stalled,        \* CPT stuck in a long command (Scenario 2 variant)
    regStage,       \* DN registration progress (BPSA:838-879 -> BPOS:422-445)
    regExport,      \* exported keys carried by the registration reply (DM:1209)
    \* ---- heartbeat RPC on the actor channel --------------------------------
    hbStage,        \* "idle" | "exported" (NN handler between BM:1675 and 1676) | "inflight"
    hbResp,         \* commands of the reply
    \* ---- workload test thread (trace validation only) --------------------
    th,             \* [st, dn, cmds]: the test's direct heartbeat (WL:152-167)
    \* ---- token-carrying operations ------------------------------------------
    xf,             \* XferIds -> [src, dst, st, key, exp]
    \* ---- oracle ------------------------------------------------------------
    targetFired

nnVars    == <<lastRot, rotPending, nnEpoch, nnSerial, nnCur, nnNext, nnKeys, safeMode>>
descVars  == <<inHM, needKeyUpdate, choosable>>
keyVars   == <<dnCur, dnKeys>>
dnRegVars == <<dnBpReg, dnTokEn, dnBTSM, regStage, regExport>>
cptVars   == <<cmdQ, stalled>>
hbVars    == <<hbStage, hbResp>>
vars == <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, th, xf, targetFired>>

-----------------------------------------------------------------------------
(* Helpers *)

NoKey  == -1                 \* a null BlockKey; real key ids are serial numbers >= 0
NNSrc  == "NN"               \* issuer of an NN-minted (client) token
NoDN   == "none"

\* Key ids of NN incarnation e start at Base(e) + 1 (setSerialNo(random), BTSM:154, 190-197).
Base(e) == SerialStart + e * KeyBase

EmptyKeys == [k \in {} |-> 0]

InSafeMode        == safeMode # "off"          \* FSN:5269-5272
InStartupSafeMode == safeMode = "startup"      \* FSN:5274-5277

\* ExportedBlockKeys: currentKey plus allKeys, including nextKey (BTSM:200-208).
Export   == [cur |-> nnCur, keys |-> nnKeys]
NoExport == [cur |-> NoKey, keys |-> EmptyKeys]

\* removeExpiredKeys: drop keys whose expiry is strictly before now (BTSM:210-219, `<` at 215).
RemoveExpired(ks, t) == [k \in {x \in DOMAIN ks : ~(ks[x] < t)} |-> ks[k]]

\* HashMap.put: the new value wins.
Put(ks, k, e) == (k :> e) @@ ks

\* allKeys.put for every received key (BTSM:238-243): received values win.
PutAll(ks, ex) == ex @@ ks

\* isExpired (BTSM:443-445): Time.now() > expiryDate.
IsExpired(e) == now > e

\* Heartbeat-reply commands; all share one record shape.
KucCmd(e)  == [type |-> "KUC",  ex |-> e,        ids |-> {}]   \* KeyUpdateCommand (BM:1675)
XferCmd(S) == [type |-> "XFER", ex |-> NoExport, ids |-> S]    \* DNA_TRANSFER BlockCommand (DM:1948-1951)
RegCmd     == [type |-> "REG",  ex |-> NoExport, ids |-> {}]   \* RegisterCommand.REGISTER (DM:1867, 1877)

IsKuc(c)    == c.type = "KUC"
IsNotKuc(c) == c.type # "KUC"
RespIds(r)  == UNION {r[k].ids : k \in 1..Len(r)}
RegQueued(d) == \E k \in 1..Len(cmdQ[d]) : cmdQ[d][k].type = "REG"

NoXfer  == [src |-> NoDN, dst |-> NoDN, st |-> "none", key |-> NoKey, exp |-> 0]
Done(x) == [x EXCEPT !.st = "done", !.key = NoKey, !.exp = 0]

Channels == IF TestActions THEN {"actor", "test"} ELSE {"actor"}
ThIdle   == [st |-> "idle", dn |-> NoDN, cmds |-> <<>>]

-----------------------------------------------------------------------------
(* Worker BTSM.addKeys(exportedKeys, updateCurrentKey) (BTSM:228-244),     *)
(* atomic under the BTSM monitor, as is the lookup in retrievePassword     *)
(* (BTSM:514-516): a verifier never sees half an export.                   *)
AddKeysWorker(d, e, upd) ==
    /\ dnKeys' = [dnKeys EXCEPT ![d] = PutAll(RemoveExpired(@, now), e.keys)]  \* BTSM:234, 238-243
    /\ dnCur'  = [dnCur EXCEPT ![d] = IF upd \/ @ = NoKey THEN e.cur ELSE @]   \* BTSM:235-237

(* Master BTSM.updateKeys() (BTSM:260-281). *)
RotateKeys ==
    LET kept     == RemoveExpired(nnKeys, now)                 \* BTSM:266 -> 210-219
        retired  == Put(kept, nnCur, now + I + L)              \* BTSM:267-270 final expiry of the retiring key
        promoted == Put(retired, nnNext, now + 2 * I + L)      \* BTSM:271-274 nextKey becomes currentKey
        newNext  == nnSerial + 1                               \* BTSM:276 setSerialNo(serialNo + 1), BTSM:161-167
    IN  /\ nnKeys'   = Put(promoted, newNext, now + 3 * I + L) \* BTSM:277-279
        /\ nnCur'    = nnNext
        /\ nnNext'   = newNext
        /\ nnSerial' = newNext

-----------------------------------------------------------------------------
(* Initial state: the workload's post-setup steady state (brief 3.1).  A   *)
(* fresh master generated currentKey and nextKey at time 0 (BTSM:190-197); *)
(* both DNs registered and applied that export (BPOS:436-440) and have     *)
(* heartbeated since; no flag is pending, no transfer is scheduled.        *)
Init ==
    LET k1 == Base(0) + 1
        k2 == Base(0) + 2
        ks == (k1 :> 2 * I + L) @@ (k2 :> 3 * I + L)
    IN
    /\ now = 0
    /\ lastRot = 0
    /\ rotPending = FALSE
    /\ nnEpoch = 0
    /\ nnSerial = k2
    /\ nnCur = k1
    /\ nnNext = k2
    /\ nnKeys = ks
    /\ safeMode = "off"
    /\ inHM = [d \in DN |-> TRUE]
    /\ needKeyUpdate = [d \in DN |-> FALSE]
    /\ choosable = [d \in DN |-> TRUE]
    /\ dnBpReg = [d \in DN |-> TRUE]
    /\ dnTokEn = [d \in DN |-> TRUE]
    /\ dnBTSM = [d \in DN |-> TRUE]
    /\ dnCur = [d \in DN |-> k1]
    /\ dnKeys = [d \in DN |-> ks]
    /\ cmdQ = [d \in DN |-> <<>>]
    /\ stalled = [d \in DN |-> FALSE]
    /\ regStage = [d \in DN |-> "idle"]
    /\ regExport = [d \in DN |-> NoExport]
    /\ hbStage = [d \in DN |-> "idle"]
    /\ hbResp = [d \in DN |-> <<>>]
    /\ th = ThIdle
    /\ xf = [i \in XferIds |-> NoXfer]
    /\ targetFired = FALSE

-----------------------------------------------------------------------------
(***************************************************************************)
(* Clock.                                                                  *)
(*                                                                         *)
(* TickRealism: one tick (1 min) is far longer than everything that keeps  *)
(* the DNs in step, so time may pass only when:                            *)
(*  - no rotation is due or half done: the Monitor runs every 5 s           *)
(*    (HBM:547-564);                                                       *)
(*  - every DN whose CPT is not stalled is registered (a heartbeat every    *)
(*    3 s gets REGISTER at once, DM:1876-1877), has heartbeated since its    *)
(*    (re)insertion, has an empty command queue, and no registration or     *)
(*    heartbeat of it is half done;                                        *)
(*  - no key push is pending outside safe mode: the next heartbeat carries *)
(*    it (BM:1674-1676) unless DM:1884-1886 returns early.  A heartbeat     *)
(*    handled between rotation and marking carries no push, so "each DN   *)
(*    heartbeated this tick" is not enough: the flag itself is checked;   *)
(*  - likewise no scheduled DNA_TRANSFER waits at the NN outside safe mode  *)
(*    (DM:1922-1951), and no transfer task or minted token is in flight:    *)
(*    connect, mint and the verifier's check take milliseconds (DN:3062-    *)
(*    3104, DXC:731).  Only a stalled CPT may hold commands across a tick.  *)
(* Without this guard the model would invent a DN that silently skips a    *)
(* whole interval of heartbeats (brief 3.1).                               *)
(***************************************************************************)
\* The Monitor compares milliseconds (HBM:547, 552 -> BM:808-810 -> BTSM:250-253,
\* updateTime > keyUpdateInterval) once per 5 s poll (HBM:564).  In floored
\* ticks of L the rotating poll lands at tick lastRot + I unless the previous
\* marking fell in the last seconds of its tick, and then at lastRot + I + 1:
\* the rotation is possible from a tick distance of I and due beyond it.
RotationEnabled == now - lastRot >= I
RotationDue     == now - lastRot > I        \* TickRealism: the clock waits for it

TickRealism ==
    /\ ~RotationDue
    /\ ~rotPending
    /\ th.st = "idle"
    /\ \A d \in DN :
          /\ hbStage[d] = "idle"
          /\ regStage[d] = "idle"
          /\ (needKeyUpdate[d] /\ inHM[d]) => InSafeMode
          /\ \/ stalled[d]
             \/ /\ inHM[d]
                /\ choosable[d]
                /\ cmdQ[d] = <<>>
    /\ \A i \in XferIds :
          \/ xf[i].st \in {"none", "done"}
          \/ xf[i].st = "nn" /\ InSafeMode
          \/ xf[i].st = "q" /\ stalled[xf[i].src]

\* The bare clock step; Trace.tla drives it from recorded timestamps.
AdvanceTime ==
    /\ now < MaxTime
    /\ now' = now + 1
    /\ UNCHANGED <<nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, th, xf, targetFired>>

Tick == TickRealism /\ AdvanceTime

-----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode HeartbeatManager.Monitor (HBM:538-575): rotation and marking   *)
(* are two separate steps.  The Monitor takes no FSN lock; the rotation    *)
(* holds the BTSM monitor (BTSM:250, 260), the marking loop the HBM        *)
(* monitor (HBM:553).  Heartbeat and registration handlers interleave      *)
(* freely between them.                                                   *)
(***************************************************************************)
Rotate ==
    /\ ~rotPending
    /\ RotationEnabled                       \* HBM:547, 552: shouldUpdateBlockKey(now - lastBlockKeyUpdate)
    /\ RotateKeys                            \* BM:808-810 -> BTSM:250-253 -> 260-281
    /\ rotPending' = TRUE
    /\ UNCHANGED <<now, lastRot, nnEpoch, safeMode, descVars, keyVars, dnRegVars,
                   cptVars, hbVars, th, xf, targetFired>>

Mark ==
    /\ rotPending
    /\ needKeyUpdate' = [d \in DN |-> IF inHM[d] THEN TRUE ELSE needKeyUpdate[d]]  \* HBM:553-557, only nodes in `datanodes`
    /\ lastRot' = now                        \* HBM:558 lastBlockKeyUpdate = now (read at HBM:547)
    /\ rotPending' = FALSE
    /\ UNCHANGED <<now, nnEpoch, nnSerial, nnCur, nnNext, nnKeys, safeMode, inHM, choosable,
                   keyVars, dnRegVars, cptVars, hbVars, th, xf, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode heartbeat handler: FSN.handleHeartbeat (FSN:4484-4498, FSN    *)
(* read lock) -> DM.handleHeartbeat (DM:1856-2006).  Split at the key      *)
(* logic: the flag check (BM:1674) and export (BM:1675) run in one step,   *)
(* the clear (BM:1676) in the next.  These are three critical sections     *)
(* (DD:280-286, BTSM:201); merging check with export loses no interleaving *)
(* (only the Monitor's rotation can come between them, and a rotation does *)
(* not change the flag), but the clear must stay separate: a rotation plus *)
(* marking between export and clear erases the new mark while the DN gets  *)
(* the old export (Scenario 3b).                                           *)
(*                                                                         *)
(* Channel "actor" is the BPServiceActor's own heartbeat (BPSA:698-756).   *)
(* Channel "test" is the workload's direct sendHeartBeat (WL:152-167); it  *)
(* runs on the test thread, concurrently with the actor's.                 *)
(***************************************************************************)
ChannelIdle(d, c) == IF c = "actor" THEN hbStage[d] = "idle" ELSE th.st = "idle"

PendingFor(d) == {i \in XferIds : xf[i].st = "nn" /\ xf[i].src = d}

SetReply(d, c, st, r) ==
    IF c = "actor"
    THEN /\ hbStage' = [hbStage EXCEPT ![d] = st]
         /\ hbResp' = [hbResp EXCEPT ![d] = r]
         /\ UNCHANGED th
    ELSE /\ th' = [st |-> st, dn |-> d, cmds |-> r]
         /\ UNCHANGED hbVars

HandleHeartbeat(d, c) ==
    /\ c \in Channels
    /\ ChannelIdle(d, c)
    \* The actor heartbeats from offerService, which starts after register()
    \* (BPSA:871, then the offerService loop); the request carries
    \* bpRegistration (BPSA:571).
    /\ dnBpReg[d]
    /\ regStage[d] = "idle"
    \* Abstraction: no further heartbeat while a REGISTER command waits in the
    \* queue.  Each would return another REGISTER (DM:1876-1877) and queue a
    \* redundant re-registration; those only deliver fresher exports.
    /\ ~RegQueued(d)
    /\ IF ~inHM[d]
       THEN \* DM:1864-1868 unknown node, DM:1876-1877 not registered -> REGISTER
            /\ SetReply(d, c, "inflight", <<RegCmd>>)
            /\ UNCHANGED <<descVars, xf>>
       ELSE IF InSafeMode
       THEN \* DM:1879-1880 liveness and storage reports; DM:1882-1886 safe mode:
            \* no commands at all, the key push included
            /\ choosable' = [choosable EXCEPT ![d] = TRUE]
            /\ SetReply(d, c, "inflight", <<>>)
            /\ UNCHANGED <<inHM, needKeyUpdate, xf>>
       ELSE \* (DM:1888-1893 block recovery is not modeled, brief 3.2)
            LET P    == PendingFor(d)            \* DM:1899-1932, DD:767 getReplicationCommand
                xcmd == IF P = {} THEN <<>> ELSE <<XferCmd(P)>>   \* DM:1948-1951
            IN /\ choosable' = [choosable EXCEPT ![d] = TRUE]     \* DM:1879-1880 (DD:385-391, 463ff)
               /\ xf' = [i \in XferIds |-> IF i \in P THEN [xf[i] EXCEPT !.st = "resp"] ELSE xf[i]]
               /\ IF needKeyUpdate[d]                             \* DM:1971 -> BM:1674
                  THEN SetReply(d, c, "exported", xcmd \o <<KucCmd(Export)>>)  \* BM:1675 exportKeys()
                  ELSE SetReply(d, c, "inflight", xcmd)
               /\ UNCHANGED <<inHM, needKeyUpdate>>
    /\ UNCHANGED <<now, nnVars, keyVars, dnRegVars, cptVars, targetFired>>

HbClear(d, c) ==
    /\ c \in Channels
    /\ IF c = "actor" THEN hbStage[d] = "exported" ELSE (th.st = "exported" /\ th.dn = d)
    /\ needKeyUpdate' = [needKeyUpdate EXCEPT ![d] = FALSE]  \* BM:1676, before the reply leaves the NN
    /\ IF c = "actor"
       THEN /\ hbStage' = [hbStage EXCEPT ![d] = "inflight"]
            /\ UNCHANGED <<hbResp, th>>
       ELSE /\ th' = [th EXCEPT !.st = "inflight"]
            /\ UNCHANGED hbVars
    /\ UNCHANGED <<now, nnVars, inHM, choosable, keyVars, dnRegVars, cptVars, xf, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* DataNode actor receives the reply (BPSA:711-756).  The (single)         *)
(* KeyUpdateCommand jumps to the HEAD of the CPT queue (BPSA:747-753,      *)
(* enqueueFirst/putFirst BPSA:1499-1508); the other commands go to the     *)
(* tail (BPSA:755, 1519-1524).  updateActorStatesFromHeartbeat (BPSA:733,  *)
(* BPOS:576-621) is not modeled: one NN, always active, so KUCs are         *)
(* applied with updateCurrentKey = true (BPOS:700-701, 788-795).           *)
(***************************************************************************)
DeliverResp(d) ==
    /\ hbStage[d] = "inflight"
    /\ LET r    == hbResp[d]
           kucs == SelectSeq(r, IsKuc)
           rest == SelectSeq(r, IsNotKuc)
       IN /\ cmdQ' = [cmdQ EXCEPT ![d] = kucs \o @ \o rest]
          /\ xf' = [i \in XferIds |->
                      IF i \in RespIds(r) /\ xf[i].st = "resp"
                      THEN [xf[i] EXCEPT !.st = "q"] ELSE xf[i]]
    /\ hbStage' = [hbStage EXCEPT ![d] = "idle"]
    /\ hbResp' = [hbResp EXCEPT ![d] = <<>>]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, stalled, th, targetFired>>

(***************************************************************************)
(* CommandProcessingThread: one queued command per step (BPSA:1427-1445,   *)
(* 1453-1484) -> BPOS.processCommandFromActor (BPOS:671-705).              *)
(***************************************************************************)
ProcessCommand(d) ==
    /\ cmdQ[d] # <<>>
    /\ ~stalled[d]
    /\ regStage[d] = "idle"            \* reRegister runs on this thread (BPOS:687)
    /\ LET c == Head(cmdQ[d]) IN
       /\ cmdQ' = [cmdQ EXCEPT ![d] = Tail(@)]                  \* BPSA:1430
       /\ IF c.type = "KUC"
          THEN \* DNA_ACCESSKEYUPDATE from the active NN: BPOS:788-795
               \* -> BPTSM:144-147 -> BTSM:228-244 with updateCurrentKey = true
               /\ AddKeysWorker(d, c.ex, TRUE)
               /\ UNCHANGED <<dnRegVars, xf>>
          ELSE IF c.type = "XFER"
          THEN \* DNA_TRANSFER: BPOS:738-743 -> DN:2899-2910 -> transferBlock DN:2835-2897;
               \* the DataTransfer task is submitted at DN:2891-2895
               /\ xf' = [i \in XferIds |->
                           IF i \in c.ids /\ xf[i].st = "q"
                           THEN [xf[i] EXCEPT !.st = "task"] ELSE xf[i]]
               /\ UNCHANGED <<keyVars, dnRegVars>>
          ELSE \* DNA_REGISTER: BPOS:681-689 -> reRegister BPSA:967-984 -> register BPSA:838-848
               /\ regStage' = [regStage EXCEPT ![d] = "rpc"]
               /\ UNCHANGED <<keyVars, dnBpReg, dnTokEn, dnBTSM, regExport, xf>>
    /\ UNCHANGED <<now, nnVars, descVars, stalled, hbVars, th, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Registration.  NN side: FSN.registerDatanode under the FSN write lock   *)
(* (FSN:4454-4461) -> DM.registerDatanode (DM:1188-1349).  The export      *)
(* snapshot (DM:1209) and the insertion into the heartbeat list (DM:1300 ->*)
(* HBM:231-239 for a known descriptor, DM:1337 -> HBM:245-249 for a new    *)
(* one) are separate steps: the Monitor holds no FSN lock and can rotate   *)
(* and mark in between (Scenario 3a).                                      *)
(* DN side: BPSA.register (BPSA:845-871) -> BPOS.registrationSucceeded     *)
(* (BPOS:422-445): publish bpRegistration (432), create the pool's BTSM    *)
(* (434 -> DN:2097-2145, only if absent), then addKeys (436-440).          *)
(***************************************************************************)
RegExport(d) ==
    /\ regStage[d] = "rpc"
    /\ regExport' = [regExport EXCEPT ![d] = Export]           \* DM:1209 setExportedKeys(getBlockKeys()), BM:1639-1642
    /\ regStage' = [regStage EXCEPT ![d] = "exported"]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnBpReg, dnTokEn, dnBTSM, cptVars,
                   hbVars, th, xf, targetFired>>

RegInsert(d) ==
    /\ regStage[d] = "exported"
    /\ inHM' = [inHM EXCEPT ![d] = TRUE]                       \* DM:1300 -> HBM:231-233 (no-op if alive) / DM:1337 -> HBM:245-249
    \* A dead descriptor is re-added with an empty storage report, which marks
    \* its old storages failed (HBM:236; DD:443-444, 507-508, 514-515 after
    \* DD:1012); a new descriptor has no storages.  Either way it is not a
    \* transfer target until its next heartbeat.  An alive one keeps its storages.
    /\ choosable' = [choosable EXCEPT ![d] = IF inHM[d] THEN @ ELSE FALSE]
    \* needKeyUpdate is untouched: neither path writes it (a new descriptor
    \* starts FALSE, DD:185, which is also the post-NNRestart value).
    /\ regStage' = [regStage EXCEPT ![d] = "replied"]
    /\ UNCHANGED <<now, nnVars, needKeyUpdate, keyVars, dnBpReg, dnTokEn, dnBTSM, regExport,
                   cptVars, hbVars, th, xf, targetFired>>

DnPublishReg(d) ==
    /\ regStage[d] = "replied"
    /\ dnBpReg' = [dnBpReg EXCEPT ![d] = TRUE]                 \* BPSA:850, BPOS:432 (volatile BPOS:74)
    \* DN:2130: the pool's BTSM is created only if absent (first registration of this process)
    /\ regStage' = [regStage EXCEPT ![d] = IF dnBTSM[d] THEN "btsm" ELSE "published"]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnTokEn, dnBTSM, regExport, cptVars,
                   hbVars, th, xf, targetFired>>

\* BPOS:434 -> DN:2097-2108 -> registerBlockPoolWithSecretManager DN:2115-2145.
\* isBlockTokenEnabled is set at DN:2118-2120 and the worker BTSM is added at
\* DN:2141-2144 (empty allKeys BTSM:148, worker generateKeys returns BTSM:175-177).
\* An op that lands between 2120 and 2144 gets IllegalArgumentException
\* (BPTSM:53-59), not the target, and no key state changes there, so the two
\* writes are one step.
DnCreateBTSM(d) ==
    /\ regStage[d] = "published"
    /\ dnTokEn' = [dnTokEn EXCEPT ![d] = TRUE]
    /\ dnBTSM' = [dnBTSM EXCEPT ![d] = TRUE]
    /\ dnKeys' = [dnKeys EXCEPT ![d] = EmptyKeys]
    /\ dnCur' = [dnCur EXCEPT ![d] = NoKey]
    /\ regStage' = [regStage EXCEPT ![d] = "btsm"]
    /\ UNCHANGED <<now, nnVars, descVars, dnBpReg, regExport, cptVars, hbVars, th, xf, targetFired>>

\* BPOS:436-440 -> BPTSM:144-147 -> BTSM:228-244.  updateCurrentKey =
\* (state == null || state == ACTIVE) (BPOS:437-438) is true with one NN.
DnAddRegKeys(d) ==
    /\ regStage[d] = "btsm"
    /\ AddKeysWorker(d, regExport[d], TRUE)
    /\ regStage' = [regStage EXCEPT ![d] = "idle"]
    /\ regExport' = [regExport EXCEPT ![d] = NoExport]
    /\ UNCHANGED <<now, nnVars, descVars, dnBpReg, dnTokEn, dnBTSM, cptVars, hbVars, th, xf, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Transfers and tokens.                                                   *)
(***************************************************************************)

\* NN RedundancyMonitor (BM:5396) -> computeDatanodeWork (BM:5431-5437: nothing
\* in safe mode) -> computeBlockReconstructionWork (BM:2113, 2145) -> target
\* choice (DD:816-841) -> RW:65 -> DD:685 addBlockToBeReplicated on the source
\* descriptor.  Many blocks are abstracted: any live source in Sources may hold
\* a block that a target in Targets lacks.
ScheduleTransfer(src, dst) ==
    /\ src \in Sources /\ dst \in Targets /\ src # dst
    /\ ~InSafeMode
    /\ inHM[src]
    /\ inHM[dst] /\ choosable[dst]
    /\ \E i \in XferIds :
          /\ xf[i].st = "none"
          /\ xf' = [xf EXCEPT ![i] = [src |-> src, dst |-> dst, st |-> "nn", key |-> NoKey, exp |-> 0]]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, th, targetFired>>

\* A client gets an NN-minted token (BM:1645-1669 -> BTSM:284-306 -> createPassword
\* BTSM:482-496 on the master: keyId = currentKey, expiry = now + L) with the block's
\* locations, and later presents it at one of them (readBlock DXC:594 or writeBlock
\* DXC:731 -> checkAccess).  The token is not bound to a DN when minted (dst = NoDN);
\* TokenAt lets any DN in Targets check it.  Reads are allowed in safe mode
\* (FSN:2215-2235); the NN returns only locations that registered DNs reported, so
\* some target must be registered.
ClientOp ==
    /\ ClientOps
    /\ \E v \in Targets : inHM[v]
    /\ \E i \in XferIds :
          /\ xf[i].st = "none"
          /\ xf' = [xf EXCEPT ![i] = [src |-> NNSrc, dst |-> NoDN, st |-> "minted",
                                      key |-> nnCur, exp |-> now + L]]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, th, targetFired>>

\* DataTransfer.run (DN:3054-3144): connect (DN:3063-3069) THEN mint (DN:3074-3076
\* -> getBlockAccessToken DN:3155-3165 -> BPTSM:153-158 -> BTSM:293-306 -> createPassword
\* BTSM:482-496): keyId = the source's currentKey at mint time, no expiry or presence
\* check of that key; token expiry = now + tokenLifetime (BTSM:490-491).
Mint(i) ==
    /\ xf[i].st = "task"
    /\ LET s == xf[i].src IN
       IF ~dnTokEn[s] \/ ~dnBTSM[s] \/ dnCur[s] = NoKey
       THEN \* DUMMY_TOKEN (DN:3158-3163), IAE (BPTSM:53-59) or ISE (BTSM:487-488):
            \* the transfer fails at the source (DN:3131-3136); never the target
            xf' = [xf EXCEPT ![i] = Done(@)]
       ELSE xf' = [xf EXCEPT ![i].st = "minted", ![i].key = dnCur[s], ![i].exp = now + L]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, th, targetFired>>

\* Token i is on its way to DN v: a DN->DN transfer names its target; a client
\* token (dst = NoDN) may be presented at any DN in Targets.
TokenAt(v, i) ==
    /\ xf[i].st = "minted"
    /\ IF xf[i].dst = NoDN THEN v \in Targets ELSE xf[i].dst = v

\* The state in which TargetCheck(v, i) evaluates the target's guard (BTSM:514-517).
AtLookup(v, i) ==
    /\ TokenAt(v, i)
    /\ dnBpReg[v] /\ dnTokEn[v] /\ dnBTSM[v]
    /\ ~IsExpired(xf[i].exp)

(***************************************************************************)
(* TargetCheck: the verifier's path to the target.                         *)
(*   DXC.writeBlock DXC:731 (readBlock DXC:594 for client reads)            *)
(*   -> DXC.checkAccess DXC:1442-1479 -> BPTSM:133-139                       *)
(*   -> BTSM.checkAccess(Token,...) BTSM:404-421 -> checkAccess(id,...)      *)
(*      BTSM:416 -> 345-372 -> retrievePassword BTSM:417 -> 507-523.         *)
(* Identifier parsing, user, pool, block id, mode and storage checks pass  *)
(* for the modeled ops (brief 1, path guards).                              *)
(***************************************************************************)
TargetCheck(v, i) ==
    /\ TokenAt(v, i)
    /\ dnBpReg[v]                                   \* DXC:1449 -> checkAndWaitForBP DXC:1401-1434 (DN:2340-2347)
    /\ IF ~dnTokEn[v]
       THEN \* DXC:1450: tokens not enabled yet in this DN process -> no verification
            /\ xf' = [xf EXCEPT ![i] = Done(@)]
            /\ UNCHANGED targetFired
       ELSE IF ~dnBTSM[v]
       THEN \* BPTSM:137 -> 53-59 IllegalArgumentException: not the target
            /\ xf' = [xf EXCEPT ![i] = Done(@)]
            /\ UNCHANGED targetFired
       ELSE IF IsExpired(xf[i].exp)
       THEN \* BTSM:364-367 (again at 509-511): expired InvalidToken, not the target
            /\ xf' = [xf EXCEPT ![i] = Done(@)]
            /\ UNCHANGED targetFired
       ELSE IF xf[i].key \notin DOMAIN dnKeys[v]   \* BTSM:513-517: allKeys.get(keyId) == null
       THEN /\ targetFired' = TRUE                 \* BTSM:518-520 throw new InvalidToken("Can't re-compute password ...")
            /\ UNCHANGED xf
       ELSE \* BTSM:522 password recomputed; BTSM:417-420 it matches (same key)
            /\ xf' = [xf EXCEPT ![i] = Done(@)]
            /\ UNCHANGED targetFired
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, th>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Faults and environment (each bounded by a counter in MC.tla).           *)
(***************************************************************************)

\* Entering safe mode: "manual" is FSN.enterSafeMode (FSN:5283-5306, 5299);
\* "startup" is BMSM.activate at NN start when the block threshold is not met
\* (BMSM:172-188, 183).  Nothing in the rotation path checks safe mode
\* (HBM:552-557, BM:808-810).
EnterSafeModeKind(k) ==
    /\ safeMode = "off"
    /\ safeMode' = k
    /\ UNCHANGED <<now, lastRot, rotPending, nnEpoch, nnSerial, nnCur, nnNext, nnKeys,
                   descVars, keyVars, dnRegVars, cptVars, hbVars, th, xf, targetFired>>

\* Scenario 1: an operator puts the NN in safe mode.
EnterSafeMode == EnterSafeModeKind("manual")

\* FSN.leaveSafeMode (FSN:5312-5327) -> BMSM.leaveSafeMode (BMSM:376-412).  An
\* operator may force startup safe mode off as well, so it is allowed any time.
LeaveSafeMode ==
    /\ safeMode # "off"
    /\ safeMode' = "off"
    /\ UNCHANGED <<now, lastRot, rotPending, nnEpoch, nnSerial, nnCur, nnNext, nnKeys,
                   descVars, keyVars, dnRegVars, cptVars, hbVars, th, xf, targetFired>>

\* Scenario 2/4.  The NN handled the heartbeat (flag already cleared, BM:1676) but
\* the reply never reaches the DN: a started handler runs to completion even if
\* the caller gave up (common ipc/Server.java:1300-1304); the DN's call times out
\* with no retry (common ipc/Client.java:276-281) and offerService drops the whole
\* response on IOException (BPSA:805-807).  Nothing re-sends the export.
LoseResp(d) ==
    /\ d \in LossyDNs
    /\ hbStage[d] = "inflight"
    /\ hbResp[d] # <<>>                \* losing an empty reply changes nothing
    /\ xf' = [i \in XferIds |-> IF i \in RespIds(hbResp[d]) THEN Done(xf[i]) ELSE xf[i]]
    /\ hbStage' = [hbStage EXCEPT ![d] = "idle"]
    /\ hbResp' = [hbResp EXCEPT ![d] = <<>>]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, th, targetFired>>

\* Scenario 2 variant.  The CPT is busy in one long command; the queue has no
\* bound or timeout (BPSA:1427-1445).  The actor keeps heartbeating meanwhile.
StallCPT(d) ==
    /\ d \in StallDNs
    /\ ~stalled[d]
    /\ regStage[d] = "idle"
    /\ stalled' = [stalled EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cmdQ, hbVars, th, xf, targetFired>>

UnstallCPT(d) ==
    /\ stalled[d]
    /\ stalled' = [stalled EXCEPT ![d] = FALSE]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cmdQ, hbVars, th, xf, targetFired>>

\* Scenario 3a.  The Monitor's heartbeatCheck finds d silent for longer than
\* 2 * recheck + 10 * heartbeat (DM:309-313, 937-941) and removes it from the
\* heartbeat list (HBM:516-523 -> DM:921-935 -> DM:885-898 -> HBM:255-262).
\* Not in startup safe mode (HBM:445-447, 512-513).  The silence itself (a
\* partition of >20 min) is abstracted: the step stands for its end.
DeclareDead(d) ==
    /\ d \in DeadDNs
    /\ inHM[d]
    /\ ~InStartupSafeMode
    /\ inHM' = [inHM EXCEPT ![d] = FALSE]
    /\ UNCHANGED <<now, nnVars, needKeyUpdate, choosable, keyVars, dnRegVars, cptVars,
                   hbVars, th, xf, targetFired>>

\* Scenario 6.  The DN process restarts.  The new process has
\* isBlockTokenEnabled = false (DN:430), bpRegistration = null (BPOS:74), no
\* pool BTSM, an empty queue; its actor registers again before offerService
\* (BPSA:838-879).  Its transfer tasks and connections die with it.  The NN
\* still sees it alive and choosable (HBM:231 is a no-op for an alive node).
\* Restriction: not while an NN handler is between export and clear for it
\* (that combination equals a lost reply followed by a restart, whose
\* registration export is at least as fresh).
DNRestart(d) ==
    /\ d \in RestartDNs
    /\ hbStage[d] # "exported"
    /\ th.st = "idle" \/ th.dn # d
    /\ dnBpReg' = [dnBpReg EXCEPT ![d] = FALSE]
    /\ dnTokEn' = [dnTokEn EXCEPT ![d] = FALSE]
    /\ dnBTSM' = [dnBTSM EXCEPT ![d] = FALSE]
    /\ dnKeys' = [dnKeys EXCEPT ![d] = EmptyKeys]
    /\ dnCur' = [dnCur EXCEPT ![d] = NoKey]
    /\ cmdQ' = [cmdQ EXCEPT ![d] = <<>>]
    /\ stalled' = [stalled EXCEPT ![d] = FALSE]
    /\ regStage' = [regStage EXCEPT ![d] = "rpc"]
    /\ regExport' = [regExport EXCEPT ![d] = NoExport]
    /\ hbStage' = [hbStage EXCEPT ![d] = "idle"]
    /\ hbResp' = [hbResp EXCEPT ![d] = <<>>]
    /\ xf' = [i \in XferIds |->
                IF \/ xf[i].src = d /\ xf[i].st \in {"resp", "q", "task", "minted"}
                   \/ xf[i].dst = d /\ xf[i].st = "minted"
                THEN Done(xf[i]) ELSE xf[i]]
    /\ UNCHANGED <<now, nnVars, descVars, th, targetFired>>

\* Scenario 5.  The NN restarts.  Block keys are not persisted: a new master
\* BTSM gets a fresh random serial and generates current and next keys
\* (BM:546 -> BM:702-762 -> BTSM:140-158, 190-197); a disjoint id range models
\* the random serial.  The Monitor's lastBlockKeyUpdate starts at 0 (HBM:540)
\* while the monotonic clock is the machine's uptime, so its first iteration
\* rotates (finding F13).  The new NN knows no DN (DM:1864-1877 -> REGISTER),
\* has no flags and no replication queue, and starts in safe mode (BMSM:172-188).
\* Replies of the old NN are lost; an unfinished registration RPC is retried
\* against the new NN (BPSA:845-864).  DN-side state, including transfer tasks
\* and minted tokens, survives.
NNRestart ==
    /\ nnEpoch + 1 < MaxEpoch
    /\ th.st = "idle"
    /\ LET e  == nnEpoch + 1
           k1 == Base(e) + 1
           k2 == Base(e) + 2
       IN /\ nnEpoch' = e
          /\ nnSerial' = k2
          /\ nnCur' = k1
          /\ nnNext' = k2
          /\ nnKeys' = (k1 :> now + 2 * I + L) @@ (k2 :> now + 3 * I + L)
    /\ lastRot' = now - I - 1
    /\ rotPending' = FALSE
    /\ safeMode' = "startup"
    /\ inHM' = [d \in DN |-> FALSE]
    /\ needKeyUpdate' = [d \in DN |-> FALSE]
    /\ choosable' = [d \in DN |-> FALSE]
    /\ hbStage' = [d \in DN |-> "idle"]
    /\ hbResp' = [d \in DN |-> <<>>]
    /\ regStage' = [d \in DN |-> IF regStage[d] \in {"rpc", "exported"} THEN "rpc" ELSE regStage[d]]
    /\ regExport' = [d \in DN |-> IF regStage[d] = "exported" THEN NoExport ELSE regExport[d]]
    /\ xf' = [i \in XferIds |-> IF xf[i].st \in {"nn", "resp"} THEN Done(xf[i]) ELSE xf[i]]
    /\ UNCHANGED <<now, keyVars, dnBpReg, dnTokEn, dnBTSM, cptVars, th, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Workload-test actions (TestActions = TRUE only in Trace.cfg).  These    *)
(* are what TestAdhocWorkload12 does directly; X9 in the analysis report:  *)
(* test-only mutators, modeled for trace validation only.                  *)
(***************************************************************************)

\* WL:98-100 master.updateKeys(Long.MAX_VALUE) -> BTSM:250-253 -> 260-281:
\* a rotation that marks no DN and leaves the Monitor's lastBlockKeyUpdate alone.
TestRotate ==
    /\ TestActions
    /\ RotateKeys
    /\ UNCHANGED <<now, lastRot, rotPending, nnEpoch, safeMode, descVars, keyVars, dnRegVars,
                   cptVars, hbVars, th, xf, targetFired>>

\* WL:104-107 getDatanode(...).setNeedKeyUpdate(true) -> DD:284-286.
TestMark(d) ==
    /\ TestActions
    /\ needKeyUpdate' = [needKeyUpdate EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<now, nnVars, inHM, choosable, keyVars, dnRegVars, cptVars, hbVars, th, xf, targetFired>>

\* WL:157 actor.sendHeartBeat(false) returns on the test thread (BPSA:571-590).
TestRecvResp ==
    /\ TestActions
    /\ th.st = "inflight"
    /\ th' = IF th.cmds = <<>> THEN ThIdle ELSE [th EXCEPT !.st = "proc"]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, xf, targetFired>>

\* WL:158-163: each command in array order, on the test thread, through
\* BPOS.processCommandFromActor (BPOS:671-705); no queue, so no KUC-first.
TestProcessCmd ==
    /\ TestActions
    /\ th.st = "proc"
    /\ th.cmds # <<>>
    /\ LET c == Head(th.cmds)
           d == th.dn
       IN /\ th' = IF Tail(th.cmds) = <<>> THEN ThIdle ELSE [th EXCEPT !.cmds = Tail(@)]
          /\ IF c.type = "KUC"
             THEN /\ AddKeysWorker(d, c.ex, TRUE)                  \* BPOS:788-795 -> BTSM:228-244
                  /\ UNCHANGED <<dnRegVars, xf>>
             ELSE IF c.type = "XFER"
             THEN /\ xf' = [i \in XferIds |->                       \* BPOS:738-743 -> DN:2899-2910
                              IF i \in c.ids /\ xf[i].st = "resp"
                              THEN [xf[i] EXCEPT !.st = "task"] ELSE xf[i]]
                  /\ UNCHANGED <<keyVars, dnRegVars>>
             ELSE /\ regStage' = [regStage EXCEPT ![d] = "rpc"]     \* BPOS:681-689
                  /\ UNCHANGED <<keyVars, dnBpReg, dnTokEn, dnBTSM, regExport, xf>>
    /\ UNCHANGED <<now, nnVars, descVars, cptVars, hbVars, targetFired>>

\* WL:129-132 source.transferBlock(block, {target}, ...) on the test thread ->
\* DN:2835-2897: the DataTransfer task is submitted at DN:2891-2895.
TestTransfer(src, dst) ==
    /\ TestActions
    /\ src # dst
    /\ dnBpReg[src]                          \* DN:2839 getDNRegistrationForBP
    /\ \E i \in XferIds :
          /\ xf[i].st = "none"
          /\ xf' = [xf EXCEPT ![i] = [src |-> src, dst |-> dst, st |-> "task", key |-> NoKey, exp |-> 0]]
    /\ UNCHANGED <<now, nnVars, descVars, keyVars, dnRegVars, cptVars, hbVars, th, targetFired>>

-----------------------------------------------------------------------------
Next ==
    \/ Tick
    \/ Rotate
    \/ Mark
    \/ \E d \in DN, c \in Channels : HandleHeartbeat(d, c) \/ HbClear(d, c)
    \/ \E d \in DN :
          \/ DeliverResp(d)
          \/ ProcessCommand(d)
          \/ RegExport(d)
          \/ RegInsert(d)
          \/ DnPublishReg(d)
          \/ DnCreateBTSM(d)
          \/ DnAddRegKeys(d)
          \/ LoseResp(d)
          \/ StallCPT(d)
          \/ UnstallCPT(d)
          \/ DeclareDead(d)
          \/ DNRestart(d)
          \/ TestMark(d)
    \/ \E src \in DN, dst \in DN : ScheduleTransfer(src, dst) \/ TestTransfer(src, dst)
    \/ ClientOp
    \/ \E i \in XferIds : Mint(i)
    \/ \E v \in DN, i \in XferIds : TargetCheck(v, i)
    \/ EnterSafeMode
    \/ LeaveSafeMode
    \/ NNRestart
    \/ TestRotate
    \/ TestRecvResp
    \/ TestProcessCmd

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties.                                                             *)
(***************************************************************************)

\* The target's failing branch is never taken.
TargetSafe == ~targetFired

\* Temporary sanity (adhoc tla-patterns 2): TLC must VIOLATE this in MC.cfg,
\* showing that the lookup at BTSM:514-517 is reached at all.
TargetReached == ~(\E v \in DN, i \in XferIds : AtLookup(v, i))

XferStates == {"none", "nn", "resp", "q", "task", "minted", "done"}
RegStates  == {"idle", "rpc", "exported", "replied", "published", "btsm"}
HbStates   == {"idle", "exported", "inflight"}

KeyMapOK(m) == IsFiniteSet(DOMAIN m) /\ \A k \in DOMAIN m : k \in Int /\ m[k] \in Int
ExportTypeOK(e) == e.cur \in Int /\ KeyMapOK(e.keys)
CmdOK(c) == /\ c.type \in {"KUC", "XFER", "REG"}
            /\ c.ids \subseteq XferIds
            /\ ExportTypeOK(c.ex)
CmdSeqOK(q) == \A k \in 1..Len(q) : CmdOK(q[k])

TypeOK ==
    /\ now \in 0..MaxTime
    /\ lastRot \in Int
    /\ rotPending \in BOOLEAN
    /\ nnEpoch \in 0..(MaxEpoch - 1)
    /\ nnSerial \in Int /\ nnCur \in Int /\ nnNext \in Int
    /\ KeyMapOK(nnKeys)
    /\ safeMode \in {"off", "manual", "startup"}
    /\ inHM \in [DN -> BOOLEAN]
    /\ needKeyUpdate \in [DN -> BOOLEAN]
    /\ choosable \in [DN -> BOOLEAN]
    /\ dnBpReg \in [DN -> BOOLEAN]
    /\ dnTokEn \in [DN -> BOOLEAN]
    /\ dnBTSM \in [DN -> BOOLEAN]
    /\ dnCur \in [DN -> Int]
    /\ DOMAIN dnKeys = DN /\ \A d \in DN : KeyMapOK(dnKeys[d])
    /\ DOMAIN cmdQ = DN /\ \A d \in DN : CmdSeqOK(cmdQ[d])
    /\ stalled \in [DN -> BOOLEAN]
    /\ regStage \in [DN -> RegStates]
    /\ DOMAIN regExport = DN /\ \A d \in DN : ExportTypeOK(regExport[d])
    /\ hbStage \in [DN -> HbStates]
    /\ DOMAIN hbResp = DN /\ \A d \in DN : CmdSeqOK(hbResp[d])
    /\ th.st \in HbStates \cup {"proc"}
    /\ th.dn \in DN \cup {NoDN}
    /\ CmdSeqOK(th.cmds)
    /\ DOMAIN xf = XferIds
    /\ \A i \in XferIds :
          /\ xf[i].st \in XferStates
          /\ xf[i].src \in DN \cup {NNSrc, NoDN}
          /\ xf[i].dst \in DN \cup {NoDN}
          /\ xf[i].key \in Int
          /\ xf[i].exp \in Int
    /\ targetFired \in BOOLEAN

\* Every key id was generated by some NN incarnation (ids of the current one
\* only up to its serial).
KeyGenerated(k) ==
    \E e \in 0..nnEpoch :
        /\ k > Base(e)
        /\ k <= IF e = nnEpoch THEN nnSerial ELSE Base(e) + KeyBase - 1

\* The shape of a master snapshot: current and next (= current + 1, BTSM:190-197,
\* 272-276) present, nothing newer than next, every id generated.
ExportOK(e) ==
    /\ e.cur \in DOMAIN e.keys
    /\ e.cur + 1 \in DOMAIN e.keys
    /\ \A k \in DOMAIN e.keys : KeyGenerated(k) /\ k <= e.cur + 1

\* "A message carries only values its sender held": DN key state, every export
\* in flight or queued, and every minted keyId come from NN key states.
KeysOriginateAtNN ==
    /\ ExportOK(Export)
    /\ nnNext = nnCur + 1
    /\ nnNext = nnSerial
    /\ \A d \in DN :
          /\ dnCur[d] # NoKey => KeyGenerated(dnCur[d])
          /\ \A k \in DOMAIN dnKeys[d] : KeyGenerated(k)
          /\ \A k \in 1..Len(cmdQ[d]) : IsKuc(cmdQ[d][k]) => ExportOK(cmdQ[d][k].ex)
          /\ \A k \in 1..Len(hbResp[d]) : IsKuc(hbResp[d][k]) => ExportOK(hbResp[d][k].ex)
          /\ regStage[d] \in {"replied", "published", "btsm"} => ExportOK(regExport[d])
    /\ \A k \in 1..Len(th.cmds) : IsKuc(th.cmds[k]) => ExportOK(th.cmds[k].ex)
    /\ \A i \in XferIds : xf[i].st = "minted" => KeyGenerated(xf[i].key)

=============================================================================
