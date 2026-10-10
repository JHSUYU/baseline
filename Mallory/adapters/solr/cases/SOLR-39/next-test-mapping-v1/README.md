# SOLR-39 Category routed-alias healthy seed

This package is **healthy-only** and has no fault plan. It selects the unchanged
`CategoryRoutedAliasUpdateProcessorTest#test` on a four-server
`MiniSolrCloudCluster`. The inherited `@AwaitsFix` test group is enabled with
`MALLORY_SOLR_AWAITSFIX=1`; the pinned ConfigSet authentication fixture flag
is retained. The selected target is
`RoutedAliasUpdateProcessor.lookupShardLeadersOfCollections()`'s line-246
null-collection-list check, with the line-247 throw recorded separately.

The category test creates a category-routed alias, then adds and commits
through it twice. `processCommit()` calls the target before distributing the
commit. The category test is shorter than the dimensional test, which creates
many more collections and includes a five-second sleep. This is a source-level
workload mapping; the new selector has not yet produced a healthy trace.

The package reuses the Solr v38 instrumentation and the pinned exact-reference
adapter. The latter records the `AliasesManager` owner object, the published
`Aliases` reference and ZooKeeper version, and the constructor/target reads of
that reference. Healthy admission requires a passing JUnit, the exact
nonthrowing target on a physical server, and a watcher `getData("/aliases.json")`
door that causally precedes a later cache publication read by the same manager
at the target. A later watcher door without a publication-to-target path is not
eligible. A future strict fault trial may use a later watcher refresh after the
actor already has a valid alias reference; the fault plan must be selected from
this healthy run, never copied from the prior Time test.

The earlier Time-test v3 pilot applied a first-watcher
`ConnectionLossException`, but the bound node2 target disappeared. Its v4
second-watcher trial was outside the healthy closure and also lost the bound
node1 target. Both JUnit tests passed; neither supplies completion credit for
this strict target-guided experiment.

Offline package check, without starting a JVM:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/next-test-mapping-v1/preflight.py
```

After dispatch issues a fresh SHA-bound GO receipt and the node1 steward has
verified resource and lane gates, the steward may run:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/next-test-mapping-v1/run_healthy.py --admission-receipt /path/to/fresh-go.json
```

The `go=false` request in this directory is staging metadata and cannot start
the JUnit. No fault may be promoted from this package without an event-time
closure and exact resource/actor/epoch/manager/reference audit.
