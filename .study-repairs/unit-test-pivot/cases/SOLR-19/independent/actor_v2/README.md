# SOLR-19 actor-aware original-JUnit adapter

This directory is an isolated, graph-free source overlay for the unchanged
Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas` embedded cluster JUnit.
The selected check is `CoreContainer.create(String, Path, Map, boolean)`:
`cd.getCloudDescriptor().getCoreNodeName() == null` in non-legacy mode.
The unchanged test configures three Jetty nodes, creates one replica, adds
three, exercises a rejected overcapacity addition, then adds five using a
randomly selected explicit create-node set. The last step can change physical
core placement even with the same test seed; this is why a core name alone or
a fixed port cannot identify the faulting actor across trials.
The test does not supply `property.coreNodeName`; its `cloud-minimal/conf`
fixture has no `solrcore.properties`. Both override mechanisms remain in
production source, so their absence is verified per run rather than assumed
from this healthy fixture alone.
`build_v2.py` copies exactly seven release source files into `generated/`,
adds observation calls, and compiles them into case-local `classes/`.
`run_v2.py` puts those classes ahead of the original release jars and original
JUnit class in the classpath. No GraphChecker skeleton, static graph, Docker
workload, or hand-written test replaces the original JUnit.

## Runtime identity

* `CreateCollectionCmd` and `AddReplicaCmd` record the outgoing CoreAdmin
  CREATE request's core name, standard `coreNodeName`, any
  `property.coreNodeName`, all `property.*` values, target logical node name,
  base URL, and the producer's bound ZooKeeper-client role.
* `CoreAdminOperation` records the receiving `ZkController` node name and
  mapped create parameters. The per-core audit requires an exact sender to
  receiver node match and a base URL whose host, port, and context agree with
  that node name.
* `CoreDescriptor` records the parameter value before and after
  `loadExtraProperties`, the exact external properties path and existence,
  and an actual `FILE_OPEN` event if that file is read. `CoreContainer`
  records the exact guard value and branch outcome.
* `ZkController` binds its `SolrZkClient` object to the actual node name and a
  within-run startup-order `JETTY_n` label. Six `SolrZkClient` methods record operation,
  ZooKeeper path, first Solr caller, role, and ZooKeeper endpoint. I/O before
  this binding or from another client is marked `UNBOUND` and is ineligible
  for high-quality cross-run fault selectors. The `JETTY_n` label cannot be
  assumed stable across runs: the original test starts Jetty nodes in
  parallel and replica placement can move. A fault plan must either prove a
  stable role-specific I/O identity in two seeds or resolve its actor from a
  preceding sender event as `OWNER_OF_CORE(coreName)` within the same run.
  The raw node name is retained in each `ZK_BIND` receipt.

The request already carries a unique core name, so the adapter joins the
sender and receiver using that existing field and the real node name. It does
not add a communication header. With an empty `--faults` argument the hooks
only observe. Fault mode accepts ordered
`OP|PATH|CALLER|ACTOR|ORDINAL` selectors and throws a
`KeeperException.ConnectionLossException` at the precisely matched I/O.
`ACTOR` may be a calibrated `JETTY_n`, `OWNER_OF_CORE:<coreName>`, or
`PRODUCER_OF_CORE:<coreName>`; the latter two resolve against a preceding
CREATE sender event in the same run. Every matched/applied event is traced.
No fault has been injected in this V3 stage yet. The future fault sequence
budget is 80 effective
target-retaining trials with at most eight ordered faults, and an optional
128/max10 extension only if late new production coverage or stable I/O sites
justify it. A strict match without a later execution of the same target is
an attempt, not an effective trial.

`smoke_v2.py` exercises all three actor selector forms in a small JVM without
starting Solr. It verifies one exact match and one applied
`ConnectionLossException` per form after a wrong-actor event was ignored.
The original JUnit remains the sole workload for healthy and faulted trials.

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

A preliminary comparison of the two generic-client seeds finds 101 exact
operation/path/caller identities on `/collections/testAddMultipleReplicas`,
`/collections`, `/overseer`, and `/live_nodes` in both runs (117 in their
union). This is an offline candidate inventory, not actor-qualified evidence.
It includes collection `state.json` read/write, replica terms and leader
records, Overseer task queues, and live-node reads. The V3 gate must qualify
these sites with the bound producer or receiver actor before they enter a
fault queue.

The current adapter additionally binds each ZooKeeper client to its Jetty
actor and records actual file opens. Its two homogeneous final healthy seeds
are pending the node1 JVM timing gate. `audit_seeds.py` must report passing
original JUnit, nine exact target paths, zero lineage issues, stable core
selectors independent of ephemeral ports, and a nonempty intersection of
actor-qualified I/O identities before a fault campaign starts. If physical
placement changes, fixed `JETTY_n` selectors are excluded unless their own
identity is separately proven. The source
override's production JaCoCo baseline is summarized by `coverage_v2.py`.

For node1, use `/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4` as the
release source root (commit `e27f44e`). Keep every run's scratch, logs,
events, coverage and manifest under a unique `actor_v2/evidence/<seed>/`
directory. `run_v2.py` accepts `--source-root` and `--coverage`.
