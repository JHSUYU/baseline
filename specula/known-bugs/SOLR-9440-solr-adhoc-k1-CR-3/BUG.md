# SOLR-9440: detected by Specula (yes), finding CR-3

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `solr-adhoc-k1`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

`ZkStateReader` keeps per-collection state in `watchedCollectionStates` (collections with a watch: a local core via `registerCore`, or a `CollectionStateWatcher`) and `lazyCollectionStates` (read from ZK on every access). `registerCollectionStateWatcher` (used by `ZkStateReader.waitForState`, hence by `CloudSolrClient.waitForState` and `SolrCloudTestCase.waitForState`) adds a `CollectionWatch` and puts the collection's `DocCollection` into `watchedCollectionStates`. `removeCollectionStateWatcher` (buggy, ZkStateReader.java ~1342) only drops the watcher from `collectionWatches` when `canBeRemoved()`; unlike `unregisterCore` it does not remove the entry from `watchedCollectionStates`, does not restore the `LazyCollectionRef`, and does not `constructState`. The ZK watch fires later, but `StateWatcher.process` returns early because the collection is no longer in `collectionWatches`, so the eviction in `refreshAndWatch` never runs. Result: the client's `getClusterState()` returns the `DocCollection` captured when the watcher was removed, forever (for a client with no local core). Any later loop on that state sees stale replica states and loops until timeout.
Trigger: on a client (e.g. the test cluster's `CloudSolrClient`), a `waitForState` on collection C (or any watcher that returns true / is removed), followed by changes to C's state (a replica going down/recovering and back, a split creating CONSTRUCTION sub-shards, a restart), then `waitForRecoveriesToFinish(C, client.getZkStateReader(), ...)`: it keeps seeing the stale RECOVERING/DOWN replica (or CONSTRUCTION slice) on a live node and fails at the timeout. Fix: `removeCollectionStateWatcher` evicts the watched state, re-adds a lazy ref and reconstructs the state, like `unregisterCore`.

## What counted as detecting it (written before the run)

A Specula finding must show: on a client `ZkStateReader` (no local core of the collection), a collection state watcher registered and then removed (e.g. through `waitForState`) leaves the collection's `DocCollection` in `watchedCollectionStates` with no watch that updates it; the collection then changes in ZK (replica state/slice state), the reader's `getClusterState()` keeps returning the old `DocCollection`, and `waitForRecoveriesToFinish` on that reader fails at line 185 although the real cluster has finished recovering. Same root cause (removeCollectionStateWatcher does not evict/restore lazy ref) and same failing check.

## What Specula found

**Specula's finding CR-3:** removeCollectionStateWatcher leaves a stale watchedCollectionStates entry, freezing a client reader's collection view (fails waitForRecoveriesToFinish:185)

- **Cause:** ZkStateReader.removeCollectionStateWatcher drops the collectionWatches entry on last removal but keeps watchedCollectionStates[coll] and adds no LazyCollectionRef; constructState prefers the watched entry and StateWatcher.process ignores events for un-watched collections.
- **Trigger:** On a client ZkStateReader with no local cores: CloudSolrClient.waitForState (register+remove watcher) while a node's replicas are DOWN, then the node restarts and recovers.
- **Consequence:** getClusterState() keeps returning the frozen DocCollection (DOWN replicas on a live node); AbstractDistribZkTestBase.waitForRecoveriesToFinish polls 30 times and fails with AssertionError at line 185 although ZK state.json is all active (ad hoc target TargetSafe violated in the real system).
- **Premises:** The reader's collection has coreRefCount 0 (client-side CloudSolrClient reader). A waitForState/registerCollectionStateWatcher on that reader returns while a replica is non-active; no later watcher registration, registerCore or forceUpdate occurs before the poller times out. Known upstream as SOLR-9440 (fixed in 7.2/8.0, commit 39376cd); pinned base 1eaa00b predates the fix.

**Operator's judgement:** yes. code-review finding, reproduced by test (no TLC): removeCollectionStateWatcher leaves stale watchedCollectionStates

## Evidence

- TLC: none (code-review finding); the evidence is the reproduction.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| 4h26m | 127.0M | $62.45 |

Time is active time; quota sleeps are excluded.
