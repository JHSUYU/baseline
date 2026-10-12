# HDFS-48 node2 full campaign stage

This is an offline stage for the original MiniDFSCluster JUnit
`TestRenameWithSnapshots#testRenameUndo_1`. No JVM or campaign has been started
by this package. Dispatch has reserved the node2 HDFS slot after its current
queue. The full configuration caps fault work at 80 trials, 3600 seconds, and
three faults per trial. It uses the v14 NameNode `IOException` model and the
original, unpatched test and adapter, copied into this case directory.

The v14 healthy receipt records one passing JUnit, the exact nonthrowing
`INodeDirectory.replaceChild` guard on `hdfs-cluster-1/nn0`, a valid target
site catalog, and an offline causal audit with observed path doors. The v14
pilot records ten effective injections at
`Server$RpcCall.run@1246:door:1`; none retained the named target after the
fault. That is the measured result for that pilot. It is not a full-campaign
terminal, and it is not a gate requiring a target-retaining pilot. The source
admission review explains why this server-ingress fault tends to stop the
rename before its NameNode handler. The separate client pre-send patch proposal
remains unbuilt and is outside this configuration.

`python3 preflight_hdfs48_node2_full.py --static` verifies package, release,
source-mirror, class, archived healthy, and effective I/O evidence hashes
without Java. On node2, `run_hdfs48_node2_full.sh` requires dispatch admission,
takes the same HDFS lock as the current node2 sequence, performs runtime
preflight against `/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8`, and
starts Mallory in a unique resumable output directory. The controller starts
with a fresh healthy seed and admits faults only if that seed passes its
runtime checks. Stop and report a new healthy mapping failure or missing door
as its natural outcome; do not substitute the archived healthy receipt for the
new seed.

After controller termination, inspect `result.json`, `checkpoint.json`, the
healthy trial, and all fault-trial receipts. A trial budget cap is a limit,
not a promise of 80 completed trials; `queue_exhausted` is also a natural
terminal. Report the actual terminal status and any target loss or missing
causal path as outcomes. Do not label the old ten-trial pilot as this full run.
