# ZOOKEEPER-02: session owner mismatch

> **Actor identity recheck pending.** The earlier I/O fault selector used a global call-site ordinal and did not bind the peer/client/socket or file owner. Its raw trials, coverage, and elapsed time are preserved as historical selector-level evidence in `result.json`, but are excluded from the current actor-matched budget. See [independent audit](../../audits/zookeeper-terminal-actor-identity-2026-10-07.md).

**Status: `quality_complete`.** The independent recorder replay below completed
80 new fault trials. The 128 trials using GraphChecker-prewoven classes and a
precomputed static region skeleton remain historical evidence in
[`legacy-graph-result.json`](legacy-graph-result.json) and
[`trial-ledger.jsonl`](trial-ledger.jsonl), excluded from current counts.

## Independent recorder replay

The unchanged ZooKeeper 3.8.7 `QuorumTest.testSessionMoved` passed under a pure JUnit Platform launcher and a rebuilt case-local ASM agent. Its healthy run took 5.045 seconds, reached the exact `SessionTrackerImpl.checkSession` owner-mismatch guard at line 322 twenty-one times, and did not reach the line 323 `KeeperException.SessionMovedException` throw. The unchanged `QuorumTest.testSessionMovedWithMultiOp` positive control passed and recorded one selected throw, expected by that test. The original class files at commit `9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae` were copied into a fresh case-specific worktree. `evidence/independent/provenance.json` checks all 80 JVM classpath/agent/launcher hashes, byte-for-byte identity of the selected original class files, and the absence of GraphChecker, skeleton, and causynth components. `evidence/independent/audit.json` recomputes every trial verdict from raw events.

The campaign completed 80 original-cluster JUnit fault trials under an eight-fault cap. All 80 ordered plans matched and applied in full, totaling 376 fault applications; 28 trials reached the exact owner guard after the final fault, with sequences up to depth eight. None reached the selected throw. Fifty-two JUnit runs failed after losing the target path: 22 connection losses while creating `/sessionMoveTest`, 16 during later `/` operations, ten failed sync assertions, and four injected epoch-file startup failures. All 28 target-retaining JUnit runs passed. Admitted runs added nine production lines, including `NIOServerCnxn.close:603` on an already-removed connection, server I/O exception handling, and `SessionTrackerImpl.run` scheduling lines. Source review found no new owner-mismatch exception or bug.

Target-retaining runs among trials 73–80 added no new production line, method, or stable target-pre I/O family, so the conditional 128-trial extension was not triggered. The recorder observed 230 target-pre I/O site and ordinal positions, with no new site family beyond the healthy run. At the 80-trial ceiling, 425 feedback-generated plans remained queued; this is a budget result, not selector-frontier exhaustion. `evidence/independent/trial-summary.csv` lists each plan, elapsed time, exact match, target retention, and outcome. The raw 82-JVM archive is `evidence/independent/raw-runs.tar.gz` (SHA-256 `aa61c11eb87fe4cdeabac31b8bc736e68a406e37eafe0ff0b6bd26be32e91418`). Fault JVMs took 494.171 seconds in aggregate and 250.899 seconds of wall time across two workers; including healthy and positive-control JVMs, the recorded total is 507.015 seconds.

## Historical graph-derived evidence

## Source check and original JUnit

ZooKeeper 3.8.7 checks session ownership in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java:320-323`,
`SessionTrackerImpl.checkSession(long,Object)`. If `session.owner != owner`,
the selected bytecode guard `#u24=false` reaches explicit throw `#u27` of
`KeeperException.SessionMovedException`. The check receives owners from
request processing and distinguishes a moved session from its former owner.
The original 102-site inventory named the throw at `#u27` and proposed
`QuorumPeerMainTest.testQuorum`; direct test and source review selected the
more focused original five-peer
`org.apache.zookeeper.test.QuorumTest#testSessionMoved`.

That JUnit moves one session among five peers twice, issuing operations on
the new connection and expecting `ConnectionLossException` on the old
handle. It passed natively. Its healthy lifecycle trace executed the selected
owner check 21 times and emitted **zero** exact selected throws. The related
original `QuorumTest#testSessionMovedWithMultiOp` also passed, but its healthy
trace emitted **one expected** exact `SessionMovedException`; it was a
positive observation of the throw instrumentation, not a bug and not the
fuzz workload. Any faulted throw requires a same-target differential review.

