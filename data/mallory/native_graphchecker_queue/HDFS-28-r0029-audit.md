# HDFS-28 r0029 raw target throw review

Verdict: Exact target IOException observed; not a confirmed ad hoc coordination bug. The throw occurs during the unchanged JUnit's intentional MiniDFSCluster shutdown and is caught/logged by a background recovery task. The JUnit passes.

## Trace

- Healthy r0000: 5 TARGET_CHECK rows, no TARGET_THROW, JUnit passed.
- r0029 planned 3 faults. FAULT_APPLIED seq 44: dn0 sendHeartbeat RPC ServiceException. FAULT_APPLIED seq 193: dn1 BlockReceiver.receivePacket IOException. The planned dn2 BlockMetadataHeader.readHeader fault did not apply; result status is unmatched, applied_prefix_count=2, strict_injection=false.
- r0029 fault-events.jsonl contains 13 TARGET_CHECK rows and one exact TARGET_THROW seq 417 at BlockRecoveryWorker.getDatanodeID#u12 on dn1 with actualExceptionClass=java.io.IOException. This is the only raw TARGET_THROW in the 56 fault trials of that terminal campaign.
- r0029 stdout.log: MiniDFSCluster.shutdown starts at 02:52:03.381 (line 2734); DataNode 1 removes the block pool at 02:52:03.513 (line 2908); getDatanodeID logs No block pool offer service for bpid at 02:52:03.537 (line 3016). A background RecoveryTaskContiguous catches/logs the exception.

## Source attribution

- Original TestPipelinesFailover.testLeaseRecoveryAfterFailover, lines 314-317, calls cluster.shutdown in finally.
- Original BlockRecoveryWorker.getDatanodeID, lines 535-541, throws the exact IOException when datanode.getBPOfferService(bpid) returns null.
- DataNode.shutdownBlockPool, lines 2147-2148, calls BlockPoolManager.remove; BlockPoolManager.remove, lines 89-94, removes the bpid map entry. This shutdown path directly explains the target condition.

Two applied faults may affect background recovery timing, but healthy absence does not establish causality. The observed throw is after teardown starts, with no failed foreground operation or persistent wrong state. The third fault missed, so the campaign did not build a faulted graph for this trial. In the old result, target_exception_triggered=false means no admitted strict target exception, not no raw event.

A generic two-fault-prefix replay is possible using the existing REGION_STATE fault-plan protocol with an isolated fresh trial and the same pins. It was intentionally not run: a teardown-only recurrence would not resolve the bug question. A useful follow-up would require a strict matching replay whose target exception precedes cluster shutdown. No case-specific instrumentation is required.

Evidence root: /proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs28-native-campaign-v1/campaign/trials
Source checkout: /users/ZhenyuLi/.mallory-worktrees/hdfs, HEAD 9d50c6884666e794e45102260a4017bb31802e1b
Campaign terminal checkpoint: /proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs28-native-campaign-v1/campaign/checkpoint.json
