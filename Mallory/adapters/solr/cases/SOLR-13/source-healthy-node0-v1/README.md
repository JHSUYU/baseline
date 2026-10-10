# SOLR-13 node0 healthy source admission

This package runs one fault-free, unchanged Solr 8.11.4
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation` JUnit. Its setup
starts a four-node `MiniSolrCloudCluster`; the test creates time-routed
aliases and calls `addOneDocSynchCreation` twice. These adds require new
collections and exercise synchronous routed-alias creation. The test needs
Solr's source-defined `solr.disableConfigSetsCreateAuthChecks` setup flag and
`tests.awaitsfix=true` selection flag, both already pinned by the source
admission config.

The exact target is `RoutedAlias.doSynchronous@348:branch:1`. After
`ensureCollection`, the method refreshes aliases and checks whether the
requested collection appears in `observedCols`; line 350 throws a
`SolrException` if it does not. The typed I/O frontier is the Overseer-side
`ZkStateReader$AliasesManager.applyModificationAndExportToZk@2259:door:1`
call to `SolrZkClient.setData`. A `BadVersionException` is caught at line
2262, followed by an alias refresh and retry. The package uses the exact
single-door catalog from `source-admission-v1`.

The prior node2 healthy run passed 1/0/0 and reached the target five times
on named node1/node4 actors. It observed 20 named typed alias-write doors.
No door had a proven event-time graph path to a selected target; the door
ran in a distinct Overseer task context. This node0 package asks for a
fresh observation and reports the path count separately. Temporal order
alone never authorizes fault injection or a bug claim.

`run_campaign.py` checks the original source-admission SHA pins, requires a
clean pinned Solr checkout, compares the node0 config with the original
config, and verifies its own manifest. It supports only `--mode healthy`.
A case-local dispatch GO receipt, fresh output, node0 host, lane/source
locks, disk and memory reserve, and no competing user JVM are required
before one JUnit trial. `audit_healthy.py` checks JUnit 1/0/0, the exact
target and typed door on named actors, loaded bytecode, and fault-free raw
evidence. It does not promote a full campaign.

Offline verification: `python3 run_campaign.py --mode healthy --preflight-only`.
The intended output is `data/mallory/solr13_source_healthy_node0_v1/healthy`.
