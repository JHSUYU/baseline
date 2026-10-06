# HDFS-32: original JUnit independent fault campaign

The selected `DataNode.deleteBlockPool` check at Hadoop 3.4.3
`DataNode.java:3819–3824` throws an `IOException` while its block pool is
still running. The correct original workload is
`TestDeleteBlockPool#testDeleteBlockPool`, which starts two NameNodes and
two DataNodes. It expects this exact exception twice, once per DataNode, then
refreshes the NameNode configuration and tests block-pool deletion. The
earlier `testDfsAdminDeleteBlockPool` mapping does not exercise this same
sequence.

The current campaign runs the original JUnit with case-local ASM target and
I/O probes plus JaCoCo production coverage, independent of GraphChecker and
skeleton artifacts. The healthy test passed; it reached the guard five times
and the selected throw twice. Trial validity requires every planned I/O
fault to match and apply in order and the same second DataNode guard to be
reached after the final fault. Expected target exceptions are subtracted
from any new bug assessment. See [independent/README.md](independent/README.md)
and [independent/evidence/healthy-baseline.json](independent/evidence/healthy-baseline.json).

The first recorder interfered with `BPServiceActor` cleanup on an interrupted
thread. Its 11 trials are quarantined under
`independent/evidence/invalid-probe-interference` and excluded from current
budget and bug counts. The corrected recorder passed an interrupted-thread
logging-failure smoke check and the original healthy JUnit. The original
three static-analysis recorder trials remain in
[legacy-graph-result.json](legacy-graph-result.json), also excluded.

The 80-trial campaign is complete. All 80 attempts are recorded, 74 matched
and applied every planned fault in order, and 47 also reached the same second
DataNode guard after the final fault. Every target-retaining trial passed the
original JUnit and produced exactly one selected `IOException`, matching the
healthy run. No new failure of the selected check was found. The late trials
added no production probe, method, or line coverage and no stable new I/O
family, so the conditional 128-trial extension did not apply. See
`independent/evidence/final-audit.json` and the checkpoint at
`independent/evidence/campaign-state.json`.

Of 21 JUnit failures, 17 directly reported the injected RPC `IOException`
before the selected guard, three timed out before it, and one failed a
different assertion. In trial 047, the injected write-pipeline RPC failure
caused `DataStreamer` to exclude the first DataNode, and `/alpha` was
allocated only on the second. The test then expected a `force=false` block
pool deletion on the first DataNode to fail because of block files there;
the dataset source permits deletion when that directory is empty. This is a
source-reviewed test assumption under the injected fault, and the selected
second-DataNode guard was not reached. It is not counted as an HDFS-32 target
bug.

`result.json` was updated atomically after each trial and is the source for
the 102-case table.
