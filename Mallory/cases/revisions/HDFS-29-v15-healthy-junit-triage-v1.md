# HDFS-29 v15 healthy JUnit failure triage (v1)

Status: read-only review of the archived v15 healthy seed and Hadoop 3.4.3 source at commit `9d50c6884666e794e45102260a4017bb31802e1b`. This review did not run a JVM or change the active case, adapter, or JUnit test.

## Result and classification

`calibration_v15/HDFS-29` is **not a valid healthy seed**. The direct `surefire:test` command returned 0 and printed `BUILD SUCCESS`, but the archived Surefire XML and `junit-receipt.json` record **one executed test, zero failures, one error**. JUnit's `@Test(timeout=60000)` raised `TestTimedOutException` while the test thread waited in `GenericTestUtils.DelayAnswer.waitForCall()` at `TestPipelinesFailover.java:380`. The outer trial took 68.577 seconds; the test ran for 60.416 seconds.

The exact selected check **did execute without throwing**: trace event `HDFS-29-r0000:2340` is `TARGET_CHECK` for `BlockRecoveryWorker#getActiveNamenodeForBP` on `hdfs-cluster-1/dn1`, epoch 0, with the concrete `hdfs-block-recovery:1` occurrence. A preceding observed RPC graph and 81 eligible doors were recorded. The same trace shows the recovery thread sent Hadoop IPC request `53826cb25fc344b2915bf7d7e052a148:90:0` from dn1 at seq 2575, nn0 received it at seq 2613, and `NameNodeRpcServer#commitBlockSynchronization` began on nn0 at seq 2636. These events occurred about 11.6 seconds after the first traced event, well before JUnit's 60-second timeout. There is no selected target throw, no injected fault, and no evidence of the target check failing.

The test installs a Mockito `DelayAnswer` spy on the DataNode-to-active-NameNode proxy and waits for its `commitBlockSynchronization` call; `waitForCall()` blocks until the answer's `fireLatch` is counted down. The trace proves a real commit RPC reached nn0, yet this test's spy callback did not release the latch. The archived artifacts cannot distinguish a Mockito argument/proxy mismatch from a different recovery primary or an instrumentation-sensitive scheduling race. The test computes an *expected* primary from the most recent heartbeat before the recovery, while the actual recovery and heartbeats are asynchronous. This is a **workload synchronization / harness validity failure with unresolved precise cause**; it is not evidence of a product defect or a Mallory target exception. A JVM rerun or spy identity/argument observation would be needed to separate these hypotheses.

An earlier archived healthy run of this same JUnit under the older adapter had `Tests run: 1, Errors: 0` in 14.918 seconds and two target checks, but its target actor was `unknown`, so it was correctly rejected for identity. That run shows the test can pass; it does not validate v15 or prove that v15 instrumentation alone caused the timeout. The old run had two server commit calls (nn0, then nn1); v15 had only the nn0 call before timing out. Treat Maven exit status as insufficient for scientific completion.

## Existing MiniCluster workload options

1. **First candidate:** `org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testLeaseRecoveryAfterFailover` (`TestPipelinesFailover.java:275-315`). It starts the same 3-DataNode HA MiniDFSCluster, creates an under-construction file, changes the active NameNode, and drives `recoverLease` until success. The product path `BlockRecoveryWorker.RecoveryTaskContiguous#syncBlock` calls `getActiveNamenodeForBP` before `commitBlockSynchronization`. This test has no `DelayAnswer.waitForCall` dependency. Its JUnit timeout is 30 seconds, so a fresh instrumented healthy seed must still prove it passes and reaches the exact selected check on a named DataNode.
2. **Fallback:** `org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2#testRecoveryWillIgnoreMinReplication` (`TestBlockRecovery2.java:389-458`). It starts a 5-DataNode MiniDFSCluster, creates an unclosed file, stops two replicas, shortens lease time, and waits for recovery and replication. It has a 300-second JUnit timeout and no delayed Mockito commit latch. It exercises the block-recovery path by source, but target reach, runtime actor, exact nonthrowing outcome, and cost remain unverified. This may be much slower; do not assume it meets the per-trial budget.

For either option, preserve the v15 failed seed and old identity-invalid seed as distinct evidence. Run an isolated healthy calibration first. Promote only on JUnit `tests>0, errors=0, failures=0`, exact check on a named DataNode, zero selected throws, and a qualifying observed closure. Do not launch full fuzz from either archived seed.

## Evidence hashes

All paths in the first table are under `data/mallory`.

