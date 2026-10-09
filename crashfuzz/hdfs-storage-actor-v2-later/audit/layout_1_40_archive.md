# HDFS-27 completed runs 1–40 archive

At 2026-10-07 11:48 UTC, the node2 `layout_upgrade` controller had completed 40 fault plans. This receipt covers only those 40 immutable plan directories; the active JUnit and later checkpoint entries were excluded.

- Original workload: `TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` in the Hadoop 3.4.3 embedded MiniDFSCluster.
- Source anchor: `/users/ZhenyuLi/hdfs-storage-v2-layout-isolated-20261007/evidence/layout-upgrade-constructor` on node2.
- `archives/layout-0001-0040.manifest.json`: SHA-256 `ff3314214af41130eaff718864e43258a083d6ea29912d0c71fd0041f45454eb`; 440 files and 40 completed sequence IDs.
- `archives/layout-0001-0040.tar.zst`: SHA-256 `a64aaca373b10615e3829141d8b0aba94508038707f93d8c696dcb6aa5051c39`; 16,164,220 bytes.
- Node2 local archive verification passed. The archive and manifest were copied to node1, and node1 restored and SHA-verified all 440 files. Its independent receipt is `archives/layout-0001-0040.node1.baseline.silentfailure-pg0.utah.cloudlab.us.verified.json` on both hosts.
- Only after the remote receipt returned, node2 published `archives/verified-pruned.json` and removed 200 verified regenerable coverage/scratch files, 250,416,822 bytes. The script retains every run with any selected target throw, including expected throws; raw traces, JUnit logs, manifests, fault plans, checkpoint, and archive remain locally available.
- Post-prune `audit_checkpoint.py` passed at 41 distinct completed plans / 40 effective HDFS-27 plans, 41 strict sequences, 0 actor issues, 0 target exception after fault. The 41st completed plan is outside this archive. `in_flight` was null at the audit snapshot; the controller itself remained active and resumable.

The archive does not change the effective budget or classify the plan-2 startup timeout as a target bug.
