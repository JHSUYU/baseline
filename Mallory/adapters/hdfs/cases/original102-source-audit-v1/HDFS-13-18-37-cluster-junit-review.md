# HDFS-13, HDFS-18, HDFS-37 cluster JUnit source review

**Scope:** Hadoop 3.4.3 source commit
`9d50c6884666e794e45102260a4017bb31802e1b`, original-102 selected
sites, and existing cluster-based JUnit fixtures. This review ran no JVM and
changed no checklist or verdict. Proposed adaptations are source-backed
candidates, not healthy admission or fault results.

## HDFS-13: four-argument token password check

- **Exact selection:** `BlockTokenSecretManager.checkAccess(Token,
  String, ExtendedBlock, AccessMode)` compares the recomputed password at
  `BlockTokenSecretManager.java:431` and throws `InvalidToken` at :432-433.
  The six-argument `Token` overload has its own comparison at :411-413 and
  is a distinct bytecode target (`BlockTokenSecretManager.java:397-435`).
  Selected sites: `@431:branch:1`, `@432:throw:1`.
- **Unchanged tests:** `TestBlockToken#testBlockTokenSecretManagerLegacy`
  and `#testBlockTokenSecretManagerProtobuf` reach the exact overload through
  their helper (`TestBlockToken.java:224-237,268-301`), but create standalone
  secret managers, not a MiniDFSCluster. The same class's
  `#testBlockTokenInLastLocatedBlockLegacy/Protobuf` creates a one-DN
  MiniDFSCluster and obtains a located-block token, then only checks its kind
  (`TestBlockToken.java:509-553`). The existing
  `TestBlockTokenWithDFS#testEnd2End` cluster calibration passed but observed
  the six-argument check and no four-argument target
  (`Mallory/cases/revisions/HDFS-13-source-gap-review-v1.json`). Production
  `DataXceiver.checkAccess` also forwards through the storage-aware
  six-argument overload (`DataXceiver.java:1434-1454`;
  `BlockPoolTokenSecretManager.java:119-138`).
- **Broad cluster-based adaptation:** extend the existing
  `TestBlockToken#testBlockTokenInLastLocatedBlockLegacy/Protobuf` phase just
  after it obtains the `LocatedBlock`. Call the live NN
  `cluster.getNamesystem().getBlockManager().getBlockTokenSecretManager()`
  (`BlockManager.java:782`) and invoke its exact four-argument `checkAccess`
  on `locatedBlocks.getLastLocatedBlock().getBlockToken()`, its
  `getBlock()`, a null user ID, and `READ`. The fixture already enables block
  tokens (`TestBlockToken.java:511-518`). This is an explicit test extension;
  it establishes a viable cluster *fixture*, not reachability in the
  unchanged JUnit or a natural DataXceiver call. Require a passing adapted
  healthy run and exact bytecode event before admitting any fault campaign.
  If adaptation is disallowed, retain the source-backed unchanged-test skip.

## HDFS-18: duplicate PROVIDED storage identity assertion

- **Exact selection:** `DatanodeDescriptor.injectStorage` first looks up the
  incoming storage ID. A missing ID inserts the object; an existing ID
  evaluates `assert storage == s` at `DatanodeDescriptor.java:519-537`.
  Assertions must be enabled for this selected bytecode check. Selected
  sites: `@537:branch:5`, `@537:branch:6`, `@537:throw:1`.
- **Unchanged tests:** `TestSecureAliasMap#testSecureConnectionToAliasMap`
  starts a MiniDFSCluster with DISK and PROVIDED volumes
  (`TestSecureAliasMap.java:119-154`). Its recorded healthy run reaches only
  the first insertion, not the selected duplicate branch
  (`Mallory/cases/revisions/HDFS-18-source-gap-review-v1.json` and
  `data/mallory/calibration/HDFS-18/trials/r0000/events.jsonl.gz`).
  `TestProvidedStorageMap#testProvidedStorageMap` directly calls
  `injectStorage`, but uses a mocked `BlockManager` and local descriptor
  (`TestProvidedStorageMap.java:49-101`), so it is not a cluster workload.
