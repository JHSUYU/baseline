# ZOOKEEPER-06: follower state ahead of leader

**Status:** `pending_graph_precision` · **new bug:** none observed · **quality complete:** no.

## Original check and workload

ZooKeeper 3.8.7, `zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java:1471–1475`, `Leader.waitForEpochAck(long, StateSummary)`:

```java
if (ss.isMoreRecentThan(leaderStateSummary)) {
    throw new IOException("Follower is ahead of the leader, ...");
}
```

The exact target is Soot guard `#u14` and throw `#u29`, region `REGION.b3eb0be6-3e8d-3adf-81c3-07d7060c0e07`. `StateSummary.isMoreRecentThan` compares `(currentEpoch, lastZxid)` lexicographically. `LearnerHandler.run:541–549` receives ACKEPOCH, decodes its epoch and zxid, and invokes the target; `Leader.lead:603` builds `leaderStateSummary` from the leader current epoch and last processed zxid. The original, unedited `QuorumRestartTest#testRollingRestart` starts an in-JVM three-peer quorum and restarts peers 1, 2, and 3 in order. The test itself checks connectivity; this campaign's oracle is the target `IOException` after an applied fault.

Healthy GraphChecker runs reached `#u14=true`. The r4 healthy trace has four matched ACKEPOCH send/receive pairs and four matched LEADERINFO pairs, with no runtime trace gap. The exact ACKEPOCH read fault markers are `LearnerHandler.run#u141` (IOException) and `#u146` (EOFException) in both the frozen static dataflow graph and the runtime trace. Full fault selectors include marker, Soot site, source peer/epoch, region occurrence, and hit ordinal. Each retained fault trace was reaggregated around its own full target occurrence; a changed ACK correlation on retry did not cause the same leader and semantic epoch request to be mistaken for a lost check.

## Executions

The [trial ledger](trial-ledger.jsonl) records each selector, UTC completion time, JUnit runtime, GraphChecker aggregation time, matched/applied count, target guard result, and archive path. There were **32 trial executions**, selecting **35 fault events**; **29 sequences** matched all selectors and applied **32 fault events**. Three sequence attempts were unmatched, including the late peer-2 response IOException that remained unmatched on retry. Unmatched attempts are not negative results. Three early sequences each contained two faults; all three lost the chosen target check.

| Fault door | Selected events | Applied events | Distinct selectors applied | Trials retaining target |
|---|---:|---:|---:|---:|
| Leader-to-learner response `IOException` | 14 | 12 | 7/8 | 2 |
| Leader-to-learner response `EOFException` | 9 | 8 | 8/8 | 2 |
| Epoch file read `IOException` | 2 | 2 | 2/2 | 0 |
| Epoch file write `IOException` | 6 | 6 | 6/6 | 2 |
| Learner-to-leader ACKEPOCH read `IOException` | 2 | 2 | 2/2 | 1 |
| Learner-to-leader ACKEPOCH read `EOFException` | 2 | 2 | 2/2 | 0 |

Seven applied-fault trials reached the same chosen leader/epoch check after the fault. All seven evaluated `#u14=true` in a dynamically reaggregated target closure with zero blocking gaps. **No trial observed the target `IOException`; no new bug is claimed.** Method-entry and branch-outcome coverage was collected each round. Within their respective woven builds, the fuzzer reported 3 new signatures in r2, 5 in the expanded r3 response campaign, and 7 in the r4 ACKEPOCH campaign. Raw site IDs shift between builds, so these gains are not summed.

The measured JUnit fault executions took **218.427 s**, and their graph aggregations **102.986 s**: **321.413 s** for the 32 completed trials. The complete case wall span from the first case-local adapter creation through report finalization was **2,704.312 s**; it includes static analysis, healthy seeds, trace reanalysis, source review, and idle time. The [result](result.json) gives machine-readable counts and time boundaries. The [archive manifest](artifact-manifest.json) records verified SHA-256 digests and sizes for 74 gzip event streams (1,198,893,524 raw bytes to 76,057,742 compressed bytes), plus immutable JAR and config digests. Raw streams can be restored with `gzip -dk`.

## Why the case remains pending

An exception before ACKEPOCH decoding can stop that `LearnerHandler` before it constructs `StateSummary`; a lost target is therefore not evidence that the check is safe. On rejoin, the target can execute again, as seven trials show. The frozen graph's `targetClosureEvidence.edgeEvidence` is `UNAVAILABLE`, even though there are no blocking membership gaps for the chosen target. The [producer gap evidence](producer-gap.json) records that `Leader.lead` receives `LeaderZooKeeperServer.getLastProcessedZxid()` through call-return edge `DF.1531`, while no `FileTxnLog` or `FileSnap` producer edge is present for the persisted zxid loaded by `zk.loadData()`. The backward state closure is not proven complete. The late response `IOException` selector also remains unmatched. These gaps prevent `quality_complete`; this bounded fault campaign stops here without treating an absent target exception as a negative proof.

GraphChecker changes were developed in isolated commits `4837827c6`, `08bbfb78e`, and `b9e73d006`, then integrated in ZooKeeper system branch head `a8bc916b7`. The generic catalog now supports a unique `sourceLine` call anchor for an exact I/O door; `LibraryCatalogTest` and Maven package passed. No ZooKeeper source or original JUnit test was edited, and Docker was not used.
