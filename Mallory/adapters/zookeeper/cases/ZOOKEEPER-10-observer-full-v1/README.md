# ZOOKEEPER-10 observer full stage

This case-local package stages a fresh, unmodified
`ObserverMasterTest#testObserver` healthy seed and, only if that seed passes
Mallory's exact target and runtime attestation gate, a full **80 fault trials /
3600 second / at most 3 faults per trial** campaign. Both existing JUnit
parameter values run; the `true` value enables ObserverMaster. The selected
check is `ObserverMaster.removeProposedPacket(long)@368:branch:3` and the
selected throw is `@374:throw:1` in the pinned overlay.

The prior healthy run passed 2/2 JUnit cases, observed seven nonthrowing exact
checks on named `zk1`, and proved 13 physical quorum archive I/O doors on
observed, time-ordered paths to the target. The frozen receipt is
`data/mallory/admissions/ZOOKEEPER-10-fa5f-observer-v1-healthy.json`. It is
guidance for a **fresh** healthy seed, not a substitute for one.

The source review at
`data/mallory/admissions/ZOOKEEPER-10-fa5f-observer-v1-fault-model-gap.json`
found no demonstrated `IOException` that selectively skips a proposal queue
update while allowing the same ObserverMaster check to continue. Faults may
therefore lose the target. This full attempt records exact fault application,
postfault target retention, and offline observed graph-path quality as its
outcome. A selected throw is a candidate for separate source review, not an
automatic bug finding. No prior fault pilot was run for this selector.

The full config uses the immutable event-time core release
`fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f`,
sets `reject_coarse_roots` and `require_event_time_paths`, and disables local
timeline admission. The no-JVM preflight verifies source/compiled/agent/core
pins, selected JUnit and target, prior healthy graph-path evidence, and the
full budget. The runner uses the same node0 lock as ZK05/ZK13, a 6 GB disk
floor plus 300 MiB admission reserve, and a 150 MiB running headroom stop.

Read-only preflight, safe while another ZooKeeper JVM campaign is active:

```sh
python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-observer-full-v1/run.py --preflight
```

After dispatch releases the node0 ZooKeeper lane and confirms free disk:

```sh
MALLORY_ZK10_NODE0_GO=1 python3 Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-observer-full-v1/run.py --run
```

The runner never starts on its own. A running checkpoint may be resumed with
the same command; a terminal checkpoint is preserved. Output goes to
`data/mallory/campaigns/ZOOKEEPER-10-observer-full-v1/`, including raw trial
receipts, JUnit reports, driver exit, offline causal audit, and a collection
receipt. This package has not launched a JVM or a fault trial.
