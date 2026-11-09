# MC-1 investigation (Phase 1 — evidence only)

Target: `CoreAdminHandler.handleCreateAction` throws `SolrException("non legacy mode coreNodeName missing")`
at `solr/core/src/java/org/apache/solr/handler/admin/CoreAdminHandler.java:560`.
Source: model checking, `MC_hunt_split_nonlegacy.cfg`, 6-state counterexample
(`spec/output/MC_hunt_split_nonlegacy_bfs.out`), invariant `TargetSafe`.

All line numbers below are from the pristine base commit 6e6ca4a (instrumentation
reverted in this finding's worktree; the instrumented tree keeps the same line numbers
for the cited sites).

## Step 1 — code audit

### The guard (CAH:557-563)
```java
if (coreContainer.getZkController() != null) {
  if(!Overseer.isLegacy(coreContainer.getZkController() .getZkStateReader().getClusterProps())){
    if(dcore.getCloudDescriptor().getCoreNodeName() ==null) {
      throw new SolrException(ErrorCode.SERVER_ERROR,               // line 560
          "non legacy mode coreNodeName missing "+ params);
```
- `Overseer.isLegacy(m)` = `!"false".equals(m.get("legacyCloud"))` (Overseer.java:1276-1278).
- `ZkStateReader.getClusterProps()` reads `/clusterprops.json` from ZK on every call
  (ZkStateReader.java:643-655), so the value is live, not cached.
- `getCoreNodeName()` comes only from the `coreNodeName` CREATE param (or a `property.coreNodeName`),
  via `buildCoreDescriptor` (CAH paramToProp / PROPERTY_PREFIX loop).
- The catch at CAH:582-608 unregisters and rethrows as `BAD_REQUEST`
  "Error CREATEing SolrCore '<name>': non legacy mode coreNodeName missing ..." with the L560 exception as cause.

### Setting legacyCloud=false is a supported public operation
- `CollectionsHandler.handleProp` (CH:237-250) accepts `action=CLUSTERPROP&name=legacyCloud&val=false`
  (`legacyCloud` is in `OverseerCollectionProcessor.KNOWN_CLUSTER_PROPS`, OCP:147) and offers it to the
  Overseer queue; `Overseer.handleProp` (OV:389-404) writes `/clusterprops.json`.
- Existing tests use it: `CollectionsAPIDistributedZkTest.testCollectionsAPI` (L661-667, random),
  `DeleteInactiveReplicaTest` (L64), and the public helper `CollectionsAPIDistributedZkTest.setClusterProp` (L1314).

### SPLITSHARD never supplies coreNodeName and never consults legacyCloud
`OverseerCollectionProcessor.splitShard` (OCP:1163-…):
- Sub-shard leader loop (OCP:1319-1348): offers `createshard` (state CONSTRUCTION, OCP:1329-1337) to the
  Overseer queue, then sends CoreAdmin CREATE with only `action, name, collection, shard` (+ async, + `property.*`
  copied from the SPLITSHARD message) to the parent leader node (OCP:1339-1347). No `coreNodeName`.
- `collectShardResponses(results, true, "SPLITSHARD failed to create subshard leaders", ...)` (OCP:1350-1351)
  aborts the split on the first error (abortOnError, OCP:1614-1623).
- Sub-shard replica CREATEs (OCP:1466-1485) are the same shape; never reached if leaders fail.
- `grep legacy` in OCP: only `KNOWN_CLUSTER_PROPS` (OCP:147). splitShard reads no cluster prop.
- Contrast: `addReplica` (OCP:~2287) does set `CORE_NODE_NAME` — the non-legacy-aware path exists elsewhere.

### Call chain (reachable in normal use)
Client `/admin/collections?action=SPLITSHARD` → `CollectionsHandler.handleSplitShardAction` (CH:555) →
OCP work queue → `OverseerCollectionProcessor.processMessage` → `splitShard` (OCP:1163) →
`sendShardRequest` (HTTP CoreAdmin CREATE to parent-leader node) → `CoreAdminHandler.handleRequestBody` →
`handleCreateAction` → CAH:560 throw.

