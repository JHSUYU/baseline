# MC-1 investigation (Phase 1: evidence only)

Pinned tree: base_commit e75b9596 (line numbers below are from `git show HEAD:` and do not include the harness instrumentation).

## Step 1: Code audit

Target: `CoreAdminHandler.java:563`, `handleCreateAction`:
```
560  if (coreContainer.getZkController() != null) {
561    if(!Overseer.isLegacy(coreContainer.getZkController() .getZkStateReader().getClusterProps())){
562      if(dcore.getCloudDescriptor().getCoreNodeName() ==null) {
563        throw new SolrException(ErrorCode.SERVER_ERROR, "non legacy mode coreNodeName missing "+ params);
```
`Overseer.isLegacy` (Overseer.java:1282-1284) returns `!"false".equals(clusterProps.get("legacyCloud"))`.
`legacyCloud` is in `OverseerCollectionProcessor.KNOWN_CLUSTER_PROPS` (OCP:147) and is set through the public
`/admin/collections?action=CLUSTERPROP` API (CollectionsHandler.java:200,246). Solr's own tests use it
(ShardSplitTest.java:99-101, CollectionsAPIDistributedZkTest.java:667), so it is a supported setting.

Call chain: client `/admin/collections?action=MIGRATE` -> CollectionsHandler -> Overseer collection queue ->
`OCP.processMessage` -> `migrate` (OCP:1706) -> `migrateKey` (OCP:1753). Inside migrateKey:
- OCP:1776-1790 REQUESTBUFFERUPDATES to the target leader (target leader UpdateLog enters BUFFERING)
- OCP:1792-1823 ADD_ROUTING_RULE on the source slice, then wait for it
- OCP:1844 `createCollection(temp)`. In non-legacy mode it offers ADDREPLICA to the state queue and passes
  `coreNodeName` (OCP:2147-2192), so replica1 passes the check.
- OCP:1894-1906: hand-built CoreAdmin CREATE for `<temp>_shard1_replica2` with only ACTION/NAME/COLLECTION/SHARD.
  It never reads `legacyCloud`, never pre-registers the replica, and never sets `coreNodeName`
  (compare addReplica OCP:2286-2295 and splitShard OCP:1318/1453, which go through ADDREPLICA).
- OCP:1904-1906 `collectShardResponses(results, true, "MIGRATE failed to create replica of temporary collection in target leader node.")`
  aborts the migration when that CREATE fails.

The CREATE carries no coreNodeName. `buildCoreDescriptor` leaves `CloudDescriptor.coreNodeName` null, so in
non-legacy mode the check at :562 is true and :563 throws. Nothing in this path is racy or depends on a fault.

Safeguards seen: none in migrateKey. It has no cleanup on failure: no REQUESTAPPLYUPDATES, no routing-rule removal
and no temp-collection delete after the abort. The routing rule expires at `expireAt` (forward.timeout).
The temp collection is deleted only by a *later* MIGRATE on the same pair (OCP:1757-1768). The target leader
leaves BUFFERING only through REQUESTAPPLYUPDATES, or through recovery/restart (not checked here).

Trigger scenario (the MC trace has clusterProps="false" in its initial state and no faults):
1. CLUSTERPROP legacyCloud=false
2. CREATE target collection (1 shard, rf=1)
3. MIGRATE split.key=a/1! from collection1 to the target -> replica2 CREATE fails at CoreAdminHandler:563.

## Step 2: Developer knowledge (pre-verdict: code and tests only, per adhoc Shared Rule 2)
- No comment near OCP:1894-1906 about legacyCloud.
- `TODO this should be moved into CoreContainer, really...` at CoreAdminHandler:557 (not about this path).
- MigrateRouteKeyTest never sets legacyCloud=false. ShardSplitTest sets it "usually()" and splitShard
  uses ADDREPLICA, which handles it. So MIGRATE under legacyCloud=false has no test coverage.

## Step 3: Known-status
Tracker/history search only runs after the verdict (Shared Rule 2). The queries are recorded below.

### Novelty queries (run after the reproduction verdict was settled; they set Novelty only)
1. WebSearch: `Solr MIGRATE legacyCloud=false "coreNodeName missing" temp collection replica JIRA`
2. WebSearch: `SOLR JIRA migrate API fails legacyCloud false addReplica temporary collection`

Result: SOLR-6197 (https://issues.apache.org/jira/browse/SOLR-6197), "migrate collection API fails when
legacyCloud=false": the replica of the temp collection fails with "non legacy mode coreNodeName missing".
Proposed fix: use ADDREPLICA instead of CoreAdmin CREATE. Committed to trunk r1605362 and branch_4x r1605366;
fix versions 4.10 and 5.0. Same mechanism, same site. The pinned base_commit predates the fix.
=> Novelty: KNOWN (cite SOLR-6197; fix-status: fixed upstream, unfixed in the pinned tree).
MC-sourced, so the code-review x known pre-filter does not apply. The verdict stays as reproduced.