| Archived file | SHA-256 |
|---|---|
| `calibration_v15/HDFS-29/config.json` | `642be378733ef86ab6192fe2657b112db34916c7178a3285d01a9baa54c15bb7` |
| `calibration_v15/HDFS-29/result.json` | `3471707d666ce9eee1c60f35850577c58661759c1c5996440ea366d07b6cd7a8` |
| `calibration_v15/HDFS-29/trials/r0000/result.json` | `008cbcbc1adc368d4a94c8522d3bbc3b3814cd3c6b4a9cce44b51dfab3ef2660` |
| `calibration_v15/HDFS-29/trials/r0000/stdout.log` | `2a65364acc4e60cdfd2c2b9dcae3af5e633e8db65bb4b6147805dc5631551694` |
| `calibration_v15/HDFS-29/trials/r0000/stderr.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `calibration_v15/HDFS-29/trials/r0000/events.jsonl.gz` | `8023ddbc2b236a9b71d3544b3da112de9759d8d661860ae547c8e1be8d1033a8` |
| `calibration_v15/HDFS-29/trials/r0000/junit-receipt.json` | `633f300d7e1dff0f6546579fe7f2609d57c496a78a9dc7f2d5f6326b0ca093b8` |
| `calibration_v15/HDFS-29/trials/r0000/junit-reports/000-TEST-org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover-mallory_0000_ec68dfb2ccec44ef92d5387732ee330e.xml` | `0aa8ba1bee17e7e5e2133ac33b18e8b23ea25b02f79ac09d6cf03ccdceabfa9b` |
| `calibration/HDFS-29/trials/r0000/stdout.log` | `8e53a0bee0d0c8ec8e4e683f37727a898fda0d19a9e094f225cc5ada660e6fa0` |

Source-file hashes are for the unmodified Hadoop source tree `/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3`. Line-range hashes are SHA-256 of the inclusive lines with original line endings.

| Source path after Hadoop root | File SHA-256 | Lines | Line-range SHA-256 |
|---|---|---:|---|
| `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.java` | `5815550fb06429b227cd7c632bf0fe1523d0417c7da0c37105ff1c43db5ec49a` | 275-315; 321-399 | `3baa4fc0df8456232e4addac47ca221d76bbed1b2af2f94cd4b119479bda3565`; `9bb9da8474462fbe2250fe21eda5656dec6aa618f24eb2dab3bc6bcb6cb45173` |
| `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestBlockRecovery2.java` | `039333d254536eaa27dd9bd2665215080bf867f530dc503b35065695c379cd96` | 389-458 | `55dfb257225f9f872695e83aa124f784f7be8c215f6a8d60cb7cf10dc8f86f85` |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.java` | `928a3e6d159a47a2f8c88e1720211ddf7af62129a5ed2d5a9f133f7ada60499b` | 180-208; 308-319; 574-588 | `207aa907748d90c109d069ebacdc7fbfe29e9a990b1afc662a1661173d16cf89`; `48063e26863d4880b8fa9bb78e6b3afe31da1375b9c3f9bb93c2e05dbc17b72d`; `cdb56df53be3bee89a4a585e8f2cecdb87eda4a2326497e836cad8c4d254249d` |
| `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/InternalDataNodeTestUtils.java` | `3562ebbb1b240402ec1c103cf21426889063d96de55bdc5b6ead334e380b293d` | 95-120 | `323f0c1a7a981634da8712b80b9e8249c678a2d21345227d92a79b0db96cd88c` |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java` | `21c5c65c5c023cc004aee8ca4814037de86de811db0e7960cb17c2909ccb8294` | 519-533 | `0cd9425ef81fe84a3f5154e1adf496064e30e1ec007d0df9cb0af3fb6f2e0b15` |
| `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java` | `fbcb03b86822e71e451242142752706b61c3f3f096d0219f5d90344bc59bb833` | 215-231; 292-305 | `aa0a45e08a7ea170b8423cf1799c1afaac04fc2a8730b5a35742ec84e91a4a5c`; `033c9e9215edfafd095597a68cd6c74be17aeb33c64d9fcf51abff8ef27a80b8` |
| `hadoop-common-project/hadoop-common/src/test/java/org/apache/hadoop/test/GenericTestUtils.java` | `9f66ae9e8ec335e6ff6d4be7dcd631c2c15eb7505d6bbf8a43ccaacb089a0288` | 519-558 | `7377bb38727f2f569daa4c44f207fcb2a04b031a3cbaa96dabeff8ef8e5658d3` |
