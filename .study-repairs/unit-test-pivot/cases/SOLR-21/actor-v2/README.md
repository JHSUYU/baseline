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
python3 smoke_transform.py
python3 smoke_actor_match.py
python3 run_healthy.py
python3 calibrate.py
python3 fuzz_v2.py --max-effective 80 --max-faults 8
```

Run these cluster JUnit steps only on a released node with the pristine Solr
source and classpath in `../independent/`; do not overlap another Solr campaign
on the same node. The checkpoint, raw traces, JaCoCo coverage, plans, and
per-trial elapsed times remain under this directory. A completed plan is not
repeated after resume. Only all-faults-matched trials reaching the exact
target after the final fault count toward 80. The default 256 selected-plan
safety cap can be extended with `--max-selected-plans` without resetting
progress. If the last eight effective trials add production probes or a
new semantic I/O family, the budget extends to 128 effective trials and ten
faults per sequence. A target assertion triggers a candidate review and is
not automatically called a new bug.

No old coarse trace, calibration, or selected plan is imported into V2.
