# HDFS-28 alternate original-JUnit terminal audit

- Workload: unmodified Hadoop 3.4.3
  `TestPipelinesFailover#testLeaseRecoveryAfterFailover` (3 DataNodes).
- Target: `BlockRecoveryWorker.getDatanodeID(String)` site `#u12`, the
  `bpos == null` branch. An effective trial requires the complete fault
  sequence to match its physical DataNode and recovery-root identity, then
  the same actor/root to reach this target after the last fault.
- Two fresh healthy JUnit runs: 22.587 and 21.035 seconds. Both reached
  the nonfatal target check with the expected actor-bound I/O.
- Natural terminal checkpoint: 395 selected attempts, 121 exact full
  sequences, 80 effective target-retaining trials, 0 target-exception
  candidates. Fault JUnit time: 8099.802 seconds. The trial-395 decision
  was `effective_budget_met_pending_independent_audit`; active plan is null.
- The alternate ledger's last eight effective trials had no new
  target-related production method/branch coverage or stable actor-bound
  I/O family, so this ledger stopped at its own base goal 80 and max depth
  eight. It is separate from the shared HA JUnit ledger and its earlier
  conditional aggregate 128 review.
- Production JaCoCo gain over the two healthy seeds: 411 probes,
  54 methods, 199 branch-count entries. These are whole-workload values;
  they do not alone establish new target behavior.
- Independent `audit_campaign.py` re-read all 395 manifests, plans,
  runtime traces and JaCoCo evidence: 80 effective, 0 candidate, 0
  errors. Terminal checkpoint SHA-256:
  `4f68fb35d58aa13fae914affd842083b83ab7183f228a89e5c91cf7c14b6966e`;
  raw audit SHA-256:
  `72dbd5c0c66a09612b8dfe4d60ab2a7c1fed3f42eb89e953a8060e165e829a84`.

The node2 terminal archive contains 4,028 files totaling 3,435,280,878
uncompressed bytes, excluding only ephemeral scratch, Python cache, the
lock and archive outputs. The zstd archive is 204,219,722 bytes, SHA-256
`703bf087c8d72fcc94fe743cff9c0c723a254293c909a4db16685fabd74efa07`.
Its file manifest SHA-256 is
`1cb268d9bb6474f49988adbbc3e99e6a2521c7aa70d5f1b4d066be8726497a2a`.
Streaming extraction on both node2 and node0 verified all 4,029 tar
members (including the manifest) against their expected SHA and length,
without creating a second expanded raw copy. The expanded node2 evidence
remains intact. The node0 terminal checkpoint and raw-audit aliases are
separate from the older local 214-attempt checkpoint.
