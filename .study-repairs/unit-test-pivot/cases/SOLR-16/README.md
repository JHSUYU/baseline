# SOLR-16 — parent-leader session-change check

`SplitShardCmd.split` lines 521–543 saves the first parent leader znode's `ephemeralOwner`, reads the **same node** again, and throws at line 543 only when the second `Stat` is non-null with a different owner. A null second `Stat` takes SOLR-15's separate line 538 protective abort.

The unchanged original cluster tests and 163 shared fault trials (162 strict) reach the line 524 outer comparison but never the selected line 539 final changed-owner guard or line 543 throw. The original `ShardSplitTest#testSplitWithChaosMonkey` stops the parent during split but restarts it only after the split request returns; its reproducible two-fault exception was SOLR-15's null-znode abort, not SOLR-16. The additional unchanged `ShardSplitTest#testSplitAfterFailedSplit` healthy JUnit passed in 35.575 s and reached the outer guard once, with zero final changed-owner guards. The [source/test remap](../SOLR-14/independent/remap/REMAP-14-16.md) and [full historical review](../SOLR-14/independent/SOLR-14-16.md) retain the per-test evidence; the remap added **zero** fault trials.

Status `no_usable_cluster_test` records the **missing same-node session-renewal window** in the audited original tests under the current exception-only fault model. The selected branch remains untested. `bug_mark=none` is not a claim that the check is bug-free.
