# HDFS-24 actor V2 terminal review

The unchanged Hadoop 3.4.3 `TestDFSUpgrade#testUpgrade` ran with its original
embedded cluster. The selected production check is
`BlockPoolSliceStorage.doTransition` at `BlockPoolSliceStorage.java:414–415`:
stored block-pool layout version and cTime are compared with the software
layout version and NameNode `NamespaceInfo`. The original test deliberately
creates future DataNode layout versions and newer fsscTime, then expects
block-pool startup to fail (`TestDFSUpgrade.java:285–315`). A selected
`IOException` is a bug candidate only if its exact actor, volume, guard
outcome, and exception signature differ from both healthy calibrations.

Two unchanged fault-free JUnits passed in 44.120 and 40.406 seconds. Each
visited the selected check 18 times and produced three identical expected
exception signatures. The actor V2 overlay bound startup episode, actual
DataNode slot, configured storage directory and raw NN0 RPC endpoint; its
digest is `a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.
Selectors missing any required identity failed closed.

The campaign completed 129 distinct ordered fault plans. All 129 injected
strictly; 128 reached the same actor's target after the last fault. One plan,
the separately reviewed plan 7, timed out in the original JUnit's 60-second
test limit and lost the selected target, so it remains attempted but
ineffective. The other 128 original JUnit runs exited 0. Across 46 fault
trials there were 67 selected target `IOException` events; every exact
signature matched both healthy seeds. There were zero novel selected target
exception signatures and zero independent raw-audit issues.

At 80 effective runs, the configured last-eight novelty rule mechanically
extended the budget to 128 effective and maximum depth 10. The one branch
count that triggered this decision came from background
`FSNamesystem$NameNodeResourceMonitor.run`, outside the selected recovery
check (see `hdfs24_extension_branch_review.md`). The remaining 48 effective
runs added zero production branches, lines, methods, probes, or stable I/O
families. We preserve the extension decision and report this incidental
global coverage separately from target-related evidence.

Two healthy JUnits plus all 129 actual fault JUnit attempts took 7170.048
seconds of measured JUnit time (84.526 + 7085.522); controller, shared-lock
waiting and archival time are excluded. Final global production coverage
union: 9428 branch counts, 36861 lines, 8427 methods and 30524 probes.
The aggregate gain over healthy was 121 branch counts, 192 lines, 20 methods
and 197 probes, with 24 stable I/O families. These global metrics do not
identify causal target recovery coverage.

The supervisor wrote `effective_budget_met` at 2026-10-07 13:39:14 UTC,
after the 128th effective manifest finished at 13:39:11 UTC. Its final
single-plan checkpoint retains `batch_pause` with `in_flight=null` and SHA-256
`867ba36871b72bc485b05fa90e7c0ae2267f0d21f5085b2fc5bc3e9410b876c0`.
The tmux and case JUnit JVM exited. Independent raw audit before and after
pruning: 129/129 strict, 128 effective, 67 healthy-signature throws, zero
novel signatures, zero issues.

All completed runs 1–120 have prior cross-host SHA-verified archives. Final
runs 121–129 were archived as `upgrade-0121-0129.tar.zst` (99 files,
78000779 raw bytes); tar SHA-256
`2fb46e15b7b02c9807448564f5d511309b220bdae9d14b30e8a35098a80d8711`,
manifest SHA-256
`794661d68d923d28cdd53c57bd5e49c291268258723580b7a6b65021b361361b`.
Node2 restored and SHA-verified every file before node1 considered pruning;
the final nine plans contained expected target throws and no local files were
pruned. Raw plans, traces, JUnit logs, JaCoCo files and receipts remain under
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/upgrade-constructor`
on node1 and the mirror on node2. Historical coarse-actor trials remain
separate from this denominator.

Result: **quality complete; no new target bug detected in this budget**.
