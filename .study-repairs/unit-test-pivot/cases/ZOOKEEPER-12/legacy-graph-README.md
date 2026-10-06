# ZOOKEEPER-12: accepted and current epoch check

The original ZooKeeper 3.8.7
`CurrentEpochWriteFailureTest.testReadCurrentEpochFromAcceptedEpochTmpFile`
JUnit method runs an embedded three-peer quorum. The selected check is
`QuorumPeer.loadDataBase()` at source line 1193, with an `IOException`
at line 1194 when `acceptedEpoch < currentEpoch`. The healthy test reached
the guard without taking its fatal outcome.

Six exact-selector trial sequences matched and applied 12 `IOException`
fault events. Five retained the target after their last fault; none took
its fatal branch. The four-write sequence applied four faults, retained the
target, and later observed a successful write retry. Its exact plan and
outcome are preserved in
[evidence/four-accepted-writes.json](evidence/four-accepted-writes.json).
The full six-trial ledger is [trials.json](trials.json).

Scoped coverage increased by two branch outcome pairs in the measured
target and epoch-file methods, 30 branch outcome pairs overall, and one
method entry. The historical fault campaign records 1381.884 seconds; the
larger 3299.649-second total includes separate instrumentation development.
[result.json](result.json) retains the timing breakdown. The current
48-trial budget and further I/O families remain open. No new bug was
confirmed.
