# ZOOKEEPER-05: Follower leader-epoch check

Apache ZooKeeper 3.8.7, `Follower.followLeader()` in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java:98-103`.
The selected guard is `newEpoch < self.getAcceptedEpoch()`; only its own
`IOException("Error: Epoch of leader is lower")` at line 103 is the target oracle.

The unchanged `QuorumRestartTest#testRollingRestart` JUnit creates three in-JVM
quorum peers and restarts them in turn. Its independent healthy run passed in
4.577 seconds, reached the selected guard six times on the normal arm,
and yielded 5041 production JaCoCo probes and 54 eligible physical I/O
families. The agent and runner classpath contain no GraphChecker or static
region skeleton. See [provenance.json](independent/provenance.json).

The graph-free CrashFuzz-style campaign tested 80 checked-I/O fault
sequences (maximum 8 faults per sequence). 47 matched and applied
all planned fault selectors in order; 35 also reached the same selected
guard after the final fault. Their admitted feedback added 170 production
JaCoCo probes and 0 stable physical I/O families. 12 fully injected
sequences lost the target, and 5 pre-FOLLOWERINFO handler selections
had ambiguous runtime identity; neither category contributed feedback. No
round executed the exact selected throw after the last fault, so **no new bug
is confirmed at this check**.

The campaign stopped at 80 trials because the final 20 added no admitted
production coverage or stable I/O family. Healthy plus trial JVM time was
443.125 seconds; instrumentor build, source review, and idle time are
excluded. Every round's elapsed time, exact fault plan, strict match, target
outcome, and coverage is in [trials.csv](independent/trials.csv) and
[trials.json](independent/trials.json). Raw logs and JaCoCo exec files remain
on node2 under `/users/ZhenyuLi/zk05-independent/runs` and in the
[compressed raw-run archive](independent/raw-runs.tar.zst) (SHA256 `d52cbd6a3364ad2f8306bc008897023c94a18caa406dbcf191de471546e9e935`). Their compact trace
hashes are in [trace-manifest.json](independent/trace-manifest.json).

The source review in [source-audit.md](independent/source-audit.md) explains
why the version-`0x10000` `LEADERINFO` handshake normally checks or updates
`acceptedEpoch` before the selected `Follower` comparison. This is a bounded
result for the original JUnit and checked-I/O fault model, not a proof for all
concurrent executions. File family keys include the peer and epoch-file
basename, not an absolute path.

Historical GraphChecker trials remain in
[legacy-graph-result.json](legacy-graph-result.json) and
[legacy-graph-README.md](legacy-graph-README.md). Those 11 trials are excluded
from all independent-method counts.
