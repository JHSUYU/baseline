# ZooKeeper 3.8.7 MiniCluster adapter

`install.py` applies small source hooks to an **isolated** ZooKeeper 3.8.7
checkout. It checks each source anchor and can be rerun. The source patch is
generated from this directory; the original ZooKeeper checkout is untouched.

```sh
python3 Mallory/adapters/zookeeper/install.py /path/to/isolated/zookeeper
```

After compiling that isolated source, generate the dispatch overlay receipt:

```sh
mvn -pl zookeeper-server -am -DskipTests test-compile
python3 Mallory/adapters/zookeeper/make_overlay_receipt.py \
  /path/to/pristine/zookeeper /path/to/isolated/zookeeper
```

The generated patch and receipt are `zookeeper-3.8.7-mallory.patch` and
`zookeeper-3.8.7-overlay.json` in this directory. The receipt records the
base commit, exact modified-source and selected-test hashes, compiled class
hashes, the Surefire agent property, and a generic JUnit selector command.
The source and receipt must both be staged on the execution host before a
case config uses `source_overlay_receipt`. A running campaign stays pinned to
the source and agent bytes with which it started.

The hooks assign `zk<sid>` at `QuorumPeer.run`, follower, leader, observer, and
observer-master entries. They also bind `SessionTrackerImpl.checkSession` and `setOwner` to the
constructor's server ID, which matters because quorum members share the test
JVM. The selected check still needs a `nodeBindings` entry in its site file so
the agent enters its region under that identity **before** the first bytecode
instruction of the method. For Follower and Learner, use the inherited numeric
`malloryServerId()` getter; Leader and ObserverMaster have the same getter.
For QuorumPeer use `getMyId()`, for ZooKeeperServer and ReadOnlyZooKeeperServer
use `getServerId()`, and for SessionTrackerImpl use the `malloryServerId` field.

`RequestThrottler` and `PrepRequestProcessor` emit `TASK_SUBMIT` immediately
before their queue adds and `TASK_CLAIM` around the next processor call after
dequeue. A unique token is associated with the actual `Request` object and
queue occurrence. This gives the target region a request context across both
processing-thread handoffs; an absent token is left as a lost handoff instead
of being inferred from timing.

The learner and leader handler construct tracing variants of their Jute
archives. Each completed `QuorumPacket` write/read emits `SEND`/`RECV` with a
correlation built from the actual TCP connection, direction, stream packet
ordinal, packet type, and zxid. It also offers `beforeDoor` at the packet
boundary for an `IOException` fault. A packet I/O that throws is not reported
as sent or received. The helper calls the Mallory Probe reflectively, so the
ZooKeeper source can compile without depending on the agent jar. These hooks
cover the learner/leader archive connections; they do not establish a direct
request-to-packet value edge or reconstruct Jute field-level provenance.

ZooKeeper's Surefire configuration supplies its own JMockit `argLine`, so the
installer adds an empty-by-default `mallory.agent.arg` property to that line.
For `ZOOKEEPER-01`, prepare an exact target config from the **patched** source
lines, then run the generated `command.json`:

```sh
python3 Mallory/adapters/zookeeper/prepare_zk01.py \
  /path/to/isolated/zookeeper /path/to/mallory-agent.jar /path/to/trial
python3 Mallory/adapters/zookeeper/run_prepared.py /path/to/trial/command.json
```

The prepared command invokes
`SessionUpgradeQuorumTest#testCloseSessionWhileUpgradeOnLeader`. Its generated
`sites.json` covers the `session.isClosing()` guard and the corresponding
`SessionExpiredException` throw, plus a node binding on `malloryServerId`.
`events.jsonl` and `catalog.jsonl` must exist before treating the JUnit result
as Mallory evidence. A passing JUnit without an observed `TARGET_CHECK` at a
named node is only a workload execution, not a calibrated check.

