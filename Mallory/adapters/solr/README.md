# Solr 8.11.4 Mallory adapter

This adapter runs unchanged Solr cluster JUnit methods against the Solr 8.11.4
distribution. The direct JUnit runner is used because the test source checkout
does not have a usable Ant installation. Each trial compiles the selected test
from its inventory-pinned source, then starts a fresh JVM and its embedded
`MiniSolrCloudCluster`. A trial's temporary directory and event files stay in
that trial's output directory.

## Runtime handoffs

The separate Solr transformer jar uses public Mallory `Probe` hooks. It assigns
each embedded server the stable `nodeN` role from the MiniSolrCloudCluster
instance directory, and marks SolrJ alias lookups as the logical `client`
actor. An outbound Solr HTTP request receives an `X-Mallory-Causal` header;
`SolrDispatchFilter` receives the same token. `ExecutorUtil` submissions and
claims also carry a token and restore the submitting actor. No GraphChecker
code is copied into this adapter.

Collection commands inherit the owning `Overseer` server actor through
`OverseerCollectionMessageHandler#processMessage`. Alias watcher callbacks
inherit the actor registered on their owning `ZkStateReader` by
`ZkController`. Both scopes close on normal return and implicit exception.
An unregistered object stays unidentified; it is never guessed from a thread
name or counted as a named causal edge.

Generated site files include exact target checks and throws from
`Mallory/cases/*.sites.json`. Additional fault doors are limited to compiled
Solr ZooKeeper operations with their declared `KeeperException` or
`TimeoutException` type. Automatic I/O callsite doors cover direct file,
socket, and SolrJ request calls in the three included classes: the target,
`ZkController`, and `BaseHttpClusterStateProvider`.

## Build and prepare a case

```sh
cd Mallory/adapters/solr
# Build Mallory/instrumentation first; this Maven module compiles against its jar.
mvn -q test package
cp target/mallory-solr-adapter.jar target/mallory-solr-adapter-v4.jar
python3 make_case_config.py SOLR-05 --output cases/SOLR-05/config.json
```

`make_case_config.py` reads the selected selector, test source hash, compiled
class hash, and target IDs from `Mallory/cases`. It writes a direct JUnit
campaign config and a bounded site file. Generated configs remain preliminary
until a healthy calibration verifies the exact target catalog, loaded class
hash, named actor, and a reachable fault door. Bind a case to a named role
only after its own healthy trace shows it.
Generated configs pin the agent, adapter, site file, and runner hashes. The inventory
currently gates `SOLR-15`, `SOLR-16`, and `SOLR-34` from fault trials because
their selected inner guards cannot be reached by a nonthrowing healthy seed.
`SOLR-16` uses the corrected `@539:branch:41` check ID.

For an isolated copied source tree, pass `--source-root` with its absolute path
and `--calibration-only`. Dispatch verifies its tracked-file fingerprint against
the inventory-pinned Solr commit; the direct JUnit runner records that commit
without requiring `.git` metadata in the copy. Versioned `run_pilot_v4.py` and
the v4 adapter preserve the SOLR-05 v1 campaign's runner and jar provenance.
The v4 SolrJ hook binds outbound HTTP/2 and HTTP/1 sends to a logical client
or an already named server actor; a paired inbound request retains its node.
The default generated runner is the pinned `releases/v4/run_pilot.py` entry
point, whose JUnit marker is checked against the trial's `pilot-result.json`
and `junit.log` by the campaign controller.
Later versioned adapters add the collection-command and alias-watcher scopes
without changing the pinned v4 artifact. The separate v6 JUnit runner enables
`@Nightly` only for cases with `MALLORY_SOLR_NIGHTLY=1` in their config, and
records that choice in `pilot-result.json`. A test skipped by `@Nightly` or
`@AwaitsFix` is an invalid healthy seed, even if JUnit reports zero failures.
The separate v8 runner can opt into `@AwaitsFix` for bounded calibration with
`MALLORY_SOLR_AWAITSFIX=1`. Such a test needs a passing healthy run, exact
named target reach, and source review before fault promotion.

For a local compile check without running the test workload:

```sh
python3 run_pilot.py SOLR-05 --source ~/.graphchecker-sources/solr-8.11.4 \
  --output /tmp/mallory-solr05-compile --compile-only
```

For a standalone healthy run, omit `--compile-only`; the runner writes a
`pilot-result.json`, `junit.log`, event trace, and site catalog. The campaign
controller invokes it with `--campaign`, `JAVA_TOOL_OPTIONS`, and a fresh
`{trial_dir}`. JUnit's original assertions and `@Repeat` iterations remain in
effect. A target exception is a candidate observation; source review is still
needed before classifying a bug.
