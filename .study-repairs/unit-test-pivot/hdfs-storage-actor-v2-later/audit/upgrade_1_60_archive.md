# HDFS-24 completed runs 1–60 archive

At 2026-10-07 11:52 UTC, the node1 `upgrade` controller had completed at least 60 fault plans. This receipt covers only completed plan directories 1–60, excluding later plans and any in-flight JUnit.

- Original workload: Hadoop 3.4.3 `TestDFSUpgrade#testUpgrade` in its embedded MiniDFSCluster.
- Source anchor: `/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/upgrade-constructor` on node1.
- `archives/upgrade-0001-0060.manifest.json`: SHA-256 `a98d9f904b534ff8a019f9d7273b51acd657e089e0778c77e01183d10bff99d8`; 660 files, 60 completed sequence IDs, 517,602,705 raw bytes.
- `archives/upgrade-0001-0060.tar.zst`: SHA-256 `17a249c2a26df12cb3d93a657838470d8d83bec31537503407723fc0a5f181b2`; 29,613,984 bytes.
- Node1 local verification passed. The archive and manifest were copied to node2, where all 660 files were restored and SHA-verified. Independent receipt `archives/upgrade-0001-0060.node2.baseline.silentfailure-pg0.utah.cloudlab.us.verified.json` was returned to node1.
- After the remote receipt, node1 published `archives/verified-pruned.json` and removed 210 verified regenerable coverage/scratch files, 304,285,125 bytes. The cleanup rule retains every run with any selected target throw. Raw traces, JUnit logs, manifests, fault plans, checkpoint, and archive remain locally available.
- Post-prune independent `audit_checkpoint.py` passed at 64 completed / 63 effective HDFS-24 plans, 64 strict, 0 actor issues. It recorded 24 selected target throws after a fault, all 24 matching both healthy seeds' stable expected signatures, and 0 novel signatures. Plan 7 remains the original JUnit's own 60-second timeout, separate from the selected target oracle.

The archive and cleanup do not alter the HDFS-24 budget or count old plans again.
