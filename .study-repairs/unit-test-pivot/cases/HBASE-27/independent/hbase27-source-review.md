# HBASE-27 independent source review of four RS ZooKeeper fault trials

Scope: read-only review of released HBase 2.6.6 production source, the
unchanged `TestClusterBootOrder.testBootRegionServerFirst` source, and all
four archived node1 fault logs. No JVM was run for this review. All 12
archived files passed `sha256sum -c independent/evidence/SHA256SUMS`.

## Exact observed chain

The node1 pilot log at
`/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-27/independent/logs/zk-master-rs-pilot.log`
records these events in order:

1. `ZK_RESPONSE~REGIONSERVER~/hbase/master~ZKNodeTracker.nodeCreated~1`
   matched and applied as `KeeperException.ConnectionLossException` at the
   successful `ZKUtil.getDataAndWatch` response. A separate `MASTER` callback
   is observed but is not selected.
2. The RegionServer logs `ABORTING ... Unexpected exception handling
   nodeCreated event` with a stack through `ZKUtil.getDataAndWatch` and
   `ZKNodeTracker.nodeCreated`. It then logs `STOPPING` and `STOPPED` for the
   same reason.
3. The target probe reports `GUARD_EVAL ... tracker=/hbase/master
   stoppedSnapshot=true` and `TARGET_THROW ... IOException: Received the
   shutdown message while waiting.`

This sequence matches the released source directly:

```text
ZKNodeTracker.nodeCreated() [199–207]
  getDataAndWatch() throws KeeperException
  catch → abortable.abort("Unexpected exception handling nodeCreated event", e)
              ↓
HRegionServer.abort() [2828–2871] → stop(reason, true, null)
              ↓
HRegionServer.stop() [2602] → this.stopped = true
              ↓
HRegionServer.blockAndCheckIfStopped() [1050–1054]
  blockUntilAvailable(...) returns null; stopped is true
  → explicit IOException("Received the shutdown message while waiting.")
```

The final IOException is a deliberate shutdown guard after the injected
ZooKeeper response error has already caused the RegionServer to abort. It is
not, by itself, evidence of an independent ad hoc coordination bug. The check
does use the master znode tracker, but this observed true branch follows the
local `stopped` flag written by the abort path. A static candidate rule that
selects the tracker wait plus `stopped` guard would overstate this pilot if it
ignored that direct causal path.

## Independent raw-trace cross-check

The unchanged healthy workload records six ZooKeeper response events in five
stable families: two Master families and three RegionServer families (the
RegionServer `getData` family appears twice with distinct ordinals). All
three RegionServer families were selected once; the first was replayed in a
fresh fixture. I checked the following event order directly in the archived
gzip logs rather than inferring it from `result.json`:

| Run | Exact fault | Postfault target | JUnit / elapsed |
| --- | --- | --- | --- |
| `zk-master-rs-pilot` | RS `/hbase/master` `nodeCreated`, matched/applied at log lines 540–541 | RS abort and stop at 544/598; guard true and exact IOException at 599–600 | runner timeout 124 / 361.69 s |
| `zk-master-rs-replay` | same selector, matched/applied at 539/541 | RS abort and stop at 544/598; guard true and exact IOException at 682–683 | runner timeout 124 / 121.37 s |
| `zk-running-rs-pilot` | RS `/hbase/running` `nodeCreated`, matched/applied at 696/699 | RS abort and stop at 701/750; guard true and exact IOException at 835–836 | runner timeout 124 / 121.25 s |
| `zk-master-getdata-rs-pilot` | RS `/hbase/master` `getData`, matched/applied at 703–704 | RS abort and stop at 705/752; both target guard evaluations were **before** injection and no postfault target occurred | runner timeout 124 / 121.63 s |

The fresh replay repeats the first exact target exception and its causal
sequence. The `getData` attempt is a strict injection but cannot count as
target-retaining evidence. The first three exceptions follow the injected RS
shutdown path; matching the target is not enough to call any of them a new
coordination bug.

## Original JUnit context and limits

The original `TestClusterBootOrder.testBootRegionServerFirst` creates one
RegionServer and one Master. Its healthy runs passed 2/2; each reached the
selected guard on a false `stopped` value. The test starts the RegionServer
first, then Master, then waits for Master initialization and RS online status.
`waitForClusterOnline()` has an unbounded loop around Master initialization.
After the sole RS aborts, a Master log saying `No servers available; cannot
place 1 unassigned regions` and a stalled JUnit are consistent with this test
topology and the injected failure. Such an outcome does not establish a new
bug unless a separate source/replay argument shows that this fault should
have been tolerated by the original workload.

The pilot's original thread dump at
`node1:cases/HBASE-27/independent/logs/zk-master-rs-pilot.thread_dump.txt`
places the JUnit execution thread at
`TestClusterBootOrder.waitForClusterOnline:90 → testBootRegionServerFirst:106`.
The contemporaneous Master log repeats `No servers available; cannot place 1
unassigned regions.` This locates the stall at the one-RS workload's online
wait rather than a second, independently evidenced target failure.

Both unchanged healthy JUnit runs passed. All four fault runs were stopped by
their bounded runners rather than completing the original JUnit; the first
used 360 seconds, and the later three used 120 seconds. The archived JaCoCo
exec files are nonempty, and the case owner's analyzer fixes the production
scope to `HRegionServer`, `ZKNodeTracker`, and `ZKUtil`. Its reported union
grows from 169 methods / 357 branches in healthy 2 to 172 / 374 across the
fault runs (+3 methods, +17 branches); 14 new branches belong to the three
target-retaining runs, while the last 3 arise in the target-lost `getData`
run. The first pilot covers both outcomes of line 1052 and the explicit
exception at line 1053. I checked the scope and archive integrity, but did
not rerun the Java coverage analyzer during this read-only review.

**Final independent disposition:** `source_excluded`, `bug_mark=none` is
supported for this original workload. B2 reads one RegionServer's local
`stopped` lifecycle flag. The three exact target exceptions follow the
source's explicit abort and stop path; the fourth fault does not reach B2
after injection. The one-RS test's timeout follows loss of its sole server.
These four attempts screen out this site's observed path as non-ad-hoc; they
are not a completed 80-trial quality negative and do not establish that all
HBase fault behaviors have been covered.
