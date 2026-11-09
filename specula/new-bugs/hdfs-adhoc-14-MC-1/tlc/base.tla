-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-14: ad hoc coordination check                                 *)
(*                                                                         *)
(*   BlockTokenSecretManager.checkAccess(Token, String, ExtendedBlock,      *)
(*       AccessMode, StorageType[], String[])          (BTSM:404-421)      *)
(*     417  if (!MessageDigest.isEqual(retrievePassword(id),                *)
(*                                     token.getPassword())) {              *)
(*     418    throw new InvalidToken("Block token with " + id               *)
(*                + " doesn't have the correct token password");            *)
(*                                                                         *)
(* Pinned tree: /bulk/specula-adhoc/v2/hdfs/cases/hdfs-adhoc-14/hadoop      *)
(*              @ 734dd8a67cd (all file:line citations refer to it).        *)
(*                                                                         *)
(* Abbreviations (paths under hadoop-hdfs-project/):                        *)
(*   BTSM  hadoop-hdfs/.../security/token/block/BlockTokenSecretManager.java*)
(*   BPTSM hadoop-hdfs/.../security/token/block/BlockPoolTokenSecretManager *)
(*   BTI   hadoop-hdfs-client/.../security/token/block/BlockTokenIdentifier *)
(*   SDTC  hadoop-hdfs-client/.../datatransfer/sasl/SaslDataTransferClient  *)
(*   SDTS  hadoop-hdfs/.../datatransfer/sasl/SaslDataTransferServer         *)
(*   DXC   hadoop-hdfs/.../server/datanode/DataXceiver.java                 *)
(*   DN    hadoop-hdfs/.../server/datanode/DataNode.java                    *)
(*   BPOS  hadoop-hdfs/.../server/datanode/BPOfferService.java              *)
(*   BPSA  hadoop-hdfs/.../server/datanode/BPServiceActor.java              *)
(*   HBM   hadoop-hdfs/.../server/blockmanagement/HeartbeatManager.java     *)
(*   DM    hadoop-hdfs/.../server/blockmanagement/DatanodeManager.java      *)
(*   DD    hadoop-hdfs/.../server/blockmanagement/DatanodeDescriptor.java   *)
(*   BM    hadoop-hdfs/.../server/blockmanagement/BlockManager.java         *)
(*   FSN   hadoop-hdfs/.../server/namenode/FSNamesystem.java                *)
(*   NNRPC hadoop-hdfs/.../server/namenode/NameNodeRpcServer.java           *)
(*   FSDW  hadoop-hdfs/.../server/namenode/FSDirWriteFileOp.java            *)
(*   DS    hadoop-hdfs-client/.../hdfs/DataStreamer.java                    *)
(*   DFSC  hadoop-hdfs-client/.../hdfs/DFSClient.java                       *)
(*                                                                         *)
(* Category A (distributed, message passing).  The guard compares a        *)
(* secret held by the verifying DataNode with the password a token         *)
(* carries.  The NameNode generates the secrets and pushes them to         *)
(* DataNodes over registration and heartbeat RPCs; the NN (or a DN) signs  *)
(* tokens; clients and DNs carry them over DataTransferProtocol.           *)
(*                                                                         *)
(* HMAC abstraction (brief 3.1, analysis 1.4).  Every key id is drawn      *)
(* fresh and is globally unique, so a secret is a function of its id.  A   *)
(* token carries `kid` (the key id inside its identifier) and `sk` (the id *)
(* of the key whose secret produced its password).  The verifier computes  *)
(* HMAC(K_v[kid], rawIdentifierBytes) (BTSM:522, BTI:220-226), so the      *)
(* guard at BTSM:417 is true exactly when  sk # kid  (given kid is held).  *)
(*                                                                         *)
(* Scope: the target oracle is TargetSafe == ~targetFired.  TypeOK and     *)
(* TokenProvenance are the two structural sanity invariants.               *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    NN,                 \* NameNodes. {n1}: non-HA (the workload); {n1, n2}: HA (Scenario 3)
    DN,                 \* DataNodes
    InitActive,         \* the NameNode that is active in the initial state
    OverwriteQOP,       \* dfs.encrypt.data.overwrite.downstream.derived.qop
                        \*   (DFSConfigKeys:1413-1416, default false; DNConf:247-256; read only at DXC:824)
    Repl,               \* replication factor = length of a client write pipeline (placement among live DNs)
    XferTargets,        \* number of targets of an NN-scheduled replication (Scenario 2)
    StartRegistered,    \* TRUE: start in the registered steady state; FALSE: NN just started, no DN registered
    SkipNoopHeartbeats, \* MC reduction, only with one NN: omit heartbeat round trips that change no state
    None                \* model value

ASSUME InitActive \in NN
ASSUME OverwriteQOP \in BOOLEAN
ASSUME StartRegistered \in BOOLEAN
ASSUME SkipNoopHeartbeats \in BOOLEAN
ASSUME Repl \in Nat \ {0}
ASSUME XferTargets \in Nat \ {0}
\* The no-op heartbeat reduction is exact only when every response carries the
\* same HA status (one NameNode).  With two NNs a stale in-flight ACTIVE claim
\* matters (BPOS:576-617), so the reduction is not allowed there.
ASSUME SkipNoopHeartbeats => Cardinality(NN) = 1
ASSUME None \notin NN \cup DN

-----------------------------------------------------------------------------
(* Key ids of the NameNodes' first keys (BTSM:174-198).  Overridden by      *)
(* Trace.cfg with the ids recorded in the trace.                            *)
NNIdx == CHOOSE f \in [NN -> 1..Cardinality(NN)] :
             \A a, b \in NN : a # b => f[a] # f[b]
InitKeyIds == [n \in NN |-> [cur |-> 2 * NNIdx[n] - 1, next |-> 2 * NNIdx[n]]]

VARIABLES
    \* ---- NameNode master BlockTokenSecretManager (one per NN process, BM:187, BM:702-762)
    nnCur,          \* [NN -> key id]        BTSM.currentKey  (BTSM:79)
    nnNext,         \* [NN -> key id]        BTSM.nextKey     (BTSM:80)
    nnKeys,         \* [NN -> SUBSET key id] keys of BTSM.allKeys (BTSM:81)
    nnEp,           \* [NN -> Nat] rotations performed by this NN process (token-expiry clock)
    nnInc,          \* [NN -> Nat] NN process incarnation (restart counter)
    keyOwner,       \* [key id -> NN] every key id ever generated and the NN that generated it
    \* ---- HA roles
    role,           \* [NN -> {"active","standby"}]   haContext.getState() (FSN:4505-4507)
    actTerm,        \* [NN -> Nat] txid abstraction of the NN's ACTIVE claims: the failover number
                    \*   at which it became active; claims of a later active are strictly larger
    term,           \* number of activations so far
    \* ---- NameNode block management
    markPending,    \* [NN -> BOOLEAN] Monitor rotated (HBM:552) but has not run the mark loop yet (HBM:553-557)
    needKU,         \* [NN -> SUBSET DN] DatanodeDescriptor.needKeyUpdate (DD:185, 280-286)
    live,           \* [NN -> SUBSET DN] HeartbeatManager.datanodes, the live list (HBM:231-262)
    known,          \* [NN -> SUBSET DN] DatanodeManager.datanodeMap (DM:2095)
    xferQ,          \* [NN -> [DN -> Seq(DN)]] pending replication command for a source DN (<<>>: none)
    \* ---- RPCs between a DN's BPServiceActor and an NN
    hb,             \* [NN -> [DN -> HB]]  heartbeat RPC in progress
    reg,            \* [NN -> [DN -> REG]] registerDatanode RPC in progress
    \* ---- DataNode BPServiceActor / BPOfferService
    act,            \* [DN -> [NN -> {"init","reg","run","rereg"}]] actor phase
    astate,         \* [DN -> [NN -> {None,"active","standby"}]] BPServiceActor.state
    bpActive,       \* [DN -> NN \cup {None}] BPOfferService.bpServiceToActive
    lastClaim,      \* [DN -> Nat] BPOfferService.lastActiveClaimTxId (in actTerm units)
    cmdQ,           \* [DN -> [NN -> Seq(Cmd)]] CommandProcessingThread queue (BPSA:1400-1525)
    \* ---- DataNode worker BlockTokenSecretManager (one per block pool, DN:2115-2146)
    dnCur,          \* [DN -> key id \cup {None}] worker BTSM.currentKey
    dnKeys,         \* [DN -> SUBSET key id]      worker BTSM.allKeys
    \* ---- client and DataTransferProtocol operations
    cliDek,         \* key id of the DFSClient's cached DataEncryptionKey, or None (DFSC:239, 1855-1863)
    ops,            \* set of in-flight DataTransferProtocol operations
    nextOp,         \* next operation id
    \* ---- target
    targetFired,    \* the failing branch BTSM:418 was taken
    fireInfo        \* details of the firing (for counterexample analysis)

keyVars   == <<nnCur, nnNext, nnKeys, nnEp, nnInc, keyOwner>>
haVars    == <<role, actTerm, term>>
nnVars    == <<markPending, needKU, live, known, xferQ>>
rpcVars   == <<hb, reg>>
actorVars == <<act, astate, bpActive, lastClaim, cmdQ>>
dnKeyVars == <<dnCur, dnKeys>>
cliVars   == <<cliDek, ops, nextOp>>
tgtVars   == <<targetFired, fireInfo>>

vars == <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars, cliVars, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Helpers                                                                 *)
(***************************************************************************)
MaxSet(S) == CHOOSE x \in S : \A y \in S : y <= x

\* A fresh key id (BTSM:154/163 serial, +1 per new key: BTSM:190-197, 276-279).
\* Ids never collide (brief 3.2: a random-serial collision is outside the
\* fault model).  Overridden by Trace.cfg with the id recorded in the trace.
FreshKey(n) == MaxSet(DOMAIN keyOwner) + 1

\* ExportedBlockKeys (BTSM:201-208): currentKey and all keys of allKeys.
Export(n) == [cur |-> nnCur[n], keys |-> nnKeys[n]]
NoEx == [cur |-> None, keys |-> {}]

\* Heartbeat RPC state.  st: "idle" (no RPC), "kuPending" (NN exported keys at
\* BM:1675, flag not yet cleared at BM:1676), "resp" (response in flight).
HBIdle == [st |-> "idle", ku |-> NoEx, reg |-> FALSE, xfer |-> <<>>,
           ha |-> "standby", tm |-> 0]
\* registerDatanode RPC state.  st: "none", "want" (DN called the RPC),
\* "exported" (DM:1209 ran), "joined" (DM:1300/1332-1337 ran; reply in flight).
RegNone == [st |-> "none", ex |-> NoEx]

\* DatanodeCommands that matter here.
KuCmd(e)   == [t |-> "ku",   ex |-> e,    tg |-> <<>>]     \* KeyUpdateCommand (DNA_ACCESSKEYUPDATE)
RegCmd     == [t |-> "reg",  ex |-> NoEx, tg |-> <<>>]     \* RegisterCommand.REGISTER (DNA_REGISTER)
XferCmd(g) == [t |-> "xfer", ex |-> NoEx, tg |-> g]        \* BlockCommand(DNA_TRANSFER, ...)

\* Tokens.  iss/inc/ep record the issuing NN process and its rotation count at
\* issue, for the expiry check (BTSM:364-367, 490, 509-512).
NoTok == [kid |-> None, sk |-> None, iss |-> None, inc |-> 0, ep |-> 0]
\* BTSM:482-496 createPassword on the NN master: one BlockKey snapshot gives
\* both the identifier's keyId (491) and the HMAC secret (495).
NNToken(n) == [kid |-> nnCur[n], sk |-> nnCur[n], iss |-> n,
               inc |-> nnInc[n], ep |-> nnEp[n]]
\* The same method on a DataNode worker (DN:3155-3165 -> BPTSM:153-158).
DNToken(s) == [kid |-> dnCur[s], sk |-> dnCur[s], iss |-> None, inc |-> 0, ep |-> 0]

\* Token expiry (BTSM:364-367 at line 365, BTSM:509-512 at line 510).
\* A token lives tokenLifetime L after issue (BTSM:490); rotations of one NN
\* process after its first one are keyUpdateInterval I apart (HBM:552-558).
\* With the defaults L = I (DFSConfigKeys:1092-1095), a token issued before the
\* (ep+1)-th rotation is certainly expired once the (ep+2)-th has happened.
\* Only that certain case is modeled (tokens are otherwise kept alive);
\* DN-signed tokens (no issuing NN here) are never expired in the model.
TokExpired(t) ==
    /\ t.iss # None
    /\ t.inc = nnInc[t.iss]
    /\ nnEp[t.iss] >= t.ep + 2

\* A DataNode can serve block-token operations once its first registration
\* completed: BPOS:432-440 publishes bpRegistration (DXC:1449 waits for it),
\* creates the worker BTSM (DN:2130-2145) and adds the keys (currentKey set).
Ready(d) == dnCur[d] # None

\* Injective sequences of length k over S.
InjSeqs(S, k) == { f \in [1..k -> S] : \A i, j \in 1..k : i # j => f[i] # f[j] }
\* Targets the NN's block placement can return for a client write: Repl
\* distinct live DNs, or all of them when fewer are live.
Pipelines(S) ==
    LET k == IF Cardinality(S) < Repl THEN Cardinality(S) ELSE Repl
    IN IF k = 0 THEN {} ELSE InjSeqs(S, k)
\* Constant supersets (for quantifiers in MC.tla; the actions check the real sets).
AllPipelines == UNION {InjSeqs(DN, k) : k \in 1..Repl}
AllXferTargets == InjSeqs(DN, XferTargets)

\* A DataTransferProtocol operation.
\*   k    : "write" (client WRITE_BLOCK), "read" (READ_BLOCK or BLOCK_CHECKSUM
\*          with a READ token), "xfer" (NN-commanded replication, DN-signed token)
\*   pipe : the DNs the op visits; pipe[pos] is the DN handling it now
\*          (pos = 0: still at its source, the client or the DataTransfer DN)
\*   ph   : "connect" (client before SASL), "xferTok" (DataTransfer before its
\*          token), "dek" (sender about to build its DEK and send SASL),
\*          "sasl" (receiver's SASL server pending), "check" (receiver's
\*          checkAccess pending), "mirror" (receiver passed the check and
\*          is setting up its downstream connection)
\*   sec  : key id of the mirror's secretKey snapshot (DXC:823-829), or None
\*   dek  : key id of the DataEncryptionKey used for the current hop
\*   src  : "client" or the DataTransfer source DN
NewOp(k, tok, pipe, ph, src) ==
    [id |-> nextOp, k |-> k, tok |-> tok, pipe |-> pipe, pos |-> 0, ph |-> ph,
     sec |-> None, dek |-> None, src |-> src]

Sender(op) == IF op.pos = 0 THEN op.src ELSE op.pipe[op.pos]

\* Operations are addressed by id (ids are unique), so that MC.tla can
\* quantify over a constant id range and TLC names every step.
OpIds == {op.id : op \in ops}
Op(i) == CHOOSE op \in ops : op.id = i

\* A registration of d with n is queued or running (deduplicates DNA_REGISTER;
\* see DNHandleHeartbeatResponse).
RegPending(d, n) ==
    \/ act[d][n] = "rereg"
    \/ \E i \in 1..Len(cmdQ[d][n]) : cmdQ[d][n][i].t = "reg"

\* BPOS:576-617 updateActorStatesFromHeartbeat, applied to a response r
\* from NN n at DN d.  Returns the new [bpa |-> bpServiceToActive,
\* lc |-> lastActiveClaimTxId].
ActorStates(d, n, r) ==
    LET claims == r.ha = "active"                 \* BPOS:583-584
        thinks == bpActive[d] = n                 \* BPOS:585
        newer  == r.tm > lastClaim[d]             \* BPOS:586
    IN IF claims /\ ~thinks
       THEN IF ~newer
            \* BPOS:591-598 split-brain: older claim rejected, return early (614-617 skipped)
            THEN [bpa |-> bpActive[d], lc |-> lastClaim[d]]
            \* BPOS:599-607 accept; BPOS:614-617 record the claim txid
            ELSE [bpa |-> n, lc |-> r.tm]
       ELSE IF ~claims /\ thinks
            \* BPOS:608-612 relinquish; 614 not taken (bpServiceToActive = null)
            THEN [bpa |-> None, lc |-> lastClaim[d]]
            ELSE [bpa |-> bpActive[d],
                  lc  |-> IF bpActive[d] = n THEN r.tm ELSE lastClaim[d]]  \* BPOS:614-617

\* A heartbeat response that changes nothing at the DN (MC reduction only).
IsNoopResponse(d, n, r) ==
    /\ r.st = "resp"
    /\ ~r.reg
    /\ r.xfer = <<>>
    /\ r.ku = NoEx
    /\ astate[d][n] = r.ha
    /\ ActorStates(d, n, r) = [bpa |-> bpActive[d], lc |-> lastClaim[d]]

NoFire == [dn |-> None, kid |-> None, sk |-> None, k |-> None, rsr |-> None]

-----------------------------------------------------------------------------
(***************************************************************************)
(* Initial state                                                           *)
(***************************************************************************)
Init ==
    \* BM:702-762 -> BTSM:140-158: each NN master draws its first two keys
    \* (BTSM:174-198); distinct NNs use disjoint key ranges (BTSM:143-144).
    /\ nnCur    = [n \in NN |-> InitKeyIds[n].cur]
    /\ nnNext   = [n \in NN |-> InitKeyIds[n].next]
    /\ nnKeys   = [n \in NN |-> {InitKeyIds[n].cur, InitKeyIds[n].next}]
    /\ nnEp     = [n \in NN |-> 0]
    /\ nnInc    = [n \in NN |-> 1]
    /\ keyOwner = [k \in UNION {{InitKeyIds[n].cur, InitKeyIds[n].next} : n \in NN} |->
                      CHOOSE n \in NN : k \in {InitKeyIds[n].cur, InitKeyIds[n].next}]
    /\ role     = [n \in NN |-> IF n = InitActive THEN "active" ELSE "standby"]
    /\ actTerm  = [n \in NN |-> IF n = InitActive THEN 1 ELSE 0]
    /\ term     = 1
    /\ markPending = [n \in NN |-> FALSE]
    /\ needKU   = [n \in NN |-> {}]
    /\ live     = [n \in NN |-> IF StartRegistered THEN DN ELSE {}]
    /\ known    = [n \in NN |-> IF StartRegistered THEN DN ELSE {}]
    /\ xferQ    = [n \in NN |-> [d \in DN |-> <<>>]]
    /\ hb       = [n \in NN |-> [d \in DN |-> HBIdle]]
    /\ reg      = [n \in NN |-> [d \in DN |-> RegNone]]
    \* Steady state = every actor registered (BPOS:436-440 with the handshake
    \* state) and heartbeating with the active NN's claim accepted.
    /\ act      = [d \in DN |-> [n \in NN |-> IF StartRegistered THEN "run" ELSE "init"]]
    /\ astate   = [d \in DN |-> [n \in NN |->
                      IF StartRegistered
                      THEN (IF n = InitActive THEN "active" ELSE "standby")
                      ELSE None]]
    /\ bpActive = [d \in DN |-> IF StartRegistered THEN InitActive ELSE None]
    /\ lastClaim = [d \in DN |-> IF StartRegistered THEN 1 ELSE 0]
    /\ cmdQ     = [d \in DN |-> [n \in NN |-> <<>>]]
    /\ dnCur    = [d \in DN |-> IF StartRegistered THEN InitKeyIds[InitActive].cur ELSE None]
    /\ dnKeys   = [d \in DN |->
                      IF StartRegistered
                      THEN UNION {{InitKeyIds[n].cur, InitKeyIds[n].next} : n \in NN}
                      ELSE {}]
    /\ cliDek   = None
    /\ ops      = {}
    /\ nextOp   = 1
    /\ targetFired = FALSE
    /\ fireInfo = NoFire

-----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode: block-key rotation, HeartbeatManager.Monitor (HBM:538-575).    *)
(* Rotation and the needKeyUpdate marking are separate steps of the        *)
(* Monitor thread; neither checks HA state or safe mode, so standby NNs    *)
(* rotate and push too (analysis 4.3).                                     *)
(***************************************************************************)
NNRotate(n) ==
    \* The Monitor runs the mark loop of one rotation before it can rotate again.
    /\ ~markPending[n]
    \* HBM:552 blockManager.shouldUpdateBlockKey(now - lastBlockKeyUpdate)
    \*   -> BM:808-810 -> BTSM:250-255 updateKeys(long) -> BTSM:260-281 updateKeys()
    \* BTSM:266 removeExpiredKeys(): nothing expires within the <= 2 rotations
    \*   per NN process that every MC configuration allows (MC.tla ASSUME).
    \* BTSM:268-270 the retiring currentKey stays in allKeys (new expiry now+I+L).
    \* BTSM:272-274 currentKey := nextKey.
    /\ nnCur' = [nnCur EXCEPT ![n] = nnNext[n]]
    \* BTSM:276-279 setSerialNo(serialNo + 1); nextKey := new key; allKeys.put.
    /\ nnNext' = [nnNext EXCEPT ![n] = FreshKey(n)]
    /\ nnKeys' = [nnKeys EXCEPT ![n] = @ \cup {FreshKey(n)}]
    /\ keyOwner' = keyOwner @@ (FreshKey(n) :> n)
    /\ nnEp' = [nnEp EXCEPT ![n] = @ + 1]
    \* HBM:552 returned true: the mark loop (HBM:553-557) comes next.
    /\ markPending' = [markPending EXCEPT ![n] = TRUE]
    /\ UNCHANGED <<nnInc, haVars, needKU, live, known, xferQ, rpcVars,
                   actorVars, dnKeyVars, cliVars, tgtVars>>

NNMarkKeyUpdate(n) ==
    /\ markPending[n]
    \* HBM:553-557 synchronized (HeartbeatManager.this):
    \*   for (DatanodeDescriptor d : datanodes) d.setNeedKeyUpdate(true);
    \* `datanodes` is the live list: a node that is registering but has not
    \* joined it yet (DM:1209 vs DM:1300/1337, W4) or is dead is not marked.
    /\ needKU' = [needKU EXCEPT ![n] = @ \cup live[n]]
    \* HBM:558 lastBlockKeyUpdate = now
    /\ markPending' = [markPending EXCEPT ![n] = FALSE]
    /\ UNCHANGED <<keyVars, haVars, live, known, xferQ, rpcVars, actorVars,
                   dnKeyVars, cliVars, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* NameNode: heartbeat handling, FSN:4484-4517 -> DM:1856-1990.            *)
(* The key-update part BM:1671-1678 is split into check+export (1674-1675) *)
(* and clear (1676): neither is atomic with the Monitor's rotate+mark (W3).*)
(***************************************************************************)
NNHandleHeartbeat(n, d) ==
    \* BPSA:694-711: the actor heartbeats only after its initial registration
    \* (connectToNNAndHandshake, BPSA:302-325); it keeps heartbeating while
    \* its command thread re-registers.
    /\ act[d][n] \in {"run", "rereg"}
    \* BPSA:711 sendHeartBeat is a blocking RPC: one heartbeat per actor.
    /\ hb[n][d].st = "idle"
    /\ LET registered == d \in live[n]
           \* DM:1864-1878 unknown node, or !isRegistered() (= !isAlive() ||
           \* forceRegistration, DD:1131-1135): reply RegisterCommand.REGISTER only.
           \* DM:1903-1952 pending replication work (only the active NN's
           \* redundancy monitor schedules it).
           x  == IF registered /\ role[n] = "active" THEN xferQ[n][d] ELSE <<>>
           \* DM:1971 -> BM:1674 isBlockTokenEnabled() && nodeinfo.needKeyUpdate()
           ku == registered /\ d \in needKU[n]
           \* (safe mode DM:1884-1886 and pending block recovery DM:1889-1893
           \* only defer the push; in this untimed model that is the same as a
           \* later heartbeat, so they are not modeled.)
           resp == [st   |-> IF ku THEN "kuPending" ELSE "resp",
                    \* BM:1675 new KeyUpdateCommand(blockTokenSecretManager.exportKeys())
                    ku   |-> IF ku THEN Export(n) ELSE NoEx,
                    reg  |-> ~registered,
                    xfer |-> x,
                    \* FSN:4505-4507 NNHAStatusHeartbeat(state, txid)
                    ha   |-> role[n],
                    tm   |-> actTerm[n]]
       IN /\ ~(SkipNoopHeartbeats /\ IsNoopResponse(d, n, resp))
          /\ hb' = [hb EXCEPT ![n][d] = resp]
          \* DM:1922-1950 the command takes the pending transfer off the node.
          /\ xferQ' = [xferQ EXCEPT ![n][d] = IF registered /\ role[n] = "active"
                                               THEN <<>> ELSE @]
    /\ UNCHANGED <<keyVars, haVars, markPending, needKU, live, known, reg,
                   actorVars, dnKeyVars, cliVars, tgtVars>>

NNHeartbeatClearKeyUpdate(n, d) ==
    /\ hb[n][d].st = "kuPending"
    \* BM:1676 nodeinfo.setNeedKeyUpdate(false).  A rotation and mark between
    \* BM:1675 and here is lost for this node (W3).
    /\ needKU' = [needKU EXCEPT ![n] = @ \ {d}]
    /\ hb' = [hb EXCEPT ![n][d].st = "resp"]
    /\ UNCHANGED <<keyVars, haVars, markPending, live, known, xferQ, reg,
                   actorVars, dnKeyVars, cliVars, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Registration.  DN side BPSA:302-325 / 838-879 / 967-984; NN side        *)
(* FSN:4454-4460 -> DM:1188-1348.  The NN exports keys (DM:1209) before the *)
(* node joins the live list (DM:1300 / 1332-1337).  The Monitor takes no   *)
(* FSN lock, so a rotation can fall between the two (W4).  (The BM write   *)
(* lock excludes other heartbeats/registrations at this NN; that does not  *)
(* change any key-relevant outcome, since only the Monitor changes keys.)  *)
(***************************************************************************)
DNHandshake(d, n) ==
    /\ act[d][n] = "init"
    \* BPSA:308 retrieveNamespaceInfo (versionRequest); BPSA:318 state = nsInfo.getState()
    /\ astate' = [astate EXCEPT ![d][n] = role[n]]
    \* BPSA:324 register(nsInfo) -> BPSA:845-851 bpNamenode.registerDatanode (blocking, retried)
    /\ act' = [act EXCEPT ![d][n] = "reg"]
    /\ reg' = [reg EXCEPT ![n][d] = [st |-> "want", ex |-> NoEx]]
    /\ UNCHANGED <<keyVars, haVars, nnVars, hb, bpActive, lastClaim, cmdQ,
                   dnKeyVars, cliVars, tgtVars>>

NNRegisterExport(n, d) ==
    /\ reg[n][d].st = "want"
    \* DM:1209 nodeReg.setExportedKeys(blockManager.getBlockKeys())
    \*   -> BM:1639-1642 -> BTSM:201-208 exportKeys()
    /\ reg' = [reg EXCEPT ![n][d] = [st |-> "exported", ex |-> Export(n)]]
    /\ UNCHANGED <<keyVars, haVars, nnVars, hb, actorVars, dnKeyVars, cliVars, tgtVars>>

NNRegisterJoin(n, d) ==
    /\ reg[n][d].st = "exported"
    \* DM:1220-1312 known node: HBM:231-239 register(nodeS) adds it to the live
    \*   list only if it is not alive (a live node stays where it is).
    \* DM:1314-1337 new node: addDatanode, HBM:245-249 heartbeatManager.addDatanode.
    \* needKeyUpdate is not reset (DD:1003-1014 updateRegInfo); a new
    \* descriptor starts with false (DD:185).
    /\ known' = [known EXCEPT ![n] = @ \cup {d}]
    /\ live'  = [live EXCEPT ![n] = @ \cup {d}]
    /\ reg' = [reg EXCEPT ![n][d].st = "joined"]
    /\ UNCHANGED <<keyVars, haVars, markPending, needKU, xferQ, hb, actorVars,
                   dnKeyVars, cliVars, tgtVars>>

\* BTSM:228-244 addKeys(exportedKeys, updateCurrentKey) on the worker BTSM
\* (synchronized).  BTSM:234 removeExpiredKeys(): nothing expires within the
\* modeled bounds.
AddKeys(d, e, upd) ==
    \* BTSM:235-237 if (updateCurrentKey || currentKey == null) currentKey = exported current
    /\ dnCur'  = [dnCur EXCEPT ![d] = IF upd \/ @ = None THEN e.cur ELSE @]
    \* BTSM:238-243 put every exported key (overwrite by id)
    /\ dnKeys' = [dnKeys EXCEPT ![d] = @ \cup e.keys]

DNRegistrationSucceeded(d, n) ==
    /\ reg[n][d].st = "joined"
    \* BPSA:848-871 RPC returned -> BPOS:422-445 registrationSucceeded (BPOS write lock):
    \*   BPOS:434 -> DN:2115-2146 isBlockTokenEnabled from the first export; worker BTSM created once.
    \*   BPOS:436-440 updateCurrentKey = actor.state == null || actor.state == ACTIVE
    \*   (the actor's own, possibly stale, state; not bpServiceToActive).
    /\ AddKeys(d, reg[n][d].ex, astate[d][n] \in {None, "active"})
    /\ reg' = [reg EXCEPT ![n][d] = RegNone]
    \* Initial: offerService starts.  Re-registration: BPSA:980-981 returns to
    \* the command thread.
    /\ act' = [act EXCEPT ![d][n] = "run"]
    /\ UNCHANGED <<keyVars, haVars, nnVars, hb, astate, bpActive, lastClaim,
                   cmdQ, cliVars, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* DataNode: heartbeat response and command processing.                    *)
(***************************************************************************)
DNHandleHeartbeatResponse(d, n) ==
    /\ hb[n][d].st = "resp"
    /\ LET r  == hb[n][d]
           as == ActorStates(d, n, r)
           \* BPSA:755 the other commands, in order (REGISTER comes alone,
           \* DM:1867/1877).  A REGISTER while one is already queued or running
           \* is dropped: it would only repeat that registration (reduction).
           rest == (IF r.xfer # <<>> THEN <<XferCmd(r.xfer)>> ELSE <<>>)
                   \o (IF r.reg /\ ~RegPending(d, n) THEN <<RegCmd>> ELSE <<>>)
       IN \* BPSA:733-734 bpos.updateActorStatesFromHeartbeat (BPOS:576-617)
          /\ bpActive'  = [bpActive EXCEPT ![d] = as.bpa]
          /\ lastClaim' = [lastClaim EXCEPT ![d] = as.lc]
          \* BPSA:735-740 state = stateFromResp (also after a rejected claim)
          /\ astate' = [astate EXCEPT ![d][n] = r.ha]
          \* BPSA:745-754 the KeyUpdateCommand is enqueueFirst'ed (BPSA:1499-1508)
          /\ cmdQ' = [cmdQ EXCEPT ![d][n] =
                        (IF r.ku # NoEx THEN <<KuCmd(r.ku)>> ELSE <<>>) \o @ \o rest]
          /\ hb' = [hb EXCEPT ![n][d] = HBIdle]
    /\ UNCHANGED <<keyVars, haVars, nnVars, reg, act, dnKeyVars, cliVars, tgtVars>>

DNProcessCommand(d, n) ==
    \* BPSA:1427-1445 CommandProcessingThread: take the queue head.  The thread
    \* is busy (not taking commands) while it runs a reRegister (BPSA:845-864).
    /\ act[d][n] = "run"
    /\ cmdQ[d][n] # <<>>
    /\ LET c == Head(cmdQ[d][n])
           \* BPOS:690-698 active or standby is decided when the command runs
           isActive == bpActive[d] = n
       IN /\ cmdQ' = [cmdQ EXCEPT ![d][n] = Tail(@)]
          /\ IF c.t = "reg"
             THEN \* BPOS:681-688 DNA_REGISTER -> actor.reRegister() (BPSA:967-984):
                  \* retrieveNamespaceInfo does not refresh `state`; register(nsInfo).
                  /\ act' = [act EXCEPT ![d][n] = "rereg"]
                  /\ reg' = [reg EXCEPT ![n][d] = [st |-> "want", ex |-> NoEx]]
                  /\ UNCHANGED <<dnKeyVars, ops, nextOp>>
             ELSE IF c.t = "ku"
             THEN \* BPOS:788-794 from the active: addKeys(..., true)
                  \* BPOS:828-835 from a standby: addKeys(..., false)
                  /\ AddKeys(d, c.ex, isActive)
                  /\ UNCHANGED <<act, reg, ops, nextOp>>
             ELSE \* c.t = "xfer": BPOS:738-743 DNA_TRANSFER (active only; a standby's is
                  \* ignored, BPOS:837-848) -> DN:2899 transferBlocks -> DN:2835-2896
                  \* transferBlock: a DataTransfer(targets, ..., PIPELINE_SETUP_CREATE, "")
                  \* runs on the xferService.
                  /\ IF isActive
                     THEN /\ ops' = ops \cup {NewOp("xfer", NoTok, c.tg, "xferTok", d)}
                          /\ nextOp' = nextOp + 1
                     ELSE UNCHANGED <<ops, nextOp>>
                  /\ UNCHANGED <<act, reg, dnKeyVars>>
    /\ UNCHANGED <<keyVars, haVars, nnVars, hb, astate, bpActive, lastClaim,
                   cliDek, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Client side: token issue at the NN, DataEncryptionKey, connect.         *)
(***************************************************************************)
ClientAddBlock(n, p) ==
    \* DS:1816-1842 setupPipelineForCreate -> locateFollowingBlock (addBlock RPC to
    \* the active NN); DS:1835 accessToken = lb.getBlockToken().  Every pipeline
    \* setup takes a fresh token (DS:1657-1666 for append/recovery).
    /\ role[n] = "active"
    /\ p \in Pipelines(live[n])
    \* FSDW:209-215 setBlockToken(lBlk, WRITE) -> BM:1645-1669 -> BTSM:293-305
    \*   -> new Token(id, this) -> BTSM:482-496 createPassword (NN currentKey)
    /\ ops' = ops \cup {NewOp("write", NNToken(n), p, "connect", "client")}
    /\ nextOp' = nextOp + 1
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   cliDek, tgtVars>>

ClientGetBlockLocations(n) ==
    \* getBlockLocations (a read, or getFileChecksum's block locations) at the active NN.
    /\ role[n] = "active"
    /\ live[n] # {}
    \* BM:1480-1492 createLocatedBlock(..., READ) -> BM:1645-1669 -> BTSM:482-496.
    \* The replica the client reads from is chosen when it connects (ClientConnect).
    /\ ops' = ops \cup {NewOp("read", NNToken(n), <<>>, "connect", "client")}
    /\ nextOp' = nextOp + 1
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   cliDek, tgtVars>>

ClientFetchDEK(n) ==
    /\ role[n] = "active"
    /\ cliDek = None
    /\ \E op \in ops : op.ph = "connect"
    \* DFSC:1855-1863 newDataEncryptionKey: encryptionKey == null ->
    \*   namenode.getDataEncryptionKey() -> NNRPC:1940-1943 -> BM:1680-1686
    \*   -> BTSM:532-543 generateDataEncryptionKey (NN currentKey's id).
    \* (Its expiry, DFSC:1858-1859, is not modeled: the key id stays valid at
    \* DNs within the modeled bounds.)
    /\ cliDek' = nnCur[n]
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   ops, nextOp, tgtVars>>

ClientConnect(i, d) ==
    /\ i \in OpIds
    /\ LET op == Op(i) IN
       /\ op.ph = "connect"
       /\ cliDek # None
       \* write: nodes[0] of the pipeline (DS:1894).  read: the replica the client
       \* picks (DFSInputStream.chooseDataNode; placement abstracted: any DN --
       \* a DN without the block pool fails the SASL step).
       /\ IF op.pipe = <<>> THEN d \in DN ELSE d = op.pipe[1]
       \* DS:1894-1901 socketSend(s, ..., dfsClient, accessToken, nodes[0]) (write);
       \* peerSend for reads.  SDTC:222-237 -> SDTC:259-268 -> SDTC:312-334: the
       \* client passes no secretKey, so the client hop never re-signs (SDTC:320).
       /\ ops' = (ops \ {op}) \cup
                 {[op EXCEPT !.pipe = IF op.pipe = <<>> THEN <<d>> ELSE op.pipe,
                             !.dek = cliDek, !.pos = 1, !.ph = "sasl"]}
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   cliDek, nextOp, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* DataNode side of DataTransferProtocol.                                  *)
(***************************************************************************)
DNTransferCreateToken(i) ==
    /\ i \in OpIds
    /\ LET op == Op(i) IN
       /\ op.ph = "xferTok"
       \* DN:3074-3076 getBlockAccessToken(b, WRITE, targetStorageTypes, ids)
       \*   -> DN:3155-3165 -> BPTSM:153-158 -> BTSM:293-305 -> BTSM:482-496
       \*   (this DN's worker currentKey supplies keyId and secret).
       /\ ops' = (ops \ {op}) \cup {[op EXCEPT !.tok = DNToken(op.src), !.ph = "dek"]}
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   cliDek, nextOp, tgtVars>>

DNSaslSendEncrypted(i) ==
    /\ i \in OpIds
    /\ LET op == Op(i)
           s  == Sender(op)
           t2 == IF op.sec # None THEN [op.tok EXCEPT !.sk = op.sec] ELSE op.tok
       IN /\ op.ph = "dek"
          \* DXC:830-832 (mirror) / DN:3082-3085 (DataTransfer): saslClient.socketSend
          \* SDTC:222-237 checkTrustAndSend -> encryptionKeyFactory.newDataEncryptionKey()
          \*   -> DN:3174-3184 -> BPTSM:167-169 -> BTSM:532-543 (this DN's currentKey,
          \*   read again under the lock: a separate read from DXC:826-828).
          \* SDTC:264-268 encrypted handshake -> SDTC:318-324: if (secretKey != null)
          \*   updateToken (SDTC:450-460): password = HMAC(secretKey, id'), the
          \*   identifier keeps its keyId (only handshakeMsg changes).
          /\ ops' = (ops \ {op}) \cup
                    {[op EXCEPT !.dek = dnCur[s], !.tok = t2, !.sec = None,
                                !.pos = op.pos + 1, !.ph = "sasl"]}
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   cliDek, nextOp, tgtVars>>

DNSaslReceiveEncrypted(i) ==
    /\ i \in OpIds
    /\ LET op == Op(i)
           v  == op.pipe[op.pos]
           \* DXC:236-238 saslServer.receive -> SDTS:117-124 (dfs.encrypt.data.transfer)
           \*   -> SDTS:170-194 -> SDTS:282-294 getEncryptionKeyFromUserName
           \*   -> BPTSM:171-174 (BPTSM:53-59: the block pool must be registered)
           \*   -> BTSM:553-565 allKeys.get(keyId), else InvalidEncryptionKeyException.
           ok == Ready(v) /\ op.dek \in dnKeys[v]
       IN /\ op.ph = "sasl"
          /\ IF ok
             THEN \* the handshake completes; the sender's op request
                  \* (DS:1922 / DXC:845-857 / DN:3099-3103) reaches v.
                  /\ ops' = (ops \ {op}) \cup {[op EXCEPT !.ph = "check"]}
                  /\ UNCHANGED cliDek
             ELSE \* the handshake fails at the sender with an IOException.
                  \* Client hop: DS:1961-1968 clearDataEncryptionKey (its retry with a
                  \* new key is a new attempt; not modeled).  DN hop: DXC:877-902
                  \* (client write: ERROR upstream; DataTransfer: continue without the
                  \* mirror).  The op ends here either way.
                  /\ ops' = ops \ {op}
                  /\ cliDek' = IF op.src = "client" /\ op.pos = 1 THEN None ELSE cliDek
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   nextOp, tgtVars>>

(***************************************************************************)
(* The target.  DXC:731-733 (writeBlock) / DXC:594 (readBlock) /           *)
(* DXC:1013 (blockChecksum) -> DXC:1442-1479 checkAccess                   *)
(*   -> BPTSM:133-139 -> BTSM:404-421.                                     *)
(***************************************************************************)
TargetCheck(i) ==
    /\ i \in OpIds
    /\ LET op == Op(i)
           v  == op.pipe[op.pos]
           t  == op.tok
       IN /\ op.ph = "check"
          \* DXC:1449 checkAndWaitForBP: waits until v's block pool registration exists.
          /\ Ready(v)
          \* DXC:1450 datanode.isBlockTokenEnabled: TRUE (tokens on in every config here).
          \* BTSM:407-415 the identifier parses; readFields caches the raw bytes (BTI:220-226).
          \* BTSM:416 -> BTSM:316-326, 345-372, 381-401: user (null at DXC:1454: skipped),
          \*   bpid, blockId, mode, storage types/ids: always pass for a token built
          \*   for this block and pipeline (brief 3.2).
          /\ IF TokExpired(t)
             THEN \* BTSM:364-367 isExpired: throws at 365 (not the target)
                  /\ ops' = ops \ {op}
                  /\ UNCHANGED tgtVars
             ELSE IF t.kid \notin dnKeys[v]
             THEN \* BTSM:513-521 allKeys.get(keyId) == null: throws at 518 (not the target)
                  /\ ops' = ops \ {op}
                  /\ UNCHANGED tgtVars
             ELSE IF t.sk # t.kid
             THEN \* BTSM:417 !isEqual(HMAC(K_v[keyId], id'), password)
                  \* BTSM:418 throw new InvalidToken("... doesn't have the correct token password")
                  /\ targetFired' = TRUE
                  /\ fireInfo' = [dn |-> v, kid |-> t.kid, sk |-> t.sk, k |-> op.k,
                                  rsr |-> IF op.pos > 1 THEN op.pipe[op.pos - 1] ELSE None]
                  /\ UNCHANGED ops
             ELSE \* BTSM:417 passes.
                  /\ ops' = IF op.k \in {"write", "xfer"} /\ op.pos < Len(op.pipe)
                            \* DXC:794 targets.length > 0: set up the mirror
                            THEN (ops \ {op}) \cup {[op EXCEPT !.ph = "mirror"]}
                            \* last DN of the pipeline, or a read/checksum: done
                            ELSE ops \ {op}
                  /\ UNCHANGED tgtVars
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   cliDek, nextOp>>

DNWriteBlockMirrorSecret(i) ==
    /\ i \in OpIds
    /\ LET op == Op(i)
           r  == op.pipe[op.pos]
       IN /\ op.ph = "mirror"
          \* DXC:757-790 the block receiver opens (assumed to succeed).
          \* DXC:794-822 connect to targets[0] (assumed to succeed).
          \* DXC:823-829 if (dnConf.overwriteDownstreamDerivedQOP)
          \*   secretKey = blockPoolTokenSecretManager.get(bpid).getCurrentKey().getKey();
          /\ ops' = (ops \ {op}) \cup
                    {[op EXCEPT !.sec = IF OverwriteQOP THEN dnCur[r] ELSE None,
                                !.ph = "dek"]}
    /\ UNCHANGED <<keyVars, haVars, nnVars, rpcVars, actorVars, dnKeyVars,
                   cliDek, nextOp, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Environment and faults (bounded in MC.tla).                             *)
(***************************************************************************)
NNScheduleReplication(n, s, g) ==
    \* Abstract redundancy monitor (BM.computeDatanodeWork -> ReplicationWork):
    \* a block with one live replica on s gets XferTargets new targets in one
    \* command (DatanodeDescriptor.addBlockToBeReplicated(block, targets)).
    /\ role[n] = "active"
    /\ s \in live[n]
    /\ xferQ[n][s] = <<>>
    /\ g \in InjSeqs(live[n] \ {s}, XferTargets)
    /\ xferQ' = [xferQ EXCEPT ![n][s] = g]
    /\ UNCHANGED <<keyVars, haVars, markPending, needKU, live, known, rpcVars,
                   actorVars, dnKeyVars, cliVars, tgtVars>>

NNFailover(a, b) ==
    \* Failover a -> b: a transitions to standby, b to active.
    /\ a # b
    /\ role[a] = "active"
    /\ role[b] = "standby"
    /\ role' = [role EXCEPT ![a] = "standby", ![b] = "active"]
    \* b's claims carry a txid above every claim a made (b has applied all of
    \* a's edits and opened a new segment).
    /\ term' = term + 1
    /\ actTerm' = [actTerm EXCEPT ![b] = term + 1]
    \* FSN:1412-1430 startActiveServices -> DM:2092-2104
    \*   markAllDatanodesStaleAndSetKeyUpdateIfNeed: every node in datanodeMap.
    \* b keeps its own keys; it does not rotate (analysis 4.3).
    /\ needKU' = [needKU EXCEPT ![b] = @ \cup known[b]]
    /\ UNCHANGED <<keyVars, markPending, live, known, xferQ, rpcVars,
                   actorVars, dnKeyVars, cliVars, tgtVars>>

NNRestart(n) ==
    \* A NameNode process restart (a non-HA NN, or an HA standby).
    /\ Cardinality(NN) = 1 \/ role[n] = "standby"
    \* BM:702-762 a new master BTSM: BTSM:154 new random serial, BTSM:174-198
    \* two fresh keys.  Block keys are not persisted.
    /\ LET k1 == FreshKey(n)
           k2 == k1 + 1
       IN /\ nnCur'  = [nnCur EXCEPT ![n] = k1]
          /\ nnNext' = [nnNext EXCEPT ![n] = k2]
          /\ nnKeys' = [nnKeys EXCEPT ![n] = {k1, k2}]
          /\ keyOwner' = keyOwner @@ (k1 :> n) @@ (k2 :> n)
    /\ nnEp'  = [nnEp EXCEPT ![n] = 0]
    /\ nnInc' = [nnInc EXCEPT ![n] = @ + 1]
    \* New DatanodeManager / HeartbeatManager: no known or live node, no flag,
    \* a new Monitor.  (Its first pass rotates at once when the host's
    \* monotonic clock exceeds the interval; that is an ordinary NNRotate.)
    /\ live'  = [live EXCEPT ![n] = {}]
    /\ known' = [known EXCEPT ![n] = {}]
    /\ needKU' = [needKU EXCEPT ![n] = {}]
    /\ markPending' = [markPending EXCEPT ![n] = FALSE]
    /\ xferQ' = [xferQ EXCEPT ![n] = [d \in DN |-> <<>>]]
    \* RPCs inside the old process fail; the DN retries them (BPSA:845-864, and
    \* the offerService loop for heartbeats).  Replies already sent stay in flight.
    /\ hb'  = [hb EXCEPT ![n] = [d \in DN |->
                  IF hb[n][d].st = "kuPending" THEN HBIdle ELSE hb[n][d]]]
    /\ reg' = [reg EXCEPT ![n] = [d \in DN |->
                  IF reg[n][d].st = "exported" THEN [st |-> "want", ex |-> NoEx]
                  ELSE reg[n][d]]]
    /\ UNCHANGED <<haVars, actorVars, dnKeyVars, cliVars, tgtVars>>

NNRemoveDeadDatanode(n, d) ==
    \* HBM:548-550 heartbeatCheck -> DM:921 removeDeadDatanode -> HBM:255-262
    \* removeDatanode: setAlive(false), off the live list (still in datanodeMap).
    \* The next heartbeat gets REGISTER (DM:1876-1878).
    /\ d \in live[n]
    /\ live' = [live EXCEPT ![n] = @ \ {d}]
    /\ UNCHANGED <<keyVars, haVars, markPending, needKU, known, xferQ, rpcVars,
                   actorVars, dnKeyVars, cliVars, tgtVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Next-state relation.  Once the target fired, everything stops.          *)
