# HBASE-28 nonloopback master full campaign

This case reuses the unchanged `TestRSStatusPage#testStatusPage` and the
case-local master UI bind from the sealed healthy observation. A fresh r0000
must pass the unchanged JUnit and observe the named master0
`Addressing.isLocalAddress` SocketException door immediately before the exact
`HRegionServer.putUpWebUI` guard in the same occurrence and thread. The runner
promotes that calibration checkpoint only after the gate validates the pinned
door, target, trace, and queued mutation point.

Run only with dispatch's node1 GO receipt and
`MALLORY_HBASE28_NODE1_GRANT=full-v2`. Budget: 80 fault trials or 3600 seconds,
maximum three faults per trial. Natural `budget_exhausted` or
`queue_exhausted` is a completed campaign. A selected IOException is a
candidate for source review; this package makes no bug claim.