- **Broad cluster-based adaptation:** extend the existing secure alias-map
  MiniDFSCluster JUnit to trigger and await a further real DN heartbeat
  after first PROVIDED storage insertion. `MiniDFSCluster.triggerHeartbeats`
  delegates to the DN actor (`MiniDFSCluster.java:2846-2851`); the DN obtains
  storage reports (`BPServiceActor.java:541`;
  `FsDatasetImpl.java:159-184`), and the NN heartbeat path
  calls `BlockManager.updateHeartbeat` then
  `ProvidedStorageMap.updateStorage` for each reported storage
  (`DatanodeManager.java:1833-1834`; `HeartbeatManager.java:263-273`;
  `BlockManager.java:2815-2823`; `ProvidedStorageMap.java:192-202`). For a
  reported PROVIDED ID, that path passes the shared `providedStorageInfo`
  object to `node.injectStorage`, so a second delivery to the same DN should
  evaluate the identity assertion and pass. This remains a **candidate**:
  the baseline logged only one injection, and source inspection does not
  prove the requested heartbeat will carry that PROVIDED storage after
  initialization. Record the actual report storage ID/type, DN descriptor,
  mapped and incoming object identities, assertion-enabled status, and
  exact branch in a passing healthy run. A second block report alone is not
  an equivalent fallback: `ProvidedStorageMap.getStorage` guards its
  injection when the DN already has the storage ID
  (`ProvidedStorageMap.java:125-138`). Do not classify a direct
  `injectStorage` call as a natural cluster hit.

## HDFS-37: existing rollback JUnit is viable with phase scoping

- **Exact selection:** `DataStorage.doRollback` checks previous layout
  version and previous cTime at `DataStorage.java:939-941`; incompatible
  state throws `InconsistentFSStateException` at :942-947. No previous
  directory returns before the guard (:922-933). DN `ROLLBACK` reaches
  `doRollback` through `doTransition` (:719-729). Selected sites:
  `@940:branch:3`, `@941:branch:4`, `@947:throw:1`.
- **Existing cluster path:** unchanged `TestDFSRollback#testRollback` creates
  DN `current` and `previous` directories, starts a MiniDFSCluster DN with
  `StartupOption.ROLLBACK`, and checks success in its **Normal DataNode
  rollback** phase (`TestDFSRollback.java:158-171`). The same method later
  writes deliberately invalid previous layout version and `Long.MAX_VALUE`
  cTime and expects startup failure (:240-290). The recorded no-fault
  calibration passed, with 12 exact guard events and three expected target
  throws (`Mallory/adapters/hdfs/cases/io-version-retry-v1/
  HDFS-37-source-gap-review-v1.json`). Its first guard pair appears before
  its first selected throw in the no-fault trace, consistent with the source
  phase order; a fresh phase/root/episode marker is needed to bind it.
- **Runnable admission:** use the unchanged JUnit, inject only at an I/O door
  in the normal DN rollback startup episode, and bind the selected guard to
  the same DN, storage root, startup option, and test phase. The healthy
  oracle is a passing JUnit, a reached normal-phase guard, zero target throws
  in that phase, and successful `checkResult(DATA_NODE)`. Later deliberately
  invalid phases have baseline expected throws; exclude those from the
  new-failure oracle. A fault candidate requires an additional same-episode
  guard throw or failed normal rollback beyond the injected I/O, followed by
  causal review. If phase filtering cannot be implemented in the runner,
  extract only the existing normal phase into a case-local JUnit adaptation;
  label it adapted. A whole-JUnit zero-target-throw gate would reject this
  source-backed valid cluster path, so `source_review_no_suitable_test` is
  too strong under the broad existing-cluster-JUnit criterion.

**Conclusion:** HDFS-37 has an existing exact-target cluster JUnit with
phase-specific baseline expectations. HDFS-13 and HDFS-18 have viable
cluster-based adaptations, but their unchanged measured JUnits do not reach
the exact selected checks. None of these source findings is a new fault or
bug result.
