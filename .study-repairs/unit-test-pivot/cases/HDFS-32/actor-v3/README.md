# HDFS-32 actor-bound V3

This recheck runs the **original** Hadoop 3.4.3
`TestDeleteBlockPool#testDeleteBlockPool` (two NameNodes, two DataNodes).
The selected check is the first `dn2.deleteBlockPool(bpid1, true)` call at
`TestDeleteBlockPool.java:109`, where `DataNode.java:3819` tests whether
`blockPoolManager.get(blockPoolId)` is still present. The original test
expects an `IOException` from that check, so the same exception in a faulted
run is a healthy outcome, not a new bug.

The old `independent/` 80-trial campaign has insufficient physical actor
identity on multi-actor I/O. Its raw data remain historical and do **not**
count toward V3's fault budget. V3 uses its own healthy seeds, plans,
checkpoint, raw traces, JUnit logs, JaCoCo data, and audit.

## Runtime identity and fault space

The case-local ASM overlay observes `MiniDFSCluster` startup, its ordered
`getDataNodes()` list, and `getNamesystem(0)`; `DataNode` registration and
UUID; `BPServiceActor`'s DataNode, block pool, nameservice, and NameNode
endpoint; `BlockPoolManager` membership; `FsDatasetImpl` object identity;
and `Client.getRpcResponse`'s actual remote endpoint. An eligible RPC fault
has the second DataNode object (`episode1/dn1`), its UUID, NN0's raw BPID,
`namesServerId1`, and an RPC peer equal to that actor's NameNode endpoint.
An eligible file fault has the same DataNode's mapped dataset object and an
`ExtendedBlock` with NN0's raw BPID. Plans select the marker, API, actor,
nameservice, ordinal, and exception type; an exact trial requires every
fault to apply in order on these runtime-bound I/O points. A trial is
**effective** only if the selected check executes on that *same UUID and
BPID* after the final fault.

RPC injections use `IOException`, `EOFException`, or
`SocketTimeoutException`; file injections use `IOException`. Production
JaCoCo probe, method, and branch counts plus stable actor-bound I/O families
guide sequence mutation. At 80 effective trials, novelty in the last eight
effective trials extends the goal to 128 and depth from 8 to 10; otherwise
it stops. The attempt cap is 320 initially and 512 if extended. Queue
exhaustion or a differing selected-check outcome is also a recorded stop.
A differing outcome is a **candidate** requiring replay and source review.

## Provenance and audit

The instrumented inputs are released Hadoop 3.4.3 JAR classes; the source
mapping is commit `9d50c6884666e794e45102260a4017bb31802e1b`.
`build/built.json` records each source, input-class, overlay, and probe SHA.
Every run manifest repeats that build and the original test/JAR hashes.
`campaign.py` writes `checkpoint.json` atomically after each completed
trial, preserving queue, seen IDs, active plan, metrics, and per-trial paths.
`audit_v3.py` independently recomputes exact/effective counts, physical
actor matches, target outcomes, feedback, source provenance, and raw hashes
from **all** completed runs. `launch.py` shares the global JVM start lock,
requires at least 10 GiB free disk, and permits a launch only with at most
four existing Java processes. The campaign can be resumed after process
interruption without repeating a completed trial.

The pilot and healthy calibrations are outside the V3 fault budget. The
campaign result is recorded in `../result.json` under `actor_v3`; the old
top-level counters are retained as historical evidence.
