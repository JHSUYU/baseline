-------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* Ad hoc coordination target zk-adhoc-b3 (Apache ZooKeeper @ eab16599).   *)
(*                                                                         *)
(* Target check (the oracle):                                              *)
(*   FinalRequestProcessor.handleGetDataRequest(Record, ServerCnxn, ...)   *)
(*     DataNode n = zks.getZKDatabase().getNode(path);        FRP:672      *)
(*     if (n == null)                                         FRP:673      *)
(*         throw new KeeperException.NoNodeException();       FRP:674      *)
(*   TargetSafe == ~targetFired                                            *)
(*                                                                         *)
(* System category: A (distributed / message passing).  A standalone       *)
(* server is a pipeline of single-threaded stages joined by FIFO queues    *)
(* (RequestThrottler -> PrepRequestProcessor -> Sync+FinalRequestProcessor)*)
(* fed by the workload client and by the ContainerManager timer thread,    *)
(* which injects deleteContainer requests straight into PRP's queue.       *)
(*                                                                         *)
(* Scenario 1 (brief section 2): the ContainerManager decides "delete P"   *)
(* from a scan of the applied DataTree, but the request it posts carries   *)
(* only the path (CM:145-146). PRP re-validates existence, child count and *)
(* EphemeralType != NORMAL only (PRP:330-336), so a PERSISTENT node        *)
(* re-created at P after the scan (owner 0 -> VOID) is deleted, and the    *)
(* client's next getData(P) finds n == null.                               *)
(*                                                                         *)
(* Source paths are relative to                                            *)
(*   zookeeper-server/src/main/java/org/apache/zookeeper/server/           *)
(*   FRP  = FinalRequestProcessor.java   PRP = PrepRequestProcessor.java   *)
(*   CM   = ContainerManager.java        DT  = DataTree.java               *)
(*   ET   = EphemeralType.java           ZKS = ZooKeeperServer.java        *)
(*   SRP  = SyncRequestProcessor.java    RT  = RequestThrottler.java       *)
(*   ZKD  = ZKDatabase.java              NHM = NodeHashMapImpl.java        *)
(* and the workload                                                        *)
(*   TEST = zookeeper-server/src/test/java/org/apache/zookeeper/server/    *)
(*          TestAdhocWorkloadB3.java                                       *)
(*   ZK   = zookeeper-server/src/main/java/org/apache/zookeeper/ZooKeeper.java *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    P,      \* "/adhoc-workload-b3"        TEST:41
    C,      \* "/adhoc-workload-b3/child"  TEST:57
    Root    \* "/"  (TEST:74 exists("/"); the parent path "" of P is the
            \*       root's alias, DT:287-289). The root always exists and no
            \*       modeled guard reads its record, so it carries no state.

ASSUME Cardinality({P, C, Root}) = 3

\* The znodes whose state the target depends on. Brief section 4 ("Guard operand").
Paths == {P, C}

\* Parent path, as PRP:300-305/726-731 and DT:434-436/535-536 compute it.
Parent(p) == IF p = C THEN P ELSE Root

-----------------------------------------------------------------------------
(***************************************************************************)
(* Ephemeral owners and EphemeralType.get (ET:168-189).                    *)
(* zookeeper.extendedTypesEnabled is not set by the workload (ET:149,      *)
(* 157-158), so the extended branch at ET:169-184 is never taken.          *)
(***************************************************************************)
OWNER_ZERO                == "owner=0"               \* PRP:692 (PERSISTENT create)
CONTAINER_EPHEMERAL_OWNER == "owner=Long.MIN_VALUE"  \* ET:130; PRP:693-694
Owners == {OWNER_ZERO, CONTAINER_EPHEMERAL_OWNER}

EphemeralTypeOf(o) ==
    IF o = CONTAINER_EPHEMERAL_OWNER THEN "CONTAINER"   \* ET:185-186
    ELSE IF o = OWNER_ZERO THEN "VOID"                  \* ET:188 (owner == 0)
    ELSE "NORMAL"                                       \* ET:188 (a session id; never created by the workload)

(***************************************************************************)
(* Node record: the fields of a DataNode / ChangeRecord that modeled code   *)
(* reads.  ex = present, owner = stat.ephemeralOwner, cv = stat.cversion,  *)
(* nch = number of children (ChangeRecord.childCount), cz = stat.czxid.    *)
(* Data, ACL, version, mtime and pzxid are not on the target's path        *)
(* (brief section 3.2).                                                    *)
(***************************************************************************)
NoNode == [ex |-> FALSE, owner |-> OWNER_ZERO, cv |-> 0, nch |-> 0, cz |-> 0]

\* DT.createStat (DT:1958-1969): cversion 0, czxid = zxid; a new node has no children.
NewNode(o, z) == [ex |-> TRUE, owner |-> o, cv |-> 0, nch |-> 0, cz |-> z]

-----------------------------------------------------------------------------
(***************************************************************************)
(* Requests, transactions, pipeline items, error codes                     *)
(***************************************************************************)
Ops == {"createContainer", "create", "delete", "deleteContainer", "getData", "exists"}

\* src = "client": cnxn != null; src = "cm": built by CM:145-146 with cnxn == null.
Req(op, path, src) == [op |-> op, path |-> path, src |-> src]

\* KeeperException.Code names (KeeperException.java code table).
ErrCodes == {"OK", "NONODE", "NODEEXISTS", "NOTEMPTY", "BADVERSION",
             "NOCHILDRENFOREPHEMERALS"}

NoReply == "none"

(***************************************************************************)
(* Txn attached by PRP (request.setTxn).  kind:                            *)
(*   "none"   - read: hdr stays null (PRP:759, 892-909)                     *)
(*   "create" - CreateTxn / CreateContainerTxn (PRP:683-689)               *)
(*   "delete" - DeleteTxn (PRP:338, 364)                                   *)
(*   "error"  - hdr type error + ErrorTxn(code) (PRP:914-918)              *)
(* pcv is the txn's parentCVersion (PRP:681, 684, 688).                    *)
(***************************************************************************)
NoTxn == [kind |-> "none", path |-> Root, owner |-> OWNER_ZERO, pcv |-> 0,
          zxid |-> 0, code |-> "OK"]
CreateTxn(path, o, pcv, z) ==
    [kind |-> "create", path |-> path, owner |-> o, pcv |-> pcv, zxid |-> z, code |-> "OK"]
DeleteTxn(path, z) ==
    [kind |-> "delete", path |-> path, owner |-> OWNER_ZERO, pcv |-> 0, zxid |-> z, code |-> "OK"]
ErrorTxn(path, code, z) ==
    [kind |-> "error", path |-> path, owner |-> OWNER_ZERO, pcv |-> 0, zxid |-> z, code |-> code]

\* A prepped request handed to SRP (PRP:769). err = request exception (PRP:927), "OK" if none.
Item(req, txn, err) == [req |-> req, txn |-> txn, err |-> err]

-----------------------------------------------------------------------------
(***************************************************************************)
(* Workload client program (TEST:53-78).  The Java client is synchronous:  *)
(* each call waits for its reply before the next is sent                   *)
(* (ClientCnxn.submitRequest), so at most one client request is in flight. *)
(***************************************************************************)
ClientSteps == {"c1", "c2", "c3", "start", "c4", "c5", "c6", "await", "c7",
                "end", "failed"}
SendSteps   == {"c1", "c2", "c3", "c4", "c5", "c6", "c7"}

\* CreateMode.CONTAINER is sent as OpCode.createContainer, any other mode as
\* OpCode.create (ZK:1437); delete passes version -1 (TEST:58, 66).
ClientReq(s) ==
    CASE s = "c1" -> Req("createContainer", P, "client")   \* TEST:56
      [] s = "c2" -> Req("create", C, "client")            \* TEST:57 (PERSISTENT)
      [] s = "c3" -> Req("delete", C, "client")            \* TEST:58
      [] s = "c4" -> Req("delete", P, "client")            \* TEST:66
      [] s = "c5" -> Req("create", P, "client")            \* TEST:70 (PERSISTENT)
      [] s = "c6" -> Req("getData", P, "client")           \* TEST:71
      [] s = "c7" -> Req("exists", Root, "client")         \* TEST:74

\* Reply codes the test tolerates; any other code throws out of run().
AcceptedErr(s) == IF s = "c4" THEN {"OK", "NONODE"}        \* TEST:65-69
                  ELSE {"OK"}

AfterReply(s) ==
    CASE s = "c1" -> "c2"
      [] s = "c2" -> "c3"
      [] s = "c3" -> "start"     \* TEST:60-62 build and start OneCheck
      [] s = "c4" -> "c5"
      [] s = "c5" -> "c6"
      [] s = "c6" -> "await"     \* TEST:72 checked.await(30 s)
      [] s = "c7" -> "end"       \* TEST:75-77 finally: cleanup.stop()

-----------------------------------------------------------------------------
VARIABLES
    tree,        \* DataTree.nodes for Paths (DT:105, 159, 215-217; NHM:62-64)
    pview,       \* what getRecordForPath returns: outstandingChangesForPath,
                 \* else the DataTree (PRP:162-187; ZKS:244-246)
    zxid,        \* ZooKeeperServer hzxid: last zxid handed out by getNextZxid
    rtQ,         \* RequestThrottler.submittedRequests (RT:64, 147, 246)
    prepQ,       \* PrepRequestProcessor.submittedRequests (PRP:101, 139, 1038)
    pipe,        \* SRP queuedRequests/toFlush -> FRP, one FIFO (SRP:166-246)
    creply,      \* reply on the client's connection (FRP:615-643)
    cpc,         \* workload client program counter (TEST:53-78)
    cwait,       \* client blocked waiting for the reply of its request
    mgr,         \* OneCheck: "off" | "armed" | "scanned" | "done"
    cand,        \* candidates returned by getCandidates (CM:142, 185-225)
    posted,      \* candidates already posted (CM:149, 163-165)
    targetFired  \* FRP:674 failing branch taken

dataVars   == <<tree, pview, zxid>>
queueVars  == <<rtQ, prepQ, pipe>>
clientVars == <<creply, cpc, cwait>>
mgrVars    == <<mgr, cand, posted>>
vars == <<tree, pview, zxid, rtQ, prepQ, pipe, creply, cpc, cwait,
          mgr, cand, posted, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* DataTree apply (FRP:159 applyRequest -> ZKS:1849-1891 processTxn ->     *)
(* ZKD processTxn -> DT:857-1040).  Returns the new nodes and rc.err.      *)
(***************************************************************************)
\* DT:433-499 createNode
CreateNodeRes(t, x) ==
    LET par == Parent(x.path) IN
    IF par /= Root /\ ~t[par].ex
        THEN [nodes |-> t, err |-> "NONODE"]                 \* DT:438-441 parent == null
    ELSE IF t[x.path].ex
        THEN [nodes |-> t, err |-> "NODEEXISTS"]             \* DT:459-463 existingChild != null
    ELSE IF par = Root
        THEN [nodes |-> [t EXCEPT ![x.path] = NewNode(x.owner, x.zxid)],  \* DT:479, 483
              err   |-> "OK"]
    ELSE [nodes |-> [t EXCEPT
                       \* DT:466-478: parent cversion := parentCVersion only if larger
                       \* DT:480: parent.addChild(childName)
                       ![par] = [@ EXCEPT !.cv = IF x.pcv > @ THEN x.pcv ELSE @,
                                          !.nch = @ + 1],
                       ![x.path] = NewNode(x.owner, x.zxid)],          \* DT:479, 483
          err   |-> "OK"]
    \* DT:484-486: containers.add(path) when EphemeralType is CONTAINER;
    \* modeled by the derived set Containers below.

\* DT:534-627 deleteNode: no type, owner or identity check.
DeleteNodeRes(t, x) ==
    LET par == Parent(x.path)
        \* DT:546-556: parent.removeChild(childName) runs before the node
        \* lookup; removing a name that is not a child is a no-op.
        t1  == IF par /= Root /\ t[x.path].ex
                   THEN [t EXCEPT ![par].nch = @ - 1]
                   ELSE t
    IN
    IF par /= Root /\ ~t[par].ex
        THEN [nodes |-> t, err |-> "NONODE"]                 \* DT:542-545 parent == null
    ELSE IF ~t[x.path].ex
        THEN [nodes |-> t1, err |-> "NONODE"]                \* DT:558-561 node == null
    ELSE [nodes |-> [t1 EXCEPT ![x.path] = NoNode],          \* DT:563 nodes.remove(path)
          err   |-> "OK"]                                    \* DT:576-579 containers.remove

\* DT:867-1040 switch on header type
ApplyTxn(t, x) ==
    CASE x.kind = "create" -> CreateNodeRes(t, x)            \* DT:868-925 (create/create2/createContainer)
      [] x.kind = "delete" -> DeleteNodeRes(t, x)            \* DT:926-931 (delete and deleteContainer alike)
      [] x.kind = "error"  -> [nodes |-> t, err |-> x.code]  \* DT:958-961 rc.err = errTxn.getErr()
      [] x.kind = "none"   -> [nodes |-> t, err |-> "OK"]    \* ZKS:1856-1859 reads return early

\* DT.containers (DT:203-205 returns a copy). Every apply runs on the
\* SyncThread under the outstandingChanges monitor (ZKS:1862), and createNode /
\* deleteNode keep the set in step with nodes (DT:484-486, 576-579), so it equals
\* the CONTAINER-owned nodes present in the tree.
Containers == {p \in Paths : tree[p].ex /\ EphemeralTypeOf(tree[p].owner) = "CONTAINER"}

-----------------------------------------------------------------------------
(***************************************************************************)
(* Initial state: a fresh standalone server with an established session    *)
(* (TEST:55 createClient; ClientBase.java:212-235).  P and C do not exist. *)
(* z0 is the server's hzxid when the workload's first operation starts.    *)
(***************************************************************************)
InitWith(z0) ==
    /\ tree   = [p \in Paths |-> NoNode]
    /\ pview  = [p \in Paths |-> NoNode]
    /\ zxid   = z0
    /\ rtQ    = <<>>
    /\ prepQ  = <<>>
    /\ pipe   = <<>>
    /\ creply = NoReply
    /\ cpc    = "c1"
    /\ cwait  = FALSE
    /\ mgr    = "off"       \* ClientBase starts no ContainerManager (ClientBase.java:431-433)
    /\ cand   = {}
    /\ posted = {}
    /\ targetFired = FALSE

Init == InitWith(0)

-----------------------------------------------------------------------------
(***************************************************************************)
(* Workload client                                                         *)
(***************************************************************************)

\* ClientCnxn.submitRequest -> NIO worker -> ZKS.processPacket (ZKS:1686-1758)
\* -> submitRequest (ZKS:1208-1218; no restore in progress) -> enqueueRequest
\* (ZKS:1220-1240) -> RT.submitRequest (RT:240-246: not stopping, add to queue).
ClientSend ==
    /\ cpc \in SendSteps
    /\ ~cwait
    /\ rtQ' = Append(rtQ, ClientReq(cpc))                    \* RT:245-246
    /\ cwait' = TRUE
    /\ UNCHANGED <<dataVars, prepQ, pipe, creply, cpc, mgrVars, targetFired>>

\* The reply reaches the blocked caller (ClientCnxn.submitRequest returns).
ClientRecv ==
    /\ cwait
    /\ creply /= NoReply
    /\ cwait'  = FALSE
    /\ creply' = NoReply
    /\ cpc' = IF creply \in AcceptedErr(cpc)
                 THEN AfterReply(cpc)
                 ELSE "failed"                              \* KeeperException thrown out of run()
    /\ UNCHANGED <<dataVars, queueVars, mgrVars, targetFired>>

\* TEST:60-62: new OneCheck(server) (TEST:85-87: ContainerManager(zkDb,
\* firstProcessor, CHECK_MS=100, maxPerMinute=Integer.MAX_VALUE) -> CM:75-77,
\* maxNeverUsedIntervalMs = 0) and cleanup.start() (CM:104-124: schedules the
\* timer task at checkIntervalMs, CM:121).
\* TEST:64 Thread.sleep(AFTER_SCAN_MS) is not modeled: time is abstracted, so
\* the scan may run before or after any later client step.
MgrStart ==
    /\ cpc = "start"
    /\ mgr = "off"
    /\ mgr' = "armed"
    /\ cpc' = "c4"
    /\ UNCHANGED <<dataVars, queueVars, creply, cwait, cand, posted, targetFired>>

\* TEST:72 cleanup.checked.await(CHECKED_S): returns once OneCheck's finally
\* (TEST:93-96) has counted down.  The 30 s timeout branch is not modeled:
\* in this model the manager always reaches "done" once the client waits here.
ClientAwaitChecked ==
    /\ cpc = "await"
    /\ mgr = "done"
    /\ cpc' = "c7"
    /\ UNCHANGED <<dataVars, queueVars, creply, cwait, mgrVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* RequestThrottler thread (client requests only)                          *)
(***************************************************************************)

\* RT:147 take(); RT:152 mustDrop() is false for a live connection; RT:157
\* throttling is off (maxRequests = 0); RT:184 shouldThrottleOp is false
\* (throttledOpWaitTime defaults to 0, ZKS:200-202; RT:101-105); RT:188
\* zks.submitRequestNow -> ZKS:1262-1266 -> PRP.processRequest (PRP:1036-1040).
RtForward ==
    /\ rtQ /= <<>>
    /\ prepQ' = Append(prepQ, Head(rtQ))
    /\ rtQ'   = Tail(rtQ)
    /\ UNCHANGED <<dataVars, pipe, clientVars, mgrVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* PrepRequestProcessor thread.  One request per step: PRP is a single     *)
(* thread (PRP:308-311); getRecordForPath reads and addChangeRecord writes *)
(* the outstanding changes under zks.outstandingChanges (PRP:164, 196),    *)
(* the same monitor FRP's apply holds (ZKS:1862), so FRP's interleaved     *)
(* applies do not change what PRP reads (see PrepViewMatchesPipeline).     *)
(* PRP:139 take(); PRP:754-771 pRequest: hdr and txn reset (PRP:759-760),  *)
(* pRequestHelper (PRP:763), then nextProcessor.processRequest (PRP:769).  *)
(* A KeeperException becomes hdr type error + ErrorTxn (PRP:914-918) and   *)
(* the request exception (PRP:927); no ChangeRecord was added before any   *)
(* of the throws below.                                                    *)
(***************************************************************************)

\* PRP:779-784 -> pRequest2Txn (PRP:312-324) -> pRequest2TxnCreate (PRP:636-715)
PrepCreate ==
    /\ prepQ /= <<>>
    /\ Head(prepQ).op \in {"create", "createContainer"}
    /\ LET req == Head(prepQ)
           z   == zxid + 1                                    \* PRP:783 zks.getNextZxid(); hdr at PRP:313-316
           par == Parent(req.path)                            \* PRP:659 validatePathForCreate
           \* PRP:692-699: CONTAINER -> CONTAINER_EPHEMERAL_OWNER, PERSISTENT -> 0
           o   == IF req.op = "createContainer" THEN CONTAINER_EPHEMERAL_OWNER
                  ELSE OWNER_ZERO
           \* PRP:657-658 validateCreateRequest: no TTL mode in the workload.
           err == IF par /= Root /\ ~pview[par].ex
                      THEN "NONODE"                           \* PRP:662 getRecordForPath(parentPath) -> PRP:183-185
                  \* PRP:664 checkACL: the workload uses OPEN_ACL_UNSAFE
                  ELSE IF pview[req.path].ex
                      THEN "NODEEXISTS"                       \* PRP:670-676
                  ELSE IF par /= Root /\ EphemeralTypeOf(pview[par].owner) = "NORMAL"
                      THEN "NOCHILDRENFOREPHEMERALS"          \* PRP:677-680 (root's owner is 0: VOID)
                  ELSE "OK"                                   \* PRP:682 checkQuota: no quota set
           \* PRP:681 newCversion = parentRecord.stat.getCversion() + 1
           pcv == IF par = Root THEN 0 ELSE pview[par].cv + 1
       IN
       /\ zxid' = z
       /\ IF err = "OK"
            THEN /\ pview' =
                      IF par = Root
                        THEN [pview EXCEPT ![req.path] = NewNode(o, z)]   \* PRP:700, 708-714
                        ELSE [pview EXCEPT
                                \* PRP:701-707 parent duplicate: childCount++, cversion = newCversion
                                ![par] = [@ EXCEPT !.nch = @ + 1, !.cv = pcv],
                                \* PRP:700, 708-714 node record: createStat(zxid, time, owner), childCount 0
                                ![req.path] = NewNode(o, z)]
                 /\ pipe' = Append(pipe, Item(req, CreateTxn(req.path, o, pcv, z), "OK"))  \* PRP:683-689, 769
            ELSE /\ pview' = pview
                 /\ pipe' = Append(pipe, Item(req, ErrorTxn(req.path, err, z), err))       \* PRP:914-918, 927, 769
       /\ prepQ' = Tail(prepQ)
    /\ UNCHANGED <<tree, rtQ, clientVars, mgrVars, targetFired>>

\* PRP:793-796 -> pRequest2Txn case OpCode.delete (PRP:352-376)
PrepDelete ==
    /\ prepQ /= <<>>
    /\ Head(prepQ).op = "delete"
    /\ LET req == Head(prepQ)
           z   == zxid + 1                                    \* PRP:795
           par == Parent(req.path)                            \* PRP:356 getParentPathAndValidate
           \* PRP:353 checkSession: the workload's session stays valid.
           err == IF par /= Root /\ ~pview[par].ex
                      THEN "NONODE"                           \* PRP:357 getRecordForPath(parentPath)
                  \* PRP:358 checkACL: OPEN_ACL_UNSAFE
                  ELSE IF ~pview[req.path].ex
                      THEN "NONODE"                           \* PRP:359 getRecordForPath(path)
                  \* PRP:360 checkAndIncVersion: the workload passes version -1
                  ELSE IF pview[req.path].nch > 0
                      THEN "NOTEMPTY"                         \* PRP:361-363
                  ELSE "OK"
       IN
       /\ zxid' = z
       /\ IF err = "OK"
            THEN /\ pview' =
                      IF par = Root
                        THEN [pview EXCEPT ![req.path] = NoNode]      \* PRP:372-375 stat == null record
                        ELSE [pview EXCEPT
                                ![par].nch = @ - 1,                   \* PRP:365-370 parent childCount--
                                ![req.path] = NoNode]                 \* PRP:372-375
                 /\ pipe' = Append(pipe, Item(req, DeleteTxn(req.path, z), "OK"))  \* PRP:364, 769
            ELSE /\ pview' = pview
                 /\ pipe' = Append(pipe, Item(req, ErrorTxn(req.path, err, z), err))
       /\ prepQ' = Tail(prepQ)
    /\ UNCHANGED <<tree, rtQ, clientVars, mgrVars, targetFired>>

\* PRP:789-792 -> pRequest2Txn case OpCode.deleteContainer (PRP:326-351).
\* The whole re-validation of the ContainerManager's stale decision. Not
\* checked: node type CONTAINER/TTL, cversion > 0 (CM:196), czxid, session, ACL.
PrepDeleteContainer ==
    /\ prepQ /= <<>>
    /\ Head(prepQ).op = "deleteContainer"
    /\ LET req == Head(prepQ)
           z   == zxid + 1                                    \* PRP:791
           par == Parent(req.path)                            \* PRP:329 getParentPathAndValidate
           rec == pview[req.path]                             \* PRP:330 getRecordForPath(path)
           err == IF ~rec.ex
                      THEN "NONODE"                           \* PRP:330 -> PRP:183-185
                  ELSE IF rec.nch > 0
                      THEN "NOTEMPTY"                         \* PRP:331-333
                  ELSE IF EphemeralTypeOf(rec.owner) = "NORMAL"
                      THEN "BADVERSION"                       \* PRP:334-336 (VOID and CONTAINER pass)
                  ELSE IF par /= Root /\ ~pview[par].ex
                      THEN "NONODE"                           \* PRP:337 getRecordForPath(parentPath)
                  ELSE "OK"
       IN
       /\ zxid' = z
       /\ IF err = "OK"
            THEN /\ pview' =
                      IF par = Root
                        THEN [pview EXCEPT ![req.path] = NoNode]      \* PRP:346-349
                        ELSE [pview EXCEPT
                                ![par].nch = @ - 1,                   \* PRP:339-344
                                ![req.path] = NoNode]                 \* PRP:346-349
                 /\ pipe' = Append(pipe, Item(req, DeleteTxn(req.path, z), "OK"))  \* PRP:338, 769
            ELSE /\ pview' = pview
                 /\ pipe' = Append(pipe, Item(req, ErrorTxn(req.path, err, z), err))
       /\ prepQ' = Tail(prepQ)
    /\ UNCHANGED <<tree, rtQ, clientVars, mgrVars, targetFired>>

\* PRP:892-909: reads only check the session (valid here); no hdr, no txn,
\* no zxid (PRP:759-760).
PrepRead ==
    /\ prepQ /= <<>>
    /\ Head(prepQ).op \in {"getData", "exists"}
    /\ pipe'  = Append(pipe, Item(Head(prepQ), NoTxn, "OK"))  \* PRP:769
    /\ prepQ' = Tail(prepQ)
    /\ UNCHANGED <<dataVars, rtQ, clientVars, mgrVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* SyncThread: SyncRequestProcessor + FinalRequestProcessor.               *)
(* SRP keeps PRP's order: a read bypasses only when toFlush is empty       *)
(* (SRP:203-213), otherwise it queues behind the writes (SRP:215) and      *)
(* flush drains in order (SRP:241-246).  FRP applies, then replies, on the *)
(* same thread (FRP:147-654), so each request is one step.                 *)
(***************************************************************************)

\* The code FRP computes for a request: the request exception for an error
\* txn (FRP:178-192 rethrows it; DT:958-961 gives the same rc.err), else rc.err
\* of the apply (FRP:303-328).
ApplyErr(it) == IF it.txn.kind = "error" THEN it.err
                ELSE ApplyTxn(tree, it.txn).err

\* FRP.processRequest for a write (hdr != null): FRP:158-159 applyRequest ->
\* ZKS:1849-1891.
FinalApply ==
    /\ pipe /= <<>>
    /\ Head(pipe).txn.kind \in {"create", "delete", "error"}  \* ZKS:1853 writeRequest = hdr != null
    /\ LET it == Head(pipe) IN
       /\ tree' = ApplyTxn(tree, it.txn).nodes                \* ZKS:1863 processTxnInDB -> DT:857-1040
       \* ZKS:1867-1883: ChangeRecords with zxid <= hdr.zxid are removed under
       \* the same monitor, and a path entry only if it still points at the
       \* removed record. The removed records describe exactly what was just
       \* applied, so getRecordForPath's answer (pview) is unchanged.
       /\ pview' = pview
       /\ IF it.req.src = "cm"
            THEN creply' = creply                              \* FRP:161-163 cnxn == null: return, no reply
            ELSE creply' = ApplyErr(it)                        \* FRP:178-192, 303-328, 604-605, 615-621
       /\ pipe' = Tail(pipe)
    /\ UNCHANGED <<zxid, rtQ, prepQ, cpc, cwait, mgrVars, targetFired>>

\* The target. FRP.processRequest for getData: FRP:159 applyRequest returns
\* early for a read (ZKS:1856-1859); FRP:161 cnxn != null; FRP:178 hdr == null;
\* FRP:194-200 no request exception; FRP:158, 208-210 not throttled;
\* FRP:398-406 case OpCode.getData -> handleGetDataRequest (FRP:669-680).
TargetCheck ==
    /\ pipe /= <<>>
    /\ LET it == Head(pipe) IN
       /\ it.req.op = "getData"
       /\ it.req.src = "client"
       /\ it.txn.kind = "none"
       /\ it.err = "OK"
       \* FRP:672 n = zks.getZKDatabase().getNode(path) (ZKD:514-516 -> DT:215-217 -> NHM:62-64)
       /\ IF ~tree[it.req.path].ex                             \* FRP:673 n == null
            THEN /\ targetFired' = TRUE                        \* FRP:674 throw new KeeperException.NoNodeException()
                 /\ creply' = "NONODE"                         \* FRP:604-605 err = e.code(); FRP:615-621
            ELSE /\ targetFired' = targetFired
                 /\ creply' = "OK"                             \* FRP:676-679 (OPEN_ACL_UNSAFE); FRP:629-632
       /\ pipe' = Tail(pipe)
    /\ UNCHANGED <<dataVars, rtQ, prepQ, cpc, cwait, mgrVars>>

\* FRP:375-397 case OpCode.exists: statNode (DT:708-715) throws NoNode when
\* the node is absent; the root always exists.
FinalExists ==
    /\ pipe /= <<>>
    /\ LET it == Head(pipe) IN
       /\ it.req.op = "exists"
       /\ it.req.src = "client"
       /\ it.txn.kind = "none"
       /\ it.err = "OK"
       /\ creply' = IF it.req.path = Root \/ tree[it.req.path].ex
                       THEN "OK" ELSE "NONODE"
       /\ pipe' = Tail(pipe)
    /\ UNCHANGED <<dataVars, rtQ, prepQ, cpc, cwait, mgrVars, targetFired>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* ContainerManagerTask timer thread (OneCheck, TEST:81-109)               *)
(***************************************************************************)

\* The timer runs checkContainers once (TEST:89-97 stops the timer in its
\* finally). CM:142 getCandidates() (CM:185-225) reads the applied DataTree
\* directly, without the outstandingChanges lock and without PRP's view. The
\* scan is one step: brief section 3.2 / CR-2.
MgrScan ==
    /\ mgr = "armed"
    /\ cand' = {p \in Containers :                            \* CM:187 getContainers() copy (DT:203-205)
                   /\ tree[p].nch = 0                         \* CM:188-189 node != null && children empty
                   /\ tree[p].cv > 0}                         \* CM:196 cversion > 0
                   \* CM:198-206: maxNeverUsedIntervalMs = 0 (CM:75-77), never adds.
                   \* CM:210-223: getTtls() is empty (no TTL nodes; extended types off).
    /\ mgr' = "scanned"
    /\ UNCHANGED <<dataVars, queueVars, clientVars, posted, targetFired>>

\* CM:142-149 for each candidate: build Request(null, 0, 0, deleteContainer,
\* DeleteContainerRequest(path), null) (CM:145-146) -- the path is the only
\* fact carried -- then OneCheck.postDeleteRequest sleeps POST_DELAY_MS
\* (TEST:100-106) and calls CM:163-165 requestProcessor.processRequest, i.e.
\* PRP:1036-1040, bypassing RequestThrottler and restoreLatch.
\* HashSet iteration order is unspecified: any remaining candidate.
\* CM:154-158 pacing: minIntervalMs = 60000 / Integer.MAX_VALUE = 0 (CM:168-170).
MgrPost(p) ==
    /\ mgr = "scanned"
    /\ p \in cand \ posted
    /\ prepQ'  = Append(prepQ, Req("deleteContainer", p, "cm"))
    /\ posted' = posted \cup {p}
    /\ UNCHANGED <<dataVars, rtQ, pipe, clientVars, mgr, cand, targetFired>>

\* CM:159 the loop ends; OneCheck's finally (TEST:93-96): stop(); checked.countDown().
MgrDone ==
    /\ mgr = "scanned"
    /\ posted = cand
    /\ mgr' = "done"
    /\ UNCHANGED <<dataVars, queueVars, clientVars, cand, posted, targetFired>>

(***************************************************************************)
(* Timing of the post (brief Scenario 1, "Timing").  In the workload the   *)
(* post comes POST_DELAY_MS = 3000 ms after the scan (TEST:49, 102), long   *)
(* after the client has read P back (c6 at about +1.0 s).  A post that      *)
(* lands before the client has received c6's reply needs a scan-to-post    *)
(* delay shorter than the client's replace-and-read; the MC layer bounds   *)
(* those with MaxEarlyPost.  Mechanism: INTERLEAVING, no fault injection.  *)
(***************************************************************************)
C6Replied == cpc \in {"await", "c7", "end"}

MgrPostOnTime(p) == C6Replied /\ MgrPost(p)
MgrPostEarly(p)  == ~C6Replied /\ MgrPost(p)

-----------------------------------------------------------------------------
(***************************************************************************)
(* The run is over: the target fired, or the workload returned normally    *)
(* with every queue drained.  Any other state without a successor is a     *)
(* deadlock that TLC reports (for example the test throwing: cpc="failed").*)
(***************************************************************************)
Terminated ==
    /\ \/ targetFired
       \/ /\ cpc = "end"
          /\ mgr = "done"
          /\ rtQ = <<>> /\ prepQ = <<>> /\ pipe = <<>>
          /\ creply = NoReply
    /\ UNCHANGED vars

\* Every enabled step of the system and the workload. Once targetFired is
\* TRUE nothing else runs (adhoc tla-patterns section 1).
SystemNext ==
    \/ ClientSend
    \/ ClientRecv
    \/ MgrStart
    \/ ClientAwaitChecked
    \/ RtForward
    \/ PrepCreate
    \/ PrepDelete
    \/ PrepDeleteContainer
    \/ PrepRead
    \/ FinalApply
    \/ TargetCheck
    \/ FinalExists
    \/ MgrScan
    \/ MgrDone

Next ==
    \/ /\ ~targetFired
       /\ \/ SystemNext
          \/ \E p \in Paths : MgrPostOnTime(p) \/ MgrPostEarly(p)
    \/ Terminated

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(***************************************************************************)
(* Properties                                                              *)
(***************************************************************************)

\* The oracle (brief section 5).
TargetSafe == ~targetFired

NodeRecs == [ex : BOOLEAN, owner : Owners, cv : Nat, nch : Nat, cz : Nat]
Requests == [op : Ops, path : Paths \cup {Root}, src : {"client", "cm"}]
Txns     == [kind : {"none", "create", "delete", "error"}, path : Paths \cup {Root},
             owner : Owners, pcv : Nat, zxid : Nat, code : ErrCodes]
Items    == [req : Requests, txn : Txns, err : ErrCodes]

InFlight == {rtQ[i] : i \in 1..Len(rtQ)}
              \cup {prepQ[i] : i \in 1..Len(prepQ)}
              \cup {pipe[i].req : i \in 1..Len(pipe)}

\* Structural sanity 1: types, and a message carries only values its sender
\* held.  Only the workload client goes through RT (CM:163-165 bypasses it),
\* the only client request in flight is the one its program counter issued,
\* and every deleteContainer was built by the manager from a scanned candidate.
TypeOK ==
    /\ tree  \in [Paths -> NodeRecs]
    /\ pview \in [Paths -> NodeRecs]
    /\ zxid  \in Nat
    /\ rtQ   \in Seq(Requests)
    /\ prepQ \in Seq(Requests)
    /\ pipe  \in Seq(Items)
    /\ creply \in ErrCodes \cup {NoReply}
    /\ cpc   \in ClientSteps
    /\ cwait \in BOOLEAN
    /\ mgr   \in {"off", "armed", "scanned", "done"}
    /\ cand  \subseteq Paths
    /\ posted \subseteq cand
    /\ targetFired \in BOOLEAN
    /\ \A i \in 1..Len(rtQ) : rtQ[i].src = "client"
    /\ \A r \in InFlight : (r.src = "cm") <=> (r.op = "deleteContainer")
    /\ \A r \in InFlight : r.src = "cm" => r.path \in posted
    /\ \A r \in InFlight : r.src = "client" => (cwait /\ r = ClientReq(cpc))

\* Structural sanity 2: PRP's view is the DataTree with the prepped-but-not-
\* yet-applied txns applied in order (PRP:162-187 + ZKS:1862-1884).
RECURSIVE ApplyPending(_, _)
ApplyPending(t, s) ==
    IF s = <<>> THEN t ELSE ApplyPending(ApplyTxn(t, Head(s)).nodes, Tail(s))

PendingTxns == [i \in 1..Len(pipe) |-> pipe[i].txn]

PrepViewMatchesPipeline == pview = ApplyPending(tree, PendingTxns)

=============================================================================
