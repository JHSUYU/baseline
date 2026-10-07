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
The V3 bounded pilot has eight attempts, seven strict same-actor injections,
and five same-core target-retaining effective trials. None triggered the
selected target exception. The first two original JUnits failed their
asynchronous status assertion after the injected ZooKeeper connection loss;
the next six passed. `evidence/v3-pilot-review.md` records the source-level
chronology, coverage, times, and archived raw traces. The fault sequence budget is 80 effective
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

The V3 adapter additionally binds each ZooKeeper client to its actual Jetty
node and records file opens. Two homogeneous, unchanged original JUnit seeds
passed on node1 at 2026-10-07 05:55:36.060–05:55:53.603 UTC and
05:55:53.625–05:56:10.665 UTC, taking 17.413 and 16.963 seconds. Each
reached nine exact, nonthrowing target guards with zero sender/receiver,
descriptor, file, or actor audit issues. Each bound three Jetty ZooKeeper
clients; the seeds recorded 1,054 and 1,022 ZooKeeper I/O events, including
1,016 and 984 bound events. No external properties file was opened. The
`property.coreNodeName` override was absent for all nine cores in both
runs. The stable core-name intersection is nine of nine, but only two of nine
core-to-fixed-`JETTY_n` placements agree across seeds. This excludes fixed
Jetty roles from the high-quality fault queue.

The selected production `CoreContainer.create` method was executed in both
seeds, with 7/24 branches covered. The JaCoCo union covers 4,482 methods and
5,588 branches in executed Solr production classes, with zero unmatched
classes. `coverage_v2.py` records method/branch totals; `CoverageProbes.java`
and `coverage_probes_v3.py` provide stable production probe IDs for feedback.
The 36 stable sender-to-guard actor-relative I/O identities become 15
nonduplicate, two-seed stable one-fault selectors after requiring a preceding
CREATE sender and excluding overlapping owner/producer actor roles. They are
predominantly the producer's collection counter and Overseer queue accesses.
`seed_queue_v3.py` persists the exact selectors in
`evidence/v3-initial-queue.json`. It resolves `PRODUCER_OF_CORE:<coreName>`
at runtime from that same run's CREATE sender; no ephemeral port or fixed
Jetty position is carried across trials. The raw traces, JUnit outputs,
coverage, receipts, and queue are archived with per-file hashes in
`evidence/v3-healthy-raw.tar.gz` and
`evidence/v3-healthy-archive-manifest.json`. These healthy and intermediate
runs supply **zero V3 fault trials**; the separate two-round pilot begins the
new campaign. The earlier coarse actor campaign remains historical evidence
only. `campaign_v3.py` keeps a monotonic checkpoint and counts only ordered,
exact same-actor injections with a later target on the same core as effective.
It retains complete attempts with lost targets as attempts only and provides
an owner-set `STOP_AFTER_TRIAL` gate at a completed original JUnit boundary.
After the first two stable-selector pilot trials, the queue was expanded at
that complete boundary without replaying them. `expand_queue_v3.py` adds 49
one-seed actor-qualified selectors, each labeled exploratory, after excluding
six generated Overseer `qn-<sequence>` resource paths. Nine collection-state
selectors are placed before the remaining stable control-plane queue to
sample a distinct I/O family. An exploratory selector is attempted once; its
one-seed origin never counts as new I/O feedback or as a strict fault unless
the original JUnit reaches the exact runtime actor, operation, path, caller,
and occurrence. `evidence/v3-exploratory-queue-receipt.json` records the
migration. The campaign paused at the r002 boundary while HBASE-32's
timing-sensitive clean replay owned node1. It resumed from r003 and stopped
at r008 after five effective trials. Node1 was then released for HBASE-32's
five-effective completion window; the saved queue resumes from r009 when
that slot is free.
`calibrate_v3.py` runs the two unchanged JUnit seeds sequentially under one
tmux supervisor, saves a checkpoint after each seed, reuses an already
passing seed after a disconnect, and stops for review on a partial or failed
seed. Thus reconnection does not silently rerun completed cluster work.

For node1, use `/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4` as the
release source root (commit `e27f44e`). Keep every run's scratch, logs,
events, coverage and manifest under a unique `actor_v2/evidence/<seed>/`
directory. `run_v2.py` accepts `--source-root` and `--coverage`.
