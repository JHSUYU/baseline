# Existing native campaigns: read-only queue preflight

This directory is a **draft in the isolated branch**
`agent/native-existing-bindings-20261013`. It records four campaigns that were
launched outside the 102-case native queue. It does not launch a worker, create
queue completion receipts, change campaign pins, or copy files into the shared
main checkout. Run from this worktree with:

```bash
python3 -m Mallory.native_graphchecker_queue.preflight_existing.audit
python3 -m unittest Mallory.native_graphchecker_queue.preflight_existing.test_audit -v
```

The audit resolves each binding through the real native dispatcher, verifies
the config SHA against the checkpoint, checks the pinned engine JAR, and checks
the original JUnit process receipts for separate trial workdirs and data/temp
arguments. The 102-case ownership draft puts ZOOKEEPER-07 and HDFS-11 on node0,
SOLR-01 on node1, and HBASE-02 on node2. Owner totals are node0 51, node1 30,
node2 21. These physical owners supersede the archived shard ownership for
these four cases.

| Case | Native config SHA-256 | State | Current preflight disposition |
| --- | --- | --- | --- |
| ZOOKEEPER-07 | `9a243f5e2e41db0258898a7bb02fc7ef06cb9636d624ab7b35401d39fe04fc0d` | `/proj/silentfailure-PG0/ZhenyuLi/Mallory/ZOOKEEPER-07-20261013-native-wjtp-campaign-v8/campaign` | Terminal checkpoint, 64 fault trials; separate ZK pilot adoption is managed elsewhere. |
| HDFS-11 | `485ece82698f969deffcd742e681b44364cf2570d6344bf15d61bbb688058871` | `/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs11-native-campaign-v2/campaign` | Terminal time budget, 24 fault trials; import only the existing audited result. |
| SOLR-01 | `ec30ac967d86b75f73314606b1946d8356acc0ce357b7d0d8c26f08dbf5ff17b` | `/proj/silentfailure-PG0/mallory/solr01-native-campaign-v1/formal` | Running at preflight; do not adopt or resume concurrently. |
| HBASE-02 | `65766ce2f863da4df2b5bf3d4a6884d64f8cda2578a767c8447a7e172cb849e2` | `/proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-02-20261014-native-v1/campaign` | Running at preflight; do not adopt or resume concurrently. |

The checkpoint status and trial counts in this table are snapshots; rerun the
audit for current status. Each JSON binding pins the exact immutable native
config and state path. HDFS-11 also pins an attestation for its alternate
unchanged upstream JUnit selector. The real `inspect_case` audit of HDFS-11
returned `tested_no_target_throw`, 24 fault trials, 15 strict and target-retained
trials, zero target throws, and 1865.235 cumulative trial seconds. Its
`terminal-review.json` SHA-256 is
`a277f743bfb55c6c2d3a23f02d97c34cd0fecac27e4569911eaa201bed0a514a`.
That review explicitly records **budget terminal, not high-quality complete**:
there are no new selected-target closure-edge families and no fault-induced
target throw. Preserve this limitation even if the queue's lower-level
`native_tested_complete` field is true. Never replay these 24 terminal trials.

## Isolation observations

- All observed original JUnit process receipts in these four roots set
  `java.io.tmpdir` to their own `trials/rNNNN/iteration-native/workdir`.
  ZooKeeper and HBase also set `build.test.dir` there; HDFS sets
  `test.build.data`; Solr sets `solr.log.dir`. State, trace, result, and fault
  files live below distinct native state roots. The audit checks every process
  receipt present at invocation, including those added while a campaign runs.
- On node0, ZOOKEEPER-07's assigned range is 28719–30064. The host ephemeral
  range starts at 32768. HDFS-11's pinned isolation proof covers 11 completed
  trial observations and 261 distinct observed bound ports with zero overlap
  with the ZooKeeper range. This is an observation plus source review, not a
  claim that every future listener has been exhaustively observed.
- SOLR-01 alone occupies node1 in this four-case set. Its draft port review
  pins the original JUnit and MiniSolrCloudCluster sources showing ZkTestServer
  and Jetty default port zero. HBASE-02 alone occupies node2 in this set.
  `MiniZooKeeperCluster` chooses a random **nonzero** port in 49152–65279 and
  retries bind conflicts. `hbase-port-review.draft.json` pins the exact JUnit,
  HBaseTestingUtility, LocalHBaseCluster, and MiniZooKeeperCluster sources for
  the new case-specific `random_retry` policy. `hbase-port-gap.json` preserves
  the reason the prior all-zero/assigned-range model could not represent it.

## Promotion gaps before any queue worker

1. `isolation.draft.json` is deliberately **not a launch profile**. Its HDFS,
   Solr, and HBase receipts are under this temporary worktree and must be
   re-pinned at a durable promotion path. This branch extends the queue's
   directory gate for the immutable HDFS `test.build.data` and Solr
   `solr.log.dir` arguments, and validates HBase's case-specific source-backed
   random/retry receipt. A logged, unresolved bind collision still invalidates
   the affected native completion.
2. The native campaign imports `ENGINE` and `JAR` from
   `MALLORY_NATIVE_ENGINE_ROOT` at module import. These four existing campaigns
   pin different engine roots, and HBase has a different engine JAR digest.
   This branch now launches a fresh Python process for each runnable case with
   the exact engine root and JAR SHA from its weave receipt. The Python source
   snapshot used by each external launcher still needs a binding pin before
   automatic resume of these existing campaigns; their currently running
   launchers remain the owners. Terminal adoption uses the existing summary
   and checkpoint, without calling `run_campaign` again.
3. The external campaigns' `.campaign.lock` is the authoritative live lease.
   The queue checks it before a run, but no queue worker has been launched by
   this preflight. Keep SOLR-01 and HBASE-02 outside queue scheduling until
   terminal, then audit their final checkpoint and summary. Publish one native
   completion receipt per case only after full `inspect_case` and isolation
   review. Any actual bind collision must invalidate affected trials.

The branch also caches a full terminal `inspect_case` result against inventory,
binding, config, checkpoint, and summary SHA-256. A valid pilot receipt plus
its native completion receipt can seed that cache for an already audited pilot;
`run-host` and the workers then reuse it while those bytes remain unchanged.
The cache invalidates on a changed checkpoint, summary, config, binding, owner,
or review. The audit cache is a performance record, not a substitute for the
first full native audit.

The current audit always emits `adopt_now: false`; it is a preparation record,
not authorization to resume or publish results.
