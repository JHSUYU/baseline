# HDFS-37 conditional extension feedback review

The unchanged `TestDFSRollback#testRollback` shared campaign reached 80
same-actor effective HDFS-37 runs at completed plan 161. Its configured
last-eight-effective novelty rule expanded this case alone to 128 effective
and maximum depth 10. HDFS-26 retained its completed 80/8 goal.

Only effective HDFS-37 run 73, sequence
`6cd2f79e6af49e740f9a` (shared completed plan 147), added production
coverage in the last-eight window: one covered branch-count identity and
one probe. There were zero new stable I/O families in that window.

To identify that branch, we reconstructed the pre-run union from the
`healthy-a/covered_branch_counts.txt` file and the corresponding exports
for HDFS-37's first 72 effective runs, using the checkpoint's immutable
`effective_history` sequence IDs. Completed raw run files 1–160 had already
been SHA-verified and restored on node1 from the node2 archive. The earlier
union contained 9444 branch identities. Run 73 covered 9338 identities,
exactly one of which was absent from the earlier union:

`org/apache/hadoop/hdfs/server/blockmanagement/BlockManagerSafeMode#reportStatus(Ljava/lang/String;Z)V#4`

The `#4` suffix is the coverage exporter's per-method aggregate branch
ordinal, not a source line. Hadoop 3.4.3 `BlockManagerSafeMode.java:625–636`
implements `reportStatus`: it rate-limits NameNode safe-mode status logging
to roughly 20-second intervals unless forced. This is outside the selected
HDFS-37 `DataStorage.doRollback:941` version/cTime guard. We infer that the
new coverage is a timing-sensitive global status-logging path; the trace
does not prove an additional target-related rollback recovery behavior.

The mechanical 128/10 budget remains in effect and no completed or queued
plan is changed. At terminal review, global coverage and selected-target
exception evidence will be reported separately. The HDFS-37 selected throw
at effective run 80 was the original test's expected
`InconsistentFSStateException`, matching both healthy seeds at the same
actor/volume; it did not constitute a new target signature.
