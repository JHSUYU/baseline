# HDFS-26 actor V2 base-budget review

The unchanged Hadoop 3.4.3 `TestDFSRollback#testRollback` is the shared
embedded-cluster workload for HDFS-26 and HDFS-37. The original test loops
over one and two DataNode directories and deliberately constructs valid and
invalid rollback states (`TestDFSRollback.java:139–215`). HDFS-26 selects
`BlockPoolSliceStorage.doRollback` at `BlockPoolSliceStorage.java:618–620`,
which permits a previous block-pool state only when its layout version is at
least the current software layout version and its cTime is no newer than the
NameNode `NamespaceInfo` cTime. This check is distinct from HDFS-37's
DataStorage-level rollback check.

Two unchanged healthy JUnits passed in 46.764 and 49.944 seconds. Each
reached HDFS-26's selected check six times with no selected throw. The
offline overlay digest was
`a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.
It binds the exact startup episode, DataNode object and slot, configured
storage directory and raw NN0 RPC endpoint. Unbound or mismatched I/O does
not consume a fault plan.

HDFS-26's 80th effective plan was `069b9c584035fc94402b`, the shared
campaign's completed-plan index 160, whose original JUnit manifest finished
at 2026-10-07 13:44:53 UTC. Exactly 80 HDFS-26-selected fault plans were
run, all 80 strictly injected in order and all 80 followed by the same
actor's selected target. The original JUnit passed for this prefix, with zero
HDFS-26 target throws and zero novel exception signatures. Its last eight
effective trials added zero production branches, lines, methods, probes or
stable I/O families, so its fixed goal remains 80 effective and depth 8.
HDFS-37 has a separate conditional extension in this shared JUnit and does
not change the HDFS-26 denominator.

Measured HDFS-26 time is 7044.122 seconds: two healthy JUnits (96.708)
plus the 80 JUnit attempts selected for this check (6947.414). This is an
attribution of shared original-JUnit work; it must not be added to HDFS-37's
reported time. Shared-lock waits, controller overhead and archival are
excluded. The HDFS-26 production coverage union is 9404 branch counts,
36717 lines, 8365 methods and 30454 probes. Effective feedback added 87
branch counts, 140 lines, 14 methods and 192 probes; eight stable I/O
families were seen. These are global production coverage values, not a
claim that every newly covered branch is target-related recovery logic.

Independent raw audit after the 161st shared completed plan and again after
cross-host archiving through plan 160 found every ordered injection exact,
HDFS-26=80 effective, zero HDFS-26 target throws, zero novel signatures, and
zero issues. The immutable original run evidence through plan 160 has been
SHA-verified and mirrored between node2 and node1; see the sequential
`rollback_*_archive.md` receipts, most recently
`rollback_141_160_archive.md`. Node2's source anchor is
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/rollback-constructor`.
Historical coarse-actor trials remain excluded.

Result: **HDFS-26 quality complete; no new selected target bug in its
80-effective budget**. HDFS-37 continues independently to its mechanically
extended 128-effective budget.
