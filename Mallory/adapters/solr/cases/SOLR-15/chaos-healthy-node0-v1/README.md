# SOLR-15 node0 healthy observation

This package runs one fault-free invocation of the unchanged Solr 8.11.4
`ShardSplitTest#testSplitWithChaosMonkey` cluster JUnit. The JUnit starts an
embedded ZooKeeper and several Jetty nodes, stops the parent shard leader
during a split, restarts it, and checks document and shard consistency. It
allows the split request itself to fail. The target is
`SplitShardCmd.split@536:branch:40` and its line-538 `SolrException`. In the
production source, the second `/live_nodes/<parent leader>` lookup occurs at
line 523; a missing znode causes the protective abort at line 538.

The package reuses the pinned `chaos-target-discovery-v1` test wrapper, site
catalog, v38 adapter, agent and target-absent core. Its config differs only
in the one-trial budget and the revision label. `run_campaign.py` verifies
that equality, the original package's immutable pins, the clean Solr source
revision, and this package's SHA manifest. It admits only `--mode healthy`.
The runner requires a case-local dispatch GO receipt, a fresh output path,
node0, free resources and the node0 Solr/source locks before starting a JVM.

`audit_healthy.py` requires the original JUnit to pass 1/0/0, exact loaded
target sites, an untruncated fault-free trace, and one named physical actor
whose first and second caller doors occur in the same split occurrence,
followed on that thread by the native `SolrZkClient.lambda$exists$2` door.
The target check is expected to be absent in a passing bootstrap trace.
This handoff is only temporal evidence: current door events do not record
the ZooKeeper path. A full campaign needs path-qualified or equivalent
parent-leader identity and a resource-aware selector, followed by exact
target/throw evidence. No full mode or GO request is included here.

Offline verification: `python3 run_campaign.py --mode healthy --preflight-only`.
The intended output is `data/mallory/solr15_chaos_healthy_node0_v1/healthy`.
