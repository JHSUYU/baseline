# Startup V2 complete-JUnit pause, 2026-10-07 06:18:47 UTC

The node1 `startup` campaign paused to free a cluster-JVM slot for an
independent HBASE-32 r159 replay. The controller was sent SIGTERM **only
after** the original `TestDFSStartupVersions#testVersions` JUnit child exited
and attempt `dd47d06fc499260a337d/attempt-1/manifest.json` was durable.
The manifest reports exit code 0 and finish time
`2026-10-07T06:18:44.681369+00:00`. The controller exited at
`2026-10-07T06:18:47.069256+00:00`; node1 then had no HDFS startup tmux or
Java process (`jps -l` showed only Jps). No JUnit child was signaled.

At the pause, the atomic checkpoint had 86 distinct completed sequences and
effective counts HDFS-22/23/25 = 78 each, HDFS-34 = 40, HDFS-35 = 39. Its
`in_flight` ID remained `dd47d06fc499260a337d` with the full raw trace,
JaCoCo output, and manifest. The independent `audit_checkpoint.py` found
zero issues among the 86 completed plans and zero novel target-exception
signatures. The in-flight raw trace has seven exact actor-bound NN0 RPC
faults, followed by the original test's three expected HDFS-34 namespace
refusals (startup episodes 6–8, `datanodeNamespaceId = Integer.MIN_VALUE`).
These three signatures match the two healthy seeds and are not a new bug.

The first boundary watcher observed the preceding plan
`5e369307830c913099c4` finish, but a typo in its signal call caused the
watcher to exit without signaling the controller. The scheduler consequently
started the next plan. A corrected watcher paused after `dd47...` finished;
neither attempt was repeated or interrupted. On restart, `campaign.py`
must consume the durable `dd47...` manifest, update the checkpoint, and
start only the next queued plan. The active overlay digest remains
`ec5a27c482919e86eb3eb82805abd44a9a32af45dcd6d89781e2b8178d91df30`.
