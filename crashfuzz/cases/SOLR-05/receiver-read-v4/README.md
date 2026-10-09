# SOLR-05 receiver state-read V4

This stage uses the unchanged Solr 8.11.4 `AddReplicaTest.testAddMultipleReplicas`
and its embedded three-node `MiniSolrCloudCluster`. The selected check is
`ZkController.register`'s `replica == null` guard. The source tree is pinned at
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`, and `build-receipt.json`
records equal SHA-256 values for the clean and instrumented original JUnit
class. The prior writer-stage 18 attempts and 9 effective trials are excluded
from this checkpoint.

The original test creates a one-shard collection with one NRT replica, adds
one NRT, one TLOG and one PULL replica, checks that an over-capacity add fails,
then explicitly selects two nodes and adds five more replicas. Its final
cluster state contains nine replicas. The campaign runs this entire JUnit
method unchanged on every trial; the selected exception remains the oracle.

## Physical I/O and runtime identity

`ZkStateWriter.writePendingUpdates` first records a newly added replica's
collection, shard, replica ID, core, and intended node. Its successful
`setData(state.json)` response supplies the actual `Stat.getVersion()`.
`ZkStateReader.fetchCollectionState` on the intended receiving node performs
the real `SolrZkClient.getData` and parses its returned data. The V4 hook then
checks that the read `Stat` has that exact version and the parsed collection
contains the same replica, core and node. It also verifies the concrete
receiver `SolrZkClient`/`ZkStateReader` objects and physical Jetty role.
`evidence/hook-order-audit.json` verifies the generated source places the
read hook after the real `getData` and state parse, the writer hook after
`setData` returns, and the selected hook immediately before the original
guard. Only this uniquely bound read-response point may throw
`KeeperException.ConnectionLossException`. The probe never infers a receiver
from its callback thread name or a shared path alone.

A trial is effective only when the planned fault sequence matches and applies
in order and the original guard subsequently executes for the final fault's
same replica, core, node, client and reader. A missing target after fault is
retained as a raw attempt but contributes no effective count or coverage
feedback. A selected exception is a candidate until an isolated original
JUnit replay and source/known-issue review establish its meaning.

## Healthy proof and budget

Two fresh clean JUnits and two fresh instrumented JUnits all passed. In each
instrumented run, all nine target replicas had a version-linked successful
write, real receiver read and later same-replica guard. The independent
reconstruction and raw hashes are in `evidence/healthy-audit.json`.
`probe/audit_v4.py` reconstructs writer/read/guard identity directly from
the raw trace and checks each planned injection. The strict pilot in
`evidence/pilot-001` is V4 trial 1; old stages are never imported.

The base budget is 80 effective target-retaining trials with at most eight
ordered faults and an initial cap of 320 attempts. New production method,
covered-branch count, or relevant I/O family in the last eight effective
trials extends to 128 effective, ten faults, and 512 attempts. Exhausting
the queue or attempt cap before the effective goal is reported separately.
The persistent queue and per-trial times live in
`evidence/campaign-v4/checkpoint.json`; each run retains its original JUnit
log, complete JVM event trace, JaCoCo data, manifest and audit receipt.

The node0 campaign runs in tmux `solr05_receiver_v4`. Every JVM launch uses
the shared `jvm-start.lock`, checks fewer than five Java processes, and
requires at least 3 GiB of free disk. The threshold was raised after trial 4
while trial 5 was active; `evidence/campaign-v4/disk-gate-migration.json`
records the exact boundary. A separate tmux `solr05_v4_mirror` copies code,
checkpoint and complete raw files to node2 every two minutes, excluding
recreatable classes and scratch files.

To inspect or resume after interruption:

```bash
python3 probe/campaign_v4.py
tmux new-session -d -s solr05_receiver_v4 \
  'cd /users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-05/receiver-read-v4 && python3 -u probe/campaign_v4.py --run --wall-seconds 43200 > evidence/campaign-v4/full.log 2>&1'
```

Do not start a second campaign if the first tmux session or its Python PID is
still live. A resumed inflight trial starts in fresh scratch; completed rows
are never rerun.

## Final result

The campaign reached its extended budget on 2026-10-07: 182 unique attempted
sequences, 145 fully applied sequences, and 128 sequences whose final fault
was followed by the same replica's selected guard. Seventeen fully applied
sequences lost that guard and were excluded from effective coverage feedback.
The longest fully applied sequence had seven faults. The cumulative feedback
over the two healthy calibrations gained 210 production coverage units, 21
methods, 79 covered branch counts, and one relevant I/O family. Trial time
summed to 5,052.027 seconds; the four initial calibrations took another
61.478 seconds.

There were zero selected-guard exception candidates, so this stage makes no
new-bug claim. The independent audit in
`evidence/campaign-v4/independent-raw-audit.json` reconstructed all 182
attempts from original traces and JaCoCo files with zero errors. The node2
mirror verification compared 930 completed raw artifact files by SHA-256 with
zero mismatches. Checkpoint snapshots before the three observed-trace queue
expansions are retained; they added 15, 13, and four previously untried
selectors. No completed trial was rerun or imported from the old stages.
