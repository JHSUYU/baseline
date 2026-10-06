# HBASE-29: replay RPC mixed-region check

The selected check is in `RSRpcServices.replay` from unchanged HBase 2.6.6
commit `d5f63f523c065f963992ea4e74db268d17816631`. The checklist anchor
at line 2263 is the last line of the `NotServingRegionException` message;
the actual comparison is at line 2260. For each WAL entry, the receiver
compares its encoded region name with the first entry's. A mixed-region
request is rejected before applying that entry.

The unchanged original embedded-cluster JUnit
`TestRegionReplicaReplicationEndpoint#testRegionReplicaReplicationWith2Replicas`
starts two RegionServers, creates a primary and a replica, writes 1000 rows,
and waits for replication. The healthy run took 77.49 seconds and passed.
It issued 110 replay RPC calls to replica 1; each call had one distinct
encoded region name. A probe at `WALSplitUtil.getMutationsFromWALEntry`,
immediately after the comparison, observed 1002 per-entry guard passes.
JaCoCo covered the actual comparison at line 2260 (six instructions and its
false branch); the exception-message line 2263 was not covered, as expected.

The case-local ByteBuddy agent intercepts the real server-side replay RPC
method. It derives a stable logical selector from the table, replica ID,
production RPC entry, and hit ordinal after the receiver resolves the region.
It records the request's entry count and number of distinct encoded regions,
and can inject an `IOException`, `EOFException`, or `FileNotFoundException`
wrapped in the declared RPC `ServiceException`. It also records whether a
post-fault replay reaches the per-entry check and whether the exact
mixed-region `NotServingRegionException` is thrown. JaCoCo records production
method and branch coverage in `RSRpcServices`, `WALSplitUtil`, and the region
replica replication endpoint. There is no GraphChecker JAR, prewoven class,
skeleton, static map, closure, or graph feedback.

The graph-free campaign seeds from observed healthy replay RPCs and mutates
one ordered fault at a time. Feedback is admitted only when all planned
runtime selectors and fault kinds match and the selected check executes
after the final fault. The default budget is 80 effective trials, at most
240 attempts, and eight ordered faults per sequence. Late new production
method/branch coverage or stable I/O family in the final 16 effective trials
extends the same checkpoint to 128 effective trials and ten faults. Plans,
matches, target outcomes, JUnit status, coverage, and elapsed time are
atomically recorded after each run. `hbase29_fuzz` and
`hbase29_supervisor` tmux sessions keep the campaign recoverable. Per-trial
MiniHBaseCluster data is removed only after checkpointing to protect the
limited root filesystem space.
