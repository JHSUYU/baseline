# Coding-agent baseline: results on the 84 ad hoc checks

Setup: `README.md`. Claude Code 2.1.319, `claude-opus-5-5[1m]`, effort high, one prompt per check (the paper's four parts), no git history, no network except the model API, 8 h budget per check. Time is the agent's active time (usage-limit waits excluded); tokens are input + output + cache writes + cache reads, as the CLI reports them, including subagents; cost is the CLI's list-price estimate.

- **Validated**: the paper's criterion. The agent's test, run on an unmodified copy of the system (only its test files carried over), throws the check's exception from the check's line.
- **Bug (reviewed)**: a validated reproduction that an independent source review (`REVIEW-RUBRIC.md`) judged a real bug by realistic means. The other validated ones are the check rejecting by design (BY_DESIGN) or reached by an unrealistic test (UNREALISTIC).

## Summary

| system | checks | claimed | validated | bug (reviewed) | by design | unrealistic | agent time | tokens | cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HDFS | 36 | 26 | 26 | 14 | 9 | 3 | 6h07m | 48.99M | $104 |
| Solr | 13 | 13 | 13 | 5 | 8 | 0 | 2h19m | 24.69M | $22 |
| HBase | 19 | 18 | 18 | 9 | 9 | 0 | 1h52m | 21.96M | $23 |
| ZooKeeper | 16 | 15 | 15 | 11 | 4 | 0 | 2h19m | 30.60M | $36 |
| **total** | 84 | 72 | 72 | 39 | 30 | 3 | 12h37m | 126.23M | $185 |

## Bugs (validated and reviewed as real), with the time and usage of their check

| case | severity | bug | agent time | tokens | output tokens | cost |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| hdfs-adhoc-07 | operation-failure | A lagging JN's acceptRecovery is wrongly rejected because the global committedTxnId, already advanced into the next segment, is compared against the recovered segment's range, leaving that JN permanently unsynchronized for the segment. | 0h09m | 0.96M | 45,252 | $1.68 |
| hdfs-adhoc-08 | minor | The writer can establish an epoch below a leftover promise held by a slow JN, and QJM never re-proposes, so that healthy JN is excluded for the writer's lifetime and the NN can no longer survive one more JN failure. | 0h05m | 0.51M | 21,680 | $0.92 |
| hdfs-adhoc-09 | data-loss | JournalNodeSyncer auto-format lets a wiped JN vote in recovery quorums before it has re-synced, so a new writer can recover without committed edits and reuse their txids (lost acknowledged edits, divergent JN logs). | 0h22m | 5.23M | 101,428 | $4.38 |
| hdfs-adhoc-11 | operation-failure | After a NameNode restart the Balancer/Mover keeps using a cached data encryption key derived from a lost block key, so all block moves to DataNodes that registered after the restart fail for up to the token lifetime (10h). | 0h18m | 2.45M | 34,793 | $1.95 |
| hdfs-adhoc-14 | operation-failure | With overwrite-downstream-derived-QOP, the pipeline head re-signs block tokens with its current key while keeping the original keyId, so downstream DNs reject valid tokens around every block-key roll and pipelines lose replicas or fail. | 0h07m | 1.59M | 27,609 | $1.48 |
| hdfs-adhoc-20 | minor | BPOfferService.verifyAndSetNamespaceInfo accepts an ACTIVE NN at handshake without the txid split-brain check, so a stale ex-active NN can become the DN's active NN (assertion kills the actor; with assertions off the split-brain protection is bypassed). | 0h09m | 1.02M | 37,819 | $1.45 |
| hdfs-adhoc-25 | operation-failure | Concurrent hot-swap volume adds race on shared BlockPoolSliceStorage fields, so a healthy volume is rejected with a spurious cTime mismatch and reported as failed. | 0h05m | 0.66M | 22,004 | $1.03 |
| hdfs-adhoc-26 | outage | A DataNode that missed a rollback silently discards its unfinalized previous snapshot on the next upgrade and keeps the rolled-back state, so a later rollback fails and its block pool cannot start. | 0h07m | 0.60M | 16,604 | $0.84 |
| hdfs-adhoc-31 | operation-failure | BlockPoolManager.remove(old BPOS) removes the bpid mapping of the new BPOS that replaced it during refreshNamenodes. The DN keeps heartbeating for the block pool, but every block-pool lookup (transfer, bad-block report, IBR) fails until it restarts. | 0h19m | 2.86M | 58,547 | $18.39 |
| hdfs-adhoc-33 | operation-failure | A volume hot-add that races with block-pool removal (refreshNamenodes) fails with AssertionError/NPE in VolumeBuilder.build and leaves the new volume's storage directory locked, so the disk cannot be added until the DataNode restarts. | 0h11m | 1.50M | 25,537 | $1.37 |
| hdfs-adhoc-38 | data-loss | Existing non-lazy-persist files inherit LAZY_PERSIST from a parent directory set later (or after a rename), which makes them permanently un-appendable and lets the LazyPersistFileScrubber delete durable DISK files whose replicas are temporarily unavailable. | 0h07m | 0.87M | 18,817 | $0.96 |
| hdfs-adhoc-49 | operation-failure | A delayed original of an idempotent disallowSnapshot runs after the client's successful retry and a later allowSnapshot, silently making '/' non-snapshottable (quota 0), so createSnapshot('/') keeps failing. | 0h12m | 2.81M | 44,814 | $2.30 |
| hdfs-adhoc-50 | minor | Default snapshot names have only millisecond resolution, so concurrent or back-to-back unnamed createSnapshot calls on one directory fail at random with 'snapshot with the same name already exists'. | 0h03m | 0.35M | 12,363 | $0.58 |
| hdfs-adhoc-52 | operation-failure | Replaying the tolerated duplicate OP_DELETE_SNAPSHOT after ordered deletion is turned off still decrements numSnapshots, making it -1 so that every fsimage save/checkpoint fails. | 0h05m | 0.79M | 16,407 | $0.87 |
| solr-adhoc-07 | minor | One lost REQUESTSTATUS poll makes the Overseer report ADDREPLICA FAILED and release the collection lock while the core is still being created, so a cleanup DELETEREPLICA races the registration (register aborts, instance dir is left behind). | 0h12m | 3.81M | 47,503 | $2.68 |
| solr-adhoc-10 | data-loss | TimeRoutedAlias.validateRouteValue writes router.start from a stale Aliases snapshot onto whatever the alias currently is, so it corrupts a replacement plain alias (and can overwrite concurrent alias changes); MAINTAINROUTEDALIAS then fails with 'called on non-routed alias'. | 0h10m | 2.17M | 33,380 | $1.80 |
| solr-adhoc-13 | minor | A routed-alias update does not refresh TRA properties during a request (contrary to the ref guide), so a concurrent ALIASPROP router.interval change makes the Overseer create a different collection and the batch fails with 'After we attempted to create X it did not exist'. | 0h10m | 2.39M | 50,119 | $2.38 |
| solr-adhoc-21 | minor | CoreContainer.reload racing with DELETEREPLICA's UNLOAD re-registers the deleted core and then fails on the missing replica (assert/NPE), leaving a closed stale core registered on the node. | 0h05m | 0.74M | 19,669 | $0.94 |
| solr-adhoc-31 | operation-failure | In perReplicaState collections, a crashed leader's PRS entry stays 'active, leader' because the clear-leader message does not change PRS entries, so FORCELEADER on the leaderless shard is rejected with 'already has an active leader'. | 0h19m | 2.01M | 32,413 | $1.74 |
| hbase-adhoc-04 | outage | QuotaObserverChore records the 'in observance' state before re-enabling the table; if that one enable fails, it is never retried and the table stays disabled until an admin enables it. | 0h02m | 0.24M | 7,547 | $0.42 |
| hbase-adhoc-07 | minor | A clone racing with an in-progress clone of the same name is sent down the restore path, which validates (and would restore) the snapshot's source table instead of the clone target. | 0h04m | 0.55M | 15,442 | $0.78 |
| hbase-adhoc-11 | minor | Decommission with offload aborts with a non-retryable error, leaving the server draining with regions still on it, if one of its regions is in the SPLITTING window (no procedure attached yet). | 0h04m | 0.72M | 15,549 | $0.91 |
| hbase-adhoc-12 | minor | Decommission with offload aborts with DoNotRetryIOException, leaving the server half-drained, when it meets an OPEN region of a DISABLING table (a state reachable when a move races with disable). | 0h10m | 1.76M | 40,652 | $1.96 |
| hbase-adhoc-13 | minor | Under accepted master/RS clock skew, the merge-qualifier delete (RS timestamp) does not cover the qualifiers written with the master timestamp, so a fully GC'd merged region keeps blocking new merges. | 0h10m | 1.37M | 24,303 | $1.29 |
| hbase-adhoc-21 | operation-failure | A rolled-back split never releases its namespace-quota region reservation (onRegionSplitReverted is never called), so later valid restore/create/split operations in the namespace are refused with QuotaExceededException until the master restarts. | 0h04m | 0.76M | 13,802 | $0.92 |
| hbase-adhoc-22 | operation-failure | truncateTable(preserveSplits=false) does not update the master's namespace quota cache, so the namespace stays overcounted and valid table creates/clones/splits are refused with QuotaExceededException. | 0h03m | 0.44M | 9,465 | $0.56 |
| hbase-adhoc-34 | minor | A follower that is late to see a key roll issues delegation tokens that outlive their signing key; once the leader expires the key, those tokens are rejected as 'Unknown master key' before their stated expiration. | 0h06m | 0.49M | 25,079 | $1.01 |
| hbase-adhoc-35 | operation-failure | setRegionStateInMeta for the hbase:meta region writes a bogus meta row into hbase:meta itself instead of rejecting the request or routing it to the master local region, permanently breaking hbck1 ('Two entries in hbase:meta are same'). | 0h09m | 3.24M | 39,393 | $2.33 |
| zk-adhoc-01 | operation-failure | restoreFromSnapshot leaves the old session tracker's expiry thread running (and the new one unstarted), so about one session timeout after an admin restore every pre-existing live session is force-expired: in-flight writes get SESSIONEXPIRED and its ephemerals are deleted. | 0h38m | 11.39M | 150,862 | $11.86 |
| zk-adhoc-04 | operation-failure | After a leader election with no new write, the leader advertises zxid newEpoch<<32 while DIFF-synced followers keep the old last zxid, so clients that talked to the new leader are refused by every in-sync follower (CLIENT_ZXID_AHEAD) until the next write. | 0h14m | 3.02M | 45,712 | $2.34 |
| zk-adhoc-10 | outage | A malformed client request gets an error txn with an already used zxid (zks.getZxid() instead of getNextZxid()), so the leader proposes a duplicate zxid. Followers then fail commit matching and crash or drop out of the quorum. | 0h16m | 3.88M | 59,983 | $5.99 |
| zk-adhoc-11 | outage | A follower that crashes between persisting the synced new-epoch txns and writing currentEpoch can never restart ('current epoch is older than the last zxid') without manual repair. | 0h03m | 0.41M | 12,767 | $0.65 |
| zk-adhoc-12 | outage | A transient failure persisting acceptedEpoch in a LearnerHandler is swallowed: the leader still establishes the epoch and writes currentEpoch > acceptedEpoch, so the server can never restart ("accepted epoch is less than the current epoch"). | 0h07m | 1.04M | 21,980 | $1.19 |
| zk-adhoc-b1 | operation-failure | A crash or connection loss between the two creates in SetQuotaCommand.createQuota leaves zookeeper_limits without zookeeper_stats: setquota then fails with NoNode for good, and the hard quota is silently not enforced. | 0h04m | 0.54M | 14,797 | $0.71 |
| zk-adhoc-b2 | outage | The LeaderElectionSupport recipe fails permanently (FAILED, no leader elected) when a competing candidate's ephemeral offer disappears between getChildren and getData, which happens exactly when a leader crashes. | 0h08m | 2.18M | 30,667 | $1.63 |
| zk-adhoc-b3 | data-loss | A stale ContainerManager deleteContainer request deletes a PERSISTENT node re-created at the same path, because deleteContainer does not re-check that the target is still a container or TTL node. | 0h03m | 0.36M | 15,333 | $0.66 |
| zk-adhoc-b4 | operation-failure | ZooKeeperRetry.create re-sends a sequential create after a lost reply because exists() on the un-suffixed path is always null, creating duplicate znodes that use up hard count quota and make legitimate creates fail. | 0h02m | 0.27M | 11,354 | $0.52 |
| zk-adhoc-b5 | data-loss | A TRUNC-mode sync interrupted before NEWLEADER leaves a committed txn applied only in memory. The follower rejoins with it, so its on-disk log has a permanent hole and the server fails to load its database on the next restart. | 0h07m | 1.50M | 30,043 | $1.51 |
| zk-adhoc-b6 | outage | An ObserverMaster created after a follower's sync drops COMMITs for proposals the follower received during the sync. Observers attached in that window get a gapped txn stream, apply later txns without the committed one, and their CommitProcessor dies. | 0h04m | 0.76M | 15,871 | $0.86 |

## Every check

| case | claimed | validated | review | agent time | waits | tokens | cost |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| hdfs-adhoc-05 | no | - | - | 0h05m | 0h00m | 0.77M | $1.27 |
| hdfs-adhoc-06 | no | - | - | 0h02m | 0h00m | 0.25M | $0.46 |
| hdfs-adhoc-07 | yes | REPRODUCED | BUG | 0h09m | 0h00m | 0.96M | $1.68 |
| hdfs-adhoc-08 | yes | REPRODUCED | BUG | 0h05m | 0h00m | 0.51M | $0.92 |
| hdfs-adhoc-09 | yes | REPRODUCED | BUG | 0h22m | 0h00m | 5.23M | $4.38 |
| hdfs-adhoc-10 | yes | REPRODUCED | BY_DESIGN | 0h06m | 0h00m | 0.75M | $0.87 |
| hdfs-adhoc-11 | yes | REPRODUCED | BUG | 0h18m | 0h00m | 2.45M | $1.95 |
| hdfs-adhoc-12 | yes | REPRODUCED | UNREALISTIC | 0h05m | 0h00m | 0.67M | $0.79 |
| hdfs-adhoc-14 | yes | REPRODUCED | BUG | 0h07m | 0h00m | 1.59M | $1.48 |
| hdfs-adhoc-15 | no | - | - | 0h03m | 0h00m | 0.43M | $0.49 |
| hdfs-adhoc-16 | no | - | - | 0h16m | 0h00m | 5.55M | $4.30 |
| hdfs-adhoc-19 | no | - | - | 0h04m | 0h00m | 0.49M | $0.58 |
| hdfs-adhoc-20 | yes | REPRODUCED | BUG | 0h09m | 0h00m | 1.02M | $1.45 |
| hdfs-adhoc-21 | no | - | - | 0h01m | 0h00m | 0.17M | $0.28 |
| hdfs-adhoc-22 | no | - | - | 0h07m | 0h00m | 0.95M | $1.26 |
| hdfs-adhoc-23 | no | - | - | 0h04m | 0h00m | 0.63M | $0.75 |
| hdfs-adhoc-24 | yes | REPRODUCED | BY_DESIGN | 0h46m | 1h15m | 3.25M | $14.34 |
| hdfs-adhoc-25 | yes | REPRODUCED | BUG | 0h05m | 0h00m | 0.66M | $1.03 |
| hdfs-adhoc-26 | yes | REPRODUCED | BUG | 0h07m | 0h00m | 0.60M | $0.84 |
| hdfs-adhoc-27 | yes | REPRODUCED | UNREALISTIC | 0h11m | 0h00m | 1.21M | $1.28 |
| hdfs-adhoc-28 | yes | REPRODUCED | BY_DESIGN | 0h07m | 0h00m | 0.99M | $1.19 |
| hdfs-adhoc-29 | yes | REPRODUCED | BY_DESIGN | 0h07m | 0h00m | 1.30M | $1.47 |
| hdfs-adhoc-30 | yes | REPRODUCED | BY_DESIGN | 0h06m | 0h00m | 0.50M | $0.68 |
| hdfs-adhoc-31 | yes | REPRODUCED | BUG | 0h19m | 1h30m | 2.86M | $18.39 |
| hdfs-adhoc-33 | yes | REPRODUCED | BUG | 0h11m | 0h00m | 1.50M | $1.37 |
| hdfs-adhoc-34 | yes | REPRODUCED | BY_DESIGN | 0h15m | 1h30m | 1.85M | $14.15 |
| hdfs-adhoc-35 | no | - | - | 0h12m | 0h00m | 2.27M | $2.60 |
| hdfs-adhoc-37 | yes | REPRODUCED | UNREALISTIC | 0h52m | 1h00m | 1.63M | $8.54 |
| hdfs-adhoc-38 | yes | REPRODUCED | BUG | 0h07m | 0h00m | 0.87M | $0.96 |
| hdfs-adhoc-39 | yes | REPRODUCED | BY_DESIGN | 0h04m | 0h00m | 0.67M | $0.78 |
| hdfs-adhoc-40 | yes | REPRODUCED | BY_DESIGN | 0h04m | 0h00m | 0.52M | $0.68 |
| hdfs-adhoc-45 | yes | REPRODUCED | BY_DESIGN | 0h07m | 1h30m | 1.00M | $7.69 |
| hdfs-adhoc-48 | no | - | - | 0h04m | 1h30m | 0.96M | $1.06 |
| hdfs-adhoc-49 | yes | REPRODUCED | BUG | 0h12m | 1h30m | 2.81M | $2.30 |
| hdfs-adhoc-50 | yes | REPRODUCED | BUG | 0h03m | 1h30m | 0.35M | $0.58 |
| hdfs-adhoc-52 | yes | REPRODUCED | BUG | 0h05m | 1h30m | 0.79M | $0.87 |
| solr-adhoc-05 | yes | REPRODUCED | BY_DESIGN | 0h10m | 0h00m | 2.51M | $2.23 |
| solr-adhoc-07 | yes | REPRODUCED | BUG | 0h12m | 0h00m | 3.81M | $2.68 |
| solr-adhoc-09 | yes | REPRODUCED | BY_DESIGN | 0h11m | 0h00m | 2.27M | $1.80 |
| solr-adhoc-10 | yes | REPRODUCED | BUG | 0h10m | 0h00m | 2.17M | $1.80 |
| solr-adhoc-13 | yes | REPRODUCED | BUG | 0h10m | 0h00m | 2.39M | $2.38 |
| solr-adhoc-14 | yes | REPRODUCED | BY_DESIGN | 0h26m | 0h00m | 1.08M | $1.21 |
| solr-adhoc-19 | yes | REPRODUCED | BY_DESIGN | 0h04m | 0h00m | 0.81M | $0.90 |
| solr-adhoc-21 | yes | REPRODUCED | BUG | 0h05m | 0h00m | 0.74M | $0.94 |
| solr-adhoc-22 | yes | REPRODUCED | BY_DESIGN | 0h08m | 0h00m | 1.94M | $1.85 |
| solr-adhoc-31 | yes | REPRODUCED | BUG | 0h19m | 0h00m | 2.01M | $1.74 |
| solr-adhoc-38 | yes | REPRODUCED | BY_DESIGN | 0h09m | 0h00m | 2.26M | $2.03 |
| solr-adhoc-39 | yes | REPRODUCED | BY_DESIGN | 0h07m | 0h00m | 1.35M | $1.42 |
| solr-adhoc-40 | yes | REPRODUCED | BY_DESIGN | 0h09m | 0h00m | 1.35M | $1.39 |
| hbase-adhoc-04 | yes | REPRODUCED | BUG | 0h02m | 0h00m | 0.24M | $0.42 |
| hbase-adhoc-07 | yes | REPRODUCED | BUG | 0h04m | 0h00m | 0.55M | $0.78 |
| hbase-adhoc-08 | yes | REPRODUCED | BY_DESIGN | 0h08m | 0h00m | 2.15M | $1.75 |
| hbase-adhoc-10 | yes | REPRODUCED | BY_DESIGN | 0h08m | 0h00m | 2.51M | $1.96 |
| hbase-adhoc-11 | yes | REPRODUCED | BUG | 0h04m | 0h00m | 0.72M | $0.91 |
| hbase-adhoc-12 | yes | REPRODUCED | BUG | 0h10m | 0h00m | 1.76M | $1.96 |
| hbase-adhoc-13 | yes | REPRODUCED | BUG | 0h10m | 0h00m | 1.37M | $1.29 |
| hbase-adhoc-14 | yes | REPRODUCED | BY_DESIGN | 0h05m | 0h00m | 0.85M | $1.04 |
| hbase-adhoc-15 | yes | REPRODUCED | BY_DESIGN | 0h06m | 0h00m | 0.93M | $1.39 |
| hbase-adhoc-19 | yes | REPRODUCED | BY_DESIGN | 0h04m | 0h00m | 0.52M | $0.80 |
| hbase-adhoc-20 | yes | REPRODUCED | BY_DESIGN | 0h08m | 0h00m | 1.63M | $1.53 |
| hbase-adhoc-21 | yes | REPRODUCED | BUG | 0h04m | 0h00m | 0.76M | $0.92 |
| hbase-adhoc-22 | yes | REPRODUCED | BUG | 0h03m | 0h00m | 0.44M | $0.56 |
| hbase-adhoc-24 | yes | REPRODUCED | BY_DESIGN | 0h08m | 0h00m | 1.37M | $1.53 |
| hbase-adhoc-28 | no | - | - | 0h01m | 0h00m | 0.22M | $0.34 |
| hbase-adhoc-31 | yes | REPRODUCED | BY_DESIGN | 0h08m | 0h00m | 1.48M | $1.63 |
| hbase-adhoc-34 | yes | REPRODUCED | BUG | 0h06m | 0h00m | 0.49M | $1.01 |
| hbase-adhoc-35 | yes | REPRODUCED | BUG | 0h09m | 0h00m | 3.24M | $2.33 |
| hbase-adhoc-37 | yes | REPRODUCED | BY_DESIGN | 0h04m | 0h00m | 0.73M | $0.86 |
| zk-adhoc-01 | yes | REPRODUCED | BUG | 0h38m | 0h00m | 11.39M | $11.86 |
| zk-adhoc-02 | yes | REPRODUCED | BY_DESIGN | 0h06m | 0h00m | 1.14M | $1.46 |
| zk-adhoc-03 | yes | REPRODUCED | BY_DESIGN | 0h09m | 0h00m | 1.43M | $2.22 |
| zk-adhoc-04 | yes | REPRODUCED | BUG | 0h14m | 0h00m | 3.02M | $2.34 |
| zk-adhoc-06 | yes | REPRODUCED | BY_DESIGN | 0h07m | 0h00m | 0.90M | $1.29 |
| zk-adhoc-07 | yes | REPRODUCED | BY_DESIGN | 0h08m | 0h00m | 1.56M | $1.73 |
| zk-adhoc-10 | yes | REPRODUCED | BUG | 0h16m | 0h00m | 3.88M | $5.99 |
| zk-adhoc-11 | yes | REPRODUCED | BUG | 0h03m | 0h00m | 0.41M | $0.65 |
| zk-adhoc-12 | yes | REPRODUCED | BUG | 0h07m | 0h00m | 1.04M | $1.19 |
| zk-adhoc-13 | no | - | - | 0h02m | 0h00m | 0.22M | $1.19 |
| zk-adhoc-b1 | yes | REPRODUCED | BUG | 0h04m | 0h00m | 0.54M | $0.71 |
| zk-adhoc-b2 | yes | REPRODUCED | BUG | 0h08m | 0h00m | 2.18M | $1.63 |
| zk-adhoc-b3 | yes | REPRODUCED | BUG | 0h03m | 0h00m | 0.36M | $0.66 |
| zk-adhoc-b4 | yes | REPRODUCED | BUG | 0h02m | 0h00m | 0.27M | $0.52 |
| zk-adhoc-b5 | yes | REPRODUCED | BUG | 0h07m | 0h00m | 1.50M | $1.51 |
| zk-adhoc-b6 | yes | REPRODUCED | BUG | 0h04m | 0h00m | 0.76M | $0.86 |

## Notes

- **Overlap with the paper's Table 2** (same defect, from the bug descriptions): hdfs-adhoc-11 = HD1 (Balancer keeps a rejected encryption key), hbase-adhoc-22 = HB1 (truncation leaves the cached region count stale), zk-adhoc-b6 = ZK1 (observer misses proposals forwarded during sync), zk-adhoc-b5 = ZK2 (gap in a follower's txn log), zk-adhoc-b1 = ZK3 (partial quota creation), zk-adhoc-b3 = ZK5 (cleanup deletes a re-created node).
- The ZooKeeper b1-b6, HBase 04/07/13/22/34 and HDFS 12 checks start from ported workloads (the same starting tests the paper's tool used); several of them set up the scenario around the bug, which the agent then only has to perturb.
- Agents finished fast: median 7 min of agent time, longest 52 min; none came near its 8 h budget. Waits are usage-limit pauses of the shared account (the last HDFS runs waited about 1.5 h).
- Leakage audit (2026-11-07): 0 agent transcripts mention GraphChecker/Causym/Specula; no WebSearch/WebFetch call; no connection refused by the egress proxy on any node (no attempt to reach anything but the model API); no agent changed production code (validation.json `production_changes` empty for all).
- Validation matcher: accepts the frame on any line of the check's throw statement (the JVM records the constructor's line) and any method of the check's file (hbase-adhoc-35's check is in an anonymous visitor). Earlier verdicts were re-run after these two fixes; superseded verdicts are in `cases/<case>/logs/validation.v1.json`.
- Reviews are first-pass source reviews by independent reviewer agents (`cases/<case>/review.json`, rubric `REVIEW-RUBRIC.md`), with operator spot checks of zk-adhoc-10, zk-adhoc-b3 and hbase-adhoc-21; BY_DESIGN/BUG calls marked as judgment calls in the reviews (e.g. solr-adhoc-07/13, hdfs-adhoc-20) can go either way.
