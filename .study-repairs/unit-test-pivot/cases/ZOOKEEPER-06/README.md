# ZOOKEEPER-06: leader acknowledgment state check

Apache ZooKeeper 3.8.7, `Leader.waitForEpochAck()` in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java:1471-1475`.
The selected guard is `ss.isMoreRecentThan(leaderStateSummary)`; only its own
`IOException("Follower is ahead of the leader...")` at line 1475 is the target oracle.

The unchanged `QuorumRestartTest#testRollingRestart` JUnit creates three in-JVM
quorum peers and restarts them in turn. Its independent healthy run passed in
4.730 seconds, reached the selected guard 4 times on the normal arm,
and yielded 5022 production JaCoCo probes and 54 eligible physical I/O
families. The agent and runner classpath contain no GraphChecker or static
region skeleton. See [provenance.json](independent/provenance.json).

The graph-free CrashFuzz-style campaign tested 128 checked-I/O fault
sequences (configured maximum 10 faults, observed maximum 6). 98 matched and applied
all planned fault selectors in order; 85 also reached the same selected
guard after the final fault. Their admitted feedback added 208 production
JaCoCo probes and 0 stable physical I/O families. 13 fully injected
sequences lost the target, and 0 pre-FOLLOWERINFO handler selections
had ambiguous runtime identity; neither category contributed feedback. No
round executed the exact selected throw after the last fault, so **no new bug
is confirmed at this check**.

The campaign stopped at its 128-trial extended budget; the final 20 added
5 admitted production probes and 0 stable I/O families. Healthy plus trial JVM time was
802.332 seconds; instrumentor build, source review, and idle time are
excluded. Every round's elapsed time, exact fault plan, strict match, target
outcome, and coverage is in [trials.csv](independent/trials.csv) and
[trials.json](independent/trials.json). Raw logs and JaCoCo exec files remain
in [raw-runs.tar.zst](independent/raw-runs.tar.zst), with per-run hashes in
[trace-manifest.json](independent/trace-manifest.json).

The source review in [source-audit.md](independent/source-audit.md) traces
the follower `ACKEPOCH` summary to this leader check and describes its
lexicographic `(epoch, zxid)` comparison. This is a bounded result for the
original JUnit and checked-I/O fault model, not a proof for all recovery
executions. File family keys include the peer and epoch-file basename, not
an absolute path.

Historical GraphChecker trials remain in
[legacy-graph-result.json](legacy-graph-result.json) and
[legacy-graph-README.md](legacy-graph-README.md). Those 32 trials are excluded
from all independent-method counts.
