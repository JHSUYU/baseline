# SOLR-15 path-aware healthy seed

This package runs one unchanged Solr 8.11.4
`ShardSplitTest#testSplitWithChaosMonkey` MiniSolrCloudCluster JUnit on node0.
It retains the pinned target-absent controller, v38 Solr adapter, source and
test selector from `chaos-healthy-node0-v2`. The only runtime substitution is
the immutable path-aware agent release with SHA-256
`b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4`.
That agent was built in its separate `solr-zk-resource-v1` source tree; its
release manifest records 26 passing instrumentation tests. No shared agent or
controller source is changed by this package.

The selected `SplitShardCmd.split` check is at line 536 and its target throw
at line 538. Source line 164 reads `/live_nodes/<parentShardLeader>` for the
first `Stat`; line 523 reads the same expression again before the guard. The
prior sealed v1 healthy trace passed JUnit 1/0/0 and showed one split on the
registered `control` actor with ordered caller/native handoffs:
`1378 (@164) → 1379 (native exists)` and
`1883 (@523) → 1884 (native exists)`. The native events lacked the path, so
that trace alone could not prove that both calls read the parent leader znode.

The path-aware agent loads the first String argument of the exact
`SolrZkClient.lambda$exists$2` retry lambda at the `SolrZooKeeper.exists`
callsite. The healthy audit requires the loaded catalog marker, one passing
JUnit, a registered `control` actor, the same split occurrence and thread,
and equal `/live_nodes/<registered shard address>` resources on the two
selected native events. It rejects missing, changed, or unrelated znode paths.
The path and actor are observations from the same events as the typed native
door, so this is a precise seed for future fault selection.

This is **healthy-only**. The current fault plan still selects by site, actor,
occurrence and ordinal; it does not match the znode path before injection.
The audit therefore never admits a full fault campaign or claims a new bug.
A later fault package must bind a replayable second lookup on the same split
and confirm the exact line-536 check and line-538 throw after an effective
fault. The user-visible exception may be an expected protective abort after
leader loss, so a target throw alone is not a new-bug conclusion.

`python3 run_campaign.py --preflight-only` checks all pinned inputs without
starting a JVM. `python3 -m unittest -v test_audit_healthy.py` exercises the
resource gate entirely in Python. Runtime execution requires a separate node0
steward GO receipt matching `admission-request.json` with `go=true`; no GO is
staged here. The runner acquires the node0 ZooKeeper and Solr lane locks,
writes to `data/mallory/solr15_path_healthy_node0_v3/healthy`, and then runs
the path-aware audit. No runtime has been launched by this package.
