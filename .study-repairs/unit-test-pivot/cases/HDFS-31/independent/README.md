# HDFS-31 independent baseline

The selected Hadoop 3.4.3 check is `DataNode.getBPOSForBlock`:
`BlockPoolManager.get(block.getBlockPoolId())` at `DataNode.java:1832`, a
null guard at line 1833, and an explicit `IOException` at lines 1834–1835.
The clean distribution bytecode has the lookup at BCI 13 and the selected
`ATHROW` at BCI 51. The case-local ASM patcher verifies one instrumentation
site for each. The original JUnit
`TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` starts one
DataNode, writes and damages a block, starts a second DataNode, and invokes
`dn0.transferBlock` for that block.

The independent healthy run uses the original test JAR with no GraphChecker
or skeleton classpath entries. It passed in 27.416 seconds. The main thread
emitted one `TRANSFER_BLOCK` event immediately followed by one
`TARGET_GUARD` event for the same DataNode identity, block pool ID, and
block ID. The service was present and the selected `IOException` was not
thrown. It observed 29 `Client.getRpcResponse` calls, all before the target.
See `evidence/healthy-baseline.json` and its raw run path.

The event recorder uses `FileOutputStream` and catches logging
`IOException` so an interrupted actor callback cannot be changed by a trace
failure. `evidence/recorder-error-path-smoke.log` verifies that the callback
returns with its interrupt flag intact when event writing deliberately
fails. Production coverage probes are filtered by exact class membership
in the original HDFS, HDFS client, and Common JARs.

The campaign uses the original JUnit and up to eight ordered RPC response
faults over an 80-trial budget. A trial counts for this target only when
every planned selector matches and applies in order and the same
`transferBlock` DataNode, block pool, and block ID guard is reached after
the final fault. New target throws or JUnit changes require source review.
Production coverage and observed target-before RPC I/O provide feedback.
Late new production probe/method/line coverage or stable I/O families can
extend the budget to 128 trials and ten faults.

## Completed campaign

The 80-trial campaign completed without a late coverage or I/O extension
signal. `evidence/final-audit.json` independently checked every trial's
original-JUnit manifest, graph-free classpath, production probe membership,
ordered fault events, exact target identity, and outcome. Sixty-one full
plans applied and 41 runs retained the exact target after the final fault.
All 41 passed the JUnit, found the service present, and had no selected
exception. Nineteen nonzero JUnits ended directly with the injected RPC
`IOException` before `transferBlock`. Trial 020 failed initial file creation
after the injected RPC error made the only DataNode ineligible for the write
pipeline; the target was not reached. Its source/log excerpt is
`evidence/trial-020-source-review-excerpt.txt`.
