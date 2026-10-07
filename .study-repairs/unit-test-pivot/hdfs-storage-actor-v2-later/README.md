# HDFS storage actor V2: upgrade and rollback groups

This is the isolated follow-on overlay for HDFS-24/26/27/37. It runs the
unchanged Hadoop 3.4.3 MiniDFSCluster JUnit methods, with one actor-aware
instrumentation shared by the `upgrade`, `layout_upgrade`, and `rollback`
groups. The `startup` group HDFS-22/23/25/34/35 continues in
`hdfs-storage-actor-v2` on its independently calibrated overlay. Never use
this directory's build output or sources to resume that startup checkpoint.

The follow-on overlay differs because the original
`TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` configures a bare
`dfs/data` directory. Both the DataNode registration hook and the Python
storage-volume matcher recognize that path, as well as numbered `dfs/dataN`
and `dfs/datanodeMaster`. The startup receipt used overlay digest
`ec5a27c482919e86eb3eb82805abd44a9a32af45dcd6d89781e2b8178d91df30`;
the updated local build's offline digest is
`a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.
Actual host seed manifests must record and agree on their own digest before
any follow-on campaign begins.

The source and bytecode hooks are the same as the startup overlay apart from
the directory pattern. `MiniDFSCluster.startDataNodes` defines a startup
episode; the DataNode constructor binds the object before BPServiceActor
starts; BPServiceActor.run adopts that actor and NameNode endpoint; storage
operations bind the actual `StorageDirectory` object. The HDFS-27 async
upgrade callable must rejoin through that storage object. `Client` RPC
responses are eligible only when their raw remote address equals the bound
actor's NameNode address. Unknown actor, storage, or peer identity fails
closed. Every JUnit run collects production JaCoCo coverage and exact branch
events, plus file/RPC I/O and target check/throw traces.

Run `python3 offline_smoke.py` in this directory before allocating a cluster
slot. The exact original JUnit mapping, two-seed calibration and campaign
commands, port and scratch isolation, expected healthy target throws, and
80-effective/8-fault conditional 128-effective/10-fault budget are recorded
in [the launch plan](audit/upgrade_rollback_calibration.md). All raw evidence
and atomic checkpoints belong under this directory's `evidence/`; no old
case status or legacy coarse trial is imported.
