# HDFS-07: recovery check under the original cluster test

The selected check is the `AssertionError` guard in
`Journal.acceptRecovery(RequestInfo, SegmentStateProto, URL)` at Hadoop
3.4.3 source line 926. The workload is the unchanged
`TestQuorumJournalManager.testRecoverAfterIncompleteRecovery` JUnit method
with its three-JournalNode `MiniJournalCluster`. The healthy test reached
the guard once on its nonfatal side in 7.439 seconds.

The earlier campaign ran 24 fault trials: 25 fault events were requested,
24 matched and applied, 23 trials met the strict injection criterion, and
three retained the selected guard after injection. Twenty trials ended
before that guard. None reached the fatal target outcome. The target-retaining
trials added no production method or branch outcome relative to the healthy
run; a synthetic injection guard supplied the only raw branch difference.
Measured campaign time was 2295.625 seconds, including 169.891 seconds of
fault-test runtime.

[trials.json](trials.json) records the individual fault outcomes and
[trace-archive-manifest.json](trace-archive-manifest.json) records archived
trace checksums. The original test and alternate-test review are retained in
[result.json](result.json). The historical 24-trial search is below the
current 48-trial budget and leaves further I/O sites and ordered sequences to
check. No new bug was confirmed.
