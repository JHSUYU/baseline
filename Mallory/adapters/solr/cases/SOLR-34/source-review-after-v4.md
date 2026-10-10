# SOLR-34: existing Solr cluster tests after the v4 path-aware seed

**Decision:** Retain the existing `TestCoordinatorRole#testSimple` JUnit for a
bounded fault bootstrap. The source review found no alternate passing,
fault-free cluster JUnit that is known to reach the exact inner check. A
successful coordinator query does not mark this check complete. Historical
CrashFuzz trials did reach the guard after faults, so fault-driven target
discovery remains warranted.

## Pinned evidence and search scope

- Solr source commit: `e27f44e3d78dfcec230c97e0a1240e3751daeff9`;
  clean checkout at `/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4`.
- Target source: `solr/core/src/java/org/apache/solr/servlet/CoordinatorHttpSolrCall.java`,
  SHA-256 `4812135778c67bfa9d466ff9d66d67ed1dfe48f0afeb2e8b18ddecd9c5b24fc9`.
- Test source: `solr/core/src/test/org/apache/solr/search/TestCoordinatorRole.java`,
  SHA-256 `2e2c6a24b8f2ea37bb1dc4b95842e7974b166e000acf8393ba7d1342bddb59b3`.
- Search of `solr/core/src/test` and `solr/solrj/src/test` for
  `CoordinatorHttpSolrCall`, `getSyntheticCollectionName`, `COORDINATOR-COLL`,
  `NodeRoles.NODE_ROLES_PROP`, and `coordinator:on` found only
  `TestCoordinatorRole.java` as an explicit coordinator-role cluster test.
  Its eight public test methods are reviewed below. This search does not
  exclude an indirect, unmarked coordinator setup elsewhere.
- The sealed v4 node1 healthy receipt is
  `data/mallory/evidence_archives/SOLR-34-path-healthy-node1-v4.receipt.json`,
  SHA-256 `519aba39d3df35b11a9ac900f892045ee850a42fdeaa68515ea7ff975837d6a8`.
  It records the b4bb path-aware agent, JUnit `1/0/0`, nine typed exact
  synthetic-state `getData` doors on named `node5`, zero exact target checks,
  and zero fault trials. The target-absent healthy run is not a full campaign.

## Exact target condition

`CoordinatorHttpSolrCall.getCore` is called only on the `/select` fallback
[`CoordinatorHttpSolrCall.java:77-84`]. The method requires an existing original
collection, then checks whether the synthetic collection is missing
[`CoordinatorHttpSolrCall.java:90-115`]. It calls `createColl` and rereads the
synthetic collection in `finally` [`CoordinatorHttpSolrCall.java:122-132`].
The mapped check `@139:branch:6` executes only if that **post-create reread
is still null** [`CoordinatorHttpSolrCall.java:138-149`]. If `createColl` threw,
line 140 rethrows that prior exception. The selected SOLR-34 exception is the
new `SolrException` at `@143:throw:1`, requiring `createException == null` as
well. The two throws are distinct outcomes; neither is an ordinary successful
query path. `createColl` requests one synthetic shard/replica and throws if
the collection-admin response lacks `success`
[`CoordinatorHttpSolrCall.java:263-286`].

## Existing JUnit review

| Existing method | Source behavior | Why it does not establish a passing exact-target seed |
| --- | --- | --- |
| `testSimple` (76) | Creates a collection, starts one coordinator, then queries it (80-108). | The sealed v4 run exercised nine exact typed path doors but observed no `@139` or `@143`. Its successful query and synthetic-collection assertion (110-118) do not require post-create absence. |
| `testMultiCollectionMultiNode` (124) | Queries ten collections with the same config through two coordinators (130-179). | Provides more creation opportunities, but no operation deliberately leaves the synthetic collection absent after `createColl`; every query and the final synthetic-collection assertion must succeed. |
| `testNRTRestart` (190) | First queries through the coordinator, then stops/restarts NRT and PULL data nodes (244-274, 376-405). | Its expected transient errors concern query routing after the synthetic core is initialized, rather than failed synthetic-collection creation. |
| `testConcurrentAccess` (494) | Sends 20 queries from ten threads through four coordinators (534-576). | This is the closest exploratory workload for a creation race, but it does not force post-create absence; `Future.get()` propagates any query exception (575-576), so reaching either target throw would fail the fault-free JUnit. Concurrency alone is not proof of target reachability. |
| `testConfigset` (596) | Queries two collections with different configsets through one coordinator (609-647). | Has two synthetic-collection creation opportunities, both expected to return successful HTTP responses; no failed post-create reread is arranged. |
| `testWatch` (654) | Queries two collections, deletes `c1`, then expects `Collection not found` (665-723). | The expected exception follows deletion of the **original** collection: `coll == null` at target-source line 98, so it does not enter the synthetic-creation block at line 100. |
| `testSplitShard` (734) | First queries through the coordinator, then splits/deletes shard metadata and queries again (743-796). | The synthetic collection is expected to exist after the first successful query; the test does not remove it. |
| `testMoveReplica` (802) | First queries through the coordinator, then moves a data replica, stops an old data node, and queries again (815-886). | The later node stop occurs after synthetic initialization and tests routing, not the post-create null condition. |

The inventory's earlier CrashFuzz record reports that fault trials using
`testSimple` did reach the exact guard after 128 effective trials, with zero
newly constructed `@143` exceptions. That historical result is scoped to its
own instrumentation and ordered same-client ZooKeeper faults; it does **not**
turn the v4 fault-free run into a target-reaching seed. It does show why this
case should remain a possible fault-bootstrap investigation rather than being
classified as an impossible target.

The v5 case-local bootstrap keeps `testSimple` unchanged and selects only
method- and path-qualified ZooKeeper reads on the named coordinator request
thread. It separates the `@140` prior-exception rethrow from the selected
`@143` new exception. The v5 stage has no Solr JUnit execution yet; any
fault-time observation requires a separate sealed run and source review.