(***************************************************************************)
Next ==
    /\ ~targetFired
    /\ \/ \E n \in NN : NNRotate(n) \/ NNMarkKeyUpdate(n)
       \/ \E n \in NN, d \in DN :
             \/ NNHandleHeartbeat(n, d)
             \/ NNHeartbeatClearKeyUpdate(n, d)
             \/ NNRegisterExport(n, d)
             \/ NNRegisterJoin(n, d)
             \/ DNHandshake(d, n)
             \/ DNRegistrationSucceeded(d, n)
             \/ DNHandleHeartbeatResponse(d, n)
             \/ DNProcessCommand(d, n)
       \/ \E i \in OpIds, d \in DN : ClientConnect(i, d)
       \/ \E i \in OpIds :
             \/ DNTransferCreateToken(i)
             \/ DNSaslSendEncrypted(i)
             \/ DNSaslReceiveEncrypted(i)
             \/ TargetCheck(i)
             \/ DNWriteBlockMirrorSecret(i)
       \/ \E n \in NN : ClientFetchDEK(n)
       \/ \E n \in NN : \E p \in Pipelines(live[n]) : ClientAddBlock(n, p)
       \/ \E n \in NN : ClientGetBlockLocations(n)
       \/ \E n \in NN, s \in DN : \E g \in InjSeqs(live[n] \ {s}, XferTargets) :
             NNScheduleReplication(n, s, g)
       \/ \E a, b \in NN : NNFailover(a, b)
       \/ \E n \in NN : NNRestart(n)
       \/ \E n \in NN, d \in DN : NNRemoveDeadDatanode(n, d)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)
