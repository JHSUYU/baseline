# ZOOKEEPER-13 connect-path recovery stage

This package is staged for a later node0 dispatch. It has **not** run a new
ZooKeeper JVM or a new fault trial. `ReadOnlyModeTest#testConnectionEvents`
remains the unmodified three-peer JUnit selector. The exact selected site is
`ReadOnlyZooKeeperServer.validateSession` line 124, branch 1; the throw is
line 127. The first pilot had seven effective faults and zero target-retaining
fault trials. It did not establish a new bug.

## Why the healthy seed varies

The test initially creates a local session with an old `ZooKeeper` client.
It shuts down peer 2, then creates a new client and waits for read-only
connection. The new client's connect request has session ID zero and takes
`createSession`, bypassing `validateSession`. The still-live old client's
nonzero-session renewal can reach `validateSession` on read-only peer 1.
Scheduling of that renewal varies between independent starts. In
`stability-repeats/repeat2`, the exact target is reached and the client log
shows the old session connecting to peer 1 after read-only startup. In
`stability-repeats/repeat3` and `repeat4`, the JUnit passes after the new
session connects, but no exact target check occurs. The preserved assessment
counts three exact nonthrowing target visits in six healthy starts. A fixed
selector alone is therefore not a reproducible admission mechanism.

## Admission and full budget

`run.py` permits at most three **separate** healthy starts. Each start is a
new Mallory campaign output under `data/mallory/campaigns/ZOOKEEPER-13-connectpath-retry-full-v1/attempts/aNN`.
Mallory admits the first exact, named, nonthrowing healthy target visit and
immediately continues that same campaign into fault trials. A retry is allowed
only when JUnit passes, the healthy trace has no target check or throw, and
Mallory stops with `healthy_seed_invalid` before any fault trial. Every attempt
keeps its own checkpoint, raw trace, JUnit report, driver exit, and hash row
in `admission-ledger.json`. A test failure, class mismatch, identity gap,
other admission error, or interrupted campaign does not consume a silent
retry. An interrupted running checkpoint resumes in its original directory.

The admitted campaign has **80 fault trials**, **3600 campaign seconds**, and
**at most 3 faults per trial**. The separate limit of three healthy starts is
an admission retry cap. The wrapper acquires the same node0 lock as the
ZOOKEEPER-05 runner, so these JVMs cannot overlap. It checks a 6 GB disk
floor plus 300 MiB reserve before dispatch and stops a running process if
free space drops below the floor plus 150 MiB. A terminal full attempt gets
an offline causal audit. The wrapper records no reproduction or bug claim;
the later campaign's strict results and source review determine that.

## Dispatch handoff

Read-only validation, safe while another JVM lane is active:

```sh
python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-13-connectpath-retry-full-v1/run.py --preflight
```

When the node0 ZooKeeper lane is released, dispatch through the coordinator:

```sh
MALLORY_ZK13_NODE0_GO=1 python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-13-connectpath-retry-full-v1/run.py --run
```

The GO gate and node0 lock are intentional. This staging package does not
schedule itself or change the shared case checklist. The admission wrapper
does not make target retention likely: all seven previously effective pilot
faults lost the target. If all three independent healthy starts miss, its
terminal status is `healthy_retry_exhausted`, with zero new fault trials.

Inputs: `full.json` is derived from the previously attempted exact
connect-path campaign, with the local site map and 80/3600/3 budget.
`pins.json` hashes the config, site map, prior evidence, overlay receipt,
source, loaded target class, agent, and core-release manifest. Preflight
verifies those pins and Mallory's ZooKeeper overlay checks without a JVM.