### Trigger scenario (= counterexample)
1. Cluster up (ShardSplitTest setup, collection1 with shard1). 
2. Operator: `CLUSTERPROP legacyCloud=false` (CE state 2). 3. Overseer applies it to ZK (CE state 3).
4. Client: `SPLITSHARD collection1 shard1` picked up by OCP (CE state 4).
5. OCP offers `createshard shard1_0` and sends CREATE `collection1_shard1_0_replica1` w/o coreNodeName (CE state 5).
6. CAH on the parent-leader node: non-legacy && coreNodeName==null → throw at L560 (CE state 6, `targetFired`).
No race, no fault.

### Safeguards considered (recorded, verified in Phase 2)
- No caller-side check in CollectionsHandler/OCP rejects SPLITSHARD in non-legacy mode or fills coreNodeName.
- A user could in principle pass `property.coreNodeName=...` on SPLITSHARD (addPropertyParams), but it would be the
  same value for every sub-shard core; not a normal-use safeguard and not used by any caller.
- ShardSplitTest's retry loop retries only `code()==500`; it is a test-side loop, and the error would recur anyway
  while legacyCloud=false.

## Step 2 — developer knowledge (code/tests only, before verdict)
- No comment near CAH:557-563 or in splitShard about non-legacy mode. CAH has `// TODO this should be moved into CoreContainer, really...` (unrelated).
- No existing test combines legacyCloud=false with SPLITSHARD. `CollectionsAPIDistributedZkTest` with
  legacyCloud=false exercises CREATE collection / ADDREPLICA paths (which set coreNodeName), not split.
- The non-legacy mode's evident contract (CAH:558-560) is "every core CREATE in a non-legacy cluster must carry a
  pre-assigned coreNodeName"; the Overseer's own SPLITSHARD does not honour it.
- Tracker/history search: deferred until after the reproduction verdict (adhoc Shared Rule 2); queries recorded below.

## Step 3 — known-status
Source is MC with an actual counterexample → no pre-filter drop; proceed to Phase 2.
(Novelty search results appended after the verdict.)

## Phase 2 outcome (recorded before the novelty search)
Level 0 reproduction (public CLUSTERPROP + SPLITSHARD, pristine 6e6ca4a) triggers
`SolrException: non legacy mode coreNodeName missing` at
`CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:560)` for both sub-shard leader CREATEs, deterministically
(seeds 1A2B3C4D, DEADBEEF). Verdict: REPRODUCED. See repro/MC-1.log, repro/MC-1.seed2.log.

## Novelty search (run after the verdict; sets Novelty only)
Queries:
1. WebSearch `SOLR JIRA "legacyCloud" false SPLITSHARD "coreNodeName missing"` → SOLR-6197 (MIGRATE, different site), SOLR-11503, SOLR-11011, SOLR-14682.
2. WebSearch `"non legacy mode coreNodeName missing" solr split shard` → SOLR-6197, solr-user threads (ADDREPLICA on 6.6).
3. Fetched https://issues.apache.org/jira/browse/SOLR-6197: "The migrate collection API fails with legacyMode=false"; fixed 4.10/6.0; MIGRATE temp-collection replica CREATE (OCP MIGRATE path), not SPLITSHARD.
4. WebSearch (extended) `SOLR JIRA shard split SPLITSHARD fails legacyCloud=false sub-shard core create addreplica coreNodeName`
   → **SOLR-6101 "Shard splitting doesn't work in legacyCloud=false mode"** (https://issues.apache.org/jira/browse/SOLR-6101),
   fixed in 4.9 / 5.0: split switched to the addReplica API (with a wait for the sub-shard to appear) and ShardSplitTest
   randomly sets legacyCloud=false. Same mechanism, same site.
5. Local check: pinned tree is trunk 5.0-SNAPSHOT; `solr/CHANGES.txt` has a 4.9.0 section but no SOLR-6101 / SOLR-6197 entry → the pinned commit predates the fix.
Novelty: KNOWN (cite: SOLR-6101; fix-status: fixed upstream in 4.9/5.0, unfixed at pinned base 6e6ca4a).
