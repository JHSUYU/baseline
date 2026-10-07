# SOLR-19 actor-aware original-JUnit adapter

This directory is an isolated, graph-free source overlay for the unchanged
Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas` embedded cluster JUnit.
The selected check is `CoreContainer.create(String, Path, Map, boolean)`:
`cd.getCloudDescriptor().getCoreNodeName() == null` in non-legacy mode.
`build_v2.py` copies exactly seven release source files into `generated/`,
adds observation calls, and compiles them into case-local `classes/`.
`run_v2.py` puts those classes ahead of the original release jars and original
JUnit class in the classpath. No GraphChecker skeleton, static graph, Docker
workload, or hand-written test replaces the original JUnit.

## Runtime identity

* `CreateCollectionCmd` and `AddReplicaCmd` record the outgoing CoreAdmin
  CREATE request's core name, standard `coreNodeName`, any
  `property.coreNodeName`, all `property.*` values, target logical node name,
  and base URL.
* `CoreAdminOperation` records the receiving `ZkController` node name and
  mapped create parameters. The per-core audit requires an exact sender to
  receiver node match and a base URL whose host, port, and context agree with
  that node name.
* `CoreDescriptor` records the parameter value before and after
  `loadExtraProperties`, the exact external properties path and existence,
  and an actual `FILE_OPEN` event if that file is read. `CoreContainer`
  records the exact guard value and branch outcome.
* `ZkController` binds its `SolrZkClient` object to the actual node name and a
  startup-order `JETTY_n` role. Six `SolrZkClient` methods record operation,
  ZooKeeper path, first Solr caller, role, and ZooKeeper endpoint. I/O before
  this binding or from another client is marked `UNBOUND` and is ineligible
  for high-quality cross-run fault selectors. The `JETTY_n` role is only
  usable after two healthy runs show stable core placement and role-specific
  I/O identities; the raw node name is retained in each `ZK_BIND` receipt.

The request already carries a unique core name, so the adapter joins the
sender and receiver using that existing field and the real node name. It does
not add a communication header. Instrumentation is observational; this stage
has not injected faults. The future fault sequence budget is 80 effective
target-retaining trials with at most eight ordered faults, and an optional
128/max10 extension only if late new production coverage or stable I/O sites
justify it. A strict match without a later execution of the same target is
an attempt, not an effective trial.

## Calibration state

The first `healthy-a` pilot had no ZooKeeper I/O hook: original JUnit passed
in 19.279 seconds; nine core CREATE senders, receivers, descriptor and file
states, and nonthrowing exact guards joined with zero audit issues. The next
`seed-a` and `seed-b` runs added six ZooKeeper I/O hooks but labeled all
clients generically. They passed in 16.568 and 20.550 seconds. Both joined
all nine cores with zero issues; 1,044 and 1,127 ZooKeeper events were
recorded, with 70 callsites each. These three runs are intermediate
calibration only and supply **zero fault trials**. Their events and JaCoCo
files are retained under `evidence/`.

The current adapter additionally binds each ZooKeeper client to its Jetty
actor and records actual file opens. Its two homogeneous final healthy seeds
are pending the node1 JVM timing gate. `audit_seeds.py` must report passing
original JUnit, nine exact target paths, zero lineage issues, stable
role-specific core selectors, and a nonempty intersection of bound
role-specific I/O identities before a fault campaign starts. The source
override's production JaCoCo baseline is summarized by `coverage_v2.py`.

For node1, use `/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4` as the
release source root (commit `e27f44e`). Keep every run's scratch, logs,
events, coverage and manifest under a unique `actor_v2/evidence/<seed>/`
directory. `run_v2.py` accepts `--source-root` and `--coverage`.
