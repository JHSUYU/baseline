# SOLR-05 actor-aware V2 preparation

This independent, graph-free campaign uses the unchanged Solr 8.11.4
`AddReplicaTest.testAddMultipleReplicas`. The test's `@BeforeClass` creates a
three-Jetty `MiniSolrCloudCluster`, creates `testAddMultipleReplicas`, adds NRT,
TLOG and PULL replicas, deliberately expects a **different** capacity request
to fail, then adds more replicas using an explicit node set. Its workload and
assertions are not edited. The selected production guard is
`ZkController.register(String, CoreDescriptor, boolean, boolean, boolean)` at
the `replica == null` check following `waitForState` and a second cluster-state
lookup. The selected exception is `Error registering SolrCore, replica is
removed from clusterstate`; the capacity failure in the JUnit is not this
oracle. Source revision: `e27f44e3d78dfcec230c97e0a1240e3751daeff9`.

## Identity and fault contract

`ZkController` registers its actual `SolrZkClient` receiver, `ZkStateReader`
object and runtime node. The original `MiniSolrCloudCluster` supplies stable
Jetty instance roles `node1..node3` after startup. `ZkController.register`
pushes a thread-local context with collection, shard, core-node replica ID and
core name; its existing `finally` pops the context. Six `SolrZkClient` read and
write APIs pass their **real `this` receiver** to the probe. An observed I/O is
eligible only when the receiver matches the active registration context, the
Jetty role is bound, and the path is collection or control-plane I/O relevant
to `testAddMultipleReplicas`. The exact selector contains operation, full path,
per-actor/context ordinal, source callsite, Jetty role, collection, shard,
replica ID and core name. Java object identity is checked with `IdentityHashMap`
inside the JVM; logged identity hash values are within-run diagnostics. The
raw ledger also reconstructs register-context stacks by thread and rejects
ambiguous role/client registrations. No thread-name heuristic assigns actors.

A trial is effective only if **all faults apply in order**, the original guard
executes after the final fault, and that guard has the same runtime node,
client, reader, collection, shard, replica and core as an applied fault in the
same trial. The campaign separately records an observed guard on a different
identity as `target_lost_identity_mismatch`; it contributes neither coverage
feedback nor an effective count. This direct relation is conservative: a
cross-node effect without a source-backed relation is outside this campaign's
claim. A matching target exception is a candidate requiring clean replay and
source review, not automatically a new bug.

The prior 128-trial path/ordinal campaign remains historical under
`../evidence/campaign/` and `../result.json:legacy_coarse_actor`. None of its
trials, timing or coverage initializes this V2 campaign or changes the current
checklist status.

## Offline preparation and pending runtime

The following **offline** steps completed without starting a cluster:

```sh
python3 crashfuzz/cases/SOLR-05/actor-v2/probe/build.py
python3 crashfuzz/cases/SOLR-05/actor-v2/probe/smoke.py
python3 crashfuzz/cases/SOLR-05/actor-v2/probe/budget_smoke.py
```

`build.py` compiles the same original JUnit class into the clean and
instrumented classpaths and checks their SHA-256 byte identity. ASM verifies
six I/O hooks, the `ZkController` registration/context/guard hooks, and the
Jetty role hook. The no-cluster smoke runs two ordered `ConnectionLoss`
exceptions at the selected actor/replica while identical I/O on another node
and another replica of the same node remains unfaulted. Synthetic, internally
consistent raw ledgers show that a guard on the other node, another replica,
or a replacement client on the same node is excluded, even when the selector
faults themselves matched. The exact receipt is
`evidence/offline-smoke/receipt.json`.

When a cluster slot is assigned, `calibrate.py` will run two original healthy
JUnits and two actor-instrumented healthy JUnits in separate scratch
directories. Each must pass unskipped, reach the exact guard, bind three Jetty
roles and show same-replica collection I/O before the guard. `campaign.py`
then starts **only** from those two actor-aware healthy traces. Its durable
`evidence/campaign/state.json` and `SOLR-05` checkpoint mirror recover an
interrupted trial from fresh scratch without replaying completed trials.

The base budget is **80 effective strict post-final-target trials, at most
8 faults per sequence, and a 240-attempt cap**. At the 80th effective trial,
the last eight effective trials are inspected for a newly covered production
method, a higher per-method covered branch count, or a new stable
actor/operation/resource I/O family. If any is present, the goal becomes
128 effective trials, with at most 10 faults and 384 attempts. Attempt-cap or
queue exhaustion before the effective goal is recorded explicitly as under
budget. JaCoCo production probe and method/branch coverage guide mutation;
all completed trial traces, logs, coverage and times have case-local receipts.
No V2 cluster calibration, fault trial or new bug is claimed yet.
