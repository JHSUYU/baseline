------------------------------- MODULE base --------------------------------
(***************************************************************************)
(* hdfs-adhoc-38 (Category A): the append guard against lazy-persist files *)
(*                                                                         *)
(* Target: FSDirAppendOp.appendFile, FSDirAppendOp.java:122, throws        *)
(*   UnsupportedOperationException("Cannot append to lazy persist file "). *)
(* Guard (L121): lpPolicy != null                                          *)
(*               && lpPolicy.getId() == file.getStoragePolicyID()          *)
(* Workload: TestFileAppend#testAppendTwice (TestFileAppend.java:314-351). *)
(*                                                                         *)
(* Granularity: one atomic action per RPC handler. Every handler modeled   *)
(* here runs whole under the namesystem write lock, and nothing it does is *)
(* visible before unlock:                                                  *)
(*   append  GLOBAL FSNamesystem.java:3037      create  FS  :2800          *)
(*   complete GLOBAL :3271                      setStoragePolicy FS :2543  *)
(*   unsetStoragePolicy FS :2625                mkdirs  FS  :3571          *)
(*   rename (old) FS :3353                      rename2 GLOBAL :3385       *)
(* FS excludes GLOBAL under both lock implementations                      *)
(* (fgl/FineGrainedFSNamesystemLock.java:98-103; GlobalFSNamesystemLock    *)
(* has one lock), and fsd.writeLock() is only an assertion                 *)
(* (FSDirectory.java:280-288). Only the logSync after unlock is outside    *)
(* the lock, and it touches no guard operand.                              *)
(*                                                                         *)
(* A rejected RPC that changes nothing (FileNotFound, FileAlreadyExists,   *)
(* rename returning false, ...) is a stutter. It is encoded as the failing *)
(* guard of the success action, with the rejecting line cited. The two     *)
(* append rejections are real steps, because they end the workload.        *)
(*                                                                         *)
(* Path prefixes: NameNode classes are in .../hdfs/server/namenode/,       *)
(* BlockStoragePolicySuite in .../hdfs/server/blockmanagement/,            *)
(* HdfsConstants and DFSClient in hadoop-hdfs-client .../hdfs/.            *)
(* Tree pinned at 734dd8a67cd.                                             *)
(*                                                                         *)
(* Not modeled (brief Section 3.2, code cited there): NameNode restart,    *)
(* HA and edit replay; DataNodes and block reports; leases beyond "under   *)
(* construction by whom", client retries and the retry cache; EC/striped   *)
(* files; snapshots, references and /.reserved paths; quotas, permissions, *)
(* encryption zones and protected directories (the workload has none and   *)
(* both its users are superusers). The namespace holds exactly one file,   *)
(* F, so "another client replaces the path with a lazy-persist file"       *)
(* (designed behaviour, brief Section 1) cannot occur.                     *)
(*                                                                         *)
(* This module is the code, not the fault model. Its environment actions   *)
(* are unfenced and unbounded. The fence ("only after the workload's       *)
(* create", brief Section 3.1) and the budgets are in MC.tla.              *)
(***************************************************************************)
EXTENDS Integers, Sequences, TLC

CONSTANTS
    \* The workload's create arguments and the NameNode default policy. All
    \* three are fixed by the workload (MC.cfg, every hunt, Trace.cfg):
    \*   CreateLazyFlag = FALSE, no LAZY_PERSIST flag
    \*     (TestFileAppend.java:329 -> DistributedFileSystem.java:513-519)
    \*   CreatePolicyId = 0, no storagePolicy name (same call, last argument)
    \*   DefaultPolicy  = 7, dfs.storage.default.policy (DFSConfigKeys.java:901)
    \* Any other value is a designed route (brief Section 1), never a finding.
    \* Only the oracle self-check MC_sanity_oracle.cfg sets another value.
    CreateLazyFlag,
    CreatePolicyId,
    DefaultPolicy

----------------------------------------------------------------------------
\* Storage policy ids (HdfsConstants.java:39,47,133). Every policy other than
\* LAZY_PERSIST behaves like HOT for the guard and for copy-on-create, so HOT
\* stands for all of them.

UNSPECIFIED == 0
HOT         == 7
LP          == 15

PolicyId       == {UNSPECIFIED, HOT, LP}
SettablePolicy == {HOT, LP}

ASSUME CreateLazyFlag \in BOOLEAN
ASSUME CreatePolicyId \in PolicyId
ASSUME DefaultPolicy \in SettablePolicy

\* BlockStoragePolicySuite.getPolicy(byte): id 0 means the default policy
\* (BlockStoragePolicySuite.java:137-140).
GetPolicy(id) == IF id = UNSPECIFIED THEN DefaultPolicy ELSE id

\* BlockStoragePolicy.isCopyOnCreateFile: only LAZY_PERSIST passes TRUE
\* (BlockStoragePolicySuite.java:60-65; the other policies use the 5-argument
\* constructor, which passes FALSE, BlockStoragePolicy.java:60-64).
IsCopyOnCreate(p) == p = LP

----------------------------------------------------------------------------
\* Inodes. Root is "/". D is the directory the workload's create auto-creates.
\* L is the one spare directory inode for the environment client's mkdirs.
\* F is the workload's file.

Root == "Root"
D    == "D"
L    == "L"
F    == "F"
NoINode == "NoINode"

Dir   == {Root, D, L}
INode == Dir \cup {F}

\* Local names. The workload's path is /testAppendTwice/foo
\* (TestFileAppend.java:323). "lp" is a free name for the environment client.
WorkloadDirName  == "testAppendTwice"
WorkloadFileName == "foo"
SpareName        == "lp"
NoName           == ""

Name == {WorkloadDirName, WorkloadFileName, SpareName}

\* The workload's two DFSClients. C1 is fs2's client, which creates the file
\* (TestFileAppend.java:320,329,337). C2 is fs1's (TestFileAppend.java:319,340).
C1 == "c1"
C2 == "c2"
NoClient == "NoClient"

Client == {C1, C2}

----------------------------------------------------------------------------
VARIABLES
    \* Namespace slice (Scenarios 1, 2).
    parent,       \* [INode -> Dir \cup {NoINode}]: INode.getParent() (INode.java:687-690).
                  \*   NoINode: the root, an inode not created yet, or one removed.
    name,         \* [INode -> Name \cup {NoName}]: INode local name.
    dirPolicy,    \* [Dir -> PolicyId]: first byte of the SYSTEM xattr
                  \*   hsm.block.storage.policy.id; 0 = no xattr
                  \*   (INodeDirectory.java:123-131).
    fileOwn,      \* PolicyId: the 4 policy bits of F's header (INodeFile.java:587-589).
    createdLazy,  \* Ghost for CopyOnCreatePinned: F's own id was LP when StartFile ended.

    \* Workload.
    pc,           \* The JUnit thread's next RPC. One thread drives both clients in
                  \*   sequence (TestFileAppend.java:329-349), so one pc suffices.
    ucHolder,     \* Client \cup {NoClient}: FileUnderConstructionFeature.getClientName().
    outcome,      \* [Client -> outcome of its last append].

    \* The oracle (adhoc-coordination Phase 2).
    targetFired

vars == <<parent, name, dirPolicy, fileOwn, createdLazy,
          pc, ucHolder, outcome, targetFired>>

PcValues == {"create", "close", "append1", "append2", "teardown", "done"}

Outcomes == {"none", "UC", "ABCE", "UOE", "FNF", "FAE", "ACE"}

\* Which test step issues each client's append.
AppendStep == [c \in Client |-> IF c = C1 THEN "append1" ELSE "append2"]

----------------------------------------------------------------------------
\* Namespace helpers

Live(x) == x = Root \/ parent[x] # NoINode

\* F exists. It never leaves the namespace: no modeled action deletes a file,
\* and rename2 can overwrite a file only with another file (FSDirRenameOp.java:
\* 572-578), of which the model has none.
created == parent[F] # NoINode

ChildrenOf(d) == {x \in INode : parent[x] = d}

\* INodeDirectory.getChild: names are unique within a directory (see TypeOK).
ChildOf(d, n) ==
    LET kids == {x \in INode : parent[x] = d /\ name[x] = n}
    IN  IF kids = {} THEN NoINode ELSE CHOOSE x \in kids : TRUE

RECURSIVE AncestorsOf(_)
AncestorsOf(x) ==
    IF parent[x] = NoINode THEN {} ELSE {parent[x]} \cup AncestorsOf(parent[x])

\* The inode's current path, as components.
RECURSIVE PathOf(_)
PathOf(x) ==
    IF parent[x] = NoINode THEN <<>> ELSE Append(PathOf(parent[x]), name[x])

----------------------------------------------------------------------------
\* The guard's operand 2: file.getStoragePolicyID().

\* INodeDirectory.getStoragePolicyID (INodeDirectory.java:134-141): the own
\* xattr, else the parent's effective id, else 0. The root yields 0, not
\* dfs.storage.default.policy.
RECURSIVE EffDir(_)
EffDir(d) ==
    IF dirPolicy[d] # UNSPECIFIED THEN dirPolicy[d]
    ELSE IF parent[d] # NoINode THEN EffDir(parent[d])
    ELSE UNSPECIFIED

\* INodeFile.getStoragePolicyID (INodeFile.java:592-597): the own id, else the
\* current parent's effective id (read now, not at create). The EC filter at
\* :603-608 is the identity here: F is contiguous, TestFileAppend.java:329.
EffFile ==
    IF fileOwn # UNSPECIFIED THEN fileOwn
    ELSE IF parent[F] # NoINode THEN EffDir(parent[F])
    ELSE fileOwn

\* The guard's operand 1: lpPolicy (FSDirAppendOp.java:118-120). A final suite,
\* built once, that always holds LAZY_PERSIST at id 15 (BlockManager.java:467,
\* 538; BlockStoragePolicySuite.java:56-65,147-158). So it is never null.
LpPolicyNonNull == TRUE
LpPolicyId      == LP

\* FSDirAppendOp.java:121, as the code evaluates it.
GuardFails == LpPolicyNonNull /\ LpPolicyId = EffFile

----------------------------------------------------------------------------
\* The workload's append path /testAppendTwice/foo, resolved now
\* (FSDirectory.resolvePath, FSDirectory.java:735-760).

AppendFirst == ChildOf(Root, WorkloadDirName)

\* A file in the middle of the path: checkTraverse throws PNDE, and resolvePath
\* turns it into AccessControlException for a non-create op
\* (FSDirectory.java:752-757; FSPermissionChecker.java:888-898,900-906).
AppendAncestorIsFile == AppendFirst = F

\* iip.getLastINode(), FSDirAppendOp.java:95.
AppendLast ==
    IF AppendFirst \in Dir THEN ChildOf(AppendFirst, WorkloadFileName)
    ELSE NoINode

\* The test thread after a failed append. An exception leaves the try block
\* for the finally at TestFileAppend.java:346-350. c1's append is the first
\* one, so no stream is open; after c2's append, c1's stream is still open and
\* fs2.close() completes it (DFSClient.java:646-670,680).
AfterFailure(c) == IF c = C1 THEN "done" ELSE "teardown"

\* The test thread after a successful append (TestFileAppend.java:337,340).
AfterSuccess(c) == IF c = C1 THEN "append2" ELSE "teardown"

----------------------------------------------------------------------------
\* Initial state: the freshly formatted namespace of the MiniDFSCluster
\* (TestFileAppend.java:317-318) has only "/", with no policy xattr.

Init ==
    /\ parent      = [x \in INode |-> NoINode]
    /\ name        = [x \in INode |-> NoName]
    /\ dirPolicy   = [d \in Dir |-> UNSPECIFIED]
    /\ fileOwn     = UNSPECIFIED
    /\ createdLazy = FALSE
    /\ pc          = "create"
    /\ ucHolder    = NoClient
    /\ outcome     = [c \in Client |-> "none"]
    /\ targetFired = FALSE

----------------------------------------------------------------------------
\* Workload actions (brief Section 3.1: the workload as a sequential program)

\* FSDirWriteFileOp.startFile (FSDirWriteFileOp.java:363-430), the create at
\* TestFileAppend.java:329. The path has no last inode: only L can exist before
\* this step and it has no children, so the overwrite branch at :379-402 and
\* the directory check at :333-336 do not apply.
StartFile(c) ==
    /\ pc = "create"
    /\ c = C1
    /\ LET \* createAncestorDirectories (:405-406; FSDirMkdirOp.java:127-151):
           \* an existing /testAppendTwice is used as is, else D is created.
           existing  == AppendFirst
           parentDir == IF existing # NoINode THEN existing ELSE D
           \* addFile: the constructor takes the id of the create-time policy
           \* name (:563-572,584-586).
           ctorOwn   == CreatePolicyId
           \* setNewINodeStoragePolicy (:815-842), run at :423 before
           \* logOpenFile at :424. inode.getStoragePolicyID() at :833 reads the
           \* own id, else the parent's effective id. A new D has no xattr, so
           \* its effective id is the root's.
           effNow    == IF ctorOwn # UNSPECIFIED THEN ctorOwn
                        ELSE IF existing # NoINode THEN EffDir(existing)
                        ELSE EffDir(Root)
           effective == GetPolicy(effNow)
           finalOwn  == IF CreateLazyFlag
                        THEN LP                       \* :818-830, the flag
                        ELSE IF IsCopyOnCreate(effective)
                             THEN effective           \* :835-840, the copy
                             ELSE ctorOwn             \* :835, no copy
       IN  /\ parent' = IF existing # NoINode
                        THEN [parent EXCEPT ![F] = parentDir]
                        ELSE [parent EXCEPT ![D] = Root, ![F] = parentDir]
           /\ name' = IF existing # NoINode
                      THEN [name EXCEPT ![F] = WorkloadFileName]
                      ELSE [name EXCEPT ![D] = WorkloadDirName,
                                        ![F] = WorkloadFileName]
           /\ fileOwn' = finalOwn
           /\ createdLazy' = (finalOwn = LP)
    /\ ucHolder' = c                     \* newNode.toUnderConstruction (:588)
    /\ pc' = "close"
    /\ UNCHANGED <<dirPolicy, outcome, targetFired>>

\* FSDirWriteFileOp.completeFile (FSDirWriteFileOp.java:690-702,704-753), the
\* close at TestFileAppend.java:331 and fs2.close() at :347. It resolves F by
\* inode id, so a rename does not affect it (:699; FSDirectory.java:793-797).
\* checkLease (:714) passes because the holder is the UC client. A call that
\* returns false at :738 or :745 changes no modeled variable and the client
\* retries it, so only the finalizing call is a step (:750-752).
CompleteFile(c) ==
    /\ pc \in {"close", "teardown"}
    /\ ucHolder = c
    /\ ucHolder' = NoClient              \* toCompleteFile (FSNamesystem.java:3970)
    /\ pc' = IF pc = "close" THEN "append1" ELSE "done"
    /\ UNCHANGED <<parent, name, dirPolicy, fileOwn, createdLazy,
                   outcome, targetFired>>

\* FSDirAppendOp.appendFile, the path is not F: rejected before the guard
\* (FSDirAppendOp.java:93-110). The test thread leaves its try block.
AppendPathRejected(c) ==
    /\ pc = AppendStep[c]
    /\ AppendLast # F
    /\ LET result == CASE AppendAncestorIsFile -> "ACE"   \* L93, FSDirectory.java:754-756
                       [] AppendLast \in Dir   -> "FAE"   \* L97-100
                       [] OTHER                -> "FNF"   \* L105-109
       IN  outcome' = [outcome EXCEPT ![c] = result]
    /\ pc' = AfterFailure(c)
    /\ UNCHANGED <<parent, name, dirPolicy, fileOwn, createdLazy,
                   ucHolder, targetFired>>

\* FSDirAppendOp.appendFile reaches L121 for F: the path resolves to a file
\* (L93-110), it is not striped (L112-116, F is contiguous), and permissions
\* pass (L101-103, both users are superusers, AppendTestUtil.java:123-130).
TargetCheckEnabled(c) ==
    /\ pc = AppendStep[c]
    /\ AppendLast = F

TargetCheck(c) ==
    /\ TargetCheckEnabled(c)
    /\ IF GuardFails                                   \* L121
       THEN \* L122: throw UnsupportedOperationException. It is not an
            \* IOException, so the catch at L145 does not log it. The client
            \* sees RemoteException(className=UOE), and the assertion at
            \* TestFileAppend.java:344-345 fails.
            /\ targetFired' = TRUE
            /\ outcome' = [outcome EXCEPT ![c] = "UOE"]
            /\ pc' = AfterFailure(c)
            /\ UNCHANGED ucHolder
       ELSE /\ UNCHANGED targetFired
            /\ IF ucHolder # NoClient
               THEN \* L126: recoverLeaseInternal, F is under construction
                    \* (FSNamesystem.java:2944). Same holder: ABCE at :2956-2958.
                    \* Other holder: ABCE at :3005-3008. The 60 s soft limit
                    \* (:2986) is abstracted as never expired, since the
                    \* workload takes ms. TestFileAppend.java:342-345 expects this.
                    /\ outcome' = [outcome EXCEPT ![c] = "ABCE"]
                    /\ pc' = AfterFailure(c)
                    /\ UNCHANGED ucHolder
               ELSE \* L126 returns true (FSNamesystem.java:3013). The last-block
                    \* checks at L131-141 come after the target and are
                    \* abstracted. L143 -> prepareFileForAppend makes F
                    \* under construction for c (FSDirAppendOp.java:190).
                    /\ ucHolder' = c
                    /\ outcome' = [outcome EXCEPT ![c] = "UC"]
                    /\ pc' = AfterSuccess(c)
    /\ UNCHANGED <<parent, name, dirPolicy, fileOwn, createdLazy>>

\* The test has ended. This keeps TLC's deadlock check useful: any other state
\* with no successor is a stuck workload.
Terminating ==
    /\ pc = "done"
    /\ UNCHANGED vars

----------------------------------------------------------------------------
\* Environment client actions: legal namespace RPCs from another client
\* (brief Section 1, INTERLEAVING). Allowed by the defaults
\* (FSNamesystem.java:2511-2522; hdfs-default.xml:3740-3753). Budgets and the
\* fence are in MC.tla.

\* Scenario 1. FSDirAttrOp.setStoragePolicy on a directory: resolve, then
\* unprotectedSetStoragePolicy -> setDirStoragePolicy (FSDirAttrOp.java:178-196,
\* 463-466,473-490). A missing path throws at :438-441. The directory branch has
\* NO copy-on-create check, unlike the file branch at :446-460.
SetDirStoragePolicy(d, p) ==
    /\ d \in Dir
    /\ Live(d)
    /\ p \in SettablePolicy
    /\ dirPolicy' = [dirPolicy EXCEPT ![d] = p]      \* :486-490
    /\ UNCHANGED <<parent, name, fileOwn, createdLazy,
                   pc, ucHolder, outcome, targetFired>>

\* Scenario 1. FSDirAttrOp.unsetStoragePolicy on a directory: policyId 0
\* removes the xattr (FSDirAttrOp.java:161-165,479-484,490).
UnsetDirStoragePolicy(d) ==
    /\ d \in Dir
    /\ Live(d)
    /\ dirPolicy' = [dirPolicy EXCEPT ![d] = UNSPECIFIED]
    /\ UNCHANGED <<parent, name, fileOwn, createdLazy,
                   pc, ucHolder, outcome, targetFired>>

\* Scenario 1, the file branch of unprotectedSetStoragePolicy
\* (FSDirAttrOp.java:443-462). p = UNSPECIFIED is the unset RPC (:161-165).
SetFileStoragePolicy(p) ==
    /\ created
    /\ p \in PolicyId
    \* :446-452: a copy-on-create policy cannot be set on a file.
    /\ p # UNSPECIFIED => ~IsCopyOnCreate(GetPolicy(p))
    \* :454-461: a file whose own id resolves to a copy-on-create policy
    \* cannot change. getPolicy(0) is the default policy.
    /\ ~IsCopyOnCreate(GetPolicy(fileOwn))
    /\ fileOwn' = p                                  \* :462
    /\ UNCHANGED <<parent, name, dirPolicy, createdLazy,
                   pc, ucHolder, outcome, targetFired>>

\* Scenario 2. FSDirMkdirOp.mkdirs (FSDirMkdirOp.java:45-91) with one missing
\* level, in the spare inode. A path that exists is a no-op or throws (:55-60).
\* A removed L has no residual state, so reusing the inode for a new directory
\* is safe.
Mkdirs(dp, n) ==
    /\ ~Live(L)
    /\ dp \in Dir
    /\ Live(dp)
    /\ n \in Name
    /\ ChildOf(dp, n) = NoINode                      \* :55,60: lastINode == null
    /\ parent' = [parent EXCEPT ![L] = dp]           \* :79-80
    /\ name'   = [name EXCEPT ![L] = n]
    /\ UNCHANGED <<dirPolicy, fileOwn, createdLazy,
                   pc, ucHolder, outcome, targetFired>>

\* Scenario 2. The old rename API, FSDirRenameOp.renameToInt -> renameTo ->
\* unprotectedRenameTo (FSDirRenameOp.java:55-69,505-540,173-254), expressed by
\* the final destination dp/n. A destination path that is a directory gets the
\* source's name appended (dstForRenameTo, :149-160), so "into dp" is the case
\* n = name[x]. Any failing check returns false (:183-184,196-197,200-205,207-212).
\* The rename keeps the moved inode's own id and xattr, and has no policy check
\* (policy is used only for quota deltas, :88-95,720-746).
RenameOld(x, dp, n) ==
    /\ x \in INode \ {Root}                          \* :609-614 (source not the root)
    /\ Live(x)                                       \* :603-608
    /\ dp \in Dir
    /\ Live(dp)                                      \* :206-212; a file as parent throws PNDE
    /\ n \in Name
    /\ dp # x /\ x \notin AncestorsOf(dp)            \* :195, validateDestination :552-559
    /\ ChildOf(dp, n) = NoINode                      \* :200-205; covers dst == src (:190-192)
    /\ parent' = [parent EXCEPT ![x] = dp]           \* :229,233, RenameOperation :794-807
    /\ name'   = [name EXCEPT ![x] = n]
    /\ UNCHANGED <<dirPolicy, fileOwn, createdLazy,
                   pc, ucHolder, outcome, targetFired>>

\* validateOverwrite (FSDirRenameOp.java:568-595).
ValidateOverwrite(x, victim, overwrite) ==
    /\ (victim \in Dir) = (x \in Dir)                \* :572-578: same kind
    /\ overwrite                                     \* :579-584
    /\ victim \in Dir => ChildrenOf(victim) = {}     \* :585-594: an empty directory

\* Scenario 2. rename2: FSDirRenameOp.unprotectedRenameTo with options
\* (FSDirRenameOp.java:259-338,381-498). Exceptions are stutters. dp/n is never
\* the root, so "rename destination cannot be the root" (:403-408) does not
\* arise. A replaced directory is removed (:450-455).
Rename2(x, dp, n, overwrite) ==
    /\ x \in INode \ {Root}                          \* :394, :609-614
    /\ Live(x)                                       \* :394, :603-608
    /\ dp \in Dir
    /\ Live(dp)                                      \* :419-431
    /\ n \in Name
    /\ overwrite \in BOOLEAN
    /\ ~(parent[x] = dp /\ name[x] = n)              \* :397-400
    /\ dp # x /\ x \notin AncestorsOf(dp)            \* :401, validateDestination :552-559
    /\ LET victim == ChildOf(dp, n)
       IN  /\ victim # NoINode => ValidateOverwrite(x, victim, overwrite)  \* :414-417
           /\ IF victim = NoINode
              THEN /\ parent' = [parent EXCEPT ![x] = dp]                  \* :445,458
                   /\ name'   = [name EXCEPT ![x] = n]
                   /\ UNCHANGED dirPolicy
              ELSE /\ parent' = [parent EXCEPT ![x] = dp, ![victim] = NoINode]
                   /\ name'   = [name EXCEPT ![x] = n, ![victim] = NoName]
                   /\ dirPolicy' = [dirPolicy EXCEPT ![victim] = UNSPECIFIED]
    /\ UNCHANGED <<fileOwn, createdLazy,
                   pc, ucHolder, outcome, targetFired>>

----------------------------------------------------------------------------
Next ==
    \/ \E c \in Client : StartFile(c)
    \/ \E c \in Client : CompleteFile(c)
    \/ \E c \in Client : TargetCheck(c)
    \/ \E c \in Client : AppendPathRejected(c)
    \/ \E d \in Dir, p \in SettablePolicy : SetDirStoragePolicy(d, p)
    \/ \E d \in Dir : UnsetDirStoragePolicy(d)
    \/ \E p \in PolicyId : SetFileStoragePolicy(p)
    \/ \E dp \in Dir, n \in Name : Mkdirs(dp, n)
    \/ \E x \in INode, dp \in Dir, n \in Name : RenameOld(x, dp, n)
    \/ \E x \in INode, dp \in Dir, n \in Name, o \in BOOLEAN : Rename2(x, dp, n, o)
    \/ Terminating

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
\* Invariants (brief Section 5)

\* The oracle: the guard at FSDirAppendOp.java:121 never takes its throwing branch.
TargetSafe == ~targetFired

\* Every variable stays in its domain, and the namespace is a tree: a live
\* inode's parent is a live directory, sibling names are unique, there is no
\* cycle, and a non-live inode has no residual state.
TypeOK ==
    /\ parent \in [INode -> Dir \cup {NoINode}]
    /\ name \in [INode -> Name \cup {NoName}]
    /\ dirPolicy \in [Dir -> PolicyId]
    /\ fileOwn \in PolicyId
    /\ createdLazy \in BOOLEAN
    /\ pc \in PcValues
    /\ ucHolder \in Client \cup {NoClient}
    /\ outcome \in [Client -> Outcomes]
    /\ targetFired \in BOOLEAN
    /\ parent[Root] = NoINode
    /\ \A x \in INode : parent[x] # NoINode => Live(parent[x])
    /\ \A x, y \in INode :
          (x # y /\ parent[x] # NoINode /\ parent[x] = parent[y]) => name[x] # name[y]
    /\ \A x \in INode : x \notin AncestorsOf(x)
    /\ \A x \in INode \ {Root} : ~Live(x) =>
          /\ name[x] = NoName
          /\ x \in Dir => dirPolicy[x] = UNSPECIFIED

\* No operation after the create changes whether F's own id is LP
\* (FSDirAttrOp.java:446-460).
CopyOnCreatePinned == created => ((fileOwn = LP) <=> createdLazy)

=============================================================================
