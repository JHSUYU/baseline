# SOLR-15 physical-control healthy seed

The original Solr 8.11.4 `ShardSplitTest#testSplitWithChaosMonkey` cluster
JUnit starts embedded ZooKeeper and several Jetty servers, splits a shard,
stops its leader during the split, and checks document and shard consistency.
The source permits the split request to fail. The selected production guard is
`SplitShardCmd.split` `@536:branch:40`, with a `SolrException` at
`@538:throw:1`. A healthy test can pass without taking that branch.

The earlier `chaos-healthy-node0-v1` run passed JUnit 1/0/0 and loaded the
exact check sites, yet its offline audit rejected the actor name `control`.
That rejection was too narrow: `SolrHooks.miniClusterRole` maps the physical
`control-<id>` Solr home to the stable `control` role, and the JUnit log
records the corresponding actual host and port. This version admits that
registered role. Its audit of the immutable v1 trace found, in one split
occurrence on `control`, the first caller door at sequence 1378 followed by a
typed ZooKeeper native `exists` door at 1379, and the second caller door at
1883 followed by that native door at 1884. The audit checks the next door on
the same actor, thread, and context, allowing unrelated threads to interleave.
The second caller is source line
523, immediately before the selected line-536 guard. Both doors have the
`ConnectionLossException` fault type in the loaded site catalog.

This is a **healthy-only** package. The trace does not contain the ZooKeeper
path, and the native fault plan cannot match that path. There has been no
Mallory fault trial for this case and no demonstrated exception outcome. The
prior CrashFuzz observation of this guard is a separate historical result,
not evidence for this Mallory campaign. A full campaign must retain the exact
second leader-znode read when selecting the native exception door and check
whether the line-536 guard and line-538 exception occur afterward.

`run_campaign.py` uses the pinned original chaos JUnit, adapter, agent, and
target-absent core. It verifies the case-local hashes and source revision,
requires a case-specific node0 dispatch GO receipt and a fresh output path,
and runs under the node0 Solr/source locks. Its single fault-free trial is
written to `data/mallory/solr15_chaos_healthy_node0_v2/healthy`. No GO
receipt is staged here, and no JVM has been started by this package.

Offline preflight: `python3 run_campaign.py --mode healthy --preflight-only`.
The v1 trace reanalysis receipt is `v1-trace-reanalysis.json` and was produced
without editing the sealed v1 runtime evidence.
