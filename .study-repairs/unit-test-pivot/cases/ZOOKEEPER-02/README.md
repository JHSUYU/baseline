# ZOOKEEPER-02: session owner mismatch

**Status: `pending_independent_recorder_replay`.** An original embedded-cluster
JUnit and 128 legacy fault trials completed, but their event recorder used
GraphChecker-prewoven classes and a precomputed static region skeleton.
Accordingly, the graph-independent method has **zero counted trials** for
this check. The completed trial results remain available as historical
evidence in [`legacy-graph-result.json`](legacy-graph-result.json) and
[`trial-ledger.jsonl`](trial-ledger.jsonl).

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
