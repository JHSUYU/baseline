# SOLR-39: postpublication exploratory fault pilot

This is one **outside-closure exploratory** trial. It is not a target-guided graph-closure trial, a reproduced failure, or a new-bug report. No JVM is started by the staging or static checks.

The sealed healthy run of `TimeRoutedAliasUpdateProcessorTest#test` passed on a four-server `MiniSolrCloudCluster`. On physical `node1`, epoch 0, the `AliasesManager` with core object `o12` and Java owner reference 1 published `Aliases` reference 21 at ZooKeeper version 2 to its volatile cache at trace sequence 6203. The same manager reached its **second** watcher `getData(ALIASES, this, stat, true)` door at sequence 6217. The later request read that exact reference at sequences 6451, 6466 and 6484, then reached the selected `lookupShardLeadersOfCollections` check at 6487. There was no intervening cache publication.

`audit_healthy.py` verifies these actor, epoch, manager, reference, version and request identities against the sealed healthy archive, with 310/310 reference markers paired to core field events. Using the pinned `OccurrenceGraph` with event-time reachability and candidate state edges enabled, it finds **no path** from door 6217 to target 6487. The exact-reference publication→read relation is supplemental telemetry; it does not turn the later watcher door into a proved graph predecessor of the target.

The prior v3 fault at `node2`'s first watcher door was precisely applied but removed the target from **node2**, even though four target checks occurred elsewhere on `node4`; JUnit passed and no exact target exception occurred. The v4 selection tests a narrower hypothesis: `node1` already has a valid alias reference before its second watcher read. Solr's `ZkStateReader.AliasesManager.process` catches `KeeperException.ConnectionLossException` around that read, so a skipped refresh may leave the existing reference available to a later request. The source resource is `ZkStateReader.ALIASES = "/aliases.json"`. This rationale supports one bounded exploratory trial; it does not establish a causal edge from this fault to the check or predict a failure.

The plan injects one typed `ConnectionLossException` at `node1`, epoch 0, watcher door ordinal 2. Budget: one trial, one fault, 480 seconds per trial, 900 seconds total. `run_node1.py --preflight-only` verifies SHA-256 pins of the healthy and prior fault archives, source and compiled classes, exact-reference adapter, agent, core release, configuration and plan. It also reruns the offline healthy selection and verifies the explicit outside-closure label. `stage-request.json` has `go=false`. Dispatch must issue a **fresh** GO receipt with its exact pinned fields, `go=true`, and a nonempty new `attempt_id` before the node1 steward invokes:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-explore-node1-v4/run_node1.py --admission-receipt /path/to/dispatch-go.json
```

The runner takes the node1 Solr lane and source locks and writes under `data/mallory/pilots/SOLR-39-exact-alias-reference-node1-v4`. The postfault audit requires exact fault match/application on the selected actor and ordinal, a pre-fault cache publication on the same manager, a later target check on that actor, and request reads of the **same** published reference/version without an intervening cache write. An exact target throw is only a source-review candidate. If the target or reference path disappears, the trial is recorded without a bug claim.

Offline controls:

```sh
python3 -m unittest discover -s Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-explore-node1-v4 -p 'test_*.py' -v
python3 Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-explore-node1-v4/run_node1.py --preflight-only
```
