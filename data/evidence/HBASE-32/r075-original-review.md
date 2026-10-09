# HBASE-32 r075 original timeout: exact replay passed

The unchanged `TestRegionReplicaFailover#testLotsOfRegionReplicas` JUnit ran on node1 with one exact `RPC_FLUSH_REGION` `DoNotRetryIOException`. The injected RPC belongs to replica 1 of one raw primary region. The same region, replica, and target invocation reached the selected `RegionReplicaFlushHandler.triggerFlushInPrimaryRegion` B7 rethrow. The run reached the 360-second test cap; its 414.63-second process time includes shutdown. It did not emit a JUnit result. This is a scheduling-sensitive timeout candidate, **not a confirmed new bug**.

The raw `r075.log`, JaCoCo `.exec`, and exit receipt are preserved in `r075-original-raw.tar.gz` (SHA-256 `7d7c4918192cf43960c00708a44802b4f81788e980f5f8e873b4ad7b27640602`). `replay-r075-plan.json` records the exact plan and raw file checksums. Relevant original log evidence:

| Observation | Log line | Time |
| --- | ---: | --- |
| Exact injected flush RPC | 17102 | during table creation |
| Same target B7 rethrow | 17117 | during table creation |
| Last successful `testLotsOfRegionRepli2` child assignment, 343/600 observed | 17208 | 03:56:20.849 UTC |
| Dead RegionServer znode expiration begins | 17920–17921 | 03:56:32.477–.480 UTC |
| First shutdown hook starts | 28987 | 04:01:41.505 UTC |
| ServerCrashProcedure for that RegionServer finally scheduled | 34538 | 04:02:10.695 UTC, after shutdown began |
| Runner exit | 37251 | 124; 414.63 seconds |

Only one RegionServer aborted before shutdown; the other two abort entries in the trial metadata happened during cleanup. The cluster was therefore within the three-RS fault-tolerance bound when it stalled. No pre-timeout thread dump was captured for r075, so the evidence cannot identify a lock owner or prove a deadlock.

An exact fresh-data replay on isolated node2 used the same selector, agent class, and HBase 2.6.6 JAR with a 600-second cap. It fully applied the fault, reached the same raw-actor B7, and **passed the unchanged JUnit 1/1 in 56.45 seconds**. The table-creation procedure completed 600/600 child assignments. Only one RegionServer aborted, and its ServerCrashProcedure was scheduled promptly at 04:21:02.644 UTC, before shutdown. The full replay log, JaCoCo file, receipt, and summary are in `r075-replay-raw.tar.gz` (SHA-256 `9541b4ab026b35ae0f9cd93d1d7ce3e2205901f7c3bf31ad1950864ae57ec363`); the summary's log and coverage checksums were independently verified. The replay ended before the 200-second thread-dump threshold, so no dump was needed.

Classification: **unreproduced timeout candidate, no confirmed new bug**. r003, r011, and r058 likewise exhibited original-run timeouts but passed exact clean 600-second replays. A special scheduling failure remains a research possibility, but these observations do not establish a stable hang, closed lock cycle, or incorrect final state.
