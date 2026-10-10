# HBASE-27 tracker identity and event-time audit

This audit uses the one completed `TestClusterBootOrder#testBootRegionServerFirst`
healthy run in `data/mallory/calibration_hbase27_tracker_identity_v2/HBASE-27`.
It does not launch a JUnit or fault trial. Run
`python3 verify.py /path/to/HBASE-27/trials/r0000/events.jsonl.gz` to
recheck the immutable gzip SHA and the event sequence.

The healthy JUnit passed (1 test, 0 failures/errors). The exact named `rs0`
target check in `HRegionServer.blockAndCheckIfStopped` executed twice, at
events 4 and 7. The typed `ZKNodeTracker.nodeCreated@getDataAndWatch`
ConnectionLoss doors executed later, at events 9 and 20. The overlay's
`IdentityHashMap<tracker, waiters>` yields unique same-tracker transfers
`9 -> 11 -> 14` and `20 -> 22 -> 24`; the claims are on `rs0` in the target
region. The first region then exits at 16 and the second at 26. Neither
transfer is followed by another exact target check. Therefore these doors
have **zero observed event-time paths to a target check** in this run. The
earlier `ZKNodeTracker.start@75` doors at 1 and 2 are on the constructor
thread and have no observed object/field handoff to the target thread.

The two tracker objects on the region server are `masterAddressTracker`
and `clusterStatusTracker`, created and started in the `HRegionServer`
constructor at lines 724–728. `initializeZooKeeper` passes them in turn to
`blockAndCheckIfStopped` at lines 1005 and 1009. In that method, a null
`blockUntilAvailable(msgInterval, false)` result reaches `if (this.stopped)`
at line 1052. With `refresh=false`, the wait loop does not execute the
conditional `checkExists/getDataAndWatch` calls. A successful
`nodeCreated` callback writes nonnull tracker data and wakes the waiter;
that explains why the healthy run exits the region after each transfer.

An injected `ConnectionLossException` at `nodeCreated@getDataAndWatch`
could instead enter `ZKNodeTracker`'s catch, call its RegionServer
`abortable.abort`, set the RegionServer's volatile `stopped` field through
`HRegionServer.stop`, and later reach the target throw after a null wait.
This is a **source-predicted fault path**, not an observed target-retaining
trial. The thrown `IOException` is the code's explicit shutdown response.
The selected JUnit's `waitForServerOnline` loop exits on `isStopped()` and
does not independently assert that the service recovered, so this exception
alone cannot establish a new coordination bug.

**GO gate for any full campaign:** an isolated healthy workload must record
a typed I/O door, a unique same-tracker or exact field handoff, and a later
exact named `rs0` target check in the same causal chain. A subsequent fault
pilot must show the chosen exception was effective and that the target was
reached after injection. Reporting a bug additionally requires source and
replay evidence for an outcome beyond the expected shutdown. The present
trace fails the first gate; full fault testing remains on hold. Changing
only the actor name or adding a time-based edge would not repair it.

Evidence SHA-256:

- Healthy event gzip: `b761f08ee5fa07e778af64cb6fba425d357bbd7370fc4eaa954812c5bdcb2014`
- Healthy trial result: `e1758d7d6d3bfd9ff00f6269453a23a6a115a6b6161fd78b04fb59f918acb106`
- Healthy case result: `744bb62aee42d0f920564749a9fde7468cfa97341588ee3900acaedc2b9dc946`
- `ZKNodeTracker.java`: `c30ebadfb0e12252ff9c0d6fcf056dd53dea7253744e230eddfefaad9a1dc1c3`
- `HRegionServer.java`: `c8a345ad34d12767d0277302ab705b9429626f0e8d7689fd493b2f81f8059023`
- `TestClusterBootOrder.java`: `7ac0843f5cc522b4494fa2570f91ba334b70492da8bf73c58ea4d3baf9f0c630`
- Runtime monitor overlay JAR: `fb2835d2b2bcd3d338011f0120685e51c6c28e2f7c87b3f0284c9465726e021e`
