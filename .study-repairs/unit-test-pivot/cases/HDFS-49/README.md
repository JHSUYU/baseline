# HDFS-49: snapshot count versus quota

Selected check: Hadoop 3.4.3
`DirectorySnapshottableFeature.addSnapshot`, line 188, tests
`getNumSnapshots() + 1 > snapshotQuota` and throws `SnapshotException` on the
true branch.

The mapped original embedded-cluster test
`TestSnapshot#testSnapshot` creates snapshots under the default quota. In the
same test class, `testAllowAndDisallowSnapshot` confirms that root has quota
zero after `disallowSnapshot`, but does not attempt to create a snapshot in
that state. The original HDFS test source tree has no `setSnapshotQuota`
call and no test expecting the snapshot-quota-exceeded exception. Thus the
mapped test is suitable for entering `addSnapshot`, but not for exercising
this selected true branch. No other original cluster JUnit reaching this arm
was identified. This is `no_cluster_test`, not a negative fault result;
`fault_trials=0`, `bug_mark=none`.