The isolated ZooKeeper tree is `/users/ZhenyuLi/zk02-unit/source` on node2;
its `pom.xml` declares version 3.8.7. SHA-256 of the checked production
source is `baffc60cd94b7b2c9edd3ea21602e02f782c26a32e82e80aac6d88cfe9fdc1bd`;
the JUnit source is
`67a3f264bc95434d9fca8de86a3ac2f398f28aa2ad752b803ad1f6411b0181b6`.

## Historical fault campaign

The same original JUnit ran in a fresh JVM for every trial. A healthy
lifecycle trace exposed 428 I/O points; 402 points remained after requiring
a later healthy target check and excluding four previously tested exact TCP
selectors. The four old probes were imported into the checkpoint and never
rerun. The campaign mutated sequences from I/O actually observed after prior
faults, balancing single- and multifault trials while favoring new method,
branch, call-site and I/O feedback. It used exact
`(marker, siteId, sourceKey, occurrence, hitOrdinal)` fault selectors. The
stable I/O **family** used for feedback was only
`(marker, siteId, sourceKey)`; retry ordinals were not counted as new
families. The file I/O hook did not record a file path, so two files accessed
at the same site on the same peer could be merged as one family.

The budget grew from 48 trials/four faults to 64/six, then 128/eight when
target-preserving trials near the earlier ceiling still added production
coverage. The largest sequence actually tested had four faults. The
checkpoint is atomic and resumable; node2 tmux sessions continued from it
without replaying completed trials. The final queue still had 13,108
sequences, so this was a budget stop, not an exhaustive search.

| Historical measurement | Result |
| --- | ---: |
| Completed sequences, including four imported trials | 128 |
| Trial attempts, including unmatched retries | 154 |
| Strictly applied sequences | 110 |
| Strict sequences evaluating `#u24` after the final fault | 47 |
| Lost-target / unmatched sequences | 63 / 18 |
| Exact selected throw after the final fault | 0 |
| Fatal owner-mismatch guard after the final fault | 0 |
| New production methods / branch outcomes / call-site IDs | 14 / 111 / 536 |
| New stable I/O families | 4 |
| Measured cumulative time, including setup, seed, trials and retries | 2,209.739 s |

The 47 valid target-preserving sequences included 27 single-fault, eight
two-fault, six three-fault, and six four-fault trials. Forty-one of their
JUnit runs exited successfully; six exited with other fault-induced test
failures. None produced the selected owner-mismatch throw. Under the agreed
target-exception oracle, these observations are **not a new bug**; they also
do not prove this source check cannot fail under other schedules or workloads.
The final `legacy-graph-result.json` records 661 new production coverage
items, admitted only from strictly applied, target-preserving trials.

## Recorder audit and next step

The fault *selection* did not aggregate a causal graph or require a closure
edge on each round. Its recorder nevertheless loaded GraphChecker-prewoven
classes from `record-v4/instrumented-classes`. The private ZooKeeper runner
set `causynth.region.preserve.failure-target=true` and supplied
`record-v4/region_skeletons.jsonl.gz`; GraphChecker's
`FailureTargetRegionPreservation.readSkeletons()` reads those static rows for
the occurrence identity used by exact selectors. The legacy JAR SHA-256 was
`fdee49a2134fe8afffbb3f851c6ff93296063e05a7e4d63a257ed926fa8c10cb`.
This recorder is not independent of GraphChecker's precomputed graph
artifacts. The 128 trials therefore cannot count toward the revised
graph-independent baseline. Reuse the verified source site and original
JUnit mapping, then record I/O and coverage with an independent ASM/JaCoCo
path before starting new counted trials.

The full historical checkpoint and trial artifacts remain on node2 under
`/users/ZhenyuLi/zk02-unit/campaign/results/ZOOKEEPER-02/`.
[`trial-ledger.jsonl`](trial-ledger.jsonl) lists every trial's duration,
selector, exact match, post-fault target, target throw and feedback; the
[`archive manifest`](archive-manifest.jsonl) maps losslessly compressed
`.zst` traces to their former paths. Decompress with `zstd -dc` when a raw
trace is needed. The
[`bootstrap audit`](bootstrap-audit.json) explains the healthy I/O filter and
four imported selectors. The SHA-256 values for the legacy result, ledger,
and archive manifest are pinned in the current [`result.json`](result.json).
