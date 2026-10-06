# ZOOKEEPER-11: current epoch temporary-file check

The original ZooKeeper 3.8.7
`CurrentEpochWriteFailureTest.testReadCurrentEpochFromAcceptedEpochTmpFile`
JUnit method runs an embedded three-peer quorum. The selected
`QuorumPeer.loadDataBase()` guard is at source line 1169 and its
`IOException` is at line 1174. The healthy test passed and reached the
guard without taking its fatal outcome.

Five distinct file-I/O exception trials each matched and applied one
planned fault. Two retained the selected guard after injection and three
ended before it; none executed the selected exception. The scoped
instrumentation observed 12 new branch outcome pairs overall and one in
the measured target/file-read methods. The five trials and healthy setup
took 420.606 seconds. Exact selectors, hit ordinals, elapsed times, JUnit
exits, target retention, and coverage deltas are in [trials.json](trials.json).
Compact execution outcomes from the removed historical run archive are in
[evidence/legacy-execution-summary.json](evidence/legacy-execution-summary.json).

The historical five-trial campaign is below the current 48-trial budget.
Additional relevant I/O sites and ordered fault sequences remain to be
checked. No new bug was confirmed.
