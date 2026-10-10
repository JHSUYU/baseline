# SOLR-39 preemptive alias watcher fault campaign (v5)

This isolated package reuses the sealed four-node
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation` healthy run and
the v4 exact-reference event-time overlay. It does not rerun the healthy seed.
The selected late watcher doors are node2 ordinal 12, node3 ordinal 13, and
node2 ordinal 15. Each is the actual `AliasesManager.process` read of
`/aliases.json` before an observed `setIfNewer` publication and a later
`lookupShardLeadersOfCollections` check in the healthy run.

`PreemptiveTransformer` runs after the pinned Mallory, Solr, and exact-reference
transformers. It replaces just the core's selected `beforeDoor` invocation by
temporarily saving the five live `getData` operands and calling
`PreemptiveGate` with the **actual String path** and Java `AliasesManager`
receiver. The gate requires the selected actor/ordinal, `/aliases.json`, a
named actor and epoch, a live causal context, and a prior successful
`setIfNewer` publication plus `getAliases` read on the same receiver. It emits
a `STATE_READ` identity marker containing the core's run-local manager token,
resource, actor, occurrence and thread before delegating to `Probe.beforeDoor`.
Wrong-resource selections suppress all later Probe calls on that actor to
prevent an ordinal shift from hitting another point.

The exception is the source-caught ZooKeeper
`KeeperException.ConnectionLossException`. An applied exception stops this
watcher invocation before the new `setIfNewer` write; the auditor explicitly
rejects any publication inside the injected watcher. A valid fault trial must
still reach the exact `@246` check on that manager through a **prior** exact
Java `Aliases` reference publication/read and a balanced getter return to
the caller. The auditor reconstructs this observed path using the v4 overlay;
it does not invent a positive edge from the fault door to the target.

The campaign has at most 12 fault trials, 2,400 trial seconds, 480 seconds per
trial and three faults per sequence. It starts with the three sealed late
doors, then adds one later observed door only after a fully valid parent.
Coverage and exact reference-edge novelty are counted only for strict valid
trials. Invalid injections, wrong resources, lost targets, and missing prior
paths contribute zero novelty and no children. An exact target throw is a
candidate for source review, not a confirmed bug.

`run_faults.py` is checkpointed after every trial and will resume an
interrupted trial without repeating an already completed one. It requires a
fresh SHA-bound dispatch GO receipt, node1 lane locks, disk and memory floors,
and an idle JVM lane. `stage-request.json` is **GO=false**; this package does
not authorize a Solr or JUnit run by itself.

Offline checks (no Solr/JUnit cluster):

```sh
python3 -m unittest discover -s Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v5 -p 'test_*.py' -v
python3 Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v5/verify_offline.py
python3 Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v5/run_faults.py --preflight-only
```

The verifier uses `-Xverify:all` to load the exact pinned SolrJ class after
the real transformer chain and checks the gate on a wrong actual path and
the correct path. It never starts the JUnit cluster.
