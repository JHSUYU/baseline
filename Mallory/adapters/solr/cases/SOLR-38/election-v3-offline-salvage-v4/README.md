# SOLR-38 sealed v3 offline correction

This directory rechecks the immutable node1 v3 campaign. It does not run a
cluster or change the original archive, trial results, or checklist.

```sh
python3 audit.py
python3 -m unittest -v test_offline.py
```

The audit pins archive SHA-256
`19440785b619ef7d80f0105ef86359767f35c674728421d875a0d9e3ffc4f455`
and checks each extracted member against the published member manifest. It
also runs the v3 package preflight and validates the Solr source and adapter
hashes used by the source-backed field witness.

The original audit's `same_actor_target_after_fault=false` was produced by a
helper that only admits `local_timeline_evidence` doors. This campaign uses
strict graph paths and disables local timeline admission. The v3 custom
acceptance flag also reads `target_check_reached`, which is absent in its
pinned feedback schema, so it is always false. Neither flag establishes that
the target was lost. The v3 r0001 closure edge fingerprint mismatch arose
because the graph contained a sampled candidate and a source-backed observed
state edge with identical producer and consumer event IDs. The pinned backward
walk sorted only those IDs, allowing Python set iteration to choose either
edge. `CanonicalSolr38Graph` removes only that exact duplicate candidate.

The corrected receipt proves two postfault paths on the fault actor:

| Trial | Actor | CloudDescriptor | Applied fault | Setter value write | Getter value read | Target check |
| --- | --- | --- | --- | --- | --- | --- |
| r0001 | node2, epoch 0, thread 178 | o24 | seq 1317 | seq 1525 | seq 2813 | seq 2818 |
| r0002 | node1, epoch 0 | o37 | seq 2200 | seq 2379 | seq 3782 | seq 3787 |

The `CloudDescriptor` object ID is interpreted within its node and epoch.
The election door and target check occur in different method occurrences;
the proven link is the same object's last setter write and getter return,
with no intervening native write. The source-backed graph contains an observed
door-to-write program-order edge and an observed write-to-read state edge.
The target check follows the read in the target method occurrence. The exact
`ConnectionLossException` injected at the ZooKeeper `getChildren` call is
caught by `waitForReplicasToComeUp`; the method retries and later sets the
leader flag. The target branch falls through in both trials. No exact target
exception or new bug was observed.

The configured campaign naturally exhausted its queue after testing both
healthy eligible typed points. It used two of four allowed fault trials. The
receipt therefore marks this check eligible for a completed table row, with
the exact budget and zero-exception result visible. Only dispatch updates the
canonical checklist. The original v3 audit remains preserved as evidence of
the gate defect.
