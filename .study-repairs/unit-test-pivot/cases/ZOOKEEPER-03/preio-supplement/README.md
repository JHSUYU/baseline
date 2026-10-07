# ZOOKEEPER-03 pre-I/O checkpoint supplement

This stage tests the 63 ordered fault plans left in the original pre-I/O
`QuorumTest#testSessionMoved` checkpoint after its 480-attempt cap. It does not
replay any of the 480 completed plans. The original result remains 37/80
effective; this supplement has its own 63-plan denominator and does not alter
the post-response or MultiOp stages.

`prepare.py` derives the fixed `plan-manifest.json` from the archived atomic
checkpoint and raw parent trials. The 63 plans are unique, depths 2–5, and
each extends an effective parent with an observed actor-bound I/O selector
before a later same-session `SessionTrackerImpl#setOwner` guard **in the parent
trace**. A fault may change that future path. The current trial only counts as
effective when its raw trace proves every planned exception applied in order
and the selected leader/raw-session/owner target was reached after the final
fault. `receipt_validator.py` checks those conditions, and `audit.py`
recomputes them independently from the archived raw events and run receipts.

The stage runs the original ZooKeeper 3.8.7 embedded five-peer JUnit. There is
no Docker cluster or GraphChecker runtime. Before fault trials, two separate
healthy JUnit runs must pass and each must show ten selected target guards for
the moved session. The runner records ASM production source-line coverage and
observed I/O families for feedback; the queue is fixed to the 63 previously
untried ordered plans. A selected target exception pauses the campaign for
source and reproduction review, without automatically marking a new bug.

The node1 stage directory is `/users/ZhenyuLi/zk03-supplement-assets`, with
raw runs in `/users/ZhenyuLi/zk03-supplement-runs`. `stage_node1.py --copy`
stages the original source, compiled classes, original JUnit runner, agent,
legacy raw checkpoint, scripts and 3,041 per-file SHA records. The compiled
original test and five production classes, agent source files, and selected
test/target sources have the same hashes as the original stage. The rebuilt
agent JAR has a different byte hash from the legacy JAR, so two healthy runs
are required to calibrate this staged build. The fixed ZooKeeper source commit
is `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.

Run on node1 under `tmux` using `python3 campaign.py --run --slot 14 --workers
16 --timeout 180 --wall-limit 1800`. The runner takes the shared
`jvm-start.lock` for each launch, requires fewer than four existing Java
processes and at least 10 GiB free disk, and reserves ports 28719–30064.
It launches one embedded-cluster JVM at a time. A checkpoint and JSONL ledger
are written atomically after each trial. On restart, a completed raw receipt
is audited once; an incomplete, no-longer-live run is moved to `interrupted`
and its plan retried. The expected 63-JVM time from the previous campaign's
4.158-second mean is about 4.4 minutes, excluding shared-lock waits. The first
five runs on a contended node1 took 85–119 seconds apiece including waits, so
the actual stage can span multiple 30-minute batches. It can pause on resource
gate failure, timeout, or target-exception candidate.

After the tmux run is terminal, run `python3 audit.py --archive` on node1.
`audit-summary.json` and the separate raw tar archive then report the actual
selected/effective counts, per-trial time, coverage, I/O, and selected target
exception evidence. No parent-trace target window is counted as a faulted
trial outcome.

The separate `resume_supervisor.py` tmux watcher waits until the original
campaign tmux exits. If and only if it stopped at `paused_wall_limit`, the
watcher checks the checkpoint's 63-plan partition, independently re-audits all
completed raw trials, rechecks asset hashes and node1 resource gates, and
resumes the same checkpoint for another 30-minute batch. It stops for any
target-exception candidate, timeout, unfinished Java process, resource gate
failure, or unexpected runner exit. When the queue is exhausted, it performs
the final raw audit and archive. The watcher itself launches no JVM while the
original tmux campaign remains active.

During the first batch, the sixth plan stopped **before JVM launch** because
`ps -C java` exits with status 1 when node1 has zero Java processes. The
resource gate now treats that empty selection as count zero. The old
`supplement-006` directory contained no launch receipt, events, coverage, or
JUnit output and was preserved under `interrupted`. `migrate_zero_java.py`
saved the old and new checkpoint SHA values, confirmed the same five completed
trials and 58 pending plans, changed only the runner asset-manifest SHA in the
checkpoint, and reset the next run ID to retry plan six. The original two
healthy traces remain valid because the test, agent, compiled classes, and
classpath hashes did not change. The [migration receipt and old/new checkpoint
snapshots](evidence/migration/zero-java-migration.json) are copied into this
case and remain with the node1 raw runs; the completed-trial denominator is
unchanged.
