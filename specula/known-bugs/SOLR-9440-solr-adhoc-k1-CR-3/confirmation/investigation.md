# CR-3 investigation (evidence record)

## Step 1 — Code audit (pinned tree, base_commit 1eaa00b; ZkStateReader.java unmodified vs base)
- `ZkStateReader.removeCollectionStateWatcher` (ZkStateReader.java:1342-1351): removes the watcher and, when
  `canBeRemoved()` (coreRefCount + stateWatchers == 0, :201-203), drops the `collectionWatches` entry only.
  It neither removes `watchedCollectionStates[coll]` nor re-adds a `LazyCollectionRef`, nor calls `constructState`.
- Contrast `unregisterCore` (:1252-1268): on last reference does `watchedCollectionStates.remove` +
  `lazyCollectionStates.put(new LazyCollectionRef)` + `constructState`.
- `constructState` (:538-554): legacy, then `watchedCollectionStates` (putIfAbsent), then lazy. A stale watched
  entry therefore wins over the lazy ref (which `registerCollectionStateWatcher` never removed).
- `StateWatcher.process` (:1027-1036) returns early when `!collectionWatches.containsKey(coll)`, so the ZK watch
  left behind never refreshes the entry. `updateWatchedCollection`'s "Resolve race with unregisterCore" eviction
  (:1402-1405) is only reached via refreshAndWatch / forceUpdateCollection / forceUpdate.
- Call chain (public API): `CloudSolrClient.waitForState` (CloudSolrClient.java:437-440) →
  `ZkStateReader.waitForState` (:1311-1331) → `registerCollectionStateWatcher` (:1275-1293, puts collectionWatches,
  `StateWatcher.refreshAndWatch` fills watchedCollectionStates) → finally `removeCollectionStateWatcher`.
  Also `SolrCloudTestCase.waitForState` (:259-263); server side ReplaceNodeCmd:143, AddReplicaCmd:235,
  MoveReplicaCmd:204, ZkController:931/1739 (server readers usually also hold coreRefCount>0).
- Consumer: `AbstractDistribZkTestBase.waitForRecoveriesToFinish` reads `zkStateReader.getClusterState()
  .getCollectionOrNull(collection)` each poll (:152-153) with no forceUpdate; live nodes are refreshed separately
  (`clusterState.setLiveNodes`, ZkStateReader :737-738), so a frozen DOWN replica on a now-live node satisfies
  sawLiveRecovering every poll → fail(...) at :185.
- Brief's "poller reads state.json fresh" (LazyCollectionRef.get, :689-693) holds only while the collection is
  lazy in the client reader — true for the unmodified workload (no watcher registered on the client reader), false
  after any waitForState on that reader.
- Things that unfreeze it: a new watcher registration / registerCore (StateWatcher.refreshAndWatch);
  `forceUpdate`/`forceUpdateCollection` evict the entry (forceUpdateCollection without constructState since
  updated=false). None runs inside waitForRecoveriesToFinish. Nothing in the window resolves it.
- Trigger scenario: workload variant — stop a node (CoreContainer.shutdown publishes node down,
  CoreContainer.java:749) → client `waitForState(predicate: stopped node's replicas DOWN)` → restart node →
  `waitForRecoveriesToFinish(coll, cluster.getSolrClient().getZkStateReader(), false, true, 30)`.

## Step 2 — Developer knowledge (searched only AFTER the reproduction verdict was settled, per adhoc Shared Rule 2)
- Local git history: single squashed commit `1eaa00b base`; no history available.
- Comments: `updateWatchedCollection` ":1402 // Resolve race with unregisterCore." — eviction intended for un-watched
  collections; `removeCollectionStateWatcher` javadoc: "This allows Zookeeper watches to be removed if there is no
  interest in the collection." No by-design note for keeping the cache.
- Tests: TestCollectionStateWatchers only asserts watcher-set emptiness, not the cached view.

## Step 3 — Known status (queries run after verdict; recorded here)
- WebSearch "SOLR JIRA removeCollectionStateWatcher watchedCollectionStates stale collection state not removed"
- WebSearch "Solr ZkStateReader removeCollectionStateWatcher lazyCollectionStates constructState fix"
- Fetched https://issues.apache.org/jira/browse/SOLR-9440 (+ XML export).
- Match: **SOLR-9440** "ZkStateReader on a client can cache collection state and never refresh it" — same mechanism,
  same site (Shalin Shekhar Mangar: "The bug is in ZkStateReader.removeCollectionStateWatcher which only removes the
  collection from ... collectionWatches map ... So a cached DocCollection reference that is neither lazy nor
  watched is left behind"; description: "any call to waitForRecoveriesToFinish would see stale state and loop until
  timeout"). Resolved Fixed 2017-11-08, fix versions 7.2, 8.0; commits 39376cd (master), f6f5d01 (branch_7x).
- Pinned tree is 7.2-dev and CHANGES.txt has no SOLR-9440 entry → base predates the fix (unfixed at base_commit).
- Per adhoc-coordination Phase 4 / Shared Rule 2, this search sets Novelty only; it does not change the verdict.
