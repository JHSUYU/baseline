# SOLR-15: source and workload disposition

Pinned Solr source: `e27f44e3d78dfcec230c97e0a1240e3751daeff9`.
The selected check is `SplitShardCmd.split` line 536 and its throw is line
538. The method saves the parent leader's live-znode `ephemeralOwner` after
the first `exists` at line 164, reads the same path again at line 523, enters
the abort block at line 524 if that second `Stat` is absent or changed, and
then evaluates line 536. A missing second `Stat` takes line 538. An unchanged
second `Stat` skips line 536.

The node0 path-aware healthy run
`data/mallory/solr15_path_healthy_node0_v3/healthy` passed the original
`ShardSplitTest#testSplitWithChaosMonkey` JUnit (1/0/0). Its path gate binds
native events `SOLR-15-r0000:1394` and `:1899` to the same parent leader path
`/live_nodes/127.0.0.1:40293_`, same split, actor, epoch and thread. Neither
the exact line-536 check nor line-538 throw executed. The trace does not log
returned `Stat` values; the normal path through line 524 is a control-flow
inference. This healthy run has **no observed target closure**.

I reviewed the 23 Solr test/support Java files containing `splitShard`,
`SPLITSHARD` or `trySplit`. The closest unchanged cluster test is already the
selected chaos JUnit. It stops the original parent leader after a child shard
has more than one replica and starts the leader again only after the async
split result (`ShardSplitTest.java:454–506`). `SplitShardCmd` performs the
second `exists` before creating those additional replica cores
(`SplitShardCmd.java:523–545`). The test's own planned stop therefore does not
deliberately remove the znode at the second lookup. Other split JUnits either
run a normal split, restart a node after split completion, or stop an old
leader before starting split. They provide no better unchanged healthy seed
for line 536.

The absence of a healthy target does **not** justify a no-suitable-test skip:
the earlier CrashFuzz supplemental fault trial and replay used this same
unchanged chaos JUnit, applied two typed native ZooKeeper faults at the
second parent live-node lookup, observed `stat=null`, and reached line 538
with JUnit 1/0/0. See
`crashfuzz/cases/SOLR-14/independent/supplemental/shardsplit/solr15-native-candidate-source-review.json`
and `native-chaos-fault-02/audit.json` alongside it. Source review classified
that exact exception as Solr's expected protective abort after leader loss,
not a new bug.

For Mallory, the faulted trace may establish the first exact target anchor.
Until then, candidate I/O points are a **target-absent discovery policy**, not
a proven target closure. A fault trial must attest the physical actor, exact
`/live_nodes/<parent>` resource, ordered fault receipts and postfault exact
line-536 check before its graph or coverage can guide later mutations.
