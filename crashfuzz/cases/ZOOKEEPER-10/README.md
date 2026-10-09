# ZOOKEEPER-10: observer-master proposal/commit ordering

Apache ZooKeeper 3.8.7, `ObserverMaster.removeProposedPacket(long)` in
`zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ObserverMaster.java:359-375`.
The selected guard compares the queued proposal zxid with the commit zxid at
line 365. Only its `RuntimeException("Unexpected proposal packet on commit ack...")`
at line 371 is the target oracle.

The unchanged `ObserverMasterTest#testInOrderCommits(true)` JUnit creates two
participants and one observer, enables observer-master forwarding, and issues
20,002 asynchronous writes. The unique-id runner executes only the `true`
parameterized invocation with its normal JUnit lifecycle. The independent
healthy run passed in 8.661 seconds and executed the exact guard
20,021 times, all with matching zxids. The compact trace samples
163 normal guard events; its end summary retains the full count.
JaCoCo recorded 7956 production probes and the runtime recorder identified
59 stable related I/O families. The classpath contains no GraphChecker or
static region skeleton. See [provenance.json](independent/provenance.json).

The graph-free CrashFuzz-style campaign tested 128 checked-I/O fault
sequences (configured maximum 10 faults, observed maximum 4).
96 matched and applied all planned fault selectors in order; 76 also
reached the same selected guard after the final fault. Their admitted feedback
added 699 production JaCoCo probes and 27 stable I/O families.
20 fully injected sequences lost the target, and 0 selections
had ambiguous runtime identity; neither contributed feedback. No round
executed the exact selected throw after its final fault, so **no new bug is
confirmed at this check**.

The campaign stopped at its 128-trial extended budget; its final 20
added 0 admitted production probes and 0 stable I/O families.
Healthy plus trial JVM time was 1383.125 seconds; build, source review,
and idle time are excluded. Every round's elapsed time, exact selector plan,
strict match, target outcome, and coverage is in [trials.csv](independent/trials.csv)
and [trials.json](independent/trials.json). Raw logs and JaCoCo exec files are
in [raw-runs.tar.zst](independent/raw-runs.tar.zst), with per-run hashes in
[trace-manifest.json](independent/trace-manifest.json).
The archive omits each JUnit run's temporary embedded-cluster data directory;
the original complete directories remain on node2 for short-term audit.

The source review in [source-audit.md](independent/source-audit.md) traces
`Follower.processPacket()` into the proposal queue and selected commit check.
The runtime hook samples repeated I/O callsite occurrences for scheduling;
every exact fault match and the first target check after each fault is retained.
Transaction-log keys identify the peer and logical log, not a distinct absolute
file path. The original preflight and excluded instrumentor setup diagnostics
are preserved in [setup-audit.tar.zst](independent/setup-audit.tar.zst). The
initial unverified mapping is in [mapping-result.json](mapping-result.json).
This bounded result does not prove the selected throw unreachable elsewhere.
