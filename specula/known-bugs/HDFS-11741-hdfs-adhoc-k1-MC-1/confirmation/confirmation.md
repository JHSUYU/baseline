# MC-1 confirmation — REPRODUCED (Level 0)

- **Source**: MC
- **Novelty**: KNOWN (cite: https://issues.apache.org/jira/browse/HDFS-11741; fix-status: fixed)
- **Status**: REPRODUCED
- **Severity**: High
- **Location**: hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/balancer/KeyManager.java:116
- **Reproduction test**: repro/test_bugMC-1_stale_balancer_dek.java (+ runner .sh), escalation level 0
- **Command**: `repro/test_bugMC-1_stale_balancer_dek.sh` (mvn -B -o test -pl hadoop-hdfs-client,hadoop-hdfs -Dtest=TestBugMC1StaleBalancerDek on pristine 595e468)

## Key output (run 2; run 1 identical: 23 ok / 5 IEKE / NO_MOVE_PROGRESS / control SUCCESS)
```
MC1 before-balancer dn=127.0.0.1:35323 used=24000 cap=40000 util=60.0%
MC1 before-balancer dn=127.0.0.1:41705 used=0 cap=40000 util=0.0%
MC1 balancer-1 start at t=1s
MC1 balancer-1 exit=-3 (NO_MOVE_PROGRESS) at t=219s, ran 217s
MC1 after-balancer-1 dn=127.0.0.1:35323 used=21700 cap=40000 util=54.3%
MC1 after-balancer-1 dn=127.0.0.1:41705 used=2300 cap=40000 util=5.8%
MC1 balancer-1 moves: succeeded=23 failed=5 failedWithInvalidEncryptionKey=5
MC1 DataNode-side frames 'BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:484)': 5
MC1 control balancer-2 (fresh DEK) exit=0 (SUCCESS), succeeded=121 failedWithInvalidEncryptionKey=0
MC1 after-balancer-2 dn=127.0.0.1:35323 used=12000 cap=40000 util=30.0%
MC1 after-balancer-2 dn=127.0.0.1:41705 used=12000 cap=40000 util=30.0%
MC1 RESULT: BUG TRIGGERED
2026-11-07 19:56:14,553 [pool-64-thread-1] INFO  balancer.Dispatcher (Dispatcher.java:dispatch(374)) - Successfully moved blk_1073741870_104
2026-11-07 19:56:22,561 [pool-66-thread-1] INFO  balancer.Dispatcher (Dispatcher.java:dispatch(374)) - Successfully moved blk_1073741857_103
2026-11-07 19:56:30,566 [pool-68-thread-1] WARN  balancer.Dispatcher (Dispatcher.java:dispatch(376)) - Failed to move blk_1073741891_1067 wi
2026-11-07 19:56:38,573 [pool-70-thread-1] WARN  balancer.Dispatcher (Dispatcher.java:dispatch(376)) - Failed to move blk_1073742006_1182 wi
2026-11-07 19:56:46,581 [pool-72-thread-1] WARN  balancer.Dispatcher (Dispatcher.java:dispatch(376)) - Failed to move blk_1073741921_1097 wi
2026-11-07 19:56:54,588 [pool-74-thread-1] WARN  balancer.Dispatcher (Dispatcher.java:dispatch(376)) - Failed to move blk_1073742006_1182 wi
2026-11-07 19:57:02,595 [pool-76-thread-1] WARN  balancer.Dispatcher (Dispatcher.java:dispatch(376)) - Failed to move blk_1073741990_1166 wi
2026-11-07 19:56:30,566 [pool-68-thread-1] WARN  balancer.Dispatcher (Dispatcher.java:dispatch(376)) - Failed to move blk_1073741891_1067 wi
2026-11-07 19:57:03,650 [DataXceiver for client /127.0.0.1:38750 [Replacing block BP-73528545-130.127.134.9-1794081200992:blk_1073742016_119
2026-11-07 19:56:30,566 [org.apache.hadoop.hdfs.server.datanode.DataXceiver@5673f591] ERROR datanode.DataNode (DataXceiver.java:run(323)) - host1.foo.com:41705:DataXceiver error processing unknown ope
Caused by: org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException: Can't re-compute encryption key for nonce, since the required block key (keyID=1211991252) doesn't exist. Current key: 1211991255
	at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:484)
	at org.apache.hadoop.hdfs.security.token.block.BlockPoolTokenSecretManager.retrieveDataEncryptionKey(BlockPoolTokenSecretManager.java:142)
```
