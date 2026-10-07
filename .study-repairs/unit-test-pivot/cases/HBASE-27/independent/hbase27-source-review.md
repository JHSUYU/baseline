# HBASE-27 independent source review of the first RS ZooKeeper fault pilot

Scope: read-only review of released HBase 2.6.6 production source, the
unchanged `TestClusterBootOrder.testBootRegionServerFirst` source, and the
first node1 pilot log. No new JVM was run for this review. The pilot's final
JUnit result and clean replay are pending the case owner.

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

The first pilot's completed JUnit outcome, its timeout or exit code, JaCoCo
feedback, and a clean replay of the exact fault plan remain to be added by the
case owner. Until then, classify the exact target IOException as an observed
candidate with a source-supported expected shutdown explanation, **not a new
bug**. Do not mark the full fuzz budget complete from this one pilot.