`prepare_session_candidate.py` prepares a combined healthy probe for
ZOOKEEPER-02 and ZOOKEEPER-03 using the three-peer
`QuorumTest#testMultiToFollower` workload. `prepare_zk13_alternate.py` prepares
read-only-mode candidates for ZOOKEEPER-13. Each produces the same
`sites.json`, `agent.properties`, and `command.json` contract for
`run_prepared.py`. Only a real run with an exact target catalog, named node,
and no healthy target throw establishes a usable seed; the ZOOKEEPER-13
alternatives remain uncalibrated.

The combined ZOOKEEPER-02/03 JUnit evidence is retained in the shared
calibration directory and copied into each case's `healthy-alternate/`
directory with a case-specific audit. These are healthy probes, not independent
core campaign results; they do not create a per-case `result.json` or mark a
check completed in the final table.

For concurrent work on node2, `install_lane2.py` creates a second isolated
source overlay. Its Surefire fork uses ZooKeeper `PortAssignment` partition
8/8 (ports 30072–32764), and `mallory.test.dir` supplies a separate
`build.test.dir` for each trial. The default data directory is under the
lane2 source root; the campaign command overrides it with
`-Dmallory.test.dir={trial_dir}/test-data`. `compile_lane2.sh` compiles under
the lane lock; `make_lane2_receipt.py` checks that the patch applies to the
pristine source and hashes all selected sources and compiled classes.

The bounded lane2 `QuorumTest#testMultiToFollower` proof passed one JUnit
test in 21.521 seconds while Solr ran in a separate source lane. Surefire
recorded fork 8/8 and `PortAssignment` allocated ports 30073–30098. The
exact ZOOKEEPER-02 guard was observed three times on `zk2`; both selected
ZOOKEEPER-03 guard branches were observed once on `zk2`, with no target
throw. Per-case raw events, catalogs, compiled class, source, Surefire
reports, and audit receipts are under
`data/mallory/calibration/ZOOKEEPER-02/healthy-lane2/` and the corresponding
ZOOKEEPER-03 path. These remain calibration evidence until their own core
fault campaigns complete.

For a core campaign on this source tree, use `agent_transport` set to
`surefire_argline` and `agent_arg_property` set to `mallory.agent.arg`. The
`campaign_zk01.json` configuration is an executable node2 example with 80
fault trials, a two-hour cap, and at most ten faults per sequence. Its absolute
paths must be changed for another host. The first isolated three-run smoke
campaign is under `data/mallory/calibration/ZOOKEEPER-01`; the terminal
80-trial result and its separate post-hoc class/source attestation are under
`data/mallory/cases/ZOOKEEPER-01`.

## Epoch-fixed ZOOKEEPER-02 follow-up

The first lane2 ZOOKEEPER-02 campaign is retained as provenance-limited
evidence. Its target region entered under `zk2` epoch 0 while the request
handoff and check used epoch 1. The healthy target closure consequently has
no observed pretarget I/O path; merely injecting and retaining the target
cannot qualify that run as closure-guided testing.

`install_epoch_fix.py` applies a separate patch after `install_lane2.py` to
an isolated pristine ZooKeeper copy. It registers the actual
`SessionTrackerImpl` receiver with the peer lifecycle epoch before the agent
enters the region, and scopes each parsed client packet through the request
queue handoffs. The client I/O door is `zookeeper.client.request.read`. A
receipt from `make_epochfix_receipt.py` pins the combined patch, source,
Surefire property, and compiled classes. The older lane2 source is not
modified by this follow-up.

The fresh `QuorumTest#testMultiToFollower` healthy run must pass
`attest_epochfix_healthy.py` before generating a fault campaign. That audit
requires matching target region/check node and epoch, a unique loaded target
class, an actual client read door, and observed `task` and `region_parent`
edges from that door into the check. `prepare_epochfix_campaign.py` refuses
an unproved seed and writes a separate short or full config pinned to its
class/source/agent hashes. The campaign still runs its own healthy seed and
must pass the core runtime and offline closure gates. Quorum packet hooks in
this overlay can see traffic from two ensembles with overlapping peer IDs;
an unscoped quorum RPC edge alone is not proof of the selected request path.

