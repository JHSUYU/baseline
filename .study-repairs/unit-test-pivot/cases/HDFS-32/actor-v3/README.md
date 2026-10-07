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
`SocketTimeoutException`; file injections use `IOException`. Stable
actor-bound I/O families guide sequence mutation and queue priority.
Production JaCoCo probe, method, and branch-count feedback is recorded
per effective trial and controls the conditional budget extension. The
versioned `coverage_successor.py` additionally gives later queued plans a
bounded priority boost when their parent trial gained production coverage.
Its handoff preserves the completed ledger, queue, seen IDs, and any reserved
but unstarted active plan; `quiesce.py` freezes only the Python controller
while it waits for the shared start lock, and verifies that no JUnit has
started before stopping it. The handoff receipt records the old and new
controller SHA and unchanged ledger/queue/seen counts. At 80 effective
trials, novelty in the last eight effective trials extends the goal to 128
and depth from 8 to 10; otherwise
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
from **all** completed runs. At a stable checkpoint, `raw_inventory.py`
additionally hashes every retained healthy, pilot, and completed-trial
artifact, including JUnit logs and JaCoCo binary data, and binds the
inventory to the matching semantic audit and checkpoint SHA. `launch.py` shares the global JVM start lock,
requires at least 10 GiB free disk, and permits a launch only with at most
four existing Java processes. The campaign can be resumed after process
interruption without repeating a completed trial.

The pilot and healthy calibrations are outside the V3 fault budget. The
campaign result is recorded in `../result.json` under `actor_v3`; the old
top-level counters are retained as historical evidence.

The first controller completed 17 strict, effective trials. It was stopped
with trial 18 reserved but unstarted; `quiescent-stop-receipt.json` records
that boundary. The coverage successor independently audited all 17 raw
trials before its handoff, retained the reserved trial and every queue/seen
entry, and wrote `coverage-handoff-receipt.json`. The scheduling change
therefore begins **after** reserved trial 18; earlier trials retain their
original recorded policy and outcome.

## Final result

The extended campaign naturally stopped after 152 selected attempts: 135
exact actor-bound injections and 128 effective same-UUID/BPID, postfault
selected checks. No run changed the healthy selected-check outcome. The
independent semantic audit found zero errors and zero candidates. The
terminal receipt records 5,199.257 seconds of original JUnit time, including
both healthy runs and all fault trials. The production coverage union gained
1,812 probes, 339 methods, and 821 branch-count entries over the healthy
baseline; this is global feedback, not a claim that every gain lies on the
selected check's path.

The all-raw inventory verifies 1,519 retained files totaling 1,196,308,651
bytes. Seven 180-second JUnit timeout trials have zero-byte JaCoCo data and
no coverage text output under the original runner's semantics; they are
recorded as coverage unavailable and contributed neither an effective check
nor new coverage/I/O feedback. See `coverage-unavailable-review.md`.
`archive/raw-v3-archive-receipt.json` records a 71,093,287-byte archive of
those files, with full extraction and per-file SHA verification. The archive
SHA-256 is `fa7c71054b66dcc9dfdae0652f0d23956f2faea4f081496a7705bb3cc9a37679`.

After the terminal audit, a separate node2 storage pass reopened that archive
and verified all 1,519 extracted files against the full raw inventory. It
also verified the byte-identical node0 archive mirror and each expanded file
selected for pruning. Only 592 derivable coverage text files (1,132,869,722
bytes) were removed from node2's expanded copy; 927 other files, including
every JUnit log, runtime trace, JaCoCo binary, manifest, and fault plan,
remain expanded. The full raw archive remains on both node0 and node2.
`archive/coverage-prune-intent.json` and
`archive/coverage-prune-receipt.json` contain the exact inventory paths,
source hashes, mirror proof, and an idempotent recovery boundary. Restoring
the archive reconstructs all 1,519 files for future audits.
