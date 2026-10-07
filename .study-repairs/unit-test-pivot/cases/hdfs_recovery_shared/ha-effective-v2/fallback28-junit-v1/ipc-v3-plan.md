# HDFS-28 alternate JUnit: IPC successor after queue exhaustion

The original `TestPipelinesFailover#testLeaseRecoveryAfterFailover` campaign
reached a complete, natural `queue_exhausted_inconclusive` checkpoint after
126 attempts and 23 same-owner postfault HDFS-28-effective trials. Its V2
HDFS RPC singleton and file-descendant queue is empty; the existing
`successor-v2.log` ends with that terminal reason. The old 126 attempts are
not rerun.

`ipc_successor_v3.py` is a versioned candidate expansion. Its offline
dry-run from this checkpoint found 23 previously unseen one-fault
`HADOOP_IPC:REQUEST` selectors in prior **exact and HDFS-28-effective**
original JUnit traces. Each has a verified recovery owner, block/recovery
root, and a later HDFS-28 guard on that same owner/root; the complete
selector ID is absent from the old `seen` ledger. The dry-run preserved
completed, queue, seen, active, coverage and I/O prefixes and did not write
to the live checkpoint. It uses the existing 4 RPC : 1 FILE lane, preferring
HDFS RPC singleton, then new IPC singleton, and retaining file plans when
new feedback creates them. The attempt cap stays 320, effective goal 80,
depth max 8, and identity gate unchanged.

The earlier one-fault HADOOP IPC pilot missed its exact selector, so these
new plans have an acknowledged low-match risk. A miss does not count as an
effective trial; queue exhaustion or cap before 80 must be reported
inconclusive. The actual handoff requires a full independent raw audit and
atomically records predecessor/new checkpoint SHA and every admitted plan.
