# HDFS-37 actor V2 terminal review

## Exact check and workload

Hadoop 3.4.3 `DataStorage.doRollback(StorageDirectory, NamespaceInfo)`
at `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java:939–941`
compares the prior DataNode volume layout version and cTime with the software
and NameNode namespace state. The unchanged original cluster JUnit was
`org.apache.hadoop.hdfs.TestDFSRollback#testRollback`. This original method
shares a JVM run with HDFS-26 but the two checks have separate target guards,
actor receipts and effective denominators. The source test deliberately
contains invalid rollback states that throw `InconsistentFSStateException`.

The two no-fault healthy JUnits passed in 46.764 and 49.944 seconds. Each
reached this check 12 times and produced three intended storage-state
exceptions. The V2 offline ASM overlay SHA was
`a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.
The probe binds RPC responses to the startup episode, physical DataNode,
configured storage directory and raw NN0 endpoint. Production coverage and
relevant I/O provide the fault-sequence feedback. No GraphChecker graph,
runtime controller, Docker workload or changed JUnit assertion was used.

## Final accounting

The shared controller reached both configured goals at 2026-10-07 15:21:18
UTC: HDFS-26 80/80 and HDFS-37 128/128 effective. Its ledger records
`effective_budget_met`; the tmux and this campaign's Java process exited.
The saved single-run checkpoint has `in_flight=null` and 209 completed plans.
The independent raw auditor reconstructed all 209 as strict, all 209 original
JUnits as exit 0, HDFS-26 80 effective and HDFS-37 128 effective, with zero
audit issues. The HDFS-37 selected subset contains 129 distinct plans:
129 strictly injected, 128 same-actor targets reached after the last fault,
and one exact file-fault plan whose target did not occur. That attempt was
not credited to the effective denominator.

The selected HDFS-37 original JUnit attempts took 11,214.548 seconds; the
two shared healthy JUnits took 96.708 seconds. The reported 11,311.256
seconds exclude controller and shared-lock waits. This JUnit time is shared
with HDFS-26 and must not be added to that check's time. Per-plan time and
fault sequence remain in the immutable checkpoint and original manifests.

The selected HDFS-37 target returned 123 postfault exceptions in 118 plans.
All 123 match the guard/actor/volume exception signatures present in both
healthy JUnits. There are zero novel selected target exception signatures
and no confirmed new bug. The postfault guard trace contains 138 checks at
`DataStorage.doRollback#L940-IF_ICMPLT` (all `reject=false`) and 138 at
`DataStorage.doRollback#L941-IFLE` (15 `reject=false`, 123 `reject=true`).
This count describes the original test's intended valid and invalid states.

At the 80-effective boundary, one newly covered branch triggered the
configured mechanical extension to 128 effective/max10 faults. Source
inspection identified it as `BlockManagerSafeMode#reportStatus` status
logging, not target-related rollback behavior; see
`hdfs37_extension_branch_review.md`. The last eight effective runs at the
128 boundary added no production coverage or stable I/O family. Final
production coverage was 9,445 branch identities, 36,808 lines, 8,375
methods and 30,521 probes, an increase of 128/231/24/259 over the healthy
union. These are global coverage counts, not target-specific recovery proof.

## Raw preservation

The final 29 completed plans, indices 181–209, contain 319 original files
(254,586,765 uncompressed bytes). `archive_completed.py` compressed and
restored the full archive on node2, recording tar SHA
`b4795cf22628d48f77c082bbfdda994388f943c50994082df6f1e96aa275b001`.
The archive and manifest were mirrored to node1; node1 restored and
independently checked all 319 file sizes and SHA-256 hashes. Its receipt was
mirrored back to node2. No original raw file was deleted in this final
batch. Earlier batches 1–180 have their own SHA manifests and cross-node
receipts. The final checkpoint SHA is
`ddeaddf7be2ae79a3fb2ae74f9877a36505914628eb68d6eaf349a73697dc07c`;
the terminal independent audit SHA is
`838125e043c054d0c86374f65ca68e2c5645bd5973682ff8341f230868b171ee`.
The terminal audit, final archive manifest and node1 verification receipt
are stored beside this review. Historical coarse actor trials remain in
`legacy_coarse_actor` and were never imported into the V2 denominator.
