# HBASE-37: active-master info-port znode read

The selected predicate is `MasterAddressTracker.getMasterInfoPort(ZKWatcher)` at
`hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/MasterAddressTracker.java:205`.
It throws the checklist's exact `IOException` at line 206 when the active-master
znode data is null. The original unchanged HBase 2.6.6 JUnit
`TestRSStatusPage#testStatusPage` starts MiniZK, MiniDFS and a one-master
`LocalHBaseCluster`, then calls `HMaster.getActiveMasterInfoPort`. The observed
production path is `HMaster` → `ActiveMasterManager` → the selected static
`MasterAddressTracker` method. The healthy JUnit passed in **52.49 seconds**;
the selected guard ran once on non-null znode data, its normal branch was
covered, and exception line 206 was not covered.

The case-local ByteBuddy Java agent observed real ZooKeeper I/O on the full
active-master znode path. Each fault selector included operation family,
normalized master/RegionServer role, production callsite and hit ordinal.
The injected `NONODE`, `CONNECTIONLOSS` and `OPERATIONTIMEOUT` exceptions were
applied at the actual ZooKeeper API call; HBase's original retry and exception
handling ran unchanged. JaCoCo 0.8.15 collected **production** method and
branch coverage from five relevant classes. No GraphChecker runtime, graph,
closure, static map, skeleton or prewoven class was loaded.

The default upper budget was 80 **effective** trials and at most eight ordered
faults, with a conditional 128/ten-fault extension for late new coverage or
stable I/O. The exact observed-I/O queue exhausted first: **108 distinct
attempted plans, 108 strict full injections, 61 target-retaining effective
trials, 47 target-lost trials, 0 remaining plans**. All 402 requested faults
were applied. Depths were 18×1, 6×2, 12×3, 24×4 and 48×5; the deepest
observed plan had five faults. The three fault kinds accounted for 183
`CONNECTIONLOSS`, 183 `OPERATIONTIMEOUT` and 36 `NONODE` events. Across the
healthy seed and all attempts, measured runtime was **6319.50 seconds**;
30 attempts passed the original JUnit, 75 returned a JUnit failure, and 3
aborted/timed out before a JUnit summary. Valid target-retaining runs added
two production methods and three production branches, with no new stable
I/O site. The final 16 effective trials had no new method, branch or stable
I/O family, so no extension was warranted. This is a `queue_exhausted`
termination at 61/80 effective trials, not a completed 80-trial budget.

The healthy trace contains six eligible target-before I/O selectors: master
and RegionServer `ZKNodeTracker.start` watch/exists, master-znode creation,
the creation follow-up watch, `ActiveMasterManager` watch, and the selected
data read. The independent raw-log audit verified that each healthy selector
was mutated with all three fault kinds. For every effective faulted trace,
every observed I/O selector after the final fault and before the selected
guard was likewise placed in the exact-plan candidate set. Four additional
observed I/O sites only occurred after the target, or in target-lost runs:
master-znode deletion, `getMasterAddress` data read, and master/RegionServer
`ZKNodeTracker.nodeDeleted` watches. They were outside this target-retaining
feedback scope. The original queue has no untested plan within that scope.

**31 trials** threw the exact selected `IOException` after the last injected
fault. Every one directly injected `NONODE` into the same selected znode
read; r002 was independently replayed with the same ordered faults and exact
target exception. Source review shows `ZKUtil.getData` catches
`NoNodeException` and deliberately returns null; the selected method then
throws the specified `IOException`, while `ActiveMasterManager` catches it
and returns info port zero. This is the expected protective path for the
injected missing-znode result, **not a newly confirmed coordination bug**.
There were no other exact target-exception signatures.

The unchanged alternative MiniCluster JUnit
`TestInfoServers#testInfoServersStatusPages` was reviewed but its
`regionserver.jsp` path calls the **instance** tracker getter, not this
selected static guard. `TestMasterAddressTracker` similarly tests the
instance getter. Neither was substituted for the exact-guard healthy seed.

`evidence/hbase37-graphfree-108-queue-exhausted.tar.gz` contains the case-local
agent and sources, original healthy/trial/replay logs, JaCoCo execution files,
the atomic trial checkpoint, timing recovery sidecars, independent audit,
provenance and resume notes. r026's 180-second timeout and r064's 56-second
completed orphan JUnit were measured from raw file timestamps because their
time wrappers exited before printing; the original logs were not edited.
Both rounds were target-lost and excluded from feedback. The archive also
documents r012's no-rerun checkpoint recovery and the supervisor path repair.