When the selected operation enters leader-side `PrepRequestProcessor` from a
follower, `install_request_path.py` adds two more explicit handoffs in a third
isolated overlay. It carries the actual `Request` object through
`FollowerRequestProcessor`, observes the physical quorum `REQUEST` packet
with its TCP direction and ordinal plus a SHA-256 of its bytes, and retains
that same deserialized packet object until `LearnerHandler` submits it to the
leader queue. `Probe.withCausalContext` scopes that exact receive correlation
without emitting another receive event. The leader request region then has
the prior receive as its unique parent. The receipt is
`zookeeper-3.8.7-requestpath-lane2-overlay.json`; its companion patch can be
applied to pristine 3.8.7 source and reversed from the isolated overlay.
For this overlay, the healthy attestor additionally requires the observed
quorum `REQUEST` RPC edge, with the same correlation and request digest at
both ends, directly followed by the leader request region parent edge.

The request-correlated `QuorumTest#testMultiToFollower` healthy run passed its
single JUnit test in 18.467 seconds. It observed the ZOOKEEPER-02 guard three
times on `zk2` epoch 1 with no target throw. The archived witness contains a
client I/O door on `zk1`, two request queue handoffs, one exact quorum
`REQUEST` RPC from `zk1` to `zk2`, a leader request region, the leader prep
queue handoff, and the target region. Its source/class snapshot, event trace,
loaded site catalog, and port proof are under
`data/mallory/calibration/ZOOKEEPER-02/healthy-requestpath/`. A separate
8-fault pilot applied all eight planned faults, retained the target in six,
and passed the offline causal-quality audit; its raw archive is under
`data/mallory/calibration/ZOOKEEPER-02/requestpath-short/`. These calibration
artifacts do not stand in for the full-budget result.

The ZOOKEEPER-02 80-fault request-path campaign later completed with all 80
fault plans strictly applied and 74 runs still reaching the target. No exact
`SessionMovedException` occurred. The independent 81-trial causal audit
verified the archive, applied fault identity, target claims, graph guidance,
and 29 healthy observed-path doors. Its unchanged result and full raw archive
are under `data/mallory/cases/ZOOKEEPER-02/`; the older epoch-mismatched run
remains separately labeled provenance-limited under calibration.

## Connect-request path for ZOOKEEPER-03

The first request-path healthy run reached both `SessionTrackerImpl.setOwner`
guard branches during **session creation**, before any ordinary client
operation could reach `zookeeper.client.request.read`. The exact REQUEST RPC
and task handoffs were already visible, but no observed client I/O door led
into the target; that seed was not promoted.

`install_connect_path.py` adds a `zookeeper.client.connect.read` door and a
scoped `ConnectRequest` correlation in a fourth, separate source overlay.
The scope starts after deserializing the connect packet and ends after
`createSession` or `validateSession`, preserving the client input across the
existing queue hooks. `make_connectpath_receipt.py` pins the combined patch,
source files, and compiled bytes against pristine 3.8.7. The request-path
overlay and earlier campaign outputs are left untouched.

With this overlay, `QuorumTest#testMultiToFollower` passed in 21.831 seconds,
reached both exact `setOwner` guard branches on `zk2` epoch 1 without the
selected throw, and proved an entirely observed connect-door → task →
physical REQUEST RPC → leader task → target path. The witness checks the
packet's send/receive correlation and byte digest on the two named peers.
Evidence is under `data/mallory/calibration/ZOOKEEPER-03/healthy-connectpath/`.
The separate eight-fault pilot applied every fault, retained the target in
every trial, and passed the independent nine-trial causal audit under
`data/mallory/calibration/ZOOKEEPER-03/connectpath-short/`. Its pinned
80-fault campaign is running under a new output path and must receive its
own terminal audit before the checklist marks ZOOKEEPER-03 complete.
