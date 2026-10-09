# HDFS-31: block-pool offer service lookup

The selected Hadoop 3.4.3 check is `DataNode.getBPOSForBlock`: it uses the
requested block's pool ID to look up a `BPOfferService` in
`blockPoolManager` and throws `IOException` if absent.

The mapped original embedded-cluster
`TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` starts with one
DataNode, writes a block, corrupts its checksum metadata, then starts a
second DataNode and calls `dn0.transferBlock(block, ...)`. The implementation
of `transferBlock` calls `getBPOSForBlock` before inspecting the damaged
replica, so this is a source-grounded route to the target lookup.

The independent original JUnit healthy run passed. Case-local ASM showed
one `TRANSFER_BLOCK` and one following `getBPOSForBlock` guard on the same
main-thread DataNode, block pool, and block ID; the service was present and
the selected `IOException` was absent as expected. The run observed 29 RPC
response I/O events before this guard. HDFS-31 has its own non-throwing
recorder and JaCoCo production coverage, independent of GraphChecker and
of HDFS-32 outcomes. See [independent/README.md](independent/README.md)
and [healthy evidence](independent/evidence/healthy-baseline.json). The
per-trial campaign updates `result.json` atomically for the 102-case table.

The campaign completed 80 attempts at up to eight ordered RPC faults. Of
these, 61 matched and applied the full plan in order; 41 also reached the
same `transferBlock` target guard after the final fault. Every target-retaining
trial passed the original JUnit, found the service present, and had no
selected `IOException`, matching healthy behavior. No new failure of this
check was found. The final eight trials added no production probe, method,
or line coverage or stable target-before I/O family, so no 128-trial
extension was needed. [Final audit](independent/evidence/final-audit.json)
rechecked the raw events, manifests, and original test results.

Of 20 nonzero JUnits, 19 directly reported the injected RPC `IOException`
before `transferBlock`. In trial 020, the injected DataStreamer RPC failure
excluded the only DataNode during the test's initial file write; the
replication requirement could not be met, so `transferBlock` and the selected
guard were never reached. This is a source-reviewed setup-path effect,
recorded in [the trial excerpt](independent/evidence/trial-020-source-review-excerpt.txt),
and is not counted as a selected-target bug.
