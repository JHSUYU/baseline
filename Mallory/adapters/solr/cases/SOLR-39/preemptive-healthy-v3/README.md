# SOLR-39 preemptive healthy seed v3

This GO-gated package runs one unchanged four-server
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`. It observes the
exact `@246` branch and each `AliasesManager`/`Aliases` object reference,
version, watcher door, and target read. The package has no fault plan.

The prior Category and Dimensional healthy runs are invalid; see
`SOURCE-REVIEW.md`. Preemptive creation is the next source-backed workload
because it repeatedly changes alias metadata and commits through routed
aliases on a four-server cluster. Its healthy JUnit and strict late watcher
path still need runtime verification.

Offline preflight:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/preemptive-healthy-v3/run_healthy.py --preflight-only
```

After dispatch issues a fresh SHA-bound GO receipt, the node1 steward may
run one healthy trial:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/preemptive-healthy-v3/run_healthy.py --admission-receipt /path/to/fresh-go.json
```

The trial must have `junit-receipt.json` status `passed`, at least one exact
target check, complete exact-reference telemetry, and a late candidate from:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/preemptive-healthy-v3/select_late_watcher.py /path/to/trials/r0000
```

The staged request has `go=false`. No JVM starts during staging or preflight.
