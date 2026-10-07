# SOLR-21 actor-aware fault campaign

The workload is the **unchanged** Solr 8.11.4 embedded-cluster JUnit
`CollectionReloadTest#testReloadedLeaderStateAfterZkSessionLoss`. The earlier
80-plan run under `../independent/` is retained as coarse selector evidence
and contributes zero V2 effective trials.

## Runtime identity

The original test calls `configureCluster(1)`. `MiniSolrCloudCluster` creates
its single Jetty under the stable Solr home directory `node1`. The V2 ASM
agent binds the exact `SolrZkClient` assigned to its `ZkController` to
`JETTY/node1` and records its actual changing node address. Every hooked
ZooKeeper lambda passes its `this` receiver to the probe. The I/O selector
and per-site hit ordinal include `actorKey`; an external or otherwise unbound
ZK client cannot consume the planned fault. Raw rows retain client identity,
node address, Solr home and MDC as evidence.

For `core.properties`, the original `CorePropertiesLocator` bytecode passes
the actual `CoreContainer` argument into the file-read probe. The probe only
binds the read if the file's parent core directory is directly under that
container's `getCoreRootDirectory()` and that container's actual ZK client is
bound to `JETTY/node1`. All other file reads get `UNBOUND:FILE_CORE` and are
ineligible. The target assertion row records `CoreDescriptor` collection,
shard, replica/core name, the receiving `CoreContainer` actor, raw node, Solr
home and core root. The target counts after a fault only with the same exact
core/replica and actor as the healthy runs.

## Verification and run order

Offline checks already pass on node0: `build_agent.py`,
`smoke_transform.py` (original class bytecode), and `smoke_actor_match.py`
(wrong ZK client cannot consume a planned exception). Before fault trials,
run two **new** clean original JUnit JVMs and audit their raw actor bindings:

```sh
python3 build_agent.py
python3 build_junit.py
python3 smoke_transform.py
python3 smoke_actor_match.py
python3 run_healthy.py
python3 calibrate.py
python3 fuzz_v2.py --max-effective 80 --max-faults 8
```

`build_junit.py` uses either the pristine checkout at `../independent/` or
the local Solr 8.11.4 source at the same Git revision. It verifies every
original test source hash and original Solr core JAR hash against the prior
pristine build. Run cluster JUnit steps only on a released node; do not overlap
another Solr campaign on the same node. The checkpoint, raw traces, JaCoCo coverage, plans, and
per-trial elapsed times remain under this directory. A completed plan is not
repeated after resume. Only all-faults-matched trials reaching the exact
target after the final fault count toward 80. The default 256 selected-plan
safety cap can be extended with `--max-selected-plans` without resetting
progress. If the last eight effective trials add production probes or a
new semantic I/O family, the budget extends to 128 effective trials and ten
faults per sequence. A target assertion triggers a candidate review and is
not automatically called a new bug.

No old coarse trace, calibration, or selected plan is imported into V2.

## Node2 pilot and continuing campaign

The new node2 healthy runs each passed the unchanged original JUnit
(`ran=1, ignored=0, failures=0`) in 15.918 and 15.919 seconds. Their exact
`CoreContainer.reload` guard used `JETTY/node1` and the same logical
`c8n_1x1/shard1/core_node2` replica; their raw physical ports differed. There
are 63 stable, actor-bound, pretarget I/O selectors, including one actual
`core.properties` read under the receiving container's core root. See
`calibration-receipt.json` and the two `healthy-*` traces.

The first ten new fault plans were 10/10 strict and reached that guard after
the final fault on the same actor. Each original JUnit passed. They took
163.704 seconds, added 32 original production JaCoCo probes, and produced no
exact target assertion. These ten selected only ZooKeeper I/O. Their
per-trial trace and JaCoCo hashes are in `pilot10-summary.json`.

At the completed ten-run checkpoint, an audited scheduler migration rotated
the source preference across reload-context ZK, the core file read, and
collection ZK I/O. The migration retained all ten completed plans, 137 queued
plans, and the prior coverage set. The old state and scheduler SHA-256 values
were `bace774587e63abe36c4c37af6dca1f4886d1131dd7d3fe66f5dd26cdb07a0d0`
and `d6b7d9f39d0b512234e3521d6d7f03b184d6f8d0fc4cd51e4fea2043c276e263`;
the migrated state and scheduler hashes were
`4054f1181542cd99b9e017699348624d9bc935ff40e4db4b8c274ae7e7f07669`
and `f720d03f16ba1929214cf80c3dccf286218bdc914614591e658a54d600f3e456`.
The byte-for-byte backups and `migration.json` are under
`campaign/migrations/0001-file-family/`.

Trial 11 then strictly injected an `IOException` at the original
`CorePropertiesLocator.buildCoreDescriptor#L187` file read, with
`exactCoreRoot=true`, `JETTY/node1`, and the actual ZK client object recorded.
The same `core_node2` target guard ran later on that physical node and client;
the original JUnit passed in 15.114 seconds and no target assertion occurred.
Its plan, audit, trace, and coverage are mirrored under `file-pilot11/`.

The original checkpoint is now continuing toward 80 effective trials with at
most eight ordered faults in node2 tmux `solr21_actor_v2_80`. The node0 tmux
`solr21_actor_v2_mirror` updates this case's `result.json` from its atomic
progress receipt. Old coarse-selector trials stay in `legacy_coarse_actor` and
do not enter the V2 denominator.
