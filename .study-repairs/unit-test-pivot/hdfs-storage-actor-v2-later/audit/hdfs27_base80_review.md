# HDFS-27 actor V2 terminal review

The unchanged Hadoop 3.4.3 `TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout`
ran on node2 with its original embedded `MiniDFSCluster`, one DataNode and the
unmanaged `dfs/data` directory. Two fault-free calibrations passed in 16.968
and 15.018 seconds. Each reached the selected target once on the exact
`episode=1/dn=1/dirs=dfs/data` actor and recorded no selected throw. The
offline overlay digest was
`a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.

The selected production check is
`BlockPoolSliceStorage.doUpgrade(String,StorageDirectory,NamespaceInfo,File,File,File,int,Configuration)`
at `BlockPoolSliceStorage.java:510`: `assert this.namespaceID ==
nsInfo.getNamespaceID()`. The original test configures `dfs/data` at
`TestDatanodeLayoutUpgrade.java:42–53`, then invokes
`TestDFSUpgradeFromImage.upgradeAndVerify`. The asynchronous upgrade callable
is joined to the same `StorageDirectory` object; RPC faults require the same
DataNode startup episode and raw NN0 endpoint. Missing actor, storage, or
endpoint information fails the selector closed.

The campaign completed 81 distinct fault plans, all 81 strictly applied in
order. Eighty plans reached the same actor's target after the last fault.
Plan 2, `3605659628b285363ed2`, strictly injected a VERSION_READ
`IOException`, then the DataNode rejected its only directory and the target
did not execute. Its original JUnit exit 1 is a direct, expected consequence
of losing the cluster startup; it is excluded from the effective denominator
and reviewed in `hdfs27_plan2_target_loss.md`. The other 80 original JUnit
runs exited 0. There were zero selected target throws and zero novel exception
signatures. The last eight effective runs added zero production branches,
lines, methods, probes, or stable I/O families, so the base budget ended at
80 effective and maximum depth 8; no conditional extension was triggered.

The two healthy JUnits plus all 81 actual fault JUnit attempts took 2741.118
seconds of measured JUnit time; controller waits and archival are excluded.
The final production coverage union is 7983 branch counts, 32726 lines, 7709
methods, and 26548 probes. Relative to the healthy seeds, effective trials
added 19 branch counts, 33 lines, 4 methods, and 40 probes, with three stable
I/O families. These are global production coverage values and do not by
themselves identify a target-related recovery path.

The independent raw audit found 81 strict sequences, 80 effective, zero
selected target throws and zero issues before and after pruning. The
supervisor ledger ended with `effective_budget_met` at 2026-10-07 13:16:42
UTC; `campaign-state.json` retains `batch_pause` from its final single-plan
invocation with `in_flight=null`. The first 80-effective manifest finished at
2026-10-07 13:16:39 UTC. The checkpoint SHA-256 is
`95f274d40c88f4e2fe8b55e2c04d8079efe9c6759eef07da6311dcacc9efee9b`.

Completed runs 1–60 were previously archived and mirrored. Runs 61–81 were
archived as `layout-0061-0081.tar.zst` with 231 files and 140468962 raw
bytes, then restored and SHA-verified on node1 before only verified
regenerable scratch and coverage exports were pruned on node2. The archive
SHA-256 is `20d34b946116de8f4d3d3d2d69fa90f1517c5d0ff11b031d3eb7efb449c8c1e9`;
the manifest SHA-256 is
`82833deeb15996e321d77bf3947150f787c63d5a47d07a1bc3464d942156cc22`.
All original traces, plans, JUnit logs, JaCoCo data, manifests, and
cross-host verification receipts remain available under
`/users/ZhenyuLi/hdfs-storage-v2-layout-isolated-20261007/evidence/layout-upgrade-constructor`
on node2 and its mirrored archive on node1. The old coarse-actor 80 attempts
are historical only and are not included in these 80 effective runs.

Result: **quality complete; no new target bug detected in this budget**.
