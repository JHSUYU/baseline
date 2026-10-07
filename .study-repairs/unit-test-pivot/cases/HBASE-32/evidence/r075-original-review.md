# HBASE-32 r075 original timeout: pending exact replay

The unchanged `TestRegionReplicaFailover#testLotsOfRegionReplicas` JUnit ran on node1 with one exact `RPC_FLUSH_REGION` `DoNotRetryIOException`. The injected RPC belongs to replica 1 of one raw primary region. The same region, replica, and target invocation reached the selected `RegionReplicaFlushHandler.triggerFlushInPrimaryRegion` B7 rethrow. The run reached the 360-second test cap; its 414.63-second process time includes shutdown. It did not emit a JUnit result. This is a scheduling-sensitive timeout candidate, **not a confirmed new bug**.

The raw `r075.log`, JaCoCo `.exec`, and exit receipt are preserved in `r075-original-raw.tar.gz` (SHA-256 `7d7c4918192cf43960c00708a44802b4f81788e980f5f8e873b4ad7b27640602`). `replay-r075-plan.json` records the exact plan and raw file checksums. Relevant raw log evidence:

| Observation | Log line | Time |
| --- | ---: | --- |
| Exact injected flush RPC | 17102 | during table creation |
| Same target B7 rethrow | 17117 | during table creation |
| Last successful `testLotsOfRegionRepli2` child assignment, 343/600 observed | 17208 | 03:56:20.849 UTC |
| Dead RegionServer znode expiration begins | 17920–17921 | 03:56:32.477–.480 UTC |
| First shutdown hook starts | 28987 | 04:01:41.505 UTC |
| ServerCrashProcedure for that RegionServer finally scheduled | 34538 | 04:02:10.695 UTC, after shutdown began |
| Runner exit | 37251 | 124; 414.63 seconds |

Only one RegionServer aborted before shutdown; the other two abort entries in the trial metadata happened during cleanup. The cluster was therefore within the three-RS fault-tolerance bound when it stalled. No pre-timeout thread dump was captured for r075, so the evidence cannot identify a lock owner or prove a deadlock. r003, r011, and r058 exhibited similar original-run timeouts yet passed exact clean 600-second replays. The next classification step is a fresh isolated 600-second replay of this exact plan, with `jcmd Thread.print -l` during any prolonged stall and explicit child assignment, ServerCrashProcedure, cluster-liveness, and JUnit results. Keep this candidate out of the new-bug count until that result and source review.
