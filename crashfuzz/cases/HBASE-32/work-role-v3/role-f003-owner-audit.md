# HBASE-32 V3 role-f003: same-role negative control

The unchanged `TestRegionReplicaFailover#testLotsOfRegionReplicas` JUnit passed
1/1 in 89.83 s. The frozen V3 plan SHA-256 is
`e3e52e9a77b03c047a25fca1d26b405985a9f7c5f931923981a2fbc07f97e1d0`.
This is the third and last bounded V3 diagnostic; it is neither a fuzz trial
nor an exact physical-actor replay of s272 or role-f001.

`logs/role-f003.log:1267` identifies the current `hbase:meta` host as
RS41129. At `:5726-5728`, F1 selects and injects `DoNotRetryIOException`
at `MASTER_OPENED_RPC` for that same server and replica 3. F2 at `:7734-7736`
injects the same exception before the first selected
`FlushRegionCallable.call:81` RPC. The selected raw primary and secondary
region bytes and replica 3 agree across F1, F2, and B7 at `:7746`.
`role-f003.receipt.json` confirms two applied faults, one post-final B7,
`identity_valid=true`, and the original JUnit success. All 600 table2 child
assignments completed; CreateTableProcedure pid 20 finished at `:36787`.

This run has no outstanding READ holder on expired RS41129's
`ServerStateNode` identity `6a65c302` when RegionServerTracker requests WRITE
at `:8159` (lock event 241). WRITE is acquired in the next event at `:8160`,
and carrying-meta SCP pid 725 is scheduled immediately at `:8161`.
`logs/role-f003.lock-audit.json` parses 3,642 lock events without an anomaly
and reports zero active readers at that WRITE request. This is a same-meta-role,
same-plan **negative control** for the pre-SCP recovery wait seen in
role-f001/f002; the scheduling condition differs. The direct B7 rethrow is
the expected response to the injected exception and is not a new bug.

Raw log SHA-256 is `687d36bfe059d2da01d34e947bd1622b8da8afcbc14913f65821080f9428ee7c`;
JaCoCo SHA-256 is `0abfe0d732d04a1ca733eebc6d1a8a2320847f0f664d9a8ae2cbf3b75c79cda1`.
The 13-file archive SHA-256 is
`b995c0188677e3ffb7f22ec950ae246e543ee2ccfcf125d5380f610554b1af90`;
its manifest SHA-256 is
`39b044b13574304955329f896dbb94830d10eb3ba25fe224152b140e0cca7c7d`.
All members were checked on node1, and a second local-to-node1 archive
SHA-256 check passed at terminal review.
