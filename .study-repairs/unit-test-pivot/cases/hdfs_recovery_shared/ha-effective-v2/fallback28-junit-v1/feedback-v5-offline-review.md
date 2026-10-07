# HDFS-28 alternate V5 feedback order (offline only)

The original `TestPipelinesFailover#testLeaseRecoveryAfterFailover` V4
controller remains live on node2. This document and
`feedback_priority_v5.py` do **not** activate V5 or change the live
checkpoint. The trial evaluator, actor/recovery-root matching, queue,
seen IDs, completed ledger, active reservation, 4:1 RPC/FILE lane schedule,
and attempt cap 512 remain those of V4.

## Why consider a different order

At V4 attempt 312, the most recent 12 trials had 1 exact and 1 effective
run; the most recent 24 had 7 exact and 7 effective runs. The recent misses
clustered in dn2 HADOOP_IPC depth-one EOF/SocketTimeout (3/0/0 each) and
dn2 local FILE IOException (2/0/0). Across all 98 V4 attempts through that
snapshot, 21 were exact and 20 effective. Depth-two RPC/IPC plans have
produced effective runs, while the remaining queue includes 48 remote FILE
singletons and 12 local FILE IOException singletons. The low-yield streak
does not justify removing any queued family.

V5 keeps the fixed lane schedule. Within the selected lane it ranks an
untried depth-two descendant of an exact, target-retaining parent first,
then its bounded retry, then deeper retained-parent plans, then untried
plans. Existing target-related coverage and stable same-actor I/O gains,
global coverage/I/O gains, and smoothed exact-and-target retention of the
same marker/depth/physical owner only break ties. The original base chooser
breaks any remaining tie. This uses feedback already in the ledger and
discards no ID. The sample rate never overrides the depth/parent tier.

## Frozen offline dry-run

- V4 policy source SHA-256: `d45c88f9473ac19b28191c175f664a03f5c6a78124e3d412892bb023716ab61a`.
- V5 policy source SHA-256: `998043d74abc980b42eb122a1c3934c095444046b5a3c3cd2bbb1b41d82fc5f2`.
- Node2 checkpoint snapshot SHA-256:
  `2b175c58629a74433de5cd5f38bfc4e53e1df1339f9cd6d59fad427de51e5818`.
- Snapshot: 322 completed, 63 effective, 82 queued, 238 seen, active
  reservation present, cap 512. This is **not** an activation boundary.
- Ordered queue-ID SHA-256: `d1311d658f69300583b22b6c3f0f34b40a26fb9085acf1969198e1235754483d`;
  seen-ID SHA-256: `b180e4de2b3ea890534b90e98690b8f5fb6f3cf9da67b162bbf02c23e059b706`;
  completed-ID SHA-256: `2c64b1cb62fd708e0a6463ab34e437d3645b05a5d679bb19eba001f45ddccc92`.
- Deterministic preview changed only the hypothetical next ID:
  V4 `c0796221669055aafaa0f66b` to V5
  `ac843d70976a53605c075bcb` (depth-two HADOOP_IPC). The
  4:1 lane, maximal rank, and no-state-mutation assertions passed.

## Activation gate

Do not stop or hot-edit the live V4 controller/JUnit to activate this
policy. A first V5 handoff is allowed only after V4 has naturally exited
and released `campaign.lock`, with `active=null`, no next trial plan,
driver, trace or case JVM, and a full independent raw audit with zero
errors and a matching checkpoint SHA. The source SHA is pinned above.
The V5 handoff writes an atomic receipt but leaves the checkpoint bytes
unchanged. Existing V5 restarts can resume a previously reserved active
plan under the same lock. The 10 GiB free-space and shared Java-start
gates still apply to each JUnit. If these conditions cannot be proven,
continue V4; the fixed cap and queue remain the terminal limits.
