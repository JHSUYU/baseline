# SOLR-14 — first parent-leader liveness check

`SplitShardCmd.split` lines 163–169 reads the selected parent leader's `/live_nodes` znode and throws at line 167 when the first read returns `null`.

The unchanged embedded-cluster `SplitShardTest#doTest` reaches that exact line 165 guard. The independent campaigns retain 163 shared fault trials (162 strict), including 20 strict post-fault guard reaches, with no selected throw. The separate original multi-node chaos evidence and SOLR-15 protective-abort replay remain under [the full review](independent/SOLR-14-16.md).

An additional unchanged original `ShardSplitTest#testSplitAfterFailedSplit` healthy JUnit passed in 35.575 s (`ran=1, ignored=0, failures=0`); it reached the SOLR-14 first guard twice, but did not stop the parent leader before either read. In `ShardSplitTest#testSplitWithChaosMonkey`, the parent stop waits for child replicas, after this first read. The [source/test remap](independent/remap/REMAP-14-16.md) audits these and the other split tests. No original cluster test identified in this audit creates the early parent-loss condition. The remap added **zero** fault trials and retained all earlier evidence.

Status `no_usable_cluster_test` means a **target-relevant workload gap under the audited original tests and exception-only fault model**. The guard is real and reached; its fatal null branch remains untested. `bug_mark=none` is not a claim that the check is bug-free.
