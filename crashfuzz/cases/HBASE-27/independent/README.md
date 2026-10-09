# HBASE-27: source excluded after original-cluster JUnit probes

**Disposition:** `source_excluded`, `bug_mark=none`. The selected true branch is
an expected shutdown check on one RegionServer's local lifecycle flag. Four
exact fault attempts covered all three RegionServer ZooKeeper response
families observed in the unchanged workload. Three retained and threw the
selected target exception, including one clean replay; the fourth occurred
after the target's healthy evaluations and lost the postfault target. These
four attempts are a bounded eligibility audit, **not** an 80-trial quality
negative or a confirmed new bug.

## Original workload and exact target

The released HBase 2.6.6 original JUnit is
`org.apache.hadoop.hbase.TestClusterBootOrder.testBootRegionServerFirst`.
It runs MiniDFS and MiniZooKeeper with a `LocalHBaseCluster`, starts its sole
RegionServer, waits four seconds, starts a Master, then waits for cluster
initialization. The selected production check is B2 in
`HRegionServer.blockAndCheckIfStopped` at line 1052:

```java
while (tracker.blockUntilAvailable(this.msgInterval, false) == null) {
  if (this.stopped) {
    throw new IOException("Received the shutdown message while waiting.");
  }
}
```

Two unchanged healthy runs passed JUnit (1/1 each), evaluated this exact
guard twice each with `stopped=false`, and threw no target exception. The
second healthy run took 50.60 s and observed six relevant ZooKeeper response
events at five stable families. The probe records event, node role, znode
path, callsite, and occurrence ordinal; the ordinal is used for exact
matching, not for claiming a new I/O family. Role separation prevents a
`MASTER` callback from matching the target `REGIONSERVER` callback.

## Fault attempts and coverage feedback

Every attempt injected `KeeperException.ConnectionLossException` at a
successful response with the exact observed selector. All four had
`FAULT_MATCHED` and `FAULT_APPLIED` in the raw log. `Target after` means the
target threw its selected `IOException` after that exact injection. Each
faulted original JUnit was stopped by its bounded runner with exit 124 after
its only RegionServer aborted; it did not report a JUnit assertion result.

| Run | Exact selector suffix after `ZK_RESPONSE~REGIONSERVER~` | Target after | Original JUnit | Wall time | Cumulative production methods/branches |
| --- | --- | --- | --- | ---: | ---: |
| Healthy 1 | no fault | 2 false evaluations | 1/1 pass | 46.45 s | not used for fixed coverage comparison |
| Healthy 2 | no fault | 2 false evaluations | 1/1 pass | 50.60 s | 169 / 357 |
| Master znode pilot | `/hbase/master~ZKNodeTracker.nodeCreated~1` | exact `IOException` | timeout 124 | 361.69 s | 172 / 370 |
| Master znode clean replay | same selector, fresh fixture | exact `IOException` | timeout 124 | 121.37 s | 172 / 371 |
| Running znode alternate | `/hbase/running~ZKNodeTracker.nodeCreated~1` | exact `IOException` | timeout 124 | 121.25 s | 172 / 371 |
| Master `getData` alternate | `/hbase/master~ZKNodeTracker.getData~1` | lost; guard had run twice before injection | timeout 124 | 121.63 s | 172 / 374 |

The fixed JaCoCo production scope is `HRegionServer`, `ZKNodeTracker`, and
`ZKUtil`. The fault-run union adds 3 methods and 17 branches over healthy 2.
The last 3 branches came from the target-lost `getData` run; the
target-retaining union added 14 branches. The first pilot covered both
outcomes of line 1052 and every instruction of the explicit exception on
line 1053. No fault run revealed a new stable response family.

## Why the true branch is expected

Released source declares `HRegionServer.stopped` as a local volatile field
at line 369. `HRegionServer.stop` writes `stopped=true` at line 2602. In
the three target-retaining runs, the injected exception reaches
`ZKNodeTracker.nodeCreated`'s catch at lines 198–207, which calls
`abortable.abort`; `HRegionServer.abort` calls `stop`, and the waiting
RegionServer then evaluates B2 with its own `stopped=true`. The first pilot
and fresh clean replay show this chronology in their raw event traces.
The final `getData` selector instead reaches the analogous
`ZKNodeTracker.getData` abort catch after the two healthy B2 evaluations;
no postfault B2 evaluation appears.

```text
RS ZooKeeper response error → ZKNodeTracker catches KeeperException
  → same RS aborts → same RS writes stopped=true
  → B2 intentionally throws shutdown IOException (if still waiting)
```

The target predicate is this local lifecycle flag, not a multi-hop
cross-actor coordination state. The two other healthy response families
belong to the Master actor; the three RegionServer families were tested.
Changing the injected znode or callsite within these observed families
does not change the B2 dependency on the local `stop` write. This is a
source-level candidate-screening conclusion for this original workload,
not a claim that every possible HBase I/O path was fuzzed.

The test's only RegionServer cannot serve metadata after it aborts. The
first pilot's preserved thread dump places the JUnit thread in
`TestClusterBootOrder.waitForClusterOnline:90` and the Master log reports
`No servers available; cannot place 1 unassigned regions`. The JUnit's
online wait has no internal timeout. The runner timeouts therefore follow
the injected loss of the test's sole server, not a separate proven hang.

## Reproduction and evidence

`run.sh` launches the unchanged original JUnit with a case-local ByteBuddy
target/I/O probe and JaCoCo. It uses no GraphChecker JAR, region skeleton,
static scope map, or prewoven classes. `pilot.sh`, `replay.sh`, and
`alternate_pilots.sh` record the exact selectors; `result.json` holds every
attempt's timing, outcome, and coverage counts. Gzipped raw logs, the
first pilot's original thread dump, and JaCoCo exec files are in
`independent/evidence/`; `SHA256SUMS` records their hashes. Uncompressed
raw logs remain in the isolated node1 case directory under `logs/`.

An independent source review is in `hbase27-source-review.md`. HBASE-17 and
HBASE-32 have separate work directories, fixtures, and checkpoints.
