# SOLR-06 actor-aware V2 campaign

This is a separate successor to the historical `independent/` 80-trial run.
Those coarse trials remain evidence but count as **zero V2 effective trials**.
The workload is the unchanged Solr 8.11.4
`TestPullReplica#testCreateDelete`, whose `@Repeat(iterations=2)` runs on the
original embedded two-Jetty cluster. The selected check is the original
`ZkController.register:1315` assertion:

```java
assert !(isLeader && replica.getType() == Type.PULL) : "Pull replica became leader!";
```

The runner uses `-ea` and `-Dtests.asserts=true`. The target hook additionally
rejects execution when `ZkController.class.desiredAssertionStatus()` is false.
Only the exact assertion's `AssertionError` is marked `TARGET_THROW`.

## Runtime identity and fault scope

An ASM agent hooks the original `ZkController` constructor after its
`zkClient` assignment. It binds the actual `SolrZkClient` object and
`ZkController` object to the controller's node name and `CoreContainer`
Solr-home role (`JETTY/node1` or `JETTY/node2`). Six original public
`SolrZkClient` operations record the exact receiver, production caller,
operation, znode path, and per-actor/site/path hit ordinal. Only I/O under
`/collections/pull_replica_test_create_delete/` from a uniquely bound Jetty
client can consume a `ConnectionLossException` plan step. Client/actor
ambiguity raises an error; unrelated and unbound clients are ineligible.

The assertion guard records the real `CoreDescriptor`, `Replica`, `ourUrl`,
`leaderUrl`, source controller, and SolrZkClient. Its target identity combines
collection, shard, and PULL core name. The leader URL must resolve through a
registered physical node to a stable `JETTY/nodeN/coreName` identity. The
guard is eligible only when the controller actor, PULL core URL, and leader
identity all resolve. Raw core-node name, replica name/type, URLs, node name,
and object identities stay in the trace. A fault run counts as effective only
if its exact planned I/O sequence applies and that **same** PULL core,
controller role, and leader identity reaches the guard after the last fault.

## Execution and budget

`python3 build_v2.py` compiles the unchanged JUnit and isolated agent, locking
source revision, original test class, release JARs, and graph-free classpath.
`python3 smoke_v2.py` transforms the untouched release classes offline,
checks all six I/O hooks and the original assertion literal/guard/throw
hooks, and rejects wrong actor, path, missing target, and unresolved leader.

After a cluster slot is assigned, `python3 calibrate_v2.py` runs **two fresh**
unfaulted original JUnits. Both must pass both repeat iterations with
assertions enabled. Calibration audits all bound I/O and guard events and
requires a shared exact PULL core/controller/leader target in the two runs.
Its receipt locks agent and runner hashes. No injection run starts if the
selected assertion is absent or its actor/leader cannot be resolved.

`python3 campaign_v2.py` starts or resumes the separate V2 campaign. Root
fault points must be observed before that same target in both healthy runs;
mutations add only actor-bound I/O exposed before the same target after an
earlier fault. JaCoCo production coverage and stable I/O families guide the
queue. The base budget is **80 effective trials, max 8 faults** with a 320
selected safety cap. Coverage or I/O novelty in the last eight effective
trials extends it to **128 effective, max 10 faults** with a 512 selected cap.
Each trial persists its fault plan, raw trace, JaCoCo data, original JUnit
log, elapsed time, target result, and atomic checkpoint. A target assertion
would be a candidate requiring source and replay review before a bug mark.

**Current state (2026-10-07 UTC):** two fresh assertion-enabled original JUnit
seeds passed. The bounded pilot completed 23 distinct selected trials, including
13 exact ordered injections and five runs in which the same physical
controller/PULL core/leader target executed after the final fault. There was
no selected `AssertionError`. The independent recount has zero issues; see
`pilot-audit-receipt.json` and its SHA-linked
`pilot-state-5-effective-23-selected.json`. The 23 fault runs took 936.847 s
and added 63 JaCoCo production probes and 19 actor-bound I/O families over the
healthy seeds. Long or target-lost runs did not contribute to coverage or
descendant generation.

At the completed pilot boundary, the checkpoint was promoted to the formal
80-effective/8-fault budget without repeating trials 1–23. Node2 tmux session
`solr06_actor_v2_full` resumes at trial 24. The live atomic checkpoint is
`campaign/state.json` on node2; the pilot checkpoint and audit are mirrored
here. A separate selected-attempt cap of 320 prevents endless unmatched
runs. The 128-effective/10-fault extension is decided only at 80 effective
trials from the last eight runs' coverage or actor-bound I/O novelty.
