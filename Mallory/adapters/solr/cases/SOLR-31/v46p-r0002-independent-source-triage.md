# SOLR-31 v46p r0002: independent source and trace triage

Status: `confirmed_fault_induced_failure`; issue novelty: `novelty_unverified`.
This is one observed, fault-injected Solr 8.11.4 execution. It is state-timeline
evidence across threads, not a Mallory observed graph edge or a claim about
production frequency.

## Source mechanism

The three Solr 8.11.4 files on node2's pinned source checkout and node0's
distribution snapshot have identical SHA-256 values:

| File | SHA-256 | Relevant lines |
| --- | --- | --- |
| `solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java` | `83e14eadfcc4896ff05f9ac77706fdb683e0c181caeee21802f8861f68ac373d` | 1334-1362, 1384-1391, 1636-1645 |
| `solr/core/src/java/org/apache/solr/handler/admin/CollectionsHandler.java` | `61be10aac1753a0defa3dcdfecf7109dd0ddc52669bdf0f1d3fa60e484d216ca` | 1458-1478 |
| `solr/core/src/test/org/apache/solr/cloud/ForceLeaderTest.java` | `c9e660ce598703f618b00ff93dbb6e305e166686e8752d031caf7d75f580105f` | 71-129, 277-282 |

`StateWatcher.refreshAndWatch` reads the collection's `state.json` through
`fetchCollectionState` / `zkClient.getData` before it calls
`updateWatchedCollection` and `constructState`. Its catch for
`KeeperException.ConnectionLossException` logs and returns, so a failed read
does not replace the previously cached collection state. The `FORCELEADER`
handler obtains its own server `ClusterState` at entry and rejects the request
with `SolrException(SERVER_ERROR)` if its selected slice has an ACTIVE leader.
The test explicitly refreshes the *client* reader, asserts no leader, then
calls `doForceLeader`; it does not wrap that call in `expectThrows`. Its earlier
`assertSendDocFails(3)` is a separate, intentional failure assertion.

## Pinned r0002 observation

Raw directory on node2:
`/users/ZhenyuLi/baseline/data/mallory/diagnostic_v46p_state_watch_lane4/SOLR-31/trials/r0002/`.
The plan selects one exception, `org.apache.zookeeper.KeeperException$ConnectionLossException`,
at `ZkStateReader#fetchCollectionState@1641:door:watcher`, ordinal 4,
`shard-2`, epoch 0. The adapter limits this door to the real
`StateWatcher.refreshAndWatch` call for
`/collections/forceleader_lower_terms_collection/state.json` and uses the
registered reader's node identity. Adapter source SHAs: `SolrHooks.java`
`e1a4b4abbaf6cef8a268f236d959c7de1dd8c3bae8bea683930be75e11a5085f`,
`SolrTransformer.java`
`80212b0c8a75df7d40b3a82bf4a2c73ec75626d78d95cb8d3513600f1278622b`.

| Evidence | Exact observation |
| --- | --- |
| Event seq 835, 839, 840 | `DOOR_OBSERVED`, `FAULT_MATCHED`, `FAULT_APPLIED` on `shard-2:0`, watcher occurrence `task:349:1`, thread 227. |
| JUnit log lines 1193, 1201, 1223 | On that same watcher occurrence, collection/path, and reader `15166816`, the cache is version 5, `core_node6` ACTIVE both before and after the injected read; the intervening log is the source's caught ZooKeeper connection-loss warning. |
| JUnit log lines 1199-1200, 1248-1250 | Unfaulted readers reach version 6 with `core_node6` DOWN, then the control reader reaches version 7 with no leader. This independently establishes a newer collection state; these are other readers, not the handler's reader. |
| Test source and JUnit lines 1268, 1514 | Test advances through its no-leader assertion and invokes `doForceLeader`. |
| Event seq 993-998, JUnit line 1591 | Client HTTP request reaches `shard-2:0`; `forceLeaderElection` on thread 335 uses the *same* reader ID `15166816`, collection, and shard. Its actual selected operand is still version 5, `core_node6` ACTIVE. Both `@1476` checks are on that handler occurrence, followed by the selected `@1477` `SolrException` throw. |
| JUnit lines 2370-2393 | The user-visible FORCELEADER call returns the active-leader server error; test result is 1 run, 1 failure, 0 ignored. |

This is a confirmed failure of the requested FORCELEADER operation in r0002.
The client and server readers are distinct; the client's `forceUpdateCollection`
does not refresh the server cache. The injected failure is a typed exception at
the call site, not a full ZooKeeper outage. No later successful refresh of this
collection on `shard-2` appears between the injected watcher callback and the
selected handler operand. One trial alone does not prove that every such fault
or deployment produces the outcome.

