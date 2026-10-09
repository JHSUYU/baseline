# HDFS-24 conditional extension at 80 effective trials

The unchanged original `TestDFSUpgrade#testUpgrade` reached 80 actor-qualified
effective trials after 81 completed plans. The checkpoint expanded its goal
to 128 effective trials and maximum sequence depth to 10, as specified by
the campaign's last-eight-effective novelty rule. Existing plans, result
counts, and the extension decision remain untouched.

The only new production branch-count feedback in that window came from plan
`ba1fb47281ec3f9b1ef2`, completed-plan index 78. Its two ordered faults
were exact, the original JUnit passed in 53.154 seconds, four same-actor
HDFS-24 checks ran after the final fault, and no selected target exception
appeared. The plan added one branch-count entry and one probe, and zero new
stable I/O families. Reconstructing the union of healthy coverage and all
earlier completed plans, including the SHA-verified archive of plans 1–60,
isolated this new branch-count entry:

`org/apache/hadoop/hdfs/server/namenode/FSNamesystem$NameNodeResourceMonitor#run()V#5`

The `#5` suffix is the exporter’s aggregate covered-branch ordinal within
that method; it does not identify a source branch line. Hadoop 3.4.3 source
places `NameNodeResourceMonitor.run` in the NameNode background disk-resource
monitor at `FSNamesystem.java:4541–4572`, outside the HDFS-24
`DataStorage.doTransition` target path. We therefore classify this feedback
as incidental global coverage, not evidence of a new target recovery path or
bug. The mechanically triggered 128/10 budget continues unchanged; terminal
review will report global and target-related evidence separately.
