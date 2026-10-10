# SOLR-34 healthy-only node0 seed

This entry point runs the unchanged Solr 8.11.4 `TestCoordinatorRole#testSimple`
MiniSolrCloudCluster JUnit once under the already pinned
`target-discovery-v1/config-healthy-node2.json`. The configuration name reflects
the first staging host; it contains no host-specific paths. This wrapper writes to
a separate node0 output directory and cannot start a fault campaign.

The selected check is the inner `createException != null` branch at
`CoordinatorHttpSolrCall.getCore:139`. It is reached only when a coordinator
request has called `createColl` for the synthetic collection and the subsequent
`ZkStateReader` lookup still returns null. The newly constructed selected
exception is at line 143. Rethrowing `createException` at line 140 is a
different outcome. The ordinary healthy JUnit is expected to create and see the
synthetic collection, so target absence in the healthy trace does not imply the
JUnit missed coordinator work.

The healthy seed must observe a named replayable I/O door before a full
campaign can be admitted. The pinned catalog includes retry-internal
`SolrZkClient.lambda$getData$6` to `SolrZooKeeper.getData` at line 349 and
`ZkStateReader` collection-state `getData` calls at lines 311 and 1641. These
are source-level candidates; only the fresh event trace can establish actor
identity, order, and whether an injected fault affects the selected check.

Run `python3 run_healthy.py --preflight-only` to check the frozen source,
compiled class, agent, adapter, site catalog, controller release, and workload
without starting a JVM. Runtime execution requires a node0 steward GO receipt
with `go=true`, `host=node0`, `case_id=SOLR-34`, `mode=healthy`, exact
`config_sha256`, exact `runner_sha256`, and the intended output path from the
preflight response. The wrapper then runs only the one healthy seed and records
the JUnit result, target events, I/O doors, and timing under
`data/mallory/solr34_healthy_node0_v2/SOLR-34`.

Source alternatives reviewed: `testMultiCollectionMultiNode` sends queries
through two coordinator nodes after creating ten collections;
`testConcurrentAccess` starts four coordinators and concurrently queries ten
collections. Both add workload and contention but still enter the selected
inner branch only if creation completes without an exception while the local
state remains absent. The existing shorter `testSimple` already exercises the
production creation path and is the first seed to calibrate. No new bug is
claimed by this static stage.
