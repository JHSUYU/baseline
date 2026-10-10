# SOLR-39 Dimensional routed-alias healthy seed

This GO-gated package runs one **healthy-only** unchanged
`DimensionalRoutedAliasUpdateProcessorTest#testTimeCat` on a four-server
`MiniSolrCloudCluster`. It carries the exact `@246` target, the line-247 throw,
the typed watcher `getData("/aliases.json")` door, and per-event Java
`AliasesManager`/`Aliases` reference and ZooKeeper version telemetry. No fault
plan is included.

The previous Category healthy seed reached the target once but its JUnit
failed before any fault: after the first add/commit, `assertInvariants` expected
one indexed document and found zero. The paired reference audit found no
watcher-publication-to-target path in its 72/72 paired field markers. The
previous custom runner name was also not recognized by the pinned JUnit gate.
This v2 entry point is named `run_pilot.py`, which the gate recognizes and
cross-checks against `pilot-result.json` and `junit.log`.

Dimensional `testTimeCat` is an existing cluster test. It creates a two
dimensional routed alias and repeatedly adds and commits documents while the
alias grows. The expected target path is `processCommit()` into
`lookupShardLeadersOfCollections()`. Admission still requires the actual
healthy JUnit to pass and exact target checks on named server actors. The
candidate selector requires a previous valid alias reference on the same
manager/actor, a later watcher read followed by a new publication, exact
reference reads in the routed request, and an event-time graph path from the
watcher door to the target. If none exists, the case remains unadmitted.

Offline preflight, without a JVM:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/dimensional-healthy-v2/run_healthy.py --preflight-only
```

Only after dispatch supplies a fresh SHA-bound GO receipt may the node1
steward run the one healthy seed:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/dimensional-healthy-v2/run_healthy.py --admission-receipt /path/to/fresh-go.json
```

If it passes, inspect `trials/r0000` offline:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/dimensional-healthy-v2/select_late_watcher.py /path/to/trials/r0000
```

The staged request has `go=false`. Neither staging nor preflight starts a JVM.