SHA-256 bindings (node2): `result.json`
`218ec233d96ad06b007e3c04d6aa6fbdd1536cc97270549c12da198448cacd46`,
`events.jsonl.gz`
`501b15c2df735937b8eedf4c4b2c5cf36f1fa3bad45cff0802ef6829f93cd68a`,
`junit.log`
`e098cf8f10cc51e8fe6620237761c8d1bdf8a95aa4ac43dde6d4880368ce234a`,
`junit-receipt.json`
`43a0e2825846bbe34db047d0c53f59f10bc1b0cb93d5439cd26512ee803ad8c0`,
`plan.json`
`9e8f8d62f2153b30f7fc093c513a058abf6c42c098c057caed6ca40d01af387c`,
`sites.jsonl`
`284776e5ac2a91ae3654765993267c08d318ab5c3f6a6786d2211f3bbb40ecd4`.

## Reproduction and boundaries

In a fresh isolated lane, use the pinned Solr 8.11.4 checkout and v46 adapter,
the existing `config-v46p-lane4-state-watch-diagnostic.json`, and the bounded
runner `releases/v46/run_solr31_state_diagnostic.py --config <config> --out
<new-output-directory>`. The output directory must be new, and runtime artifact
and healthy receipt gates in the runner must pass. To evaluate each trial,
verify the exact selected typed door, the before/after cache snapshot, then
the same server, epoch, collection, reader ID, and selected operand at `@1476`;
check JUnit separately. The original r0002 JUnit seed is
`F0993D5343E20BA4`. The wrapper emitted an `ant test` reproduction line for
the test alone; that line does not inject the fault. Repeating the test alone
is therefore not a reproduction of this mechanism.

The bounded v46p diagnostic subsequently terminated with four exact applied
faults. Only r0002 has the same-reader stale ACTIVE operand and selected
`@1477` throw (one strict witness in four trials). r0001 and r0003 never
reach the target. r0004 reaches `@1476` on the **control** node with a
different reader (`42e7b724`), version 8 and no leader; the selected throw
does not occur, and JUnit instead fails at a 330-second recovery wait. Thus
the cohort does not provide a second reproduction of the r0002 failure.
The SHA-bound compact terminal review is
`data/mallory/quality_reviews/solr31_v46_state/SOLR-31-diagnostic.json`,
SHA-256 `074fd9bc7a019a5ce5f44d722320950bef1a39e0be793de8c938179c6f5e4f94`;
the terminal campaign `result.json` SHA-256 is
`35333243e45dd7cee0d2d021b70b8014de41c206e6e5a1f5cb1f1fb98276ab60`.

## Prior issue check

On 2026-10-09, bounded Apache Solr JIRA REST searches for
`forceLeaderElection`, `refreshAndWatch`, `watcher` plus `ConnectionLoss`,
`FORCELEADER`, and `stale cluster state` found no report clearly describing
this exact one-shot watcher read failure followed by a stale ACTIVE operand
in FORCELEADER. Related reports are
[SOLR-16257](https://issues.apache.org/jira/browse/SOLR-16257)
(race between `collectionWatches` and `watchedCollectionStates`),
[SOLR-9440](https://issues.apache.org/jira/browse/SOLR-9440)
(unwatched *client* collection cache),
[SOLR-12176](https://issues.apache.org/jira/browse/SOLR-12176)
(elected replica missing from cluster state), and
[SOLR-6405](https://issues.apache.org/jira/browse/SOLR-6405)
(general ZooKeeper retry policy). These documented mechanisms differ from
the injected server watcher failure. A bounded search cannot establish issue
novelty, so the status remains `novelty_unverified`.

The bounded Apache Solr GitHub issues/PR search additionally found
[PR #909](https://github.com/apache/solr/pull/909), which fixes the
`collectionWatches`/`watchedCollectionStates` map race from SOLR-16257;
its description says that race can leave collection state stale until a new
watch is registered. It does not describe a caught `ConnectionLossException`
in a fired `StateWatcher` or the FORCELEADER active-leader guard.
[PR #1964](https://github.com/apache/solr/pull/1964) fixes duplicate
`StateWatcher` registration and callback flooding from SOLR-11535, and
[PR #1752](https://github.com/apache/solr/pull/1752) removes a coordinator
watch after collection deletion. Those mechanisms also differ. GitHub
searches pairing `forceLeaderElection` with `stale`, `FORCELEADER` with
`active leader`, and `StateWatcher` with `ConnectionLoss` returned no direct
match in the repository's issue/PR index. This is a search limit, not proof
that the observed mechanism has never been reported elsewhere.
