# solr-adhoc-22: ported workload

Operator record (B3). Never given to a Specula agent; the agent sees only the ported test and its configset.

**Status: PORT_BLOCKED** (see "Why blocked"). The port below is written and compiles against upstream, but it cannot
pass there.

- **Case**: solr-adhoc-22 = GraphChecker's `solr-18406` (marker `solr-18406`), the throw at upstream
  `solr/core/src/java/org/apache/solr/core/IndexDeletionPolicyWrapper.java:177`, `getAndSaveCommitPoint(Long)`.
- **Defect present at the base**: upstream `faca81bff1` is the tip of `branch_8_11` (GitHub API, 2026-11-02). The
  reservation of a fetched generation is still the time-based `reserves` map (`setReserveDuration`, `System.nanoTime`),
  and the JIRA (affects 8.11.4 and 9.10.1) is fixed in 9.11 and 10.1 only, i.e. in apache/solr, not on `branch_8_11`.
- **GraphChecker original**: `org.apache.solr.handler.TestCausynthPullReplicaReservation#pullReplicaFetchesAcrossALeaderCommit`,
  in the fork tree `/bulk/wt/lucene-solr-checks` (`graphchecker/solr-checks` 12d23091d1 on top of upstream `faca81bff1`),
  `solr/core/src/test/org/apache/solr/handler/TestCausynthPullReplicaReservation.java`, with the fork-only configset
  `solr/core/src/test-files/solr/configsets/causynth-replication/conf/{solrconfig.xml,schema.xml}`. Scope from
  `experiments/solr/solr-18406/case.sh`.
- **Port**: `org.apache.solr.handler.TestAdhocWorkload22#run`, in
  `tree/solr/core/src/test/org/apache/solr/handler/TestAdhocWorkload22.java`, and its configset
  `tree/solr/core/src/test-files/solr/configsets/adhoc-workload-22/conf/{solrconfig.xml,schema.xml}`. Untracked files of
  the case tree.

## Kept (same scenario)

- Topology: `SolrCloudTestCase.configureCluster(2)` (upstream `MiniSolrCloudCluster`), one config `conf`.
- The test's own configuration (configset): upstream `cloud-minimal`'s schema unchanged; its solrconfig plus
  `NoMergePolicyFactory`, `useCompoundFile=true`, and a `/replication` handler with `commitReserveDuration=01:00:00`
  (all three kept from the original, values unchanged).
- The operations in the same order: create a 1x1 collection on node 0; wait active; add a PULL replica on node 1; wait
  active (1 shard, 2 replicas); stop node 1's replication from the leader (`ZkController.stopReplicationFromLeader`);
  index 20 docs and commit (one round, `COMMITS = 1`); set `IndexFetcher.testWait` to a latch hold; send
  `/replication?command=fetchindex&leaderUrl=<leader core url>` to the PULL core; wait until the fetch is held;
  index 20 more docs and commit; restore `testWait` and release the hold; poll the PULL core (`distrib=false`) every
  200 ms until it has the first 20 docs.
- The same waits: 60 s for the hold, 60 s hold limit in the hook, 60 s poll with 200 ms sleeps.
- `@LuceneTestCase.Slow`, JUnit 4, package `org.apache.solr.handler` (needed for the package-private `IndexFetcher.testWait`).

## Removed or replaced, and why

| original | port | why |
| --- | --- | --- |
| class `TestCausynthPullReplicaReservation`, method `pullReplicaFetchesAcrossALeaderCommit`, collection `causynthPull`, configset `causynth-replication` | `TestAdhocWorkload22#run`, collection `adhocWorkload22`, configset `adhoc-workload-22` | neutral names (B3) |
| javadoc naming the JIRA and describing the generations, the reservation, the deletion policy's decision and the clock that would delete G | javadoc listing the topology, operations and waits | no comment states the failure or the mechanism |
| inline comments ("G+1 ... the leader's deletion policy asks to delete G, and G's reservation keeps it", "the follower listed G") and assertion messages naming G | neutral comments and messages ("the follower's fetch was held", "the follower holds the first commit's documents"); variable `inG` -> `firstDocs`, latch `listed` -> `held` | same |
| configset comments ("A reservation no run outlasts ...", "No merge between the leader's commits of G and G+1 ...") | removed; settings kept | same |
| the fork's automatic cluster under the same `SolrCloudTestCase`/`MiniSolrCloudCluster` (GraphChecker's `CausynthSolrCluster`: nodes started one at a time, client registration, the test-method request scope, a client socket timeout that never fires, CausynthRandom placement/order) | upstream `SolrCloudTestCase`/`MiniSolrCloudCluster` unchanged | adapter and replay-determinism helpers (B3); the test itself calls none of them |

The original has no GraphChecker or Causynth call in the test body, writes no operand of the guard (`knownCommits`,
`commit.isDeleted()`, `latestCommit`), and injects nothing. The workload injects no fault.

## Why blocked

The hold the scenario depends on ("the follower is held after filelist(G) while the leader commits G+1") is a hook in
production code that the fork added and upstream `faca81bff1` does not have:

```java
// fork, solr/core/src/java/org/apache/solr/handler/IndexFetcher.java, fetchLatestIndex, after fetchFileList(latestGeneration):
      // The test hook upstream added here (apache/solr#4820), without its fix:
      // a workload holds the follower between filelist(G) and filecontent(G).
      assert testWait.getAsBoolean();
```

Upstream 8.11.4 calls `IndexFetcher.testWait` only in the disk-space cleanup path (`IndexFetcher.java:1188`), which this
workload never takes. On the upstream tree the hold never happens: `held.await(60 s)` times out and the test fails
before the second commit. Measured 2026-11-02 (`baseline/REACH.tsv`): FAIL in 104 s, `AssertionError: the
follower's fetch was held`; the unheld fetch still enters `getAndSaveCommitPoint` 5 times. The hook comes from the upstream fix PR's test. A faithful port
needs one of these, for the owner to choose:

1. Add that one hook line to the case tree's `IndexFetcher` as a neutral commit (the target's `base_commit`, provenance
   in `inventory.tsv` only, as B1 step 5 does for reverts). The agent then sees a one-line production change (an
   `assert` that is a no-op unless a test sets `testWait`).
2. Hold on the leader instead, with no production change: a test-only `ReplicationHandler` subclass named in the
   configset that, after serving `command=filelist`, waits for the latch before the response is written. Same
   leader-side order (file list computed and its commit point released, then the leader commit, then the
   `filecontent` requests), but the follower waits for the response instead of after it.
3. Drop the hold: fetch and commit concurrently. Not the same scenario (the order becomes a race).