\* The target oracle: the failing branch at BTSM:418 is never taken.
TargetSafe == ~targetFired

KeyIds == DOMAIN keyOwner
OwnedBy(n) == {k \in KeyIds : keyOwner[k] = n}
ExOK(e, n) == e = NoEx \/ (e.cur \in e.keys /\ e.keys \subseteq OwnedBy(n))

\* Structural sanity 1: types.
TypeOK ==
    /\ KeyIds \subseteq Nat
    /\ keyOwner \in [KeyIds -> NN]
    /\ nnCur \in [NN -> KeyIds]
    /\ nnNext \in [NN -> KeyIds]
    /\ nnKeys \in [NN -> SUBSET KeyIds]
    /\ nnEp \in [NN -> Nat]
    /\ nnInc \in [NN -> Nat \ {0}]
    /\ role \in [NN -> {"active", "standby"}]
    /\ actTerm \in [NN -> Nat]
    /\ term \in Nat
    /\ markPending \in [NN -> BOOLEAN]
    /\ needKU \in [NN -> SUBSET DN]
    /\ live \in [NN -> SUBSET DN]
    /\ known \in [NN -> SUBSET DN]
    /\ \A n \in NN : live[n] \subseteq known[n]
    /\ xferQ \in [NN -> [DN -> Seq(DN)]]
    /\ \A n \in NN, d \in DN :
          /\ hb[n][d].st \in {"idle", "kuPending", "resp"}
          /\ hb[n][d].reg \in BOOLEAN
          /\ hb[n][d].ha \in {"active", "standby"}
          /\ reg[n][d].st \in {"none", "want", "exported", "joined"}
          /\ act[d][n] \in {"init", "reg", "run", "rereg"}
          /\ astate[d][n] \in {None, "active", "standby"}
          /\ \A i \in 1..Len(cmdQ[d][n]) : cmdQ[d][n][i].t \in {"ku", "reg", "xfer"}
    /\ bpActive \in [DN -> NN \cup {None}]
    /\ lastClaim \in [DN -> Nat]
    /\ dnCur \in [DN -> KeyIds \cup {None}]
    /\ dnKeys \in [DN -> SUBSET KeyIds]
    /\ cliDek \in KeyIds \cup {None}
    /\ nextOp \in Nat \ {0}
    /\ \A op \in ops :
          /\ op.k \in {"write", "read", "xfer"}
          /\ op.ph \in {"connect", "xferTok", "dek", "sasl", "check", "mirror"}
          /\ op.pipe \in Seq(DN)
          /\ op.pos \in 0..Len(op.pipe)
          /\ op.src \in DN \cup {"client"}
          /\ op.sec \in KeyIds \cup {None}
          /\ op.dek \in KeyIds \cup {None}
          /\ op.id < nextOp
    /\ targetFired \in BOOLEAN

\* Structural sanity 2 (brief 5): a token or message carries only key ids
\* that its signer or sender held.
TokenProvenance ==
    /\ \A op \in ops : op.ph # "xferTok" =>
          /\ op.tok.kid \in KeyIds
          /\ op.tok.sk \in KeyIds
          \* a token is re-signed only on a DN -> DN hop with the overwrite flag
          /\ (~OverwriteQOP \/ op.pos <= 1) => op.tok.sk = op.tok.kid
          \* an NN-signed token names a key of its issuer
          /\ op.tok.iss # None => keyOwner[op.tok.kid] = op.tok.iss
    /\ \A d \in DN : dnCur[d] # None => dnCur[d] \in dnKeys[d]
    /\ \A n \in NN, d \in DN :
          /\ ExOK(hb[n][d].ku, n)
          /\ ExOK(reg[n][d].ex, n)
          /\ \A i \in 1..Len(cmdQ[d][n]) : ExOK(cmdQ[d][n][i].ex, n)
    /\ \A n \in NN : nnCur[n] \in nnKeys[n] /\ nnNext[n] \in nnKeys[n]
                     /\ nnKeys[n] \subseteq OwnedBy(n)

=============================================================================
